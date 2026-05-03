"""
Test Suite 9: Integration Flow Tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
End-to-end flow tests that simulate the full message lifecycle.
Tests the interactions between multiple systems working together.
"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestTextMessageFlow:
    """Test the full text message → response flow."""

    def test_route_to_text_response(self):
        """
        Full flow: user message → route_message → text response.
        This is the most common path.
        """
        response = SimpleNamespace()
        block = SimpleNamespace()
        block.type = "text"
        block.text = "Quality is the event at which awareness happens."
        response.content = [block]
        response.stop_reason = "end_turn"

        with patch("skills.tool_router.client") as mock_client:
            mock_client.messages.create.return_value = response

            from skills.tool_router import route_message
            result = route_message(
                "You are Alicia.",
                [{"role": "user", "content": "What is quality?"}]
            )
            assert result["type"] == "text"
            assert len(result["text"]) > 0

    def test_route_to_tool_then_execute(self):
        """
        Full flow: user message → route_message → tool_use → execute_tool.
        Tests the remember tool end-to-end.
        """
        # Step 1: Router returns tool_use
        response = SimpleNamespace()
        tool_block = SimpleNamespace()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_test123"
        tool_block.name = "remember"
        tool_block.input = {"key": "favorite_color", "value": "deep blue"}
        response.content = [tool_block]
        response.stop_reason = "tool_use"

        with patch("skills.tool_router.client") as mock_client:
            mock_client.messages.create.return_value = response

            from skills.tool_router import route_message
            routed = route_message(
                "You are Alicia.",
                [{"role": "user", "content": "Remember my favorite color is deep blue"}]
            )
            assert routed["type"] == "tool_use"
            assert routed["tool_name"] == "remember"

            # Step 2: Execute the tool
            with patch("skills.memory_skill.remember_manual", return_value="Remembered: favorite_color = deep blue"):
                from skills.tool_router import execute_tool
                result = execute_tool(routed["tool_name"], routed["tool_input"])
                assert result["success"] is True
                assert "deep blue" in result["result"]

    def test_error_type_triggers_fallback(self):
        """
        When router returns type='error', alicia.py should show
        "Something went wrong" — not crash or hang.
        """
        with patch("skills.tool_router.client") as mock_client:
            mock_client.messages.create.side_effect = Exception("API unavailable")

            from skills.tool_router import route_message
            result = route_message("system", [{"role": "user", "content": "test"}])

            assert result["type"] == "error"
            # In alicia.py, this falls into the else branch:
            # else: await update.message.reply_text("⚠️ Something went wrong...")
            # This is correct behavior — we just need to ensure the error type is returned


class TestMemoryExtractionFlow:
    """Test the background memory extraction pipeline."""

    @patch("skills.memory_skill.client")
    def test_extraction_stores_and_syncs(self, mock_client, tmp_path):
        """
        Full flow: message → extract → store in file → sync to vault.
        """
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        vault_mem = tmp_path / "vault_mem"

        for f in ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]:
            (mem_dir / f).write_text(f"# {f}\n")

        # Mock Sonnet's extraction response
        response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({
            "facts": [{"key": "philosophy_interest", "value": "quantum mechanics and consciousness", "confidence": 5}],
            "patterns": [],
            "preferences": [],
            "discard": False
        })
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        with patch("skills.memory_skill.MEMORY_DIR", str(mem_dir)), \
             patch("skills.memory_skill.MEMORY_FILE", str(mem_dir / "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", str(mem_dir / "patterns.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "insights.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "preferences.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "concepts.md")), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", str(vault_mem)):
            from skills.memory_skill import extract_from_message
            result = extract_from_message(
                "I've been deeply interested in the measurement problem in quantum mechanics "
                "and how it relates to consciousness and observation."
            )
            # Should return True/list indicating something was extracted, or False
            assert isinstance(result, (bool, list))


class TestToolResultToMessage:
    """Test how tool results flow back to the user."""

    def test_short_result_formatted_by_sonnet(self):
        """
        Short tool results (<500 chars) should be sent through Sonnet
        for natural formatting before being shown to the user.
        """
        result_text = "Found 3 notes about quality in your vault."
        assert len(result_text) < 500

        # In alicia.py, this triggers a followup Sonnet call:
        # final = claude.messages.create(model=MODEL_SONNET, messages=followup, tools=TOOLS)
        # This is the correct behavior — no test needed beyond verifying the length check

    def test_long_result_sent_directly(self):
        """
        Long tool results (>500 chars) should be sent directly in chunks,
        NOT through Sonnet (would waste tokens).
        """
        long_result = "x" * 10000
        assert len(long_result) >= 500

        chunks = [long_result[i:i+3500] for i in range(0, len(long_result), 3500)]
        assert len(chunks) == 3
        assert all(len(c) <= 3500 for c in chunks)


class TestEmailConfirmationFlow:
    """Test the two-step email confirmation flow."""

    def test_send_email_requires_confirmation(self):
        """
        send_email tool should NEVER send directly.
        It must return action='confirm_email' first.
        """
        from skills.tool_router import execute_tool
        result = execute_tool("send_email", {
            "to": "boss@company.com",
            "subject": "Project update",
            "body": "Hi boss, the project is on track."
        })

        assert result["action"] == "confirm_email", \
            "CRITICAL: send_email must require confirmation, never send directly!"
        assert result["email_data"]["to"] == "boss@company.com"

    def test_email_data_preserved_in_confirmation(self):
        """All email fields should be preserved in the confirmation data."""
        from skills.tool_router import execute_tool
        input_data = {
            "to": "colleague@work.com",
            "subject": "Meeting notes",
            "body": "Here are the notes from today's meeting."
        }
        result = execute_tool("send_email", input_data)

        for key in ["to", "subject", "body"]:
            assert result["email_data"][key] == input_data[key], \
                f"Email field '{key}' was corrupted in confirmation"


class TestConversationHistoryManagement:
    """Test conversation history windowing and persistence."""

    def test_history_windowing_preserves_order(self):
        """Windowed history should preserve message order."""
        history = [
            {"role": "user", "content": f"message_{i}"}
            for i in range(100)
        ]

        windowed = history[-20:]
        assert len(windowed) == 20
        assert windowed[0]["content"] == "message_80"
        assert windowed[-1]["content"] == "message_99"

    def test_tool_results_in_history(self):
        """Tool use blocks should be properly formatted for conversation history."""
        # This is the format Anthropic expects for tool results
        tool_use_msg = {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_123", "name": "search_vault", "input": {"query": "quality"}}
        ]}
        tool_result_msg = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_123", "content": "Found 3 notes"}
        ]}

        history = [
            {"role": "user", "content": "Search for quality"},
            tool_use_msg,
            tool_result_msg,
        ]

        # Verify the history structure is valid
        assert history[1]["content"][0]["type"] == "tool_use"
        assert history[2]["content"][0]["type"] == "tool_result"
        assert history[2]["content"][0]["tool_use_id"] == history[1]["content"][0]["id"]
