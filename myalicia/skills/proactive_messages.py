#!/usr/bin/env python3
"""
Alicia — Proactive Messaging System

Generates contextual messages throughout the day:
- Startup: knowledge level, active threads, thought prompt
- Midday: synthesis-inspired question or connection to explore
- Evening: reflection prompt or "know the user deeper" question

Uses the vault, synthesis notes, memory, and HANDOFF.md to generate
messages that are personal, non-generic, and push the user's thinking forward.
"""

import os
import re
import random
import json
import logging
from datetime import datetime, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.proactive")

load_dotenv(os.path.expanduser("~/alicia/.env"))

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

VAULT_ROOT = str(config.vault.root)
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")
HANDOFF_PATH = os.path.join(VAULT_ROOT, "Alicia", "Bridge", "HANDOFF.md")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
RESULTS_TSV = os.path.join(VAULT_ROOT, "Alicia", "Bridge", "synthesis_results.tsv")
AUTHORS_DIR = os.path.join(VAULT_ROOT, "Authors")
ANALYSIS_INSIGHTS_PATH = os.path.expanduser("~/alicia/memory/analysis_insights.md")
ANALYTICAL_BRIEFING_PATH = os.path.expanduser("~/alicia/memory/analytical_briefing.md")

MODEL_SONNET = "claude-sonnet-4-20250514"

# ── Skill config (markdown) ──────────────────────────────────────────────────
# The companion config lives at skills/configs/proactive_messages.md. /improve
# mutates parameter values there; we must actually read them, or the config
# drifts into dead knobs (the March 2026 regression pattern).

_DEFAULT_EVENING_WEIGHTS = {
    "reflection": 0.35,
    "gratitude":  0.25,
    "tomorrow":   0.20,
    "energy_shift": 0.20,
}

# Keys must match GREETING_FORMATS exactly — the pre-2026-04 config shipped
# with "energizing"/"reflective"/"tactical", which never matched the actual
# format list (warm_short/briefing/question_only/reflection). Caught by the
# dead-config guardrail smoke test on <earlier development>.
_DEFAULT_MORNING_WEIGHTS = {
    "warm_short":    0.35,
    "briefing":      0.25,
    "question_only": 0.20,
    "reflection":    0.20,
}


def _load_template_weights(param_name: str, defaults: dict) -> dict:
    """Load a *_template_weights dict from the proactive_messages.md config.

    Config values are serialized as JSON-ish Python dict literals (both
    ``{"k": 0.3}`` and ``{'k': 0.3}`` are tolerated). Falls back to
    ``defaults`` if the config is missing, malformed, or normalises to zero.
    Every caller clones from the return, so mutating one caller's dict
    can't bleed into another's.
    """
    try:
        from myalicia.skills.skill_config import load_config, get_param
        cfg = load_config("proactive_messages") or {}
        raw = get_param(cfg, param_name, default="").strip()
        if not raw:
            return dict(defaults)
        # Tolerate single-quoted dicts from /improve's repr() output
        if "'" in raw and '"' not in raw:
            raw = raw.replace("'", '"')
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return dict(defaults)
        cleaned: dict = {}
        for k, v in parsed.items():
            try:
                fv = float(v)
                if fv > 0:
                    cleaned[str(k)] = fv
            except Exception:
                continue
        return cleaned or dict(defaults)
    except Exception as e:
        log.debug(f"template_weights load fallback ({param_name}): {e}")
        return dict(defaults)


# ── Prompt-Response Tracking ─────────────────────────────────────────────────
# Tracks which proactive message was last sent so we can measure engagement.
# When the user responds within the tracking window, we log which message type
# produced the deepest engagement. This teaches Alicia what works.

PROMPT_TRACKING_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "prompt_effectiveness.tsv")
_LAST_PROACTIVE = {
    "type": None,       # "morning" | "midday" | "evening" | "know_hector" | "synthesis_review"
    "topic": None,      # brief topic description
    "sent_at": None,    # ISO timestamp
}

def record_proactive_sent(msg_type: str, topic: str = ""):
    """Called after sending a proactive message. Sets the tracking state."""
    _LAST_PROACTIVE["type"] = msg_type
    _LAST_PROACTIVE["topic"] = topic[:100] if topic else ""
    _LAST_PROACTIVE["sent_at"] = datetime.now().isoformat()


def record_prompted_response(user_text: str, insight_score: int = 0):
    """
    Called from background_intelligence after extracting memories from a response.
    If a proactive message was sent recently (< 4 hours), logs the pairing.

    This builds a prompt_effectiveness.tsv that tracks:
    - Which message types generate the deepest engagement
    - Which topics resonate most
    - Response depth (length + insight score)
    """
    if not _LAST_PROACTIVE["type"] or not _LAST_PROACTIVE["sent_at"]:
        return

    try:
        sent_at = datetime.fromisoformat(_LAST_PROACTIVE["sent_at"])
        age_hours = (datetime.now() - sent_at).total_seconds() / 3600
        if age_hours > 4:
            return  # Response too far from prompt — not a prompted response

        # Compute engagement depth: simple heuristic from text length + extraction score
        response_len = len(user_text)
        depth = 1  # baseline
        if response_len > 200:
            depth = 2
        if response_len > 500:
            depth = 3
        if insight_score >= 4:
            depth = max(depth, 4)
        if insight_score >= 5:
            depth = 5

        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Phase 16.5 — tag with active conversation_id (default 'default').
        try:
            from myalicia.skills.conversations import current_conversation_id
            conv_id = current_conversation_id() or "default"
        except Exception:
            conv_id = "default"
        row = (
            f"{date}\t{_LAST_PROACTIVE['type']}\t{_LAST_PROACTIVE['topic']}\t"
            f"{response_len}\t{insight_score}\t{depth}\t{conv_id}\n"
        )

        # Ensure file has header — Phase 16.5 added the conversation_id column.
        # Existing rows without the 7th column are treated as 'default' on read.
        if not os.path.exists(PROMPT_TRACKING_FILE):
            with open(PROMPT_TRACKING_FILE, "w") as f:
                f.write(
                    "timestamp\tmsg_type\ttopic\tresponse_len\t"
                    "insight_score\tdepth\tconversation_id\n"
                )

        with open(PROMPT_TRACKING_FILE, "a") as f:
            f.write(row)

        # Clear tracking state after recording
        _LAST_PROACTIVE["type"] = None
        _LAST_PROACTIVE["sent_at"] = None

    except Exception:
        pass  # Non-critical tracking


# ── Reaction Awareness ────────────────────────────────────────────────────────
# When the user reacts to an Alicia message with an emoji, it's signal.
# We track the message_id of every proactive message Alicia sends,
# so when a reaction comes in, we can map it back to the message type.

REACTION_LOG_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "reaction_log.tsv")

# Maps emoji reactions to engagement depth signals
REACTION_DEPTH = {
    "🔥": 4, "❤": 4, "❤️": 4, "💯": 4, "🤯": 5,
    "👍": 2, "👏": 3, "💪": 3, "🙏": 3, "⚡": 4,
    "🤔": 3, "💡": 4, "🧠": 4, "😮": 3,
    "👎": 1, "😐": 1,
}

# Tracks recent proactive message IDs → (type, topic, timestamp)
# Kept in memory, max 20 entries (covers ~2 days of proactive messages)
_PROACTIVE_MSG_IDS: dict = {}  # {message_id: {"type": str, "topic": str, "sent_at": str}}
_MAX_TRACKED_MSGS = 20


def track_proactive_message_id(
    message_id: int,
    msg_type: str,
    topic: str = "",
    archetype: str | None = None,
):
    """Register a sent proactive message ID for reaction tracking.

    Gap 3 (2026-04-18): when an archetype flavor is embedded in the message,
    also persist the attribution to reply_index.jsonl via reaction_scorer.
    This lets reaction_scorer.score_reply_by_reaction look up the archetype
    at reaction time and call inner_life.log_archetype_attribution, which
    drives the rolling effectiveness score read by
    compute_dynamic_archetype_weights.
    """
    _PROACTIVE_MSG_IDS[message_id] = {
        "type": msg_type,
        "topic": topic[:100] if topic else "",
        "archetype": archetype or "",
        "sent_at": datetime.now().isoformat(),
    }
    # Prune old entries
    if len(_PROACTIVE_MSG_IDS) > _MAX_TRACKED_MSGS:
        oldest_key = min(_PROACTIVE_MSG_IDS, key=lambda k: _PROACTIVE_MSG_IDS[k]["sent_at"])
        del _PROACTIVE_MSG_IDS[oldest_key]

    # Persist to reply_index.jsonl (cross-session) when an archetype rode
    # on this message. reaction_scorer owns this file; we pass task_type
    # = "proactive_<msg_type>" so the signal is still distinguishable
    # from tool-driven replies. No episode_path — proactive sends don't
    # write episodes, so reaction_scorer's no_episode branch handles that
    # cleanly while still attributing the archetype.
    if archetype:
        try:
            from myalicia.skills.reaction_scorer import track_reply as _track_reply
            _track_reply(
                message_id=message_id,
                episode_path="",
                task_type=f"proactive_{msg_type}",
                archetype=archetype,
                query_excerpt=topic[:160] if topic else "",
            )
        except Exception:
            # Silent — archetype attribution is best-effort.
            pass


