f"""
Message Quality Assessment Module

Implements:
  - Resonance-Driven Synthesis Targeting (Idea 6): Tracks and prioritizes notes {USER_NAME} frequently revisits
  - Would {USER_NAME} Care? Quality Gate (Idea 8): Scores proactive messages for relevance and timing

All scoring is heuristic-based using keyword matching and simple math—no ML or embeddings.
Thread-safe file access with logging for debugging and metrics.
"""

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# Module-level constants
MEMORY_DIR = Path.home() / "alicia" / "memory"
VAULT_ROOT = Path.home() / "alicia" / "vault"
HOT_TOPICS_PATH = MEMORY_DIR / "hot_topics.md"
PROMPT_EFFECTIVENESS_PATH = MEMORY_DIR / "prompt_effectiveness.tsv"
RESONANCE_PATH = MEMORY_DIR / "resonance.md"

# Thread-safe file access
_file_lock = threading.Lock()

# Configure logging
logger = logging.getLogger(__name__)

# Stopwords for keyword overlap calculation (50-80 words)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "must", "can", "this", "that", "these", "those", "i", "you", "he", "she",
    "it", "we", "they", "what", "which", "who", "when", "where", "why", "how",
    "as", "if", "all", "each", "every", "both", "few", "more", "most", "some",
    "any", "no", "not", "only", "same", "so", "such", "than", "too", "very"
}

# Daily quality tracking file
QUALITY_LOG_PATH = MEMORY_DIR / "quality_log.txt"


def get_resonance_priorities() -> list[dict]:
    f"""
    Read resonance.md to identify notes {USER_NAME} frequently asks to hear aloud.

    Counts frequency of each note title and applies weighting:
    - 3+ reads: 2x weight
    - Referenced in conversation: 3x weight

    Returns:
        List of dicts with {{"title": str, "count": int, "last_read": str}}
        sorted by count descending.
    """
    try:
        with _file_lock:
            if not RESONANCE_PATH.exists():
                logger.debug(f"Resonance file not found: {RESONANCE_PATH}")
                return []

            content = RESONANCE_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read resonance file: {e}")
        return []

    # Parse resonance.md format: expected to have entries like:
    # ## Note Title
    # Read: 2024-04-10, 2024-04-11, 2024-04-12
    # Referenced: 2024-04-09

    priorities = {}
    lines = content.split("\n")
    current_note = None

    for line in lines:
        line = line.strip()
        if line.startswith("##"):
            current_note = line.replace("##", "").strip()
            priorities[current_note] = {"count": 0, "last_read": "", "referenced": 0}
        elif line.startswith("Read:") and current_note:
            dates = [d.strip() for d in line.replace("Read:", "").split(",")]
            priorities[current_note]["count"] += len(dates)
            if dates:
                priorities[current_note]["last_read"] = dates[-1]
        elif line.startswith("Referenced:") and current_note:
            ref_count = len([d.strip() for d in line.replace("Referenced:", "").split(",")])
            priorities[current_note]["referenced"] = ref_count

    # Apply weighting: 3+ reads = 2x, referenced = 3x
    weighted_priorities = []
    for title, data in priorities.items():
        weight = 1.0
        if data["count"] >= 3:
            weight *= 2.0
        if data["referenced"] > 0:
            weight *= 3.0

        weighted_count = int(data["count"] * weight)
        weighted_priorities.append({
            "title": title,
            "count": weighted_count,
            "last_read": data["last_read"]
        })

    # Sort by count descending
    weighted_priorities.sort(key=lambda x: x["count"], reverse=True)
    logger.debug(f"Loaded {len(weighted_priorities)} resonance priorities")
    return weighted_priorities


def build_resonance_biased_context(resonance_data: list[dict]) -> str:
    """
    Build context string for synthesis prompts using resonance priorities.

    Args:
        resonance_data: List from get_resonance_priorities()

    Returns:
        Context string highlighting priority sources, or empty string if no data.
    """
    if not resonance_data:
        return ""

    top_titles = [item["title"] for item in resonance_data[:5]]
    titles_str = ", ".join(top_titles)
    context = f"Priority sources ({USER_NAME} keeps returning to these): {titles_str}"
    logger.debug(f"Built resonance context: {context}")
    return context


def _load_hot_topics() -> str:
    """Load content from hot_topics.md."""
    try:
        with _file_lock:
            if not HOT_TOPICS_PATH.exists():
                logger.debug(f"Hot topics file not found: {HOT_TOPICS_PATH}")
                return ""
            return HOT_TOPICS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read hot topics: {e}")
        return ""


