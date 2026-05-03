#!/usr/bin/env python3
"""
Voice Skill — Speech-to-Text + Text-to-Speech for Alicia
Supports three TTS backends with automatic fallback:
  TTS: Gemini TTS (google-genai) → OpenAI TTS API → edge-tts (free)
  STT: OpenAI Whisper API → local whisper (openai-whisper package)

Dependencies:
  Always needed: ffmpeg (brew install ffmpeg)
  For Gemini TTS: pip install google-genai  (+ GEMINI_API_KEY in .env)
  For local STT:  pip install openai-whisper
  For free TTS:   pip install edge-tts
  For OpenAI:     pip install openai  (+ OPENAI_API_KEY in .env)
"""

import os
import shutil
import logging
import subprocess
import asyncio
import wave
import uuid
from pathlib import Path
from myalicia.config import config

log = logging.getLogger(__name__)


# ── ffmpeg resolution ───────────────────────────────────────────────────────
# The launchctl-spawned Python process inherits a minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin) that doesn't include Homebrew's
# /opt/homebrew/bin — so a bare "ffmpeg" subprocess.run() call fails with
# FileNotFoundError even though ffmpeg is installed. Resolve it once against
# an augmented search path and cache the absolute path.
_FFMPEG_BIN: str | None = None

# Common Homebrew install locations on macOS (Apple Silicon + Intel) plus
# standard system paths. Checked in order.
_FFMPEG_SEARCH_PATHS = [
    "/opt/homebrew/bin",   # Homebrew on Apple Silicon
    "/opt/homebrew/sbin",
    "/usr/local/bin",      # Homebrew on Intel
    "/usr/local/sbin",
    "/usr/bin",
    "/bin",
]


def _resolve_ffmpeg() -> str:
    """
    Find the ffmpeg binary on disk. Returns the absolute path if found.
    Raises RuntimeError with an actionable message if not.

    Tries in order:
      1. shutil.which() against the current PATH (fast path)
      2. shutil.which() against an augmented PATH covering Homebrew
      3. Direct os.path.isfile() probe of /opt/homebrew/bin/ffmpeg etc.
    """
    global _FFMPEG_BIN
    if _FFMPEG_BIN:
        return _FFMPEG_BIN

    # 1. Try current PATH
    found = shutil.which("ffmpeg")
    if found:
        _FFMPEG_BIN = found
        return _FFMPEG_BIN

    # 2. Augment PATH with Homebrew locations and retry
    augmented = os.pathsep.join(_FFMPEG_SEARCH_PATHS + [os.environ.get("PATH", "")])
    found = shutil.which("ffmpeg", path=augmented)
    if found:
        _FFMPEG_BIN = found
        # Also patch the process PATH so child processes see it too
        if os.path.dirname(found) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = os.path.dirname(found) + os.pathsep + os.environ.get("PATH", "")
        log.info(f"Resolved ffmpeg via augmented PATH: {_FFMPEG_BIN}")
        return _FFMPEG_BIN

    # 3. Direct file probe as last resort
    for p in _FFMPEG_SEARCH_PATHS:
        candidate = os.path.join(p, "ffmpeg")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            _FFMPEG_BIN = candidate
            log.info(f"Resolved ffmpeg via direct probe: {_FFMPEG_BIN}")
            return _FFMPEG_BIN

    log.error(
        "ffmpeg not found on PATH or in common Homebrew locations "
        "(/opt/homebrew/bin, /usr/local/bin). Install with: brew install ffmpeg"
    )
    raise RuntimeError(
        "ffmpeg not installed or not on PATH — needed for voice processing. "
        "Run: brew install ffmpeg"
    )

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")  # base|small|medium|large-v3
VOICE_DIR = os.path.expanduser("~/alicia/voice_cache")
os.makedirs(VOICE_DIR, exist_ok=True)

# ── Gemini TTS Configuration ────────────────────────────────────────────────

# Voice: Aoede is warm and expressive — good default for a personal assistant
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Aoede")
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Style prompts — steer tone via natural language prefix
VOICE_STYLES = {
    "warm":     "Say this warmly and personally, like a close friend checking in: ",
    "measured": "Say this in a clear, measured, thoughtful tone, like reading an insightful passage: ",
    "excited":  "Say this with enthusiasm and energy, like sharing a discovery: ",
    "gentle":   "Say this gently and reflectively, like an evening thought: ",
    # Phase 17.4 — softened style used automatically when recent voice
    # notes have been emotionally heavy. Slower pace, lower volume, more
    # space between phrases. the user hears Alicia attune.
    "tender":   "Say this very softly and slowly, with extra space between phrases, like sitting beside someone on a hard day: ",
    "default":  "",  # No style prefix — let the model decide naturally
}


