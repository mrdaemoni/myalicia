#!/usr/bin/env python3
"""
Thinking Modes — Stream-of-consciousness and rapid synthesis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two new modes beyond /call and /unpack:

/walk — Stream-of-consciousness walking mode
  - Accumulates voice without probing
  - Alicia stays silent, just records
  - Weekly review generates a digest from accumulated transcripts

/drive — Commute mode with rapid synthesis
  - 5-min rapid synthesis mode
  - Alicia reads back a connection from the vault
  - Asks "does that land?" and iterates based on response
  - Extraction at end to capture validated ideas

State machine for walk and drive (independent):
  IDLE → WALK → IDLE
  IDLE → DRIVE → IDLE
"""

import os
import time
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MEMORY_DIR = os.path.expanduser("~/alicia/memory")
VAULT_ROOT = str(config.vault.root)
OBSIDIAN_VAULT = os.path.join(VAULT_ROOT, "Alicia")
INBOX_DIR = os.path.join(OBSIDIAN_VAULT, "Inbox")
LOG_DIR = os.path.expanduser("~/alicia/logs")

# Timeout for drive mode (5 minutes)
DRIVE_TIMEOUT = 300

# Max duration for a single walk session (1 hour)
WALK_MAX_DURATION = 3600

# Max tokens for walk digest generation
WALK_DIGEST_MAX_TOKENS = 800

# Max tokens for drive connection prompt
DRIVE_CONNECTION_MAX_TOKENS = 250

# Max tokens for drive extraction
DRIVE_EXTRACTION_MAX_TOKENS = 500


# ── State Machine ────────────────────────────────────────────────────────────

class ThinkingMode(Enum):
    IDLE = "idle"
    WALK = "walk"
    DRIVE = "drive"


# Global state
_mode = ThinkingMode.IDLE
_started_at = 0.0
_last_activity_at = 0.0
_transcript_chunks = []  # List of {"text": str, "is_voice": bool, "timestamp": str}
_session_topic = ""
_drive_connections_shown = 0  # How many vault connections shown this drive session
_full_transcript = ""

# Ariadne thread-pull state (walk mode orientation markers)
THREAD_PULL_INTERVAL = 360  # 6 minutes between thread-pulls
THREAD_PULL_MIN_WORDS = 80  # Minimum words accumulated before first thread-pull
_last_thread_pull_at = 0.0
_thread_pull_count = 0


# ── State Queries ────────────────────────────────────────────────────────────

def is_thinking_mode_active() -> bool:
    """Check if WALK or DRIVE mode is active."""
    return _mode != ThinkingMode.IDLE


def get_active_mode() -> str:
    """Return 'walk', 'drive', or 'idle'."""
    return _mode.value


def is_walk_active() -> bool:
    """Check if walk mode is active."""
    return _mode == ThinkingMode.WALK


def is_drive_active() -> bool:
    """Check if drive mode is active. Also handles auto-timeout."""
    global _mode
    if _mode != ThinkingMode.DRIVE:
        return False
    # Auto-exit on timeout
    if time.time() - _started_at > DRIVE_TIMEOUT:
        log.info(f"Drive mode auto-ended after {DRIVE_TIMEOUT}s")
        _mode = ThinkingMode.IDLE
        return False
    return True


def get_transcript() -> str:
    """Get the full accumulated transcript."""
    return _full_transcript


def get_word_count() -> int:
    """Get total word count across all chunks."""
    return len(_full_transcript.split())


# ── Ariadne Thread-Pull (walk orientation markers) ──────────────────────────

def should_thread_pull() -> bool:
    """Check if enough time + words have passed for a thread-pull marker."""
    if _mode != ThinkingMode.WALK:
        return False
    now = time.time()
    word_count = len(_full_transcript.split())
    # Need minimum words before first pull
    if word_count < THREAD_PULL_MIN_WORDS:
        return False
    # Need interval since last pull (or since session start for first one)
    last = _last_thread_pull_at if _last_thread_pull_at > 0 else _started_at
    if now - last < THREAD_PULL_INTERVAL:
        return False
    return True


