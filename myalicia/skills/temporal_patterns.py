"""
Alicia's Temporal Pattern Engine

Analyzes timestamps across all data sources to learn the user's rhythms:
when he engages most deeply, what days work for what, and how to adapt
message timing to his actual patterns rather than hardcoded schedules.
"""

import os
import json
import csv
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger("alicia")

MEMORY_DIR = os.path.expanduser("~/alicia/memory")
PROMPT_TRACKING = os.path.join(MEMORY_DIR, "prompt_effectiveness.tsv")
REACTION_LOG = os.path.join(MEMORY_DIR, "reaction_log.tsv")
VOICE_META_LOG = os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl")
SESSION_THREADS = os.path.join(MEMORY_DIR, "session_threads.json")
DAILY_RHYTHM = os.path.join(MEMORY_DIR, "daily_rhythm.json")
TEMPORAL_STATE = os.path.join(MEMORY_DIR, "temporal_state.json")
LOG_FILE = os.path.expanduser("~/alicia/logs/interactions.jsonl")

# Day names for readability
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def analyze_engagement_by_hour(days: int = 30) -> dict:
    """
    Compute average engagement depth by hour of day.

    Returns:
        dict: {hour (0-23): {"avg_depth": float, "count": int, "response_rate": float}}
    """
    hourly = defaultdict(lambda: {"total_depth": 0, "count": 0, "responded": 0})
    cutoff = datetime.now() - timedelta(days=days)

    try:
        if os.path.exists(PROMPT_TRACKING):
            with open(PROMPT_TRACKING, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) < 6:
                        continue
                    try:
                        ts = datetime.strptime(parts[0][:16], "%Y-%m-%d %H:%M")
                        if ts < cutoff:
                            continue
                        hour = ts.hour
                        depth = float(parts[5]) if parts[5] else 0
                        resp_len = int(parts[3]) if parts[3] else 0
                        hourly[hour]["total_depth"] += depth
                        hourly[hour]["count"] += 1
                        if resp_len > 0:
                            hourly[hour]["responded"] += 1
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.debug(f"Error analyzing hourly engagement: {e}")

    result = {}
    for hour in range(24):
        data = hourly[hour]
        count = max(data["count"], 1)
        result[hour] = {
            "avg_depth": round(data["total_depth"] / count, 2),
            "count": data["count"],
            "response_rate": round(data["responded"] / count, 2),
        }
    return result


def analyze_engagement_by_day(days: int = 30) -> dict:
    """
    Compute average engagement depth by day of week.

    Returns:
        dict: {day_name: {"avg_depth": float, "count": int, "best_hour": int}}
    """
    daily = defaultdict(lambda: {"total_depth": 0, "count": 0, "hours": defaultdict(float)})
    cutoff = datetime.now() - timedelta(days=days)

    try:
        if os.path.exists(PROMPT_TRACKING):
            with open(PROMPT_TRACKING, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) < 6:
                        continue
                    try:
                        ts = datetime.strptime(parts[0][:16], "%Y-%m-%d %H:%M")
                        if ts < cutoff:
                            continue
                        day = ts.weekday()
                        hour = ts.hour
                        depth = float(parts[5]) if parts[5] else 0
                        daily[day]["total_depth"] += depth
                        daily[day]["count"] += 1
                        daily[day]["hours"][hour] += depth
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.debug(f"Error analyzing daily engagement: {e}")

    result = {}
    for day_idx in range(7):
        data = daily[day_idx]
        count = max(data["count"], 1)
        # Find best hour for this day
        best_hour = 0
        if data["hours"]:
            best_hour = max(data["hours"], key=data["hours"].get)
        result[DAY_NAMES[day_idx]] = {
            "avg_depth": round(data["total_depth"] / count, 2),
            "count": data["count"],
            "best_hour": best_hour,
        }
    return result


