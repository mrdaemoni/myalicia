"""
core.security — security level classification and chat-guard decorator.

PLANNED CONTENT (currently lives in myalicia/alicia.py:402-490):

Functions:

  classify_security_level(text) -> int
      Returns L1-L4 based on content sensitivity. Used by the
      handle_message pipeline as step 1.

  get_context_size(level) -> int
      Maps security level to context window size budget.

  security_emoji(level) -> str
      Maps level to a glyph for inline indicators.

  log_interaction(level, action, outcome) -> None
      Audit log line.

  @chat_guard
      Decorator that gates a handler on chat_id allowlist; returns
      politely if the chat isn't authorized.

These are small and self-contained — likely one of the first
extractions to land. Low risk.

Status: not yet extracted.
"""
