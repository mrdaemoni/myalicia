#!/usr/bin/env python3
"""
Unit tests for skills/dimension_research.py.

Sandbox-friendly: log path is rerouted to a tmpfile per test. The
user_model.find_thin_dimensions function is monkey-patched to control
which dimensions appear thin without needing a real baseline.

Haiku composition (compose_dimension_question) requires a live API call
and is not exercised here. The wiring guardrail in smoke_test.py covers
the import + scheduler + midday rotation branch.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
            print(f"  ✗ {label}\n      unexpected error: {type(e).__name__}: {e}")
    print(f"\n{_PASSED} passed · {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


# ── Fixtures ────────────────────────────────────────────────────────────────


def _setup_tmp_log(tmpdir: str) -> str:
    """Reroute the dimension log path to a tmp file. Returns the path."""
    from myalicia.skills import dimension_research as dr
    p = os.path.join(tmpdir, "dimension_questions_log.jsonl")
    dr.MEMORY_DIR = tmpdir
    dr.DIMENSION_LOG_PATH = p
    return p


def _patch_thin(monkey_thin: list[str]) -> callable:
    """Patch user_model.find_thin_dimensions to return `monkey_thin`.
    Returns a restore callable."""
    import myalicia.skills.user_model as hm
    original = hm.find_thin_dimensions
    hm.find_thin_dimensions = lambda **kw: list(monkey_thin)
    return lambda: setattr(hm, "find_thin_dimensions", original)


# ── log + cooldown ────────────────────────────────────────────────────────


@test("record + recent: round-trip")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.dimension_research import (
            record_dimension_question_asked, recent_dimension_questions,
        )
        record_dimension_question_asked("body", "have you moved today?")
        record_dimension_question_asked("shadow", "what are you avoiding?")
        recent = recent_dimension_questions(within_days=14)
        assert len(recent) == 2
        dims = [e["dimension"] for e in recent]
        assert "body" in dims and "shadow" in dims


@test("recent_dimension_questions: respects window")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with open(log_path, "w") as f:
            f.write(json.dumps({"ts": old_ts, "dimension": "wealth", "question": "x"}) + "\n")
            f.write(json.dumps({"ts": new_ts, "dimension": "creative", "question": "y"}) + "\n")

        from myalicia.skills.dimension_research import recent_dimension_questions
        recent = recent_dimension_questions(within_days=7)
        dims = [e["dimension"] for e in recent]
        assert "creative" in dims
        assert "wealth" not in dims, f"30d-old entry must not appear in 7d window: {dims}"


# ── pick_thin_dimension ─────────────────────────────────────────────────────


@test("pick_thin_dimension: returns first thin dim when nothing on cooldown")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        restore = _patch_thin(["body", "wealth", "shadow"])
        try:
            from myalicia.skills.dimension_research import pick_thin_dimension
            assert pick_thin_dimension() == "body"
        finally:
            restore()


@test("pick_thin_dimension: skips dimensions asked recently")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.dimension_research import (
            pick_thin_dimension, record_dimension_question_asked,
        )
        record_dimension_question_asked("body", "asked recently")
        restore = _patch_thin(["body", "wealth", "shadow"])
        try:
            chosen = pick_thin_dimension()
            assert chosen == "wealth", (
                f"body was on cooldown; expected wealth, got {chosen!r}"
            )
        finally:
            restore()


@test("pick_thin_dimension: returns None when ALL thin dims on cooldown")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.dimension_research import (
            pick_thin_dimension, record_dimension_question_asked,
        )
        record_dimension_question_asked("body", "x")
        record_dimension_question_asked("wealth", "y")
        restore = _patch_thin(["body", "wealth"])
        try:
            assert pick_thin_dimension() is None
        finally:
            restore()


@test("pick_thin_dimension: returns None when no thin dimensions")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        restore = _patch_thin([])
        try:
            from myalicia.skills.dimension_research import pick_thin_dimension
            assert pick_thin_dimension() is None
        finally:
            restore()


@test("pick_thin_dimension: respects cooldown_days argument")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Mark body as asked 10 days ago
        ts_10d = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with open(log_path, "w") as f:
            f.write(json.dumps({"ts": ts_10d, "dimension": "body", "question": "x"}) + "\n")

        restore = _patch_thin(["body", "wealth"])
        try:
            from myalicia.skills.dimension_research import pick_thin_dimension
            # 7-day cooldown — 10d-old is OUTSIDE cooldown → body is eligible
            assert pick_thin_dimension(cooldown_days=7) == "body"
            # 14-day cooldown — 10d-old is INSIDE cooldown → body skipped
            assert pick_thin_dimension(cooldown_days=14) == "wealth"
        finally:
            restore()


# ── run_dimension_research_scan ────────────────────────────────────────────


@test("run_dimension_research_scan: surfaces next candidate when one exists")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        restore = _patch_thin(["practice", "creative"])
        try:
            from myalicia.skills.dimension_research import run_dimension_research_scan
            r = run_dimension_research_scan()
            assert r["thin_dimensions"] == ["practice", "creative"]
            assert r["next_candidate"] == "practice"
            assert r["all_on_cooldown"] is False
        finally:
            restore()


@test("run_dimension_research_scan: all_on_cooldown when thin exist but all asked")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.dimension_research import (
            record_dimension_question_asked, run_dimension_research_scan,
        )
        record_dimension_question_asked("practice", "x")
        restore = _patch_thin(["practice"])
        try:
            r = run_dimension_research_scan()
            assert r["thin_dimensions"] == ["practice"]
            assert r["next_candidate"] is None
            assert r["all_on_cooldown"] is True
        finally:
            restore()


@test("run_dimension_research_scan: empty thin → empty result, not error")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        restore = _patch_thin([])
        try:
            from myalicia.skills.dimension_research import run_dimension_research_scan
            r = run_dimension_research_scan()
            assert r["thin_dimensions"] == []
            assert r["next_candidate"] is None
            assert r["all_on_cooldown"] is False
        finally:
            restore()


# ── Dimension frame coverage ───────────────────────────────────────────────


@test("Phase 12.4 record + recent scan history: round-trip")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")
        dr.record_dimension_scan(["body", "wealth"], "body")
        dr.record_dimension_scan(["body"], "body")
        scans = dr.recent_dimension_scans(within_days=7)
        assert len(scans) == 2
        # Chronological order — oldest first
        assert scans[0]["thin_dimensions"] == ["body", "wealth"]
        assert scans[1]["thin_dimensions"] == ["body"]


@test("Phase 12.4 get_persistent_thin_dimensions: needs N scans of same dim")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")

        # Only 1 scan → not enough history
        dr.record_dimension_scan(["body"], "body")
        assert dr.get_persistent_thin_dimensions() == []

        # Second scan with same dim → persistent
        dr.record_dimension_scan(["body", "shadow"], "body")
        persistent = dr.get_persistent_thin_dimensions(min_consecutive_scans=2)
        assert "body" in persistent, f"body should be persistent: {persistent}"
        # shadow appeared in only 1 of last 2 → NOT persistent
        assert "shadow" not in persistent


@test("Phase 12.4 get_persistent_thin_dimensions: all dims dropping out")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")
        dr.record_dimension_scan(["body"], "body")
        dr.record_dimension_scan([], None)  # body now has activity
        assert dr.get_persistent_thin_dimensions() == []


@test("Phase 12.4 escalation log: round-trip and cooldown filter")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")
        dr.record_dimension_escalation("body", "energy practices",
                                       "/path/to/note.md", "ok")
        dr.record_dimension_escalation("wealth", "tax strategy",
                                       None, "import_failed")
        recent = dr.recent_escalations(within_days=30)
        assert len(recent) == 2
        dims = [e["dimension"] for e in recent]
        assert "body" in dims and "wealth" in dims


@test("Phase 12.4 pick_escalation_target: prefers non-cooldown dim")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")

        # body persistently thin
        dr.record_dimension_scan(["body", "wealth"], "body")
        dr.record_dimension_scan(["body", "wealth"], "body")

        # body was just escalated → wealth is the next pick
        dr.record_dimension_escalation("body", "x", "/tmp/x.md", "ok")
        target = dr.pick_escalation_target()
        assert target == "wealth", (
            f"body on cooldown, expected wealth: got {target!r}"
        )

        # Both on cooldown → None
        dr.record_dimension_escalation("wealth", "y", "/tmp/y.md", "ok")
        assert dr.pick_escalation_target() is None


@test("Phase 12.4 escalate_to_research: handles missing topic mapping")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")
        # nonexistent dimension → no topic, no crash, returns None
        result = dr.escalate_to_research("not_a_real_dim")
        assert result is None


@test("Phase 12.4 escalate_to_research: writes escalation log on import failure")
def _():
    """When research_skill is unavailable, escalate_to_research should
    log the failure (so /multichannel-style observability sees it) and
    return None — never raise."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")
        # Force import failure by pre-poisoning sys.modules
        import sys as _sys
        saved = _sys.modules.pop("skills.research_skill", None)
        _sys.modules["skills.research_skill"] = None
        try:
            result = dr.escalate_to_research("body")
            assert result is None
            # The log captured the failure
            recent = dr.recent_escalations(within_days=30)
            assert len(recent) == 1
            assert recent[0]["status"] == "import_failed"
            assert recent[0]["dimension"] == "body"
        finally:
            if saved is not None:
                _sys.modules["skills.research_skill"] = saved
            else:
                _sys.modules.pop("skills.research_skill", None)


