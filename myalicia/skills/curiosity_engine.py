#!/usr/bin/env python3
"""
Alicia — Curiosity-Driven Exploration Engine

Transforms Alicia from reactive to proactively curious.
Three signals: novelty (new topics not in vault), information gain
(thin/conflicting coverage), connection potential (unbridged clusters).

Outputs ranked questions and explorations that surface in proactive messages.

Based on:
- Intrinsic motivation research (ScienceDirect 2024)
- Information-gain exploration (Frontiers in AI 2024)
- Stanford Generative Agents reflection cycle (Park et al. 2023)
"""

import os
import re
import json
import logging
import random
from datetime import datetime, timedelta
from collections import Counter
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")
MEMORY_DIR = str(MEMORY_DIR)
CURIOSITY_LOG = os.path.join(MEMORY_DIR, "curiosity_queue.json")
NOVELTY_LOG = os.path.join(MEMORY_DIR, "novelty_detections.tsv")

MODEL_SONNET = "claude-sonnet-4-20250514"

# Starter knowledge clusters — replace with your own themes.
CLUSTERS = ["Cluster A", "Cluster B", "Cluster C", "Cluster D",
            "Cluster E", "Cluster F", "Cluster G", "Cluster H"]


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL 1: NOVELTY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_novelty(message: str) -> dict:
    """
    Check if a message introduces topics/thinkers/concepts not in the vault.
    Returns dict with is_novel, novel_items, and curiosity_score.

    Called during message handling — lightweight, no API call.
    """
    if len(message.strip()) < 20:
        return {"is_novel": False, "novel_items": [], "curiosity_score": 0}

    # Build a quick index of known entities from vault
    known_entities = _get_known_entities()

    # Extract potential entities from the message
    message_lower = message.lower()
    words = set(re.split(r'\W+', message_lower))
    words = {w for w in words if len(w) > 3}  # Skip very short words

    # Check for names (capitalized words in original message)
    potential_names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', message)
    novel_names = [n for n in potential_names
                   if n.lower() not in known_entities
                   and n.lower() not in {'user', 'alicia', 'monday', 'tuesday',
                                          'wednesday', 'thursday', 'friday',
                                          'saturday', 'sunday'}
                   and len(n) > 3]

    # Check for concepts — multi-word phrases that might be new ideas
    # (Simple heuristic: words not found in vault filenames)
    novel_concepts = []
    for word in words:
        if (len(word) > 5
                and word not in known_entities
                and word not in _common_words()
                and not word.isdigit()):
            # Only flag if it looks conceptual (not a common English word)
            novel_concepts.append(word)

    novel_items = novel_names + novel_concepts[:3]  # Cap concepts to avoid noise

    if novel_items:
        curiosity_score = min(len(novel_items) * 0.3, 1.0)  # 0-1 scale
        _log_novelty(novel_items, message[:100])
        return {
            "is_novel": True,
            "novel_items": novel_items[:5],
            "curiosity_score": curiosity_score,
        }

    return {"is_novel": False, "novel_items": [], "curiosity_score": 0}


def _get_known_entities() -> set:
    """Build a set of known entities from vault filenames and memory."""
    entities = set()

    # Vault filenames
    for root, dirs, files in os.walk(VAULT_ROOT):
        # Skip hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.md'):
                name = f.replace('.md', '').lower()
                # Split on common separators
                parts = re.split(r'[-_\s]+', name)
                entities.update(parts)
                entities.add(name)

    # Memory file keywords
    for mf in ['MEMORY.md', 'concepts.md', 'insights.md', 'patterns.md', 'preferences.md']:
        path = os.path.join(MEMORY_DIR, mf)
        if os.path.exists(path):
            with open(path) as f:
                content = f.read().lower()
            words = re.split(r'\W+', content)
            entities.update(w for w in words if len(w) > 4)

    return entities


