#!/usr/bin/env python3
"""
Alicia — Skill: Conversation Afterglow
After a /call or /unpack session ends, schedules a follow-up message 2-4 hours later
that connects what was said to something in the vault.
"""

import os
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MEMORY_DIR = str(MEMORY_DIR)
VAULT_ROOT = str(config.vault.root)
AFTERGLOW_STATE_FILE = os.path.join(MEMORY_DIR, "afterglow_queue.json")

# Ensure memory directory exists
Path(MEMORY_DIR).mkdir(parents=True, exist_ok=True)


# ── Utility: File locking ─────────────────────────────────────────────────────

def _read_state() -> list:
    """Read the afterglow state file with locking."""
    try:
        if os.path.exists(AFTERGLOW_STATE_FILE):
            with open(AFTERGLOW_STATE_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read afterglow state: {e}")
    return []


def _write_state(entries: list) -> None:
    """Write the afterglow state file atomically."""
    try:
        atomic_write_json(AFTERGLOW_STATE_FILE, entries)
    except IOError as e:
        logger.error(f"Failed to write afterglow state: {e}")


def _cleanup_old_entries(entries: list) -> list:
    """Remove entries older than 7 days and already delivered."""
    cutoff = datetime.fromisoformat(
        (datetime.utcnow() - timedelta(days=7)).isoformat()
    )
    cleaned = []
    for entry in entries:
        created_at = datetime.fromisoformat(entry.get("created_at", ""))
        if created_at > cutoff:
            cleaned.append(entry)
        elif not entry.get("delivered", False):
            logger.info(f"Keeping undelivered afterglow {entry['id']} (age: 7+ days)")
            cleaned.append(entry)
    return cleaned


# ── Core Functions ───────────────────────────────────────────────────────────

def queue_afterglow(source: str, transcript: str, topic: str = "") -> str:
    """
    Queue a new afterglow entry for delivery 2-4 hours from now.

    Args:
        source: "call" or "unpack"
        transcript: Full transcript of the session
        topic: Optional topic/title for the session

    Returns:
        The entry ID (UUID)

    Max 3 pending at once — if exceeded, oldest undelivered entry is dropped.
    """
    if source not in ("call", "unpack", "walk", "drive"):
        raise ValueError(f"Invalid source: {source}. Must be 'call', 'unpack', 'walk', or 'drive'.")

    entries = _read_state()
    entries = _cleanup_old_entries(entries)

    # Generate delivery time: 2-4 hours from now
    delay_minutes = 120 + (120 * (uuid.uuid4().int % 100) // 100)
    deliver_after = datetime.utcnow() + timedelta(minutes=delay_minutes)

    entry_id = str(uuid.uuid4())
    new_entry = {
        "id": entry_id,
        "source": source,
        "transcript": transcript,
        "topic": topic,
        "created_at": datetime.utcnow().isoformat(),
        "deliver_after": deliver_after.isoformat(),
        "delivered": False,
    }

    entries.append(new_entry)

    # Keep only 3 pending entries; drop oldest if exceeded
    pending = [e for e in entries if not e.get("delivered", False)]
    if len(pending) > 3:
        logger.info(f"Max 3 pending afterglows reached; dropping oldest")
        # Find and remove the oldest undelivered entry
        oldest = min(pending, key=lambda e: e.get("created_at", ""))
        entries = [e for e in entries if e["id"] != oldest["id"]]

    _write_state(entries)
    logger.info(f"Queued afterglow {entry_id} for {source} session")
    return entry_id


def get_pending_afterglows() -> list:
    """
    Returns list of afterglows that are ready for delivery.
    A delivery is ready when:
    - delivered=false
    - current_time > deliver_after
    """
    entries = _read_state()
    entries = _cleanup_old_entries(entries)

    now = datetime.utcnow()
    pending = []

    for entry in entries:
        if entry.get("delivered", False):
            continue
        deliver_after = datetime.fromisoformat(entry.get("deliver_after", ""))
        if now > deliver_after:
            pending.append(entry)

    return pending


def build_afterglow_prompt(entry: dict, vault_context: str) -> dict:
    """
    Build a prompt for Sonnet to generate the afterglow message.

    The prompt instructs Sonnet to:
    1. Recognize the session type (call or unpack) and topic
    2. Read the transcript
    3. Find ONE unexpected connection between the transcript and vault knowledge
    4. Write 2-3 sentences as a warm follow-up (like a friend texting)
    5. End with a question inviting exploration

    Args:
        entry: The afterglow queue entry dict
        vault_context: Relevant vault excerpts/context to pull connections from

    Returns:
        A dict with keys: "system", "messages", "max_tokens"
    """
    source = entry.get("source", "unknown")
    topic = entry.get("topic", "")
    transcript = entry.get("transcript", "")

    # Calculate hours since session
    created_at = datetime.fromisoformat(entry.get("created_at", datetime.utcnow().isoformat()))
    hours_ago = (datetime.utcnow() - created_at).total_seconds() / 3600

    # Build system prompt
    source_label = "call" if source == "call" else "unpack"
    system_prompt = (
        f"{USER_NAME} had a /{source_label} session {hours_ago:.1f} hours ago"
    )
    if topic:
        system_prompt += f" about {topic}"
    system_prompt += (
        ". The transcript is below. Your task:\n\n"
        "1. Find ONE unexpected, insightful connection between what he said "
        "and something in his vault knowledge.\n"
        "2. Write 2-3 sentences as a warm follow-up message — like a friend "
        "texting back after thinking about the conversation.\n"
        f"3. End with a question that invites {USER_NAME} to explore the connection further.\n\n"
        "Keep it genuine, concise, and conversational. No preamble."
    )

    # Build messages array
    messages = [
        {
            "role": "user",
            "content": (
                f"Transcript:\n{transcript}\n\n"
                f"Vault context (for finding connections):\n{vault_context}\n\n"
                "Now write the afterglow follow-up message."
            ),
        }
    ]

    return {
        "system": system_prompt,
        "messages": messages,
        "max_tokens": 400,
    }


def mark_delivered(entry_id: str) -> None:
    """
    Mark an afterglow entry as delivered.

    Args:
        entry_id: The UUID of the entry to mark
    """
    entries = _read_state()
    for entry in entries:
        if entry["id"] == entry_id:
            entry["delivered"] = True
            entry["delivered_at"] = datetime.utcnow().isoformat()
            break
    _write_state(entries)
    logger.info(f"Marked afterglow {entry_id} as delivered")


def get_afterglow_stats() -> dict:
    """
    Return stats about the afterglow system.

    Returns:
        Dict with keys:
        - pending: Count of undelivered afterglows not yet ready
        - ready: Count of undelivered afterglows ready for delivery now
        - delivered_today: Count delivered in the last 24 hours
        - total_delivered: Total count ever delivered
    """
    entries = _read_state()
    entries = _cleanup_old_entries(entries)

    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)

    pending = 0  # Not yet ready
    ready = 0    # Ready now
    delivered_today = 0
    total_delivered = 0

    for entry in entries:
        if entry.get("delivered", False):
            total_delivered += 1
            delivered_at = entry.get("delivered_at", "")
            if delivered_at:
                delivered_time = datetime.fromisoformat(delivered_at)
                if delivered_time > cutoff_24h:
                    delivered_today += 1
        else:
            deliver_after = datetime.fromisoformat(entry.get("deliver_after", ""))
            if now > deliver_after:
                ready += 1
            else:
                pending += 1

    return {
        "pending": pending,
        "ready": ready,
        "delivered_today": delivered_today,
        "total_delivered": total_delivered,
    }


# ── Test / Debug ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test queueing
    test_transcript = f"{USER_NAME}: I was thinking about my patterns...\nAlicia: Tell me more"
    entry_id = queue_afterglow("call", test_transcript, topic="patterns and growth")
    print(f"Queued afterglow: {entry_id}")

    # Test stats
    stats = get_afterglow_stats()
    print(f"Stats: {stats}")

    # Test pending (won't find any since deliver time is 2-4 hours out)
    pending = get_pending_afterglows()
    print(f"Pending afterglows ready now: {len(pending)}")
