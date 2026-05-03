"""
core.vault_io — read/write primitives for the user's knowledge vault.

Functions here operate on the configured vault root (typically an
Obsidian-formatted folder). All paths route through the typed config
layer; nothing is hardcoded.

Extracted from myalicia/alicia.py in Phase 1 of the core/ split. The
heavier read function (get_vault_context) stays in alicia.py for now —
it depends on the semantic_search skill, which deserves its own
factoring pass.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from myalicia.config import config


def write_to_obsidian(subfolder: str, filename: str, content: str) -> str:
    """Write `content` to `<vault.inner>/<subfolder>/<filename>`.

    Creates intermediate directories as needed. Returns the absolute
    path of the written file.
    """
    target_dir = Path(config.vault.inner_path) / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def write_daily_log(content: str) -> str:
    """Append today's daily log to `<vault.inner>/Self/Daily Log/YYYY-MM-DD.md`.

    Returns the absolute path of the file written.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    return write_to_obsidian("Self/Daily Log", f"{today}.md", content)


__all__ = [
    "write_to_obsidian",
    "write_daily_log",
]
