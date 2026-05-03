#!/usr/bin/env python3
"""
Unit tests for skills/multichannel_dashboard.py.

Sandbox-friendly: every test reroutes the multi_channel decisions log
to a tmpfile and seeds it with synthesized decision events.
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


def _setup_tmp_log(tmpdir: str) -> str:
    """Reroute the multi_channel log to a tmp file. Returns the path."""
    from skills import multi_channel as mc
    p = os.path.join(tmpdir, "multi_channel_decisions.jsonl")
    mc.MEMORY_DIR = tmpdir
    mc.DECISIONS_LOG_PATH = p
    return p


def _seed_log(path: str, entries: list[dict]) -> None:
    """Write entries to the log, auto-stamping ts as 'now' if absent."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        for e in entries:
            full = dict(e)
            full.setdefault("ts", now_iso)
            f.write(json.dumps(full) + "\n")


# ── Tests ──────────────────────────────────────────────────────────────────


@test("empty log: shows the no-decisions hint, no crash")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "Multichannel — last 24h" in out
        assert "No decisions logged yet" in out


@test("renders header + voice + drawing + skip sections")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        _seed_log(log_path, [
            # Voice fires
            {"channel": "voice", "voice": True, "path": "fast_voice_default",
             "slot": "morning", "rationale": "short clean text",
             "text_hash": "v1", "text_len": 80},
            {"channel": "voice", "voice": True, "path": "fast_voice_default",
             "slot": "midday", "rationale": "short clean text",
             "text_hash": "v2", "text_len": 90},
            # Voice skips
            {"channel": "voice", "voice": False, "path": "skip_markdown_list",
             "slot": "evening", "rationale": "heuristic skip: markdown_list",
             "text_hash": "v3", "text_len": 200},
            # Drawing fires
            {"drawing": True, "path": "fast_high_conviction",
             "score": 3.5, "archetype": "muse", "source_kind": "surfacing",
             "rationale": "score 3.50 ≥ 3.0", "text_hash": "d1", "decision_id": "x"},
            # Drawing skips
            {"drawing": False, "path": "below_floor",
             "score": 1.0, "archetype": "daimon", "source_kind": "contradiction",
             "rationale": "score 1.00 < floor 1.5", "text_hash": "d2", "decision_id": "y"},
            {"drawing": False, "path": "judge_no",
             "score": 2.2, "archetype": "psyche", "source_kind": "surfacing",
             "rationale": "purely conversational", "text_hash": "d3", "decision_id": "z"},
        ])
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        # Header
        assert "Multichannel — last 24h" in out
        # Voice section: 2 fired, 1 skipped → 67% rate
        assert "Voice:" in out
        assert "2 fired" in out and "1 skipped" in out
        assert "67%" in out
        # Drawing section: 1 fired, 2 skipped → 33% rate
        assert "Drawing:" in out
        assert "1 fired" in out
        assert "33%" in out
        # Top skip reasons
        assert "Top skip reasons:" in out


@test("saturation guard hint surfaces when tripped")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        _seed_log(log_path, [
            {"channel": "voice", "voice": False, "path": "saturation_guard",
             "slot": "evening", "rationale": "cap reached",
             "text_hash": "v1", "text_len": 80},
        ])
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "saturation guard tripped" in out


