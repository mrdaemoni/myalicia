#!/usr/bin/env python3
"""
Unit tests for skills/thread_puller.py.

Sandbox-friendly: parser tests use sample profile text inline. Pull-history
tests reroute THREAD_PULLS_PATH to a tmpfile. Haiku-call tests aren't
executed here — they require live API. The wiring guardrail in
smoke_test.py asserts the import + midday branch exist.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
            print(f"  ✗ {label}\n      unexpected error: {type(e).__name__}: {e}")
    print(f"\n{_PASSED} passed · {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


# ── Sample profile text (mirrors person_diarization output style) ──────────

SAMPLE_PROFILE = """# the user This Week
**Week:** 2026-W16

**Open Threads**
Several threads await continuation: the AI-as-unconscious exploration needs operational unpacking; the "what are you unwilling to feel" quote connection to Stoic avoidance remains partially explored; the technology-body question opened a new investigation vector. His interest in making smaller circles as mastery principle suggests upcoming focus on compression.

**Emotional Weather**
The week reads as intellectually volcanic.
"""

SAMPLE_PROFILE_HEADER_STYLE = """# the user This Week

## Open Threads

Three threads remain open: the question of voice versus craft in his synthesis writing; the unresolved tension between depth and breadth in his reading list; the daimon-vs-comfort polarity that surfaced in two evening reflections this week.

## Other Section
Body.
"""

SAMPLE_PROFILE_NO_THREADS = """# the user This Week
**Week:** 2026-W17

