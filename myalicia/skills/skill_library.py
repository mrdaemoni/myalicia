#!/usr/bin/env python3
"""
Alicia — Skill Library as Memory (Memento-Skills Pattern)

Treats the skill config directory as an evolving memory system, not
a flat collection of files. Tracks metadata per config (last_used,
times_rewritten, rule_count, staleness), runs weekly health checks,
and surfaces visibility into the learning system's balance.

Inspired by Memento-Skills (VentureBeat, April 2026): "skills as
evolving external memory with importance scoring, consolidation,
and decay."

Key question this answers: "curiosity_engine's config has been
rewritten 8 times but semantic_search hasn't been touched — is
that because semantic_search is perfect or because /improve can't
observe its failures?"
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from myalicia.skills.safe_io import atomic_write_json

log = logging.getLogger(__name__)

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
LIBRARY_INDEX = os.path.join(MEMORY_DIR, "skill_library.json")
IMPROVE_LOG = os.path.join(MEMORY_DIR, "improve_log.md")


def _load_index() -> dict:
    """Load the skill library index, or return empty structure."""
    if os.path.exists(LIBRARY_INDEX):
        try:
            with open(LIBRARY_INDEX, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            log.warning(f"Failed to load skill library index: {e}")
    return {"skills": {}, "last_scan": None}


def _save_index(index: dict):
    """Persist the skill library index."""
    atomic_write_json(LIBRARY_INDEX, index)


def _count_rules(config_path: str) -> tuple:
    """Count total rules, seed rules, and learned rules in a config."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return (0, 0, 0)

    total = 0
    seed = 0
    learned = 0
    in_rules = False

    for line in content.split("\n"):
        if line.startswith("## Learned Rules") or line.startswith("## Rules"):
            in_rules = True
            continue
        if line.startswith("## ") and in_rules:
            in_rules = False
            continue
        if in_rules and (line.strip().startswith("- ") or line.strip().startswith("* ")):
            total += 1
            if "_(seed)_" in line:
                seed += 1
            elif "_(added" in line:
                learned += 1
            else:
                seed += 1  # unmarked rules count as seed

    return (total, seed, learned)


def _count_params(config_path: str) -> int:
    """Count parameters in a config."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return 0

    count = 0
    in_params = False
    for line in content.split("\n"):
        if line.startswith("## Parameters"):
            in_params = True
            continue
        if line.startswith("## ") and in_params:
            break
        if in_params and line.strip().startswith("- **"):
            count += 1
    return count


def _count_improve_rewrites(skill_name: str) -> int:
    """Count how many times /improve has rewritten this skill's config."""
    if not os.path.exists(IMPROVE_LOG):
        return 0

    try:
        with open(IMPROVE_LOG, "r", encoding="utf-8") as f:
            content = f.read()
        # Count occurrences of skill_name in improve log
        return content.lower().count(skill_name.lower())
    except Exception:
        return 0


def _get_last_modified(config_path: str) -> str:
    """Get last modified timestamp of a config file."""
    try:
        mtime = os.path.getmtime(config_path)
        return datetime.fromtimestamp(mtime).isoformat()
    except Exception:
        return ""


def _days_since_modified(config_path: str) -> int:
    """Days since the config was last modified."""
    try:
        mtime = os.path.getmtime(config_path)
        delta = datetime.now() - datetime.fromtimestamp(mtime)
        return delta.days
    except Exception:
        return 999


def scan_skill_library() -> dict:
    """
    Scan all skill configs and build comprehensive metadata.
    Returns a dict with per-skill stats and library-wide health metrics.
    """
    if not os.path.isdir(CONFIGS_DIR):
        return {"skills": {}, "health": {"status": "no_configs_dir"}}

    skills = {}
    for filename in sorted(os.listdir(CONFIGS_DIR)):
        if not filename.endswith(".md"):
            continue

        skill_name = filename.replace(".md", "")
        config_path = os.path.join(CONFIGS_DIR, filename)

        total_rules, seed_rules, learned_rules = _count_rules(config_path)
        param_count = _count_params(config_path)
        rewrite_count = _count_improve_rewrites(skill_name)
        last_modified = _get_last_modified(config_path)
        days_stale = _days_since_modified(config_path)

        skills[skill_name] = {
            "config_file": filename,
            "total_rules": total_rules,
            "seed_rules": seed_rules,
            "learned_rules": learned_rules,
            "param_count": param_count,
            "times_rewritten": rewrite_count,
            "last_modified": last_modified,
            "days_since_modified": days_stale,
            "learning_velocity": round(learned_rules / max(1, rewrite_count), 2),
            "staleness": "fresh" if days_stale < 7 else "aging" if days_stale < 30 else "stale",
        }

    # Compute library-wide health
    health = _compute_health(skills)

    result = {
        "skills": skills,
        "health": health,
        "scanned_at": datetime.now().isoformat(),
        "total_configs": len(skills),
    }

    # Save to index
    index = _load_index()
    index["skills"] = skills
    index["last_scan"] = datetime.now().isoformat()
    index["health"] = health
    _save_index(index)

    return result


