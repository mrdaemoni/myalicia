"""
Alicia's Feedback Loop Engine

Closes the gap between output and learning. Tracks what lands,
coordinates analysis module outputs, and provides learned context
for system prompt enrichment and proactive message targeting.
"""

import os
import json
import csv
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from myalicia.skills.safe_io import atomic_write_json
from myalicia.skills.bridge_protocol import get_latest_report
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger("alicia")

# Paths
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
REACTION_LOG = os.path.join(MEMORY_DIR, "reaction_log.tsv")
PROMPT_TRACKING = os.path.join(MEMORY_DIR, "prompt_effectiveness.tsv")
ANALYSIS_INSIGHTS = os.path.join(MEMORY_DIR, "analysis_insights.md")
EFFECTIVENESS_STATE = os.path.join(MEMORY_DIR, "effectiveness_state.json")
BRIDGE_DIR = str(config.vault.bridge_path)
EMERGENCE_STATE = os.path.join(MEMORY_DIR, "emergence_state.json")

# Daimon comfort topics — patterns that indicate staying safe rather than growing
COMFORT_INDICATORS = [
    "morning routine", "daily practice", "what you already know",
    "favorite quote", "familiar territory", "review", "recap",
]
GROWTH_INDICATORS = [
    "tension", "contradiction", "edge", "unresolved", "challenge",
    "bridge", "unexplored", "gap", "dormant", "uncomfortable",
]


def analyze_message_effectiveness(days: int = 30) -> dict:
    """
    Analyze which proactive message types get the best engagement.

    Reads reaction_log.tsv and prompt_effectiveness.tsv to compute:
    - avg depth per message type
    - response rate per message type
    - best/worst performing types
    - archetype effectiveness (if tracked)

    Returns:
        dict with keys: type_scores, best_types, worst_types, archetype_scores
    """
    type_scores = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Read prompt effectiveness (response tracking)
    try:
        if os.path.exists(PROMPT_TRACKING):
            with open(PROMPT_TRACKING, 'r') as f:
                reader = csv.reader(f, delimiter='\t')
                for row in reader:
                    if len(row) < 6:
                        continue
                    try:
                        ts_str, msg_type, topic, resp_len, insight_score, depth = row[:6]
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        if msg_type not in type_scores:
                            type_scores[msg_type] = {
                                "sent": 0, "responded": 0,
                                "total_depth": 0, "total_insight": 0,
                            }
                        type_scores[msg_type]["sent"] += 1
                        resp = int(resp_len) if resp_len else 0
                        if resp > 0:
                            type_scores[msg_type]["responded"] += 1
                        depth_val = float(depth) if depth else 0
                        type_scores[msg_type]["total_depth"] += depth_val
                        insight_val = float(insight_score) if insight_score else 0
                        type_scores[msg_type]["total_insight"] += insight_val
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.debug(f"Error reading prompt tracking: {e}")

    # Read reaction log (emoji engagement)
    try:
        if os.path.exists(REACTION_LOG):
            with open(REACTION_LOG, 'r') as f:
                reader = csv.reader(f, delimiter='\t')
                for row in reader:
                    if len(row) < 5:
                        continue
                    try:
                        ts_str, msg_type, topic, emoji, depth = row[:5]
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        if msg_type not in type_scores:
                            type_scores[msg_type] = {
                                "sent": 0, "responded": 0,
                                "total_depth": 0, "total_insight": 0,
                            }
                        # Reactions count as engagement
                        type_scores[msg_type]["responded"] += 1
                        type_scores[msg_type]["total_depth"] += float(depth)
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.debug(f"Error reading reaction log: {e}")

    # Compute averages
    for msg_type, data in type_scores.items():
        sent = max(data["sent"], 1)
        data["avg_depth"] = round(data["total_depth"] / sent, 2)
        data["response_rate"] = round(data["responded"] / sent, 2)
        data["avg_insight"] = round(data["total_insight"] / sent, 2)

    # Rank
    sorted_types = sorted(
        type_scores.items(),
        key=lambda x: x[1]["avg_depth"],
        reverse=True,
    )
    best_types = [t[0] for t in sorted_types[:3] if t[1]["avg_depth"] > 0]
    worst_types = [t[0] for t in sorted_types[-3:] if t[1]["sent"] > 2]

    result = {
        "type_scores": type_scores,
        "best_types": best_types,
        "worst_types": worst_types,
        "analyzed_days": days,
    }

    # Persist
    try:
        atomic_write_json(EFFECTIVENESS_STATE, result)
    except Exception as e:
        logger.debug(f"Could not save effectiveness state: {e}")

    return result


