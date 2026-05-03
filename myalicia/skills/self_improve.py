#!/usr/bin/env python3
"""
Alicia — Self-Improvement Engine (/improve)

The module that closes the learning loop. Reads reflexion episodes,
effectiveness data, curiosity engagement, and trajectory analysis,
then writes concrete rule changes into skill config files.

This is what Garry Tan calls "the skill rewrites itself."
Every change is git-tracked. Every rule has provenance.

Safety: append-only rules, max 5 changes per run, full logging.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import re

import dotenv
import anthropic

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
PROCEDURES_FILE = MEMORY_DIR / "procedures.md"
REFLEXION_LOG_FILE = MEMORY_DIR / "reflexion_log.tsv"
PROMPT_EFFECTIVENESS_FILE = MEMORY_DIR / "prompt_effectiveness.tsv"
CURIOSITY_FILE = MEMORY_DIR / "curiosity_followthrough.jsonl"
IMPROVE_LOG_FILE = MEMORY_DIR / "improve_log.md"

# Anthropic client config
OPUS_MODEL = "claude-opus-4-20250514"
MAX_CHANGES_PER_RUN = 5

# Import skill_config functions
from myalicia.skills.skill_config import (
    list_configs,
    load_config,
    get_rules,
    get_param,
    append_rule,
    update_param
)


def _get_api_key() -> str:
    """Get Anthropic API key from environment."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    return api_key


def _get_client() -> anthropic.Anthropic:
    """Lazy-load Anthropic client."""
    return anthropic.Anthropic(api_key=_get_api_key(), max_retries=5)


def _load_recent_procedures(days: int = 7) -> str:
    """Load recent procedure updates from the last N days."""
    if not PROCEDURES_FILE.exists():
        return ""

    try:
        content = PROCEDURES_FILE.read_text(encoding="utf-8")
        lines = content.split("\n")
        cutoff = datetime.now() - timedelta(days=days)

        recent = []
        for line in lines:
            # Extract timestamp from procedure entries like: "[task] (YYYY-MM-DD)"
            match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', line)
            if match:
                try:
                    entry_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                    if entry_date >= cutoff.date():
                        recent.append(line)
                except ValueError:
                    continue

        return "\n".join(recent[:100])  # Last 100 recent procedures
    except Exception as e:
        logger.warning(f"Failed to load procedures: {e}")
        return ""


def _load_recent_episodes(days: int = 7) -> str:
    """Load and summarize recent reflexion episodes."""
    if not EPISODES_DIR.exists():
        return ""

    cutoff = datetime.now() - timedelta(days=days)
    episodes_summary = []

    try:
        for episode_file in sorted(EPISODES_DIR.glob("*.json"), reverse=True)[:50]:
            # Parse timestamp from filename: YYYY-MM-DD_HHMMSS_tasktype.json
            match = re.match(r'(\d{4}-\d{2}-\d{2})_\d{6}_(.+)\.json', episode_file.name)
            if not match:
                continue

            ep_date_str, task_type = match.groups()
            try:
                ep_date = datetime.strptime(ep_date_str, "%Y-%m-%d").date()
                if ep_date < cutoff.date():
                    continue
            except ValueError:
                continue

            try:
                with open(episode_file, "r", encoding="utf-8") as f:
                    episode = json.load(f)

                reflection = episode.get("reflection", {})
                summary = f"[{task_type}] went well: {reflection.get('went_well', 'N/A')[:100]}... to improve: {reflection.get('to_improve', 'N/A')[:100]}..."
                episodes_summary.append(summary)
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"Failed to parse {episode_file.name}: {e}")
                continue

        return "\n".join(episodes_summary[:20])
    except Exception as e:
        logger.warning(f"Failed to load episodes: {e}")
        return ""


