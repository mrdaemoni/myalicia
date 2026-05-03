"""
core.voice — voice input/output handling and call flows.

PLANNED CONTENT (currently lives in myalicia/alicia.py:1922-2300):

Functions:

  handle_voice(update, context)
      Telegram voice-message handler. STT via Anthropic, then routes
      through handle_message with is_voice=True.

  _handle_call_voice(update, user_text)
      The "/call" mode: live conversational voice over Telegram.

  _handle_unpack_voice(update, user_text)
      The "/unpack" mode: long-form voice processing.

These integrate with skills.voice_skill, skills.voice_intelligence,
and skills.prosody_calibration for the actual TTS/STT and tone work.

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py:1922-2300
  - Imports: telegram, the voice skills
  - Depends on handle_message — extract that first

Status: not yet extracted.
"""
