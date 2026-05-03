"""
Voice pattern analysis and voice-informed response intelligence for Alicia.

Analyzes voice metadata to correlate vocal patterns with conversation depth and topic
engagement, then provides intelligence that shapes how Alicia responds.

Input sources (all in ~/alicia/memory/):
  - voice_metadata_log.jsonl: per-message voice stats
  - voice_signature.json: rolling 30-day profile
  - memory_results.tsv: memory extractions with scores
  - hot_topics.md: recent topics with timestamps
"""

import json
import os
import logging
import csv
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Dict, List, Any, Optional

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger(__name__)
MEMORY_DIR = os.path.expanduser("~/alicia/memory")


# ═══════════════════════════════════════════════════════════════════════
# GAP 2 PHASE B — LIBROSA PROSODY TAGS (2026-04-18)
# ═══════════════════════════════════════════════════════════════════════
#
# Phase A mapped the user's cadence (WPM + duration) to three tags:
#   [deliberate] < 100 wpm, [excited] > 160 wpm, [extended] > 60 s.
#
# Phase B adds four acoustic tags from librosa features:
#   [whispered] — low RMS energy (soft, intimate)
#   [forceful]  — high RMS + wide F0 spread (loud, emphatic)
#   [tender]    — moderate RMS + narrow F0 spread (close, slow)
#   [hesitant]  — frequent long inter-word pauses (searching)
#
# When a prosody tag fires with confidence, it DISPLACES the WPM tag in
# handle_voice — the acoustic signal is richer than cadence alone. When
# no prosody tag fires (quiet audio, short clip, ambient-only, librosa
# failure), the WPM tag stands. Phase A behaviour is the fallback.
#
# Thresholds are hard-coded constants, gated by a minimum audio duration
# and a minimum voiced-frame duration so librosa's F0 estimator isn't
# fed single-word voice notes that produce noisy pitch stdevs.
# ───────────────────────────────────────────────────────────────────────

# Gates — below these, prosody extraction returns [] and Phase A takes over
PROSODY_MIN_AUDIO_SEC = 1.5        # librosa F0 noisy on very short clips
PROSODY_MIN_VOICED_SEC = 0.5       # need real speech, not just ambient

# Thresholds (in dBFS, Hz, seconds). Retuned 2026-04-18 (Phase B.1) based on
# live data from the user's phone mic + AGC — the original thresholds were
# catching normal speech (baseline ~-38 dBFS) as whispered because the
# whisper-vs-normal RMS delta was only ~2 dB. New rules require BOTH a mean
# threshold AND a peak threshold (90th-percentile RMS) so sustained softness
# and loud stressed syllables are discriminable. Precision >> recall here —
# better to fall through to Phase A than to misclassify neutral speech.

# WHISPERED: two fire paths to handle both compressed and dynamic mics.
# Phase B.1.2: the user's real whispers land at mean=-44 but with loud
# stressed syllables ("*very* quiet"), peak ~ -22. The composite path
# (mean<-40 AND peak<-32) misses these because AGC boosts the peak.
# Deep-quiet path: if mean is VERY quiet and the clip is short (whispers
# are typically brief), trust the mean alone — no one whispers long
# passages by accident.
PROSODY_WHISPERED_DEEP_RMS_DBFS = -42.0      # NEW (path 1): extremely quiet mean
PROSODY_WHISPERED_DEEP_MAX_VOICED_SEC = 2.5  # NEW (path 1): short clip only
PROSODY_WHISPERED_RMS_DBFS = -40.0           # path 2: composite quiet
PROSODY_WHISPERED_PEAK_DBFS = -32.0          # path 2: peak gate

# FORCEFUL: loud mean + loud peak. F0-stdev gate dropped.
# Phase B.1.2: the user's emphatic voice is LOUD and FLAT (peak=-16, F0=7Hz),
# not loud-and-expressive. The 40 Hz F0 stdev floor was imported from
# generic assumptions about sing-song emphasis and rejects his entire
# forceful register. Mean relaxed -28 → -34 for the same compressed-mic
# reason that fixed whisper: his "loud" only reaches -32.9 mean despite
# peaks at -16.
PROSODY_FORCEFUL_RMS_DBFS = -34.0            # was -28 (too strict for his mic)
PROSODY_FORCEFUL_PEAK_DBFS = -18.0

