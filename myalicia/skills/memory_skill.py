#!/usr/bin/env python3
"""
Alicia — 3-Layer Memory System
Layer 1: Session memory (MEMORY.md + topic files)
Layer 2: Knowledge graph (Obsidian vault with wikilinks)
Layer 3: Ingestion pipeline (URLs, transcripts → structured notes)
"""

import os
import json
import re
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_text, locked_file
from myalicia.skills.bridge_protocol import write_bridge_text
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

# ── Paths ─────────────────────────────────────────────────────────────────────

MEMORY_DIR     = str(MEMORY_DIR)
ALICIA_MD      = str(ALICIA_HOME / "ALICIA.md")
VAULT          = str(config.vault.inner_path)
VAULT_ROOT     = str(config.vault.root)
QUOTES_FOLDER  = str(config.vault.root / "Quotes")

MEMORY_FILE    = os.path.join(MEMORY_DIR, "MEMORY.md")
PATTERNS_FILE  = os.path.join(MEMORY_DIR, "patterns.md")
INSIGHTS_FILE  = os.path.join(MEMORY_DIR, "insights.md")
PREFERENCES_FILE = os.path.join(MEMORY_DIR, "preferences.md")
CONCEPTS_FILE  = os.path.join(MEMORY_DIR, "concepts.md")
HOT_TOPICS_FILE = os.path.join(MEMORY_DIR, "hot_topics.md")

# ── Bridge (cross-interface continuity) ──────────────────────────────────────
BRIDGE_HANDOFF = os.path.join(VAULT_ROOT, "Alicia/Bridge/HANDOFF.md")

# ── Vault mirror (so the user can browse memory in Obsidian) ───────────────────
VAULT_MEMORY_DIR = os.path.join(VAULT, "Self", "Memory")

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)


# ── Setup ─────────────────────────────────────────────────────────────────────

def ensure_memory_structure():
    """Create all memory files and vault folders if they don't exist."""
    os.makedirs(MEMORY_DIR, exist_ok=True)

    defaults = {
        MEMORY_FILE: f"# MEMORY.md — Master Routing Document\n*Max 200 lines. Deep detail lives in topic files.*\n\n## About {USER_NAME}\n\n## Key Insights\n\n## Active Concepts\n\n## Important Patterns\n\n## Links\n- Patterns: [[patterns]]\n- Insights: [[insights]]\n- Preferences: [[preferences]]\n- Concepts: [[concepts]]\n",
        PATTERNS_FILE: f"# Patterns\n*Thinking patterns and behaviours Alicia has observed in {USER_NAME}.*\n\n",
        INSIGHTS_FILE: "# Insights\n*Key insights from conversations, in order of recency.*\n\n",
        PREFERENCES_FILE: f"# Preferences\n*How {USER_NAME} likes to think, work, and communicate.*\n\n",
        CONCEPTS_FILE: "# Concepts\n*Ideas being actively developed together.*\n\n",
    }

    for filepath, default_content in defaults.items():
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(default_content)

    # Vault folders
    for folder in [
        "Knowledge Vault/Concepts",
        "Self/Patterns",
        "Self/Memory",
        "Wisdom/Synthesis",
        "Wisdom/Contradictions",
        "Wisdom/Principles",
        "Wisdom/Frameworks",
        "Inbox",
    ]:
        os.makedirs(os.path.join(VAULT, folder), exist_ok=True)


def sync_memory_to_vault():
    """Copy all memory files to the Obsidian vault so the user can browse them.
    Mirrors ~/alicia/memory/*.md → Alicia/Self/Memory/ in the vault.
    Called after every memory write operation."""
    import shutil
    try:
        os.makedirs(VAULT_MEMORY_DIR, exist_ok=True)
        for src_path in [MEMORY_FILE, PATTERNS_FILE, INSIGHTS_FILE,
                         PREFERENCES_FILE, CONCEPTS_FILE]:
            if os.path.exists(src_path):
                filename = os.path.basename(src_path)
                dst_path = os.path.join(VAULT_MEMORY_DIR, filename)
                shutil.copy2(src_path, dst_path)
    except Exception:
        pass  # Non-critical — don't break memory writes if vault sync fails


# ── Hot Topics Bridge (Alicia → Cowork) ──────────────────────────────────────

def _write_hot_topic(value: str, ext_type: str, score: int):
    """
    Write a score-5 insight to hot_topics.md so Cowork scheduled tasks
    can bias their synthesis targeting toward the user's current interests.

    Format: timestamped entries, max 15 (oldest pruned).
    Read by: vault-synthesis-pass, weekly-vault-blitz, outward-research-discovery.
    """
    try:
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- ({date}) [{ext_type}] {value.strip()}"

        # Exclusive lock across the whole read-modify-write — prevents
        # two concurrent writers from silently losing each other's entries.
        with locked_file(HOT_TOPICS_FILE, "a"):
            existing = []
            if os.path.exists(HOT_TOPICS_FILE):
                with open(HOT_TOPICS_FILE) as f:
                    lines = f.readlines()
                existing = [l.rstrip() for l in lines if l.startswith("- (")]

            # Add new entry and keep only the 15 most recent
            existing.append(entry)
            existing = existing[-15:]

            header = (
                "# Hot Topics — Alicia → Cowork Bridge\n"
                f"# Score-5 insights from {USER_NAME}'s conversations.\n"
                "# Read by Cowork synthesis tasks to bias targeting toward current interests.\n"
                "# Auto-maintained: max 15 entries, oldest pruned.\n\n"
            )
            atomic_write_text(
                HOT_TOPICS_FILE,
                header + "\n".join(existing) + "\n",
            )
    except Exception:
        pass  # Non-critical — don't break memory writes


