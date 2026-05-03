#!/usr/bin/env python3
"""
Unit + invariant tests for circulation_composer.

The module is feature-flagged (USE_CIRCULATION_COMPOSER), so these tests
exercise its behavior directly rather than through the flag. Separate
integration tests in smoke_test.py verify wiring.

Usage:
    python tests/test_circulation_composer.py
    pytest tests/test_circulation_composer.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_memory_dir() -> str:
    """Point ALICIA_MEMORY_DIR at a clean tmpdir so tests don't mutate prod state."""
    d = tempfile.mkdtemp(prefix="alicia_composer_test_")
    os.environ["ALICIA_MEMORY_DIR"] = d
    return d


def _reload_composer():
    """Force re-import so module-level env vars are re-read."""
    import importlib
    # Also reload the finalizer + practice_runner because the composer
    # imports from both (practice_runner is consulted for the practice-link
    # bonus on contradiction scoring).
    for m in (
        "skills.synthesis_finalizer",
        "skills.practice_runner",
        "skills.circulation_composer",
    ):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    import myalicia.skills.circulation_composer as cc
    return cc


def test_import_and_public_api() -> None:
    """Every public name named in the design doc exists."""
    # Ensure VAULT_ROOT points at the real vault for parse tests
    import myalicia.skills.circulation_composer as cc
    for name in (
        "decide_for_slot", "record_reaction", "check_invariants",
        "CirculationDecision", "Archetype", "Channel",
        "CIRCULATION_LOG_FILE", "USE_CIRCULATION_COMPOSER",
        "_parse_active_contradictions",
    ):
        assert hasattr(cc, name), f"circulation_composer missing: {name}"


def test_archetype_and_channel_enums() -> None:
    from myalicia.skills.circulation_composer import Archetype, Channel
    assert Archetype.DAIMON.value == "Daimon"
    assert Archetype.MUSE.value == "Muse"
    assert Channel.NO_SEND.value == "no_send"
    assert Channel.VOICE.value == "voice"
    # Every archetype in the proposal's §8 table is represented
    names = {a.value for a in Archetype}
    assert names == {"Daimon", "Beatrice", "Ariadne", "Psyche", "Musubi", "Muse"}


def test_no_candidates_returns_no_send() -> None:
    """With empty memory (no surfacings) and morning slot (excludes
    contradictions), decision must be NO_SEND."""
    _fresh_memory_dir()
    os.environ["ALICIA_VAULT_ROOT"] = tempfile.mkdtemp()  # empty vault — no Contradictions.md
    cc = _reload_composer()

    decision = cc.decide_for_slot("morning")
    assert decision.send is False
    assert decision.channel == cc.Channel.NO_SEND.value
    assert decision.source_kind == "quiet"
    assert decision.archetype is None


def test_contradiction_branch_evening_only() -> None:
    """Contradictions are only offered for evening / out_of_band slots, not morning."""
    mem = _fresh_memory_dir()
    # Build a fake vault with a Contradictions.md containing one active entry
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    self_dir = Path(vault) / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "Contradictions.md").write_text(
        "# Contradictions\n\n"
        "### 1. Test tension\n\n"
        "- **Pole A** — x\n"
        "- **Pole B** — y\n"
        "- **Archetype home** — Daimon (quality gate).\n"
        "- **Status** — `active`\n"
        "- **Last updated** — 2026-04-22\n",
        encoding="utf-8",
    )
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    # Morning: contradictions excluded → NO_SEND
    dec_morning = cc.decide_for_slot("morning")
    assert dec_morning.send is False, f"morning must NO_SEND, got {dec_morning}"

    # Evening: contradictions scored high → SEND with voice channel, Daimon
    dec_evening = cc.decide_for_slot("evening")
    assert dec_evening.send is True
    assert dec_evening.source_kind == "contradiction"
    assert dec_evening.archetype == "Daimon"
    assert dec_evening.channel == cc.Channel.VOICE.value


