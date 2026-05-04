"""
Gap 2 Phase B.2 — Per-user prosody baseline calibration.

Replaces the hand-tuned prosody thresholds in voice_intelligence.py with
percentile-based thresholds rebuilt nightly from the user's actual voice
history (voice_metadata_log.jsonl).

Why
---
Every iteration of Phase B (B → B.1 → B.1.1 → B.1.2) closed one gap and
opened another, because static thresholds on a single user's compressed-
mic audio will always be one edge case away from breaking. Each retune
wasted live voice notes as debugging fodder.

The robust answer is to let the user's own data set his thresholds:
   - WHISPERED fires at the quietest 10% of his speech.
   - FORCEFUL fires at the loudest 10% of his peaks.
   - TENDER's "narrow pitch" is narrow FOR HIM, not for generic voices.
   - HESITANT's "long pause" is long RELATIVE to his typical cadence.

The hand-tuned B.1.2 constants remain as the bootstrap defaults and the
clamp anchors. Calibration is a soft override, not a replacement.

Pipeline
--------
    voice note in
        ↓
    extract_prosody_tags() computes features
        ↓
    handle_voice passes features to record_voice_metadata(features=...)
        ↓
    voice_metadata_log.jsonl accumulates {..., "features": {...}}
        ↓
    23:10 nightly — rebuild_prosody_baseline()
        ↓
    memory/calibrated_prosody_thresholds.json
        ↓
    voice_intelligence._maybe_reload_calibration() picks up mtime change
        ↓
    next voice note uses calibrated thresholds

Safety
------
- Minimum sample size (MIN_SAMPLES = 20) before calibration activates.
- Each calibrated threshold clamped to ± CLAMP_PCT (40%) of its default.
  Prevents runaway if the log is somehow corrupted or all-one-tag.
- Skip feature entirely if the feature's own range (p90 - p10) is smaller
  than a minimum, i.e. all samples look the same → no discrimination.
- Atomic write (safe_io) so a partial file can never corrupt the runtime.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

logger = logging.getLogger(__name__)

MEMORY_DIR = str(MEMORY_DIR)
VOICE_LOG_PATH = os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl")
CALIBRATION_PATH = os.path.join(MEMORY_DIR, "calibrated_prosody_thresholds.json")

# How many logged entries (with features) we need before calibration
# is considered meaningful. 20 is roughly a day or two of normal use.
MIN_SAMPLES = 20

# Clamp each calibrated threshold to ± this fraction of its default.
# Keeps a weird day (mostly-whisper or mostly-forceful) from wrenching
# the thresholds into bad territory.
CLAMP_PCT = 0.40

# Rolling window — older than this is not used for calibration.
WINDOW_DAYS = 30

# Per-feature minimum dynamic range — if the log shows essentially no
# variation, skip that feature (hand-tuned default stands).
MIN_RANGE = {
    "mean_rms_db": 4.0,          # dB
    "peak_rms_db": 4.0,          # dB
    "f0_stdev_hz": 3.0,          # Hz
    "voiced_duration_sec": 2.0,  # s
    "max_pause_sec": 0.3,        # s
    "long_pauses": 1.0,          # count
}


# ─── Percentile helper (no numpy dep) ──────────────────────────────────
def _percentile(values: List[float], pct: float) -> float:
    """Linear-interpolation percentile on a sorted copy. pct in [0, 100]."""
    if not values:
        return 0.0
    s = sorted(values)
    if pct <= 0:
        return s[0]
    if pct >= 100:
        return s[-1]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def compute_percentiles(values: List[float]) -> Dict[str, float]:
    """Return p5/p10/p25/p50/p75/p90 for a list of numbers."""
    return {
        "p5":  _percentile(values, 5),
        "p10": _percentile(values, 10),
        "p25": _percentile(values, 25),
        "p50": _percentile(values, 50),
        "p75": _percentile(values, 75),
        "p90": _percentile(values, 90),
    }


# ─── Log reader ────────────────────────────────────────────────────────
def load_features_from_log(
    path: str = VOICE_LOG_PATH, days: int = WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Read voice_metadata_log.jsonl, return entries with a non-empty
    features dict from within the last `days` days."""
    if not os.path.exists(path):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: List[Dict[str, Any]] = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                feats = entry.get("features")
                if not isinstance(feats, dict) or not feats:
                    continue

                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.rstrip("Z")).replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, TypeError):
                    continue

                if ts < cutoff:
                    continue

                out.append(entry)
    except OSError as e:
        logger.warning(f"prosody_calibration: read failed: {e}")
        return []

    return out


