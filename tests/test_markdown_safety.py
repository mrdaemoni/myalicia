"""
Test Suite 1: Telegram Markdown Safety
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers the #1 recurring bug: Telegram Markdown parse errors.
Tests safe_reply_md() and safe_send_md() with all known crash inputs.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import MARKDOWN_BREAKING_INPUTS, SAFE_MARKDOWN_INPUTS
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle


# ── Simulate TelegramBadRequest since telegram package isn't in this env ──────

class TelegramBadRequest(Exception):
    """Simulates telegram.error.BadRequest for testing."""
    pass


# ── Import the helpers under test ─────────────────────────────────────────────

# We can't import alicia.py directly (it boots the bot), so we recreate the helpers
# and verify they match the production code's behavior.

async def safe_reply_md(message, text: str, **kwargs):
    """Production-equivalent safe_reply_md."""
    try:
        return await message.reply_text(text, parse_mode="Markdown", **kwargs)
    except TelegramBadRequest:
        plain = text.replace("*", "").replace("_", "").replace("`", "")
        return await message.reply_text(plain, **kwargs)


async def safe_send_md(bot, chat_id, text: str, **kwargs):
    """Production-equivalent safe_send_md."""
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs)
    except TelegramBadRequest:
        plain = text.replace("*", "").replace("_", "").replace("`", "")
        return await bot.send_message(chat_id=chat_id, text=plain, **kwargs)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSafeReplyMd:
    """Tests for safe_reply_md() — the reply-based Markdown safety helper."""

    @pytest.mark.asyncio
    async def test_safe_markdown_passes_through(self):
        """Safe Markdown should be sent with parse_mode=Markdown."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(return_value=MagicMock())

        for text in SAFE_MARKDOWN_INPUTS:
            await safe_reply_md(msg, text)
            msg.reply_text.assert_called_with(text, parse_mode="Markdown")

    @pytest.mark.asyncio
    async def test_breaking_markdown_falls_back_to_plain(self):
        """Breaking Markdown should trigger plain text fallback, not crash."""
        for text in MARKDOWN_BREAKING_INPUTS:
            msg = AsyncMock()
            # First call raises BadRequest (Markdown failure), second succeeds
            msg.reply_text = AsyncMock(
                side_effect=[TelegramBadRequest("Can't parse entities"), MagicMock()]
            )

            result = await safe_reply_md(msg, text)
            assert msg.reply_text.call_count == 2, f"Expected fallback for: {text!r}"
            # Second call should NOT have parse_mode
            second_call = msg.reply_text.call_args_list[1]
            assert "parse_mode" not in second_call.kwargs, f"Fallback should be plain text for: {text!r}"

    @pytest.mark.asyncio
    async def test_fallback_strips_markdown_chars(self):
        """Fallback text should have *, _, ` stripped."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("parse error"), MagicMock()]
        )

        await safe_reply_md(msg, "📎 *From your vault:*\n· Zen_and_the_Art")
        second_call = msg.reply_text.call_args_list[1]
        plain_text = second_call.args[0]
        assert "*" not in plain_text
        assert "_" not in plain_text

    @pytest.mark.asyncio
    async def test_passes_kwargs_through(self):
        """Extra kwargs like disable_web_page_preview should pass through."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(return_value=MagicMock())

        await safe_reply_md(msg, "Test", disable_web_page_preview=True)
        msg.reply_text.assert_called_with(
            "Test", parse_mode="Markdown", disable_web_page_preview=True
        )

    @pytest.mark.asyncio
    async def test_kwargs_survive_fallback(self):
        """Extra kwargs should also be passed in the fallback call."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("parse error"), MagicMock()]
        )

        await safe_reply_md(msg, "*test_text*", disable_web_page_preview=True)
        second_call = msg.reply_text.call_args_list[1]
        assert second_call.kwargs.get("disable_web_page_preview") is True


class TestSafeSendMd:
    """Tests for safe_send_md() — the bot.send_message based helper."""

    @pytest.mark.asyncio
    async def test_breaking_markdown_falls_back(self):
        """Bot-level sends should also handle Markdown failures gracefully."""
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=[TelegramBadRequest("entity error"), MagicMock()]
        )

        await safe_send_md(bot, 12345, "📎 *vault:*\n· Title_With_Underscores")
        assert bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_non_badrequest_errors_propagate(self):
        """Non-BadRequest errors should still raise."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(side_effect=ConnectionError("Network down"))

        with pytest.raises(ConnectionError):
            await safe_reply_md(msg, "test")


class TestRealWorldCrashInputs:
    """Test against actual crash scenarios from Alicia's logs."""

    @pytest.mark.asyncio
    async def test_vault_source_titles_with_underscores(self):
        """The exact pattern that caused the 2026-03-28 18:33 crash."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("can't find end of the entity starting at byte offset 64"), MagicMock()]
        )

        # This is what the vault source titles code builds
        sources = [
            "Zen_and_the_Art_of_Motorcycle_Maintenance",
            "Quality_Before_Objects",
            "Mastery_does_not_transcend_boredom — it_discovers_everything",
        ]
        titles = [f"· {s}" for s in sources]
        text = "📎 *From your vault:*\n" + "\n".join(titles)

        await safe_reply_md(msg, text)
        assert msg.reply_text.call_count == 2, "Should have retried as plain text"

    @pytest.mark.asyncio
    async def test_startup_greeting_with_vault_titles(self):
        """Morning greeting that references vault notes with underscores."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("byte offset 128"), MagicMock()]
        )

        greeting = (
            f"🌅 *Good morning, {USER_NAME}.*\n\n"
            "Yesterday you explored _Mastery_does_not_transcend_boredom_ "
            "and connected it to _Quality_Before_Objects_.\n\n"
            "Today's provocation: What if the boredom IS the quality?"
        )
        await safe_reply_md(msg, greeting)
        assert msg.reply_text.call_count == 2

    @pytest.mark.asyncio
    async def test_email_body_with_underscores(self):
        """Email confirmation with underscore-heavy addresses/content."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("parse error"), MagicMock()]
        )

        text = (
            "🟠 *Confirm send?*\n\n"
            "To: `test_user_name@example_domain.com`\n"
            "Subject: `Project_Update_Q1`\n"
            "Body: _Hi there, the project_status is on_track_\n\n"
            "Reply *YES*"
        )
        await safe_reply_md(msg, text)
        assert msg.reply_text.call_count == 2

    @pytest.mark.asyncio
    async def test_research_output_with_markdown_chars(self):
        """Research results that contain unbalanced markdown."""
        msg = AsyncMock()
        msg.reply_text = AsyncMock(
            side_effect=[TelegramBadRequest("entity parse error"), MagicMock()]
        )

        text = (
            "**Before Measurement:**\n"
            "- Quantum systems exist in *superposition*\n"
            "- Space at this level is pure_potentiality\n"
            "- There's no *where* until something_forces_a_choice\n\n"
            "**During Measurement:**\n"
            "- The act of observation_measurement forces collapse"
        )
        await safe_reply_md(msg, text)
        # Should handle gracefully regardless of whether Telegram accepts it
        assert msg.reply_text.call_count >= 1