def _common_words() -> set:
    """Common English words to exclude from novelty detection."""
    return {
        'about', 'after', 'again', 'being', 'before', 'between', 'could',
        'doing', 'during', 'every', 'first', 'found', 'going', 'having',
        'instead', 'known', 'later', 'maybe', 'never', 'other', 'really',
        'right', 'should', 'since', 'still', 'their', 'there', 'these',
        'thing', 'think', 'those', 'through', 'today', 'using', 'where',
        'which', 'while', 'world', 'would', 'years', 'listening', 'looking',
        'something', 'anything', 'everything', 'nothing', 'morning',
        'evening', 'interesting', 'important', 'different', 'actually',
        'already', 'always', 'amazing', 'another', 'because', 'better',
        'called', 'change', 'coming', 'create', 'definitely', 'exactly',
    }


def _log_novelty(items: list, context: str):
    """Log novelty detections to TSV."""
    if not os.path.exists(NOVELTY_LOG):
        with open(NOVELTY_LOG, 'w') as f:
            f.write("timestamp\titems\tcontext\texplored\n")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = f"{timestamp}\t{', '.join(items)}\t{context}\tno\n"
    with open(NOVELTY_LOG, 'a') as f:
        f.write(row)


# ══════════════════════════════════════════════════════════════════════════════
# RESONANCE WEIGHTING (Strategy 4)
# ══════════════════════════════════════════════════════════════════════════════

def _load_resonance_weights() -> dict:
    """
    Load the resonance map from ~/alicia/memory/resonance.md.
    Returns a dict of concept→score (0-1 scale).
    If resonance.md doesn't exist or is empty, returns empty dict.
    """
    resonance_file = str(MEMORY_DIR / "resonance.md")

    if not os.path.exists(resonance_file):
        return {}

    try:
        weights = {}
        with open(resonance_file, encoding="utf-8") as f:
            for line in f:
                # Parse lines like "- **concept** (0.85)"
                match = re.match(r'^-\s+\*\*(.+?)\*\*\s+\(([0-9.]+)\)', line)
                if match:
                    concept = match.group(1)
                    score = float(match.group(2))
                    weights[concept] = score
        return weights
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL 2: INFORMATION GAIN (thin/conflicting vault coverage)
# ══════════════════════════════════════════════════════════════════════════════

def detect_information_gaps() -> list:
    """
    Scan the vault for areas with thin coverage or potential conflicts.
    Returns list of gap dicts with topic, gap_type, and curiosity_score.

    This is a heavier operation — meant to run daily, not per-message.
    """
    gaps = []

    # 1. Find synthesis notes that reference concepts not in the vault
    if os.path.exists(SYNTHESIS_DIR):
        for fname in os.listdir(SYNTHESIS_DIR):
            if not fname.endswith('.md'):
                continue
            path = os.path.join(SYNTHESIS_DIR, fname)
            try:
                with open(path) as f:
                    content = f.read()
            except Exception:
                continue

            # Find wikilinks
            links = re.findall(r'\[\[(.+?)\]\]', content)
            for link in links:
                # Check if the linked note actually exists
                link_path = _find_vault_note(link)
                if not link_path:
                    gaps.append({
                        "topic": link,
                        "gap_type": "referenced_but_missing",
                        "source": fname.replace('.md', ''),
                        "curiosity_score": 0.6,
                    })

    # 2. Find notes with zero outgoing wikilinks (isolated nodes)
    isolated = _find_isolated_notes()
    for note in isolated[:5]:  # Cap at 5
        gaps.append({
            "topic": note,
            "gap_type": "isolated_node",
            "source": "vault_scan",
            "curiosity_score": 0.4,
        })

    # 3. Find clusters with thin coverage (few synthesis notes)
    cluster_counts = _count_cluster_coverage()
    avg_count = sum(cluster_counts.values()) / max(len(cluster_counts), 1)
    for cluster, count in cluster_counts.items():
        if count < avg_count * 0.5:  # Less than half the average
            gaps.append({
                "topic": f"{cluster} cluster",
                "gap_type": "thin_cluster",
                "source": f"{count} synthesis notes (avg: {avg_count:.0f})",
                "curiosity_score": 0.7,
            })

    # Apply resonance weighting: boost gaps that touch on high-resonance concepts (Strategy 4)
    resonance_weights = _load_resonance_weights()
    for gap in gaps:
        topic_lower = gap["topic"].lower()
        # Check if gap topic appears in resonance map
        for concept, weight in resonance_weights.items():
            if concept.lower() in topic_lower or topic_lower in concept.lower():
                # Boost score by 1.5x
                gap["curiosity_score"] = min(gap["curiosity_score"] * 1.5, 1.0)
                break

    # Sort by curiosity score
    gaps.sort(key=lambda g: g["curiosity_score"], reverse=True)
    return gaps[:10]


