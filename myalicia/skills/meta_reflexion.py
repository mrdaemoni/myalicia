#!/usr/bin/env python3
"""
Alicia — Meta-Reflexion Engine (Hyperagents Pattern)

The improvement process that improves itself. Evaluates whether
/improve's changes were actually effective, and if quality is
declining, rewrites the improvement prompts and heuristics.

Inspired by Hyperagents (arxiv 2603.19461): self-referential agents
where a meta-agent can edit both the task agent and itself, with
improvements that transfer across domains and accumulate across runs.

This is the second-order compounding loop — the system that
improves the system that improves.
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

import dotenv
import anthropic

from myalicia.skills.safe_io import locked_file

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Load environment variables
dotenv.load_dotenv()

# Paths (compatible with both local dev and deployed Alicia)
ALICIA_HOME = Path.home() / "alicia"
MEMORY_DIR = ALICIA_HOME / "memory"
EPISODES_DIR = MEMORY_DIR / "episodes"
SKILLS_DIR = Path(__file__).parent
CONFIG_DIR = SKILLS_DIR / "configs"

# Key memory files
IMPROVE_LOG_FILE = MEMORY_DIR / "improve_log.md"
META_REFLEXION_LOG_FILE = MEMORY_DIR / "meta_reflexion_log.md"
REFLEXION_LOG_FILE = MEMORY_DIR / "reflexion_log.tsv"
# H4: per-rule-change before/after reward log, fed back into run_weekly_improve
IMPROVE_VALIDATIONS_FILE = MEMORY_DIR / "improve_validations.jsonl"

# Anthropic client config
OPUS_MODEL = "claude-opus-4-20250514"
META_THRESHOLD = 0.50  # If effectiveness falls below 50%, trigger meta-improvement


def _get_api_key() -> str:
    """Get Anthropic API key from environment."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    return api_key


def _get_client() -> anthropic.Anthropic:
    """Lazy-load Anthropic client."""
    return anthropic.Anthropic(api_key=_get_api_key(), max_retries=5)