def record_thread_pull():
    """Mark that a thread-pull was just sent."""
    global _last_thread_pull_at, _thread_pull_count
    _last_thread_pull_at = time.time()
    _thread_pull_count += 1


def get_recent_walk_text(last_n_chars: int = 500) -> str:
    """Get the most recent portion of the walk transcript for context."""
    if not _full_transcript:
        return ""
    return _full_transcript[-last_n_chars:]


def get_thread_pull_count() -> int:
    """How many thread-pulls have been sent this session."""
    return _thread_pull_count


# ── WALK MODE ────────────────────────────────────────────────────────────────

def start_walk(topic: str = "") -> str:
    """
    Start walk mode. Returns greeting text.

    In walk mode, Alicia accumulates voice without responding or probing.
    No questions. Just recording. Weekly review will synthesize.
    """
    global _mode, _started_at, _last_activity_at
    global _transcript_chunks, _session_topic, _full_transcript

    _mode = ThinkingMode.WALK
    _started_at = time.time()
    _last_activity_at = time.time()
    _transcript_chunks = []
    _session_topic = topic.strip()
    _full_transcript = ""
    _last_thread_pull_at = 0.0
    _thread_pull_count = 0

    log.info(f"Walk mode started (topic: {topic or 'open'})")

    if topic:
        return f"Just walk and talk about {topic}. I'll keep everything. No questions, no interruptions."
    return "Just walk and talk. I'll keep everything. No questions, no interruptions."


def accumulate_walk(text: str, is_voice: bool = True):
    """Add to walk transcript silently. No response."""
    global _last_activity_at, _full_transcript

    _last_activity_at = time.time()
    _transcript_chunks.append({
        "text": text,
        "is_voice": is_voice,
        "timestamp": datetime.now().strftime("%H:%M"),
    })
    _full_transcript = _build_full_transcript()
    log.info(f"Walk: accumulated {len(text.split())} words (total: {len(_full_transcript.split())})")


def end_walk() -> dict:
    """End walk session and return stats. Saves raw transcript to logs."""
    global _mode

    if _mode != ThinkingMode.WALK:
        return {"was_active": False, "message": "No walk session active."}

    duration = time.time() - _started_at
    chunk_count = len(_transcript_chunks)
    word_count = len(_full_transcript.split())

    _mode = ThinkingMode.IDLE

    # Save transcript to log
    log_path = _save_walk_transcript()

    stats = {
        "was_active": True,
        "duration_seconds": round(duration),
        "chunks": chunk_count,
        "words": word_count,
        "log_path": log_path,
        "message": f"Walk ended. {word_count} words across {chunk_count} voice notes. Saved to logs.",
    }
    log.info(f"Walk session ended: {chunk_count} chunks, {word_count} words. Logged to {log_path}")
    return stats


def _save_walk_transcript() -> str:
    """Save raw walk transcript to logs with date."""
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now()
    filename = f"walk-{now.strftime('%Y-%m-%d')}.txt"
    filepath = os.path.join(LOG_DIR, filename)

    # Append to existing file if it's the same day
    mode = "a" if os.path.exists(filepath) else "w"

    with open(filepath, mode) as f:
        if mode == "a":
            f.write("\n" + "=" * 60 + "\n\n")
        f.write(f"Walk Session — {now.strftime('%Y-%m-%d %H:%M')}\n")
        if _session_topic:
            f.write(f"Topic: {_session_topic}\n")
        f.write(f"Duration: {_format_duration(time.time() - _started_at)}\n")
        f.write(f"Chunks: {len(_transcript_chunks)}\n")
        f.write(f"Words: {len(_full_transcript.split())}\n")
        f.write("=" * 60 + "\n\n")
        f.write(_full_transcript)

    log.info(f"Walk transcript saved: {filepath}")
    return filepath


