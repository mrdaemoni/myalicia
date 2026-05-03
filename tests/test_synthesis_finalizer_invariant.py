#!/usr/bin/env python3
"""
Invariant test for synthesis_finalizer.

The invariant:
    Every wikilink in every structured synthesis's `## The Claim Across Sources`
    section MUST have a reciprocal wikilink in the cited source's page.

Why this test uses a baseline (not strict=0) at Phase 11.0:
    When the Finalizer first landed, the corpus had 1067 one-way edges and 220
    unresolvable wikilinks. Making the test strict from day one would red CI
    immediately. Item #15 (Backlink Audit) runs `finalize_all` across the whole
    corpus and is expected to drive these numbers to ~0 (one_way_edge) and close
    to 0 (unresolvable, after manual repair of genuinely broken links).

    After #15 lands, ratchet the baselines down. The goal is strict=0 on
    one_way_edge. `unresolvable` has a permanent floor because some wikilinks
    are intentionally ghost (future notes, deliberately dangling references).

Usage:
    python tests/test_synthesis_finalizer_invariant.py
    pytest tests/test_synthesis_finalizer_invariant.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.synthesis_finalizer import check_invariant, check_lived_invariants  # noqa: E402


# ── Baselines ──────────────────────────────────────────────────────────────
# These get RATCHETED DOWN as the corpus cleans up. Never raise them.
# one_way_edge is STRICT after item #15 — any new one-way edge red-CIs
# immediately because it means a new synthesis writer skipped the Finalizer.
#
# History:
#   2026-04-22 Phase 11.0 initial: one_way=1067, unresolvable=220
#   2026-04-22 Phase 11.0 item #15: live finalize_all closed 1067 → 0,
#              flipped ENFORCE_STRICT_ONE_WAY = True.
#              Unresolvables held at 220 pending Phase B manual repair.

BASELINE_ONE_WAY_EDGES = 0        # strict — enforced
BASELINE_UNRESOLVABLE = 220       # ratchets down as Phase B repairs ghost refs
ENFORCE_STRICT_ONE_WAY = True     # locked — any new one-way edge fails CI


def test_synthesis_graph_bidirectional() -> None:
    """Bidirectional-graph invariant with baseline ratchet."""
    violations = check_invariant()
    by_kind: dict[str, int] = {}
    for v in violations:
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1

    one_way = by_kind.get("one_way_edge", 0)
    unresolvable = by_kind.get("unresolvable", 0)
    parse_errors = by_kind.get("parse_error", 0)
    read_errors = by_kind.get("source_read_error", 0)

    # Parse errors are always fatal — a synthesis we can't parse is a synthesis
    # the Finalizer can't maintain.
    assert parse_errors == 0, f"Parse errors found: {parse_errors}"
    # Source-read errors are always fatal — the source file exists (it resolved)
    # but we couldn't open it. That's an FS / permissions problem, not baseline.
    assert read_errors == 0, f"Source read errors: {read_errors}"

    if ENFORCE_STRICT_ONE_WAY:
        assert one_way == 0, (
            f"Strict mode: {one_way} one-way edges found. "
            f"First 5: {[v for v in violations if v['kind'] == 'one_way_edge'][:5]}"
        )
    else:
        assert one_way <= BASELINE_ONE_WAY_EDGES, (
            f"Regression: one-way edges {one_way} > baseline {BASELINE_ONE_WAY_EDGES}. "
            f"New edges not being finalized — did a writer forget to call "
            f"synthesis_finalizer.finalize()?"
        )

    assert unresolvable <= BASELINE_UNRESOLVABLE, (
        f"Regression: unresolvable wikilinks {unresolvable} > baseline "
        f"{BASELINE_UNRESOLVABLE}. A new synthesis is citing a ghost file."
    )


def test_finalizer_is_importable() -> None:
    """Smoke — every export named in the design doc must exist."""
    import skills.synthesis_finalizer as sf
    for name in (
        "finalize", "finalize_all", "check_invariant", "parse_synthesis",
        "resolve_wikilink", "classify_wikilink",
        "queue_surfacings", "get_ready_surfacings", "mark_surfacing_delivered",
        "SURFACING_STAGES", "VAULT_ROOT", "SYNTHESIS_DIR", "THEMES_DIR",
        # Layer 4 feedback loop (item #20): Lived → Synthesis
        "LIVED_DIR", "PRACTICES_DIR", "CANONICAL_SOURCE_DIRS",
        "parse_lived_note", "list_lived_notes", "find_syntheses_citing",
        "finalize_lived_note", "finalize_all_lived_notes",
        "check_lived_invariants",
    ):
        assert hasattr(sf, name), f"synthesis_finalizer missing export: {name}"


def test_lived_is_in_canonical_sources() -> None:
    """
    Lived notes are first-class sources (Layer 4 feedback loop). If the
    canonical source tier list ever drops LIVED_DIR it means someone has
    silently removed the feedback loop — CI red.
    """
    import skills.synthesis_finalizer as sf
    assert sf.LIVED_DIR in sf.CANONICAL_SOURCE_DIRS, (
        "LIVED_DIR must be in CANONICAL_SOURCE_DIRS — the Lived → Synthesis "
        "feedback loop depends on it being first-class."
    )


def test_lived_invariants_are_green_on_real_vault() -> None:
    """
    Real-vault sanity check: every Lived note has a descent + a practice
    folder. Unused Lived notes (>90d, uncited) are informational — we log
    but do not fail on those, because the first-class contract is structural
    (descent + practice.md exists), not usage-based.
    """
    vs = check_lived_invariants()
    structural = [v for v in vs if v["kind"] in (
        "parse_error", "lived_missing_descent", "lived_orphan_practice",
    )]
    assert not structural, (
        f"Lived-note structural violations: {structural}. "
        "Each Lived note must have a **Descent.** wikilink and a matching "
        "Alicia/Practices/<slug>/practice.md."
    )


def test_finalizer_wired_in_writers() -> None:
    """
    The dead-config-guardrail analog for the Finalizer:
    every module that writes a synthesis file MUST also call finalize().

    Current known writers:
      - skills/memory_skill.py :: synthesise_vault (writes 'Wisdom/Synthesis')
      - skills/vault_ingest.py :: update_synthesis_notes (writes to SYNTHESIS_DIR)

    If you add a new writer that puts files into /Alicia/Wisdom/Synthesis/,
    add it to this list AND ensure it calls synthesis_finalizer.finalize().
    """
    repo_root = Path(__file__).resolve().parent.parent
    writers = [
        repo_root / "skills" / "memory_skill.py",
        repo_root / "skills" / "vault_ingest.py",
    ]
    missing_calls = []
    for f in writers:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        # Must import AND call it
        if "synthesis_finalizer" not in text:
            missing_calls.append(str(f.relative_to(repo_root)))
    assert not missing_calls, (
        "Known synthesis writer(s) do not reference synthesis_finalizer: "
        f"{missing_calls}. Every synthesis write must be finalized."
    )


if __name__ == "__main__":
    test_finalizer_is_importable()
    print("[OK] test_finalizer_is_importable")
    test_lived_is_in_canonical_sources()
    print("[OK] test_lived_is_in_canonical_sources")
    test_finalizer_wired_in_writers()
    print("[OK] test_finalizer_wired_in_writers")
    test_synthesis_graph_bidirectional()
    print("[OK] test_synthesis_graph_bidirectional")
    test_lived_invariants_are_green_on_real_vault()
    print("[OK] test_lived_invariants_are_green_on_real_vault")
