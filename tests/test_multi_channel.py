#!/usr/bin/env python3
"""
Unit tests for skills/multi_channel.py.

Sandbox-friendly: log path is rerouted to a tmpfile per test. The Haiku
judge is monkey-patched in a few tests so the borderline path can be
exercised without a live API call. Live judge integration is covered by
manual smoke (run main of multi_channel).
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


def _setup_tmp_log(tmpdir: str) -> str:
    from myalicia.skills import multi_channel as mc
    p = os.path.join(tmpdir, "multi_channel_decisions.jsonl")
    mc.MEMORY_DIR = tmpdir
    mc.DECISIONS_LOG_PATH = p
    return p


# ── Path tests ─────────────────────────────────────────────────────────────


@test("no_archetype path")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="any text", archetype=None,
            source_kind="contradiction", score=2.5,
        )
        assert d["drawing"] is False
        assert d["path"] == "no_archetype"


@test("ineligible_source path")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="x", archetype="muse",
            source_kind="practice_progress", score=2.5,
        )
        assert d["drawing"] is False
        assert d["path"] == "ineligible_source"


@test("below_floor path: score < SCORE_FLOOR")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import (
            decide_drawing_amplification, SCORE_FLOOR,
        )
        d = decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=SCORE_FLOOR - 0.1,
        )
        assert d["drawing"] is False
        assert d["path"] == "below_floor"


@test("fast_high_conviction path: score >= SCORE_FAST_PATH")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import (
            decide_drawing_amplification, SCORE_FAST_PATH,
        )
        d = decide_drawing_amplification(
            text="image-laden text", archetype="daimon",
            source_kind="contradiction", score=SCORE_FAST_PATH + 0.5,
        )
        assert d["drawing"] is True, f"expected fast-path True: {d}"
        assert d["path"] == "fast_high_conviction"


@test("judge_disabled path: borderline + use_judge=False")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import (
            decide_drawing_amplification, SCORE_FLOOR, SCORE_FAST_PATH,
        )
        # Pick a score that's truly borderline: above floor, below fast.
        # Phase 15.1 narrowed the band to [1.5, 2.0) so we use the midpoint.
        borderline = (SCORE_FLOOR + SCORE_FAST_PATH) / 2.0
        d = decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=borderline, use_judge=False,
        )
        assert d["drawing"] is False
        assert d["path"] == "judge_disabled"


# ── Saturation guard ───────────────────────────────────────────────────────


@test("saturation_guard: blocks after SATURATION_24H drawings in 24h")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Pre-populate the log with SATURATION_24H drawing-True entries
        from myalicia.skills.multi_channel import SATURATION_24H
        ts = datetime.now(timezone.utc).isoformat()
        with open(log_path, "w") as f:
            for i in range(SATURATION_24H):
                f.write(json.dumps({
                    "ts": ts, "drawing": True, "path": "fast_high_conviction",
                    "score": 3.5, "archetype": "muse",
                    "source_kind": "surfacing", "rationale": "x",
                    "text_hash": f"hash{i}", "decision_id": None,
                }) + "\n")

        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=3.5,  # Even fast-path is blocked
            use_judge=False,
        )
        assert d["drawing"] is False, f"saturation must block: {d}"
        assert d["path"] == "saturation_guard"


@test("saturation_guard: doesn't count drawing=False entries")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills.multi_channel import SATURATION_24H
        ts = datetime.now(timezone.utc).isoformat()
        with open(log_path, "w") as f:
            for i in range(SATURATION_24H + 5):
                f.write(json.dumps({
                    "ts": ts, "drawing": False, "path": "judge_no",
                    "score": 2.0, "archetype": "muse",
                    "source_kind": "surfacing", "rationale": "x",
                    "text_hash": f"h{i}", "decision_id": None,
                }) + "\n")

        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=3.5, use_judge=False,
        )
        # Should reach fast_high_conviction (no drawings actually fired)
        assert d["drawing"] is True, (
            f"drawing=False entries must NOT count toward saturation: {d}"
        )
        assert d["path"] == "fast_high_conviction"


@test("saturation_guard: respects 24h window")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills.multi_channel import SATURATION_24H
        # Write SATURATION_24H entries 30 hours old — outside window
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        with open(log_path, "w") as f:
            for i in range(SATURATION_24H + 2):
                f.write(json.dumps({
                    "ts": old_ts, "drawing": True, "path": "fast_high_conviction",
                    "score": 3.5, "archetype": "muse",
                    "source_kind": "surfacing", "rationale": "x",
                    "text_hash": f"h{i}", "decision_id": None,
                }) + "\n")

        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=3.5, use_judge=False,
        )
        assert d["drawing"] is True, (
            f"30h-old drawings must NOT count toward 24h saturation: {d}"
        )


# ── Judge path (mocked) ────────────────────────────────────────────────────


@test("judge_yes path: borderline score + judge says draw")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills import multi_channel as mc
        original_ask = mc._ask_judge
        mc._ask_judge = lambda text, arch, src, sc: (True, "vivid imagery present")
        try:
            # Phase 15.1: borderline band is [1.5, 2.0). Use midpoint.
            d = mc.decide_drawing_amplification(
                text="the weight you carry that no one sees",
                archetype="daimon", source_kind="contradiction",
                score=1.75,  # Borderline (Phase 15.1: was 2.2)
            )
            assert d["drawing"] is True
            assert d["path"] == "judge_yes"
            assert "vivid imagery" in d["rationale"]
        finally:
            mc._ask_judge = original_ask


@test("judge_no path: borderline score + judge says skip")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills import multi_channel as mc
        original_ask = mc._ask_judge
        mc._ask_judge = lambda text, arch, src, sc: (False, "purely conversational")
        try:
            d = mc.decide_drawing_amplification(
                text="what landed today?", archetype="beatrice",
                source_kind="surfacing", score=1.8,
            )
            assert d["drawing"] is False
            assert d["path"] == "judge_no"
            assert "conversational" in d["rationale"]
        finally:
            mc._ask_judge = original_ask


# ── Logging ────────────────────────────────────────────────────────────────


@test("every decision is recorded to the log")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_drawing_amplification
        decide_drawing_amplification(
            text="x", archetype=None, source_kind="surfacing", score=2.5,
        )  # no_archetype
        decide_drawing_amplification(
            text="x", archetype="muse", source_kind="surfacing",
            score=4.0, use_judge=False,
        )  # fast path
        # Two entries should land
        with open(log_path) as f:
            lines = [ln for ln in f if ln.strip()]
        assert len(lines) == 2, f"expected 2 log entries, got {len(lines)}"


@test("recent_multi_channel_decisions: respects window")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        new_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with open(log_path, "w") as f:
            f.write(json.dumps({"ts": old_ts, "drawing": True}) + "\n")
            f.write(json.dumps({"ts": new_ts, "drawing": True}) + "\n")

        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        recent = recent_multi_channel_decisions(within_hours=24)
        assert len(recent) == 1, f"expected 1 entry within 24h, got {len(recent)}"


@test("Phase 15.1 retune: SCORE_FAST_PATH=2.0, SATURATION_24H=5 (regression guard)")
def _():
    """Phase 15.1 recalibrated the decider to fire MORE drawings, matching
    the user's stated intent. If these thresholds drift back up, drawings
    will mute again."""
    from myalicia.skills.multi_channel import (
        SCORE_FAST_PATH, SCORE_FLOOR, SATURATION_24H,
    )
    assert SCORE_FAST_PATH == 2.0, (
        f"SCORE_FAST_PATH must be 2.0 (Phase 15.1); got {SCORE_FAST_PATH}. "
        f"3.0 was too conservative — most decisions never reached fast-path."
    )
    assert SCORE_FLOOR == 1.5, f"SCORE_FLOOR must remain 1.5; got {SCORE_FLOOR}"
    assert SATURATION_24H == 5, (
        f"SATURATION_24H must be 5 (Phase 15.1); got {SATURATION_24H}. "
        f"3 was too restrictive for {USER_NAME}'s 'all-three-channels' intent."
    )


@test("Phase 15.1 retune: judge prompt biases toward YES")
def _():
    """The judge system prompt should explicitly state bias-toward-YES
    so a future edit doesn't silently re-mute drawings."""
    from myalicia.skills.multi_channel import _JUDGE_SYSTEM
    assert "BIAS TOWARD YES" in _JUDGE_SYSTEM, (
        "Phase 15.1 judge prompt must explicitly state BIAS TOWARD YES — "
        "the original 'Bias toward NO' tuning muted drawings."
    )


