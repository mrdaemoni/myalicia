"""
surfaces.telegram — Telegram bot adapter.

The primary conversational surface for My Alicia. Currently the entire
Telegram integration lives in myalicia/alicia.py (the legacy monolith).
This module is the destination for that extraction.

PLANNED CONTENT:

  register(application) -> None
      Wires up message, voice, reaction, and command handlers on a
      pre-built telegram.ext.Application. Called from core.main.

  send(chat_id, text, **kwargs) -> None
      Sends a message OUT to the user. Used by proactive_messages and
      scheduled tasks.

  send_voice(chat_id, audio) -> None
      Sends a voice note. Used by voice_skill.

  send_dashboard(chat_id, html) -> None
      Sends a rendered dashboard image or interactive view.

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py — Telegram-specific code throughout
  - The handle_message and handle_voice functions stay in core/
  - Only the protocol-translation glue lives here
  - Reads config from config.surfaces.telegram

Status: not yet extracted. Stub for the planned location.
"""
