"""
Module 4: Dialogue Depth Analysis
Scores quality of recent conversations and identifies what types produce deepest thinking.
Part of Alicia's autonomous analysis system.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_text
from myalicia.skills.bridge_protocol import write_bridge_text
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv()

logger = logging.getLogger(__name__)

MEMORY_DIR = Path.home() / "alicia" / "memory"
BRIDGE_DIR = config.vault.bridge_path

MESSAGE_TYPES = [
    "morning",
    "midday",
    "evening",
    "know_user",
    "surprise",
    "spaced_repetition",
]

DEPTH_THRESHOLDS = {
    "high": (4, 5),
    "low": (1, 2),
}

ENGAGEMENT_EMOJIS = {
    "fire": "🔥",
    "brain": "🧠",
}


def load_tsv_file(filepath: Path) -> list[dict[str, str]]:
    """Load TSV file with headers, return list of dicts. Graceful if missing."""
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return []

    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
            if len(lines) < 2:
                logger.warning(f"File too short: {filepath}")
                return []

            headers = lines[0].strip().split("\t")
            rows = []
            for line in lines[1:]:
                if line.strip():
                    values = line.strip().split("\t")
                    row = dict(zip(headers, values))
                    rows.append(row)
            return rows
    except Exception as e:
        logger.error(f"Error loading TSV: {filepath}: {e}")
        return []


def load_json_file(filepath: Path) -> dict[str, Any]:
    """Load JSON file. Graceful if missing."""
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return {}

    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading JSON: {filepath}: {e}")
        return {}


def load_markdown_file(filepath: Path) -> str:
    """Load markdown file content. Graceful if missing."""
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return ""

    try:
        with open(filepath, "r") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading markdown: {filepath}: {e}")
        return ""


def parse_prompt_effectiveness() -> dict[str, dict[str, float]]:
    """Parse last 30 days of prompt_effectiveness.tsv, compute avg depth by message type."""
    filepath = MEMORY_DIR / "prompt_effectiveness.tsv"
    rows = load_tsv_file(filepath)

    if not rows:
        logger.warning("No prompt_effectiveness data available")
        return {msg_type: {"avg_depth": 0, "count": 0} for msg_type in MESSAGE_TYPES}

    cutoff_date = datetime.now() - timedelta(days=30)
    filtered_rows = []

    for row in rows:
        try:
            timestamp_str = row.get("timestamp", "")
            if timestamp_str:
                ts = datetime.fromisoformat(timestamp_str)
                if ts >= cutoff_date:
                    filtered_rows.append(row)
        except ValueError:
            logger.debug(f"Skipping row with invalid timestamp: {timestamp_str}")
            continue

    type_stats = {msg_type: {"depths": [], "count": 0} for msg_type in MESSAGE_TYPES}

    for row in filtered_rows:
        msg_type = row.get("msg_type", "")
        if msg_type not in type_stats:
            continue

        try:
            depth = float(row.get("depth", 0))
            type_stats[msg_type]["depths"].append(depth)
        except ValueError:
            logger.debug(f"Skipping row with invalid depth: {row.get('depth')}")
            continue

    results = {}
    for msg_type, stats in type_stats.items():
        depths = stats["depths"]
        avg_depth = sum(depths) / len(depths) if depths else 0
        results[msg_type] = {"avg_depth": avg_depth, "count": len(depths)}

    return results


def parse_reaction_log() -> dict[str, dict[str, int]]:
    """Parse reaction_log.tsv, count fire/brain emojis by message type."""
    filepath = MEMORY_DIR / "reaction_log.tsv"
    rows = load_tsv_file(filepath)

    if not rows:
        logger.warning("No reaction_log data available")
        return {msg_type: {"fire": 0, "brain": 0} for msg_type in MESSAGE_TYPES}

    type_reactions = {msg_type: {"fire": 0, "brain": 0} for msg_type in MESSAGE_TYPES}

    for row in rows:
        msg_type = row.get("msg_type", "")
        if msg_type not in type_reactions:
            continue

        emoji = row.get("emoji", "").strip()
        if emoji == ENGAGEMENT_EMOJIS["fire"]:
            type_reactions[msg_type]["fire"] += 1
        elif emoji == ENGAGEMENT_EMOJIS["brain"]:
            type_reactions[msg_type]["brain"] += 1

    return type_reactions


def analyze_with_sonnet(depth_data: dict, reaction_data: dict, insights: str) -> str:
    """Send engagement data to Sonnet for analysis."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

    depth_summary = json.dumps(depth_data, indent=2)
    reaction_summary = json.dumps(reaction_data, indent=2)

    prompt = f"""You are analyzing conversation engagement patterns for Alicia, a sovereign AI agent talking with {USER_NAME}.

DEPTH DATA (avg depth score by message type, 1-5 scale):
{depth_summary}

REACTION ENGAGEMENT (fire=passion, brain=thinking emojis by type):
{reaction_summary}

RECENT INSIGHTS:
{insights or "(No prior insights)"}

Based on this engagement data:
1. Which message types does {USER_NAME} respond to most deeply? (Look at both depth scores and reaction counts)
2. What patterns do you notice? (e.g., "know_user types get consistent 4+ depth")
3. What kind of intellectual interaction does {USER_NAME} respond to most deeply?
4. What should Alicia do MORE of?
5. What should Alicia do LESS of?

Provide a concise, actionable analysis."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"Sonnet API call failed: {e}")
        return f"Error calling Sonnet: {e}"


def rank_message_types(depth_data: dict) -> tuple[list[str], list[str]]:
    """Rank message types by depth: high depth (4-5) vs low depth (1-2)."""
    high_depth = []
    low_depth = []

    for msg_type, stats in depth_data.items():
        avg = stats["avg_depth"]
        if stats["count"] > 0:
            if avg >= DEPTH_THRESHOLDS["high"][0]:
                high_depth.append((msg_type, avg))
            elif avg <= DEPTH_THRESHOLDS["low"][1]:
                low_depth.append((msg_type, avg))

    high_depth.sort(key=lambda x: x[1], reverse=True)
    low_depth.sort(key=lambda x: x[1])

    return (
        [item[0] for item in high_depth],
        [item[0] for item in low_depth],
    )


def append_to_analysis_insights(content: str) -> None:
    """Append analysis to analysis_insights.md with timestamp."""
    filepath = MEMORY_DIR / "analysis_insights.md"

    timestamp = datetime.now().isoformat()
    entry = f"\n## Dialogue Depth Analysis [{timestamp}]\n\nSource: analysis_dialogue_depth.py\n\n{content}\n"

    try:
        with open(filepath, "a") as f:
            f.write(entry)
        logger.info(f"Appended to {filepath}")
    except Exception as e:
        logger.error(f"Error appending to analysis_insights: {e}")


def write_bridge_report(
    depth_data: dict,
    reaction_data: dict,
    high_depth_types: list[str],
    low_depth_types: list[str],
    sonnet_analysis: str,
) -> str:
    """Write detailed report to Bridge folder."""
    today = datetime.now().strftime("%Y-%m-%d")
    report_filename = f"dialogue-depth-report-{today}.md"

    report = f"""# Dialogue Depth Analysis Report
