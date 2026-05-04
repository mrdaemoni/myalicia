"""
Module 2: Temporal Analysis
Maps when the user thinks deepest and what patterns emerge over time.

This module analyzes engagement metrics across time-of-day and day-of-week dimensions
to identify patterns in cognitive depth, communication preferences, and temporal rhythms.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict
import csv

import anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_text, locked_file
from myalicia.skills.bridge_protocol import write_bridge_text
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle


# Configure logging
logger = logging.getLogger(__name__)


def run_temporal_analysis() -> dict:
    """
    Main entry point for temporal analysis.

    Returns:
        dict with keys:
            - status: "success" or "error"
            - peak_hours: list of hours (0-23) ranked by average depth
            - patterns: dict of discovered patterns
            - report_path: path to detailed markdown report
            - error: error message if status is "error"
    """
    try:
        load_dotenv()

        # Resolve home directory paths
        home = Path.home()
        memory_dir = home / "alicia" / "memory"

        # Create memory dir if needed
        memory_dir.mkdir(parents=True, exist_ok=True)
        # Bridge dir is ensured by bridge_protocol on write.

        logger.info("Starting temporal analysis")

        # Load and parse data
        prompt_effectiveness = _load_prompt_effectiveness(memory_dir)
        reaction_log = _load_reaction_log(memory_dir)

        if not prompt_effectiveness:
            logger.warning("No prompt effectiveness data found")
            return {
                "status": "error",
                "error": "No prompt effectiveness data available",
                "peak_hours": [],
                "patterns": {}
            }

        # Analyze temporal patterns
        hourly_depth = _compute_hourly_depth(prompt_effectiveness)
        daily_patterns = _compute_daily_patterns(prompt_effectiveness)
        voice_text_patterns = _compute_voice_text_patterns(prompt_effectiveness)

        peak_hours = _rank_peak_hours(hourly_depth)

        # Get AI interpretation
        interpretation = _get_sonnet_interpretation(
            hourly_depth=hourly_depth,
            daily_patterns=daily_patterns,
            voice_text_patterns=voice_text_patterns,
            peak_hours=peak_hours
        )

        # Compile patterns dict
        patterns = {
            "hourly_depth": hourly_depth,
            "daily_patterns": daily_patterns,
            "voice_text_patterns": voice_text_patterns,
            "interpretation": interpretation
        }

        # Write findings
        _append_analysis_insights(memory_dir, patterns)
        report_path = _write_detailed_report(patterns)

        logger.info(f"Temporal analysis complete. Report: {report_path}")

        return {
            "status": "success",
            "peak_hours": peak_hours,
            "patterns": patterns,
            "report_path": str(report_path)
        }

    except Exception as e:
        logger.exception("Temporal analysis failed")
        return {
            "status": "error",
            "error": str(e),
            "peak_hours": [],
            "patterns": {}
        }


def _load_prompt_effectiveness(memory_dir: Path) -> list[dict]:
    """
    Load prompt_effectiveness.tsv and parse last 30 days.

    Returns list of dicts with keys: timestamp, msg_type, topic, depth, response_length
    """
    tsv_path = memory_dir / "prompt_effectiveness.tsv"

    if not tsv_path.exists():
        logger.warning(f"prompt_effectiveness.tsv not found at {tsv_path}")
        return []

    entries = []
    cutoff_date = datetime.now() - timedelta(days=30)

    try:
        with open(tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                try:
                    ts_str = row.get("timestamp", "")
                    if not ts_str:
                        continue

                    # Parse ISO timestamp
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        # Try alternate format
                        ts = datetime.fromisoformat(ts_str)

                    if ts < cutoff_date:
                        continue

                    # Try to parse depth as float
                    depth_str = row.get("depth", "0")
                    try:
                        depth = float(depth_str) if depth_str else 0.0
                    except ValueError:
                        depth = 0.0

                    # Try to parse response_length as int
                    resp_len_str = row.get("response_length", "0")
                    try:
                        response_length = int(resp_len_str) if resp_len_str else 0
                    except ValueError:
                        response_length = 0

                    entries.append({
                        "timestamp": ts,
                        "msg_type": row.get("msg_type", "unknown"),
                        "topic": row.get("topic", ""),
                        "depth": depth,
                        "response_length": response_length
                    })
                except Exception as line_error:
                    logger.debug(f"Skipping malformed line: {line_error}")
                    continue
    except Exception as e:
        logger.error(f"Failed to load prompt_effectiveness.tsv: {e}")
        return []

    logger.info(f"Loaded {len(entries)} prompt effectiveness entries from last 30 days")
    return entries


def _load_reaction_log(memory_dir: Path) -> list[dict]:
    """
    Load reaction_log.tsv if available.

    Returns list of dicts with keys: timestamp, message_id, msg_type, emoji, depth
    """
    tsv_path = memory_dir / "reaction_log.tsv"

    if not tsv_path.exists():
        logger.debug("reaction_log.tsv not found")
        return []

    entries = []
    cutoff_date = datetime.now() - timedelta(days=30)

    try:
        with open(tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                try:
                    ts_str = row.get("timestamp", "")
                    if not ts_str:
                        continue

                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

                    if ts < cutoff_date:
                        continue

                    depth_str = row.get("depth", "0")
                    try:
                        depth = float(depth_str) if depth_str else 0.0
                    except ValueError:
                        depth = 0.0

                    entries.append({
                        "timestamp": ts,
                        "message_id": row.get("message_id", ""),
                        "msg_type": row.get("msg_type", ""),
                        "emoji": row.get("emoji", ""),
                        "depth": depth
                    })
                except Exception as line_error:
                    logger.debug(f"Skipping malformed reaction line: {line_error}")
                    continue
    except Exception as e:
        logger.error(f"Failed to load reaction_log.tsv: {e}")

    logger.info(f"Loaded {len(entries)} reaction log entries")
    return entries


def _compute_hourly_depth(entries: list[dict]) -> dict[int, float]:
    """
    Compute average depth by hour of day (0-23).

    Returns dict: hour -> average depth
    """
    hourly_stats = defaultdict(lambda: {"depth_sum": 0.0, "count": 0})

    for entry in entries:
        hour = entry["timestamp"].hour
        hourly_stats[hour]["depth_sum"] += entry["depth"]
        hourly_stats[hour]["count"] += 1

    hourly_depth = {}
    for hour in range(24):
        if hour in hourly_stats:
            stats = hourly_stats[hour]
            hourly_depth[hour] = stats["depth_sum"] / stats["count"]
        else:
            hourly_depth[hour] = 0.0

    return hourly_depth


def _compute_daily_patterns(entries: list[dict]) -> dict:
    """
    Compute patterns by day of week.

    Returns dict with:
        - weekday_avg_depth: dict mapping day name to avg depth
        - weekend_vs_weekday: comparison metrics
    """
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    daily_stats = defaultdict(lambda: {"depth_sum": 0.0, "count": 0})

    for entry in entries:
        day_num = entry["timestamp"].weekday()
        daily_stats[day_num]["depth_sum"] += entry["depth"]
        daily_stats[day_num]["count"] += 1

    weekday_avg = {}
    for day_num in range(7):
        if day_num in daily_stats:
            stats = daily_stats[day_num]
            weekday_avg[day_names[day_num]] = stats["depth_sum"] / stats["count"]
        else:
            weekday_avg[day_names[day_num]] = 0.0

    # Weekday vs weekend
    weekday_depths = [
        weekday_avg.get("Monday", 0),
        weekday_avg.get("Tuesday", 0),
        weekday_avg.get("Wednesday", 0),
        weekday_avg.get("Thursday", 0),
        weekday_avg.get("Friday", 0)
    ]
    weekend_depths = [
        weekday_avg.get("Saturday", 0),
        weekday_avg.get("Sunday", 0)
    ]

    weekday_avg_val = sum(weekday_depths) / len(weekday_depths) if weekday_depths else 0
    weekend_avg_val = sum(weekend_depths) / len(weekend_depths) if weekend_depths else 0

    return {
        "weekday_avg_depth": weekday_avg,
        "weekday_avg": weekday_avg_val,
        "weekend_avg": weekend_avg_val,
        "weekend_vs_weekday_ratio": (
            weekend_avg_val / weekday_avg_val if weekday_avg_val > 0 else 1.0
        )
    }


def _compute_voice_text_patterns(entries: list[dict]) -> dict:
    """
    Compute patterns by message type (voice vs text).

    Returns dict with:
        - msg_type_avg_depth: dict mapping type to avg depth
        - msg_type_counts: dict mapping type to count
    """
    type_stats = defaultdict(lambda: {"depth_sum": 0.0, "count": 0})

    for entry in entries:
        msg_type = entry["msg_type"].lower()
        type_stats[msg_type]["depth_sum"] += entry["depth"]
        type_stats[msg_type]["count"] += 1

    msg_type_avg = {}
    msg_type_counts = {}
    for msg_type in type_stats:
        stats = type_stats[msg_type]
        msg_type_avg[msg_type] = stats["depth_sum"] / stats["count"]
        msg_type_counts[msg_type] = stats["count"]

    return {
        "msg_type_avg_depth": msg_type_avg,
        "msg_type_counts": msg_type_counts
    }


def _rank_peak_hours(hourly_depth: dict[int, float]) -> list[int]:
    """
    Rank hours by depth, returning top 5.

    Returns list of hours (0-23) ranked by depth descending.
    """
    sorted_hours = sorted(
        hourly_depth.items(),
        key=lambda x: x[1],
        reverse=True
    )
    return [hour for hour, _ in sorted_hours[:5]]


def _get_sonnet_interpretation(
    hourly_depth: dict,
    daily_patterns: dict,
    voice_text_patterns: dict,
    peak_hours: list
) -> str:
    """
    Send temporal data to Sonnet for interpretation.

    Returns interpretation string.
    """
    client = anthropic.Anthropic(max_retries=5)

    prompt = f"""Analyze the following temporal pattern data about {USER_NAME}'s thinking depth and provide insights about when he thinks deepest and why.

