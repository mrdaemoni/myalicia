#!/usr/bin/env python3
"""
Alicia — Meta-Cognition Engine

Gives Alicia awareness of her own confidence, knowledge boundaries,
and reasoning quality. Instead of responding with equal certainty about
everything, she tracks what she knows well vs. where she's guessing.

Based on:
- Microsoft's AI Metacognition framework (2025)
- Stanford's "Imagining and Building Wise Machines" (Johnson 2024)
- Nature's "Fast, Slow, and Metacognitive Thinking in AI" (2025)

Five dimensions: confidence, knowledge boundary, conflict detection,
calibration, and decision mode (fast Sonnet vs. slow Opus).
"""

import os
import json
import logging
import re
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

MEMORY_DIR = str(MEMORY_DIR)
CALIBRATION_LOG = os.path.join(MEMORY_DIR, "calibration_log.tsv")
VAULT_ROOT = str(config.vault.root)

# ── Metacognitive assessment prompt ──────────────────────────────────────────

METACOG_SYSTEM = ("""You are Alicia's metacognition engine. Before responding to {USER_NAME}, you assess your own epistemic state.

Given:
- The user's message
- Retrieved memory context (what Alicia knows about this topic from memory files)
- Retrieved vault context (what's in the Obsidian vault about this topic)

Assess QUICKLY (this runs on every message, be fast):

Return ONLY valid JSON:
{
  "confidence": 1-5,
  "confidence_reasoning": "one sentence — why this confidence level",
  "knowledge_source": "vault|memory|training|inference|mixed",
  "has_conflicts": false,
  "conflict_detail": null,
  "suggest_opus": false,
  "uncertainty_note": "one sentence to optionally include in response, or null"
}

Scoring:
- 5: Deep coverage in vault + personal memory. Multiple sources agree.
- 4: Good vault coverage OR strong memory. Can speak with authority.
- 3: Some relevant content but gaps exist. Should acknowledge limits.
- 2: Thin coverage. Mostly relying on training knowledge. Should flag.
- 1: No vault/memory coverage. Pure inference. Should be transparent.

knowledge_source: Where is the knowledge primarily coming from?
- vault: Strong vault coverage on this exact topic
- memory: From stored memories of {USER_NAME}'s preferences/patterns
- training: From Claude's general training data (not personalized)
- inference: Reasoning from related concepts, not direct knowledge
- mixed: Multiple sources contributing

has_conflicts: Do retrieved memories/vault notes contradict each other?
conflict_detail: If yes, describe the specific tension in one sentence.

suggest_opus: Should this go to Opus for deeper reasoning?
Set true when: multi-step reasoning needed, conflicting sources,
novel synthesis required, or confidence < 2.

uncertainty_note: A phrase Alicia can naturally include in her response.
Example: "I'm drawing mostly from Pirsig here — the vault has less on Nishida's take"
Set null if confidence >= 4 (no need to flag certainty).""".replace("{USER_NAME}", USER_NAME))


# ── Core functions ────────────────────────────────────────────────────────────

def assess_confidence(user_message: str, memory_context: str = "", vault_context: str = "") -> dict:
    """
    Assess Alicia's epistemic state before responding.
    Returns metacognitive assessment dict.

    Designed to be fast — runs on every message as a lightweight pre-check.
    """
    # Skip very short messages
    if len(user_message.strip()) < 15:
        return _default_assessment()

    # Skip greetings and meta-messages
    lowered = user_message.lower().strip()
    skip_patterns = ["hi", "hello", "hey", "thanks", "ok", "yes", "no", "sure",
                     "good morning", "good night", "bye", "lol", "haha"]
    if lowered in skip_patterns or len(lowered) < 10:
        return _default_assessment()

    try:
        # Trim context to keep this fast
        mem_trimmed = memory_context[:600] if memory_context else "(no memory context retrieved)"
        vault_trimmed = vault_context[:600] if vault_context else "(no vault context retrieved)"

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=METACOG_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"USER MESSAGE: {user_message}\n\n"
                    f"MEMORY CONTEXT:\n{mem_trimmed}\n\n"
                    f"VAULT CONTEXT:\n{vault_trimmed}"
                )
            }]
        )

        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        assessment = json.loads(raw)

        # Log for calibration tracking
        _log_assessment(user_message, assessment)

        return assessment

    except Exception as e:
        log.error(f"Metacognition error: {e}")
        return _default_assessment()


def _default_assessment() -> dict:
    """Return a neutral assessment for trivial messages."""
    return {
        "confidence": 4,
        "confidence_reasoning": "Routine interaction",
        "knowledge_source": "mixed",
        "has_conflicts": False,
        "conflict_detail": None,
        "suggest_opus": False,
        "uncertainty_note": None,
    }


