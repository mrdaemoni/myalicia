"""
Test Suite 3: Tool Router
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers: route_message parsing, execute_tool dispatch, error type handling,
        the "Something went wrong" bug from error type responses.
"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helper to create mock Anthropic responses ────────────────────────────────

def make_text_response(text, stop_reason="end_turn"):
    resp = SimpleNamespace()
    block = SimpleNamespace()
    block.type = "text"
    block.text = text
    resp.content = [block]
    resp.stop_reason = stop_reason
    return resp


def make_tool_response(tool_name, tool_input, tool_id="toolu_123", thinking=None, stop_reason="tool_use"):
    resp = SimpleNamespace()
    blocks = []
    if thinking:
        tb = SimpleNamespace()
        tb.type = "text"
        tb.text = thinking
        blocks.append(tb)
    tub = SimpleNamespace()
    tub.type = "tool_use"
    tub.id = tool_id
    tub.name = tool_name
    tub.input = tool_input
    blocks.append(tub)
    resp.content = blocks
    resp.stop_reason = stop_reason
    return resp


# ── Router Tests ──────────────────────────────────────────────────────────────

class TestRouteMessage:
    """Tests for route_message() — the Sonnet routing function."""

    @patch("skills.tool_router.client")
    def test_text_response_parsed(self, mock_client):
        """Text-only responses should return type='text'."""
        mock_client.messages.create.return_value = make_text_response(
            "Quality is the event at which the subject becomes aware of the object."
        )
        from skills.tool_router import route_message
        result = route_message("system prompt", [{"role": "user", "content": "test"}])

        assert result["type"] == "text"
        assert "Quality" in result["text"]

    @patch("skills.tool_router.client")
    def test_tool_use_response_parsed(self, mock_client):
        """Tool use responses should return type='tool_use' with name and input."""
        mock_client.messages.create.return_value = make_tool_response(
            "search_vault", {"query": "quality"}, thinking="Let me search the vault."
        )
        from skills.tool_router import route_message
        result = route_message("system prompt", [{"role": "user", "content": "find quality"}])

        assert result["type"] == "tool_use"
        assert result["tool_name"] == "search_vault"
        assert result["tool_input"] == {"query": "quality"}
        assert result["thinking"] == "Let me search the vault."

    @patch("skills.tool_router.client")
    def test_api_error_returns_error_type(self, mock_client):
        """API errors should return type='error', not crash."""
        mock_client.messages.create.side_effect = Exception("API timeout")
        from skills.tool_router import route_message
        result = route_message("system prompt", [{"role": "user", "content": "test"}])

        assert result["type"] == "error"
        assert "API timeout" in result["error"]

    @patch("skills.tool_router.client")
    def test_error_type_not_text_or_tool(self, mock_client):
        """
        CRITICAL: The 'error' type is NEITHER 'text' NOR 'tool_use'.
        In alicia.py, the handle_message function checks:
          if routed["type"] == "tool_use": ...
          elif routed["type"] == "text": ...
          else: send "Something went wrong"

        An 'error' response WILL trigger "Something went wrong" — which is correct
        but we need to ensure the error is logged and the user sees a useful message.
        """
        mock_client.messages.create.side_effect = ConnectionError("Network failure")
        from skills.tool_router import route_message
        result = route_message("system prompt", [{"role": "user", "content": "test"}])

        assert result["type"] == "error", "Router should return 'error' type on API failure"
        assert result["type"] not in ("text", "tool_use"), \
            "Error responses must be distinguishable from text/tool_use"


# ── Execute Tool Tests ────────────────────────────────────────────────────────

class TestExecuteTool:
    """Tests for execute_tool() — the tool dispatch function."""

    def test_unknown_tool_returns_error(self):
        """Unknown tools should return {success: False} not crash."""
        from skills.tool_router import execute_tool
        result = execute_tool("nonexistent_tool", {"arg": "value"})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    # ── Phase 11.6 — recent_responses tool ──────────────────────────────────

    def test_recent_responses_requires_synthesis_title(self):
        """Missing or empty synthesis_title returns {success: False}."""
        from skills.tool_router import execute_tool
        result = execute_tool("recent_responses", {})
        assert result["success"] is False
        assert "synthesis_title" in result["error"].lower()
        result = execute_tool("recent_responses", {"synthesis_title": "   "})
        assert result["success"] is False

    def test_recent_responses_empty_returns_helpful_message(self):
        """When no responses exist, return a success=True with a 'compose
        normally' hint, not an error — Sonnet should know it's safe to skip
        past-conversation references."""
        from skills.tool_router import execute_tool
        with patch(
            "skills.response_capture.get_responses_for_synthesis",
            return_value=[],
        ):
            result = execute_tool(
                "recent_responses",
                {"synthesis_title": "Some synthesis title"},
            )
        assert result["success"] is True
        assert "no captured responses" in result["result"].lower()
        assert "compose normally" in result["result"].lower()

    def test_recent_responses_formats_results_for_sonnet(self):
        """When responses exist, return them in a Sonnet-friendly format
        (newest first, with timestamp + channel + archetype + body excerpt)."""
        from skills.tool_router import execute_tool
        fake_responses = [
            {
                "captured_at": "2026-04-25T18:00:00+00:00",
                "channel": "text",
                "archetype": "Beatrice",
                "body_excerpt": "still very true",
                "synthesis_referenced": "S",
                "kind": "response",
            },
            {
                "captured_at": "2026-04-22T10:00:00+00:00",
                "channel": "voice",
                "archetype": "Daimon",
                "body_excerpt": "the resistance is the practice",
                "synthesis_referenced": "S",
                "kind": "response",
            },
        ]
        with patch(
            "skills.response_capture.get_responses_for_synthesis",
            return_value=fake_responses,
        ):
            result = execute_tool(
                "recent_responses",
                {"synthesis_title": "S", "max_recent": 5},
            )
        assert result["success"] is True
        body = result["result"]
        # Must include both excerpts
        assert "still very true" in body
        assert "resistance is the practice" in body
        # Must include archetypes and channels
        assert "Beatrice" in body and "Daimon" in body
        assert "text" in body and "voice" in body
        # Must include date-only timestamps
        assert "2026-04-25" in body
        assert "2026-04-22" in body

    def test_send_email_returns_confirm_action(self):
        """send_email should NEVER send directly — always returns confirm_email action."""
        from skills.tool_router import execute_tool
        result = execute_tool("send_email", {
            "to": "test@example.com",
            "subject": "Test",
            "body": "Hello"
        })
        assert result["success"] is True
        assert result["action"] == "confirm_email"
        assert result["email_data"]["to"] == "test@example.com"

    @patch("skills.tool_router.remember_manual", create=True)
    def test_remember_tool_returns_result(self, mock_remember):
        """remember tool should return the confirmation string."""
        # We need to patch the import inside execute_tool
        with patch.dict("sys.modules", {}):
            from skills.tool_router import execute_tool
            with patch("skills.memory_skill.remember_manual", return_value="Remembered: key = value"):
                result = execute_tool("remember", {"key": "test_key", "value": "test_value"})
                assert result["success"] is True

    def test_tool_exception_returns_error_dict(self):
        """Any exception in tool execution should return {success: False, error: str}."""
        from skills.tool_router import execute_tool
        # generate_pdf with impossible input should fail gracefully
        with patch("skills.pdf_skill.generate_pdf_from_query", side_effect=FileNotFoundError("no such note")):
            result = execute_tool("generate_pdf", {"note_name": "nonexistent_note_xyz"})
            assert result["success"] is False
            assert isinstance(result["error"], str)

    @patch("skills.tool_router.semantic_search_formatted", create=True)
    def test_search_vault_with_top_k(self, mock_search):
        """search_vault should pass top_k parameter."""
        mock_search.return_value = "Results here"
        from skills.tool_router import execute_tool
        with patch("skills.semantic_search.semantic_search_formatted", return_value="Results"):
            result = execute_tool("search_vault", {"query": "quality", "top_k": 3})
            assert result["success"] is True

    def test_research_depth_routing(self):
        """Research tool should route to correct depth function."""
        from skills.tool_router import execute_tool

        for depth, expected_func in [("quick", "research_quick"), ("brief", "research_brief"), ("deep", "research_deep")]:
            with patch(f"skills.research_skill.{expected_func}", return_value=("Summary", "/path")) as mock_fn:
                if depth == "quick":
                    with patch("skills.research_skill.research_quick", return_value="Quick result"):
                        result = execute_tool("research", {"topic": "quantum", "depth": depth})
                elif depth == "deep":
                    with patch("skills.research_skill.research_deep", return_value=("Deep summary", "/path")):
                        result = execute_tool("research", {"topic": "quantum", "depth": depth})
                else:
                    with patch("skills.research_skill.research_brief", return_value=("Brief summary", "/path")):
                        result = execute_tool("research", {"topic": "quantum", "depth": depth})
                assert result["success"] is True


# ── Tool Result Handling Tests ────────────────────────────────────────────────

class TestToolResultHandling:
    """Test how alicia.py handles different tool result shapes."""

    def test_tool_result_none_handling(self):
        """Tools that return None in result field should be handled."""
        from skills.tool_router import execute_tool

        # Simulate each tool that could return None
        tools_that_might_return_none = [
            ("get_vault_stats", {}, "skills.vault_intelligence.get_vault_stats"),
            ("get_random_quote", {}, "skills.quote_skill.get_random_quote"),
            ("inbox_summary", {}, "skills.gmail_skill.get_inbox_summary"),
        ]

        for tool_name, tool_input, patch_path in tools_that_might_return_none:
            with patch(patch_path, return_value=None):
                result = execute_tool(tool_name, tool_input)
                assert result["success"] is True
                assert result["result"] is not None, \
                    f"{tool_name} returned None result — will cause str() crash in alicia.py"