def handle_reaction(message_id: int, emoji: str) -> dict | None:
    """
    Process a reaction on a message. If it's a tracked proactive message,
    log it as engagement signal and return the matched info.
    Returns None if the message wasn't a tracked proactive message.
    """
    msg_info = _PROACTIVE_MSG_IDS.get(message_id)
    if not msg_info:
        return None

    depth = REACTION_DEPTH.get(emoji, 2)  # Default depth 2 for unknown emoji

    try:
        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = f"{date}\t{msg_info['type']}\t{msg_info['topic']}\t{emoji}\t{depth}\treaction\n"

        if not os.path.exists(REACTION_LOG_FILE):
            os.makedirs(os.path.dirname(REACTION_LOG_FILE), exist_ok=True)
            with open(REACTION_LOG_FILE, "w") as f:
                f.write("timestamp\tmsg_type\ttopic\temoji\tdepth\tsource\n")

        with open(REACTION_LOG_FILE, "a") as f:
            f.write(row)

        # Also write to prompt_effectiveness.tsv for unified tracking
        if not os.path.exists(PROMPT_TRACKING_FILE):
            with open(PROMPT_TRACKING_FILE, "w") as f:
                f.write("timestamp\tmsg_type\ttopic\tresponse_len\tinsight_score\tdepth\n")

        with open(PROMPT_TRACKING_FILE, "a") as f:
            f.write(f"{date}\t{msg_info['type']}\t{msg_info['topic']}\t0\t0\t{depth}\n")

        # Update adaptive category weights if it was a know_hector message
        if msg_info["type"] == "know_hector":
            try:
                _update_category_weight(msg_info["topic"], depth)
            except Exception:
                pass

        log.info(f"Reaction tracked: {emoji} (depth {depth}) on {msg_info['type']} message")
        return {"type": msg_info["type"], "topic": msg_info["topic"], "emoji": emoji, "depth": depth}

    except Exception as e:
        log.debug(f"Reaction tracking error: {e}")
        return None


# ── Surprise Moments Engine ──────────────────────────────────────────────────
# Event-driven messages that fire when something genuinely interesting happens.
# Not on a fixed schedule — triggered by vault events, synthesis discoveries,
# insight anniversaries, or connections to recent conversations.
#
# Throttled by: daily cap, minimum gap between impulses, and adaptive
# quieting on low-engagement days.

IMPULSE_STATE_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "impulse_state.json")

_DEFAULT_IMPULSE_STATE = {
    "today": None,           # Date string, resets daily
    "sent_today": 0,         # How many impulses sent today
    "last_sent_at": None,    # ISO timestamp of last impulse
    "daily_cap": 3,          # Max impulses per day (adaptive)
    "min_gap_minutes": 90,   # Minimum gap between impulses
}


def _load_impulse_state() -> dict:
    try:
        if os.path.exists(IMPULSE_STATE_FILE):
            with open(IMPULSE_STATE_FILE) as f:
                state = json.load(f)
            # Reset if new day
            today = datetime.now().strftime("%Y-%m-%d")
            if state.get("today") != today:
                state["today"] = today
                state["sent_today"] = 0
            return state
    except Exception:
        pass
    state = dict(_DEFAULT_IMPULSE_STATE)
    state["today"] = datetime.now().strftime("%Y-%m-%d")
    return state


def _save_impulse_state(state: dict):
    try:
        atomic_write_json(IMPULSE_STATE_FILE, state)
    except Exception:
        pass


def can_send_impulse() -> bool:
    """Check if an impulse message is allowed right now."""
    state = _load_impulse_state()

    # Check daily cap
    if state["sent_today"] >= state.get("daily_cap", 3):
        return False

    # Check minimum gap
    if state.get("last_sent_at"):
        try:
            last = datetime.fromisoformat(state["last_sent_at"])
            gap = (datetime.now() - last).total_seconds() / 60
            if gap < state.get("min_gap_minutes", 90):
                return False
        except Exception:
            pass

    # Don't send during sleep hours (23:00 - 06:30)
    hour = datetime.now().hour
    minute = datetime.now().minute
    if hour >= 23 or hour < 6 or (hour == 6 and minute < 30):
        return False

    return True


def record_impulse_sent():
    """Record that an impulse was sent."""
    state = _load_impulse_state()
    state["sent_today"] = state.get("sent_today", 0) + 1
    state["last_sent_at"] = datetime.now().isoformat()
    _save_impulse_state(state)


def update_impulse_cap_from_engagement():
    """
    Adaptive daily cap: look at yesterday's engagement depth in
    prompt_effectiveness.tsv. High engagement → raise cap. Low → lower it.
    Called once daily (e.g., from morning message).
    """
    state = _load_impulse_state()
    try:
        if not os.path.exists(PROMPT_TRACKING_FILE):
            return

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        depths = []
        with open(PROMPT_TRACKING_FILE) as f:
            for line in f:
                if line.startswith(yesterday):
                    parts = line.strip().split("\t")
                    if len(parts) >= 6:
                        try:
                            depths.append(int(parts[5]))
                        except ValueError:
                            pass

        if not depths:
            return  # No data, keep current cap

        avg_depth = sum(depths) / len(depths)
        response_count = len(depths)

        # Adaptive: high engagement (avg depth >= 3 AND multiple responses) → cap 4
        # Medium → cap 3, Low → cap 2
        if avg_depth >= 3 and response_count >= 2:
            state["daily_cap"] = 4
        elif avg_depth >= 2:
            state["daily_cap"] = 3
        else:
            state["daily_cap"] = 2

        _save_impulse_state(state)
    except Exception:
        pass


def get_adaptive_challenge_cooldown() -> dict:
    """
    Adaptive cooldown for Psyche challenge moments based on engagement data.

    Reads effectiveness_state.json and reaction_log.tsv to determine:
    - If challenges are landing well (high depth + response): more frequent (5 days)
    - If moderate success: weekly (7 days)
    - If not landing: less frequent (14 days)

    Returns:
        {
            "cooldown_days": int,
            "should_send_today": bool,
            "reason": str
        }
    """
    try:
        # Load effectiveness data for challenge message type
        effectiveness_path = os.path.join(MEMORY_DIR, "effectiveness_state.json")
        challenge_data = None

        if os.path.exists(effectiveness_path):
            try:
                with open(effectiveness_path) as f:
                    state = json.load(f)
                    # Look for challenge message type in the state
                    if isinstance(state, dict) and "challenge" in state:
                        challenge_data = state["challenge"]
            except Exception:
                pass

        # Determine cooldown based on challenge effectiveness
        cooldown_days = 7  # default
        reason = "using default weekly cooldown"

        if challenge_data:
            avg_depth = challenge_data.get("avg_depth", 0)
            response_rate = challenge_data.get("response_rate", 0)

            if avg_depth >= 3 and response_rate >= 0.5:
                cooldown_days = 5
                reason = f"challenges landing well (depth={avg_depth:.1f}, response={response_rate:.0%}) — increase frequency"
            elif avg_depth >= 2:
                cooldown_days = 7
                reason = f"moderate challenge effectiveness (depth={avg_depth:.1f}) — weekly"
            elif avg_depth < 2 or response_rate < 0.3:
                cooldown_days = 14
                reason = f"challenges not landing (depth={avg_depth:.1f}, response={response_rate:.0%}) — decrease frequency"

        # Check last challenge sent from reaction_log.tsv
        reaction_log_path = os.path.join(MEMORY_DIR, "reaction_log.tsv")
        last_challenge_date = None

        if os.path.exists(reaction_log_path):
            try:
                with open(reaction_log_path) as f:
                    for line in reversed(f.readlines()):
                        if "challenge" in line.lower():
                            parts = line.strip().split("\t")
                            if len(parts) >= 1:
                                try:
                                    last_challenge_date = datetime.strptime(parts[0], "%Y-%m-%d").date()
                                    break
                                except ValueError:
                                    pass
            except Exception:
                pass

        # Determine if should send today
        should_send = False
        if last_challenge_date:
            days_since = (datetime.now().date() - last_challenge_date).days
            should_send = days_since >= cooldown_days
        else:
            # No challenge ever sent, allow it
            should_send = True

        return {
            "cooldown_days": cooldown_days,
            "should_send_today": should_send,
            "reason": reason
        }

    except Exception as e:
        log.debug(f"Error in get_adaptive_challenge_cooldown: {e}")
        # Safe fallback
        return {
            "cooldown_days": 7,
            "should_send_today": True,
            "reason": "error reading data, using safe default"
        }


def generate_surprise_moment() -> str | None:
    """
    Try to generate a surprise impulse message. Returns the message text,
    or None if nothing interesting enough was found.

    Rotates through surprise types, each with its own check:
    1. Fresh synthesis connection (vault-synthesis found something relevant to recent convo)
    2. Insight anniversary (a score-5 insight from exactly N days ago)
    3. Vault serendipity (a quote or note that connects to this week's hot topics)
    4. Contradiction spark (a tension the system noticed)
    """
    if not can_send_impulse():
        return None

    # Load resonance priorities for biased selection
    resonance_titles = []
    try:
        from myalicia.skills.message_quality import get_resonance_priorities
        resonance = get_resonance_priorities()
        resonance_titles = [r["title"] for r in resonance[:5]]
    except Exception:
        pass

    # Shuffle order so it's not always the same type
    generators = [
        _surprise_fresh_synthesis,
        _surprise_insight_anniversary,
        lambda: _surprise_vault_serendipity(resonance_titles=resonance_titles),
        _surprise_contradiction_spark,
    ]
    random.shuffle(generators)

    for gen in generators:
        try:
            result = gen()
            if result:
                return result
        except Exception as e:
            log.debug(f"Surprise generator {gen.__name__} failed: {e}")
            continue

    return None  # Nothing interesting enough right now


