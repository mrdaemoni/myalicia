#!/usr/bin/env python3
f"""
Unpack Mode — Deep extraction from voice monologues
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Activated via /unpack or "let me unpack something". Designed for
post-podcast, post-sauna, or driving moments when {USER_NAME} wants to
think aloud and have Alicia extract the gold.

State machine:
  IDLE → LISTENING → PROBING → EXTRACTING → DONE → IDLE

LISTENING:
  - Accumulates voice note transcriptions silently
  - No responses until silence detected (30s) or /done
  - Shows brief "..." acknowledgment per voice note

PROBING:
  - Sonnet analyzes full transcript + vault context
  - Generates 2-3 targeted clarifying questions as voice notes
  - {USER_NAME} responds, feeding back into the transcript
  - Up to 3 probe rounds (or until "that's it" / /done)

EXTRACTING:
  - Writes structured note to vault (Inbox or Synthesis)
  - Extracts key insights for memory
  - Maps connections to existing clusters
  - Sends summary voice note + vault link
"""

import os
import time
import logging
import json
from datetime import datetime
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

# How long to wait after last voice note before probing (seconds)
SILENCE_BEFORE_PROBE = 30

# Maximum probe rounds before auto-extracting
MAX_PROBE_ROUNDS = 3

# Max tokens for probe questions (keep them tight)
PROBE_MAX_TOKENS = 400

# Max tokens for extraction (needs room for structured output)
EXTRACT_MAX_TOKENS = 2000

# Exit phrases that trigger extraction
DONE_PHRASES = [
    "that's it", "thats it", "that's all", "thats all",
    "i'm done", "im done", "done", "wrap it up",
    "extract that", "save that", "end unpack",
]


# ── State Machine ────────────────────────────────────────────────────────────

class UnpackState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROBING = "probing"
    EXTRACTING = "extracting"


_state = UnpackState.IDLE
_started_at = 0.0
_last_voice_at = 0.0
_transcript_chunks = []       # List of {"text": str, "is_voice": bool, "timestamp": str}
_probe_round = 0
_probe_questions = []         # Questions Alicia asked
_topic_hint = ""              # Optional topic from /unpack argument
_full_transcript = ""         # Accumulated full text


def get_state() -> str:
    """Return current unpack state as string."""
    return _state.value


def is_unpack_active() -> bool:
    """Check if unpack mode is active (any state except IDLE)."""
    return _state != UnpackState.IDLE


def is_listening() -> bool:
    """Check if we're in the listening phase (accumulating, not responding)."""
    return _state == UnpackState.LISTENING


def is_probing() -> bool:
    """Check if we're in the probing phase."""
    return _state == UnpackState.PROBING


def should_probe_now() -> bool:
    """Check if enough silence has passed to trigger probing."""
    if _state != UnpackState.LISTENING:
        return False
    if not _transcript_chunks:
        return False
    elapsed = time.time() - _last_voice_at
    return elapsed >= SILENCE_BEFORE_PROBE


def detect_done_intent(text: str) -> bool:
    """Check if the user wants to finish unpacking."""
    lowered = text.lower().strip()
    return any(phrase in lowered for phrase in DONE_PHRASES)


# ── Start / Stop ─────────────────────────────────────────────────────────────

def start_unpack(topic: str = "") -> str:
    """Start an unpack session. Returns acknowledgment text."""
    global _state, _started_at, _last_voice_at
    global _transcript_chunks, _probe_round, _probe_questions
    global _topic_hint, _full_transcript

    _state = UnpackState.LISTENING
    _started_at = time.time()
    _last_voice_at = time.time()
    _transcript_chunks = []
    _probe_round = 0
    _probe_questions = []
    _topic_hint = topic.strip()
    _full_transcript = ""

    log.info(f"Unpack session started (topic: {topic or 'open'})")

    if topic:
        return f"I'm listening. Unpack your thoughts on {topic} — I'll stay quiet until you're done, then ask you some questions."
    return "I'm listening. Take your time — I'll stay quiet until you're done, then dig in with some questions."


def end_unpack() -> dict:
    """End unpack session and return stats."""
    global _state
    if _state == UnpackState.IDLE:
        return {"was_active": False, "message": "No unpack session active."}

    duration = time.time() - _started_at
    chunk_count = len(_transcript_chunks)
    word_count = len(_full_transcript.split())

    _state = UnpackState.IDLE

    stats = {
        "was_active": True,
        "duration_seconds": round(duration),
        "chunks": chunk_count,
        "words": word_count,
        "probe_rounds": _probe_round,
        "message": _format_unpack_summary(duration, chunk_count, word_count),
    }
    log.info(f"Unpack session ended: {chunk_count} chunks, {word_count} words, {_probe_round} probe rounds")
    return stats