def test_surfacing_branch_uses_finalizer_queue(monkeypatch=None) -> None:
    """When a surfacing is ready in the queue, the composer picks it and marks delivered."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    # Stub get_ready_surfacings to return a synthetic surfacing
    fake_entry_id = str(uuid4())
    fake_surfacing = {
        "entry_id": fake_entry_id,
        "stage_name": "fresh",
        "synthesis_title": "Test synthesis — the leading edge",
        "synthesis_path": "/tmp/fake/path.md",
        "voice_hint": "still-warm",
        "source": "synthesis_finalize:Test synthesis:fresh",
    }
    calls = {"mark": []}

    def fake_get_ready_surfacings(now=None):
        return [fake_surfacing]

    def fake_mark_delivered(entry_id, stage_name):
        calls["mark"].append((entry_id, stage_name))

    import myalicia.skills.synthesis_finalizer as sf
    sf.get_ready_surfacings = fake_get_ready_surfacings
    sf.mark_surfacing_delivered = fake_mark_delivered

    decision = cc.decide_for_slot("morning")
    assert decision.send is True
    assert decision.source_kind == "surfacing"
    assert decision.stage_name == "fresh"
    assert decision.archetype == cc.Archetype.ARIADNE.value  # fresh → Ariadne
    assert decision.synthesis_title.startswith("Test synthesis")
    assert decision.channel == cc.Channel.TEXT.value
    assert calls["mark"] == [(fake_entry_id, "fresh")]


def test_broken_record_dedup() -> None:
    """After a send, the same synthesis × archetype pair is blocked for 7 days."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    fake_surfacing = {
        "entry_id": str(uuid4()),
        "stage_name": "fresh",
        "synthesis_title": "Same synthesis",
        "synthesis_path": "/tmp/x.md",
        "voice_hint": "still-warm",
        "source": "synthesis_finalize:Same synthesis:fresh",
    }
    import myalicia.skills.synthesis_finalizer as sf
    sf.get_ready_surfacings = lambda now=None: [fake_surfacing]
    sf.mark_surfacing_delivered = lambda eid, sn: None

    first = cc.decide_for_slot("morning")
    assert first.send is True

    # Second call with the same surfacing: composer must dedup
    # (We stub a FRESH entry_id to simulate a re-queue, but same title+archetype)
    fake_surfacing_2 = dict(fake_surfacing)
    fake_surfacing_2["entry_id"] = str(uuid4())
    sf.get_ready_surfacings = lambda now=None: [fake_surfacing_2]
    second = cc.decide_for_slot("morning")
    assert second.send is False, f"dedup failed; got {second}"