def analyze_voice_patterns(days: int = 30) -> dict:
    """
    Analyze when the user uses voice vs text, and voice emotional patterns.

    Returns:
        dict: {
            "voice_hours": {hour: count},
            "avg_wpm_by_hour": {hour: float},
            "emotional_tags": {tag: count},
            "peak_voice_hour": int,
        }
    """
    voice_hours = defaultdict(int)
    wpm_by_hour = defaultdict(list)
    tags = defaultdict(int)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # Check both possible paths
        for path in [VOICE_META_LOG,
                     str(config.vault.root / "voice_metadata_log.jsonl")]:
            if not os.path.exists(path):
                continue
            with open(path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("timestamp", "")
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        hour = ts.hour
                        voice_hours[hour] += 1
                        wpm = entry.get("wpm", 0)
                        if wpm:
                            wpm_by_hour[hour].append(wpm)
                        for tag in entry.get("tags", []):
                            tags[tag] += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
            break  # Use first found path
    except Exception as e:
        logger.debug(f"Error analyzing voice patterns: {e}")

    avg_wpm = {}
    for hour, wpms in wpm_by_hour.items():
        avg_wpm[hour] = round(sum(wpms) / len(wpms), 1)

    peak_hour = max(voice_hours, key=voice_hours.get) if voice_hours else 12

    return {
        "voice_hours": dict(voice_hours),
        "avg_wpm_by_hour": avg_wpm,
        "emotional_tags": dict(tags),
        "peak_voice_hour": peak_hour,
    }


def analyze_session_depth_by_mode(days: int = 60) -> dict:
    """
    Analyze which conversation modes produce the deepest sessions and when.

    Returns:
        dict: {mode: {"count": int, "avg_themes": float, "best_day": str, "best_hour": int}}
    """
    mode_data = defaultdict(lambda: {
        "count": 0, "total_themes": 0,
        "day_counts": defaultdict(int), "hour_counts": defaultdict(int),
    })
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        if os.path.exists(SESSION_THREADS):
            with open(SESSION_THREADS, 'r') as f:
                data = json.load(f)
            threads = data if isinstance(data, list) else data.get("threads", [])
            for t in threads:
                try:
                    ts_str = t.get("timestamp", "")
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                    mode = t.get("mode", t.get("source", "conversation"))
                    themes = len(t.get("themes", []))
                    mode_data[mode]["count"] += 1
                    mode_data[mode]["total_themes"] += themes
                    mode_data[mode]["day_counts"][ts.weekday()] += 1
                    mode_data[mode]["hour_counts"][ts.hour] += 1
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        logger.debug(f"Error analyzing session depth: {e}")

    result = {}
    for mode, data in mode_data.items():
        count = max(data["count"], 1)
        best_day_idx = max(data["day_counts"], key=data["day_counts"].get) if data["day_counts"] else 0
        best_hour = max(data["hour_counts"], key=data["hour_counts"].get) if data["hour_counts"] else 12
        result[mode] = {
            "count": data["count"],
            "avg_themes": round(data["total_themes"] / count, 1),
            "best_day": DAY_NAMES[best_day_idx],
            "best_hour": best_hour,
        }
    return result


def get_optimal_message_windows() -> dict:
    """
    Compute the best time windows for each message type based on engagement data.

    Returns:
        dict: {
            "peak_hours": [int] (top 3 hours by depth),
            "avoid_hours": [int] (bottom 3 hours),
            "best_challenge_day": str,
            "best_deep_hour": int,
            "voice_peak": int,
        }
    """
    hourly = analyze_engagement_by_hour()
    daily = analyze_engagement_by_day()
    voice = analyze_voice_patterns()

    # Top 3 peak hours
    sorted_hours = sorted(
        [(h, d["avg_depth"]) for h, d in hourly.items() if d["count"] > 0],
        key=lambda x: x[1], reverse=True
    )
    peak_hours = [h for h, _ in sorted_hours[:3]] if sorted_hours else [9, 12, 18]

    # Avoid hours (lowest engagement, at least 2 data points)
    low_hours = sorted(
        [(h, d["avg_depth"]) for h, d in hourly.items() if d["count"] >= 2],
        key=lambda x: x[1]
    )
    avoid_hours = [h for h, _ in low_hours[:3]] if low_hours else [23, 0, 1]

    # Best day for challenges (highest avg depth)
    sorted_days = sorted(
        [(d, info["avg_depth"]) for d, info in daily.items() if info["count"] > 0],
        key=lambda x: x[1], reverse=True
    )
    best_challenge_day = sorted_days[0][0] if sorted_days else "Wednesday"

    # Best hour for deep thinking
    best_deep = peak_hours[0] if peak_hours else 10

    return {
        "peak_hours": peak_hours,
        "avoid_hours": avoid_hours,
        "best_challenge_day": best_challenge_day,
        "best_deep_hour": best_deep,
        "voice_peak": voice.get("peak_voice_hour", 12),
    }


def compute_engagement_trajectory(weeks: int = 4) -> dict:
    """
    Track how engagement depth changes over time — is it growing, stable, or declining?

    Returns:
        dict: {
            "weekly_depths": [float] (avg depth per week, oldest first),
            "trend": "growing" | "stable" | "declining",
            "current_week_depth": float,
            "previous_week_depth": float,
        }
    """
    weekly_depths = defaultdict(list)
    now = datetime.now()

    try:
        if os.path.exists(PROMPT_TRACKING):
            with open(PROMPT_TRACKING, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) < 6:
                        continue
                    try:
                        ts = datetime.strptime(parts[0][:16], "%Y-%m-%d %H:%M")
                        weeks_ago = (now - ts).days // 7
                        if weeks_ago >= weeks:
                            continue
                        depth = float(parts[5]) if parts[5] else 0
                        weekly_depths[weeks_ago].append(depth)
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.debug(f"Error computing trajectory: {e}")

    # Compute averages per week
    weekly_avgs = []
    for w in range(weeks - 1, -1, -1):  # Oldest first
        depths = weekly_depths.get(w, [])
        avg = round(sum(depths) / len(depths), 2) if depths else 0
        weekly_avgs.append(avg)

    # Determine trend
    if len(weekly_avgs) >= 2:
        recent = weekly_avgs[-1]
        previous = weekly_avgs[-2]
        if recent > previous + 0.3:
            trend = "growing"
        elif recent < previous - 0.3:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "weekly_depths": weekly_avgs,
        "trend": trend,
        "current_week_depth": weekly_avgs[-1] if weekly_avgs else 0,
        "previous_week_depth": weekly_avgs[-2] if len(weekly_avgs) >= 2 else 0,
    }


