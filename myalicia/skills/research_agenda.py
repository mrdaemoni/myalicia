"""
Alicia's Autonomous Research Agenda

Self-directed vault exploration — Alicia identifies her own research
questions, explores gaps she finds interesting, and builds her own
understanding independent of the user's direct requests.

This is Goal #7: "Build own research agenda — self-directed vault
exploration based on gaps she detects, not just responding to the user."

The agenda is informed by:
- Curiosity engine gaps (thin coverage, missing nodes)
- Graph intelligence (unbridged clusters, weak connections)
- Novelty detections (new topics the user mentioned but vault doesn't cover)
- Emergence metrics (what's growing, what's stagnant)
- Muse discoveries (cross-cluster bridges that want deepening)
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

logger = logging.getLogger("alicia")

MEMORY_DIR = str(MEMORY_DIR)
VAULT_ROOT = str(config.vault.root)
AGENDA_PATH = os.path.join(MEMORY_DIR, "research_agenda.json")
RESEARCH_LOG = os.path.join(MEMORY_DIR, "research_log.jsonl")
MYSELF_DIR = os.path.join(VAULT_ROOT, "Alicia", "Myself")
RESEARCH_NOTES_DIR = os.path.join(MYSELF_DIR, "research-notes")

# Max active research threads at once
MAX_ACTIVE_THREADS = 5

# Minimum days before re-evaluating a research thread
MIN_THREAD_AGE_DAYS = 3

# Research thread states
STATES = ("active", "paused", "completed", "abandoned")


def ensure_research_dirs():
    """Create research note directories if needed."""
    os.makedirs(RESEARCH_NOTES_DIR, exist_ok=True)
    os.makedirs(MEMORY_DIR, exist_ok=True)


def generate_research_questions() -> list:
    """
    Generate new research questions from multiple signals.

    Synthesizes:
    - Curiosity engine gaps
    - Graph intelligence predictions
    - Novelty detections
    - Emergence state

    Returns:
        list of dicts: [{question, source, priority, topic, rationale}, ...]
    """
    questions = []

    # Signal 1: Curiosity engine gaps
    try:
        curiosity_path = os.path.join(MEMORY_DIR, "curiosity_queue.json")
        if os.path.exists(curiosity_path):
            with open(curiosity_path, 'r') as f:
                queue = json.load(f)

            for gap in queue.get("gaps", []):
                topic = gap.get("topic", "")
                gap_type = gap.get("gap_type", "")
                score = gap.get("curiosity_score", 0)
                if topic and score > 0.3:
                    questions.append({
                        "question": f"What would the vault gain from deeper exploration of {topic}?",
                        "source": "curiosity_gap",
                        "priority": score,
                        "topic": topic,
                        "rationale": f"Vault gap ({gap_type}): {topic} is referenced but underdeveloped.",
                    })

            for conn in queue.get("unbridged", []):
                ca = conn.get("cluster_a", "")
                cb = conn.get("cluster_b", "")
                score = conn.get("curiosity_score", 0)
                if ca and cb and score > 0.3:
                    questions.append({
                        "question": f"What connects {ca} and {cb} that we haven't articulated yet?",
                        "source": "unbridged_cluster",
                        "priority": score,
                        "topic": f"{ca} ↔ {cb}",
                        "rationale": f"These clusters have no synthesis bridge yet.",
                    })
    except Exception as e:
        logger.debug(f"Curiosity gaps read error: {e}")

    # Signal 2: Novelty detections (topics the user mentioned but vault doesn't cover)
    try:
        novelty_path = os.path.join(MEMORY_DIR, "novelty_detections.tsv")
        if os.path.exists(novelty_path):
            with open(novelty_path, 'r') as f:
                lines = f.readlines()

            # Look at recent unexplored novelties
            for line in lines[-10:]:
                parts = line.strip().split('\t')
                if len(parts) >= 4 and parts[3] == "no":
                    items = parts[1]
                    context = parts[2]
                    questions.append({
                        "question": f"Should the vault have a perspective on {items}?",
                        "source": "novelty_detection",
                        "priority": 0.5,
                        "topic": items,
                        "rationale": f"{USER_NAME} mentioned {items} but the vault has no coverage. Context: {context}",
                    })
    except Exception as e:
        logger.debug(f"Novelty read error: {e}")

    # Signal 3: Graph intelligence — predicted links suggest latent connections
    try:
        link_path = os.path.join(MEMORY_DIR, "link_suggestions.json")
        if os.path.exists(link_path):
            with open(link_path, 'r') as f:
                suggestions = json.load(f)

            for sugg in suggestions.get("predictions", suggestions if isinstance(suggestions, list) else [])[:5]:
                source = sugg.get("source", "")
                target = sugg.get("target", "")
                similarity = sugg.get("similarity", 0)
                if source and target and similarity > 0.35:
                    questions.append({
                        "question": f"What is the deeper connection between {source} and {target}?",
                        "source": "graph_prediction",
                        "priority": similarity,
                        "topic": f"{source} → {target}",
                        "rationale": f"Semantically similar ({similarity:.0%}) but no vault link exists.",
                    })
    except Exception as e:
        logger.debug(f"Graph predictions read error: {e}")

    # Signal 4: Emergence state — areas where Alicia's own growth is thin
    try:
        emergence_path = os.path.join(MEMORY_DIR, "emergence_state.json")
        if os.path.exists(emergence_path):
            with open(emergence_path, 'r') as f:
                state = json.load(f)
            metrics = state.get("metrics", {})

            # If certain metrics are low, generate research around them
            if metrics.get("edges_seen", 0) < 5:
                questions.append({
                    "question": f"What growth edges am I not seeing? Where is {USER_NAME} avoiding?",
                    "source": "emergence_self",
                    "priority": 0.6,
                    "topic": "growth edges",
                    "rationale": f"Few depth signals detected — either {USER_NAME} is avoiding edges or I'm not detecting them.",
                })
            if metrics.get("connections_woven", 0) < 10:
                questions.append({
                    "question": "Which vault clusters have the richest unexplored connection potential?",
                    "source": "emergence_self",
                    "priority": 0.5,
                    "topic": "synthesis gaps",
                    "rationale": "Synthesis output is low — need to find more generative intersection points.",
                })
    except Exception as e:
        logger.debug(f"Emergence read error: {e}")

    # Sort by priority
    questions.sort(key=lambda q: -q["priority"])
    return questions[:15]


def build_research_agenda() -> dict:
    """
    Build or update the research agenda from all signals.

    Preserves active threads and adds new ones up to MAX_ACTIVE_THREADS.

    Returns:
        dict: The updated agenda with active_threads, completed, and metadata.
    """
    ensure_research_dirs()

    # Load existing agenda
    agenda = _load_agenda()

    # Clean up — move stale threads
    active = agenda.get("active_threads", [])
    completed = agenda.get("completed", [])

    # Check for threads that should be paused (no progress in 7+ days)
    now = datetime.now(timezone.utc)
    still_active = []
    for thread in active:
        last_touched = thread.get("last_touched", thread.get("created", ""))
        try:
            lt = datetime.fromisoformat(last_touched)
            age = (now - lt).days
            if age > 14:
                thread["state"] = "paused"
                thread["pause_reason"] = "No progress in 14+ days"
                completed.append(thread)
                continue
        except (ValueError, TypeError):
            pass
        still_active.append(thread)

    # Generate new questions
    new_questions = generate_research_questions()

    # Don't duplicate existing threads
    existing_topics = {t.get("topic", "").lower() for t in still_active}
    existing_topics |= {t.get("topic", "").lower() for t in completed}

    # Add new threads up to max
    for q in new_questions:
        if len(still_active) >= MAX_ACTIVE_THREADS:
            break
        if q["topic"].lower() in existing_topics:
            continue

        thread = {
            "id": f"rt-{now.strftime('%Y%m%d')}-{len(still_active)+1}",
            "question": q["question"],
            "source": q["source"],
            "priority": q["priority"],
            "topic": q["topic"],
            "rationale": q["rationale"],
            "state": "active",
            "created": now.isoformat(),
            "last_touched": now.isoformat(),
            "findings": [],
            "notes_created": [],
        }
        still_active.append(thread)
        existing_topics.add(q["topic"].lower())

    agenda = {
        "updated": now.isoformat(),
        "active_threads": still_active,
        "completed": completed[-20:],  # Keep last 20 completed
        "stats": {
            "total_active": len(still_active),
            "total_completed": len(completed),
            "sources": _count_sources(still_active),
        },
    }

    _save_agenda(agenda)
    return agenda


def explore_research_thread(thread_id: str = None) -> dict | None:
    """
    Pick a research thread and do one step of exploration.

    Uses semantic search to find relevant vault notes, reads them,
    and generates a research finding.

    Args:
        thread_id: Specific thread to explore, or None for auto-pick.

    Returns:
        dict with thread info, finding, and any vault notes discovered.
    """
    agenda = _load_agenda()
    active = agenda.get("active_threads", [])

    if not active:
        return None

    # Pick thread — either specified or highest priority unrecently-touched
    thread = None
    if thread_id:
        for t in active:
            if t.get("id") == thread_id:
                thread = t
                break
    else:
        # Sort by: fewest findings first (explore fresh threads),
        # then by priority
        sorted_threads = sorted(active, key=lambda t: (len(t.get("findings", [])), -t.get("priority", 0)))
        thread = sorted_threads[0] if sorted_threads else None

    if not thread:
        return None

    # Search the vault for related content
    finding = None
    try:
        from myalicia.skills.semantic_search import semantic_search
        results = semantic_search(
            query=thread["question"],
            n_results=5,
        )

        if results:
            # Build a finding from what we discovered
            found_notes = []
            for r in results:
                title = r.get("title", "")
                snippet = r.get("snippet", "")[:200]
                score = r.get("score", 0)
                found_notes.append({
                    "title": title,
                    "snippet": snippet,
                    "relevance": round(score, 3),
                })

            finding = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notes_found": len(results),
                "top_notes": found_notes[:3],
                "exploration_type": "semantic_search",
            }

            thread["findings"].append(finding)
            thread["last_touched"] = datetime.now(timezone.utc).isoformat()

            _save_agenda(agenda)
            _log_research_step(thread, finding)

    except Exception as e:
        logger.debug(f"Research exploration error: {e}")

    return {
        "thread": thread,
        "finding": finding,
    }


def record_research_insight(thread_id: str, insight: str):
    """
    Record an insight discovered during research exploration.

    Args:
        thread_id: The research thread this insight belongs to.
        insight: The insight text.
    """
    try:
        agenda = _load_agenda()
        for thread in agenda.get("active_threads", []):
            if thread.get("id") == thread_id:
                thread.setdefault("findings", []).append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "insight",
                    "text": insight[:500],
                })
                thread["last_touched"] = datetime.now(timezone.utc).isoformat()
                break
        _save_agenda(agenda)
    except Exception as e:
        logger.debug(f"Could not record research insight: {e}")


def complete_research_thread(thread_id: str, summary: str = ""):
    """Mark a research thread as completed with optional summary."""
    try:
        agenda = _load_agenda()
        active = agenda.get("active_threads", [])
        completed = agenda.get("completed", [])

        for i, thread in enumerate(active):
            if thread.get("id") == thread_id:
                thread["state"] = "completed"
                thread["completed_at"] = datetime.now(timezone.utc).isoformat()
                thread["summary"] = summary
                completed.append(thread)
                active.pop(i)
                break

        agenda["active_threads"] = active
        agenda["completed"] = completed[-20:]
        _save_agenda(agenda)

    except Exception as e:
        logger.debug(f"Could not complete research thread: {e}")


def save_research_note(thread_id: str, title: str, content: str) -> str:
    """
    Save a research finding as a vault note in Alicia/Myself/research-notes/.

    Args:
        thread_id: Research thread this belongs to.
        title: Note title.
        content: Note content.

    Returns:
        str: Path to the created note.
    """
    ensure_research_dirs()

    slug = title.replace(" ", "-").replace("/", "-")[:50]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{date}-{slug}.md"
    filepath = os.path.join(RESEARCH_NOTES_DIR, filename)

    note = f"""---