def _load_prompt_effectiveness(days: int = 7) -> str:
    """Load recent prompt effectiveness data."""
    if not PROMPT_EFFECTIVENESS_FILE.exists():
        return ""

    try:
        content = PROMPT_EFFECTIVENESS_FILE.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        if not lines:
            return ""

        # Skip header
        cutoff = datetime.now() - timedelta(days=days)
        recent = [lines[0]]  # Keep header

        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) >= 1:
                try:
                    entry_date = datetime.strptime(
                        parts[0], "%Y-%m-%d %H:%M"
                    ).date()
                    if entry_date >= cutoff.date():
                        recent.append(line)
                except ValueError:
                    continue

        return "\n".join(recent[:20])
    except Exception as e:
        logger.warning(f"Failed to load prompt effectiveness: {e}")
        return ""


def _load_curiosity_followthrough() -> str:
    """Load curiosity engagement and followthrough data."""
    if not CURIOSITY_FILE.exists():
        return ""

    try:
        summaries = []
        with open(CURIOSITY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line.strip())
                    if item:
                        summaries.append(
                            f"Type: {item.get('type', 'unknown')}, Engagement: {item.get('engagement_rate', 0):.2f}"
                        )
                except json.JSONDecodeError:
                    continue

        return "\n".join(summaries[-10:])  # Last 10 items
    except Exception as e:
        logger.warning(f"Failed to load curiosity data: {e}")
        return ""


def _get_all_skill_context() -> dict:
    """Load current rules and parameters for all skills."""
    context = {}
    for skill_name in list_configs():
        config = load_config(skill_name)
        context[skill_name] = {
            "rules": get_rules(config),
            "parameters": {},
        }

        # Extract all parameters
        params_text = config.get("parameters", "")
        for line in params_text.split("\n"):
            match = re.search(r'\*\*([^*]+)\*\*:\s*(.+?)(?:\s|$)', line)
            if match:
                key, val = match.groups()
                context[skill_name]["parameters"][key] = val.strip()

    return context


def _parse_improve_response(response_text: str) -> Optional[dict]:
    """Parse Opus response into structured changes dict."""
    # Look for JSON block in response
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if not json_match:
        logger.warning("No JSON found in Opus response")
        return None

    try:
        result = json.loads(json_match.group(0))
        # Validate structure
        if "changes" not in result:
            logger.warning("No 'changes' key in parsed JSON")
            return None
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Opus JSON response: {e}")
        return None


def _apply_change(change: dict) -> bool:
    """
    Apply a single change to a skill config. Returns True if successful.

    SSGM provenance: every add_rule write captures the originating episode
    id, /improve's confidence, and a corroboration date. memory_audit later
    uses these to flag stale rules and roll back the ones that didn't help.
    """
    skill = change.get("skill")
    change_type = change.get("type")
    content = change.get("content")

    if not skill or not change_type or not content:
        logger.warning(f"Incomplete change: {change}")
        return False

    try:
        if change_type == "add_rule":
            reasoning = change.get("reasoning", "improved by /improve")
            rule_text = content
            # Provenance — comes from the change dict if Opus supplied it,
            # otherwise we fall back to whatever signals are available so
            # memory_audit always has something to work with.
            source_episode_id = change.get("source_episode_id")
            confidence_raw = change.get("confidence")
            confidence: float | None
            try:
                confidence = (
                    float(confidence_raw) if confidence_raw is not None else None
                )
            except (TypeError, ValueError):
                confidence = None

            success = append_rule(
                skill,
                rule_text,
                source="improve",
                source_episode_id=source_episode_id,
                confidence=confidence,
                last_corroborated=None,  # defaults to today inside append_rule
            )
            if success:
                logger.info(f"Added rule to {skill}: {rule_text[:80]}")
            return success

        elif change_type == "update_param":
            if isinstance(content, dict):
                key = content.get("key")
                value = content.get("value")
                if key and value:
                    success = update_param(skill, key, str(value))
                    if success:
                        logger.info(f"Updated {skill} param {key}={value}")
                    return success
            else:
                logger.warning(f"Invalid param update format: {content}")
                return False

        else:
            logger.warning(f"Unknown change type: {change_type}")
            return False

    except Exception as e:
        logger.error(f"Failed to apply change: {e}")
        return False


