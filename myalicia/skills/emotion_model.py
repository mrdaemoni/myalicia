"""
Gap 2 Phase C — Full speech-emotion classification (background thread).

Layers affective tags (neu / hap / sad / ang) on top of the Phase B
prosody layer. Runs STRICTLY in the background — never gates, delays,
or modifies an in-flight reply. The signal accumulates in
emotion_log.jsonl and feeds into future archetype-effectiveness
analysis (Phase D's loop).

Architecture
------------
    handle_voice
        │
        ├─ reply sent to user                      ← user latency path
        │
        └─ threading.Thread(_run_emotion_async, daemon=True).start()
               │
               ├─ classify_emotion(ogg_path)
               │     • lazy-load transformers pipeline (first call
               │       downloads superb/wav2vec2-base-superb-er)
               │     • audio → 16k mono → pipeline
               │     • hard timeout so bad audio can't wedge forever
               │     • returns {label, score, all_scores, latency_ms}
               │
               └─ record_emotion_entry(...)
                     • append to memory/emotion_log.jsonl
                     • captures: ts, message_id, label, score, all_scores,
                                 prosody_tags, voice_archetype, latency

Failure posture
---------------
This module MUST fail silent. If transformers is missing, if the model
download fails, if pyin crashes on strange audio — none of that must
ever touch the user. classify_emotion returns None and we log at debug
level. record_emotion_entry is a best-effort append; IOError is swallowed.

Why no in-flight use
--------------------
The pipeline call is ~1–3 s on CPU. That's bad UX on top of TTS + STT
+ LLM. Phase D's effectiveness loop already closes the learning gap
through reactions; we feed this signal into the same loop instead of
blocking the reply on it.

Model
-----
Default: superb/wav2vec2-base-superb-er (4-class IEMOCAP emotion).
Override via EMOTION_MODEL_NAME env var if a different HF model is
preferred. Cached in the standard HF_HUB_CACHE (~/.cache/huggingface).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger(__name__)

MEMORY_DIR = str(MEMORY_DIR)
EMOTION_LOG_PATH = os.path.join(MEMORY_DIR, "emotion_log.jsonl")

DEFAULT_MODEL = os.environ.get(
    "EMOTION_MODEL_NAME", "superb/wav2vec2-base-superb-er"
)
PIPELINE_TIMEOUT_SEC = 15.0    # hard ceiling on a single classification
MIN_AUDIO_SEC = 1.0            # wav2vec2 needs a little content
TARGET_SR = 16_000             # what the superb model expects

# Module-level cache + lock. The transformers pipeline is thread-safe for
# inference but loading it is not — synchronize the first-time init.
_pipeline: Any = None
_pipeline_load_failed: bool = False
_pipeline_lock = Lock()
_log_write_lock = Lock()

# If a previous load already failed we don't want every voice note to
# re-try (and re-log) the failure. Stamp the time so we can retry
# gracefully after a while — but by default we just give up.
_last_load_attempt_ts: float = 0.0
LOAD_RETRY_COOLDOWN_SEC = 3600.0  # retry at most once per hour


# ─── Lazy pipeline loader ────────────────────────────────────────────
def _ensure_pipeline() -> Optional[Any]:
    """Load (or return cached) HF audio-classification pipeline.

    Returns None if deps are missing or load fails. Idempotent and
    thread-safe.
    """
    global _pipeline, _pipeline_load_failed, _last_load_attempt_ts

    if _pipeline is not None:
        return _pipeline

    # Cooldown gate — don't hammer a broken install
    now = time.monotonic()
    if _pipeline_load_failed:
        if (now - _last_load_attempt_ts) < LOAD_RETRY_COOLDOWN_SEC:
            return None
        # Reset and try again
        _pipeline_load_failed = False

    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        _last_load_attempt_ts = now
        try:
            from transformers import pipeline
        except Exception as e:
            logger.info(f"emotion_model: transformers unavailable ({e}); disabled")
            _pipeline_load_failed = True
            return None

        try:
            logger.info(
                f"emotion_model: loading {DEFAULT_MODEL} "
                "(first call may download ~370MB)"
            )
            _pipeline = pipeline(
                "audio-classification",
                model=DEFAULT_MODEL,
                top_k=None,
            )
            logger.info("emotion_model: pipeline ready")
        except Exception as e:
            logger.warning(f"emotion_model: pipeline load failed: {e}")
            _pipeline_load_failed = True
            _pipeline = None
            return None

        return _pipeline


# ─── Classification ──────────────────────────────────────────────────
def classify_emotion(audio_path: str, duration: float = 0.0) -> Optional[Dict[str, Any]]:
    """Classify an audio file's emotion. Returns dict or None.

    Return shape:
        {
          "label": "hap"|"sad"|"ang"|"neu"|...,
          "score": float,               # top-1 softmax
          "all_scores": {label: float}, # full distribution
          "latency_ms": int,
          "model": str,
        }

    None is returned for: missing file, too-short audio, missing deps,
    pipeline load failure, or pipeline runtime error.
    """
    if not audio_path or not os.path.exists(audio_path):
        return None
    if duration and duration < MIN_AUDIO_SEC:
        return None

    pl = _ensure_pipeline()
    if pl is None:
        return None

    # Resample to 16k mono — wav2vec2-base-superb-er expects it. librosa
    # is already a dep (Phase B), so we reuse it rather than pulling
    # torchaudio directly.
    try:
        import librosa  # type: ignore
        y, sr = librosa.load(audio_path, sr=TARGET_SR, mono=True)
    except Exception as e:
        logger.debug(f"emotion_model: audio load failed: {e}")
        return None

    if len(y) < int(TARGET_SR * MIN_AUDIO_SEC):
        return None

    t0 = time.monotonic()
    try:
        out = pl({"array": y, "sampling_rate": sr})
    except Exception as e:
        logger.debug(f"emotion_model: pipeline runtime error: {e}")
        return None
    latency_ms = int((time.monotonic() - t0) * 1000)

    if latency_ms > PIPELINE_TIMEOUT_SEC * 1000:
        # We don't have a cooperative cancel; just flag it.
        logger.warning(f"emotion_model: slow classify ({latency_ms} ms)")

    # `out` is a list of {"label": "...", "score": float}
    if not isinstance(out, list) or not out:
        return None
    try:
        all_scores = {item["label"]: float(item["score"]) for item in out}
    except (KeyError, TypeError, ValueError):
        return None
    if not all_scores:
        return None
    top_label = max(all_scores, key=all_scores.get)
    return {
        "label": top_label,
        "score": round(all_scores[top_label], 4),
        "all_scores": {k: round(v, 4) for k, v in all_scores.items()},
        "latency_ms": latency_ms,
        "model": DEFAULT_MODEL,
    }


# ─── Log append ──────────────────────────────────────────────────────
def record_emotion_entry(
    message_id: Optional[int],
    classification: Dict[str, Any],
    prosody_tags: Optional[List[str]] = None,
    voice_archetype: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one emotion entry to emotion_log.jsonl. Silent on IOError."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "message_id": message_id,
            "emotion_label": classification.get("label"),
            "emotion_score": classification.get("score"),
            "all_scores": classification.get("all_scores", {}),
            "latency_ms": classification.get("latency_ms"),
            "model": classification.get("model"),
            "prosody_tags": prosody_tags or [],
            "voice_archetype": (voice_archetype or "").lower() or None,
        }
        if extra:
            for k, v in extra.items():
                if k not in entry:
                    entry[k] = v
        with _log_write_lock:
            with open(EMOTION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    except OSError as e:
        logger.debug(f"emotion_model: log write failed: {e}")


# ─── Background-thread entrypoint ────────────────────────────────────
def run_emotion_async(
    audio_path: str,
    duration: float = 0.0,
    message_id: Optional[int] = None,
    prosody_tags: Optional[List[str]] = None,
    voice_archetype: Optional[str] = None,
) -> None:
    """Top-level target for threading.Thread in handle_voice.

    Does classification + log append + info log. All failures silent.
    """
    try:
        result = classify_emotion(audio_path, duration=duration)
        if result is None:
            return
        record_emotion_entry(
            message_id=message_id,
            classification=result,
            prosody_tags=prosody_tags,
            voice_archetype=voice_archetype,
        )
        logger.info(
            f"Emotion: label={result['label']} score={result['score']:.2f} "
            f"(latency {result['latency_ms']} ms, "
            f"prosody={prosody_tags or '-'} arc={voice_archetype or '-'})"
        )
    except Exception as e:
        logger.debug(f"emotion_model: async run failed: {e}")


# ─── Stats / observability ───────────────────────────────────────────
def load_recent_emotions(
    days: int = 7, path: str = EMOTION_LOG_PATH,
) -> List[Dict[str, Any]]:
    """Return emotion_log entries from the last `days` days."""
    if not os.path.exists(path):
        return []
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = e.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.rstrip("Z"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
                if ts.timestamp() < cutoff:
                    continue
                out.append(e)
    except OSError:
        return []
    return out


# Phase 19.3 — Sidecar context for mood check-in/lift voice rendering.
#
# Mirror of Phase 18.0's sidecar for noticings. After build_mood_checkin_proactive
# or build_mood_lift_proactive succeeds, populates _LAST_MOOD_CHECKIN_CONTEXT
# so the midday handler in alicia.py can read it and pre-render voice in
# Beatrice's gentle/tender style. Without this, the smart decider gets
# only the text and may make a default decision unaware that this is a
# ceremonial moment.
_LAST_MOOD_CHECKIN_CONTEXT: Optional[Dict[str, Any]] = None
_MOOD_CHECKIN_CONTEXT_FRESH_SEC = 60


def get_last_mood_checkin_context() -> Optional[Dict[str, Any]]:
    """Return the mood-checkin sidecar context if set within the freshness
    window, else None. Mirror of get_last_noticing_context."""
    global _LAST_MOOD_CHECKIN_CONTEXT
    if not _LAST_MOOD_CHECKIN_CONTEXT:
        return None
    try:
        ts = _LAST_MOOD_CHECKIN_CONTEXT.get("ts")
        if not ts:
            return None
        ctx_ts = datetime.fromisoformat(ts)
        if ctx_ts.tzinfo is None:
            ctx_ts = ctx_ts.replace(tzinfo=timezone.utc)
        age_sec = (
            datetime.now(timezone.utc) - ctx_ts
        ).total_seconds()
        if age_sec > _MOOD_CHECKIN_CONTEXT_FRESH_SEC:
            return None
    except Exception:
        return None
    return dict(_LAST_MOOD_CHECKIN_CONTEXT)


def _set_last_mood_checkin_context(ctx: Dict[str, Any]) -> None:
    """Populate the sidecar (called by build_mood_checkin/lift_proactive)."""
    global _LAST_MOOD_CHECKIN_CONTEXT
    _LAST_MOOD_CHECKIN_CONTEXT = dict(ctx)
    _LAST_MOOD_CHECKIN_CONTEXT["ts"] = datetime.now(timezone.utc).isoformat()


def _clear_last_mood_checkin_context() -> None:
    """Test helper — drop the sidecar to ensure clean state per test."""
    global _LAST_MOOD_CHECKIN_CONTEXT
    _LAST_MOOD_CHECKIN_CONTEXT = None


# Phase 19.1 — Mood-aware proactive check-in.
#
# When the week's emotional weather has trended sharply downward, the
# midday rotation can raise a soft check-in: "the week's been heavier
# than usual — anything worth naming?" Beatrice's voice, witnessing not
# fixing. Cooldown so the same trend doesn't fire it twice.
MOOD_CHECKIN_LOG_PATH = os.path.join(MEMORY_DIR, "mood_checkin_log.jsonl")
MOOD_CHECKIN_TREND_THRESHOLD = -0.3   # delta in happy-ratio (newer half - older half)
MOOD_CHECKIN_COOLDOWN_DAYS = 5        # don't check in twice on the same heavy stretch
MOOD_CHECKIN_MIN_NOTES = 4            # need this many voice notes in the window


def _last_mood_checkin_age_days() -> Optional[float]:
    """Return age (days) of the most recent mood checkin, or None if never."""
    if not os.path.exists(MOOD_CHECKIN_LOG_PATH):
        return None
    try:
        last_ts = None
        with open(MOOD_CHECKIN_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    last_ts = e.get("ts") or last_ts
                except Exception:
                    continue
        if not last_ts:
            return None
        ts = datetime.fromisoformat(last_ts.rstrip("Z"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    except Exception:
        return None


def _record_mood_checkin(mood: Dict[str, Any], message: str) -> None:
    """Append a mood checkin record so cooldown applies next time."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trend": mood.get("trend"),
            "trend_explanation": mood.get("trend_explanation"),
            "summary_line": mood.get("summary_line"),
            "message_excerpt": (message or "")[:160],
        }
        # Phase 16.0 — conversation tag
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(MOOD_CHECKIN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"_record_mood_checkin failed: {e}")