# ── Layer 1: Session Memory ───────────────────────────────────────────────────

def load_alicia_md() -> str:
    """Load the ALICIA.md exosuit document."""
    if os.path.exists(ALICIA_MD):
        with open(ALICIA_MD) as f:
            return f.read()
    return ""


def load_memory_files() -> dict:
    """Load all memory files into a dict."""
    ensure_memory_structure()
    files = {
        "memory":      MEMORY_FILE,
        "patterns":    PATTERNS_FILE,
        "insights":    INSIGHTS_FILE,
        "preferences": PREFERENCES_FILE,
        "concepts":    CONCEPTS_FILE,
    }
    loaded = {}
    for key, path in files.items():
        try:
            with open(path) as f:
                loaded[key] = f.read()
        except Exception:
            loaded[key] = ""
    return loaded


def load_bridge_handoff() -> str:
    """Read the Bridge handoff file for cross-interface continuity.
    This is how Telegram Alicia knows what happened in Cowork sessions
    and vice versa. The Bridge layer lives in the Obsidian vault so
    it syncs across all devices."""
    if os.path.exists(BRIDGE_HANDOFF):
        try:
            with open(BRIDGE_HANDOFF) as f:
                return f.read()
        except Exception:
            return ""
    return ""


def write_telegram_session_summary(summary: str, active_threads: list = None):
    """Write a Telegram session digest to the Bridge.
    Called at the end of meaningful conversations so Cowork
    can pick up where Telegram left off.

    Routes through bridge_protocol.write_bridge_text for atomicity + INDEX
    logging. (Was previously a bare `open(...).write(...)` — the migration
    also fixes that non-atomic write bug.)
    """
    date = datetime.now().strftime("%Y-%m-%d")
    content = f"# Telegram Session — {date}\n\n{summary}\n\n"
    if active_threads:
        content += "## Active Threads\n"
        for thread in active_threads:
            content += f"- {thread}\n"

    write_bridge_text(f"telegram-sessions/{date}.md", content)


def build_session_context(user_message: str = "") -> str:
    """
    Build the session context with retrieval-augmented memory.

    Instead of dumping all memory files into the prompt, we:
    1. Always include MEMORY.md (core identity — small, high-signal)
    2. Always include the Bridge handoff (cross-interface continuity)
    3. Use semantic search to pull ONLY the memories relevant to the current message
    4. Include ALICIA.md (the exosuit)

    This means: if the user is talking about his daughter, he gets parenting memories.
    If he's talking about Pirsig, he gets quality/philosophy memories. Not both.
    """
    alicia_md = load_alicia_md()
    mem = load_memory_files()
    bridge = load_bridge_handoff()

    # Keep MEMORY.md under 200 lines (always included — it's the identity core)
    memory_lines = mem["memory"].split("\n")
    if len(memory_lines) > 200:
        memory_lines = memory_lines[:200]
        mem["memory"] = "\n".join(memory_lines)

    context = f"{alicia_md}\n\n---\n\n## Current Memory State\n\n"
    context += f"### MEMORY.md\n{mem['memory']}\n\n"

    # Retrieval-augmented memory: if there's a user message, search memory files
    # for relevant content instead of including everything
    if user_message and len(user_message) > 10:
        relevant_memories = _retrieve_relevant_memories(user_message, mem)
        if relevant_memories:
            context += f"### Relevant Memories (for this conversation)\n{relevant_memories}\n\n"
    else:
        # No message context — fall back to recent entries from each file
        if mem["patterns"].strip() and len(mem["patterns"]) > 50:
            context += f"### Patterns\n{mem['patterns'][-1000:]}\n\n"
        if mem["insights"].strip() and len(mem["insights"]) > 50:
            context += f"### Recent Insights\n{mem['insights'][-1000:]}\n\n"
        if mem["concepts"].strip() and len(mem["concepts"]) > 50:
            context += f"### Active Concepts\n{mem['concepts'][-800:]}\n\n"

    # Bridge: cross-interface continuity (always included)
    if bridge.strip() and len(bridge) > 50:
        # Only include the top sections of the bridge, not the full vault changelog
        bridge_lines = bridge.split('\n')
        bridge_compact = []
        for line in bridge_lines:
            bridge_compact.append(line)
            if line.startswith('## Vault Changes'):
                bridge_compact.append("_(see HANDOFF.md for full details)_")
                break
        context += f"---\n\n## Bridge — Cross-Interface Continuity\n\n" + "\n".join(bridge_compact) + "\n\n"

    return context


