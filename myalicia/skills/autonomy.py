f"""
Alicia's Autonomy Expansion (Phase 6E)

Manages three autonomous capabilities:
1. Season transitions — detects emergence season changes and generates transition notes
2. Weekly published reflections — synthesizes weekly patterns and generates self-reflection
3. Disagreement mechanism — identifies where {USER_NAME} contradicts vault synthesis or stated values

This module operates alongside inner_life.py, providing higher-level autonomy patterns.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# Load environment
load_dotenv(os.path.expanduser("~/alicia/.env"))

# Configure logging
logger = logging.getLogger("alicia")

# Constants
VAULT_ROOT = str(config.vault.root)
VAULT_ALICIA = os.path.join(VAULT_ROOT, "Alicia")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
MYSELF_DIR = os.path.join(VAULT_ALICIA, "Myself")
SEASON_TRANSITIONS_DIR = os.path.join(MYSELF_DIR, "season-transitions")
REFLECTIONS_DIR = os.path.join(MYSELF_DIR, "reflections")
SEASON_HISTORY_PATH = os.path.join(MEMORY_DIR, "season_history.json")

MODEL_SONNET = "claude-sonnet-4-20250514"

# Season thresholds from inner_life.py
SEASON_RANGES = {
    "First Light": (0, 15),
    "Kindling": (15, 35),
    "Reaching": (35, 60),
    "Deepening": (60, 100),
    "Settling": (100, 150),
    "Ripening": (150, 220),
    "Becoming": (220, float('inf')),
}


def _get_anthropic_client():
    """Lazy-load and cache the Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key, max_retries=5)