def _compute_mood_delta() -> Optional[float]:
    """Recompute the half-window happy-vs-sad ratio delta. Returns the
    delta (newer half minus older half) or None on insufficient data."""
    try:
        entries = load_recent_emotions(days=7) or []
        sorted_entries = sorted(
            entries, key=lambda e: e.get("timestamp", ""),
        )
        half = len(sorted_entries) // 2
        if half < 2:
            return None
        older, newer = sorted_entries[:half], sorted_entries[half:]
        def _hr(es):
            hap = sum(
                1 for e in es
                if (e.get("emotion_label") or "").lower() == "hap"
            )
            sad = sum(
                1 for e in es
                if (e.get("emotion_label") or "").lower() in ("sad", "ang")
            )
            return (hap / (hap + sad)) if (hap + sad) else 0.5
        return _hr(newer) - _hr(older)
    except Exception as e:
        logger.debug(f"_compute_mood_delta failed: {e}")
        return None


def build_mood_checkin_proactive() -> Optional[Dict[str, Any]]:
    """Phase 19.1 — Build a mood check-in message when the week has
    trended sharply heavier.

    Returns dict {"message", "trend", "summary_line", "archetype",
    "score", "source_kind"} or None when:
      - mood is unknown / insufficient data
      - trend isn't sharply declining (delta > MOOD_CHECKIN_TREND_THRESHOLD)
      - cooldown applies (last check-in within MOOD_CHECKIN_COOLDOWN_DAYS)

    The message is composed via Haiku in Beatrice's voice — witness
    not fixer. Score 2.5 + Beatrice + lived_surfacing matches the
    Phase 17.0 ceremonial wiring so voice + drawing fast-path."""
    mood = get_mood_of_the_week(days=7)
    if not mood or mood.get("total_classifications", 0) < MOOD_CHECKIN_MIN_NOTES:
        return None
    if mood.get("trend") != "declining":
        return None
    delta = _compute_mood_delta()
    if delta is None or delta > MOOD_CHECKIN_TREND_THRESHOLD:
        # Not sharp enough — just generally declining
        return None
    # Cooldown check
    age = _last_mood_checkin_age_days()
    if age is not None and age < MOOD_CHECKIN_COOLDOWN_DAYS:
        return None
    # Compose via Haiku (Beatrice voice). Cheap call.
    body = _compose_mood_checkin_message(mood)
    if not body:
        return None
    message = f"🌧 _a quiet check-in_\n\n{body}"
    _record_mood_checkin(mood, message)
    result = {
        "message": message,
        "voice_text": body,
        "trend": mood.get("trend"),
        "summary_line": mood.get("summary_line"),
        "archetype": "beatrice",
        "score": 2.5,
        "source_kind": "lived_surfacing",
        # Phase 19.3 — voice style: tender for the heavy-week check-in
        "voice_style": "tender",
        "kind": "mood_checkin",
    }
    # Phase 19.3 — sidecar for the midday handler
    _set_last_mood_checkin_context(result)
    return result


