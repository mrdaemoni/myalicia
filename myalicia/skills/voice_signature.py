"""
Voice signature tracking module for the user.

Builds a rolling 30-day profile of voice patterns to steer conversation responses.
Thread-safe logging of voice metadata with computed analytics.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger(__name__)

# Module-level constants
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
VOICE_LOG_FILE = os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl")
VOICE_SIGNATURE_FILE = os.path.join(MEMORY_DIR, "voice_signature.json")


def _ensure_memory_dir() -> None:
    """Ensure memory directory exists."""
    try:
        Path(MEMORY_DIR).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create memory directory: {e}")
        raise


def record_voice_metadata(
    duration: float, word_count: int, wpm: float, tags: list[str], file_size: int = 0,
    features: dict | None = None,
) -> None:
    """
    Append voice message metadata to the log.

    Args:
        duration: Duration in seconds
        word_count: Number of words in message
        wpm: Words per minute
        tags: List of tags, should contain one of ["deliberate", "excited", "extended"]
        file_size: File size in bytes (optional)
        features: Optional prosody feature snapshot (mean_rms_db, peak_rms_db,
                  f0_stdev_hz, voiced_duration_sec, long_pauses, max_pause_sec).
                  Written verbatim so Phase B.2 calibration can percentile
                  these features nightly.

    Returns:
        None
    """
    _ensure_memory_dir()

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "duration": duration,
        "word_count": word_count,
        "wpm": wpm,
        "tags": tags,
        "file_size": file_size,
    }
    if features:
        # Keep it defensive: only numeric fields survive serialization.
        entry["features"] = {
            k: float(v) for k, v in features.items()
            if isinstance(v, (int, float))
        }

    try:
        with open(VOICE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug(f"Recorded voice metadata: {entry}")
    except IOError as e:
        logger.error(f"Failed to write voice metadata: {e}")


def compute_voice_signature() -> dict[str, Any]:
    """
    Compute voice signature from last 30 days of logged messages.

    Reads voice_metadata_log.jsonl, filters to last 30 days, computes statistics,
    and saves result to voice_signature.json.

    Returns:
        Dictionary with computed voice profile, or empty dict if insufficient data.
    """
    _ensure_memory_dir()

    if not os.path.exists(VOICE_LOG_FILE):
        logger.warning("Voice log file does not exist")
        return {"trend": "insufficient_data"}

    # Read and parse log entries
    entries = []
    try:
        with open(VOICE_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        logger.warning(f"Skipped malformed JSON line: {line[:50]}")
                        continue
    except IOError as e:
        logger.error(f"Failed to read voice log: {e}")
        return {"trend": "insufficient_data"}

    # Filter to last 30 days (use timezone-aware UTC to match parsed timestamps)
    now = datetime.now(tz=timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    recent_entries = []

    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if ts >= thirty_days_ago:
                recent_entries.append(entry)
        except (ValueError, KeyError):
            logger.warning(f"Skipped entry with invalid timestamp: {entry}")
            continue

    # Check for insufficient data
    if len(recent_entries) < 10:
        logger.info(f"Insufficient data: only {len(recent_entries)} entries in last 30 days")
        return {"trend": "insufficient_data"}

    # Compute statistics
    total_voice_messages = len(recent_entries)
    total_duration = sum(e.get("duration", 0) for e in recent_entries)
    avg_duration = total_duration / total_voice_messages if total_voice_messages > 0 else 0

    total_wpm_sum = sum(e.get("wpm", 0) for e in recent_entries)
    avg_wpm = total_wpm_sum / total_voice_messages if total_voice_messages > 0 else 0

    # Tag ratios
    deliberate_count = sum(
        1 for e in recent_entries if "deliberate" in e.get("tags", [])
    )
    excited_count = sum(1 for e in recent_entries if "excited" in e.get("tags", []))
    extended_count = sum(1 for e in recent_entries if "extended" in e.get("tags", []))

    deliberate_ratio = (deliberate_count / total_voice_messages) if total_voice_messages > 0 else 0
    excited_ratio = (excited_count / total_voice_messages) if total_voice_messages > 0 else 0
    extended_ratio = (extended_count / total_voice_messages) if total_voice_messages > 0 else 0

    # Peak voice hours
    hour_counts = {}
    for entry in recent_entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            hour = ts.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        except (ValueError, KeyError):
            continue

    peak_voice_hours = sorted(
        hour_counts.items(), key=lambda x: x[1], reverse=True
    )[:3]
    peak_voice_hours = [hour for hour, _ in peak_voice_hours]

    # Average messages per day
    date_counts = {}
    for entry in recent_entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            date_key = ts.date()
            date_counts[date_key] = date_counts.get(date_key, 0) + 1
        except (ValueError, KeyError):
            continue

    num_days = len(date_counts) if date_counts else 1
    avg_messages_per_day = total_voice_messages / num_days

    # Compute trend: compare first 15 days vs last 15 days
    mid_point = now - timedelta(days=15)
    first_half = [e for e in recent_entries if datetime.fromisoformat(
        e["timestamp"].replace("Z", "+00:00")
    ) < mid_point]
    second_half = [e for e in recent_entries if datetime.fromisoformat(
        e["timestamp"].replace("Z", "+00:00")
    ) >= mid_point]

    trend = "stable"
    if len(first_half) >= 5 and len(second_half) >= 5:
        first_deliberate_ratio = (
            sum(1 for e in first_half if "deliberate" in e.get("tags", []))
            / len(first_half)
        )
        second_deliberate_ratio = (
            sum(1 for e in second_half if "deliberate" in e.get("tags", []))
            / len(second_half)
        )
        first_excited_ratio = (
            sum(1 for e in first_half if "excited" in e.get("tags", []))
            / len(first_half)
        )
        second_excited_ratio = (
            sum(1 for e in second_half if "excited" in e.get("tags", []))
            / len(second_half)
        )

        if second_deliberate_ratio > first_deliberate_ratio + 0.1:
            trend = "more_deliberate"
        elif second_excited_ratio > first_excited_ratio + 0.1:
            trend = "more_excited"

    signature = {
        "total_voice_messages": total_voice_messages,
        "avg_duration": round(avg_duration, 2),
        "avg_wpm": round(avg_wpm, 2),
        "deliberate_ratio": round(deliberate_ratio, 3),
        "excited_ratio": round(excited_ratio, 3),
        "extended_ratio": round(extended_ratio, 3),
        "peak_voice_hours": peak_voice_hours,
        "avg_messages_per_day": round(avg_messages_per_day, 2),
        "trend": trend,
        "last_computed": datetime.utcnow().isoformat() + "Z",
    }

    # Save to file
    try:
        with open(VOICE_SIGNATURE_FILE, "w", encoding="utf-8") as f:
            json.dump(signature, f, indent=2)
        logger.debug(f"Computed and saved voice signature: {signature}")
    except IOError as e:
        logger.error(f"Failed to save voice signature: {e}")

    return signature


def get_voice_signature() -> dict[str, Any]:
    """
    Get cached voice signature or compute fresh if needed.

    Returns cached voice_signature.json if it exists and is less than 24 hours old.
    Otherwise computes fresh signature via compute_voice_signature().

    Returns:
        Dictionary with voice profile, or empty dict with "insufficient_data" if < 10 messages.
    """
    _ensure_memory_dir()

    # Check for cached file
    if os.path.exists(VOICE_SIGNATURE_FILE):
        try:
            stat = os.stat(VOICE_SIGNATURE_FILE)
            age_seconds = (datetime.utcnow() - datetime.utcfromtimestamp(stat.st_mtime)).total_seconds()

            if age_seconds < 86400:  # 24 hours in seconds
                with open(VOICE_SIGNATURE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                logger.debug(f"Using cached voice signature (age: {age_seconds}s)")
                return cached
        except (IOError, json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read cached signature: {e}")

    # Compute fresh
    return compute_voice_signature()


def get_voice_steering_hint() -> str:
    """
    Generate natural language hint for system prompt based on voice signature.

    Returns:
        String hint for conversation steering, or empty string if insufficient data.

    Examples:
        "the user tends to speak deliberately (avg 85 wpm). Give him space — don't fill pauses."
        "the user's been speaking faster lately (trend: more_excited). Match his energy."
        "Most of the user's voice messages are extended (>60s). He thinks in long arcs."
    """
    sig = get_voice_signature()

    if sig.get("trend") == "insufficient_data":
        return ""

    hints = []

    # Deliberate pattern
    deliberate_ratio = sig.get("deliberate_ratio", 0)
    if deliberate_ratio > 0.7:
        avg_wpm = sig.get("avg_wpm", 0)
        hints.append(
            f"{USER_NAME} tends to speak deliberately (avg {avg_wpm} wpm). Give him space — don't fill pauses."
        )

    # Trend-based hint
    trend = sig.get("trend", "stable")
    if trend == "more_excited":
        hints.append(f"{USER_NAME}'s been speaking faster lately (trend: more_excited). Match his energy.")
    elif trend == "more_deliberate":
        hints.append(
            f"{USER_NAME}'s been speaking more deliberately lately. Give him time to think."
        )

    # Extended pattern
    extended_ratio = sig.get("extended_ratio", 0)
    if extended_ratio > 0.5:
        hints.append(f"Most of {USER_NAME}'s voice messages are extended (>60s). He thinks in long arcs.")

    return " ".join(hints) if hints else ""


def get_voice_stats_summary() -> str:
    """
    Return formatted summary for /status or proactive messages.

    Returns:
        String summary like "Voice: 42 messages, avg 45.2s, 120 wpm. Trend: stable."
    """
    sig = get_voice_signature()

    if sig.get("trend") == "insufficient_data":
        return ""

    total = sig.get("total_voice_messages", 0)
    duration = sig.get("avg_duration", 0)
    wpm = sig.get("avg_wpm", 0)
    trend = sig.get("trend", "unknown")

    return f"Voice: {total} messages, avg {duration}s, {wpm} wpm. Trend: {trend}."