def _retrieve_relevant_memories(message: str, mem: dict, max_entries: int = 15) -> str:
    """
    Search across all memory files for entries relevant to the current message.
    Returns a curated string of the most relevant memories.
    """
    message_lower = message.lower()

    # Extract key terms from the message for matching
    # Remove common words, keep meaningful terms
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
                  'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
                  'before', 'after', 'above', 'below', 'and', 'but', 'or', 'not', 'no',
                  'so', 'if', 'then', 'than', 'too', 'very', 'just', 'about', 'up',
                  'out', 'that', 'this', 'what', 'which', 'who', 'how', 'when', 'where',
                  'why', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
                  'some', 'such', 'only', 'own', 'same', 'also', 'you', 'your', 'i',
                  'me', 'my', 'we', 'our', 'it', 'its', 'they', 'them', 'their',
                  'him', 'her', 'his', 'she', 'he'}
    terms = set()
    for word in re.split(r'\W+', message_lower):
        if word and len(word) > 2 and word not in stop_words:
            terms.add(word)

    if not terms:
        return ""

    # Score each line across all memory files
    scored_entries = []

    for file_name in ["patterns", "insights", "preferences", "concepts"]:
        content = mem.get(file_name, "")
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('*'):
                continue

            line_lower = line.lower()
            # Count term matches
            matches = sum(1 for t in terms if t in line_lower)
            if matches > 0:
                # Boost score for more matches and for score-tagged entries
                score = matches
                if '[score:5]' in line:
                    score *= 1.5
                elif '[score:4]' in line:
                    score *= 1.2
                scored_entries.append((score, f"[{file_name}] {line}"))

    if not scored_entries:
        # No keyword matches — include recent high-signal entries as fallback
        fallback = []
        for file_name in ["insights", "patterns", "concepts"]:
            content = mem.get(file_name, "")
            lines = [l.strip() for l in content.split('\n') if l.strip() and not l.startswith('#') and not l.startswith('*')]
            # Take last 3 entries from each
            for l in lines[-3:]:
                fallback.append(f"[{file_name}] {l}")
        return "\n".join(fallback[-max_entries:])

    # Sort by relevance score, take top entries
    scored_entries.sort(key=lambda x: x[0], reverse=True)
    return "\n".join(entry for _, entry in scored_entries[:max_entries])


def append_to_memory_file(filepath: str, content: str):
    """Append content to a memory file."""
    ensure_memory_structure()
    with open(filepath, "a") as f:
        f.write(f"\n{content}\n")
    sync_memory_to_vault()


def update_memory_md(key: str, value: str):
    """Update or add a key in MEMORY.md. Deduplicates by key name."""
    ensure_memory_structure()
    with open(MEMORY_FILE) as f:
        content = f.read()

    date = datetime.now().strftime("%Y-%m-%d")
    new_line = f"- **{key}** ({date}): {value}"

    # Check if this key already exists — update in place instead of appending
    key_pattern = re.compile(r'^- \*\*' + re.escape(key) + r'\*\*\s*\(.*?\):.*$', re.MULTILINE)
    if key_pattern.search(content):
        # Replace the LAST occurrence (most recent gets updated, old ones removed)
        matches = list(key_pattern.finditer(content))
        # Remove all occurrences
        content = key_pattern.sub('', content)
        # Clean up empty lines left behind
        content = re.sub(r'\n{3,}', '\n\n', content)
        # Append the updated version
        content = content.rstrip() + f"\n{new_line}"
    else:
        # New key — find the right section and insert
        if f"## About {USER_NAME}" in content and key.lower() in ["name", "age", "location", "job", "family"]:
            content = content.replace(f"## About {USER_NAME}\n", f"## About {USER_NAME}\n{new_line}\n")
        elif "## Key Insights" in content and "insight" in key.lower():
            content = content.replace("## Key Insights\n", f"## Key Insights\n{new_line}\n")
        else:
            content = content.rstrip() + f"\n{new_line}"

    with open(MEMORY_FILE, "w") as f:
        f.write(content)
    sync_memory_to_vault()

    return f"Remembered: {key} = {value}"


# ── Layer 1: Auto-extraction from conversations ───────────────────────────────