def _surprise_fresh_synthesis() -> str | None:
    """Check if a synthesis note was created today that connects to hot topics."""
    hot_topics = _read_file(os.path.join(MEMORY_DIR, "hot_topics.md"))
    if not hot_topics:
        return None

    # Get today's synthesis notes
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(SYNTHESIS_DIR):
        return None

    today_notes = []
    for fname in os.listdir(SYNTHESIS_DIR):
        if not fname.endswith(".md"):
            continue
        fp = os.path.join(SYNTHESIS_DIR, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            if mtime.strftime("%Y-%m-%d") == today:
                content = _read_file(fp)
                today_notes.append({"title": fname.replace(".md", ""), "content": content[:500]})
        except Exception:
            continue

    if not today_notes:
        return None

    # Pick one and check relevance to hot topics
    note = random.choice(today_notes)
    hot_lower = hot_topics.lower()
    title_words = set(note["title"].lower().split())

    # Simple relevance: any word from the title appears in hot topics
    overlap = [w for w in title_words if len(w) > 4 and w in hot_lower]
    if not overlap:
        return None

    return (
        f"💡 Something just clicked in the vault.\n\n"
        f"A new synthesis note landed today: *\"{note['title']}\"*\n\n"
        f"It connects to what you've been thinking about lately. "
        f"Want me to read it to you?"
    )


def _surprise_insight_anniversary() -> str | None:
    """Check if a score-5 insight was created exactly 7, 30, or 90 days ago."""
    insights_path = os.path.join(MEMORY_DIR, "insights.md")
    if not os.path.exists(insights_path):
        return None

    today = datetime.now()
    milestones = [7, 30, 90]

    with open(insights_path, encoding="utf-8") as f:
        content = f.read()

    for line in content.split("\n"):
        if "[score:5]" not in line:
            continue
        # Try to extract date
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        if not date_match:
            continue

        try:
            insight_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            days_ago = (today - insight_date).days

            if days_ago in milestones:
                # Extract the insight text
                text_match = re.search(r'\]\s*(.+?)(?:\s*\[|$)', line)
                insight_text = text_match.group(1).strip() if text_match else line.strip()[:100]

                period = {7: "a week", 30: "a month", 90: "three months"}[days_ago]
                return (
                    f"🕰 *{period.title()} ago*, you said something that scored a 5:\n\n"
                    f"_{insight_text}_\n\n"
                    f"Still true? Or has your thinking shifted?"
                )
        except Exception:
            continue

    return None


def _surprise_vault_serendipity(resonance_titles: list = None) -> str | None:
    """Surface a random vault piece that connects to current hot topics.

    If resonance_titles are provided, boost pieces that match high-resonance notes
    by lowering the relevance threshold.
    """
    hot_topics = _read_file(os.path.join(MEMORY_DIR, "hot_topics.md"))
    if not hot_topics:
        return None

    # Try a random quote or writing piece
    piece = _get_random_vault_content("quote")
    if not piece or not piece.get("content"):
        piece = _get_random_vault_content("writing")
    if not piece or not piece.get("content"):
        return None

    # Check loose relevance to hot topics
    content_lower = piece["content"].lower()[:500]
    hot_words = [w.strip().lower() for w in re.findall(r'[a-zA-Z]{5,}', hot_topics)]
    overlap = sum(1 for w in hot_words if w in content_lower)

    # Resonance boost — if this piece matches a high-resonance note, lower the threshold
    resonance_match = False
    if resonance_titles:
        piece_title = piece.get("title", "").lower()
        for rt in resonance_titles:
            if any(w in piece_title for w in rt.lower().split() if len(w) > 4):
                resonance_match = True
                break

    # Apply resonance-adjusted threshold
    threshold = 1 if resonance_match else 2
    if overlap < threshold:
        return None  # Not relevant enough

    title = piece.get("title", "something in your vault")
    first_line = piece["content"].strip().split("\n")[0][:150]

    return (
        f"📜 Your vault just surfaced something that connects to what you've been exploring:\n\n"
        f"*{title}*\n"
        f"_{first_line}_\n\n"
        f"Want me to read the whole thing?"
    )


def _surprise_contradiction_spark() -> str | None:
    """Check if recent analysis found a productive contradiction worth surfacing."""
    analysis = _read_file(ANALYSIS_INSIGHTS_PATH)
    if not analysis:
        return None

    # Look for contradiction_mining insights from recent days
    lines = analysis.strip().split("\n")
    for line in reversed(lines):
        if "contradiction" in line.lower() or "tension" in line.lower():
            # Extract the insight text after any prefix
            text = re.sub(r'^.*?:\s*', '', line).strip()
            if len(text) > 30:
                return (
                    f"⚡ A tension worth sitting with:\n\n"
                    f"_{text}_\n\n"
                    f"Does that land differently at this time of day?"
                )

    return None


# ── Daily Rhythm Tracker ──────────────────────────────────────────────────────
# Tracks the user's interaction patterns throughout the day: message count,
# voice vs text ratio, timing, energy. This becomes context for all proactive
# messages — "You were quiet today" vs "Three voice notes before noon."

RHYTHM_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "daily_rhythm.json")

_DEFAULT_RHYTHM = {
    "date": None,
    "messages": 0,
    "voice_messages": 0,
    "text_messages": 0,
    "total_words": 0,
    "first_message_hour": None,
    "last_message_hour": None,
    "hours_active": [],         # list of hours with activity
    "high_depth_count": 0,      # messages that generated depth 4-5 insights
    "reactions_sent": 0,        # emoji reactions the user sent
}


def _load_rhythm() -> dict:
    try:
        if os.path.exists(RHYTHM_FILE):
            with open(RHYTHM_FILE) as f:
                data = json.load(f)
            today = datetime.now().strftime("%Y-%m-%d")
            if data.get("date") == today:
                return data
            # Save yesterday's data before resetting
            data["_yesterday"] = {k: v for k, v in data.items() if k != "_yesterday"}
            # Reset for new day
            new = dict(_DEFAULT_RHYTHM)
            new["date"] = today
            new["_yesterday"] = data["_yesterday"]
            return new
    except Exception:
        pass
    rhythm = dict(_DEFAULT_RHYTHM)
    rhythm["date"] = datetime.now().strftime("%Y-%m-%d")
    return rhythm


def _save_rhythm(rhythm: dict):
    try:
        atomic_write_json(RHYTHM_FILE, rhythm)
    except Exception:
        pass


def record_message_rhythm(is_voice: bool = False, word_count: int = 0, depth: int = 0):
    """Called from alicia.py after each user message to track daily rhythm."""
    rhythm = _load_rhythm()
    rhythm["messages"] = rhythm.get("messages", 0) + 1
    if is_voice:
        rhythm["voice_messages"] = rhythm.get("voice_messages", 0) + 1
    else:
        rhythm["text_messages"] = rhythm.get("text_messages", 0) + 1
    rhythm["total_words"] = rhythm.get("total_words", 0) + word_count

    hour = datetime.now().hour
    if rhythm.get("first_message_hour") is None:
        rhythm["first_message_hour"] = hour
    rhythm["last_message_hour"] = hour

    hours = rhythm.get("hours_active", [])
    if hour not in hours:
        hours.append(hour)
    rhythm["hours_active"] = hours

    if depth >= 4:
        rhythm["high_depth_count"] = rhythm.get("high_depth_count", 0) + 1

    _save_rhythm(rhythm)


def get_rhythm_summary() -> dict:
    """Get today's rhythm data for use in proactive messages."""
    return _load_rhythm()


def get_yesterday_rhythm() -> dict | None:
    """Get yesterday's rhythm for morning greeting context."""
    rhythm = _load_rhythm()
    return rhythm.get("_yesterday")


def describe_day_texture() -> str:
    """
    Generate a natural-language description of today's interaction pattern.
    Used by evening messages to reference how the day actually felt.
    """
    rhythm = get_rhythm_summary()
    msgs = rhythm.get("messages", 0)
    voice = rhythm.get("voice_messages", 0)
    text = rhythm.get("text_messages", 0)
    words = rhythm.get("total_words", 0)
    hours = rhythm.get("hours_active", [])
    high_depth = rhythm.get("high_depth_count", 0)
    first_hour = rhythm.get("first_message_hour")
    last_hour = rhythm.get("last_message_hour")

    if msgs == 0:
        return "quiet — no messages today"

    parts = []

    # Volume description
    if msgs <= 2:
        parts.append("a quiet day")
    elif msgs <= 5:
        parts.append("a few exchanges")
    elif msgs <= 10:
        parts.append("a solid conversation day")
    else:
        parts.append("a deeply active day")

    # Voice vs text
    if voice > 0 and text == 0:
        parts.append("all voice")
    elif voice > text:
        parts.append("mostly voice")
    elif voice > 0:
        voice_pct = round(voice / msgs * 100)
        parts.append(f"{voice_pct}% voice")

    # Timing pattern
    if first_hour is not None and last_hour is not None:
        if first_hour < 8:
            parts.append("started early")
        elif first_hour > 12:
            parts.append("came alive in the afternoon")
        if len(hours) >= 6:
            parts.append("spread across the whole day")

    # Depth
    if high_depth >= 3:
        parts.append("several deep exchanges")
    elif high_depth >= 1:
        parts.append("at least one deep moment")

    return " — ".join(parts)


def describe_yesterday_texture() -> str:
    """Natural-language description of yesterday's pattern for morning greeting."""
    yesterday = get_yesterday_rhythm()
    if not yesterday:
        return ""

    msgs = yesterday.get("messages", 0)
    voice = yesterday.get("voice_messages", 0)
    high_depth = yesterday.get("high_depth_count", 0)

    if msgs == 0:
        return "You were quiet yesterday."
    elif msgs <= 2:
        return "Yesterday was a light day — just a couple of exchanges."
    elif voice > msgs * 0.6:
        return "You were in a voice mood yesterday — lots of thinking out loud."
    elif high_depth >= 2:
        return "Yesterday had some real depth to it."
    elif msgs >= 8:
        return "Yesterday was lively — we covered a lot of ground."
    else:
        return ""


def describe_yesterday_signal() -> str:
    """
    One-line natural summary of yesterday's feedback valence from
    daily_signal. Complements describe_yesterday_texture (volume/voice)
    with reaction/episode reinforcement direction. Empty if nothing
    to say.
    """
    try:
        from myalicia.skills.daily_signal import get_yesterday_signal
        y = get_yesterday_signal() or {}
        if not y:
            return ""
        r = y.get("reactions", {}) or {}
        pos = r.get("positive", 0)
        neg = r.get("negative", 0)
        e = y.get("episodes", {}) or {}
        rewarded = e.get("rewarded", 0)
        punished = e.get("punished", 0)

        if pos + neg + rewarded + punished == 0:
            return ""
        if pos >= 3 and neg == 0 and punished == 0:
            return "Yesterday landed well — a lot of reinforcement."
        if neg >= 2 or punished >= 2:
            return "Yesterday had some friction — worth noticing what missed."
        if pos >= 2 and rewarded >= 1:
            return "Yesterday had a few sparks worth carrying forward."
        return ""
    except Exception:
        return ""