Data:
- Peak hours (ranked by avg depth): {peak_hours}
- Hourly average depth across all 24 hours: {json.dumps(hourly_depth, indent=2)}
- Daily patterns:
  - Weekday avg depth: {daily_patterns.get('weekday_avg', 0):.2f}
  - Weekend avg depth: {daily_patterns.get('weekend_avg', 0):.2f}
  - Weekday breakdown: {json.dumps(daily_patterns.get('weekday_avg_depth', {}), indent=2)}
- Message type patterns:
  - Avg depth by type: {json.dumps(voice_text_patterns.get('msg_type_avg_depth', {}), indent=2)}
  - Counts by type: {json.dumps(voice_text_patterns.get('msg_type_counts', {}), indent=2)}

Based on this data, answer these questions concisely:
1. What are the peak thinking hours for {USER_NAME}?
2. What differences exist between weekday and weekend patterns?
3. How do voice vs text interactions differ in terms of depth?
4. What might explain these patterns (e.g., work schedule, circadian rhythm, task type)?
5. What recommendations emerge for optimal engagement timing?

Keep the response to 200-300 words, structured and actionable."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        interpretation = message.content[0].text
        logger.info("Sonnet interpretation received")
        return interpretation
    except Exception as e:
        logger.error(f"Failed to get Sonnet interpretation: {e}")
        return "Unable to generate interpretation at this time."


