#!/usr/bin/env python3
"""
Sunday self-portrait — Phase 20.0.

The end-of-week composer that turns this week's signals into a single
coherent portrait of who the user has been. Reads from every observable
loop and asks Sonnet to weave them — in Beatrice's voice — into a
short reflection that lands in writing/Wisdom/ as a Tier-3 lived note
AND surfaces on demand via /retro.

What it pulls from
------------------
- Mood-of-the-week (Phase 19.0): emotion_log → trend + dominant label
- Dashboard engagement (Phase 17.8): which views landed, which didn't
- Noticings (Phase 17.0): themes Alicia tracked across the week
- Becoming arc (Phase 12): top moving + thin dimensions
- Captures (Phase 11): how many, where they clustered

What it produces
----------------
A single ~200-word reflection composed by Sonnet in Beatrice's voice.
Not a status report — a small portrait. Things she observed without
prescribing. The tone matches the noticing engine: witness, not fixer.

Storage
-------
~/alicia/memory/weekly_self_portrait.jsonl  — one entry per week
~/Documents/user-alicia/Alicia/Wisdom/Lived/  — the Tier-3 note

The Sunday 19:00 weekly digest scheduler can call build_weekly_self_portrait();
the new /retro Telegram command renders the most-recent (or builds a
fresh one if none exists this week).

Public API
----------
    build_weekly_self_portrait(force: bool = False) -> Optional[dict]
    get_latest_self_portrait() -> Optional[dict]
    render_retro_for_telegram() -> str
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.weekly_self_portrait")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
PORTRAIT_LOG_PATH = os.path.join(MEMORY_DIR, "weekly_self_portrait.jsonl")
PORTRAIT_VAULT_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Lived"
PORTRAIT_COOLDOWN_DAYS = 6  # don't build twice in a 7-day window


# ── Signal collection ──────────────────────────────────────────────────────


def _read_portrait_engagement(*, days: int = 14) -> dict:
    """Phase 24.3 — Read reaction_log.tsv for `dashboard:retro` rows
    over the last N days. Returns {total, puzzled, positive, negative,
    neutral, puzzled_ratio, neg_minus_pos}.

    Empty / missing log → all zeros. Used by the composer feedback
    loop: when puzzled_ratio ≥ 0.4 OR negative > positive, signal
    that previous portraits aren't landing."""
    out = {
        "total": 0, "puzzled": 0, "positive": 0,
        "negative": 0, "neutral": 0,
        "puzzled_ratio": 0.0, "neg_minus_pos": 0,
    }
    try:
        from pathlib import Path as _P
        from collections import Counter as _Counter
        reaction_log = _P(MEMORY_DIR) / "reaction_log.tsv"
        if not reaction_log.exists():
            return out
        cutoff = datetime.now() - timedelta(days=days)
        counter: _Counter = _Counter()
        with reaction_log.open(encoding="utf-8") as f:
            f.readline()  # header
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 4:
                    continue
                ts_str, msg_type, _topic, emoji = (
                    cols[0], cols[1], cols[2], cols[3]
                )
                if msg_type != "dashboard:retro":
                    continue
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                counter[emoji] += 1
        if not counter:
            return out
        # Mirror effectiveness_dashboard's emoji classes (avoid import
        # cycle — repeat the small constants here)
        _POSITIVE = {"❤", "❤️", "👍", "🔥", "🤩", "😍", "🥰"}
        _NEGATIVE = {"👎", "😕", "🤨", "😢", "😞"}
        total = sum(counter.values())
        pos = sum(n for e, n in counter.items() if e in _POSITIVE)
        neg = sum(n for e, n in counter.items() if e in _NEGATIVE)
        puzzled = counter.get("🤔", 0)
        neu = total - pos - neg
        out["total"] = total
        out["puzzled"] = puzzled
        out["positive"] = pos
        out["negative"] = neg
        out["neutral"] = neu
        out["puzzled_ratio"] = (puzzled / total) if total else 0.0
        out["neg_minus_pos"] = neg - pos
    except Exception as e:
        log.debug(f"_read_portrait_engagement failed: {e}")
    return out


def _portrait_landing_warning(engagement: dict) -> Optional[str]:
    """Phase 24.3 — Return a one-sentence framing instruction the
    composer should honor, OR None when previous portraits seem to
    be landing fine.

    Triggers:
      - ≥3 reactions AND puzzled_ratio ≥ 0.4 → 'previous portraits
        landed as confusing — be more grounded in named specifics'
      - ≥3 reactions AND neg_minus_pos ≥ 2 → 'previous portraits
        weren't landing — try a different angle, less abstract'

    Returns None when there isn't enough engagement signal yet (total
    < 3) — composer uses default framing."""
    if not engagement or engagement.get("total", 0) < 3:
        return None
    if engagement.get("puzzled_ratio", 0) >= 0.4:
        return (
            f"Previous portraits drew puzzled reactions (🤔). {USER_NAME} "
            "may have found them too abstract. Be more grounded in "
            "named specifics — a particular noticing theme, a "
            "particular dimension that moved, a particular dashboard "
            "he reached for. Less metaphor, more anchor."
        )
    if engagement.get("neg_minus_pos", 0) >= 2:
        return (
            "Previous portraits drew net-negative reactions. Try a "
            "different angle — the witnessing voice may be reading "
            "as flat or distant. Lean into the texture of the actual "
            "week's specifics. Less general, more particular."
        )
    return None