# TENDER: moderate RMS, narrow F0, sustained (≥ 4s voiced).
# Phase B.1.1: peak gate removed (the user's tender voice has peaks around
# -19 to -24, above our previous -25 floor — the gate was too tight).
# F0 stdev tightened 20 → 15 and voiced-seconds minimum (4s) added so
# short bursts of normal speech in the same RMS band can't trigger tender.
PROSODY_TENDER_RMS_DBFS_MIN = -42.0
PROSODY_TENDER_RMS_DBFS_MAX = -33.0
PROSODY_TENDER_F0_STDEV_HZ_MAX = 15.0     # was 20 (too wide)
PROSODY_TENDER_MIN_VOICED_SEC = 4.0       # NEW — tender is sustained

# HESITANT: sparse long thinking pauses, not frequent breath gaps.
# Phase B.1.1: added an upper bound on pause count (3) because normal
# speech has 4+ sentence-boundary pauses. Real hesitation is FEWER but
# longer pauses. Raised max_pause 1.0 → 1.3s. Added voiced-seconds
# minimum (3s) so short clips with a single long silence can't qualify.
PROSODY_SILENCE_RMS_DBFS = -40.0
PROSODY_HESITANT_MIN_PAUSE_SEC = 0.6
PROSODY_HESITANT_MIN_PAUSE_COUNT = 2
PROSODY_HESITANT_MAX_PAUSE_COUNT = 3      # NEW — cap; > 3 is normal structure
PROSODY_HESITANT_MAX_PAUSE_SEC = 1.3      # was 1.0 (too permissive)
PROSODY_HESITANT_MIN_VOICED_SEC = 3.0     # NEW — need real speech content

# When multiple tags would fire, pick the one most acoustically distinct
# first. Whispered and forceful are loudness extremes (hardest to mis-tag);
# hesitant beats tender because its pause-structure signal is more
# discriminative than bare "close-speech" loudness — if the user is pausing
# to think, that's the dominant tell even when their timbre is soft.
PROSODY_TAG_PRIORITY = ["whispered", "forceful", "hesitant", "tender"]


# ═══════════════════════════════════════════════════════════════════════
# GAP 2 PHASE B.2 — PER-USER BASELINE CALIBRATION (2026-04-19)
# ═══════════════════════════════════════════════════════════════════════
#
# The PROSODY_* constants above are the HAND-TUNED DEFAULTS from B.1.2.
# Phase B.2 adds a soft override layer: thresholds rebuilt nightly from
# the user's own voice_metadata_log.jsonl, clamped to ± 40% of the default.
#
# Snapshot the defaults BEFORE any calibration can overwrite them, so
# prosody_calibration can always anchor clamps to the code-defined value
# rather than the (possibly already calibrated) current module global.
# ───────────────────────────────────────────────────────────────────────
_HARDCODED_DEFAULTS: Dict[str, float] = {
    name: value
    for name, value in list(globals().items())
    if name.startswith("PROSODY_") and isinstance(value, (int, float))
}

_CALIBRATION_PATH = os.path.join(MEMORY_DIR, "calibrated_prosody_thresholds.json")
_calibration_mtime: float = 0.0
_calibration_applied: int = 0  # how many thresholds currently overridden

# Most-recent prosody feature snapshot — populated by extract_prosody_tags,
# read by handle_voice so features can be persisted to voice_metadata_log.
_latest_features: Dict[str, float] = {}


def _maybe_reload_calibration() -> None:
    """Hot-reload calibrated_prosody_thresholds.json if it's been rewritten.

    Called once per extract_prosody_tags() invocation. The stat check is
    microseconds; librosa's extraction is ~50–200ms, so overhead is noise.
    Silent on failure — if calibration reload breaks for any reason, the
    hand-tuned defaults stand.
    """
    global _calibration_mtime, _calibration_applied
    try:
        mtime = os.path.getmtime(_CALIBRATION_PATH)
    except OSError:
        return
    if mtime <= _calibration_mtime:
        return
    try:
        from myalicia.skills.prosody_calibration import load_calibrated_thresholds
        thresholds = load_calibrated_thresholds(_CALIBRATION_PATH)
    except Exception as e:
        logger.debug(f"calibration reload skipped: {e}")
        return

    applied = 0
    for name, value in thresholds.items():
        if name in _HARDCODED_DEFAULTS:
            globals()[name] = float(value)
            applied += 1
    _calibration_mtime = mtime
    _calibration_applied = applied
    if applied:
        logger.info(
            f"Prosody calibration: applied {applied} calibrated thresholds "
            f"(mtime={int(mtime)})"
        )


