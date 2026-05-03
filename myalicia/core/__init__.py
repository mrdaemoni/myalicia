"""
myalicia.core — the thin harness.

This package will eventually hold the orchestration logic split out from
the legacy ``myalicia/alicia.py`` monolith (7951 lines as of v0.1.0). As
of this writing, the runtime still lives in alicia.py; the submodules
below are placeholders documenting where each piece is destined to land.

The split is intentionally incremental — each function moves to its
proper home in a focused PR that:

  1. Lifts the function (and only the function) out of alicia.py
  2. Adds it to the appropriate core/ module with proper imports
  3. Replaces the original site in alicia.py with
     ``from myalicia.core.<module> import <name>``
  4. Verifies tests still pass

The end state: ``alicia.py`` becomes a thin entry point that wires the
core modules together; the heavy logic lives in core/.

See ../REFACTORING.md for the planned moves and rationale.

Planned modules:

  core.handle_message       — the 10-step message pipeline (~1100 lines)
  core.scheduler            — scheduled tasks (morning/midday/evening/weekly)
  core.security             — classify_security_level + chat_guard
  core.system_prompt        — build_system_prompt and helpers
  core.vault_io             — write_to_obsidian, get_vault_context
  core.voice                — handle_voice + call/unpack flows
  core.telegram_commands    — all the cmd_* handlers
  core.main                 — bot setup + main entry point
"""

# When extraction PRs land, re-export the canonical public surface here:
__all__: list[str] = []
