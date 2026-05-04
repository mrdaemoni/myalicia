"""
core.main — bot setup helpers (Phase 7, partial).

This module's eventual job is to be the runtime entry point: build the
Telegram application, register handlers, start the scheduler thread,
and run the polling loop. As of v0.1.x the heavy lifting still lives
in ``myalicia.alicia.main``; what's here are the small bot-setup
helpers that landed first.

Currently extracted:
  - ALICIA_MENU_COMMANDS — the curated /command menu shown in Telegram
  - set_alicia_menu_commands — pushes that menu to the Telegram API

Planned (per REFACTORING.md Phase 7):
  - build_application — construct the Telegram Application
  - register_all_handlers — wire up message/voice/reaction/callback handlers
  - main — the runtime entry point
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# The /commands menu Telegram surfaces in its UI when the user types "/".
# Order matters: the first ~5 should be the most-used. Keep this list
# curated — Telegram's UI gets crowded fast. Less-used commands stay
# discoverable via /skills.
ALICIA_MENU_COMMANDS: list[tuple[str, str]] = [
    ("walk",          "Stream-of-consciousness walk mode"),
    ("done",          "Finish the active walk / drive / unpack session"),
    ("draw",          "Render a drawing from her current archetype weather"),
    ("archetypes",    "Show today's archetype weather and distribution"),
    ("call",          "Start a live voice conversation"),
    ("unpack",        "Deep extraction from a voice monologue"),
    ("drive",         "5-min rapid synthesis with vault connections"),
    ("note",          "Capture a quick note into the vault"),
    ("semanticsearch", "Search the vault by meaning"),
    ("memory",        "Show what Alicia remembers about you"),
    ("noticings",     "Themes Alicia has been quietly tracking"),
    ("retro",         "Sunday self-portrait — what she noticed this week"),
    ("conversation",  "Switch / list / create conversation routings"),
    ("dailyquote",    "Pull a quote from the vault"),
    ("briefingnow",   "Run the morning briefing on demand"),
    ("status",        "System health and pipeline status"),
    ("skills",        "Full catalog of every command Alicia has"),
]


async def set_alicia_menu_commands(app: Any) -> None:
    """Push the curated menu to Telegram. Idempotent — safe to call on every boot.

    Wraps ``app.bot.set_my_commands(...)``. Any failure (network, auth,
    rate limit) is logged and swallowed — a missing menu is not worth
    crashing the boot for.
    """
    # Lazy import: telegram is a core dep but we want this module to
    # import cleanly even in environments that don't have it (tests,
    # syntax-check CI without the full pip install).
    try:
        from telegram import BotCommand
    except ImportError:
        log.warning("set_alicia_menu_commands: python-telegram-bot not installed; skipping")
        return

    try:
        commands = [BotCommand(name, desc) for name, desc in ALICIA_MENU_COMMANDS]
        await app.bot.set_my_commands(commands)
        log.info(f"Telegram menu set: {len(commands)} commands")
    except Exception as e:
        log.warning(f"set_my_commands failed: {e}")


__all__ = [
    "ALICIA_MENU_COMMANDS",
    "set_alicia_menu_commands",
]