def test_check_invariants_detects_broken_record() -> None:
    """Manually inject a log with a 3-day-gap same-synthesis-same-archetype
    pair and confirm the invariant fires."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    now = datetime.now(timezone.utc)
    three_days_ago = (now - timedelta(days=3)).isoformat()
    now_iso = now.isoformat()
    log = [
        {
            "id": "a", "slot": "morning", "send": True, "channel": "text",
            "archetype": "Ariadne", "source_kind": "surfacing",
            "source_id": "e1", "synthesis_title": "Broken record candidate",
            "synthesis_path": "/tmp/x.md", "stage_name": "fresh",
            "score": 1.5, "reason": "test", "decided_at": three_days_ago,
        },
        {
            "id": "b", "slot": "midday", "send": True, "channel": "text",
            "archetype": "Ariadne", "source_kind": "surfacing",
            "source_id": "e2", "synthesis_title": "Broken record candidate",
            "synthesis_path": "/tmp/x.md", "stage_name": "three_days",
            "score": 1.5, "reason": "test", "decided_at": now_iso,
        },
    ]
    Path(mem).mkdir(parents=True, exist_ok=True)
    cc.CIRCULATION_LOG_FILE.write_text(json.dumps(log), encoding="utf-8")

    violations = cc.check_invariants()
    kinds = [v["kind"] for v in violations]
    assert "same_synthesis_archetype_lt_7d" in kinds, f"got {violations}"


def test_feature_flag_default_is_off() -> None:
    """USE_CIRCULATION_COMPOSER must default to False so existing behavior
    is untouched on a fresh install."""
    # Clear and reload
    os.environ.pop("USE_CIRCULATION_COMPOSER", None)
    cc = _reload_composer()
    assert cc.USE_CIRCULATION_COMPOSER is False


def _write_contradictions_md(vault: str, entries: list[dict]) -> None:
    """Helper: write a Contradictions.md with N active entries.

    Each entry dict supports keys: title, archetype, last_updated.
    """
    self_dir = Path(vault) / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    body = ["# Contradictions\n"]
    for i, e in enumerate(entries, 1):
        body.append(
            f"### {i}. {e['title']}\n\n"
            f"- **Pole A** — x\n"
            f"- **Pole B** — y\n"
            f"- **Archetype home** — {e['archetype']}\n"
            f"- **Status** — `active`\n"
            f"- **Last updated** — {e['last_updated']}\n"
        )
    (self_dir / "Contradictions.md").write_text("\n".join(body), encoding="utf-8")


def test_contradiction_scoring_breaks_ties_by_recency() -> None:
    """When two contradictions both score, the more recently updated one wins.

    Regression for the Apr 2026 dogfood week where 5 active contradictions all
    tied on score and the file-order-first one ('Acquisition urge') always won.
    """
    from datetime import datetime, timezone, timedelta
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    today = datetime.now(timezone.utc).date()
    stale = (today - timedelta(days=20)).isoformat()
    fresh = today.isoformat()
    _write_contradictions_md(vault, [
        # Older entry (file-order #1) would have won under old scoring
        {"title": "Stale file-order winner", "archetype": "Daimon",
         "last_updated": stale},
        {"title": "Recent challenger",       "archetype": "Psyche",
         "last_updated": fresh},
    ])
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    dec = cc.decide_for_slot("evening")
    assert dec.send is True, dec
    assert dec.source_kind == "contradiction"
    assert dec.source_id == "Recent challenger", (
        f"recency-bumped entry should win; got source_id={dec.source_id!r} "
        f"score={dec.score}"
    )


def test_contradiction_scoring_practice_link_overrides_archetype() -> None:
    """A contradiction with an active practice descending from one of its
    archetype-home values speaks in the practice's voice — not the primary.

    The 'Daimon ⇄ Beatrice' tension with a Beatrice practice should produce
    a Beatrice-archetype send, not Daimon, because Beatrice is the one being
    lived."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    # Two contradictions on the same date — practice link is the only signal
    today = datetime.now(timezone.utc).date().isoformat()
    self_dir = Path(vault) / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "Contradictions.md").write_text(
        "# Contradictions\n\n"
        "### 1. Pure Daimon tension\n\n"
        "- **Pole A** — x\n- **Pole B** — y\n"
        "- **Archetype home** — Daimon\n"
        "- **Status** — `active`\n"
        f"- **Last updated** — {today}\n\n"
        "### 2. Daimon vs Beatrice tension\n\n"
        "- **Pole A** — x\n- **Pole B** — y\n"
        "- **Archetype home** — Daimon ⇄ Beatrice (both)\n"
        "- **Status** — `active`\n"
        f"- **Last updated** — {today}\n",
        encoding="utf-8",
    )
    # Scaffold a Beatrice practice in the vault
    practices_dir = Path(vault) / "Alicia" / "Practices" / "test-practice"
    practices_dir.mkdir(parents=True, exist_ok=True)
    (practices_dir / "practice.md").write_text(
        "---\n"
        "slug: test-practice\n"
        "title: Test practice\n"
        "synthesis_title: Some synthesis\n"
        "synthesis_path: Alicia/Wisdom/Synthesis/Some synthesis.md\n"
        "archetype: Beatrice\n"
        "instrument: do the thing\n"
        f"started_at: {today}\n"
        "status: active\n"
        "---\n# Test practice\n",
        encoding="utf-8",
    )
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    dec = cc.decide_for_slot("evening")
    assert dec.send is True, dec
    assert dec.source_kind == "contradiction"
    assert dec.source_id == "Daimon vs Beatrice tension", (
        f"practice-linked entry should win; got {dec.source_id!r}")
    assert dec.archetype == "Beatrice", (
        f"voice should be Beatrice (the practiced archetype), not Daimon; "
        f"got {dec.archetype!r}")