# ── Accumulation (Listening Phase) ───────────────────────────────────────────

def accumulate_voice(transcription: str):
    """Add a transcribed voice note to the accumulator. No response during listening."""
    global _last_voice_at, _full_transcript

    _last_voice_at = time.time()
    _transcript_chunks.append({
        "text": transcription,
        "is_voice": True,
        "timestamp": datetime.now().strftime("%H:%M"),
    })
    _full_transcript = _build_full_transcript()
    log.info(f"Unpack: accumulated {len(transcription.split())} words (total: {len(_full_transcript.split())})")


def accumulate_text(text: str):
    """Add a text message to the accumulator."""
    global _last_voice_at, _full_transcript

    _last_voice_at = time.time()
    _transcript_chunks.append({
        "text": text,
        "is_voice": False,
        "timestamp": datetime.now().strftime("%H:%M"),
    })
    _full_transcript = _build_full_transcript()


def _build_full_transcript() -> str:
    """Build the complete transcript from all chunks."""
    parts = []
    for chunk in _transcript_chunks:
        mode = "voice" if chunk["is_voice"] else "text"
        parts.append(f"[{chunk['timestamp']} {mode}] {chunk['text']}")
    return "\n\n".join(parts)


def get_transcript() -> str:
    """Get the full accumulated transcript."""
    return _full_transcript


def get_word_count() -> int:
    """Get total word count across all chunks."""
    return len(_full_transcript.split())


# ── Probing Phase ────────────────────────────────────────────────────────────

def enter_probing():
    """Transition from LISTENING to PROBING."""
    global _state
    _state = UnpackState.PROBING
    log.info(f"Unpack: entering probe phase (round {_probe_round + 1})")


def build_probe_prompt(vault_context: str = "", hot_topics: str = "") -> dict:
    """
    Build the Sonnet prompt for generating clarifying questions.
    Returns dict with system prompt and messages for API call.
    """
    global _probe_round
    _probe_round += 1

    topic_line = f"Topic hint: {_topic_hint}" if _topic_hint else "No specific topic — infer from content."

    previous_probes = ""
    if _probe_questions:
        prev = "\n".join(f"- {q}" for q in _probe_questions)
        previous_probes = f"\nYou already asked these questions (don't repeat):\n{prev}"

    system = f"""You are Alicia, {USER_NAME}'s thinking partner. He just finished a voice monologue — unpacking thoughts after a podcast, sauna session, or drive.

Your job: ask 2-3 sharp clarifying questions that will extract MORE from him. Not surface questions — questions that reach into what he almost said but didn't. Questions that connect his monologue to ideas he's been developing.

{topic_line}

Rules:
1. Ask exactly 2-3 questions. No more.
2. Each question should target a different thread from his monologue.
3. At least one question should connect to his vault knowledge (clusters, thinkers, past insights).
4. Questions should feel like a thinking partner probing, not an interviewer interrogating.
5. No preamble, no summary of what he said. Jump straight into the questions.
6. Write in natural spoken language — these will be read aloud as voice notes.
7. Keep each question to 1-2 sentences max.
{previous_probes}

{vault_context}

{hot_topics}

This is probe round {_probe_round} of {MAX_PROBE_ROUNDS}."""

    messages = [{"role": "user", "content": f"Here is {USER_NAME}'s full monologue:\n\n{_full_transcript}"}]

    return {"system": system, "messages": messages, "max_tokens": PROBE_MAX_TOKENS}


def record_probe_response(questions_text: str):
    """Record the questions Alicia asked for dedup in next round."""
    _probe_questions.append(questions_text)


def can_probe_again() -> bool:
    """Check if we have probe rounds remaining."""
    return _probe_round < MAX_PROBE_ROUNDS


# ── Extraction Phase ─────────────────────────────────────────────────────────

def enter_extracting():
    """Transition to EXTRACTING state."""
    global _state
    _state = UnpackState.EXTRACTING
    log.info("Unpack: entering extraction phase")