def run_temporal_update() -> dict:
    """
    Full temporal analysis — run daily to update temporal state.

    Returns:
        dict with all computed patterns, saved to temporal_state.json
    """
    try:
        hourly = analyze_engagement_by_hour()
        daily = analyze_engagement_by_day()
        voice = analyze_voice_patterns()
        sessions = analyze_session_depth_by_mode()
        windows = get_optimal_message_windows()
        trajectory = compute_engagement_trajectory()

        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hourly_engagement": hourly,
            "daily_engagement": daily,
            "voice_patterns": voice,
            "session_depth_by_mode": sessions,
            "optimal_windows": windows,
            "engagement_trajectory": trajectory,
        }

        atomic_write_json(TEMPORAL_STATE, state)

        logger.info(
            f"Temporal update: peaks={windows['peak_hours']}, "
            f"trend={trajectory['trend']}, "
            f"challenge_day={windows['best_challenge_day']}"
        )
        return state

    except Exception as e:
        logger.error(f"Temporal update failed: {e}")
        return {"error": str(e)}


def get_temporal_context() -> str:
    """
    Build temporal context string for system prompt injection.

    Returns:
        str: Natural language summary of the user's engagement patterns.
    """
    try:
        if not os.path.exists(TEMPORAL_STATE):
            return ""

        with open(TEMPORAL_STATE, 'r') as f:
            state = json.load(f)

        windows = state.get("optimal_windows", {})
        trajectory = state.get("engagement_trajectory", {})

        parts = []

        peaks = windows.get("peak_hours", [])
        if peaks:
            peak_str = ", ".join(f"{h}:00" for h in peaks[:2])
            parts.append(f"{USER_NAME}'s peak engagement hours: {peak_str}")

        trend = trajectory.get("trend", "")
        if trend:
            parts.append(f"Engagement trend: {trend}")

        voice = state.get("voice_patterns", {})
        voice_tags = voice.get("emotional_tags", {})
        if voice_tags:
            top_tags = sorted(voice_tags.items(), key=lambda x: x[1], reverse=True)[:2]
            tag_str = ", ".join(f"{t[0]}" for t in top_tags)
            parts.append(f"Voice patterns: often {tag_str}")

        return ". ".join(parts) + "." if parts else ""

    except Exception as e:
        logger.debug(f"Could not build temporal context: {e}")
        return ""


def should_delay_message(msg_type: str) -> int:
    """
    Check if now is a good time for this message type based on temporal patterns.

    Returns:
        int: 0 if good to send, otherwise suggested delay in minutes.
    """
    try:
        if not os.path.exists(TEMPORAL_STATE):
            return 0

        with open(TEMPORAL_STATE, 'r') as f:
            state = json.load(f)

        windows = state.get("optimal_windows", {})
        avoid = windows.get("avoid_hours", [])
        current_hour = datetime.now().hour

        if current_hour in avoid:
            # Suggest delay until next non-avoid hour
            for offset in range(1, 24):
                next_hour = (current_hour + offset) % 24
                if next_hour not in avoid:
                    return offset * 60
            return 60  # Default 1 hour delay

        return 0
    except Exception:
        return 0
