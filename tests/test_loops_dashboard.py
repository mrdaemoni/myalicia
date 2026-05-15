#!/usr/bin/env python3
"""
Unit tests for skills/loops_dashboard.py.

Sandbox-friendly: each test reroutes the relevant memory paths to tmp
and seeds them with synthetic events. Tests focus on the dashboard's
fault-tolerance and section composition — section text is checked via
substring matches.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

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


# ── Tests ──────────────────────────────────────────────────────────────────


@test("renders without errors when all logs are missing")
def _():
    """The dashboard must degrade gracefully — even with no data files,
    every section should render without raising."""
    with tempfile.TemporaryDirectory() as td:
        # Reroute every module's storage paths into tmp
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc, user_model as hm,
        )
        # response_capture
        rc.RESPONSES_DIR = Path(td) / "Responses"
        rc.CAPTURES_DIR = Path(td) / "Captures"
        # meta_synthesis
        ms.MEMORY_DIR = td
        ms.META_LOG_PATH = os.path.join(td, "meta_synthesis_log.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        # dimension_research
        dr.MEMORY_DIR = td
        dr.DIMENSION_LOG_PATH = os.path.join(td, "dimension_questions_log.jsonl")
        dr.SCAN_HISTORY_PATH = os.path.join(td, "dimension_scan_history.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "dimension_escalation_log.jsonl")
        # thread_puller
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")
        # multi_channel
        mc.MEMORY_DIR = td
        mc.DECISIONS_LOG_PATH = os.path.join(td, "multi_channel_decisions.jsonl")
        # user_model
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "user_learnings.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        assert "Loops — the circulatory system" in out
        # All four loop sections must appear
        assert "1. Inner reply" in out
        assert "2. Meta-synthesis" in out
        assert "3. Gap-driven outbound" in out
        assert "4. Thread-pull" in out
        # Cross-loop section shows even with zero counts
        assert "Cross-loop signals" in out


@test("loop 1 surfaces capture count + most-responded")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import response_capture as rc
        rc.RESPONSES_DIR = Path(td) / "Responses"
        rc.CAPTURES_DIR = Path(td) / "Captures"
        rc.RESPONSES_DIR.mkdir(parents=True)

        # Seed two captures referencing the same synthesis
        now_iso = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            (rc.RESPONSES_DIR / f"2026-04-26-12{i:02d}-foo.md").write_text(
                f"---\ncaptured_at: {now_iso}\nchannel: text\n"
                f"synthesis_referenced: \"On Quality\"\n---\n\nbody {i}",
                encoding="utf-8",
            )

        # Stub other modules to avoid log noise
        from myalicia.skills import (
            meta_synthesis as ms, dimension_research as dr,
            thread_puller as tp, multi_channel as mc, user_model as hm,
        )
        ms.MEMORY_DIR = td
        ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td
        mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        loop1 = out.split("1. Inner reply")[1].split("2. Meta-synthesis")[0]
        assert "2 captures in last 7d" in loop1, (
            f"expected capture count in loop 1: {loop1!r}"
        )
        assert "On Quality" in loop1, (
            f"expected most-responded synthesis in loop 1: {loop1!r}"
        )


@test("loop 3 surfaces persistent thin dims as escalation-eligible")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import dimension_research as dr, user_model as hm
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")

        # Two scans both showing 'body' as thin → persistent
        dr.record_dimension_scan(["body", "wealth"], "body")
        dr.record_dimension_scan(["body"], "body")

        # Force find_thin_dimensions to return ['body'] regardless of state
        original = hm.find_thin_dimensions
        hm.find_thin_dimensions = lambda **kw: ["body"]

        # Stub every other module to avoid noise
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            thread_puller as tp, multi_channel as mc,
        )
        rc.RESPONSES_DIR = Path(td) / "responses"
        rc.CAPTURES_DIR = Path(td) / "captures"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        try:
            from myalicia.skills.loops_dashboard import render_loops_dashboard
            out = render_loops_dashboard()
            loop3 = out.split("3. Gap-driven outbound")[1].split(
                "4. Thread-pull"
            )[0]
            assert "body" in loop3, f"expected body in loop 3: {loop3!r}"
            assert "persistent" in loop3, (
                f"expected persistent escalation flag: {loop3!r}"
            )
        finally:
            hm.find_thin_dimensions = original


@test("loop 4 surfaces pull/reply rate")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")

        # Seed two pulls with DISTINCTIVE bodies + one reply on the first
        msg_a = f"{tp.THREAD_PULL_BANNER}\n\nthe AI-as-unconscious thread continues"
        msg_b = f"{tp.THREAD_PULL_BANNER}\n\nwhat are you unwilling to feel"
        tp.record_thread_pull("thread A summary", msg_a)
        tp.record_thread_pull("thread B summary", msg_b)
        tp.mark_thread_pull_replied(msg_a, capture_path="/x.md")

        # Stub other modules
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        loop4 = out.split("4. Thread-pull")[1].split("Cross-loop signals")[0]
        assert "2 pull" in loop4
        assert "1 repl" in loop4
        assert "50%" in loop4, f"expected 50% reply rate: {loop4!r}"
        assert "thread A summary" in loop4, (
            f"expected the replied-to thread in 'most advanced': {loop4!r}"
        )


@test("Phase 14.5 _wow_delta helper: empty when both zero, ↑+N when growing, ↓-N when shrinking")
def _():
    from myalicia.skills.loops_dashboard import _wow_delta
    assert _wow_delta(0, 0) == ""
    assert _wow_delta(5, 3) == " ↑+2"
    assert _wow_delta(2, 5) == " ↓-3"
    assert _wow_delta(3, 3) == " →"
    assert _wow_delta(0, 4) == " ↓-4"
    assert _wow_delta(4, 0) == " ↑+4"


@test("Phase 14.5 loop 1 shows wow delta when this-week vs last-week differ")
def _():
    """Captures: 2 in last 7d, 5 in 7-14d window → ↓-3."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import response_capture as rc
        rc.RESPONSES_DIR = Path(td) / "Responses"
        rc.CAPTURES_DIR = Path(td) / "Captures"
        rc.RESPONSES_DIR.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        # 2 captures this week (within last 7d)
        for i, days_ago in enumerate([1, 3]):
            ts = (now - timedelta(days=days_ago)).isoformat()
            (rc.RESPONSES_DIR / f"thisweek-{i}.md").write_text(
                f"---\ncaptured_at: {ts}\nchannel: text\n"
                f"synthesis_referenced: \"X\"\n---\n\nbody",
                encoding="utf-8",
            )
        # 5 captures last week (7-14d ago)
        for i, days_ago in enumerate([8, 9, 10, 11, 13]):
            ts = (now - timedelta(days=days_ago)).isoformat()
            (rc.RESPONSES_DIR / f"lastweek-{i}.md").write_text(
                f"---\ncaptured_at: {ts}\nchannel: text\n"
                f"synthesis_referenced: \"Y\"\n---\n\nbody",
                encoding="utf-8",
            )

        # Stub other modules
        from myalicia.skills import (
            meta_synthesis as ms, dimension_research as dr,
            thread_puller as tp, multi_channel as mc, user_model as hm,
        )
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        loop1 = out.split("1. Inner reply")[1].split("2. Meta-synthesis")[0]
        assert "2 captures in last 7d" in loop1
        assert "↓-3" in loop1, (
            f"expected ↓-3 delta (2 this week vs 5 last week): {loop1!r}"
        )


