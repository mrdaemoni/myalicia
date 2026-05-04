#!/usr/bin/env python3
"""
Emergent theme detection — Phase 17.0.

The system mostly reacts. Phase 11 closed the inner reply loop, Phase
13.6 distilled meta-syntheses, Phase 12 tracked the the user-model arc.
But there was no module that LISTENED across the conversational stream
for patterns the user hasn't yet named.

This module fills that gap. A daily 04:00 scan reads:
  - Recent captures (writing/Responses + writing/Captures, last 14d)
  - Recent the user-model learnings (memory/user_learnings.jsonl)
  - Recent meta-syntheses (memory/meta_synthesis_log.jsonl)

…and asks Sonnet to identify themes that REPEAT across these sources
but haven't been formalized as synthesis titles or named learnings.

When a theme accumulates recurrence ≥3 AND hasn't been recently surfaced,
the midday rotation can pick it up (~15% gate) and Alicia raises it as a
noticing — a quiet observation rendered as TEXT + VOICE + DRAWING (the
ceremonial multi-channel moment the user named: "Alicia notices, and the
noticing fills the room").

The noticing isn't a question, isn't a check-in, isn't a capture nudge.
It's: "I've been noticing this. Want it to live somewhere?"

Public API:
    detect_emergent_themes(within_days=14) -> list[dict]
    record_emergent_theme(theme, evidence, recurrence)
    recent_emergent_themes(within_days=30, status=None) -> list[dict]
    pick_theme_to_surface() -> Optional[dict]
    compose_noticing_message(theme) -> Optional[str]
    record_theme_acknowledged(theme)
    build_noticing_proactive() -> Optional[dict]    # entry for midday rotation
    run_emergent_theme_scan() -> dict               # entry for 04:00 scheduler

Storage:
    ~/alicia/memory/emergent_themes.jsonl
    Schema: {ts, theme, evidence: [str], recurrence_count, status:
             'pending'|'surfaced'|'acknowledged', surfaced_ts, acked_ts}
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.emergent_themes")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = str(MEMORY_DIR)
EMERGENT_THEMES_PATH = os.path.join(MEMORY_DIR, "emergent_themes.jsonl")
SYNTHESIS_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"

# Tunables
MIN_RECURRENCE = 3                # need this many appearances before surfacing
SURFACE_COOLDOWN_DAYS = 14        # don't re-surface the same theme within this window
NOTICING_PROBABILITY = 0.15       # midday gate
SCAN_LOOKBACK_DAYS = 14
NOTICING_ARCHETYPE = "beatrice"   # witnessing voice
NOTICING_SCORE = 2.5              # high enough to fast-path drawing decider
NOTICING_SOURCE_KIND = "lived_surfacing"  # eligible for drawing amplification

# Phase 18.1 — Voice cache for noticings.
# Defensive: if the same noticing somehow fires twice (the surface
# cooldown in pick_theme_to_surface should prevent this, but a process
# restart between sends OR a future code path that re-renders the
# same noticing for the dashboard could trip it), avoid regenerating
# the TTS audio. The cache lives at NOTICING_VOICE_CACHE_DIR keyed
# by hash of (theme_name + voice_text + style). TTL = 24h: noticings
# are surfaced at most once per cooldown window so a 24h cache is
# generous and old entries get pruned next time the cache is touched.
NOTICING_VOICE_CACHE_DIR = os.path.join(MEMORY_DIR, "noticing_voice_cache")
NOTICING_VOICE_CACHE_TTL_HOURS = 24


# ── Sonnet detection prompt ───────────────────────────────────────────────


_DETECT_SYSTEM = (
    f"You are Alicia, listening across {USER_NAME}'s recent stream of captures, "
    "learnings, and distillations. Your job: identify 1-3 themes that "
    "REPEAT across multiple entries but haven't yet been given a name "
    f"as a synthesis title. These are observations {USER_NAME} is circling "
    "without quite landing on.\n\n"
    "Reply with EXACTLY one JSON line:\n"
    '{"themes": [{"theme": "<short noun phrase, ~3-8 words>", '
    '"evidence": ["<quote 1>", "<quote 2>", ...], '
    '"recurrence_count": <int>}]}\n\n'
    "RULES:\n"
    "- A theme must appear in at least 2 distinct entries with semantically "
    "related (not identical) language.\n"
    f"- The theme phrase should be NEW — something {USER_NAME} might not yet have "
    "phrased to himself in this exact form.\n"
    "- Bias toward 1-2 themes of high quality over 3 of mediocre quality. "
    "Empty list (themes: []) is valid when nothing is repeating yet.\n"
    "- evidence quotes should be VERBATIM excerpts (≤120 chars each)."
)


def _gather_stream(within_days: int = SCAN_LOOKBACK_DAYS) -> list[dict]:
    """Pull the recent the user-stream input for theme detection.

    Returns a list of {kind, ts, text} dicts spanning captures +
    learnings + meta-syntheses in the last `within_days` days.
    """
    out: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)

    # Captures
    try:
        from myalicia.skills.response_capture import get_recent_captures
        for c in (get_recent_captures(n=200) or []):
            try:
                ts = datetime.fromisoformat(c.get("captured_at", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except Exception:
                continue
            text = (c.get("body_excerpt") or "").strip()
            if not text:
                continue
            out.append({
                "kind": "capture",
                "ts": c.get("captured_at", ""),
                "text": text,
            })
    except Exception as e:
        log.debug(f"_gather_stream captures failed: {e}")

    # Learnings
    try:
        from myalicia.skills.user_model import get_learnings
        for L in (get_learnings(since_days=within_days) or []):
            claim = (L.get("claim") or "").strip()
            if claim:
                out.append({
                    "kind": "learning",
                    "ts": L.get("ts", ""),
                    "text": claim,
                })
    except Exception as e:
        log.debug(f"_gather_stream learnings failed: {e}")

    # Meta-syntheses
    try:
        from myalicia.skills.meta_synthesis import recent_meta_syntheses
        for m in (recent_meta_syntheses(within_days=within_days) or []):
            title = (m.get("child_title") or m.get("parent_title") or "").strip()
            if title:
                out.append({
                    "kind": "meta_synthesis",
                    "ts": m.get("ts", ""),
                    "text": title,
                })
    except Exception as e:
        log.debug(f"_gather_stream meta_syntheses failed: {e}")

    return out


def _existing_synthesis_titles_lower() -> set[str]:
    """Return lower-case set of all current synthesis titles in the vault.

    Used to filter out themes that already have a name."""
    out: set[str] = set()
    if not SYNTHESIS_DIR.is_dir():
        return out
    try:
        for f in SYNTHESIS_DIR.glob("*.md"):
            out.add(f.stem.lower())
    except Exception:
        pass
    return out


def detect_emergent_themes(within_days: int = SCAN_LOOKBACK_DAYS) -> list[dict]:
    """Sonnet pass over the recent stream → list of theme candidates.

    Returns [{theme, evidence: [str], recurrence_count}]. Filters out
    themes whose phrasing already matches an existing synthesis title.
    Empty list when nothing repeats or the call fails.
    """
    stream = _gather_stream(within_days=within_days)
    if len(stream) < 3:
        return []  # not enough material to find repetition

    # Build the user prompt — kind/ts header + text body for each entry
    parts = [
        f"# {USER_NAME}'s stream (last {within_days} days, {len(stream)} entries)\n"
    ]
    for i, e in enumerate(stream, 1):
        parts.append(
            f"\n[{i}] {e['kind']} · {e['ts'][:10]}\n{e['text'][:400]}"
        )
    parts.append("\n\n---\n\nReturn the JSON line.")
    user_prompt = "\n".join(parts)

    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=_DETECT_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return []
        raw = (resp.content[0].text or "").strip()
        m = re.search(r"\{[\s\S]*?\"themes\"[\s\S]*\}", raw)
        if not m:
            log.debug(f"detect_emergent_themes: no JSON: {raw[:120]}")
            return []
        try:
            parsed = json.loads(m.group(0))
        except Exception as je:
            log.debug(f"detect_emergent_themes: bad JSON ({je}): {raw[:120]}")
            return []
        candidates = parsed.get("themes") or []
        if not isinstance(candidates, list):
            return []
        existing = _existing_synthesis_titles_lower()
        out: list[dict] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            theme = (item.get("theme") or "").strip()
            evidence = item.get("evidence") or []
            try:
                rc = int(item.get("recurrence_count", 0))
            except Exception:
                rc = 0
            if not theme or rc < 2:
                continue
            # Filter out themes that already match an existing synthesis
            if theme.lower() in existing:
                log.debug(f"theme {theme!r} already a synthesis title; skipping")
                continue
            out.append({
                "theme": theme[:200],
                "evidence": [str(e)[:240] for e in evidence if e][:5],
                "recurrence_count": max(rc, len(evidence)),
            })
        return out
    except Exception as e:
        log.warning(f"detect_emergent_themes failed: {e}")
        return []


# ── Storage ────────────────────────────────────────────────────────────────


def record_emergent_theme(
    theme: str, evidence: list[str], recurrence: int,
    status: str = "pending",
) -> None:
    """Append a detected theme to the log."""
    if not theme:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "theme": theme[:200],
            "evidence": evidence[:5] if evidence else [],
            "recurrence_count": int(recurrence),
            "status": status,  # pending | surfaced | acknowledged
            "surfaced_ts": None,
            "acked_ts": None,
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(EMERGENT_THEMES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_emergent_theme failed: {e}")


def recent_emergent_themes(
    within_days: int = 30, status: Optional[str] = None,
) -> list[dict]:
    """Return theme entries newer than `within_days`, optionally filtered
    by status."""
    if not os.path.exists(EMERGENT_THEMES_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(EMERGENT_THEMES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                try:
                    ts = datetime.fromisoformat(e.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                if status and e.get("status") != status:
                    continue
                out.append(e)
    except Exception as e:
        log.debug(f"recent_emergent_themes failed: {e}")
    return out


def _consolidated_themes(
    conversation_id: Optional[str] = None,
) -> dict[str, dict]:
    """Walk the append-only log and consolidate by theme name.

    The log is append-only: each theme starts with a 'pending' record
    (with full evidence + recurrence_count), then any status changes
    are appended as separate update records (is_status_update=True).
    This helper merges them into a single dict per theme:

        {theme_name: {
            "theme": ..., "evidence": ..., "recurrence_count": ...,
            "status": <latest>, "surfaced_ts": <latest>,
            "acked_ts": <latest>, "ts": <oldest record's ts>,
        }, ...}

    'status' reflects the MOST RECENT update for that theme. Other
    fields come from the original full record (status updates don't
    repeat them)."""
    out: dict[str, dict] = {}
    if not os.path.exists(EMERGENT_THEMES_PATH):
        return out
    try:
        with open(EMERGENT_THEMES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                theme = (e.get("theme") or "").strip()
                if not theme:
                    continue
                # Phase 16.3 — conversation scoping. None = no filter
                # (whole-vault). Backwards-compat: entries without the
                # field are treated as 'default'.
                if conversation_id is not None:
                    entry_cid = (e.get("conversation_id") or "default")
                    if entry_cid != conversation_id:
                        continue
                if e.get("is_status_update"):
                    # Update an existing entry's latest-status fields
                    if theme in out:
                        out[theme]["status"] = e.get("status") or out[theme].get("status")
                        if e.get("surfaced_ts"):
                            out[theme]["surfaced_ts"] = e["surfaced_ts"]
                        if e.get("acked_ts"):
                            out[theme]["acked_ts"] = e["acked_ts"]
                else:
                    # Full record — first time we see this theme,
                    # OR a re-detection; keep most-recent full data.
                    existing = out.get(theme)
                    if existing is None:
                        out[theme] = dict(e)
                    else:
                        # If a later full record arrives, it's a fresh
                        # detection — bump recurrence + ts but keep any
                        # status updates that came in between.
                        out[theme]["recurrence_count"] = max(
                            existing.get("recurrence_count", 0),
                            e.get("recurrence_count", 0),
                        )
                        out[theme]["evidence"] = e.get("evidence") or existing.get("evidence", [])
                        out[theme]["ts"] = e.get("ts", existing.get("ts"))
    except Exception as e:
        log.debug(f"_consolidated_themes failed: {e}")
    return out


def pick_theme_to_surface() -> Optional[dict]:
    """Pick the next theme to surface as a noticing.

    Strategy:
      1. Consolidate the append-only log by theme (latest status wins).
      2. Require recurrence_count >= MIN_RECURRENCE.
      3. Filter out acknowledged themes.
      4. Filter out themes matching an existing synthesis title.
      5. Filter out themes surfaced within SURFACE_COOLDOWN_DAYS.
      6. Prefer highest recurrence_count.
    """
    consolidated = _consolidated_themes()
    if not consolidated:
        return None
    existing = _existing_synthesis_titles_lower()
    eligible: list[dict] = []
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(
        days=SURFACE_COOLDOWN_DAYS,
    )
    for theme_name, t in consolidated.items():
        if t.get("recurrence_count", 0) < MIN_RECURRENCE:
            continue
        if theme_name.lower() in existing:
            continue
        status = t.get("status", "pending")
        if status == "acknowledged":
            continue
        if status == "surfaced":
            try:
                surf_ts = datetime.fromisoformat(t.get("surfaced_ts") or "")
                if surf_ts.tzinfo is None:
                    surf_ts = surf_ts.replace(tzinfo=timezone.utc)
                if surf_ts >= cooldown_cutoff:
                    continue
            except Exception:
                pass
        eligible.append(t)
    if not eligible:
        return None
    eligible.sort(key=lambda t: (-t.get("recurrence_count", 0),
                                 t.get("ts", "")))
    return eligible[0]


def _update_theme_status(theme: str, status: str) -> None:
    """Mark a theme's status in the log by appending an update record.

    Append-only — easier than rewriting the file. recent_emergent_themes
    naturally returns the most recent record for any theme based on ts."""
    if not theme:
        return
    update = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "theme": theme,
        "status": status,
        "is_status_update": True,
    }
    if status == "surfaced":
        update["surfaced_ts"] = update["ts"]
    elif status == "acknowledged":
        update["acked_ts"] = update["ts"]
    try:
        from myalicia.skills.conversations import tag as _tag_conv
        _tag_conv(update)
    except Exception:
        pass
    try:
        with open(EMERGENT_THEMES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(update, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"_update_theme_status failed: {e}")


def record_theme_acknowledged(theme: str) -> None:
    """Mark a theme as acknowledged (the user replied to a noticing)."""
    _update_theme_status(theme, status="acknowledged")


# ── Composition ────────────────────────────────────────────────────────────


# Phase 17.1 — emotion-aware softening: when the user's recent emotional
# weather skews tender (sad-dominant in the last 24h), the noticing
# composer is given a softer brief and the surfacing gate is held back
# slightly. The intent is NOT to silence the noticing but to let
# Beatrice be even more careful about pacing: a noticing on a heavy day
# should land like a hand on the shoulder, not a tap on the calendar.
TENDER_HEAVY_FRACTION = 0.5      # ≥50% sad in last 24h → 'tender'
TENDER_RECENT_HOURS = 24
TENDER_MIN_ENTRIES = 2           # need at least N classifications to call it
TENDER_PROBABILITY_DAMP = 0.5    # halve surface probability on tender days


def _recent_emotion_weather() -> str:
    """Return a coarse state for noticing pacing: 'tender' | 'neutral'.

    Reads emotion_log.jsonl for the last TENDER_RECENT_HOURS hours. If
    'sad' (or 'ang') dominates ≥TENDER_HEAVY_FRACTION of recent
    classifications AND we have ≥TENDER_MIN_ENTRIES, returns 'tender'.
    Otherwise 'neutral'. Fault-tolerant — any error returns 'neutral'."""
    try:
        from myalicia.skills.emotion_model import load_recent_emotions
        days = max(1, TENDER_RECENT_HOURS / 24.0)
        entries = load_recent_emotions(days=days) or []
        if len(entries) < TENDER_MIN_ENTRIES:
            return "neutral"
        labels = [(e.get("emotion_label") or "").lower() for e in entries]
        if not labels:
            return "neutral"
        heavy = sum(1 for L in labels if L in ("sad", "ang"))
        if heavy / len(labels) >= TENDER_HEAVY_FRACTION:
            return "tender"
    except Exception as e:
        log.debug(f"_recent_emotion_weather failed: {e}")
    return "neutral"


_NOTICING_SYSTEM = (
    f"You are Alicia, raising a noticing with {USER_NAME}. You've been quietly "
    "tracking a theme that's appeared multiple times in his recent "
    "stream — captures, learnings, distillations — without him giving "
    "it a name. This isn't a question, isn't a check-in, isn't a "
    "request to capture. It's: 'I've been noticing this. Want it to "
    "live somewhere?'\n\n"
    "Write 2-4 short lines (40-80 words total). Open by NAMING the "
    "theme (lowercase, in italics if helpful, but keep it natural). "
    "One short line of evidence — what you've seen. Then one quiet "
    "invitation, not pressed. Beatrice's voice — witness, not analyst. "
    "End on the invitation, not a summary. No labels, no headers, no "
    "markdown beyond a single italic phrase if it lands."
)


_NOTICING_SYSTEM_TENDER = (
    f"You are Alicia, raising a noticing with {USER_NAME} — but his recent "
    "voice notes have been emotionally heavy (sadness or anger have "
    "dominated the last day). This noticing should land like a hand on "
    "the shoulder, not a tap on the calendar.\n\n"
    "Write 2-3 short lines (30-60 words total). Open by gently naming "
    "the theme (lowercase). One short line of evidence — softly. Then "
    "one quiet invitation that EXPLICITLY makes it okay to leave it for "
    "later: 'no rush', 'whenever it feels right', 'just leaving it "
    "here'. Beatrice's voice — witness, not analyst, and especially "
    "tender today. No labels, no headers, no urgency."
)


def compose_noticing_message(
    theme: dict, weather: Optional[str] = None,
) -> Optional[str]:
    """Render the noticing as Telegram-ready text via Haiku (cheap call).

    `weather` (Phase 17.1) — if 'tender', uses the softer system prompt
    that explicitly invites postponement and lowers urgency. Defaults to
    'neutral' if not provided."""
    if not theme:
        return None
    theme_name = theme.get("theme") or ""
    evidence = theme.get("evidence") or []
    if not theme_name:
        return None
    weather = weather or "neutral"
    system = _NOTICING_SYSTEM_TENDER if weather == "tender" else _NOTICING_SYSTEM
    user_prompt = (
        f"Theme: {theme_name}\n"
        f"Recurrence: {theme.get('recurrence_count', 0)}\n"
        f"Evidence quotes from his stream:\n"
        + "\n".join(f'- "{e}"' for e in evidence[:3])
        + f"\n\nWrite the noticing message Alicia sends {USER_NAME}."
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return None
        raw = (resp.content[0].text or "").strip()
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1].strip()
        return raw or None
    except Exception as e:
        log.warning(f"compose_noticing_message failed: {e}")
        return None


# ── Main entry points ─────────────────────────────────────────────────────


# Phase 18.0 — Sidecar context for the last noticing built. The proactive
# pipeline calls build_noticing_proactive() and only gets back a string
# (the message text) — there's no clean way for the midday handler to
# know whether the message it's about to send IS a noticing without
# string-sniffing. This sidecar lets the handler fetch the noticing's
# decision metadata (archetype/score/source_kind/weather/timestamp) and
# thread it into voice + drawing rendering so all three channels arrive
# as one ceremonial moment.
#
# The context is in-process state — accessed only by the same handler
# that build_noticing_proactive ran in. Stale across restarts (cleared
# on import); a fresh midday cycle will repopulate. is_recent() uses
# wall-clock timestamp to avoid threading a stale context onto a later
# midday by accident (defensive against bugs that might call
# build_midday_message twice).
_LAST_NOTICING_CONTEXT: Optional[dict] = None
_NOTICING_CONTEXT_FRESH_SEC = 60


def get_last_noticing_context() -> Optional[dict]:
    """Return the metadata for the most recent build_noticing_proactive()
    call IF it happened in the last _NOTICING_CONTEXT_FRESH_SEC seconds.

    Returns None when nothing recent (the midday handler should treat
    the message as a normal text send and let the smart deciders make
    the calls). Returns the dict otherwise — caller can pre-render
    voice in Beatrice tone and pass score+archetype+source_kind to the
    drawing decider for guaranteed multi-channel coherence."""
    global _LAST_NOTICING_CONTEXT
    if not _LAST_NOTICING_CONTEXT:
        return None
    try:
        ts = _LAST_NOTICING_CONTEXT.get("ts")
        if not ts:
            return None
        ctx_ts = datetime.fromisoformat(ts)
        if ctx_ts.tzinfo is None:
            ctx_ts = ctx_ts.replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - ctx_ts).total_seconds()
        if age_sec > _NOTICING_CONTEXT_FRESH_SEC:
            return None
    except Exception:
        return None
    return dict(_LAST_NOTICING_CONTEXT)


def _set_last_noticing_context(ctx: dict) -> None:
    """Populate the sidecar (called by build_noticing_proactive on success)."""
    global _LAST_NOTICING_CONTEXT
    _LAST_NOTICING_CONTEXT = dict(ctx)
    _LAST_NOTICING_CONTEXT["ts"] = datetime.now(timezone.utc).isoformat()


def _clear_last_noticing_context() -> None:
    """Test helper — drop the sidecar to ensure clean state per test."""
    global _LAST_NOTICING_CONTEXT
    _LAST_NOTICING_CONTEXT = None


def build_noticing_proactive() -> Optional[dict]:
    """Build a complete noticing message + the multi-channel context.

    Returns:
        {
          "message": <full Telegram-ready text with banner>,
          "theme": <theme name>,
          "archetype": "beatrice",
          "score": 2.5,
          "source_kind": "lived_surfacing",
          "weather": "tender" | "neutral",
        }
    or None if no eligible theme exists OR if a tender-day damping
    roll suppresses the surfacing.

    The score + archetype + source_kind values are chosen so the
    Phase 13.3 + 13.7 smart deciders will fast-path BOTH voice and
    drawing — this is a ceremonial moment by design.

    Phase 17.1 — when the recent emotional weather is 'tender'
    (sad/ang dominant in the last 24h):
      * with probability TENDER_PROBABILITY_DAMP we suppress the
        noticing entirely (returns None) — protecting the user from
        a barrage on heavy days
      * if it does fire, the composer is given the softer system
        prompt + the banner is gentler ('a small noticing' vs the
        all-caps 'noticing')
    """
    theme = pick_theme_to_surface()
    if not theme:
        log.debug("build_noticing_proactive: no eligible theme")
        return None
    weather = _recent_emotion_weather()
    # Phase 17.1 — tender-day suppression (probabilistic)
    if weather == "tender":
        import random as _random
        if _random.random() < TENDER_PROBABILITY_DAMP:
            log.info(
                f"noticing suppressed: weather=tender, theme={theme['theme'][:60]!r}"
            )
            return None
    body = compose_noticing_message(theme, weather=weather)
    if not body:
        return None
    # Mark the theme as surfaced now (before the send) so a duplicate
    # midday call later in the day doesn't pick it again.
    _update_theme_status(theme["theme"], status="surfaced")
    banner = (
        "👁 _a small noticing_" if weather == "tender" else "👁 _noticing_"
    )
    message = f"{banner}\n\n{body}"
    result = {
        "message": message,
        "voice_text": body,  # Phase 18.0 — voice render skips the markdown banner
        "theme": theme["theme"],
        "archetype": NOTICING_ARCHETYPE,
        "score": NOTICING_SCORE,
        "source_kind": NOTICING_SOURCE_KIND,
        "weather": weather,
    }
    # Phase 18.0 — sidecar context for the midday handler. After this
    # call returns, alicia.py's send_midday_message can fetch this via
    # get_last_noticing_context() and use the metadata to (a) pre-render
    # voice in Beatrice tone (or tender style on heavy days) and (b)
    # thread the noticing's archetype/score/source_kind into the drawing
    # decider so it fast-paths. Result: text + voice + drawing as one
    # ceremonial moment instead of three independent decisions.
    _set_last_noticing_context({
        "theme": theme["theme"],
        "archetype": NOTICING_ARCHETYPE,
        "score": NOTICING_SCORE,
        "source_kind": NOTICING_SOURCE_KIND,
        "weather": weather,
        "voice_text": body,
        "message_excerpt": (message or "")[:160],
    })
    return result


# ── Phase 18.1: voice cache for noticings ────────────────────────────────


def _voice_cache_key(theme: str, voice_text: str, style: str = "gentle") -> str:
    """Stable hash key for the (theme, voice_text, style) triple.

    Theme alone isn't enough — Phase 17.1's tender-day softening can
    produce different `voice_text` for the same theme, and Phase 17.4
    can swap style based on weather. The cache key incorporates all
    three so different renderings get different cached files.
    """
    import hashlib
    blob = f"{(theme or '').strip()}|{(voice_text or '').strip()}|{(style or '').strip()}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def get_cached_noticing_voice(
    theme: str, voice_text: str, style: str = "gentle",
) -> Optional[str]:
    """Return path to a cached voice clip for this noticing, or None.

    None means a fresh render is needed. The caller (alicia.py midday
    handler) renders + then calls cache_noticing_voice to store.
    Returns None on any error so the caller falls back to fresh-render.
    """
    try:
        os.makedirs(NOTICING_VOICE_CACHE_DIR, exist_ok=True)
        key = _voice_cache_key(theme, voice_text, style)
        # Voice clips are .ogg (Telegram-compatible)
        path = os.path.join(NOTICING_VOICE_CACHE_DIR, f"{key}.ogg")
        if not os.path.exists(path):
            return None
        # TTL check
        try:
            mtime = os.path.getmtime(path)
            age_hours = (
                datetime.now().timestamp() - mtime
            ) / 3600.0
            if age_hours > NOTICING_VOICE_CACHE_TTL_HOURS:
                # Stale — delete + report miss
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
        except Exception:
            return None
        return path
    except Exception as e:
        log.debug(f"get_cached_noticing_voice failed: {e}")
        return None


def cache_noticing_voice(
    theme: str, voice_text: str, source_path: str, style: str = "gentle",
) -> Optional[str]:
    """Copy `source_path` (a freshly rendered .ogg) into the cache.

    Returns the cache path on success, None on failure. The caller can
    keep using `source_path` regardless — caching is best-effort, not
    a contract.
    """
    if not source_path or not os.path.exists(source_path):
        return None
    try:
        os.makedirs(NOTICING_VOICE_CACHE_DIR, exist_ok=True)
        key = _voice_cache_key(theme, voice_text, style)
        cache_path = os.path.join(NOTICING_VOICE_CACHE_DIR, f"{key}.ogg")
        # Use shutil.copy so the original source is preserved (caller
        # may want to delete it explicitly per the existing pattern).
        import shutil
        shutil.copy(source_path, cache_path)
        return cache_path
    except Exception as e:
        log.debug(f"cache_noticing_voice failed: {e}")
        return None


def prune_noticing_voice_cache(max_age_hours: Optional[float] = None) -> int:
    """Drop cache entries older than max_age_hours (default: TTL).
    Returns count pruned. Safe to call from a scheduler."""
    if not os.path.isdir(NOTICING_VOICE_CACHE_DIR):
        return 0
    cutoff = (max_age_hours or NOTICING_VOICE_CACHE_TTL_HOURS) * 3600.0
    now_ts = datetime.now().timestamp()
    pruned = 0
    try:
        for fname in os.listdir(NOTICING_VOICE_CACHE_DIR):
            path = os.path.join(NOTICING_VOICE_CACHE_DIR, fname)
            try:
                if (now_ts - os.path.getmtime(path)) > cutoff:
                    os.remove(path)
                    pruned += 1
            except Exception:
                continue
    except Exception:
        pass
    return pruned


def _count_theme_acknowledgments() -> dict[str, int]:
    """Phase 24.4 — Walk the append-only log and count acknowledgment
    EVENTS per theme. Each `is_status_update` entry with `status =
    acknowledged` counts as one ack — multiple acks = a theme the user
    keeps engaging with but the system never formalizes.

    Returns dict {theme_name (lowercased): count}."""
    counts: dict[str, int] = {}
    if not os.path.exists(EMERGENT_THEMES_PATH):
        return counts
    try:
        with open(EMERGENT_THEMES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if not e.get("is_status_update"):
                    continue
                if (e.get("status") or "").lower() != "acknowledged":
                    continue
                theme = (e.get("theme") or "").strip().lower()
                if not theme:
                    continue
                counts[theme] = counts.get(theme, 0) + 1
    except Exception as e:
        log.debug(f"_count_theme_acknowledgments failed: {e}")
    return counts


def detect_theme_drift(
    *,
    min_acks: int = 3,
    conversation_id: Optional[str] = None,
) -> list[dict]:
    """Phase 24.4 — Themes the user keeps acknowledging without ever
    being formalized as synthesis titles. The signal: he engages with
    the noticing AND the engagement repeats, but the underlying idea
    isn't graduating into the vault as a named synthesis.

    Returns a list of drift entries:
        [{
          "theme": str,
          "ack_count": int,
          "first_seen_ts": str,
          "evidence": list[str],
        }, ...]

    Default `min_acks=3` — engagement that repeats at least three
    times across separate ceremonial moments. The system recognizes
    a candidate for synthesis promotion."""
    consolidated = _consolidated_themes(conversation_id=conversation_id)
    if not consolidated:
        return []
    ack_counts = _count_theme_acknowledgments()
    if not ack_counts:
        return []
    existing_synthesis = _existing_synthesis_titles_lower()
    out: list[dict] = []
    for theme_name, t in consolidated.items():
        norm = theme_name.lower().strip()
        ack_n = ack_counts.get(norm, 0)
        if ack_n < min_acks:
            continue
        # Loose match: if any synthesis title contains the theme phrase
        # or vice versa, the theme has graduated. Skip.
        if any(
            (norm in existing or existing in norm)
            for existing in existing_synthesis
            if existing
        ):
            continue
        out.append({
            "theme": theme_name,
            "ack_count": ack_n,
            "first_seen_ts": t.get("ts"),
            "evidence": (t.get("evidence") or [])[:3],
        })
    out.sort(key=lambda d: -d.get("ack_count", 0))
    return out


def get_themes_summary(
    conversation_id: Optional[str] = None,
) -> dict:
    """Phase 17.2 + 17.3 — Surface-agnostic summary of tracked themes.

    Phase 16.3 — `conversation_id` scopes which themes are returned.
    None = all conversations (whole-vault). Pass a specific id to filter.
    Phase 24.4 — Adds `drift` array: themes acknowledged ≥3 times that
    haven't been formalized as syntheses. Engagement signal that the
    idea wants a real name.

    Returns:
        {
          "total": int,
          "by_status": {"pending": int, "surfaced": int, "acknowledged": int},
          "themes": [<top N entries with evidence>],
          "next_to_surface": <theme dict if eligible, else None>,
          "drift": [<themes acknowledged ≥3× without a synthesis>],
        }
    """
    consolidated = _consolidated_themes(conversation_id=conversation_id)
    by_status: dict[str, int] = {"pending": 0, "surfaced": 0, "acknowledged": 0}
    themes: list[dict] = []
    for theme_name, t in consolidated.items():
        status = t.get("status", "pending")
        by_status[status] = by_status.get(status, 0) + 1
        themes.append({
            "theme": theme_name,
            "evidence": t.get("evidence") or [],
            "recurrence_count": t.get("recurrence_count", 0),
            "status": status,
            "ts": t.get("ts"),
            "surfaced_ts": t.get("surfaced_ts"),
            "acked_ts": t.get("acked_ts"),
        })
    # Sort: surfaced/acked recent first, then pending by recurrence
    def _sort_key(t: dict):
        s = t.get("status", "pending")
        # acked first (most recent), surfaced next, pending last
        order = {"acknowledged": 0, "surfaced": 1, "pending": 2}.get(s, 3)
        return (order, -t.get("recurrence_count", 0))
    themes.sort(key=_sort_key)
    # Phase 24.4 — drift detection
    try:
        drift = detect_theme_drift(conversation_id=conversation_id)
    except Exception as de:
        log.debug(f"drift detection skip: {de}")
        drift = []
    return {
        "total": len(themes),
        "by_status": by_status,
        "themes": themes,
        "next_to_surface": pick_theme_to_surface(),
        "drift": drift,
    }


def render_noticings_for_telegram(
    conversation_id: Optional[str] = None,
) -> str:
    """Phase 17.2 — Telegram-flavored /noticings rendering.

    Phase 16.3 — `conversation_id` scopes which themes are shown.
    None = all conversations (whole-vault). Pass a specific id to filter.
    A scope banner appears in the header so the view is unambiguous."""
    summary = get_themes_summary(conversation_id=conversation_id)
    if summary["total"] == 0:
        scope_blurb = ""
        if conversation_id is not None:
            try:
                from myalicia.skills.conversations import get_conversation_meta
                meta = get_conversation_meta(conversation_id) or {}
                label = meta.get("label", conversation_id)
                scope_blurb = f"\n_(scope: *{label}* — try `/noticings all` for whole-vault)_"
            except Exception:
                scope_blurb = f"\n_(scope: `{conversation_id}`)_"
        return (
            "👁 *Noticings*\n\n"
            "_No themes tracked yet. The 04:00 nightly scan will populate "
            "this once your captures + learnings show repetition._"
            + scope_blurb
        )
    # Phase 16.3 — scope banner
    scope_line = ""
    if conversation_id is not None:
        try:
            from myalicia.skills.conversations import get_conversation_meta
            meta = get_conversation_meta(conversation_id) or {}
            label = meta.get("label", conversation_id)
            scope_line = f"_scoped to:_ *{label}* (`{conversation_id}`)\n\n"
        except Exception:
            scope_line = f"_scoped to:_ `{conversation_id}`\n\n"
    lines = [
        "👁 *Noticings — what Alicia has been tracking*",
        "",
        scope_line.rstrip("\n") if scope_line else None,
        f"*{summary['total']} theme(s)* · "
        f"{summary['by_status']['pending']} pending · "
        f"{summary['by_status']['surfaced']} surfaced · "
        f"{summary['by_status']['acknowledged']} acked",
        "",
    ]
    lines = [l for l in lines if l is not None]
    nxt = summary.get("next_to_surface")
    if nxt:
        lines.append(
            f"*Next to surface:* _{nxt['theme'][:80]}_ "
            f"(recurrence {nxt['recurrence_count']})"
        )
        lines.append("")
    lines.append("*Recent themes:*")
    for t in summary["themes"][:8]:
        status_emoji = {
            "pending": "⏳", "surfaced": "📬", "acknowledged": "✅",
        }.get(t["status"], "•")
        lines.append(
            f"{status_emoji} _{t['theme'][:80]}_ ({t['recurrence_count']}×)"
        )
        if t.get("evidence"):
            lines.append(f"  └ \"{t['evidence'][0][:100]}\"")
    # Phase 24.4 — drift section. Themes the user keeps acknowledging
    # without ever being formalized. The 🌀 marker says "this idea
    # wants a real name."
    drift = summary.get("drift") or []
    if drift:
        lines.append("")
        lines.append(
            "*🌀 Drifting themes* "
            "(acknowledged ≥3× without becoming a synthesis):"
        )
        for d in drift[:5]:
            lines.append(
                f"  • _{d['theme'][:80]}_ "
                f"(acked {d['ack_count']}×)"
            )
        lines.append(
            "  _These ideas want a name. Run `/synthesise` against "
            "the theme phrase to graduate it into the vault._"
        )
    return "\n".join(lines)


def run_emergent_theme_scan() -> dict:
    """Scheduled nightly (04:00): detect themes + write to log.

    Returns a result dict with counts so the scheduler log shows what
    happened. Cheap — just one Sonnet call over the recent stream.
    """
    themes = detect_emergent_themes(within_days=SCAN_LOOKBACK_DAYS)
    n_recorded = 0
    for t in themes:
        record_emergent_theme(
            theme=t["theme"],
            evidence=t.get("evidence", []),
            recurrence=t.get("recurrence_count", 0),
        )
        n_recorded += 1
    log.info(
        f"emergent_theme_scan: detected={len(themes)} recorded={n_recorded}"
    )
    return {
        "detected": len(themes),
        "recorded": n_recorded,
        "themes": [t["theme"] for t in themes],
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(run_emergent_theme_scan(), indent=2))
