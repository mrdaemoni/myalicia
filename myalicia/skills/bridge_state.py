#!/usr/bin/env python3
"""
Alicia — Bridge State Snapshot (H2)

Writes a small machine-readable JSON file at
<vault.bridge_path>/alicia-state.json
containing Alicia's current vitals: season, emergence score, archetype
weights, last voice interaction, mood signal, hot threads, last score-5
reaction.

Purpose — close the "two Alicias sharing a brain" loop: Telegram writes
the snapshot; Desktop-side scheduled synthesis tasks read it and inject
it as context ("the user is in First Light season; weight wonder over
challenge"). The narrative about symmetrical bridge becomes literally
true instead of aspirational.

All reads are cheap and local. All writes are atomic via safe_io.
Scheduled every 10 min from alicia.py; also fire-and-forget callable
from any place where emergence-relevant state changes.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from myalicia.skills.bridge_protocol import (
    BRIDGE_DIR, bridge_path, write_bridge_json, read_bridge_json,
)
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger(__name__)

MEMORY_DIR = str(MEMORY_DIR)
SNAPSHOT_FILENAME = "alicia-state.json"
# Exposed for legacy callers; prefer bridge_protocol going forward.
SNAPSHOT_PATH = bridge_path(SNAPSHOT_FILENAME)

EMERGENCE_STATE_PATH = os.path.join(MEMORY_DIR, "emergence_state.json")
VOICE_LOG_PATH = os.path.join(MEMORY_DIR, "voice_metadata_log.jsonl")
REACTION_LOG_PATH = os.path.join(MEMORY_DIR, "reaction_log.tsv")


def _read_emergence_state() -> dict:
    """Read last-computed emergence state from disk. Never calls the heavy
    recompute path — this reflects whatever inner_life's scheduled pulse
    most recently wrote."""
    if not os.path.exists(EMERGENCE_STATE_PATH):
        return {}
    try:
        with open(EMERGENCE_STATE_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"emergence_state read failed: {e}")
        return {}


def _archetype_weights() -> dict:
    """Return current archetype weights. Fast recompute ~a few ms."""
    try:
        from myalicia.skills.inner_life import compute_dynamic_archetype_weights
        weights = compute_dynamic_archetype_weights()
        # Round to 2dp for JSON noise reduction.
        return {k: round(float(v), 3) for k, v in weights.items()}
    except Exception as e:
        log.warning(f"archetype weights read failed: {e}")
        return {}


def _last_voice_at() -> str:
    """Return ISO timestamp of the most recent voice interaction, or ''
    if no voice log exists."""
    if not os.path.exists(VOICE_LOG_PATH):
        return ""
    try:
        # Voice log is JSONL, append-only. Read the last non-empty line.
        with open(VOICE_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Walk backwards up to 16KB — log lines are small.
            chunk = min(size, 16384)
            f.seek(max(0, size - chunk))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return ""
        last = json.loads(lines[-1])
        return str(last.get("timestamp", ""))
    except Exception as e:
        log.warning(f"voice_log tail read failed: {e}")
        return ""


def _mood_signal(emergence: dict) -> str:
    """
    Heuristic mood signal derived from the engagement trajectory.

    Falls back gracefully: trajectory.trend → season-based default →
    'contemplative' as the neutral floor.
    """
    try:
        from myalicia.skills.temporal_patterns import compute_engagement_trajectory
        traj = compute_engagement_trajectory() or {}
        trend = (traj.get("trend") or "").lower()
        if trend in ("growing", "rising", "up"):
            return "energized"
        if trend in ("declining", "falling", "down"):
            return "contemplative"
        if trend in ("stable", "steady"):
            return "centered"
    except Exception as e:
        log.debug(f"trajectory mood inference skipped: {e}")

    # Season-based fallback — First Light feels exploratory, later seasons
    # consolidate. This is just a soft default; Desktop can override.
    season = (emergence.get("season") or "").lower()
    if "first" in season or "dawn" in season:
        return "exploratory"
    if "generative" in season or "voice" in season:
        return "generative"
    return "contemplative"


def _hot_threads(limit: int = 5) -> list:
    """Top recurring themes from session_threads.get_thread_stats()."""
    try:
        from myalicia.skills.session_threads import get_thread_stats
        stats = get_thread_stats() or {}
        themes = stats.get("most_common_themes") or []
        # get_thread_stats may return tuples (theme, count) or dicts — normalize.
        names: list[str] = []
        for item in themes[:limit]:
            if isinstance(item, (list, tuple)) and item:
                names.append(str(item[0]))
            elif isinstance(item, dict) and "theme" in item:
                names.append(str(item["theme"]))
            elif isinstance(item, str):
                names.append(item)
        return names
    except Exception as e:
        log.warning(f"hot_threads read failed: {e}")
        return []


def _last_score5_at() -> str:
    """Timestamp of the most recent '5' reaction (the user's top signal)."""
    if not os.path.exists(REACTION_LOG_PATH):
        return ""
    try:
        with open(REACTION_LOG_PATH, "r") as f:
            lines = f.readlines()
        if len(lines) < 2:
            return ""
        headers = lines[0].rstrip("\n").split("\t")
        # Find column indices — tolerant of schema drift.
        try:
            emoji_idx = headers.index("emoji")
        except ValueError:
            emoji_idx = None
        try:
            ts_idx = headers.index("timestamp")
        except ValueError:
            ts_idx = 0  # reaction_log conventionally starts with timestamp

        for line in reversed(lines[1:]):
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(ts_idx, emoji_idx or 0):
                continue
            emoji_val = parts[emoji_idx] if emoji_idx is not None else ""
            # Accept literal "5", the keycap "5️⃣", or a row labelled "score_5".
            if emoji_val.strip() in ("5", "5️⃣", "score_5"):
                return parts[ts_idx]
        return ""
    except Exception as e:
        log.warning(f"reaction_log read failed: {e}")
        return ""


def build_snapshot() -> dict:
    """Assemble the current state dict. Pure reads — no side effects."""
    emergence = _read_emergence_state()
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": emergence.get("season", ""),
        "emergence_score": emergence.get("score", 0.0),
        "archetype_weights": _archetype_weights(),
        "last_voice_at": _last_voice_at(),
        "mood_signal": _mood_signal(emergence),
        "hot_threads": _hot_threads(),
        "last_score5_at": _last_score5_at(),
    }
    return snapshot


