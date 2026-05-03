"""
core.system_prompt — system prompt construction.

PLANNED CONTENT (currently lives in myalicia/alicia.py:528-826):

Functions:

  build_system_prompt(
      user_message="",
      reflections="",
      curiosity_context="",
      novelty_context="",
      metacog_note="",
      thread_hint="",
      mode="casual",
      resolved_modules=None,
      precomputed_vault_context=None,
      voice_guidance=None,
  ) -> str

The system prompt is composed from many sources at runtime — vault
context, recent reflections, curiosity findings, metacognitive notes,
the current archetype, the thread state. This module owns that
composition.

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py:528-826
  - Imports needed: from myalicia.config import config; archetype loading
  - Should ideally be pure (input -> string), no side effects

Status: not yet extracted.
"""
