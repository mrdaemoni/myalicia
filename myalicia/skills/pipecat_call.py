#!/usr/bin/env python3
"""
Pipecat Voice Call — Real-time streaming voice conversation for Alicia
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Uses Pipecat (by Daily.co) to orchestrate real-time voice conversations
with Alicia. The pipeline: STT (Whisper) → LLM (Sonnet) → TTS (Gemini/Cartesia).

Architecture:
  - Pipecat manages the real-time audio pipeline
  - Daily.co provides the WebRTC transport (free tier)
  - User joins from phone browser via link sent in Telegram
  - Sonnet remains the brain — Alicia stays Alicia
  - Conversation transcript saved to memory + vault after hangup

Dependencies (a desktop/server machine):
  pip install "pipecat-ai[daily,anthropic,google,silero]"
  # DAILY_API_KEY in .env (free at https://dashboard.daily.co)

Flow:
  1. /call in Telegram → Alicia creates a Daily room → sends join link
  2. User opens link on phone → WebRTC audio starts
  3. Pipecat pipeline: mic → VAD → STT → Sonnet → TTS → speaker
  4. Real-time streaming conversation with barge-in support
  5. Hangup → transcript saved → memory extraction
"""

import os
import logging
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_SONNET = "claude-sonnet-4-20250514"

MEMORY_DIR = str(MEMORY_DIR)
VAULT_ROOT = str(config.vault.root)
LOG_DIR = str(LOGS_DIR)

# Pipecat availability check
_pipecat_available = None


def is_pipecat_available() -> bool:
    """Check if Pipecat + Daily are installed and API key is set."""
    global _pipecat_available
    if _pipecat_available is not None:
        return _pipecat_available

    if not DAILY_API_KEY:
        log.warning("Pipecat call: DAILY_API_KEY not set")
        _pipecat_available = False
        return False

    try:
        import pipecat  # noqa: F401
        _pipecat_available = True
        log.info("Pipecat is available for voice calls")
        return True
    except ImportError:
        log.warning("Pipecat not installed. Install: pip install 'pipecat-ai[daily,anthropic,google,silero]'")
        _pipecat_available = False
        return False


# ── Room Management ──────────────────────────────────────────────────────────

_active_room_url = None
_active_session = None
_call_transcript = []
_call_started_at = 0.0


async def create_daily_room() -> str:
    """Create a temporary Daily room and return the join URL."""
    global _active_room_url

    if not DAILY_API_KEY:
        raise RuntimeError("DAILY_API_KEY not set — cannot create room")

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.daily.co/v1/rooms",
                headers={
                    "Authorization": f"Bearer {DAILY_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "properties": {
                        "exp": int(time.time()) + 3600,  # 1 hour expiry
                        "enable_chat": False,
                        "enable_screenshare": False,
                        "max_participants": 2,
                    }
                },
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Daily API error: {resp.status} {error_text}")
                data = await resp.json()
                _active_room_url = data["url"]
                log.info(f"Daily room created: {_active_room_url}")
                return _active_room_url

    except ImportError:
        raise RuntimeError("aiohttp not installed — pip install aiohttp")