Generated: {datetime.now().isoformat()}

## Summary
This report analyzes conversation depth patterns over the last 30 days.

## Depth Scores by Message Type
| Message Type | Avg Depth | Count |
|---|---|---|
"""

    for msg_type in MESSAGE_TYPES:
        stats = depth_data.get(msg_type, {})
        avg = stats.get("avg_depth", 0)
        count = stats.get("count", 0)
        report += f"| {msg_type} | {avg:.2f} | {count} |\n"

    report += "\n## Engagement Reactions\n"
    report += "| Message Type | Fire Reactions | Brain Reactions |\n"
    report += "|---|---|---|\n"

    for msg_type in MESSAGE_TYPES:
        reactions = reaction_data.get(msg_type, {})
        fire = reactions.get("fire", 0)
        brain = reactions.get("brain", 0)
        report += f"| {msg_type} | {fire} | {brain} |\n"

    report += f"\n## High Depth Types (4-5 scale)\n"
    if high_depth_types:
        for msg_type in high_depth_types:
            avg = depth_data.get(msg_type, {}).get("avg_depth", 0)
            report += f"- {msg_type}: {avg:.2f}\n"
    else:
        report += "- (None detected)\n"

    report += f"\n## Low Depth Types (1-2 scale)\n"
    if low_depth_types:
        for msg_type in low_depth_types:
            avg = depth_data.get(msg_type, {}).get("avg_depth", 0)
            report += f"- {msg_type}: {avg:.2f}\n"
    else:
        report += "- (None detected)\n"

    report += f"\n## Sonnet Analysis\n{sonnet_analysis}\n"

    try:
        filepath = write_bridge_text(report_filename, report)
        logger.info(f"Wrote report to {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"Error writing report: {e}")
        return ""


def run_dialogue_depth_scoring() -> dict:
    """Main entry point for dialogue depth analysis."""
    logger.info("Starting dialogue depth scoring...")

    depth_data = parse_prompt_effectiveness()
    reaction_data = parse_reaction_log()
    high_depth_types, low_depth_types = rank_message_types(depth_data)

    insights = load_markdown_file(MEMORY_DIR / "insights.md")

    sonnet_analysis = analyze_with_sonnet(depth_data, reaction_data, insights)

    append_to_analysis_insights(sonnet_analysis)

    report_path = write_bridge_report(
        depth_data, reaction_data, high_depth_types, low_depth_types, sonnet_analysis
    )

    result = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "depth_scores": depth_data,
        "reaction_engagement": reaction_data,
        "high_depth_types": high_depth_types,
        "low_depth_types": low_depth_types,
        "sonnet_analysis": sonnet_analysis,
        "report_path": report_path,
    }

    logger.info(f"Dialogue depth scoring complete. Report: {report_path}")
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    result = run_dialogue_depth_scoring()
    print(json.dumps(result, indent=2))