def _compute_health(skills: dict) -> dict:
    """Compute library-wide health metrics."""
    if not skills:
        return {"status": "empty", "issues": ["No skill configs found"]}

    total_learned = sum(s["learned_rules"] for s in skills.values())
    total_seed = sum(s["seed_rules"] for s in skills.values())
    total_rules = sum(s["total_rules"] for s in skills.values())
    total_rewrites = sum(s["times_rewritten"] for s in skills.values())

    stale_skills = [name for name, s in skills.items() if s["staleness"] == "stale"]
    untouched_skills = [name for name, s in skills.items() if s["learned_rules"] == 0]
    hot_skills = [name for name, s in skills.items() if s["times_rewritten"] >= 3]

    issues = []
    recommendations = []

    # Check for imbalance
    if untouched_skills and hot_skills:
        untouched_str = ", ".join(untouched_skills)
        hot_str = ", ".join(hot_skills)
        issues.append(
            f"Imbalanced learning: {hot_str} getting frequent rewrites "
            f"while {untouched_str} remain untouched"
        )
        recommendations.append(
            f"Investigate why /improve never touches {untouched_str} — "
            f"is the reflexion data not capturing failures in those skills?"
        )

    # Check for stale configs
    if stale_skills:
        stale_str = ", ".join(stale_skills)
        issues.append(f"Stale configs (>30 days): {stale_str}")
        recommendations.append(
            f"Consider running /improve with a focus on {stale_str}"
        )

    # Check learning velocity
    if total_learned == 0 and total_rewrites > 0:
        issues.append("Zero learned rules despite /improve runs — improve prompt may need tuning")

    # Check rule density
    avg_rules = total_rules / len(skills) if skills else 0
    if avg_rules < 4:
        recommendations.append(
            "Low average rule density — system is still early in its learning curve"
        )
    elif avg_rules > 20:
        recommendations.append(
            "High rule density — consider consolidating overlapping rules"
        )

    status = "healthy"
    if len(issues) >= 3:
        status = "needs_attention"
    elif len(issues) >= 1:
        status = "minor_issues"

    return {
        "status": status,
        "total_rules": total_rules,
        "total_seed": total_seed,
        "total_learned": total_learned,
        "total_rewrites": total_rewrites,
        "avg_rules_per_skill": round(avg_rules, 1),
        "learning_ratio": round(total_learned / max(1, total_rules), 2),
        "stale_skills": stale_skills,
        "untouched_skills": untouched_skills,
        "hot_skills": hot_skills,
        "issues": issues,
        "recommendations": recommendations,
    }


def run_weekly_library_health() -> dict:
    """
    Weekly health check on the skill library. Called from Sunday weekly pass.
    Returns scan results + comparison to last week.
    """
    log.info("Running skill library health check...")

    # Load previous scan for comparison
    prev_index = _load_index()
    prev_health = prev_index.get("health", {})

    # Run current scan
    current = scan_skill_library()

    # Compute delta
    delta = {}
    curr_health = current.get("health", {})

    if prev_health:
        prev_rules = prev_health.get("total_rules", 0)
        curr_rules = curr_health.get("total_rules", 0)
        prev_learned = prev_health.get("total_learned", 0)
        curr_learned = curr_health.get("total_learned", 0)

        delta = {
            "rules_added": curr_rules - prev_rules,
            "learned_added": curr_learned - prev_learned,
            "new_issues": [i for i in curr_health.get("issues", [])
                          if i not in prev_health.get("issues", [])],
            "resolved_issues": [i for i in prev_health.get("issues", [])
                               if i not in curr_health.get("issues", [])],
        }

    current["delta"] = delta
    log.info(
        f"Skill library: {current['total_configs']} configs, "
        f"{curr_health.get('total_rules', 0)} rules "
        f"({curr_health.get('total_learned', 0)} learned)"
    )
    return current


def format_library_report(result: dict) -> str:
    """Format the library health check for Telegram display."""
    health = result.get("health", {})
    skills = result.get("skills", {})
    delta = result.get("delta", {})

    lines = []
    lines.append(f"*Skill Library Health* ({result.get('total_configs', 0)} configs)")
    lines.append("")

    # Per-skill summary
    for name, meta in sorted(skills.items()):
        icon = "🟢" if meta["staleness"] == "fresh" else "🟡" if meta["staleness"] == "aging" else "🔴"
        lines.append(
            f"{icon} *{name}*: {meta['total_rules']} rules "
            f"({meta['learned_rules']} learned), "
            f"{meta['times_rewritten']}x rewritten"
        )

    lines.append("")

    # Health summary
    ratio = health.get("learning_ratio", 0)
    lines.append(f"Learning ratio: {ratio:.0%} of rules are learned (not seed)")

    # Delta
    if delta:
        added = delta.get("rules_added", 0)
        learned = delta.get("learned_added", 0)
        if added or learned:
            lines.append(f"This week: +{added} rules, +{learned} learned")

    # Issues
    issues = health.get("issues", [])
    if issues:
        lines.append("")
        for issue in issues:
            lines.append(f"⚠️ {issue}")

    # Recommendations
    recs = health.get("recommendations", [])
    if recs:
        lines.append("")
        for rec in recs:
            lines.append(f"💡 {rec}")

    return "\n".join(lines)


def get_library_context() -> str:
    """
    Brief context string for injection into /improve's prompt.
    Tells /improve which skills are getting attention and which aren't.
    """
    index = _load_index()
    skills = index.get("skills", {})

    if not skills:
        return ""

    untouched = [name for name, s in skills.items() if s.get("learned_rules", 0) == 0]
    hot = [name for name, s in skills.items() if s.get("times_rewritten", 0) >= 3]
    stale = [name for name, s in skills.items() if s.get("staleness") == "stale"]

    parts = []
    if untouched:
        untouched_str = ", ".join(untouched)
        parts.append(f"Untouched skills (0 learned rules): {untouched_str}")
    if hot:
        hot_str = ", ".join(hot)
        parts.append(f"Frequently rewritten: {hot_str}")
    if stale:
        stale_str = ", ".join(stale)
        parts.append(f"Stale (>30 days): {stale_str}")

    if not parts:
        return "Skill library: all configs healthy, balanced learning across skills."

    return "Skill library status: " + ". ".join(parts) + "."
