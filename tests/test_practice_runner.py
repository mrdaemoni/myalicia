#!/usr/bin/env python3
"""
Unit tests for practice_runner (Layer 4).

Every test points ALICIA_VAULT_ROOT / ALICIA_MEMORY_DIR at fresh tmp dirs
so the real vault is never touched.

Usage:
    python tests/test_practice_runner.py
    pytest tests/test_practice_runner.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_env() -> tuple[Path, Path]:
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload_runner():
    if "skills.practice_runner" in sys.modules:
        importlib.reload(sys.modules["skills.practice_runner"])
    import skills.practice_runner as pr
    return pr


# ── Tests ───────────────────────────────────────────────────────────────────


def test_import_and_public_api() -> None:
    _fresh_env()
    pr = _reload_runner()
    for name in (
        "Practice", "USE_PRACTICE_RUNNER", "PRACTICES_DIR", "LIVED_DIR",
        "MAX_ACTIVE_PRACTICES", "CHECK_IN_DAYS",
        "load_practices", "active_practices",
        "promote_synthesis_to_practice",
        "due_check_ins", "compose_check_in", "record_check_in",
        "record_log_entry", "close_practice",
        "check_invariants", "run_daily_pass",
    ):
        assert hasattr(pr, name), f"practice_runner missing: {name}"


def test_feature_flag_default_is_off() -> None:
    os.environ.pop("USE_PRACTICE_RUNNER", None)
    _fresh_env()
    pr = _reload_runner()
    assert pr.USE_PRACTICE_RUNNER is False


def test_promote_and_load_round_trip() -> None:
    _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice",
        synthesis_title="A great synthesis",
        synthesis_path="Alicia/Wisdom/Synthesis/A great synthesis.md",
        instrument="Do the thing every day for 30 days.",
        archetype="Beatrice",
        started_at="2026-04-22",
    )
    assert p.slug == "test-practice"
    assert (Path(p.path) / "practice.md").exists()
    assert (Path(p.path) / "log.md").exists()
    loaded = pr.load_practices()
    assert len(loaded) == 1
    assert loaded[0].title == "Test practice"
    assert loaded[0].archetype == "Beatrice"
    assert loaded[0].status == "active"


def test_max_active_practices_cap_enforced() -> None:
    _fresh_env()
    pr = _reload_runner()
    for i in range(pr.MAX_ACTIVE_PRACTICES):
        pr.promote_synthesis_to_practice(
            title=f"Practice {i}",
            synthesis_title="s", synthesis_path="", instrument="do",
            archetype="Beatrice", started_at="2026-04-22",
        )
    try:
        pr.promote_synthesis_to_practice(
            title="Overflow practice",
            synthesis_title="s", synthesis_path="", instrument="do",
            archetype="Beatrice", started_at="2026-04-22",
        )
    except RuntimeError as e:
        assert "Cap reached" in str(e)
    else:
        raise AssertionError("cap was not enforced")


def test_due_check_ins_day_3_fires() -> None:
    _fresh_env()
    pr = _reload_runner()
    pr.promote_synthesis_to_practice(
        title="Test practice",
        synthesis_title="s", synthesis_path="", instrument="do",
        archetype="Beatrice", started_at="2026-04-22",
    )
    # Now = start + 3 days → day-3 check-in should fire
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    due = pr.due_check_ins(now=now)
    assert len(due) == 1
    practice, day = due[0]
    assert practice.slug == "test-practice"
    assert day == 3


def test_due_check_ins_skipped_after_recorded() -> None:
    _fresh_env()
    pr = _reload_runner()
    pr.promote_synthesis_to_practice(
        title="Test practice",
        synthesis_title="s", synthesis_path="", instrument="do",
        archetype="Beatrice", started_at="2026-04-22",
    )
    pr.record_check_in("test-practice", 3)
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    due = pr.due_check_ins(now=now)
    assert due == [], f"recorded check-in must not re-fire, got {due}"


def test_compose_check_in_references_instrument() -> None:
    _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="s", synthesis_path="",
        instrument="One public-facing attempt per day.",
        archetype="Beatrice", started_at="2026-04-22",
    )
    msg = pr.compose_check_in(p, 7)
    assert "day 7" in msg
    assert "public-facing attempt" in msg
    assert "Beatrice" in msg


def test_compose_check_in_day_specific_templates() -> None:
    """Each canonical day_number gets a distinct framing — Phase 11.3+.
    Day 3 = baseline, Day 7 = patterns, Day 14 = midpoint, Day 21 =
    integration, Day 30 = closeout."""
    _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice",
        synthesis_title="The descent claim",
        synthesis_path="",
        instrument="Do the thing.",
        archetype="Beatrice", started_at="2026-04-22",
    )

    # Day 3 — baseline reading, mentions "reporter" and "witness"
    d3 = pr.compose_check_in(p, 3)
    assert "day 3" in d3
    assert "reporter" in d3 and "witness" in d3, "day 3 must be baseline framing"

    # Day 7 — pattern reading, mentions "repeating" and "surprised"
    d7 = pr.compose_check_in(p, 7)
    assert "day 7" in d7
    assert "repeating" in d7.lower(), "day 7 must ask about patterns"
    assert "surprised" in d7.lower(), "day 7 must ask about surprises"

    # Day 14 — midpoint, references the parent synthesis
    d14 = pr.compose_check_in(p, 14)
    assert "day 14" in d14
    assert "Midpoint" in d14
    assert "The descent claim" in d14, (
        "day 14 must reference the parent synthesis title"
    )

    # Day 21 — integration check, asks about automatic vs effortful
    d21 = pr.compose_check_in(p, 21)
    assert "day 21" in d21
    assert "automatic" in d21.lower() and "effortful" in d21.lower(), (
        "day 21 must ask about automatic vs effortful"
    )

    # Day 30 — closeout signal, names the Lived note
    d30 = pr.compose_check_in(p, 30)
    assert "day 30" in d30
    assert "Lived note" in d30 or "lived note" in d30.lower()
    assert "what did this practice teach" in d30.lower(), (
        "day 30 must ask the closing question explicitly"
    )

    # All five templates must produce different bodies
    bodies = [d3, d7, d14, d21, d30]
    assert len(set(bodies)) == 5, (
        "all 5 day-N templates must be distinct"
    )


def test_close_practice_embeds_captures_made_during_practice() -> None:
    """Phase 11.12: when a practice closes, the Lived note includes a
    'Captures during this practice' section listing every capture (Captures/
    + Responses/) made between started_at and now. Captures outside the
    window are excluded."""
    vault, _ = _fresh_env()
    pr = _reload_runner()
    # Reload response_capture too so they share env
    if "skills.response_capture" in sys.modules:
        importlib.reload(sys.modules["skills.response_capture"])
    import skills.response_capture as rc

    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="Some synthesis",
        synthesis_path="",
        instrument="Do the thing.",
        archetype="Beatrice", started_at="2026-04-22",
    )
    # Two captures inside the window
    rc.capture_unprompted(
        "the resistance is the practice",
        now=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    rc.capture_response(
        "still very true",
        proactive_synthesis_title="Some synthesis",
        now=datetime(2026, 4, 25, tzinfo=timezone.utc),
    )
    # One capture before the window (must NOT appear)
    rc.capture_unprompted(
        "before the practice started",
        now=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )

    lived_path = pr.close_practice(
        p.slug,
        lived_note_text="The body learned to attend differently.",
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    text = lived_path.read_text(encoding="utf-8")
    # Captures section present
    assert "## Captures during this practice" in text
    # Both in-window excerpts present
    assert "resistance is the practice" in text
    assert "still very true" in text
    # Capture KIND tags present ([R] for Response, [C] for Capture)
    assert "[R]" in text and "[C]" in text
    # Out-of-window capture excluded
    assert "before the practice started" not in text


def test_close_practice_writes_lived_note() -> None:
    vault, _ = _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="The synthesis",
        synthesis_path="Alicia/Wisdom/Synthesis/The synthesis.md",
        instrument="do", archetype="Beatrice", started_at="2026-04-22",
    )
    lived = pr.close_practice(
        p.slug, lived_note_text="I learned that the body's knowing precedes the mind's naming.",
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    assert lived.exists()
    text = lived.read_text(encoding="utf-8")
    assert "The synthesis" in text
    assert "body's knowing" in text
    # practice.md's status must be flipped
    pmd = Path(p.path) / "practice.md"
    assert "status: closed" in pmd.read_text(encoding="utf-8")
    # closeout.md exists
    assert (Path(p.path) / "closeout.md").exists()


def test_invariant_closed_missing_lived_note_fires() -> None:
    vault, _ = _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="s", synthesis_path="",
        instrument="do", archetype="Beatrice", started_at="2026-04-22",
    )
    # Flip status to closed WITHOUT writing Lived note
    pmd = Path(p.path) / "practice.md"
    text = pmd.read_text(encoding="utf-8").replace("status: active", "status: closed")
    pmd.write_text(text, encoding="utf-8")
    vs = pr.check_invariants()
    kinds = {v["kind"] for v in vs}
    assert "closed_practice_missing_lived_note" in kinds, vs


def test_invariant_overdue_check_in_fires() -> None:
    _fresh_env()
    pr = _reload_runner()
    # Started 10 days ago → day-3 and day-7 are past their grace windows.
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="s", synthesis_path="",
        instrument="do", archetype="Beatrice", started_at=start,
    )
    vs = pr.check_invariants()
    kinds = [v["kind"] for v in vs]
    assert "overdue_check_in" in kinds, vs


def test_record_log_entry_appends() -> None:
    _fresh_env()
    pr = _reload_runner()
    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="s", synthesis_path="",
        instrument="do", archetype="Beatrice", started_at="2026-04-22",
    )
    out = pr.record_log_entry(
        p.slug, "Posted a half-formed Loom to #eng — exposure felt: 6/10.",
        now=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    text = out.read_text(encoding="utf-8")
    assert "Posted a half-formed Loom" in text
    # Second append lands on a new line
    pr.record_log_entry(
        p.slug, "Shared WIP deck with Samir — 4/10.",
        now=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    text2 = out.read_text(encoding="utf-8")
    assert text2.count("\n") > text.count("\n")


def test_record_log_entry_queues_practice_progress_surfacing() -> None:
    """Logging an attempt should queue a single short-lived surfacing tagged
    `kind=practice_progress` with the practice's archetype as hint, so the
    Composer can hear that voice during the next ~24h."""
    _fresh_env()
    pr = _reload_runner()
    # Reload finalizer too so its module-level paths match the new env
    if "skills.synthesis_finalizer" in sys.modules:
        importlib.reload(sys.modules["skills.synthesis_finalizer"])
    import skills.synthesis_finalizer as sf

    p = pr.promote_synthesis_to_practice(
        title="Public-facing attempts at the not-yet-good",
        synthesis_title="parent synthesis", synthesis_path="",
        instrument="one attempt per day",
        archetype="Beatrice", started_at="2026-04-22",
    )
    pr.record_log_entry(
        p.slug, "Posted a half-formed Loom to #eng — exposure felt: 6/10.",
    )

    queue = sf._read_surfacing_queue()
    practice_entries = [e for e in queue if e.get("kind") == "practice_progress"]
    assert len(practice_entries) == 1, (
        f"expected one practice_progress entry, got {len(practice_entries)} "
        f"(queue has {len(queue)} total)"
    )
    e = practice_entries[0]
    assert e["archetype_hint"] == "Beatrice"
    assert e["practice_slug"] == p.slug
    assert e.get("expires_at"), "practice_progress entries must carry expires_at"


def test_practice_progress_surfacing_expires_after_24h() -> None:
    """get_ready_surfacings must filter out practice_progress entries whose
    expires_at is in the past — preventing a stale 'Beatrice has something
    to say' from leaking into next week's slots."""
    _fresh_env()
    pr = _reload_runner()
    if "skills.synthesis_finalizer" in sys.modules:
        importlib.reload(sys.modules["skills.synthesis_finalizer"])
    import skills.synthesis_finalizer as sf

    p = pr.promote_synthesis_to_practice(
        title="Test practice", synthesis_title="s", synthesis_path="",
        instrument="do", archetype="Beatrice", started_at="2026-04-22",
    )
    pr.record_log_entry(p.slug, "test attempt")

    # +5h: fresh stage ready, not expired → present
    soon = datetime.now(timezone.utc) + timedelta(hours=5)
    ready_soon = sf.get_ready_surfacings(now=soon)
    practice_progress = [r for r in ready_soon if r.get("kind") == "practice_progress"]
    assert len(practice_progress) == 1, (
        f"expected practice_progress to be ready at +5h, got {ready_soon}"
    )

    # +30h: past expires_at (24h default) → filtered out
    later = datetime.now(timezone.utc) + timedelta(hours=30)
    ready_later = sf.get_ready_surfacings(now=later)
    practice_progress_later = [
        r for r in ready_later if r.get("kind") == "practice_progress"
    ]
    assert practice_progress_later == [], (
        f"practice_progress must be expired at +30h, got {practice_progress_later}"
    )


def test_run_daily_pass_dry_run_returns_shape() -> None:
    _fresh_env()
    os.environ.pop("USE_PRACTICE_RUNNER", None)  # default off
    pr = _reload_runner()
    summary = pr.run_daily_pass()
    for key in (
        "dry_run", "active", "closed", "due_check_ins",
        "invariant_violations", "readme_refreshed",
    ):
        assert key in summary, f"summary missing {key}"
    assert summary["dry_run"] is True


if __name__ == "__main__":
    import traceback
    tests = [
        test_import_and_public_api,
        test_feature_flag_default_is_off,
        test_promote_and_load_round_trip,
        test_max_active_practices_cap_enforced,
        test_due_check_ins_day_3_fires,
        test_due_check_ins_skipped_after_recorded,
        test_compose_check_in_references_instrument,
        test_compose_check_in_day_specific_templates,
        test_close_practice_embeds_captures_made_during_practice,
        test_close_practice_writes_lived_note,
        test_invariant_closed_missing_lived_note_fires,
        test_invariant_overdue_check_in_fires,
        test_record_log_entry_appends,
        test_record_log_entry_queues_practice_progress_surfacing,
        test_practice_progress_surfacing_expires_after_24h,
        test_run_daily_pass_dry_run_returns_shape,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK] {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
            traceback.print_exc()
    print()
    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print("All practice_runner tests passed.")