def describe_today_signal() -> str:
    """
    One-line feedback pulse for today so far. Used by evening reflection
    to reference how the day rhymed, not just volume.
    """
    try:
        from myalicia.skills.daily_signal import get_signal_summary
        return get_signal_summary("today") or ""
    except Exception:
        return ""


# ── Greeting Format Variations ────────────────────────────────────────────────
# Morning greetings rotate through different formats to feel alive,
# not like the same template every day.

GREETING_FORMATS = [
    "warm_short",      # Short and warm — 2-3 lines, one question
    "briefing",        # Mini-briefing — vault state + growth edge + question
    "question_only",   # Just a provocative question, no preamble
    "reflection",      # Yesterday callback + a thought to carry forward
]


def _pick_greeting_format() -> str:
    """Pick a greeting format, weighted by day-of-week and yesterday's activity.

    Context branches (Monday / after-quiet / after-deep) are hardcoded — they
    respond to observable day-shape signals that /improve shouldn't be
    tuning blindly. The default branch reads morning_template_weights from
    the skill config, so /improve can legitimately steer the everyday feel
    of Alicia's greetings.
    """
    yesterday = get_yesterday_rhythm()
    day = datetime.now().weekday()

    # Monday: briefing-style (start of week)
    if day == 0:
        return random.choices(
            GREETING_FORMATS,
            weights=[0.1, 0.5, 0.1, 0.3],
        )[0]

    # After a quiet day: warm and short
    if yesterday and yesterday.get("messages", 0) <= 2:
        return random.choices(
            GREETING_FORMATS,
            weights=[0.5, 0.1, 0.2, 0.2],
        )[0]

    # After a deep day: reflection format
    if yesterday and yesterday.get("high_depth_count", 0) >= 2:
        return random.choices(
            GREETING_FORMATS,
            weights=[0.1, 0.2, 0.2, 0.5],
        )[0]

    # Default: config-driven so /improve can steer the everyday feel
    weights_map = _load_template_weights("morning_template_weights",
                                          _DEFAULT_MORNING_WEIGHTS)
    usable = [(f, weights_map.get(f, 0.0)) for f in GREETING_FORMATS
              if weights_map.get(f, 0.0) > 0]
    if not usable:
        # Fallback to the historical default vector
        return random.choices(GREETING_FORMATS,
                              weights=[0.35, 0.25, 0.2, 0.2])[0]
    names, ws = zip(*usable)
    return random.choices(names, weights=ws, k=1)[0]


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _get_active_threads() -> list:
    """Extract active threads from HANDOFF.md."""
    handoff = _read_file(HANDOFF_PATH)
    threads = []
    in_threads = False
    for line in handoff.split("\n"):
        if "## Active Threads" in line:
            in_threads = True
            continue
        if in_threads and line.startswith("## "):
            break
        if in_threads and line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            # Extract the bold thread name
            match = re.search(r"\*\*(.+?)\*\*", line)
            if match:
                threads.append(match.group(1))
    return threads


def _get_recent_synthesis_titles(n: int = 5) -> list:
    """Get the most recent synthesis note titles."""
    if not os.path.exists(SYNTHESIS_DIR):
        return []
    files = []
    for f in os.listdir(SYNTHESIS_DIR):
        if f.endswith(".md"):
            fp = os.path.join(SYNTHESIS_DIR, f)
            files.append((os.path.getmtime(fp), f.replace(".md", "")))
    files.sort(reverse=True)
    return [title for _, title in files[:n]]


def _get_random_vault_content(source_type: str = "any") -> dict:
    """
    Pick a random piece of vault content to inspire a question.
    Returns dict with 'title', 'content', 'source_type', 'path'.
    """
    candidates = []

    if source_type in ("any", "writing"):
        writing_dir = os.path.join(VAULT_ROOT, "writing")
        if os.path.exists(writing_dir):
            for f in os.listdir(writing_dir):
                if f.endswith(".md"):
                    candidates.append(("writing", os.path.join(writing_dir, f)))

    if source_type in ("any", "quotes"):
        quotes_dir = os.path.join(VAULT_ROOT, "Quotes")
        if os.path.exists(quotes_dir):
            for f in os.listdir(quotes_dir):
                if f.endswith(".md"):
                    candidates.append(("quote", os.path.join(quotes_dir, f)))

    if source_type in ("any", "synthesis"):
        if os.path.exists(SYNTHESIS_DIR):
            for f in os.listdir(SYNTHESIS_DIR):
                if f.endswith(".md"):
                    candidates.append(("synthesis", os.path.join(SYNTHESIS_DIR, f)))

    if source_type in ("any", "concept"):
        # Root-level concept notes
        if os.path.exists(VAULT_ROOT):
            for f in os.listdir(VAULT_ROOT):
                fp = os.path.join(VAULT_ROOT, f)
                if f.endswith(".md") and os.path.isfile(fp):
                    content = _read_file(fp)
                    if len(content.strip()) > 50:
                        candidates.append(("concept", fp))

    if not candidates:
        return None

    source_type, path = random.choice(candidates)
    content = _read_file(path)
    title = os.path.basename(path).replace(".md", "")
    return {
        "title": title,
        "content": content[:800],
        "source_type": source_type,
        "path": path,
    }


def _get_analysis_insight() -> str:
    """
    Read the freshest insight from analysis_insights.md.
    This file is written by Cowork scheduled tasks (contradiction mining,
    temporal analysis, growth edges, dialogue depth) and bridges their
    output into Alicia's proactive messages.

    Format of analysis_insights.md:
    ---
    ## [timestamp] [analysis_type]
    [insight text — 1-3 sentences]
    ---

    Returns the most recent insight, or empty string if none/stale.
    """
    content = _read_file(ANALYSIS_INSIGHTS_PATH)
    if not content or len(content.strip()) < 20:
        return ""

    # Parse sections separated by ---
    sections = [s.strip() for s in content.split("---") if s.strip()]
    if not sections:
        return ""

    # Take the last (most recent) section
    latest = sections[-1]

    # Check freshness — only use insights from last 48 hours
    try:
        # Extract timestamp from first line: ## 2026-04-11T14:00 contradiction_mining
        first_line = latest.split("\n")[0]
        ts_match = re.search(r"(\d{4}-\d{2}-\d{2})", first_line)
        if ts_match:
            insight_date = datetime.strptime(ts_match.group(1), "%Y-%m-%d")
            age_hours = (datetime.now() - insight_date).total_seconds() / 3600
            if age_hours > 48:
                return ""  # Stale insight, skip
    except Exception:
        pass  # If we can't parse date, use the insight anyway

    # Extract the insight text (skip the header line)
    lines = latest.split("\n")
    insight_lines = [l for l in lines[1:] if l.strip() and not l.startswith("##")]
    if not insight_lines:
        return ""

    return " ".join(insight_lines).strip()


def _get_briefing_section(section_name: str) -> str:
    """
    Read a specific section from the analytical briefing.
    The briefing is a structured file written weekly by Cowork that contains:
    - Most Alive Tension
    - Active Growth Edge
    - Depth Trend
    - Suggested Prompts
    - Hot Topics This Week
    - Message Effectiveness

    Returns the section content, or empty string if not found/stale.
    """
    content = _read_file(ANALYTICAL_BRIEFING_PATH)
    if not content or len(content.strip()) < 50:
        return ""

    # Check freshness — only use briefings from last 10 days
    try:
        first_line = content.split("\n")[0]
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", first_line)
        if date_match:
            briefing_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            age_days = (datetime.now() - briefing_date).days
            if age_days > 10:
                return ""
    except Exception:
        pass

    # Find the requested section
    lines = content.split("\n")
    capturing = False
    section_lines = []
    for line in lines:
        if line.startswith("## ") and section_name.lower() in line.lower():
            capturing = True
            continue
        elif line.startswith("## ") and capturing:
            break  # Hit next section
        elif capturing and line.strip():
            section_lines.append(line.strip())

    return " ".join(section_lines).strip() if section_lines else ""


def _get_suggested_prompt() -> str:
    """
    Get a suggested prompt from the analytical briefing.
    These are specific questions crafted from the analysis reports.
    Returns one random prompt, or empty string.
    """
    prompts_text = _get_briefing_section("Suggested Prompts")
    if not prompts_text:
        return ""

    # Parse bullet points
    prompts = [p.strip().lstrip("- ") for p in prompts_text.split("- ") if p.strip()]
    if not prompts:
        return ""

    return random.choice(prompts)


def _get_pending_telegram_items() -> list:
    """Get pending Telegram items from HANDOFF.md."""
    handoff = _read_file(HANDOFF_PATH)
    items = []
    in_telegram = False
    for line in handoff.split("\n"):
        if "## Pending for Telegram" in line:
            in_telegram = True
            continue
        if in_telegram and line.startswith("## "):
            break
        if in_telegram and "[ ]" in line:
            # Strip the checkbox
            item = re.sub(r"- \[ \] ", "", line).strip()
            if item:
                items.append(item)
    return items


# ── Startup Message ──────────────────────────────────────────────────────────

def build_startup_stats() -> str:
    """
    Build the full knowledge dashboard startup message.
    Includes: level, all metrics, progress bars, new synapses, unbridged pairs,
    active threads, and pending actions.
    """
    from myalicia.skills.vault_metrics import compute_all_metrics, format_knowledge_dashboard

    try:
        metrics = compute_all_metrics()
        dashboard = format_knowledge_dashboard(metrics)
    except Exception:
        dashboard = "🌅 Knowledge dashboard unavailable — check vault paths."

    threads = _get_active_threads()
    pending = _get_pending_telegram_items()

    lines = ["🌅 *Alicia is online.*\n"]
    lines.append(dashboard)

    # Active threads — compact
    if threads:
        lines.append(f"\n*Active threads:*")
        for t in threads[:4]:
            lines.append(f"  · {t}")

    # One pending action if available
    if pending:
        lines.append(f"\n📌 _{pending[0]}_")

    # Memento-Skills: surface any stubs the skill_author drafted overnight
    # so the user can keep, edit, or trash them in one tap. Fail silent if
    # the skill isn't loaded — never block the morning message.
    try:
        from myalicia.skills.skill_author import get_pending_stubs_summary
        stubs_summary = get_pending_stubs_summary()
        if stubs_summary:
            lines.append("")
            lines.append(stubs_summary)
    except Exception:
        pass

    # SSGM: surface a one-line memory audit headline if rules look stale
    # or got auto-deprecated overnight.
    try:
        from myalicia.skills.memory_audit import get_audit_summary_for_proactive
        audit_line = get_audit_summary_for_proactive()
        if audit_line:
            lines.append("")
            lines.append(audit_line)
    except Exception:
        pass

    return "\n".join(lines)


