"""
Cross-module intelligence coordination layer for Alicia.

Reads outputs from all analysis modules (contradiction, growth edge, dialogue depth,
temporal) and builds a unified daily context that proactive messages and the system
prompt can read from.

Key functions:
- build_daily_context(): Reads all sources, builds unified context, saves to JSON
- get_coordination_context(): Returns 3-5 line summary for system prompt injection
- get_recommended_topics(): Returns 3 topics combining growth edges + hot topics
- get_archetype_recommendation(): Suggests which archetype to foreground
- detect_stagnation(days=14): Checks if key metrics have plateaued
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta

from myalicia.skills.safe_io import atomic_write_json
from myalicia.skills.bridge_protocol import list_bridge_reports
from glob import glob
from pathlib import Path
from myalicia.config import config

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.expanduser("~/alicia/memory")
BRIDGE_DIR = str(config.vault.bridge_path)

# Ensure memory directory exists
Path(MEMORY_DIR).mkdir(parents=True, exist_ok=True)


def _read_analysis_insights():
    """
    Read analysis_insights.md — compiled insights from all analysis modules.
    Format: markdown with sections for each module's findings.
    Returns list of insight strings.
    """
    filepath = os.path.join(MEMORY_DIR, "analysis_insights.md")
    insights = []
    try:
        with open(filepath, "r") as f:
            content = f.read()
            # Extract lines that look like insights (non-empty, non-heading)
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    insights.append(line)
    except FileNotFoundError:
        logger.debug(f"analysis_insights.md not found at {filepath}")
    except Exception as e:
        logger.error(f"Error reading analysis_insights.md: {e}")
    return insights


def _read_hot_topics():
    """
    Read hot_topics.md — recent high-signal conversation topics.
    Format: - (YYYY-MM-DD HH:MM) [tag] text [source]
    Returns list of dicts: {"topic": str, "date": str, "tag": str, "source": str}
    """
    filepath = os.path.join(MEMORY_DIR, "hot_topics.md")
    topics = []
    try:
        with open(filepath, "r") as f:
            pattern = r"- \((\d{4}-\d{2}-\d{2} \d{2}:\d{2})\) \[(\w+)\] (.+?)(?: \[(.+?)\])?$"
            for line in f:
                match = re.match(pattern, line.strip())
                if match:
                    timestamp, tag, text, source = match.groups()
                    topics.append({
                        "topic": text.strip(),
                        "date": timestamp,
                        "tag": tag,
                        "source": source or "unknown"
                    })
    except FileNotFoundError:
        logger.debug(f"hot_topics.md not found at {filepath}")
    except Exception as e:
        logger.error(f"Error reading hot_topics.md: {e}")
    return topics


def _read_effectiveness_state():
    """
    Read effectiveness_state.json — proactive message effectiveness scores by type.
    Returns dict: {"type_name": float, ...}
    """
    filepath = os.path.join(MEMORY_DIR, "effectiveness_state.json")
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(f"effectiveness_state.json not found at {filepath}")
        return {}
    except Exception as e:
        logger.error(f"Error reading effectiveness_state.json: {e}")
        return {}


def _read_curiosity_followthrough():
    """
    Read curiosity_followthrough.jsonl — entries with timestamp, event, question, type, target.
    Returns list of dicts with these keys.
    """
    filepath = os.path.join(MEMORY_DIR, "curiosity_followthrough.jsonl")
    entries = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        logger.debug(f"curiosity_followthrough.jsonl not found at {filepath}")
    except Exception as e:
        logger.error(f"Error reading curiosity_followthrough.jsonl: {e}")
    return entries


def _read_voice_signature():
    """
    Read voice_signature.json — voice profile with trend and steering hints.
    Returns dict with keys: "trend", "steering", "stability_score", etc.
    """
    filepath = os.path.join(MEMORY_DIR, "voice_signature.json")
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(f"voice_signature.json not found at {filepath}")
        return {}
    except Exception as e:
        logger.error(f"Error reading voice_signature.json: {e}")
        return {}


def _find_latest_bridge_report(pattern):
    """
    Find the most recently dated bridge report matching a glob pattern.
    Pattern should contain a single `*` wildcard (e.g., "contradiction-report-*.md").
    Returns the full path (str) or None if not found.

    Routes through bridge_protocol.list_bridge_reports for uniform discovery.
    """
    try:
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
        else:
            prefix, suffix = pattern, ""
        matches = list_bridge_reports(prefix, suffix=suffix, max_results=1)
        if matches:
            return str(matches[0])
    except Exception as e:
        logger.error(f"Error finding bridge report with pattern {pattern}: {e}")
    return None


def _extract_bridge_insights(filepath, section_pattern=None):
    """
    Extract insights from a bridge report.
    If section_pattern provided, only extract from matching sections.
    Returns list of insight strings.
    """
    insights = []
    try:
        with open(filepath, "r") as f:
            content = f.read()
            # Extract non-empty, non-heading lines
            in_section = True if not section_pattern else False
            for line in content.split("\n"):
                if section_pattern and f"## {section_pattern}" in line:
                    in_section = True
                    continue
                if section_pattern and line.startswith("##") and not line.startswith(f"## {section_pattern}"):
                    in_section = False
                    continue
                line = line.strip()
                if in_section and line and not line.startswith("#") and not line.startswith("---"):
                    insights.append(line)
    except Exception as e:
        logger.error(f"Error extracting bridge insights from {filepath}: {e}")
    return insights


def _get_resonance_priorities():
    """
    Try to import resonance data from message_quality module.
    Falls back gracefully if module not available.
    Returns list of dicts: [{"title": str, "count": int}, ...]
    """
    try:
        from myalicia.skills.message_quality import get_resonance_priorities
        return get_resonance_priorities()
    except ImportError:
        logger.debug("message_quality module not available for resonance")
        return []
    except Exception as e:
        logger.error(f"Error getting resonance priorities: {e}")
        return []


def _calculate_curiosity_followthrough_rate(entries):
    """
    Calculate engaged / asked ratio from curiosity_followthrough entries.
    Returns float 0-1.
    """
    if not entries:
        return 0.0
    asked = sum(1 for e in entries if e.get("event") == "asked")
    engaged = sum(1 for e in entries if e.get("event") == "engaged")
    if asked == 0:
        return 0.0
    return min(1.0, engaged / asked)


def _calculate_best_curiosity_types(entries):
    """
    Find question types with highest engagement rate.
    Returns list of type strings, up to 3.
    """
    if not entries:
        return []

    type_stats = {}
    for entry in entries:
        q_type = entry.get("type", "unknown")
        event = entry.get("event")
        if q_type not in type_stats:
            type_stats[q_type] = {"asked": 0, "engaged": 0}
        if event == "asked":
            type_stats[q_type]["asked"] += 1
        elif event == "engaged":
            type_stats[q_type]["engaged"] += 1

    # Calculate engagement rates
    rates = []
    for q_type, stats in type_stats.items():
        if stats["asked"] > 0:
            rate = stats["engaged"] / stats["asked"]
            rates.append((q_type, rate))

    # Return top 3 by rate
    rates.sort(key=lambda x: x[1], reverse=True)
    return [t[0] for t in rates[:3]]


def build_daily_context():
    """
    Main function: reads all sources, builds unified context, saves to daily_context.json.
    Returns the constructed context dict.
    """
    logger.info("Building daily context from analysis modules...")

    # Gather all inputs
    insights = _read_analysis_insights()
    hot_topics = _read_hot_topics()
    effectiveness = _read_effectiveness_state()
    curiosity_entries = _read_curiosity_followthrough()
    voice_data = _read_voice_signature()
    resonance_priorities = _get_resonance_priorities()

    # Extract from bridge reports
    growth_edges_report = _find_latest_bridge_report("growth-edge-report-*.md")
    growth_edges = []
    if growth_edges_report:
        growth_insights = _extract_bridge_insights(growth_edges_report, "Growth Edges")
        # Parse top 3 with evidence
        for insight in growth_insights[:3]:
            parts = insight.split("—")
            if len(parts) >= 2:
                growth_edges.append({
                    "area": parts[0].strip(),
                    "evidence": parts[1].strip()
                })

    contradiction_report = _find_latest_bridge_report("contradiction-report-*.md")
    contradictions = []
    if contradiction_report:
        contradiction_insights = _extract_bridge_insights(contradiction_report)
        # Parse top 3 with productive value
        for insight in contradiction_insights[:3]:
            parts = insight.split("—")
            if len(parts) >= 2:
                contradictions.append({
                    "name": parts[0].strip(),
                    "clusters": parts[1].strip() if len(parts) > 2 else "active",
                    "productive_value": parts[-1].strip() if len(parts) > 2 else "unknown"
                })

    dialogue_report = _find_latest_bridge_report("dialogue-depth-report-*.md")
    high_depth_types = []
    low_depth_types = []
    if dialogue_report:
        dialogue_insights = _extract_bridge_insights(dialogue_report)
        # Try to parse message types that work vs don't work
        for insight in dialogue_insights:
            if "high depth" in insight.lower() or "work" in insight.lower():
                msg_type = insight.split(":")[0].strip() if ":" in insight else insight
                if msg_type:
                    high_depth_types.append(msg_type[:40])
            elif "low depth" in insight.lower() or "don't" in insight.lower():
                msg_type = insight.split(":")[0].strip() if ":" in insight else insight
                if msg_type:
                    low_depth_types.append(msg_type[:40])

    temporal_report = _find_latest_bridge_report("temporal-report-*.md")
    peak_hours = []
    if temporal_report:
        temporal_insights = _extract_bridge_insights(temporal_report)
        # Extract hour numbers from insights
        for insight in temporal_insights[:5]:
            hours = re.findall(r'\b([0-5]?\d)\s*(?:h|hour)', insight)
            for h in hours:
                peak_hours.append(int(h))
        peak_hours = sorted(list(set(peak_hours)))[:3]

    # Calculate derived metrics
    followthrough_rate = _calculate_curiosity_followthrough_rate(curiosity_entries)
    best_curiosity_types = _calculate_best_curiosity_types(curiosity_entries)

    # Get voice trend and steering
    voice_trend = voice_data.get("trend", "stable")
    voice_steering = voice_data.get("steering", "maintain current trajectory")

    # Get top resonance priorities
    top_resonance = resonance_priorities[:5] if resonance_priorities else []

    # Recommend archetype based on data
    archetype = get_archetype_recommendation()

    # Get recommended topics
    recommended_topics = get_recommended_topics()

    # Detect stagnation
    stagnation_alerts = detect_stagnation(days=14)

    # Build final context
    context = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "growth_edges": growth_edges,
        "active_contradictions": contradictions,
        "hot_topics": [
            {"topic": t["topic"], "date": t["date"]}
            for t in hot_topics[-5:]
        ],
        "high_depth_message_types": high_depth_types[:3],
        "low_depth_message_types": low_depth_types[:3],
        "peak_hours": peak_hours,
        "curiosity_followthrough_rate": round(followthrough_rate, 2),
        "best_curiosity_types": best_curiosity_types,
        "voice_trend": voice_trend,
        "voice_steering": voice_steering,
        "resonance_priorities": top_resonance,
        "recommended_archetype": archetype,
        "recommended_topics": recommended_topics,
        "stagnation_alerts": stagnation_alerts
    }

    # Save to daily_context.json
    output_path = os.path.join(MEMORY_DIR, "daily_context.json")
    try:
        atomic_write_json(output_path, context)
        logger.info(f"Daily context saved to {output_path}")
    except Exception as e:
        logger.error(f"Error saving daily_context.json: {e}")

    return context


def get_coordination_context():
    """
    Returns a 3-5 line summary for system prompt injection.
    Format:
    ## Coordination Intelligence
    Growth edges: [area1], [area2]. Hot topics: [topic1], [topic2].
    Best message types: [type1], [type2]. Avoid: [type3].
    Voice trend: [trend]. Recommended archetype: [archetype].
    Curiosity follow-through: [rate]%. Best question types: [types].
    """
    try:
        context_path = os.path.join(MEMORY_DIR, "daily_context.json")
        with open(context_path, "r") as f:
            context = json.load(f)
    except Exception as e:
        logger.error(f"Error reading daily_context.json: {e}")
        return "## Coordination Intelligence\n(No coordination data available)"

    growth_areas = [e["area"] for e in context.get("growth_edges", [])[:2]]
    hot_topics = [t["topic"] for t in context.get("hot_topics", [])[:2]]
    high_depth = context.get("high_depth_message_types", [])[:2]
    low_depth = context.get("low_depth_message_types", [0])[0] if context.get("low_depth_message_types") else "generic"
    voice_trend = context.get("voice_trend", "stable")
    archetype = context.get("recommended_archetype", "Balanced")
    followthrough = int(context.get("curiosity_followthrough_rate", 0) * 100)
    best_curiosity = context.get("best_curiosity_types", [])[:2]

    summary = f"""## Coordination Intelligence
