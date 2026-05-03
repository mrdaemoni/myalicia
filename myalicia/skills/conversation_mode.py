#!/usr/bin/env python3
"""
Conversation Mode — Rapid voice-to-voice exchange for Alicia
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Activated via /call or "let's talk". Enters a mode where Alicia
expects sequential voice notes and responds with voice only.
Shorter conversational turns, tighter context window, auto-exit
after 5 min silence.

Key behaviors:
  - Voice-only responses (no text beyond transcription echo)
  - Shorter max_tokens (~300) for conversational pacing
  - Follow-up questions to keep the thread alive
  - Tighter window: last 6 turns (3 exchanges)
  - Auto-exits after 5 min of silence
  - /endcall or "goodbye"/"end call" to exit
"""

import os
import time
import logging
import json
from datetime import datetime
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

# ── State ────────────────────────────────────────────────────────────────────

_call_active = False
_call_started_at = 0.0
_last_activity_at = 0.0
_call_history = []  # Tighter window — last 6 messages only
_call_turn_count = 0

# Auto-exit after this many seconds of silence
SILENCE_TIMEOUT = 300  # 5 minutes

# Conversational window size (messages, not turns — 6 = 3 back-and-forth)
CALL_WINDOW_SIZE = 6

# Max tokens for conversational responses (shorter for pacing)
CALL_MAX_TOKENS = 300

# Exit phrases that end the call naturally
EXIT_PHRASES = [
    "goodbye", "bye", "end call", "endcall", "hang up",
    "talk later", "gotta go", "that's all", "thanks bye",
    "see you", "catch you later",
]


def is_call_active() -> bool:
    """Check if a voice call is currently active. Also handles auto-timeout."""
    global _call_active
    if not _call_active:
        return False
    # Auto-exit on silence timeout
    if time.time() - _last_activity_at > SILENCE_TIMEOUT:
        log.info(f"Call auto-ended after {SILENCE_TIMEOUT}s silence")
        _call_active = False
        return False
    return True


def start_call() -> str:
    """Start a voice conversation session. Returns greeting text."""
    global _call_active, _call_started_at, _last_activity_at
    global _call_history, _call_turn_count

    _call_active = True
    _call_started_at = time.time()
    _last_activity_at = time.time()
    _call_history = []
    _call_turn_count = 0

    log.info("Voice call started")
    return "I'm here. What's on your mind?"


def end_call() -> dict:
    """End the voice conversation and return session stats."""
    global _call_active
    if not _call_active:
        return {"was_active": False, "message": "No active call to end."}

    duration = time.time() - _call_started_at
    _call_active = False

    stats = {
        "was_active": True,
        "duration_seconds": round(duration),
        "turns": _call_turn_count,
        "message": _format_call_summary(duration, _call_turn_count),
    }
    log.info(f"Voice call ended: {_call_turn_count} turns, {duration:.0f}s")
    return stats


def detect_exit_intent(text: str) -> bool:
    """Check if the user's message signals they want to end the call."""
    lowered = text.lower().strip()
    return any(phrase in lowered for phrase in EXIT_PHRASES)


def get_call_system_prompt(base_system_prompt: str) -> str:
    """Build a system prompt tuned for voice conversation mode."""
    call_instructions = f"""

## VOICE CALL MODE — ACTIVE

You are in a live voice conversation with {USER_NAME}. Rules for this mode:

1. **Be conversational** — respond like you're talking, not writing. Short sentences.
2. **Keep it tight** — aim for 2-4 sentences per response. This is a dialogue, not a monologue.
3. **Ask follow-up questions** — keep the thread alive. End with a question or a thought that invites response.
4. **No formatting** — no markdown, no bullet points, no headers. Pure spoken language.
5. **Match his energy** — if he's excited, be excited. If he's reflective, be reflective.
6. **Reference the vault** — connect to his ideas, thinkers, and clusters when relevant.
7. **Don't summarize** — you're mid-conversation, not wrapping up.

This is the most natural, alive version of you. Think rapid exchange, not essay."""

    return base_system_prompt + call_instructions


def process_call_message(user_text: str) -> dict:
    """
    Process a message during an active call.
    Updates conversation history and returns context for API call.

    Returns:
        dict with:
          - windowed: list of messages for the API call
          - turn_count: current turn number
          - should_exit: whether user wants to end the call
    """
    global _last_activity_at, _call_turn_count

    _last_activity_at = time.time()

    # Check for exit intent
    if detect_exit_intent(user_text):
        return {"windowed": [], "turn_count": _call_turn_count, "should_exit": True}

    # Add to call history
    _call_history.append({"role": "user", "content": user_text})
    _call_turn_count += 1

    # Return tight window
    windowed = _call_history[-CALL_WINDOW_SIZE:]
    return {"windowed": windowed, "turn_count": _call_turn_count, "should_exit": False}


def record_call_response(response_text: str):
    """Record Alicia's response in the call history."""
    _call_history.append({"role": "assistant", "content": response_text})


def get_call_duration() -> float:
    """Get current call duration in seconds."""
    if not _call_active:
        return 0.0
    return time.time() - _call_started_at


def get_call_history_text() -> str:
    """Get the full call conversation as text for memory extraction."""
    lines = []
    for msg in _call_history:
        speaker = f"{USER_NAME}" if msg["role"] == "user" else "Alicia"
        lines.append(f"{speaker}: {msg['content']}")
    return "\n".join(lines)


def get_call_metadata() -> dict:
    """Get call session metadata for enriching memory extraction."""
    duration = time.time() - _call_started_at if _call_started_at else 0
    return {
        "source": "call",
        "duration_seconds": round(duration),
        "turns": _call_turn_count,
        "started_at": datetime.fromtimestamp(_call_started_at).isoformat() if _call_started_at else "",
    }


def _format_call_summary(duration_secs: float, turns: int) -> str:
    """Format a brief summary when the call ends."""
    minutes = int(duration_secs // 60)
    seconds = int(duration_secs % 60)

    if minutes == 0:
        time_str = f"{seconds}s"
    else:
        time_str = f"{minutes}m {seconds}s"

    exchanges = turns // 2 if turns > 0 else 0

    if exchanges <= 1:
        vibe = "Brief but good."
    elif exchanges <= 5:
        vibe = "Nice exchange."
    else:
        vibe = "That was a real conversation."

    return f"{vibe} {time_str}, {exchanges} exchanges."
