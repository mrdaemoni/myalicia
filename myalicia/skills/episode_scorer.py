#!/usr/bin/env python3
"""
Alicia — Episode Scorer (MemRL Pattern)

Reward-scored episodic memory with two-phase retrieval. Adds
reinforcement learning signals to reflexion episodes without
model weight updates.

Inspired by MemRL (arxiv 2601.03192): agents self-evolve at runtime
through RL on episodic memory. A Two-Phase Retrieval mechanism
filters noise, then identifies high-utility strategies.

Phase 1: Broad semantic/task-type match → candidates
Phase 2: Reward-score ranking with time decay → top strategies
"""
import os
import json
import math
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

load_dotenv(str(ENV_FILE))
log = logging.getLogger(__name__)

MEMORY_DIR = str(MEMORY_DIR)
EPISODES_DIR = os.path.join(MEMORY_DIR, "episodes")
SCORES_INDEX = os.path.join(MEMORY_DIR, "episode_scores.json")

# Task type relationships for Phase 1 retrieval
_TASK_KEYWORDS = {
    "search_vault": ["search_vault", "read_vault_note", "find_contradictions", "research"],
    "read_vault_note": ["read_vault_note", "search_vault", "synthesise_vault"],
    "remember": ["remember", "reflect", "store_insight"],
    "reflect": ["reflect", "remember", "analysis_dialogue_depth"],
    "synthesis": ["synthesise_vault", "generate_concept_note", "research"],
    "research": ["research", "synthesis", "find_contradictions"],
}

# Ensure directories exist
os.makedirs(EPISODES_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)


def score_episode(episode: dict, user_response_depth: int = 0) -> float:
    """
    Compute a reward score for a reflexion episode.

    Reward = 0.3 * success_signal + 0.3 * confidence_normalized +
             0.2 * procedure_generated + 0.2 * user_satisfaction

    Args:
        episode: Episode dict with 'score' and 'reflection' keys
        user_response_depth: 0-5 scale of user engagement (optional)

    Returns:
        float 0.0-1.0
    """
    try:
        # Extract success signal from episode score
        episode_score_str = episode.get("score", "n/a")
        if episode_score_str == "n/a":
            success_signal = 0.0
        else:
            try:
                ep_score = float(episode_score_str)
                if ep_score >= 4:
                    success_signal = 1.0
                elif ep_score >= 2:
                    success_signal = 0.5
                else:
                    success_signal = 0.0
            except (ValueError, TypeError):
                success_signal = 0.0

        # Extract confidence from reflection
        reflection = episode.get("reflection", {})
        confidence = reflection.get("confidence", 2.5)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 2.5
        confidence_normalized = min(confidence / 5.0, 1.0)

        # Check if procedure was generated
        procedure_update = reflection.get("procedure_update", "")
        procedure_generated = 1.0 if procedure_update and procedure_update.strip() else 0.0

        # Clamp user satisfaction to [0, 1]
        user_satisfaction = min(user_response_depth / 5.0, 1.0)

        # Weighted sum
        reward = (
            0.3 * success_signal +
            0.3 * confidence_normalized +
            0.2 * procedure_generated +
            0.2 * user_satisfaction
        )

        return round(max(0.0, min(reward, 1.0)), 4)

    except Exception as e:
        log.error(f"Error scoring episode: {e}")
        return 0.0


def apply_time_decay(score: float, episode_timestamp: str, half_life_days: int = 30) -> float:
    """
    Apply exponential decay to a score based on age.

    Decay = score * 0.5^(age_days / half_life_days)

    Args:
        score: Initial reward score (0.0-1.0)
        episode_timestamp: ISO 8601 timestamp string
        half_life_days: Half-life in days (default 30)

    Returns:
        float: Decayed score
    """
    try:
        # Parse timestamp
        ts = datetime.fromisoformat(episode_timestamp.replace("Z", "+00:00"))
        age = datetime.now(ts.tzinfo) - ts if ts.tzinfo else datetime.now() - ts.replace(tzinfo=None)
        age_days = age.total_seconds() / 86400.0

        # Exponential decay
        decay_factor = 0.5 ** (age_days / half_life_days)
        decayed = score * decay_factor

        return round(decayed, 4)

    except Exception as e:
        log.error(f"Error applying time decay: {e}")
        return score