def _log_improve_run(result: dict, summary: str) -> None:
    """Log the improvement run to improve_log.md."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_entry = f"\n## {timestamp}\n\n"
        log_entry += f"**Summary**: {summary}\n\n"
        log_entry += f"**Changes applied**: {len(result.get('changes', []))}\n\n"

        if result.get("changes"):
            log_entry += "### Applied Changes\n"
            for change in result["changes"]:
                log_entry += f"\n- **{change.get('skill')}** ({change.get('type')}): {change.get('reasoning', 'N/A')}\n"

        if result.get("no_change_skills"):
            log_entry += f"\n### No Changes\nSkills with no updates: {', '.join(result['no_change_skills'])}\n"

        # Append to log file
        if IMPROVE_LOG_FILE.exists():
            current_content = IMPROVE_LOG_FILE.read_text(encoding="utf-8")
            IMPROVE_LOG_FILE.write_text(current_content + log_entry, encoding="utf-8")
        else:
            header = "# Improvement Log\n\nRecords of /improve skill rewrites over time.\n"
            IMPROVE_LOG_FILE.write_text(header + log_entry, encoding="utf-8")

        logger.info(f"Logged improvement run to {IMPROVE_LOG_FILE}")
    except Exception as e:
        logger.error(f"Failed to log improvement run: {e}")


def run_weekly_improve() -> dict:
    """
    Main entry point. Runs the weekly self-improvement cycle.

    Steps:
    1. Load all skill configs and current rules/params
    2. Gather learning data from procedures.md, episodes, effectiveness, curiosity
    3. Call Opus with all data and ask for proposed changes
    4. Parse structured JSON response
    5. Apply each change via skill_config functions
    6. Log results to improve_log.md
    7. Return the result dict

    Returns:
        {
            "changes": [
                {
                    "skill": "vault_intelligence",
                    "type": "add_rule" | "update_param",
                    "content": "rule text" | {"key": "param", "value": "new_value"},
                    "reasoning": "why"
                }
            ],
            "no_change_skills": ["reflexion", "memory_skill"],
            "summary": "One paragraph summary"
        }
    """
    logger.info("Starting weekly /improve cycle...")

    # 1. Load current skill context
    skill_context = _get_all_skill_context()
    logger.info(f"Loaded {len(skill_context)} skill configs")

    # 2. Gather learning data
    procedures = _load_recent_procedures(days=7)
    episodes = _load_recent_episodes(days=7)
    effectiveness = _load_prompt_effectiveness(days=7)
    curiosity = _load_curiosity_followthrough()

    # Get meta-reflexion context (tells /improve what worked last time)
    meta_context = ""
    try:
        from myalicia.skills.meta_reflexion import get_meta_reflexion_context
        meta_context = get_meta_reflexion_context()
    except Exception as e:
        logger.warning(f"meta_reflexion context fetch failed: {e}")

    # Get per-rule validation context (H4: did last week's /improve changes
    # actually move the reward needle for the skills they touched?)
    improve_validations_context = ""
    try:
        from myalicia.skills.meta_reflexion import get_improve_validations_context
        improve_validations_context = get_improve_validations_context()
    except Exception as e:
        logger.warning(f"improve_validations context fetch failed: {e}")

    # Get skill library balance context
    library_context = ""
    try:
        from myalicia.skills.skill_library import get_library_context
        library_context = get_library_context()
    except Exception:
        pass

    # Get top strategies from episode scorer
    top_strategies = ""
    try:
        from myalicia.skills.episode_scorer import get_top_strategies
        strategies = get_top_strategies(min_score=0.6)
        if strategies:
            strategy_lines = []
            for s in strategies[:5]:
                ref = s.get("reflection", {})
                strategy_lines.append(
                    f"- [{s.get('task_type', '?')}] score={s.get('reward_score', 0):.2f}: "
                    f"{ref.get('went_well', '?')[:80]}"
                )
            top_strategies = "\n".join(strategy_lines)
    except Exception:
        pass

    learning_summary = f"""