def build_extraction_prompt(vault_context: str = "", hot_topics: str = "") -> dict:
    """
    Build the Sonnet prompt for extracting structured insights from the full session.
    Returns dict with system prompt and messages for API call.
    """
    topic_line = f"Topic: {_topic_hint}" if _topic_hint else ""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    system = f"""You are Alicia, extracting structured knowledge from {USER_NAME}'s unpack session.

He spoke freely — your job is to distill this into a vault-quality note. The note will be saved to his Obsidian vault.

{topic_line}

Output a single markdown note with this structure:

# Unpack: [Short descriptive title]
**Date:** {date_str} {time_str}
**Mode:** Voice unpack session
**Duration:** {_format_duration(time.time() - _started_at)}

## Core Insight
[The single most important idea from this session — stated as a claim, not a category]

## Key Threads
[2-4 distinct threads from the monologue, each as a brief paragraph]

## Vault Connections
[How these ideas connect to existing vault clusters. Use [[wikilinks]] to known concepts, thinkers, synthesis notes]

## Open Questions
[1-3 questions this session raised but didn't answer — future exploration seeds]

## Raw Extraction
[3-5 specific claims or observations worth remembering, as bullet points]

Rules:
- The Core Insight should be a claim, not a topic. "Patience completes speed" not "Thoughts about patience."
- Vault Connections should reference specific thinkers, clusters, or synthesis notes from context.
- Write in {USER_NAME}'s intellectual register — these are his ideas, you're just structuring them.
- Use [[wikilinks]] for vault concepts.

{vault_context}

{hot_topics}"""

    messages = [{"role": "user", "content": f"Full unpack session transcript:\n\n{_full_transcript}"}]

    return {"system": system, "messages": messages, "max_tokens": EXTRACT_MAX_TOKENS}


def build_memory_extraction_prompt() -> dict:
    """
    Build a second prompt to extract memory-level insights (score 4-5) from the session.
    Returns dict with system prompt and messages for API call.
    """
    system = f"""Extract the highest-signal insights from this unpack session for {USER_NAME}'s long-term memory.

For each insight, provide:
- A one-sentence claim (not a topic)
- A score from 1-5 (5 = foundational shift, 4 = significant, 3 = interesting)
- Which knowledge cluster it belongs to

Only extract score 4-5 insights. If nothing qualifies, return an empty list.

Respond in this exact JSON format:
[
  {{"claim": "...", "score": 5, "cluster": "Quality & Mastery"}},
  {{"claim": "...", "score": 4, "cluster": "Risk & Antifragility"}}
]

Knowledge clusters: Quality & Mastery, Risk & Antifragility, Systems Thinking, Stoic/Classical Wisdom, Meaning & Purpose, Learning & Knowledge, Leadership & Strategy, Creativity & Expression"""

    messages = [{"role": "user", "content": f"Unpack session transcript:\n\n{_full_transcript}"}]

    return {"system": system, "messages": messages, "max_tokens": 500}


def save_vault_note(note_content: str) -> str:
    """Save the extraction note to the vault Inbox. Returns filepath."""
    os.makedirs(INBOX_DIR, exist_ok=True)
    now = datetime.now()
    date_slug = now.strftime("%Y-%m-%d-%H%M")

    # Extract title from first heading
    title = "Unpack Session"
    for line in note_content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    slug = title.replace(" ", "-").replace(":", "")[:60]
    filename = f"{date_slug}-{slug}.md"
    filepath = os.path.join(INBOX_DIR, filename)

    with open(filepath, "w") as f:
        f.write(note_content)

    log.info(f"Unpack note saved: {filepath}")
    return filepath


def save_transcript_log() -> str:
    """Save the raw transcript to logs for reference."""
    log_dir = os.path.expanduser("~/alicia/logs")
    os.makedirs(log_dir, exist_ok=True)
    now = datetime.now()
    filename = f"unpack-{now.strftime('%Y-%m-%d-%H%M')}.txt"
    filepath = os.path.join(log_dir, filename)

    with open(filepath, "w") as f:
        f.write(f"Unpack Session — {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Topic: {_topic_hint or 'open'}\n")
        f.write(f"Duration: {_format_duration(time.time() - _started_at)}\n")
        f.write(f"Chunks: {len(_transcript_chunks)}\n")
        f.write(f"Words: {len(_full_transcript.split())}\n")
        f.write("=" * 60 + "\n\n")
        f.write(_full_transcript)

    log.info(f"Unpack transcript logged: {filepath}")
    return filepath


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_session_metadata() -> dict:
    """Get unpack session metadata for enriching memory extraction."""
    duration = time.time() - _started_at if _started_at else 0
    return {
        "source": "unpack",
        "topic": _topic_hint,
        "duration_seconds": round(duration),
        "chunks": len(_transcript_chunks),
        "words": len(_full_transcript.split()),
        "probe_rounds": _probe_round,
        "started_at": datetime.fromtimestamp(_started_at).isoformat() if _started_at else "",
    }


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes == 0:
        return f"{secs}s"
    return f"{minutes}m {secs}s"


def _format_unpack_summary(duration_secs: float, chunks: int, words: int) -> str:
    """Format a summary when the unpack session ends."""
    dur = _format_duration(duration_secs)
    return f"Extracted. {dur}, {words} words across {chunks} voice notes, {_probe_round} probe rounds."