def write_alicia_state_snapshot() -> dict:
    """
    Build and atomically write the current snapshot to
    Alicia/Bridge/alicia-state.json.

    Returns the dict that was written (handy for logging / tests).
    Caller should treat this as fire-and-forget — any exception is caught
    and logged; we never want a bad snapshot to take down the scheduler.
    """
    try:
        snapshot = build_snapshot()
        # Routes through bridge_protocol so the write is atomic, schema-
        # validated (if bridge_schema is available), and logged in the
        # bridge _INDEX.jsonl for Desktop-side consumers.
        write_bridge_json(SNAPSHOT_FILENAME, snapshot)
        log.info(
            f"Bridge snapshot written: season={snapshot.get('season')!r} "
            f"score={snapshot.get('emergence_score')} "
            f"mood={snapshot.get('mood_signal')!r} "
            f"hot_threads={len(snapshot.get('hot_threads', []))}"
        )
        return snapshot
    except Exception as e:
        log.error(f"write_alicia_state_snapshot failed: {e}")
        return {}


def read_alicia_state_snapshot() -> dict:
    """Read the most recently written snapshot. Returns {} if missing.
    Exposed so Desktop-side code (or a /bridge-state command) can consume it
    symmetrically without re-implementing the path."""
    return read_bridge_json(SNAPSHOT_FILENAME, default={})


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    snap = write_alicia_state_snapshot()
    print(json.dumps(snap, indent=2))