## Recent Learning Data

### Procedures (last 7 days)
{procedures or "[No recent procedures]"}

### Reflexion Episodes Summary
{episodes or "[No recent episodes]"}

### Top-Scoring Strategies (MemRL)
{top_strategies or "[No scored strategies yet]"}

### Prompt Effectiveness Trends
{effectiveness or "[No effectiveness data]"}

### Curiosity Engagement
{curiosity or "[No curiosity data]"}

### Meta-Reflexion Context (how past /improve runs performed)
{meta_context or "[First run — no meta-reflexion data yet]"}

### Per-Rule Validation (did last week's changes actually help?)
{improve_validations_context or "[No per-rule validation data yet]"}

### Skill Library Balance
{library_context or "[No library data yet]"}
"""

    # 3. Build Opus prompt
    skills_section = ""
    for skill_name in sorted(skill_context.keys()):
        context = skill_context[skill_name]
        skills_section += f"\n### {skill_name}\n"
        skills_section += "**Current Rules:**\n"
        for rule in context["rules"][:5]:
            skills_section += f"- {rule}\n"
        if context["parameters"]:
            skills_section += "\n**Current Parameters:**\n"
            for key, val in list(context["parameters"].items())[:5]:
                skills_section += f"- {key}: {val}\n"

    prompt = f"""You are Alicia's self-improvement engine. Your job is to analyze recent learning data and propose concrete, evidence-based improvements to skill rules and parameters.

## Current Skill Configuration

{skills_section}

## Recent Learning Data

{learning_summary}

## Analysis Task

Based on the learning data and current skill configuration:

1. **Identify patterns**: Look for recurring themes in reflexion episodes, procedure updates, and effectiveness metrics.
2. **Spot gaps**: Are there situations where current rules didn't help, or where new insights emerged?
3. **Propose changes**: For each improvement, provide:
   - The skill to improve
   - The change type (add_rule, update_param)
   - The specific rule text or parameter update
   - Clear reasoning with evidence from the learning data

## Constraints

- **Quality over quantity**: Propose only 3-5 changes maximum
- **Evidence required**: Each change must be grounded in the learning data—don't speculate
- **Conservative**: Only propose changes with clear evidence of improvement
- **Append-only rules**: Never suggest deleting rules, only adding new ones or updating parameters
- **No system rules**: Don't modify core system rules or safety constraints

## Output Format

Return ONLY valid JSON (no markdown, no explanation outside the JSON).

For each add_rule change, populate the SSGM provenance fields so the memory_audit pass can validate the rule later:

- `source_episode_id`: the filename of the reflexion episode whose evidence justifies this rule (e.g. "2026-04-26_103045_search_vault.json"). Use "none" only if no single episode drove the change.
- `confidence`: a float 0.0-1.0 reflecting how strongly the learning data supports the rule. < 0.5 means weak; > 0.8 means strong, repeated signal.

