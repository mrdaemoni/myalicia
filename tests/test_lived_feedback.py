#!/usr/bin/env python3
"""
Unit tests for the Lived → Synthesis feedback loop (item #20).

A Lived note is emitted by skills.practice_runner.close_practice and should
receive the same circulation parity as a newly-finalized synthesis:
  - Bridge TSV row
  - Weekly-digest paragraph under 'New Lived notes this week'
  - 5-stage surfacing queue entry with kind=lived + archetype_hint
  - Discoverable by list_lived_notes()
  - find_syntheses_citing() resolves syntheses that cite the Lived note
  - check_lived_invariants() flags orphans / missing-descent / unused

Every test points ALICIA_VAULT_ROOT / ALICIA_MEMORY_DIR at fresh tmp dirs
so the real vault is never touched.

Usage:
    python tests/test_lived_feedback.py
    pytest tests/test_lived_feedback.py -v
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
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_lived_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_lived_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload():
    for mod in ("skills.synthesis_finalizer", "skills.practice_runner"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import myalicia.skills.synthesis_finalizer as sf
    import myalicia.skills.practice_runner as pr
    return sf, pr


# ── Tests ──────────────────────────────────────────────────────────────────


def test_finalizer_exports_lived_feedback_api() -> None:
    _fresh_env()
    sf, _ = _reload()
    for name in (
        "LIVED_DIR",
        "PRACTICES_DIR",
        "CANONICAL_SOURCE_DIRS",
        "LIVED_UNUSED_DAYS",
        "parse_lived_note",
        "list_lived_notes",
        "find_syntheses_citing",
        "finalize_lived_note",
        "finalize_all_lived_notes",
        "check_lived_invariants",
    ):
        assert hasattr(sf, name), f"synthesis_finalizer missing export: {name}"


def test_canonical_source_dirs_includes_lived() -> None:
    _fresh_env()
    sf, _ = _reload()
    # Lived/ is a first-class source tier — must be in the canonical set.
    assert sf.LIVED_DIR in sf.CANONICAL_SOURCE_DIRS
    # And so must the Synthesis directory.
    assert sf.SYNTHESIS_DIR in sf.CANONICAL_SOURCE_DIRS


def test_parse_lived_note_extracts_metadata() -> None:
    vault, _ = _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    p = sf.LIVED_DIR / "test-practice.md"
    p.write_text(
        "# Test practice\n\n"
        "*Lived note — emitted 2026-04-22 from 30-day practice.*\n\n"
        "**Descent.** [[A great synthesis]]\n"
        "**Archetype home.** Beatrice\n"
        "**Duration.** 2026-04-22 → 2026-05-22\n\n"
        "## What the body learned\n\n"
        "The learning lived in the hand before the tongue.\n",
        encoding="utf-8",
    )
    info = sf.parse_lived_note(p)
    assert info["title"] == "Test practice"
    assert info["slug"] == "test-practice"
    assert info["emitted_at"] == "2026-04-22"
    assert info["descent_synthesis_title"] == "A great synthesis"
    assert info["archetype"] == "Beatrice"


def test_list_lived_notes_finds_everything() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (sf.LIVED_DIR / f"p{i}.md").write_text(
            f"# Practice {i}\n\n*Lived note — emitted <earlier development>*\n\n"
            f"**Descent.** [[Syn {i}]]\n**Archetype home.** Beatrice\n",
            encoding="utf-8",
        )
    rows = sf.list_lived_notes()
    assert len(rows) == 3
    slugs = sorted(r["slug"] for r in rows)
    assert slugs == ["p0", "p1", "p2"]


def test_finalize_lived_note_queues_surfacing() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    lived_path = sf.LIVED_DIR / "my-practice.md"
    lived_path.write_text(
        "# Practice title\n\n*Lived note — emitted <earlier development>*\n\n"
        "**Descent.** [[My synthesis]]\n**Archetype home.** Beatrice\n",
        encoding="utf-8",
    )
    r = sf.finalize_lived_note(lived_path)
    assert r["status"] == "finalized"
    assert r["surfacing_id"], "finalize_lived_note must queue a surfacing"
    # The queue entry must carry kind=lived + archetype_hint
    queue = json.loads(sf.SURFACING_QUEUE_FILE.read_text(encoding="utf-8"))
    entry = next(e for e in queue if e["id"] == r["surfacing_id"])
    assert entry["kind"] == "lived"
    assert entry["archetype_hint"] == "Beatrice"
    assert entry["synthesis_title"] == "Practice title"
    # Stages present and in the right shape
    names = [s["name"] for s in entry["stages"]]
    assert names == ["fresh", "next_day", "three_days", "one_week", "three_weeks"]


def test_finalize_lived_note_bridge_log_and_digest() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    lived_path = sf.LIVED_DIR / "my-practice.md"
    lived_path.write_text(
        "# Public-facing attempts\n\n*Lived note — emitted <earlier development>*\n\n"
        "**Descent.** [[Every real learning]]\n**Archetype home.** Beatrice\n",
        encoding="utf-8",
    )
    r = sf.finalize_lived_note(lived_path)
    assert r["bridge_log"] in ("appended", "dry_run")
    assert r["digest"] in ("created", "appended", "dry_run")
    # Bridge TSV row should be tagged lived:
    assert sf.SYNTHESIS_LOG.exists()
    assert "lived:Public-facing attempts" in sf.SYNTHESIS_LOG.read_text(encoding="utf-8")
    # Weekly digest should have the "New Lived notes this week" section
    week_path = sf._week_digest_path()
    assert week_path.exists()
    assert "## New Lived notes this week" in week_path.read_text(encoding="utf-8")


def test_get_ready_surfacings_carries_kind_and_hint() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    lived_path = sf.LIVED_DIR / "my-practice.md"
    lived_path.write_text(
        "# Practice title\n\n*Lived note — emitted <earlier development>*\n\n"
        "**Descent.** [[Syn]]\n**Archetype home.** Psyche\n",
        encoding="utf-8",
    )
    sf.finalize_lived_note(lived_path)
    # Push "now" forward 5h so the "fresh" (+4h) stage is ready
    later = datetime.now(timezone.utc) + timedelta(hours=5)
    ready = sf.get_ready_surfacings(now=later)
    assert ready, "should have at least one ready surfacing"
    fresh = next(r for r in ready if r["stage_name"] == "fresh")
    assert fresh["kind"] == "lived"
    assert fresh["archetype_hint"] == "Psyche"


def test_close_practice_feeds_finalizer() -> None:
    """
    End-to-end: promote → close → verify the Lived note gets finalized.
    """
    _fresh_env()
    sf, pr = _reload()
    practice = pr.promote_synthesis_to_practice(
        title="Test practice",
        synthesis_title="A great synthesis",
        synthesis_path="Alicia/Wisdom/Synthesis/A great synthesis.md",
        instrument="Do the thing every day for 30 days.",
        archetype="Beatrice",
        started_at="2026-04-22",
    )
    lived_path = pr.close_practice(
        practice.slug,
        lived_note_text="The body learned before the mind could name it.",
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    assert lived_path.exists()
    # Finalizer side-effects must have fired:
    # - Bridge TSV now has a lived: row
    assert sf.SYNTHESIS_LOG.exists()
    assert "lived:" in sf.SYNTHESIS_LOG.read_text(encoding="utf-8")
    # - Surfacing queue has a kind=lived entry
    queue = json.loads(sf.SURFACING_QUEUE_FILE.read_text(encoding="utf-8"))
    lived_entries = [e for e in queue if e.get("kind") == "lived"]
    assert lived_entries, "close_practice must queue a lived surfacing"
    assert lived_entries[0]["archetype_hint"] == "Beatrice"


def test_find_syntheses_citing_matches_by_basename() -> None:
    vault, _ = _fresh_env()
    sf, _ = _reload()
    sf.SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)
    # A structured synthesis that cites a Lived note by its title
    syn = sf.SYNTHESIS_DIR / "The body teaches what the mind can only point to.md"
    syn.write_text(
        "---\ntags: [synthesis]\n---\n\n"
        "# The body teaches what the mind can only point to\n\n"
        "## The Claim Across Sources\n\n"
        "**Lived note** — [[Public-facing attempts]]\n\n"
        "**Waitzkin** — [[Books/X/1]]\n\n"
        "## The Synthesis\n\nThings happen.\n",
        encoding="utf-8",
    )
    hits = sf.find_syntheses_citing("Public-facing attempts")
    assert len(hits) == 1
    assert hits[0].name == syn.name


def test_check_lived_invariants_flags_missing_descent() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    (sf.LIVED_DIR / "sketchy.md").write_text(
        "# Sketchy practice\n\n*Lived note — emitted <earlier development>*\n\n"
        "**Archetype home.** Beatrice\n\nNo descent link.\n",
        encoding="utf-8",
    )
    vs = sf.check_lived_invariants()
    kinds = [v["kind"] for v in vs]
    assert "lived_missing_descent" in kinds, vs


def test_check_lived_invariants_flags_orphan_practice() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    # A Lived note exists but no matching practice folder does
    (sf.LIVED_DIR / "ghost.md").write_text(
        "# Ghost\n\n*Lived note — emitted <earlier development>*\n\n"
        "**Descent.** [[Something]]\n**Archetype home.** Beatrice\n",
        encoding="utf-8",
    )
    vs = sf.check_lived_invariants()
    kinds = [v["kind"] for v in vs]
    assert "lived_orphan_practice" in kinds, vs


def test_check_lived_invariants_flags_unused() -> None:
    _fresh_env()
    sf, _ = _reload()
    sf.LIVED_DIR.mkdir(parents=True, exist_ok=True)
    sf.PRACTICES_DIR.mkdir(parents=True, exist_ok=True)
    # Matching practice folder exists (so orphan_practice doesn't fire)
    (sf.PRACTICES_DIR / "ancient").mkdir(parents=True, exist_ok=True)
    (sf.PRACTICES_DIR / "ancient" / "practice.md").write_text(
        "---\nslug: ancient\ntitle: Ancient\nstatus: closed\n---\n",
        encoding="utf-8",
    )
    # Lived note emitted well over LIVED_UNUSED_DAYS ago
    old = datetime.now(timezone.utc) - timedelta(days=sf.LIVED_UNUSED_DAYS + 10)
    (sf.LIVED_DIR / "ancient.md").write_text(
        f"# Ancient\n\n*Lived note — emitted {old.strftime('%Y-%m-%d')}*\n\n"
        "**Descent.** [[Missing synthesis]]\n**Archetype home.** Beatrice\n",
        encoding="utf-8",
    )
    vs = sf.check_lived_invariants()
    kinds = [v["kind"] for v in vs]
    assert "lived_unused" in kinds, vs


def test_practice_runner_export_hook() -> None:
    """Guardrail: practice_runner must import the finalizer hook."""
    import myalicia.skills.practice_runner as pr
    src = Path(pr.__file__).read_text(encoding="utf-8")
    assert "from skills.synthesis_finalizer import finalize_lived_note" in src, (
        "close_practice must call finalize_lived_note (Lived → Synthesis feedback)"
    )


if __name__ == "__main__":
    import traceback
    tests = [
        test_finalizer_exports_lived_feedback_api,
        test_canonical_source_dirs_includes_lived,
        test_parse_lived_note_extracts_metadata,
        test_list_lived_notes_finds_everything,
        test_finalize_lived_note_queues_surfacing,
        test_finalize_lived_note_bridge_log_and_digest,
        test_get_ready_surfacings_carries_kind_and_hint,
        test_close_practice_feeds_finalizer,
        test_find_syntheses_citing_matches_by_basename,
        test_check_lived_invariants_flags_missing_descent,
        test_check_lived_invariants_flags_orphan_practice,
        test_check_lived_invariants_flags_unused,
        test_practice_runner_export_hook,
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
    print("All Lived → Synthesis feedback tests passed.")
