"""
Cross-session threading module for the user-Alicia system.

Enables continuity across /unpack, /call, /walk, and /drive sessions by tracking
thematic threads and suggesting connections to related prior discussions.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger(__name__)

# Module-level constants
MEMORY_DIR = str(MEMORY_DIR)
THREADS_FILE = os.path.join(MEMORY_DIR, "session_threads.json")

# Hardcoded stopword list for theme extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "been", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "that", "this", "these",
    "those", "it", "its", "they", "them", "their", "what", "which", "who",
    "whom", "when", "where", "why", "how", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "same", "so", "than", "too", "very", "just", "now", "about",
    "out", "if", "then", "because", "while", "during", "before", "after",
    "above", "below", "up", "down", "through", "into", "across", "between",
    "among", "around", "along", "we", "us", "our", "ours", "you", "your",
    "yours", "he", "him", "his", "she", "her", "hers", "i", "me", "my",
    "mine", "there", "here", "being", "having", "doing", "am", "are", "is",
    "been", "being", "get", "gets", "getting", "got", "gotten", "make",
    "makes", "making", "made", "see", "sees", "seeing", "saw", "seen",
    "think", "thinks", "thinking", "thought", "know", "knows", "knowing",
    "knew", "known", "come", "comes", "coming", "came", "take", "takes",
    "taking", "took", "taken", "use", "uses", "using", "used",
}

# Max threads to keep before pruning
MAX_THREADS = 50
# Days to keep threads for relevance matching
RELEVANCE_WINDOW_DAYS = 30
# Days to prune threads older than
PRUNE_WINDOW_DAYS = 90


def _ensure_memory_dir() -> None:
    """Ensure memory directory exists."""
    Path(MEMORY_DIR).mkdir(parents=True, exist_ok=True)


def _load_threads() -> list[dict]:
    """Load threads from JSON file. Returns empty list if file doesn't exist."""
    _ensure_memory_dir()
    if not os.path.exists(THREADS_FILE):
        return []
    try:
        with open(THREADS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load threads file: {e}")
        return []


def _save_threads(threads: list[dict]) -> None:
    """Save threads to JSON file with thread-safe handling."""
    _ensure_memory_dir()
    try:
        # Atomic write with fsync (crash-safe)
        atomic_write_json(THREADS_FILE, threads)
    except IOError as e:
        logger.error(f"Failed to save threads file: {e}")


def _extract_themes(text: str, n: int = 5) -> list[str]:
    """
    Extract key themes from text using simple frequency analysis.

    Returns up to n most frequent multi-word phrases (1-2 words), excluding stopwords.
    """
    if not text:
        return []

    # Normalize: lowercase, split into words
    words = text.lower().split()
    # Filter: remove stopwords and short words
    filtered = [w.strip(".,!?;:\"'()[]{}") for w in words if w.strip(".,!?;:\"'()[]{}") and len(w) > 2]
    filtered = [w for w in filtered if w not in STOPWORDS and len(w) > 2]

    if len(filtered) < 2:
        return []

    # Build 2-word phrase frequencies
    phrase_freq = {}
    for i in range(len(filtered) - 1):
        phrase = f"{filtered[i]} {filtered[i + 1]}"
        phrase_freq[phrase] = phrase_freq.get(phrase, 0) + 1

    # Also include single words with good frequency
    word_freq = {}
    for word in filtered:
        word_freq[word] = word_freq.get(word, 0) + 1

    # Combine and sort by frequency
    combined = {}
    for phrase, count in phrase_freq.items():
        combined[phrase] = count * 2  # boost 2-word phrases
    for word, count in word_freq.items():
        if count >= 2:  # only include words appearing 2+ times
            combined[word] = combined.get(word, 0) + count

    # Get top N
    sorted_themes = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return [theme[0] for theme in sorted_themes[:n]]


def _prune_old_threads(threads: list[dict]) -> list[dict]:
    """Remove threads older than PRUNE_WINDOW_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRUNE_WINDOW_DAYS)
    pruned = []
    for thread in threads:
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            if thread_date > cutoff:
                pruned.append(thread)
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping malformed thread: {e}")
    return pruned


def _prune_to_max(threads: list[dict]) -> list[dict]:
    """Keep only the MAX_THREADS most recent threads."""
    if len(threads) <= MAX_THREADS:
        return threads
    # Sort by timestamp descending, keep newest
    sorted_threads = sorted(threads, key=lambda t: t.get("timestamp", ""), reverse=True)
    return sorted_threads[:MAX_THREADS]


def save_session_thread(
    source: str,
    topic: str,
    transcript: str,
    summary: str = "",
    probe_rounds: int = 0,
) -> str:
    """
    Save a new session thread.

    Args:
        source: "call", "unpack", "walk", or "drive"
        topic: Brief topic/title for the session
        transcript: Full transcript or text from the session
        summary: Optional 2-3 sentence summary. If empty, generated from transcript.
        probe_rounds: Number of probe rounds (0 for calls)

    Returns:
        Thread ID (UUID string)
    """
    _ensure_memory_dir()

    # Generate thread ID
    thread_id = str(uuid.uuid4())

    # Generate summary if not provided
    if not summary:
        summary = transcript[:200].replace("\n", " ").strip()
        if len(transcript) > 200:
            summary += "..."

    # Extract themes
    themes = _extract_themes(transcript, n=5)

    # Create thread entry
    thread = {
        "id": thread_id,
        "source": source,
        "topic": topic,
        "summary": summary,
        "key_themes": themes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "word_count": len(transcript.split()),
        "probe_rounds": probe_rounds,
    }

    # Load existing threads, add new one
    threads = _load_threads()
    threads.append(thread)

    # Prune old threads and enforce max limit
    threads = _prune_old_threads(threads)
    threads = _prune_to_max(threads)

    # Save
    _save_threads(threads)
    logger.info(f"Saved thread {thread_id} on topic: {topic}")
    return thread_id


def find_related_threads(
    topic: str = "",
    transcript: str = "",
    limit: int = 3,
) -> list[dict]:
    """
    Find threads related to a given topic or transcript.

    Uses Jaccard-like similarity on topic words and key_themes.
    Only considers threads from last RELEVANCE_WINDOW_DAYS.

    Args:
        topic: Topic string to match against
        transcript: Transcript to extract themes from for matching
        limit: Max number of related threads to return

    Returns:
        List of dicts with: id, source, topic, summary, timestamp, similarity_score
        Sorted by similarity_score descending.
    """
    if not topic and not transcript:
        return []

    # Extract query themes
    query_themes = set(_extract_themes(transcript, n=5)) if transcript else set()
    query_words = set(topic.lower().split()) if topic else set()

    # Remove stopwords from query
    query_words = {w for w in query_words if w not in STOPWORDS and len(w) > 2}
    query_set = query_words | query_themes

    if not query_set:
        return []

    # Load threads from relevance window
    all_threads = _load_threads()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RELEVANCE_WINDOW_DAYS)

    recent_threads = []
    for thread in all_threads:
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            if thread_date > cutoff:
                recent_threads.append(thread)
        except ValueError:
            continue

    # Score each thread
    scored = []
    for thread in recent_threads:
        thread_words = set(thread.get("topic", "").lower().split())
        thread_words = {w for w in thread_words if w not in STOPWORDS and len(w) > 2}
        thread_themes = set(thread.get("key_themes", []))
        thread_set = thread_words | thread_themes

        if not thread_set:
            continue

        # Jaccard similarity
        intersection = len(query_set & thread_set)
        union = len(query_set | thread_set)
        similarity = intersection / union if union > 0 else 0

        if similarity > 0:
            scored.append({
                "id": thread.get("id", ""),
                "source": thread.get("source", ""),
                "topic": thread.get("topic", ""),
                "summary": thread.get("summary", ""),
                "timestamp": thread.get("timestamp", ""),
                "similarity_score": round(similarity, 3),
            })

    # Sort by similarity and return top N
    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored[:limit]


def build_thread_connection_message(related_threads: list[dict]) -> str:
    """
    Build a natural language message suggesting thread connections.

    Args:
        related_threads: Output from find_related_threads

    Returns:
        Natural language message or empty string if no threads.
    """
    if not related_threads:
        return ""

    if len(related_threads) == 1:
        thread = related_threads[0]
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            date_str = thread_date.strftime("%A").lower()
        except ValueError:
            date_str = "recently"

        summary_snippet = thread["summary"][:60]
        if len(thread["summary"]) > 60:
            summary_snippet += "..."

        return (
            f"Last {date_str} you were {thread['source']}ing on {thread['topic']} "
            f"and landed on: '{summary_snippet}'. Want to pick up that thread, "
            f"or start fresh?"
        )

    # Multiple threads
    topics_dates = []
    for i, thread in enumerate(related_threads[:2]):
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            date_str = thread_date.strftime("%A").lower()
        except ValueError:
            date_str = "recently"
        topics_dates.append(f"{thread['topic']} from {date_str}")

    topics_str = " and ".join(topics_dates)
    return (
        f"This connects to a couple of recent threads — {topics_str}. "
        f"Any of those worth revisiting?"
    )


def get_recent_threads(days: int = 7, source: str = None) -> list[dict]:
    """
    Get threads from the last N days.

    Args:
        days: Number of days to look back
        source: Optional source filter ("call", "unpack", "walk", "drive")

    Returns:
        List of thread dicts, sorted by timestamp descending.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_threads = _load_threads()

    recent = []
    for thread in all_threads:
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            if thread_date > cutoff:
                if source is None or thread.get("source") == source:
                    recent.append(thread)
        except ValueError:
            continue

    recent.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
    return recent


def get_thread_stats() -> dict:
    """
    Get statistics about all threads.

    Returns:
        Dict with total_threads, threads_this_week, most_common_themes, sources breakdown.
    """
    all_threads = _load_threads()
    week_cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    threads_this_week = 0
    source_counts = {"call": 0, "unpack": 0, "walk": 0, "drive": 0}
    all_themes = []

    for thread in all_threads:
        try:
            thread_date = datetime.fromisoformat(thread["timestamp"].replace("Z", "+00:00"))
            if thread_date > week_cutoff:
                threads_this_week += 1
        except ValueError:
            pass

        source = thread.get("source")
        if source in source_counts:
            source_counts[source] += 1

        all_themes.extend(thread.get("key_themes", []))

    # Find most common themes
    theme_freq = {}
    for theme in all_themes:
        theme_freq[theme] = theme_freq.get(theme, 0) + 1

    sorted_themes = sorted(theme_freq.items(), key=lambda x: x[1], reverse=True)
    most_common = [theme[0] for theme in sorted_themes[:10]]

    return {
        "total_threads": len(all_threads),
        "threads_this_week": threads_this_week,
        "most_common_themes": most_common,
        "sources": source_counts,
    }


def build_thread_summary_prompt(threads: list[dict]) -> dict:
    """
    Build a prompt for weekly thread digest.

    Args:
        threads: List of thread dicts (typically from get_recent_threads)

    Returns:
        Dict with "system", "messages", and "max_tokens" for LLM call.
    """
    source_counts = {"call": 0, "unpack": 0, "walk": 0, "drive": 0}
    thread_summaries = []

    for thread in threads:
        source = thread.get("source")
        if source in source_counts:
            source_counts[source] += 1

        topic = thread.get("topic", "Untitled")
        summary = thread.get("summary", "No summary")
        themes = ", ".join(thread.get("key_themes", []))

        thread_summaries.append(
            f"- [{source.upper()}] {topic}\n  {summary}\n  "
            f"Themes: {themes}"
        )

    thread_text = "\n".join(thread_summaries)
    total_sessions = sum(source_counts.values())

    system_prompt = (
        f"{USER_NAME} had {total_sessions} thinking sessions this week across calls, "
        f"unpacks, walks, and drives. Below are the summaries. Write a brief weekly "
        f"thread digest: What intellectual threads is he pulling on? Any threads that "
        f"should connect but don't yet? 2-3 paragraphs."
    )

    return {
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": f"Session threads this week:\n\n{thread_text}",
            }
        ],
        "max_tokens": 600,
    }
