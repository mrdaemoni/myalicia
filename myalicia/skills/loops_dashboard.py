#!/usr/bin/env python3
"""
Loops meta-dashboard — Phase 14.0.

Six dashboards now exist, each showing one slice of the system:
  /wisdom         circulation surfaces
  /effectiveness  feedback signals
  /becoming       the user's arc
  /season         Alicia's arc
  /metasynthesis  meta-synthesis candidates
  /multichannel   smart-decider observability

What's missing: a single view of the four CLOSED LOOPS that connect
those surfaces into one circulatory system. /loops fills that gap.

Loop 1 — Inner reply (Phase 11):
    capture → re-surface (with past-response footer)
Loop 2 — Meta-synthesis (Phase 13.6 + 13.10):
    capture → ≥3 captures on parent → meta-synthesis (level 1-3)
Loop 3 — Gap-driven outbound (Phase 12 + 12.4):
    message → learning → dim tracker → gap → question → research escalation
Loop 4 — Thread-pull bridge (Phase 13.5 + 13.11):
    Sunday Open Thread → midday pull → reply → advanced thread

Plus three connection points (Phase 13.9, Phase 13.12, etc.) that make
this a nervous system rather than four parallel rings.

Public API:
    render_loops_dashboard(now=None) -> str
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger("alicia.loops_dashboard")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(str(MEMORY_DIR))
RESPONSES_DIR = VAULT_ROOT / "writing" / "Responses"
CAPTURES_DIR = VAULT_ROOT / "writing" / "Captures"


# ── Phase 14.5 — Week-over-week delta helper ───────────────────────────────


def _wow_delta(this_week: int, last_week: int) -> str:
    """Return a compact week-over-week delta indicator.

    ↑+N when growing, ↓-N when shrinking, → unchanged when same nonzero,
    empty string when both weeks are zero (no signal worth showing)."""
    if this_week == 0 and last_week == 0:
        return ""
    delta = this_week - last_week
    if delta > 0:
        return f" ↑+{delta}"
    if delta < 0:
        return f" ↓{delta}"
    return " →"


# ── Phase 14.7 — Dormancy detection ─────────────────────────────────────────

DORMANCY_THRESHOLD_DAYS = 21  # ≥3 weeks silent → flag as dormant


def _days_since(ts_str: str) -> Optional[int]:
    """Return whole days since the ISO timestamp `ts_str`, or None on error."""
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - ts).total_seconds() / 86400)
    except Exception:
        return None


def _dormancy_signal(latest_iso: Optional[str]) -> str:
    """Render a compact 'last activity' signal.

    None → first-time message. days < threshold → empty (no flag).
    days >= threshold → '⚠️ dormant for N days' so it's impossible to miss."""
    if not latest_iso:
        return ""  # No activity ever — likely a new system, not 'dormant'
    days = _days_since(latest_iso)
    if days is None:
        return ""
    if days >= DORMANCY_THRESHOLD_DAYS:
        return f"\n  ⚠️ _dormant for {days} days_"
    return ""


def _latest_capture_ts() -> Optional[str]:
    """Most recent capture timestamp, or None."""
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = get_recent_captures(n=10)
        if not recent:
            return None
        # captured_at field carries ISO ts; pick max
        ts = [c.get("captured_at", "") for c in recent if c.get("captured_at")]
        return max(ts) if ts else None
    except Exception:
        return None


def _latest_meta_synthesis_ts() -> Optional[str]:
    """Most recent meta-synthesis build, or None."""
    try:
        from myalicia.skills.meta_synthesis import recent_meta_syntheses
        recent = recent_meta_syntheses(within_days=365)
        if not recent:
            return None
        ts = [r.get("ts", "") for r in recent if r.get("ts")]
        return max(ts) if ts else None
    except Exception:
        return None


def _latest_dimension_question_ts() -> Optional[str]:
    """Most recent dimension question asked, or None."""
    try:
        from myalicia.skills.dimension_research import recent_dimension_questions
        recent = recent_dimension_questions(within_days=365)
        if not recent:
            return None
        ts = [r.get("ts", "") for r in recent if r.get("ts")]
        return max(ts) if ts else None
    except Exception:
        return None