@test("Phase 14.5 loop 4 shows wow delta on pulls + replies")
def _():
    """Pulls: 3 this week, 1 last week → ↑+2. Replies: 1 this week, 0 last → ↑+1."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        now = datetime.now(timezone.utc)
        # 3 pulls this week, 1 last week, 1 reply this week
        entries = []
        for i, days_ago in enumerate([1, 3, 5]):
            ts = (now - timedelta(days=days_ago)).isoformat()
            entries.append({"ts": ts, "thread_summary": f"thread {i}",
                            "message": f"{tp.THREAD_PULL_BANNER}\n\nbody {i}"})
        ts_lw = (now - timedelta(days=10)).isoformat()
        entries.append({"ts": ts_lw, "thread_summary": "lw",
                        "message": f"{tp.THREAD_PULL_BANNER}\n\nlast week body"})
        # 1 reply this week
        entries.append({"ts": (now - timedelta(days=2)).isoformat(),
                        "kind": "reply", "thread_summary": "thread 0",
                        "pull_ts": entries[0]["ts"], "capture_path": "/x.md"})
        with open(tp.THREAD_PULLS_PATH, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        # Stub others
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        loop4 = out.split("4. Thread-pull")[1].split("Cross-loop signals")[0]
        # 3 pulls this week vs 1 last week → ↑+2
        assert "3 pull" in loop4
        assert "↑+2" in loop4, f"expected ↑+2 on pulls: {loop4!r}"
        # 1 reply this week vs 0 last week → ↑+1
        assert "1 repl" in loop4
        assert "↑+1" in loop4, f"expected ↑+1 on replies: {loop4!r}"


@test("Phase 14.7 _dormancy_signal: returns empty when no activity ever or recent activity")
def _():
    from myalicia.skills.loops_dashboard import _dormancy_signal
    # No activity ever — cold start, not dormancy
    assert _dormancy_signal(None) == ""
    assert _dormancy_signal("") == ""
    # Recent activity (1 day ago) — no flag
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _dormancy_signal(recent) == ""
    # Just under threshold (20d) — no flag
    almost = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    assert _dormancy_signal(almost) == ""


@test("Phase 14.7 _dormancy_signal: flags ≥21d as dormant")
def _():
    from myalicia.skills.loops_dashboard import _dormancy_signal
    # 25 days ago — should flag dormant with the day count
    old = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
    out = _dormancy_signal(old)
    assert "dormant" in out
    assert "25" in out


@test("Phase 14.7 loop 4 surfaces dormant flag when last pull was >=21d ago")
def _():
    """Active replies in last 14d don't save the loop if pulls themselves
    haven't fired for 3+ weeks. The latency we care about is fire latency,
    not engagement latency."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")

        now = datetime.now(timezone.utc)
        # Last pull was 30 days ago — dormant
        old_pull_ts = (now - timedelta(days=30)).isoformat()
        with open(tp.THREAD_PULLS_PATH, "w") as f:
            f.write(json.dumps({
                "ts": old_pull_ts, "thread_summary": "old thread",
                "message": f"{tp.THREAD_PULL_BANNER}\n\nold body",
            }) + "\n")

        # Stub other modules
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        loop4 = out.split("4. Thread-pull")[1].split("Cross-loop signals")[0]
        assert "dormant" in loop4, f"expected dormant flag in loop 4: {loop4!r}"


