#!/usr/bin/env python3
"""Unit tests for skills/user_model.py — Phase 12.0 foundation."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_env() -> tuple[Path, Path]:
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_hm_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_hm_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _seed_memory_files(mem: Path) -> None:
    """Seed the memory files that init_baseline copies."""
    (mem / "MEMORY.md").write_text(
        "# MEMORY.md\n\nDesign leader. Quality, mastery, stoic.\n",
        encoding="utf-8",
    )
    (mem / "patterns.md").write_text(
        "# Patterns\n\nReturns to the same questions.\n",
        encoding="utf-8",
    )
    (mem / "insights.md").write_text(
        "# Insights\n\nOften reaches for paradox.\n",
        encoding="utf-8",
    )
    (mem / "preferences.md").write_text(
        "# Preferences\n\nDeep work. Voice notes.\n",
        encoding="utf-8",
    )
    (mem / "concepts.md").write_text(
        "# Concepts\n\nQuality. Practice vs ritual.\n",
        encoding="utf-8",
    )


def _reload():
    if "skills.user_model" in sys.modules:
        importlib.reload(sys.modules["skills.user_model"])
    import myalicia.skills.user_model as hm
    return hm


# ── Tests ────────────────────────────────────────────────────────────────────


def test_module_exports() -> None:
    _fresh_env()
    hm = _reload()
    for name in (
        "init_baseline", "get_active_baseline", "append_learning",
        "get_learnings", "DIMENSIONS", "compute_dimension_counts",
        "find_thin_dimensions", "find_dimensions_movement",
        "days_since_baseline", "render_becoming_dashboard",
        "BASELINE_SOURCES",
    ):
        assert hasattr(hm, name), f"user_model must export {name}"


def test_init_baseline_creates_snapshot_with_all_sources() -> None:
    """init_baseline copies every memory source file into one combined doc."""
    vault, mem = _fresh_env()
    _seed_memory_files(mem)
    hm = _reload()
    p = hm.init_baseline(now=datetime(2026, 4, 25, tzinfo=timezone.utc))
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    # Every source's content should appear
    assert "Design leader" in text  # MEMORY.md
    assert "Returns to the same questions" in text  # patterns.md
    assert "reaches for paradox" in text  # insights.md
    assert "Deep work" in text  # preferences.md
    assert "Quality. Practice vs ritual" in text  # concepts.md
    # Header includes the date
    assert "2026-04-25" in text


def test_init_baseline_rejects_same_day_without_label() -> None:
    """Two baselines on the same date without a distinguishing label is an
    error — Phase 12 treats baselines as foundational moments, not refreshes."""
    vault, mem = _fresh_env()
    _seed_memory_files(mem)
    hm = _reload()
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    hm.init_baseline(now=now)
    try:
        hm.init_baseline(now=now)
        assert False, "expected RuntimeError on same-day re-init"
    except RuntimeError:
        pass
    # With a label, second baseline same day succeeds
    p2 = hm.init_baseline(label="phase12-revision", now=now)
    assert "phase12-revision" in p2.name


def test_get_active_baseline_returns_most_recent() -> None:
    vault, mem = _fresh_env()
    _seed_memory_files(mem)
    hm = _reload()
    hm.init_baseline(now=datetime(2026, 4, 22, tzinfo=timezone.utc))
    hm.init_baseline(now=datetime(2026, 4, 25, tzinfo=timezone.utc))
    p = hm.get_active_baseline()
    assert p is not None
    assert "2026-04-25" in p.name


def test_days_since_baseline() -> None:
    vault, mem = _fresh_env()
    _seed_memory_files(mem)
    hm = _reload()
    hm.init_baseline(now=datetime(2026, 4, 22, tzinfo=timezone.utc))
    days = hm.days_since_baseline(
        now=datetime(2026, 4, 27, tzinfo=timezone.utc)
    )
    assert days == 5


def test_append_learning_writes_jsonl_entry() -> None:
    _fresh_env()
    hm = _reload()
    entry = hm.append_learning(
        f"{USER_NAME} prefers evening practice to morning practice",
        dimension="practice",
        confidence=0.85,
        source="memory_skill",
        evidence="said so on Apr 22",
    )
    assert entry["dimension"] == "practice"
    assert entry["confidence"] == 0.85
    assert entry["source"] == "memory_skill"
    # Persisted to disk
    log_path = Path(os.environ["ALICIA_MEMORY_DIR"]) / "user_learnings.jsonl"
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["claim"].startswith(f"{USER_NAME} prefers")


def test_append_learning_validates_dimension() -> None:
    _fresh_env()
    hm = _reload()
    try:
        hm.append_learning("any claim", dimension="not-a-dimension")
        assert False, "expected ValueError for unknown dimension"
    except ValueError:
        pass


def test_append_learning_validates_empty_claim() -> None:
    _fresh_env()
    hm = _reload()
    for empty in ("", "   ", "\n"):
        try:
            hm.append_learning(empty, dimension="practice")
            assert False, "expected ValueError for empty claim"
        except ValueError:
            pass


def test_append_learning_clamps_confidence() -> None:
    _fresh_env()
    hm = _reload()
    e_high = hm.append_learning("x", dimension="practice", confidence=2.5)
    assert e_high["confidence"] == 1.0
    e_low = hm.append_learning("y", dimension="practice", confidence=-0.5)
    assert e_low["confidence"] == 0.0


def test_get_learnings_filters_by_dimension_and_window() -> None:
    _fresh_env()
    hm = _reload()
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    hm.append_learning("p1", dimension="practice", now=now - timedelta(days=2))
    hm.append_learning("k1", dimension="knowledge", now=now - timedelta(days=2))
    hm.append_learning("p2 stale", dimension="practice",
                       now=now - timedelta(days=30))

    # All
    assert len(hm.get_learnings(now=now)) == 3
    # By dimension
    assert len(hm.get_learnings(dimension="practice", now=now)) == 2
    # By window — last 7 days excludes the 30-day-old
    recent = hm.get_learnings(since_days=7, now=now)
    assert len(recent) == 2
    assert all("stale" not in (e.get("claim") or "") for e in recent)
    # Newest first
    assert recent[0]["ts"] >= recent[-1]["ts"]


def test_compute_dimension_counts_returns_all_dimensions() -> None:
    _fresh_env()
    hm = _reload()
    hm.append_learning("x", dimension="practice")
    hm.append_learning("y", dimension="practice")
    hm.append_learning("z", dimension="knowledge")
    counts = hm.compute_dimension_counts()
    # Every canonical dimension is in the result, even unused ones
    for d in hm.DIMENSIONS:
        assert d in counts
    assert counts["practice"] == 2
    assert counts["knowledge"] == 1
    assert counts["body"] == 0


def test_find_thin_dimensions_lists_zero_recent() -> None:
    _fresh_env()
    hm = _reload()
    now = datetime(2026, 4, 25, tzinfo=timezone.utc)
    # Recent learning on practice + knowledge
    hm.append_learning("recent practice", dimension="practice",
                       now=now - timedelta(days=2))
    hm.append_learning("recent knowledge", dimension="knowledge",
                       now=now - timedelta(days=5))
    # Stale learning on body (outside window)
    hm.append_learning("stale body", dimension="body",
                       now=now - timedelta(days=30))
    thin = hm.find_thin_dimensions(stale_after_days=14, now=now)
    # practice + knowledge are NOT thin
    assert "practice" not in thin
    assert "knowledge" not in thin
    # body IS thin (no recent learning despite an old one)
    assert "body" in thin
    # Other untouched dimensions also thin
    assert "wealth" in thin


def test_classify_dimension_keyword_routing() -> None:
    """Phase 12.1 — keyword classifier routes extractions to dimensions.
    Coverage of every dimension's keyword set with a representative phrase."""
    _fresh_env()
    hm = _reload()
    cases = [
        # (phrase, expected_dimension)
        ("I had a great workout this morning",                 "body"),
        ("Need to think about my 401k allocation",             "wealth"),
        ("Conversation with my wife about parenting",          "relationships"),
        ("Sprint review with my design team at work",        "work"),
        ("Drafted a new essay about quality",                  "voice"),
        ("Did some art making this evening",                   "creative"),
        ("Returning to the same morning ritual",               "practice"),
        ("Notice I keep avoiding this conversation",           "shadow"),
        ("Reading more McGilchrist on hemispheric balance",    "knowledge"),
        # Default: nothing matches → identity
        ("Today I made a clear choice",                        "identity"),
    ]
    for phrase, expected in cases:
        got = hm.classify_dimension(phrase)
        assert got == expected, (
            f"{phrase!r} → {got!r} (expected {expected!r})"
        )