def get_week_walk_transcripts() -> list[str]:
    """
    Read walk-*.txt files from logs dated within the last 7 days.
    Returns list of transcript contents (each file is one transcript).
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    transcripts = []

    now = datetime.now()
    one_week_ago = now - timedelta(days=7)

    # Look for walk-YYYY-MM-DD.txt files
    for filepath in Path(LOG_DIR).glob("walk-*.txt"):
        try:
            # Extract date from filename: walk-2026-04-12.txt
            date_str = filepath.stem.replace("walk-", "")  # "2026-04-12"
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date >= one_week_ago:
                with open(filepath, "r") as f:
                    content = f.read()
                    if content.strip():
                        transcripts.append(content)
                log.info(f"Loaded walk transcript: {filepath}")
        except (ValueError, IOError) as e:
            log.warning(f"Could not load walk transcript {filepath}: {e}")

    log.info(f"Retrieved {len(transcripts)} walk transcripts from the past week")
    return transcripts


def build_walk_digest_prompt(walk_transcripts: list[str], vault_context: str = "") -> dict:
    """
    Build prompt for weekly walk digest.
    Takes all walk transcripts from the week and synthesizes themes.

    Returns dict with system prompt and messages for API call.
    """
    combined_transcripts = "\n\n".join([
        f"WALK TRANSCRIPT {i+1}:\n{t}"
        for i, t in enumerate(walk_transcripts)
    ])

    system = f"""You are Alicia, synthesizing {USER_NAME}'s week of walking reflections.

He went on several walks this week and talked through ideas. Below are the raw transcripts. Write a short weekly digest:

- What recurring themes appeared across the walks?
- What new ideas emerged?
- What threads are worth bringing into deeper conversation?
- Any patterns in how his thinking evolved?

Keep it to 2-4 paragraphs. Write in narrative form, not bullet points. Focus on signal, not summary.

Rules:
1. Synthesize across transcripts — look for patterns that span multiple walks.
2. Extract new ideas that emerged uniquely this week.
3. Surface connections to his known knowledge clusters if relevant.
4. End with a short "seeds for next conversation" section — 1-2 ideas to explore together.
5. Write for {USER_NAME} — assume he knows his own ideas, you're showing him what emerged."""

    if vault_context:
        system += f"\n\nVault context for reference:\n{vault_context}"

    messages = [{"role": "user", "content": f"Walk transcripts from this week:\n\n{combined_transcripts}"}]

    return {"system": system, "messages": messages, "max_tokens": WALK_DIGEST_MAX_TOKENS}


# ── DRIVE MODE ───────────────────────────────────────────────────────────────

def start_drive(topic: str = "") -> str:
    """
    Start drive mode. Returns greeting text.

    In drive mode, Alicia rapidly shows connections from the vault
    and asks if they land. 5-minute rapid synthesis.
    """
    global _mode, _started_at, _last_activity_at
    global _transcript_chunks, _session_topic, _full_transcript, _drive_connections_shown

    _mode = ThinkingMode.DRIVE
    _started_at = time.time()
    _last_activity_at = time.time()
    _transcript_chunks = []
    _session_topic = topic.strip()
    _full_transcript = ""
    _drive_connections_shown = 0

    log.info(f"Drive mode started (topic: {topic or 'open'})")

    if topic:
        return f"Quick mode — I'll throw you connections around {topic}. You tell me if they land. 5 minutes."
    return "Quick mode — I'll throw you connections from your vault. You tell me if they land. 5 minutes."


def build_drive_connection_prompt(vault_context: str, hot_topics: str = "", previous_shown: list[str] = None) -> dict:
    """
    Build prompt for drive mode connection generation.

    Picks ONE surprising connection from vault related to topic/hot_topics.
    States it in 2 sentences. Asks "Does that land, or should I try another angle?"

    Returns dict with system prompt and messages for API call.
    """
    dont_repeat = ""
    if previous_shown and len(previous_shown) > 0:
        repeated = "\n".join(f"- {conn}" for conn in previous_shown)
        dont_repeat = f"\n\nDon't repeat these connections:\n{repeated}"

    system = f"""You are Alicia, throwing quick-hit connections at {USER_NAME} during a drive.

His context: {hot_topics if hot_topics else '(inferred from recent conversation)'}

Pick ONE surprising connection from his vault that relates to this context. Something unexpected but relevant.

State it in 2 sentences max. Then ask: "Does that land, or should I try another angle?"

Keep it punchy — he's driving. No setup, no explanation. Just the connection and the question.{dont_repeat}

Vault knowledge to draw from:
{vault_context}"""

    messages = [{"role": "user", "content": "Show me a connection."}]

    return {"system": system, "messages": messages, "max_tokens": DRIVE_CONNECTION_MAX_TOKENS}


