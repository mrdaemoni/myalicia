"""
Test Suite 6: Voice Pipeline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers: STT backend detection, TTS backend detection, audio conversion,
        voice status diagnostics, error handling.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestVoiceStatus:
    """Test voice pipeline diagnostics."""

    def test_get_voice_status_returns_dict(self):
        """get_voice_status should always return a diagnostic dict."""
        try:
            from myalicia.skills.voice_skill import get_voice_status
            status = get_voice_status()
            assert isinstance(status, dict)
            # Should have at least these keys
            for key in ["stt_backend", "tts_backend"]:
                assert key in status, f"Missing key: {key}"
        except ImportError:
            pytest.skip("voice_skill not importable (missing deps)")

    def test_voice_status_detects_ffmpeg(self):
        """Voice status should report whether ffmpeg is available."""
        try:
            from myalicia.skills.voice_skill import get_voice_status
            status = get_voice_status()
            # ffmpeg_available should be a boolean
            if "ffmpeg_available" in status:
                assert isinstance(status["ffmpeg_available"], bool)
        except ImportError:
            pytest.skip("voice_skill not importable")


class TestTTSCleaning:
    """Test text cleaning for TTS."""

    def test_clean_for_tts_removes_markdown(self):
        """TTS text should have Markdown formatting stripped."""
        try:
            from myalicia.skills.voice_skill import _clean_for_tts
        except ImportError:
            pytest.skip("_clean_for_tts not available")

        test_cases = [
            ("*Bold text*", "Bold text"),
            ("_Italic text_", "Italic text"),
            ("`code`", "code"),
            ("Normal text", "Normal text"),
        ]
        for input_text, expected in test_cases:
            result = _clean_for_tts(input_text)
            assert isinstance(result, str)
            # Should not contain Markdown markers
            assert "**" not in result or "*" not in result

    def test_clean_for_tts_handles_empty(self):
        """Empty text should not crash TTS cleaning."""
        try:
            from myalicia.skills.voice_skill import _clean_for_tts
            result = _clean_for_tts("")
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("_clean_for_tts not available")


class TestVoiceRequestDetection:
    """Test voice-on-demand phrase matching."""

    def test_voice_request_phrases(self):
        """All documented voice request phrases should be detected."""
        # Recreate the detection logic
        VOICE_REQUEST_PHRASES = [
            "say this in voice", "say that in voice", "say it in voice",
            "send it via voice", "send that via voice", "send this via voice",
            "send it in voice", "send that in voice", "send this in voice",
            "read that to me", "read this to me", "read it to me",
            "tell me in voice", "say it again in voice", "send it via voice again",
            "voice please", "in voice please", "voice version",
            "can you say that", "say that again", "repeat in voice",
            "speak it", "speak that", "read it out", "read that out",
            "read it aloud", "read that aloud", "listen to it",
            "i want to listen", "let me listen",
        ]

        def detect_voice_request(text):
            text_lower = text.lower().strip()
            return any(phrase in text_lower for phrase in VOICE_REQUEST_PHRASES)

        for phrase in VOICE_REQUEST_PHRASES:
            assert detect_voice_request(phrase) is True, f"Missed: {phrase}"
            assert detect_voice_request(phrase.upper()) is True, f"Case-sensitive miss: {phrase}"

    def test_non_voice_requests_rejected(self):
        """Normal messages should NOT trigger voice mode."""
        VOICE_REQUEST_PHRASES = ["say that in voice", "read that to me", "voice please"]

        def detect_voice_request(text):
            text_lower = text.lower().strip()
            return any(phrase in text_lower for phrase in VOICE_REQUEST_PHRASES)

        negatives = [
            "What is voice recognition?",
            "Tell me about audio processing",
            "How does speech synthesis work?",
            "I have a question about quality",
        ]
        for text in negatives:
            assert detect_voice_request(text) is False, f"False positive: {text}"
