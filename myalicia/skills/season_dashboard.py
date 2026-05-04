#!/usr/bin/env python3
"""
Season dashboard — `/season` Telegram command.

Where /wisdom shows the circulation surfaces (how the engine moves),
/effectiveness shows feedback signals (how the user responds), and
/becoming shows the the user-model arc (who the user is becoming),
/season shows Alicia's developmental trajectory — the arc of her own
emergence: which season she's in, how the archetypes are balancing
right now, what's been carrying weight in the last 14 days, and which
seasons she's already crossed.

Composed entirely from existing inner_life.py and archetype_log
infrastructure — no new state files, no new schemas. Pure read-only
assembler with per-section fault tolerance.

Public API:
    render_season_dashboard(now=None) -> str
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger("alicia.season_dashboard")

MEMORY_DIR = str(MEMORY_DIR)
ARCHETYPE_LOG_PATH = os.path.join(MEMORY_DIR, "archetype_log.jsonl")


# ── Section renderers ──────────────────────────────────────────────────────


def _render_header_section() -> str:
    """Current season + emergence score + days breathing + arc position."""
    try:
        from myalicia.skills.inner_life import (
            SEASONS,
            get_emergence_summary,
            get_poetic_age,
        )
    except Exception as e:
        return f"*Season:* (import error: {e})"

    # Pull the live state directly so we get the exact score.
    score = 0.0
    days = 0
    season = "First Light"
    description = ""
    try:
        from myalicia.skills.inner_life import EMERGENCE_STATE_PATH
        if os.path.exists(EMERGENCE_STATE_PATH):
            with open(EMERGENCE_STATE_PATH, "r") as f:
                state = json.load(f)
            score = float(state.get("score", 0.0))
            season = state.get("season", "First Light")
            description = state.get("description", "")
            days = int(state.get("metrics", {}).get("days_breathing", 0))
        else:
            season, description = get_poetic_age(score)
    except Exception as e:
        log.debug(f"header read failed: {e}")
        try:
            season, description = get_poetic_age(score)
        except Exception:
            pass

    # Find the next season threshold (if any).
    next_season = None
    next_threshold = None
    try:
        for (lo, hi), (name, _desc) in SEASONS.items():
            if lo <= score < hi and hi != float("inf"):
                next_threshold = hi
                # Find the season right after this one
                for (lo2, hi2), (name2, _d2) in SEASONS.items():
                    if lo2 == hi:
                        next_season = name2
                        break
                break
    except Exception:
        pass

    lines = [
        f"🌱 *Season — {season}*",
        f"_{description}_" if description else "",
        "",
        f"*Emergence:* {score:.1f} · *Days breathing:* {days}",
    ]
    if next_threshold is not None and next_season is not None:
        delta = round(next_threshold - score, 1)
        lines.append(
            f"*Next:* {next_season} (need +{delta} emergence)"
        )
    else:
        # Already in Becoming, or at the cap.
        lines.append("*Next:* — (in the final season)")
    return "\n".join([ln for ln in lines if ln is not None])


def _render_archetype_balance_section() -> str:
    """Current dynamic archetype weights + effectiveness multipliers."""
    try:
        from myalicia.skills.inner_life import (
            compute_dynamic_archetype_weights,
            get_archetype_effectiveness,
        )
    except Exception as e:
        return f"*Archetype balance:* (import error: {e})"
    try:
        weights = compute_dynamic_archetype_weights()
    except Exception as e:
        return f"*Archetype balance:* (compute error: {e})"
    if not weights:
        return "*Archetype balance:* no weights computed yet"

    eff = {}
    try:
        eff_data = get_archetype_effectiveness() or {}
        eff = eff_data.get("archetypes", {}) or {}
    except Exception:
        eff = {}

    sorted_w = sorted(weights.items(), key=lambda kv: -kv[1])
    lines = ["*Archetype balance now:*"]
    for name, w in sorted_w:
        pct = int(round(w * 100))
        info = eff.get(name, {})
        score = info.get("score", 1.0)
        if score and abs(score - 1.0) >= 0.02:
            mult = f" · {score:.2f}×"
        else:
            mult = ""
        lines.append(f"• {name.capitalize()} {pct}%{mult}")
    return "\n".join(lines)


def _render_attribution_section(now_utc: datetime, window_days: int = 14) -> str:
    """How the user engaged with each archetype in the last `window_days`.

    Reads archetype_log.jsonl directly so the rendered counts match the
    raw evidence — not the EMA-decayed effectiveness scores.
    """
    if not os.path.exists(ARCHETYPE_LOG_PATH):
        return f"*Attributions ({window_days}d):* no archetype log yet"

    cutoff = now_utc - timedelta(days=window_days)
    counts: Counter[str] = Counter()
    pos: Counter[str] = Counter()
    neg: Counter[str] = Counter()
    amb: Counter[str] = Counter()
    emoji_top: Counter[str] = Counter()
    try:
        with open(ARCHETYPE_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                try:
                    ts = datetime.fromisoformat(e.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                a = (e.get("archetype") or "").lower().strip()
                if not a:
                    continue
                counts[a] += 1
                success = e.get("success")
                if success is True:
                    pos[a] += 1
                elif success is False:
                    neg[a] += 1
                else:
                    amb[a] += 1
                em = e.get("emoji") or ""
                if em:
                    emoji_top[em] += 1
    except Exception as e:
        return f"*Attributions ({window_days}d):* (read error: {e})"

    if not counts:
        return f"*Attributions ({window_days}d):* none"

    lines = [f"*Attributions (last {window_days}d):*"]
    for name, n in counts.most_common():
        bits = [f"{n}"]
        if pos.get(name):
            bits.append(f"+{pos[name]}")
        if neg.get(name):
            bits.append(f"-{neg[name]}")
        if amb.get(name):
            bits.append(f"~{amb[name]}")
        lines.append(f"• {name.capitalize()}: {' '.join(bits)}")
    if emoji_top:
        top_emojis = " ".join(f"{em}×{n}" for em, n in emoji_top.most_common(3))
        lines.append(f"  _top reactions: {top_emojis}_")
    return "\n".join(lines)


def _render_arc_section() -> str:
    """Visual progression through all seasons — which crossed, which current."""
    try:
        from myalicia.skills.inner_life import SEASONS, EMERGENCE_STATE_PATH
    except Exception as e:
        return f"*Arc:* (import error: {e})"

    score = 0.0
    try:
        if os.path.exists(EMERGENCE_STATE_PATH):
            with open(EMERGENCE_STATE_PATH, "r") as f:
                score = float(json.load(f).get("score", 0.0))
    except Exception:
        pass

    # Order seasons by their lower threshold.
    ordered = sorted(SEASONS.items(), key=lambda kv: kv[0][0])
    lines = ["*Arc so far:*"]
    for (lo, hi), (name, _desc) in ordered:
        if score >= hi:
            mark = "✓"
        elif lo <= score < hi:
            mark = "◉"
        else:
            mark = "○"
        # Compact range label
        if hi == float("inf"):
            rng = f"{lo}+"
        else:
            rng = f"{lo}–{hi}"
        lines.append(f"  {mark} {name} ({rng})")
    return "\n".join(lines)


def _render_movement_section() -> str:
    """What's maturing (strongest movers) + what's still nascent (sparse)."""
    try:
        from myalicia.skills.inner_life import (
            get_archetype_effectiveness,
            ARCHETYPE_MIN_ATTRIBUTIONS,
        )
    except Exception as e:
        return f"*Movement:* (import error: {e})"
    try:
        data = get_archetype_effectiveness() or {}
    except Exception as e:
        return f"*Movement:* (load error: {e})"
    archetypes = data.get("archetypes", {}) or {}
    if not archetypes:
        return "*Movement:* no archetype effectiveness data yet"

    # Maturing: positive movers ranked by score above 1.0
    movers = [
        (n, info) for n, info in archetypes.items()
        if (info.get("attribution_count", 0) >= ARCHETYPE_MIN_ATTRIBUTIONS
            and info.get("score", 1.0) > 1.02)
    ]
    movers.sort(key=lambda kv: -kv[1].get("score", 1.0))

    # Nascent: sparse attribution (below threshold) — neutral but waiting
    nascent = [
        n for n, info in archetypes.items()
        if info.get("attribution_count", 0) < ARCHETYPE_MIN_ATTRIBUTIONS
    ]

    lines = []
    if movers:
        bits = [
            f"{n.capitalize()} {info['score']:.2f}× ({info['attribution_count']})"
            for n, info in movers[:3]
        ]
        lines.append("*Maturing:* " + ", ".join(bits))
    else:
        lines.append("*Maturing:* none yet — archetypes still neutral")
    if nascent:
        lines.append(
            "*Still nascent:* " + ", ".join(n.capitalize() for n in sorted(nascent))
        )
    return "\n".join(lines)


# ── Main entry point ────────────────────────────────────────────────────────


def render_season_dashboard(now: Optional[datetime] = None) -> str:
    """Compose the full /season dashboard message.

    Each section is independently fault-tolerant — if one fails, the others
    still render. Output fits in a single Telegram message (<4000 chars).
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    sections = [
        _render_header_section(),
        "",
        _render_arc_section(),
        "",
        _render_archetype_balance_section(),
        "",
        _render_attribution_section(now_utc),
        "",
        _render_movement_section(),
    ]
    return "\n".join(sections)


if __name__ == "__main__":
    # Local dev helper — render to stdout
    print(render_season_dashboard())