def test_record_send_augments_existing_log_entry() -> None:
    """record_send writes prompt_text + telegram_message_id + sent_at back
    onto the matching circulation_log entry — leaves decided_at alone."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    # Stub a synthetic surfacing so decide_for_slot writes a real entry first
    fake_entry_id = str(uuid4())
    fake_surfacing = {
        "entry_id": fake_entry_id,
        "stage_name": "fresh",
        "synthesis_title": "Some synthesis",
        "synthesis_path": "/tmp/syn.md",
        "voice_hint": "still-warm",
        "source": "synthesis_finalize:Some synthesis:fresh",
    }
    import myalicia.skills.synthesis_finalizer as sf
    sf.get_ready_surfacings = lambda now=None: [fake_surfacing]
    sf.mark_surfacing_delivered = lambda eid, stage: None

    decision = cc.decide_for_slot("morning")
    assert decision.send is True

    # Now record the send
    rendered = "Good morning. Three weeks ago you wrote: ..."
    ok = cc.record_send(
        decision.id,
        prompt_text=rendered,
        telegram_message_id=99999,
    )
    assert ok is True

    # Reload the log and verify the entry was updated in place
    entries = cc._load_circulation_log()
    matched = [e for e in entries if e["id"] == decision.id]
    assert len(matched) == 1
    e = matched[0]
    assert e["prompt_text"] == rendered
    assert e["telegram_message_id"] == 99999
    assert "sent_at" in e
    # decided_at was preserved (record_send must not overwrite it)
    assert "decided_at" in e and e["decided_at"]


def test_record_send_returns_false_for_unknown_decision() -> None:
    """record_send tolerates a missing decision id without raising."""
    _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()
    ok = cc.record_send(
        "not-a-real-decision-id",
        prompt_text="anything",
        telegram_message_id=1,
    )
    assert ok is False


def test_record_send_then_response_capture_uses_rendered_prompt() -> None:
    """End-to-end: composer decision → record_send writes rendered prompt →
    response_capture uses the rendered text in the captured note, not the
    composer's internal reason format."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    # Build a fake surfacing path so decide_for_slot writes a send=True entry
    fake_entry_id = str(uuid4())
    fake_surfacing = {
        "entry_id": fake_entry_id,
        "stage_name": "fresh",
        "synthesis_title": "Three weeks ago insight",
        "synthesis_path": "/tmp/syn.md",
        "voice_hint": "still-warm",
        "source": "synthesis_finalize:Three weeks ago insight:fresh",
    }
    import myalicia.skills.synthesis_finalizer as sf
    sf.get_ready_surfacings = lambda now=None: [fake_surfacing]
    sf.mark_surfacing_delivered = lambda eid, stage: None

    decision = cc.decide_for_slot("morning")
    rendered = ("A week ago, you said something that scored a 5: "
                "[voice quote]. Still true? Or has your thinking shifted?")
    cc.record_send(decision.id, prompt_text=rendered)

    # Now run response_capture and assert it uses `prompt_text`, not `reason`
    if "skills.response_capture" in sys.modules:
        import importlib
        importlib.reload(sys.modules["skills.response_capture"])
    import myalicia.skills.response_capture as rc
    out = rc.capture_if_responsive(
        "still very true",
        channel="text",
    )
    assert out is not None and out.exists()
    text = out.read_text(encoding="utf-8")
    assert ("Still true? Or has your thinking shifted?" in text), (
        "captured note should include the actually-rendered Telegram prompt, "
        f"got body excerpt:\n{text[:600]}"
    )
    # The internal reason format must NOT appear
    assert "score=" not in text, (
        "captured note should NOT include the composer's internal reason"
    )


def test_should_amplify_with_drawing_threshold() -> None:
    """Phase 13.1 — only high-conviction composer decisions amplify with drawing."""
    _fresh_memory_dir()
    cc = _reload_composer()
    # Build a high-score surfacing decision — should amplify
    high = cc.CirculationDecision(
        id="x", slot="evening", send=True, channel="text",
        archetype="Beatrice", source_kind="contradiction",
        source_id="some title", synthesis_title=None, synthesis_path=None,
        stage_name=None, score=2.2, reason="x",
        decided_at="2026-04-25T18:00:00+00:00",
    )
    assert cc.should_amplify_with_drawing(high) is True

    # Below threshold — must NOT amplify
    low = cc.CirculationDecision(
        id="y", slot="evening", send=True, channel="text",
        archetype="Beatrice", source_kind="contradiction",
        source_id="some title", synthesis_title=None, synthesis_path=None,
        stage_name=None, score=1.5, reason="x",
        decided_at="2026-04-25T18:00:00+00:00",
    )
    assert cc.should_amplify_with_drawing(low) is False

    # No-archetype decision — must NOT amplify
    no_arch = cc.CirculationDecision(
        id="z", slot="evening", send=True, channel="text",
        archetype=None, source_kind="contradiction",
        source_id="some title", synthesis_title=None, synthesis_path=None,
        stage_name=None, score=2.5, reason="x",
        decided_at="2026-04-25T18:00:00+00:00",
    )
    assert cc.should_amplify_with_drawing(no_arch) is False

    # NO_SEND decision — must NOT amplify
    quiet = cc.CirculationDecision(
        id="q", slot="morning", send=False, channel="no_send",
        archetype=None, source_kind="quiet",
        source_id=None, synthesis_title=None, synthesis_path=None,
        stage_name=None, score=0.0, reason="quiet",
        decided_at="2026-04-25T18:00:00+00:00",
    )
    assert cc.should_amplify_with_drawing(quiet) is False

    # practice_progress — must NOT amplify (those are quieter signals)
    pp = cc.CirculationDecision(
        id="p", slot="morning", send=True, channel="text",
        archetype="Beatrice", source_kind="practice_progress",
        source_id="x", synthesis_title=None, synthesis_path=None,
        stage_name=None, score=2.5, reason="x",
        decided_at="2026-04-25T18:00:00+00:00",
    )
    assert cc.should_amplify_with_drawing(pp) is False