def get_metacog_prompt_injection(assessment: dict) -> str:
    """
    Generate a system prompt injection based on the metacognitive assessment.
    This tells Sonnet how to modulate its response.
    """
    if not assessment:
        return ""

    lines = []
    confidence = assessment.get("confidence", 4)

    if confidence <= 2:
        lines.append(
            "⚠️ METACOGNITION: Low confidence on this topic. "
            "Be transparent about what you're sure of vs. inferring. "
            "Explicitly say where your knowledge comes from."
        )
        uncertainty = assessment.get("uncertainty_note")
        if uncertainty:
            lines.append(f"Suggested uncertainty note: \"{uncertainty}\"")

    elif confidence == 3:
        lines.append(
            "📊 METACOGNITION: Moderate confidence. Some gaps exist. "
            "Acknowledge limits naturally without undermining your response."
        )
        uncertainty = assessment.get("uncertainty_note")
        if uncertainty:
            lines.append(f"You could mention: \"{uncertainty}\"")

    if assessment.get("has_conflicts"):
        conflict = assessment.get("conflict_detail", "unspecified tension")
        lines.append(
            f"⚡ CONFLICT DETECTED: {conflict}. "
            "Present both sides. Don't silently pick one."
        )

    source = assessment.get("knowledge_source", "mixed")
    if source == "training":
        lines.append(
            "📚 NOTE: This response draws mainly from general training knowledge, "
            f"not from {USER_NAME}'s vault or memory. Consider suggesting research to strengthen the vault."
        )

    if not lines:
        return ""

    return "\n### Metacognitive Assessment\n" + "\n".join(lines)


# ── Calibration tracking ─────────────────────────────────────────────────────

def _init_calibration_log():
    """Initialize the calibration log TSV."""
    if not os.path.exists(CALIBRATION_LOG):
        with open(CALIBRATION_LOG, 'w') as f:
            f.write("timestamp\ttopic\tconfidence\tknowledge_source\thas_conflicts\n")


def _log_assessment(message: str, assessment: dict):
    """Log a metacognitive assessment for calibration analysis."""
    _init_calibration_log()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Extract topic keywords (first 5 meaningful words)
    words = re.split(r'\W+', message.lower())
    stop = {'the', 'a', 'an', 'is', 'are', 'was', 'to', 'of', 'in', 'for', 'on',
            'with', 'i', 'my', 'me', 'you', 'your', 'and', 'or', 'but', 'not',
            'can', 'do', 'does', 'did', 'will', 'what', 'how', 'this', 'that'}
    topic_words = [w for w in words if w and len(w) > 2 and w not in stop][:5]
    topic = " ".join(topic_words) if topic_words else "general"

    row = (
        f"{timestamp}\t"
        f"{topic}\t"
        f"{assessment.get('confidence', 0)}\t"
        f"{assessment.get('knowledge_source', 'unknown')}\t"
        f"{assessment.get('has_conflicts', False)}\n"
    )
    with open(CALIBRATION_LOG, 'a') as f:
        f.write(row)


def log_prediction(topic: str, claim: str, confidence: int):
    """
    Manually log a specific prediction for later verification.
    Used when Alicia makes a factual claim she wants to track.
    """
    pred_file = os.path.join(MEMORY_DIR, "predictions.tsv")
    if not os.path.exists(pred_file):
        with open(pred_file, 'w') as f:
            f.write("timestamp\ttopic\tclaim\tconfidence\tverified\toutcome\n")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = f"{timestamp}\t{topic}\t{claim[:200]}\t{confidence}\t\t\n"
    with open(pred_file, 'a') as f:
        f.write(row)


def check_calibration() -> dict:
    """
    Analyze calibration data — are confidence scores accurate?
    Returns stats on confidence distribution and source patterns.
    """
    if not os.path.exists(CALIBRATION_LOG):
        return {"total": 0, "message": "No calibration data yet."}

    confidence_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    source_counts = {}
    conflict_count = 0
    total = 0

    try:
        with open(CALIBRATION_LOG) as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    total += 1
                    conf = int(parts[2]) if parts[2].isdigit() else 3
                    confidence_counts[conf] = confidence_counts.get(conf, 0) + 1
                    source = parts[3]
                    source_counts[source] = source_counts.get(source, 0) + 1
                    if parts[4].lower() == "true":
                        conflict_count += 1
    except Exception:
        pass

    if total == 0:
        return {"total": 0, "message": "No calibration data yet."}

    avg_confidence = sum(k * v for k, v in confidence_counts.items()) / total
    top_source = max(source_counts, key=source_counts.get) if source_counts else "unknown"

    return {
        "total": total,
        "avg_confidence": round(avg_confidence, 1),
        "confidence_distribution": confidence_counts,
        "primary_knowledge_source": f"{top_source} ({source_counts[top_source]}/{total})",
        "conflicts_detected": conflict_count,
        "conflict_rate": f"{conflict_count/total*100:.0f}%",
    }


# ── Decision mode ─────────────────────────────────────────────────────────────

def should_use_opus(assessment: dict) -> bool:
    """
    Determine if the current task should be escalated to Opus.
    Based on metacognitive assessment.
    """
    if not assessment:
        return False

    # Explicit suggestion from metacognition
    if assessment.get("suggest_opus"):
        return True

    # Very low confidence
    if assessment.get("confidence", 4) <= 1:
        return True

    # Detected conflicts that need careful reasoning
    if assessment.get("has_conflicts") and assessment.get("confidence", 4) <= 3:
        return True

    return False