**Emotional Weather**
Steady week.
"""


# ── parse_open_threads tests ────────────────────────────────────────────────


@test("parse_open_threads: bold-label style with semicolon-split prose")
def _():
    from myalicia.skills.thread_puller import parse_open_threads
    threads = parse_open_threads(SAMPLE_PROFILE)
    assert len(threads) >= 3, (
        f"expected ≥3 threads from semicolon split, got {len(threads)}: {threads}"
    )
    summaries = [t["summary"] for t in threads]
    assert any("AI-as-unconscious" in s for s in summaries), (
        f"expected AI-as-unconscious thread in: {summaries}"
    )
    assert any("technology-body" in s for s in summaries), (
        f"expected technology-body thread in: {summaries}"
    )


@test("parse_open_threads: header style with semicolon prose")
def _():
    from myalicia.skills.thread_puller import parse_open_threads
    threads = parse_open_threads(SAMPLE_PROFILE_HEADER_STYLE)
    assert len(threads) >= 3, (
        f"expected ≥3 threads from header-style profile, got {len(threads)}: {threads}"
    )
    summaries = " ".join(t["summary"] for t in threads)
    assert "voice versus craft" in summaries
    assert "daimon" in summaries
    # Must not bleed into the next section
    assert "Body." not in summaries


@test("parse_open_threads: no Open Threads section returns []")
def _():
    from myalicia.skills.thread_puller import parse_open_threads
    assert parse_open_threads(SAMPLE_PROFILE_NO_THREADS) == []
    assert parse_open_threads("") == []
    assert parse_open_threads("# Just a header\n") == []


@test("parse_open_threads: framing lead-in is stripped")
def _():
    from myalicia.skills.thread_puller import parse_open_threads
    threads = parse_open_threads(SAMPLE_PROFILE)
    # The first thread must NOT start with "Several threads await…"
    first = threads[0]["summary"]
    assert not first.lower().startswith("several threads"), (
        f"lead-in framing was not stripped: {first!r}"
    )


# ── pull-history tests ────────────────────────────────────────────────────


@test("record_thread_pull + recent_thread_pulls: round-trip")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")

        tp.record_thread_pull("about voice versus craft", "msg one")
        tp.record_thread_pull("about daimon-vs-comfort", "msg two")

        recent = tp.recent_thread_pulls(within_days=14)
        assert len(recent) == 2, f"expected 2 entries, got {len(recent)}"
        summaries = [e["thread_summary"] for e in recent]
        assert "about voice versus craft" in summaries
        assert "about daimon-vs-comfort" in summaries


@test("recent_thread_pulls: respects window")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")

        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with open(tp.THREAD_PULLS_PATH, "w") as f:
            f.write(json.dumps({"ts": old_ts, "thread_summary": "old", "message": "x"}) + "\n")
            f.write(json.dumps({"ts": new_ts, "thread_summary": "new", "message": "y"}) + "\n")

        recent = tp.recent_thread_pulls(within_days=14)
        summaries = [e["thread_summary"] for e in recent]
        assert "new" in summaries and "old" not in summaries, (
            f"window not respected: {summaries}"
        )


# ── pick_thread tests ──────────────────────────────────────────────────────


@test("pick_thread: returns one thread when nothing was pulled")
def _():
    from myalicia.skills.thread_puller import pick_thread
    threads = [
        {"summary": "the AI-as-unconscious exploration needs operational unpacking"},
        {"summary": "the technology-body question opened a new investigation vector"},
    ]
    chosen = pick_thread(threads, recent_pulls=[])
    assert chosen is not None
    assert chosen["summary"] in [t["summary"] for t in threads]


@test("pick_thread: filters out recently-pulled threads (high overlap)")
def _():
    from myalicia.skills.thread_puller import pick_thread
    threads = [
        {"summary": "the AI-as-unconscious exploration needs operational unpacking"},
        {"summary": "the technology-body question opened a new investigation vector"},
    ]
    # A previous pull about AI-as-unconscious — overlap should suppress it
    recent = [{
        "thread_summary": "the AI-as-unconscious exploration needs deeper operational unpacking and inquiry",
    }]
    # Run several times so we can be confident the AI thread is filtered out
    for _ in range(20):
        chosen = pick_thread(threads, recent_pulls=recent)
        assert chosen is not None
        assert "AI-as-unconscious" not in chosen["summary"], (
            f"recently-pulled thread leaked through: {chosen}"
        )


@test("pick_thread: returns None when ALL threads are recently pulled")
def _():
    from myalicia.skills.thread_puller import pick_thread
    threads = [
        {"summary": "the AI-as-unconscious exploration needs operational unpacking"},
    ]
    recent = [{
        "thread_summary": "the AI-as-unconscious exploration needs operational unpacking",
    }]
    chosen = pick_thread(threads, recent_pulls=recent)
    assert chosen is None, f"expected None when all on cooldown, got {chosen}"


@test("pick_thread: returns None for empty thread list")
def _():
    from myalicia.skills.thread_puller import pick_thread
    assert pick_thread([], recent_pulls=[]) is None


# ── build_thread_pull_message: precondition gates ──────────────────────────


@test("build_thread_pull_message: returns None when no profile dir")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.PROFILES_DIR = os.path.join(td, "does-not-exist")
        out = tp.build_thread_pull_message()
        assert out is None, f"expected None with no profile, got {out!r}"


@test("Phase 13.11 is_thread_pull_message: detects banner")
def _():
    from myalicia.skills.thread_puller import is_thread_pull_message, THREAD_PULL_BANNER
    assert is_thread_pull_message(f"{THREAD_PULL_BANNER}\n\nsomething") is True
    assert is_thread_pull_message("a normal Alicia message") is False
    assert is_thread_pull_message("") is False
    assert is_thread_pull_message(None) is False


@test("Phase 13.11 mark_thread_pull_replied: matches recent pull and writes reply record")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")

        # Seed a real thread-pull
        message_body = "what does it mean to live the technology-body question?"
        full_message = f"{tp.THREAD_PULL_BANNER}\n\n{message_body}"
        tp.record_thread_pull(
            "the technology-body question opened a new investigation vector",
            full_message,
        )

        # User replies to that pull — bridge should match
        result = tp.mark_thread_pull_replied(
            full_message, capture_path="/some/capture.md",
        )
        assert result is not None
        assert result["kind"] == "reply"
        assert "technology-body" in result["thread_summary"]
        assert result["capture_path"] == "/some/capture.md"

        # Reply record persisted to log
        replies = tp.recent_thread_pull_replies(within_days=7)
        assert len(replies) == 1
        assert replies[0]["thread_summary"] == result["thread_summary"]


@test("Phase 13.11 mark_thread_pull_replied: returns None for non-thread-pull text")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")
        result = tp.mark_thread_pull_replied(
            "a regular message without the banner", capture_path="/x.md",
        )
        assert result is None


@test("Phase 13.11 advanced_threads: groups replies by thread_summary")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")

        # Two pulls for two different threads
        msg_a = f"{tp.THREAD_PULL_BANNER}\n\nthread A body"
        msg_b = f"{tp.THREAD_PULL_BANNER}\n\nthread B body"
        tp.record_thread_pull("thread A summary", msg_a)
        tp.record_thread_pull("thread B summary", msg_b)

        # 2 replies on A, 1 on B
        tp.mark_thread_pull_replied(msg_a, capture_path="/a1.md")
        tp.mark_thread_pull_replied(msg_a, capture_path="/a2.md")
        tp.mark_thread_pull_replied(msg_b, capture_path="/b1.md")

        advanced = tp.advanced_threads(within_days=7)
        assert len(advanced) == 2
        # Sorted by reply_count desc — thread A first
        assert advanced[0]["thread_summary"] == "thread A summary"
        assert advanced[0]["reply_count"] == 2
        assert len(advanced[0]["capture_paths"]) == 2
        assert advanced[1]["reply_count"] == 1


@test("Phase 13.11 recent_thread_pulls: skips reply records (kind='reply')")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.MEMORY_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")
        msg = f"{tp.THREAD_PULL_BANNER}\n\nbody"
        tp.record_thread_pull("a thread", msg)
        tp.mark_thread_pull_replied(msg, capture_path="/x.md")
        # recent_thread_pulls must report just 1 (the pull), not 2 (pull + reply)
        pulls = tp.recent_thread_pulls(within_days=14)
        assert len(pulls) == 1, (
            f"recent_thread_pulls must filter out reply records: got {len(pulls)}"
        )
        assert pulls[0]["thread_summary"] == "a thread"


@test("build_thread_pull_message: returns None when profile has no Open Threads")
def _():
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import thread_puller as tp
        tp.PROFILES_DIR = td
        tp.THREAD_PULLS_PATH = os.path.join(td, "thread_pulls.jsonl")
        with open(os.path.join(td, "2026-W18-hector.md"), "w") as f:
            f.write(SAMPLE_PROFILE_NO_THREADS)
        out = tp.build_thread_pull_message()
        assert out is None, f"expected None with empty Open Threads, got {out!r}"


if __name__ == "__main__":
    print("Testing thread_puller.py …")
    sys.exit(_run_all())
