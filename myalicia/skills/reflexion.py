#!/usr/bin/env python3
"""
Alicia — Reflexion Layer

After significant tasks, Alicia reflects on what went well and what to improve.
Reflections are stored as episodic memory and retrieved for similar future tasks.

Based on: Shinn et al. "Reflexion: Language Agents with Verbal Reinforcement Learning" (2023)
Pattern: Act → Evaluate → Reflect (verbally) → Store → Retrieve for next similar task

No weight updates — all learning happens through linguistic feedback in context.
"""

import os
import json
import logging
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

load_dotenv(str(ENV_FILE))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

MEMORY_DIR = str(MEMORY_DIR)
EPISODES_DIR = os.path.join(MEMORY_DIR, "episodes")
PROCEDURES_FILE = os.path.join(MEMORY_DIR, "procedures.md")
REFLEXION_LOG = os.path.join(MEMORY_DIR, "reflexion_log.tsv")

os.makedirs(EPISODES_DIR, exist_ok=True)

# ── Task types that warrant reflection ────────────────────────────────────────

REFLECTABLE_TASKS = {
    "generate_pdf", "search_vault", "send_email", "generate_concept_note",
    "research", "synthesise_vault", "find_contradictions", "consolidate_memory",
    "remember",
    # <earlier development>: read_vault_note writes an episode too so that reactions on
    # the resulting voice notes (and the intro text) can score the same
    # episode via reply_index.jsonl. Without this, read-aloud replies were
    # invisible to Gap 1's reaction scorer.
    "read_vault_note",
}

# Minimum threshold — don't reflect on trivial operations
SKIP_TOOLS = {"get_vault_stats", "get_random_quote", "inbox_summary", "knowledge_dashboard"}

# ── Reflexion prompt ──────────────────────────────────────────────────────────

REFLEXION_SYSTEM = """You are Alicia's reflexion engine. After a task completes, you generate a brief, actionable self-critique.

You receive:
- task_type: which tool was called
- input_summary: what was requested
- output_summary: what was produced
- score: quality score (1-5) if available, or "n/a"
- relevant_procedures: any existing procedural memory for this task type

Generate a reflection with EXACTLY this JSON structure:
{
  "went_well": "1 sentence on what worked",
  "to_improve": "1 sentence on what could be better next time",
  "procedure_update": "1 sentence procedure to remember, or null if nothing new learned",
  "confidence": 1-5,
  "decision_attribution": [
    {"step": "short label", "attribution": "positive" | "negative" | "neutral", "reason": "1 phrase"}
  ],
  "responsibility_skill": "name of the skill primarily responsible, or null if no existing skill claims this"
}

Rules:
- Be specific and actionable — "use more diverse sources" not "do better"
- Reference the actual content — name specific thinkers, concepts, vault notes
- procedure_update should be a reusable instruction, not a one-off observation
- Only suggest procedure_update when you've genuinely learned something new
- confidence: how useful is this reflection? 5 = highly reusable, 1 = too specific to generalize
- decision_attribution is the TIMG (arxiv 2603.10600) per-step trace. List 1-4 key decisions in this task and label each "positive" (helped), "negative" (hurt outcome), or "neutral". This is what enables retrieval to surface the specific failure-causing decision next time, not the whole transcript. If the task type doesn't break down into discrete decisions, return an empty list.
- responsibility_skill names which existing Alicia skill (e.g. semantic_search, vault_intelligence, gmail_skill, research_skill) is most responsible for the outcome. Set to null ONLY when a task failed in a way no existing skill claims as its territory — that triggers the skill_author to draft a new skill stub."""


# ── Core functions ────────────────────────────────────────────────────────────

def should_reflect(tool_name: str) -> bool:
    """Determine if a task warrants reflection. Checks config for additional reflectable tasks."""
    reflectable = set(REFLECTABLE_TASKS)
    try:
        from myalicia.skills.skill_config import load_config, get_param
        config = load_config("reflexion")
        extra = get_param(config, "reflectable_tasks")
        if extra:
            for task in extra.split(","):
                task = task.strip()
                if task:
                    reflectable.add(task)
    except Exception:
        pass
    return tool_name in reflectable and tool_name not in SKIP_TOOLS


def _load_procedures() -> str:
    """Load existing procedural memory."""
    if os.path.exists(PROCEDURES_FILE):
        with open(PROCEDURES_FILE) as f:
            return f.read()
    return ""