def _load_prompt_effectiveness() -> list[dict]:
    """
    Parse prompt_effectiveness.tsv into list of dicts.

    Expected format:
    prompt_text    depth_score    success_flag
    ...
    """
    try:
        with _file_lock:
            if not PROMPT_EFFECTIVENESS_PATH.exists():
                logger.debug(f"Prompt effectiveness file not found: {PROMPT_EFFECTIVENESS_PATH}")
                return []

            content = PROMPT_EFFECTIVENESS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read prompt effectiveness: {e}")
        return []

    records = []
    lines = content.strip().split("\n")

    # Skip header if present
    start_idx = 1 if lines and lines[0].lower().startswith("prompt") else 0

    for line in lines[start_idx:]:
        if not line.strip():
            continue

        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                record = {
                    "prompt": parts[0].strip(),
                    "depth_score": float(parts[1].strip()),
                    "success": parts[2].strip().lower() == "true" if len(parts) > 2 else True
                }
                records.append(record)
            except ValueError:
                continue

    logger.debug(f"Loaded {len(records)} prompt effectiveness records")
    return records


def _keyword_overlap(text1: str, text2: str) -> float:
    """
    Calculate Jaccard similarity between two texts (word-level, ignoring stopwords).

    Args:
        text1: First text
        text2: Second text

    Returns:
        Jaccard similarity score (0.0 to 1.0)
    """
    def extract_keywords(text: str) -> set:
        words = text.lower().split()
        return {w.strip(".,!?;:") for w in words if w.strip(".,!?;:") not in STOPWORDS}

    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)

    if not keywords1 or not keywords2:
        return 0.0

    intersection = len(keywords1 & keywords2)
    union = len(keywords1 | keywords2)

    return intersection / union if union > 0 else 0.0


def would_hector_care(message_text: str) -> float:
    """
    Score a proposed proactive message on relevance and timing (0.0-1.0).

    Scoring factors:
      a. Hot topic match (0-0.4): Keywords from hot_topics.md in message
      b. Depth signal (0-0.3): Similarity to high-depth past prompts
      c. Time since last message (0-0.2): Longer gap = higher score
      d. Novelty (0-0.1): Concepts not in hot_topics = bonus

    Returns:
        Score 0.0-1.0. Returns 0.5 on file errors (neutral, don't block).
    """
    score = 0.0

    # Load reference data
    hot_topics_content = _load_hot_topics()
    prompt_effectiveness = _load_prompt_effectiveness()
    last_proactive_time = _get_last_proactive_sent()

    # If we can't load any critical files, return neutral (don't block on errors)
    if not hot_topics_content and not prompt_effectiveness:
        logger.warning("No reference data available for scoring")
        return 0.5

    # Factor a: Hot topic match (0-0.4)
    hot_topic_score = 0.0
    if hot_topics_content:
        def count_matching_topics(text: str) -> int:
            text_lower = text.lower()
            content_lower = hot_topics_content.lower()
            lines = content_lower.split("\n")
            matches = 0
            for line in lines:
                # Extract potential topics (simple heuristic: lines with words)
                if line.strip() and len(line.strip()) > 3:
                    if any(word in text_lower for word in line.split()):
                        matches += 1
            return matches

        topic_count = count_matching_topics(message_text)
        hot_topic_score = min(0.4, topic_count * 0.1)
        logger.debug(f"Hot topic score: {hot_topic_score} (matches: {topic_count})")

    score += hot_topic_score

    # Factor b: Depth signal (0-0.3)
    depth_score = 0.0
    if prompt_effectiveness:
        overlaps = []
        for record in prompt_effectiveness:
            overlap = _keyword_overlap(message_text, record["prompt"])
            if overlap > 0.1:  # Only consider reasonably similar prompts
                overlaps.append((overlap, record["depth_score"]))

        if overlaps:
            overlaps.sort(reverse=True, key=lambda x: x[0])
            top_overlaps = overlaps[:3]
            avg_depth = sum(depth for _, depth in top_overlaps) / len(top_overlaps)
            depth_score = min(0.3, avg_depth * 0.3)
            logger.debug(f"Depth score: {depth_score} (similar prompts: {len(overlaps)})")

    score += depth_score

    # Factor c: Time since last message (0-0.2)
    time_score = 0.0
    if last_proactive_time:
        try:
            last_sent = datetime.fromisoformat(last_proactive_time)
            time_diff = datetime.now() - last_sent
            hours_since = time_diff.total_seconds() / 3600
            # Logarithmic scaling: 1 hour = 0.05, 24 hours = 0.2
            time_score = min(0.2, (hours_since ** 0.5) * 0.04)
            logger.debug(f"Time score: {time_score} (hours since last: {hours_since:.1f})")
        except Exception as e:
            logger.debug(f"Could not parse last proactive time: {e}")
            time_score = 0.1  # Default to moderate score if unparseable

    score += time_score

    # Factor d: Novelty bonus (0-0.1)
    novelty_score = 0.0
    if hot_topics_content:
        hot_words = set()
        for line in hot_topics_content.lower().split("\n"):
            hot_words.update(line.split())

        message_keywords = set(message_text.lower().split())
        novel_keywords = message_keywords - hot_words - STOPWORDS
        novelty_ratio = len(novel_keywords) / max(len(message_keywords), 1)

        # Bonus for mostly novel content
        if novelty_ratio > 0.4:
            novelty_score = 0.1
        elif novelty_ratio > 0.2:
            novelty_score = 0.05

        logger.debug(f"Novelty score: {novelty_score} (ratio: {novelty_ratio:.2f})")

    score += novelty_score

    # Cap at 1.0
    final_score = min(1.0, score)
    logger.debug(f"Final would_hector_care score: {final_score}")
    return final_score


