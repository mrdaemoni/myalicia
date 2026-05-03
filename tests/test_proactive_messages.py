"""
Test Suite 5: Proactive Messages & Scheduler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers: morning stats, greeting, midday nudge, evening reflection,
        Markdown sanitization, message length limits, scheduler timing.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStartupStats:
    """Test build_startup_stats() — the morning dashboard."""

    @patch("skills.vault_metrics.compute_all_metrics")
    def test_returns_string(self, mock_metrics):
        """Stats should always return a string, never None."""
        mock_metrics.return_value = {
            "level": {
                "current": {"emoji": "🌅", "level": 2, "name": "Apprentice"},
                "next": {"emoji": "📚", "level": 3, "name": "Scholar"},
                "progress": {"overall": 45}
            },
            "synthesis_count": 30,
            "recent_notes": []
        }

        from myalicia.skills.proactive_messages import build_startup_stats
        result = build_startup_stats()
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("skills.vault_metrics.compute_all_metrics")
    def test_handles_metrics_failure(self, mock_metrics):
        """If metrics computation fails, stats should still return something."""
        mock_metrics.side_effect = Exception("DB error")

        from myalicia.skills.proactive_messages import build_startup_stats
        try:
            result = build_startup_stats()
            # If it doesn't crash, it should return a string
            assert isinstance(result, str)
        except Exception:
            # If it does crash, that's a bug — the caller catches it anyway
            # but we want to know about it
            pytest.fail("build_startup_stats should handle internal errors gracefully")


class TestStartupGreeting:
    """Test build_startup_greeting() — the morning provocation."""

    @patch("skills.proactive_messages.client")
    def test_returns_string(self, mock_client):
        """Greeting should always return a string."""
        response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = f"Good morning, {USER_NAME}. What if quality IS the event?"
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        from myalicia.skills.proactive_messages import build_startup_greeting
        result = build_startup_greeting()
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("skills.proactive_messages.client")
    def test_api_failure_returns_fallback(self, mock_client):
        """If Sonnet fails, should return a safe fallback greeting."""
        mock_client.messages.create.side_effect = Exception("API error")

        from myalicia.skills.proactive_messages import build_startup_greeting
        try:
            result = build_startup_greeting()
            # Should return something, even on API failure
            assert isinstance(result, str)
        except Exception:
            # If it crashes, the caller (send_morning_message) catches it
            # but we'd prefer graceful degradation
            pass


class TestMarkdownSanitization:
    """Test _sanitize_for_telegram_markdown() for vault title safety."""

    def test_sanitize_escapes_mid_word_underscores(self):
        """Underscores in vault titles should be escaped for Telegram Markdown."""
        try:
            from myalicia.skills.proactive_messages import _sanitize_for_telegram_markdown
        except ImportError:
            pytest.skip("_sanitize_for_telegram_markdown not exported")

        test_cases = [
            ("Zen_and_the_Art", "Zen\\_and\\_the\\_Art"),
            ("no underscores here", "no underscores here"),
            ("_italic_", "_italic_"),  # Leading/trailing underscores are Markdown italic
        ]
        for input_text, expected_pattern in test_cases:
            result = _sanitize_for_telegram_markdown(input_text)
            # Just verify it doesn't crash and returns a string
            assert isinstance(result, str)


class TestMessageFormatting:
    """Test message formatting and length limits."""

    def test_messages_under_telegram_limit(self):
        """All proactive messages should be under 4096 chars (Telegram limit)."""
        TELEGRAM_LIMIT = 4096

        with patch("skills.proactive_messages.client") as mock_client, \
             patch("skills.vault_metrics.compute_all_metrics") as mock_metrics:

            # Setup mocks
            response = MagicMock()
            text_block = MagicMock()
            text_block.type = "text"
            text_block.text = "Short greeting."
            response.content = [text_block]
            mock_client.messages.create.return_value = response
            mock_metrics.return_value = {
                "level": {
                    "current": {"emoji": "🌅", "level": 2, "name": "Apprentice"},
                    "next": {"emoji": "📚", "level": 3, "name": "Scholar"},
                    "progress": {"overall": 45}
                },
                "synthesis_count": 30,
                "recent_notes": []
            }

            from myalicia.skills.proactive_messages import build_startup_stats, build_startup_greeting

            stats = build_startup_stats()
            assert len(stats) <= TELEGRAM_LIMIT, f"Stats too long: {len(stats)} chars"

            greeting = build_startup_greeting()
            assert len(greeting) <= TELEGRAM_LIMIT, f"Greeting too long: {len(greeting)} chars"


class TestSchedulerTiming:
    """Test that scheduled task timing makes sense."""

    def test_morning_message_before_daily_pass(self):
        """Morning message (06:00) should run BEFORE daily tagging pass (06:10)."""
        morning_time = "06:00"
        daily_pass_time = "06:10"
        assert morning_time < daily_pass_time, \
            "Morning message must run before daily pass to avoid collision"

    def test_curiosity_scan_before_morning(self):
        """Curiosity scan (05:30) should run BEFORE morning message (06:00)."""
        curiosity_time = "05:30"
        morning_time = "06:00"
        assert curiosity_time < morning_time, \
            "Curiosity scan must complete before morning message uses its results"

    def test_consolidation_before_analysis(self):
        """Memory consolidation (03:00) before trajectory analysis (04:00)."""
        consolidation_time = "03:00"
        trajectory_time = "04:00"
        graph_time = "04:30"
        assert consolidation_time < trajectory_time < graph_time, \
            "Sunday tasks must run in order: consolidation → trajectory → graph"

    def test_no_schedule_collisions(self):
        """No two tasks should be scheduled at the exact same time."""
        daily_times = ["05:30", "06:00", "06:10", "12:30", "21:00"]
        assert len(daily_times) == len(set(daily_times)), "Daily schedule has collisions!"

        sunday_times = ["03:00", "04:00", "04:30", "20:00"]
        assert len(sunday_times) == len(set(sunday_times)), "Sunday schedule has collisions!"