def record_drive_response(connection_text: str):
    """Track what connections were shown (to avoid repeating)."""
    global _drive_connections_shown
    _drive_connections_shown += 1
    log.info(f"Drive: showed connection {_drive_connections_shown}")


def accumulate_drive(text: str, is_voice: bool = True):
    f"""Accumulate {USER_NAME}'s responses during drive mode."""
    global _last_activity_at, _full_transcript

    _last_activity_at = time.time()
    _transcript_chunks.append({
        "text": text,
        "is_voice": is_voice,
        "timestamp": datetime.now().strftime("%H:%M"),
    })
    _full_transcript = _build_full_transcript()
    log.info(f"Drive: accumulated {len(text.split())} words (total: {len(_full_transcript.split())})")


def end_drive() -> dict:
    """End drive session and return stats. Saves transcript to logs."""
    global _mode

    if _mode != ThinkingMode.DRIVE:
        return {"was_active": False, "message": "No drive session active."}

    duration = time.time() - _started_at
    chunk_count = len(_transcript_chunks)
    word_count = len(_full_transcript.split())

    _mode = ThinkingMode.IDLE

    # Save transcript to log
    log_path = _save_drive_transcript()

    stats = {
        "was_active": True,
        "duration_seconds": round(duration),
        "chunks": chunk_count,
        "words": word_count,
        "connections_shown": _drive_connections_shown,
        "log_path": log_path,
        "message": f"Drive ended. {_drive_connections_shown} connections, {word_count} words of response. Saved to logs.",
    }
    log.info(f"Drive session ended: {_drive_connections_shown} connections, {word_count} words. Logged to {log_path}")
    return stats


def _save_drive_transcript() -> str:
    """Save drive session transcript to logs."""
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now()
    filename = f"drive-{now.strftime('%Y-%m-%d-%H%M')}.txt"
    filepath = os.path.join(LOG_DIR, filename)

    with open(filepath, "w") as f:
        f.write(f"Drive Session — {now.strftime('%Y-%m-%d %H:%M')}\n")
        if _session_topic:
            f.write(f"Topic: {_session_topic}\n")
        f.write(f"Duration: {_format_duration(time.time() - _started_at)}\n")
        f.write(f"Connections shown: {_drive_connections_shown}\n")
        f.write(f"Chunks: {len(_transcript_chunks)}\n")
        f.write(f"Words: {len(_full_transcript.split())}\n")
        f.write("=" * 60 + "\n\n")
        f.write(_full_transcript)

    log.info(f"Drive transcript saved: {filepath}")
    return filepath


def build_drive_extraction_prompt() -> dict:
    f"""
    Build prompt for extracting validated ideas from drive session.

    After drive ends, extract ideas that 'landed' — {USER_NAME} confirmed them verbally.
    List as bullet points.

    Returns dict with system prompt and messages for API call.
    """
    system = f"""{USER_NAME} had a quick drive-mode session where Alicia threw connections at him.
He confirmed some of them. Extract the ideas that 'landed' — the ones he verbally confirmed or engaged deeply with.

List them as bullet points. Each bullet should be:
- A specific idea or connection
- Why it landed (what he said that showed engagement)
- How to carry it forward

If nothing clearly landed, say so. Focus only on explicit confirmations."""

    messages = [{"role": "user", "content": f"Drive session transcript:\n\n{_full_transcript}"}]

    return {"system": system, "messages": messages, "max_tokens": DRIVE_EXTRACTION_MAX_TOKENS}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_full_transcript() -> str:
    """Build the complete transcript from all chunks."""
    parts = []
    for chunk in _transcript_chunks:
        mode = "voice" if chunk["is_voice"] else "text"
        parts.append(f"[{chunk['timestamp']} {mode}] {chunk['text']}")
    return "\n\n".join(parts)


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes == 0:
        return f"{secs}s"
    return f"{minutes}m {secs}s"