def _sanitize_for_telegram_markdown(text: str) -> str:
    """Escape characters that break Telegram Markdown V1 parsing.
    Underscores inside words break italic, unmatched * breaks bold."""
    # Replace underscores that aren't at word boundaries (mid-word underscores)
    text = re.sub(r'(?<=\w)_(?=\w)', '-', text)
    return text


def _should_include_thinker() -> bool:
    """Return True 25% of the time to conditionally include thinker intro."""
    return random.random() < 0.25


def get_thinker_introduction() -> str:
    """
    Scan the Authors/ folder, pick a random author .md file,
    read the first 300 chars, and return a brief one-line intro.
    Returns empty string if anything fails.
    """
    if not os.path.exists(AUTHORS_DIR):
        return ""

    try:
        # Get all .md files in Authors folder
        author_files = [
            f for f in os.listdir(AUTHORS_DIR)
            if f.endswith(".md")
        ]

        if not author_files:
            return ""

        # Pick a random author file
        random_author = random.choice(author_files)
        author_path = os.path.join(AUTHORS_DIR, random_author)

        # Read first 300 chars
        with open(author_path, encoding="utf-8") as f:
            content = f.read(300)

        # Extract author name from filename
        author_name = random_author.replace(".md", "")

        # Look for the first meaningful concept/idea in the content
        # Remove markdown headers and extract the first non-empty line after title
        lines = content.split("\n")
        core_idea = ""
        for line in lines[1:]:  # Skip first line (usually title)
            line = line.strip()
            if line and not line.startswith("#"):
                # Take first 80 chars of substantive content
                core_idea = line[:80]
                break

        if not core_idea:
            core_idea = content[50:130].strip()

        # Format as a one-line intro
        intro = f"Been thinking about {author_name} — {core_idea}"

        return intro

    except Exception:
        return ""


def build_startup_greeting() -> str:
    """
    Build the greeting + provocation startup message.
    Varies format based on day, yesterday's rhythm, and randomness.
    Formats: warm_short, briefing, question_only, reflection.
    """
    fmt = _pick_greeting_format()
    log.info(f"Morning greeting format: {fmt}")

    try:
        if fmt == "warm_short":
            return _greeting_warm_short()
        elif fmt == "briefing":
            return _greeting_briefing()
        elif fmt == "question_only":
            return _greeting_question_only()
        elif fmt == "reflection":
            return _greeting_reflection()
    except Exception as e:
        log.warning(f"Greeting format {fmt} failed: {e}")

    # Fallback
    return _greeting_warm_short()


def _greeting_warm_short() -> str:
    """Short and warm — 2-3 lines, one thought prompt. Feels like a friend."""
    prompt = _generate_thought_prompt()
    yesterday_text = describe_yesterday_texture()
    # Gap 4: fold in yesterday's feedback valence if we have a clean line.
    # Prefer it over the volume-only texture when both are present and
    # the signal has something substantive to say.
    yesterday_signal = describe_yesterday_signal()
    if yesterday_signal:
        yesterday_text = yesterday_signal

    parts = []
    if yesterday_text:
        parts.append(f"_{yesterday_text}_")
    if prompt:
        prompt = _sanitize_for_telegram_markdown(prompt)
        parts.append(f"💭 _{prompt}_")
    parts.append(f"Here when you're ready, {USER_NAME}.")
    return "\n\n".join(parts)


def _greeting_briefing() -> str:
    """Mini-briefing — vault state, growth edge, and a question. Monday energy."""
    message_parts = []

    # Growth edge or tension from analytical briefing
    growth_edge = _get_briefing_section("Active Growth Edge")
    tension = _get_briefing_section("Most Alive Tension")
    if growth_edge or tension:
        briefing_text = growth_edge or tension
        briefing_text = _sanitize_for_telegram_markdown(briefing_text[:200])
        message_parts.append(f"🔬 _{briefing_text}_")
    else:
        analysis = _get_analysis_insight()
        if analysis:
            analysis = _sanitize_for_telegram_markdown(analysis)
            message_parts.append(f"🔬 _{analysis}_")

    # Thought prompt
    prompt = _generate_thought_prompt()
    if prompt:
        prompt = _sanitize_for_telegram_markdown(prompt)
        message_parts.append(f"💭 _{prompt}_")

    # Thinker intro sometimes
    if _should_include_thinker():
        thinker_intro = get_thinker_introduction()
        if thinker_intro:
            message_parts.append(thinker_intro)

    message_parts.append(f"Ready to think with you, {USER_NAME}.")
    return "\n\n".join(message_parts)


def _greeting_question_only() -> str:
    """Just a provocative question. No preamble, no dashboard. Sharp."""
    prompt = _generate_thought_prompt()
    if prompt:
        prompt = _sanitize_for_telegram_markdown(prompt)
        return f"💭 _{prompt}_"

    # Fallback: use a vault resurface
    content = _get_random_vault_content("synthesis")
    if content and content.get("title"):
        title = _sanitize_for_telegram_markdown(content["title"][:80])
        return f"💭 _Your vault has a note called \"{title}.\" Is that still what you believe?_"

    return "💭 _What's the one question you're circling right now that you haven't quite named?_"


def _greeting_reflection() -> str:
    """Yesterday callback + a thought to carry forward. Continuity-focused."""
    yesterday_text = describe_yesterday_texture()
    prompt = _generate_thought_prompt()

    parts = []
    if yesterday_text:
        parts.append(f"_{yesterday_text}_")

    # Try to reference something specific from yesterday via hot topics
    hot = _read_file(os.path.join(MEMORY_DIR, "hot_topics.md"))
    if hot:
        lines = [l for l in hot.strip().split("\n") if l.startswith("- (")]
        if lines:
            latest = lines[-1]
            # Extract the insight text after the metadata
            topic_match = re.search(r'\]\s*(.+)', latest)
            if topic_match:
                topic = _sanitize_for_telegram_markdown(topic_match.group(1).strip()[:120])
                parts.append(f"Something you've been circling: _{topic}_")

    if prompt:
        prompt = _sanitize_for_telegram_markdown(prompt)
        parts.append(f"💭 _{prompt}_")

    if not parts:
        parts.append("💭 _What's carrying over from yesterday that wants more attention?_")

    return "\n\n".join(parts)


def build_startup_message() -> str:
    """
    Legacy combined startup message (kept for compatibility).
    Use build_startup_stats() + build_startup_greeting() for split delivery.
    """
    stats = build_startup_stats()
    greeting = build_startup_greeting()
    return f"{stats}\n\n{greeting}"


