#!/usr/bin/env python3
"""
Unit tests for skills/meta_synthesis.py.

Sandbox-friendly: vault paths and memory paths are rerouted to tmp dirs.
Sonnet calls are not exercised here (live API needed); the wiring
guardrail in smoke_test.py covers the import + scheduler + handler.
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


# ── Fixtures ────────────────────────────────────────────────────────────────

def _setup_vault(tmpdir: str) -> tuple[Path, Path]:
    """Create a fake vault structure under tmpdir; return (synth_dir, mem_dir)."""
    vault = Path(tmpdir) / "vault"
    synth = vault / "Alicia" / "Wisdom" / "Synthesis"
    synth.mkdir(parents=True, exist_ok=True)
    mem = Path(tmpdir) / "memory"
    mem.mkdir(parents=True, exist_ok=True)

    from myalicia.skills import meta_synthesis as ms
    ms.SYNTHESIS_DIR = synth
    ms.MEMORY_DIR = str(mem)
    ms.META_LOG_PATH = str(mem / "meta_synthesis_log.jsonl")
    return synth, mem


# ── find_synthesis_path ─────────────────────────────────────────────────────


@test("find_synthesis_path: exact filename match")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Abstraction is awareness articulate.md").write_text("# x", encoding="utf-8")
        from myalicia.skills.meta_synthesis import find_synthesis_path
        p = find_synthesis_path("Abstraction is awareness articulate")
        assert p is not None and p.name == "Abstraction is awareness articulate.md"


@test("find_synthesis_path: case-insensitive normalized match")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Quality vs Pattern.md").write_text("# x", encoding="utf-8")
        from myalicia.skills.meta_synthesis import find_synthesis_path
        p = find_synthesis_path("quality vs PATTERN")
        assert p is not None and p.name == "Quality vs Pattern.md"


@test("find_synthesis_path: returns None for non-existent")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills.meta_synthesis import find_synthesis_path
        assert find_synthesis_path("does not exist") is None


# ── log + cooldown ─────────────────────────────────────────────────────────


@test("record_meta_synthesis + recent_meta_syntheses: round-trip")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills.meta_synthesis import (
            record_meta_synthesis, recent_meta_syntheses
        )
        record_meta_synthesis("Parent A", "Child A", "/v/Child A.md", 4)
        record_meta_synthesis("Parent B", "Child B", "/v/Child B.md", 3)
        recent = recent_meta_syntheses(within_days=30)
        assert len(recent) == 2
        parents = [e["parent_title"] for e in recent]
        assert "Parent A" in parents and "Parent B" in parents


@test("has_recent_meta: detects within-window match")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills import meta_synthesis as ms
        ms.record_meta_synthesis("Parent A", "Child A", "/v/Child A.md", 4)
        recent = ms.has_recent_meta("Parent A", within_days=14)
        assert recent is not None
        assert recent["captures_at_build"] == 4
        # Different title — no match
        assert ms.has_recent_meta("Different parent", within_days=14) is None


@test("has_recent_meta: respects window")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills import meta_synthesis as ms
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(ms.META_LOG_PATH, "w") as f:
            f.write(json.dumps({
                "ts": old_ts, "parent_title": "Old Parent",
                "child_title": "Old Child", "child_path": "/v/Old.md",
                "captures_at_build": 5,
            }) + "\n")
        # Within 14d: should NOT find it
        assert ms.has_recent_meta("Old Parent", within_days=14) is None
        # Within 60d: should find it
        assert ms.has_recent_meta("Old Parent", within_days=60) is not None


# ── candidates_for_meta_synthesis ──────────────────────────────────────────


@test("candidates: no responses → no candidates")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        # Mock most_responded_syntheses to return empty
        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        rc.most_responded_syntheses = lambda n=50: []
        try:
            from myalicia.skills.meta_synthesis import candidates_for_meta_synthesis
            assert candidates_for_meta_synthesis() == []
        finally:
            rc.most_responded_syntheses = original


@test("candidates: only counts titles that exist on disk")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Real synthesis.md").write_text("# x", encoding="utf-8")

        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        rc.most_responded_syntheses = lambda n=50: [
            ("Real synthesis", 5),
            ("Phantom synthesis with no file", 4),
        ]
        try:
            from myalicia.skills.meta_synthesis import candidates_for_meta_synthesis
            cands = candidates_for_meta_synthesis()
            titles = [c["title"] for c in cands]
            assert "Real synthesis" in titles
            assert "Phantom synthesis with no file" not in titles, (
                f"phantom should be filtered out: {titles}"
            )
        finally:
            rc.most_responded_syntheses = original


@test("candidates: filters titles below min_captures")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Above threshold.md").write_text("# x", encoding="utf-8")
        (synth / "Below threshold.md").write_text("# x", encoding="utf-8")

        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        rc.most_responded_syntheses = lambda n=50: [
            ("Above threshold", 5),
            ("Below threshold", 2),
        ]
        try:
            from myalicia.skills.meta_synthesis import (
                candidates_for_meta_synthesis, MIN_CAPTURES_FOR_META,
            )
            assert MIN_CAPTURES_FOR_META == 3
            cands = candidates_for_meta_synthesis()
            titles = [c["title"] for c in cands]
            assert "Above threshold" in titles
            assert "Below threshold" not in titles
        finally:
            rc.most_responded_syntheses = original


@test("candidates: respects cooldown unless capture growth is sufficient")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Recently meta'd.md").write_text("# x", encoding="utf-8")
        (synth / "Recently meta'd grew.md").write_text("# x", encoding="utf-8")

        from myalicia.skills import meta_synthesis as ms
        # Both have a recent meta: one at count=4 (no growth), one at count=3 (growth)
        ms.record_meta_synthesis("Recently meta'd", "C1", "/v/C1.md", 4)
        ms.record_meta_synthesis("Recently meta'd grew", "C2", "/v/C2.md", 3)

        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        # New capture counts: first has only 4 (no new captures), second has 8 (5 new)
        rc.most_responded_syntheses = lambda n=50: [
            ("Recently meta'd", 4),
            ("Recently meta'd grew", 8),
        ]
        try:
            cands = ms.candidates_for_meta_synthesis()
            titles = [c["title"] for c in cands]
            # First was recently meta'd with no growth → filtered out
            assert "Recently meta'd" not in titles, (
                f"no-growth recent meta should be on cooldown: {cands}"
            )
            # Second has +5 captures since last meta → eligible
            assert "Recently meta'd grew" in titles, (
                f"meta with +5 growth should be eligible: {cands}"
            )
            # Verify delta is computed
            grew = next(c for c in cands if c["title"] == "Recently meta'd grew")
            assert grew["delta"] == 5, f"delta should be 5: {grew}"
        finally:
            rc.most_responded_syntheses = original


@test("candidates: sorts by delta descending")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        (synth / "Big growth.md").write_text("# x", encoding="utf-8")
        (synth / "Small growth.md").write_text("# x", encoding="utf-8")
        (synth / "Fresh entry.md").write_text("# x", encoding="utf-8")

        from myalicia.skills import meta_synthesis as ms
        ms.record_meta_synthesis("Big growth", "Cb", "/Cb.md", 3)
        ms.record_meta_synthesis("Small growth", "Cs", "/Cs.md", 5)

        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        rc.most_responded_syntheses = lambda n=50: [
            ("Big growth", 13),       # delta=10
            ("Small growth", 8),      # delta=3
            ("Fresh entry", 4),       # delta=4 (no prior)
        ]
        try:
            cands = ms.candidates_for_meta_synthesis()
            titles_in_order = [c["title"] for c in cands]
            # Big growth first (delta=10), then Fresh entry (delta=4), then Small growth (delta=3)
            assert titles_in_order[0] == "Big growth", (
                f"highest delta should be first: {titles_in_order}"
            )
        finally:
            rc.most_responded_syntheses = original


# ── helpers (no Sonnet call) ───────────────────────────────────────────────


@test("_sanitize_title_for_filename: strips heading + bad chars")
def _():
    from myalicia.skills.meta_synthesis import _sanitize_title_for_filename
    assert _sanitize_title_for_filename("# A Living Title.") == "A Living Title"
    assert _sanitize_title_for_filename("Title / with / slashes") == "Title — with — slashes"
    assert _sanitize_title_for_filename("  #   Padded title   ") == "Padded title"


@test("_attach_frontmatter: produces valid YAML header")
def _():
    from myalicia.skills.meta_synthesis import _attach_frontmatter
    body = "# child title\n\nsome body"
    out = _attach_frontmatter(
        body, parent_title="Parent X", parent_path=Path("Parent X.md"),
        capture_count=4,
    )
    assert out.startswith("---\n")
    assert "kind: meta_synthesis" in out
    assert 'parent_synthesis: "Parent X"' in out
    assert "captures_at_build: 4" in out
    # Body comes after frontmatter
    assert "# child title" in out


# ── run_meta_synthesis_pass: precondition gates ───────────────────────────


@test(f"Phase 13.9 bridge: appends to {USER_NAME}-model when extractor returns valid learnings")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        # Reroute user_model storage to tmp too
        from myalicia.skills import user_model as hm
        baselines_dir = Path(td) / "baselines"
        baselines_dir.mkdir()
        # NOTE: user_model uses LEARNINGS_LOG (not LEARNINGS_PATH).
        # Reroute MEMORY_DIR too so the .mkdir() inside append_learning
        # doesn't try to create the production memory dir.
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "user_learnings.jsonl"
        hm.BASELINES_DIR = baselines_dir

        # Stub the Sonnet extractor to return controlled learnings
        from myalicia.skills import meta_synthesis as ms
        original = ms._extract_learnings_from_meta
        ms._extract_learnings_from_meta = lambda body, parent_title: [
            {"dimension": "knowledge",
             "claim": f"{USER_NAME} returns to McGilchrist when thinking about hemispheric balance",
             "confidence": 0.85},
            {"dimension": "voice",
             "claim": f"{USER_NAME} consistently writes about the boundary between intellect and presence",
             "confidence": 0.7},
        ]
        try:
            n = ms.bridge_meta_to_hector_model(
                body="Some meta-synthesis body text",
                parent_title="Parent title",
                child_title="Child title",
            )
            assert n == 2, f"expected 2 learnings appended, got {n}"
            # Verify they actually landed in the log
            entries = list(hm.get_learnings())
            assert len(entries) == 2
            dims = {e["dimension"] for e in entries}
            assert "knowledge" in dims and "voice" in dims
            # Source tag must encode meta_synthesis provenance
            for e in entries:
                assert e["source"].startswith("meta_synthesis:"), (
                    f"source must encode bridge origin: {e['source']!r}"
                )
                assert "Parent title" in e["source"]
                # Evidence captures the child title for backtracking
                assert e.get("evidence") == "Child title"
        finally:
            ms._extract_learnings_from_meta = original


@test("Phase 13.9 bridge: returns 0 when extractor returns empty list (no spam)")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills import meta_synthesis as ms
        original = ms._extract_learnings_from_meta
        ms._extract_learnings_from_meta = lambda body, parent_title: []
        try:
            n = ms.bridge_meta_to_hector_model(
                body="x", parent_title="p", child_title="c",
            )
            assert n == 0
        finally:
            ms._extract_learnings_from_meta = original


@test("Phase 13.9 bridge: filters unknown dimensions silently")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills import user_model as hm
        baselines_dir = Path(td) / "baselines"
        baselines_dir.mkdir()
        # NOTE: user_model uses LEARNINGS_LOG (not LEARNINGS_PATH).
        # Reroute MEMORY_DIR too so the .mkdir() inside append_learning
        # doesn't try to create the production memory dir.
        hm.MEMORY_DIR = Path(td)
        hm.LEARNINGS_LOG = Path(td) / "user_learnings.jsonl"
        hm.BASELINES_DIR = baselines_dir

        from myalicia.skills import meta_synthesis as ms
        original = ms._extract_learnings_from_meta
        ms._extract_learnings_from_meta = lambda body, parent_title: [
            {"dimension": "fictional_dimension", "claim": "x", "confidence": 0.7},
            {"dimension": "body", "claim": f"{USER_NAME} walked yesterday", "confidence": 0.8},
        ]
        try:
            n = ms.bridge_meta_to_hector_model(
                body="x", parent_title="p", child_title="c",
            )
            assert n == 1, f"unknown dim must be filtered, expected 1: got {n}"
            entries = list(hm.get_learnings())
            assert len(entries) == 1
            assert entries[0]["dimension"] == "body"
        finally:
            ms._extract_learnings_from_meta = original


@test("Phase 13.9 bridge: empty body → 0, no crash")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        from myalicia.skills.meta_synthesis import bridge_meta_to_hector_model
        assert bridge_meta_to_hector_model(body="", parent_title="p", child_title="c") == 0
        assert bridge_meta_to_hector_model(body=None, parent_title="p", child_title="c") == 0


@test("Phase 13.10 get_synthesis_level: plain synthesis returns 0")
def _():
    from myalicia.skills.meta_synthesis import get_synthesis_level
    plain = "# Just a regular synthesis\n\nBody text here.\n"
    assert get_synthesis_level(plain) == 0
    assert get_synthesis_level("") == 0
    assert get_synthesis_level("no frontmatter at all\nBody.") == 0


@test("Phase 13.10 get_synthesis_level: reads explicit level field from frontmatter")
def _():
    from myalicia.skills.meta_synthesis import get_synthesis_level
    text = (
        "---\n"
        "kind: meta_meta_synthesis\n"
        "level: 2\n"
        "parent_synthesis: \"some parent\"\n"
        "---\n\n"
        "# Body\n"
    )
    assert get_synthesis_level(text) == 2

    text3 = (
        "---\n"
        "kind: meta_meta_meta_synthesis\n"
        "level: 3\n"
        "---\n\n"
        "body"
    )
    assert get_synthesis_level(text3) == 3


@test("Phase 13.10 get_synthesis_level: backwards-compat — kind: meta_synthesis without level → 1")
def _():
    from myalicia.skills.meta_synthesis import get_synthesis_level
    pre_13_10 = (
        "---\n"
        "kind: meta_synthesis\n"
        "parent_synthesis: \"x\"\n"
        "captures_at_build: 4\n"
        "---\n\n"
        "Body"
    )
    assert get_synthesis_level(pre_13_10) == 1, (
        "pre-13.10 metas (no level field) must report level 1 for back-compat"
    )


@test("Phase 13.10 _attach_frontmatter: emits correct kind + level for each level")
def _():
    from myalicia.skills.meta_synthesis import _attach_frontmatter
    for lvl, expected_kind in [
        (1, "meta_synthesis"),
        (2, "meta_meta_synthesis"),
        (3, "meta_meta_meta_synthesis"),
    ]:
        out = _attach_frontmatter(
            "# title\nbody",
            parent_title="P", parent_path=Path("P.md"),
            capture_count=4, level=lvl,
        )
        assert f"kind: {expected_kind}" in out, (
            f"level {lvl} should emit kind: {expected_kind}, got:\n{out[:200]}"
        )
        assert f"level: {lvl}" in out, (
            f"level field missing for level {lvl}: {out[:200]}"
        )


@test("Phase 13.10 build_meta_synthesis: refuses to build above MAX_META_LEVEL")
def _():
    with tempfile.TemporaryDirectory() as td:
        synth, _ = _setup_vault(td)
        # Plant a level-3 meta-synthesis as parent — building from it would
        # produce level 4 which exceeds MAX_META_LEVEL=3
        parent_text = (
            "---\n"
            "kind: meta_meta_meta_synthesis\n"
            "level: 3\n"
            "parent_synthesis: \"some grandparent\"\n"
            "captures_at_build: 4\n"
            "---\n\n"
            "# Already at the cap\n\nBody"
        )
        (synth / "Already at the cap.md").write_text(parent_text, encoding="utf-8")

        # Stub out get_responses_for_synthesis to return enough captures
        # so the level-cap is the ONLY thing that should block the build
        import myalicia.skills.response_capture as rc
        original = rc.get_responses_for_synthesis
        rc.get_responses_for_synthesis = lambda title, max_recent=999: [
            {"path": Path("/dev/null"), "captured_at": "2026-04-26",
             "channel": "text", "body_excerpt": "x"}
        ] * 5
        try:
            from myalicia.skills.meta_synthesis import build_meta_synthesis, MAX_META_LEVEL
            assert MAX_META_LEVEL == 3
            result = build_meta_synthesis("Already at the cap")
            assert result is None, (
                f"build_meta_synthesis should refuse level-4 builds, got {result}"
            )
        finally:
            rc.get_responses_for_synthesis = original


@test("Phase 13.10 round-trip: written meta is readable as level 1, level-2 builds atop it")
def _():
    """Integration: emit a level-1 frontmatter, then read it back and
    confirm get_synthesis_level returns 1. The next build atop it would
    therefore correctly land at level 2."""
    from myalicia.skills.meta_synthesis import _attach_frontmatter, get_synthesis_level
    md = _attach_frontmatter(
        "# Level-1 child\n\nbody",
        parent_title="P", parent_path=Path("P.md"),
        capture_count=3, level=1,
    )
    assert get_synthesis_level(md) == 1
    # Then a level-2 build atop it
    md2 = _attach_frontmatter(
        "# Level-2 child\n\nbody",
        parent_title="Level-1 child", parent_path=Path("Level-1 child.md"),
        capture_count=3, level=2,
    )
    assert get_synthesis_level(md2) == 2


@test("run_meta_synthesis_pass: empty candidates → no_eligible_candidates")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_vault(td)
        import myalicia.skills.response_capture as rc
        original = rc.most_responded_syntheses
        rc.most_responded_syntheses = lambda n=50: []
        try:
            from myalicia.skills.meta_synthesis import run_meta_synthesis_pass
            r = run_meta_synthesis_pass()
            assert r["built"] is False
            assert r["reason"] == "no_eligible_candidates"
            assert r["candidate"] is None
            assert r["candidate_count"] == 0
        finally:
            rc.most_responded_syntheses = original


if __name__ == "__main__":
    print("Testing meta_synthesis.py …")
    sys.exit(_run_all())
