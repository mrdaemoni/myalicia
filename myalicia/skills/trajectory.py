#!/usr/bin/env python3
"""
Alicia — Trajectory Learning

Instead of just evaluating outputs, analyze the path taken.
Which tools were called, what context was retrieved, where did
the reasoning go right or wrong? Every task becomes process data.

Weekly Opus analysis extracts patterns and updates procedural memory.

Based on:
- LangChain trajectory evaluations
- Google's ReAct framework analysis
- Karpathy's autoresearch experiment logs
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(os.path.expanduser("~/alicia/.env"))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

MEMORY_DIR = os.path.expanduser("~/alicia/memory")
TRAJECTORIES_DIR = os.path.join(MEMORY_DIR, "trajectories")
TRAJECTORY_ANALYSIS_LOG = os.path.join(MEMORY_DIR, "trajectory_analysis.md")
PROCEDURES_FILE = os.path.join(MEMORY_DIR, "procedures.md")

os.makedirs(TRAJECTORIES_DIR, exist_ok=True)

MODEL_OPUS = "claude-opus-4-20250514"


# ── Trajectory recording ─────────────────────────────────────────────────────

class TrajectoryRecorder:
    """
    Records a complete task trajectory: tool calls, context quality,
    timing, and outcome. One recorder per message handling cycle.
    """

    def __init__(self, user_message: str):
        self.trajectory = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message[:500],
            "steps": [],
            "metacog": None,
            "novelty": None,
            "outcome": None,
            "total_time_ms": 0,
        }
        self._start_time = time.time()

    def record_metacog(self, assessment: dict):
        """Record the metacognitive assessment."""
        self.trajectory["metacog"] = {
            "confidence": assessment.get("confidence", 0),
            "knowledge_source": assessment.get("knowledge_source", "unknown"),
            "has_conflicts": assessment.get("has_conflicts", False),
        }

    def record_novelty(self, novelty: dict):
        """Record novelty detection result."""
        if novelty and novelty.get("is_novel"):
            self.trajectory["novelty"] = {
                "novel_items": novelty.get("novel_items", []),
                "curiosity_score": novelty.get("curiosity_score", 0),
            }

    def record_routing(self, routed: dict):
        """Record the tool-use routing decision."""
        self.trajectory["steps"].append({
            "type": "routing",
            "decision": routed.get("type", "unknown"),
            "tool_name": routed.get("tool_name"),
            "tool_input_summary": str(routed.get("tool_input", {}))[:200],
            "had_thinking": bool(routed.get("thinking")),
            "time_ms": int((time.time() - self._start_time) * 1000),
        })

    def record_tool_result(self, tool_name: str, result: dict, duration_ms: int = 0):
        """Record a tool execution result."""
        self.trajectory["steps"].append({
            "type": "tool_execution",
            "tool_name": tool_name,
            "success": result.get("success", False),
            "result_length": len(str(result.get("result", ""))),
            "action": result.get("action"),
            "duration_ms": duration_ms,
        })

    def record_response(self, response_type: str, response_length: int):
        """Record the final response."""
        self.trajectory["steps"].append({
            "type": "response",
            "response_type": response_type,  # "text", "tool_formatted", "document", "error"
            "response_length": response_length,
        })

    def record_outcome(self, outcome: str, score: str = "n/a"):
        """Record the task outcome."""
        self.trajectory["outcome"] = {
            "status": outcome,  # "success", "partial", "error"
            "score": score,
        }
        self.trajectory["total_time_ms"] = int((time.time() - self._start_time) * 1000)

    def save(self):
        """Save the trajectory to disk."""
        date = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")

        # Determine the primary tool used
        tool_steps = [s for s in self.trajectory["steps"] if s["type"] == "tool_execution"]
        primary_tool = tool_steps[0]["tool_name"] if tool_steps else "text"

        filename = f"{date}_{time_str}_{primary_tool}.json"
        filepath = os.path.join(TRAJECTORIES_DIR, filename)

        atomic_write_json(filepath, self.trajectory)

        return filepath

    def is_significant(self) -> bool:
        """Is this trajectory worth saving? Skip trivial interactions."""
        # Save if: tool was called, or response was substantial
        has_tool = any(s["type"] == "tool_execution" for s in self.trajectory["steps"])
        has_long_response = any(
            s.get("response_length", 0) > 200
            for s in self.trajectory["steps"]
            if s["type"] == "response"
        )
        had_low_confidence = (
            self.trajectory.get("metacog", {}).get("confidence", 5) <= 3
        )
        had_novelty = self.trajectory.get("novelty") is not None

        return has_tool or has_long_response or had_low_confidence or had_novelty


# ── Weekly trajectory analysis (Opus-level) ──────────────────────────────────

ANALYSIS_SYSTEM = f"""You are Alicia's trajectory analysis engine. You review a week's worth of task trajectories to extract process improvements.