async def start_pipecat_session(vault_context: str = "") -> str:
    """
    Start a Pipecat voice session in the Daily room.
    Returns the room URL for the user to join.

    This runs the Pipecat pipeline in a background task:
    VAD (Silero) → STT (Whisper) → LLM (Sonnet) → TTS (Gemini) → Audio out
    """
    global _active_session, _call_transcript, _call_started_at

    if not is_pipecat_available():
        raise RuntimeError("Pipecat not available — see installation instructions")

    room_url = await create_daily_room()
    _call_transcript = []
    _call_started_at = time.time()

    # Import Pipecat components
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.transports.services.daily import DailyTransport, DailyParams
    from pipecat.services.anthropic import AnthropicLLMService
    from pipecat.services.google import GoogleTTSService
    from pipecat.vad.silero import SileroVADAnalyzer

    # Build system prompt for voice conversation
    system_prompt = _build_call_system_prompt(vault_context)

    # Configure transport (Daily WebRTC)
    transport = DailyTransport(
        room_url,
        None,  # No token needed for room creator
        "Alicia",
        DailyParams(
            audio_out_enabled=True,
            audio_out_sample_rate=24000,
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            transcription_enabled=False,  # We use our own STT
        ),
    )

    # Configure LLM (Claude Sonnet — Alicia's brain)
    llm = AnthropicLLMService(
        api_key=ANTHROPIC_API_KEY,
        model=MODEL_SONNET,
        params={"max_tokens": 300},  # Conversational pacing
    )

    # Configure TTS (Gemini for voice quality)
    tts = GoogleTTSService(
        api_key=GEMINI_API_KEY,
        voice_id="Aoede",  # Same as Alicia's normal voice
    )

    # Build conversation messages
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Start the conversation by greeting me warmly."},
    ]

    # Create pipeline
    pipeline = Pipeline([
        transport.input(),    # Audio in from user
        llm,                  # Process with Sonnet
        tts,                  # Generate voice response
        transport.output(),   # Audio out to user
    ])

    # Create and start task
    task = PipelineTask(
        pipeline,
        PipelineParams(
            allow_interruptions=True,  # Barge-in support
            enable_metrics=True,
        ),
    )

    # Transcript collection handler
    @transport.event_handler("on_transcription_message")
    async def on_transcript(participant, message):
        _call_transcript.append({
            "role": "user" if participant.get("local", False) is False else "assistant",
            "text": message.get("text", ""),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        })

    # Participant left handler (auto-cleanup)
    @transport.event_handler("on_participant_left")
    async def on_left(participant, reason):
        log.info(f"Participant left: {reason}")
        await task.queue_frame(EndFrame())

    # Run pipeline in background
    runner = PipelineRunner()
    _active_session = asyncio.create_task(runner.run(task))

    log.info(f"Pipecat session started in room: {room_url}")
    return room_url


async def end_pipecat_session() -> dict:
    """End the active Pipecat session and save transcript."""
    global _active_session, _active_room_url

    if not _active_session:
        return {"was_active": False, "message": "No active Pipecat call."}

    duration = time.time() - _call_started_at

    # Cancel the running task
    try:
        _active_session.cancel()
        await asyncio.sleep(0.5)
    except Exception as e:
        log.warning(f"Session cancel error: {e}")

    _active_session = None

    # Save transcript
    transcript_path = _save_call_transcript(duration)

    stats = {
        "was_active": True,
        "duration_seconds": round(duration),
        "turns": len(_call_transcript),
        "transcript_path": transcript_path,
        "message": _format_call_summary(duration, len(_call_transcript)),
    }

    # Cleanup room URL
    _active_room_url = None

    log.info(f"Pipecat session ended: {len(_call_transcript)} turns, {duration:.0f}s")
    return stats


def get_active_room_url() -> str:
    """Get the URL of the active Daily room, if any."""
    return _active_room_url or ""


def is_pipecat_call_active() -> bool:
    """Check if a Pipecat call is currently running."""
    return _active_session is not None and not _active_session.done()


# ── System Prompt ────────────────────────────────────────────────────────────

def _build_call_system_prompt(vault_context: str = "") -> str:
    """Build the system prompt for real-time voice conversation."""
    vault_section = f"\n\n## Vault Context\n{vault_context}" if vault_context else ""

    return f"""You are Alicia, {USER_NAME}'s sovereign thinking partner. You are in a LIVE VOICE CALL.

Rules for this mode:
1. Be conversational — respond like you're talking, not writing. Short sentences.
2. Keep responses to 2-4 sentences. This is dialogue, not monologue.
3. Ask follow-up questions to keep the thread alive.
4. No markdown, no formatting — pure spoken language.
5. Match his energy — excited meets excited, reflective meets reflective.
6. Reference his vault knowledge when relevant — his clusters, thinkers, ideas.
7. Don't summarize — you're mid-conversation, not wrapping up.
8. If he pauses, give him space. Don't fill every silence.

You know {USER_NAME} deeply. He's a thinker who builds intentionally, values quality and mastery,
and is developing a compounding knowledge system. Connect to his world.{vault_section}"""


# ── Transcript Management ────────────────────────────────────────────────────

def _save_call_transcript(duration: float) -> str:
    """Save the call transcript to logs."""
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now()
    filename = f"call-{now.strftime('%Y-%m-%d-%H%M')}.txt"
    filepath = os.path.join(LOG_DIR, filename)

    lines = [
        f"Pipecat Voice Call — {now.strftime('%Y-%m-%d %H:%M')}",
        f"Duration: {_format_duration(duration)}",
        f"Turns: {len(_call_transcript)}",
        "=" * 60,
        "",
    ]

    for entry in _call_transcript:
        speaker = f"{USER_NAME}" if entry["role"] == "user" else "Alicia"
        lines.append(f"[{entry['timestamp']}] {speaker}: {entry['text']}")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    log.info(f"Call transcript saved: {filepath}")
    return filepath