def test_classify_dimension_concept_default_is_knowledge() -> None:
    """ext_type='concept' biases unmatched text to 'knowledge'."""
    _fresh_env()
    hm = _reload()
    # Generic-sounding text with no keyword matches
    assert hm.classify_dimension("a thing exists",
                                  ext_type="concept") == "knowledge"
    # With explicit keyword, the keyword wins regardless of ext_type
    assert hm.classify_dimension("workout daily",
                                  ext_type="concept") == "body"


def test_classify_dimension_handles_empty() -> None:
    _fresh_env()
    hm = _reload()
    assert hm.classify_dimension("") == "identity"
    assert hm.classify_dimension(None) == "identity"


def test_classify_dimension_word_boundary_no_substring_false_positives() -> None:
    """Phase 12.3 — \\b regex matching kills the substring-bug class.

    Same regression pattern as the security classifier (March '26):
    'production' should NOT match 'product', 'walking the dog' should
    not be parsed because 'walk' is in body keywords (the new walking
    is now also explicitly there for that reason). Documents the
    surgical removal of overly-loose work keywords (product/report/
    review) that previously dragged in unrelated phrases."""
    _fresh_env()
    hm = _reload()
    # Direct false-positive checks: these used to match work keywords
    # via substring; now they should fall through to identity.
    cases_should_NOT_be_work = [
        "production environment is unstable",   # was matching 'product'
        "executive function is hard today",     # 'execute' nearby words
        "reviewing the artwork I made",          # was matching 'review'
        "report cards came home",                # was matching 'report'
    ]
    for phrase in cases_should_NOT_be_work:
        got = hm.classify_dimension(phrase)
        assert got != "work", (
            f"FALSE POSITIVE: {phrase!r} → {got!r} should NOT be 'work'"
        )

    # Stem matching still works for marked prefixes
    assert hm.classify_dimension("synthesizing my notes today") == "knowledge", (
        "synthesi~ should match 'synthesizing'"
    )
    assert hm.classify_dimension("contradicting myself again") == "shadow", (
        "contradict~ should match 'contradicting'"
    )
    assert hm.classify_dimension("avoidance is a tell") == "shadow", (
        "avoid~ should match 'avoidance'"
    )
    assert hm.classify_dimension("struggled with this all week") == "shadow", (
        "struggl~ should match 'struggled'"
    )

    # Multi-word phrases still match correctly
    assert hm.classify_dimension("the design team shipped on Friday") == "work"
    assert hm.classify_dimension("morning routine going well") == "practice"

    # Genuine mentions still classify correctly
    assert hm.classify_dimension("My promotion came through") == "work"
    assert hm.classify_dimension("walking the dog tonight") == "body"