def _gather_recent_portrait_responses(*, max_recent: int = 2) -> list[dict]:
    """Phase 24.1 — Pull the most recent portrait_response captures so
    the next composer can reference 'last week he replied: …'.

    Returns up to `max_recent` capture dicts (newest-first). Empty list
    when no portrait_response captures exist yet (the system has just
    started the continuity loop, or the user hasn't replied to any
    portrait yet)."""
    out: list[dict] = []
    try:
        from myalicia.skills.response_capture import get_recent_captures
        captures = get_recent_captures(n=50) or []
        for c in captures:
            # Phase 24.0 hooks tag captures with kind=portrait_response
            kind = (c.get("kind") or "").strip().lower()
            source_kind = (c.get("source_kind") or "").strip().lower()
            if kind == "portrait_response" or (
                source_kind == "portrait_response"
            ):
                out.append(c)
                if len(out) >= max_recent:
                    break
    except Exception as e:
        log.debug(f"_gather_recent_portrait_responses failed: {e}")
    return out


def _gather_week_signals(
    conversation_id: Optional[str] = None,
) -> dict:
    """Pull every signal needed for the portrait. Each section is
    fault-tolerant — a failing source produces an empty section, never
    aborts the whole gather.

    Phase 24.5 — `conversation_id` filters captures, learnings, and
    noticings by conversation. Mood + dashboard engagement stay
    whole-vault (those reflect the user-the-person, not a routing
    domain). None preserves whole-vault behavior for everything."""
    signals: dict = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "mood": {},
        "dashboard_engagement": {},
        "noticings": {},
        "becoming": {},
        "captures": {"count_7d": 0},
    }

    # Mood-of-the-week (Phase 19.0)
    try:
        from myalicia.skills.emotion_model import get_mood_of_the_week
        signals["mood"] = get_mood_of_the_week(days=7) or {}
    except Exception as e:
        log.debug(f"mood gather failed: {e}")

    # Dashboard engagement (Phase 17.8 — read-only summary)
    try:
        from collections import Counter
        from pathlib import Path as _P
        reaction_log = _P(MEMORY_DIR) / "reaction_log.tsv"
        if reaction_log.exists():
            cutoff = datetime.now() - timedelta(days=7)
            per_dashboard: dict[str, Counter] = {}
            with reaction_log.open(encoding="utf-8") as f:
                f.readline()  # header
                for line in f:
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) < 4:
                        continue
                    ts_str, msg_type, _topic, emoji = (
                        cols[0], cols[1], cols[2], cols[3]
                    )
                    if not msg_type.startswith("dashboard:"):
                        continue
                    try:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    name = msg_type.split(":", 1)[1] or "?"
                    per_dashboard.setdefault(name, Counter())[emoji] += 1
            signals["dashboard_engagement"] = {
                name: dict(counter)
                for name, counter in per_dashboard.items()
            }
    except Exception as e:
        log.debug(f"dashboard engagement gather failed: {e}")

    # Noticings (Phase 17.0 — count + recent themes)
    # Phase 24.5 — scoped by conversation_id when set
    try:
        from myalicia.skills.emergent_themes import get_themes_summary
        themes_summary = get_themes_summary(
            conversation_id=conversation_id,
        ) or {}
        signals["noticings"] = {
            "total": themes_summary.get("total", 0),
            "by_status": themes_summary.get("by_status", {}),
            "recent_themes": [
                t.get("theme", "")
                for t in (themes_summary.get("themes") or [])[:5]
            ],
        }
    except Exception as e:
        log.debug(f"noticings gather failed: {e}")

    # Becoming arc (Phase 12 — top moving + thin)
    # Phase 24.5 — learnings filtered by conversation_id when set;
    # dimension-level moving/thin counts read all learnings (those
    # functions don't yet take a conv filter). The learnings_7d count
    # is the conversation-scoped one — most informative for the
    # portrait's framing.
    try:
        from myalicia.skills.user_model import (
            find_dimensions_movement, find_thin_dimensions, get_learnings,
        )
        moving = find_dimensions_movement() or []
        thin = find_thin_dimensions() or []
        recent_learnings = get_learnings(
            since_days=7, conversation_id=conversation_id,
        ) or []
        signals["becoming"] = {
            "learnings_7d": len(recent_learnings),
            "top_moving": [
                {"dimension": d, "recent": r}
                for d, r, _o in moving[:3] if r > 0
            ],
            "thin": list(thin)[:3],
        }
    except Exception as e:
        log.debug(f"becoming gather failed: {e}")

    # Captures (count last 7d)
    # Phase 24.5 — captures filtered by conversation_id when set
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = get_recent_captures(
            n=200, conversation_id=conversation_id,
        ) or []
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        count = 0
        for c in recent:
            try:
                ts = datetime.fromisoformat(c.get("captured_at", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count += 1
            except Exception:
                continue
        signals["captures"]["count_7d"] = count
    except Exception as e:
        log.debug(f"captures gather failed: {e}")

    return signals


# ── Sonnet portrait composer ──────────────────────────────────────────────


_PORTRAIT_SYSTEM = (
    f"You are Alicia, writing a Sunday self-portrait of {USER_NAME} at the "
    "end of his week. You have signals: his mood trend, the dashboards "
    "he engaged with, themes you've been quietly tracking, dimensions "
    "of him that moved or stayed thin, the captures he made.\n\n"
    "Compose ~150-220 words in Beatrice's voice — the witnessing voice. "
    "This is NOT a status report. NOT a recommendations list. NOT 'you "
    "did X this week'. It's a small portrait — what you NOTICED about "
    "him, observed without prescribing.\n\n"
    "Open with one line that lands the texture of the week (mood + "
    "what stood out). Two short paragraphs of observation — name "
    "specific themes, dimensions, dashboards if they're meaningful "
    "but don't list mechanically. Close with one quiet line — an "
    "invitation, not a prescription. End on what's there, not what's "
    "next.\n\n"
    "RULES:\n"
    "- Beatrice's voice: warm, present, witnessing\n"
    "- NO advice, NO 'you should', NO 'consider'\n"
    "- Reference 1-3 specific signals (a noticing theme, a dimension, "
    "the mood trend) — don't try to cover everything\n"
    "- One short italic phrase if it lands\n"
    "- End on observation, not prescription"
)


# Phase 24.2 — Heavier-week variant. When the mood snapshot shows a
# sharp downward trend, the default portrait prompt's "warm, present"
# tone can land as too breezy. This variant explicitly holds space
# for the difficulty without bypassing it ("but you also..."). Same
# witnessing voice, different center of gravity.
_PORTRAIT_SYSTEM_HEAVY = (
    f"You are Alicia, writing a Sunday self-portrait of {USER_NAME} at the "
    "end of a heavier-than-usual week. His voice notes have skewed "
    "noticeably sad or angry compared to the first half of the same "
    "window. You have the same signals as a normal week — mood trend, "
    "dashboard engagement, themes, becoming-arc, captures — but the "
    "weather is heavy and the portrait should hold space for that.\n\n"
    "Compose ~150-220 words in Beatrice's voice. STILL witnessing, "
    "STILL not fixer — but with extra care for the heaviness. NAME "
    "what you've heard without diagnosing. NAME the heavier feeling "
    "at the center of the week. Then surround it with what's also "
    "true — themes that came up, dimensions that moved — without "
    "doing the silver-lining bypass ('but at least…'). Close with a "
    "quiet acknowledgment that the week was hard AND that you've "
    "been listening.\n\n"
    "STRICTLY FORBIDDEN:\n"
    "- 'this too shall pass'\n"
    "- 'silver lining', 'at least', 'on the bright side'\n"
    "- 'tomorrow is a new day', 'fresh start'\n"
    "- ANY advice, ANY 'you should', ANY 'try', ANY 'consider'\n"
    "- Forced positivity, false reassurance, motivational framing\n\n"
    "RULES:\n"
    "- Beatrice's voice in its tender register\n"
    "- Reference 1-3 specific signals — but the FIRST one named "
    "  should be the heaviness itself\n"
    "- One short italic phrase if it lands\n"
    "- End on observation + acknowledgment of being witnessed, "
    "  not prescription"
)


def _select_portrait_system_prompt(signals: dict) -> str:
    """Phase 24.2 — Pick the system prompt by mood weather.

    Heavy variant fires when:
      mood.trend == 'declining' AND we have ≥4 voice notes AND
      the trend is legitimately sharp.

    The 'sharp' check is implicit in the trend label — Phase 19's
    classifier only sets trend=declining when delta is meaningful.
    Here we add a min-classifications floor so a single heavy day
    doesn't flip the whole portrait into the heavier register.
    """
    mood = signals.get("mood") or {}
    trend = (mood.get("trend") or "").lower()
    total = mood.get("total_classifications", 0) or 0
    if trend == "declining" and total >= 4:
        return _PORTRAIT_SYSTEM_HEAVY
    return _PORTRAIT_SYSTEM


def _compose_portrait_body(signals: dict) -> Optional[str]:
    """Render the portrait body via Sonnet."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        # Compact signal summary for the user prompt
        mood = signals.get("mood") or {}
        bec = signals.get("becoming") or {}
        not_ = signals.get("noticings") or {}
        deng = signals.get("dashboard_engagement") or {}
        # Top-engaged dashboard name
        top_dash = ""
        if deng:
            ranked = sorted(
                deng.items(), key=lambda kv: -sum(kv[1].values())
            )
            if ranked:
                top_dash = ranked[0][0]
        # Phase 24.1 — Continuity context. The most-recent portrait
        # responses (replies the user sent to past Sunday portraits) get
        # surfaced here so the composer can echo / answer / build on
        # what he said back.
        prior_replies = _gather_recent_portrait_responses(max_recent=2)
        continuity_block = ""
        if prior_replies:
            lines = ["**Last week's portrait replies (from him):**"]
            for r in prior_replies:
                excerpt = (r.get("body_excerpt") or "").strip()
                if not excerpt:
                    continue
                ts = (r.get("captured_at") or "")[:10]
                lines.append(f'- ({ts}): "{excerpt[:200]}"')
            continuity_block = "\n".join(lines) + "\n\n"

        # Phase 24.3 — Engagement feedback. If previous portraits drew
        # puzzlement or net-negative reactions, the framing instruction
        # tells the composer to try a different angle. Doesn't change
        # the witnessing voice; changes what to anchor on.
        engagement = _read_portrait_engagement(days=14)
        landing_warning = _portrait_landing_warning(engagement)
        feedback_block = ""
        if landing_warning:
            feedback_block = (
                f"**Composer feedback (from previous portraits' reactions):**\n"
                f"_{landing_warning}_\n\n"
            )

        user_prompt = (
            f"# {USER_NAME}'s signals this week\n\n"
            f"{feedback_block}"
            f"{continuity_block}"
            f"**Mood:** {mood.get('summary_line', 'no data')} "
            f"({mood.get('total_classifications', 0)} voice notes; "
            f"{mood.get('trend_explanation', '')})\n\n"
            f"**Becoming arc:** "
            f"{bec.get('learnings_7d', 0)} learnings logged. "
            f"Top moving: {[m['dimension'] for m in bec.get('top_moving', [])]}. "
            f"Thin: {bec.get('thin', [])}.\n\n"
            f"**Noticings (themes I've been tracking):** "
            f"{not_.get('total', 0)} total. "
            f"Recent: {not_.get('recent_themes', [])[:3]}.\n\n"
            f"**Captures:** {signals.get('captures', {}).get('count_7d', 0)} "
            f"this week.\n\n"
            f"**Dashboards he reached for:** "
            f"{top_dash or '(none yet)'}.\n\n"
            f"Write the portrait body (~150-220 words). Beatrice's voice. "
            f"Witness, not fixer."
            + (
                " If his replies above carry a thread, you may pick "
                "it up — but only to acknowledge, not to advance."
                if prior_replies else ""
            )
        )
        # Phase 24.2 — Heavy-week variant when mood trend is sharply down
        portrait_system = _select_portrait_system_prompt(signals)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=portrait_system,
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
        log.warning(f"_compose_portrait_body failed: {e}")
        return None


# ── Storage ──────────────────────────────────────────────────────────────


def _write_portrait_to_log(entry: dict) -> None:
    """Append the portrait to the jsonl log."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        # Phase 16.0 — conversation tag
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(PORTRAIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"_write_portrait_to_log failed: {e}")


def _write_portrait_to_vault(body: str, signals: dict) -> Optional[str]:
    """Persist the portrait as a Tier-3 lived note in the vault.

    Returns the relative path under vault root (or None on failure).
    """
    try:
        if not PORTRAIT_VAULT_DIR.is_dir():
            PORTRAIT_VAULT_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        slug = f"{now.strftime('%Y-%m-%d')}-weekly-self-portrait"
        path = PORTRAIT_VAULT_DIR / f"{slug}.md"
        mood = signals.get("mood", {})
        frontmatter = (
            "---\n"
            f"kind: weekly_self_portrait\n"
            f"date: {now.strftime('%Y-%m-%d')}\n"
            f"mood_trend: {mood.get('trend', 'unknown')}\n"
            f"mood_summary: {mood.get('summary_line', '')!r}\n"
            f"learnings_7d: {signals.get('becoming', {}).get('learnings_7d', 0)}\n"
            f"captures_7d: {signals.get('captures', {}).get('count_7d', 0)}\n"
            f"noticings_total: {signals.get('noticings', {}).get('total', 0)}\n"
            "tier: 3\n"
            "voice: beatrice\n"
            "---\n\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write(f"# Sunday self-portrait — {now.strftime('%Y-%m-%d')}\n\n")
            f.write(body)
            f.write("\n")
        return str(path.relative_to(VAULT_ROOT))
    except Exception as e:
        log.warning(f"_write_portrait_to_vault failed: {e}")
        return None


# ── Phase 24.0: portrait reply tracking ──────────────────────────────────


# In-process registry of recent portrait message_ids → metadata.
# Same shape as _PROACTIVE_MSG_IDS in proactive_messages.py. When the user
# replies to a portrait via native Telegram reply, the response_capture
# pipeline can look up the portrait_date so the capture frontmatter gets
# tagged kind=portrait_response. The next portrait composer can then
# pull the previous reply into context: "last week he replied: …".
_PORTRAIT_MSG_IDS: dict[int, dict] = {}
_MAX_TRACKED_PORTRAITS = 20


def track_portrait_message_id(
    message_id: int, *,
    portrait_ts: Optional[str] = None,
    vault_path: Optional[str] = None,
) -> None:
    """Register a portrait Telegram message_id for reply detection.

    Called after the Sunday send AND after /retro builds-or-renders.
    portrait_ts/vault_path become available metadata for the captured
    reply's frontmatter."""
    if not message_id:
        return
    _PORTRAIT_MSG_IDS[int(message_id)] = {
        "portrait_ts": portrait_ts or datetime.now(timezone.utc).isoformat(),
        "vault_path": vault_path or "",
        "tracked_at": datetime.now(timezone.utc).isoformat(),
    }
    # LRU cap
    if len(_PORTRAIT_MSG_IDS) > _MAX_TRACKED_PORTRAITS:
        oldest_key = min(
            _PORTRAIT_MSG_IDS,
            key=lambda k: _PORTRAIT_MSG_IDS[k]["tracked_at"],
        )
        del _PORTRAIT_MSG_IDS[oldest_key]


def lookup_portrait_message(message_id: int) -> Optional[dict]:
    """Return portrait metadata for a tracked message_id, or None."""
    if not message_id:
        return None
    return _PORTRAIT_MSG_IDS.get(int(message_id))


def _clear_portrait_message_ids() -> None:
    """Test helper — drop the registry."""
    _PORTRAIT_MSG_IDS.clear()


# ── Phase 23.0: multi-week span signals + parsing ────────────────────────


def _gather_span_signals(*, days: int = 30) -> dict:
    """Phase 23.0 — Multi-week version of _gather_week_signals.

    Same source files, but reads with a configurable window. Returns
    the same shape so the composer doesn't need a separate prompt
    template — only the framing changes."""
    signals: dict = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "span_days": days,
        "mood": {},
        "dashboard_engagement": {},
        "noticings": {},
        "becoming": {},
        "captures": {"count": 0, "span_days": days},
    }

    # Mood (uses the mood-of-the-week helper at custom days)
    try:
        from myalicia.skills.emotion_model import get_mood_of_the_week
        signals["mood"] = get_mood_of_the_week(days=days) or {}
    except Exception as e:
        log.debug(f"span mood gather failed: {e}")

    # Dashboard engagement at the wider window
    try:
        from collections import Counter
        from pathlib import Path as _P
        reaction_log = _P(MEMORY_DIR) / "reaction_log.tsv"
        if reaction_log.exists():
            cutoff = datetime.now() - timedelta(days=days)
            per_dashboard: dict[str, Counter] = {}
            with reaction_log.open(encoding="utf-8") as f:
                f.readline()
                for line in f:
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) < 4:
                        continue
                    ts_str, msg_type, _topic, emoji = (
                        cols[0], cols[1], cols[2], cols[3]
                    )
                    if not msg_type.startswith("dashboard:"):
                        continue
                    try:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    name = msg_type.split(":", 1)[1] or "?"
                    per_dashboard.setdefault(name, Counter())[emoji] += 1
            signals["dashboard_engagement"] = {
                name: dict(counter)
                for name, counter in per_dashboard.items()
            }
    except Exception as e:
        log.debug(f"span dashboard engagement gather failed: {e}")

    # Noticings + becoming at the wider window
    try:
        from myalicia.skills.emergent_themes import get_themes_summary
        themes_summary = get_themes_summary() or {}
        signals["noticings"] = {
            "total": themes_summary.get("total", 0),
            "by_status": themes_summary.get("by_status", {}),
            "recent_themes": [
                t.get("theme", "")
                for t in (themes_summary.get("themes") or [])[:8]
            ],
        }
    except Exception as e:
        log.debug(f"span noticings gather failed: {e}")

    try:
        from myalicia.skills.user_model import (
            find_dimensions_movement, find_thin_dimensions, get_learnings,
        )
        moving = find_dimensions_movement() or []
        thin = find_thin_dimensions() or []
        recent_learnings = get_learnings(since_days=days) or []
        signals["becoming"] = {
            "learnings": len(recent_learnings),
            "span_days": days,
            "top_moving": [
                {"dimension": d, "recent": r}
                for d, r, _o in moving[:5] if r > 0
            ],
            "thin": list(thin)[:5],
        }
    except Exception as e:
        log.debug(f"span becoming gather failed: {e}")

    # Captures count at the wider window
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = get_recent_captures(n=500) or []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0
        for c in recent:
            try:
                ts = datetime.fromisoformat(c.get("captured_at", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count += 1
            except Exception:
                continue
        signals["captures"]["count"] = count
    except Exception as e:
        log.debug(f"span captures gather failed: {e}")

    return signals


def parse_retro_span_arg(arg: str) -> Optional[int]:
    """Phase 23.0 — Parse a free-text span specifier into a number of days.

    Returns days (int) or None if the arg doesn't look like a span.
    Recognized formats:
      'this month'           → days since first of current month
      'last month'           → ~30
      'past N days'          → N (where N is a positive integer)
      'last N weeks'         → N*7
      'since YYYY-MM-DD'     → days between then and now
    """
    if not arg:
        return None
    s = arg.strip().lower()
    # 'this month'
    if s == "this month":
        now = datetime.now()
        return max(1, (now - now.replace(day=1)).days + 1)
    if s in ("last month", "past month"):
        return 30
    if s in ("last week", "past week"):
        return 7
    # 'past N days' / 'last N days'
    import re as _re
    m = _re.match(r"(?:past|last)\s+(\d+)\s+days?", s)
    if m:
        try:
            return max(1, min(365, int(m.group(1))))
        except Exception:
            return None
    # 'past N weeks' / 'last N weeks'
    m = _re.match(r"(?:past|last)\s+(\d+)\s+weeks?", s)
    if m:
        try:
            return max(1, min(52, int(m.group(1)))) * 7
        except Exception:
            return None
    # 'since YYYY-MM-DD'
    m = _re.match(r"since\s+(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            since = datetime.strptime(m.group(1), "%Y-%m-%d")
            delta = (datetime.now() - since).days
            return max(1, min(365, delta))
        except Exception:
            return None
    return None


def _compose_span_portrait_body(signals: dict) -> Optional[str]:
    """Phase 23.0 — Render a span-flavored portrait via Sonnet.

    Different framing from the weekly portrait — looking at a longer
    arc instead of one week. Same Beatrice voice."""
    days = signals.get("span_days", 30)
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        mood = signals.get("mood") or {}
        bec = signals.get("becoming") or {}
        not_ = signals.get("noticings") or {}
        deng = signals.get("dashboard_engagement") or {}
        top_dash = ""
        if deng:
            ranked = sorted(
                deng.items(), key=lambda kv: -sum(kv[1].values())
            )
            if ranked:
                top_dash = ranked[0][0]
        span_label = (
            f"the last {days} days" if days != 30 else "the last month"
        )
        user_prompt = (
            f"# {USER_NAME}'s signals over {span_label}\n\n"
            f"**Mood:** {mood.get('summary_line', 'no data')} "
            f"({mood.get('total_classifications', 0)} voice notes; "
            f"{mood.get('trend_explanation', '')})\n\n"
            f"**Becoming arc:** "
            f"{bec.get('learnings', 0)} learnings logged. "
            f"Top moving: {[m['dimension'] for m in bec.get('top_moving', [])]}. "
            f"Thin: {bec.get('thin', [])}.\n\n"
            f"**Noticings:** "
            f"{not_.get('total', 0)} themes total. "
            f"Recent: {not_.get('recent_themes', [])[:5]}.\n\n"
            f"**Captures:** "
            f"{signals.get('captures', {}).get('count', 0)} in this span.\n\n"
            f"**Dashboards he reached for:** "
            f"{top_dash or '(none)'}.\n\n"
            f"Write the span portrait body (~180-260 words, slightly "
            f"longer than a weekly portrait — the arc is wider). "
            f"Beatrice's voice. Witness, not fixer. Reference 2-4 "
            f"specific signals where they're meaningful. Don't try to "
            f"cover everything."
        )
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=700,
            system=_PORTRAIT_SYSTEM,
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
        log.warning(f"_compose_span_portrait_body failed: {e}")
        return None


def render_retro_span(*, days: int) -> str:
    """Phase 23.0 — Render a span retro for Telegram.

    Returns the formatted body (with header). No archival — span
    retros are exploratory, not canonical."""
    if days < 1:
        return "🪞 _Span must be at least 1 day._"
    signals = _gather_span_signals(days=days)
    body = _compose_span_portrait_body(signals)
    if not body:
        return (
            f"🪞 *Retro — last {days} days*\n\n"
            f"_Couldn't compose. Either the composer failed or "
            f"signals were too thin._"
        )
    span_label = (
        f"last {days} days" if days != 30 else "the last month"
    )
    return f"🪞 *Retro — {span_label}*\n\n{body}"


# ── Phase 21.0: voice-render cache ────────────────────────────────────────


PORTRAIT_VOICE_CACHE_DIR = os.path.join(MEMORY_DIR, "portrait_voice_cache")
PORTRAIT_VOICE_CACHE_TTL_HOURS = 7 * 24  # one week (cooldown == build window)


def _portrait_voice_cache_key(body: str, style: str) -> str:
    """Stable hash for (body, style). Phase 18.1 pattern."""
    import hashlib
    blob = f"{(body or '').strip()}|{(style or '').strip()}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def get_cached_portrait_voice(body: str, style: str = "gentle") -> Optional[str]:
    """Return path to a cached voice clip for this portrait body, or None.

    Mirrors Phase 18.1's noticing-voice cache. TTL is one week so the
    Sunday portrait can be replayed via /retro within the same week
    without re-rendering."""
    try:
        os.makedirs(PORTRAIT_VOICE_CACHE_DIR, exist_ok=True)
        key = _portrait_voice_cache_key(body, style)
        path = os.path.join(PORTRAIT_VOICE_CACHE_DIR, f"{key}.ogg")
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            age_hours = (
                datetime.now().timestamp() - mtime
            ) / 3600.0
            if age_hours > PORTRAIT_VOICE_CACHE_TTL_HOURS:
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
        except Exception:
            return None
        return path
    except Exception as e:
        log.debug(f"get_cached_portrait_voice failed: {e}")
        return None


def cache_portrait_voice(
    body: str, source_path: str, style: str = "gentle",
) -> Optional[str]:
    """Copy `source_path` (a freshly rendered .ogg) into the cache."""
    if not source_path or not os.path.exists(source_path):
        return None
    try:
        os.makedirs(PORTRAIT_VOICE_CACHE_DIR, exist_ok=True)
        key = _portrait_voice_cache_key(body, style)
        cache_path = os.path.join(PORTRAIT_VOICE_CACHE_DIR, f"{key}.ogg")
        import shutil
        shutil.copy(source_path, cache_path)
        return cache_path
    except Exception as e:
        log.debug(f"cache_portrait_voice failed: {e}")
        return None


def pick_portrait_voice_style(signals: Optional[dict] = None) -> str:
    """Pick gentle (default) or tender (heavy week) style for the
    portrait voice. Mirrors Phase 17.4's adapt_style_to_weather but
    derives the decision from the portrait's own mood snapshot rather
    than re-reading the emotion log."""
    if not signals:
        return "gentle"
    mood = signals.get("mood") or {}
    if mood.get("trend") == "declining":
        return "tender"
    return "gentle"


# ── Public API ─────────────────────────────────────────────────────────────


def get_latest_self_portrait() -> Optional[dict]:
    """Return the most recent portrait entry, or None."""
    if not os.path.exists(PORTRAIT_LOG_PATH):
        return None
    try:
        last = None
        with open(PORTRAIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except Exception:
                    continue
        return last
    except Exception as e:
        log.debug(f"get_latest_self_portrait failed: {e}")
        return None


def list_self_portraits(
    *, conversation_id: Optional[str] = None,
) -> list[dict]:
    """Phase 20.1 — Return every portrait entry, newest-first.

    Used by /retro all and /retro <date>. Filtered by conversation_id
    when provided (None = whole-vault). Backwards-compat: entries
    without the conversation_id field are treated as 'default'."""
    if not os.path.exists(PORTRAIT_LOG_PATH):
        return []
    out: list[dict] = []
    try:
        with open(PORTRAIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if conversation_id is not None:
                    entry_cid = (
                        entry.get("conversation_id") or "default"
                    )
                    if entry_cid != conversation_id:
                        continue
                out.append(entry)
    except Exception as e:
        log.debug(f"list_self_portraits failed: {e}")
        return []
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out


def get_self_portrait_for_date(
    target_date: str, *, conversation_id: Optional[str] = None,
) -> Optional[dict]:
    """Phase 20.1 — Return the portrait whose timestamp falls in the
    week containing `target_date` (YYYY-MM-DD). The week is anchored
    on Sunday (the canonical build day).

    None when no matching portrait exists."""
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d")
    except Exception:
        return None
    # Anchor to that week's Sunday — find Sunday before-or-equal target
    days_after_sunday = (target.weekday() + 1) % 7  # Sun=0, Mon=1, ...
    week_sunday = target - timedelta(days=days_after_sunday)
    week_start = week_sunday - timedelta(days=1)  # generous: Sat → next Sat
    week_end = week_sunday + timedelta(days=6)
    portraits = list_self_portraits(conversation_id=conversation_id)
    for p in portraits:
        try:
            ts = datetime.fromisoformat(p.get("ts", "").rstrip("Z"))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if week_start <= ts <= week_end:
                return p
        except Exception:
            continue
    return None


def _portrait_age_days(portrait: Optional[dict]) -> Optional[float]:
    """Age in days, or None if no portrait or bad timestamp."""
    if not portrait:
        return None
    try:
        ts_str = portrait.get("ts") or portrait.get("captured_at")
        if not ts_str:
            return None
        ts = datetime.fromisoformat(ts_str.rstrip("Z"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    except Exception:
        return None


def build_weekly_self_portrait(
    force: bool = False,
    conversation_id: Optional[str] = None,
) -> Optional[dict]:
    """Build a Sunday self-portrait. Side effect: writes to the log AND
    drops a Tier-3 lived note in the vault.

    Phase 24.5 — `conversation_id` scopes the gather. None = aggregate
    (whole-vault, default Sunday behavior). When passed, signals are
    filtered to that conversation; the portrait is tagged in the log
    + frontmatter so per-conversation history is queryable.

    Returns the portrait dict or None when:
      - Cooldown applies (last build <PORTRAIT_COOLDOWN_DAYS days ago)
        and `force=False`
      - Sonnet composition fails
    """
    if not force:
        last = get_latest_self_portrait()
        age = _portrait_age_days(last)
        if age is not None and age < PORTRAIT_COOLDOWN_DAYS:
            log.debug(
                f"portrait skipped: last built {age:.1f}d ago "
                f"(<{PORTRAIT_COOLDOWN_DAYS}d cooldown)"
            )
            return None
    signals = _gather_week_signals(conversation_id=conversation_id)
    body = _compose_portrait_body(signals)
    if not body:
        log.info("portrait skipped: composer failed or returned empty")
        return None
    vault_path = _write_portrait_to_vault(body, signals)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "body": body,
        "signals": signals,
        "vault_path": vault_path,
    }
    _write_portrait_to_log(entry)
    log.info(
        f"weekly self-portrait built ({len(body)} chars) → {vault_path}"
    )
    return entry


_RETRO_QA_SYSTEM = (
    f"You are Alicia, answering {USER_NAME}'s question about his own week. "
    "He's asking you to look at the same signals you'd use to compose "
    "the Sunday self-portrait — mood, dashboards he engaged with, "
    "themes you've been quietly tracking, dimensions of him that "
    "moved or stayed thin, the captures he made — and to ANSWER his "
    "specific question from those.\n\n"
    "Beatrice's voice. Witnessing, not advising. ~120-180 words. "
    "Reference 1-3 specific signals where they actually answer the "
    "question. NO recommendations. NO 'you should'. NO 'consider'. "
    "If the signals don't really answer the question — say so quietly "
    "rather than confabulating.\n\n"
    "If the question is open-ended ('what was hardest', 'what stood "
    "out', 'how was the week'), give a small portrait-flavored "
    "response. If it's specific ('did I write more this week?', "
    "'was Tuesday rough?'), answer that question directly from "
    "what's in the signals — pull the number, name the day, quote "
    "the noticing.\n\n"
    "Open with the answer (no preamble). Close on observation, not "
    "prescription."
)


# Phase 22.1 — Cache retro Q&A answers so re-asking the same question
# in the same week skips the Sonnet call. Hash key: (normalized
# question, week_key). TTL: 7 days (matches the build cooldown).
RETRO_QA_CACHE_DIR = os.path.join(MEMORY_DIR, "retro_qa_cache")
RETRO_QA_CACHE_TTL_HOURS = 7 * 24


def _retro_qa_cache_key(question: str, week_key: str) -> str:
    """Stable hash of (normalized question, week_key)."""
    import hashlib
    norm = " ".join((question or "").lower().split())
    blob = f"{norm}|{week_key or ''}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _current_week_key() -> str:
    """Return YYYY-W## for the current ISO week. Stable Monday-anchored
    week boundary used by the cache."""
    now = datetime.now()
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _read_retro_qa_cache(question: str, week_key: str) -> Optional[str]:
    """Return cached answer text, or None if missing/stale."""
    try:
        os.makedirs(RETRO_QA_CACHE_DIR, exist_ok=True)
        key = _retro_qa_cache_key(question, week_key)
        path = os.path.join(RETRO_QA_CACHE_DIR, f"{key}.txt")
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            age_hours = (
                datetime.now().timestamp() - mtime
            ) / 3600.0
            if age_hours > RETRO_QA_CACHE_TTL_HOURS:
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
        except Exception:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        log.debug(f"_read_retro_qa_cache failed: {e}")
        return None


def _write_retro_qa_cache(
    question: str, week_key: str, answer: str,
) -> None:
    """Persist a Q&A answer to the cache."""
    if not answer:
        return
    try:
        os.makedirs(RETRO_QA_CACHE_DIR, exist_ok=True)
        key = _retro_qa_cache_key(question, week_key)
        path = os.path.join(RETRO_QA_CACHE_DIR, f"{key}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(answer)
    except Exception as e:
        log.debug(f"_write_retro_qa_cache failed: {e}")


def answer_retro_question(
    question: str, *,
    conversation_id: Optional[str] = None,
    use_cache: bool = True,
) -> Optional[str]:
    """Phase 22.0 — Sonnet Q&A over the same week's signals the
    self-portrait composer uses. Returns the answer text, or None on
    failure. Side-effect-free — this isn't archived as a Tier-3 note
    (those are reserved for the canonical Sunday portrait); it's just
    a witness response to a probe.

    Phase 22.1 — Caches by hash(question, week_key) with 7d TTL.
    Same question in the same week skips the Sonnet call. Set
    `use_cache=False` to force a fresh call (useful for testing or
    when the user wants a fresh look at the same probe)."""
    if not question or not question.strip():
        return None
    week_key = _current_week_key()
    # Phase 22.1 — cache lookup
    if use_cache:
        cached = _read_retro_qa_cache(question, week_key)
        if cached:
            log.info(
                f"[retro-qa-cache] hit week={week_key} "
                f"q={question[:40]!r}"
            )
            return cached
    signals = _gather_week_signals()
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        # Compact summary similar to the portrait prompt but trimmed
        # for question-answering rather than portrait-painting.
        mood = signals.get("mood") or {}
        bec = signals.get("becoming") or {}
        not_ = signals.get("noticings") or {}
        deng = signals.get("dashboard_engagement") or {}
        top_dash = ""
        if deng:
            ranked = sorted(
                deng.items(), key=lambda kv: -sum(kv[1].values())
            )
            if ranked:
                top_dash = ranked[0][0]
        user_prompt = (
            f"# {USER_NAME}'s question\n"
            f"_{question.strip()}_\n\n"
            f"# This week's signals\n\n"
            f"**Mood:** {mood.get('summary_line', 'no data')} "
            f"({mood.get('total_classifications', 0)} voice notes; "
            f"{mood.get('trend_explanation', '')})\n\n"
            f"**Becoming arc:** "
            f"{bec.get('learnings_7d', 0)} learnings logged. "
            f"Top moving: {[m['dimension'] for m in bec.get('top_moving', [])]}. "
            f"Thin: {bec.get('thin', [])}.\n\n"
            f"**Noticings (themes I've been tracking):** "
            f"{not_.get('total', 0)} total. "
            f"Recent: {not_.get('recent_themes', [])[:3]}.\n\n"
            f"**Captures:** "
            f"{signals.get('captures', {}).get('count_7d', 0)} this week.\n\n"
            f"**Dashboards he reached for:** "
            f"{top_dash or '(none yet)'}.\n\n"
            f"Answer his question from these signals. Beatrice's voice. "
            f"~120-180 words. Witness, not advise."
        )
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=_RETRO_QA_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return None
        raw = (resp.content[0].text or "").strip()
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1].strip()
        if raw and use_cache:
            _write_retro_qa_cache(question, week_key, raw)
        return raw or None
    except Exception as e:
        log.warning(f"answer_retro_question failed: {e}")
        return None


def render_retro_for_telegram(
    *,
    target_date: Optional[str] = None,
    show_all: bool = False,
    conversation_id: Optional[str] = None,
) -> str:
    """Phase 20.0 — render the most recent portrait as a Telegram message.

    Phase 20.1 args:
        target_date: YYYY-MM-DD — render the portrait for that week
            (Sunday-anchored). None means most-recent.
        show_all: if True, render an INDEX of every portrait (with
            dates + one-line snippets) instead of a single body.
        conversation_id: filter portraits to one conversation. None
            preserves whole-vault behavior.

    If no portrait exists for the requested target, builds fresh
    (force=True bypasses cooldown).
    """
    # Phase 20.1 — index view
    if show_all:
        portraits = list_self_portraits(conversation_id=conversation_id)
        if not portraits:
            return (
                "🪞 *Self-portraits*\n\n"
                "_None archived yet — try `/retro` to build the first._"
            )
        scope_blurb = ""
        if conversation_id is not None:
            scope_blurb = f" _scoped to_ `{conversation_id}`"
        lines = [
            f"🪞 *Self-portraits — {len(portraits)} archived*"
            f"{scope_blurb}",
            "",
        ]
        for p in portraits[:12]:
            ts = (p.get("ts") or "")[:10]
            body = (p.get("body") or "").strip()
            # First sentence — Markdown-safe, ≤140 chars
            snippet = body.split(".")[0][:140] if body else "_(no body)_"
            lines.append(f"  • _{ts}_ — {snippet}…")
        if len(portraits) > 12:
            lines.append(f"  _…+{len(portraits) - 12} older_")
        return "\n".join(lines)

    # Phase 20.1 — historical view by date
    if target_date:
        portrait = get_self_portrait_for_date(
            target_date, conversation_id=conversation_id,
        )
        if not portrait:
            return (
                f"🪞 *Self-portrait for week of {target_date}*\n\n"
                f"_No portrait archived for that week. "
                f"Use `/retro all` to see what is archived._"
            )
        body = (portrait.get("body") or "").strip()
        ts = (portrait.get("ts") or "")[:10]
        header = f"🪞 *Self-portrait — {ts}*\n\n"
        vault_path = portrait.get("vault_path")
        footer = (
            f"\n\n_archived: `{vault_path}`_" if vault_path else ""
        )
        return header + body + footer

    # Default: most-recent or build fresh
    portrait = get_latest_self_portrait()
    age = _portrait_age_days(portrait)
    if portrait is None or (age is not None and age > 7):
        # No portrait ever, or older than a week — build fresh
        portrait = build_weekly_self_portrait(force=True)
    if not portrait:
        return (
            "🪞 *Sunday self-portrait*\n\n"
            "_Not enough signal yet, or composer failed. Try again "
            "after a few more voice notes + captures land._"
        )
    body = (portrait.get("body") or "").strip()
    age_str = ""
    if age is not None:
        if age < 1:
            age_str = "today"
        elif age < 1.5:
            age_str = "yesterday"
        else:
            age_str = f"{int(age)} days ago"
    header = (
        f"🪞 *Sunday self-portrait*"
        + (f" _({age_str})_" if age_str else "")
        + "\n\n"
    )
    vault_path = portrait.get("vault_path")
    footer = ""
    if vault_path:
        footer = f"\n\n_archived: `{vault_path}`_"
    return header + body + footer


if __name__ == "__main__":
    import json as _json
    result = build_weekly_self_portrait(force=True)
    print(_json.dumps(result, indent=2, default=str)[:600])
