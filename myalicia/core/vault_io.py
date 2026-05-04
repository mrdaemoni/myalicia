"""
core.vault_io — read/write primitives for the user's knowledge vault.

Functions here operate on the configured vault root (typically an
Obsidian-formatted folder). All paths route through the typed config
layer; nothing is hardcoded.

Phase 1 of the alicia.py split shipped: write_to_obsidian, write_daily_log.
Phase 2a (this file) adds: get_vault_context — semantic vault retrieval
formatted as system-prompt context with deep-link sources.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

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


def get_vault_context(user_message: str, n_results: int = 4) -> tuple[str, list[str]]:
    """Retrieve semantically relevant vault notes for a user message.

    Returns a tuple ``(context_text, source_links)`` where:
      - ``context_text`` is markdown-formatted prose ready to drop into
        a system prompt (or empty string when no relevant context exists)
      - ``source_links`` is a list of markdown-formatted Obsidian deep
        links to the matched notes

    The vault name in deep links is derived from ``config.user.handle``
    (so a user named "maria" gets ``obsidian://open?vault=maria-alicia``);
    customize via the ``ALICIA_VAULT_NAME`` env var if your vault has a
    different name.

    Returns ``("", [])`` for messages shorter than 10 characters or when
    the semantic search subsystem is unavailable.
    """
    if not user_message or len(user_message) < 10:
        return "", []

    # Lazy import — semantic_search has heavy dependencies (chromadb,
    # sentence-transformers) that we don't want loaded at module import.
    try:
        from myalicia.skills.semantic_search import semantic_search
    except ImportError:
        return "", []

    try:
        hits = semantic_search(user_message, n_results=n_results)
    except Exception:
        return "", []
    if not hits:
        return "", []

    user_name = config.user.name
    user_handle = config.user.handle
    vault_root = str(config.vault.root)
    # Vault name for Obsidian deep-link URI scheme. Defaults to <handle>-alicia
    # to match the shipped vault_layouts/obsidian-default.md structure.
    import os
    vault_name = os.environ.get("ALICIA_VAULT_NAME", f"{user_handle}-alicia")

    lines = [f"\n## Relevant notes from {user_name}'s vault\n"]
    sources: list[str] = []
    for h in hits:
        relative = h["filepath"].replace(vault_root + "/", "")
        deep_link = f"obsidian://open?vault={vault_name}&file={quote(relative, safe='/')}"
        lines.append(f"### {h['title']}\n{h['snippet'][:300]}\n")
        sources.append(f"[{h['title']}]({deep_link})")

    return "\n".join(lines), sources


__all__ = [
    "write_to_obsidian",
    "write_daily_log",
    "get_vault_context",
]
