#!/usr/bin/env python3
"""
Smart multi-channel amplification — Phase 13.3 + 15.1 (recalibration).

Phase 13.1 introduced multi-channel moments: when a composer decision
scores high enough and has an archetype, a drawing fires in the same
archetype right after the text. The threshold worked but it's a blunt
instrument — a high-scoring contradiction prompt that's verbal in
nature ('what would you have to admit…') doesn't always WANT to be a
drawing.

Phase 13.3 replaced the score-only gate with a three-tier decider.
Phase 15.1 recalibrates after dogfood — the original tuning was TOO
conservative. the user's stated intent was that drawings be a co-equal
channel firing FREELY when an idea wants visual amplification, not a
rare event. The judge's bias-toward-NO was muting the system.

The new tuning:

  1. **Fast path** — score ≥ SCORE_FAST_PATH (2.0, was 3.0): most
     composer decisions reach this; fast-path is the common case.
  2. **Skip path** — score < SCORE_FLOOR (1.5), no archetype, or
     saturation guard tripped (≥SATURATION_24H drawings in 24h, was 3
     now 5): no drawing.
  3. **Judge path** — narrow band (1.5 ≤ score < 2.0): one Haiku call.
     Phase 15.1: judge now BIASES TOWARD YES — only refuses when the
     text is truly conversational (a question, a list, a reference).

Public API:
    decide_drawing_amplification(*, text, archetype, source_kind, score,
                                 now=None) -> dict
    record_multi_channel_decision(decision_dict)
    recent_multi_channel_decisions(within_hours=24) -> list[dict]
    drawings_fired_recently(within_hours=24) -> int

Tunables (Phase 15.1):
    SCORE_FAST_PATH = 2.0   (was 3.0)
    SCORE_FLOOR = 1.5
    SATURATION_24H = 5      (was 3)
    JUDGE_MODEL = "claude-haiku-4-5-20251001"
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.multi_channel")

MEMORY_DIR = str(MEMORY_DIR)
DECISIONS_LOG_PATH = os.path.join(MEMORY_DIR, "multi_channel_decisions.jsonl")

# Tunables (Phase 15.1 recalibration)
SCORE_FAST_PATH = 2.0   # at or above: fire drawing without judge (was 3.0)
SCORE_FLOOR = 1.5       # below: no drawing, no judge
SATURATION_24H = 5      # max drawings per 24h regardless of judge (was 3)
JUDGE_MODEL = "claude-haiku-4-5-20251001"

# Source kinds eligible for amplification at all (matches Phase 13.1 set).
ELIGIBLE_SOURCE_KINDS = {"surfacing", "lived_surfacing", "contradiction"}


# ── Decision log ────────────────────────────────────────────────────────────


def record_multi_channel_decision(decision: dict) -> None:
    """Append a decision dict to the multi-channel decisions log."""
    if not decision:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = dict(decision)
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(DECISIONS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_multi_channel_decision failed: {e}")


def recent_multi_channel_decisions(within_hours: int = 24) -> list[dict]:
    """Return decision-log entries newer than `within_hours`."""
    if not os.path.exists(DECISIONS_LOG_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    out: list[dict] = []
    try:
        with open(DECISIONS_LOG_PATH, "r", encoding="utf-8") as f:
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
        log.debug(f"recent_multi_channel_decisions failed: {e}")
    return out


def drawings_fired_recently(within_hours: int = 24) -> int:
    """Count drawing-firings (drawing=True) in the last `within_hours`.

    Used for saturation guard. Reads the multi-channel decisions log
    rather than the drawing log so it counts firings caused by THIS
    decider — manual /draw calls don't add to the saturation count."""
    return sum(
        1 for e in recent_multi_channel_decisions(within_hours)
        if e.get("drawing") is True
    )


# ── Judge prompt ───────────────────────────────────────────────────────────