EXTRACTION_SYSTEM = """You are a memory extraction and scoring engine for a sovereign AI agent.

Given a message from the user, extract memorable content AND score each extraction for signal quality.

Return ONLY valid JSON:
{
  "extractions": [
    {
      "type": "memory_md|pattern|insight|preference|concept",
      "key": "descriptive_key (for memory_md and preference types)",
      "value": "the content to remember",
      "score": 1-5,
      "reasoning": "why this score — one sentence"
    }
  ]
}

SCORING RUBRIC (same pattern as vault synthesis scoring):
- 5: Life-defining realization, core value revealed, permanent identity marker. Would still matter in 5 years.
- 4: Significant insight, durable pattern, or meaningful preference. Changes how Alicia understands the user.
- 3: Moderate signal. Real content but could be noise. Not distinctive enough to keep long-term.
- 2: Low signal. Meta-observation, surface-level, or obvious from context.
- 1: Noise. Small talk, technical troubleshooting, communication tics, passing remarks.

QUALITY GATE: Only extractions scoring 4 or 5 will be persisted. 3 and below are logged but discarded.
This means you should STILL extract 2s and 3s (for logging), but be honest about their score.

TYPE DEFINITIONS:
- memory_md: Core facts about who the user is — identity, relationships, beliefs, life circumstances
- pattern: DEEP recurring ways of thinking, deciding, or valuing (NOT behavioral tics)
- insight: Original realizations the user reached — ideas worth preserving for years
- preference: Strong, durable preferences about how he works, thinks, or communicates
- concept: Ideas being actively developed with intellectual weight

Return {"extractions": []} if the message has nothing worth extracting at any level."""

MEMORY_RESULTS_FILE = os.path.join(MEMORY_DIR, "memory_results.tsv")


def _init_memory_results_log():
    """Initialize the memory results TSV if it doesn't exist."""
    if not os.path.exists(MEMORY_RESULTS_FILE):
        with open(MEMORY_RESULTS_FILE, 'w') as f:
            f.write("timestamp\ttype\tkey\tscore\tdecision\tvalue\treasoning\n")


def _log_memory_result(extraction: dict, decision: str):
    """Log a memory extraction result to the TSV."""
    _init_memory_results_log()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = (
        f"{timestamp}\t"
        f"{extraction.get('type', '')}\t"
        f"{extraction.get('key', '')}\t"
        f"{extraction.get('score', 0)}\t"
        f"{decision}\t"
        f"{extraction.get('value', '')[:200]}\t"
        f"{extraction.get('reasoning', '')}\n"
    )
    with open(MEMORY_RESULTS_FILE, 'a') as f:
        f.write(row)


def extract_from_message(message: str, is_voice: bool = False) -> bool:
    """
    Extract, score, and gate memorable content from a message.
    Follows the autoresearch pattern: extract → score → keep/discard → log.
    Only score 4+ gets persisted. Everything gets logged.

    Args:
        message: The text to extract from.
        is_voice: If True, message originated from voice input. Adds voice awareness to extraction.

    Returns True if anything was kept.
    """
    # Skip very short messages — not worth an API call
    if len(message.strip()) < 30:
        return False

    try:
        system_prompt = EXTRACTION_SYSTEM
        if is_voice:
            system_prompt += """

NOTE: This message was SPOKEN (voice input). Voice often reveals authenticity that text misses. Tag any extracted insight with [voice] marker.

VOICE METADATA TAGS (if present at the start of the message):
- [deliberate] = the user spoke slowly and deliberately (< 100 wpm). This signals deep thinking, uncertainty, or a growth edge being explored. BOOST score by 1 for insights tagged this way.
- [excited] = the user spoke rapidly (> 160 wpm). This signals enthusiasm, resonance, or a connection being made in real time. Note the energy in your extraction.
- [extended] = Voice note was longer than 60 seconds. Extended voice notes are inherently high-signal — the user chose to think out loud at length. BOOST score by 1 for insights from extended notes.

These tags are metadata — do NOT include them in the extracted value text. They inform scoring only."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": message}]
        )
        # Guard against empty or non-text API responses
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return False

        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        result = json.loads(raw)
        extractions = result.get("extractions", [])
        if not extractions:
            return False

        kept = False
        date = datetime.now().strftime("%Y-%m-%d %H:%M")

        for ext in extractions:
            score = ext.get("score", 0)
            ext_type = ext.get("type", "")
            value = ext.get("value", "")
            key = ext.get("key", "")

            # Quality gate: only persist 4+
            if score >= 4:
                decision = "keep"

                # Prepend [voice] marker if this came from voice input
                voice_prefix = "[voice] " if is_voice else ""

                if ext_type == "memory_md" and key:
                    update_memory_md(key, voice_prefix + value)
                    kept = True
                elif ext_type == "pattern":
                    append_to_memory_file(PATTERNS_FILE, f"- ({date}) [score:{score}] {voice_prefix}{value}")
                    kept = True
                elif ext_type == "insight":
                    append_to_memory_file(INSIGHTS_FILE, f"- ({date}) [score:{score}] {voice_prefix}{value}")
                    kept = True
                elif ext_type == "preference" and key:
                    append_to_memory_file(PREFERENCES_FILE, f"- **{key}** [score:{score}]: {voice_prefix}{value}")
                    kept = True
                elif ext_type == "concept":
                    append_to_memory_file(CONCEPTS_FILE, f"- ({date}) [score:{score}] {voice_prefix}{value}")
                    kept = True

                # Hot topics bridge: score-5 insights signal current interests to Cowork
                if score >= 5:
                    _write_hot_topic(value, ext_type, score)

                # Phase 12.1 — the user-model auto-extraction. Every kept
                # extraction also appends a learning to user_learnings.jsonl
                # tagged with a keyword-classified dimension. Confidence
                # = score/5 (so 4 → 0.8, 5 → 1.0). Failures are non-fatal.
                try:
                    from myalicia.skills.user_model import (
                        append_learning as _hm_append_learning,
                        classify_dimension as _hm_classify_dimension,
                    )
                    dim = _hm_classify_dimension(value, ext_type=ext_type)
                    _hm_append_learning(
                        claim=value,
                        dimension=dim,
                        confidence=score / 5.0,
                        source=f"memory_skill:{ext_type}",
                        evidence=key or None,
                    )
                except Exception:
                    # Non-fatal — the user-model is best-effort augmentation,
                    # never blocks memory_skill from doing its primary job.
                    pass
            else:
                decision = "discard"

            # Log everything — kept AND discarded
            _log_memory_result(ext, decision)

        if kept:
            sync_memory_to_vault()
        return kept

    except Exception:
        return False


def get_memory_extraction_stats() -> dict:
    """Get stats from the memory results log — like synthesis_results.tsv but for memory."""
    if not os.path.exists(MEMORY_RESULTS_FILE):
        return {"total": 0, "kept": 0, "discarded": 0, "avg_score": 0}

    total = kept = discarded = score_sum = 0
    try:
        with open(MEMORY_RESULTS_FILE) as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    total += 1
                    score = int(parts[3]) if parts[3].isdigit() else 0
                    score_sum += score
                    if parts[4] == "keep":
                        kept += 1
                    else:
                        discarded += 1
    except Exception:
        pass

    return {
        "total": total,
        "kept": kept,
        "discarded": discarded,
        "keep_rate": f"{kept/total*100:.0f}%" if total > 0 else "0%",
        "avg_score": round(score_sum / total, 1) if total > 0 else 0,
    }


# ── Memory Consolidation ─────────────────────────────────────────────────────

CONSOLIDATION_PROMPT = """You are Alicia's memory consolidation engine. You're given the raw contents of a memory file that has accumulated over time.