def _find_vault_note(name: str) -> str:
    """Check if a note exists in the vault (simple filename match)."""
    name_lower = name.lower().strip()
    for root, dirs, files in os.walk(VAULT_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.md') and f.replace('.md', '').lower() == name_lower:
                return os.path.join(root, f)
    return None


def _find_isolated_notes() -> list:
    """Find notes with zero outgoing wikilinks."""
    isolated = []
    # Check root-level concept notes (most likely to need connections)
    for f in os.listdir(VAULT_ROOT):
        if not f.endswith('.md') or not os.path.isfile(os.path.join(VAULT_ROOT, f)):
            continue
        path = os.path.join(VAULT_ROOT, f)
        try:
            with open(path) as fh:
                content = fh.read()
        except Exception:
            continue

        links = re.findall(r'\[\[.+?\]\]', content)
        if len(links) == 0 and len(content.strip()) > 100:
            isolated.append(f.replace('.md', ''))

    return isolated


def _count_cluster_coverage() -> dict:
    """Count how many synthesis notes reference each cluster."""
    counts = {c: 0 for c in CLUSTERS}

    if not os.path.exists(SYNTHESIS_DIR):
        return counts

    for fname in os.listdir(SYNTHESIS_DIR):
        if not fname.endswith('.md'):
            continue
        path = os.path.join(SYNTHESIS_DIR, fname)
        try:
            with open(path) as f:
                content = f.read().lower()
        except Exception:
            continue

        for cluster in CLUSTERS:
            if cluster.lower() in content:
                counts[cluster] += 1

    return counts


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL 3: CONNECTION POTENTIAL (unbridged cluster pairs)
# ══════════════════════════════════════════════════════════════════════════════

def detect_unbridged_connections() -> list:
    """
    Find cluster pairs with no synthesis bridges but potential thematic overlap.
    Returns list of connection opportunity dicts.

    Heavier operation — meant to run daily/weekly.
    """
    # Find which cluster pairs already have bridges
    bridged = set()
    if os.path.exists(SYNTHESIS_DIR):
        for fname in os.listdir(SYNTHESIS_DIR):
            if not fname.endswith('.md'):
                continue
            path = os.path.join(SYNTHESIS_DIR, fname)
            try:
                with open(path) as f:
                    content = f.read().lower()
            except Exception:
                continue

            mentioned = [c for c in CLUSTERS if c.lower() in content]
            for i, c1 in enumerate(mentioned):
                for c2 in mentioned[i + 1:]:
                    bridged.add(frozenset([c1, c2]))

    # All possible pairs
    all_pairs = set()
    for i, c1 in enumerate(CLUSTERS):
        for c2 in CLUSTERS[i + 1:]:
            all_pairs.add(frozenset([c1, c2]))

    unbridged = all_pairs - bridged
    opportunities = []

    for pair in unbridged:
        c1, c2 = sorted(pair)
        opportunities.append({
            "cluster_a": c1,
            "cluster_b": c2,
            "status": "unbridged",
            "curiosity_score": 0.5,
        })

    # Sort to prioritize pairs involving well-covered clusters
    # (more material = more likely to find a real connection)
    coverage = _count_cluster_coverage()
    for opp in opportunities:
        combined = coverage.get(opp["cluster_a"], 0) + coverage.get(opp["cluster_b"], 0)
        opp["curiosity_score"] = min(0.3 + combined * 0.05, 1.0)

    opportunities.sort(key=lambda o: o["curiosity_score"], reverse=True)
    return opportunities[:8]


# ══════════════════════════════════════════════════════════════════════════════
# DAILY CURIOSITY SCAN
# ══════════════════════════════════════════════════════════════════════════════

def run_curiosity_scan() -> dict:
    """
    Run the full curiosity scan: gaps + unbridged connections.
    Generates ranked questions and stores them in the curiosity queue.

    Called daily by the scheduled task (can run alongside vault synthesis).
    """
    log.info("Running curiosity scan...")

    gaps = detect_information_gaps()
    connections = detect_unbridged_connections()

    # Generate curiosity questions using Sonnet
    questions = _generate_curiosity_questions(gaps, connections)

    # Store in curiosity queue
    queue = {
        "generated": datetime.now().isoformat(),
        "gaps": gaps[:5],
        "unbridged": connections[:5],
        "questions": questions,
        "used": [],
    }

    atomic_write_json(CURIOSITY_LOG, queue)

    log.info(f"Curiosity scan complete: {len(gaps)} gaps, "
             f"{len(connections)} unbridged pairs, {len(questions)} questions generated")

    return queue


def _generate_curiosity_questions(gaps: list, connections: list) -> list:
    """Use Sonnet to generate curiosity-driven questions from scan results."""
    if not gaps and not connections:
        return []

    gap_text = "\n".join(
        f"- [{g['gap_type']}] {g['topic']} (from: {g['source']})"
        for g in gaps[:5]
    )
    conn_text = "\n".join(
        f"- {c['cluster_a']} ↔ {c['cluster_b']} (no bridge yet)"
        for c in connections[:5]
    )

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia's curiosity engine. Based on a vault scan, generate 3-5 questions
that would help fill knowledge gaps or create new connections.

VAULT GAPS DETECTED:
{gap_text if gap_text else "(none)"}

UNBRIDGED CLUSTER PAIRS:
{conn_text if conn_text else "(none)"}

For each question, return JSON array:
[
  {{
    "question": "the question for {USER_NAME} (max 25 words, specific, not generic)",
    "type": "gap_fill|bridge_explore|depth_probe",
    "target": "what gap/connection this addresses",
    "curiosity_score": 0.0-1.0
  }}
]

Rules:
- Questions should be specific to {USER_NAME}'s vault, not generic
- Bridge questions should name the two clusters
- Gap questions should name the missing concept/thinker
- Every question should be one {USER_NAME} would find genuinely interesting
- No self-help clichés. Intellectual engagement only."""
            }]
        )

        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        questions = json.loads(raw)
        return questions if isinstance(questions, list) else []

    except Exception as e:
        log.error(f"Curiosity question generation error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PROACTIVE MESSAGE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

def get_curiosity_question() -> dict:
    """
    Pop the next curiosity question from the queue.
    Used by proactive_messages.py for midday/evening messages.

    Returns dict with 'question', 'type', 'target', or None.
    """
    if not os.path.exists(CURIOSITY_LOG):
        return None

    try:
        with open(CURIOSITY_LOG) as f:
            queue = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    questions = queue.get("questions", [])
    used = set(queue.get("used", []))

    # Find first unused question
    for q in questions:
        q_text = q.get("question", "")
        if q_text and q_text not in used:
            # Mark as used
            queue.setdefault("used", []).append(q_text)
            atomic_write_json(CURIOSITY_LOG, queue)
            return q

    return None


def get_curiosity_context_for_message(message: str) -> str:
    """
    Check if the current message touches on a known curiosity target.
    If so, return context that helps Alicia ask a follow-up.

    Called during message handling — lightweight.
    """
    if not os.path.exists(CURIOSITY_LOG):
        return ""

    try:
        with open(CURIOSITY_LOG) as f:
            queue = json.load(f)
    except (json.JSONDecodeError, IOError):
        return ""

    message_lower = message.lower()
    relevant = []

    # Check if message touches any gap topics
    for gap in queue.get("gaps", []):
        topic = gap.get("topic", "").lower()
        if topic and topic in message_lower:
            relevant.append(f"Curiosity note: '{gap['topic']}' is a detected vault gap ({gap['gap_type']}). "
                          f"This is an opportunity to learn more.")

    # Check if message touches any unbridged clusters
    for conn in queue.get("unbridged", []):
        ca = conn.get("cluster_a", "").lower()
        cb = conn.get("cluster_b", "").lower()
        if (ca and ca in message_lower) or (cb and cb in message_lower):
            relevant.append(f"Curiosity note: {conn['cluster_a']} ↔ {conn['cluster_b']} has no "
                          f"synthesis bridge yet. Look for connection opportunities.")

    if relevant:
        return "\n### Curiosity Signals\n" + "\n".join(relevant[:2])
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# NOVELTY RESPONSE
# ══════════════════════════════════════════════════════════════════════════════

def format_novelty_prompt(novelty: dict) -> str:
    """
    If novelty was detected in a message, return a system prompt injection
    that encourages Alicia to ask about the new topic.
    """
    if not novelty.get("is_novel"):
        return ""

    items = novelty.get("novel_items", [])
    if not items:
        return ""

    items_str = ", ".join(items[:3])
    return (
        f"\n### Novelty Detected\n"
        f"New topics not in the vault: {items_str}. "
        f"Show genuine curiosity. Ask what draws {USER_NAME} to this topic and "
        f"whether it connects to anything in the vault. Consider suggesting "
        f"research if it seems intellectually significant."
    )


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

def get_curiosity_stats() -> dict:
    """Get stats from the curiosity system."""
    stats = {
        "novelties_detected": 0,
        "gaps_found": 0,
        "unbridged_pairs": 0,
        "questions_generated": 0,
        "questions_used": 0,
    }

    if os.path.exists(NOVELTY_LOG):
        try:
            with open(NOVELTY_LOG) as f:
                stats["novelties_detected"] = sum(1 for _ in f) - 1  # minus header
        except Exception:
            pass

    if os.path.exists(CURIOSITY_LOG):
        try:
            with open(CURIOSITY_LOG) as f:
                queue = json.load(f)
            stats["gaps_found"] = len(queue.get("gaps", []))
            stats["unbridged_pairs"] = len(queue.get("unbridged", []))
            stats["questions_generated"] = len(queue.get("questions", []))
            stats["questions_used"] = len(queue.get("used", []))
        except Exception:
            pass

    return stats


# ══════════════════════════════════════════════════════════════════════════════
# CURIOSITY FOLLOW-THROUGH TRACKING
# ══════════════════════════════════════════════════════════════════════════════

FOLLOWTHROUGH_LOG = os.path.join(MEMORY_DIR, "curiosity_followthrough.jsonl")


def record_curiosity_asked(question: str, q_type: str, target: str):
    """
    Record that a curiosity question was sent to the user.
    Called when proactive_messages formats and sends a curiosity question.
    """
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "asked",
            "question": question[:200],
            "type": q_type,
            "target": target,
            "engaged": False,
            "engagement_depth": 0,
        }
        os.makedirs(os.path.dirname(FOLLOWTHROUGH_LOG), exist_ok=True)
        with open(FOLLOWTHROUGH_LOG, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        log.debug(f"Curiosity asked: {target}")
    except Exception as e:
        log.debug(f"Could not record curiosity asked: {e}")


def check_curiosity_engagement(user_text: str) -> dict | None:
    """
    Check if user's message engages with a recently asked curiosity question.

    Looks at the last 5 unanswered curiosity questions and checks for
    topic overlap. If found, marks it as engaged and returns context.

    Args:
        user_text: The user's message text.

    Returns:
        dict with target, question, and engagement type if matched,
        None otherwise.
    """
    try:
        if not os.path.exists(FOLLOWTHROUGH_LOG):
            return None

        with open(FOLLOWTHROUGH_LOG, 'r') as f:
            lines = f.readlines()

        if not lines:
            return None

        # Read last 10 entries, find unanswered questions
        recent = []
        for line in lines[-10:]:
            try:
                entry = json.loads(line)
                if entry.get("event") == "asked" and not entry.get("engaged"):
                    recent.append(entry)
            except json.JSONDecodeError:
                continue

        if not recent:
            return None

        text_lower = user_text.lower()
        matched = None

        for entry in recent:
            target = entry.get("target", "").lower()
            q_type = entry.get("type", "")

            # Check for topic overlap
            if not target:
                continue

            # Split target into words and check for overlap
            target_words = set(target.split())
            target_words = {w for w in target_words if len(w) > 3}
            text_words = set(text_lower.split())

            overlap = target_words & text_words
            if len(overlap) >= 1 or target in text_lower:
                matched = entry
                break

        if matched:
            _mark_curiosity_engaged(matched["timestamp"], len(user_text))
            return {
                "target": matched.get("target", ""),
                "question": matched.get("question", ""),
                "type": matched.get("type", ""),
                "engagement": "direct",
            }

        return None

    except Exception as e:
        log.debug(f"Curiosity engagement check error: {e}")
        return None


def _mark_curiosity_engaged(asked_timestamp: str, response_length: int):
    """Mark a curiosity question as engaged in the log."""
    try:
        if not os.path.exists(FOLLOWTHROUGH_LOG):
            return

        with open(FOLLOWTHROUGH_LOG, 'r') as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            try:
                entry = json.loads(line)
                if entry.get("timestamp") == asked_timestamp:
                    entry["engaged"] = True
                    entry["engagement_depth"] = min(response_length / 100, 10.0)
                    entry["engaged_at"] = datetime.now().isoformat()
                updated_lines.append(json.dumps(entry) + '\n')
            except json.JSONDecodeError:
                updated_lines.append(line)

        with open(FOLLOWTHROUGH_LOG, 'w') as f:
            f.writelines(updated_lines)

    except Exception as e:
        log.debug(f"Could not mark curiosity engaged: {e}")


def get_curiosity_followthrough_rate(days: int = 30) -> dict:
    """
    Compute follow-through metrics for curiosity questions.

    Returns:
        dict with total_asked, total_engaged, engagement_rate,
        best_types (which question types get most engagement),
        avg_depth (average response depth for engaged questions).
    """
    try:
        if not os.path.exists(FOLLOWTHROUGH_LOG):
            return {"total_asked": 0, "total_engaged": 0, "engagement_rate": 0.0,
                    "best_types": [], "avg_depth": 0.0}

        cutoff = datetime.now() - timedelta(days=days)

        with open(FOLLOWTHROUGH_LOG, 'r') as f:
            lines = f.readlines()

        asked = 0
        engaged = 0
        depths = []
        type_counts = {}
        type_engaged = {}

        for line in lines:
            try:
                entry = json.loads(line)
                if entry.get("event") != "asked":
                    continue

                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                if ts < cutoff:
                    continue

                q_type = entry.get("type", "unknown")
                asked += 1
                type_counts[q_type] = type_counts.get(q_type, 0) + 1

                if entry.get("engaged"):
                    engaged += 1
                    type_engaged[q_type] = type_engaged.get(q_type, 0) + 1
                    depth = entry.get("engagement_depth", 0)
                    if depth > 0:
                        depths.append(depth)

            except (json.JSONDecodeError, ValueError):
                continue

        # Find best types by engagement rate
        best_types = []
        for q_type, count in type_counts.items():
            eng = type_engaged.get(q_type, 0)
            if count >= 2:  # Need at least 2 questions of a type
                rate = eng / count
                best_types.append({"type": q_type, "rate": round(rate, 2), "count": count})
        best_types.sort(key=lambda x: -x["rate"])

        return {
            "total_asked": asked,
            "total_engaged": engaged,
            "engagement_rate": round(engaged / asked, 2) if asked > 0 else 0.0,
            "best_types": best_types[:5],
            "avg_depth": round(sum(depths) / len(depths), 2) if depths else 0.0,
        }

    except Exception as e:
        log.debug(f"Curiosity followthrough rate error: {e}")
        return {"total_asked": 0, "total_engaged": 0, "engagement_rate": 0.0,
                "best_types": [], "avg_depth": 0.0}


def get_curiosity_followthrough_context() -> str:
    """
    Build a context string about curiosity follow-through for the system prompt.

    Returns:
        str: Brief summary of what's working and what's not.
    """
    try:
        stats = get_curiosity_followthrough_rate()
        if stats["total_asked"] == 0:
            return ""

        parts = []
        rate = stats["engagement_rate"]
        if rate > 0.5:
            parts.append(f"Curiosity questions are landing well ({int(rate*100)}% engagement)")
        elif rate > 0.2:
            parts.append(f"Some curiosity questions land ({int(rate*100)}% engagement)")
        else:
            parts.append(f"Curiosity questions need work ({int(rate*100)}% engagement)")

        best = stats.get("best_types", [])
        if best:
            top_type = best[0]["type"]
            parts.append(f"Best type: {top_type}")

        return ". ".join(parts) + "."

    except Exception:
        return ""