def _parse_improve_log_entry(entry_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single improve_log.md entry (between ## timestamps).

    Returns dict with:
    {
        "timestamp": "2026-04-14 10:35:56",
        "summary": "...",
        "changes_count": 3,
        "changes": [
            {
                "skill": "memory_skill",
                "type": "add_rule",
                "reasoning": "..."
            }
        ],
        "no_change_skills": [...]
    }
    """
    result = {
        "timestamp": None,
        "summary": "",
        "changes_count": 0,
        "changes": [],
        "no_change_skills": []
    }

    lines = entry_text.split("\n")

    # Parse timestamp
    if lines and lines[0].startswith("## "):
        ts_str = lines[0][3:].strip()
        try:
            result["timestamp"] = ts_str
        except Exception as e:
            logger.debug(f"Failed to parse timestamp: {e}")
            return None

    # Parse summary
    for line in lines:
        if line.startswith("**Summary**:"):
            result["summary"] = line.replace("**Summary**:", "").strip()
            break

    # Parse changes count
    for line in lines:
        if "Changes applied" in line:
            match = re.search(r'(\d+)', line)
            if match:
                result["changes_count"] = int(match.group(1))

    # Parse individual changes
    in_changes_section = False
    for line in lines:
        if "Applied Changes" in line:
            in_changes_section = True
            continue
        if in_changes_section:
            if line.startswith("- **"):
                # Extract skill and type
                match = re.match(r'- \*\*(.+?)\*\*\s*\((.+?)\):\s*(.*)', line)
                if match:
                    skill, change_type, reasoning = match.groups()
                    result["changes"].append({
                        "skill": skill.strip(),
                        "type": change_type.strip(),
                        "reasoning": reasoning.strip()
                    })
            elif line.startswith("## "):
                in_changes_section = False

    # Parse no-change skills
    for line in lines:
        if "Stable skills:" in line:
            skills_str = line.replace("Stable skills:", "").strip()
            result["no_change_skills"] = [s.strip() for s in skills_str.split(",")]
            break

    return result


def _load_improve_history(max_runs: int = 10) -> List[Dict[str, Any]]:
    """Load recent /improve runs from the log file."""
    if not IMPROVE_LOG_FILE.exists():
        logger.warning(f"No improve log found at {IMPROVE_LOG_FILE}")
        return []

    try:
        content = IMPROVE_LOG_FILE.read_text(encoding="utf-8")

        # Split by ## timestamp entries
        entries_raw = re.split(r'\n## (?=\d{4}-\d{2}-\d{2})', content)

        parsed_entries = []
        for entry_raw in entries_raw:
            if not entry_raw.strip():
                continue

            # Prepend the ## that was stripped during split
            entry_text = "## " + entry_raw if not entry_raw.startswith("##") else entry_raw

            parsed = _parse_improve_log_entry(entry_text)
            if parsed:
                parsed_entries.append(parsed)

        # Return most recent entries first
        return sorted(parsed_entries,
                     key=lambda x: x["timestamp"] or "",
                     reverse=True)[:max_runs]

    except Exception as e:
        logger.error(f"Failed to load improve history: {e}")
        return []


def _load_episodes_for_date_range(start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
    """Load reflexion episodes from a specific date range."""
    if not EPISODES_DIR.exists():
        return []

    episodes = []
    try:
        for episode_file in EPISODES_DIR.glob("*.json"):
            # Parse timestamp from filename: YYYY-MM-DD_HHMMSS_tasktype.json
            match = re.match(r'(\d{4}-\d{2}-\d{2})_\d{6}_(.+)\.json', episode_file.name)
            if not match:
                continue

            ep_date_str, task_type = match.groups()
            try:
                ep_date = datetime.strptime(ep_date_str, "%Y-%m-%d").date()
                if start_date.date() <= ep_date <= end_date.date():
                    with open(episode_file, "r", encoding="utf-8") as f:
                        episode = json.load(f)
                        episode["file"] = episode_file.name
                        episode["task_type"] = task_type
                        episodes.append(episode)
            except (ValueError, json.JSONDecodeError) as e:
                logger.debug(f"Failed to parse episode {episode_file.name}: {e}")
                continue

    except Exception as e:
        logger.error(f"Failed to load episodes: {e}")

    return episodes


def _score_episodes(episodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze episodes for quality metrics.

    Returns:
    {
        "avg_confidence": float,
        "total_episodes": int,
        "by_task_type": {
            "task_type": {
                "count": int,
                "avg_confidence": float,
                "high_confidence": int
            }
        },
        "to_improve_mentions": List[str],
        "procedure_updates": int
    }
    """
    if not episodes:
        return {
            "avg_confidence": 0.0,
            "total_episodes": 0,
            "by_task_type": {},
            "to_improve_mentions": [],
            "procedure_updates": 0
        }

    result = {
        "avg_confidence": 0.0,
        "total_episodes": len(episodes),
        "by_task_type": {},
        "to_improve_mentions": [],
        "procedure_updates": 0
    }

    confidences = []

    for episode in episodes:
        reflection = episode.get("reflection", {})
        task_type = episode.get("task_type", "unknown")

        # Aggregate by task type
        if task_type not in result["by_task_type"]:
            result["by_task_type"][task_type] = {
                "count": 0,
                "avg_confidence": 0.0,
                "high_confidence": 0,
                "confidences": []
            }

        confidence = reflection.get("confidence", 0)
        if isinstance(confidence, (int, float)):
            confidences.append(confidence)
            result["by_task_type"][task_type]["confidences"].append(confidence)
            if confidence >= 4:
                result["by_task_type"][task_type]["high_confidence"] += 1

        result["by_task_type"][task_type]["count"] += 1

        # Collect "to improve" mentions for pattern detection
        to_improve = reflection.get("to_improve", "")
        if to_improve:
            result["to_improve_mentions"].append(to_improve[:100])

        # Count procedure updates
        if reflection.get("procedure_update"):
            result["procedure_updates"] += 1

    # Calculate averages
    if confidences:
        result["avg_confidence"] = sum(confidences) / len(confidences)

    for task_type_data in result["by_task_type"].values():
        if task_type_data["confidences"]:
            task_type_data["avg_confidence"] = sum(task_type_data["confidences"]) / len(task_type_data["confidences"])
        del task_type_data["confidences"]

    return result


def evaluate_improve_effectiveness() -> Dict[str, Any]:
    """
    Read the improve_log.md and compare pre/post data for each /improve run.

    For each past /improve run:
    1. Read what changes were made (from improve_log.md)
    2. Read reflexion episodes from BEFORE the changes (7 days prior)
    3. Read reflexion episodes from AFTER the changes (7 days after)
    4. Compare: did the relevant skill's episodes improve?
       - Higher avg confidence scores?
       - Fewer "to_improve" entries mentioning the same issue?
       - More procedure_updates generated (sign of productive learning)?

    Returns dict with:
    {
        "runs_evaluated": int,
        "effective_changes": int,
        "ineffective_changes": int,
        "neutral_changes": int,
        "effectiveness_rate": float,
        "declining": bool,
        "details": [...]
    }
    """
    logger.info("Evaluating /improve effectiveness...")

    improve_history = _load_improve_history(max_runs=10)

    if not improve_history:
        logger.warning("No /improve history found")
        return {
            "runs_evaluated": 0,
            "effective_changes": 0,
            "ineffective_changes": 0,
            "neutral_changes": 0,
            "effectiveness_rate": 0.0,
            "declining": False,
            "details": [],
            "error": "No improve history"
        }

    details = []
    total_changes = 0
    effective_changes = 0
    ineffective_changes = 0
    neutral_changes = 0

    # Evaluate last 3 runs in detail (more recent = more relevant)
    for run_idx, run in enumerate(improve_history[:3]):
        if not run["timestamp"] or not run["changes"]:
            continue

        try:
            # Parse run timestamp
            run_date = datetime.strptime(run["timestamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            logger.debug(f"Failed to parse run timestamp: {e}")
            continue

        before_start = run_date - timedelta(days=14)
        before_end = run_date - timedelta(days=7)
        after_start = run_date + timedelta(days=1)
        after_end = run_date + timedelta(days=8)

        # Load episodes before and after
        episodes_before = _load_episodes_for_date_range(before_start, before_end)
        episodes_after = _load_episodes_for_date_range(after_start, after_end)

        before_scores = _score_episodes(episodes_before)
        after_scores = _score_episodes(episodes_after)

        run_detail = {
            "run_index": run_idx,
            "timestamp": run["timestamp"],
            "changes": len(run["changes"]),
            "episodes_before": before_scores["total_episodes"],
            "episodes_after": after_scores["total_episodes"],
            "confidence_before": before_scores["avg_confidence"],
            "confidence_after": after_scores["avg_confidence"],
            "procedure_updates_before": before_scores["procedure_updates"],
            "procedure_updates_after": after_scores["procedure_updates"],
            "effectiveness_assessment": "neutral"
        }

        # Determine if changes were effective
        confidence_improvement = after_scores["avg_confidence"] - before_scores["avg_confidence"]
        procedure_improvement = after_scores["procedure_updates"] - before_scores["procedure_updates"]

        # Heuristic: effective if confidence improved by >0.3 OR procedure updates increased
        if confidence_improvement > 0.3 or procedure_improvement > 0:
            run_detail["effectiveness_assessment"] = "effective"
            effective_changes += len(run["changes"])
        elif confidence_improvement < -0.2:
            run_detail["effectiveness_assessment"] = "ineffective"
            ineffective_changes += len(run["changes"])
        else:
            neutral_changes += len(run["changes"])

        total_changes += len(run["changes"])
        details.append(run_detail)

    effectiveness_rate = effective_changes / total_changes if total_changes > 0 else 0.0

    # Check if declining: last 2 runs have effectiveness < 50%
    declining = False
    if len(details) >= 2:
        last_two_effective = effective_changes / (len(details[-2:]) * 3) if total_changes > 0 else 0
        declining = last_two_effective < META_THRESHOLD

    result = {
        "runs_evaluated": len(details),
        "effective_changes": effective_changes,
        "ineffective_changes": ineffective_changes,
        "neutral_changes": neutral_changes,
        "effectiveness_rate": effectiveness_rate,
        "declining": declining,
        "details": details
    }

    logger.info(f"Effectiveness evaluation: {effectiveness_rate:.1%} effective")
    return result


def generate_meta_improvements(effectiveness: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    If improvement effectiveness is declining (< 50% over last 2 runs),
    call Opus to analyze WHY and propose changes to the /improve process.

    The meta-improvement can:
    1. Suggest changes to self_improve.py's Opus prompt
       (saved as ~/alicia/skills/configs/self_improve.md — a config for /improve itself)
    2. Adjust scoring heuristics (what counts as "actionable evidence")
    3. Propose new data sources for /improve to read
    4. Recommend focus areas for next /improve run

    Returns structured proposals (not auto-applied — logged for review).
    """
    # Only generate meta-improvements if declining or below threshold
    if effectiveness["effectiveness_rate"] >= META_THRESHOLD and not effectiveness["declining"]:
        logger.info("Improvement process is healthy, no meta-improvements needed")
        return None

    logger.info("Improvement process effectiveness declining, generating meta-improvements...")

    # Build context from effectiveness analysis
    context = f"""
## Current Improvement Effectiveness

- Effectiveness rate: {effectiveness['effectiveness_rate']:.1%}
- Effective changes: {effectiveness['effective_changes']}
- Ineffective changes: {effectiveness['ineffective_changes']}
- Neutral changes: {effectiveness['neutral_changes']}
- Declining: {effectiveness['declining']}

## Recent Run Details

"""

    for detail in effectiveness.get("details", []):
        context += f"""
### Run {detail['run_index']} ({detail['timestamp']})
- Changes applied: {detail['changes']}
- Episodes before: {detail['episodes_before']}, confidence: {detail['confidence_before']:.2f}
- Episodes after: {detail['episodes_after']}, confidence: {detail['confidence_after']:.2f}
- Procedure updates: {detail['procedure_updates_before']} → {detail['procedure_updates_after']}
- Assessment: {detail['effectiveness_assessment']}
"""

    prompt = f"""You are Alicia's meta-improvement engine. Your job is to analyze why the /improve skill's proposed changes are becoming less effective, and recommend improvements to the improvement process itself.

## Current State

{context}

## Analysis Task

Based on the effectiveness data:

1. **Diagnosis**: Why might /improve's changes be becoming less effective?
   - Is it proposing changes that are too incremental?
   - Is it missing important signals in the learning data?
   - Are the evidence thresholds wrong?
   - Is the skill scope too broad?

2. **Root causes**: Identify 2-3 specific failure modes:
   - What patterns of ineffective changes do you see?
   - What opportunities is /improve missing?
   - What data sources are underutilized?

3. **Meta-improvements**: Propose changes to /improve itself:
   - Changes to the Opus prompt (how it analyzes data)
   - New heuristics for evaluating evidence quality
   - New data sources or metrics to incorporate
   - Adjusted constraints or focus areas
   - Scoring criteria adjustments

4. **Implementation**: For each proposal, specify:
   - What to change (e.g., "add skill-specific thresholds")
   - Why it should help (grounded in the pattern analysis)
   - How to validate it worked (what metric to watch)

## Constraints

- Focus on process improvements, not one-time fixes
- Proposals should be testable and measurable
- Don't suggest discarding existing good signals
- Prefer small, targeted changes over wholesale rewrites

## Output Format

Return ONLY valid JSON (no markdown, no explanation outside):

{{
    "diagnosis": "2-3 sentence explanation of why effectiveness is declining",
    "root_causes": [
        {{"cause": "specific failure mode", "evidence": "from the data"}},
        {{"cause": "...", "evidence": "..."}}
    ],
    "meta_improvements": [
        {{
            "target": "prompt" | "heuristic" | "data_source" | "constraint",
            "change": "specific change to make",
            "rationale": "why this helps",
            "metric": "how to validate success"
        }}
    ],
    "confidence": 1-5,
    "summary": "One paragraph summary of recommended strategy"
}}
"""

    logger.info("Calling Opus for meta-improvement analysis...")
    client = _get_client()

    try:
        response = client.messages.create(
            model=OPUS_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = response.content[0].text
        logger.debug(f"Meta-improvement response: {response_text[:500]}")
    except anthropic.APIError as e:
        logger.error(f"Opus API error during meta-improvement: {e}")
        return None

    # Parse response
    try:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            logger.info(f"Generated {len(result.get('meta_improvements', []))} meta-improvements")
            return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse meta-improvement response: {e}")
        return None

    return None


def run_meta_reflexion() -> Dict[str, Any]:
    """
    Main entry point. Called after /improve runs (weekly or on-demand).

    Steps:
    1. evaluate_improve_effectiveness()
    2. If declining or effectiveness < 50%: generate_meta_improvements()
    3. If not declining: log "meta-reflexion: improvement process healthy"
    4. Always: update ~/alicia/memory/meta_reflexion_log.md with findings

    Returns results dict.
    """
    logger.info("Starting meta-reflexion cycle...")

    # 1. Evaluate effectiveness
    effectiveness = evaluate_improve_effectiveness()

    # 2. Generate meta-improvements if needed
    meta_improvements = None
    if effectiveness["effectiveness_rate"] < META_THRESHOLD or effectiveness["declining"]:
        meta_improvements = generate_meta_improvements(effectiveness)

    # 3. & 4. Build result and log
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "effectiveness": effectiveness,
        "meta_improvements": meta_improvements,
        "status": "healthy" if effectiveness["effectiveness_rate"] >= META_THRESHOLD else "declining"
    }

    # Log to meta_reflexion_log.md
    _log_meta_reflexion(result)

    logger.info(f"Meta-reflexion complete: status={result['status']}")
    return result


def _log_meta_reflexion(result: Dict[str, Any]) -> None:
    """Log meta-reflexion findings to meta_reflexion_log.md."""
    try:
        timestamp = result["timestamp"]
        effectiveness = result["effectiveness"]
        meta_improvements = result["meta_improvements"]
        status = result["status"]

        log_entry = f"\n## {timestamp}\n\n"
        log_entry += f"**Status**: {status}\n\n"
        log_entry += f"**Effectiveness**: {effectiveness['effectiveness_rate']:.1%} "
        log_entry += f"({effectiveness['effective_changes']} effective, "
        log_entry += f"{effectiveness['ineffective_changes']} ineffective, "
        log_entry += f"{effectiveness['neutral_changes']} neutral)\n\n"

        if effectiveness.get("declining"):
            log_entry += "**Alert**: Improvement effectiveness is declining\n\n"

        if meta_improvements:
            log_entry += "### Meta-Improvements Proposed\n\n"
            log_entry += f"Diagnosis: {meta_improvements.get('diagnosis', 'N/A')}\n\n"
            log_entry += "Root causes:\n"
            for cause in meta_improvements.get("root_causes", []):
                log_entry += f"- {cause.get('cause', 'unknown')}: {cause.get('evidence', 'N/A')}\n"
            log_entry += "\nProposed meta-improvements:\n"
            for imp in meta_improvements.get("meta_improvements", []):
                log_entry += f"- **{imp.get('target', 'unknown')}**: {imp.get('change', 'N/A')}\n"
                log_entry += f"  Rationale: {imp.get('rationale', 'N/A')}\n"
        else:
            log_entry += "No meta-improvements needed (process is healthy)\n\n"

        # Append to log file
        if META_REFLEXION_LOG_FILE.exists():
            current = META_REFLEXION_LOG_FILE.read_text(encoding="utf-8")
            META_REFLEXION_LOG_FILE.write_text(current + log_entry, encoding="utf-8")
        else:
            header = "# Meta-Reflexion Log\n\nSecond-order learning: evaluates and improves the improvement process itself.\n"
            META_REFLEXION_LOG_FILE.write_text(header + log_entry, encoding="utf-8")

        logger.info(f"Logged meta-reflexion to {META_REFLEXION_LOG_FILE}")
    except Exception as e:
        logger.error(f"Failed to log meta-reflexion: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# H4: Improve-output validation loop
#
# Closes the Level-2 feedback loop: evaluate_improve_effectiveness() averages
# confidence across ALL tasks. This function does it *per rule change*, using
# MemRL reward scores, and persists a row per change to improve_validations.jsonl
# so future /improve runs can see "rule X on skill Y, applied at T, moved
# reward from 0.62 → 0.71 over the next 7 days."
# ─────────────────────────────────────────────────────────────────────────────


def _episode_reward(episode: Dict[str, Any]) -> Optional[float]:
    """
    Return the best-available reward signal for an episode.

    Uses episode_scorer.score_episode when available (MemRL reward) and falls
    back to reflection.confidence normalised to 0.0-1.0. Returns None if neither
    signal is available.
    """
    try:
        from myalicia.skills.episode_scorer import score_episode
        score = score_episode(episode)
        if isinstance(score, (int, float)):
            return float(score)
    except Exception as e:
        logger.debug(f"episode_scorer unavailable, falling back to confidence: {e}")

    conf = episode.get("reflection", {}).get("confidence")
    if isinstance(conf, (int, float)):
        # Reflection confidence is 1-5; normalise to 0.0-1.0 for comparability.
        return max(0.0, min(1.0, (float(conf) - 1.0) / 4.0))
    return None


def _mean_reward_for_skill(
    skill: str,
    start: datetime,
    end: datetime,
) -> tuple[float, int]:
    """
    Mean reward + episode count for a skill across a date range.

    Returns (0.0, 0) if no episodes exist — caller must check count before
    treating the mean as meaningful.
    """
    episodes = _load_episodes_for_date_range(start, end)
    rewards: list[float] = []
    for ep in episodes:
        if ep.get("task_type") != skill:
            continue
        r = _episode_reward(ep)
        if r is not None:
            rewards.append(r)
    if not rewards:
        return (0.0, 0)
    return (sum(rewards) / len(rewards), len(rewards))


def _classify_delta(delta: float, episodes_before: int, episodes_after: int) -> str:
    """
    Classify a before/after reward delta.

    Requires ≥2 episodes on each side before claiming "helped" or "hurt";
    otherwise returns "insufficient_data". This is the guardrail against
    declaring a rule successful off a single lucky episode.
    """
    if episodes_before < 2 or episodes_after < 2:
        return "insufficient_data"
    if delta > 0.05:
        return "helped"
    if delta < -0.05:
        return "hurt"
    return "neutral"


def validate_improve_outputs(lookback_days: int = 7, window_days: int = 7) -> Dict[str, Any]:
    """
    Score each rule change in the last `lookback_days` by the reward delta
    between the `window_days` before and after the /improve run.

    Appends one JSON line per rule change to improve_validations.jsonl.
    Called Monday 22:00 so Sunday's /improve run has ~2 days of post-change
    episodes, plus the prior week's episodes as the "before" baseline.

    Returns a summary dict for logging / Telegram notification.
    """
    logger.info(f"Running /improve validation — lookback={lookback_days}d window={window_days}d")

    now = datetime.now()
    cutoff = now - timedelta(days=lookback_days)

    runs = _load_improve_history(max_runs=10)
    recent_runs = []
    for run in runs:
        if not run.get("timestamp"):
            continue
        try:
            run_date = datetime.strptime(run["timestamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if run_date >= cutoff:
            recent_runs.append((run_date, run))

    if not recent_runs:
        logger.info("No /improve runs in lookback window — nothing to validate")
        return {
            "validated_at": now.isoformat(),
            "runs_checked": 0,
            "changes_scored": 0,
            "validations": [],
        }

    validations: list[dict] = []
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # Accumulate all new lines then append under a single fcntl lock — prevents
    # interleaving if two validators ever run concurrently (manual + scheduled).
    new_lines: list[str] = []

    for run_date, run in recent_runs:
        before_start = run_date - timedelta(days=window_days)
        before_end = run_date
        after_start = run_date + timedelta(hours=1)  # exclude the run timestamp itself
        after_end = run_date + timedelta(days=window_days)

        for change in run.get("changes", []):
            skill = change.get("skill")
            if not skill:
                continue
            reward_before, ep_before = _mean_reward_for_skill(skill, before_start, before_end)
            reward_after, ep_after = _mean_reward_for_skill(skill, after_start, after_end)
            delta = reward_after - reward_before if ep_before and ep_after else 0.0
            assessment = _classify_delta(delta, ep_before, ep_after)

            entry = {
                "validated_at": now.isoformat(),
                "improve_run_at": run["timestamp"],
                "skill": skill,
                "change_type": change.get("type", ""),
                "reasoning": change.get("reasoning", "")[:500],
                "episodes_before": ep_before,
                "reward_before": round(reward_before, 4),
                "episodes_after": ep_after,
                "reward_after": round(reward_after, 4),
                "delta": round(delta, 4),
                "assessment": assessment,
                "window_days": window_days,
            }
            validations.append(entry)
            new_lines.append(json.dumps(entry, ensure_ascii=False))

    if new_lines:
        # §D3 — Validate every line against the registered JSONL schema
        # before writing. Drift logs a warning but does not stop the
        # write (we never want schema drift to silently *drop* data;
        # better to write a line with a warning and fix later).
        try:
            from skills import bridge_schema
            for entry in validations:
                try:
                    bridge_schema.validate_jsonl_line(
                        "improve_validations.jsonl", entry
                    )
                except bridge_schema.ValidationError as ve:
                    logger.warning(f"improve_validations line drift: {ve}")
        except ImportError:
            pass

        try:
            with locked_file(IMPROVE_VALIDATIONS_FILE, "a") as f:
                f.write("\n".join(new_lines) + "\n")
        except Exception as e:
            logger.error(f"Failed to append validations: {e}")

    summary = {
        "validated_at": now.isoformat(),
        "runs_checked": len(recent_runs),
        "changes_scored": len(validations),
        "helped": sum(1 for v in validations if v["assessment"] == "helped"),
        "hurt": sum(1 for v in validations if v["assessment"] == "hurt"),
        "neutral": sum(1 for v in validations if v["assessment"] == "neutral"),
        "insufficient_data": sum(1 for v in validations if v["assessment"] == "insufficient_data"),
        "validations": validations,
    }
    logger.info(
        f"Validation complete: {summary['changes_scored']} changes across "
        f"{summary['runs_checked']} runs "
        f"(helped={summary['helped']} hurt={summary['hurt']} "
        f"neutral={summary['neutral']} "
        f"insufficient={summary['insufficient_data']})"
    )
    return summary


def get_improve_validations_context(max_entries: int = 20) -> str:
    """
    Format the last `max_entries` rule-change validations as a compact
    markdown block for injection into run_weekly_improve's Opus prompt.

    Tells /improve: "here's which of your past rewrites helped or hurt —
    double down on the patterns that worked and stop proposing ones that
    don't." Empty string if the validations file is missing or empty.
    """
    if not IMPROVE_VALIDATIONS_FILE.exists():
        return ""

    try:
        with locked_file(IMPROVE_VALIDATIONS_FILE, "r") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except Exception as e:
        logger.warning(f"Failed to read improve_validations.jsonl: {e}")
        return ""

    if not lines:
        return ""

    # Parse most recent entries first.
    recent: list[dict] = []
    for ln in reversed(lines):
        try:
            recent.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
        if len(recent) >= max_entries:
            break

    if not recent:
        return ""

    by_skill: dict[str, list[dict]] = {}
    for v in recent:
        by_skill.setdefault(v.get("skill", "?"), []).append(v)

    out: list[str] = [
        "## Past Rule-Change Validations",
        "",
        "Each prior /improve rule change, scored by the reward delta over "
        "the 7 days before vs. 7 days after. Use this to avoid repeating "
        "changes that didn't move the needle.",
        "",
    ]
    for skill in sorted(by_skill.keys()):
        entries = by_skill[skill]
        helped = sum(1 for e in entries if e["assessment"] == "helped")
        hurt = sum(1 for e in entries if e["assessment"] == "hurt")
        neutral = sum(1 for e in entries if e["assessment"] == "neutral")
        insuff = sum(1 for e in entries if e["assessment"] == "insufficient_data")
        out.append(
            f"- **{skill}**: helped={helped} hurt={hurt} "
            f"neutral={neutral} insufficient_data={insuff}"
        )
        # Show the 2 most recent entries for this skill in detail.
        for e in entries[:2]:
            out.append(
                f"  - [{e.get('assessment')}] "
                f"Δ={e.get('delta'):+.3f} "
                f"(before {e.get('reward_before'):.2f} / n={e.get('episodes_before')}; "
                f"after {e.get('reward_after'):.2f} / n={e.get('episodes_after')}) "
                f"— {(e.get('reasoning') or '')[:120]}"
            )
    return "\n".join(out)


def get_meta_reflexion_context() -> str:
    """
    Brief context string for injection into /improve's prompt.
    Tells /improve what worked and what didn't in past runs,
    so it can adjust its strategy.
    """
    effectiveness = evaluate_improve_effectiveness()

    if not effectiveness.get("details"):
        return ""

    context_lines = [
        "## Meta-Reflexion Insights for /improve",
        "",
        f"**Overall effectiveness**: {effectiveness['effectiveness_rate']:.1%}",
        f"**Effective changes**: {effectiveness['effective_changes']}",
        f"**Declining**: {effectiveness['declining']}",
        ""
    ]

    # Add insights from recent runs
    if effectiveness.get("details"):
        context_lines.append("### Recent Run Analysis")
        for detail in effectiveness["details"][:2]:
            context_lines.append(
                f"- Run {detail['run_index']} ({detail['timestamp']}): "
                f"{detail['effectiveness_assessment']}, "
                f"confidence {detail['confidence_before']:.2f} → {detail['confidence_after']:.2f}"
            )

    return "\n".join(context_lines)


def format_meta_report(result: Dict[str, Any]) -> str:
    """Format meta-reflexion results for Telegram display."""
    lines = []
    lines.append("🔬 *Meta-Reflexion Report*\n")

    effectiveness = result.get("effectiveness", {})
    status = result.get("status", "unknown")

    lines.append(f"Status: {status}\n")
    lines.append(f"Improvement Effectiveness: {effectiveness.get('effectiveness_rate', 0):.1%}\n")

    if effectiveness.get("declining"):
        lines.append("⚠️ *Process is declining* — meta-improvements generated\n")

    # Summarize effectiveness
    lines.append(
        f"Effective: {effectiveness.get('effective_changes', 0)} | "
        f"Ineffective: {effectiveness.get('ineffective_changes', 0)} | "
        f"Neutral: {effectiveness.get('neutral_changes', 0)}\n"
    )

    # Meta-improvements summary
    meta_improvements = result.get("meta_improvements")
    if meta_improvements:
        lines.append("\n*Recommended meta-improvements:*")
        for imp in meta_improvements.get("meta_improvements", []):
            lines.append(f"• {imp.get('target')}: {imp.get('change')[:80]}")

    return "\n".join(lines)


if __name__ == "__main__":
    result = run_meta_reflexion()
    print(json.dumps(result, indent=2, default=str))
    print("\n" + format_meta_report(result))
