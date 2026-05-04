#!/usr/bin/env python3
"""
Layer 2 — Circulation Composer.

Signal-driven policy: at each communication slot, decide whether there is
anything in Alicia's circulatory state that *earns* a message right now. If
yes, return a decision with the synthesis, archetype, and channel. If no,
return NO_SEND — silence is a valid output.

Replaces the fixed-probability cap pattern in
`proactive_messages._pick_greeting_format` and related dispatchers. Feature-
flagged behind USE_CIRCULATION_COMPOSER (default False).

See /Alicia/Bridge/WISDOM_ENGINE_PROPOSAL.md §Layer 2 and §8 for the why.

Public API:
    decide_for_slot(slot) -> CirculationDecision
    record_reaction(decision_id, reaction) -> None
    check_invariants() -> list[dict]         # used by CI test
    CIRCULATION_LOG_FILE                       # where decisions land

Inputs read:
    - Finalizer queue: skills.synthesis_finalizer.get_ready_surfacings
    - /Alicia/Self/Contradictions.md — active contradictions
    - /Alicia/Wisdom/Lineages/*.md — lineage bridges (read when synthesis cites a lineage)
    - circulation log — for broken-record dedup

Side effects (on send=True decisions):
    - Append the decision to circulation_log.json
    - Mark the source surfacing stage as delivered in the Finalizer queue
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.circulation")

# ── Config ──────────────────────────────────────────────────────────────────

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", os.path.expanduser("~/alicia/memory")
))
CONTRADICTIONS_PATH = VAULT_ROOT / "Alicia" / "Self" / "Contradictions.md"
LINEAGES_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Lineages"
CIRCULATION_LOG_FILE = MEMORY_DIR / "circulation_log.json"

# Feature flag. Default False — the composer only takes over when set.
USE_CIRCULATION_COMPOSER = os.environ.get(
    "USE_CIRCULATION_COMPOSER", "false"
).lower() in ("1", "true", "yes", "on")

# Broken-record invariant: same synthesis × same archetype blocked for N days.
NO_SAME_SYNTHESIS_ARCHETYPE_DAYS = 7

# Log cap (most-recent N decisions retained).
LOG_MAX_ENTRIES = 2000


# ── Types ───────────────────────────────────────────────────────────────────


class Archetype(str, Enum):
    DAIMON = "Daimon"          # quality gate
    BEATRICE = "Beatrice"      # visible growth
    ARIADNE = "Ariadne"        # threading / patterns
    PSYCHE = "Psyche"          # soul / dialectic
    MUSUBI = "Musubi"          # pattern from repetition
    MUSE = "Muse"              # felt-shift / generative


class Channel(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    DRAWING = "drawing"
    NO_SEND = "no_send"


@dataclass
class CirculationDecision:
    """What the Composer returns for a slot evaluation."""
    id: str                              # uuid for logging / reactions
    slot: str                            # "morning" | "midday" | "evening" | "out_of_band"
    send: bool
    channel: str                         # Channel enum value
    archetype: Optional[str]             # Archetype enum value, or None on NO_SEND
    source_kind: str                     # "surfacing" | "contradiction" | "lineage_bridge" | "quiet"
    source_id: Optional[str]             # surfacing entry_id | contradiction title | None
    synthesis_title: Optional[str]
    synthesis_path: Optional[str]
    stage_name: Optional[str]            # surfacing stage ("fresh" | "next_day" | ...)
    score: float                         # how strongly this candidate was selected
    reason: str                          # human-readable explanation
    decided_at: str                      # ISO timestamp UTC


# ── Signal → Archetype mapping (from proposal §8) ───────────────────────────

# Stage-to-archetype for surfacings. This is the "voice hint" of the stage
# expressed as the archetype who speaks it.
_STAGE_ARCHETYPE: dict[str, Archetype] = {
    "fresh":       Archetype.ARIADNE,    # still-warm — thread-keeper
    "next_day":    Archetype.MUSE,       # slept-on-it — generative echo
    "three_days":  Archetype.MUSUBI,     # settling — pattern from repetition
    "one_week":    Archetype.BEATRICE,   # test-the-grip — visible growth check
    "three_weeks": Archetype.PSYCHE,     # test-of-time — dialectic depth
}

# Slot preferences — which stages a given slot "leans toward".
_SLOT_STAGE_BIAS: dict[str, set[str]] = {
    "morning":     {"fresh", "next_day"},
    "midday":      {"three_days"},
    "evening":     {"one_week", "three_weeks"},
    "out_of_band": {"fresh", "three_weeks"},
}


# ── Circulation log ─────────────────────────────────────────────────────────


def _load_circulation_log() -> list[dict]:
    try:
        if CIRCULATION_LOG_FILE.exists():
            return json.loads(CIRCULATION_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to read circulation log: {e}")
    return []


def _append_circulation_log(decision: CirculationDecision) -> None:
    entries = _load_circulation_log()
    record = asdict(decision)
    # Phase 16.0 — tag every entry with the active conversation id so
    # future surfaces can scope by conversation. No behavior change today.
    try:
        from myalicia.skills.conversations import tag as _tag_conv
        _tag_conv(record)
    except Exception:
        pass
    entries.append(record)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(CIRCULATION_LOG_FILE), entries)
    except Exception as e:
        log.warning(f"Failed to write circulation log: {e}")


# Phase 13.1 — drawing amplification threshold. A composer decision whose
# score reaches this threshold AND has an archetype set is eligible for
# multi-channel amplification (text + voice already there; drawing fires
# in background as visual amplification). 2.0 is conservative — only the
# truly high-conviction moments get all three channels.
DRAWING_AMPLIFY_THRESHOLD = 2.0


def should_amplify_with_drawing(decision: "CirculationDecision") -> bool:
    """Phase 13.1 — does this composer decision deserve drawing amplification?

    Returns True when ALL hold:
      - decision.send is True (no amplifying NO_SEND)
      - decision.archetype is set (need a voice for the drawing)
      - decision.score >= DRAWING_AMPLIFY_THRESHOLD (high-conviction only)
      - decision.source_kind in (surfacing, lived_surfacing, contradiction)
        — not practice_progress (those are quieter morning signals)

    The drawing will share the decision's id as `moment_id` so the two
    events are linkable in /wisdom and /effectiveness.
    """
    if not getattr(decision, "send", False):
        return False
    if not getattr(decision, "archetype", None):
        return False
    if (decision.score or 0.0) < DRAWING_AMPLIFY_THRESHOLD:
        return False
    if decision.source_kind not in (
        "surfacing", "lived_surfacing", "contradiction",
    ):
        return False
    return True


def record_drawing_decision(
    *,
    archetype: str,
    caption: str,
    source_kind: str = "drawing_impulse",
    source_id: Optional[str] = None,
    drawing_path: Optional[str] = None,
    telegram_message_id: Optional[int] = None,
    slot: str = "drawing",
    decided_at: Optional[datetime] = None,
    moment_id: Optional[str] = None,
) -> str:
    """Phase 13.0 — record a drawing send into the circulation log.

    Drawings are first-class circulation events. Same audit surface as
    composer-driven text/voice sends so /wisdom, /effectiveness engagement
    rate, and response_capture's proactive_decision_id linkage all work.

    Unlike `record_send` (which augments an existing decision), this
    function CREATES a fresh entry — drawings don't pass through
    decide_for_slot's gate (yet — Phase 13.1 will integrate them).

    Args:
        archetype: which archetype voice the drawing speaks in
        caption:   the drawing's caption (becomes prompt_text for capture)
        source_kind: 'drawing_impulse' (scheduler), 'drawing_manual'
                     (/draw command), 'drawing_composer' (Phase 13.1)
        source_id:  drawing-context id (the `did` from drawing_skill)
        drawing_path: filesystem path of the rendered image
        telegram_message_id: Telegram message_id of the sent drawing
        slot:       'drawing' by default; future composer-driven multi-
                    channel sends may use 'morning'/'midday'/'evening'
        decided_at: defaults to now

    Returns the new decision_id (uuid).
    """
    now_utc = decided_at or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    decision_id = str(uuid.uuid4())
    decision = CirculationDecision(
        id=decision_id,
        slot=slot,
        send=True,
        channel=Channel.DRAWING.value,
        archetype=archetype or None,
        source_kind=source_kind,
        source_id=source_id,
        synthesis_title=None,
        synthesis_path=drawing_path,
        stage_name=None,
        score=0.0,
        reason=(caption or "")[:200],
        decided_at=now_utc.isoformat(),
    )
    _append_circulation_log(decision)

    # Phase 13.1 — moment_id linkage. Drawings amplifying a composer-driven
    # text moment carry the text decision's id as moment_id so /wisdom and
    # /effectiveness can show 'these two events are one moment'. We inject
    # the field after _append_circulation_log because CirculationDecision
    # has fixed fields; the JSON log is permissive about extras.
    if moment_id:
        try:
            entries = _load_circulation_log()
            for e in entries:
                if e.get("id") == decision_id:
                    e["moment_id"] = moment_id
                    break
            atomic_write_json(str(CIRCULATION_LOG_FILE), entries)
        except Exception as e:
            log.debug(f"record_drawing_decision moment_id inject skip: {e}")

    # Augment immediately with the rendered caption + telegram_message_id.
    # We could roll this into the initial _append, but reusing record_send
    # keeps the augmentation path uniform across all decision types.
    if caption:
        try:
            record_send(
                decision_id,
                prompt_text=caption,
                telegram_message_id=telegram_message_id,
                sent_at=now_utc,
            )
        except Exception as e:
            log.debug(f"record_drawing_decision augmentation skip: {e}")
    log.info(
        f"[circulation] drawing recorded id={decision_id[:8]} "
        f"archetype={archetype} src={source_kind} "
        f"telegram_id={telegram_message_id}"
    )
    return decision_id


def record_send(
    decision_id: str,
    *,
    prompt_text: str,
    telegram_message_id: Optional[int] = None,
    sent_at: Optional[datetime] = None,
) -> bool:
    """
    Augment an existing circulation_log entry with the actually-rendered
    Telegram text + message_id + sent_at timestamp. Called from the proactive
    send paths (morning/midday/evening, etc.) right after Telegram returns
    the sent Message object.

    `decided_at` is left untouched — it represents when the composer made
    the choice; `sent_at` is when the user actually saw it. The two can
    differ by tens of seconds (TTS rendering, archetype-flavor injection).

    Returns True if the log entry was found and updated, False otherwise.
    Failures are non-fatal — the send already happened either way.
    """
    if sent_at is None:
        sent_at = datetime.now(timezone.utc)
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)

    try:
        entries = _load_circulation_log()
        updated = False
        for entry in entries:
            if entry.get("id") == decision_id:
                entry["prompt_text"] = prompt_text
                if telegram_message_id is not None:
                    entry["telegram_message_id"] = telegram_message_id
                entry["sent_at"] = sent_at.isoformat()
                updated = True
                break
        if updated:
            atomic_write_json(str(CIRCULATION_LOG_FILE), entries)
            log.info(
                f"[circulation] recorded send for decision {decision_id[:8]} "
                f"telegram_id={telegram_message_id} "
                f"prompt_len={len(prompt_text)}"
            )
        else:
            log.warning(
                f"[circulation] record_send: decision {decision_id} not found"
            )
        return updated
    except Exception as e:
        log.warning(f"[circulation] record_send failed: {e}")
        return False


def _recent_synthesis_archetype_pairs(
    days: int = NO_SAME_SYNTHESIS_ARCHETYPE_DAYS,
) -> set[tuple[str, str]]:
    """Set of (synthesis_title, archetype) pairs sent in last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pairs: set[tuple[str, str]] = set()
    for entry in _load_circulation_log():
        if not entry.get("send"):
            continue
        title = entry.get("synthesis_title")
        archetype = entry.get("archetype")
        if not title or not archetype:
            continue
        try:
            decided_at = datetime.fromisoformat(entry["decided_at"])
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if decided_at >= cutoff:
            pairs.add((title, archetype))
    return pairs