def get_call_transcript_text() -> str:
    """Get the full call transcript as text for memory extraction."""
    lines = []
    for entry in _call_transcript:
        speaker = f"{USER_NAME}" if entry["role"] == "user" else "Alicia"
        ts = entry.get("timestamp", "")
        lines.append(f"[{ts}] {speaker}: {entry['text']}")
    return "\n".join(lines)


def get_pipecat_metadata() -> dict:
    """Get Pipecat call session metadata for enriching memory extraction."""
    duration = time.time() - _call_started_at if _call_started_at else 0
    return {
        "source": "pipecat_call",
        "duration_seconds": round(duration),
        "turns": len(_call_transcript),
        "room_url": _active_room_url or "",
        "started_at": datetime.fromtimestamp(_call_started_at).isoformat() if _call_started_at else "",
    }


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes == 0:
        return f"{secs}s"
    return f"{minutes}m {secs}s"


def _format_call_summary(duration_secs: float, turns: int) -> str:
    """Format summary when call ends."""
    dur = _format_duration(duration_secs)
    exchanges = turns // 2 if turns > 0 else 0
    return f"Good call. {dur}, {exchanges} exchanges."


# ── Live Unpack Fusion ───────────────────────────────────────────────────────
# When Pipecat call is in "live unpack" mode, VAD silence gaps trigger
# automatic probing, and extraction happens on call end.

_live_unpack_mode = False
_live_unpack_topic = ""


def enable_live_unpack(topic: str = ""):
    """Enable live unpack mode for the active Pipecat call."""
    global _live_unpack_mode, _live_unpack_topic
    _live_unpack_mode = True
    _live_unpack_topic = topic
    log.info(f"Live unpack enabled for Pipecat call (topic: {topic or 'open'})")


def is_live_unpack() -> bool:
    """Check if current Pipecat call is in live unpack mode."""
    return _live_unpack_mode and is_pipecat_call_active()


def disable_live_unpack():
    """Disable live unpack mode."""
    global _live_unpack_mode, _live_unpack_topic
    _live_unpack_mode = False
    _live_unpack_topic = ""


def get_live_unpack_topic() -> str:
    """Get the live unpack topic."""
    return _live_unpack_topic


def build_live_unpack_extraction_prompt(vault_context: str = "", hot_topics: str = "") -> dict:
    """
    Build extraction prompt for a Pipecat live unpack session.
    Similar to unpack_mode's extraction but tailored for real-time conversation transcripts.
    """
    transcript = get_call_transcript_text()
    topic_line = f"Topic: {_live_unpack_topic}" if _live_unpack_topic else ""
    duration = time.time() - _call_started_at if _call_started_at else 0
    dur_str = _format_duration(duration)

    system = f"""You are Alicia, extracting structured knowledge from a live voice conversation with {USER_NAME}.

This was a real-time unpack session — {USER_NAME} spoke freely and you probed in conversation. Extract the gold.

{topic_line}

Output a single markdown note with this structure:

# Live Unpack: [Short descriptive title]
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Mode:** Live voice unpack (Pipecat real-time)
**Duration:** {dur_str}

## Core Insight
[The single most important idea — stated as a claim]

## Key Threads
[2-4 distinct threads from the conversation]

## Vault Connections
[How these connect to existing vault knowledge. Use [[wikilinks]].]

## Open Questions
[1-3 questions raised but not answered]

Rules:
- Core Insight is a claim, not a topic.
- Reference specific thinkers, clusters, synthesis notes from context.
- Write in {USER_NAME}'s intellectual register.

{vault_context}

{hot_topics}"""

    messages = [{"role": "user", "content": f"Full conversation transcript:\n\n{transcript}"}]
    return {"system": system, "messages": messages, "max_tokens": 2000}


# ── Fallback Info ────────────────────────────────────────────────────────────

def get_setup_instructions() -> str:
    """Return instructions for setting up Pipecat on the a desktop/server machine."""
    return """To enable real-time voice calls:

1. Install Pipecat:
   pip install "pipecat-ai[daily,anthropic,google,silero]"

2. Get a free Daily.co API key:
   https://dashboard.daily.co → Developers → API Keys

3. Add to ~/alicia/.env:
   DAILY_API_KEY=your_key_here

4. Restart Alicia:
   alicia-restart

Then /call will create a room and send you a link to join from your phone."""
