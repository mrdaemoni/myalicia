"""
reaction_scorer.py — Bridges Telegram reactions into the MemRL episode scorer.

When the user reacts with an emoji on one of Alicia's messages, we want that
reaction to update the reward score of the episode that produced that
response. This closes the tightest feedback loop: a 🔥 on a tool-assisted
reply reinforces similar future replies because get_rewarded_reflections
is reward-ranked during retrieval.

Why a dedicated module
----------------------
Reactions can arrive hours (or days) after Alicia's reply, so we can't
rely on find_latest_episode_for_task's 5-minute mtime window at reaction
time. Instead we capture (message_id, episode_path, task_type) at reply
time, persist it, and look it up on reaction.

Architecture
------------
  1. track_reply(message_id, episode_path, task_type, reply_ts, meta)
     appends an entry to ~/alicia/memory/reply_index.jsonl (append-only).

  2. lookup_reply(message_id) scans tail-first for a matching entry.

  3. score_reply_by_reaction(message_id, emoji) looks up the entry,
     converts emoji → (success_bool, user_depth), calls episode_scorer.
     record_outcome with the stored absolute episode_path.

  4. Pure-conversation replies (no tool_name, no episode written) aren't
     tracked. Gap 3 (archetype weights) will handle reinforcement for
     that channel via a different mechanism.

Emoji semantics
---------------
  🔥 ❤ ❤️ 🧠 💡  → strongly positive, high depth (success=True, 4–5)
  👍 🙏 😂       → positive, medium depth (success=True, 3)
  🤔              → engagement without judgement — log but no episode update
  👎 💩 ❌        → negative (success=False, depth=1)
  unknown         → mild positive default (True, 2) so novel emoji aren't
                    silently ignored

The depth number is what episode_scorer.score_episode folds into its
user_satisfaction term. success flips the outcome bit.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger(__name__)

MEMORY_DIR = Path(str(MEMORY_DIR))
REPLY_INDEX = MEMORY_DIR / "reply_index.jsonl"

# Emoji → (success: bool | None, user_depth: int 1–5)
# None means "ambiguous — don't flip success, but still log the engagement".
EMOJI_TO_OUTCOME: dict[str, tuple[bool | None, int]] = {
    # Strong positive
    "🔥": (True, 5),
    "❤": (True, 5),
    "❤️": (True, 5),
    "🧠": (True, 4),
    "💡": (True, 4),
    "🤯": (True, 5),
    "🙌": (True, 4),
    # Positive
    "👍": (True, 3),
    "🙏": (True, 3),
    "😂": (True, 3),
    "😀": (True, 3),
    "😊": (True, 3),
    "⭐": (True, 4),
    "🎯": (True, 4),
    # Ambiguous — engagement without clear judgement
    "🤔": (None, 3),
    "😐": (None, 2),
    "👀": (None, 3),
    # Negative
    "👎": (False, 1),
    "💩": (False, 1),
    "❌": (False, 1),
    "😡": (False, 1),
    "🙄": (False, 2),
}
# Unknown emoji: treat as mild positive engagement so novel signals still
# push the episode in a useful direction rather than being silently dropped.
DEFAULT_OUTCOME: tuple[bool, int] = (True, 2)


def track_reply(
    message_id: int,
    episode_path: str,
    task_type: str,
    reply_timestamp: str | None = None,
    archetype: str | None = None,
    query_excerpt: str | None = None,
) -> None:
    """Persist a reply → episode mapping so reactions can be scored later.

    Called from alicia.py AFTER the reply has been sent AND reflexion has
    written the episode (so episode_path actually exists on disk).
    """
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "message_id": int(message_id),
            "episode_path": str(episode_path) if episode_path else "",
            "task_type": task_type or "",
            "reply_timestamp": reply_timestamp or datetime.now().isoformat(),
            "archetype": archetype or "",
            "query_excerpt": (query_excerpt or "")[:160],
        }
        with open(REPLY_INDEX, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"track_reply failed for msg_id={message_id}: {e}")


def lookup_reply(message_id: int) -> dict | None:
    """Return the entry for message_id, or None. Tail-first scan for recency."""
    if not REPLY_INDEX.exists():
        return None
    try:
        # Tail-first: we load all lines, iterate in reverse. For 30-day
        # retention the file stays small (thousands of entries max), so a
        # full scan is fine. If this ever grows, switch to a sidecar index.
        with open(REPLY_INDEX, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("message_id") == int(message_id):
                return entry
        return None
    except Exception as e:
        log.warning(f"lookup_reply failed for msg_id={message_id}: {e}")
        return None


def emoji_to_outcome(emoji: str) -> tuple[bool | None, int]:
    """Normalise an emoji to (success_bool_or_None, user_depth)."""
    return EMOJI_TO_OUTCOME.get(emoji, DEFAULT_OUTCOME)


def score_reply_by_reaction(message_id: int, emoji: str) -> dict | None:
    """Main entry — called from handle_message_reaction in alicia.py.

    Returns a status dict for logging (or None if nothing found).
    Possible actions:
      - "scored"              — episode updated
      - "skipped_ambiguous"   — emoji is engagement-only (🤔 etc.)
      - "no_tracked_reply"    — this message_id wasn't one we tracked
      - "no_episode"          — entry had no episode_path (defensive)
    """
    entry = lookup_reply(message_id)
    if not entry:
        return {"action": "no_tracked_reply", "message_id": int(message_id)}

    success, depth = emoji_to_outcome(emoji)

    # Gap 3: attribute this reaction to the archetype that carried the
    # message (if any). The log entry is written for all reactions —
    # including ambiguous ones (🤔) — because engagement itself is signal.
    # Silent failure: inner_life decides neutral defaults for any archetype
    # with too few attributions.
    archetype = (entry.get("archetype") or "").strip()
    if archetype:
        try:
            from myalicia.skills.inner_life import log_archetype_attribution
            log_archetype_attribution(archetype, emoji, success, depth)
        except Exception as e:
            log.debug(f"archetype attribution skip: {e}")

    if success is None:
        return {
            "action": "skipped_ambiguous",
            "emoji": emoji,
            "depth": depth,
            "episode_path": entry.get("episode_path", ""),
            "archetype": archetype,
        }

    ep = entry.get("episode_path", "")
    if not ep or not os.path.isfile(ep):
        return {
            "action": "no_episode",
            "task_type": entry.get("task_type", ""),
            "episode_path": ep,
        }

    # Lazy import to avoid a circular at module load (episode_scorer
    # imports nothing from us but keeps the module graph tidy).
    try:
        from myalicia.skills.episode_scorer import record_outcome
        record_outcome(
            episode_path=ep,
            success=bool(success),
            user_depth=int(depth),
        )
    except Exception as e:
        log.warning(f"record_outcome failed via reaction_scorer: {e}")
        return {"action": "error", "error": str(e)}

    return {
        "action": "scored",
        "episode_path": ep,
        "task_type": entry.get("task_type", ""),
        "emoji": emoji,
        "success": bool(success),
        "depth": int(depth),
        "archetype": archetype,
    }


def prune_old_entries(max_age_days: int = 30) -> int:
    """Keep reply_index.jsonl bounded. Returns count pruned.

    Safe to call often — idempotent, atomic via rename.
    """
    if not REPLY_INDEX.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    try:
        kept: list[str] = []
        pruned = 0
        with open(REPLY_INDEX, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("reply_timestamp", ""))
                    if ts >= cutoff:
                        kept.append(line)
                    else:
                        pruned += 1
                except Exception:
                    # Keep unparseable lines so we don't lose data silently.
                    kept.append(line)
        if pruned > 0:
            tmp = REPLY_INDEX.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(kept) + ("\n" if kept else ""))
            tmp.replace(REPLY_INDEX)
            log.info(f"reply_index pruned {pruned} entries older than {max_age_days}d")
        return pruned
    except Exception as e:
        log.warning(f"prune_old_entries failed: {e}")
        return 0


def get_stats() -> dict:
    """Lightweight stats for /status or /tasks."""
    if not REPLY_INDEX.exists():
        return {"tracked_replies": 0, "file": str(REPLY_INDEX), "exists": False}
    try:
        with open(REPLY_INDEX, "r", encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
        return {
            "tracked_replies": n,
            "file": str(REPLY_INDEX),
            "exists": True,
        }
    except Exception as e:
        return {"error": str(e), "file": str(REPLY_INDEX)}