def _latest_thread_pull_ts() -> Optional[str]:
    """Most recent thread-pull (not reply), or None."""
    try:
        from myalicia.skills.thread_puller import recent_thread_pulls
        recent = recent_thread_pulls(within_days=365)
        if not recent:
            return None
        ts = [r.get("ts", "") for r in recent if r.get("ts")]
        return max(ts) if ts else None
    except Exception:
        return None


# ── Phase 14.8 — Dormancy alert system ─────────────────────────────────────


DORMANCY_ALERTS_PATH = MEMORY_DIR / "dormancy_alerts.jsonl"

# Loop name → ts-getter mapping. Stable identifiers used in alert log.
_LOOP_LATEST_GETTERS = {
    "inner_reply":      _latest_capture_ts,
    "meta_synthesis":   _latest_meta_synthesis_ts,
    "gap_driven":       _latest_dimension_question_ts,
    "thread_pull":      _latest_thread_pull_ts,
}

_LOOP_LABELS = {
    "inner_reply":      "Inner reply (capture → re-surface)",
    "meta_synthesis":   "Meta-synthesis (≥3 captures → distillation)",
    "gap_driven":       "Gap-driven outbound (silent dim → question)",
    "thread_pull":      "Thread-pull (Sunday Open Threads → midday)",
}


def detect_dormant_loops() -> list[dict]:
    """Return a list of loops that have been dormant >=DORMANCY_THRESHOLD_DAYS.

    Each entry: {loop, days_dormant, last_activity_ts, label}.
    Loops with no activity ever (None ts) are NOT included — those are
    cold-start, not dormancy.
    """
    out: list[dict] = []
    for loop, getter in _LOOP_LATEST_GETTERS.items():
        try:
            latest = getter()
        except Exception:
            continue
        if not latest:
            continue
        days = _days_since(latest)
        if days is None or days < DORMANCY_THRESHOLD_DAYS:
            continue
        out.append({
            "loop": loop,
            "days_dormant": days,
            "last_activity_ts": latest,
            "label": _LOOP_LABELS.get(loop, loop),
        })
    return out


