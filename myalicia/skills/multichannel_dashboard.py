#!/usr/bin/env python3
"""
Multi-channel observability dashboard — Phase 13.8.

Phases 13.3 and 13.7 introduced smart deciders for drawing and voice
amplification. Both write every decision (fire OR skip + path +
rationale) to memory/multi_channel_decisions.jsonl. Until now that log
has been write-only — there's no visible signal about whether the
deciders are actually doing what we want.

This module renders /multichannel: a compact Telegram dashboard
showing last-24h fire/skip rates by channel + path, top skip reasons,
saturation status, and the most recent skipped + most recent fired
items in each channel.

Public API:
    render_multichannel_dashboard(now=None) -> str
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("alicia.multichannel_dashboard")


# ── Section renderers ──────────────────────────────────────────────────────


def _channel_summary_section(
    channel: str,
    decisions: list[dict],
    *,
    fire_key: str,
    saturation_path: str,
) -> str:
    """Render the per-channel section: fire/skip totals + path breakdown."""
    if channel == "voice":
        rows = [d for d in decisions if d.get("channel") == "voice"]
    else:
        # Drawing entries don't have channel='drawing' (older format) —
        # they're identified by presence of 'archetype' + drawing key.
        # Phase 14.3 — explicitly exclude coherent_moment entries (which
        # ALSO carry drawing=True for the linked drawing) so they don't
        # double-count in the per-channel rollup. They get their own
        # section below.
        rows = [d for d in decisions
                if d.get("channel") not in ("voice", "coherent_moment")
                and d.get("drawing") is not None]

    if not rows:
        return f"*{channel.capitalize()}:* no decisions in last 24h"

    fired = sum(1 for r in rows if r.get(fire_key) is True)
    skipped = len(rows) - fired
    rate = (fired / len(rows) * 100.0) if rows else 0.0

    # Path breakdown
    path_counts: Counter[str] = Counter(
        r.get("path", "?") for r in rows
    )

    lines = [
        f"*{channel.capitalize()}:* {fired} fired · {skipped} skipped "
        f"({rate:.0f}% fire rate, {len(rows)} total)",
    ]
    # Saturation hint
    sat_count = path_counts.get(saturation_path, 0)
    if sat_count:
        lines.append(f"  ⚠️ saturation guard tripped {sat_count}×")

    # Top 3 paths
    top = path_counts.most_common(3)
    if top:
        path_bits = [f"{p}={n}" for p, n in top]
        lines.append("  paths: " + ", ".join(path_bits))
    return "\n".join(lines)


def _coherent_moments_section(decisions: list[dict]) -> str:
    """Phase 14.3 — surface coherent_moment counts separately.

    Phase 13.12 + 14.1 log a coherent_moment event when voice + drawing
    BOTH fire on the same content, with the bridged tail attached to
    the voice script. /multichannel was hiding these in the generic
    per-channel summary; this section makes them first-class.
    """
    coherent = [d for d in decisions if d.get("channel") == "coherent_moment"]
    if not coherent:
        return "*Coherent moments:* none in last 24h _(voice + drawing on same content)_"
    n = len(coherent)
    # Group by archetype to show which voices land coherent moments
    by_arch: dict[str, int] = {}
    for c in coherent:
        a = (c.get("archetype") or "?").capitalize()
        by_arch[a] = by_arch.get(a, 0) + 1
    arch_str = " · ".join(f"{k} {v}" for k, v in sorted(
        by_arch.items(), key=lambda kv: -kv[1]
    ))
    # Most recent rationale (the bridged tail itself) — proves it landed
    most_recent = sorted(coherent, key=lambda d: d.get("ts", ""), reverse=True)[0]
    tail = (most_recent.get("rationale") or "").strip()
    lines = [
        f"🎼 *Coherent moments:* {n} in last 24h _(voice + drawing as one)_",
        f"  by archetype: {arch_str}",
    ]
    if tail:
        lines.append(f"  _latest tail:_ \"{tail[:80]}\"")
    return "\n".join(lines)


def _top_skip_reasons_section(decisions: list[dict]) -> str:
    """Top skip rationales across both channels."""
    skips = [
        d for d in decisions
        if d.get("voice") is False or d.get("drawing") is False
    ]
    if not skips:
        return "*Top skip reasons:* — (no skips in last 24h)"
    reasons: Counter[str] = Counter()
    for d in skips:
        # Prefer path (compact) over rationale (verbose) for the chart
        reasons[d.get("path", "?")] += 1
    top = reasons.most_common(4)
    parts = [f"{p}×{n}" for p, n in top]
    return "*Top skip reasons:* " + ", ".join(parts)


def _recent_examples_section(decisions: list[dict]) -> str:
    """Most recent fired + most recent skipped, one of each channel."""
    # Decisions arrive newest-first when sorted by ts desc
    sorted_d = sorted(
        decisions, key=lambda d: d.get("ts", ""), reverse=True
    )
    examples: list[str] = ["*Recent decisions:*"]
    found = {"voice_fire": False, "voice_skip": False,
             "draw_fire": False, "draw_skip": False}
    for d in sorted_d:
        ts_full = d.get("ts", "")
        ts_short = ts_full[11:16] if len(ts_full) >= 16 else ts_full
        path = d.get("path", "?")
        rationale = (d.get("rationale", "") or "")[:60]
        if d.get("channel") == "voice":
            if d.get("voice") is True and not found["voice_fire"]:
                examples.append(f"  • {ts_short} 🎙️ FIRE _{path}_")
                found["voice_fire"] = True
            elif d.get("voice") is False and not found["voice_skip"]:
                examples.append(f"  • {ts_short} 🎙️ SKIP _{path}_ — {rationale}")
                found["voice_skip"] = True
        elif d.get("drawing") is True and not found["draw_fire"]:
            examples.append(f"  • {ts_short} 🎨 FIRE _{path}_")
            found["draw_fire"] = True
        elif d.get("drawing") is False and not found["draw_skip"]:
            examples.append(f"  • {ts_short} 🎨 SKIP _{path}_ — {rationale}")
            found["draw_skip"] = True
        if all(found.values()):
            break
    if len(examples) == 1:
        return ""  # no examples → suppress section entirely
    return "\n".join(examples)


# ── Main entry ────────────────────────────────────────────────────────────


def render_multichannel_dashboard(now: Optional[datetime] = None) -> str:
    """Compose the /multichannel Telegram message.

    Sections (each fault-tolerant):
      1. Header line
      2. Voice channel summary (fire/skip + paths + saturation)
      3. Drawing channel summary (same shape)
      4. Top skip reasons across both
      5. Recent fired/skipped examples (timestamped)
    """
    try:
        from myalicia.skills.multi_channel import (
            recent_multi_channel_decisions,
            VOICE_SATURATION_24H, SATURATION_24H,
        )
    except Exception as e:
        return f"⚠️ /multichannel error: import failed ({e})"

    try:
        decisions = recent_multi_channel_decisions(within_hours=24)
    except Exception as e:
        return f"⚠️ /multichannel error: log read failed ({e})"

    if not decisions:
        return (
            "🎛️ *Multichannel — last 24h*\n\n"
            "_No decisions logged yet._ The smart deciders write to "
            "`memory/multi_channel_decisions.jsonl` on every proactive "
            "send. Will populate after the next morning/midday/evening."
        )

    voice_section = _channel_summary_section(
        "voice", decisions,
        fire_key="voice", saturation_path="saturation_guard",
    )
    drawing_section = _channel_summary_section(
        "drawing", decisions,
        fire_key="drawing", saturation_path="saturation_guard",
    )
    coherent_section = _coherent_moments_section(decisions)
    skip_section = _top_skip_reasons_section(decisions)
    examples_section = _recent_examples_section(decisions)

    parts = [
        "🎛️ *Multichannel — last 24h*",
        "",
        voice_section,
        f"  _saturation cap: {VOICE_SATURATION_24H}/24h_",
        "",
        drawing_section,
        f"  _saturation cap: {SATURATION_24H}/24h_",
        "",
        coherent_section,
        "",
        skip_section,
    ]
    if examples_section:
        parts.append("")
        parts.append(examples_section)
    return "\n".join(parts)


if __name__ == "__main__":
    print(render_multichannel_dashboard())
