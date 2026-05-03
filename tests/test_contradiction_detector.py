#!/usr/bin/env python3
"""
Unit tests for contradiction_detector.

The module is feature-flagged (USE_CONTRADICTION_DETECTOR). These tests
exercise the rule-based path directly and isolate writes to a tmp dir
so the real vault/memory is never touched.

Usage:
    python tests/test_contradiction_detector.py
    pytest tests/test_contradiction_detector.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from myalicia.config import config

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_env() -> tuple[Path, Path]:
    """Point ALICIA_VAULT_ROOT + ALICIA_MEMORY_DIR at fresh tmp dirs."""
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload_detector():
    """Force re-import so module-level env vars are re-read."""
    if "skills.contradiction_detector" in sys.modules:
        importlib.reload(sys.modules["skills.contradiction_detector"])
    import myalicia.skills.contradiction_detector as cd
    return cd


def _seed_ledger(vault: Path, *, today: str = "2026-04-22") -> Path:
    self_dir = vault / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    path = self_dir / "Contradictions.md"
    path.write_text(
        "# Contradictions\n\n"
        "## Entries\n\n"
        "### 1. Acquisition urge vs. accumulation discipline\n\n"
        "- **Pole A** — Get more, buy the book, upgrade the tool, "
        "expansion is evidence of aliveness.\n"
        "- **Pole B** — Stay with what you have long enough for it to "
        "become yours; depth with the known is primary.\n"
        "- **Evidence A** — Recurring impulse to enroll, subscribe.\n"
        "- **Evidence B** — Synthesis note on familiarity compound interest.\n"
        "- **Archetype home** — Daimon (quality gate).\n"
        f"- **Status** — `active`\n"
        f"- **Last updated** — {today}\n",
        encoding="utf-8",
    )
    return path


# ── Tests ───────────────────────────────────────────────────────────────────


def test_import_and_public_api() -> None:
    _fresh_env()
    cd = _reload_detector()
    for name in (
        "collect_recent_signals", "load_active_contradictions",
        "detect_contradictions", "apply_drafts", "detect_lineage_unused",
        "mark_lineage_unused", "check_invariants", "run_daily_pass",
        "ContradictionDraft", "EvidenceBump",
        "USE_CONTRADICTION_DETECTOR", "CONTRADICTIONS_PATH",
        "LINEAGES_DIR", "UNUSED_LINEAGE_TAG",
        "EVIDENCE_THRESHOLD", "STALE_ACTIVE_DAYS", "LINEAGE_UNUSED_DAYS",
    ):
        assert hasattr(cd, name), f"contradiction_detector missing: {name}"


def test_feature_flag_default_is_off() -> None:
    os.environ.pop("USE_CONTRADICTION_DETECTOR", None)
    _fresh_env()
    cd = _reload_detector()
    assert cd.USE_CONTRADICTION_DETECTOR is False


def test_load_active_contradictions_parses_seed_entry() -> None:
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    entries = cd.load_active_contradictions()
    assert len(entries) == 1
    e = entries[0]
    assert e["title"].startswith("Acquisition urge")
    assert e["archetype"] == "Daimon"
    assert e["status"] == "active"
    assert "familiarity" in e["evidence_b"].lower()


def test_rule_detect_finds_evidence_bump() -> None:
    """A reflection that re-uses Pole B's keyword fingerprint must produce a bump."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()

    signals = {
        "reflections": [{
            "source": "reflexion",
            "ts": "2026-04-20T09:00:00+00:00",
            "task_type": "remember",
            "text": (
                "Noticed a pull to accumulate rather than acquire today — "
                "stayed with familiarity and depth instead of chasing the next "
                "upgrade. Expansion is seductive but accumulation compounds."
            ),
        }],
        "episodes": [],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    bumps = detections["bumps"]
    assert len(bumps) == 1, f"expected 1 bump, got {bumps!r}"
    assert bumps[0].title.startswith("Acquisition urge")
    assert bumps[0].pole in ("A", "B")
    assert bumps[0].score >= cd.EVIDENCE_THRESHOLD


def test_rule_detect_drafts_on_tension_cue_only() -> None:
    """A the user-voice signal (memory) with a tension cue becomes a draft.
    Phase 11.3: reflexion-source signals can no longer spawn drafts —
    they're system self-talk, not the user tensions. This test now uses a
    memory-source signal which IS the user voice."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [],
        "memory": [{
            "source": "memory:patterns",
            "ts": "2026-04-20T09:00:00+00:00",
            "text": ("I feel torn between shipping the talk and keeping it "
                     "private to mature. Both pulls are real and I haven't "
                     "found the synthesis yet."),
        }],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"], f"expected a draft, got {detections}"
    assert detections["drafts"][0].status == "draft"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 11.3 — false-positive regression tests (2026-04-25 dogfood)
# ═══════════════════════════════════════════════════════════════════════════
# 14 noise drafts in 3 days surfaced 3 categories of false positive. Each
# below is a concrete signal pulled from the live ledger that previously
# produced a noise draft and must NOT under the new filters.


def test_reflexion_source_never_drafts() -> None:
    """Reflexion text is the system reflecting on its OWN processing — never
    a the user tension. Even with a perfect tension cue, drafting is blocked
    when source='reflexion'."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [{
            "source": "reflexion",
            "ts": "2026-04-23T09:00:00+00:00",
            "task_type": "search_vault",
            "text": ("On the one hand the search captured what was asked. "
                     "On the other hand the result was tangential. "
                     "This contradicts the desired pattern."),
        }],
        "episodes": [],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"reflexion source must not draft, got {detections['drafts']}"
    )