_JUDGE_SYSTEM = (
    f"You decide whether an Alicia text message {USER_NAME} is about to "
    "receive should also be accompanied by a drawing in the same "
    f"archetype. The drawing fires right after the text. {USER_NAME} "
    "explicitly WANTS drawings to be a co-equal channel — they're a "
    "form of presence, not a rare reward. When in doubt, draw.\n\n"
    "You will receive: the rendered text Alicia is sending, the "
    "archetype, the source kind, and a numeric score. Reply with "
    "EXACTLY one line of JSON:\n"
    "{\"draw\": true|false, \"reason\": \"<one short sentence>\"}\n\n"
    "BIAS TOWARD YES. Refuse ONLY when the text is purely "
    "transactional — a list of items, a file path, a code block, a "
    "URL, or a literal yes/no question with no atmosphere "
    "(\"did you log today?\"). Anything with mood, metaphor, "
    "imagery, tension, or even a quiet question with feeling — "
    "draw. The drawing doesn't have to ILLUSTRATE the text; it can "
    "extend it, hold the same weather in another medium."
)


def _hash_text(s: str) -> str:
    """Short stable hash for text identity in the log."""
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _ask_judge(text: str, archetype: str, source_kind: str, score: float) -> tuple[bool, str]:
    """Run the Haiku judge. Returns (decision_bool, rationale_str).
    On any error, defaults to (False, '<error>') — fail closed."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        text_excerpt = text.strip()
        if len(text_excerpt) > 800:
            text_excerpt = text_excerpt[:799].rstrip() + "…"
        user_prompt = (
            f"text: {text_excerpt}\n"
            f"archetype: {archetype}\n"
            f"source_kind: {source_kind}\n"
            f"score: {score:.2f}\n\n"
            "Respond with the JSON line."
        )
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=120,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return False, "judge_no_content"
        raw = (resp.content[0].text or "").strip()
        # Best-effort JSON extraction — handle Haiku occasionally adding prose
        m = re.search(r"\{[^{}]*\"draw\"[^{}]*\}", raw, re.DOTALL)
        if not m:
            return False, f"judge_no_json: {raw[:100]}"
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            return False, f"judge_bad_json: {raw[:100]}"
        draw = bool(parsed.get("draw"))
        reason = str(parsed.get("reason", "")).strip()[:160]
        return draw, reason or ("yes" if draw else "no")
    except Exception as e:
        log.warning(f"_ask_judge failed: {e}")
        return False, f"judge_error: {e}"


# ── Main entry ─────────────────────────────────────────────────────────────


def decide_drawing_amplification(
    *,
    text: str,
    archetype: Optional[str],
    source_kind: Optional[str],
    score: float,
    decision_id: Optional[str] = None,
    use_judge: bool = True,
) -> dict:
    """Decide whether to amplify this text with a drawing. Logs the decision.

    Returns a dict:
        {
            "drawing": bool,
            "path": "fast_high_conviction" | "below_floor" |
                    "no_archetype" | "ineligible_source" |
                    "saturation_guard" | "judge_yes" | "judge_no" |
                    "judge_disabled",
            "rationale": str,
            "score": float,
            "archetype": str|None,
            "source_kind": str|None,
            "text_hash": str,
            "decision_id": str|None,
        }
    """
    text_hash = _hash_text(text or "")
    base = {
        "score": float(score or 0.0),
        "archetype": archetype,
        "source_kind": source_kind,
        "text_hash": text_hash,
        "decision_id": decision_id,
    }

    # Hard preconditions
    if not archetype:
        out = {**base, "drawing": False, "path": "no_archetype",
               "rationale": "archetype is None"}
        record_multi_channel_decision(out)
        return out
    if source_kind not in ELIGIBLE_SOURCE_KINDS:
        out = {**base, "drawing": False, "path": "ineligible_source",
               "rationale": f"source_kind={source_kind} not in eligible set"}
        record_multi_channel_decision(out)
        return out
    if (score or 0.0) < SCORE_FLOOR:
        out = {**base, "drawing": False, "path": "below_floor",
               "rationale": f"score {score:.2f} < floor {SCORE_FLOOR}"}
        record_multi_channel_decision(out)
        return out

    # Saturation guard — count drawings fired by THIS decider in last 24h
    fired = drawings_fired_recently(within_hours=24)
    if fired >= SATURATION_24H:
        out = {**base, "drawing": False, "path": "saturation_guard",
               "rationale": f"already {fired} drawings in last 24h "
                            f"(cap {SATURATION_24H})"}
        record_multi_channel_decision(out)
        return out

    # Fast path — score is unambiguous
    if (score or 0.0) >= SCORE_FAST_PATH:
        out = {**base, "drawing": True, "path": "fast_high_conviction",
               "rationale": f"score {score:.2f} ≥ {SCORE_FAST_PATH}"}
        record_multi_channel_decision(out)
        return out

    # Borderline — judge or skip
    if not use_judge:
        out = {**base, "drawing": False, "path": "judge_disabled",
               "rationale": "use_judge=False, defaulting to no"}
        record_multi_channel_decision(out)
        return out

    draw, reason = _ask_judge(text or "", archetype, source_kind or "", float(score or 0.0))
    out = {**base,
           "drawing": draw,
           "path": "judge_yes" if draw else "judge_no",
           "rationale": reason}
    record_multi_channel_decision(out)
    return out


# ════════════════════════════════════════════════════════════════════════
# Phase 13.7 — Smart voice decider
# ════════════════════════════════════════════════════════════════════════
#
# Voice has been the always-on second channel for proactive sends since
# the early phases. But some text reads better than it sounds: lists,
# code blocks, URLs, headers, and very long paragraphs all degrade in
# TTS. This module mirrors decide_drawing_amplification with three tiers
# tuned for the inverse default — voice is ON unless the text is
# prose-shaped to be read silently.
#
# Tunables (separate constants so we can tune voice and drawing
# independently as we accumulate data):
#   VOICE_SATURATION_24H = 8 (much higher than drawings — voice is the
#     primary multi-channel default)
#   VOICE_LONG_THRESHOLD = 800 (chars; above this, default to text-only)
#
# Heuristic skip patterns (any one trips text-only without judge):
#   - 2+ markdown list items
#   - any markdown heading line (## )
#   - any code block fence (```)
#   - any URL (http(s)://)
#   - any markdown table separator (|---|)
#
# Wiring: alicia.py:send_morning_message / send_midday_message /
# send_evening_message wrap their text_to_voice call with a check.

VOICE_SATURATION_24H = 8
VOICE_LONG_THRESHOLD = 800


_VOICE_LIST_RE = re.compile(r"(?m)^\s*[\-\*•]\s+\S")
_VOICE_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")
_VOICE_CODE_RE = re.compile(r"```")
_VOICE_URL_RE = re.compile(r"https?://\S+")
_VOICE_TABLE_RE = re.compile(r"(?m)^\s*\|[-:\s|]+\|\s*$")


def _voice_skip_patterns_present(text: str) -> Optional[str]:
    """Return the pattern name that triggers text-only, or None.

    Pure heuristic — no model call. Catches 90%+ of cases that obviously
    sound bad in TTS. Anything that passes lands in the judge tier."""
    if not text:
        return None
    if len(text) > VOICE_LONG_THRESHOLD:
        return "long_text"
    if _VOICE_HEADING_RE.search(text):
        return "markdown_heading"
    if _VOICE_CODE_RE.search(text):
        return "code_block"
    if _VOICE_URL_RE.search(text):
        return "url_present"
    if _VOICE_TABLE_RE.search(text):
        return "markdown_table"
    # 2+ list items in a row (one bullet is a fine emphasis device)
    if len(_VOICE_LIST_RE.findall(text)) >= 2:
        return "markdown_list"
    return None


def voice_fired_recently(within_hours: int = 24) -> int:
    """Count voice firings in the last `within_hours`. Reads the same
    multi_channel_decisions log; voice entries have channel='voice'."""
    return sum(
        1 for e in recent_multi_channel_decisions(within_hours)
        if e.get("channel") == "voice" and e.get("voice") is True
    )


_VOICE_JUDGE_SYSTEM = (
    f"You decide whether a short Telegram text {USER_NAME} is about to receive "
    "should ALSO be spoken to him as voice. Voice WORKS for: warm "
    "openings, intimate questions, single-sentence aphorisms, emotional "
    "arrivals. Voice is BAD for: enumerated lists, references to files "
    "or paths, anything that requires reading and re-reading.\n\n"
    "Reply with EXACTLY one line of JSON:\n"
    "{\"speak\": true|false, \"reason\": \"<one short sentence>\"}\n\n"
    "Bias toward YES — voice is the default. Only refuse when the text "
    "would clearly degrade in audio."
)


def _ask_voice_judge(text: str, slot: str) -> tuple[bool, str]:
    """Run the Haiku voice judge. Returns (decision_bool, rationale_str).
    On any error, defaults to (True, '<error>') — fail OPEN since voice
    is the historical default and skipping it silently degrades UX."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        text_excerpt = text.strip()
        if len(text_excerpt) > 800:
            text_excerpt = text_excerpt[:799].rstrip() + "…"
        user_prompt = (
            f"slot: {slot}\n"
            f"text: {text_excerpt}\n\n"
            "Respond with the JSON line."
        )
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=120,
            system=_VOICE_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return True, "judge_no_content_fail_open"
        raw = (resp.content[0].text or "").strip()
        m = re.search(r"\{[^{}]*\"speak\"[^{}]*\}", raw, re.DOTALL)
        if not m:
            return True, f"judge_no_json_fail_open: {raw[:80]}"
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            return True, f"judge_bad_json_fail_open: {raw[:80]}"
        speak = bool(parsed.get("speak"))
        reason = str(parsed.get("reason", "")).strip()[:160]
        return speak, reason or ("yes" if speak else "no")
    except Exception as e:
        log.warning(f"_ask_voice_judge failed (fail open to YES): {e}")
        return True, f"judge_error_fail_open: {e}"


