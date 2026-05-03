"""
Overnight Synthesis module.

After evening conversations, extracts daily themes and builds a synthesis prompt
to find surprising connections overnight. By morning, delivers crystallized insights.

Architecture:
- Lightweight theme extraction from conversation history
- No API calls, prompt building only
- State persistence via JSON
- Thread-safe writes with file locking
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# Module-level constants
MEMORY_DIR = Path.home() / "alicia" / "memory"
VAULT_ROOT = Path.home() / "alicia" / "vault"
SYNTHESIS_DIR = MEMORY_DIR / "synthesis"
OVERNIGHT_STATE_FILE = MEMORY_DIR / "overnight_state.json"

# Ensure directories exist
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

# Common English stopwords for theme extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "i", "you", "he", "she",
    "it", "we", "they", "what", "which", "who", "when", "where", "why",
    "how", "as", "if", "just", "only", "very", "so", "too", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "nor", "my", "your", "his", "her", "its", "our", "their",
}


def extract_day_themes(conversation_history: list[dict]) -> list[str]:
    """
    Extract 3-5 key themes/topics from the day's conversation.

    Args:
        conversation_history: List of {"role": "user"|"assistant", "content": str}

    Returns:
        List of theme strings (3-5 items)
    """
    # Collect all user messages
    user_messages = [
        msg["content"].lower()
        for msg in conversation_history
        if msg.get("role") == "user"
    ]

    if not user_messages:
        logger.warning("No user messages found in conversation history")
        return []

    # Tokenize and count word frequencies
    word_freq = {}
    for message in user_messages:
        # Simple tokenization: split on whitespace and punctuation
        words = message.replace(",", "").replace(".", "").replace("!", "").replace("?", "").split()
        for word in words:
            word = word.strip().lower()
            # Filter: length > 3, not stopword
            if len(word) > 3 and word not in STOPWORDS:
                word_freq[word] = word_freq.get(word, 0) + 1

    # Also extract multi-word phrases (2-3 words, at least one non-stopword)
    phrases = {}
    for message in user_messages:
        words = message.replace(",", "").replace(".", "").replace("!", "").replace("?", "").split()
        # 2-word phrases
        for i in range(len(words) - 1):
            w1, w2 = words[i].lower().strip(), words[i + 1].lower().strip()
            if (len(w1) > 3 and w1 not in STOPWORDS) or (len(w2) > 3 and w2 not in STOPWORDS):
                phrase = f"{w1} {w2}"
                if len(phrase) > 5:  # Meaningful phrases
                    phrases[phrase] = phrases.get(phrase, 0) + 1

    # Combine and sort by frequency
    combined = {**word_freq, **phrases}
    sorted_themes = sorted(combined.items(), key=lambda x: x[1], reverse=True)

    # Return top 3-5 themes
    themes = [theme[0] for theme in sorted_themes[:5]]
    if len(themes) < 3:
        themes = [theme[0] for theme in sorted_themes]

    logger.info(f"Extracted {len(themes)} themes: {themes}")
    return themes


def build_overnight_prompt(themes: list[str], vault_context: str = "", hot_topics: str = "") -> dict:
    """
    Build the prompt for overnight synthesis.

    Args:
        themes: List of key themes from the day
        vault_context: Context from vault notes (optional)
        hot_topics: Hot topics or areas of interest (optional)

    Returns:
        Dict with "system", "messages", and "max_tokens" keys
    """
    themes_str = ", ".join(themes) if themes else "recent conversations"

    system_prompt = (
        f"You are {USER_NAME}'s overnight thinking partner. "
        f"{USER_NAME}'s thinking today centered on these themes: {themes_str}. "
        f"Your job: find ONE surprising connection between today's themes and something in his vault "
        f"or broader knowledge that would surprise him. "
        f"Write it as a 2-3 sentence insight — the kind of thing that crystallizes overnight. "
        f"State it as a claim. Reference specific vault notes with [[wikilinks]] if relevant. "
        f"Be concise, specific, and insightful."
    )

    if vault_context:
        system_prompt += f"\n\nRelevant vault context:\n{vault_context}"

    if hot_topics:
        system_prompt += f"\n\nHot topics: {hot_topics}"

    return {
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Based on these themes from today ({', '.join(themes)}), "
                    f"what's one connection that crystallized overnight?"
                ),
            }
        ],
        "max_tokens": 400,
    }


def save_overnight_result(insight: str, themes: list[str]) -> None:
    """
    Save the overnight synthesis result to state file.

    Args:
        insight: The synthesized insight
        themes: List of themes that led to this insight
    """
    today = datetime.now().strftime("%Y-%m-%d")

    state = {
        "date": today,
        "themes": themes,
        "insight": insight,
        "delivered": False,
    }

    # Thread-safe write
    try:
        # Atomic write with fsync (crash-safe)
        atomic_write_json(OVERNIGHT_STATE_FILE, state)
        logger.info(f"Saved overnight synthesis for {today}")
    except Exception as e:
        logger.error(f"Failed to save overnight result: {e}")
        raise


def get_pending_overnight() -> Optional[dict]:
    """
    Get the pending overnight insight if one exists for today.

    Returns:
        Dict with insight data if pending and undelivered for today, None otherwise
    """
    if not OVERNIGHT_STATE_FILE.exists():
        return None

    try:
        with open(OVERNIGHT_STATE_FILE, "r") as f:
            state = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")

        # Check if this is for today and not yet delivered
        if state.get("date") == today and not state.get("delivered", True):
            return state

        return None
    except Exception as e:
        logger.error(f"Failed to read overnight state: {e}")
        return None


def mark_overnight_delivered() -> None:
    """
    Mark the current overnight insight as delivered.
    """
    if not OVERNIGHT_STATE_FILE.exists():
        logger.warning("No overnight state file to mark delivered")
        return

    try:
        with open(OVERNIGHT_STATE_FILE, "r") as f:
            state = json.load(f)

        state["delivered"] = True

        # Atomic write with fsync (crash-safe)
        atomic_write_json(OVERNIGHT_STATE_FILE, state)

        logger.info("Marked overnight insight as delivered")
    except Exception as e:
        logger.error(f"Failed to mark overnight delivered: {e}")
        raise


def build_morning_delivery(insight: str) -> str:
    """
    Wrap the overnight insight in warm morning context.

    Args:
        insight: The synthesized insight

    Returns:
        Formatted delivery string
    """
    return f"Something crystallized overnight. {insight}"


def should_run_overnight(conversation_history: list[dict]) -> bool:
    """
    Determine if overnight synthesis should run.

    Conditions:
    - Day had >= 5 user messages
    - No overnight already pending for today

    Args:
        conversation_history: List of messages from the day

    Returns:
        True if synthesis should run, False otherwise
    """
    # Count user messages
    user_message_count = sum(1 for msg in conversation_history if msg.get("role") == "user")

    if user_message_count < 5:
        logger.debug(f"Too few user messages ({user_message_count}) for overnight synthesis")
        return False

    # Check if already pending
    if get_pending_overnight() is not None:
        logger.debug("Overnight synthesis already pending for today")
        return False

    logger.info(
        f"Should run overnight synthesis: {user_message_count} user messages, no pending results"
    )
    return True