Growth edges: {', '.join(growth_areas) or 'none identified'}. Hot topics: {', '.join(hot_topics) or 'none tracked'}.
Best message types: {', '.join(high_depth) or 'mixed'}. Avoid: {low_depth}.
Voice trend: {voice_trend}. Recommended archetype: {archetype}.
Curiosity follow-through: {followthrough}%. Best question types: {', '.join(best_curiosity) or 'exploring'}."""

    return summary


def get_recommended_topics():
    """
    Returns 3 topics combining growth edges + hot topics + contradictions.
    Prefers recent hot topics and active growth areas.
    """
    try:
        context_path = os.path.join(MEMORY_DIR, "daily_context.json")
        with open(context_path, "r") as f:
            context = json.load(f)
    except Exception as e:
        logger.error(f"Error reading daily_context.json: {e}")
        return ["general exploration", "knowledge synthesis", "growth tracking"]

    topics = []

    # Add from growth edges
    for edge in context.get("growth_edges", [])[:1]:
        topics.append(f"deepening {edge['area']}")

    # Add from hot topics
    for topic in context.get("hot_topics", [])[:2]:
        topics.append(topic["topic"][:50])

    # Add from contradictions if space remains
    for contra in context.get("active_contradictions", []):
        if len(topics) < 3:
            topics.append(f"exploring {contra['name'][:40]}")

    # Pad to 3 if needed
    defaults = ["knowledge synthesis", "pattern discovery", "growth exploration"]
    while len(topics) < 3:
        topics.append(defaults[len(topics)])

    return topics[:3]


def get_archetype_recommendation():
    """
    Recommends which archetype to foreground based on data patterns.
    - Psyche: if contradictions active and growing
    - Beatrice: if growth edges expanding (>2 active areas)
    - Daimon: if stagnation detected
    - Muse: if creative or dialogue-heavy topics hot
    """
    try:
        context_path = os.path.join(MEMORY_DIR, "daily_context.json")
        with open(context_path, "r") as f:
            context = json.load(f)
    except Exception as e:
        logger.error(f"Error reading daily_context.json: {e}")
        return "Balanced"

    stagnation = context.get("stagnation_alerts", [])
    if stagnation:
        return "Daimon"

    growth_edges = context.get("growth_edges", [])
    if len(growth_edges) >= 2:
        return "Beatrice"

    contradictions = context.get("active_contradictions", [])
    if len(contradictions) >= 2:
        return "Psyche"

    hot_topics = context.get("hot_topics", [])
    creative_keywords = ["creative", "art", "writing", "dialogue", "narrative"]
    for topic in hot_topics:
        if any(k in topic["topic"].lower() for k in creative_keywords):
            return "Muse"

    return "Beatrice"  # Default: growth-oriented


def detect_stagnation(days=14):
    """
    Check if any key metrics have plateaued over the specified days.
    Returns list of alert strings describing stagnation.
    """
    alerts = []

    # Check curiosity followthrough trend
    try:
        context_path = os.path.join(MEMORY_DIR, "daily_context.json")
        with open(context_path, "r") as f:
            context = json.load(f)

        followthrough = context.get("curiosity_followthrough_rate", 0)
        if followthrough < 0.3:
            alerts.append("Low curiosity follow-through (<30%)")

        hot_topics = context.get("hot_topics", [])
        if len(hot_topics) == 0:
            alerts.append("No hot topics tracked")

        # Check if growth edges are stagnant
        growth_edges = context.get("growth_edges", [])
        if len(growth_edges) == 0:
            alerts.append("No active growth edges detected")

        # Check if high-depth message types exist
        high_depth = context.get("high_depth_message_types", [])
        if len(high_depth) == 0:
            alerts.append("No high-depth message patterns identified")

    except Exception as e:
        logger.error(f"Error detecting stagnation: {e}")

    return alerts


if __name__ == "__main__":
    # CLI interface for testing
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "build":
            context = build_daily_context()
            print(json.dumps(context, indent=2))
        elif command == "summary":
            print(get_coordination_context())
        elif command == "topics":
            print(get_recommended_topics())
        elif command == "archetype":
            print(get_archetype_recommendation())
        elif command == "stagnation":
            print(detect_stagnation())
        else:
            print(f"Unknown command: {command}")
            print("Available: build, summary, topics, archetype, stagnation")
    else:
        # Default: build and print summary
        context = build_daily_context()
        print("\n" + get_coordination_context() + "\n")