Your job: consolidate it into a clean, non-redundant version that preserves ALL important information but removes:
1. Duplicate entries (keep the richest version)
2. Trivial observations ("asks follow-up questions", "encounters technical issues")
3. Meta-observations about communication style that aren't real preferences
4. One-off mentions that aren't actually patterns/insights/concepts

Rules:
- PRESERVE the file's header and any structured sections (## headers)
- PRESERVE all genuinely important content — do not delete real insights or patterns
- MERGE duplicates into a single, richer entry
- REMOVE noise ruthlessly
- Keep the format consistent: "- (date) content" for timestamped entries, "- **key**: value" for keyed entries
- Output the COMPLETE consolidated file, ready to be written back"""


def consolidate_memory_file(filepath: str) -> str:
    """
    Consolidate a memory file: merge duplicates, remove noise, preserve signal.
    Returns the consolidated content.
    """
    with open(filepath) as f:
        content = f.read()

    # Skip if file is small enough already
    line_count = len(content.strip().split('\n'))
    if line_count < 30:
        return content

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=CONSOLIDATION_PROMPT,
            messages=[{"role": "user", "content": f"Consolidate this memory file:\n\n{content}"}]
        )
        # Guard against empty or non-text API responses
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return content

        consolidated = response.content[0].text.strip()

        # Safety: don't write if consolidation is drastically shorter (lost data)
        if len(consolidated) < len(content) * 0.3:
            return content  # Refuse — too much was removed

        return consolidated
    except Exception:
        return content


def consolidate_all_memory():
    """
    Run consolidation across all memory files.
    Called weekly or on demand. Returns summary of what changed.
    """
    ensure_memory_structure()
    results = []
    for name, filepath in [
        ("patterns", PATTERNS_FILE),
        ("insights", INSIGHTS_FILE),
        ("preferences", PREFERENCES_FILE),
        ("concepts", CONCEPTS_FILE),
    ]:
        with open(filepath) as f:
            before = f.read()
        before_lines = len(before.strip().split('\n'))

        consolidated = consolidate_memory_file(filepath)
        after_lines = len(consolidated.strip().split('\n'))

        if consolidated != before:
            with open(filepath, 'w') as f:
                f.write(consolidated)
            results.append(f"{name}: {before_lines} → {after_lines} lines")
        else:
            results.append(f"{name}: no changes needed")

    # Also deduplicate MEMORY.md keys
    _deduplicate_memory_md()

    # Sync consolidated files to vault
    sync_memory_to_vault()

    return results


def _deduplicate_memory_md():
    """Remove duplicate key entries from MEMORY.md, keeping the most recent."""
    with open(MEMORY_FILE) as f:
        lines = f.readlines()

    seen_keys = {}
    output = []

    for line in lines:
        # Match keyed entries: - **key** (date): value
        match = re.match(r'^- \*\*(.+?)\*\*\s*\((\d{4}-\d{2}-\d{2})\):\s*(.+)$', line.strip())
        if match:
            key = match.group(1)
            date = match.group(2)
            if key in seen_keys:
                # Keep the newer one (replace if this date is more recent)
                old_idx, old_date = seen_keys[key]
                if date >= old_date:
                    output[old_idx] = None  # Mark old one for removal
                    seen_keys[key] = (len(output), date)
                    output.append(line)
                else:
                    output.append(None)  # Skip this older duplicate
                continue
            else:
                seen_keys[key] = (len(output), date)

        output.append(line)

    # Write back, filtering out None entries
    with open(MEMORY_FILE, 'w') as f:
        f.writelines(line for line in output if line is not None)


# ── Layer 2: Knowledge Graph ──────────────────────────────────────────────────

def find_related_notes(topic: str, max_results: int = 5) -> list:
    """Search vault for notes related to a topic by filename and content."""
    results = []
    topic_words = set(topic.lower().split())

    for root, dirs, files in os.walk(VAULT_ROOT):
        # Skip hidden folders
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            name = f.replace(".md", "").lower()
            # Score by word overlap in filename
            name_words = set(re.split(r'[\s\-_]+', name))
            overlap = len(topic_words & name_words)
            if overlap > 0:
                results.append((overlap, filepath, f.replace(".md", "")))

    # Sort by relevance
    results.sort(reverse=True)
    return [(path, name) for _, path, name in results[:max_results]]


def build_wikilinks(topic: str) -> str:
    """Find related notes and format as wikilinks."""
    related = find_related_notes(topic)
    if not related:
        return ""
    links = [f"[[{name}]]" for _, name in related]
    return ", ".join(links)


def write_concept_note(title: str, content: str, folder: str = "Knowledge Vault/Concepts") -> str:
    """Write a concept note to Obsidian with proper wikilinks."""
    path = os.path.join(VAULT, folder)
    os.makedirs(path, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[\s_]+', '-', slug)[:60]
    filename = f"{date}-{slug}.md"
    filepath = os.path.join(path, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


# ── Wisdom synthesis ──────────────────────────────────────────────────────────

CONCEPT_SYSTEM = """You are Alicia, a wisdom partner. Create a rich concept note for an Obsidian knowledge vault.