@test("Phase 14.7 cold-start: empty logs → no dormancy flags (avoids noise)")
def _():
    """A first-deploy system has no logs at all. The dashboard must NOT
    flag cold-start as dormancy — that would be noise. Only loops that
    HAVE fired but stopped should be flagged."""
    with tempfile.TemporaryDirectory() as td:
        # Reroute everything to empty tmp
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        # No dormancy flags at cold start — every loop reads as fresh
        assert "dormant" not in out, (
            f"cold-start system must not flag dormancy: {out!r}"
        )


@test("Phase 14.8 detect_dormant_loops: ignores cold-start (no activity ever)")
def _():
    with tempfile.TemporaryDirectory() as td:
        # Reroute every module so all latest-getters return None
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import detect_dormant_loops
        out = detect_dormant_loops()
        assert out == [], f"cold-start system must produce no dormancy: {out}"


@test("Phase 14.8 detect_dormant_loops: flags loops with old activity")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        # Write a thread-pull from 30 days ago
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(tp.THREAD_PULLS_PATH, "w") as f:
            f.write(json.dumps({
                "ts": old_ts, "thread_summary": "old",
                "message": f"{tp.THREAD_PULL_BANNER}\n\nbody",
            }) + "\n")
        # Stub other modules
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import detect_dormant_loops
        dormant = detect_dormant_loops()
        loops = [d["loop"] for d in dormant]
        assert "thread_pull" in loops, (
            f"thread_pull (30d old) should be detected as dormant: {dormant}"
        )
        # Each entry has the required shape
        tp_entry = next(d for d in dormant if d["loop"] == "thread_pull")
        assert tp_entry["days_dormant"] >= 21
        assert tp_entry["last_activity_ts"] == old_ts
        assert "label" in tp_entry


@test("Phase 14.8 unalerted_dormant_loops: suppresses already-alerted loops")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import loops_dashboard as ld
        ld.MEMORY_DIR = Path(td)
        ld.DORMANCY_ALERTS_PATH = Path(td) / "dormancy_alerts.jsonl"
        # Pre-record an alert for thread_pull
        ld.record_dormancy_alert("thread_pull", 25)

        # Stub everything else; thread_pull dormant
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(tp.THREAD_PULLS_PATH, "w") as f:
            f.write(json.dumps({
                "ts": old_ts, "thread_summary": "old",
                "message": f"{tp.THREAD_PULL_BANNER}\n\nbody",
            }) + "\n")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        unalerted = ld.unalerted_dormant_loops()
        loops = [d["loop"] for d in unalerted]
        assert "thread_pull" not in loops, (
            f"thread_pull was already alerted; should be suppressed: {unalerted}"
        )


