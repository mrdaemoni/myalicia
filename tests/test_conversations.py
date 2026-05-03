#!/usr/bin/env python3
"""Unit tests for skills/conversations.py — multi-conversation foundation."""
from __future__ import annotations

import sys
from pathlib import Path
from myalicia.config import config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


_PASSED = 0
_FAILED = 0
_TESTS: list[tuple[str, callable]] = []


def test(label: str):
    def deco(fn):
        _TESTS.append((label, fn))
        return fn
    return deco


def _run_all() -> int:
    global _PASSED, _FAILED
    for label, fn in _TESTS:
        try:
            fn()
            _PASSED += 1
            print(f"  ✓ {label}")
        except AssertionError as e:
            _FAILED += 1
            print(f"  ✗ {label}\n      {e}")
        except Exception as e:
            _FAILED += 1
            print(f"  ✗ {label}\n      unexpected: {type(e).__name__}: {e}")
    print(f"\n{_PASSED} passed · {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


@test("DEFAULT_CONVERSATION_ID is 'default'")
def _():
    from myalicia.skills.conversations import DEFAULT_CONVERSATION_ID
    assert DEFAULT_CONVERSATION_ID == "default"


@test("current_conversation_id returns DEFAULT_CONVERSATION_ID")
def _():
    from myalicia.skills.conversations import current_conversation_id, DEFAULT_CONVERSATION_ID
    assert current_conversation_id() == DEFAULT_CONVERSATION_ID


@test("tag adds conversation_id field to a dict")
def _():
    from myalicia.skills.conversations import tag
    e = {"foo": "bar"}
    tag(e)
    assert e["conversation_id"] == "default"


@test("tag preserves existing conversation_id")
def _():
    from myalicia.skills.conversations import tag
    e = {"foo": "bar", "conversation_id": "philosophy"}
    tag(e)
    assert e["conversation_id"] == "philosophy"


@test("tag with explicit conversation_id sets the chosen value")
def _():
    from myalicia.skills.conversations import tag
    e = {"foo": "bar"}
    tag(e, conversation_id="work")
    assert e["conversation_id"] == "work"


@test("for_conversation filters entries by conversation_id")
def _():
    from myalicia.skills.conversations import for_conversation
    entries = [
        {"foo": "a", "conversation_id": "default"},
        {"foo": "b", "conversation_id": "work"},
        {"foo": "c", "conversation_id": "default"},
    ]
    out = for_conversation(entries, "default")
    assert [e["foo"] for e in out] == ["a", "c"]
    out2 = for_conversation(entries, "work")
    assert [e["foo"] for e in out2] == ["b"]


@test("for_conversation backwards-compat: missing field treated as default")
def _():
    """Entries written before Phase 16.0 don't have the field. Reading
    them with conversation_id='default' should still surface them."""
    from myalicia.skills.conversations import for_conversation
    entries = [
        {"foo": "old1"},  # no field — pre-16.0
        {"foo": "new1", "conversation_id": "default"},
        {"foo": "other", "conversation_id": "work"},
    ]
    out = for_conversation(entries, "default")
    assert "old1" in [e["foo"] for e in out]
    assert "new1" in [e["foo"] for e in out]
    assert "other" not in [e["foo"] for e in out]


@test("for_conversation strict mode excludes entries without the field")
def _():
    from myalicia.skills.conversations import for_conversation
    entries = [
        {"foo": "old1"},  # no field
        {"foo": "new1", "conversation_id": "default"},
    ]
    out = for_conversation(entries, "default", treat_missing_as_default=False)
    assert [e["foo"] for e in out] == ["new1"]


@test("list_conversations returns the default registry entry (Phase 16.1)")
def _():
    """Phase 16.0 returned a list of strings; Phase 16.1 returns a list
    of dicts with id/label/description metadata. Default registry on
    empty disk has exactly one entry — the canonical 'default'."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td) if "_isolate_registry" in globals() else None
        # _isolate_registry is defined later in the file; on first run
        # we may not see it yet — fall back to checking the default-disk
        # behavior by setting the path directly.
        from pathlib import Path
        from myalicia.skills import conversations as cv
        cv.CONVERSATIONS_PATH = Path(td) / "conversations.json"
        cv._invalidate_cache()
        regs = cv.list_conversations()
        assert isinstance(regs, list)
        assert len(regs) == 1
        assert regs[0]["id"] == cv.DEFAULT_CONVERSATION_ID


@test("hector_model.append_learning tags new entries with conversation_id")
def _():
    """End-to-end: append_learning should result in an entry with the
    field set, so future readers can filter by conversation."""
    import tempfile, os
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import hector_model as hm
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "hector_learnings.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"
        hm.BASELINES_DIR.mkdir()
        hm.append_learning(
            claim="Test learning", dimension="identity",
            confidence=0.7, source="test",
        )
        entries = list(hm.get_learnings())
        assert len(entries) == 1
        assert entries[0].get("conversation_id") == "default", (
            f"hector_model entry should be tagged: {entries[0]}"
        )


@test("multi_channel.record_multi_channel_decision tags new entries")
def _():
    import tempfile, os, json
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import multi_channel as mc
        mc.MEMORY_DIR = td
        mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        mc.record_multi_channel_decision({
            "channel": "voice", "voice": True, "path": "fast_voice_default",
            "rationale": "x", "text_hash": "h1", "text_len": 10,
        })
        with open(mc.DECISIONS_LOG_PATH) as f:
            entry = json.loads(f.readline())
        assert entry.get("conversation_id") == "default"


@test("dimension_research.record_dimension_question_asked tags entries")
def _():
    import tempfile, os, json
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        dr.record_dimension_question_asked("body", "have you moved?")
        with open(dr.DIMENSION_LOG_PATH) as f:
            entry = json.loads(f.readline())
        assert entry.get("conversation_id") == "default"


@test("thread_puller.record_thread_pull tags entries")
def _():
    import tempfile, os, json
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        tp.record_thread_pull("a thread", "a message")
        with open(tp.THREAD_PULLS_PATH) as f:
            entry = json.loads(f.readline())
        assert entry.get("conversation_id") == "default"


# ── Phase 16.1: registry + active state primitives ──────────────────────


def _isolate_registry(td):
    """Reroute conversations.CONVERSATIONS_PATH + invalidate cache so
    each test gets a clean registry on disk."""
    from pathlib import Path
    from myalicia.skills import conversations as cv
    cv.CONVERSATIONS_PATH = Path(td) / "conversations.json"
    cv._invalidate_cache()


@test("Phase 16.1: empty disk → default registry with one entry")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            list_conversations, current_conversation_id,
        )
        regs = list_conversations()
        assert len(regs) == 1, f"expected 1 conversation, got {len(regs)}"
        assert regs[0]["id"] == "default"
        assert regs[0].get("label") == "general"
        assert current_conversation_id() == "default"


@test("Phase 16.1: add_conversation creates a new entry")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import add_conversation, list_conversations
        ok = add_conversation(
            "work", label="work-Alicia",
            description="Professional context — projects, decisions",
        )
        assert ok is True
        ids = [c["id"] for c in list_conversations()]
        assert "default" in ids and "work" in ids


@test("Phase 16.1: add_conversation rejects duplicate id")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import add_conversation
        assert add_conversation("work", "x") is True
        assert add_conversation("work", "y") is False, (
            "duplicate id should fail"
        )


@test("Phase 16.1: add_conversation rejects invalid characters")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import add_conversation
        for bad in ("with space", "with.dot", "with/slash", ""):
            assert add_conversation(bad) is False, (
                f"id {bad!r} should be rejected"
            )


@test("Phase 16.1: set_active_conversation switches active state")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            add_conversation, set_active_conversation, current_conversation_id,
        )
        add_conversation("work", "work-Alicia")
        assert set_active_conversation("work") is True
        assert current_conversation_id() == "work"
        # Switching to default works too
        assert set_active_conversation("default") is True
        assert current_conversation_id() == "default"


@test("Phase 16.1: set_active_conversation rejects unknown id")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import set_active_conversation
        assert set_active_conversation("nonexistent") is False


@test("Phase 16.1: active conversation persists across cache invalidation")
def _():
    """the user switches; we drop the cache (simulating restart); state
    must come back from disk."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills import conversations as cv
        cv.add_conversation("work", "work-Alicia")
        cv.set_active_conversation("work")
        # Simulate process restart: invalidate cache, force re-read
        cv._invalidate_cache()
        assert cv.current_conversation_id() == "work", (
            "active state must survive cache invalidation (= restart)"
        )


@test("Phase 16.1: tag() picks up the active conversation")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            add_conversation, set_active_conversation, tag,
        )
        add_conversation("work", "work-Alicia")
        set_active_conversation("work")
        entry = tag({"some": "data"})
        assert entry["conversation_id"] == "work", (
            f"tag should pick up active conversation, got: {entry}"
        )