Rules for this note:
1. Title must be a CLAIM, not a category. e.g. "curiosity compounds faster than discipline" not "notes on curiosity"
2. The note should develop the idea deeply — not just define it
3. Include connections to related ideas using [[wikilink]] syntax
4. Find tensions and contradictions within the concept
5. End with "What this means for the user" — practical, personal, specific
6. Suggest 2-3 follow-on questions worth exploring

Format:
# [claim as title]
**Created:** [date]
**Tags:** #concept #[domain]

## The Core Idea
[2-3 sentences that capture the essential claim]

## Why This Matters
[deeper development — what makes this non-obvious]

## Tensions and Contradictions
[where this idea gets complicated or conflicts with other things]

## Connections
[wikilinks to related concepts, written as sentences]
e.g. "This builds on [[the gap between knowing and doing]] and challenges [[discipline as the foundation of growth]]"

## What This Means for the user
[specific, personal, actionable — not generic wisdom]

## Questions Worth Exploring
- [question 1]
- [question 2]
- [question 3]"""


SYNTHESIS_SYSTEM = """You are Alicia, a wisdom partner with access to the user's knowledge vault. 

Your job is to synthesise across multiple notes and find:
1. Patterns that appear in 3+ places (likely a principle)
2. Tensions between ideas (productive contradictions worth exploring)
3. New concepts that haven't been named yet
4. Ideas that are close but haven't been connected yet

