"""
core.security — security-level classification for incoming messages.

Each message is classified into one of four tiers based on the actions
it requests. The classification drives:
  - Context window budget (get_context_size)
  - Confirmation requirements (handle_message)
  - Audit log entries (log_interaction)
  - User-facing visual indicators (security_emoji)

The keyword sets are deliberately conservative; tier 4 is reserved for
truly irreversible / financial / credential-exposing actions.

Extracted from myalicia/alicia.py in Phase 1 of the core/ split. The
non-pure functions (chat_guard, log_interaction) stay in alicia.py for
now — they depend on TELEGRAM_CHAT_ID and LOG_FILE module state that
hasn't been factored out yet.
"""
from __future__ import annotations

import re

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


__all__ = [
    "SECURITY_KEYWORDS",
    "classify_security_level",
    "get_context_size",
    "security_emoji",
]
