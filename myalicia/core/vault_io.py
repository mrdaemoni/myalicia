"""
core.vault_io — read/write primitives for the user's knowledge vault.

PLANNED CONTENT (currently lives in myalicia/alicia.py:493-528):

Functions:

  write_to_obsidian(subfolder, filename, content)
      Atomic write of a note into the configured vault.

  write_daily_log(content)
      Append to the day's log file in the vault.

  get_vault_context(user_message)
      Pull relevant notes from the vault for the current message.
      Used by handle_message as step 2 (Retrieval).

These all use config.vault.* paths exclusively — no hardcoding.

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py:493-528
  - Imports: from myalicia.config import config; from myalicia.skills.safe_io import atomic_write_json
  - Should be one of the very first extractions (small, foundational)

Status: not yet extracted.
"""