# Phase 19.2 — Mirror of 19.1 for sharp upward trends.
#
# When the week's emotional weather has lifted markedly (delta ≥ +0.3),
# Alicia can quietly acknowledge the lift. Same Beatrice voice; same
# cooldown; different system prompt — witness the lift WITHOUT making
# it transactional ("good job!" / "keep it up!"). Just notice that
# something feels lighter.
MOOD_LIFT_TREND_THRESHOLD = 0.3   # delta in happy-ratio (newer - older)


def build_mood_lift_proactive() -> Optional[Dict[str, Any]]:
    """Phase 19.2 — Acknowledge an upward shift in the week's mood.

    Mirror of build_mood_checkin_proactive but for trend='improving'
    with delta ≥ +0.3. Same cooldown (MOOD_CHECKIN_COOLDOWN_DAYS) since
    both write to the same log — we don't want a downward-then-upward
    swing in the same window to fire two messages in quick succession.

    Returns the same shape as build_mood_checkin_proactive."""
    mood = get_mood_of_the_week(days=7)
    if not mood or mood.get("total_classifications", 0) < MOOD_CHECKIN_MIN_NOTES:
        return None
    if mood.get("trend") != "improving":
        return None
    delta = _compute_mood_delta()
    if delta is None or delta < MOOD_LIFT_TREND_THRESHOLD:
        return None
    # Cooldown shared with downward check-in
    age = _last_mood_checkin_age_days()
    if age is not None and age < MOOD_CHECKIN_COOLDOWN_DAYS:
        return None
    body = _compose_mood_lift_message(mood)
    if not body:
        return None
    message = f"☀️ _a small noticing_\n\n{body}"
    _record_mood_checkin(mood, message)
    result = {
        "message": message,
        "voice_text": body,
        "trend": mood.get("trend"),
        "summary_line": mood.get("summary_line"),
        "archetype": "beatrice",
        "score": 2.5,
        "source_kind": "lived_surfacing",
        # Phase 19.3 — voice style: gentle for the upward acknowledgment
        # (we don't soften further — gentle Beatrice IS the acknowledgment)
        "voice_style": "gentle",
        "kind": "mood_lift",
    }
    # Phase 19.3 — sidecar for the midday handler
    _set_last_mood_checkin_context(result)
    return result