@test("Phase 15.1 retune: score=2.0 hits fast-path (was borderline before)")
def _():
    """Score 2.0 was borderline in Phase 13.3. After Phase 15.1's retune
    it should be fast-path. This test guards the change."""
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_drawing_amplification
        d = decide_drawing_amplification(
            text="the weight you carry that no one sees",
            archetype="daimon", source_kind="contradiction",
            score=2.0, use_judge=False,
        )
        assert d["drawing"] is True
        assert d["path"] == "fast_high_conviction", (
            f"score 2.0 should hit fast-path post-15.1: {d}"
        )


@test("ELIGIBLE_SOURCE_KINDS matches Phase 13.1 set (regression guard)")
def _():
    from myalicia.skills.multi_channel import ELIGIBLE_SOURCE_KINDS
    expected = {"surfacing", "lived_surfacing", "contradiction"}
    assert ELIGIBLE_SOURCE_KINDS == expected, (
        f"ELIGIBLE_SOURCE_KINDS drifted from Phase 13.1 spec: "
        f"got {ELIGIBLE_SOURCE_KINDS}, want {expected}"
    )


# ── Phase 13.7 — Voice decider tests ────────────────────────────────────────


@test("voice fast_voice_default: short clean text → voice on")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="what's been quiet today that you want to make room for tomorrow?",
            slot="evening",
        )
        assert d["voice"] is True
        assert d["path"] == "fast_voice_default"
        assert d["channel"] == "voice"