@test("Phase 16.1: remove_conversation removes from registry")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            add_conversation, remove_conversation, list_conversations,
        )
        add_conversation("temp", "temporary")
        assert remove_conversation("temp") is True
        ids = [c["id"] for c in list_conversations()]
        assert "temp" not in ids


@test("Phase 16.1: remove_conversation refuses to delete `default`")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import remove_conversation, list_conversations
        assert remove_conversation("default") is False
        assert any(c["id"] == "default" for c in list_conversations())


@test("Phase 16.1: removing active conversation falls back to default")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            add_conversation, set_active_conversation, remove_conversation,
            current_conversation_id,
        )
        add_conversation("temp")
        set_active_conversation("temp")
        assert current_conversation_id() == "temp"
        remove_conversation("temp")
        assert current_conversation_id() == "default", (
            "active should fall back to default after removal"
        )


@test("Phase 16.1: get_conversation_meta returns dict for known, None for unknown")
def _():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills.conversations import (
            add_conversation, get_conversation_meta,
        )
        add_conversation("work", "work-Alicia", "professional")
        meta = get_conversation_meta("work")
        assert meta is not None
        assert meta["id"] == "work"
        assert meta["label"] == "work-Alicia"
        assert meta["description"] == "professional"
        assert get_conversation_meta("nonexistent") is None


@test("Phase 16.1: missing-active-id falls back to default at read time")
def _():
    """If conversations.json names an active id that no longer exists
    in the registry, current_conversation_id() must fall back to
    'default' rather than crash."""
    import tempfile, json
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        _isolate_registry(td)
        from myalicia.skills import conversations as cv
        # Manually write a state where active points at a missing id
        path = Path(td) / "conversations.json"
        path.write_text(json.dumps({
            "active": "ghost",
            "conversations": [{
                "id": "default", "label": "general", "description": "",
            }],
        }), encoding="utf-8")
        cv._invalidate_cache()
        assert cv.current_conversation_id() == "default"


if __name__ == "__main__":
    print("Testing conversations.py …")
    sys.exit(_run_all())
