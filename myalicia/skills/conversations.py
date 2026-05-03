#!/usr/bin/env python3
"""
Multi-conversation routing — Phase 16.0 (schema) + Phase 16.1 (active routing).

This module is the canonical home for the concept of conversation_id.

Phase 16.0 introduced the field — every state-file writer threads
`conversation_id` so future scoping works without rewriting writers.
Phase 16.1 activates real routing: a registry of conversations, a
persistent 'active' selection, and primitives for switching.

Architecture (Phase 16.1)
-------------------------
A single JSON state file at `~/alicia/memory/conversations.json`:

    {
      "active": "default",
      "conversations": [
        {"id": "default", "label": "general",
         "description": "Everyday conversation between Alicia and the user"},
        {"id": "work", "label": "work-Alicia",
         "description": "Professional context — projects, decisions, output"}
      ]
    }

The file is created on first call with a single 'default' conversation.
All edits go through atomic writes (safe_io) so concurrent writes from
the scheduler thread + handler thread can't corrupt it.

Behavior change vs Phase 16.0
-----------------------------
- `current_conversation_id()` now reads from the active state. When
  the user switches via /conversation, every subsequent write picks up
  the new id.
- `list_conversations()` returns the full registry.
- New primitives: `set_active_conversation`, `add_conversation`,
  `remove_conversation`, `get_conversation_meta`.
- READS are still NOT scoped by conversation in Phase 16.1 — every
  dashboard and resurfacing sees all data regardless of which
  conversation is active. Phase 16.2+ will add read scoping where it
  makes sense (without breaking shared context like the vault).

Why writes-only scoping first
-----------------------------
the user likely doesn't want a hard partition. Conversations are a way
to TAG context, not silo memory. He still wants Alicia to draw on all
his thinking even from inside 'work' — the vault is shared. What he
wants is the PROVENANCE: 'this learning came from the work thread',
'this contradiction was spotted in the philosophy thread'. Tagging
writes gives him provenance; read scoping would silo. We start with
the safe move and add scoping only where it earns its keep.

Backwards compatibility
-----------------------
Entries written before Phase 16.0 don't have the field. Read helpers
treat missing fields as belonging to the 'default' conversation, so
existing data Just Works.

Public API
----------
    DEFAULT_CONVERSATION_ID                       — fallback id
    current_conversation_id()                     — active right now
    set_active_conversation(id)                   — switch
    tag(entry, conversation_id=None)              — stamp a dict
    for_conversation(entries, conversation_id)    — filter a list
    list_conversations()                          — full registry
    add_conversation(id, label, description)      — register a new one
    remove_conversation(id)                       — delete (default protected)
    get_conversation_meta(id)                     — single record
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Iterable, Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.conversations")


# The fallback conversation id. Always exists in the registry. Cannot
# be removed. Used when nothing else is active.
DEFAULT_CONVERSATION_ID = "default"

# Registry storage path. JSON for atomic-write compatibility (jsonl
# would lose the per-conversation metadata semantics on append).
_MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", str(Path.home() / "alicia" / "memory")
))
CONVERSATIONS_PATH = _MEMORY_DIR / "conversations.json"

# In-process cache + lock — registry is read often, written rarely.
_cache_lock = threading.Lock()
_cached_state: Optional[dict] = None


def _empty_state() -> dict:
    """Initial state when no file exists."""
    return {
        "active": DEFAULT_CONVERSATION_ID,
        "conversations": [
            {
                "id": DEFAULT_CONVERSATION_ID,
                "label": "general",
                "description": (
                    f"Everyday conversation between Alicia and {USER_NAME}. "
                    "Default home for any thread that hasn't been routed elsewhere."
                ),
            },
        ],
    }


def _read_state(force: bool = False) -> dict:
    """Load state from disk into the in-process cache."""
    global _cached_state
    with _cache_lock:
        if _cached_state is not None and not force:
            return _cached_state
        if not CONVERSATIONS_PATH.exists():
            _cached_state = _empty_state()
            return _cached_state
        try:
            with open(CONVERSATIONS_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            # Sanity check shape; fall back to empty if corrupt
            if (not isinstance(state, dict)
                    or not isinstance(state.get("conversations"), list)
                    or not state.get("active")):
                log.warning(
                    f"conversations.json corrupt (shape) — falling back to default"
                )
                _cached_state = _empty_state()
                return _cached_state
            _cached_state = state
            return _cached_state
        except Exception as e:
            log.warning(f"conversations.json read failed ({e}) — using default")
            _cached_state = _empty_state()
            return _cached_state


def _write_state(state: dict) -> None:
    """Persist state to disk + update cache."""
    global _cached_state
    try:
        from myalicia.skills.safe_io import atomic_write_json
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(CONVERSATIONS_PATH), state)
    except Exception:
        # Fallback if safe_io isn't available — direct write.
        try:
            _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            tmp = str(CONVERSATIONS_PATH) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONVERSATIONS_PATH)
        except Exception as e2:
            log.warning(f"conversations.json write failed: {e2}")
            return
    with _cache_lock:
        _cached_state = state


def _invalidate_cache() -> None:
    """Force the next read to hit disk. Used by tests."""
    global _cached_state
    with _cache_lock:
        _cached_state = None


def current_conversation_id() -> str:
    """Return the currently-active conversation id.

    Phase 16.1 — reads from the persistent state. When the user switches
    via /conversation, every subsequent write picks up the new id."""
    state = _read_state()
    active = state.get("active") or DEFAULT_CONVERSATION_ID
    # Sanity: if active id no longer exists in registry, fall back
    known = {c.get("id") for c in state.get("conversations", []) if isinstance(c, dict)}
    if active not in known:
        log.warning(
            f"active conversation {active!r} not in registry; "
            f"falling back to {DEFAULT_CONVERSATION_ID!r}"
        )
        return DEFAULT_CONVERSATION_ID
    return active


def set_active_conversation(conversation_id: str) -> bool:
    """Switch the active conversation. Returns True if applied,
    False if the id isn't in the registry."""
    if not conversation_id:
        return False
    state = _read_state()
    known = {c.get("id") for c in state.get("conversations", []) if isinstance(c, dict)}
    if conversation_id not in known:
        return False
    if state.get("active") == conversation_id:
        return True  # no-op success
    state = dict(state)
    state["active"] = conversation_id
    _write_state(state)
    log.info(f"active conversation switched: {conversation_id}")
    return True