def test_system_self_praise_does_not_draft() -> None:
    """`successfully captured the paradox of...` — the system patting itself
    on the back. Eight of 14 noise drafts in dogfood matched this pattern."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    # Even from a NON-reflexion source, the not-tension pattern blocks.
    signals = {
        "reflections": [],
        "episodes": [{
            "source": "episode",
            "ts": "2026-04-23T09:00:00+00:00",
            "task_type": "search_vault",
            "text": ("Successfully captured the paradoxical beauty of the "
                     "human's revelation about practice as an infinite "
                     "circle that never completes yet always deepens."),
        }],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"'successfully captured' phrase must block drafts, got "
        f"{detections['drafts']}"
    )


def test_user_affirmation_does_not_draft() -> None:
    """'Love that paradox' is the user saying yes to something Alicia said —
    not naming a tension."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [{
            "source": "episode",
            "ts": "2026-04-23T09:00:00+00:00",
            "task_type": "text",
            "text": ("Love that paradox. How the growing of weightlessness "
                     "feels grounding. Beautiful."),
        }],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"'love that' affirmation must block drafts, got "
        f"{detections['drafts']}"
    )


def test_user_query_does_not_draft() -> None:
    """'Help me find koans' is a request, not a tension. 'Tell me your
    favorite' is too short and too query-shaped to be a tension."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [
            {"source": "episode", "ts": "2026-04-23T09:00:00+00:00",
             "task_type": "text",
             "text": ("Help me find koans inside my vault. Koans that tell "
                      "my story. Or our story. The paradoxical ones.")},
            {"source": "episode", "ts": "2026-04-23T09:30:00+00:00",
             "task_type": "text",
             "text": "Tell me your favorite one"},
        ],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"user queries must block drafts, got {detections['drafts']}"
    )


def test_voice_tone_tagged_positive_does_not_draft() -> None:
    """[excited] / [happy] tone tags signal positive states, not tensions."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [{
            "source": "episode",
            "ts": "2026-04-23T09:00:00+00:00",
            "task_type": "voice",
            "text": ("[excited] After my sauna and my hot lunch, I had a "
                     "revelation about the paradox of practice as a circle "
                     "that never finishes — it just deepens."),
        }],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"[excited]-tagged signals must block drafts, got "
        f"{detections['drafts']}"
    )


def test_short_signal_below_min_length_does_not_draft() -> None:
    """Short fragments don't carry enough context to frame two poles, even
    when they contain a tension cue."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [{
            "source": "episode",
            "ts": "2026-04-23T09:00:00+00:00",
            "task_type": "text",
            "text": "torn between two things",  # 21 chars, below floor
        }],
        "memory": [],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    assert detections["drafts"] == [], (
        f"signals below DRAFT_MIN_LENGTH must block, got "
        f"{detections['drafts']}"
    )


def test_dedup_against_existing_draft_evidence() -> None:
    """A draft whose Evidence A prefix already exists in the ledger should
    NOT be re-appended on subsequent runs. The 2026-04-25 dogfood produced
    4 day-23/day-24 dupes because the same signal was re-classified daily."""
    vault, _ = _fresh_env()
    ledger = _seed_ledger(vault, today="2026-04-22")
    cd = _reload_detector()

    draft = cd.ContradictionDraft(
        title="Test draft",
        pole_a="(needs human phrasing)",
        pole_b="(needs human phrasing)",
        evidence_a=("On the one hand I want to ship the work, on the other "
                    "hand I want to keep it private until it matures."),
        evidence_b="",
        archetype="Psyche",
        status="draft",
        rationale="detected tension cue",
    )
    # First write — should append
    r1 = cd.apply_drafts(
        {"bumps": [], "drafts": [draft]},
        now=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    assert r1["drafts_appended"] == 1
    assert r1.get("drafts_skipped_duplicate", 0) == 0

    # Second write with the same evidence — should dedup
    r2 = cd.apply_drafts(
        {"bumps": [], "drafts": [draft]},
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    assert r2["drafts_appended"] == 0, (
        f"expected dedup, got drafts_appended={r2['drafts_appended']}"
    )
    assert r2["drafts_skipped_duplicate"] == 1

    text = ledger.read_text(encoding="utf-8")
    # Only ONE Pole A line for the test draft, not two.
    assert text.count("On the one hand I want to ship") == 1


def test_legit_tension_still_drafts() -> None:
    """Make sure the new filters don't over-block real the user tensions."""
    vault, _ = _fresh_env()
    _seed_ledger(vault)
    cd = _reload_detector()
    signals = {
        "reflections": [],
        "episodes": [],
        "memory": [{
            "source": "memory:insights",
            "ts": "2026-04-25T09:00:00+00:00",
            "text": ("My instinct to share contradicts my synthesis about "
                     "solitude completing what togetherness begins. The two "
                     "ideas conflict with each other in practice — I can't "
                     "decide which one to commit to right now."),
        }],
    }
    active = cd.load_active_contradictions()
    detections = cd.detect_contradictions(signals, active)
    # Should pass all filters: memory source (allowed), real tension cues
    # ("contradicts", "conflict with", "can't decide"), no NOT-tension
    # pattern hits, length > 80.
    assert detections["drafts"], (
        f"legit tension must still draft, got {detections}"
    )


def test_apply_drafts_bumps_last_updated_and_appends_draft() -> None:
    vault, mem = _fresh_env()
    ledger = _seed_ledger(vault, today="2026-04-01")
    cd = _reload_detector()

    bump = cd.EvidenceBump(
        title="Acquisition urge vs. accumulation discipline",
        pole="B",
        archetype="Daimon",
        evidence_snippet="stayed with familiarity rather than chasing upgrades",
        score=0.44,
        signal_source="reflexion",
        signal_ts="2026-04-20T09:00:00+00:00",
    )
    draft = cd.ContradictionDraft(
        title="Shipping vs. maturing",
        pole_a="Ship early, let the world finish the work.",
        pole_b="Keep the work private until it matures.",
        evidence_a="Felt a pull to publish the talk today.",
        evidence_b="",
        archetype="Psyche",
        status="draft",
        rationale="detected tension cue 'torn between'",
    )
    result = cd.apply_drafts(
        {"bumps": [bump], "drafts": [draft]},
        now=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    assert result["bumps_applied"] == 1
    assert result["drafts_appended"] == 1

    text = ledger.read_text(encoding="utf-8")
    assert "Last updated** — 2026-04-22" in text
    assert "## Drafts (pending human review)" in text
    assert "DRAFT 2026-04-22 — Shipping vs. maturing" in text
    assert "Pole A** — Ship early" in text


def test_check_invariants_flags_stale_active() -> None:
    vault, _ = _fresh_env()
    # 61 days stale → must flag
    stale_date = (datetime.now(timezone.utc) - timedelta(days=61)).strftime("%Y-%m-%d")
    _seed_ledger(vault, today=stale_date)
    cd = _reload_detector()
    violations = cd.check_invariants()
    kinds = {v["kind"] for v in violations}
    assert "stale_active_contradiction" in kinds, f"got {violations}"


def test_detect_lineage_unused() -> None:
    vault, _ = _fresh_env()
    lineages = vault / "Alicia" / "Wisdom" / "Lineages"
    lineages.mkdir(parents=True, exist_ok=True)
    (lineages / "TestLineage-line.md").write_text(
        "# TestLineage\n\nLineage tag: `#lineage/testlineage`\n",
        encoding="utf-8",
    )
    # Empty synthesis dir → lineage is unused
    synth = vault / "Alicia" / "Wisdom" / "Synthesis"
    synth.mkdir(parents=True, exist_ok=True)
    cd = _reload_detector()
    unused = cd.detect_lineage_unused()
    slugs = {u["slug"] for u in unused}
    assert "testlineage" in slugs, f"expected testlineage in unused, got {unused}"


def test_mark_lineage_unused_is_idempotent() -> None:
    vault, _ = _fresh_env()
    lineages = vault / "Alicia" / "Wisdom" / "Lineages"
    lineages.mkdir(parents=True, exist_ok=True)
    p = lineages / "TestLineage-line.md"
    p.write_text("# TestLineage\n\nLineage tag: `#lineage/testlineage`\n", encoding="utf-8")
    cd = _reload_detector()
    unused = [{"lineage": "TestLineage-line", "slug": "testlineage",
               "last_seen": None, "path": str(p)}]
    n1 = cd.mark_lineage_unused(unused)
    n2 = cd.mark_lineage_unused(unused)
    assert n1 == 1
    assert n2 == 0, "mark_lineage_unused must be idempotent"
    text = p.read_text(encoding="utf-8")
    assert text.count(cd.UNUSED_LINEAGE_TAG) == 1


def test_run_daily_pass_dry_run_writes_nothing() -> None:
    vault, _ = _fresh_env()
    ledger = _seed_ledger(vault, today="2026-04-01")
    before = ledger.read_text(encoding="utf-8")
    os.environ.pop("USE_CONTRADICTION_DETECTOR", None)  # default off → dry run
    cd = _reload_detector()
    summary = cd.run_daily_pass()
    after = ledger.read_text(encoding="utf-8")
    assert summary["dry_run"] is True
    assert before == after, "dry run must not touch the ledger"


if __name__ == "__main__":
    import traceback
    tests = [
        test_import_and_public_api,
        test_feature_flag_default_is_off,
        test_load_active_contradictions_parses_seed_entry,
        test_rule_detect_finds_evidence_bump,
        test_rule_detect_drafts_on_tension_cue_only,
        test_apply_drafts_bumps_last_updated_and_appends_draft,
        test_check_invariants_flags_stale_active,
        test_detect_lineage_unused,
        test_mark_lineage_unused_is_idempotent,
        test_run_daily_pass_dry_run_writes_nothing,
        # Phase 11.3 — false-positive regressions (2026-04-25 dogfood)
        test_reflexion_source_never_drafts,
        test_system_self_praise_does_not_draft,
        test_user_affirmation_does_not_draft,
        test_user_query_does_not_draft,
        test_voice_tone_tagged_positive_does_not_draft,
        test_short_signal_below_min_length_does_not_draft,
        test_dedup_against_existing_draft_evidence,
        test_legit_tension_still_drafts,
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
    else:
        print("All contradiction_detector tests passed.")