Be specific. Reference actual content. This is synthesis, not summary.
Write as if speaking directly to the user — warm, direct, intellectually alive."""


def generate_concept_note(topic: str) -> tuple:
    """Generate a deep concept note and save to Obsidian."""
    date = datetime.now().strftime("%Y-%m-%d")

    # Find related notes from vault for context
    related = find_related_notes(topic, max_results=8)
    related_context = ""
    if related:
        related_context = f"\n\nRelated notes already in vault:\n"
        for path, name in related:
            related_context += f"- [[{name}]]\n"
            try:
                with open(path) as f:
                    snippet = f.read()[:300]
                related_context += f"  Preview: {snippet[:150]}...\n"
            except Exception:
                pass

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=CONCEPT_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Create a concept note for: {topic}\n\nToday's date: {date}{related_context}"
        }]
    )

    # Guard against empty or non-text API responses
    if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
        fallback = f"# {topic}\n\n*Could not generate concept note — API returned empty response.*\n"
        filepath = write_concept_note(topic, fallback)
        return fallback, filepath, topic

    content = response.content[0].text

    # Extract title from first line
    first_line = content.split("\n")[0].replace("# ", "").strip()

    filepath = write_concept_note(first_line, content)
    return content, filepath, first_line


def synthesise_vault(recent_only: bool = True) -> str:
    """Read recent vault notes and synthesise patterns and connections."""
    notes_content = []

    # Gather recent notes
    search_paths = [
        os.path.join(VAULT, "Knowledge Vault"),
        os.path.join(VAULT, "Self/Reflections"),
        os.path.join(VAULT, "Wisdom"),
    ]

    all_files = []
    for search_path in search_paths:
        if not os.path.exists(search_path):
            continue
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.endswith(".md"):
                    filepath = os.path.join(root, f)
                    mtime = os.path.getmtime(filepath)
                    all_files.append((mtime, filepath))

    # Sort by recency, take last 15
    all_files.sort(reverse=True)
    recent_files = all_files[:15]

    for _, filepath in recent_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()[:600]
            name = os.path.basename(filepath).replace(".md", "")
            notes_content.append(f"### {name}\n{content}\n")
        except Exception:
            pass

    if not notes_content:
        return "📭 No notes found in vault to synthesise."

    vault_text = "\n".join(notes_content)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        system=SYNTHESIS_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Synthesise these recent notes from {USER_NAME}'s vault. Find patterns, tensions, and new connections:\n\n{vault_text}"
        }]
    )

    # Guard against empty or non-text API responses
    if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
        return "Could not synthesise — API returned empty response."

    synthesis = response.content[0].text

    # Save synthesis note to Obsidian
    date = datetime.now().strftime("%Y-%m-%d")
    note_content = f"# Synthesis — {date}\n**Generated by Alicia**\n\n{synthesis}\n"
    synthesis_path = write_concept_note(f"Synthesis {date}", note_content, "Wisdom/Synthesis")

    # Close the circulatory loop (Wisdom Engine · Layer 1). Best-effort:
    # unstructured daily roll-ups are skipped by the Finalizer gracefully;
    # structured syntheses get backlinks + themes + bridge log + surfacings.
    try:
        from myalicia.skills.synthesis_finalizer import finalize as _finalize_synthesis
        _finalize_synthesis(synthesis_path)
    except Exception as e:
        print(f"[memory_skill] synthesis_finalizer failed for {synthesis_path}: {e}")

    return synthesis


def find_contradictions() -> str:
    """Find tensions and contradictions across vault notes."""
    notes = []

    quotes_path = QUOTES_FOLDER
    vault_wisdom = os.path.join(VAULT, "Wisdom")

    for search_path in [quotes_path, vault_wisdom]:
        if not os.path.exists(search_path):
            continue
        for root, dirs, files in os.walk(search_path):
            for f in files[:20]:
                if f.endswith(".md"):
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, encoding="utf-8") as fh:
                            content = fh.read()[:400]
                        notes.append(f"**{f.replace('.md','')}**: {content[:200]}")
                    except Exception:
                        pass

    if not notes:
        return "No notes found to analyse for contradictions."

    notes_text = "\n\n".join(notes[:20])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        system="You are a philosophical thinking partner. Find productive contradictions and tensions between these ideas. Don't resolve them — illuminate them. These tensions are where the real thinking happens.",
        messages=[{
            "role": "user",
            "content": f"Find 3-4 productive contradictions or tensions in these notes:\n\n{notes_text}"
        }]
    )

    # Guard against empty or non-text API responses
    if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
        return "Could not find contradictions — API returned empty response."

    result = response.content[0].text

    # Save to vault
    date = datetime.now().strftime("%Y-%m-%d")
    note_content = f"# Contradictions — {date}\n**Found by Alicia**\n\n{result}\n"
    write_concept_note(f"Contradictions {date}", note_content, "Wisdom/Contradictions")

    return result


# ── Layer 3: Ingestion pipeline ───────────────────────────────────────────────

INGEST_SYSTEM = """You are a knowledge extraction engine. Given raw text (from a URL, transcript, or document), extract structured knowledge for an Obsidian vault.

Output a complete Obsidian note with this structure:

# [claim-as-title — name the most important idea as a statement]
**Source:** [source]
**Ingested:** [date]
**Tags:** #ingested #[domain]

## Core Claim
[The single most important idea in 2-3 sentences]

## Key Ideas
[5-8 bullet points of the most valuable, non-obvious ideas]

## Frameworks and Mental Models
[Any named frameworks, models, or structured ways of thinking]

## Actionable Insights
[What someone could actually do with this knowledge]

## Connections
[Wikilinks to related concepts — write them as sentences]
e.g. "This challenges [[the assumption that discipline beats curiosity]]"

## Questions This Raises
[2-3 genuine open questions worth exploring]

---
Rules:
- Name the note as a CLAIM, not a category
- Only include genuinely non-obvious insights
- Make wikilinks specific and meaningful
- Be intellectually honest about what's speculation vs established"""