def get_effectiveness_summary() -> str:
    """
    One-paragraph summary of message effectiveness for system prompt injection.

    Returns:
        str: Natural language summary of what's working and what's not.
    """
    try:
        if os.path.exists(EFFECTIVENESS_STATE):
            with open(EFFECTIVENESS_STATE, 'r') as f:
                state = json.load(f)
        else:
            state = analyze_message_effectiveness()

        if not state.get("type_scores"):
            return ""

        best = state.get("best_types", [])
        worst = state.get("worst_types", [])

        parts = []
        if best:
            best_str = ", ".join(best[:2])
            parts.append(f"Messages that land best: {best_str}")
        if worst:
            worst_str = ", ".join(worst[:2])
            parts.append(f"Lower engagement: {worst_str}")

        return ". ".join(parts) + "." if parts else ""
    except Exception as e:
        logger.debug(f"Could not get effectiveness summary: {e}")
        return ""


def get_latest_analysis_context() -> str:
    """
    Read the most recent analysis module outputs and build a unified context string.

    Checks Bridge/ for contradiction, growth-edge, and dialogue-depth reports.
    Returns a compact summary for system prompt injection.
    """
    context_parts = []

    try:
        # Find most recent contradiction report
        contradictions = _read_latest_bridge_report("contradiction-report")
        if contradictions:
            context_parts.append(f"Active vault tensions: {contradictions}")

        # Find most recent growth edge report
        growth_edges = _read_latest_bridge_report("growth-edge-report")
        if growth_edges:
            context_parts.append(f"Current growth edges: {growth_edges}")

        # Find most recent dialogue depth insights
        depth = _read_latest_bridge_report("dialogue-depth-report")
        if depth:
            context_parts.append(f"Dialogue patterns: {depth}")
    except Exception as e:
        logger.debug(f"Could not read analysis context: {e}")

    return " | ".join(context_parts) if context_parts else ""


def _read_latest_bridge_report(prefix: str, max_chars: int = 200) -> str:
    """Read the most recent Bridge report matching prefix, return summary.

    Routes through bridge_protocol.get_latest_report for a uniform
    discovery path (no more ad-hoc os.listdir + filter loops).
    """
    try:
        path = get_latest_report(prefix)
        if not path:
            return ""
        with open(path, 'r') as f:
            content = f.read()
        # Extract first meaningful section (skip header)
        lines = content.split('\n')
        body_lines = [l for l in lines if l.strip() and not l.startswith('#')]
        summary = ' '.join(body_lines[:5])[:max_chars]
        return summary.strip() if summary.strip() else ""
    except Exception as e:
        logger.debug(f"Could not read bridge report {prefix}: {e}")
        return ""


def get_growth_edges_for_challenge() -> list:
    """
    Extract active growth edges from the latest report for Psyche challenge targeting.

    Returns:
        list of dicts: [{"area": str, "evidence": str}, ...]
    """
    try:
        path = get_latest_report("growth-edge-report")
        if not path:
            return []
        with open(path, 'r') as f:
            content = f.read()

        # Parse growth edges from markdown (look for growth edge section)
        edges = []
        in_edges = False
        current_edge = {}
        for line in content.split('\n'):
            if "growth edge" in line.lower() or "expanding" in line.lower():
                in_edges = True
                continue
            if in_edges and line.startswith("- "):
                text = line.lstrip("- ").strip()
                if text:
                    edges.append({"area": text[:100], "evidence": ""})
            if in_edges and line.startswith("#"):
                in_edges = False

        return edges[:5]  # Top 5 edges
    except Exception as e:
        logger.debug(f"Could not extract growth edges: {e}")
        return []