def get_latest_prosody_features() -> Dict[str, float]:
    """Return a copy of the features from the most recent extract call.

    Used by handle_voice to pass features through to record_voice_metadata
    so the calibration log has real data to work from.
    """
    return dict(_latest_features)


def get_calibration_state() -> Dict[str, Any]:
    """Current calibration state for /prosody-cal + observability."""
    return {
        "path": _CALIBRATION_PATH,
        "file_exists": os.path.exists(_CALIBRATION_PATH),
        "applied_count": _calibration_applied,
        "mtime": _calibration_mtime,
    }


# One-shot initial load at import so a fresh Alicia process picks up
# whatever calibration exists on disk without waiting for the first
# voice note.
_maybe_reload_calibration()


def extract_prosody_tags(audio_path: str, duration: float) -> List[str]:
    """Run librosa analysis on a voice note. Return a single-tag list or [].

    Phase B prosody tags displace Phase A WPM tags when non-empty. The
    function is defensively wrapped: any failure (missing librosa, audio
    load error, pyin crash, silent file) returns [] so handle_voice
    falls back cleanly to the WPM tag. No voice reply ever breaks because
    of a prosody bug.

    Called from handle_voice in alicia.py with the downloaded .ogg path
    and Telegram-reported duration.
    """
    # Phase B.2: pick up any freshly-computed calibration before we run.
    # On module init this also ran once (see bottom-of-constants block).
    _maybe_reload_calibration()
    # Reset the features snapshot — if we return early the caller
    # legitimately sees an empty dict.
    _latest_features.clear()

    # Gate 1: too-short audio
    if not audio_path or duration < PROSODY_MIN_AUDIO_SEC:
        return []
    if not os.path.exists(audio_path):
        return []

    try:
        import librosa
        import numpy as np
    except ImportError:
        logger.warning("librosa not installed — Phase B prosody extraction disabled")
        return []

    try:
        # Load at native sample rate, mono. librosa uses soundfile/audioread
        # under the hood; .ogg Opus goes through audioread → ffmpeg.
        y, sr = librosa.load(audio_path, sr=None, mono=True)
    except Exception as e:
        logger.warning(f"Prosody load failed: {e}")
        return []

    if len(y) == 0:
        return []

    try:
        import numpy as np
    except ImportError:
        return []

    # Feature 1: RMS energy in dBFS — both mean and 90th percentile.
    # The peak (90th-pct) separates sustained softness (whispered/tender)
    # from speech with loud stressed syllables (normal/forceful).
    hop_length = 512
    frame_length = 2048
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    eps = 1e-6
    rms_db = 20.0 * np.log10(np.maximum(rms, eps))
    mean_rms_db = float(np.mean(rms_db))
    peak_rms_db = float(np.percentile(rms_db, 90))

    # Feature 2: F0 via pyin (probabilistic YIN)
    try:
        f0, voiced_flag, _voiced_prob = librosa.pyin(
            y, fmin=80, fmax=400, sr=sr,
            frame_length=frame_length,
        )
        voiced_f0 = f0[~np.isnan(f0)] if f0 is not None else np.array([])
        f0_stdev_hz = float(np.std(voiced_f0)) if len(voiced_f0) > 10 else 0.0
        voiced_frame_count = int(np.sum(voiced_flag)) if voiced_flag is not None else 0
        voiced_duration_sec = voiced_frame_count * hop_length / sr
    except Exception as e:
        logger.debug(f"pyin failed: {e}")
        f0_stdev_hz = 0.0
        voiced_duration_sec = 0.0

    # Gate 2: need enough actual speech content
    if voiced_duration_sec < PROSODY_MIN_VOICED_SEC:
        return []

    # Feature 3: per-pause durations (list), long-pause count, max pause.
    # Tracking individual pause lengths lets HESITANT require at least one
    # genuinely long thinking-pause (≥ 1s) rather than just multiple
    # breathing-gap-length pauses which normal speech has plenty of.
    frame_sec = hop_length / sr
    silent = rms_db < PROSODY_SILENCE_RMS_DBFS
    pause_durations = []
    run = 0
    for is_silent in silent:
        if is_silent:
            run += 1
        else:
            if run * frame_sec >= PROSODY_HESITANT_MIN_PAUSE_SEC:
                pause_durations.append(run * frame_sec)
            run = 0
    if run * frame_sec >= PROSODY_HESITANT_MIN_PAUSE_SEC:
        pause_durations.append(run * frame_sec)
    long_pauses = len(pause_durations)
    max_pause_sec = max(pause_durations) if pause_durations else 0.0

    # Phase B.2: snapshot features for record_voice_metadata. The
    # calibration log uses these to rebuild per-user thresholds nightly.
    _latest_features.update({
        "mean_rms_db": mean_rms_db,
        "peak_rms_db": peak_rms_db,
        "f0_stdev_hz": f0_stdev_hz,
        "voiced_duration_sec": voiced_duration_sec,
        "long_pauses": float(long_pauses),
        "max_pause_sec": max_pause_sec,
    })

    # Score each tag independently. Phase B.1.2 rules — calibrated against
    # the user's actual mic: mean RMS is compressed (whisper-to-forceful
    # spans ~12 dB), peaks are loud regardless of register (AGC), F0
    # stdev stays narrow even on emphatic speech.
    candidates = []
    # WHISPERED — two paths:
    #   Path 1 (deep): very quiet mean on a short clip (whispers are brief)
    #   Path 2 (composite): quiet mean AND quiet peak (sustained softness)
    whispered_deep = (
        mean_rms_db < PROSODY_WHISPERED_DEEP_RMS_DBFS
        and voiced_duration_sec < PROSODY_WHISPERED_DEEP_MAX_VOICED_SEC
    )
    whispered_composite = (
        mean_rms_db < PROSODY_WHISPERED_RMS_DBFS
        and peak_rms_db < PROSODY_WHISPERED_PEAK_DBFS
    )
    if whispered_deep or whispered_composite:
        candidates.append("whispered")
    # FORCEFUL — loud peak + elevated mean. F0-stdev gate dropped: the user's
    # emphatic register is loud-and-flat, not loud-and-expressive. Phase C
    # emotion model will handle affective pitch signals; prosody here just
    # flags volume bursts.
    if (mean_rms_db > PROSODY_FORCEFUL_RMS_DBFS
            and peak_rms_db > PROSODY_FORCEFUL_PEAK_DBFS):
        candidates.append("forceful")
    # Tender: moderate-soft + narrow F0 + sustained. No peak gate (the user's
    # tender voice has stressed syllables), but must be ≥ 4s voiced so
    # a short normal-voice burst in the same RMS band can't sneak in.
    if (PROSODY_TENDER_RMS_DBFS_MIN < mean_rms_db < PROSODY_TENDER_RMS_DBFS_MAX
            and 0 < f0_stdev_hz < PROSODY_TENDER_F0_STDEV_HZ_MAX
            and voiced_duration_sec >= PROSODY_TENDER_MIN_VOICED_SEC):
        candidates.append("tender")
    # Hesitant: FEW long pauses (2-3), at least one >= 1.3s, and real
    # speech content (>= 3s voiced). Many pauses (4+) indicate sentence
    # structure, not hesitation.
    if (PROSODY_HESITANT_MIN_PAUSE_COUNT <= long_pauses <= PROSODY_HESITANT_MAX_PAUSE_COUNT
            and max_pause_sec >= PROSODY_HESITANT_MAX_PAUSE_SEC
            and voiced_duration_sec >= PROSODY_HESITANT_MIN_VOICED_SEC):
        candidates.append("hesitant")

    logger.info(
        f"Prosody features: rms_db={mean_rms_db:.1f} peak_db={peak_rms_db:.1f} "
        f"f0_stdev_hz={f0_stdev_hz:.1f} voiced_sec={voiced_duration_sec:.1f} "
        f"long_pauses={long_pauses} max_pause={max_pause_sec:.2f}s "
        f"candidates={candidates}"
    )

    # Displacement rule: one tag wins by priority
    for tag in PROSODY_TAG_PRIORITY:
        if tag in candidates:
            return [tag]
    return []