@test("Phase 12.4 run_dimension_research_scan: records scan and surfaces escalation")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills import dimension_research as dr
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")

        # Stub escalate_to_research so test doesn't make a real research call
        original_escalate = dr.escalate_to_research
        dr.escalate_to_research = lambda dim: f"/fake/research/{dim}.md"
        # Stub find_thin to keep returning [body]
        restore = _patch_thin(["body"])
        try:
            # First scan — no history yet, no escalation possible
            r1 = dr.run_dimension_research_scan()
            assert r1["thin_dimensions"] == ["body"]
            assert r1["escalated_dim"] is None, (
                f"first scan must NOT escalate (no consecutive history yet): {r1}"
            )

            # Second scan — body now persistent → escalate
            r2 = dr.run_dimension_research_scan()
            assert r2["escalated_dim"] == "body"
            assert r2["escalation_path"] == "/fake/research/body.md"
        finally:
            dr.escalate_to_research = original_escalate
            restore()


@test("_DIMENSION_FRAMES covers every canonical user_model dimension")
def _():
    from myalicia.skills.dimension_research import _DIMENSION_FRAMES
    from myalicia.skills.user_model import DIMENSIONS as HM_DIMENSIONS
    missing = [d for d in HM_DIMENSIONS if d not in _DIMENSION_FRAMES]
    assert not missing, (
        f"_DIMENSION_FRAMES missing entries for: {missing}. "
        f"All user_model dimensions must have a Haiku framing hint."
    )


if __name__ == "__main__":
    print("Testing dimension_research.py …")
    sys.exit(_run_all())