# ── STT Backend Detection ────────────────────────────────────────────────────

_stt_backend = None

def _detect_stt_backend():
    global _stt_backend
    if _stt_backend:
        return _stt_backend

    # Priority 1: OpenAI Whisper API
    if OPENAI_API_KEY:
        try:
            import openai  # noqa: F401
            _stt_backend = "openai_api"
            log.info("STT backend: OpenAI Whisper API")
            return _stt_backend
        except ImportError:
            log.warning("OPENAI_API_KEY set but openai package not installed. Falling back.")

    # Priority 2: Local whisper (openai-whisper package)
    try:
        import whisper  # noqa: F401
        _stt_backend = "local_whisper"
        log.info("STT backend: Local Whisper")
        return _stt_backend
    except ImportError:
        pass

    log.error("No STT backend available. Install: pip install openai-whisper")
    _stt_backend = "none"
    return _stt_backend


# ── TTS Backend Detection ────────────────────────────────────────────────────

_tts_backend = None

def _detect_tts_backend():
    global _tts_backend
    if _tts_backend:
        return _tts_backend

    # Priority 1: Gemini TTS (best quality + steerable)
    if GEMINI_API_KEY:
        try:
            from google import genai  # noqa: F401
            _tts_backend = "gemini"
            log.info("TTS backend: Gemini TTS (google-genai)")
            return _tts_backend
        except ImportError:
            log.warning("GEMINI_API_KEY set but google-genai not installed. Falling back.")

    # Priority 2: OpenAI TTS API
    if OPENAI_API_KEY:
        try:
            import openai  # noqa: F401
            _tts_backend = "openai_api"
            log.info("TTS backend: OpenAI TTS API")
            return _tts_backend
        except ImportError:
            log.warning("OPENAI_API_KEY set but openai package not installed. Falling back.")

    # Priority 3: edge-tts (free, no key needed)
    try:
        import edge_tts  # noqa: F401
        _tts_backend = "edge_tts"
        log.info("TTS backend: edge-tts (Microsoft neural voices)")
        return _tts_backend
    except ImportError:
        pass

    log.error("No TTS backend available. Install: pip install google-genai")
    _tts_backend = "none"
    return _tts_backend


# ── Audio Conversion ─────────────────────────────────────────────────────────

def _ogg_to_wav(ogg_path: str) -> str:
    """Convert Telegram .ogg (Opus) to .wav for Whisper."""
    wav_path = ogg_path.replace(".ogg", ".wav")
    ffmpeg = _resolve_ffmpeg()
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, check=True, timeout=30
        )
        return wav_path
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg conversion failed: {e.stderr.decode()[:200]}")
        raise RuntimeError("Audio conversion failed")


def _wav_to_ogg(wav_path: str) -> str:
    """Convert WAV to OGG (Opus) for Telegram voice note."""
    ogg_path = wav_path.replace(".wav", ".ogg")
    ffmpeg = _resolve_ffmpeg()
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
            capture_output=True, check=True, timeout=60
        )
        return ogg_path
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg wav->ogg failed: {e.stderr.decode()[:200]}")
        raise RuntimeError("Audio conversion failed")


def _mp3_to_ogg(mp3_path: str) -> str:
    """Convert MP3 to OGG (Opus) for Telegram voice note."""
    ogg_path = mp3_path.replace(".mp3", ".ogg")
    ffmpeg = _resolve_ffmpeg()
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
            capture_output=True, check=True, timeout=30
        )
        return ogg_path
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg mp3->ogg failed: {e.stderr.decode()[:200]}")
        raise RuntimeError("Audio conversion failed")


# ── Speech-to-Text ───────────────────────────────────────────────────────────

# Local whisper model (lazy-loaded, kept in memory)
_whisper_model = None

def _load_local_whisper():
    """Load local Whisper model. Size set by WHISPER_MODEL env var (default: medium)."""
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(WHISPER_MODEL)
        log.info(f"Local Whisper model loaded ({WHISPER_MODEL})")
    return _whisper_model