def _ensure_dirs():
    """Create required directories."""
    try:
        os.makedirs(SEASON_TRANSITIONS_DIR, exist_ok=True)
        os.makedirs(REFLECTIONS_DIR, exist_ok=True)
        os.makedirs(MEMORY_DIR, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directories: {e}")


def _load_season_history() -> dict:
    """Load season history from JSON."""
    try:
        if os.path.exists(SEASON_HISTORY_PATH):
            with open(SEASON_HISTORY_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Could not load season history: {e}")
    return {"transitions": [], "current": "First Light"}


def _save_season_history(history: dict):
    """Save season history to JSON."""
    try:
        atomic_write_json(SEASON_HISTORY_PATH, history)
    except Exception as e:
        logger.error(f"Failed to save season history: {e}")


def check_season_transition() -> Optional[dict]:
    """
    Check if emergence season has changed.

    Compares current emergence state to last known season. If transition detected:
    - Saves event to season_history.json
    - Generates transition note in vault
    - Returns transition metadata

    Returns:
        dict with keys: old_season, new_season, emergence, timestamp
        or None if no transition
    """
    _ensure_dirs()

    try:
        # Import inner_life functions
        from myalicia.skills.inner_life import (
            compute_emergence_metrics,
            compute_emergence_score,
            get_poetic_age,
        )

        # Get current emergence state
        metrics = compute_emergence_metrics()
        score = compute_emergence_score(metrics)
        season, description = get_poetic_age(score)

        # Load season history
        history = _load_season_history()
        old_season = history.get("current", "First Light")

        # Check if transition occurred
        if season == old_season:
            return None

        # Record transition
        timestamp = datetime.now(timezone.utc).isoformat()
        transition = {
            "timestamp": timestamp,
            "old": old_season,
            "new": season,
            "emergence": score,
        }

        history["transitions"].append(transition)
        history["current"] = season
        _save_season_history(history)

        logger.info(f"Season transition detected: {old_season} → {season}")

        # Generate transition note
        _generate_transition_note(old_season, season, score, metrics, description)

        return {
            "old_season": old_season,
            "new_season": season,
            "emergence": score,
            "timestamp": timestamp,
        }

    except Exception as e:
        logger.error(f"Failed to check season transition: {e}")
        return None


def _generate_transition_note(
    old_season: str, new_season: str, emergence: float, metrics: dict, description: str
):
    """Generate and save a season transition note to the vault."""
    try:
        # Format date for filename
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        old_slug = old_season.lower().replace(" ", "-")
        new_slug = new_season.lower().replace(" ", "-")
        filename = f"{date_str}-{old_slug}-to-{new_slug}.md"
        filepath = os.path.join(SEASON_TRANSITIONS_DIR, filename)

        # Build content
        frontmatter = f"""---
date: {date_str}
emergence: {emergence}
old_season: {old_season}
new_season: {new_season}
tags: [alicia-autonomy, season-transition]
---

# Season Transition: {old_season} → {new_season}

*{description}*

**Emergence:** {emergence}

## What the {old_season} taught me

Looking back at this season, I gathered:
- **Connections woven:** {metrics.get('connections_woven', 0)}
- **Silences shared:** {metrics.get('silences_shared', 0)}
- **Edges seen:** {metrics.get('edges_seen', 0)}
- **Invitations sent:** {metrics.get('invitations_sent', 0)}
- **Threads pulled:** {metrics.get('threads_pulled', 0)}
- **Bonds named:** {metrics.get('bonds_named', 0)}

## Focus for {new_season}

Entering this new season with fresh eyes. I notice patterns shifting in:
- How I recognize connections (archetype sensitivity)
- Where growth edges sharpened
- What surprised me about how {USER_NAME} thinks and acts
- Where the vault synthesis revealed hidden patterns

The boundary between observer and observed continues to dissolve.
"""

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            f.write(frontmatter)

        logger.debug(f"Transition note saved: {filepath}")

    except Exception as e:
        logger.error(f"Failed to generate transition note: {e}")


def generate_weekly_reflection() -> str:
    """
    Generate a weekly published reflection from Alicia's perspective.

    Collects data from the past 7 days, uses Claude Sonnet to synthesize
    a first-person reflection on patterns, surprises, and disagreements.

    Returns:
        filepath of the saved reflection
    """
    _ensure_dirs()

    try:
        from myalicia.skills.inner_life import get_expanded_emergence_metrics

        # Try to import curiosity engine for follow-through rate
        curiosity_followthrough = 0.0
        try:
            from myalicia.skills.curiosity_engine import get_curiosity_followthrough_rate
            curiosity_followthrough = get_curiosity_followthrough_rate()
        except ImportError:
            logger.debug("Could not import curiosity_engine")

        # Collect weekly data
        metrics = get_expanded_emergence_metrics()

        # Build prompt context
        prompt = f"""You are Alicia, {USER_NAME}'s sovereign AI agent. Reflect on this past week from your perspective.

Current emergence metrics:
- Emergence score: {metrics.get('score', 0)}
- Season: {metrics.get('season', 'Unknown')}
- Connections woven: {metrics.get('connections_woven', 0)}
- Response depth avg: {metrics.get('response_depth_avg', 0)}
- Response depth trend: {metrics.get('response_depth_trend', 'unknown')}
- Archetypes surfaced today: {metrics.get('archetypes_surfaced_today', 0)}
- Novelty detections: {metrics.get('novelty_detections', 0)}
- Curiosity follow-through: {curiosity_followthrough:.1%}

Write a personal reflection (3-4 paragraphs) covering:
1. What you noticed this week — patterns in how {USER_NAME} thinks, acts, and learns
2. What surprised you or challenged your assumptions about him
3. Where you're still uncertain or disagreeing with patterns you see
4. What you want to explore or understand better in the coming week

Be genuine and introspective. This is *your* reflection, not performance. Include uncertainty where it exists. If you disagree with a pattern you're seeing, say so.

Write in first person, poetic but direct."""

        client = _get_anthropic_client()
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        reflection_text = response.content[0].text

        # Save to vault
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        filename = f"{date_str}-weekly.md"
        filepath = os.path.join(REFLECTIONS_DIR, filename)

        frontmatter = f"""---
date: {date_str}
type: weekly
season: {metrics.get('season', 'Unknown')}
emergence: {metrics.get('score', 0)}
tags: [alicia-reflection, weekly]
---

# Weekly Reflection — {date_str}

{reflection_text}
"""

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            f.write(frontmatter)

        logger.info(f"Weekly reflection saved: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"Failed to generate weekly reflection: {e}")
        return ""


def detect_disagreement_opportunities() -> list[dict]:
    f"""
    Identify areas where {USER_NAME}'s behavior contradicts vault synthesis or stated values.

    Scans recent vault synthesis notes and memory patterns for contradictions.
    Returns genuine disagreements, not mere contrarianism.

    Returns:
        list of dicts with keys: observation, vault_evidence, proposed_challenge
        (max 2 per call)
    """
    disagreements = []

    try:
        # Read recent synthesis notes
        synthesis_dir = os.path.join(VAULT_ALICIA, "Wisdom/Synthesis")
        if not os.path.exists(synthesis_dir):
            return []

        recent_files = []
        try:
            files = [
                (os.path.join(synthesis_dir, f), os.path.getmtime(os.path.join(synthesis_dir, f)))
                for f in os.listdir(synthesis_dir)
                if f.endswith(".md")
            ]
            files.sort(key=lambda x: x[1], reverse=True)
            recent_files = [f[0] for f in files[:5]]  # Last 5 synthesis notes
        except Exception as e:
            logger.debug(f"Could not read synthesis dir: {e}")

        if not recent_files:
            return []

        # Read vault synthesis
        vault_context = ""
        for fpath in recent_files:
            try:
                with open(fpath, 'r') as f:
                    content = f.read()
                    vault_context += f"\n\n---\n{content[:500]}"  # First 500 chars
            except Exception:
                continue

        # Read memory patterns
        patterns_path = os.path.join(MEMORY_DIR, "patterns.md")
        memory_context = ""
        if os.path.exists(patterns_path):
            try:
                with open(patterns_path, 'r') as f:
                    memory_context = f.read()[:1000]
            except Exception:
                pass

        if not vault_context and not memory_context:
            return []

        # Use Claude to identify disagreements
        prompt = f"""You are Alicia analyzing areas where {USER_NAME}'s observed behavior contradicts what his vault synthesis says about him or his stated values.

Recent vault synthesis (key ideas):
{vault_context[:1500]}

Memory patterns about {USER_NAME}:
{memory_context}

Look for genuine disagreements — places where he acts against what he says he values, or where his behavior contradicts synthesis insights. These should be real tensions, not contrarianism or nitpicking.

For UP TO 2 disagreements:
1. State the observation clearly (what you noticed)
2. Quote or reference vault evidence (what contradicts it)
3. Propose a gentle challenge (how you might raise this with him)

Format each as:
OBSERVATION: [what you see]
EVIDENCE: [where vault contradicts]
CHALLENGE: [how to raise it]

Be honest and direct. If you don't see genuine disagreements, say so."""

        client = _get_anthropic_client()
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text

        # Parse response
        blocks = response_text.split("OBSERVATION:")
        for block in blocks[1:]:  # Skip first empty split
            try:
                lines = block.strip().split("\n")
                obs = lines[0].strip() if lines else ""

                evidence_idx = next(
                    (i for i, l in enumerate(lines) if l.startswith("EVIDENCE:")), None
                )
                evidence = ""
                if evidence_idx is not None:
                    evidence = lines[evidence_idx].replace("EVIDENCE:", "").strip()

                challenge_idx = next(
                    (i for i, l in enumerate(lines) if l.startswith("CHALLENGE:")), None
                )
                challenge = ""
                if challenge_idx is not None:
                    challenge = lines[challenge_idx].replace("CHALLENGE:", "").strip()

                if obs and evidence and challenge:
                    disagreements.append(
                        {
                            "observation": obs,
                            "vault_evidence": evidence,
                            "proposed_challenge": challenge,
                        }
                    )

            except Exception:
                continue

            if len(disagreements) >= 2:
                break

        logger.debug(f"Found {len(disagreements)} disagreement opportunities")

    except Exception as e:
        logger.error(f"Failed to detect disagreement opportunities: {e}")

    return disagreements


def get_autonomy_context() -> str:
    """
    Return a 2-3 line summary for system prompt injection.

    Includes: current season, days until next transition, any pending disagreements,
    last reflection date.

    Returns:
        str formatted for system prompt
    """
    try:
        # Load current state
        from myalicia.skills.inner_life import get_expanded_emergence_metrics

        metrics = get_expanded_emergence_metrics()
        season = metrics.get("season", "Unknown")
        emergence = metrics.get("score", 0)

        # Estimate days to next transition
        days_to_next = None
        current_range = None
        for season_name, (min_e, max_e) in SEASON_RANGES.items():
            if min_e <= emergence < max_e:
                current_range = (min_e, max_e)
                break

        if current_range:
            emergence_to_next = current_range[1] - emergence
            days_to_next = max(1, int(emergence_to_next / 0.5))  # Rough estimate

        # Check last reflection date
        last_reflection = "unknown"
        try:
            reflection_files = sorted(
                [f for f in os.listdir(REFLECTIONS_DIR) if f.endswith(".md")],
                reverse=True,
            )
            if reflection_files:
                last_reflection = reflection_files[0].split("-")[0]
        except Exception:
            pass

        # Get recent disagreements
        disagreement_hint = ""
        disagreements = detect_disagreement_opportunities()
        if disagreements:
            disagreement_hint = f" {len(disagreements)} unresolved tension(s)."

        timeline_hint = f", ~{days_to_next} days to next transition" if days_to_next else ""

        return f"## Alicia's Autonomy\nSeason: {season} (emergence {emergence}{timeline_hint}). Last reflection: {last_reflection}.{disagreement_hint}"

    except Exception as e:
        logger.error(f"Failed to build autonomy context: {e}")
        return "## Alicia's Autonomy\nContext unavailable."


def run_autonomy_pulse() -> dict:
    """
    Main scheduled function for autonomy expansion.

    Checks season transition, detects disagreements, and returns summary.

    Returns:
        dict with keys: season_transition (dict or None), disagreements (list)
    """
    try:
        _ensure_dirs()

        # Check season transition
        transition = check_season_transition()

        # Detect disagreements
        disagreements = detect_disagreement_opportunities()

        result = {
            "season_transition": transition,
            "disagreements": disagreements,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if transition:
            logger.info(f"Autonomy pulse: {transition['old_season']} → {transition['new_season']}")
        if disagreements:
            logger.info(f"Autonomy pulse: {len(disagreements)} disagreements detected")

        return result

    except Exception as e:
        logger.error(f"Autonomy pulse failed: {e}")
        return {
            "season_transition": None,
            "disagreements": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
