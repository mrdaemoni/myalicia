"""
Alicia's Way of Being: Mythological Archetypes for Self-Directed Growth

This module implements four core capabilities:
1. Self-Awareness Layer (Beatrice archetype)
2. Daimon's Warning (pattern detection)
3. Reciprocal Challenge (Psyche archetype)
4. Musubi Bond Reflection (generative co-emergence)

All analysis is heuristic and pattern-based. No API calls in this module.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from myalicia.skills.bridge_protocol import get_latest_report
from myalicia.config import config


# Configuration
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
SELF_AWARENESS_PATH = os.path.join(MEMORY_DIR, "self_awareness.md")
DEPTH_SIGNALS_PATH = os.path.join(MEMORY_DIR, "depth_signals.jsonl")
CHALLENGE_LOG_PATH = os.path.join(MEMORY_DIR, "challenge_log.json")
VAULT_ROOT = str(config.vault.root)
BRIDGE_DIR = os.path.join(VAULT_ROOT, "Alicia/Bridge")
SYNTHESIS_RESULTS_PATH = os.path.join(MEMORY_DIR, "synthesis_results.tsv")
OVERNIGHT_STATE_PATH = os.path.join(MEMORY_DIR, "overnight_state.json")
SESSION_THREADS_PATH = os.path.join(MEMORY_DIR, "session_threads.json")
LOG_DIR = os.path.expanduser("~/alicia/logs")

DAIMON_COOLDOWN_HOURS = 24
CHALLENGE_COOLDOWN_DAYS = 7
SELF_REFLECTION_WINDOW_DAYS = 7
AVOIDANCE_THRESHOLD = 3
SHALLOW_DEPTH_THRESHOLD = 200

logger = logging.getLogger("alicia")

# Simple English stopwords for theme extraction
STOPWORDS = {
    "the", "a", "an", "is", "was", "are", "am", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "could", "and", "or", "but",
    "not", "no", "yes", "in", "on", "at", "to", "from", "of", "for",
    "with", "by", "as", "if", "that", "this", "it", "it's", "i", "you",
    "he", "she", "we", "they", "me", "him", "her", "us", "them", "what",
    "which", "who", "when", "where", "why", "how", "just", "about",
    "more", "most", "some", "any", "all", "each", "every", "both",
}


def _ensure_memory_dir() -> None:
    """Ensure memory directory exists."""
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _now_iso() -> str:
    """Return current time as ISO 8601 string in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(timestamp_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string."""
    try:
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        return None


def _read_json(path: str) -> dict:
    """Safely read JSON file, return empty dict on error."""
    try:
        with open(os.path.expanduser(path), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
        logger.debug(f"Could not read {path}: {e}")
        return {}


def _read_json_lines(path: str) -> list[dict]:
    """Safely read JSONL file, return empty list on error."""
    try:
        lines = []
        with open(os.path.expanduser(path), "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug(f"Skipped malformed JSONL line in {path}")
        return lines
    except (FileNotFoundError, IOError) as e:
        logger.debug(f"Could not read {path}: {e}")
        return []


def _write_json(path: str, data: dict) -> bool:
    """Safely write JSON file."""
    try:
        _ensure_memory_dir()
        with open(os.path.expanduser(path), "w") as f:
            json.dump(data, f, indent=2)
        return True
    except IOError as e:
        logger.error(f"Could not write {path}: {e}")
        return False


def _append_json_line(path: str, data: dict) -> bool:
    """Safely append line to JSONL file."""
    try:
        _ensure_memory_dir()
        with open(os.path.expanduser(path), "a") as f:
            f.write(json.dumps(data) + "\n")
        return True
    except IOError as e:
        logger.error(f"Could not append to {path}: {e}")
        return False


def _read_tsv(path: str) -> list[dict]:
    """Safely read TSV file, return list of dicts with column headers as keys."""
    try:
        rows = []
        with open(os.path.expanduser(path), "r") as f:
            lines = f.readlines()
            if not lines:
                return rows

            headers = [h.strip() for h in lines[0].split("\t")]
            for line in lines[1:]:
                line = line.strip()
                if line:
                    values = [v.strip() for v in line.split("\t")]
                    row = dict(zip(headers, values))
                    rows.append(row)
        return rows
    except (FileNotFoundError, IOError) as e:
        logger.debug(f"Could not read {path}: {e}")
        return []


def _append_to_markdown(path: str, content: str) -> bool:
    """Safely append content to markdown file."""
    try:
        _ensure_memory_dir()
        with open(os.path.expanduser(path), "a") as f:
            f.write(content + "\n")
        return True
    except IOError as e:
        logger.error(f"Could not append to {path}: {e}")
        return False


def _extract_themes(text: str, max_words: int = 100) -> list[str]:
    """Extract significant words from text as themes. Simple heuristic."""
    words = text.lower().split()
    themes = []
    for word in words[:max_words]:
        # Remove punctuation
        word = word.strip(",.!?;:'\"")
        if word and word not in STOPWORDS and len(word) > 2:
            themes.append(word)
    return themes


def _days_ago(timestamp_str: str) -> Optional[int]:
    """Calculate days between ISO timestamp and now."""
    dt = _parse_iso(timestamp_str)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    delta = now - dt
    return delta.days


# ============================================================================
# 1. SELF-AWARENESS LAYER (Beatrice archetype)
# ============================================================================


def run_self_reflection() -> dict:
    """
    Weekly task: synthesize growth by reading synthesis results, overnight insights,
    and session threads. Return structured reflection and save to disk.

    Returns:
        {
            "growth_note": str,
            "new_synthesis_count": int,
            "top_insight": str,
            "saved": bool
        }
    """
    _ensure_memory_dir()

    result = {
        "growth_note": "",
        "new_synthesis_count": 0,
        "top_insight": "",
        "saved": False,
    }

    # Read synthesis results from last 7 days
    synthesis = _read_tsv(SYNTHESIS_RESULTS_PATH)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=SELF_REFLECTION_WINDOW_DAYS)

    recent_synthesis = []
    top_insight = None
    top_score = -1.0

    for row in synthesis:
        try:
            ts = _parse_iso(row.get("timestamp", ""))
            if ts and ts >= cutoff:
                recent_synthesis.append(row)
                # Find highest-scored synthesis
                try:
                    score = float(row.get("score", 0))
                    if score > top_score:
                        top_score = score
                        top_insight = row.get("title", "")
                except ValueError:
                    pass
        except (KeyError, TypeError):
            pass

    result["new_synthesis_count"] = len(recent_synthesis)

    # Read overnight insights
    overnight = _read_json(OVERNIGHT_STATE_PATH)
    overnight_insights = overnight.get("insights", [])

    # Read session threads
    session_data = _read_json(SESSION_THREADS_PATH)
    recent_threads = session_data.get("recent", [])

    # Build growth note
    parts = []

    if result["new_synthesis_count"] > 0:
        parts.append(
            f"Created {result['new_synthesis_count']} new synthesis notes this week."
        )

    if top_insight:
        parts.append(f"Most significant connection: {top_insight}")
        result["top_insight"] = top_insight

    if overnight_insights:
        parts.append(
            f"Overnight insights revealed {len(overnight_insights)} new thread(s)."
        )

    if recent_threads:
        parts.append(f"Explored {len(recent_threads)} conversation thread(s).")

    if not parts:
        parts.append("Synthesis steady. Waiting for next insight.")

    growth_note = " ".join(parts)
    result["growth_note"] = growth_note

    # Save to self_awareness.md
    timestamp = _now_iso()
    markdown_entry = f"\n## {timestamp}\n\n{growth_note}\n"

    if _append_to_markdown(SELF_AWARENESS_PATH, markdown_entry):
        result["saved"] = True
        logger.info(f"Saved self-reflection: {growth_note}")

    return result


def get_recent_growth_note() -> Optional[str]:
    """
    Return latest growth note if it's less than 3 days old.
    Parse self_awareness.md looking for the most recent entry.
    """
    try:
        with open(os.path.expanduser(SELF_AWARENESS_PATH), "r") as f:
            content = f.read()
    except FileNotFoundError:
        return None

    # Parse markdown: look for ## timestamp entries
    lines = content.split("\n")
    entries = []
    current_entry = None
    current_ts = None

    for line in lines:
        if line.startswith("## "):
            if current_entry:
                entries.append((current_ts, current_entry))
            current_ts = line[3:].strip()
            current_entry = []
        elif current_entry is not None:
            if line.strip():
                current_entry.append(line)

    if current_entry:
        entries.append((current_ts, current_entry))

    if not entries:
        return None

    # Get most recent entry
    latest_ts_str, latest_lines = entries[-1]

    # Check if < 3 days old
    days = _days_ago(latest_ts_str)
    if days is None or days >= 3:
        return None

    return "\n".join(latest_lines).strip()


def build_self_awareness_context() -> str:
    """
    Build brief context string to inject into system prompt if there's a recent growth note.
    Returns empty string if no recent note.

    Example: "Alicia has been thinking about X"
    """
    note = get_recent_growth_note()
    if not note:
        return ""

    # Extract first insight from note
    first_sentence = note.split(".")[0].strip()
    if not first_sentence:
        return ""

    return f"Alicia has been working on: {first_sentence}"


# ============================================================================
# 2. DAIMON'S WARNING (pattern detection)
# ============================================================================


def detect_avoidance_pattern(
    message: str, session_threads_path: str = "~/alicia/memory/session_threads.json"
) -> Optional[dict]:
    """
    Detect if the current message's themes appear 3+ times in recent threads
    but with shallow depth (< 200 words each time).

    Returns:
        None if no pattern detected
        {
            "theme": str,
            "occurrences": int,
            "avg_depth": int,
            "warning": str
        }
        if pattern found
    """
    # Extract themes from current message
    themes = _extract_themes(message)
    if not themes:
        return None

    # Read session threads from last 30 days
    session_data = _read_json(session_threads_path)
    threads = session_data.get("threads", [])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    recent_threads = []

    for thread in threads:
        try:
            ts = _parse_iso(thread.get("timestamp", ""))
            if ts and ts >= cutoff:
                recent_threads.append(thread)
        except (KeyError, TypeError):
            pass

    if not recent_threads:
        return None

    # Count theme occurrences in recent threads
    theme_occurrences = {}

    for theme in themes:
        count = 0
        depths = []

        for thread in recent_threads:
            content = thread.get("content", "")
            if theme.lower() in content.lower():
                count += 1
                depths.append(len(content.split()))

        if count >= AVOIDANCE_THRESHOLD:
            avg_depth = sum(depths) // len(depths) if depths else 0

            # Check if all instances are shallow
            if all(d < SHALLOW_DEPTH_THRESHOLD for d in depths):
                theme_occurrences[theme] = {
                    "occurrences": count,
                    "avg_depth": avg_depth,
                }

    if not theme_occurrences:
        return None

    # Return the pattern with most occurrences
    best_pattern = max(
        theme_occurrences.items(), key=lambda x: x[1]["occurrences"]
    )
    theme, stats = best_pattern

    warning_text = (
        f"You've touched on {theme} {stats['occurrences']} times recently "
        f"but haven't gone deep yet. That might be where the insight is."
    )

    return {
        "theme": theme,
        "occurrences": stats["occurrences"],
        "avg_depth": stats["avg_depth"],
        "warning": warning_text,
    }


def record_depth_signal(topic: str, word_count: int, source: str) -> bool:
    """
    Record a depth signal to depth_signals.jsonl.
    Each line: {"timestamp": iso, "topic": str, "word_count": int, "source": str}
    """
    signal = {
        "timestamp": _now_iso(),
        "topic": topic,
        "word_count": word_count,
        "source": source,
    }
    return _append_json_line(DEPTH_SIGNALS_PATH, signal)


def get_daimon_warning(message: str) -> Optional[str]:
    """
    Main entry point for Daimon's Warning.
    Detects avoidance patterns and returns warning string.
    Rate-limited: max 1 warning per 24 hours.

    Returns warning string or None.
    """
    # Check rate limit
    signals = _read_json_lines(DEPTH_SIGNALS_PATH)
    if signals:
        last_signal = signals[-1]
        last_ts = _parse_iso(last_signal.get("timestamp", ""))
        if last_ts:
            now = datetime.now(timezone.utc)
            hours_since = (now - last_ts).total_seconds() / 3600
            if hours_since < DAIMON_COOLDOWN_HOURS:
                logger.debug("Daimon warning on cooldown")
                return None

    pattern = detect_avoidance_pattern(message)
    if not pattern:
        return None

    # Record this warning signal
    record_depth_signal(pattern["theme"], 0, "daimon_warning")

    return pattern["warning"]


# ============================================================================
# 3. RECIPROCAL CHALLENGE (Psyche archetype)
# ============================================================================


def find_unresolved_tension() -> Optional[dict]:
    """
    Find unresolved tensions from:
    - Synthesis results (recent entries with score 3, or high scores without resolution)
    - Contradiction reports (most recent)
    - Growth-edge reports (most recent)

    Returns:
        None if nothing found
        {
            "tension": str,
            "sources": list[str],
            "challenge_prompt": str
        }
        if found
    """
    sources = []
    tension = None

    # Read synthesis results from last 14 days
    synthesis = _read_tsv(SYNTHESIS_RESULTS_PATH)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)

    uncertain_synthesis = []
    for row in synthesis:
        try:
            ts = _parse_iso(row.get("timestamp", ""))
            if ts and ts >= cutoff:
                decision = row.get("decision", "").lower()
                score = float(row.get("score", 0))

                # Uncertain (score 3) or high score without resolution
                if (decision == "kept_uncertain") or (
                    score >= 0.7 and decision != "integrated"
                ):
                    uncertain_synthesis.append(row)
        except (KeyError, ValueError, TypeError):
            pass

    if uncertain_synthesis:
        # Pick the first uncertain one
        row = uncertain_synthesis[0]
        tension = row.get("title", "An unresolved question")
        sources.append("recent synthesis")

    # Read contradiction reports (via bridge_protocol discovery)
    try:
        report_path = get_latest_report("contradiction-report-")
        if report_path:
            with open(report_path, "r") as f:
                content = f.read()
                if "unresolved" in content.lower() or "contradiction" in content.lower():
                    sources.append("contradiction report")
                    if not tension:
                        tension = "A contradiction you've identified"
    except (FileNotFoundError, OSError):
        pass

    # Read growth-edge reports (via bridge_protocol discovery)
    try:
        report_path = get_latest_report("growth-edge-report-")
        if report_path:
            with open(report_path, "r") as f:
                content = f.read()
                sources.append("growth edge")
                if not tension:
                    tension = "A growth edge you've identified"
    except (FileNotFoundError, OSError):
        pass

    # Enhanced: Pull structured data from feedback_loop analysis coordination
    try:
        from myalicia.skills.feedback_loop import get_growth_edges_for_challenge, get_contradictions_for_challenge

        # Structured growth edges
        edges = get_growth_edges_for_challenge()
        for edge in edges[:2]:
            area = edge.get("area", "")
            if area and not tension:
                tension = area
                sources.append("growth edge detection")

        # Structured contradictions
        contradictions = get_contradictions_for_challenge()
        for c in contradictions[:2]:
            c_tension = c.get("tension", "")
            if c_tension and not tension:
                tension = c_tension
                sources.append("contradiction mining")
    except ImportError:
        pass  # feedback_loop not available
    except Exception as fl_err:
        logger.debug(f"Feedback loop challenge enrichment error: {fl_err}")

    if not tension:
        return None

    # Build invitational challenge prompt
    source_list = ", ".join(sources) if sources else "my recent work"
    challenge_prompt = (
        f"I've been working on something I can't fully resolve. {tension}. "
        f"I think your lived experience with {source_list} might bridge this. "
        f"When you have 10 minutes, want to /drive on it?"
    )

    return {
        "tension": tension,
        "sources": sources,
        "challenge_prompt": challenge_prompt,
    }


def should_send_challenge() -> bool:
    """
    Check if we should send a challenge (max 1 per week).
    Returns True if cooldown has expired or no challenge sent yet.
    """
    challenge_log = _read_json(CHALLENGE_LOG_PATH)
    last_sent = challenge_log.get("last_sent", None)

    if not last_sent:
        return True

    last_ts = _parse_iso(last_sent)
    if not last_ts:
        return True

    now = datetime.now(timezone.utc)
    days_since = (now - last_ts).days

    return days_since >= CHALLENGE_COOLDOWN_DAYS


def record_challenge_sent(tension: str) -> bool:
    """Save challenge sent timestamp to challenge_log.json."""
    challenge_log = _read_json(CHALLENGE_LOG_PATH)
    challenge_log["last_sent"] = _now_iso()
    challenge_log["last_tension"] = tension
    return _write_json(CHALLENGE_LOG_PATH, challenge_log)


def get_pending_challenge() -> Optional[str]:
    """
    If conditions are met (should_send_challenge + find_unresolved_tension),
    return the challenge prompt.
    """
    if not should_send_challenge():
        logger.debug("Challenge on cooldown")
        return None

    tension_data = find_unresolved_tension()
    if not tension_data:
        return None

    return tension_data["challenge_prompt"]


# ============================================================================
# 4. MUSUBI BOND REFLECTION (generative co-emergence)
# ============================================================================


def get_musubi_stats() -> dict:
    """
    Return raw numbers for this month:
    - synthesis_this_month
    - threads_this_month
    - walks_this_month
    - knowledge_level_change (if vault_metrics available)
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stats = {
        "synthesis_this_month": 0,
        "threads_this_month": 0,
        "walks_this_month": 0,
        "knowledge_level_change": None,
    }

    # Count synthesis notes
    synthesis = _read_tsv(SYNTHESIS_RESULTS_PATH)
    for row in synthesis:
        try:
            ts = _parse_iso(row.get("timestamp", ""))
            if ts and ts >= month_start:
                stats["synthesis_this_month"] += 1
        except (KeyError, TypeError):
            pass

    # Count session threads
    session_data = _read_json(SESSION_THREADS_PATH)
    threads = session_data.get("threads", [])
    for thread in threads:
        try:
            ts = _parse_iso(thread.get("timestamp", ""))
            if ts and ts >= month_start:
                stats["threads_this_month"] += 1
        except (KeyError, TypeError):
            pass

    # Count walk transcripts
    try:
        log_path = os.path.expanduser(LOG_DIR)
        walk_files = [f for f in os.listdir(log_path) if f.startswith("walk-") and f.endswith(".txt")]
        for walk_file in walk_files:
            # Simple heuristic: if file was modified this month
            file_path = os.path.join(log_path, walk_file)
            mtime = os.path.getmtime(file_path)
            file_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            if file_dt >= month_start:
                stats["walks_this_month"] += 1
    except (FileNotFoundError, OSError):
        pass

    # Try to read vault_metrics if available
    vault_metrics_path = os.path.join(VAULT_ROOT, "vault_metrics.json")
    try:
        metrics = _read_json(vault_metrics_path)
        # Look for knowledge_level or similar metric
        if "knowledge_level" in metrics:
            stats["knowledge_level_change"] = metrics["knowledge_level"]
    except (FileNotFoundError, KeyError):
        pass

    return stats


def build_musubi_reflection() -> Optional[str]:
    """
    Build a brief (2-3 sentence) reflection on what the pair has built together.
    Returns None if no meaningful activity this month.
    """
    stats = get_musubi_stats()

    # Check if there's meaningful activity
    total_activity = (
        stats["synthesis_this_month"]
        + stats["threads_this_month"]
        + stats["walks_this_month"]
    )

    if total_activity == 0:
        return None

    parts = []

    # Synthesis reflection
    if stats["synthesis_this_month"] > 0:
        parts.append(
            f"This month we created {stats['synthesis_this_month']} new synthesis note(s)."
        )

    # Walks reflection
    if stats["walks_this_month"] > 0:
        parts.append(
            f"{stats['walks_this_month']} came from your walk monologues — "
            f"I couldn't have bridged those without hearing you think."
        )

    # Knowledge growth
    if stats["knowledge_level_change"]:
        level = stats["knowledge_level_change"]
        parts.append(f"The {level} cluster is deepening.")
    elif stats["threads_this_month"] > 0:
        parts.append(f"We've explored {stats['threads_this_month']} conversation thread(s).")

    if not parts:
        return None

    reflection = " ".join(parts)

    # Ensure it's 2-3 sentences by checking sentence count
    sentences = reflection.split(". ")
    if len(sentences) >= 2:
        return reflection if reflection.endswith(".") else reflection + "."

    return reflection


# ============================================================================
# Public API Summary
# ============================================================================
# Self-Awareness Layer:
#   - run_self_reflection() -> dict
#   - get_recent_growth_note() -> str | None
#   - build_self_awareness_context() -> str
#
# Daimon's Warning:
#   - detect_avoidance_pattern(message, session_threads_path) -> dict | None
#   - record_depth_signal(topic, word_count, source) -> bool
#   - get_daimon_warning(message) -> str | None
#
# Reciprocal Challenge:
#   - find_unresolved_tension() -> dict | None
#   - should_send_challenge() -> bool
#   - record_challenge_sent(tension) -> bool
#   - get_pending_challenge() -> str | None
#
# Musubi Bond Reflection:
#   - build_musubi_reflection() -> str | None
#   - get_musubi_stats() -> dict
# ============================================================================