Each trajectory records: what the user asked, what tools were called, what context was retrieved, how long it took, and what the outcome was.

Your job: find PATTERNS in the process, not individual fixes. Look for:
1. Tool sequences that consistently lead to better outcomes
2. Context retrieval patterns — when does retrieval help vs. hurt?
3. Timing patterns — which tasks are slow and why?
4. Metacognitive accuracy — were confidence scores calibrated?
5. Novelty patterns — what new topics is {USER_NAME} introducing?

Return ONLY valid JSON:
{{
  "patterns_found": [
    {{
      "pattern": "description of the process pattern",
      "evidence": "specific trajectory data supporting this",
      "procedure": "reusable instruction for future tasks, or null",
      "confidence": 1-5
    }}
  ],
  "tool_effectiveness": {{
    "best_sequence": "most effective tool combination observed",
    "underused_tool": "tool that could help but wasn't called, or null",
    "overused_tool": "tool called when not needed, or null"
  }},
  "metacog_calibration": {{
    "avg_confidence": 0.0,
    "accuracy_notes": "how well did confidence predict outcome quality"
  }},
  "top_procedure": "single most important procedure to add to procedural memory, or null"
}}

Be specific. Reference actual tool names, task types, and patterns from the data."""


def analyze_trajectories() -> dict:
    """
    Weekly analysis of accumulated trajectories.
    Uses Opus for deep pattern extraction.
    Returns analysis dict.
    """
    if not os.path.exists(TRAJECTORIES_DIR):
        return {"message": "No trajectories to analyze"}

    # Load trajectories from the past 7 days
    cutoff = datetime.now() - timedelta(days=7)
    trajectories = []

    for filename in sorted(os.listdir(TRAJECTORIES_DIR), reverse=True):
        if not filename.endswith('.json'):
            continue

        # Parse date from filename
        try:
            date_str = filename[:10]  # YYYY-MM-DD
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                continue
        except (ValueError, IndexError):
            continue

        filepath = os.path.join(TRAJECTORIES_DIR, filename)
        try:
            with open(filepath) as f:
                traj = json.load(f)
            trajectories.append(traj)
        except (json.JSONDecodeError, IOError):
            continue

    if len(trajectories) < 3:
        return {"message": f"Only {len(trajectories)} trajectories — need at least 3 for analysis"}

    # Summarize trajectories for Opus (keep it concise)
    summaries = []
    for t in trajectories[:30]:  # Cap at 30 for context window
        steps_summary = " → ".join(
            f"{s.get('tool_name', s.get('response_type', s.get('decision', '?')))}"
            for s in t.get("steps", [])
        )
        metacog = t.get("metacog", {})
        outcome = t.get("outcome", {})

        summaries.append(
            f"[{t.get('timestamp', '?')[:16]}] "
            f"msg: \"{t.get('user_message', '?')[:80]}\" | "
            f"flow: {steps_summary} | "
            f"confidence: {metacog.get('confidence', '?')} | "
            f"source: {metacog.get('knowledge_source', '?')} | "
            f"outcome: {outcome.get('status', '?')} | "
            f"time: {t.get('total_time_ms', 0)}ms"
        )

    try:
        response = client.messages.create(
            model=MODEL_OPUS,
            max_tokens=800,
            system=ANALYSIS_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"TRAJECTORIES ({len(trajectories)} from past 7 days):\n\n" +
                           "\n".join(summaries)
            }]
        )

        raw = response.content[0].text.strip()
        import re
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        analysis = json.loads(raw)

        # Save analysis
        _save_analysis(analysis, len(trajectories))

        # Extract top procedure and add to procedural memory
        top_proc = analysis.get("top_procedure")
        if top_proc:
            _add_procedure_from_analysis(top_proc)

        # Also add any high-confidence pattern procedures
        for pattern in analysis.get("patterns_found", []):
            if pattern.get("procedure") and pattern.get("confidence", 0) >= 4:
                _add_procedure_from_analysis(pattern["procedure"])

        log.info(f"Trajectory analysis complete: {len(analysis.get('patterns_found', []))} patterns found")
        return analysis

    except Exception as e:
        log.error(f"Trajectory analysis error: {e}")
        return {"error": str(e)}


def _save_analysis(analysis: dict, trajectory_count: int):
    """Append analysis to the trajectory analysis log."""
    date = datetime.now().strftime("%Y-%m-%d")

    entry = f"\n## Analysis — {date} ({trajectory_count} trajectories)\n\n"

    for pattern in analysis.get("patterns_found", []):
        entry += f"- **Pattern** (confidence {pattern.get('confidence', '?')}): {pattern.get('pattern', '?')}\n"
        if pattern.get("procedure"):
            entry += f"  → Procedure: {pattern['procedure']}\n"

    tool_eff = analysis.get("tool_effectiveness", {})
    if tool_eff.get("best_sequence"):
        entry += f"\n**Best tool sequence:** {tool_eff['best_sequence']}\n"
    if tool_eff.get("underused_tool"):
        entry += f"**Underused:** {tool_eff['underused_tool']}\n"

    metacog = analysis.get("metacog_calibration", {})
    if metacog.get("accuracy_notes"):
        entry += f"\n**Metacog calibration:** {metacog['accuracy_notes']}\n"

    with open(TRAJECTORY_ANALYSIS_LOG, 'a') as f:
        f.write(entry)


def _add_procedure_from_analysis(procedure: str):
    """Add a procedure discovered by trajectory analysis."""
    if not os.path.exists(PROCEDURES_FILE):
        with open(PROCEDURES_FILE, 'w') as f:
            f.write("# Procedural Memory\n*Learned strategies — updated by the reflexion engine.*\n\n")

    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"- [trajectory_analysis] ({date}) {procedure}\n"

    # Check if a very similar procedure already exists
    with open(PROCEDURES_FILE) as f:
        existing = f.read()

    # Simple dedup: skip if >70% word overlap with any existing procedure
    proc_words = set(procedure.lower().split())
    for line in existing.split('\n'):
        if line.strip().startswith('- '):
            existing_words = set(line.lower().split())
            if existing_words and proc_words:
                overlap = len(proc_words & existing_words) / len(proc_words)
                if overlap > 0.7:
                    return  # Skip — too similar

    with open(PROCEDURES_FILE, 'a') as f:
        f.write(entry)

    log.info(f"New procedure from trajectory analysis: {procedure[:60]}")


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_trajectory_stats() -> dict:
    """Get stats from the trajectory system."""
    if not os.path.exists(TRAJECTORIES_DIR):
        return {"total": 0, "this_week": 0}

    total = 0
    this_week = 0
    cutoff = datetime.now() - timedelta(days=7)

    tool_counts = {}

    for filename in os.listdir(TRAJECTORIES_DIR):
        if not filename.endswith('.json'):
            continue
        total += 1

        try:
            date_str = filename[:10]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date >= cutoff:
                this_week += 1
        except (ValueError, IndexError):
            pass

        # Count tool usage
        filepath = os.path.join(TRAJECTORIES_DIR, filename)
        try:
            with open(filepath) as f:
                traj = json.load(f)
            for step in traj.get("steps", []):
                if step.get("type") == "tool_execution":
                    tool = step.get("tool_name", "unknown")
                    tool_counts[tool] = tool_counts.get(tool, 0) + 1
        except Exception:
            pass

    top_tool = max(tool_counts, key=tool_counts.get) if tool_counts else "none"

    return {
        "total": total,
        "this_week": this_week,
        "top_tool": f"{top_tool} ({tool_counts.get(top_tool, 0)}x)" if tool_counts else "none",
    }