def record_proactive_timestamp() -> None:
    """Record the current time as the last proactive message sent."""
    try:
        with _file_lock:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            timestamp_file = MEMORY_DIR / "last_proactive_sent.txt"
            timestamp_file.write_text(datetime.now().isoformat(), encoding="utf-8")
            logger.debug("Recorded proactive message timestamp")
    except Exception as e:
        logger.error(f"Failed to record proactive timestamp: {e}")


def _get_last_proactive_sent() -> Optional[str]:
    """Internal helper to get last proactive message timestamp."""
    try:
        with _file_lock:
            timestamp_file = MEMORY_DIR / "last_proactive_sent.txt"
            if timestamp_file.exists():
                return timestamp_file.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.debug(f"Failed to read last proactive sent: {e}")
    return None


def get_quality_stats() -> dict:
    """
    Get quality assessment statistics for today.

    Returns:
        {"avg_score": float, "messages_gated_today": int, "messages_passed_today": int}
    """
    try:
        with _file_lock:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            if not QUALITY_LOG_PATH.exists():
                logger.debug("No quality log found, returning zeros")
                return {
                    "avg_score": 0.0,
                    "messages_gated_today": 0,
                    "messages_passed_today": 0
                }

            content = QUALITY_LOG_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read quality log: {e}")
        return {
            "avg_score": 0.5,
            "messages_gated_today": 0,
            "messages_passed_today": 0
        }

    # Parse simple CSV format: timestamp,score,passed
    today = datetime.now().date()
    scores = []
    gated_count = 0
    passed_count = 0

    for line in content.strip().split("\n"):
        if not line.strip():
            continue

        parts = line.split(",")
        if len(parts) >= 3:
            try:
                timestamp_str = parts[0].strip()
                score = float(parts[1].strip())
                passed = parts[2].strip().lower() == "true"

                # Parse date from ISO format timestamp
                entry_date = datetime.fromisoformat(timestamp_str).date()
                if entry_date == today:
                    scores.append(score)
                    if passed:
                        passed_count += 1
                    else:
                        gated_count += 1
            except (ValueError, IndexError):
                continue

    avg_score = sum(scores) / len(scores) if scores else 0.0

    stats = {
        "avg_score": avg_score,
        "messages_gated_today": gated_count,
        "messages_passed_today": passed_count
    }

    logger.debug(f"Quality stats: {stats}")
    return stats


def _record_quality_score(score: float, passed: bool) -> None:
    """
    Internal helper to record a quality score to the daily log.

    Args:
        score: Message quality score (0.0-1.0)
        passed: Whether message passed the quality gate (threshold > 0.3)
    """
    try:
        with _file_lock:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat()
            entry = f"{timestamp},{score:.3f},{str(passed).lower()}\n"

            with QUALITY_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(entry)

            logger.debug(f"Recorded quality score: {score}, passed: {passed}")
    except Exception as e:
        logger.error(f"Failed to record quality score: {e}")


# Public constants for threshold
DEFAULT_CARE_THRESHOLD = 0.3