def transcribe_voice(ogg_path: str) -> str:
    """
    Transcribe a Telegram voice note (.ogg) to text.
    Returns the transcribed text string.
    """
    backend = _detect_stt_backend()

    if backend == "none":
        return "[Voice transcription unavailable — install openai-whisper]"

    # Convert OGG -> WAV
    wav_path = _ogg_to_wav(ogg_path)

    try:
        if backend == "openai_api":
            return _transcribe_openai_api(wav_path)
        elif backend == "local_whisper":
            return _transcribe_local_whisper(wav_path)
    finally:
        # Cleanup temp files
        for p in [wav_path]:
            try:
                os.remove(p)
            except OSError:
                pass


def _transcribe_openai_api(wav_path: str) -> str:
    """Transcribe using OpenAI Whisper API."""
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    with open(wav_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="en",  # Optimize for English; remove for auto-detect
        )
    text = transcript.text.strip()
    log.info(f"Transcribed (OpenAI API): {text[:80]}...")
    return text


def _transcribe_local_whisper(wav_path: str) -> str:
    """Transcribe using local Whisper model."""
    model = _load_local_whisper()
    result = model.transcribe(
        wav_path,
        language="en",      # Force English for speed; remove for auto-detect
        fp16=False,          # MPS/CPU compatibility on Mac
        condition_on_previous_text=False,  # Prevent hallucination on silence
    )
    text = result["text"].strip()
    log.info(f"Transcribed (local): {text[:80]}...")
    return text


# ── Text-to-Speech ───────────────────────────────────────────────────────────

# Legacy voice settings (kept for fallback backends)
EDGE_TTS_VOICE = "en-AU-NatashaNeural"     # Australian female — crisp, clear
OPENAI_TTS_VOICE = "nova"                   # OpenAI nova — natural female

# Max TTS length per chunk — Gemini silently truncates audio beyond ~2000 chars
# even though the API accepts more. Keep chunks short so voice notes are complete.
MAX_TTS_CHARS = 2000

# Max chars for a single Gemini API call
_GEMINI_CHUNK_SIZE = 2000


async def text_to_voice(text: str, style: str = "default") -> str:
    """
    Convert text to a Telegram-compatible voice note (.ogg).
    Returns path to the .ogg file.

    Args:
        text:  The text to speak.
        style: Voice style — one of: "warm", "measured", "excited",
               "gentle", "tender", "default". Controls tone via natural
               language prompting (Gemini only; ignored by other backends).

    Phase 17.4 — the requested style is auto-adapted to the user's recent
    emotional weather. On tender days (sad/ang dominant in last 24h),
    "warm"/"measured"/"default" all soften to "tender". Emphatic styles
    like "excited" pass through unchanged.
    """
    # Phase 17.4 — emotion-aware voice attunement (no-op when neutral)
    try:
        from myalicia.skills.voice_intelligence import adapt_style_to_weather
        style = adapt_style_to_weather(style)
    except Exception:
        pass

    backend = _detect_tts_backend()

    if backend == "none":
        raise RuntimeError("No TTS backend available — install google-genai or edge-tts")

    # Truncate if too long
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS] + "... I'll keep the rest in text."

    # Clean text for TTS (remove markdown formatting)
    clean = _clean_for_tts(text)

    if not clean.strip():
        raise RuntimeError("No speakable text after cleaning")

    if backend == "gemini":
        return await _tts_gemini(clean, style)
    elif backend == "openai_api":
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: _tts_openai_api(clean)
        )
    elif backend == "edge_tts":
        return await _tts_edge(clean)