_MOOD_LIFT_SYSTEM = (
    f"You are Alicia gently acknowledging a lift in {USER_NAME}'s week. His "
    "voice notes over the last 7 days have trended noticeably lighter "
    "— the emotion classifier is reading more happiness in the recent "
    "half than the first half of the same window.\n\n"
    "Write 2-3 short lines (30-60 words). Open by quietly naming what "
    "you've heard — the shift in the air, not the cause. One line of "
    "presence. Then ONE small invitation to notice it without making "
    "it transactional. Beatrice's voice — witness, not cheerleader. "
    "STRICTLY FORBIDDEN: 'great job', 'keep it up', 'you're doing "
    "great', 'proud of you', any praise. Also forbidden: explanations "
    "or causal claims ('because you...'). Just: 'something's lighter "
    "this week. I noticed.'"
)


def _compose_mood_lift_message(mood: Dict[str, Any]) -> Optional[str]:
    """Render the upward-mood body via Haiku."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        user_prompt = (
            f"Mood signal:\n"
            f"- summary: {mood.get('summary_line', '?')}\n"
            f"- trend: {mood.get('trend', '?')} "
            f"({mood.get('trend_explanation', '?')})\n"
            f"- {mood.get('total_classifications', 0)} voice notes "
            f"this week\n\n"
            f"Write the gentle acknowledgment body Alicia sends {USER_NAME}."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_MOOD_LIFT_SYSTEM,
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
        logger.warning(f"_compose_mood_lift_message failed: {e}")
        return None


_MOOD_CHECKIN_SYSTEM = (
    f"You are Alicia raising a quiet check-in with {USER_NAME}. His voice "
    "notes over the last week have trended noticeably heavier — the "
    "emotion classifier is reading more sadness or anger than the "
    "first half of the same window.\n\n"
    "Write 2-3 short lines (30-60 words total). Open by gently "
    "naming what you've heard — without diagnosing. One line of "
    "presence. Then ONE invitation to name what's there if he wants — "
    "explicitly making it okay to leave it for later. Beatrice's "
    "voice — witness, not fixer. NO advice. NO 'have you tried'. "
    "NO 'you should'. Just: 'I've been hearing it. I'm here.'"
)


def _compose_mood_checkin_message(mood: Dict[str, Any]) -> Optional[str]:
    """Render the mood-checkin body via Haiku."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2,
        )
        user_prompt = (
            f"Mood signal:\n"
            f"- summary: {mood.get('summary_line', '?')}\n"
            f"- trend: {mood.get('trend', '?')} "
            f"({mood.get('trend_explanation', '?')})\n"
            f"- {mood.get('total_classifications', 0)} voice notes "
            f"this week\n\n"
            f"Write the gentle check-in body Alicia sends {USER_NAME}."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_MOOD_CHECKIN_SYSTEM,
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
        logger.warning(f"_compose_mood_checkin_message failed: {e}")
        return None


def get_mood_of_the_week(days: int = 7) -> Dict[str, Any]:
    """Phase 19.0 — Compute the user's emotional weather over the last N days.

    Returns a structured summary the dashboard + /effectiveness can render:

        {
          "total_classifications": int,
          "dominant_label": str,            # most-common emotion label
          "dominant_share": float,          # 0.0–1.0
          "distribution": {label: count},   # full tally
          "trend": str,                     # 'improving' | 'stable' | 'declining' | 'unknown'
          "trend_explanation": str,         # one short sentence
          "summary_line": str,              # one-line headline ready for header pill
          "days": int,                      # window
        }

    Empty/uncertain returns sensible defaults; never raises. Trend is
    computed by splitting the window in halves and comparing the
    happy-vs-sad ratio. Improving means recent half is happier than
    older half; declining is the inverse.

    Reuses the same emotion_log.jsonl that Phase 17.1's
    `_recent_emotion_weather` reads — this is the longer-window
    cousin (7 days vs 24 hours, descriptive vs gating).
    """
    out: Dict[str, Any] = {
        "total_classifications": 0,
        "dominant_label": "",
        "dominant_share": 0.0,
        "distribution": {},
        "trend": "unknown",
        "trend_explanation": "",
        "summary_line": "",
        "days": days,
    }
    try:
        entries = load_recent_emotions(days=days) or []
    except Exception:
        return out
    if not entries:
        out["summary_line"] = "no voice notes this week yet"
        return out
    out["total_classifications"] = len(entries)
    # Distribution
    from collections import Counter as _Counter
    dist = _Counter(
        (e.get("emotion_label") or "?").lower() for e in entries
    )
    out["distribution"] = dict(dist)
    if dist:
        dominant_label, dominant_count = dist.most_common(1)[0]
        out["dominant_label"] = dominant_label
        out["dominant_share"] = round(dominant_count / len(entries), 2)
    # Trend: split into older half + newer half, compare happy/sad ratio
    sorted_entries = sorted(
        entries,
        key=lambda e: e.get("timestamp", ""),
    )
    half = len(sorted_entries) // 2
    if half >= 2:
        older = sorted_entries[:half]
        newer = sorted_entries[half:]
        def _happy_ratio(es):
            if not es:
                return 0.0
            hap = sum(
                1 for e in es
                if (e.get("emotion_label") or "").lower() == "hap"
            )
            sad = sum(
                1 for e in es
                if (e.get("emotion_label") or "").lower() in ("sad", "ang")
            )
            denom = hap + sad
            if denom == 0:
                return 0.5  # neutral if neither class present
            return hap / denom
        older_r = _happy_ratio(older)
        newer_r = _happy_ratio(newer)
        delta = newer_r - older_r
        if delta > 0.15:
            out["trend"] = "improving"
            out["trend_explanation"] = (
                f"recent days lighter (happy ratio {older_r:.0%}→{newer_r:.0%})"
            )
        elif delta < -0.15:
            out["trend"] = "declining"
            out["trend_explanation"] = (
                f"recent days heavier (happy ratio {older_r:.0%}→{newer_r:.0%})"
            )
        else:
            out["trend"] = "stable"
            out["trend_explanation"] = (
                f"holding steady (happy ratio ~{newer_r:.0%})"
            )
    elif len(sorted_entries) > 0:
        out["trend"] = "stable"
        out["trend_explanation"] = "too few entries to detect trend"
    # Summary line
    label_glyph = {
        "hap": "🙂", "neu": "😐", "sad": "😔", "ang": "😤", "?": "·",
    }.get(out["dominant_label"], "·")
    trend_glyph = {
        "improving": "↑", "stable": "→", "declining": "↓",
        "unknown": "·",
    }.get(out["trend"], "·")
    out["summary_line"] = (
        f"{label_glyph} {out['dominant_label']} "
        f"{int(out['dominant_share'] * 100)}% "
        f"{trend_glyph} {out['trend']}"
    )
    return out


def format_emotion_stats(days: int = 7) -> str:
    """Markdown summary for /emotion-stats."""
    entries = load_recent_emotions(days=days)
    if not entries:
        return (
            f"*Emotion (Phase C)*: no entries in the last {days} days.\n"
            f"First voice note after this deploy will start populating "
            f"`memory/emotion_log.jsonl`.\n"
            f"Model: `{DEFAULT_MODEL}`"
        )

    # Distribution
    counts: Dict[str, int] = {}
    latencies: List[int] = []
    for e in entries:
        lab = e.get("emotion_label") or "?"
        counts[lab] = counts.get(lab, 0) + 1
        lm = e.get("latency_ms")
        if isinstance(lm, (int, float)):
            latencies.append(int(lm))

    total = sum(counts.values())
    lines = [
        f"*Emotion (Phase C)* 🎭",
        f"_Window:_ last {days} days, *{total}* voice notes classified",
        "",
    ]
    for lab, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        pct = (100.0 * n / total) if total else 0.0
        lines.append(f"  • `{lab}`: {n} ({pct:.0f}%)")

    if latencies:
        latencies.sort()
        med = latencies[len(latencies) // 2]
        lines.append("")
        lines.append(f"_Latency median:_ {med} ms  _Model:_ `{DEFAULT_MODEL}`")

    # Show the latest 3 classifications
    recent = entries[-3:]
    if recent:
        lines.append("")
        lines.append("*Most recent:*")
        for e in recent:
            ts = e.get("timestamp", "")[:19]
            lab = e.get("emotion_label") or "?"
            sc = e.get("emotion_score") or 0
            pro = ",".join(e.get("prosody_tags") or []) or "-"
            arc = e.get("voice_archetype") or "-"
            lines.append(
                f"  • `{ts}` — {lab} ({sc:.2f}) "
                f"[prosody={pro}, arc={arc}]"
            )

    return "\n".join(lines)
