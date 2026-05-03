#!/usr/bin/env python3
"""Unit tests for skills/wisdom_dashboard.py (the /wisdom command)."""
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
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_wd_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_wd_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload():
    for mod in (
        "skills.synthesis_finalizer",
        "skills.practice_runner",
        "skills.circulation_composer",
        "skills.wisdom_dashboard",
    ):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import skills.wisdom_dashboard as wd
    return wd


def _seed_circulation_log(mem: Path, decisions: list[dict]) -> None:
    (mem / "circulation_log.json").write_text(
        json.dumps(decisions), encoding="utf-8"
    )


def _seed_contradictions_md(vault: Path, entries: list[tuple[str, str]]) -> None:
    self_dir = vault / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    body = ["# Contradictions\n"]
    for i, (title, archetype) in enumerate(entries, 1):
        body.append(
            f"### {i}. {title}\n\n"
            f"- **Pole A** — x\n- **Pole B** — y\n"
            f"- **Archetype home** — {archetype}\n"
            f"- **Status** — `active`\n"
            f"- **Last updated** — {today}\n"
        )
    (self_dir / "Contradictions.md").write_text("\n".join(body), encoding="utf-8")


# ── Tests ────────────────────────────────────────────────────────────────────


def test_dashboard_renders_with_no_data() -> None:
    """All sections should render (with empty/placeholder content) when
    nothing exists yet — no exceptions."""
    _fresh_env()
    wd = _reload()
    out = wd.render_wisdom_dashboard()
    assert "🌀" in out and "Wisdom Engine" in out
    assert "Practices" in out
    assert "Contradictions" in out
    assert "Composer" in out
    assert "Surfacings" in out
    assert "Captures" in out


def test_dashboard_shows_active_practice_with_next_check_in() -> None:
    """Active practice section names the slug, archetype, and next CHECK_IN_DAYS."""
    vault, mem = _fresh_env()
    wd = _reload()
    # Seed an active practice via practice_runner
    import skills.practice_runner as pr
    importlib.reload(pr)
    pr.promote_synthesis_to_practice(
        title="Public-facing attempts at the not-yet-good",
        synthesis_title="Some synthesis",
        synthesis_path="",
        instrument="One attempt per day.",
        archetype="Beatrice",
        started_at="2026-04-22",
    )
    # Re-import wd so it sees the seeded practice via the same env
    wd = _reload()
    out = wd.render_wisdom_dashboard(
        now=datetime(2026, 4, 25, tzinfo=timezone.utc)
    )
    assert "public-facing-attempts" in out
    assert "Beatrice" in out
    assert "day 3" in out, f"day-3 expected, got:\n{out}"
    # Next check-in is day 7 = Apr 29
    assert "day 7" in out, f"next check-in (day 7) expected, got:\n{out}"


def test_dashboard_shows_contradiction_pick_counts() -> None:
    """Contradictions section reports last-7-day composer pick counts. The
    🔥 marker fires for entries picked ≥2 times."""
    vault, mem = _fresh_env()
    _seed_contradictions_md(vault, [
        ("Hot one", "Daimon"),
        ("Lukewarm", "Psyche"),
        ("Cold", "Ariadne"),
    ])
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    _seed_circulation_log(mem, [
        # Hot one picked 3x in window
        {"id": "a", "send": True, "source_kind": "contradiction",
         "source_id": "Hot one", "archetype": "Daimon",
         "decided_at": (now - timedelta(days=1)).isoformat()},
        {"id": "b", "send": True, "source_kind": "contradiction",
         "source_id": "Hot one", "archetype": "Daimon",
         "decided_at": (now - timedelta(days=2)).isoformat()},
        {"id": "c", "send": True, "source_kind": "contradiction",
         "source_id": "Hot one", "archetype": "Daimon",
         "decided_at": (now - timedelta(days=3)).isoformat()},
        # Lukewarm picked 1x
        {"id": "d", "send": True, "source_kind": "contradiction",
         "source_id": "Lukewarm", "archetype": "Psyche",
         "decided_at": (now - timedelta(days=4)).isoformat()},
        # Cold picked 0x — and one stale entry outside the 7-day window
        {"id": "e", "send": True, "source_kind": "contradiction",
         "source_id": "Cold", "archetype": "Ariadne",
         "decided_at": (now - timedelta(days=20)).isoformat()},
    ])
    wd = _reload()
    out = wd.render_wisdom_dashboard(now=now)
    # All three titles named
    assert "Hot one" in out
    assert "Lukewarm" in out
    assert "Cold" in out
    # Pick counts in parentheses
    assert "(3)" in out, f"Hot one's count missing, got:\n{out}"
    assert "(1)" in out
    assert "(0)" in out, f"Cold's zero count missing, got:\n{out}"
    # 🔥 fires for ≥2 picks
    assert "🔥 Hot one" in out, f"🔥 marker missing, got:\n{out}"