def _get_procedures_for_task(task_type: str) -> str:
    """Get procedures relevant to a specific task type."""
    procedures = _load_procedures()
    if not procedures:
        return "(No procedures yet)"

    # Filter for relevant lines
    relevant = []
    for line in procedures.split('\n'):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith('#'):
            continue
        # Match if the task type or related keywords appear
        if task_type in line_stripped.lower() or any(kw in line_stripped.lower() for kw in _task_keywords(task_type)):
            relevant.append(line_stripped)

    return "\n".join(relevant[-5:]) if relevant else "(No procedures for this task type yet)"


def _task_keywords(task_type: str) -> list:
    """Keywords associated with a task type for procedure matching."""
    mapping = {
        "generate_pdf": ["pdf", "document", "export", "reportlab"],
        "search_vault": ["search", "semantic", "find", "vault"],
        "generate_concept_note": ["concept", "note", "wikilink", "obsidian"],
        "research": ["research", "deep dive", "topic", "sources"],
        "synthesise_vault": ["synthesis", "connection", "bridge", "cross-book"],
        "find_contradictions": ["contradiction", "tension", "conflict", "disagree"],
        "send_email": ["email", "send", "gmail", "message"],
        "consolidate_memory": ["memory", "consolidate", "clean", "merge"],
        "remember": ["remember", "memory", "store", "preference"],
    }
    return mapping.get(task_type, [task_type])


def reflect_on_task(task_type: str, input_summary: str, output_summary: str, score: str = "n/a") -> dict:
    """
    Generate a verbal self-critique after a task.
    Returns the reflection dict or None if reflection wasn't useful.
    """
    if not should_reflect(task_type):
        return None

    procedures = _get_procedures_for_task(task_type)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=REFLEXION_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"task_type: {task_type}\n"
                    f"input_summary: {input_summary[:300]}\n"
                    f"output_summary: {output_summary[:500]}\n"
                    f"score: {score}\n"
                    f"relevant_procedures: {procedures}"
                )
            }]
        )

        # Guard against empty or non-text responses
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            log.warning(f"Reflexion ({task_type}): API returned no text content")
            return None

        raw = response.content[0].text.strip()
        # Clean JSON fences
        import re
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        reflection = json.loads(raw)

        # Store the episode
        episode = {
            "timestamp": datetime.now().isoformat(),
            "task_type": task_type,
            "input": input_summary[:300],
            "output": output_summary[:300],
            "score": score,
            "reflection": reflection,
        }

        # TIMG step attribution — copy out so retrieval can surface it
        # at the top level without unpacking reflection.
        if "decision_attribution" in reflection:
            episode["decision_attribution"] = reflection.get("decision_attribution") or []

        # Responsibility-gap flag (Memento-Skills): when the reflection
        # admits no existing skill claims this failure, set a top-level
        # flag so skill_author can pick it up later. We only flag when
        # the task actually struggled (low score / low confidence) so
        # we don't manufacture stubs for routine successes.
        try:
            episode_score_num = float(score) if score not in ("n/a", "", None) else None
        except (ValueError, TypeError):
            episode_score_num = None
        responsibility_skill = reflection.get("responsibility_skill")
        struggled = (episode_score_num is not None and episode_score_num <= 2) or (
            reflection.get("confidence", 5) <= 2
        )
        if (responsibility_skill in (None, "null", "")) and struggled:
            episode["responsibility_gap"] = True

        episode_path = _store_episode(episode)

        # Memento-Skills: queue a stub draft when the gap is real. Lazy
        # import + best-effort: if skill_author is unavailable or errors,
        # we never block reflexion's main flow.
        if episode.get("responsibility_gap"):
            try:
                from myalicia.skills.skill_author import maybe_draft_stub
                maybe_draft_stub(episode, episode_path=episode_path)
            except Exception as gap_e:
                log.debug(f"skill_author skip: {gap_e}")

        # Update procedural memory if the reflection suggests it
        if reflection.get("procedure_update") and reflection.get("confidence", 0) >= 4:
            _update_procedures(task_type, reflection["procedure_update"])

        # Log to TSV
        _log_reflexion(task_type, reflection)

        log.info(f"Reflexion ({task_type}): {reflection.get('to_improve', '')[:80]}")
        return reflection

    except Exception as e:
        log.error(f"Reflexion error: {e}")
        return None


