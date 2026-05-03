#!/usr/bin/env python3
"""
Gap-driven research scheduler — Phase 12.2.

The the user-model (Phase 12.0) tracks learnings across 10 dimensions
(identity, knowledge, practice, relationships, work, voice, body, wealth,
creative, shadow). When a dimension goes silent (no learnings for >14
days), that's a gap — Alicia hasn't been hearing from the user on that
plane of life. Phase 12.2 closes the loop: the gap becomes the seed for
a targeted proactive question.

This module:
  1. Identifies thin dimensions (find_thin_dimensions from hector_model).
  2. Picks one that hasn't been asked-about in the last 7 days.
  3. Asks Haiku to compose a single warm question targeted at that
     dimension, in Alicia's voice.
  4. Records the ask so the rotation stays diverse.

Two integration points:
  * Scheduler (alicia.py 03:00 nightly) — `run_dimension_research_scan()`
    runs the scan, logs the chosen candidate; the question itself is
    composed lazily by proactive_messages so the model call is paid for
    exactly when it's used.
  * Midday rotation (proactive_messages.build_midday_message) — early
    branch, ~20%, calls `build_dimension_targeted_question()` and uses
    the rendered question as the message body.

Public API:
    pick_thin_dimension() -> str | None
    compose_dimension_question(dimension) -> str | None
    record_dimension_question_asked(dimension, question)
    recent_dimension_questions(within_days=7) -> list[dict]
    build_dimension_targeted_question() -> dict | None  # {dimension, question}
    run_dimension_research_scan() -> dict               # scheduler entry
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.dimension_research")

MEMORY_DIR = os.path.expanduser("~/alicia/memory")
DIMENSION_LOG_PATH = os.path.join(MEMORY_DIR, "dimension_questions_log.jsonl")

# Phase 12.4 — gap escalation. Scan history lets us detect when the same
# dimension stays thin across consecutive scans. After
# ESCALATE_AFTER_CONSECUTIVE thin scans (default 2 — i.e. ~48h of "still
# silent"), escalate from "ask the user a question" to "do a research_skill
# web pass". Don't re-research the same dim within ESCALATION_COOLDOWN_DAYS.
SCAN_HISTORY_PATH = os.path.join(MEMORY_DIR, "dimension_scan_history.jsonl")
ESCALATION_LOG_PATH = os.path.join(MEMORY_DIR, "dimension_escalation_log.jsonl")
ESCALATE_AFTER_CONSECUTIVE = 2
ESCALATION_COOLDOWN_DAYS = 30

# Don't ask about the same dimension within this window.
DIMENSION_COOLDOWN_DAYS = 7


# ── Pull-history storage ───────────────────────────────────────────────────


def record_dimension_question_asked(dimension: str, question: str) -> None:
    """Append an event to the dimension-question log."""
    if not dimension:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "dimension": dimension,
            "question": (question or "")[:600],
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(DIMENSION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_dimension_question_asked failed: {e}")


def recent_dimension_questions(within_days: int = DIMENSION_COOLDOWN_DAYS) -> list[dict]:
    """Return question events newer than `within_days`."""
    if not os.path.exists(DIMENSION_LOG_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(DIMENSION_LOG_PATH, "r", encoding="utf-8") as f:
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
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_dimension_questions failed: {e}")
    return out


# ── Dimension picker ──────────────────────────────────────────────────────


def pick_thin_dimension(
    *,
    cooldown_days: int = DIMENSION_COOLDOWN_DAYS,
    stale_after_days: int = 14,
) -> Optional[str]:
    """Choose the next thin dimension to ask about.

    Strategy:
      1. Get find_thin_dimensions (no learnings in last `stale_after_days`).
      2. Filter out any dimension that's been asked about in the last
         `cooldown_days`.
      3. Return the first remaining (find_thin_dimensions preserves the
         canonical DIMENSIONS order — identity → knowledge → ... → shadow,
         which works as a stable rotation).

    Returns None when:
      - hector_model isn't importable
      - no dimensions are thin (everything has recent learnings)
      - all thin dimensions are on cooldown
    """
    try:
        from myalicia.skills.hector_model import find_thin_dimensions
    except Exception as e:
        log.debug(f"pick_thin_dimension: import failed: {e}")
        return None

    try:
        thin = find_thin_dimensions(stale_after_days=stale_after_days)
    except Exception as e:
        log.debug(f"find_thin_dimensions failed: {e}")
        return None

    if not thin:
        return None

    recently_asked = {
        e["dimension"] for e in recent_dimension_questions(within_days=cooldown_days)
        if e.get("dimension")
    }
    eligible = [d for d in thin if d not in recently_asked]
    if not eligible:
        return None
    return eligible[0]


# ── Haiku composer ────────────────────────────────────────────────────────


# Per-dimension framing hints — what each dimension MEANS in the user's life.
# Keeps Haiku grounded so the question lands instead of abstracting.
_DIMENSION_FRAMES = {
    "identity":      "who he is becoming, the deep self, sense of selfhood",
    "knowledge":     "what he's reading, learning, integrating intellectually",
    "practice":      "the daily practices and rituals that shape his life",
    "relationships": "his wife, family, friendships, the bonds that hold him",
    "work":          "Amazon, his work output, leadership, professional craft",
    "voice":         "his writing, essays, public expression, the work he publishes",
    "body":          "physical practice, energy, sleep, movement, embodiment",
    "wealth":        "money, security, financial trajectory, abundance",
    "creative":      "his art, photography, design, generative play",
    "shadow":        "what he's avoiding, suppressing, or refusing to face",
}


_DIMENSION_QUESTION_SYSTEM = (
    f"You are Alicia. You're sending {USER_NAME} a single warm question because "
    "you haven't heard from him on a particular dimension of his life "
    "for a while. The question should feel intimate, present, and "
    "specific — not survey-like. NOT 'how is your X going?' style. "
    "Better: a question that names the absence and offers a real opening.\n\n"
    "Write 1-3 short lines (20-60 words total). No headers, no labels, "
    "no markdown beyond a single italic phrase if it lands. End on the "
    "question — do not summarise."
)


def compose_dimension_question(dimension: str) -> Optional[str]:
    """Ask Haiku to compose a single warm question targeted at this dimension.

    Returns the rendered message text, or None on failure."""
    if not dimension:
        return None
    frame = _DIMENSION_FRAMES.get(dimension, dimension)
    user_prompt = (
        f"Dimension that's gone quiet: **{dimension}**\n"
        f"What this dimension covers: {frame}\n\n"
        f"Write the message Alicia sends {USER_NAME} to invite him back into "
        f"this part of his life."
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=180,
            system=_DIMENSION_QUESTION_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = ""
        if resp.content and hasattr(resp.content[0], "text"):
            raw = (resp.content[0].text or "").strip()
        # Strip wrapping quotes if Haiku wrapped the whole output
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1].strip()
        return raw or None
    except Exception as e:
        log.warning(f"compose_dimension_question failed: {e}")
        return None


# ── Main entry points ────────────────────────────────────────────────────


def build_dimension_targeted_question() -> Optional[dict]:
    """Build a complete dimension-targeted question, ready for Telegram.

    Returns dict {"dimension", "question", "message"} where `message` is
    the Telegram-flavored body, or None when no eligible dimension exists.
    Side effect: on success, records the ask so cooldown applies next time.
    """
    dim = pick_thin_dimension()
    if not dim:
        log.debug("build_dimension_targeted_question: no eligible thin dimension")
        return None
    body = compose_dimension_question(dim)
    if not body:
        return None
    # Lightweight banner so the format is identifiable
    message = f"🪞 _checking in on a part of you I haven't heard from_\n\n{body}"
    record_dimension_question_asked(dim, body)
    return {"dimension": dim, "question": body, "message": message}


# ── Phase 12.4 — Gap escalation to research ────────────────────────────────


# Per-dimension research-topic templates. The dimension name alone is
# too abstract; these turn it into a question Alicia would actually
# benefit from researching for the user.
_ESCALATION_TOPICS = {
    "identity":      "deep self vs surface self — practices for sustained inner clarity",
    "knowledge":     "intellectual depth maintenance — staying sharp without burnout",
    "practice":      "daily ritual design — habit architecture for high-output knowledge workers",
    "relationships": "long-marriage repair patterns — what couples in their 40s do that lasts",
    "work":          "individual contributor leverage at large tech companies — recent thinking",
    "voice":         "writing rhythm for a knowledge worker who publishes irregularly",
    "body":          "men in their 40s — sustainable energy + recovery practices",
    "wealth":        "tech compensation strategy mid-2020s — RSUs, taxes, and runway",
    "creative":      "generative practice maintenance — keeping the make-thing alive",
    "shadow":        "shadow work for type-A men — what therapists actually recommend",
}


def record_dimension_scan(thin_dims: list[str], candidate: Optional[str]) -> None:
    """Append a scan record to the history jsonl."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "thin_dimensions": list(thin_dims or []),
            "candidate": candidate,
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(SCAN_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_dimension_scan failed: {e}")


def recent_dimension_scans(within_days: int = 7) -> list[dict]:
    """Return scan history entries newer than `within_days`, oldest first."""
    if not os.path.exists(SCAN_HISTORY_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(SCAN_HISTORY_PATH, "r", encoding="utf-8") as f:
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
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_dimension_scans failed: {e}")
    out.sort(key=lambda x: x.get("ts", ""))
    return out


def get_persistent_thin_dimensions(
    *, min_consecutive_scans: int = ESCALATE_AFTER_CONSECUTIVE,
) -> list[str]:
    """Return dimensions that have been thin in the last
    `min_consecutive_scans` scans.

    Reads scan history in chronological order; any dimension present in
    every one of the last N scans qualifies. With min=2, this means the
    gap has persisted across two 03:00 cycles (~48h)."""
    scans = recent_dimension_scans(within_days=14)
    if len(scans) < min_consecutive_scans:
        return []
    last_n = scans[-min_consecutive_scans:]
    persistent: set[str] = set(last_n[0].get("thin_dimensions") or [])
    for s in last_n[1:]:
        persistent &= set(s.get("thin_dimensions") or [])
    return sorted(persistent)


def record_dimension_escalation(
    dimension: str, topic: str, research_path: Optional[str], status: str,
) -> None:
    """Append an escalation event to the log."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "dimension": dimension,
            "topic": topic[:300],
            "research_path": research_path or "",
            "status": status,
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(ESCALATION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_dimension_escalation failed: {e}")


def recent_escalations(within_days: int = ESCALATION_COOLDOWN_DAYS) -> list[dict]:
    """Return escalation events newer than `within_days`."""
    if not os.path.exists(ESCALATION_LOG_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(ESCALATION_LOG_PATH, "r", encoding="utf-8") as f:
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
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_escalations failed: {e}")
    return out


def pick_escalation_target() -> Optional[str]:
    """Return a dimension that's been persistently thin AND not escalated
    recently, or None when nothing qualifies."""
    persistent = get_persistent_thin_dimensions()
    if not persistent:
        return None
    recent_dims = {
        e.get("dimension") for e in recent_escalations(
            within_days=ESCALATION_COOLDOWN_DAYS
        )
    }
    for d in persistent:
        if d not in recent_dims:
            return d
    return None


def escalate_to_research(dimension: str) -> Optional[str]:
    """Trigger a research_skill brief on the dimension's topic. Returns
    the path of the written research note on success, or None on any
    failure (research_skill error, no topic mapping, etc.).

    Called by run_dimension_research_scan when a gap has persisted past
    ESCALATE_AFTER_CONSECUTIVE scans. Cheap: ~10s of Sonnet time, writes
    to the vault. The output is a research note, not a synthesis — it
    seeds the user's vault with material the gap suggests would help.
    """
    if not dimension:
        return None
    topic = _ESCALATION_TOPICS.get(dimension)
    if not topic:
        log.debug(f"escalate_to_research: no topic mapping for {dimension!r}")
        return None
    try:
        from myalicia.skills.research_skill import research_brief
    except Exception as e:
        log.warning(f"escalate_to_research: research_skill import failed: {e}")
        record_dimension_escalation(dimension, topic, None, "import_failed")
        return None
    try:
        text, filepath = research_brief(topic)
        if not filepath:
            record_dimension_escalation(dimension, topic, None, "no_filepath")
            return None
        record_dimension_escalation(dimension, topic, filepath, "ok")
        log.info(
            f"dimension escalation → research: dim={dimension} "
            f"topic={topic[:60]!r} → {filepath}"
        )
        return filepath
    except Exception as e:
        log.warning(f"escalate_to_research: research_brief failed: {e}")
        record_dimension_escalation(dimension, topic, None, f"error: {e}")
        return None


def run_dimension_research_scan() -> dict:
    """Scheduled nightly: scan for thin dimensions and log the candidate
    that proactive_messages would target tomorrow.

    Cheap baseline — no Sonnet/Haiku call. Just the gap detection. Lets
    ops see in the logs which dimension is currently in deficit; the
    actual question is rendered lazily when midday picks it up.

    Phase 12.4 — also records the scan in scan-history and, when a gap
    has persisted across `ESCALATE_AFTER_CONSECUTIVE` scans (and isn't
    on the 30-day escalation cooldown), triggers a research_skill brief
    on the dimension's mapped topic. The research note lands in the
    vault under Knowledge Vault/Research/ and is treated as a synthesis
    seed by future passes.

    Returns: {"thin_dimensions": [...], "next_candidate": str|None,
              "all_on_cooldown": bool, "escalated_dim": str|None,
              "escalation_path": str|None}
    """
    try:
        from myalicia.skills.hector_model import find_thin_dimensions
        thin = find_thin_dimensions(stale_after_days=14)
    except Exception as e:
        log.warning(f"run_dimension_research_scan: thin lookup failed: {e}")
        return {
            "thin_dimensions": [], "next_candidate": None,
            "all_on_cooldown": False, "error": str(e),
            "escalated_dim": None, "escalation_path": None,
        }

    candidate = pick_thin_dimension()
    on_cooldown = bool(thin) and candidate is None

    # Phase 12.4 — record the scan BEFORE checking for persistent gaps so
    # this scan counts toward the consecutive-scan threshold.
    record_dimension_scan(thin, candidate)

    escalated_dim = None
    escalation_path = None
    try:
        target = pick_escalation_target()
        if target:
            escalated_dim = target
            escalation_path = escalate_to_research(target)
    except Exception as e:
        log.debug(f"escalation step skipped: {e}")

    log.info(
        f"dimension_research_scan: thin={thin} "
        f"next_candidate={candidate} on_cooldown={on_cooldown} "
        f"escalated={escalated_dim} path={escalation_path}"
    )
    return {
        "thin_dimensions": thin,
        "next_candidate": candidate,
        "all_on_cooldown": on_cooldown,
        "escalated_dim": escalated_dim,
        "escalation_path": escalation_path,
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(run_dimension_research_scan(), indent=2))