@test("recent examples section shows fired + skipped per channel")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Most recent voice fire + voice skip + drawing fire + drawing skip
        base = datetime.now(timezone.utc)
        entries = [
            {"ts": (base - timedelta(minutes=5)).isoformat(),
             "channel": "voice", "voice": True, "path": "fast_voice_default",
             "slot": "midday", "rationale": "x", "text_hash": "v1", "text_len": 50},
            {"ts": (base - timedelta(minutes=10)).isoformat(),
             "channel": "voice", "voice": False, "path": "skip_markdown_heading",
             "slot": "evening", "rationale": "header detected",
             "text_hash": "v2", "text_len": 120},
            {"ts": (base - timedelta(minutes=15)).isoformat(),
             "drawing": True, "path": "fast_high_conviction", "score": 3.5,
             "archetype": "muse", "source_kind": "surfacing",
             "rationale": "x", "text_hash": "d1", "decision_id": "a"},
            {"ts": (base - timedelta(minutes=20)).isoformat(),
             "drawing": False, "path": "judge_no", "score": 2.0,
             "archetype": "daimon", "source_kind": "contradiction",
             "rationale": "purely conversational",
             "text_hash": "d2", "decision_id": "b"},
        ]
        with open(log_path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "Recent decisions:" in out
        # Both fire emojis present
        assert "🎙️ FIRE" in out and "🎙️ SKIP" in out
        assert "🎨 FIRE" in out and "🎨 SKIP" in out


@test("respects 24h window — entries older than 24h are excluded")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        new_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with open(log_path, "w") as f:
            f.write(json.dumps({
                "ts": old_ts, "channel": "voice", "voice": True,
                "path": "fast_voice_default", "slot": "midday",
                "rationale": "old", "text_hash": "old", "text_len": 50,
            }) + "\n")
            f.write(json.dumps({
                "ts": new_ts, "channel": "voice", "voice": True,
                "path": "fast_voice_default", "slot": "morning",
                "rationale": "new", "text_hash": "new", "text_len": 50,
            }) + "\n")

        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        # Only the new (within 24h) entry should count → "1 fired"
        assert "1 fired" in out, (
            f"30h-old entry must not count toward 24h totals:\n{out}"
        )


@test("voice-only log: drawing section says 'no decisions'")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        _seed_log(log_path, [
            {"channel": "voice", "voice": True, "path": "fast_voice_default",
             "slot": "midday", "rationale": "x", "text_hash": "v1", "text_len": 50},
        ])
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "Voice:" in out
        assert "1 fired" in out
        assert "Drawing:" in out
        assert "no decisions in last 24h" in out


@test("Phase 14.3 coherent moments: empty log → 'none in last 24h' message")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Seed only a regular voice fire — no coherent_moment
        _seed_log(log_path, [
            {"channel": "voice", "voice": True, "path": "fast_voice_default",
             "slot": "morning", "rationale": "x", "text_hash": "v1", "text_len": 50},
        ])
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "Coherent moments" in out
        assert "none in last 24h" in out


@test("Phase 14.3 coherent moments: counts entries + groups by archetype + shows latest tail")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Distinct timestamps so the "latest tail" is deterministic
        base = datetime.now(timezone.utc)
        with open(log_path, "w") as f:
            f.write(json.dumps({
                "ts": (base - timedelta(hours=4)).isoformat(),
                "channel": "voice", "voice": True, "path": "fast_voice_default",
                "slot": "morning", "rationale": "x", "text_hash": "v1", "text_len": 50,
            }) + "\n")
            f.write(json.dumps({
                "ts": (base - timedelta(hours=3)).isoformat(),
                "drawing": True, "path": "fast_high_conviction", "score": 3.5,
                "archetype": "muse", "source_kind": "surfacing",
                "rationale": "x", "text_hash": "d1", "decision_id": "y",
            }) + "\n")
            f.write(json.dumps({
                "ts": (base - timedelta(hours=2)).isoformat(),
                "channel": "coherent_moment", "voice": True, "drawing": True,
                "path": "voice_drawing_tail", "archetype": "muse",
                "rationale": "older muse tail", "text_hash": "c1",
            }) + "\n")
            f.write(json.dumps({
                "ts": (base - timedelta(hours=1)).isoformat(),
                "channel": "coherent_moment", "voice": True, "drawing": True,
                "path": "voice_drawing_tail", "archetype": "muse",
                "rationale": "newer muse tail", "text_hash": "c2",
            }) + "\n")
            # Most recent — should be the surfaced "latest tail"
            f.write(json.dumps({
                "ts": base.isoformat(),
                "channel": "coherent_moment", "voice": True, "drawing": True,
                "path": "voice_drawing_tail", "archetype": "daimon",
                "rationale": "the white line refusing to break", "text_hash": "c3",
            }) + "\n")

        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "3 in last 24h" in out, f"expected '3 in last 24h': {out!r}"
        assert "Muse 2" in out and "Daimon 1" in out
        # Latest tail = the most recently-stamped one
        assert "the white line refusing to break" in out, (
            f"expected the most recent tail to surface as 'latest tail': {out!r}"
        )


@test("Phase 14.3 coherent_moment NOT double-counted in drawing/voice rollups")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Seed coherent_moment entries only (each carries voice=True + drawing=True)
        _seed_log(log_path, [
            {"channel": "coherent_moment", "voice": True, "drawing": True,
             "path": "voice_drawing_tail", "archetype": "muse",
             "rationale": "tail", "text_hash": "c1"},
            {"channel": "coherent_moment", "voice": True, "drawing": True,
             "path": "voice_drawing_tail", "archetype": "daimon",
             "rationale": "tail", "text_hash": "c2"},
        ])
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        # Voice + drawing channels should both report no decisions —
        # the coherent_moment entries belong to their own section, not the per-channel rollup.
        assert "Voice:* no decisions in last 24h" in out, (
            f"coherent_moment must not double-count toward voice channel rollup: "
            f"{out!r}"
        )
        assert "Drawing:* no decisions in last 24h" in out, (
            f"coherent_moment must not double-count toward drawing channel rollup: "
            f"{out!r}"
        )
        # But the coherent moments section itself shows the count
        assert "2 in last 24h" in out


@test("graceful when log import fails")
def _():
    # Force an ImportError on multi_channel by replacing module entry briefly
    import sys as _sys
    saved = _sys.modules.pop("skills.multi_channel", None)
    _sys.modules["skills.multi_channel"] = None  # forces ImportError on next import
    try:
        # Need a fresh import of the dashboard so the import inside it re-runs
        _sys.modules.pop("skills.multichannel_dashboard", None)
        from skills.multichannel_dashboard import render_multichannel_dashboard
        out = render_multichannel_dashboard()
        assert "/multichannel error" in out, f"expected error message, got:\n{out}"
    finally:
        # Restore the module
        if saved is not None:
            _sys.modules["skills.multi_channel"] = saved
        else:
            _sys.modules.pop("skills.multi_channel", None)
        _sys.modules.pop("skills.multichannel_dashboard", None)


if __name__ == "__main__":
    print("Testing multichannel_dashboard.py …")
    sys.exit(_run_all())