def _store_episode(episode: dict) -> str | None:
    """
    Store an episode as a JSON file in the episodes directory.
    Returns the full filepath (used by skill_author and meta_reflexion to
    refer back to the originating episode), or None on failure.
    """
    try:
        os.makedirs(EPISODES_DIR, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        time = datetime.now().strftime("%H%M%S")
        task = episode.get("task_type", "unknown")
        filename = f"{date}_{time}_{task}.json"
        filepath = os.path.join(EPISODES_DIR, filename)

        atomic_write_json(filepath, episode)
        return filepath
    except Exception as e:
        log.error(f"Failed to store episode: {e}")
        return None


def _update_procedures(task_type: str, procedure: str):
    """Add a new procedure to procedural memory."""
    try:
        if not os.path.exists(PROCEDURES_FILE):
            with open(PROCEDURES_FILE, 'w') as f:
                f.write("# Procedural Memory\n*Learned strategies — updated by the reflexion engine.*\n\n")

        date = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{task_type}] ({date}) {procedure}\n"

        with open(PROCEDURES_FILE, 'a') as f:
            f.write(entry)

        log.info(f"New procedure: [{task_type}] {procedure[:60]}")
    except Exception as e:
        log.error(f"Failed to update procedures: {e}")


def _init_reflexion_log():
    """Initialize the reflexion log TSV."""
    if not os.path.exists(REFLEXION_LOG):
        with open(REFLEXION_LOG, 'w') as f:
            f.write("timestamp\ttask_type\twent_well\tto_improve\tprocedure_update\tconfidence\n")


def _log_reflexion(task_type: str, reflection: dict):
    """Log a reflexion to the TSV."""
    try:
        _init_reflexion_log()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = (
            f"{timestamp}\t"
            f"{task_type}\t"
            f"{reflection.get('went_well', '')[:200]}\t"
            f"{reflection.get('to_improve', '')[:200]}\t"
            f"{reflection.get('procedure_update', 'none')[:200]}\t"
            f"{reflection.get('confidence', 0)}\n"
        )
        with open(REFLEXION_LOG, 'a') as f:
            f.write(row)
    except Exception as e:
        log.error(f"Failed to log reflexion: {e}")


# ── Retrieval: get past reflections for similar tasks ─────────────────────────

def get_relevant_reflections(task_type: str, context: str = "", max_reflections: int = 3) -> str:
    """
    Retrieve past reflections relevant to the current task.
    Returns a string to inject into the system prompt.
    """
    # Collect all episodes for this task type
    if not os.path.exists(EPISODES_DIR):
        return ""

    matching_episodes = []
    for filename in sorted(os.listdir(EPISODES_DIR), reverse=True):  # Most recent first
        if not filename.endswith('.json'):
            continue
        if task_type not in filename:
            continue

        filepath = os.path.join(EPISODES_DIR, filename)
        try:
            with open(filepath) as f:
                episode = json.load(f)
            reflection = episode.get("reflection", {})
            if reflection:
                matching_episodes.append(episode)
        except (json.JSONDecodeError, IOError):
            continue

        if len(matching_episodes) >= max_reflections * 2:  # Read more than needed for scoring
            break

    if not matching_episodes:
        return ""

    # Score by relevance (confidence + recency)
    scored = []
    for ep in matching_episodes:
        ref = ep.get("reflection", {})
        confidence = ref.get("confidence", 3)
        scored.append((confidence, ep))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_reflections]

    # Format for injection
    lines = ["### Past Reflections (from similar tasks)"]
    for _, ep in top:
        ref = ep.get("reflection", {})
        lines.append(f"- **{ep.get('task_type', '?')}** ({ep.get('timestamp', '?')[:10]}): "
                     f"Worked: {ref.get('went_well', '?')} | "
                     f"Improve: {ref.get('to_improve', '?')}")

    return "\n".join(lines)


def get_procedures_context() -> str:
    """
    Get procedural memory context for the system prompt.
    Returns a formatted string with the most recent procedures.
    """
    if not os.path.exists(PROCEDURES_FILE):
        return ""

    with open(PROCEDURES_FILE) as f:
        content = f.read()

    lines = [l.strip() for l in content.split('\n') if l.strip() and l.strip().startswith('- ')]

    if not lines:
        return ""

    # Return the most recent 10 procedures
    recent = lines[-10:]
    return "### Learned Procedures\n" + "\n".join(recent)


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_reflexion_stats() -> dict:
    """Get stats from the reflexion system."""
    episode_count = 0
    if os.path.exists(EPISODES_DIR):
        episode_count = len([f for f in os.listdir(EPISODES_DIR) if f.endswith('.json')])

    procedure_count = 0
    if os.path.exists(PROCEDURES_FILE):
        with open(PROCEDURES_FILE) as f:
            procedure_count = sum(1 for l in f if l.strip().startswith('- '))

    return {
        "episodes": episode_count,
        "procedures": procedure_count,
    }