# ── Candidate gathering ─────────────────────────────────────────────────────


def _get_surfacing_candidates(now: Optional[datetime] = None) -> list[dict]:
    """Pull ready surfacings from the Finalizer's queue. Safe on import failure."""
    try:
        from myalicia.skills.synthesis_finalizer import get_ready_surfacings
        return get_ready_surfacings(now=now)
    except Exception as e:
        log.warning(f"Could not get surfacings: {e}")
        return []


def _parse_active_contradictions() -> list[dict]:
    """
    Parse /Alicia/Self/Contradictions.md. Returns list of
    {title, archetype, archetypes, status, last_updated} for entries with
    status == active.

    `archetype` is the primary (first-matched) archetype for backward compat;
    `archetypes` is the full list (an entry like "Daimon ⇄ Beatrice" returns
    both). `last_updated` is the YYYY-MM-DD string from the entry, or None.

    The parser is deliberately tolerant — it walks top-level `### N. Title`
    headers and `**Archetype home**` / `**Status**` / `**Last updated**` lines.
    If the schema drifts, unknown entries are skipped (logged at debug), never
    raised.
    """
    if not CONTRADICTIONS_PATH.exists():
        return []
    try:
        text = CONTRADICTIONS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Could not read Contradictions.md: {e}")
        return []

    candidates: list[dict] = []
    current: Optional[dict] = None

    header_re = re.compile(r"^###\s+\d+\.\s*(.+?)\s*$")
    last_updated_re = re.compile(r"(\d{4}-\d{2}-\d{2})")

    def _flush():
        if current and current.get("status") == "active":
            candidates.append(current)

    for line in text.split("\n"):
        m = header_re.match(line)
        if m:
            _flush()
            current = {
                "title": m.group(1).strip(),
                "status": None,
                "archetype": None,
                "archetypes": [],
                "last_updated": None,
            }
            continue
        if current is None:
            continue
        lower = line.lower()
        if "**archetype home**" in lower:
            # Capture every archetype mentioned on the line (e.g. "Daimon ⇄ Beatrice").
            seen: list[str] = []
            for arch in Archetype:
                if arch.value in line and arch.value not in seen:
                    seen.append(arch.value)
            if seen:
                current["archetypes"] = seen
                current["archetype"] = seen[0]
        elif "**status**" in lower:
            if "`active`" in line:
                current["status"] = "active"
            elif "`dormant`" in line:
                current["status"] = "dormant"
            elif "`resolved`" in line:
                current["status"] = "resolved"
        elif "**last updated**" in lower:
            mdate = last_updated_re.search(line)
            if mdate:
                current["last_updated"] = mdate.group(1)
    _flush()
    return candidates