def decide_voice_amplification(
    *,
    text: str,
    slot: str = "midday",
    use_judge: bool = True,
) -> dict:
    """Decide whether to fire voice for this text. Logs every decision.

    Returns:
        {
            "voice": bool,
            "channel": "voice",
            "path": "fast_voice_default" | "skip_<reason>" |
                    "saturation_guard" | "judge_yes" | "judge_no" |
                    "judge_disabled",
            "rationale": str,
            "slot": str,
            "text_hash": str,
            "text_len": int,
        }
    """
    text_hash = _hash_text(text or "")
    base = {
        "channel": "voice",
        "slot": slot,
        "text_hash": text_hash,
        "text_len": len(text or ""),
    }

    # Saturation
    fired = voice_fired_recently(within_hours=24)
    if fired >= VOICE_SATURATION_24H:
        out = {**base, "voice": False, "path": "saturation_guard",
               "rationale": f"already {fired} voice messages in last 24h "
                            f"(cap {VOICE_SATURATION_24H})"}
        record_multi_channel_decision(out)
        return out

    # Heuristic skip patterns
    skip = _voice_skip_patterns_present(text or "")
    if skip:
        out = {**base, "voice": False, "path": f"skip_{skip}",
               "rationale": f"heuristic skip: {skip}"}
        record_multi_channel_decision(out)
        return out

    # Short, clean text → fast voice path
    if len(text or "") <= 350:
        out = {**base, "voice": True, "path": "fast_voice_default",
               "rationale": f"short clean text ({len(text or '')} chars)"}
        record_multi_channel_decision(out)
        return out

    # Borderline — judge or fall through to YES (voice is the default)
    if not use_judge:
        out = {**base, "voice": True, "path": "judge_disabled",
               "rationale": "use_judge=False, defaulting to YES (voice is default)"}
        record_multi_channel_decision(out)
        return out

    speak, reason = _ask_voice_judge(text or "", slot)
    out = {**base,
           "voice": speak,
           "path": "judge_yes" if speak else "judge_no",
           "rationale": reason}
    record_multi_channel_decision(out)
    return out


