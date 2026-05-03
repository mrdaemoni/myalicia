"""
Test Suite 2: Memory System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers: memory file I/O, sync to vault, truncation bugs, extraction, consolidation.
"""
import os
import sys
import pytest
import shutil
import tempfile
from unittest.mock import patch, MagicMock
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Memory file I/O tests ────────────────────────────────────────────────────

class TestMemoryFileOps:
    """Test memory file creation, reading, and writing."""

    def test_ensure_memory_structure_creates_files(self, tmp_path):
        """ensure_memory_structure should create all 5 memory files if missing."""
        mem_dir = str(tmp_path / "memory")
        vault_dir = str(tmp_path / "vault")
        vault_memory_dir = str(tmp_path / "vault" / "Self" / "Memory")

        with patch("skills.memory_skill.MEMORY_DIR", mem_dir), \
             patch("skills.memory_skill.MEMORY_FILE", os.path.join(mem_dir, "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", os.path.join(mem_dir, "patterns.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", os.path.join(mem_dir, "insights.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", os.path.join(mem_dir, "preferences.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", os.path.join(mem_dir, "concepts.md")), \
             patch("skills.memory_skill.VAULT", vault_dir), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", vault_memory_dir):
            from myalicia.skills.memory_skill import ensure_memory_structure
            ensure_memory_structure()

            assert os.path.isdir(mem_dir)
            for f in ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]:
                assert os.path.exists(os.path.join(mem_dir, f)), f"Missing: {f}"

    def test_load_memory_files_returns_dict(self, tmp_memory_dir, tmp_path):
        """load_memory_files should return a dict with all 5 keys."""
        vault_dir = str(tmp_path / "vault")
        with patch("skills.memory_skill.MEMORY_DIR", tmp_memory_dir), \
             patch("skills.memory_skill.MEMORY_FILE", os.path.join(tmp_memory_dir, "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", os.path.join(tmp_memory_dir, "patterns.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", os.path.join(tmp_memory_dir, "insights.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", os.path.join(tmp_memory_dir, "preferences.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", os.path.join(tmp_memory_dir, "concepts.md")), \
             patch("skills.memory_skill.VAULT", vault_dir):
            from myalicia.skills.memory_skill import load_memory_files
            result = load_memory_files()

            assert isinstance(result, dict)
            for key in ["memory", "patterns", "insights", "preferences", "concepts"]:
                assert key in result, f"Missing key: {key}"
                assert isinstance(result[key], str)


class TestMemorySync:
    """Test memory-to-vault synchronization."""

    def test_sync_copies_all_files(self, tmp_path):
        """sync_memory_to_vault should copy all 5 memory files to vault."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        vault_mem = tmp_path / "vault" / "Self" / "Memory"

        files = ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]
        for f in files:
            (mem_dir / f).write_text(f"Content of {f}\n")

        with patch("skills.memory_skill.MEMORY_FILE", str(mem_dir / "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", str(mem_dir / "patterns.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "insights.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "preferences.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "concepts.md")), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", str(vault_mem)):
            from myalicia.skills.memory_skill import sync_memory_to_vault
            sync_memory_to_vault()

            assert os.path.isdir(str(vault_mem))
            for f in files:
                dst = vault_mem / f
                assert dst.exists(), f"Not synced: {f}"
                assert dst.read_text() == f"Content of {f}\n"

    def test_sync_survives_missing_vault_dir(self, tmp_path):
        """sync_memory_to_vault should NOT raise even if vault path is broken."""
        with patch("skills.memory_skill.MEMORY_FILE", "/nonexistent/MEMORY.md"), \
             patch("skills.memory_skill.PATTERNS_FILE", "/nonexistent/patterns.md"), \
             patch("skills.memory_skill.INSIGHTS_FILE", "/nonexistent/insights.md"), \
             patch("skills.memory_skill.PREFERENCES_FILE", "/nonexistent/preferences.md"), \
             patch("skills.memory_skill.CONCEPTS_FILE", "/nonexistent/concepts.md"), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", "/readonly/impossible/path"):
            from myalicia.skills.memory_skill import sync_memory_to_vault
            # Should not raise
            sync_memory_to_vault()


class TestRememberTruncation:
    """Test the remember tool truncation bug (fixed 2026-03-28)."""

    def test_remember_returns_full_value(self, tmp_path):
        """update_memory_md should return the FULL value, not truncated to 100 chars."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        mem_file = mem_dir / "MEMORY.md"
        mem_file.write_text("# MEMORY\n")

        long_value = (
            "The act of creation is not an act of the imagination but an act of discovery. "
            "The creative mind plays with the objects it loves, while the calculating mind "
            "manipulates objects that it has defined. — Arthur Koestler, The Act of Creation"
        )
        assert len(long_value) > 100, "Test value must be >100 chars"

        vault_dir = str(tmp_path / "vault")
        vault_mem = str(tmp_path / "vault" / "Self" / "Memory")

        with patch("skills.memory_skill.MEMORY_FILE", str(mem_file)), \
             patch("skills.memory_skill.MEMORY_DIR", str(mem_dir)), \
             patch("skills.memory_skill.VAULT", vault_dir), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", vault_mem), \
             patch("skills.memory_skill.PATTERNS_FILE", str(mem_dir / "p.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "i.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "pr.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "c.md")):
            from myalicia.skills.memory_skill import update_memory_md
            result = update_memory_md("koestler_quote", long_value)

            # The critical assertion: result should contain the full value
            assert long_value in result, (
                f"Return value was truncated! Got {len(result)} chars. "
                f"This was the bug: value[:100] in the return string."
            )
            # Also verify it was actually stored
            stored = mem_file.read_text()
            assert long_value in stored, "Value not stored in file"

    def test_remember_manual_returns_full_value(self, tmp_path):
        """remember_manual wrapper should also not truncate."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        mem_file = mem_dir / "MEMORY.md"
        mem_file.write_text("# MEMORY\n")
        vault_dir = str(tmp_path / "vault")
        vault_mem = str(tmp_path / "vault" / "Self" / "Memory")

        long_key = "favorite_philosopher_quote"
        long_value = "x" * 200  # Well over 100 chars

        with patch("skills.memory_skill.MEMORY_FILE", str(mem_file)), \
             patch("skills.memory_skill.MEMORY_DIR", str(mem_dir)), \
             patch("skills.memory_skill.VAULT", vault_dir), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", vault_mem), \
             patch("skills.memory_skill.PATTERNS_FILE", str(mem_dir / "p.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "i.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "pr.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "c.md")):
            from myalicia.skills.memory_skill import remember_manual
            result = remember_manual(long_key, long_value)
            # Should contain the full value, not truncated
            # (The confirmation string is what Sonnet sees — if truncated, Sonnet retries)
            assert "x" * 150 in result or long_value in result, \
                "remember_manual confirmation was truncated — Sonnet will retry endlessly"


class TestMemoryExtraction:
    """Test the background memory extraction from messages."""

    @patch("skills.memory_skill.client")
    def test_extract_returns_bool(self, mock_client, tmp_path):
        """extract_from_message should return True/False, not crash."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        for f in ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]:
            (mem_dir / f).write_text(f"# {f}\n")

        # Mock Sonnet response for extraction
        response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '{"facts": [], "patterns": [], "preferences": [], "discard": true}'
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        vault_mem = tmp_path / "vault_mem"
        vault_mem.mkdir()

        with patch("skills.memory_skill.MEMORY_DIR", str(mem_dir)), \
             patch("skills.memory_skill.MEMORY_FILE", str(mem_dir / "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", str(mem_dir / "patterns.md")), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "insights.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "preferences.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "concepts.md")), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", str(vault_mem)):
            from myalicia.skills.memory_skill import extract_from_message
            result = extract_from_message("I think quality is more important than quantity.")
            assert isinstance(result, (bool, list)), f"Expected bool or list, got {type(result)}"


class TestAppendToMemoryFile:
    """Test the append_to_memory_file function and its sync behavior."""

    def test_append_writes_and_syncs(self, tmp_path):
        """append_to_memory_file should write content and trigger vault sync."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        test_file = mem_dir / "patterns.md"
        test_file.write_text("# Patterns\n")
        vault_dir = str(tmp_path / "vault")
        vault_mem = str(tmp_path / "vault" / "Self" / "Memory")

        with patch("skills.memory_skill.MEMORY_DIR", str(mem_dir)), \
             patch("skills.memory_skill.MEMORY_FILE", str(mem_dir / "MEMORY.md")), \
             patch("skills.memory_skill.PATTERNS_FILE", str(test_file)), \
             patch("skills.memory_skill.INSIGHTS_FILE", str(mem_dir / "i.md")), \
             patch("skills.memory_skill.PREFERENCES_FILE", str(mem_dir / "p.md")), \
             patch("skills.memory_skill.CONCEPTS_FILE", str(mem_dir / "c.md")), \
             patch("skills.memory_skill.VAULT", vault_dir), \
             patch("skills.memory_skill.VAULT_MEMORY_DIR", vault_mem):
            from myalicia.skills.memory_skill import append_to_memory_file
            append_to_memory_file(str(test_file), f"New pattern: {USER_NAME} works best in the morning")

            content = test_file.read_text()
            assert f"{USER_NAME} works best in the morning" in content