def _assign_surfacing_archetype(stage_name: str) -> Archetype:
    """Map a surfacing stage to its archetype voice. Defaults to Ariadne."""
    return _STAGE_ARCHETYPE.get(stage_name, Archetype.ARIADNE)


# ── Scoring ─────────────────────────────────────────────────────────────────


# Phase 13.13 — meta-synthesis surfacing bonus. Meta-syntheses are higher-
# altitude distillations (Phase 13.6) and deserve a small composer-weight
# bump so they surface ahead of plain syntheses, all else equal. Bonus
# scales with the recursion level (Phase 13.10): level 1 = +0.3, level 2
# = +0.5, level 3 = +0.7. Plain syntheses (level 0) get no bonus.
META_SURFACING_BONUS_PER_LEVEL = 0.2
META_SURFACING_BONUS_BASE = 0.1


def _meta_surfacing_bonus(entry: dict) -> float:
    """Return the meta-synthesis bonus for this surfacing entry, or 0.0.

    Looks up the surfaced synthesis's path and reads its frontmatter level
    via meta_synthesis.get_synthesis_level. Cheap (one file read per
    candidate). Failures (missing path, unreadable file, no frontmatter)
    return 0.0 silently — degrading gracefully to baseline scoring."""
    title = entry.get("synthesis_title") or entry.get("title")
    if not title:
        return 0.0
    try:
        from myalicia.skills.meta_synthesis import (
            find_synthesis_path, read_synthesis, get_synthesis_level,
        )
        path = find_synthesis_path(title)
        if path is None:
            return 0.0
        text = read_synthesis(path)
        level = get_synthesis_level(text)
        if level <= 0:
            return 0.0
        return META_SURFACING_BONUS_BASE + META_SURFACING_BONUS_PER_LEVEL * level
    except Exception as e:
        log.debug(f"_meta_surfacing_bonus failed for {title!r}: {e}")
        return 0.0