```json
{{
    "changes": [
        {{
            "skill": "skill_name",
            "type": "add_rule" | "update_param",
            "content": "rule text" | {{"key": "param_name", "value": "new_value"}},
            "reasoning": "Evidence from learning data supporting this change",
            "source_episode_id": "2026-04-26_103045_search_vault.json",
            "confidence": 0.72
        }}
    ],
    "no_change_skills": ["skill_name1", "skill_name2"],
    "summary": "One paragraph summary of what improved and why"
}}
```
"""

    # 4. Call Opus
    logger.info("Calling Opus for improvement analysis...")
    client = _get_client()

    try:
        response = client.messages.create(
            model=OPUS_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = response.content[0].text
        logger.debug(f"Opus response: {response_text[:500]}")
    except anthropic.APIError as e:
        logger.error(f"Opus API error: {e}")
        return {
            "changes": [],
            "no_change_skills": list(skill_context.keys()),
            "summary": f"API error: {str(e)[:100]}",
        }

    # 5. Parse response
    result = _parse_improve_response(response_text)
    if not result:
        logger.warning("Failed to parse Opus response, returning empty result")
        return {
            "changes": [],
            "no_change_skills": list(skill_context.keys()),
            "summary": "Failed to parse response",
        }

    # 6. Validate and cap changes
    changes = result.get("changes", [])
    if len(changes) > MAX_CHANGES_PER_RUN:
        logger.info(f"Capping {len(changes)} changes to {MAX_CHANGES_PER_RUN}")
        changes = changes[:MAX_CHANGES_PER_RUN]

    # 7. Apply each change
    applied_count = 0
    failed_changes = []

    for i, change in enumerate(changes, 1):
        logger.info(f"Applying change {i}/{len(changes)}: {change.get('skill')}")
        if _apply_change(change):
            applied_count += 1
        else:
            failed_changes.append(change)

    result["changes"] = [c for c in changes if c not in failed_changes]

    # 8. Log the run
    summary = result.get("summary", "No summary provided")
    _log_improve_run(result, summary)

    logger.info(
        f"Completed /improve cycle: {applied_count} changes applied, {len(failed_changes)} failed"
    )
    return result


def get_improve_history(weeks: int = 4) -> str:
    """
    Return recent improvement history from the log file.

    Args:
        weeks: Number of weeks of history to return

    Returns:
        Formatted text of recent improvements
    """
    if not IMPROVE_LOG_FILE.exists():
        return "No improvement history yet."

    try:
        content = IMPROVE_LOG_FILE.read_text(encoding="utf-8")
        lines = content.split("\n")

        cutoff = datetime.now() - timedelta(weeks=weeks)
        recent = []
        current_entry = []

        for line in lines:
            # Each entry starts with "## YYYY-MM-DD HH:MM:SS"
            if line.startswith("## "):
                if current_entry:
                    recent.append("\n".join(current_entry))
                current_entry = [line]

                # Check timestamp
                ts_match = re.search(r'## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                if ts_match:
                    entry_ts = datetime.strptime(
                        ts_match.group(1), "%Y-%m-%d %H:%M:%S"
                    )
                    if entry_ts < cutoff:
                        current_entry = []
            else:
                if current_entry:
                    current_entry.append(line)

        if current_entry:
            recent.append("\n".join(current_entry))

        return "\n".join(recent[-20:])  # Last 20 entries
    except Exception as e:
        logger.error(f"Failed to read improve history: {e}")
        return f"Error reading history: {e}"


def format_improve_report(result: dict) -> str:
    """
    Format the result of run_weekly_improve for display (e.g., Telegram).

    Args:
        result: Dict returned by run_weekly_improve

    Returns:
        Formatted text report
    """
    lines = []
    lines.append("🔄 *Weekly /improve Report*\n")

    summary = result.get("summary", "No summary")
    lines.append(f"Summary: {summary}\n")

    changes = result.get("changes", [])
    lines.append(f"Changes applied: {len(changes)}")

    if changes:
        lines.append("\nImprovement details:")
        for change in changes:
            skill = change.get("skill", "unknown")
            change_type = change.get("type", "unknown")
            reasoning = change.get("reasoning", "N/A")[:100]
            lines.append(f"  • {skill} ({change_type}): {reasoning}...")

    no_change = result.get("no_change_skills", [])
    if no_change:
        lines.append(f"\nStable skills: {', '.join(no_change[:3])}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Example usage
    result = run_weekly_improve()
    print(json.dumps(result, indent=2))
    print("\n" + format_improve_report(result))