def _append_analysis_insights(memory_dir: Path, patterns: dict) -> None:
    """
    Append findings to ~/alicia/memory/analysis_insights.md.

    Appends under temporal_analysis key with timestamp.
    """
    insights_path = memory_dir / "analysis_insights.md"

    timestamp = datetime.now().isoformat()
    section_header = f"## Temporal Analysis ({timestamp})"

    hourly_depth = patterns.get("hourly_depth", {})
    daily_patterns = patterns.get("daily_patterns", {})
    voice_text = patterns.get("voice_text_patterns", {})
    interpretation = patterns.get("interpretation", "")

    content_lines = [
        "",
        section_header,
        f"**Timestamp:** {timestamp}",
        f"**Source:** analysis_temporal.py",
        "",
        "### Peak Hours",
        f"Hours ranked by average depth: {list(hourly_depth.keys())[:5]}",
        "",
        "### Daily Patterns",
        f"- Weekday avg depth: {daily_patterns.get('weekday_avg', 0):.2f}",
        f"- Weekend avg depth: {daily_patterns.get('weekend_avg', 0):.2f}",
        f"- Weekend/Weekday ratio: {daily_patterns.get('weekend_vs_weekday_ratio', 1.0):.2f}",
        "",
        "### Message Type Patterns",
        f"- Avg depth by type: {voice_text.get('msg_type_avg_depth', {})}",
        "",
        "### AI Interpretation",
        interpretation,
        ""
    ]

    try:
        # Append under exclusive lock — other analysis modules also append here
        with locked_file(insights_path, "a", encoding="utf-8") as f:
            f.write("\n".join(content_lines))
        logger.info(f"Appended analysis insights to {insights_path}")
    except Exception as e:
        logger.error(f"Failed to append analysis insights: {e}")