def test_render_becoming_dashboard_handles_no_baseline() -> None:
    _fresh_env()
    hm = _reload()
    out = hm.render_becoming_dashboard()
    assert "📈" in out and "Becoming" in out
    assert "not yet established" in out.lower()


def test_render_becoming_dashboard_shows_arc() -> None:
    vault, mem = _fresh_env()
    _seed_memory_files(mem)
    hm = _reload()
    hm.init_baseline(now=datetime(2026, 4, 22, tzinfo=timezone.utc))
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    hm.append_learning("evening practice preferred",
                       dimension="practice",
                       now=now - timedelta(days=2))
    hm.append_learning("McGilchrist hemisphere reading is sticking",
                       dimension="knowledge",
                       now=now - timedelta(days=3))
    out = hm.render_becoming_dashboard(now=now)
    # Baseline + days-since
    assert "5 days ago" in out  # <earlier development> → <earlier development>
    # Totals
    assert "Learnings logged since baseline:" in out
    # Top moving lists practice and knowledge
    assert "practice" in out and "knowledge" in out
    # Thin dimensions list contains body, wealth, voice etc.
    assert "Gap dimensions" in out
    # Most recent learnings preview
    assert "evening practice" in out or "McGilchrist" in out


if __name__ == "__main__":
    import traceback
    tests = [
        test_module_exports,
        test_init_baseline_creates_snapshot_with_all_sources,
        test_init_baseline_rejects_same_day_without_label,
        test_get_active_baseline_returns_most_recent,
        test_days_since_baseline,
        test_append_learning_writes_jsonl_entry,
        test_append_learning_validates_dimension,
        test_append_learning_validates_empty_claim,
        test_append_learning_clamps_confidence,
        test_get_learnings_filters_by_dimension_and_window,
        test_compute_dimension_counts_returns_all_dimensions,
        test_find_thin_dimensions_lists_zero_recent,
        # Phase 12.1 — keyword-based dimension classifier
        test_classify_dimension_keyword_routing,
        test_classify_dimension_concept_default_is_knowledge,
        test_classify_dimension_handles_empty,
        # Phase 12.3 — \b word-boundary regex (substring-bug fix)
        test_classify_dimension_word_boundary_no_substring_false_positives,
        test_render_becoming_dashboard_handles_no_baseline,
        test_render_becoming_dashboard_shows_arc,
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
    print("All user_model tests passed.")