# ════════════════════════════════════════════════════════════════════════
# Phase 13.12 — Cross-channel coherence (voice ↔ drawing)
# ════════════════════════════════════════════════════════════════════════
#
# Phase 13.2 made the drawing's caption echo the text. This module closes
# the bidirectional loop: when both voice and drawing are about to fire
# in the same moment, the VOICE script can ground the listener in the
# visual that's about to arrive ("...you'll see the white line refusing
# to break — that's the refusal"). Same archetype, two outputs,
# mutually aware.
#
# Implementation: cheap Haiku call that previews what the drawing's
# caption will be, then composes a 5-15 word voice tail that points to
# it. Returns (augmented_text, tail) or (text, None) when nothing useful
# emerges. The drawing-render itself happens asynchronously as before.

_VOICE_TAIL_SYSTEM = (
    f"You write a SHORT voice tail (5-15 words) that grounds {USER_NAME} in "
    "a drawing he's about to receive. The tail comes at the end of the "
    "spoken message. Reference the visual concretely without naming it "
    "as a 'drawing' or 'image'. Examples:\n"
    "  '...and you'll see the white line in the middle.'\n"
    "  '...look for the way the dark folds inward.'\n"
    "  '...the shape coming through is the refusal itself.'\n\n"
    "TONE: intimate, present, archetype-appropriate. NO meta-language "
    "('I'm sending you a drawing'). NO greetings. End on a period.\n\n"
    "OUTPUT: just the tail phrase, no quotes, no labels."
)