def _write_detailed_report(patterns: dict) -> Path:
    """
    Write detailed markdown report to Bridge/temporal-report-YYYY-MM-DD.md.

    Returns path to report.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    report_filename = f"temporal-report-{today}.md"

    hourly_depth = patterns.get("hourly_depth", {})
    daily_patterns = patterns.get("daily_patterns", {})
    voice_text = patterns.get("voice_text_patterns", {})
    interpretation = patterns.get("interpretation", "")

    # Build report content
    lines = [
        "# Temporal Analysis Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Executive Summary",
        interpretation,
        "",
        "## Hourly Depth Analysis",
        "Average engagement depth by hour of day (0=midnight, 23=11pm):",
        ""
    ]

    # Format hourly table
    lines.append("| Hour | Avg Depth |")
    lines.append("|------|-----------|")
    for hour in range(24):
        depth = hourly_depth.get(hour, 0.0)
        hour_str = f"{hour:02d}:00"
        lines.append(f"| {hour_str} | {depth:.2f} |")

    lines.extend([
        "",
        "## Daily Patterns (Weekday vs Weekend)",
        ""
    ])

    weekday_avg = daily_patterns.get("weekday_avg_depth", {})
    for day, depth in weekday_avg.items():
        lines.append(f"- **{day}**: {depth:.2f}")

    lines.extend([
        "",
        f"- **Weekday average**: {daily_patterns.get('weekday_avg', 0):.2f}",
        f"- **Weekend average**: {daily_patterns.get('weekend_avg', 0):.2f}",
        f"- **Weekend/Weekday ratio**: {daily_patterns.get('weekend_vs_weekday_ratio', 1.0):.2f}",
        "",
        "## Message Type Patterns",
        ""
    ])

    msg_type_depth = voice_text.get("msg_type_avg_depth", {})
    msg_type_counts = voice_text.get("msg_type_counts", {})

    lines.append("| Type | Avg Depth | Count |")
    lines.append("|------|-----------|-------|")
    for msg_type in sorted(msg_type_depth.keys()):
        depth = msg_type_depth.get(msg_type, 0.0)
        count = msg_type_counts.get(msg_type, 0)
        lines.append(f"| {msg_type} | {depth:.2f} | {count} |")

    lines.extend([
        "",
        "## Detailed Interpretation",
        "",
        interpretation,
        "",
        "---",
        f"Report generated by analysis_temporal.py on {datetime.now().isoformat()}",
    ])

    try:
        report_path = write_bridge_text(report_filename, "\n".join(lines))
        logger.info(f"Wrote detailed report to {report_path}")
        return report_path
    except Exception as e:
        logger.error(f"Failed to write detailed report: {e}")
        raise


if __name__ == "__main__":
    # Configure logging for CLI execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    result = run_temporal_analysis()
    print(json.dumps(result, indent=2, default=str))
