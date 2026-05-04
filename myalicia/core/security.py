"""
core.security — security-level classification + chat auth + audit logging.

Each message is classified into one of four tiers based on the actions
it requests. The classification drives:
  - Context window budget (get_context_size)
  - Confirmation requirements (handle_message)
  - Audit log entries (log_interaction)
  - User-facing visual indicators (security_emoji)

The keyword sets are deliberately conservative; tier 4 is reserved for
truly irreversible / financial / credential-exposing actions.

Phase 1 of the alicia.py split. The pure classifiers landed first; in
Phase 2c chat_guard and log_interaction joined this module — both now
config-driven (no TELEGRAM_CHAT_ID or LOG_FILE module globals).
"""
from __future__ import annotations

import functools
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from myalicia.config import config

log = logging.getLogger(__name__)

# ── Tier definitions ──────────────────────────────────────────────────────

SECURITY_KEYWORDS: dict[int, list[str]] = {
    # Tier 4 — irreversible / financial / credential exposure. Whole-word
    # matching only; bare "wire" used to fire on "wired"/"wireless".
    4: [
        "delete", "transfer", "payment", "credential", "credentials",
        "api key", "password", "bank account", "irreversible",
        "send money", "wire transfer", "wire money", "wire funds",
    ],
    # Tier 3 — outbound / publishing / shell-execution. Compound phrases
    # avoid the "executive"/"sharepoint"/"compost" false positives that
    # bare "execute"/"share"/"post" used to produce.
    3: [
        "send email", "forward email", "share document", "publish",
        "submit form", "financial record", "run command", "execute trade",
        "execute command", "shell command",
    ],
    # Tier 2 — privacy-sensitive read access.
    2: [
        "read email", "gmail", "obsidian", "health data", "spending",
        "research", "finance", "personal data",
    ],
}

# Compile word-boundary regex per level. Multi-word phrases match as
# literal substrings (the boundary check still applies at the start and
# end). This replaces the old `kw in lowered` substring test.
_SECURITY_REGEX: dict[int, list[re.Pattern[str]]] = {
    level: [
        re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        for kw in keywords
    ]
    for level, keywords in SECURITY_KEYWORDS.items()
}


# ── Pure classifiers ──────────────────────────────────────────────────────

def classify_security_level(text: str | None) -> int:
    """Return the highest security tier whose keyword list matches `text`.

    Matching is word-boundary aware, so "wired" doesn't fire L4 just
    because "wire" is a money-transfer keyword. Phrases like "send email"
    still match because boundaries only apply at the outer edges.

    Returns 1 if `text` is empty or matches nothing.
    """
    if not text:
        return 1
    for level in (4, 3, 2):
        for pattern in _SECURITY_REGEX[level]:
            if pattern.search(text):
                return level
    return 1


def get_context_size(level: int) -> int:
    """Map a security level to a context window size budget."""
    return {1: 5, 2: 20, 3: 40, 4: 60}.get(level, 5)


def security_emoji(level: int) -> str:
    """Map a security level to its user-facing visual indicator."""
    return {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴"}.get(level, "🟢")


# ── Audit logging ─────────────────────────────────────────────────────────

def _interactions_log_path() -> Path:
    """Resolve the interactions audit-log path from config.

    Defaults to ``~/.alicia/logs/interactions.jsonl``; overridable
    via ``config.user`` extension if a contributor adds a logs config
    section in a future release.
    """
    log_dir = Path.home() / ".alicia" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "interactions.jsonl"


def log_interaction(level: int, action: str, outcome: str) -> None:
    """Append one audit-log entry for a security-classified interaction.

    Records the timestamp (UTC), the security tier, what was attempted,
    and the outcome. Each entry is one JSON line so the log is
    grep-friendly and tail-able.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "security_level": f"L{level}",
        "action": action,
        "outcome": outcome,
    }
    try:
        with _interactions_log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        # Logging shouldn't crash the runtime; fall back to logger
        log.warning(f"log_interaction: failed to write audit entry: {e}")


# ── Chat auth decorator ───────────────────────────────────────────────────

def chat_guard(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Drop Telegram updates not originating from an allowed chat.

    Works for both regular ``Update`` objects (where ``effective_chat``
    is set) and ``MessageReactionUpdated`` objects (where only
    ``message_reaction.chat`` is set). Safe to stack above any async
    Telegram handler.

    The allow-list comes from
    ``config.surfaces.telegram.allowed_chat_ids`` (a tuple of int
    chat IDs). If the tuple is empty, the guard rejects every update —
    explicit opt-in is required.

    Usage::

        @chat_guard
        async def cmd_status(update, context):
            ...
    """
    @functools.wraps(fn)
    async def inner(update: Any, context: Any, *args: Any, **kwargs: Any) -> Any:
        chat_id: int | None = None
        try:
            if getattr(update, "effective_chat", None) is not None:
                chat_id = update.effective_chat.id
            elif getattr(update, "message_reaction", None) is not None:
                chat_id = update.message_reaction.chat.id
        except Exception as e:
            log.debug(f"chat_guard: failed to resolve chat_id: {e}")
            return None

        allowed = config.surfaces.telegram.allowed_chat_ids
        if not allowed or chat_id not in allowed:
            return None
        return await fn(update, context, *args, **kwargs)

    return inner


__all__ = [
    "SECURITY_KEYWORDS",
    "classify_security_level",
    "get_context_size",
    "security_emoji",
    "log_interaction",
    "chat_guard",
]