def compose_voice_with_drawing_tail(
    *, text: str, archetype: str,
) -> tuple[str, Optional[str]]:
    """Phase 13.12 — augment voice text with a drawing-tail when both
    channels are about to fire in the same moment.

    Strategy:
      1. Use bridge_text_to_drawing_caption to preview what the drawing's
         caption will be (cheap, already exists).
      2. Ask Haiku to compose a 5-15 word voice tail that grounds the
         listener in that visual.
      3. Return (augmented_text, tail) on success, (text, None) when the
         preview or composition fails.

    Caller is responsible for deciding to invoke this — this function
    assumes both decide_voice_amplification and decide_drawing_amplification
    returned YES for the same content."""
    if not text or not archetype:
        return text, None
    # Step 1: preview the drawing's caption
    try:
        from myalicia.skills.drawing_skill import bridge_text_to_drawing_caption
        caption = bridge_text_to_drawing_caption(
            text=text, archetype=archetype, original_caption="",
        )
    except Exception as e:
        log.debug(f"voice tail caption preview failed: {e}")
        return text, None
    if not caption:
        return text, None

    # Step 2: compose the voice tail
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        user_prompt = (
            f"archetype: {archetype}\n"
            f"text being spoken: {text.strip()[:600]}\n"
            f"drawing caption (what {USER_NAME} will see): {caption}\n\n"
            "Write the voice tail."
        )
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=80,
            system=_VOICE_TAIL_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return text, None
        tail = (resp.content[0].text or "").strip()
        # Strip surrounding quotes
        if (tail.startswith('"') and tail.endswith('"')) or (
            tail.startswith("'") and tail.endswith("'")
        ):
            tail = tail[1:-1].strip()
        if not tail:
            return text, None
        # Cap length defensively (15 words max)
        words = tail.split()
        if len(words) > 18:
            tail = " ".join(words[:18])
        # Augment with paragraph break for natural pause in TTS
        augmented = f"{text.rstrip()}\n\n{tail}"
        # Log the coherent moment for /multichannel observability
        record_multi_channel_decision({
            "channel": "coherent_moment", "voice": True, "drawing": True,
            "path": "voice_drawing_tail", "rationale": tail[:160],
            "archetype": archetype, "text_hash": _hash_text(text),
        })
        return augmented, tail
    except Exception as e:
        log.warning(f"compose_voice_with_drawing_tail failed: {e}")
        return text, None


if __name__ == "__main__":
    import json as _json
    sample = decide_drawing_amplification(
        text="the weight you carry that no one sees",
        archetype="daimon",
        source_kind="contradiction",
        score=2.4,
        use_judge=False,
    )
    print("DRAWING:", _json.dumps(sample, indent=2))
    sample_v = decide_voice_amplification(
        text="what's been quiet today that you want to make room for tomorrow?",
        slot="evening",
        use_judge=False,
    )
    print("VOICE:", _json.dumps(sample_v, indent=2))