@test("Phase 14.9 _compute_active_streak_weeks: 0 when no current-week activity")
def _():
    from myalicia.skills.loops_dashboard import _compute_active_streak_weeks
    # Activity 14 days ago — current week (0-7d) is empty → streak 0
    old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    assert _compute_active_streak_weeks([old]) == 0
    # No timestamps → 0
    assert _compute_active_streak_weeks([]) == 0


@test("Phase 14.9 _compute_active_streak_weeks: counts consecutive weeks")
def _():
    from myalicia.skills.loops_dashboard import _compute_active_streak_weeks
    now = datetime.now(timezone.utc)
    # Activity in week 0, 1, 2 (i.e. last 3 weeks) — streak 3
    timestamps = [
        (now - timedelta(days=2)).isoformat(),    # week 0
        (now - timedelta(days=10)).isoformat(),   # week 1
        (now - timedelta(days=17)).isoformat(),   # week 2
        # gap at week 3 (21-28d) breaks the streak
    ]
    assert _compute_active_streak_weeks(timestamps) == 3


@test("Phase 14.9 _streak_signal: empty for streak < 2")
def _():
    from myalicia.skills.loops_dashboard import _streak_signal
    now = datetime.now(timezone.utc)
    # Just one week of activity — not noteworthy
    only_this_week = [(now - timedelta(days=2)).isoformat()]
    assert _streak_signal(only_this_week) == ""


@test("Phase 14.9 _streak_signal: surfaces 'active streak: N weeks' for N >= 2")
def _():
    from myalicia.skills.loops_dashboard import _streak_signal
    now = datetime.now(timezone.utc)
    timestamps = [
        (now - timedelta(days=1)).isoformat(),
        (now - timedelta(days=10)).isoformat(),
        (now - timedelta(days=15)).isoformat(),
    ]
    out = _streak_signal(timestamps)
    assert "active streak: 3 weeks" in out, f"expected 3-week streak: {out!r}"
    assert "🔥" in out


@test("Phase 13.16 topology section is present in render output")
def _():
    """The static ASCII diagram should appear at the end of /loops."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc, user_model as hm,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")
        hm.MEMORY_DIR = Path(td); hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        assert "Topology:" in out
        # Expected loop callouts in the topology
        assert "Loop 1: Phase 11" in out
        assert "Loop 2: 13.6/13.10" in out
        assert "Loop 3: 12.2" in out
        assert "Loop 4: 13.5/13.11" in out


@test("cross-loop section counts meta_synthesis-sourced learnings")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import user_model as hm
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "hl.jsonl"
        hm.BASELINES_DIR = Path(td) / "baselines"
        hm.BASELINES_DIR.mkdir()

        # Two meta_synthesis-sourced learnings + one manual
        hm.append_learning(
            claim=f"{USER_NAME} returns to Gamma often",
            dimension="knowledge", confidence=0.85,
            source="meta_synthesis:On Quality",
        )
        hm.append_learning(
            claim=f"{USER_NAME}'s writing has a strong arc",
            dimension="voice", confidence=0.8,
            source="meta_synthesis:Quality vs Pattern",
        )
        hm.append_learning(
            claim="Manual entry",
            dimension="identity", confidence=0.7,
            source="manual",
        )

        # Stub everything else
        from myalicia.skills import (
            response_capture as rc, meta_synthesis as ms,
            dimension_research as dr, thread_puller as tp,
            multi_channel as mc,
        )
        rc.RESPONSES_DIR = Path(td) / "r"
        rc.CAPTURES_DIR = Path(td) / "c"
        ms.MEMORY_DIR = td; ms.META_LOG_PATH = os.path.join(td, "ms.jsonl")
        ms.SYNTHESIS_DIR = Path(td) / "Synthesis"
        dr.MEMORY_DIR = td
        dr.SCAN_HISTORY_PATH = os.path.join(td, "scan.jsonl")
        dr.ESCALATION_LOG_PATH = os.path.join(td, "esc.jsonl")
        dr.DIMENSION_LOG_PATH = os.path.join(td, "qa.jsonl")
        tp.MEMORY_DIR = td; tp.THREAD_PULLS_PATH = os.path.join(td, "tp.jsonl")
        mc.MEMORY_DIR = td; mc.DECISIONS_LOG_PATH = os.path.join(td, "mc.jsonl")

        from myalicia.skills.loops_dashboard import render_loops_dashboard
        out = render_loops_dashboard()
        cross = out.split("Cross-loop signals")[1]
        # Two meta-sourced learnings should show
        assert "2 13.9 meta→user" in cross, (
            f"expected '2 13.9 meta→user' in cross-loop: {cross!r}"
        )


if __name__ == "__main__":
    print("Testing loops_dashboard.py …")
    sys.exit(_run_all())