tags:
  - research
  - alicia-autonomous
thread: {thread_id}
created: {date}
---

# {title}

{content}
"""

    try:
        with open(filepath, 'w') as f:
            f.write(note)

        # Record in agenda
        agenda = _load_agenda()
        for thread in agenda.get("active_threads", []):
            if thread.get("id") == thread_id:
                thread.setdefault("notes_created", []).append(filename)
                thread["last_touched"] = datetime.now(timezone.utc).isoformat()
                break
        _save_agenda(agenda)

        logger.info(f"Research note saved: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"Could not save research note: {e}")
        return ""


def run_research_session() -> dict:
    """
    Run one autonomous research session.

    Called by the scheduler. Steps:
    1. Build/update the agenda from all signals
    2. Pick the highest-priority thread
    3. Do one exploration step
    4. Generate a brief finding summary

    Returns:
        dict with agenda stats and any findings.
    """
    try:
        # Step 1: Refresh agenda
        agenda = build_research_agenda()

        active = agenda.get("active_threads", [])
        if not active:
            return {"status": "no_threads", "message": "No active research threads."}

        # Step 2-3: Explore one thread
        result = explore_research_thread()

        if not result or not result.get("finding"):
            return {
                "status": "explored_but_nothing_new",
                "active_threads": len(active),
            }

        thread = result["thread"]
        finding = result["finding"]

        return {
            "status": "finding",
            "thread_topic": thread.get("topic", ""),
            "thread_question": thread.get("question", ""),
            "notes_found": finding.get("notes_found", 0),
            "top_notes": finding.get("top_notes", []),
            "active_threads": len(active),
            "total_findings": len(thread.get("findings", [])),
        }

    except Exception as e:
        logger.error(f"Research session error: {e}")
        return {"status": "error", "message": str(e)}


def get_research_context() -> str:
    """
    Build a context string about active research for the system prompt.

    Returns:
        str: Brief summary of what Alicia is researching.
    """
    try:
        agenda = _load_agenda()
        active = agenda.get("active_threads", [])

        if not active:
            return ""

        parts = [f"I have {len(active)} active research thread(s):"]
        for thread in active[:3]:
            topic = thread.get("topic", "")
            findings = len(thread.get("findings", []))
            parts.append(f"- {topic} ({findings} findings so far)")

        return "\n".join(parts)

    except Exception:
        return ""


def get_agenda_summary() -> str:
    """One-line summary for health checks."""
    try:
        agenda = _load_agenda()
        active = len(agenda.get("active_threads", []))
        completed = len(agenda.get("completed", []))
        return f"Research: {active} active threads, {completed} completed"
    except Exception:
        return "Research: no agenda"


# ── Internal Helpers ───────────────────────────────────────────────────────

def _load_agenda() -> dict:
    try:
        if os.path.exists(AGENDA_PATH):
            with open(AGENDA_PATH, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"active_threads": [], "completed": [], "stats": {}}


def _save_agenda(agenda: dict):
    try:
        atomic_write_json(AGENDA_PATH, agenda)
    except Exception as e:
        logger.debug(f"Could not save agenda: {e}")


def _count_sources(threads: list) -> dict:
    counts = {}
    for t in threads:
        src = t.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1
    return counts


def _log_research_step(thread: dict, finding: dict):
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": thread.get("id", ""),
            "topic": thread.get("topic", ""),
            "finding_type": finding.get("exploration_type", ""),
            "notes_found": finding.get("notes_found", 0),
        }
        os.makedirs(os.path.dirname(RESEARCH_LOG), exist_ok=True)
        with open(RESEARCH_LOG, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass
