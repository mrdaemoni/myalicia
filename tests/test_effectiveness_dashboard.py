#!/usr/bin/env python3
"""Unit tests for skills/effectiveness_dashboard.py (the /effectiveness command)."""
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
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_eff_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_eff_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload():
    if "skills.effectiveness_dashboard" in sys.modules:
        importlib.reload(sys.modules["skills.effectiveness_dashboard"])
    import skills.effectiveness_dashboard as ed
    return ed


# ── Tests ────────────────────────────────────────────────────────────────────


def test_dashboard_renders_with_no_data() -> None:
    """All sections degrade gracefully when nothing is on disk."""
    _fresh_env()
    ed = _reload()
    out = ed.render_effectiveness_dashboard()
    assert "📊" in out and "Effectiveness" in out
    for section in ("Reactions", "Archetype EMA", "Voice tone", "Emotion",
                    "Engagement rate"):
        assert section in out


def test_reactions_section_tallies_emojis() -> None:
    _, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    rows = [
        # 5 positive
        f"{(now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t🔥",
        f"{(now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t🔥",
        f"{(now - timedelta(days=3)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t❤",
        f"{(now - timedelta(days=4)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t👍",
        f"{(now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t🔥",
        # 1 negative
        f"{(now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t👎",
        # 1 outside the window — should be excluded
        f"{(now - timedelta(days=20)).strftime('%Y-%m-%d %H:%M')}\tx\ty\t🔥",
    ]
    (mem / "reaction_log.tsv").write_text(
        "timestamp\tmsg_type\ttopic\temoji\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    ed = _reload()
    out = ed.render_effectiveness_dashboard(now=now)
    assert "🔥×3" in out  # 3 fires inside window
    assert "❤×1" in out
    assert "👍×1" in out
    assert "👎×1" in out
    assert "+5 positive" in out and "−1 negative" in out


def test_archetype_ema_section_ranks_by_score() -> None:
    _, mem = _fresh_env()
    (mem / "archetype_effectiveness.json").write_text(json.dumps({
        "archetypes": {
            "beatrice": {"score": 1.4,  "attribution_count": 14},
            "muse":     {"score": 1.2,  "attribution_count": 10},
            "psyche":   {"score": 1.0,  "attribution_count": 5},
            "daimon":   {"score": 0.8,  "attribution_count": 3},
        },
    }), encoding="utf-8")
    ed = _reload()
    out = ed.render_effectiveness_dashboard()
    # Highest first
    bea_pos = out.find("beatrice")
    muse_pos = out.find("muse")
    psy_pos = out.find("psyche")
    dai_pos = out.find("daimon")
    assert 0 <= bea_pos < muse_pos < psy_pos < dai_pos, (
        f"unexpected ordering — beatrice/muse/psyche/daimon should be in "
        f"score order (1.4>1.2>1.0>0.8), got positions "
        f"{bea_pos}/{muse_pos}/{psy_pos}/{dai_pos}"
    )
    # Score values rendered
    assert "1.40" in out and "1.20" in out and "0.80" in out


def test_voice_tone_counts_tags_within_window() -> None:
    _, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    entries = [
        # In window
        {"timestamp": (now - timedelta(days=1)).isoformat(),
         "tags": ["forceful", "deliberate"]},
        {"timestamp": (now - timedelta(days=2)).isoformat(),
         "tags": ["forceful"]},
        {"timestamp": (now - timedelta(days=3)).isoformat(),
         "tags": ["whispered"]},
        # Out of window
        {"timestamp": (now - timedelta(days=20)).isoformat(),
         "tags": ["excited"]},
    ]
    (mem / "voice_metadata_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    ed = _reload()
    out = ed.render_effectiveness_dashboard(now=now)
    assert "forceful×2" in out
    assert "whispered×1" in out
    assert "deliberate×1" in out
    # Out-of-window tag must NOT appear
    assert "excited" not in out
    # n=3 (entries) is the relevant count
    assert "n=3" in out


def test_emotion_section_distribution() -> None:
    _, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    entries = [
        {"timestamp": (now - timedelta(days=1)).isoformat(),
         "emotion_label": "sad"},
        {"timestamp": (now - timedelta(days=2)).isoformat(),
         "emotion_label": "sad"},
        {"timestamp": (now - timedelta(days=3)).isoformat(),
         "emotion_label": "hap"},
        {"timestamp": (now - timedelta(days=4)).isoformat(),
         "emotion_label": "ang"},
    ]
    (mem / "emotion_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    ed = _reload()
    out = ed.render_effectiveness_dashboard(now=now)
    assert "sad×2" in out
    assert "hap×1" in out
    assert "ang×1" in out
    assert "n=4" in out


def test_engagement_rate_joins_circulation_against_responses() -> None:
    """The new metric: of last N composer sends, how many have a matching
    capture file (proactive_decision_id from response_capture)?"""
    vault, mem = _fresh_env()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    # Seed circulation log with 4 sends, decision_ids id-1 .. id-4
    decisions = [
        {"id": "id-1", "send": True, "source_kind": "surfacing",
         "decided_at": (now - timedelta(hours=4)).isoformat()},
        {"id": "id-2", "send": True, "source_kind": "surfacing",
         "decided_at": (now - timedelta(hours=3)).isoformat()},
        {"id": "id-3", "send": True, "source_kind": "contradiction",
         "decided_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "id-4", "send": True, "source_kind": "surfacing",
         "decided_at": (now - timedelta(hours=1)).isoformat()},
    ]
    (mem / "circulation_log.json").write_text(
        json.dumps(decisions), encoding="utf-8"
    )
    # Seed responses: 2 of the 4 sends got replies (id-2, id-4)
    responses_dir = vault / "writing" / "Responses"
    responses_dir.mkdir(parents=True, exist_ok=True)
    for did in ("id-2", "id-4"):
        (responses_dir / f"2026-04-25-1200-reply-to-{did}.md").write_text(
            f"---\n"
            f"captured_at: {now.isoformat()}\n"
            f"channel: text\n"
            f"proactive_decision_id: {did}\n"
            f"---\n\n# reply\n\nyes\n",
            encoding="utf-8",
        )
    # Plus a native-reply capture (telegram-reply:NNN — must NOT count)
    (responses_dir / "2026-04-25-1300-native-reply.md").write_text(
        f"---\n"
        f"captured_at: {now.isoformat()}\n"
        f"channel: text\n"
        f"proactive_decision_id: telegram-reply:9999\n"
        f"---\n\n# native\n\nresponse\n",
        encoding="utf-8",
    )
    ed = _reload()
    out = ed.render_effectiveness_dashboard(now=now)
    # 2 out of 4 sends matched
    assert "2/4 replied" in out, f"expected '2/4 replied', got:\n{out}"
    assert "(50%)" in out


def test_engagement_rate_handles_no_circulation_log() -> None:
    _fresh_env()
    ed = _reload()
    out = ed.render_effectiveness_dashboard()
    # Section should report no log, not crash
    assert "no circulation log" in out.lower() or \
        "Engagement rate" in out


def test_phase_12_5_engagement_by_source_no_log() -> None:
    """Phase 12.5 — by-source breakdown degrades cleanly when no TSV exists."""
    _fresh_env()
    ed = _reload()
    out = ed._render_engagement_by_source_section()
    assert "(no prompt_effectiveness.tsv yet)" in out


def test_phase_12_5_engagement_by_source_groups_and_ranks() -> None:
    """Phase 12.5 — TSV rows group by msg_type, rank by avg depth desc.
    Depth bars: 🟢 ≥4.0, 🟡 ≥2.5, else 🔻."""
    _, mem = _fresh_env()
    # Seed prompt_effectiveness.tsv with two msg_types at different depths
    tsv = mem / "prompt_effectiveness.tsv"
    now = datetime.now()
    rows = [
        "timestamp\tmsg_type\ttopic\tresponse_len\tinsight_score\tdepth",
        # thread_pull at avg depth 4.5 (great)
        f"{now.strftime('%Y-%m-%d %H:%M')}\tthread_pull\tx\t300\t5\t5",
        f"{now.strftime('%Y-%m-%d %H:%M')}\tthread_pull\ty\t150\t3\t4",
        # dimension_question at avg depth 2.0 (so-so)
        f"{now.strftime('%Y-%m-%d %H:%M')}\tdimension_question\tz\t60\t1\t2",
        f"{now.strftime('%Y-%m-%d %H:%M')}\tdimension_question\tw\t40\t1\t2",
        # midday at depth 3
        f"{now.strftime('%Y-%m-%d %H:%M')}\tmidday\tv\t200\t2\t3",
    ]
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    ed = _reload()
    out = ed._render_engagement_by_source_section(within_days=7)
    assert "By source (depth" in out
    # Ranking: thread_pull (4.5) before dimension_question (2.0)
    tp_idx = out.find("thread_pull")
    dq_idx = out.find("dimension_question")
    assert tp_idx > 0 and dq_idx > 0
    assert tp_idx < dq_idx, f"thread_pull should rank before dimension_question: {out!r}"
    # Visual bars
    assert "🟢 thread_pull" in out, (
        f"thread_pull at 4.5 depth should get green bar: {out!r}"
    )
    assert "🔻 dimension_question" in out, (
        f"dimension_question at 2.0 depth should get red bar: {out!r}"
    )
    # Reply counts shown
    assert "2 replies" in out  # thread_pull and dimension_question both have 2


def test_phase_13_15_meta_quality_buckets_by_level() -> None:
    """Phase 13.15 — engagement aggregated by synthesis recursion level.

    Plain syntheses, level-1 metas, level-2 metas should each appear in
    their own row with capture totals. Comparison line ('meta vs plain')
    surfaces when both exist."""
    vault, _ = _fresh_env()
    synth_dir = vault / "Alicia" / "Wisdom" / "Synthesis"
    synth_dir.mkdir(parents=True, exist_ok=True)
    # Plain synthesis
    (synth_dir / "Plain claim.md").write_text(
        "# Plain claim\n\nbody", encoding="utf-8",
    )
    # Level-1 meta
    (synth_dir / "Level 1 meta.md").write_text(
        "---\nkind: meta_synthesis\nlevel: 1\nparent_synthesis: \"Plain claim\"\n---\n\n"
        "# Level 1 meta\nbody",
        encoding="utf-8",
    )

    # Stub most_responded_syntheses to control capture counts
    import skills.response_capture as rc
    original = rc.most_responded_syntheses
    rc.most_responded_syntheses = lambda n=100: [
        ("Plain claim", 2),       # plain: 2 captures
        ("Level 1 meta", 5),      # meta: 5 captures
    ]
    # Phase 13.15 — meta_synthesis caches SYNTHESIS_DIR at import time.
    # Reload it so it sees the test's ALICIA_VAULT_ROOT.
    if "skills.meta_synthesis" in sys.modules:
        importlib.reload(sys.modules["skills.meta_synthesis"])
    try:
        ed = _reload()
        out = ed._render_meta_synthesis_quality_section()
        # Both buckets should appear
        assert "Plain: 1 syntheses · 2 captures" in out, (
            f"plain bucket missing: {out!r}"
        )
        assert "Level 1: 1 syntheses · 5 captures" in out, (
            f"level-1 bucket missing: {out!r}"
        )
        # Comparison line: 5/1 = 5x deeper for meta
        assert "meta vs plain: 2.50×" in out, (
            f"expected ratio comparison: {out!r}"
        )
        assert "higher altitude lands deeper" in out
    finally:
        rc.most_responded_syntheses = original


def test_phase_13_15_meta_quality_no_data() -> None:
    """Empty / no-syntheses-on-disk degrades gracefully."""
    vault, _ = _fresh_env()
    (vault / "Alicia" / "Wisdom" / "Synthesis").mkdir(parents=True, exist_ok=True)
    import skills.response_capture as rc
    original = rc.most_responded_syntheses
    rc.most_responded_syntheses = lambda n=100: []
    try:
        ed = _reload()
        out = ed._render_meta_synthesis_quality_section()
        assert "no responded syntheses" in out
    finally:
        rc.most_responded_syntheses = original


def test_phase_12_5_engagement_by_source_respects_window() -> None:
    """Rows older than within_days are excluded."""
    _, mem = _fresh_env()
    tsv = mem / "prompt_effectiveness.tsv"
    now = datetime.now()
    old = now - timedelta(days=30)
    rows = [
        "timestamp\tmsg_type\ttopic\tresponse_len\tinsight_score\tdepth",
        f"{old.strftime('%Y-%m-%d %H:%M')}\told_type\tancient\t100\t1\t5",
        f"{now.strftime('%Y-%m-%d %H:%M')}\tnew_type\trecent\t100\t1\t3",
    ]
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    ed = _reload()
    out = ed._render_engagement_by_source_section(within_days=14)
    assert "new_type" in out
    assert "old_type" not in out, (
        f"30d-old row must not appear in 14d window: {out!r}"
    )


if __name__ == "__main__":
    import traceback
    tests = [
        test_dashboard_renders_with_no_data,
        test_reactions_section_tallies_emojis,
        test_archetype_ema_section_ranks_by_score,
        test_voice_tone_counts_tags_within_window,
        test_emotion_section_distribution,
        test_engagement_rate_joins_circulation_against_responses,
        test_engagement_rate_handles_no_circulation_log,
        test_phase_12_5_engagement_by_source_no_log,
        test_phase_12_5_engagement_by_source_groups_and_ranks,
        test_phase_12_5_engagement_by_source_respects_window,
        test_phase_13_15_meta_quality_buckets_by_level,
        test_phase_13_15_meta_quality_no_data,
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
    print("All effectiveness_dashboard tests passed.")