def _score_surfacing(entry: dict, slot: str) -> float:
    """
    Score a surfacing candidate for this slot. Higher = more likely to be chosen.
      base                                        1.0
      + stage matches slot bias                  +0.5
      + synthesis has a numeric score (Finalizer) +0.01*score (capped at 0.5)
      + Phase 13.13 meta-synthesis bonus          +0.3 (L1) / +0.5 (L2) / +0.7 (L3)
    """
    score = 1.0
    if entry.get("stage_name") in _SLOT_STAGE_BIAS.get(slot, set()):
        score += 0.5
    # Not currently populated by Finalizer but honored if present
    raw = entry.get("score")
    if isinstance(raw, (int, float)):
        score += min(max(float(raw) * 0.01, 0.0), 0.5)
    # Phase 13.13 — meta-synthesis surfacing bonus
    score += _meta_surfacing_bonus(entry)
    return score


def _practice_archetype_for_contradiction(entry: dict) -> Optional[str]:
    """
    If an active practice's archetype matches one of this contradiction's
    archetype-home values, return that archetype string. Otherwise None.

    This is the bridge that lets a contradiction speak in the voice that is
    actually being lived. E.g. for a "Daimon ⇄ Beatrice" tension where Beatrice
    has an active practice, the composer should hear Beatrice tonight — not
    Daimon — because Beatrice is where the practice is happening.
    """
    archetypes = entry.get("archetypes") or (
        [entry["archetype"]] if entry.get("archetype") else []
    )
    if not archetypes:
        return None
    try:
        from myalicia.skills.practice_runner import active_practices
        for p in active_practices():
            if p.archetype in archetypes:
                return p.archetype
    except Exception as e:
        log.debug(f"practice-link lookup failed: {e}")
    return None


