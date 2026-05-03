"""
Shared test fixtures for Alicia test suite.
Provides mocked Anthropic client, Telegram bot, file system, and vault structure.

CRITICAL: Must patch environment BEFORE any skills modules are imported,
because they call load_dotenv() and create Anthropic() clients at import time.
"""
import os
import sys
import json
import pytest
import tempfile
import shutil
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# Add parent dir so we can import skills
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Set up fake environment BEFORE any skills import ──────────────────────────
# Skills modules call load_dotenv() and Anthropic() at import time.
# We need the env vars to exist so the client doesn't crash.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-fake-key-for-testing")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-telegram-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-openai-key")

# ── Remove SOCKS proxy vars that crash httpx in Anthropic client ────────────
# The VM sets ALL_PROXY=socks5h://... which requires 'socksio' package.
# Since tests mock the client anyway, we just remove the proxy.
for _proxy_key in ["ALL_PROXY", "all_proxy", "GRPC_PROXY", "grpc_proxy",
                    "FTP_PROXY", "ftp_proxy", "RSYNC_PROXY"]:
    os.environ.pop(_proxy_key, None)

# ── Pre-create directories that skills expect ─────────────────────────────────
os.makedirs(os.path.expanduser("~/alicia/memory"), exist_ok=True)
os.makedirs(os.path.expanduser("~/alicia/logs"), exist_ok=True)


# ── Temp directories for isolated testing ─────────────────────────────────────

@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create a temporary memory directory with structure."""
    mem = tmp_path / "memory"
    mem.mkdir()
    for f in ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]:
        (mem / f).write_text(f"# {f}\n")
    return str(mem)


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal Obsidian vault structure for testing."""
    vault = tmp_path / "vault"
    vault.mkdir()
    for folder in [
        "Alicia/Self/Memory",
        "Alicia/Bridge",
        "Alicia/Wisdom/Synthesis",
        "Wisdom",
        "Quotes",
        "Books",
    ]:
        (vault / folder).mkdir(parents=True)

    (vault / "Wisdom" / "Quality Before Objects.md").write_text(
        "# Quality Before Objects\n\nQuality is the event.\n\n#theme/quality\n"
    )
    (vault / "Wisdom" / "Compounding_And_Layers.md").write_text(
        "# Compounding & Layers\n\nKnowledge compounds when layers connect.\n\n#theme/compounding\n"
    )
    (vault / "Books" / "Zen and the Art_of_Motorcycle_Maintenance.md").write_text(
        "# Zen and the Art of Motorcycle Maintenance\n\nPirsig explores quality.\n"
    )
    (vault / "Quotes" / "Pirsig_on_Quality.md").write_text(
        "# Pirsig on Quality\n\n> Quality is not a thing. It is an event.\n— Robert Pirsig\n"
    )
    (vault / "Alicia" / "Wisdom" / "Synthesis" / "Mastery_does_not_transcend_boredom.md").write_text(
        "# Mastery does not transcend boredom\n\nSynthesis note content.\n"
    )
    (vault / "Alicia" / "Bridge" / "HANDOFF.md").write_text(
        "# HANDOFF.md\n## Last Session\n- Test session\n"
    )
    return str(vault)


# ── Common test data ──────────────────────────────────────────────────────────

MARKDOWN_BREAKING_INPUTS = [
    "· Zen_and_the_Art_of_Motorcycle_Maintenance",
    "· Mastery_does_not_transcend_boredom — it_discovers_that_at_the_center",
    "· Compounding_And_Layers",
    "Here is *bold that never closes",
    "Some *nested *bold* text",
    "_italic that never closes",
    "Here is _nested _italic_ text",
    "*Bold start _italic start but never closed",
    "Text with `backtick that never closes",
    "test_user@example.com",
    "multiple_parts_here@domain.co.uk",
    "📎 *From your vault:*\n· Zen_and_the_Art_of_Motorcycle_Maintenance\n· Quality_Before_Objects",
]

SAFE_MARKDOWN_INPUTS = [
    "Hello, world!",
    "*Bold text*",
    "_Italic text_",
    "`Inline code`",
    f"🌅 *Good morning, {USER_NAME}.*",
    "✅ *Alicia online.*",
    "📎 *From your vault:*\n· Quality Before Objects\n· Compounding",
]