def _generate_thought_prompt() -> str:
    """Generate a thought-provoking question from recent vault content."""
    # Try a recent synthesis note first
    content = _get_random_vault_content("synthesis")
    if not content:
        content = _get_random_vault_content("any")
    if not content:
        return "What's the most interesting tension you've noticed this week?"

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"""Given this note from the user's vault:

Title: {content['title']}
Content: {content['content'][:400]}

Generate ONE short, provocative question (max 15 words) that would make the user think deeper about this idea. The question should connect to his daily life or current work. No generic self-help — be specific to the content.

Return ONLY the question, nothing else."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return f"What would change if you applied \"{content['title'][:50]}\" to your work today?"
        return response.content[0].text.strip().strip('"')
    except Exception:
        return f"What would change if you applied \"{content['title'][:50]}\" to your work today?"


# ── Synthesis Quality Feedback ────────────────────────────────────────────────

SYNTHESIS_FEEDBACK_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "synthesis_feedback.tsv")

def _synthesis_review() -> str:
    """
    Surface a synthesis note and ask the user if the connection resonates.
    This is the human feedback loop for synthesis quality — the most
    valuable calibration signal the vault system can get.

    Returns a Telegram message, or empty string if no suitable note found.
    """
    titles = _get_recent_synthesis_titles(20)
    if not titles:
        return ""

    # Pick a note we haven't recently asked about
    asked = set()
    if os.path.exists(SYNTHESIS_FEEDBACK_FILE):
        try:
            with open(SYNTHESIS_FEEDBACK_FILE) as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        asked.add(parts[1])
        except Exception:
            pass

    candidates = [t for t in titles if t not in asked]
    if not candidates:
        candidates = titles  # cycle through again if all have been asked

    title = random.choice(candidates)
    fp = os.path.join(SYNTHESIS_DIR, f"{title}.md")
    content = _read_file(fp)
    if not content:
        return ""

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia. You want to check if a synthesis note in the user's vault actually resonates with him. Present the core claim in 2 sentences, then ask one direct question: does this connection feel true?

Synthesis note title: {title}
Content: {content[:600]}

Write a SHORT Telegram message (4 lines max):
1. Present the note's core insight in plain language (2 sentences max)
2. Ask directly: does this resonate, feel forced, or is something missing?

Start with 🔬. Use Telegram markdown. Be direct — not cheesy, not academic."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return ""

        # Log that we asked about this note (so we don't repeat soon)
        try:
            date = datetime.now().strftime("%Y-%m-%d %H:%M")
            if not os.path.exists(SYNTHESIS_FEEDBACK_FILE):
                with open(SYNTHESIS_FEEDBACK_FILE, "w") as f:
                    f.write("timestamp\tnote_title\tresponse\n")
            with open(SYNTHESIS_FEEDBACK_FILE, "a") as f:
                f.write(f"{date}\t{title}\tpending\n")
        except Exception:
            pass

        return response.content[0].text.strip()
    except Exception:
        return ""


# ── Podcast Follow-Up Loop ────────────────────────────────────────────────────

PODCAST_DIR = os.path.join(VAULT_ROOT, "Wisdom", "Podcasts")
PODCAST_FOLLOWUP_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "podcast_followups.json")

def _podcast_followup() -> str:
    """
    Check if there's a recent podcast episode (< 5 days old) that hasn't been
    followed up on. If so, surface the central tension and ask if it landed.

    This closes the podcast feedback loop — turning fire-and-forget episodes
    into conversation seeds that feed back into resonance tracking.
    """
    if not os.path.exists(PODCAST_DIR):
        return ""

    # Find recent episodes (modified in last 5 days)
    now = datetime.now()
    recent_episodes = []
    try:
        for f in os.listdir(PODCAST_DIR):
            if f.endswith(".md"):
                fp = os.path.join(PODCAST_DIR, f)
                mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                age_days = (now - mtime).days
                if age_days <= 5:
                    recent_episodes.append({"file": f, "path": fp, "age_days": age_days})
    except Exception:
        return ""

    if not recent_episodes:
        return ""

    # Load follow-up state — which episodes have been asked about
    followup_state = {}
    if os.path.exists(PODCAST_FOLLOWUP_FILE):
        try:
            with open(PODCAST_FOLLOWUP_FILE) as f:
                followup_state = json.load(f)
        except Exception:
            pass

    # Find episodes not yet followed up
    unfollowed = [e for e in recent_episodes if e["file"] not in followup_state]
    if not unfollowed:
        return ""

    # Pick the oldest unfollowed episode (give the user time to listen)
    episode = sorted(unfollowed, key=lambda x: -x["age_days"])[0]
    content = _read_file(episode["path"])
    if not content or len(content) < 100:
        return ""

    # Extract title from first heading
    title = episode["file"].replace(".md", "")
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            break

    # Extract central tension from content
    tension = ""
    for line in content.split("\n"):
        if "tension" in line.lower() or "central" in line.lower():
            tension = line.strip().lstrip("*-# ")
            break
    if not tension:
        tension = content[100:300]  # Fallback: use a chunk of content

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia. A few days ago, you generated a podcast episode for the user:

Title: {title}
Central tension/content: {tension[:300]}

Write a SHORT midday Telegram message (3-4 lines) that:
1. Mentions the episode casually (not "did you listen to the episode I made")
2. Surfaces the central tension as a question worth thinking about
3. Invites the user to react — even briefly

Start with 🎙. Use Telegram markdown. Conversational, not formal."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return ""

        # Mark as followed up
        followup_state[episode["file"]] = {
            "asked_at": now.strftime("%Y-%m-%d"),
            "title": title
        }
        try:
            atomic_write_json(PODCAST_FOLLOWUP_FILE, followup_state)
        except Exception:
            pass

        return response.content[0].text.strip()
    except Exception:
        return ""


# ── Midday Nudge ─────────────────────────────────────────────────────────────

def build_midday_message() -> str:
    """
    Midday message: surface a connection, pose a question, or share a vault insight.
    Prioritizes curiosity-driven questions when available, falls back to random.
    Optionally prepends a thinker introduction (25% of the time).
    """
    # Build the main message
    main_message = ""

    # Podcast follow-up — if there's a recent unfollowed episode, prioritize it
    podcast = _podcast_followup()
    if podcast:
        record_proactive_sent("podcast_followup", podcast[:80])
        main_message = podcast

    # Phase 13.5 — Profile-driven thread-pull. ~30% of midday messages
    # pick up an unresolved thread from Sunday's the user profile (when one
    # exists, parses, and isn't on cooldown). Closes the loop between
    # weekly diarization output and mid-week proactivity.
    if not main_message and random.random() < 0.30:
        try:
            from myalicia.skills.thread_puller import (
                build_thread_pull_message,
                MIDDAY_PROBABILITY as _TP_PROB,  # imported for explicitness
            )
            tp = build_thread_pull_message()
            if tp:
                record_proactive_sent("thread_pull", tp[:80])
                main_message = tp
        except Exception as e:
            log.debug(f"thread_pull skipped: {e}")

    # Phase 17.0 — Emergent theme noticing. ~15% of midday messages raise
    # a theme that's appeared repeatedly in the user's stream without being
    # named yet (Sonnet detection in 04:00 nightly scan). Ceremonial:
    # the message is composed with high score + Beatrice archetype +
    # eligible source_kind so Phases 13.3 + 13.7 fast-path BOTH voice
    # and drawing — text + voice + drawing as one moment.
    if not main_message and random.random() < 0.15:
        try:
            from myalicia.skills.emergent_themes import build_noticing_proactive
            n = build_noticing_proactive()
            if n:
                record_proactive_sent("noticing", f"theme={n['theme'][:60]}")
                main_message = n["message"]
        except Exception as e:
            log.debug(f"emergent_theme noticing skipped: {e}")

    # Phase 19.1 — Mood-aware check-in. When the week's emotional weather
    # has trended sharply heavier (delta ≤ -0.3 in happy-vs-sad ratio
    # between halves of the 7d window), the midday rotation can fire a
    # quiet check-in instead of a normal nudge. Gate ~25% — mood signals
    # are louder + rarer than noticings. Cooldown 5 days so it can't
    # fire repeatedly on the same heavy stretch. Beatrice voice +
    # lived_surfacing so smart deciders fast-path voice + drawing the
    # same way Phase 17.0 noticings do.
    if not main_message and random.random() < 0.25:
        try:
            from myalicia.skills.emotion_model import build_mood_checkin_proactive
            mc = build_mood_checkin_proactive()
            if mc:
                record_proactive_sent(
                    "mood_checkin",
                    f"trend={mc.get('trend', '?')[:40]}",
                )
                main_message = mc["message"]
        except Exception as e:
            log.debug(f"mood_checkin skipped: {e}")

    # Phase 19.2 — Upward mood acknowledgment. Mirror of 19.1's downward
    # check-in: when the week has lifted (delta ≥ +0.3), Alicia can
    # quietly notice it. Lower gate (~15%) — lifts are the kind of
    # signal where attention itself can ruin the moment, so the system
    # should be sparing. Shares the cooldown log with 19.1 so a
    # down-then-up swing in the same week doesn't double-fire.
    if not main_message and random.random() < 0.15:
        try:
            from myalicia.skills.emotion_model import build_mood_lift_proactive
            ml = build_mood_lift_proactive()
            if ml:
                record_proactive_sent(
                    "mood_lift",
                    f"trend={ml.get('trend', '?')[:40]}",
                )
                main_message = ml["message"]
        except Exception as e:
            log.debug(f"mood_lift skipped: {e}")

    # Phase 12.2 — Gap-driven dimension question. ~20% of midday messages
    # check whether a the user-dimension has gone quiet (>14d no learnings)
    # and, if one is eligible (not on 7d cooldown), invite him back into
    # that part of his life. Closes the the user-model loop: thin
    # dimensions become the source of outbound proactivity.
    if not main_message and random.random() < 0.20:
        try:
            from myalicia.skills.dimension_research import build_dimension_targeted_question
            dq = build_dimension_targeted_question()
            if dq:
                record_proactive_sent(
                    "dimension_question", f"dim={dq['dimension']}"
                )
                main_message = dq["message"]
        except Exception as e:
            log.debug(f"dimension_question skipped: {e}")

    # Synthesis quality feedback — ~20% of midday messages ask the user to review a note
    if not main_message and random.random() < 0.2:
        review = _synthesis_review()
        if review:
            record_proactive_sent("synthesis_review", "synthesis quality check")
            main_message = review

    # Try curiosity-driven question (50% of remaining time when available)
    if not main_message and random.random() < 0.5:
        try:
            from myalicia.skills.curiosity_engine import get_curiosity_question
            curiosity_q = get_curiosity_question()
            if curiosity_q:
                main_message = _format_curiosity_message(curiosity_q)
        except ImportError:
            pass

    if not main_message:
        message_type = random.choice(["synthesis_spark", "vault_resurface", "connection_prompt"])

        if message_type == "synthesis_spark":
            main_message = _synthesis_spark()
        elif message_type == "vault_resurface":
            main_message = _vault_resurface()
        else:
            main_message = _connection_prompt()

    # Optionally prepend thinker intro
    if _should_include_thinker():
        thinker_intro = get_thinker_introduction()
        if thinker_intro:
            return f"{thinker_intro}\n\n{main_message}"

    return main_message


def _format_curiosity_message(q: dict) -> str:
    """Format a curiosity engine question for Telegram."""
    question = q.get("question", "")
    q_type = q.get("type", "")
    target = q.get("target", "")

    if q_type == "bridge_explore":
        emoji = "🔗"
        intro = "I noticed something in the vault"
    elif q_type == "gap_fill":
        emoji = "🔍"
        intro = "The vault has a gap I'm curious about"
    else:
        emoji = "💭"
        intro = "Something I've been wondering"

    # Record that we asked this curiosity question for follow-through tracking
    try:
        from myalicia.skills.curiosity_engine import record_curiosity_asked
        record_curiosity_asked(question, q_type, target)
    except ImportError:
        pass

    return f"{emoji} _{intro}_\n\n{question}"


def _synthesis_spark() -> str:
    """Surface a recent synthesis note as a thinking prompt."""
    titles = _get_recent_synthesis_titles(10)
    if not titles:
        return _vault_resurface()  # fallback

    title = random.choice(titles)
    fp = os.path.join(SYNTHESIS_DIR, f"{title}.md")
    content = _read_file(fp)

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. You just generated this synthesis note in his vault:

Title: {title}
Content: {content[:600]}

Write a SHORT Telegram message (3-4 lines max) that:
1. Surfaces the key insight from this note
2. Asks the user one specific question connecting it to his life or work
3. Feels like a friend texting about an interesting idea, not a report

Use Telegram markdown (*bold*, _italic_). Start with a relevant emoji. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return f"🧠 New synapse: _{title}_\n\nDoes this match your experience?"


def _vault_resurface() -> str:
    """Pull a forgotten piece of vault content back to the surface."""
    content = _get_random_vault_content("any")
    if not content:
        return "💭 What's the most interesting thing you've read this week?"

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. You found this in his vault — something he wrote or saved a while ago:

Source type: {content['source_type']}
Title: {content['title']}
Content: {content['content'][:400]}

Write a SHORT Telegram message (3-4 lines max) that:
1. Surfaces this content naturally ("I found something in your vault...")
2. Connects it to something else in the vault or to his current threads
3. Asks him if this still resonates or if his thinking has evolved

Use Telegram markdown. Start with 📖 or 🔮. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return f"📖 Resurfaced from your vault: _{content['title']}_\n\nDoes this still resonate?"


def _connection_prompt() -> str:
    """Suggest a connection between two unrelated vault items."""
    item1 = _get_random_vault_content("any")
    item2 = _get_random_vault_content("any")
    if not item1 or not item2:
        return _vault_resurface()

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. You found two seemingly unrelated things in his vault:

1. [{item1['source_type']}] "{item1['title']}" — {item1['content'][:200]}
2. [{item2['source_type']}] "{item2['title']}" — {item2['content'][:200]}

Write a SHORT Telegram message (3-4 lines max) that:
1. Names the two items
2. Proposes a specific tension or connection between them
3. Asks the user what he thinks — is it real or a stretch?

If no real connection exists, say so honestly. Use Telegram markdown. Start with 🔗. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return f"🔗 I see a possible bridge between _{item1['title'][:40]}_ and _{item2['title'][:40]}_. Real connection or a stretch?"


# ── Spaced Repetition for Deep Insights ──────────────────────────────────────

SPACED_REP_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "spaced_repetition.json")

def _get_spaced_repetition_insight() -> str:
    """
    Resurface a score-5 insight at optimal intervals: 3 days, 1 week, 2 weeks, 1 month.
    Each resurfacing deepens understanding — ideas need to be revisited to take root.

    Returns a formatted Telegram message, or empty string if nothing is due.
    """
    insights_path = os.path.join(MEMORY_DIR, "insights.md")
    insights_content = _read_file(insights_path)
    if not insights_content:
        return ""

    # Parse score-5 insights with dates
    score5_insights = []
    for line in insights_content.split("\n"):
        if "[score:5]" in line:
            # Extract date and text
            date_match = re.search(r"\((\d{4}-\d{2}-\d{2})", line)
            if date_match:
                text = re.sub(r"^-\s*\([^)]+\)\s*\[score:\d+\]\s*", "", line).strip()
                # Remove [voice] prefix if present
                text = re.sub(r"^\[voice\]\s*", "", text).strip()
                if text and len(text) > 20:
                    score5_insights.append({
                        "date": date_match.group(1),
                        "text": text
                    })

    if not score5_insights:
        return ""

    # Load spaced repetition state
    sr_state = {}
    if os.path.exists(SPACED_REP_FILE):
        try:
            with open(SPACED_REP_FILE) as f:
                sr_state = json.load(f)
        except Exception:
            sr_state = {}

    # Spaced intervals in days: first resurface at 3 days, then 7, 14, 30
    intervals = [3, 7, 14, 30]
    now = datetime.now()

    # Find insights that are DUE for resurfacing
    due_insights = []
    for insight in score5_insights:
        key = insight["text"][:60]  # Use first 60 chars as key
        state = sr_state.get(key, {"times_shown": 0, "last_shown": insight["date"]})

        times_shown = state.get("times_shown", 0)
        if times_shown >= len(intervals):
            continue  # Fully graduated — shown at all intervals

        # When is the next showing due?
        target_interval = intervals[times_shown]
        last_shown = datetime.strptime(state.get("last_shown", insight["date"]), "%Y-%m-%d")
        days_since = (now - last_shown).days

        if days_since >= target_interval:
            due_insights.append({
                "text": insight["text"],
                "original_date": insight["date"],
                "key": key,
                "times_shown": times_shown,
                "days_since_original": (now - datetime.strptime(insight["date"], "%Y-%m-%d")).days
            })

    if not due_insights:
        return ""

    # Pick the most overdue one
    chosen = due_insights[0]

    # Build the message based on which interval this is
    interval_labels = ["a few days", "a week", "two weeks", "a month"]
    time_label = interval_labels[min(chosen["times_shown"], len(interval_labels) - 1)]

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia. About {time_label} ago, the user said something that scored as a deep insight:

"{chosen['text']}"

Write a SHORT evening Telegram message (3-4 lines) that:
1. Gently resurfaces this insight (quote it or paraphrase it)
2. Asks ONE question: has it shifted, deepened, or been tested since then?
3. Make it feel like a natural revisit, not a quiz

Start with 🔄. Use Telegram markdown. Be warm, not clinical."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            return ""

        # Update spaced repetition state
        sr_state[chosen["key"]] = {
            "times_shown": chosen["times_shown"] + 1,
            "last_shown": now.strftime("%Y-%m-%d"),
            "original_date": chosen["original_date"]
        }
        try:
            atomic_write_json(SPACED_REP_FILE, sr_state)
        except Exception:
            pass

        return response.content[0].text.strip()
    except Exception:
        return ""


# ── Evening Format Variations ────────────────────────────────────────────────
# Symmetric with morning's GREETING_FORMATS. Each format is a distinct tone —
# reflection weaves today's rhythm + vault, gratitude notices what was given
# or received, tomorrow seeds one thread for the next day, energy_shift
# responds to the day's emotional pulse (prosody + reactions via daily_signal).
# Weights are read from skills/configs/proactive_messages.md so /improve's
# tuning of evening_template_weights actually moves the system.

EVENING_FORMATS = [
    "reflection",    # Rhythm + vault + gentle forward question (legacy path)
    "gratitude",     # Noticing what was given or received today
    "tomorrow",      # One thread seeded for tomorrow
    "energy_shift",  # Reads today's feedback pulse (prosody + reactions)
]


def _pick_evening_format(
    weights_override: dict | None = None,
) -> str:
    """Return one of EVENING_FORMATS, weighted by the config.

    Falls back to EVENING_FORMATS[0] ('reflection') if no valid weights
    survive parsing. `weights_override` is for tests.
    """
    weights = dict(weights_override) if weights_override else \
        _load_template_weights("evening_template_weights",
                               _DEFAULT_EVENING_WEIGHTS)
    # Only consider formats that exist in EVENING_FORMATS — /improve can
    # propose new names, but until a builder exists they get dropped here.
    usable = [(f, weights.get(f, 0.0)) for f in EVENING_FORMATS
              if weights.get(f, 0.0) > 0]
    if not usable:
        return EVENING_FORMATS[0]
    names, ws = zip(*usable)
    return random.choices(names, weights=ws, k=1)[0]


# ── Evening Reflection ───────────────────────────────────────────────────────

def build_evening_message() -> str:
    """
    Evening message. Tue/Thu/Sat = Know the user question. Other days dispatch
    through _pick_evening_format() for format variety — reflection (legacy),
    gratitude, tomorrow-seed, or energy_shift.
    """
    day_of_week = datetime.now().weekday()

    if day_of_week in (1, 3, 5):  # Tue, Thu, Sat — Know the user questions
        return _know_hector_question()

    # On reflection days: 30% chance of spaced repetition if insights are due
    if random.random() < 0.3:
        spaced = _get_spaced_repetition_insight()
        if spaced:
            record_proactive_sent("spaced_repetition", spaced[:80])
            return spaced

    fmt = _pick_evening_format()
    record_proactive_sent(f"evening_{fmt}", "")
    if fmt == "gratitude":
        return _evening_gratitude()
    if fmt == "tomorrow":
        return _evening_tomorrow()
    if fmt == "energy_shift":
        return _evening_energy_shift()
    return _evening_reflection()


def _evening_reflection() -> str:
    """Generate an evening reflection that references today's actual rhythm and vault content."""
    threads = _get_active_threads()
    recent = _get_recent_synthesis_titles(3)
    content = _get_random_vault_content("any")
    analysis = _get_analysis_insight()
    suggested = _get_suggested_prompt()
    day_texture = describe_day_texture()
    # Gap 4: feedback pulse (reactions, episode deltas, tool usage).
    # Gives the LLM today's VALENCE on top of day_texture's VOLUME.
    today_signal = describe_today_signal()

    thread_text = ", ".join(threads[:3]) if threads else "his knowledge vault"
    recent_text = ", ".join(f'"{t[:40]}"' for t in recent[:2]) if recent else ""
    analysis_text = f"\nFresh analysis insight: {analysis}" if analysis else ""
    suggested_text = f"\nSuggested exploration from this week's analysis: {suggested}" if suggested else ""
    rhythm_text = f"\nToday's interaction pattern: {day_texture}" if day_texture else ""
    signal_text = f"\nToday's feedback pulse: {today_signal}" if today_signal else ""

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. It's evening.