@test("voice skip_markdown_list: 2+ list items → text-only")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="Three things from today:\n- one\n- two\n- three",
            slot="evening",
        )
        assert d["voice"] is False
        assert d["path"] == "skip_markdown_list"


@test("voice skip_markdown_heading: ## header → text-only")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="## Today's reflection\n\nA quiet morning.",
            slot="morning",
        )
        assert d["voice"] is False
        assert d["path"] == "skip_markdown_heading"


@test("voice skip_url_present: any URL → text-only")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="check this thread: https://example.com/something",
            slot="midday",
        )
        assert d["voice"] is False
        assert d["path"] == "skip_url_present"


@test("voice skip_code_block: ``` → text-only")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="here's the snippet:\n```\nfoo\n```\n",
            slot="midday",
        )
        assert d["voice"] is False
        assert d["path"] == "skip_code_block"


@test("voice skip_long_text: >800 chars → text-only")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        long_text = "Word " * 200  # ~1000 chars
        d = decide_voice_amplification(text=long_text, slot="morning")
        assert d["voice"] is False
        assert d["path"] == "skip_long_text"


@test("voice judge_disabled: borderline length + use_judge=False → YES (default)")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import decide_voice_amplification
        # ~500 chars of clean prose — between fast (350) and long (800)
        text = "This is a longer reflection paragraph that covers a single thought " * 7
        d = decide_voice_amplification(
            text=text, slot="evening", use_judge=False,
        )
        assert d["voice"] is True, f"expected YES default: {d}"
        assert d["path"] == "judge_disabled"


@test("voice judge_yes path: borderline + judge says speak")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills import multi_channel as mc
        original = mc._ask_voice_judge
        mc._ask_voice_judge = lambda text, slot: (True, "intimate prose")
        try:
            text = "A longer reflective paragraph " * 15  # borderline length
            d = mc.decide_voice_amplification(text=text, slot="evening")
            assert d["voice"] is True
            assert d["path"] == "judge_yes"
            assert "intimate prose" in d["rationale"]
        finally:
            mc._ask_voice_judge = original


@test("voice judge_no path: borderline + judge says skip")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills import multi_channel as mc
        original = mc._ask_voice_judge
        mc._ask_voice_judge = lambda text, slot: (False, "reads better silently")
        try:
            text = "A longer reflective paragraph " * 15
            d = mc.decide_voice_amplification(text=text, slot="midday")
            assert d["voice"] is False
            assert d["path"] == "judge_no"
        finally:
            mc._ask_voice_judge = original


