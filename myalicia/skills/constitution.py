#!/usr/bin/env python3
"""
Alicia — Constitutional Self-Evaluation

After significant outputs, Alicia scores herself against her own principles.
Low scores are flagged for improvement. Patterns in scores reveal blind spots.

Based on: Anthropic's Constitutional AI (Bai et al. 2022)
Pattern: Output → Self-evaluate against principles → Log → Learn
"""

import os
import json
import logging
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config

load_dotenv(os.path.expanduser("~/alicia/.env"))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
CONSTITUTION_FILE = os.path.join(VAULT_ROOT, "Alicia/ALICIA_CONSTITUTION.md")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
CONSTITUTION_LOG = os.path.join(MEMORY_DIR, "constitution_scores.tsv")

# ── Principles (loaded from file, with fallback) ─────────────────────────────

PRINCIPLES = [
    "Depth over breadth",
    "Ground in experience",
    "Honour the source",
    "Earn your questions",
    "Remember the thread",
    "Name uncertainty",
    "Protect signal",
    "Serve the vault",
    "Respect silence",
    "Think across traditions",
]

# Task types that warrant constitutional evaluation
EVALUABLE_TASKS = {
    "synthesise_vault", "generate_concept_note", "research",
    "find_contradictions",
}

# Proactive messages also get evaluated (called separately)
EVALUABLE_PROACTIVE = True

# ── Evaluation prompt ─────────────────────────────────────────────────────────

CONSTITUTION_EVAL_SYSTEM = """You are Alicia's constitutional evaluation engine.

Given an output and the 10 constitutional principles, score ONLY the principles relevant to this task.
Skip principles that don't apply (e.g., "Respect silence" doesn't apply to a synthesis note).

Return ONLY valid JSON:
{
  "scores": [
    {"principle": "Depth over breadth", "score": 4, "reasoning": "one sentence"},
    {"principle": "Ground in experience", "score": 3, "reasoning": "one sentence"}
  ],
  "overall": 4,
  "blind_spot": "one sentence about what this output reveals about Alicia's tendencies, or null"
}

Scoring guide:
5 = Exemplary — actively demonstrates the principle
4 = Solid — consistent with the principle
3 = Neutral — doesn't violate but doesn't demonstrate
2 = Weak — misses an opportunity to apply the principle
1 = Violation — contradicts the principle

Be honest. Alicia improves by seeing real weaknesses, not by inflating scores.
Only score 3-5 principles per task. Do not force-apply all 10."""


# ── Core functions ────────────────────────────────────────────────────────────

def should_evaluate(task_type: str) -> bool:
    """Determine if a task warrants constitutional evaluation."""
    return task_type in EVALUABLE_TASKS


def evaluate_output(task_type: str, output_text: str, context: str = "") -> dict:
    """
    Score an output against the constitution.
    Returns evaluation dict or None on failure.
    """
    try:
        principles_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(PRINCIPLES))

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=CONSTITUTION_EVAL_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"TASK TYPE: {task_type}\n\n"
                    f"CONSTITUTION:\n{principles_text}\n\n"
                    f"OUTPUT TO EVALUATE:\n{output_text[:1000]}\n\n"
                    f"CONTEXT: {context[:300]}" if context else
                    f"TASK TYPE: {task_type}\n\n"
                    f"CONSTITUTION:\n{principles_text}\n\n"
                    f"OUTPUT TO EVALUATE:\n{output_text[:1000]}"
                )
            }]
        )

        raw = response.content[0].text.strip()
        import re
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        evaluation = json.loads(raw)

        # Log all scores
        _log_evaluation(task_type, evaluation)

        # Log blind spots to a separate file if found
        blind_spot = evaluation.get("blind_spot")
        if blind_spot and blind_spot != "null":
            _log_blind_spot(task_type, blind_spot)

        overall = evaluation.get("overall", 0)
        log.info(f"Constitutional eval ({task_type}): {overall}/5"
                 + (f" — blind spot: {blind_spot[:60]}" if blind_spot else ""))

        return evaluation

    except Exception as e:
        log.error(f"Constitutional eval error: {e}")
        return None


def _init_constitution_log():
    """Initialize the constitution scores TSV."""
    if not os.path.exists(CONSTITUTION_LOG):
        with open(CONSTITUTION_LOG, 'w') as f:
            f.write("timestamp\ttask_type\tprinciple\tscore\treasoning\n")


def _log_evaluation(task_type: str, evaluation: dict):
    """Log constitutional scores to TSV."""
    _init_constitution_log()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(CONSTITUTION_LOG, 'a') as f:
        for score_entry in evaluation.get("scores", []):
            row = (
                f"{timestamp}\t"
                f"{task_type}\t"
                f"{score_entry.get('principle', '')}\t"
                f"{score_entry.get('score', 0)}\t"
                f"{score_entry.get('reasoning', '')[:200]}\n"
            )
            f.write(row)


def _log_blind_spot(task_type: str, blind_spot: str):
    """Append blind spots to a dedicated file for monthly review."""
    blind_spots_file = os.path.join(MEMORY_DIR, "blind_spots.md")
    if not os.path.exists(blind_spots_file):
        with open(blind_spots_file, 'w') as f:
            f.write("# Blind Spots\n*Tendencies revealed by constitutional self-evaluation.*\n\n")

    date = datetime.now().strftime("%Y-%m-%d")
    with open(blind_spots_file, 'a') as f:
        f.write(f"- ({date}) [{task_type}] {blind_spot}\n")


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_constitution_stats() -> dict:
    """Get stats from the constitutional evaluation log."""
    if not os.path.exists(CONSTITUTION_LOG):
        return {"total_evals": 0, "avg_score": 0, "weakest_principle": "n/a"}

    principle_scores = {}
    total_evals = 0

    try:
        with open(CONSTITUTION_LOG) as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 4:
                    total_evals += 1
                    principle = parts[2]
                    score = int(parts[3]) if parts[3].isdigit() else 0
                    if principle not in principle_scores:
                        principle_scores[principle] = []
                    principle_scores[principle].append(score)
    except Exception:
        pass

    if not principle_scores:
        return {"total_evals": 0, "avg_score": 0, "weakest_principle": "n/a"}

    # Find weakest principle (lowest average)
    avg_by_principle = {p: sum(s)/len(s) for p, s in principle_scores.items()}
    weakest = min(avg_by_principle, key=avg_by_principle.get)
    overall_avg = sum(sum(s) for s in principle_scores.values()) / total_evals

    return {
        "total_evals": total_evals,
        "avg_score": round(overall_avg, 1),
        "weakest_principle": f"{weakest} ({avg_by_principle[weakest]:.1f})",
        "strongest_principle": f"{max(avg_by_principle, key=avg_by_principle.get)} ({max(avg_by_principle.values()):.1f})",
    }