# ─── Threshold derivation ──────────────────────────────────────────────
# Mapping: which percentile of which feature maps to which hand-tuned
# constant in voice_intelligence.py. Keep in lock-step with the constant
# names there — smoke test verifies every mapped constant still exists.
#
# (target_constant, feature_key, percentile)
THRESHOLD_MAP = [
    # WHISPERED path 1 (deep quiet): p5 of mean RMS — the quietest 5%
    ("PROSODY_WHISPERED_DEEP_RMS_DBFS", "mean_rms_db", "p5"),
    # WHISPERED path 2 composite: p10 of mean RMS — bottom decile
    ("PROSODY_WHISPERED_RMS_DBFS",      "mean_rms_db", "p10"),
    # WHISPERED path 2 peak gate: p25 of peak RMS — the quieter quartile
    ("PROSODY_WHISPERED_PEAK_DBFS",     "peak_rms_db", "p25"),
    # FORCEFUL mean: p75 of mean RMS — top quartile of loudness
    ("PROSODY_FORCEFUL_RMS_DBFS",       "mean_rms_db", "p75"),
    # FORCEFUL peak: p90 of peak RMS — top decile of peak loudness
    ("PROSODY_FORCEFUL_PEAK_DBFS",      "peak_rms_db", "p90"),
    # TENDER narrow-pitch ceiling: p25 of f0 stdev — his quieter-pitch quartile
    ("PROSODY_TENDER_F0_STDEV_HZ_MAX",  "f0_stdev_hz", "p25"),
    # TENDER minimum voiced duration: p50 — his median clip length
    ("PROSODY_TENDER_MIN_VOICED_SEC",   "voiced_duration_sec", "p50"),
    # HESITANT long-pause floor: p75 of max_pause — top-quartile gap length
    ("PROSODY_HESITANT_MAX_PAUSE_SEC",  "max_pause_sec", "p75"),
]


def _clamp(value: float, default: float, pct: float = CLAMP_PCT) -> float:
    """Clamp `value` to default ± pct * |default|.

    The absolute width never collapses below 1.0 so signed thresholds
    (dBFS defaults like -40) don't pin to the default when pct * default
    is small.
    """
    width = max(abs(default) * pct, 1.0)
    lo = default - width
    hi = default + width
    return max(lo, min(hi, value))


def derive_thresholds(
    feature_samples: Dict[str, List[float]],
    defaults: Dict[str, float],
) -> Dict[str, float]:
    """Turn feature arrays into calibrated threshold values (clamped)."""
    out: Dict[str, float] = {}
    for constant_name, feat_key, pct_key in THRESHOLD_MAP:
        values = feature_samples.get(feat_key) or []
        if len(values) < MIN_SAMPLES:
            continue
        # Dynamic-range gate
        pcts = compute_percentiles(values)
        rng = pcts["p90"] - pcts["p10"]
        if rng < MIN_RANGE.get(feat_key, 0.0):
            continue
        default = defaults.get(constant_name)
        if default is None:
            continue
        raw = pcts[pct_key]
        clamped = _clamp(raw, default)
        out[constant_name] = round(clamped, 2)
    return out


def _defaults_from_voice_intelligence() -> Dict[str, float]:
    """Snapshot every hand-tuned PROSODY_* constant from voice_intelligence
    so we can anchor clamps to code-defined defaults even after a calibration
    has already overwritten the in-memory value."""
    try:
        from myalicia.skills import voice_intelligence as vi
    except Exception as e:
        logger.warning(f"prosody_calibration: cannot import voice_intelligence: {e}")
        return {}
    # Code-defined defaults are stashed on import (see voice_intelligence.py
    # bottom block). If the snapshot module global is missing we fall back
    # to the current values.
    snapshot = getattr(vi, "_HARDCODED_DEFAULTS", None)
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot)
    return {
        name: getattr(vi, name)
        for name in dir(vi)
        if name.startswith("PROSODY_") and isinstance(getattr(vi, name), (int, float))
    }


