#!/usr/bin/env python3
"""
Unit tests for skills/response_capture.py.

Every test points ALICIA_VAULT_ROOT / ALICIA_MEMORY_DIR at fresh tmp dirs
so the real vault is never touched.

Usage:
    python tests/test_response_capture.py
    pytest tests/test_response_capture.py -v
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
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_env() -> tuple[Path, Path]:
    vault = Path(tempfile.mkdtemp(prefix="alicia_vault_resp_test_"))
    mem = Path(tempfile.mkdtemp(prefix="alicia_mem_resp_test_"))
    os.environ["ALICIA_VAULT_ROOT"] = str(vault)
    os.environ["ALICIA_MEMORY_DIR"] = str(mem)
    return vault, mem


def _reload():
    if "skills.response_capture" in sys.modules:
        importlib.reload(sys.modules["skills.response_capture"])
    import myalicia.skills.response_capture as rc
    return rc


def _seed_circulation_log(mem: Path, decisions: list[dict]) -> None:
    (mem / "circulation_log.json").write_text(
        json.dumps(decisions), encoding="utf-8"
    )


# ── Tests ───────────────────────────────────────────────────────────────────


def test_import_and_public_api() -> None:
    _fresh_env()
    rc = _reload()
    for name in (
        "capture_response", "find_recent_proactive_context",
        "capture_if_responsive", "RESPONSES_DIR",
        "DEFAULT_RESPONSE_WINDOW_MINUTES",
    ):
        assert hasattr(rc, name), f"response_capture missing: {name}"


def test_capture_writes_file_with_expected_shape() -> None:
    vault, _ = _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    p = rc.capture_response(
        "still very true",
        channel="text",
        proactive_decision_id="dc9191f3-aaaa",
        proactive_synthesis_title="The journey from knowing to being requires compression",
        proactive_prompt_text="Still true? Or has your thinking shifted?",
        proactive_source_kind="resonance",
        archetype="Beatrice",
        now=now,
    )
    assert p.exists(), p
    text = p.read_text(encoding="utf-8")
    # Frontmatter
    assert text.startswith("---\n")
    assert "channel: text" in text
    assert "proactive_decision_id: dc9191f3-aaaa" in text
    assert "in_response_to: resonance" in text
    assert "archetype: Beatrice" in text
    assert "source_tier: writing" in text
    # Body has the wikilink to the synthesis
    assert "[[The journey from knowing to being requires compression]]" in text
    # Body has Alicia's prompt + the user's reply
    assert "Still true? Or has your thinking shifted?" in text
    assert "still very true" in text
    # Path under writing/Responses
    assert "writing/Responses" in str(p)


def test_capture_voice_response_marks_transcription() -> None:
    _fresh_env()
    rc = _reload()
    p = rc.capture_response(
        "I think the practice is starting to settle into me",
        channel="voice",
        voice_audio_path="/path/to/audio.ogg",
        now=datetime(2026, 4, 25, 16, 30, 0, tzinfo=timezone.utc),
    )
    text = p.read_text(encoding="utf-8")
    assert "channel: voice" in text
    assert "voice_audio: /path/to/audio.ogg" in text
    assert "spoken response" in text


def test_find_recent_proactive_context_within_window() -> None:
    _fresh_env()
    rc = _reload()
    mem = Path(os.environ["ALICIA_MEMORY_DIR"])
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    # 10 min ago — inside the 30-min window
    _seed_circulation_log(mem, [{
        "id": "abc",
        "send": True,
        "synthesis_title": "X",
        "source_kind": "surfacing",
        "archetype": "Beatrice",
        "decided_at": (now - timedelta(minutes=10)).isoformat(),
        "reason": "fresh stage",
    }])
    ctx = rc.find_recent_proactive_context(now=now)
    assert ctx is not None
    assert ctx["id"] == "abc"


def test_find_recent_proactive_context_outside_window_returns_none() -> None:
    _fresh_env()
    rc = _reload()
    mem = Path(os.environ["ALICIA_MEMORY_DIR"])
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    # 2 hours ago — outside default 30-min window
    _seed_circulation_log(mem, [{
        "id": "stale",
        "send": True,
        "synthesis_title": "X",
        "source_kind": "surfacing",
        "decided_at": (now - timedelta(hours=2)).isoformat(),
    }])
    ctx = rc.find_recent_proactive_context(now=now)
    assert ctx is None


def test_find_recent_skips_no_send_decisions() -> None:
    _fresh_env()
    rc = _reload()
    mem = Path(os.environ["ALICIA_MEMORY_DIR"])
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    _seed_circulation_log(mem, [
        # most recent is NO_SEND — should be skipped
        {
            "id": "quiet", "send": False,
            "decided_at": (now - timedelta(minutes=2)).isoformat(),
        },
        # earlier real send still in window
        {
            "id": "real-send", "send": True,
            "synthesis_title": "Y", "source_kind": "contradiction",
            "decided_at": (now - timedelta(minutes=20)).isoformat(),
            "reason": "midday contradiction",
        },
    ])
    ctx = rc.find_recent_proactive_context(now=now)
    assert ctx is not None
    assert ctx["id"] == "real-send"


def test_capture_if_responsive_no_recent_proactive_returns_none() -> None:
    _fresh_env()
    rc = _reload()
    # No circulation log → no proactive context → no capture
    out = rc.capture_if_responsive("hi", channel="text")
    assert out is None


def test_capture_if_responsive_writes_when_in_window() -> None:
    vault, mem = _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    _seed_circulation_log(mem, [{
        "id": "decision-1",
        "send": True,
        "source_kind": "contradiction",
        "source_id": "Daimon's quality gate vs. Beatrice's visible growth",
        "synthesis_title": None,
        "archetype": "Beatrice",
        "decided_at": (now - timedelta(minutes=15)).isoformat(),
        "reason": "Active contradiction",
    }])
    out = rc.capture_if_responsive(
        "yes — and beatrice is winning today",
        channel="text",
        now=now,
    )
    assert out is not None and out.exists()
    text = out.read_text(encoding="utf-8")
    # When synthesis_title is null, the source_id (contradiction title) is
    # used so the response still has a wikilink target
    assert "[[Daimon's quality gate vs. Beatrice's visible growth]]" in text
    assert "proactive_decision_id: decision-1" in text


def test_capture_if_responsive_skips_empty_text() -> None:
    _fresh_env()
    rc = _reload()
    out = rc.capture_if_responsive("", channel="text")
    assert out is None
    out = rc.capture_if_responsive("   \n  ", channel="text")
    assert out is None


def test_native_reply_capture_bypasses_circulation_log() -> None:
    """direct_prompt should trigger capture even when circulation_log is empty
    (or stale). This is the 'tap Reply on Alicia in Telegram' path — the
    reply target IS the prompt, no need to consult the composer log."""
    vault, mem = _fresh_env()
    rc = _reload()
    # Empty circulation log — without direct_prompt, capture would skip
    out = rc.capture_if_responsive(
        "Tell me more about the Daimon energy that you feel.",
        channel="text",
        direct_prompt=("The Daimon energy feels like the part of me that "
                       "refuses to let things be easy when they should be hard..."),
        direct_prompt_telegram_id=1234567,
    )
    assert out is not None and out.exists()
    text = out.read_text(encoding="utf-8")
    # Frontmatter records the conversational reply path
    assert "in_response_to: conversational_reply" in text
    assert "proactive_decision_id: telegram-reply:1234567" in text
    # Body has Alicia's prompt + the user's response
    assert "The Daimon energy feels like" in text
    assert "Tell me more about the Daimon energy" in text


def test_native_reply_takes_priority_over_circulation_log() -> None:
    """When BOTH a direct_prompt and a recent circulation_log entry exist,
    the explicit reply target wins — the user told us what they're
    responding to."""
    _fresh_env()
    rc = _reload()
    mem = Path(os.environ["ALICIA_MEMORY_DIR"])
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    _seed_circulation_log(mem, [{
        "id": "stale-but-in-window",
        "send": True,
        "synthesis_title": "Some other synthesis",
        "source_kind": "surfacing",
        "decided_at": (now - timedelta(minutes=5)).isoformat(),
        "reason": "fresh stage",
        "prompt_text": "Some other rendered prompt",
    }])
    out = rc.capture_if_responsive(
        "still very true",
        channel="text",
        direct_prompt=f"The actual message {USER_NAME} replied to",
        direct_prompt_telegram_id=99,
        now=now,
    )
    assert out is not None
    text = out.read_text(encoding="utf-8")
    # Native reply path wins
    assert "in_response_to: conversational_reply" in text
    assert "proactive_decision_id: telegram-reply:99" in text
    assert f"The actual message {USER_NAME} replied to" in text
    # The circulation_log entry was NOT used
    assert "Some other synthesis" not in text
    assert "Some other rendered prompt" not in text


def test_capture_unprompted_writes_to_captures_dir() -> None:
    """The /capture <text> command path — no prompt, no proactive context."""
    vault, _ = _fresh_env()
    rc = _reload()
    out = rc.capture_unprompted(
        "I've been thinking about how generosity is a discipline, "
        "not a virtue.",
        channel="text",
    )
    assert out.exists()
    assert "writing/Captures" in str(out)
    text = out.read_text(encoding="utf-8")
    assert "kind: capture" in text
    assert "source_tier: writing" in text
    assert "generosity is a discipline" in text


def test_capture_unprompted_voice_marks_transcription() -> None:
    _fresh_env()
    rc = _reload()
    out = rc.capture_unprompted(
        "spoken thought transcription",
        channel="voice",
        voice_audio_path="/tmp/audio.ogg",
    )
    text = out.read_text(encoding="utf-8")
    assert "channel: voice" in text
    assert "voice_audio: /tmp/audio.ogg" in text
    assert "spoken capture" in text


def test_capture_unprompted_rejects_empty_text() -> None:
    _fresh_env()
    rc = _reload()
    import pytest as _pytest_local  # noqa: F401  (only used for assertRaises shape)
    try:
        rc.capture_unprompted("")
        raised = False
    except ValueError:
        raised = True
    assert raised, "empty text must raise ValueError"


def test_parse_capture_file_extracts_frontmatter() -> None:
    """parse_capture_file pulls frontmatter fields and a body excerpt."""
    vault, _ = _fresh_env()
    rc = _reload()
    p = rc.capture_response(
        "still very true",
        channel="text",
        proactive_decision_id="abc-123",
        proactive_synthesis_title="The journey from knowing to being requires compression",
        proactive_prompt_text="Still true? Or has your thinking shifted?",
        proactive_source_kind="resonance",
        archetype="Beatrice",
        now=datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc),
    )
    meta = rc.parse_capture_file(p)
    assert meta is not None
    assert meta["kind"] == "response"
    assert meta["channel"] == "text"
    assert meta["proactive_decision_id"] == "abc-123"
    assert meta["synthesis_referenced"] == \
        "The journey from knowing to being requires compression"
    assert meta["archetype"] == "Beatrice"
    assert meta["in_response_to"] == "resonance"
    assert "still very true" in meta["body_excerpt"]


def test_parse_capture_file_handles_unprompted_capture() -> None:
    """capture_unprompted writes a capture (no synthesis_referenced) — parser
    must handle the absent field gracefully."""
    vault, _ = _fresh_env()
    rc = _reload()
    p = rc.capture_unprompted(
        "I've been thinking about generosity as a discipline.",
        channel="text",
    )
    meta = rc.parse_capture_file(p)
    assert meta is not None
    assert meta["kind"] == "capture"
    assert meta["synthesis_referenced"] is None
    assert "generosity" in meta["body_excerpt"]


def test_get_responses_for_synthesis_filters_by_title() -> None:
    """Multiple captures referencing different syntheses; query returns only
    the ones matching the target."""
    vault, _ = _fresh_env()
    rc = _reload()
    title_a = "Synthesis A — the first one"
    title_b = "Synthesis B — a different one"
    # 2 captures on A, 1 on B, 1 unprompted (no title)
    rc.capture_response(
        "yes for A 1", channel="text",
        proactive_synthesis_title=title_a,
        now=datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc),
    )
    rc.capture_response(
        "yes for A 2", channel="text",
        proactive_synthesis_title=title_a,
        now=datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc),
    )
    rc.capture_response(
        "yes for B", channel="text",
        proactive_synthesis_title=title_b,
        now=datetime(2026, 4, 25, 11, 0, 0, tzinfo=timezone.utc),
    )
    rc.capture_unprompted("standalone thought", channel="text")

    matches = rc.get_responses_for_synthesis(title_a)
    assert len(matches) == 2
    titles = {m["synthesis_referenced"] for m in matches}
    assert titles == {title_a}
    # Newest-first ordering
    assert matches[0]["captured_at"] > matches[1]["captured_at"]


def test_get_responses_for_synthesis_respects_max_recent_cap() -> None:
    """The max_recent parameter caps the result set."""
    vault, _ = _fresh_env()
    rc = _reload()
    title = "Heavy synthesis"
    for i in range(7):
        rc.capture_response(
            f"reply {i}", channel="text",
            proactive_synthesis_title=title,
            now=datetime(2026, 4, 25, 10, i, 0, tzinfo=timezone.utc),
        )
    matches = rc.get_responses_for_synthesis(title, max_recent=3)
    assert len(matches) == 3


def test_get_recent_captures_returns_all_kinds() -> None:
    """get_recent_captures returns both responses and unprompted captures."""
    vault, _ = _fresh_env()
    rc = _reload()
    rc.capture_response(
        "a response", channel="text",
        proactive_synthesis_title="Some synthesis",
        now=datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc),
    )
    rc.capture_unprompted("a thought", channel="text")
    recent = rc.get_recent_captures(n=10)
    assert len(recent) == 2
    kinds = {m["kind"] for m in recent}
    assert kinds == {"response", "capture"}


def test_most_responded_syntheses_ranks_by_count() -> None:
    """Most-responded syntheses ranked highest first."""
    vault, _ = _fresh_env()
    rc = _reload()
    # Synthesis A: 3 captures, B: 1, C: 2
    for n in range(3):
        rc.capture_response(
            f"a-{n}", channel="text",
            proactive_synthesis_title="Synthesis A",
            now=datetime(2026, 4, 25, 10, n, 0, tzinfo=timezone.utc),
        )
    rc.capture_response(
        "b-0", channel="text",
        proactive_synthesis_title="Synthesis B",
        now=datetime(2026, 4, 25, 11, 0, 0, tzinfo=timezone.utc),
    )
    for n in range(2):
        rc.capture_response(
            f"c-{n}", channel="text",
            proactive_synthesis_title="Synthesis C",
            now=datetime(2026, 4, 25, 12, n, 0, tzinfo=timezone.utc),
        )
    # Plus an unprompted one — should NOT be counted toward any title
    rc.capture_unprompted("standalone", channel="text")

    ranked = rc.most_responded_syntheses(n=5)
    assert ranked[0] == ("Synthesis A", 3)
    assert ranked[1] == ("Synthesis C", 2)
    assert ranked[2] == ("Synthesis B", 1)


def test_enrich_returns_message_unchanged_when_no_synthesis_title() -> None:
    """No synthesis title → enrichment is a no-op (e.g. contradiction-driven send)."""
    _fresh_env()
    rc = _reload()
    msg = "Good morning. Three weeks ago you wrote: ..."
    out = rc.enrich_proactive_with_past_responses(msg, None)
    assert out == msg
    out2 = rc.enrich_proactive_with_past_responses(msg, "")
    assert out2 == msg
    out3 = rc.enrich_proactive_with_past_responses(msg, "   ")
    assert out3 == msg


def test_enrich_returns_message_unchanged_when_no_past_responses() -> None:
    """Synthesis with no captured replies → enrichment is a no-op."""
    _fresh_env()
    rc = _reload()
    msg = "Good morning."
    out = rc.enrich_proactive_with_past_responses(
        msg, "A synthesis nobody has responded to yet"
    )
    assert out == msg


def test_enrich_appends_footer_when_past_responses_exist() -> None:
    """When past responses exist, a 📎 footer is appended with natural-
    language age labels (voice-friendly: 'yesterday' / 'N days ago' /
    'last week' instead of ISO dates that sound robotic when spoken)."""
    _fresh_env()
    rc = _reload()
    title = "The journey from knowing to being requires compression"
    # Use ages that produce predictable labels relative to "now" inside
    # the test (which uses real time). We use far-back dates to test the
    # 'N weeks ago' label.
    now = datetime.now(timezone.utc)
    rc.capture_response(
        "still very true",
        channel="text",
        proactive_synthesis_title=title,
        now=now - timedelta(days=4),
    )
    rc.capture_response(
        "the resistance is the practice",
        channel="voice",
        proactive_synthesis_title=title,
        now=now - timedelta(days=1),
    )
    msg = "Three weeks ago you wrote about the journey from knowing to being."
    out = rc.enrich_proactive_with_past_responses(msg, title)
    # Original message preserved
    assert msg in out
    # Footer header present (📎 marker + voice-friendly opener)
    assert "📎" in out
    assert "earlier on this" in out.lower()
    # Both excerpts present
    assert "still very true" in out
    assert "resistance is the practice" in out
    # Natural-language age labels (NOT ISO dates)
    assert "yesterday" in out  # the 1-day-ago response
    assert "4 days ago" in out  # the 4-day-ago response
    # ISO dates must NOT appear (voice would mispronounce them)
    assert "2026-" not in out


def test_enrich_caps_at_max_recent() -> None:
    """max_recent caps the footer to N most recent."""
    _fresh_env()
    rc = _reload()
    title = "Heavy synthesis"
    for i in range(8):
        rc.capture_response(
            f"reply number {i}",
            channel="text",
            proactive_synthesis_title=title,
            now=datetime(2026, 4, 25, 10, i, 0, tzinfo=timezone.utc),
        )
    msg = "Hello again."
    out = rc.enrich_proactive_with_past_responses(msg, title, max_recent=3)
    # Should cap at 3
    excerpt_count = out.count("reply number")
    assert excerpt_count == 3, (
        f"expected 3 excerpts in footer, got {excerpt_count}\n{out}"
    )


def test_enrich_truncates_long_excerpts() -> None:
    """Excerpts longer than excerpt_chars are truncated with an ellipsis."""
    _fresh_env()
    rc = _reload()
    title = "Some synthesis"
    long_text = "a " * 300  # 600+ chars
    rc.capture_response(
        long_text,
        channel="text",
        proactive_synthesis_title=title,
        now=datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc),
    )
    msg = "x"
    out = rc.enrich_proactive_with_past_responses(
        msg, title, max_recent=1, excerpt_chars=80
    )
    # The footer line for the excerpt should be reasonably short
    footer = out[len(msg):]
    excerpt_line = next(
        (line for line in footer.splitlines() if " — " in line and "_" in line),
        "",
    )
    assert "…" in excerpt_line, f"truncation marker missing: {excerpt_line!r}"
    # The footer line shouldn't be wildly long
    assert len(excerpt_line) < 200, len(excerpt_line)


def test_get_captures_during_practice_filters_by_window() -> None:
    """Captures whose captured_at is within [started_at, now] are returned;
    captures outside the window are excluded. Both writing/Captures/ and
    writing/Responses/ are walked."""
    _fresh_env()
    rc = _reload()
    started_at = "2026-04-22"
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    # Inside window — capture
    rc.capture_unprompted(
        "during the practice", now=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )
    # Inside window — response
    rc.capture_response(
        "reply during the practice",
        proactive_synthesis_title="Some synthesis",
        now=datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    # Before window — should be excluded
    rc.capture_unprompted(
        "before the practice", now=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    # After window — should be excluded (after `now`)
    rc.capture_unprompted(
        "after the cutoff", now=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )
    matches = rc.get_captures_during_practice(started_at, now=now)
    excerpts = [m["body_excerpt"] for m in matches]
    assert any("during the practice" in e for e in excerpts)
    assert any("reply during" in e for e in excerpts)
    assert not any("before the practice" in e for e in excerpts)
    assert not any("after the cutoff" in e for e in excerpts)
    # Newest-first ordering
    assert matches[0]["captured_at"] > matches[-1]["captured_at"]


def test_get_captures_during_practice_returns_empty_for_invalid_date() -> None:
    """Bad started_at strings degrade gracefully."""
    _fresh_env()
    rc = _reload()
    assert rc.get_captures_during_practice("") == []
    assert rc.get_captures_during_practice("not-a-date") == []


def test_pick_capture_for_morning_resurface_returns_qualifying_capture() -> None:
    """Captures aged 2-14 days, never resurfaced before, qualify."""
    _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 8, 0, 0, tzinfo=timezone.utc)
    # Three captures: too-fresh, qualifying, too-old
    rc.capture_unprompted("too fresh", now=now - timedelta(days=1))
    rc.capture_unprompted(
        "right age — should be picked", now=now - timedelta(days=5),
    )
    rc.capture_unprompted("too old", now=now - timedelta(days=30))
    pick = rc.pick_capture_for_morning_resurface(now=now)
    assert pick is not None
    assert "right age" in pick["body_excerpt"]


def test_pick_capture_skips_already_resurfaced_within_cooldown() -> None:
    """Capture marked resurfaced 5 days ago is skipped (cooldown=21d)."""
    _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 8, 0, 0, tzinfo=timezone.utc)
    # Make a qualifying capture
    p = rc.capture_unprompted(
        "should be skipped due to cooldown",
        now=now - timedelta(days=5),
    )
    # Mark it as already resurfaced 5 days ago — within default cooldown
    rc.mark_capture_resurfaced(p, now=now - timedelta(days=5))
    pick = rc.pick_capture_for_morning_resurface(now=now)
    assert pick is None


def test_pick_capture_returns_oldest_qualifying_first() -> None:
    """When multiple captures qualify, pick the oldest one (deepest unresurfaced)."""
    _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 8, 0, 0, tzinfo=timezone.utc)
    rc.capture_unprompted("3 days ago", now=now - timedelta(days=3))
    rc.capture_unprompted("10 days ago — older", now=now - timedelta(days=10))
    rc.capture_unprompted("5 days ago", now=now - timedelta(days=5))
    pick = rc.pick_capture_for_morning_resurface(now=now)
    assert pick is not None
    assert "10 days ago" in pick["body_excerpt"]


def test_pick_capture_excludes_responses_dir() -> None:
    """response files (writing/Responses/) are not eligible — they have
    their own past-response loop via Phase 11.7. Only writing/Captures/
    feeds the morning resurface."""
    _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 8, 0, 0, tzinfo=timezone.utc)
    # Response file: should NOT be picked
    rc.capture_response(
        "a response in the right age window",
        proactive_synthesis_title="Some synthesis",
        now=now - timedelta(days=5),
    )
    pick = rc.pick_capture_for_morning_resurface(now=now)
    assert pick is None


def test_render_morning_capture_resurface_includes_excerpt_and_age() -> None:
    """Rendered message must include the excerpt + a days-ago label + the
    'where has it landed?' framing."""
    _fresh_env()
    rc = _reload()
    meta = {
        "captured_at": (datetime.now(timezone.utc)
                        - timedelta(days=4)).isoformat(),
        "body_excerpt": "the discipline of letting go without abandoning",
        "kind": "capture",
    }
    msg = rc.render_morning_capture_resurface(meta)
    assert "📔" in msg
    assert "letting go without abandoning" in msg
    assert "4 days ago" in msg
    assert "where has it landed" in msg.lower()


def test_filename_is_local_date_stamped_and_slugged() -> None:
    _fresh_env()
    rc = _reload()
    now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=timezone.utc)
    p = rc.capture_response("Hello world! It's still true.", now=now)
    name = p.name
    # YYYY-MM-DD-HHMM-<slug>.md (local time may differ from UTC; just check shape)
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9-]+\.md$", name), name
    assert "hello-world-it-s-still-true" in name


if __name__ == "__main__":
    import traceback
    tests = [
        test_import_and_public_api,
        test_capture_writes_file_with_expected_shape,
        test_capture_voice_response_marks_transcription,
        test_find_recent_proactive_context_within_window,
        test_find_recent_proactive_context_outside_window_returns_none,
        test_find_recent_skips_no_send_decisions,
        test_capture_if_responsive_no_recent_proactive_returns_none,
        test_capture_if_responsive_writes_when_in_window,
        test_capture_if_responsive_skips_empty_text,
        test_native_reply_capture_bypasses_circulation_log,
        test_native_reply_takes_priority_over_circulation_log,
        test_capture_unprompted_writes_to_captures_dir,
        test_capture_unprompted_voice_marks_transcription,
        test_capture_unprompted_rejects_empty_text,
        # Phase 11.5 — read-back queries
        test_parse_capture_file_extracts_frontmatter,
        test_parse_capture_file_handles_unprompted_capture,
        test_get_responses_for_synthesis_filters_by_title,
        test_get_responses_for_synthesis_respects_max_recent_cap,
        test_get_recent_captures_returns_all_kinds,
        test_most_responded_syntheses_ranks_by_count,
        # Phase 11.7 — composer-driven enrichment
        test_enrich_returns_message_unchanged_when_no_synthesis_title,
        test_enrich_returns_message_unchanged_when_no_past_responses,
        test_enrich_appends_footer_when_past_responses_exist,
        test_enrich_caps_at_max_recent,
        test_enrich_truncates_long_excerpts,
        # Phase 11.12 — captures during a practice window
        test_get_captures_during_practice_filters_by_window,
        test_get_captures_during_practice_returns_empty_for_invalid_date,
        # Phase 11.10 — morning capture resurface
        test_pick_capture_for_morning_resurface_returns_qualifying_capture,
        test_pick_capture_skips_already_resurfaced_within_cooldown,
        test_pick_capture_returns_oldest_qualifying_first,
        test_pick_capture_excludes_responses_dir,
        test_render_morning_capture_resurface_includes_excerpt_and_age,
        test_filename_is_local_date_stamped_and_slugged,
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
    print("All response_capture tests passed.")