@test("voice saturation: blocks after VOICE_SATURATION_24H firings")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills.multi_channel import VOICE_SATURATION_24H
        ts = datetime.now(timezone.utc).isoformat()
        with open(log_path, "w") as f:
            for i in range(VOICE_SATURATION_24H):
                f.write(json.dumps({
                    "ts": ts, "channel": "voice", "voice": True,
                    "path": "fast_voice_default", "slot": "midday",
                    "rationale": "x", "text_hash": f"h{i}", "text_len": 50,
                }) + "\n")

        from myalicia.skills.multi_channel import decide_voice_amplification
        d = decide_voice_amplification(
            text="short clean text", slot="evening",
        )
        assert d["voice"] is False
        assert d["path"] == "saturation_guard"


@test("Phase 13.12 compose_voice_with_drawing_tail: empty inputs → unchanged")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        from myalicia.skills.multi_channel import compose_voice_with_drawing_tail
        out, tail = compose_voice_with_drawing_tail(text="", archetype="muse")
        assert out == "" and tail is None
        out2, tail2 = compose_voice_with_drawing_tail(text="x", archetype="")
        assert out2 == "x" and tail2 is None


@test("Phase 13.12 compose_voice_with_drawing_tail: caption preview None → no tail")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp_log(td)
        # Stub bridge_text_to_drawing_caption to return None
        from myalicia.skills import drawing_skill as ds
        original = ds.bridge_text_to_drawing_caption
        ds.bridge_text_to_drawing_caption = lambda text, archetype, original_caption: None
        try:
            from myalicia.skills.multi_channel import compose_voice_with_drawing_tail
            out, tail = compose_voice_with_drawing_tail(
                text="some message", archetype="muse",
            )
            assert out == "some message"
            assert tail is None
        finally:
            ds.bridge_text_to_drawing_caption = original


@test("Phase 13.12 compose_voice_with_drawing_tail: success path augments + logs coherent_moment")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        # Stub caption preview + Haiku tail
        from myalicia.skills import drawing_skill as ds, multi_channel as mc
        original_caption = ds.bridge_text_to_drawing_caption
        ds.bridge_text_to_drawing_caption = lambda text, archetype, original_caption: \
            "the white line refusing to break"

        # Stub the Haiku tail call by intercepting Anthropic
        class _FakeContent:
            def __init__(self, text): self.text = text
        class _FakeResp:
            def __init__(self, text): self.content = [_FakeContent(text)]
        class _FakeMessages:
            def create(self, **kw): return _FakeResp("you'll see the white line in the middle")
        class _FakeClient:
            def __init__(self, **kw): self.messages = _FakeMessages()
        import anthropic as _a
        original_client = _a.Anthropic
        _a.Anthropic = _FakeClient
        try:
            out, tail = mc.compose_voice_with_drawing_tail(
                text="beneath the weight, something refuses to break",
                archetype="daimon",
            )
            assert tail is not None
            assert "white line" in tail
            assert tail in out, f"tail must be appended to text: {out}"
            # Coherent-moment log entry written
            with open(log_path) as f:
                entries = [json.loads(ln) for ln in f if ln.strip()]
            coherent = [e for e in entries if e.get("channel") == "coherent_moment"]
            assert len(coherent) == 1
            assert coherent[0]["voice"] is True
            assert coherent[0]["drawing"] is True
            assert coherent[0]["path"] == "voice_drawing_tail"
        finally:
            ds.bridge_text_to_drawing_caption = original_caption
            _a.Anthropic = original_client


@test("voice + drawing channels share decisions log without collision")
def _():
    with tempfile.TemporaryDirectory() as td:
        log_path = _setup_tmp_log(td)
        from myalicia.skills.multi_channel import (
            decide_drawing_amplification, decide_voice_amplification,
            voice_fired_recently, drawings_fired_recently,
        )
        # Fire one of each
        decide_voice_amplification(text="short", slot="midday")
        decide_drawing_amplification(
            text="vivid imagery", archetype="muse",
            source_kind="surfacing", score=4.0, use_judge=False,
        )
        # Both counters should report 1 each — channels don't cross-contaminate
        assert voice_fired_recently(within_hours=24) == 1, (
            f"voice counter must not include drawings"
        )
        assert drawings_fired_recently(within_hours=24) == 1, (
            f"drawing counter must not include voice"
        )


if __name__ == "__main__":
    print("Testing multi_channel.py …")
    sys.exit(_run_all())