def test_record_drawing_decision_with_moment_id_links_to_text_decision() -> None:
    """Phase 13.1 — drawings that amplify a text moment carry the text
    decision's id as moment_id so the two events are linkable."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()
    parent_id = "parent-text-decision-uuid"
    decision_id = cc.record_drawing_decision(
        archetype="Beatrice",
        caption="visible motion is the motion",
        source_kind="drawing_composer",
        moment_id=parent_id,
        telegram_message_id=99,
    )
    entries = cc._load_circulation_log()
    matched = [e for e in entries if e["id"] == decision_id]
    assert len(matched) == 1
    assert matched[0].get("moment_id") == parent_id


def test_record_drawing_decision_creates_circulation_entry() -> None:
    """Phase 13.0: drawings are first-class circulation events.
    record_drawing_decision creates a fresh circulation_log entry with
    channel='drawing' and the proper source_kind tag, plus augments it
    with the rendered caption + telegram_message_id immediately."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    decision_id = cc.record_drawing_decision(
        archetype="Muse",
        caption="dappled light through old branches",
        source_kind="drawing_impulse",
        source_id="draw_abc123",
        drawing_path="/tmp/draw.png",
        telegram_message_id=42,
    )
    assert decision_id

    # Reload the log and verify the entry shape
    entries = cc._load_circulation_log()
    matched = [e for e in entries if e["id"] == decision_id]
    assert len(matched) == 1
    e = matched[0]
    assert e["channel"] == "drawing"
    assert e["source_kind"] == "drawing_impulse"
    assert e["archetype"] == "Muse"
    assert e["source_id"] == "draw_abc123"
    assert e["synthesis_path"] == "/tmp/draw.png"
    # record_send augmentation should have written prompt_text + msg_id
    assert e.get("prompt_text") == "dappled light through old branches"
    assert e.get("telegram_message_id") == 42
    # decided_at preserved
    assert "decided_at" in e


def test_record_drawing_decision_handles_empty_caption() -> None:
    """Empty captions don't trigger augmentation but the entry still lands."""
    _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()
    decision_id = cc.record_drawing_decision(
        archetype="Daimon",
        caption="",
        source_kind="drawing_manual",
        telegram_message_id=99,
    )
    entries = cc._load_circulation_log()
    matched = [e for e in entries if e["id"] == decision_id]
    assert len(matched) == 1
    assert matched[0]["channel"] == "drawing"
    assert matched[0]["source_kind"] == "drawing_manual"