def test_dashboard_includes_prompt_text_when_present() -> None:
    """Composer section uses prompt_text (Phase 11.2) when available, falling
    back to reason otherwise."""
    vault, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    _seed_circulation_log(mem, [{
        "id": "x",
        "send": True,
        "slot": "evening",
        "channel": "voice",
        "source_kind": "contradiction",
        "source_id": "Some tension",
        "archetype": "Beatrice",
        "score": 1.5,
        "prompt_text": "What if the tension you avoided is the one that wants to teach you?",
        "reason": "Active contradiction archetype=Beatrice score=1.50",
        "decided_at": (now - timedelta(minutes=5)).isoformat(),
    }])
    wd = _reload()
    out = wd.render_wisdom_dashboard(now=now)
    # Should include a snippet of the rendered prompt, NOT the internal reason
    assert "tension you avoided" in out, (
        f"prompt_text excerpt missing, got:\n{out}"
    )
    assert "score=1.50" not in out, "internal reason should not appear in body"


def test_dashboard_lists_recent_captures() -> None:
    """Captures section lists files in writing/Responses/ and writing/Captures/."""
    vault, mem = _fresh_env()
    # Seed a Capture and a Response file
    captures_dir = vault / "writing" / "Captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    (captures_dir / "2026-04-25-1230-test-capture.md").write_text(
        "# test\n", encoding="utf-8"
    )
    responses_dir = vault / "writing" / "Responses"
    responses_dir.mkdir(parents=True, exist_ok=True)
    (responses_dir / "2026-04-25-1240-test-response.md").write_text(
        "# test\n", encoding="utf-8"
    )
    wd = _reload()
    out = wd.render_wisdom_dashboard()
    assert "test-capture" in out
    assert "test-response" in out
    assert "[C]" in out and "[R]" in out


def test_dashboard_includes_drawings_section_when_present() -> None:
    """Phase 13.0: drawings recorded into circulation_log appear on /wisdom."""
    vault, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    decisions = [
        # Drawing in window
        {"id": "d1", "send": True, "channel": "drawing",
         "archetype": "Muse", "source_kind": "drawing_impulse",
         "source_id": "draw_001",
         "prompt_text": "dappled light through old branches",
         "decided_at": (now - timedelta(hours=4)).isoformat()},
        # Drawing in window — manual
        {"id": "d2", "send": True, "channel": "drawing",
         "archetype": "Daimon", "source_kind": "drawing_manual",
         "source_id": "draw_002",
         "prompt_text": "the quality gate that won't let you ship",
         "decided_at": (now - timedelta(hours=2)).isoformat()},
        # Drawing OUT of window — should NOT show
        {"id": "d3", "send": True, "channel": "drawing",
         "archetype": "Beatrice", "source_kind": "drawing_impulse",
         "prompt_text": "old drawing",
         "decided_at": (now - timedelta(days=20)).isoformat()},
        # Text composer decision — should NOT appear in drawings section
        {"id": "t1", "send": True, "channel": "text",
         "archetype": "Daimon", "source_kind": "contradiction",
         "decided_at": (now - timedelta(hours=1)).isoformat()},
    ]
    _seed_circulation_log(mem, decisions)
    wd = _reload()
    out = wd.render_wisdom_dashboard(now=now)
    # Section header with in-window count = 2 (out-of-window excluded
    # from the drawings section by the 7-day filter — the n=2 is the
    # canonical assertion that the window works)
    assert "Drawings (last 7d, n=2)" in out, f"got:\n{out}"
    # In-window captions present in the drawings section
    drawings_block = out.split("*Drawings")[1].split("*Surfacings")[0]
    assert "dappled light" in drawings_block
    assert "quality gate" in drawings_block
    # Out-of-window drawing's caption ('old drawing') excluded from THIS section
    assert "old drawing" not in drawings_block
    # Source-kind suffix shown (impulse/manual stripped of 'drawing_' prefix)
    assert "(impulse)" in drawings_block and "(manual)" in drawings_block


def test_dashboard_handles_missing_optional_files_gracefully() -> None:
    """Layers with no on-disk data should degrade gracefully, not crash."""
    _fresh_env()
    wd = _reload()
    out = wd.render_wisdom_dashboard()
    # Should not contain "Traceback" or "error" except inside graceful-degrade lines
    assert "Traceback" not in out


if __name__ == "__main__":
    import traceback
    tests = [
        test_dashboard_renders_with_no_data,
        test_dashboard_shows_active_practice_with_next_check_in,
        test_dashboard_shows_contradiction_pick_counts,
        test_dashboard_includes_prompt_text_when_present,
        test_dashboard_lists_recent_captures,
        # Phase 13.0 — drawings as first-class circulation events
        test_dashboard_includes_drawings_section_when_present,
        test_dashboard_handles_missing_optional_files_gracefully,
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
    print("All wisdom_dashboard tests passed.")
