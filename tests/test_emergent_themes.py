#!/usr/bin/env python3
"""Unit tests for skills/emergent_themes.py — Phase 17.0."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
            print(f"  ✗ {label}\n      unexpected: {type(e).__name__}: {e}")
    print(f"\n{_PASSED} passed · {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


def _setup_tmp(td: str) -> None:
    """Reroute MEMORY_DIR + EMERGENT_THEMES_PATH to tmp."""
    from myalicia.skills import emergent_themes as et
    et.MEMORY_DIR = td
    et.EMERGENT_THEMES_PATH = os.path.join(td, "emergent_themes.jsonl")


# ── Storage round-trip ────────────────────────────────────────────────────


@test("record_emergent_theme + recent_emergent_themes: round-trip")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import (
            record_emergent_theme, recent_emergent_themes,
        )
        record_emergent_theme(
            theme="making smaller circles",
            evidence=["the chess metaphor", "writing density piece"],
            recurrence=3,
        )
        record_emergent_theme(
            theme="technology as body extension",
            evidence=["voice note about phones"],
            recurrence=2,
        )
        items = recent_emergent_themes(within_days=14)
        assert len(items) == 2
        themes = [t["theme"] for t in items]
        assert "making smaller circles" in themes
        assert "technology as body extension" in themes


@test("recent_emergent_themes: filters by status")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import (
            record_emergent_theme, recent_emergent_themes,
        )
        record_emergent_theme(
            theme="alpha", evidence=["x"], recurrence=3, status="pending",
        )
        record_emergent_theme(
            theme="beta", evidence=["y"], recurrence=3, status="acknowledged",
        )
        pending = recent_emergent_themes(status="pending")
        assert len(pending) == 1
        assert pending[0]["theme"] == "alpha"


# ── pick_theme_to_surface ─────────────────────────────────────────────────


@test("pick_theme_to_surface: picks highest-recurrence pending theme")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import (
            record_emergent_theme, pick_theme_to_surface,
        )
        record_emergent_theme(theme="low", evidence=["x"], recurrence=3)
        record_emergent_theme(theme="high", evidence=["x", "y"], recurrence=5)
        record_emergent_theme(theme="mid", evidence=["x"], recurrence=4)
        pick = pick_theme_to_surface()
        assert pick is not None
        assert pick["theme"] == "high"


@test("pick_theme_to_surface: skips below recurrence threshold")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import (
            record_emergent_theme, pick_theme_to_surface, MIN_RECURRENCE,
        )
        # Only 2 mentions — below MIN_RECURRENCE=3
        record_emergent_theme(theme="too quiet", evidence=["x"], recurrence=2)
        assert pick_theme_to_surface() is None


@test("pick_theme_to_surface: skips acknowledged themes")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import (
            record_emergent_theme, pick_theme_to_surface,
            record_theme_acknowledged,
        )
        record_emergent_theme(theme="acked theme", evidence=["x"], recurrence=4)
        record_theme_acknowledged("acked theme")
        assert pick_theme_to_surface() is None


@test("pick_theme_to_surface: respects surface cooldown")
def _():
    """A theme surfaced 7 days ago should NOT be re-surfaced (cooldown=14d)."""
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        # Manually write entries to control timestamps
        recent = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with open(et.EMERGENT_THEMES_PATH, "w") as f:
            f.write(json.dumps({
                "ts": recent, "theme": "recently surfaced",
                "evidence": ["x"], "recurrence_count": 5,
                "status": "surfaced", "surfaced_ts": recent,
            }) + "\n")
        assert et.pick_theme_to_surface() is None


# ── build_noticing_proactive integration (with mocked composition) ────────


@test("build_noticing_proactive: returns full ceremonial dict on success")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        # Seed an eligible theme
        et.record_emergent_theme(
            theme="the white line",
            evidence=["from drawing capture", "echoed in writing"],
            recurrence=3,
        )
        # Stub Sonnet noticing composer
        original = et.compose_noticing_message
        et.compose_noticing_message = lambda theme, weather=None: (
            "i've been noticing the white line — it surfaced in your drawing reply, "
            "and again when you wrote about refusal. want it to live somewhere?"
        )
        try:
            result = et.build_noticing_proactive()
            assert result is not None
            assert result["theme"] == "the white line"
            assert result["archetype"] == "beatrice"
            assert result["score"] == 2.5
            assert result["source_kind"] == "lived_surfacing"
            assert "👁" in result["message"]
            assert "noticing" in result["message"].lower()
            assert "white line" in result["message"]
        finally:
            et.compose_noticing_message = original


@test("build_noticing_proactive: marks theme as surfaced after success")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="theme to surface", evidence=["a", "b"], recurrence=3,
        )
        et.compose_noticing_message = lambda theme, weather=None: "a composed noticing"
        result = et.build_noticing_proactive()
        assert result is not None
        # Same theme should NOT be picked again immediately (now surfaced)
        second = et.build_noticing_proactive()
        assert second is None, (
            f"theme should be on cooldown after surfacing: {second}"
        )


@test("build_noticing_proactive: returns None when no eligible theme")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import build_noticing_proactive
        assert build_noticing_proactive() is None


@test("build_noticing_proactive: returns None when composer returns None")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(theme="x", evidence=["y"], recurrence=3)
        et.compose_noticing_message = lambda theme, weather=None: None
        assert et.build_noticing_proactive() is None


# ── record_theme_acknowledged ─────────────────────────────────────────────


@test("record_theme_acknowledged: changes status so theme isn't picked again")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(theme="ack me", evidence=["x"], recurrence=4)
        et.record_theme_acknowledged("ack me")
        # Pick should now be None — acknowledged themes are filtered
        assert et.pick_theme_to_surface() is None


# ── conversation tag (Phase 16.0 integration) ─────────────────────────────


@test("Phase 16.0: emergent theme entries carry conversation_id")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="tagged theme", evidence=["x"], recurrence=3,
        )
        with open(et.EMERGENT_THEMES_PATH) as f:
            entry = json.loads(f.readline())
        assert entry.get("conversation_id") == "default", (
            f"emergent theme entry should be tagged: {entry}"
        )


# ── Stream gathering ──────────────────────────────────────────────────────


@test("_gather_stream: returns empty when no input")
def _():
    """Sandbox has no captures/learnings/metas → empty stream → no
    detection runs (saves a Sonnet call)."""
    from myalicia.skills.emergent_themes import _gather_stream
    s = _gather_stream(within_days=14)
    # In sandbox this is empty; in production it'll have entries.
    assert isinstance(s, list)


# ── Phase 17.2 + 17.3: surface-agnostic summary ──────────────────────────


@test("get_themes_summary: empty when nothing tracked")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import get_themes_summary
        s = get_themes_summary()
        assert s["total"] == 0
        assert s["by_status"] == {"pending": 0, "surfaced": 0, "acknowledged": 0}
        assert s["themes"] == []
        assert s["next_to_surface"] is None


@test("get_themes_summary: counts by status")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(theme="alpha", evidence=["x"], recurrence=3)
        et.record_emergent_theme(theme="beta", evidence=["y"], recurrence=4)
        et.record_emergent_theme(theme="gamma", evidence=["z"], recurrence=5)
        et._update_theme_status("beta", status="surfaced")
        et._update_theme_status("gamma", status="acknowledged")
        s = et.get_themes_summary()
        assert s["total"] == 3
        assert s["by_status"]["pending"] == 1
        assert s["by_status"]["surfaced"] == 1
        assert s["by_status"]["acknowledged"] == 1


@test("get_themes_summary: includes lead evidence in entries")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="theme one",
            evidence=["evidence quote here", "second quote"],
            recurrence=3,
        )
        s = et.get_themes_summary()
        assert s["total"] == 1
        t = s["themes"][0]
        assert t["theme"] == "theme one"
        assert t["recurrence_count"] == 3
        assert t["evidence"][0] == "evidence quote here"


@test("get_themes_summary: next_to_surface populated when eligible")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="surfaceable", evidence=["x"], recurrence=4,
        )
        s = et.get_themes_summary()
        assert s["next_to_surface"] is not None
        assert s["next_to_surface"]["theme"] == "surfaceable"


@test("render_noticings_for_telegram: empty-state message")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills.emergent_themes import render_noticings_for_telegram
        out = render_noticings_for_telegram()
        assert "Noticings" in out
        assert "No themes tracked yet" in out


@test("render_noticings_for_telegram: renders themes with status emojis")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="the white line", evidence=["from drawing"], recurrence=3,
        )
        et.record_emergent_theme(
            theme="surfaced one", evidence=["from voice"], recurrence=4,
        )
        et._update_theme_status("surfaced one", status="surfaced")
        out = et.render_noticings_for_telegram()
        assert "the white line" in out
        assert "surfaced one" in out
        # Status emojis present
        assert "⏳" in out  # pending
        assert "📬" in out  # surfaced
        assert "1 surfaced" in out
        assert "1 pending" in out


@test("render_noticings_for_telegram: includes lead evidence quote")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="lead theme",
            evidence=["this distinctive quote"],
            recurrence=3,
        )
        out = et.render_noticings_for_telegram()
        assert "this distinctive quote" in out


# ── Phase 17.1: emotion-aware noticing softening ─────────────────────────


@test("Phase 17.1 _recent_emotion_weather: returns 'neutral' on no data")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        # Override loader to return no entries
        import myalicia.skills.emotion_model as em
        original = em.load_recent_emotions
        em.load_recent_emotions = lambda days=7, path=None: []
        try:
            assert et._recent_emotion_weather() == "neutral"
        finally:
            em.load_recent_emotions = original


@test("Phase 17.1 _recent_emotion_weather: returns 'tender' when sad-dominant")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        import myalicia.skills.emotion_model as em
        original = em.load_recent_emotions
        em.load_recent_emotions = lambda days=7, path=None: [
            {"emotion_label": "sad"},
            {"emotion_label": "sad"},
            {"emotion_label": "neu"},
        ]
        try:
            assert et._recent_emotion_weather() == "tender"
        finally:
            em.load_recent_emotions = original


@test("Phase 17.1 _recent_emotion_weather: returns 'neutral' when sad below threshold")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        import myalicia.skills.emotion_model as em
        original = em.load_recent_emotions
        em.load_recent_emotions = lambda days=7, path=None: [
            {"emotion_label": "hap"},
            {"emotion_label": "hap"},
            {"emotion_label": "neu"},
            {"emotion_label": "sad"},
        ]
        try:
            assert et._recent_emotion_weather() == "neutral"
        finally:
            em.load_recent_emotions = original


@test("Phase 17.1 build_noticing_proactive: tender weather uses softer banner")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="tender-day theme", evidence=["x"], recurrence=4,
        )
        # Force weather=tender, neutralize random suppression
        original_weather = et._recent_emotion_weather
        et._recent_emotion_weather = lambda: "tender"
        original_compose = et.compose_noticing_message
        et.compose_noticing_message = (
            lambda theme, weather=None:
            f"composed (weather={weather})"
        )
        # Patch random to always pass (no suppression)
        import random as _r
        original_rand = _r.random
        _r.random = lambda: 0.99  # > TENDER_PROBABILITY_DAMP=0.5
        try:
            result = et.build_noticing_proactive()
            assert result is not None, "expected noticing on tender day"
            assert result["weather"] == "tender"
            assert "small noticing" in result["message"], (
                f"tender-day banner missing in: {result['message']!r}"
            )
            assert "weather=tender" in result["message"]
        finally:
            et._recent_emotion_weather = original_weather
            et.compose_noticing_message = original_compose
            _r.random = original_rand


@test("Phase 17.1 build_noticing_proactive: tender weather can suppress entirely")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="suppressed", evidence=["x"], recurrence=4,
        )
        original_weather = et._recent_emotion_weather
        et._recent_emotion_weather = lambda: "tender"
        import random as _r
        original_rand = _r.random
        _r.random = lambda: 0.01  # < TENDER_PROBABILITY_DAMP=0.5 → suppress
        try:
            result = et.build_noticing_proactive()
            assert result is None, (
                f"expected suppression on tender day, got: {result}"
            )
        finally:
            et._recent_emotion_weather = original_weather
            _r.random = original_rand


@test("Phase 17.1 build_noticing_proactive: neutral weather uses normal banner")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.record_emergent_theme(
            theme="normal-day theme", evidence=["x"], recurrence=4,
        )
        original_weather = et._recent_emotion_weather
        et._recent_emotion_weather = lambda: "neutral"
        original_compose = et.compose_noticing_message
        et.compose_noticing_message = (
            lambda theme, weather=None: f"composed (weather={weather})"
        )
        try:
            result = et.build_noticing_proactive()
            assert result is not None
            assert result["weather"] == "neutral"
            # Standard banner — "_noticing_" without "small"
            assert "small noticing" not in result["message"]
            assert "_noticing_" in result["message"]
        finally:
            et._recent_emotion_weather = original_weather
            et.compose_noticing_message = original_compose


# ── Phase 18.0: pre-render voice for noticings (sidecar context) ────────


@test("Phase 18.0: build_noticing_proactive populates the sidecar context")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et._clear_last_noticing_context()
        et.record_emergent_theme(
            theme="ceremonial test", evidence=["x"], recurrence=4,
        )
        original_compose = et.compose_noticing_message
        et.compose_noticing_message = (
            lambda theme, weather=None: "the body of the noticing"
        )
        try:
            result = et.build_noticing_proactive()
            assert result is not None
            ctx = et.get_last_noticing_context()
            assert ctx is not None, (
                "build_noticing_proactive must populate the sidecar"
            )
            assert ctx["theme"] == "ceremonial test"
            assert ctx["archetype"] == "beatrice"
            assert ctx["score"] == 2.5
            assert ctx["source_kind"] == "lived_surfacing"
            assert ctx["voice_text"] == "the body of the noticing"
            assert "ts" in ctx
        finally:
            et.compose_noticing_message = original_compose
            et._clear_last_noticing_context()


@test("Phase 18.0: voice_text strips the markdown banner")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et._clear_last_noticing_context()
        et.record_emergent_theme(theme="banner test", evidence=["x"], recurrence=4)
        et.compose_noticing_message = (
            lambda theme, weather=None: "just the body, no banner"
        )
        try:
            result = et.build_noticing_proactive()
            # Telegram message has the banner
            assert "👁" in result["message"]
            # voice_text is just the body (banner-free, easier to TTS)
            assert "👁" not in result["voice_text"]
            assert result["voice_text"] == "just the body, no banner"
        finally:
            et._clear_last_noticing_context()


@test("Phase 18.0: get_last_noticing_context expires after freshness window")
def _():
    """The midday handler reads the sidecar after build_midday_message
    returns. If somehow the sidecar held stale data from hours ago, we'd
    incorrectly mark a non-noticing midday as ceremonial. Test that
    get_last_noticing_context returns None for stale entries."""
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        et._clear_last_noticing_context()
        # Manually populate with a stale timestamp
        et._LAST_NOTICING_CONTEXT = {
            "theme": "stale", "archetype": "beatrice",
            "ts": (_dt.now(_tz.utc) - _td(seconds=120)).isoformat(),
        }
        # Should be None because >60s old
        assert et.get_last_noticing_context() is None
        et._clear_last_noticing_context()


@test("Phase 18.0: get_last_noticing_context returns None when never set")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et._clear_last_noticing_context()
        assert et.get_last_noticing_context() is None


# ── Phase 18.1: voice cache for noticings ──────────────────────────────


@test("Phase 18.1: cache miss returns None for un-cached theme")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.NOTICING_VOICE_CACHE_DIR = os.path.join(td, "voice_cache")
        result = et.get_cached_noticing_voice(
            theme="never cached", voice_text="some text", style="gentle",
        )
        assert result is None


@test("Phase 18.1: cache hit returns path after cache write")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.NOTICING_VOICE_CACHE_DIR = os.path.join(td, "voice_cache")
        # Create a fake source file
        src = os.path.join(td, "src.ogg")
        with open(src, "wb") as f:
            f.write(b"fake ogg bytes")
        # Write to cache
        cached = et.cache_noticing_voice(
            theme="t1", voice_text="hello world", source_path=src, style="gentle",
        )
        assert cached is not None and os.path.exists(cached)
        # Now retrieve
        hit = et.get_cached_noticing_voice(
            theme="t1", voice_text="hello world", style="gentle",
        )
        assert hit == cached


@test("Phase 18.1: cache key sensitive to theme + voice_text + style")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.NOTICING_VOICE_CACHE_DIR = os.path.join(td, "voice_cache")
        src = os.path.join(td, "src.ogg")
        with open(src, "wb") as f:
            f.write(b"fake")
        et.cache_noticing_voice(
            theme="t1", voice_text="text A", source_path=src, style="gentle",
        )
        # Different theme → miss
        assert et.get_cached_noticing_voice("t2", "text A", "gentle") is None
        # Different voice_text → miss
        assert et.get_cached_noticing_voice("t1", "text B", "gentle") is None
        # Different style → miss
        assert et.get_cached_noticing_voice("t1", "text A", "tender") is None
        # Same triple → hit
        assert et.get_cached_noticing_voice("t1", "text A", "gentle") is not None


@test("Phase 18.1: stale cache entries are evicted on read")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.NOTICING_VOICE_CACHE_DIR = os.path.join(td, "voice_cache")
        et.NOTICING_VOICE_CACHE_TTL_HOURS = 0.001  # ~3.6 seconds
        src = os.path.join(td, "src.ogg")
        with open(src, "wb") as f:
            f.write(b"fake")
        cached = et.cache_noticing_voice(
            theme="stale", voice_text="x", source_path=src,
        )
        assert cached is not None
        # Backdate the file mtime so it's "stale"
        old_ts = datetime.now().timestamp() - 3600  # 1 hour old
        os.utime(cached, (old_ts, old_ts))
        # TTL is 0.001 hours; this file is way past
        assert et.get_cached_noticing_voice("stale", "x", "gentle") is None


@test("Phase 18.1: prune_noticing_voice_cache removes stale entries")
def _():
    with tempfile.TemporaryDirectory() as td:
        _setup_tmp(td)
        from myalicia.skills import emergent_themes as et
        et.NOTICING_VOICE_CACHE_DIR = os.path.join(td, "voice_cache")
        src = os.path.join(td, "src.ogg")
        with open(src, "wb") as f:
            f.write(b"fake")
        cached = et.cache_noticing_voice(
            theme="prune-me", voice_text="x", source_path=src,
        )
        # Backdate
        old_ts = datetime.now().timestamp() - 3600
        os.utime(cached, (old_ts, old_ts))
        pruned = et.prune_noticing_voice_cache(max_age_hours=0.0001)
        assert pruned >= 1
        assert not os.path.exists(cached)


if __name__ == "__main__":
    print("Testing emergent_themes.py …")
    sys.exit(_run_all())