def get_contradictions_for_challenge() -> list:
    """
    Extract active contradictions from the latest report for Psyche challenge targeting.

    Returns:
        list of dicts: [{"tension": str, "severity": str}, ...]
    """
    try:
        path = get_latest_report("contradiction-report")
        if not path:
            return []
        with open(path, 'r') as f:
            content = f.read()

        # Parse tensions from markdown
        tensions = []
        for line in content.split('\n'):
            line_lower = line.lower()
            if "tension" in line_lower or "contradiction" in line_lower:
                text = line.lstrip("#- ").strip()
                if len(text) > 20:
                    tensions.append({"tension": text[:150], "severity": "moderate"})

        return tensions[:3]  # Top 3
    except Exception as e:
        logger.debug(f"Could not extract contradictions: {e}")
        return []


def get_emergence_context() -> str:
    """
    Read current emergence state for system prompt injection.

    Returns:
        str: Natural language context about Alicia's current season and growth.
    """
    try:
        if not os.path.exists(EMERGENCE_STATE):
            return ""
        with open(EMERGENCE_STATE, 'r') as f:
            state = json.load(f)
        season = state.get("season", "First Light")
        score = state.get("score", 0)
        metrics = state.get("metrics", {})
        days = metrics.get("days_breathing", 0)
        connections = metrics.get("connections_woven", 0)
        threads = metrics.get("threads_pulled", 0)

        # Archetype flavor surfaced today
        flavors = state.get("archetype_flavors_today", [])
        flavor_str = ""
        if flavors:
            archetype_names = [f.get("archetype", "") for f in flavors]
            flavor_str = f" Today's archetype voices: {', '.join(archetype_names)}."

        return (
            f"I am in my {season} season (emergence {score}, "
            f"{days} days breathing, {connections} connections woven, "
            f"{threads} threads pulled).{flavor_str}"
        )
    except Exception as e:
        logger.debug(f"Could not read emergence context: {e}")
        return ""


def daimon_pre_send_check(message: str) -> dict:
    f"""
    Daimon archetype: check a proactive message before sending.

    Detects comfort bias — messages that keep {USER_NAME} in familiar territory
    instead of pushing toward growth edges.

    Args:
        message: the proactive message text to check

    Returns:
        dict with keys:
            - approved: bool (True if message should send)
            - reason: str (why it was flagged, if flagged)
            - suggestion: str (alternative framing, if flagged)
    """
    msg_lower = message.lower()

    # Count comfort vs growth signals
    comfort_count = sum(1 for c in COMFORT_INDICATORS if c in msg_lower)
    growth_count = sum(1 for g in GROWTH_INDICATORS if g in msg_lower)

    # If heavily comfort-biased and we have growth edges available
    if comfort_count >= 2 and growth_count == 0:
        edges = get_growth_edges_for_challenge()
        if edges:
            edge_text = edges[0].get("area", "an unresolved tension")
            return {
                "approved": False,
                "reason": "Comfort bias detected — this message stays in safe territory",
                "suggestion": f"Consider referencing: {edge_text}",
            }

    return {"approved": True, "reason": "", "suggestion": ""}