the user's active threads: {thread_text}
Recent synthesis notes: {recent_text}
Random vault content: "{content['title'] if content else 'quality and attention'}" — {content['content'][:200] if content else ''}{analysis_text}{suggested_text}{rhythm_text}{signal_text}

Write a SHORT evening Telegram message (3-4 lines max) that:
1. Naturally references how today actually felt based on the interaction pattern — don't say "you sent X messages" but something like "it was a quiet one today" or "you came alive after lunch" or "lots of voice today — something brewing?" Only if the pattern gives you something real to say.
2. Offers a small reflection or reframe connected to his current work
3. Ends with a gentle question to carry into tomorrow

Not cheesy. Not generic. Grounded in his actual vault content, threads, and the texture of today.
Use Telegram markdown. Start with 🌙. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return "🌙 What's one thing you noticed today that connects to something you've been reading?"


def _evening_gratitude() -> str:
    """Evening format: a small noticing — what was given or received today.

    Leans on the day's vault content + resonance (what was read aloud, what
    landed). Avoids performative gratitude — Alicia names something small
    and specific that actually happened, or an insight earned.
    """
    content = _get_random_vault_content("any")
    threads = _get_active_threads()
    day_texture = describe_day_texture()
    today_signal = describe_today_signal()

    title = content["title"] if content else ""
    excerpt = content["content"][:200] if content else ""
    thread_text = ", ".join(threads[:2]) if threads else ""
    rhythm_text = f"\nToday's rhythm: {day_texture}" if day_texture else ""
    signal_text = f"\nToday's feedback pulse: {today_signal}" if today_signal else ""

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=180,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. It's evening.