def _score_contradiction(entry: dict, slot: str) -> float:
    """
    Score a contradiction for this slot. Higher = more likely to be chosen.

    Base by slot (contradictions prefer evening / out_of_band, avoid morning):
        morning      → 0.0  (always silent)
        midday       → 0.9
        evening      → 1.5
        out_of_band  → 1.8

    Then modulated by entry data:
        + recency bonus (0.0 to +0.3): newer Last updated = higher
        + practice-link bonus (+0.4): an active practice descends from this
          contradiction's archetype-home

    Tie-breaking: if all 5 active contradictions had identical scores, the
    composer would always pick the first one in file order (stable sort). The
    recency + practice-link bumps break that tie based on real signal — the
    most recently touched and most actively practiced tension wins.
    """
    base = {
        "morning":     0.0,
        "midday":      0.9,
        "evening":     1.5,
        "out_of_band": 1.8,
    }.get(slot, 0.9)
    if base == 0.0:
        return 0.0

    bonus = 0.0

    # Recency bonus — 0 days → +0.3, ≥30 days → 0.0, linear in between.
    last_updated = entry.get("last_updated")
    if last_updated:
        try:
            dt = datetime.strptime(last_updated, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            days = max(0, (datetime.now(timezone.utc) - dt).days)
            bonus += max(0.0, 0.3 * (1.0 - days / 30.0))
        except Exception:
            pass

    # Practice-link bonus — a contradiction with an active practice wins.
    if _practice_archetype_for_contradiction(entry):
        bonus += 0.4

    return base + bonus


# ── Main decision function ──────────────────────────────────────────────────


def decide_for_slot(
    slot: str, *, now: Optional[datetime] = None
) -> CirculationDecision:
    """
    Evaluate the circulatory state for `slot` and return a decision.

    Slots: "morning", "midday", "evening", "out_of_band"

    The returned CirculationDecision always lands in the circulation log
    (including NO_SEND decisions — quiet slots are themselves data).
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    decision_id = str(uuid.uuid4())
    recent_pairs = _recent_synthesis_archetype_pairs()

    # 1. Collect candidates
    surfacings = _get_surfacing_candidates(now=now_utc)
    contradictions = _parse_active_contradictions()

    # 2. Filter surfacings through broken-record dedup.
    #    When an entry is a Lived note (kind="lived") and carries an
    #    `archetype_hint`, prefer that over the stage-default archetype —
    #    Lived notes inherit the practice's archetype, which is a truer
    #    signal of voice than the stage timer.
    surfacing_candidates: list[tuple[dict, Archetype, float]] = []
    for s in surfacings:
        stage = s.get("stage_name", "fresh")
        archetype = _assign_surfacing_archetype(stage)
        # Lived notes and practice-progress entries both inherit the
        # practice's archetype, which is a truer signal of voice than the
        # stage timer.
        if s.get("kind") in ("lived", "practice_progress"):
            hint = s.get("archetype_hint")
            if hint:
                try:
                    archetype = Archetype(hint)
                except ValueError:
                    # Unknown archetype string — fall back to stage default.
                    pass
        key = (s.get("synthesis_title") or "", archetype.value)
        if key in recent_pairs:
            continue
        surfacing_candidates.append((s, archetype, _score_surfacing(s, slot)))

    # 3. Score contradictions (only for slots that welcome them).
    #    Each contradiction is scored individually now — recency and
    #    practice-link drive the differentiation. If a contradiction has an
    #    active practice descending from its archetype-home, the composer
    #    hears that practice's voice (Beatrice) instead of the primary
    #    archetype on the entry (Daimon).
    contradiction_candidates: list[tuple[dict, Archetype, float]] = []
    for c in contradictions:
        score = _score_contradiction(c, slot)
        if score <= 0.0:
            continue
        practice_arch = _practice_archetype_for_contradiction(c)
        arch_str = practice_arch or c.get("archetype") or Archetype.DAIMON.value
        try:
            archetype = Archetype(arch_str)
        except ValueError:
            archetype = Archetype.DAIMON
        contradiction_candidates.append((c, archetype, score))

    # 4. Choose best
    all_candidates: list[tuple[str, dict, Archetype, float]] = (
        [("surfacing", p, a, sc) for p, a, sc in surfacing_candidates]
        + [("contradiction", p, a, sc) for p, a, sc in contradiction_candidates]
    )

    if not all_candidates:
        decision = CirculationDecision(
            id=decision_id,
            slot=slot,
            send=False,
            channel=Channel.NO_SEND.value,
            archetype=None,
            source_kind="quiet",
            source_id=None,
            synthesis_title=None,
            synthesis_path=None,
            stage_name=None,
            score=0.0,
            reason=(
                f"NO_SEND. surfacings_ready={len(surfacings)} "
                f"surfacings_after_dedup={len(surfacing_candidates)} "
                f"active_contradictions={len(contradictions)} "
                f"slot={slot}"
            ),
            decided_at=now_utc.isoformat(),
        )
        _append_circulation_log(decision)
        log.info(f"[circulation] NO_SEND slot={slot}")
        return decision

    # Highest score wins; ties broken by surfacings over contradictions.
    all_candidates.sort(key=lambda x: (x[3], 0 if x[0] == "surfacing" else -1), reverse=True)
    kind, payload, archetype, score = all_candidates[0]

    # 5. Compose the decision record
    if kind == "surfacing":
        channel = Channel.TEXT  # default text for routine resurfacings
        # Differentiate synthesis vs lived vs practice-progress surfacings
        # in the circulation log so we can audit how often each voice gets
        # heard.
        payload_kind = payload.get("kind")
        if payload_kind == "lived":
            source_kind = "lived_surfacing"
        elif payload_kind == "practice_progress":
            source_kind = "practice_progress"
        else:
            source_kind = "surfacing"
        decision = CirculationDecision(
            id=decision_id,
            slot=slot,
            send=True,
            channel=channel.value,
            archetype=archetype.value,
            source_kind=source_kind,
            source_id=payload.get("entry_id"),
            synthesis_title=payload.get("synthesis_title"),
            synthesis_path=payload.get("synthesis_path"),
            stage_name=payload.get("stage_name"),
            score=score,
            reason=(
                f"{source_kind} stage={payload.get('stage_name')} "
                f"archetype={archetype.value} score={score:.2f} slot={slot}"
            ),
            decided_at=now_utc.isoformat(),
        )
        _append_circulation_log(decision)
        # Mark delivered so the Finalizer won't re-propose this stage
        try:
            from myalicia.skills.synthesis_finalizer import mark_surfacing_delivered
            mark_surfacing_delivered(payload["entry_id"], payload["stage_name"])
        except Exception as e:
            log.warning(f"Failed to mark surfacing delivered: {e}")
        log.info(
            f"[circulation] SEND slot={slot} kind=surfacing "
            f"stage={payload.get('stage_name')} archetype={archetype.value}"
        )
        return decision

    # Contradiction branch
    channel = Channel.VOICE if slot == "evening" else Channel.TEXT
    decision = CirculationDecision(
        id=decision_id,
        slot=slot,
        send=True,
        channel=channel.value,
        archetype=archetype.value,
        source_kind="contradiction",
        source_id=payload.get("title"),
        synthesis_title=None,
        synthesis_path=None,
        stage_name=None,
        score=score,
        reason=(
            f"Active contradiction '{(payload.get('title') or '')[:60]}' "
            f"archetype={archetype.value} score={score:.2f} slot={slot}"
        ),
        decided_at=now_utc.isoformat(),
    )
    _append_circulation_log(decision)
    log.info(
        f"[circulation] SEND slot={slot} kind=contradiction archetype={archetype.value}"
    )
    return decision


# ── Reaction hook (for future Layer 4 feedback) ────────────────────────────


def record_reaction(decision_id: str, reaction: str) -> None:
    """
    Called when the user reacts to a circulation-driven message (thumbs-up,
    emoji, reply). Reactions are stored on the log entry for future weight
    adjustment. Non-fatal on any error.
    """
    entries = _load_circulation_log()
    changed = False
    for e in entries:
        if e.get("id") == decision_id:
            e.setdefault("reactions", []).append(
                {"at": datetime.now(timezone.utc).isoformat(), "value": reaction}
            )
            changed = True
            break
    if changed:
        try:
            atomic_write_json(str(CIRCULATION_LOG_FILE), entries)
        except Exception as e:
            log.warning(f"Failed to record reaction: {e}")


# ── Invariants (consumed by CI test) ───────────────────────────────────────


def check_invariants() -> list[dict]:
    """
    Returns a list of invariant violations. Two kinds today:

      - same_synthesis_archetype_lt_7d: broken-record dynamic
      - log_corruption: a log entry missing required fields

    Dead-letter detection (a synthesis not surfaced in 30d) is not checked
    here — it requires enumerating the full synthesis corpus, which the
    Finalizer owns. That invariant lives in test_synthesis_finalizer_invariant
    when it lands in Phase B.
    """
    violations: list[dict] = []
    entries = _load_circulation_log()
    by_pair: dict[tuple[str, str], datetime] = {}

    for e in entries:
        if not e.get("send"):
            continue
        title = e.get("synthesis_title")
        archetype = e.get("archetype")
        if not title or not archetype:
            if e.get("source_kind") in ("surfacing", "lived_surfacing"):
                violations.append({
                    "kind": "log_corruption",
                    "id": e.get("id"),
                    "reason": "surfacing-decision missing title or archetype",
                })
            continue
        try:
            dt = datetime.fromisoformat(e["decided_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            violations.append({
                "kind": "log_corruption",
                "id": e.get("id"),
                "reason": "unparseable decided_at",
            })
            continue
        key = (title, archetype)
        prev = by_pair.get(key)
        if prev:
            gap_days = abs((dt - prev).total_seconds()) / 86400.0
            if 0 < gap_days < NO_SAME_SYNTHESIS_ARCHETYPE_DAYS:
                violations.append({
                    "kind": "same_synthesis_archetype_lt_7d",
                    "synthesis_title": title,
                    "archetype": archetype,
                    "gap_days": round(gap_days, 2),
                })
        by_pair[key] = dt

    return violations


# ── CLI (debug / dry-run) ──────────────────────────────────────────────────


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Circulation Composer (debug)")
    parser.add_argument("--slot", choices=["morning", "midday", "evening", "out_of_band"],
                        default="morning")
    parser.add_argument("--check", action="store_true",
                        help="Run invariant check and print violations")
    parser.add_argument("--show-log", action="store_true",
                        help="Print the last 20 circulation decisions")
    args = parser.parse_args()

    if args.check:
        violations = check_invariants()
        by_kind: dict[str, int] = {}
        for v in violations:
            by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
        print("Invariant check:")
        for k, n in by_kind.items():
            print(f"  {k}: {n}")
        print(f"  total violations: {len(violations)}")
        return

    if args.show_log:
        entries = _load_circulation_log()[-20:]
        for e in entries:
            send = "SEND" if e.get("send") else "NO_SEND"
            print(f"{e.get('decided_at')} [{e.get('slot'):>11}] {send:>7} "
                  f"{e.get('source_kind'):>13} {e.get('archetype') or '-':>9} "
                  f"stage={e.get('stage_name') or '-'}")
        return

    dec = decide_for_slot(args.slot)
    print(json.dumps(asdict(dec), indent=2))


if __name__ == "__main__":
    _main()