def detect_conversation_thread(user_text: str, recent_topics: list = None) -> str | None:
    """
    Ariadne archetype: detect when current conversation connects to an older thread.

    Lightweight check — looks for topic overlap between current message
    and recent session threads.

    Args:
        user_text: current message text
        recent_topics: list of recent session thread topics (from session_threads.json)

    Returns:
        str: thread connection hint, or None if no thread detected
    """
    if not recent_topics:
        return None

    user_words = set(user_text.lower().split())
    # Remove common words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "i", "you", "we",
        "it", "this", "that", "in", "on", "at", "to", "for", "of", "and",
        "but", "or", "not", "so", "can", "do", "did", "have", "has", "had",
        "my", "your", "about", "what", "how", "why", "when", "think",
        "know", "just", "like", "with", "from", "been", "more", "some",
    }
    user_words -= stop_words

    if len(user_words) < 3:
        return None

    best_match = None
    best_overlap = 0

    for thread in recent_topics:
        thread_topic = thread.get("topic", "")
        thread_summary = thread.get("summary", "")
        thread_text = f"{thread_topic} {thread_summary}".lower()
        thread_words = set(thread_text.split()) - stop_words

        overlap = len(user_words & thread_words)
        if overlap > best_overlap and overlap >= 2:
            best_overlap = overlap
            ts = thread.get("timestamp", "")
            # Format date nicely
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age = datetime.now(timezone.utc) - dt
                if age.days > 0:
                    when = f"{age.days} days ago"
                else:
                    hours = age.seconds // 3600
                    when = f"{hours} hours ago" if hours > 0 else "earlier today"
            except (ValueError, TypeError):
                when = "recently"

            mode = thread.get("mode", "conversation")
            shared_words = user_words & thread_words
            topic_hint = thread_topic if thread_topic else ", ".join(list(shared_words)[:3])
            best_match = {
                "when": when,
                "mode": mode,
                "topic": topic_hint,
                "overlap": overlap,
            }

    if best_match and best_match["overlap"] >= 2:
        mode_label = best_match["mode"]
        return (
            f"You touched on this {best_match['when']} "
            f"during a {mode_label} — the thread about {best_match['topic']} is pulling."
        )

    return None


def get_recent_session_topics(limit: int = 20) -> list:
    """
    Load recent session thread topics for thread detection.

    Returns:
        list of dicts with keys: topic, summary, timestamp, mode
    """
    try:
        threads_path = os.path.join(MEMORY_DIR, "session_threads.json")
        if not os.path.exists(threads_path):
            return []
        with open(threads_path, 'r') as f:
            data = json.load(f)

        threads = data if isinstance(data, list) else data.get("threads", [])
        # Sort by timestamp descending, take most recent
        threads.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
        return [
            {
                "topic": t.get("topic", ""),
                "summary": t.get("summary", "")[:200],
                "timestamp": t.get("timestamp", ""),
                "mode": t.get("mode", "conversation"),
            }
            for t in threads[:limit]
        ]
    except Exception as e:
        logger.debug(f"Could not load session topics: {e}")
        return []


def build_learned_context() -> str:
    """
    Build the full learned context string for system prompt injection.

    Combines: emergence state + analysis insights + effectiveness learning.

    Returns:
        str: Multi-line context for system prompt (or empty string)
    """
    parts = []

    # Emergence state
    emergence = get_emergence_context()
    if emergence:
        parts.append(emergence)

    # Analysis insights
    analysis = get_latest_analysis_context()
    if analysis:
        parts.append(analysis)

    # Effectiveness learning
    effectiveness = get_effectiveness_summary()
    if effectiveness:
        parts.append(effectiveness)

    return "\n".join(parts) if parts else ""


def run_daily_effectiveness_update() -> dict:
    """
    Daily scheduled task: recompute message effectiveness from tracking data.
    Designed to run once daily (e.g., at 22:30).

    Returns:
        dict: effectiveness analysis results
    """
    try:
        result = analyze_message_effectiveness(days=30)
        logger.info(
            f"Effectiveness update: {len(result.get('type_scores', {}))} types tracked, "
            f"best: {result.get('best_types', [])}"
        )
        return result
    except Exception as e:
        logger.error(f"Effectiveness update failed: {e}")
        return {"error": str(e)}