# ─── Public: rebuild + load ────────────────────────────────────────────
def rebuild_prosody_baseline(
    path: str = VOICE_LOG_PATH,
    out_path: str = CALIBRATION_PATH,
    days: int = WINDOW_DAYS,
) -> Dict[str, Any]:
    """Read the voice log, compute per-user prosody thresholds, write them.

    Returns a summary dict:
        {
          "status": "ok" | "insufficient_data" | "no_log",
          "sample_size": int,
          "thresholds": { name: value, ... },     # only when status=ok
          "skipped": [constant_name, ...],        # defaults standing
          "computed_at": "2026-04-19T23:10:00",
          "window_days": 30,
        }
    """
    entries = load_features_from_log(path, days=days)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not entries:
        return {
            "status": "no_log",
            "sample_size": 0,
            "computed_at": now_iso,
            "window_days": days,
        }

    if len(entries) < MIN_SAMPLES:
        return {
            "status": "insufficient_data",
            "sample_size": len(entries),
            "computed_at": now_iso,
            "window_days": days,
            "min_samples": MIN_SAMPLES,
        }

    # Transpose features: Dict[feature_name] -> List[float]
    feature_samples: Dict[str, List[float]] = {}
    for e in entries:
        for k, v in (e.get("features") or {}).items():
            if isinstance(v, (int, float)):
                feature_samples.setdefault(k, []).append(float(v))

    defaults = _defaults_from_voice_intelligence()
    thresholds = derive_thresholds(feature_samples, defaults)

    # What we chose NOT to calibrate — caller can see which defaults
    # are standing so observability stays honest.
    all_targeted = {t[0] for t in THRESHOLD_MAP}
    skipped = sorted(all_targeted - set(thresholds.keys()))

    payload = {
        "version": 1,
        "computed_at": now_iso,
        "window_days": days,
        "sample_size": len(entries),
        "thresholds": thresholds,
        "skipped": skipped,
        "feature_percentiles": {
            k: compute_percentiles(v) for k, v in feature_samples.items()
        },
    }

    try:
        atomic_write_json(out_path, payload)
    except Exception as e:
        logger.error(f"prosody_calibration: write failed: {e}")
        return {
            "status": "write_failed",
            "sample_size": len(entries),
            "error": str(e),
            "computed_at": now_iso,
        }

    logger.info(
        f"prosody_calibration: wrote {len(thresholds)} thresholds "
        f"(skipped={len(skipped)}) from {len(entries)} samples "
        f"over {days}d window"
    )

    return {
        "status": "ok",
        "sample_size": len(entries),
        "thresholds": thresholds,
        "skipped": skipped,
        "computed_at": now_iso,
        "window_days": days,
    }


def load_calibrated_thresholds(
    path: str = CALIBRATION_PATH,
) -> Dict[str, float]:
    """Read the calibration JSON and return the thresholds dict (or {})."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"prosody_calibration: bad JSON at {path}: {e}")
        return {}
    t = data.get("thresholds")
    if not isinstance(t, dict):
        return {}
    # Filter to numeric only — defence against hand-edits.
    return {k: float(v) for k, v in t.items() if isinstance(v, (int, float))}


def format_calibration_report(
    path: str = CALIBRATION_PATH,
    show_defaults: bool = True,
) -> str:
    """Human-readable markdown for /prosody-cal command."""
    if not os.path.exists(path):
        return (
            "*Prosody calibration:* not yet computed.\n"
            f"Need ≥ {MIN_SAMPLES} voice notes with prosody features in the "
            "last 30 days. Phase B.1.2 defaults are in effect."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"*Prosody calibration:* read failed: `{e}`"

    lines: List[str] = []
    lines.append("*Prosody calibration* 🎚️")
    lines.append(f"_Computed:_ `{data.get('computed_at', '?')}`")
    lines.append(
        f"_Window:_ last {data.get('window_days', '?')} days, "
        f"*{data.get('sample_size', '?')}* voice notes"
    )

    thresholds = data.get("thresholds") or {}
    skipped = data.get("skipped") or []

    if thresholds:
        defaults = _defaults_from_voice_intelligence() if show_defaults else {}
        lines.append("")
        lines.append("*Calibrated thresholds:*")
        for name, val in sorted(thresholds.items()):
            short = name.replace("PROSODY_", "").lower()
            if name in defaults:
                d = defaults[name]
                delta = val - d
                arrow = "↑" if delta > 0 else "↓" if delta < 0 else "="
                lines.append(f"  • `{short}`: {val:+.2f} ({arrow} {d:+.2f})")
            else:
                lines.append(f"  • `{short}`: {val:+.2f}")

    if skipped:
        lines.append("")
        lines.append(f"_Skipped ({len(skipped)} — default standing):_")
        for name in skipped:
            short = name.replace("PROSODY_", "").lower()
            lines.append(f"  • `{short}`")

    return "\n".join(lines)
