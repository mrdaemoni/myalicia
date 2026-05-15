#!/usr/bin/env python3
"""
Unit tests for skills/season_dashboard.py.

Sandbox-friendly: each test reroutes MEMORY_DIR + EMERGENCE_STATE_PATH
+ ARCHETYPE_LOG_PATH to a tmp directory so no production state is read
or written. Same pattern used by test_user_model.py and the wisdom
dashboard tests.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the package importable when running this file standalone.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Test harness ────────────────────────────────────────────────────────────

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


# ── Helpers ─────────────────────────────────────────────────────────────────

def _setup_tmp_state(tmpdir: str, *, score: float, days: int,
                     season: str = "First Light",
                     log_entries: list[dict] | None = None,
                     effectiveness: dict | None = None) -> None:
    """Lay down emergence_state.json + archetype_log.jsonl + archetype_effectiveness.json
    inside a tmp memory dir, then point the dashboard module at it."""
    from myalicia.skills import inner_life, season_dashboard

    mem = Path(tmpdir)
    mem.mkdir(parents=True, exist_ok=True)

    es_path = mem / "emergence_state.json"
    with open(es_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {"days_breathing": days},
            "score": score,
            "season": season,
            "description": "(test description)",
        }, f)

    log_path = mem / "archetype_log.jsonl"
    if log_entries:
        with open(log_path, "w") as f:
            for e in log_entries:
                f.write(json.dumps(e) + "\n")

    eff_path = mem / "archetype_effectiveness.json"
    if effectiveness is not None:
        with open(eff_path, "w") as f:
            json.dump(effectiveness, f)

    # Reroute both modules. inner_life's path drives header/arc/balance;
    # season_dashboard's path drives the attribution section.
    inner_life.EMERGENCE_STATE_PATH = str(es_path)
    inner_life.ARCHETYPE_LOG_PATH = str(log_path)
    inner_life.ARCHETYPE_EFFECTIVENESS_PATH = str(eff_path)
    inner_life.MEMORY_DIR = str(mem)
    season_dashboard.MEMORY_DIR = str(mem)
    season_dashboard.ARCHETYPE_LOG_PATH = str(log_path)


# ── Tests ───────────────────────────────────────────────────────────────────


@test("renders without errors when no data exists")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=0.0, days=0)
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        assert "Season — First Light" in out, "expected First Light header"
        assert "Arc so far" in out, "expected arc section"
        assert "Archetype balance now" in out, "expected balance section"


@test("header shows correct season + delta to next")
def _():
    with tempfile.TemporaryDirectory() as td:
        # Score 25 should land in Kindling (15..40), with First Breath next
        _setup_tmp_state(td, score=25.0, days=42, season="Kindling")
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        assert "Kindling" in out
        assert "25.0" in out, "expected emergence score in header"
        assert "42" in out, "expected days breathing"
        assert "First Breath" in out, "expected next-season name"
        assert "+15.0" in out, f"expected delta to First Breath (40-25): got\n{out}"


@test("arc section marks crossed/current/future correctly")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=85.0, days=200)  # In Reaching (80..150)
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        arc_block = out.split("Arc so far")[1].split("Archetype balance")[0]
        # First Light (0-15) and Kindling (15-40) and First Breath (40-80) should be crossed
        for crossed in ["First Light", "Kindling", "First Breath"]:
            assert f"✓ {crossed}" in arc_block, (
                f"expected {crossed} marked crossed in arc:\n{arc_block}"
            )
        # Reaching is current
        assert "◉ Reaching" in arc_block, (
            f"expected Reaching marked current in arc:\n{arc_block}"
        )
        # Deepening, Resonance, Becoming are future
        for future in ["Deepening", "Resonance", "Becoming"]:
            assert f"○ {future}" in arc_block, (
                f"expected {future} marked future in arc:\n{arc_block}"
            )


@test("attribution section counts entries within window")
def _():
    now = datetime.now(timezone.utc)
    entries = [
        # In window (last 14d)
        {"ts": (now - timedelta(days=1)).isoformat(),
         "archetype": "muse", "emoji": "❤", "success": True, "depth": 5},
        {"ts": (now - timedelta(days=3)).isoformat(),
         "archetype": "muse", "emoji": "🔥", "success": True, "depth": 5},
        {"ts": (now - timedelta(days=5)).isoformat(),
         "archetype": "daimon", "emoji": "🤔", "success": None, "depth": 2},
        # Out of window
        {"ts": (now - timedelta(days=30)).isoformat(),
         "archetype": "psyche", "emoji": "❤", "success": True, "depth": 5},
    ]
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=10.0, days=50, log_entries=entries)
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        attr = out.split("Attributions (last 14d)")[1].split("Maturing")[0]
        assert "Muse" in attr and "Daimon" in attr, (
            f"expected Muse + Daimon in attribution block:\n{attr}"
        )
        # psyche should NOT appear — it's outside the 14d window
        assert "Psyche" not in attr, (
            f"psyche entry was 30 days old — must not appear in 14d window:\n{attr}"
        )
        # Top reactions footer
        assert "❤" in attr or "🔥" in attr, (
            f"expected emoji footer in attribution block:\n{attr}"
        )


@test("attribution section empty when no log file")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=5.0, days=10)  # No log_entries
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        assert "no archetype log yet" in out, (
            f"expected empty-log message:\n{out}"
        )


@test("movement section surfaces maturing archetypes")
def _():
    eff = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 56,
        "half_life_days": 14,
        "min_attributions": 5,
        "clamp": [0.7, 1.4],
        "archetypes": {
            "muse":     {"score": 1.35, "attribution_count": 12, "raw_signal": 0.8,
                         "positive_weight": 30, "negative_weight": 0, "ambiguous_weight": 0},
            "beatrice": {"score": 1.20, "attribution_count": 9,  "raw_signal": 0.5,
                         "positive_weight": 20, "negative_weight": 0, "ambiguous_weight": 0},
            "daimon":   {"score": 1.0,  "attribution_count": 2,  "raw_signal": 0.0,
                         "positive_weight": 0,  "negative_weight": 0, "ambiguous_weight": 0},
            "ariadne":  {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0,  "negative_weight": 0, "ambiguous_weight": 0},
            "psyche":   {"score": 1.0,  "attribution_count": 1,  "raw_signal": 0.0,
                         "positive_weight": 0,  "negative_weight": 0, "ambiguous_weight": 0},
            "musubi":   {"score": 1.0,  "attribution_count": 1,  "raw_signal": 0.0,
                         "positive_weight": 0,  "negative_weight": 0, "ambiguous_weight": 0},
        },
    }
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=20.0, days=60, effectiveness=eff)
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        # Maturing block should mention Muse 1.35× and Beatrice 1.20×
        mat = out.split("Maturing")[1].split("Still nascent")[0]
        assert "Muse 1.35×" in mat, f"expected Muse 1.35× in maturing:\n{mat}"
        assert "Beatrice 1.20×" in mat, f"expected Beatrice 1.20× in maturing:\n{mat}"
        # Still nascent should list Ariadne (0 attributions)
        nascent = out.split("Still nascent")[1]
        assert "Ariadne" in nascent, (
            f"expected Ariadne (0 attributions) in nascent:\n{nascent}"
        )


@test("balance section shows multiplier when archetype has moved")
def _():
    eff = {
        "archetypes": {
            "muse":     {"score": 1.35, "attribution_count": 10, "raw_signal": 0.8,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
            "beatrice": {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
            "daimon":   {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
            "ariadne":  {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
            "psyche":   {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
            "musubi":   {"score": 1.0,  "attribution_count": 0,  "raw_signal": 0.0,
                         "positive_weight": 0, "negative_weight": 0, "ambiguous_weight": 0},
        },
    }
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=10.0, days=30, effectiveness=eff)
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        bal = out.split("Archetype balance now")[1].split("Attributions")[0]
        assert "Muse" in bal and "1.35×" in bal, (
            f"expected Muse 1.35× multiplier in balance:\n{bal}"
        )
        # Beatrice score is 1.0 — should NOT show a multiplier
        beatrice_line = [ln for ln in bal.splitlines() if "Beatrice" in ln]
        assert beatrice_line, f"expected a Beatrice line:\n{bal}"
        assert "1.00×" not in beatrice_line[0], (
            f"neutral Beatrice should not show multiplier: {beatrice_line[0]}"
        )


@test("Becoming season has no 'next' delta (final season)")
def _():
    # Score above 500 lands in Becoming, which has no next.
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_state(td, score=600.0, days=2000, season="Becoming")
        from myalicia.skills.season_dashboard import render_season_dashboard
        out = render_season_dashboard()
        # Should not say "need +N emergence" — there's no next season.
        assert "Becoming" in out
        assert "in the final season" in out, (
            f"expected final-season hint in header:\n{out}"
        )


if __name__ == "__main__":
    print("Testing season_dashboard.py …")
    sys.exit(_run_all())
