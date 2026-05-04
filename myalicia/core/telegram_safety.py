"""
core.telegram_safety — markdown-safe Telegram send helpers.

Telegram's Markdown parser is strict; if a message contains an unmatched
asterisk or underscore, ``message.reply_text(text, parse_mode="Markdown")``
raises BadRequest. These helpers attempt the markdown send first and
fall back to a plain-text version (with formatting markers stripped)
if the parser refuses.

Use these instead of the raw Telegram methods anywhere user-visible
content is being sent — most LLM-generated text contains stray
asterisks that would otherwise break the send.

Extracted from myalicia/alicia.py in Phase 2b of the core/ split.
"""
from __future__ import annotations

from typing import Any

from telegram.error import BadRequest as TelegramBadRequest


def _strip_markdown(text: str) -> str:
    """Remove the Telegram Markdown formatting characters that broke parsing.

    Conservative — only strips the three characters that cause BadRequest:
    `*`, `_`, and backticks. Leaves brackets, parens, and other punctuation
    alone so links remain readable as plain text.
    """
    return text.replace("*", "").replace("_", "").replace("`", "")


async def safe_reply_md(message: Any, text: str, **kwargs: Any) -> Any:
    """Reply with Markdown formatting; fall back to plain text if it fails.

    ``message`` is a python-telegram-bot Message object (typically
    ``update.message``). ``text`` is the body. Any extra keyword args
    pass through to ``reply_text`` (e.g. ``disable_web_page_preview``).

    Returns the sent Message object so callers can read its ``message_id``.
    """
    try:
        return await message.reply_text(text, parse_mode="Markdown", **kwargs)
    except TelegramBadRequest:
        return await message.reply_text(_strip_markdown(text), **kwargs)


async def safe_send_md(bot: Any, chat_id: int, text: str, **kwargs: Any) -> Any:
    """Send a message via the bot with Markdown; fall back to plain text on parse error.

    ``bot`` is a python-telegram-bot Bot object. ``chat_id`` is the
    target chat. Used for proactive (un-prompted) sends — morning
    messages, midday nudges, weekly synthesis posts, etc.

    Returns the sent Message object.
    """
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs
        )
    except TelegramBadRequest:
        return await bot.send_message(
            chat_id=chat_id, text=_strip_markdown(text), **kwargs
        )


__all__ = [
    "safe_reply_md",
    "safe_send_md",
]