def test_practice_progress_surfacing_drives_composer_with_practice_voice() -> None:
    """A kind='practice_progress' surfacing should drive the composer:
    archetype = the practice's archetype (not the stage default), and
    source_kind = 'practice_progress' in the decision log."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    fake_entry_id = str(uuid4())
    fake_surfacing = {
        "entry_id": fake_entry_id,
        "stage_name": "fresh",
        "synthesis_title": "Public-facing attempts at the not-yet-good",
        "synthesis_path": "/tmp/practice.md",
        "voice_hint": "still-warm",
        "source": "practice_progress:public-facing-attempts:fresh",
        "kind": "practice_progress",
        "archetype_hint": "Beatrice",
    }
    calls = {"mark": []}
    import myalicia.skills.synthesis_finalizer as sf
    sf.get_ready_surfacings = lambda now=None: [fake_surfacing]
    sf.mark_surfacing_delivered = lambda eid, stage: calls["mark"].append(
        (eid, stage)
    )

    decision = cc.decide_for_slot("morning")
    assert decision.send is True
    assert decision.source_kind == "practice_progress", (
        f"expected source_kind=practice_progress, got {decision.source_kind!r}")
    assert decision.archetype == "Beatrice", (
        f"voice should be Beatrice (the practice's archetype), got "
        f"{decision.archetype!r}")
    assert decision.synthesis_title.startswith("Public-facing attempts")
    assert calls["mark"] == [(fake_entry_id, "fresh")]


def test_contradictions_parser_captures_archetypes_list_and_last_updated() -> None:
    """Parser returns the full list of archetypes on the line and last_updated."""
    mem = _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_test_")
    self_dir = Path(vault) / "Alicia" / "Self"
    self_dir.mkdir(parents=True, exist_ok=True)
    (self_dir / "Contradictions.md").write_text(
        "# Contradictions\n\n"
        "### 1. Multi-archetype tension\n\n"
        "- **Pole A** — x\n- **Pole B** — y\n"
        "- **Archetype home** — Daimon ⇄ Beatrice (both).\n"
        "- **Status** — `active`\n"
        "- **Last updated** — 2026-04-25\n",
        encoding="utf-8",
    )
    os.environ["ALICIA_VAULT_ROOT"] = vault
    cc = _reload_composer()

    rows = cc._parse_active_contradictions()
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == "Multi-archetype tension"
    assert r["archetype"] == "Daimon"  # primary
    assert "Daimon" in r["archetypes"] and "Beatrice" in r["archetypes"]
    assert r["last_updated"] == "2026-04-25"


def test_phase_13_13_meta_synthesis_surfacing_bonus() -> None:
    """Phase 13.13 — meta-syntheses get a composer weight bonus that
    scales with their recursion level. Plain syntheses get 0.0; level-1
    metas get 0.3; level-2 metas get 0.5; level-3 metas get 0.7."""
    _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_phase1313_")
    synth_dir = Path(vault) / "Alicia" / "Wisdom" / "Synthesis"
    synth_dir.mkdir(parents=True, exist_ok=True)

    # A plain synthesis — no frontmatter
    (synth_dir / "Plain claim.md").write_text(
        "# Plain claim\n\nSome body text.\n", encoding="utf-8",
    )
    # A level-1 meta-synthesis
    (synth_dir / "Level 1 meta.md").write_text(
        "---\nkind: meta_synthesis\nlevel: 1\nparent_synthesis: \"Plain claim\"\n---\n\n"
        "# Level 1 meta\n\nbody",
        encoding="utf-8",
    )
    # A level-2 meta-meta-synthesis
    (synth_dir / "Level 2 meta.md").write_text(
        "---\nkind: meta_meta_synthesis\nlevel: 2\nparent_synthesis: \"Level 1 meta\"\n---\n\n"
        "# Level 2 meta\n\nbody",
        encoding="utf-8",
    )
    os.environ["ALICIA_VAULT_ROOT"] = vault

    # Reload BOTH composer and meta_synthesis so they see the new vault root
    import importlib, skills.meta_synthesis as ms
    importlib.reload(ms)
    cc = _reload_composer()

    base_score = 1.0  # base for a surfacing entry with no stage/score bonus
    # _meta_surfacing_bonus directly:
    plain = cc._meta_surfacing_bonus({"synthesis_title": "Plain claim"})
    l1 = cc._meta_surfacing_bonus({"synthesis_title": "Level 1 meta"})
    l2 = cc._meta_surfacing_bonus({"synthesis_title": "Level 2 meta"})
    missing = cc._meta_surfacing_bonus({"synthesis_title": "Does not exist"})
    assert plain == 0.0, f"plain synthesis should get 0 bonus, got {plain}"
    assert missing == 0.0, f"missing path should get 0 bonus, got {missing}"
    assert l1 > plain, f"L1 meta must score higher than plain: {l1} vs {plain}"
    assert l2 > l1, f"L2 meta must score higher than L1 meta: {l2} vs {l1}"
    # Concrete formula check: BASE 0.1 + PER_LEVEL 0.2 * level
    assert abs(l1 - 0.3) < 1e-6, f"L1 expected 0.3, got {l1}"
    assert abs(l2 - 0.5) < 1e-6, f"L2 expected 0.5, got {l2}"

    # End-to-end via _score_surfacing
    plain_total = cc._score_surfacing({"synthesis_title": "Plain claim"}, "morning")
    l1_total = cc._score_surfacing({"synthesis_title": "Level 1 meta"}, "morning")
    l2_total = cc._score_surfacing({"synthesis_title": "Level 2 meta"}, "morning")
    assert l1_total > plain_total
    assert l2_total > l1_total
    # Baseline (no stage match) is 1.0; bonuses add on top
    assert abs(plain_total - base_score) < 1e-6
    assert abs(l1_total - (base_score + 0.3)) < 1e-6
    assert abs(l2_total - (base_score + 0.5)) < 1e-6


def test_phase_13_13_bonus_is_silent_on_missing_synthesis() -> None:
    """When a surfacing references a synthesis that no longer exists on
    disk (e.g. moved/renamed/deleted), the bonus must return 0.0
    silently — never raise."""
    _fresh_memory_dir()
    vault = tempfile.mkdtemp(prefix="alicia_vault_phase1313_silent_")
    (Path(vault) / "Alicia" / "Wisdom" / "Synthesis").mkdir(parents=True)
    os.environ["ALICIA_VAULT_ROOT"] = vault
    import importlib, skills.meta_synthesis as ms
    importlib.reload(ms)
    cc = _reload_composer()

    # No file on disk → bonus is 0.0, scoring still works
    assert cc._meta_surfacing_bonus({"synthesis_title": "Ghost"}) == 0.0
    assert cc._meta_surfacing_bonus({}) == 0.0  # missing title key
    score = cc._score_surfacing({"synthesis_title": "Ghost"}, "evening")
    assert score == 1.0  # baseline only


if __name__ == "__main__":
    test_import_and_public_api()
    print("[OK] test_import_and_public_api")
    test_archetype_and_channel_enums()
    print("[OK] test_archetype_and_channel_enums")
    test_no_candidates_returns_no_send()
    print("[OK] test_no_candidates_returns_no_send")
    test_contradiction_branch_evening_only()
    print("[OK] test_contradiction_branch_evening_only")
    test_surfacing_branch_uses_finalizer_queue()
    print("[OK] test_surfacing_branch_uses_finalizer_queue")
    test_broken_record_dedup()
    print("[OK] test_broken_record_dedup")
    test_check_invariants_detects_broken_record()
    print("[OK] test_check_invariants_detects_broken_record")
    test_feature_flag_default_is_off()
    print("[OK] test_feature_flag_default_is_off")
    test_contradiction_scoring_breaks_ties_by_recency()
    print("[OK] test_contradiction_scoring_breaks_ties_by_recency")
    test_contradiction_scoring_practice_link_overrides_archetype()
    print("[OK] test_contradiction_scoring_practice_link_overrides_archetype")
    test_contradictions_parser_captures_archetypes_list_and_last_updated()
    print("[OK] test_contradictions_parser_captures_archetypes_list_and_last_updated")
    test_practice_progress_surfacing_drives_composer_with_practice_voice()
    print("[OK] test_practice_progress_surfacing_drives_composer_with_practice_voice")
    test_record_drawing_decision_creates_circulation_entry()
    print("[OK] test_record_drawing_decision_creates_circulation_entry")
    test_record_drawing_decision_handles_empty_caption()
    print("[OK] test_record_drawing_decision_handles_empty_caption")
    test_should_amplify_with_drawing_threshold()
    print("[OK] test_should_amplify_with_drawing_threshold")
    test_record_drawing_decision_with_moment_id_links_to_text_decision()
    print("[OK] test_record_drawing_decision_with_moment_id_links_to_text_decision")
    test_record_send_augments_existing_log_entry()
    print("[OK] test_record_send_augments_existing_log_entry")
    test_record_send_returns_false_for_unknown_decision()
    print("[OK] test_record_send_returns_false_for_unknown_decision")
    test_record_send_then_response_capture_uses_rendered_prompt()
    print("[OK] test_record_send_then_response_capture_uses_rendered_prompt")
    test_phase_13_13_meta_synthesis_surfacing_bonus()
    print("[OK] test_phase_13_13_meta_synthesis_surfacing_bonus")
    test_phase_13_13_bonus_is_silent_on_missing_synthesis()
    print("[OK] test_phase_13_13_bonus_is_silent_on_missing_synthesis")
    print()
    print("All circulation_composer tests passed.")