def index_episodes() -> int:
    """
    Scan ~/alicia/memory/episodes/*.json, compute reward scores,
    and store them in a scores index file (~/alicia/memory/episode_scores.json).

    The index maps filename → {reward_score, task_type, timestamp, decayed_score}.
    Called periodically (daily) or on demand.

    Returns:
        int: Count of episodes indexed
    """
    try:
        if not os.path.isdir(EPISODES_DIR):
            log.warning(f"Episodes directory not found: {EPISODES_DIR}")
            return 0

        index = {}
        count = 0

        for filename in os.listdir(EPISODES_DIR):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(EPISODES_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    episode = json.load(f)

                # Compute reward score
                reward_score = score_episode(episode)

                # Apply time decay
                timestamp = episode.get("timestamp", "")
                decayed_score = apply_time_decay(reward_score, timestamp)

                # Store in index
                index[filename] = {
                    "reward_score": reward_score,
                    "decayed_score": decayed_score,
                    "task_type": episode.get("task_type", "unknown"),
                    "timestamp": timestamp,
                }

                count += 1

            except json.JSONDecodeError as e:
                log.error(f"Corrupt JSON in {filename}: {e}")
            except Exception as e:
                log.error(f"Error indexing {filename}: {e}")

        # Write index to file (atomic — crash-safe)
        atomic_write_json(SCORES_INDEX, index)

        log.info(f"Indexed {count} episodes to {SCORES_INDEX}")
        return count

    except Exception as e:
        log.error(f"Error in index_episodes: {e}")
        return 0


def _load_scores_index() -> dict:
    """Load scores index from file, returning empty dict if not found."""
    try:
        if os.path.isfile(SCORES_INDEX):
            with open(SCORES_INDEX, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error(f"Error loading scores index: {e}")
    return {}


def _get_related_task_types(task_type: str) -> set:
    """Get task types related to the given task_type."""
    related = set()
    related.add(task_type)

    # Forward mapping
    if task_type in _TASK_KEYWORDS:
        related.update(_TASK_KEYWORDS[task_type])

    # Reverse mapping
    for key, values in _TASK_KEYWORDS.items():
        if task_type in values:
            related.add(key)
            related.update(values)

    return related


def get_rewarded_reflections(task_type: str, context: str = "", max_results: int = 3) -> str:
    """
    Two-phase retrieval replacing the old get_relevant_reflections.

    Phase 1 (Broad match): Load all episodes matching task_type OR
    related task types from the scores index. Use the _task_keywords mapping.

    Phase 2 (Reward-ranked): Sort by decayed reward score. Return
    top max_results formatted as prompt-injectable text.

    Falls back to recency if no scored episodes exist.

    Args:
        task_type: Primary task type to match
        context: Optional context string (for future semantic matching)
        max_results: Number of top episodes to return

    Returns:
        str: Formatted text suitable for prompt injection
    """
    try:
        index = _load_scores_index()

        if not index:
            # First run or empty index
            return "No indexed episodes available yet."

        # Phase 1: Broad match by task type
        related_types = _get_related_task_types(task_type)
        candidates = []

        for filename, entry in index.items():
            if entry.get("task_type") in related_types:
                candidates.append((filename, entry))

        if not candidates:
            return f"No episodes found for task type: {task_type}"

        # Phase 2: Reward-ranked
        candidates.sort(
            key=lambda x: (x[1].get("decayed_score", 0), x[1].get("reward_score", 0)),
            reverse=True
        )

        # Format top results
        results = []
        for filename, entry in candidates[:max_results]:
            reward = entry.get("reward_score", 0)
            decayed = entry.get("decayed_score", 0)
            task = entry.get("task_type", "unknown")
            ts = entry.get("timestamp", "")

            results.append(
                f"Episode {filename}: task={task}, reward={reward:.3f}, "
                f"decayed={decayed:.3f}, timestamp={ts}"
            )

        return "\n".join(results)

    except Exception as e:
        log.error(f"Error in get_rewarded_reflections: {e}")
        return f"Error retrieving reflections: {e}"


def find_latest_episode_for_task(task_type: str, max_age_minutes: int = 5) -> str | None:
    """
    Return the path to the most recent episode JSON for `task_type`, or None
    if nothing qualifies. Only considers episodes modified within the last
    `max_age_minutes` (default 5) so we don't retroactively rescore stale
    ones after a long quiet period.
    """
    try:
        if not os.path.isdir(EPISODES_DIR):
            return None
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        latest_path = None
        latest_mtime = 0.0
        # Episode files are named "{date}_{time}_{task_type}.json" — fast
        # substring filter before stat().
        suffix = f"_{task_type}.json"
        for name in os.listdir(EPISODES_DIR):
            if not name.endswith(suffix):
                continue
            path = os.path.join(EPISODES_DIR, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if datetime.fromtimestamp(mtime) < cutoff:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = path
        return latest_path
    except Exception as e:
        log.debug(f"find_latest_episode_for_task({task_type!r}) failed: {e}")
        return None


def record_outcome(
    episode_path: str,
    success: bool,
    user_depth: int = 0,
    task_type: str | None = None,
) -> None:
    """
    Record actual outcome for a recent episode after the fact.
    Updates the episode JSON with outcome data and recomputes score.
    Called from handle_message's background intelligence thread.

    Args:
        episode_path: Full path to episode JSON file. If empty/None, and
            `task_type` is provided, the latest episode for that task in
            the last 5 minutes is used.
        success: Whether the task succeeded
        user_depth: User engagement depth (0-5)
        task_type: Optional task type to resolve `episode_path` from when empty.
    """
    try:
        if not episode_path:
            if not task_type:
                # Nothing to look up — caller didn't give us a handle. Silent
                # no-op; reflexion may not have produced an episode for this
                # message (e.g. should_reflect() returned False).
                log.debug("record_outcome: no episode_path or task_type; skipping.")
                return
            resolved = find_latest_episode_for_task(task_type)
            if not resolved:
                log.debug(
                    f"record_outcome: no recent episode for task_type={task_type!r}; skipping."
                )
                return
            episode_path = resolved

        if not os.path.isfile(episode_path):
            log.error(f"Episode not found: {episode_path}")
            return

        with open(episode_path, "r", encoding="utf-8") as f:
            episode = json.load(f)

        # Add outcome data
        if "outcome" not in episode:
            episode["outcome"] = {}
        episode["outcome"]["success"] = success
        episode["outcome"]["user_depth"] = user_depth
        episode["outcome"]["recorded_at"] = datetime.now().isoformat()

        # Recompute score with user depth
        new_score = score_episode(episode, user_depth)
        episode["score"] = str(new_score)

        # Write back (atomic — crash-safe)
        atomic_write_json(episode_path, episode)

        log.info(f"Recorded outcome for {os.path.basename(episode_path)}: success={success}, score={new_score}")

        # Gap 4 (closed-loop feedback): every scored episode contributes
        # to today's shared signal so morning/midday/evening builders can
        # read the day's valence. Lazy-imported to avoid hard coupling
        # and a circular at module load.
        try:
            from myalicia.skills.daily_signal import record_episode_scored as _signal_ep
            _ep_task = task_type or (episode.get("task_type") or "?")
            _signal_ep(_ep_task, float(new_score))
        except Exception as _sig_e:
            log.debug(f"daily_signal record_episode_scored skip: {_sig_e}")

    except Exception as e:
        log.error(f"Error recording outcome: {e}")


def get_episode_stats() -> dict:
    """
    Return stats: total episodes, scored episodes, avg reward,
    top task types by reward, episodes indexed today.

    Returns:
        dict with keys: total_episodes, scored_episodes, avg_reward,
                       median_reward, top_task_types, indexed_today
    """
    try:
        index = _load_scores_index()

        if not index:
            return {
                "total_episodes": 0,
                "scored_episodes": 0,
                "avg_reward": 0.0,
                "median_reward": 0.0,
                "top_task_types": {},
                "indexed_today": 0,
            }

        scores = [entry.get("reward_score", 0) for entry in index.values()]
        task_types = {}
        for entry in index.values():
            task = entry.get("task_type", "unknown")
            reward = entry.get("reward_score", 0)
            if task not in task_types:
                task_types[task] = {"count": 0, "total_reward": 0.0}
            task_types[task]["count"] += 1
            task_types[task]["total_reward"] += reward

        # Compute averages by task type
        top_tasks = {}
        for task, data in sorted(
            task_types.items(),
            key=lambda x: x[1]["total_reward"] / x[1]["count"],
            reverse=True
        )[:5]:
            top_tasks[task] = round(data["total_reward"] / data["count"], 4)

        # Check indexed today — LOCAL date on both sides. The stored
        # timestamp is UTC ISO, so convert it to local before comparing
        # against today's local date (otherwise "today" shifts by up to
        # a day for users outside UTC).
        today = datetime.now().date()
        indexed_today = 0
        for entry in index.values():
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.astimezone().date() == today:
                    indexed_today += 1
            except Exception:
                pass

        avg_reward = round(sum(scores) / len(scores), 4) if scores else 0.0
        scores_sorted = sorted(scores)
        median_reward = round(scores_sorted[len(scores_sorted) // 2], 4) if scores else 0.0

        return {
            "total_episodes": len(index),
            "scored_episodes": len(scores),
            "avg_reward": avg_reward,
            "median_reward": median_reward,
            "top_task_types": top_tasks,
            "indexed_today": indexed_today,
        }

    except Exception as e:
        log.error(f"Error computing stats: {e}")
        return {
            "total_episodes": 0,
            "scored_episodes": 0,
            "avg_reward": 0.0,
            "median_reward": 0.0,
            "top_task_types": {},
            "indexed_today": 0,
            "error": str(e),
        }


def get_top_strategies(task_type: str = None, min_score: float = 0.6) -> list[dict]:
    """
    Return the highest-scored episodes as reusable strategies.
    Used by /improve to identify what works best.

    Args:
        task_type: Filter by task type (optional)
        min_score: Minimum reward score to include

    Returns:
        list of dict: Each dict has keys: filename, task_type, reward_score,
                     timestamp, reflection_summary
    """
    try:
        index = _load_scores_index()

        if not index:
            return []

        strategies = []

        for filename, entry in index.items():
            reward = entry.get("reward_score", 0)

            # Filter
            if reward < min_score:
                continue
            if task_type and entry.get("task_type") != task_type:
                continue

            # Load full episode to get reflection
            episode_path = os.path.join(EPISODES_DIR, filename)
            try:
                with open(episode_path, "r", encoding="utf-8") as f:
                    episode = json.load(f)

                reflection = episode.get("reflection", {})
                strategy_dict = {
                    "filename": filename,
                    "task_type": entry.get("task_type", "unknown"),
                    "reward_score": reward,
                    "timestamp": entry.get("timestamp", ""),
                    "went_well": reflection.get("went_well", ""),
                    "procedure_update": reflection.get("procedure_update", ""),
                }
                strategies.append(strategy_dict)

            except Exception as e:
                log.error(f"Error loading strategy {filename}: {e}")

        # Sort by reward descending
        strategies.sort(key=lambda x: x["reward_score"], reverse=True)

        return strategies

    except Exception as e:
        log.error(f"Error in get_top_strategies: {e}")
        return []


def run_daily_scoring() -> dict:
    """
    Daily maintenance: re-index all episodes, apply time decay,
    prune scores for deleted episodes. Called from scheduler.

    Returns:
        dict with keys: indexed_count, pruned_count, stats
    """
    try:
        # Re-index all episodes
        indexed_count = index_episodes()

        # Prune deleted episodes from index
        index = _load_scores_index()
        pruned_count = 0

        for filename in list(index.keys()):
            episode_path = os.path.join(EPISODES_DIR, filename)
            if not os.path.isfile(episode_path):
                del index[filename]
                pruned_count += 1

        # Write pruned index (atomic — crash-safe)
        atomic_write_json(SCORES_INDEX, index)

        # Get stats
        stats = get_episode_stats()

        result = {
            "indexed_count": indexed_count,
            "pruned_count": pruned_count,
            "stats": stats,
            "completed_at": datetime.now().isoformat(),
        }

        log.info(f"Daily scoring complete: indexed={indexed_count}, pruned={pruned_count}")
        return result

    except Exception as e:
        log.error(f"Error in run_daily_scoring: {e}")
        return {
            "error": str(e),
            "indexed_count": 0,
            "pruned_count": 0,
        }


# ── CLI helpers ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python episode_scorer.py [index|stats|strategies|daily]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "index":
        count = index_episodes()
        print(f"Indexed {count} episodes")

    elif cmd == "stats":
        stats = get_episode_stats()
        print(json.dumps(stats, indent=2))

    elif cmd == "strategies":
        task_type = sys.argv[2] if len(sys.argv) > 2 else None
        min_score = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
        strategies = get_top_strategies(task_type, min_score)
        for s in strategies:
            print(f"{s['filename']}: {s['task_type']} (reward={s['reward_score']:.3f})")
            if s['procedure_update']:
                print(f"  Procedure: {s['procedure_update'][:100]}...")

    elif cmd == "daily":
        result = run_daily_scoring()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