async def text_to_voice_chunked(text: str, style: str = "measured") -> list:
    """
    Convert long text to multiple Telegram voice notes.
    Returns a list of .ogg file paths, one per chunk.
    Use this for reading vault notes aloud.

    Args:
        text:  The full text to speak (no length limit).
        style: Voice style for all chunks.
    """
    clean = _clean_for_tts(text)
    if not clean.strip():
        raise RuntimeError("No speakable text after cleaning")

    # Split into chunks at sentence boundaries
    chunks = _split_into_chunks(clean, MAX_TTS_CHARS)
    ogg_paths = []

    for i, chunk in enumerate(chunks):
        log.info(f"Generating voice chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        try:
            ogg_path = await text_to_voice(chunk, style=style)
            ogg_paths.append(ogg_path)
        except Exception as e:
            log.error(f"Failed to generate chunk {i+1}: {e}")
            break  # Return what we have so far

    return ogg_paths


def _split_into_chunks(text: str, max_chars: int) -> list:
    """Split text into chunks at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Find a sentence boundary near the limit
        split_at = max_chars
        # Try period + space first
        period_pos = remaining.rfind(". ", 0, max_chars)
        if period_pos > max_chars * 0.5:  # Don't split too early
            split_at = period_pos + 1
        else:
            # Try newline
            newline_pos = remaining.rfind("\n", 0, max_chars)
            if newline_pos > max_chars * 0.3:
                split_at = newline_pos
            else:
                # Try any space
                space_pos = remaining.rfind(" ", 0, max_chars)
                if space_pos > 0:
                    split_at = space_pos

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    return [c for c in chunks if c]  # Filter empties


def strip_leading_stage_direction(text: str) -> str:
    """Strip a leading bracketed stage direction from a model response.

    Sonnet sometimes mirrors the `[tender]` / `[whispered]` prosody tag we
    prepend to voice transcriptions and emits e.g.
        "[tender, feeling the shift in recognition]\\n\\nYes — ..."
    as the first line of its reply. That leaks into the displayed text AND
    into the TTS input (Gemini reads the directive aloud, blowing up the
    audio length), and reflexion was scoring it as "captured [tender]
    quality accurately" so the pattern was reinforcing itself.

    Strips a single leading `[...]` block when:
      * it sits at the very start of the message (whitespace allowed)
      * the bracket content is lowercase-first (matches our tone tags)
      * the closing `]` is NOT immediately followed by `(` (so real
        markdown links `[text](url)` are left intact)

    Wikilinks (`[[X]]`) and mid-message brackets are untouched.
    """
    if not text:
        return text
    import re
    return re.sub(
        r"^\s*\[[a-z][^\]\[]{0,200}\](?!\()",
        "",
        text,
        count=1,
    ).lstrip()


def _clean_for_tts(text: str) -> str:
    """Remove markdown and special characters that don't translate to speech."""
    import re
    # Strip leaked stage directions like "[tender, ...]" before TTS.
    # Without this, Gemini reads the bracketed directive aloud, padding
    # the audio length significantly and producing voice files Telegram
    # can't display correctly.
    text = strip_leading_stage_direction(text)
    # Remove YAML frontmatter (common in Obsidian notes)
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    # Remove markdown headers but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', ' ', text)
    # Remove wikilinks — keep the display text [[target|display]] or [[target]]
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # Remove markdown links — keep the text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove code blocks (multi-line and inline)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    # Remove bullet points and list markers
    text = re.sub(r'^[•·\-\*]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove tags (#tag-name)
    text = re.sub(r'#[\w\-/]+', '', text)
    # Remove emoji (most common ranges)
    text = re.sub(
        r'[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F]',
        '', text
    )
    # Remove horizontal rules
    text = re.sub(r'^[\-\*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


# ── Gemini TTS Backend ───────────────────────────────────────────────────────

def _write_wav(filename: str, pcm_data: bytes, channels: int = 1,
               rate: int = 24000, sample_width: int = 2):
    """Write raw PCM data to a WAV file. Gemini returns 24kHz 16-bit mono."""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


async def _tts_gemini(text: str, style: str = "default") -> str:
    """Generate speech using Gemini TTS API (google-genai)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Apply style prefix for natural language voice steering
    style_prefix = VOICE_STYLES.get(style, VOICE_STYLES["default"])
    prompted_text = style_prefix + text

    # Unique filenames to avoid race conditions with concurrent calls
    uid = uuid.uuid4().hex[:8]
    wav_path = os.path.join(VOICE_DIR, f"tts_{uid}.wav")
    ogg_path = os.path.join(VOICE_DIR, f"tts_{uid}.ogg")

    try:
        # Run the synchronous API call in executor to not block event loop
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=prompted_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=GEMINI_TTS_VOICE,
                            )
                        )
                    ),
                ),
            )
        )

        # Extract PCM audio data from response
        part = response.candidates[0].content.parts[0]
        audio_data = part.inline_data.data
        mime_type = getattr(part.inline_data, "mime_type", "") or ""

        if not audio_data:
            raise RuntimeError("Gemini returned empty audio data")

        # Write PCM to WAV (24kHz, 16-bit, mono)
        _write_wav(wav_path, audio_data)

        # Convert WAV to OGG (Opus) for Telegram
        result_ogg = _wav_to_ogg(wav_path)
        if not result_ogg or not os.path.isfile(result_ogg):
            raise RuntimeError("WAV→Opus conversion produced no output")

        # Size sanity check — Opus at 64 kbps for 1k chars of text should
        # be well under 1 MB. If the OGG comes back unreasonably large
        # (>3 MB), something went wrong (Gemini ran on, ffmpeg fell back
        # to a non-Opus codec, etc). Log a warning so we can see it next
        # time without breaking the flow.
        ogg_size = os.path.getsize(result_ogg)
        wav_size = os.path.getsize(wav_path) if os.path.isfile(wav_path) else 0
        if ogg_size > 3 * 1024 * 1024:
            log.warning(
                f"TTS output suspiciously large: {ogg_size/1024/1024:.1f} MB "
                f"(wav={wav_size/1024/1024:.1f} MB, mime='{mime_type}', "
                f"text={len(text)} chars). Telegram may render as 00:00."
            )

        log.info(
            f"TTS generated (Gemini/{GEMINI_TTS_VOICE}/{style}): "
            f"{len(text)} chars → {ogg_size/1024:.0f} KB ogg "
            f"(wav {wav_size/1024:.0f} KB, mime='{mime_type}')"
        )
        return result_ogg

    except Exception as e:
        log.error(f"Gemini TTS failed: {e}")
        # Clean up partial files
        for p in [wav_path, ogg_path]:
            try:
                os.remove(p)
            except OSError:
                pass
        # Fall through to next backend
        log.info("Falling back from Gemini to next TTS backend...")
        if OPENAI_API_KEY:
            try:
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _tts_openai_api(text)
                )
            except Exception as e2:
                log.error(f"OpenAI TTS fallback also failed: {e2}")
        try:
            return await _tts_edge(text)
        except Exception as e3:
            log.error(f"edge-tts fallback also failed: {e3}")
        raise RuntimeError(f"All TTS backends failed. Gemini error: {e}")

    finally:
        # Clean up intermediate WAV (keep the OGG)
        try:
            os.remove(wav_path)
        except OSError:
            pass


# ── OpenAI TTS Backend ───────────────────────────────────────────────────────

def _tts_openai_api(text: str) -> str:
    """Generate speech using OpenAI TTS API."""
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    uid = uuid.uuid4().hex[:8]
    mp3_path = os.path.join(VOICE_DIR, f"tts_{uid}.mp3")

    response = client.audio.speech.create(
        model="tts-1",
        voice=OPENAI_TTS_VOICE,
        input=text,
    )
    response.stream_to_file(mp3_path)

    # Convert to OGG for Telegram
    ogg_path = _mp3_to_ogg(mp3_path)
    try:
        os.remove(mp3_path)
    except OSError:
        pass

    log.info(f"TTS generated (OpenAI): {len(text)} chars")
    return ogg_path


# ── edge-tts Backend ─────────────────────────────────────────────────────────

async def _tts_edge(text: str) -> str:
    """Generate speech using edge-tts (free Microsoft neural voices)."""
    import edge_tts

    uid = uuid.uuid4().hex[:8]
    mp3_path = os.path.join(VOICE_DIR, f"tts_{uid}.mp3")

    communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
    await communicate.save(mp3_path)

    # Convert to OGG for Telegram
    ogg_path = _mp3_to_ogg(mp3_path)
    try:
        os.remove(mp3_path)
    except OSError:
        pass

    log.info(f"TTS generated (edge-tts): {len(text)} chars")
    return ogg_path


# ── Status / Diagnostics ────────────────────────────────────────────────────

def get_voice_status() -> dict:
    """Return current voice capability status."""
    return {
        "stt_backend": _detect_stt_backend(),
        "tts_backend": _detect_tts_backend(),
        "gemini_voice": GEMINI_TTS_VOICE,
        "gemini_model": GEMINI_TTS_MODEL,
        "voice_dir": VOICE_DIR,
        "ffmpeg_available": _check_ffmpeg(),
        "max_tts_chars": MAX_TTS_CHARS,
    }


def _check_ffmpeg() -> bool:
    """Truthy if ffmpeg can be located and invoked."""
    try:
        ffmpeg = _resolve_ffmpeg()
        subprocess.run([ffmpeg, "-version"], capture_output=True, check=True, timeout=5)
        return True
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError):
        return False