def ingest_text(text: str, source: str = "manual input", title: str = "") -> tuple:
    """Ingest raw text into a structured vault note."""
    date = datetime.now().strftime("%Y-%m-%d")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=INGEST_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Source: {source}\nDate: {date}\n\nContent to extract knowledge from:\n\n{text[:4000]}"
        }]
    )

    # Guard against empty or non-text API responses
    if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
        fallback = f"# {title or source}\n\n*Could not ingest — API returned empty response.*\n"
        filepath = write_concept_note(title or source, fallback, "Inbox")
        return fallback, filepath, title or source

    content = response.content[0].text

    # Extract title from first line
    first_line = content.split("\n")[0].replace("# ", "").strip()
    if title:
        first_line = title

    filepath = write_concept_note(first_line, content, "Inbox")
    return content, filepath, first_line


# ── Memory summary for Telegram ───────────────────────────────────────────────

def get_memory_summary() -> str:
    """Return readable memory summary for Telegram."""
    ensure_memory_structure()

    with open(MEMORY_FILE) as f:
        memory_content = f.read()

    with open(INSIGHTS_FILE) as f:
        insights_content = f.read()

    with open(CONCEPTS_FILE) as f:
        concepts_content = f.read()

    # Count vault notes
    note_count = 0
    for root, dirs, files in os.walk(VAULT):
        note_count += len([f for f in files if f.endswith(".md")])

    lines = [f"🧠 *Alicia's Memory State*\n"]
    lines.append(f"📚 Vault notes: {note_count}")

    # Recent insights
    insight_lines = [l for l in insights_content.split("\n") if l.startswith("- (")]
    if insight_lines:
        lines.append(f"\n*💡 Recent insights ({len(insight_lines)} total):*")
        for l in insight_lines[-3:]:
            lines.append(f"  {l}")

    # Active concepts
    concept_lines = [l for l in concepts_content.split("\n") if l.startswith("- (")]
    if concept_lines:
        lines.append(f"\n*🔮 Active concepts ({len(concept_lines)} total):*")
        for l in concept_lines[-3:]:
            lines.append(f"  {l}")

    lines.append(f"\n_Full memory in Obsidian → Self/Memory_")
    lines.append(f"_Use /synthesise to find new connections_")

    return "\n".join(lines)


def remember_manual(key: str, value: str) -> str:
    """Manually store a memory. Returns confirmation string."""
    return update_memory_md(key, value)


def forget_manual(key: str) -> bool:
    """Remove a key from MEMORY.md."""
    with open(MEMORY_FILE) as f:
        lines = f.readlines()
    new_lines = [l for l in lines if key.lower() not in l.lower()]
    if len(new_lines) < len(lines):
        with open(MEMORY_FILE, "w") as f:
            f.writelines(new_lines)
        return True
    return False


def build_resonance_map() -> dict:
    """
    Build a resonance map by counting how often concepts/topics appear
    across memory files (MEMORY.md, patterns.md, insights.md, concepts.md).
    Scores each by frequency (normalized 0-1).
    Writes top 15 to ~/alicia/memory/resonance.md.
    Returns dict of concept→score.
    """
    ensure_memory_structure()

    # Files to scan
    memory_files = [MEMORY_FILE, PATTERNS_FILE, INSIGHTS_FILE, CONCEPTS_FILE]

    # Collect all content
    all_content = ""
    for fpath in memory_files:
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    all_content += "\n" + f.read()
            except Exception:
                pass

    # Count concepts/topics:
    # 1. Look for [[wikilinks]]
    wikilinks = re.findall(r'\[\[(.+?)\]\]', all_content)
    wikilink_counts = {}
    for link in wikilinks:
        wikilink_counts[link] = wikilink_counts.get(link, 0) + 1

    # 2. Look for **bold** terms (markdown emphasis)
    bold_terms = re.findall(r'\*\*(.+?)\*\*', all_content)
    bold_counts = {}
    for term in bold_terms:
        # Filter out common markdown markup
        if len(term) > 3 and term.lower() not in ['note', 'important', 'key']:
            bold_counts[term] = bold_counts.get(term, 0) + 1

    # Merge counts
    all_counts = {**wikilink_counts, **bold_counts}

    if not all_counts:
        return {}

    # Normalize scores to 0-1 range
    max_count = max(all_counts.values()) if all_counts else 1
    resonance_map = {
        concept: min(count / max_count, 1.0)
        for concept, count in all_counts.items()
    }

    # Sort by score and take top 15
    top_resonances = sorted(
        resonance_map.items(),
        key=lambda x: x[1],
        reverse=True
    )[:15]

    # Write to resonance.md
    resonance_file = os.path.join(MEMORY_DIR, "resonance.md")
    with open(resonance_file, "w") as f:
        f.write("# Resonance Map\n")
        f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("*Top 15 concepts by frequency across memory files*\n\n")
        for concept, score in top_resonances:
            f.write(f"- **{concept}** ({score:.2f})\n")

    # Return the full map for use in other functions
    return dict(resonance_map)


if __name__ == "__main__":
    ensure_memory_structure()
    print("Memory system initialised.")
    print(f"Memory dir: {MEMORY_DIR}")
    print(f"Vault: {VAULT}")
    print("\nTesting concept generation...")
    content, path, title = generate_concept_note("the relationship between curiosity and wisdom")
    print(f"Created: {title}")
    print(f"Path: {path}")