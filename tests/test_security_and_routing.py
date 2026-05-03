"""
Test Suite 4: Security Classification & Message Routing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers: security levels, context window sizing, email/PDF/voice intent detection,
        system prompt construction, credential redaction.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test against production's classifier directly ────────────────────────────
# Previously this file recreated SECURITY_KEYWORDS locally and tests passed
# while production behaved differently. The <earlier development> dogfood incident — a
# reflective L1 message classified as L4 because it contained "wired" — is
# exactly that shadow-list trap, so we now import from alicia.py.
#
# alicia.py boots the bot at module load, so we can't naively import it. The
# pattern below reads the source, extracts SECURITY_KEYWORDS + the regex
# table + classify_security_level, and execs them in an isolated namespace.

import re as _re_test
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

def _load_classifier():
    src_path = os.path.join(os.path.dirname(__file__), "..", "alicia.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    flags = _re_test.DOTALL | _re_test.MULTILINE
    m = _re_test.search(r"^SECURITY_KEYWORDS\s*=\s*\{.*?^\}", src, flags)
    assert m, "SECURITY_KEYWORDS block not found in alicia.py"
    m2 = _re_test.search(r"^_SECURITY_REGEX\s*=.*?\n\}", src, flags)
    assert m2, "_SECURITY_REGEX block not found in alicia.py"
    m3 = _re_test.search(
        r"^def classify_security_level\(text\):.*?^    return 1", src, flags
    )
    assert m3, "classify_security_level fn not found in alicia.py"
    # Production aliases the regex module as _re. Match that here so the
    # extracted _SECURITY_REGEX dict comprehension finds the name it needs.
    ns: dict = {}
    exec("import re as _re\nimport re\n" + m.group(0) + "\n"
         + m2.group(0) + "\n" + m3.group(0), ns)
    return ns["SECURITY_KEYWORDS"], ns["classify_security_level"]


SECURITY_KEYWORDS, classify_security_level = _load_classifier()


def get_context_size(level):
    return {1: 5, 2: 20, 3: 40, 4: 60}.get(level, 5)


# ── Email/PDF/Voice detection (recreated for isolated testing) ────────────────

EMAIL_PHRASES = [
    "send an email", "send email", "email to", "write an email",
    "draft an email", "compose an email", "mail to",
]

def detect_email_intent(text):
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in EMAIL_PHRASES)


PDF_PHRASES = [
    "create a pdf", "make a pdf", "generate a pdf", "pdf of",
    "convert to pdf", "export as pdf", "save as pdf",
]

def detect_pdf_intent(text):
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in PDF_PHRASES)


VOICE_REQUEST_PHRASES = [
    "say this in voice", "say that in voice", "say it in voice",
    "read that to me", "voice please", "in voice please",
]

def detect_voice_request(text):
    text_lower = text.lower().strip()
    return any(phrase in text_lower for phrase in VOICE_REQUEST_PHRASES)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSecurityClassification:
    """Test security level classification."""

    def test_level_1_default(self):
        assert classify_security_level("What is quality?") == 1
        assert classify_security_level("Hello Alicia") == 1
        assert classify_security_level("Tell me about Pirsig") == 1

    def test_level_2_knowledge_ops(self):
        # L2 covers privacy-sensitive read access. "Research" (a tier-2
        # keyword in production) catches the third example.
        assert classify_security_level("Research quantum computing") == 2
        assert classify_security_level("Read email from yesterday") == 2
        assert classify_security_level("What's in my Obsidian vault") == 2

    def test_level_3_sensitive(self):
        # L3 in production covers outbound publishing and shell execution.
        assert classify_security_level("Send email to the team") == 3
        assert classify_security_level("Run command ls -la") == 3
        assert classify_security_level("Publish this to the blog") == 3

    def test_level_4_critical(self):
        # L4 covers irreversible / financial / credential exposure.
        assert classify_security_level("Delete all my notes") == 4
        assert classify_security_level("Send money to my brother") == 4
        assert classify_security_level("What's my password again?") == 4
        assert classify_security_level("Transfer $100 to checking") == 4

    def test_case_insensitive(self):
        assert classify_security_level("SEND EMAIL to someone") == 3
        assert classify_security_level("DELETE all the things") == 4

    # ── False-positive regressions (caught <earlier development>) ────────────────────

    def test_wired_does_not_trigger_l4(self):
        """Regression: 'wired' contains the substring 'wire' but is not a
        money-transfer action. Caught when a reflective observation about
        wiring composer slots got an L4 passphrase challenge."""
        msg = ("I've been noticing how you're becoming much more connected "
               "— and today we wired the morning slot, the contradiction-"
               "voice picker, and made my replies count")
        assert classify_security_level(msg) == 1, (
            f"reflective observation must be L1, got L{classify_security_level(msg)}"
        )

    def test_executive_does_not_trigger_l3(self):
        """'executive' contains 'execute' but is not a shell-execution request."""
        assert classify_security_level("My executive coach said...") == 1
        assert classify_security_level(
            "The Effective Executive is a great book"
        ) == 1

    def test_sharepoint_does_not_trigger_l3(self):
        """'sharepoint' contains 'share' but is not a publishing request."""
        # 'share document' is the production phrase; bare 'share' should not fire
        assert classify_security_level("I saw it on SharePoint") == 1
        assert classify_security_level("Shareholders meeting tomorrow") == 1

    def test_lamppost_does_not_trigger_l3(self):
        """'lamppost' contains 'post' but is not a publishing request."""
        # 'post' is no longer a bare L3 keyword in production
        assert classify_security_level("Met him by the lamppost") == 1
        assert classify_security_level("Compost smells in the kitchen") == 1
        assert classify_security_level("Post-meeting writeup") == 1

    def test_forwarding_motion_does_not_trigger_l3(self):
        """'moving forward' contains 'forward' but is not an email forward."""
        # 'forward email' is the production phrase
        assert classify_security_level("Moving forward, let's commit") == 1
        assert classify_security_level("Looking forward to it") == 1

    def test_personal_phrase_is_not_l2(self):
        """'personal' alone is too aggressive; 'personal data' is the actual concern."""
        assert classify_security_level("This is personal to me") == 1
        assert classify_security_level("Personal AI agent on my Mac") == 1
        assert classify_security_level("Read my personal data file") == 2

    def test_word_boundary_phrase_still_matches(self):
        """Phrase keywords like 'send email' still match as a phrase."""
        assert classify_security_level("Please send email now") == 3
        assert classify_security_level("send email tomorrow morning") == 3

    def test_context_window_sizing(self):
        """Higher security = larger context window for better decision-making."""
        assert get_context_size(1) == 5
        assert get_context_size(2) == 20
        assert get_context_size(3) == 40
        assert get_context_size(4) == 60
        assert get_context_size(99) == 5  # Unknown level defaults to 5


class TestIntentDetection:
    """Test email, PDF, and voice intent detection."""

    def test_email_intent_positive(self):
        assert detect_email_intent(f"Send an email to {USER_NAME}") is True
        assert detect_email_intent("email to test@example.com") is True
        assert detect_email_intent("Draft an email about the project") is True

    def test_email_intent_negative(self):
        assert detect_email_intent("Tell me about email protocols") is False
        assert detect_email_intent("What is SMTP?") is False

    def test_pdf_intent_positive(self):
        assert detect_pdf_intent("Create a PDF of S3E01") is True
        assert detect_pdf_intent("Make a pdf from that note") is True
        assert detect_pdf_intent("Export as pdf") is True

    def test_pdf_intent_negative(self):
        assert detect_pdf_intent("What format is a PDF?") is False
        assert detect_pdf_intent("Tell me about document formats") is False

    def test_voice_request_positive(self):
        assert detect_voice_request("Say that in voice") is True
        assert detect_voice_request("Read that to me") is True
        assert detect_voice_request("voice please") is True

    def test_voice_request_negative(self):
        assert detect_voice_request("What is voice recognition?") is False
        assert detect_voice_request("Tell me about audio") is False


class TestCredentialRedaction:
    """Test that API keys and tokens are never leaked in responses."""

    def test_api_key_redacted(self):
        """If a response accidentally contains the API key, it must be redacted."""
        fake_key = "sk-ant-api03-xxxxxxxxxxxxxxxxxxxx"
        reply = f"Your key is {fake_key} and that's sensitive."

        # Simulate the redaction logic from alicia.py
        for env_var_value in [fake_key]:
            if env_var_value and env_var_value in reply:
                reply = reply.replace(env_var_value, "[REDACTED]")

        assert fake_key not in reply
        assert "[REDACTED]" in reply

    def test_telegram_token_redacted(self):
        """Telegram bot tokens must also be redacted."""
        fake_token = "8184397005:AAF8nAdfW1Gdc9UZPKrl46AjJxyuiMM3Woo"
        reply = f"Bot token: {fake_token}"

        for env_var_value in [fake_token]:
            if env_var_value and env_var_value in reply:
                reply = reply.replace(env_var_value, "[REDACTED]")

        assert fake_token not in reply


class TestConversationHistory:
    """Test conversation history management."""

    def test_windowing_respects_security_level(self):
        """Conversation window should be sized by security level."""
        history = [{"role": "user", "content": f"msg_{i}"} for i in range(100)]

        for level, expected_size in [(1, 5), (2, 20), (3, 40), (4, 60)]:
            ctx_size = get_context_size(level)
            windowed = history[-ctx_size:]
            assert len(windowed) == expected_size

    def test_empty_history_doesnt_crash(self):
        """Empty conversation history should work with any window size."""
        history = []
        for level in [1, 2, 3, 4]:
            ctx_size = get_context_size(level)
            windowed = history[-ctx_size:]
            assert windowed == []


class TestMessageChunking:
    """Test that long messages are properly chunked for Telegram's 4096 char limit."""

    def test_chunking_at_3500_chars(self):
        """Long text should be chunked at 3500 chars."""
        long_text = "x" * 10000
        chunks = [long_text[i:i+3500] for i in range(0, len(long_text), 3500)]
        assert len(chunks) == 3  # 3500 + 3500 + 3000
        assert all(len(c) <= 3500 for c in chunks)
        assert "".join(chunks) == long_text

    def test_empty_text_produces_one_chunk(self):
        """Empty or short text should produce exactly one chunk."""
        for text in ["", "Hello", "x" * 3500]:
            chunks = [text[i:i+3500] for i in range(0, len(text), 3500)] if text else [""]
            assert len(chunks) >= 1