def _read_jsonl(filepath: str) -> List[Dict]:
    """Parse JSONL file with error handling."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r') as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return []


def _read_tsv(filepath: str) -> List[Dict]:
    """Parse TSV file into list of dicts."""
    if not os.path.exists(filepath):
        return []
    try:
        rows = []
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f, delimiter='\t')
            rows = list(reader)
        return rows
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return []


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp, handling multiple formats."""
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except:
            pass
    return None


def analyze_voice_depth_correlation(days: int = 30) -> Dict[str, Any]:
    """
    Correlate voice patterns with memory extraction depth.

    Returns dict with:
      - deliberate_avg_score, excited_avg_score, extended_avg_score
      - depth_by_hour (hour → avg_score)
      - depth_by_wpm_band (slow/medium/fast → avg_score)
      - sample_size
    """
    cutoff = datetime.now() - timedelta(days=days)

    voice_log = _read_jsonl(os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl"))
    memory_results = _read_tsv(os.path.join(MEMORY_DIR, "memory_results.tsv"))

    # Filter voice messages within timeframe
    voice_messages = []
    for entry in voice_log:
        try:
            ts = _parse_timestamp(entry.get("timestamp", ""))
            if ts and ts >= cutoff:
                voice_messages.append(entry)
        except:
            pass

    if len(voice_messages) < 10:
        return {"status": "insufficient_data", "sample_size": len(voice_messages)}

    # Index memory results by timestamp (within 5 min window)
    memory_by_time = {}
    for row in memory_results:
        try:
            ts_str = row.get("timestamp", "")
            ts = _parse_timestamp(ts_str)
            score = float(row.get("score", 0))
            if ts:
                memory_by_time[ts] = score
        except:
            pass

    # Correlate: for each voice message, find memory extraction within 5 minutes
    deliberate_scores = []
    excited_scores = []
    extended_scores = []
    depth_by_hour = {}
    depth_by_wpm = {"slow": [], "medium": [], "fast": []}

    for voice in voice_messages:
        try:
            voice_ts = _parse_timestamp(voice.get("timestamp", ""))
            if not voice_ts:
                continue

            # Find matching memory score (5 min window)
            best_score = None
            for mem_ts, score in memory_by_time.items():
                if abs((mem_ts - voice_ts).total_seconds()) <= 300:
                    best_score = score
                    break

            if best_score is not None:
                tags = voice.get("tags", [])
                wpm = voice.get("wpm", 0)
                hour = voice_ts.hour

                # Categorize by tag
                if "deliberate" in tags:
                    deliberate_scores.append(best_score)
                if "excited" in tags:
                    excited_scores.append(best_score)
                if "extended" in tags:
                    extended_scores.append(best_score)

                # By hour
                if hour not in depth_by_hour:
                    depth_by_hour[hour] = []
                depth_by_hour[hour].append(best_score)

                # By WPM band
                if wpm < 100:
                    depth_by_wpm["slow"].append(best_score)
                elif wpm < 150:
                    depth_by_wpm["medium"].append(best_score)
                else:
                    depth_by_wpm["fast"].append(best_score)
        except:
            pass

    # Compute averages
    result = {
        "deliberate_avg_score": mean(deliberate_scores) if deliberate_scores else None,
        "excited_avg_score": mean(excited_scores) if excited_scores else None,
        "extended_avg_score": mean(extended_scores) if extended_scores else None,
        "depth_by_hour": {h: mean(v) for h, v in depth_by_hour.items()},
        "depth_by_wpm_band": {k: mean(v) if v else None for k, v in depth_by_wpm.items()},
        "sample_size": len(voice_messages),
        "status": "success"
    }

    return result


def get_voice_context() -> str:
    """
    Return 2-3 line summary for system prompt.

    Falls back gracefully if insufficient data.
    """
    voice_sig_path = os.path.join(MEMORY_DIR, "voice_signature.json")
    if not os.path.exists(voice_sig_path):
        return "## Voice Intelligence\n(No voice data yet.)"

    try:
        with open(voice_sig_path, 'r') as f:
            sig = json.load(f)
    except:
        return "## Voice Intelligence\n(Unable to load voice signature.)"

    trend = sig.get("trend", "stable")
    deliberate_ratio = sig.get("deliberate_ratio", 0)
    avg_score = sig.get("avg_deliberate_depth_score", 0)
    peak_hours = sig.get("peak_hours", [])
    hint = sig.get("steering_hints", "")

    hours_str = ", ".join(map(str, peak_hours[:3])) if peak_hours else "morning"

    return f"""## Voice Intelligence
the user's voice pattern: {trend}. When he speaks deliberately ({deliberate_ratio:.0%}), his insights score {avg_score:.1f} avg.
Peak voice depth: {hours_str}. Current steering: {hint}."""


def detect_voice_topic_patterns(days: int = 30) -> List[Dict]:
    """
    Cross-reference voice messages with hot topics.

    Returns list of dicts: [{"topic": str, "voice_ratio": float, "avg_depth": float}]
    """
    cutoff = datetime.now() - timedelta(days=days)

    voice_log = _read_jsonl(os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl"))
    hot_topics_path = os.path.join(MEMORY_DIR, "hot_topics.md")

    # Parse voice timestamps
    voice_times = set()
    for entry in voice_log:
        try:
            ts = _parse_timestamp(entry.get("timestamp", ""))
            if ts and ts >= cutoff:
                voice_times.add(ts)
        except:
            pass

    if not os.path.exists(hot_topics_path):
        return []

    # Parse hot_topics.md for topic + timestamp pairs
    topic_voices = {}
    try:
        with open(hot_topics_path, 'r') as f:
            content = f.read()
            # Simple parsing: look for lines with timestamps and topics
            for line in content.split('\n'):
                if '- ' in line and any(char.isdigit() for char in line):
                    # Try to extract topic and timestamp
                    parts = line.split(' - ')
                    if len(parts) >= 2:
                        topic = parts[0].strip('- ').lower()
                        for voice_time in voice_times:
                            if voice_time.isoformat()[:10] in line:
                                if topic not in topic_voices:
                                    topic_voices[topic] = {"voice": 0, "total": 0}
                                topic_voices[topic]["voice"] += 1
                                topic_voices[topic]["total"] += 1
    except:
        pass

    result = []
    for topic, counts in topic_voices.items():
        ratio = counts["voice"] / max(counts["total"], 1)
        result.append({
            "topic": topic,
            "voice_ratio": ratio,
            "avg_depth": 0.0  # Would require memory score lookup
        })

    return sorted(result, key=lambda x: x["voice_ratio"], reverse=True)


# Gap 2 Phase A (2026-04-18):
# Mapping from get_voice_response_guidance's "tone" field → text_to_voice "style"
# enum. The TTS engine only understands its own 5 enum values; this translation
# is the bridge. Centralised here so smoke tests can lock the policy and Phase B
# (prosody-driven tones) can extend the table without touching alicia.py.
#
# The mapping favours tonal *complement* over literal mirroring:
#   - the user excited → Alicia excited (mirror — match his energy)
#   - the user deliberate → Alicia measured (match the reflective register)
#   - the user extended → Alicia measured (he gave her room, don't rush)
#   - Everything else → warm (the existing default for voice replies)
#
# Future tones added by Phase B (whispered / forceful / tender / hesitant) will
# map here, not everywhere the TTS is invoked.
TONE_TO_TTS_STYLE = {
    "balanced":                  "warm",
    "warm":                      "warm",
    # Phase A (WPM-driven tones)
    "deep and reflective":       "measured",
    "energetic and engaged":     "excited",
    "threading and elaborative": "measured",
    # Phase B (prosody-driven tones, 2026-04-18)
    "quiet and intimate":        "gentle",     # whispered
    "passionate and forceful":   "excited",    # forceful — match intensity
    "tender and close":          "gentle",     # tender
    "searching and tentative":   "measured",   # hesitant — give space
}


def tone_to_tts_style(tone: str, default: str = "warm") -> str:
    """Map a get_voice_response_guidance tone string to a text_to_voice style.

    Returns `default` when the tone is unknown so voice replies never break.
    Exposed as a helper rather than inlined so Phase B can extend the map
    and smoke tests can lock the mapping per-tone.
    """
    if not tone:
        return default
    return TONE_TO_TTS_STYLE.get(tone.strip().lower(), default)


# ── Phase 17.4 — emotion-aware voice adaptation ──────────────────────────

# Styles that pre-empt weather adaptation: when the caller deliberately
# asked for "excited", we don't soften it to "tender" — that would
# silently override an explicit creative choice.
_VOICE_STYLES_EMPHATIC = frozenset({"excited"})

# Styles that adapt-down to "tender" when the user's recent voice notes
# show a sad/ang skew. These are the everyday-warm baseline styles.
_VOICE_STYLES_ADAPTIVE = frozenset({"warm", "measured", "default"})


def adapt_style_to_weather(style: str) -> str:
    """Phase 17.4 — soften the TTS style when the user's recent emotional
    weather is tender (sad/ang dominant in the last 24h).

    Pure function. Pass-through when:
      * weather is neutral
      * style is already "gentle" or "tender"
      * style is in _VOICE_STYLES_EMPHATIC (e.g. "excited")
      * any error occurs reading the emotion log

    The adaptation is applied automatically by text_to_voice() so every
    voice path attunes — proactives, voice replies, /walk readings,
    everything. Deliberate emphatic styles are preserved; everyday
    warmth is softened to tender."""
    if not style:
        return "default"
    s = style.strip().lower()
    if s in _VOICE_STYLES_EMPHATIC:
        return style
    if s in ("gentle", "tender"):
        return style  # already in the soft register
    if s not in _VOICE_STYLES_ADAPTIVE:
        return style  # unknown style — pass through
    try:
        from myalicia.skills.emergent_themes import _recent_emotion_weather
        if _recent_emotion_weather() == "tender":
            return "tender"
    except Exception:
        pass
    return style


def format_archetype_lens_directive(guidance: Dict[str, Any]) -> str:
    """Gap 2 Phase D: turn voice_guidance.archetype_hint into a prompt block.

    The hint itself lives in voice_guidance["archetype_hint"] and is
    already mapped from the voice tags in get_voice_response_guidance.
    This function wraps it into a short "respond through the X lens"
    directive and — if the archetype has enough attribution data —
    annotates the directive with its rolling effectiveness score from
    archetype_effectiveness.json. That score is what closes the loop:
    voice tone → archetype hint → prompt → reply → the user reacts →
    reaction_scorer.log_archetype_attribution → nightly rebuild →
    next voice-biased reply weights this archetype more or less
    strongly.

    Design choices
    --------------
    - Effectiveness-aware copy, not effectiveness-aware gating. We
      don't suppress the hint when score is low, because the voice tone
      signal is the whole point of this path. Instead we tell Sonnet
      "this register hasn't been landing — hold the lens lightly".
      Sonnet can then blend in warmth or concreteness.
    - Minimum 5 attributions before we surface any score annotation.
      Below that, the effectiveness number is noise.
    - Returns empty string for archetype_hint == "none" or balanced/warm
      defaults, so the prompt stays lean on non-signalled messages.
    """
    if not guidance or not guidance.get("suggest_voice_reply"):
        return ""
    hint = (guidance.get("archetype_hint") or "").strip()
    if not hint or hint.lower() == "none":
        return ""

    arch_key = hint.lower()
    # Archetype descriptions mirror inner_life.ARCHETYPES. Kept inline
    # (not imported) to avoid a circular-import risk between
    # voice_intelligence and inner_life; both modules are leaf-leaning
    # in the dependency graph and should stay that way.
    archetype_descriptions = {
        "beatrice": "growth witness — presence and validation",
        "daimon":   "shadow keeper — pattern detection, gentle naming of what's avoided",
        "ariadne":  "thread weaver — connect this to what's come before",
        "psyche":   "challenge holder — reciprocal invitation to the growth edge",
        "musubi":   "bond keeper — relational depth, stay close",
        "muse":     "inspiration seeker — serendipity, delight, vault echoes",
    }
    description = archetype_descriptions.get(arch_key)
    if not description:
        return ""

    lens = (
        f"Respond through the {hint.title()} lens — {description}. "
        f"Tonally, not verbatim. Do not announce the lens or open with "
        f"bracketed stage directions — the lens shapes the prose, it "
        f"isn't a label."
    )

    # Pull effectiveness score (best-effort). Silent on any failure —
    # the archetype lens still fires; we just drop the annotation.
    try:
        from myalicia.skills.inner_life import get_archetype_effectiveness
        eff = get_archetype_effectiveness() or {}
        archs = eff.get("archetypes", {}) or {}
        row = archs.get(arch_key) or {}
        score = float(row.get("score", 1.0))
        count = int(row.get("attribution_count", 0))
    except Exception:
        score, count = 1.0, 0

    if count >= 5:
        if score < 0.85:
            lens += (
                f" Note: this register has been landing softly lately "
                f"(effectiveness {score:.2f}× across {count} recent attributions). "
                f"Hold the lens lightly — blend in warmth or concreteness as feels right."
            )
        elif score > 1.15:
            lens += (
                f" This register has been landing well lately "
                f"(effectiveness {score:.2f}× across {count} recent attributions)."
            )

    return lens


def format_voice_tone_directive(guidance: Dict[str, Any]) -> str:
    """Build the system-prompt snippet that tells Sonnet how the user sounded.

    Gap 2 Phase A: Sonnet has always seen the bracketed tags ([deliberate],
    [excited], [extended]) prepended to the transcription, but never any
    explicit guidance on how to respond to them. This snippet turns the
    tag into an instruction:
      - tone → "respond in a {tone} register"
      - length → "keep it short" | "" | "respond at length"

    Returns an empty string when the guidance is empty/balanced so the
    prompt stays lean on non-voice messages.
    """
    if not guidance or not guidance.get("suggest_voice_reply"):
        return ""
    tone = (guidance.get("tone") or "").strip()
    length = (guidance.get("response_length") or "").strip().lower()
    # "balanced" = text message; "warm" = voice message with no tags fired
    # (middle-band WPM, under 60s). Both cases carry no signal worth
    # burning prompt tokens on — return empty so the prompt stays lean.
    if not tone or tone in ("balanced", "warm"):
        return ""

    length_hint = {
        "short":  " Keep the response concise — a sentence or two.",
        "medium": "",
        "long":   f" Respond at length — {USER_NAME} has given you room to think out loud.",
    }.get(length, "")

    return (
        f"{USER_NAME}'s voice just now sounded {tone}. "
        f"Match that register in your reply — tonally, not verbatim. "
        f"Do not preface your reply with bracketed tone descriptors "
        f"(e.g. '[tender, ...]', '[whispered]', '[gentle]') or other "
        f"stage directions — let the register live in the prose itself."
        f"{length_hint}"
    )


def get_voice_response_guidance(user_is_voice: bool, voice_tags: List[str]) -> Dict[str, Any]:
    """
    Provide guidance for response style based on voice characteristics.

    Returns dict with:
      - response_length: "short"|"medium"|"long"
      - tone: string description
      - suggest_voice_reply: bool
      - archetype_hint: string (Psyche/Beatrice/Muse/Ariadne)
    """
    if not user_is_voice:
        return {
            "response_length": "medium",
            "tone": "balanced",
            "suggest_voice_reply": False,
            "archetype_hint": "none"
        }

    guidance = {
        "response_length": "medium",
        "tone": "warm",
        "suggest_voice_reply": True,
        "archetype_hint": "Psyche"
    }

    # Gap 2 Phase B (prosody tags) — displace WPM-only tags. Order matters:
    # prosody is checked first so that when handle_voice displaces voice_tags
    # with a prosody tag, the right branch fires. The WPM tags below only
    # run when no prosody tag is present.
    if "whispered" in voice_tags:
        guidance.update({
            "response_length": "medium",
            "tone": "quiet and intimate",
            # Phase D: Musubi (bond keeper, relational depth) — intimate
            # whisper is relational depth, not reciprocal challenge. Psyche
            # was carried over from defaults and didn't match semantically.
            "archetype_hint": "Musubi"
        })
    elif "forceful" in voice_tags:
        guidance.update({
            "response_length": "short",
            "tone": "passionate and forceful",
            # Phase D: Psyche (challenge holder) — forceful emphatic energy
            # deserves reciprocal invitation, not delight. Muse is for
            # serendipity, not matched intensity.
            "archetype_hint": "Psyche"
        })
    elif "tender" in voice_tags:
        guidance.update({
            "response_length": "medium",
            "tone": "tender and close",
            "archetype_hint": "Beatrice"  # warmth, presence
        })
    elif "hesitant" in voice_tags:
        guidance.update({
            "response_length": "long",
            "tone": "searching and tentative",
            "archetype_hint": "Ariadne"  # help land the thought
        })
    # Gap 2 Phase A (WPM tags) — fallback when no prosody tag fired
    elif "deliberate" in voice_tags:
        guidance.update({
            "response_length": "long",
            "tone": "deep and reflective",
            "archetype_hint": "Psyche"  # Deep, introspective
        })
    elif "excited" in voice_tags:
        guidance.update({
            "response_length": "short",
            "tone": "energetic and engaged",
            "archetype_hint": "Muse"  # Creative, responsive
        })
    elif "extended" in voice_tags:
        guidance.update({
            "response_length": "long",
            "tone": "threading and elaborative",
            "archetype_hint": "Ariadne"  # Weaves connections
        })

    return guidance


def run_voice_analysis() -> Dict[str, Any]:
    """
    Main scheduled function. Runs full correlation analysis + topic patterns.

    Saves results to ~/alicia/memory/voice_intelligence.json
    Returns summary dict.
    """
    try:
        correlation = analyze_voice_depth_correlation()
        topics = detect_voice_topic_patterns()

        result = {
            "timestamp": datetime.now().isoformat(),
            "correlation": correlation,
            "topics": topics,
            "status": "success" if correlation.get("status") == "success" else "warning"
        }

        # Save to disk (atomic — crash-safe)
        output_path = os.path.join(MEMORY_DIR, "voice_intelligence.json")
        atomic_write_json(output_path, result)

        logger.info(f"Voice analysis complete: {correlation.get('sample_size', 0)} samples")
        return result
    except Exception as e:
        logger.error(f"Voice analysis failed: {e}")
        return {"status": "error", "error": str(e)}