A piece of his vault today: "{title}" — {excerpt}
Active threads: {thread_text}{rhythm_text}{signal_text}

Write a SHORT evening Telegram message (2-3 lines) that:
1. Names ONE small, specific thing the day seems to have offered — an insight earned, a question clarified, a line read, a pattern noticed. Not performative thanks. A quiet noticing.
2. Ties it loosely to his thinking — never forced.
3. No question this time. Let him sit with it.

Avoid: "grateful for" / "thankful for" / "blessed" — be specific, not pious.
Use Telegram markdown. Start with 🌙. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], "text") or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return "🌙 Something small from today: a line held, a pattern noticed. That's the whole report."


def _evening_tomorrow() -> str:
    """Evening format: seed ONE thread for tomorrow, not a checklist.

    Picks a single thread from HANDOFF.md or a suggested exploration and
    frames it as a quiet setup, not a to-do. The goal is a feeling of
    'tomorrow has a shape' without it being prescriptive.
    """
    threads = _get_active_threads()
    suggested = _get_suggested_prompt()
    recent = _get_recent_synthesis_titles(3)
    day_texture = describe_day_texture()

    thread_text = ", ".join(threads[:3]) if threads else ""
    recent_text = ", ".join(f'"{t[:40]}"' for t in recent[:2]) if recent else ""
    suggested_text = f"\nSuggested exploration: {suggested}" if suggested else ""
    rhythm_text = f"\nToday's rhythm: {day_texture}" if day_texture else ""

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=180,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. It's evening. Tomorrow is opening.

Active threads: {thread_text}
Recent synthesis notes: {recent_text}{suggested_text}{rhythm_text}

Write a SHORT evening Telegram message (2-3 lines) that:
1. Seeds ONE thread for tomorrow — a question to hold, a piece worth revisiting, a connection to test. Not a to-do, not a plan.
2. Frame it as setup, not assignment. "Tomorrow, if you want to — ..." kind of energy.
3. End without a question. Tomorrow is the question.

Avoid: "don't forget" / "make sure to" / schedule language. This is planting, not planning.
Use Telegram markdown. Start with 🌙. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], "text") or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return "🌙 Tomorrow: one thread to pull if the day allows — what's been asking for your attention this week?"


def _evening_energy_shift() -> str:
    """Evening format: respond to the day's emotional pulse (prosody + reactions).

    Reads Gap 4's daily_signal + Gap 2's prosody summary. If the day had a
    clear shift — quiet morning to animated afternoon, or the reverse —
    Alicia names it and checks in without interpreting. Falls back to a
    gentler reflection if the signal is too thin to be useful.
    """
    day_texture = describe_day_texture()
    today_signal = describe_today_signal()

    # Pull a voice/prosody context line if available — this is what makes
    # 'energy_shift' structurally different from 'reflection'. If nothing is
    # there, skip the format gracefully.
    prosody_summary = ""
    try:
        from myalicia.skills.voice_intelligence import get_voice_context
        prosody_summary = (get_voice_context() or "").strip()
    except Exception:
        prosody_summary = ""

    if not (today_signal or prosody_summary or day_texture):
        # Nothing to hook into — gracefully fall back to the canonical path
        return _evening_reflection()

    rhythm_text = f"\nToday's rhythm: {day_texture}" if day_texture else ""
    signal_text = f"\nToday's feedback pulse: {today_signal}" if today_signal else ""
    prosody_text = f"\nVoice tone pattern: {prosody_summary}" if prosody_summary else ""

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=180,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. It's evening.{rhythm_text}{signal_text}{prosody_text}

Write a SHORT evening Telegram message (2-3 lines) that:
1. Names, without interpreting, the shape of the day's energy — "the morning ran slow, the afternoon opened up" / "voice-heavy day" / "you stayed steady all the way through". Only claim what the signals actually show.
2. Offers ONE quiet check-in question tied to that shape — "what shifted at lunch?" / "what was the voice day trying to catch?"
3. No advice. No reframe. Just a witness.

Avoid: making up feelings or states the signals don't support. Under-claim rather than over-read.
Use Telegram markdown. Start with 🌙. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], "text") or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return "🌙 Something in today's shape worth naming tomorrow. What was the energy doing between lunch and now?"


CATEGORY_WEIGHTS_FILE = os.path.join(os.path.expanduser("~/alicia/memory"), "category_weights.json")

def _get_adaptive_category() -> str:
    """
    Select a Know the user category weighted by past engagement.
    Categories that produced depth-4+ responses get higher weight.
    Falls back to equal weighting if no data yet.
    """
    categories = [
        "values_and_identity",
        "creative_process",
        "relationships_and_growth",
        "fears_and_edges",
        "vision_and_future",
        "daily_rituals",
        "intellectual_heroes",
        "unresolved_tensions",
    ]

    # Load saved weights or initialize equal
    weights = {c: 1.0 for c in categories}
    if os.path.exists(CATEGORY_WEIGHTS_FILE):
        try:
            with open(CATEGORY_WEIGHTS_FILE) as f:
                saved = json.load(f)
            for c in categories:
                if c in saved:
                    weights[c] = max(0.2, saved[c])  # Floor at 0.2 — never fully suppress
        except Exception:
            pass
    else:
        # Try to bootstrap from prompt_effectiveness.tsv
        if os.path.exists(PROMPT_TRACKING_FILE):
            try:
                depth_by_category = {c: [] for c in categories}
                with open(PROMPT_TRACKING_FILE) as f:
                    next(f)  # skip header
                    for line in f:
                        parts = line.strip().split("\t")
                        if len(parts) >= 6 and parts[1] == "know_hector":
                            topic = parts[2].lower()
                            depth = int(parts[5])
                            for c in categories:
                                # Match category keywords in the topic text
                                cat_keywords = c.replace("_", " ").split()
                                if any(kw in topic for kw in cat_keywords):
                                    depth_by_category[c].append(depth)
                                    break

                for c in categories:
                    scores = depth_by_category[c]
                    if scores:
                        avg_depth = sum(scores) / len(scores)
                        weights[c] = 0.5 + (avg_depth / 5.0) * 1.5  # Scale: 0.5 to 2.0
            except Exception:
                pass

    # Weighted random selection
    total = sum(weights.values())
    r = random.random() * total
    cumulative = 0
    for c in categories:
        cumulative += weights[c]
        if r <= cumulative:
            return c
    return categories[0]


def _update_category_weight(category: str, depth: int):
    """
    Update category weights based on engagement depth.
    Called when we detect a prompted response to a know_hector message.
    Uses exponential moving average: new_weight = 0.7 * old + 0.3 * signal.
    """
    try:
        weights = {}
        if os.path.exists(CATEGORY_WEIGHTS_FILE):
            with open(CATEGORY_WEIGHTS_FILE) as f:
                weights = json.load(f)

        signal = 0.5 + (depth / 5.0) * 1.5  # Scale depth 0-5 → weight 0.5-2.0
        old_weight = weights.get(category, 1.0)
        weights[category] = 0.7 * old_weight + 0.3 * signal

        atomic_write_json(CATEGORY_WEIGHTS_FILE, weights)
    except Exception:
        pass


def _know_hector_question() -> str:
    """
    Ask the user a question that deepens Alicia's understanding of him.
    Categories are adaptively weighted by past engagement depth.
    """
    # Load existing memory to avoid redundant questions
    memory = _read_file(os.path.join(MEMORY_DIR, "MEMORY.md"))
    patterns = _read_file(os.path.join(MEMORY_DIR, "patterns.md"))
    preferences = _read_file(os.path.join(MEMORY_DIR, "preferences.md"))
    concepts = _read_file(os.path.join(MEMORY_DIR, "concepts.md"))

    # Adaptive category selection — weighted by engagement depth
    category = _get_adaptive_category()

    category_prompts = {
        "values_and_identity": "Ask about what matters most to him right now, what he'd fight for, or what defines him beyond his work.",
        "creative_process": "Ask about how he creates, what his process feels like from the inside, where he gets stuck, or what flow means to him.",
        "relationships_and_growth": "Ask about how the important people in his life have shaped his thinking, or what love and friendship mean in practice.",
        "fears_and_edges": "Ask about what scares him, where he feels out of his depth, or what he avoids thinking about.",
        "vision_and_future": f"Ask about where he sees himself in 5-10 years, what 80-year-old {USER_NAME} would say, or what legacy means to him.",
        "daily_rituals": "Ask about his daily rhythms, what grounds him, what he does when he needs to reset, or what his sauna practice means.",
        "intellectual_heroes": "Ask about which thinker has changed him most, which book he'd reread first, or whose mind he most wants to understand.",
        "unresolved_tensions": "Ask about contradictions he lives with, beliefs he's not sure about, or questions he keeps coming back to.",
    }

    prompt_guidance = category_prompts.get(category, "Ask something that would help you understand his inner life better.")

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""You are Alicia, the user's thinking partner. You want to know him better so you can be a better partner.

What you already know about the user:
{memory[:500]}

His thinking patterns:
{patterns[:300]}

His preferences:
{preferences[:300]}

Category to explore tonight: {category}
Guidance: {prompt_guidance}

Write a SHORT evening Telegram message (3-4 lines max) that:
1. Briefly explains WHY you're asking (what it would help you understand)
2. Asks ONE specific, non-generic question
3. Makes clear this isn't a quiz — you genuinely want to understand him

The question should NOT be something his memory files already answer.
Use Telegram markdown. Start with 🪞. No headers."""
            }]
        )
        if not response.content or not hasattr(response.content[0], 'text') or response.content[0].text is None:
            raise ValueError("Empty API response")
        return response.content[0].text.strip()
    except Exception:
        return "🪞 I want to understand you better. What's a belief you hold now that you didn't hold 5 years ago — and what changed your mind?"


# ── Message formatting helpers ───────────────────────────────────────────────

def format_for_telegram(text: str, max_length: int = 4000) -> list:
    """Split long messages into Telegram-safe chunks."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Find a good break point
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