def list_conversations() -> list[dict]:
    """Return the full conversation registry (list of dicts).

    Each entry has: {id, label, description}. Phase 16.1 returns the
    real registry, not the [DEFAULT] stub of Phase 16.0."""
    state = _read_state()
    return list(state.get("conversations") or [])


def get_conversation_meta(conversation_id: str) -> Optional[dict]:
    """Return the metadata dict for one conversation, or None if unknown."""
    if not conversation_id:
        return None
    for c in list_conversations():
        if c.get("id") == conversation_id:
            return dict(c)
    return None


def add_conversation(
    conversation_id: str, label: str = "", description: str = "",
) -> bool:
    """Register a new conversation. Returns True if created, False if
    the id already exists or is invalid.

    `id` should be a short slug (alphanumeric + underscore + hyphen).
    `label` is the human-friendly name shown on dashboards. `description`
    is one sentence of intent."""
    if not conversation_id or not conversation_id.strip():
        return False
    cid = conversation_id.strip()
    # Light slug validation — fail loud on bad ids before they hit jsonl
    if not all(ch.isalnum() or ch in "-_" for ch in cid):
        return False
    state = _read_state()
    existing = {c.get("id") for c in state.get("conversations", [])}
    if cid in existing:
        return False
    state = dict(state)
    state["conversations"] = list(state.get("conversations") or []) + [{
        "id": cid,
        "label": (label or cid).strip(),
        "description": (description or "").strip(),
    }]
    _write_state(state)
    log.info(f"conversation registered: {cid}")
    return True


def remove_conversation(conversation_id: str) -> bool:
    """Remove a conversation from the registry. Returns True if removed,
    False if not found OR if the id is DEFAULT (protected).

    If the active conversation is removed, active falls back to default."""
    if not conversation_id or conversation_id == DEFAULT_CONVERSATION_ID:
        return False
    state = _read_state()
    before = state.get("conversations") or []
    after = [c for c in before if c.get("id") != conversation_id]
    if len(after) == len(before):
        return False
    state = dict(state)
    state["conversations"] = after
    if state.get("active") == conversation_id:
        state["active"] = DEFAULT_CONVERSATION_ID
    _write_state(state)
    log.info(f"conversation removed: {conversation_id}")
    return True


def tag(entry: dict, conversation_id: Optional[str] = None) -> dict:
    """Stamp a conversation_id onto an entry dict (in place + return).

    If `conversation_id` is None, uses current_conversation_id().
    Existing values are not overwritten — call tag() before storing
    a record that hasn't already been tagged.
    """
    if not isinstance(entry, dict):
        return entry
    if "conversation_id" in entry and entry["conversation_id"]:
        return entry
    entry["conversation_id"] = conversation_id or current_conversation_id()
    return entry


def for_conversation(
    entries: Iterable[dict],
    conversation_id: Optional[str] = None,
    *,
    treat_missing_as_default: bool = True,
) -> list[dict]:
    """Filter `entries` to those belonging to `conversation_id`.

    By default, entries without a conversation_id field are treated
    as belonging to the 'default' conversation (backwards-compat).
    Set `treat_missing_as_default=False` to require an explicit field.
    """
    target = conversation_id or current_conversation_id()
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        cid = e.get("conversation_id")
        if cid:
            if cid == target:
                out.append(e)
        elif treat_missing_as_default and target == DEFAULT_CONVERSATION_ID:
            out.append(e)
    return out