def record_dormancy_alert(loop: str, days: int) -> None:
    """Append a dormancy alert event so we can suppress repeats."""
    if not loop:
        return
    try:
        import os as _os
        _os.makedirs(str(MEMORY_DIR), exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "loop": loop,
            "days_dormant": int(days),
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(str(DORMANCY_ALERTS_PATH), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_dormancy_alert failed: {e}")


def recent_dormancy_alerts(within_days: int = 30) -> list[dict]:
    """Return alerts newer than `within_days`."""
    if not DORMANCY_ALERTS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(str(DORMANCY_ALERTS_PATH), "r", encoding="utf-8") as f:
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
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_dormancy_alerts failed: {e}")
    return out


def unalerted_dormant_loops() -> list[dict]:
    """Return dormant loops that haven't been alerted on in the last 30 days.

    Suppression window matches the assumed length of any single dormancy
    period — once we alert, we don't re-alert until either activity
    resumes (and dormancy clears) or a month passes.
    """
    dormant = detect_dormant_loops()
    if not dormant:
        return []
    recent_alerts = recent_dormancy_alerts(within_days=30)
    already_alerted = {a.get("loop") for a in recent_alerts}
    return [d for d in dormant if d["loop"] not in already_alerted]


# ── Phase 14.9 — Active streak counter ─────────────────────────────────────


def _compute_active_streak_weeks(timestamps: list[str]) -> int:
    """Return the number of consecutive most-recent weeks that contain
    at least one activity timestamp.

    A week is a 7-day window from now (week 0 = last 7 days). Walks
    weeks 0, 1, 2, ... outward; stops at the first empty week. Returns
    0 if there's no activity in the current week (because then the
    streak isn't ongoing — Phase 14.7 dormancy covers that case)."""
    if not timestamps:
        return 0
    now = datetime.now(timezone.utc)
    parsed: list[datetime] = []
    for s in timestamps:
        try:
            ts = datetime.fromisoformat(s)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            parsed.append(ts)
        except Exception:
            continue
    if not parsed:
        return 0

    streak = 0
    while True:
        window_end = now - timedelta(days=streak * 7)
        window_start = now - timedelta(days=(streak + 1) * 7)
        # Any timestamp in [window_start, window_end)?
        has_activity = any(
            window_start <= t < window_end for t in parsed
        )
        if not has_activity:
            break
        streak += 1
        # Safety stop — we don't store more than ~365 days of history
        # and infinite streaks aren't a real outcome we'd see.
        if streak > 52:
            break
    return streak


def _all_capture_timestamps(within_days: int = 90) -> list[str]:
    """Pull capture timestamps from response_capture for streak math."""
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = get_recent_captures(n=500)
        cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
        out: list[str] = []
        for c in recent:
            ts_str = c.get("captured_at", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    out.append(ts_str)
            except Exception:
                continue
        return out
    except Exception:
        return []


def _all_meta_synthesis_timestamps(within_days: int = 90) -> list[str]:
    try:
        from myalicia.skills.meta_synthesis import recent_meta_syntheses
        return [r.get("ts", "") for r in recent_meta_syntheses(within_days=within_days) if r.get("ts")]
    except Exception:
        return []


def _all_dimension_question_timestamps(within_days: int = 90) -> list[str]:
    try:
        from myalicia.skills.dimension_research import recent_dimension_questions
        return [r.get("ts", "") for r in recent_dimension_questions(within_days=within_days) if r.get("ts")]
    except Exception:
        return []


def _all_thread_pull_timestamps(within_days: int = 90) -> list[str]:
    try:
        from myalicia.skills.thread_puller import recent_thread_pulls
        return [r.get("ts", "") for r in recent_thread_pulls(within_days=within_days) if r.get("ts")]
    except Exception:
        return []


def _streak_signal(timestamps: list[str]) -> str:
    """Render a 'streak: N weeks' signal, or empty when streak < 2 weeks.

    Single-week activity is just normal cadence, not noteworthy.
    Two+ consecutive weeks crosses into "this loop has been carrying
    momentum" — that's worth surfacing."""
    streak = _compute_active_streak_weeks(timestamps)
    if streak < 2:
        return ""
    return f"  🔥 _active streak: {streak} weeks running_"


def render_dormancy_alert_message(dormant: list[dict]) -> str:
    """Render a single Telegram message announcing dormancy event(s)."""
    if not dormant:
        return ""
    if len(dormant) == 1:
        d = dormant[0]
        return (
            f"⚠️ *Loop went dormant*\n\n"
            f"_{d['label']}_ has had no activity for {d['days_dormant']} days.\n\n"
            f"Run `/loops` to see the full state."
        )
    lines = ["⚠️ *Multiple loops dormant*\n"]
    for d in dormant:
        lines.append(f"• _{d['label']}_ — {d['days_dormant']} days quiet")
    lines.append("\nRun `/loops` to see the full state.")
    return "\n".join(lines)


# ── Section renderers ──────────────────────────────────────────────────────


def _loop1_inner_reply() -> str:
    """Capture → re-surface (Phase 11). Shows recent capture rate + most-
    responded synthesis (the next likely meta candidate)."""
    try:
        from myalicia.skills.response_capture import (
            get_recent_captures, most_responded_syntheses,
        )
    except Exception as e:
        return f"*1. Inner reply:* (import error: {e})"

    try:
        # Pull a generous window so we can compute both this-week and last-week
        recent = get_recent_captures(n=200)
    except Exception as e:
        return f"*1. Inner reply:* (load error: {e})"

    # Count captures in last 7 days vs the 7-14d window before that
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    week_count = 0
    last_week_count = 0
    for c in recent:
        try:
            ts = datetime.fromisoformat(c.get("captured_at", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= week_ago:
                week_count += 1
            elif ts >= two_weeks_ago:
                last_week_count += 1
        except Exception:
            pass

    lines = [
        "*1. Inner reply* — capture → re-surface",
        f"  • {week_count} captures in last 7d{_wow_delta(week_count, last_week_count)}",
    ]
    try:
        top = most_responded_syntheses(n=3)
        if top:
            top_lines = [f"{title[:60]} ({n})" for title, n in top]
            lines.append("  • most-responded: " + " · ".join(top_lines))
    except Exception:
        pass
    # Phase 14.7 — dormancy alert
    dorm = _dormancy_signal(_latest_capture_ts())
    if dorm:
        lines.append(dorm.lstrip("\n"))
    # Phase 14.9 — active streak (positive signal)
    streak = _streak_signal(_all_capture_timestamps())
    if streak:
        lines.append(streak)
    return "\n".join(lines)


def _loop2_meta_synthesis() -> str:
    """≥3 captures → meta-synthesis (Phase 13.6 + 13.10).
    Shows candidates ready, recent meta builds, current max recursion level."""
    try:
        from myalicia.skills.meta_synthesis import (
            candidates_for_meta_synthesis, recent_meta_syntheses,
            MAX_META_LEVEL, get_synthesis_level,
        )
    except Exception as e:
        return f"*2. Meta-synthesis:* (import error: {e})"

    try:
        cands = candidates_for_meta_synthesis()
    except Exception as e:
        return f"*2. Meta-synthesis:* (candidates error: {e})"
    try:
        # Pull 14d to compute this-week + last-week
        recent_14d = recent_meta_syntheses(within_days=14)
        recent = recent_meta_syntheses(within_days=30)  # for the long-window stat
    except Exception:
        recent_14d = []
        recent = []

    # Split 14d window into this-week (0-7) vs last-week (7-14)
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    builds_this_week = 0
    builds_last_week = 0
    for entry in recent_14d:
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= week_ago:
                builds_this_week += 1
            else:
                builds_last_week += 1
        except Exception:
            pass

    lines = [
        "*2. Meta-synthesis* — captures → distillation (level 1-3)",
        f"  • {len(cands)} candidate(s) ready · "
        f"{builds_this_week} built this week"
        f"{_wow_delta(builds_this_week, builds_last_week)}"
        f" · {len(recent)} in last 30d",
    ]
    if cands:
        top_cand = cands[0]
        lines.append(
            f"  • next: _{top_cand['title'][:60]}_ "
            f"({top_cand['capture_count']} captures)"
        )
    # Show current max recursion level achieved
    if recent:
        max_level_seen = 0
        for entry in recent:
            try:
                p = Path(entry.get("child_path", ""))
                if p.exists():
                    text = p.read_text(encoding="utf-8")
                    lvl = get_synthesis_level(text)
                    max_level_seen = max(max_level_seen, lvl)
            except Exception:
                continue
        if max_level_seen > 0:
            lines.append(
                f"  • deepest level reached: {max_level_seen}/{MAX_META_LEVEL}"
            )
    # Phase 14.7 — dormancy alert (only flag when ≥1 build has ever happened
    # AND it was >=21d ago; if no builds ever, that's a normal cold-start, not
    # dormancy worth alerting on)
    dorm = _dormancy_signal(_latest_meta_synthesis_ts())
    if dorm:
        lines.append(dorm.lstrip("\n"))
    # Phase 14.9 — active streak
    streak = _streak_signal(_all_meta_synthesis_timestamps())
    if streak:
        lines.append(streak)
    return "\n".join(lines)


def _loop3_gap_driven() -> str:
    """thin dim → question → research escalation (Phase 12 + 12.4)."""
    try:
        from myalicia.skills.dimension_research import (
            recent_dimension_questions, recent_dimension_scans,
            recent_escalations, get_persistent_thin_dimensions,
        )
        from myalicia.skills.user_model import find_thin_dimensions
    except Exception as e:
        return f"*3. Gap-driven outbound:* (import error: {e})"

    try:
        thin_now = find_thin_dimensions(stale_after_days=14)
    except Exception:
        thin_now = []
    try:
        # Phase 14.5 — pull 14d so we can split this-week vs last-week
        questions_14d = recent_dimension_questions(within_days=14)
        questions_7d = recent_dimension_questions(within_days=7)
    except Exception:
        questions_14d = []
        questions_7d = []
    try:
        escalations_30d = recent_escalations(within_days=30)
    except Exception:
        escalations_30d = []
    try:
        persistent = get_persistent_thin_dimensions()
    except Exception:
        persistent = []

    lines = [
        "*3. Gap-driven outbound* — silent dim → question → research",
        f"  • {len(thin_now)} thin dim(s) right now: "
        f"{', '.join(thin_now[:5]) if thin_now else '—'}"
    ]
    # Phase 14.5 — week-over-week delta on question volume
    qs_this_week_n = len(questions_7d)
    qs_last_week_n = max(0, len(questions_14d) - len(questions_7d))
    if questions_7d:
        dims = [q.get("dimension", "?") for q in questions_7d]
        lines.append(
            f"  • {qs_this_week_n} asked in last 7d"
            f"{_wow_delta(qs_this_week_n, qs_last_week_n)}: "
            f"{', '.join(set(dims))}"
        )
    elif qs_last_week_n > 0:
        lines.append(
            f"  • 0 asked in last 7d{_wow_delta(0, qs_last_week_n)} "
            f"(silence after activity last week)"
        )
    if persistent:
        lines.append(
            f"  ⚠️ persistent (≥2 scans): {', '.join(persistent)} "
            f"→ escalation eligible"
        )
    if escalations_30d:
        ok_ones = [e for e in escalations_30d if e.get("status") == "ok"]
        lines.append(
            f"  • {len(ok_ones)} research brief(s) in last 30d"
        )
    # Phase 14.7 — dormancy alert (last question asked >= threshold ago)
    dorm = _dormancy_signal(_latest_dimension_question_ts())
    if dorm:
        lines.append(dorm.lstrip("\n"))
    # Phase 14.9 — active streak
    streak = _streak_signal(_all_dimension_question_timestamps())
    if streak:
        lines.append(streak)
    return "\n".join(lines)


def _loop4_thread_pull() -> str:
    """Sunday Open Thread → midday pull → reply → advanced (Phase 13.5+13.11)."""
    try:
        from myalicia.skills.thread_puller import (
            recent_thread_pulls, recent_thread_pull_replies,
            advanced_threads,
        )
    except Exception as e:
        return f"*4. Thread-pull:* (import error: {e})"

    try:
        pulls_14d = recent_thread_pulls(within_days=14)
        pulls_7d = recent_thread_pulls(within_days=7)
    except Exception:
        pulls_14d = []
        pulls_7d = []
    try:
        replies_14d = recent_thread_pull_replies(within_days=14)
        replies_7d = recent_thread_pull_replies(within_days=7)
    except Exception:
        replies_14d = []
        replies_7d = []
    try:
        advanced = advanced_threads(within_days=14)
    except Exception:
        advanced = []

    # Phase 14.5 — week-over-week deltas for both pulls and replies
    pulls_this = len(pulls_7d)
    pulls_last = max(0, len(pulls_14d) - pulls_this)
    replies_this = len(replies_7d)
    replies_last = max(0, len(replies_14d) - replies_this)
    rate = (replies_this / pulls_this * 100.0) if pulls_this else 0.0

    lines = [
        "*4. Thread-pull* — Sunday Open Threads → midday → reply → advance",
        f"  • {pulls_this} pull(s){_wow_delta(pulls_this, pulls_last)} · "
        f"{replies_this} reply(ies){_wow_delta(replies_this, replies_last)} "
        f"({rate:.0f}% reply rate, this week)",
    ]
    if advanced:
        top = advanced[0]
        lines.append(
            f"  • most advanced: _{top['thread_summary'][:60]}_ "
            f"({top['reply_count']} replies)"
        )
    # Phase 14.7 — dormancy alert (no thread-pull fired for >= threshold)
    dorm = _dormancy_signal(_latest_thread_pull_ts())
    if dorm:
        lines.append(dorm.lstrip("\n"))
    # Phase 14.9 — active streak
    streak = _streak_signal(_all_thread_pull_timestamps())
    if streak:
        lines.append(streak)
    return "\n".join(lines)


def _topology_section() -> str:
    """Phase 13.16 — static ASCII diagram of the four closed loops +
    five connection points. Same shape that's documented in PIPELINE_AUDIT;
    surfacing it inline in /loops makes the architecture visible at a glance.
    """
    return (
        "*Topology:*\n"
        "```\n"
        "    capture ──┬─→ re-surface          [Loop 1: Phase 11]\n"
        "              ├─→ ≥3 → meta-synthesis [Loop 2: 13.6/13.10]\n"
        "              │           ↓\n"
        "              │      bridge [13.9]\n"
        "              │           ↓\n"
        "  message ──→ learning → /becoming\n"
        "                  ↓\n"
        "                gap → question         [Loop 3: 12.2]\n"
        "                  ↓ (persistent)\n"
        "                research               [12.4]\n"
        "\n"
        "  Sunday profile → midday pull → reply [Loop 4: 13.5/13.11]\n"
        "                                  ↓\n"
        "                            advanced thread\n"
        "```"
    )


def _connection_points_section() -> str:
    """Show how many cross-loop signals fired recently — proof the system
    is stitched, not just running parallel rings."""
    counts = {
        "13.9 meta→user": 0,
        "13.11 thread→advance": 0,
        "13.12 voice+drawing": 0,
    }
    # 13.9 — count meta_synthesis-sourced learnings in user_learnings.jsonl
    try:
        from myalicia.skills.user_model import get_learnings
        recent_learnings = get_learnings(since_days=30)
        counts["13.9 meta→user"] = sum(
            1 for L in recent_learnings
            if (L.get("source") or "").startswith("meta_synthesis:")
        )
    except Exception:
        pass
    # 13.11 — count reply records in thread_pulls.jsonl in last 14d
    try:
        from myalicia.skills.thread_puller import recent_thread_pull_replies
        counts["13.11 thread→advance"] = len(
            recent_thread_pull_replies(within_days=14)
        )
    except Exception:
        pass
    # 13.12 — count coherent_moment entries in last 7d
    try:
        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        recents = recent_multi_channel_decisions(within_hours=24*7)
        counts["13.12 voice+drawing"] = sum(
            1 for d in recents if d.get("channel") == "coherent_moment"
        )
    except Exception:
        pass

    parts = [f"{n} {k}" for k, n in counts.items()]
    return "*Cross-loop signals (recent):* " + " · ".join(parts)


# ── Phase 15.0a — state/renderer split ────────────────────────────────────
#
# compute_loops_state() returns a structured dict — the canonical contract
# for any presentation surface (Telegram, web, iOS, watch glance, ...).
# render_loops_dashboard() is the Telegram-flavored markdown renderer that
# composes existing per-section helpers; it's preserved exactly as before
# so all callers keep working without change.


def compute_loops_state(now: Optional[datetime] = None) -> dict:
    """Return all the structured data /loops shows, in one dict.

    Surface-agnostic by design: a web dashboard or iOS app can render
    these fields any way it likes without re-deriving them. Each loop
    contributes a sub-dict with counts, deltas, dormancy state, and
    streak. Cross-loop signals + topology are at the top level.

    Shape:
      {
        "generated_at": "2026-04-26T...",
        "loops": {
          "inner_reply": { ... },
          "meta_synthesis": { ... },
          "gap_driven": { ... },
          "thread_pull": { ... },
        },
        "cross_loop_signals": {
          "13.9 meta→user": int,
          "13.11 thread→advance": int,
          "13.12 voice+drawing": int,
        },
        "dormant_loops": [{loop, days_dormant, last_activity_ts, label}],
      }
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    state: dict = {
        "generated_at": now_utc.isoformat(),
        "loops": {},
        "cross_loop_signals": {},
        "dormant_loops": [],
    }

    # ── Loop 1: inner reply ──
    loop1: dict = {"name": "Inner reply", "phase_origin": "11"}
    try:
        from myalicia.skills.response_capture import (
            get_recent_captures, most_responded_syntheses,
        )
        recent = get_recent_captures(n=200)
        week_ago = now_utc - timedelta(days=7)
        two_weeks_ago = now_utc - timedelta(days=14)
        this_week = 0
        last_week = 0
        for c in recent:
            try:
                ts = datetime.fromisoformat(c.get("captured_at", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= week_ago:
                    this_week += 1
                elif ts >= two_weeks_ago:
                    last_week += 1
            except Exception:
                pass
        loop1["captures_this_week"] = this_week
        loop1["captures_last_week"] = last_week
        loop1["delta"] = this_week - last_week
        try:
            loop1["most_responded"] = [
                {"title": t, "count": n}
                for t, n in most_responded_syntheses(n=3)
            ]
        except Exception:
            loop1["most_responded"] = []
        loop1["last_activity_ts"] = _latest_capture_ts()
        loop1["streak_weeks"] = _compute_active_streak_weeks(
            _all_capture_timestamps()
        )
    except Exception as e:
        loop1["error"] = str(e)
    state["loops"]["inner_reply"] = loop1

    # ── Loop 2: meta-synthesis ──
    loop2: dict = {"name": "Meta-synthesis", "phase_origin": "13.6"}
    try:
        from myalicia.skills.meta_synthesis import (
            candidates_for_meta_synthesis, recent_meta_syntheses,
            MAX_META_LEVEL, get_synthesis_level,
        )
        cands = candidates_for_meta_synthesis()
        recent_14d = recent_meta_syntheses(within_days=14)
        recent_30d = recent_meta_syntheses(within_days=30)
        wk_ago = now_utc - timedelta(days=7)
        builds_this_week = sum(
            1 for e in recent_14d
            if (datetime.fromisoformat(e.get("ts", "")).replace(tzinfo=timezone.utc)
                if datetime.fromisoformat(e.get("ts", "")).tzinfo is None
                else datetime.fromisoformat(e.get("ts", ""))) >= wk_ago
        ) if recent_14d else 0
        loop2["candidate_count"] = len(cands)
        loop2["candidates"] = [
            {"title": c["title"], "capture_count": c["capture_count"],
             "delta": c.get("delta", 0)}
            for c in cands[:5]
        ]
        loop2["builds_this_week"] = builds_this_week
        loop2["builds_last_week"] = max(0, len(recent_14d) - builds_this_week)
        loop2["builds_30d"] = len(recent_30d)
        loop2["max_meta_level"] = MAX_META_LEVEL
        # Deepest level reached
        max_level = 0
        for entry in recent_30d:
            try:
                p = Path(entry.get("child_path", ""))
                if p.exists():
                    max_level = max(
                        max_level, get_synthesis_level(p.read_text(encoding="utf-8"))
                    )
            except Exception:
                continue
        loop2["deepest_level_reached"] = max_level
        loop2["last_activity_ts"] = _latest_meta_synthesis_ts()
        loop2["streak_weeks"] = _compute_active_streak_weeks(
            _all_meta_synthesis_timestamps()
        )
    except Exception as e:
        loop2["error"] = str(e)
    state["loops"]["meta_synthesis"] = loop2

    # ── Loop 3: gap-driven outbound ──
    loop3: dict = {"name": "Gap-driven outbound", "phase_origin": "12"}
    try:
        from myalicia.skills.dimension_research import (
            recent_dimension_questions, recent_escalations,
            get_persistent_thin_dimensions,
        )
        from myalicia.skills.user_model import find_thin_dimensions
        thin_now = find_thin_dimensions(stale_after_days=14)
        questions_14d = recent_dimension_questions(within_days=14)
        questions_7d = recent_dimension_questions(within_days=7)
        escalations_30d = recent_escalations(within_days=30)
        persistent = get_persistent_thin_dimensions()
        loop3["thin_dimensions"] = thin_now
        loop3["questions_this_week"] = len(questions_7d)
        loop3["questions_last_week"] = max(0, len(questions_14d) - len(questions_7d))
        loop3["dims_asked_this_week"] = sorted(set(
            q.get("dimension", "?") for q in questions_7d
        ))
        loop3["persistent_thin"] = persistent
        loop3["research_briefs_30d"] = sum(
            1 for e in escalations_30d if e.get("status") == "ok"
        )
        loop3["last_activity_ts"] = _latest_dimension_question_ts()
        loop3["streak_weeks"] = _compute_active_streak_weeks(
            _all_dimension_question_timestamps()
        )
    except Exception as e:
        loop3["error"] = str(e)
    state["loops"]["gap_driven"] = loop3

    # ── Loop 4: thread-pull ──
    loop4: dict = {"name": "Thread-pull", "phase_origin": "13.5"}
    try:
        from myalicia.skills.thread_puller import (
            recent_thread_pulls, recent_thread_pull_replies, advanced_threads,
        )
        pulls_14d = recent_thread_pulls(within_days=14)
        pulls_7d = recent_thread_pulls(within_days=7)
        replies_14d = recent_thread_pull_replies(within_days=14)
        replies_7d = recent_thread_pull_replies(within_days=7)
        advanced = advanced_threads(within_days=14)
        loop4["pulls_this_week"] = len(pulls_7d)
        loop4["pulls_last_week"] = max(0, len(pulls_14d) - len(pulls_7d))
        loop4["replies_this_week"] = len(replies_7d)
        loop4["replies_last_week"] = max(0, len(replies_14d) - len(replies_7d))
        loop4["reply_rate_pct"] = (
            round((len(replies_7d) / len(pulls_7d)) * 100.0)
            if pulls_7d else 0
        )
        loop4["advanced_threads"] = [
            {"summary": t["thread_summary"][:80], "reply_count": t["reply_count"]}
            for t in advanced[:3]
        ]
        loop4["last_activity_ts"] = _latest_thread_pull_ts()
        loop4["streak_weeks"] = _compute_active_streak_weeks(
            _all_thread_pull_timestamps()
        )
    except Exception as e:
        loop4["error"] = str(e)
    state["loops"]["thread_pull"] = loop4

    # ── Cross-loop signals ──
    state["cross_loop_signals"] = _cross_loop_signal_counts()

    # ── Dormancy ──
    try:
        state["dormant_loops"] = detect_dormant_loops()
    except Exception:
        state["dormant_loops"] = []

    return state


def _cross_loop_signal_counts() -> dict:
    """Same data the existing _connection_points_section computes,
    exposed as a dict for the state-based contract."""
    counts = {
        "13.9 meta→user": 0,
        "13.11 thread→advance": 0,
        "13.12 voice+drawing": 0,
    }
    try:
        from myalicia.skills.user_model import get_learnings
        recent_learnings = get_learnings(since_days=30)
        counts["13.9 meta→user"] = sum(
            1 for L in recent_learnings
            if (L.get("source") or "").startswith("meta_synthesis:")
        )
    except Exception:
        pass
    try:
        from myalicia.skills.thread_puller import recent_thread_pull_replies
        counts["13.11 thread→advance"] = len(
            recent_thread_pull_replies(within_days=14)
        )
    except Exception:
        pass
    try:
        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        recents = recent_multi_channel_decisions(within_hours=24 * 7)
        counts["13.12 voice+drawing"] = sum(
            1 for d in recents if d.get("channel") == "coherent_moment"
        )
    except Exception:
        pass
    return counts


# ── Main entry ────────────────────────────────────────────────────────────


def render_loops_dashboard(now: Optional[datetime] = None) -> str:
    """Compose the /loops Telegram message.

    Sections (each fault-tolerant):
      1. Header
      2-5. One per loop (inner reply, meta-synthesis, gap-driven, thread-pull)
      6. Cross-loop signals — the connection points that turn the four
         loops into a connected nervous system
    """
    sections = [
        "🔄 *Loops — the circulatory system*",
        "",
        _loop1_inner_reply(),
        "",
        _loop2_meta_synthesis(),
        "",
        _loop3_gap_driven(),
        "",
        _loop4_thread_pull(),
        "",
        _connection_points_section(),
        "",
        _topology_section(),
    ]
    return "\n".join(sections)


if __name__ == "__main__":
    print(render_loops_dashboard())
