"""
daily_signal.py — Shared daily-signal digest.

Complements daily_rhythm.json (what happened: messages, voice, timing)
with the FEEDBACK layer (how it landed: reactions, episode score deltas,
proactive engagement, tool effectiveness).

Why this exists
---------------
the user's vision: every scheduled task, every message, every emoji reaction
should feed the same closed-loop substrate. Gap 1 made reactions re-score
episodes. Gap 4 is the shared digest that every scheduled task writes
into and every day-shaping message reads from, so the morning greeting
knows yesterday's valence, the midday nudge knows how the morning landed,
and the evening reflection knows what today rhymed with.

Writers
-------
  - handle_message                → record_tool_call(tool_name)
  - handle_message_reaction       → record_reaction(emoji, valence, delta)
                                  → record_proactive_engagement(slot, ...)
  - episode_scorer.record_outcome → record_episode_scored(task, score)
  - alicia.py morning/midday/evening → record_proactive_slot(slot)

Readers
-------
  - proactive_messages.build_startup_greeting  → yesterday's signal
  - proactive_messages.build_midday_message    → today-so-far signal
  - proactive_messages._evening_reflection     → full day signal
  - /status and /tasks                         → get_signal_summary()

Storage
-------
  ~/alicia/memory/daily_signal.json            — current day (rolls at 05:00)
  ~/alicia/memory/daily_signal_archive.jsonl   — append-only history

Schema
------
  {
    "date": "YYYY-MM-DD",
    "started_at": ISO8601,
    "reactions": {positive, negative, ambiguous, by_emoji},
    "tools":     {calls, by_tool},
    "episodes":  {scored, score_sum, rewarded, punished},
    "proactive": {morning_sent, midday_sent, evening_sent, engagement[]},
    "events":    [last ~50 notable events],
    "_yesterday": {...same shape without _yesterday...}
  }
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from myalicia.config import config

log = logging.getLogger(__name__)

MEMORY_DIR = Path(os.path.expanduser("~/alicia/memory"))
SIGNAL_FILE = MEMORY_DIR / "daily_signal.json"
SIGNAL_ARCHIVE = MEMORY_DIR / "daily_signal_archive.jsonl"

MAX_EVENTS = 50  # rolling window so events[] doesn't blow up


def _default_signal() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "started_at": datetime.now().isoformat(),
        "reactions": {
            "positive": 0,
            "negative": 0,
            "ambiguous": 0,
            "by_emoji": {},
        },
        "tools": {
            "calls": 0,
            "by_tool": {},
        },
        "episodes": {
            "scored": 0,
            "score_sum": 0.0,
            "rewarded": 0,     # score >= 0.7
            "punished": 0,     # score <  0.5
        },
        "proactive": {
            "morning_sent": False,
            "midday_sent": False,
            "evening_sent": False,
            "reactions_received": 0,
            "engagement": [],   # {slot, emoji, minutes_to_react}
        },
        "events": [],           # rolling {ts, kind, data}
    }


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load() -> dict:
    """
    Load today's signal. If stored date is not today, archive it to
    _yesterday (and to the JSONL archive) and start a fresh day.
    Idempotent: callers don't need to think about rollover.
    """
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if SIGNAL_FILE.exists():
            with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            today = datetime.now().strftime("%Y-%m-%d")
            if data.get("date") == today:
                # Ensure expected top-level keys exist (schema drift defence)
                defaults = _default_signal()
                for k, v in defaults.items():
                    data.setdefault(k, v)
                return data
            # Date rolled. Archive and start fresh.
            try:
                with open(SIGNAL_ARCHIVE, "a", encoding="utf-8") as f:
                    yesterday_line = {k: v for k, v in data.items() if k != "_yesterday"}
                    f.write(json.dumps(yesterday_line, ensure_ascii=False) + "\n")
            except Exception as e:
                log.warning(f"daily_signal archive write failed: {e}")
            new = _default_signal()
            new["_yesterday"] = {k: v for k, v in data.items() if k != "_yesterday"}
            return new
    except Exception as e:
        log.warning(f"daily_signal load failed: {e}")
    return _default_signal()


def _save(data: dict) -> None:
    try:
        _atomic_write(SIGNAL_FILE, data)
    except Exception as e:
        log.warning(f"daily_signal save failed: {e}")


def _push_event(data: dict, kind: str, payload: dict) -> None:
    evt = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "kind": kind,
        "data": payload,
    }
    events = data.setdefault("events", [])
    events.append(evt)
    if len(events) > MAX_EVENTS:
        del events[: len(events) - MAX_EVENTS]


# ── Writers ───────────────────────────────────────────────────────────────

def record_reaction(emoji: str, valence: str, score_delta: float | None = None) -> None:
    """
    valence ∈ {"positive", "negative", "ambiguous"} — matches
    reaction_scorer.emoji_to_outcome semantics:
      success=True  → "positive"
      success=False → "negative"
      success=None  → "ambiguous"
    """
    try:
        data = _load()
        r = data["reactions"]
        if valence in ("positive", "negative", "ambiguous"):
            r[valence] = r.get(valence, 0) + 1
        by = r.setdefault("by_emoji", {})
        by[emoji] = by.get(emoji, 0) + 1
        _push_event(data, "reaction", {
            "emoji": emoji, "valence": valence, "delta": score_delta,
        })
        _save(data)
    except Exception as e:
        log.warning(f"record_reaction failed: {e}")


def record_tool_call(tool_name: str) -> None:
    if not tool_name:
        return
    try:
        data = _load()
        t = data["tools"]
        t["calls"] = t.get("calls", 0) + 1
        by = t.setdefault("by_tool", {})
        by[tool_name] = by.get(tool_name, 0) + 1
        _push_event(data, "tool_call", {"tool": tool_name})
        _save(data)
    except Exception as e:
        log.warning(f"record_tool_call failed: {e}")


def record_episode_scored(task_type: str, score: float) -> None:
    try:
        data = _load()
        e = data["episodes"]
        e["scored"] = e.get("scored", 0) + 1
        e["score_sum"] = float(e.get("score_sum", 0.0)) + float(score)
        if score >= 0.7:
            e["rewarded"] = e.get("rewarded", 0) + 1
        elif score < 0.5:
            e["punished"] = e.get("punished", 0) + 1
        _push_event(data, "episode_scored", {
            "task": task_type or "?", "score": round(float(score), 3),
        })
        _save(data)
    except Exception as e:
        log.warning(f"record_episode_scored failed: {e}")


def record_proactive_slot(slot: str, msg_type: str | None = None) -> None:
    """slot ∈ {morning, midday, evening}"""
    try:
        data = _load()
        p = data["proactive"]
        key = f"{slot}_sent"
        p[key] = True
        _push_event(data, "proactive_sent", {
            "slot": slot, "msg_type": msg_type or "",
        })
        _save(data)
    except Exception as e:
        log.warning(f"record_proactive_slot failed: {e}")


def record_proactive_engagement(slot: str, emoji: str, minutes_to_react: int) -> None:
    """Called from reaction handling when the reacted-to message was a proactive send."""
    try:
        data = _load()
        p = data["proactive"]
        p["reactions_received"] = p.get("reactions_received", 0) + 1
        engagement = p.setdefault("engagement", [])
        engagement.append({
            "slot": slot,
            "emoji": emoji,
            "minutes": int(minutes_to_react),
            "ts": datetime.now().isoformat(),
        })
        _push_event(data, "proactive_engagement", {
            "slot": slot, "emoji": emoji, "minutes": int(minutes_to_react),
        })
        _save(data)
    except Exception as e:
        log.warning(f"record_proactive_engagement failed: {e}")


# ── Readers ───────────────────────────────────────────────────────────────

def get_today_signal() -> dict:
    return _load()


def get_yesterday_signal() -> dict | None:
    data = _load()
    return data.get("_yesterday")


def get_signal_summary(scope: str = "today") -> str:
    """
    Human-readable one-liner of today's/yesterday's feedback pulse.
    Safe to drop into LLM prompts. Empty string if nothing notable.

    scope ∈ {"today", "yesterday"}.
    """
    data = _load()
    target = data if scope == "today" else (data.get("_yesterday") or {})
    if not target:
        return ""

    r = target.get("reactions", {})
    pos = r.get("positive", 0)
    neg = r.get("negative", 0)
    amb = r.get("ambiguous", 0)

    e = target.get("episodes", {})
    scored = e.get("scored", 0)
    score_sum = e.get("score_sum", 0.0)
    avg = (score_sum / scored) if scored else 0.0
    rewarded = e.get("rewarded", 0)
    punished = e.get("punished", 0)

    t = target.get("tools", {})
    tool_calls = t.get("calls", 0)
    by_tool = t.get("by_tool", {})
    top_tool = max(by_tool.items(), key=lambda kv: kv[1])[0] if by_tool else None

    p = target.get("proactive", {})
    prox_reacts = p.get("reactions_received", 0)

    # Nothing meaningful? skip.
    if pos + neg + amb == 0 and scored == 0 and tool_calls == 0 and prox_reacts == 0:
        return ""

    parts: list[str] = []
    if pos or neg or amb:
        bits = []
        if pos: bits.append(f"{pos} 🔥/👍")
        if neg: bits.append(f"{neg} 👎")
        if amb: bits.append(f"{amb} 🤔")
        parts.append(", ".join(bits))
    if scored:
        parts.append(
            f"{scored} episode{'s' if scored != 1 else ''} scored "
            f"(avg {avg:.2f}; +{rewarded}/-{punished})"
        )
    if tool_calls:
        if top_tool:
            parts.append(f"{tool_calls} tool calls (top: {top_tool})")
        else:
            parts.append(f"{tool_calls} tool calls")
    if prox_reacts:
        parts.append(f"{prox_reacts} reacted to proactive")
    return " · ".join(parts)


def valence_from_emoji(emoji: str) -> str:
    """
    Lightweight wrapper around reaction_scorer.emoji_to_outcome so the
    signal writer doesn't need to know the success bool shape.
    """
    try:
        from myalicia.skills.reaction_scorer import emoji_to_outcome
        success, _ = emoji_to_outcome(emoji)
        if success is True:
            return "positive"
        if success is False:
            return "negative"
        return "ambiguous"
    except Exception:
        return "ambiguous"
