#!/usr/bin/env python3
"""
Alicia — Paired Person Diarization

Weekly synthesis that generates structured profiles of both the user
and Alicia, tracking intellectual evolution, calibration quality,
and the alignment between them.

Inspired by Garry Tan's diarization principle: "The model reads
everything about a subject and writes a structured profile — a
single page of judgment distilled from dozens of documents."
"""
import os
import json
import glob
import logging
from datetime import datetime, timedelta
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_text
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))
log = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

MODEL_OPUS = "claude-opus-4-20250514"
PROFILES_DIR = str(config.vault.self_path / "Profiles")
MEMORY_DIR = str(MEMORY_DIR)


def _get_week_identifier(date: datetime = None) -> str:
    """Return YYYY-WNN week identifier."""
    if date is None:
        date = datetime.now()
    year = date.year
    week = date.isocalendar()[1]
    return f"{year}-W{week:02d}"


def _load_file_content(path: str) -> str:
    """Load file content safely, return empty string if missing."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
    except Exception as e:
        log.warning(f"Failed to load {path}: {e}")
    return ""


def _load_json_file(path: str) -> dict:
    """Load JSON file safely, return empty dict if missing."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"Failed to load JSON {path}: {e}")
    return {}


def _gather_memory_data() -> dict:
    """Gather all memory files into a unified context."""
    data = {}

    core_files = {
        "memory": "MEMORY.md",
        "patterns": "patterns.md",
        "insights": "insights.md",
        "preferences": "preferences.md",
        "concepts": "concepts.md",
        "resonance": "resonance.md",
        "procedures": "procedures.md",
    }

    for key, filename in core_files.items():
        path = os.path.join(MEMORY_DIR, filename)
        data[key] = _load_file_content(path)

    return data


def _gather_recent_trajectories(days_back: int = 7) -> str:
    """Gather recent trajectory entries."""
    traj_dir = os.path.join(MEMORY_DIR, "trajectories")
    if not os.path.exists(traj_dir):
        return ""

    cutoff = datetime.now() - timedelta(days=days_back)
    entries = []

    for traj_file in glob.glob(os.path.join(traj_dir, "*.md")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(traj_file))
            if mtime > cutoff:
                content = _load_file_content(traj_file)
                entries.append(content)
        except Exception as e:
            log.warning(f"Failed to process trajectory {traj_file}: {e}")

    return "\n---\n".join(entries)


def _gather_recent_episodes(days_back: int = 7) -> str:
    """Gather recent reflection episodes."""
    ep_dir = os.path.join(MEMORY_DIR, "episodes")
    if not os.path.exists(ep_dir):
        return ""

    cutoff = datetime.now() - timedelta(days=days_back)
    entries = []

    for ep_file in glob.glob(os.path.join(ep_dir, "*.md")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(ep_file))
            if mtime > cutoff:
                content = _load_file_content(ep_file)
                entries.append(content)
        except Exception as e:
            log.warning(f"Failed to process episode {ep_file}: {e}")

    return "\n---\n".join(entries)


def _gather_curiosity_data() -> dict:
    """Load curiosity followthrough data."""
    path = os.path.join(MEMORY_DIR, "curiosity_followthrough.jsonl")
    if not os.path.exists(path):
        return {"entries": [], "summary": "No curiosity data available"}

    entries = []
    try:
        with open(path, "r") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    except Exception as e:
        log.warning(f"Failed to load curiosity data: {e}")

    recent = [e for e in entries if _is_recent(e.get("timestamp"), 7)]

    summary = {
        "total_entries": len(entries),
        "recent_entries": len(recent),
        "entries": recent[-20:] if recent else [],
    }

    return summary


def _gather_effectiveness_data() -> dict:
    """Load proactive message effectiveness data."""
    path = os.path.join(MEMORY_DIR, "prompt_effectiveness.tsv")
    if not os.path.exists(path):
        return {"summary": "No effectiveness data available"}

    entries = []
    try:
        with open(path, "r") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        entries.append(
                            {
                                "date": parts[0],
                                "prompt": parts[1],
                                "user_response": parts[2],
                                "score": parts[3],
                            }
                        )
    except Exception as e:
        log.warning(f"Failed to load effectiveness data: {e}")

    recent = [e for e in entries if _is_recent(e.get("date"), 7)]

    if recent:
        scores = [float(e["score"]) for e in recent if e["score"].replace(".", "", 1).isdigit()]
        avg_score = sum(scores) / len(scores) if scores else 0
    else:
        avg_score = 0

    return {
        "total_entries": len(entries),
        "recent_entries": len(recent),
        "recent_avg_score": avg_score,
        "recent": recent[-15:] if recent else [],
    }


def _is_recent(timestamp_str: str, days: int = 7) -> bool:
    """Check if timestamp is within N days."""
    if not timestamp_str:
        return False
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return (datetime.now(ts.tzinfo) - ts).days <= days
    except Exception:
        return False


def _get_vault_metrics() -> dict:
    """Get vault metrics from skills module."""
    try:
        from myalicia.skills.vault_metrics import compute_all_metrics
        return compute_all_metrics()
    except Exception as e:
        log.warning(f"Failed to get vault metrics: {e}")
        return {}


def _get_emergence_state() -> dict:
    """Get emergence state from inner_life module."""
    try:
        from myalicia.skills.inner_life import get_emergence_summary
        return get_emergence_summary()
    except Exception as e:
        log.warning(f"Failed to get emergence state: {e}")
        return {}


def _get_archetype_weights() -> dict:
    """Get archetype weights from inner_life module."""
    try:
        from myalicia.skills.inner_life import get_archetype_weights_summary
        return get_archetype_weights_summary()
    except Exception as e:
        log.warning(f"Failed to get archetype weights: {e}")
        return {}


def _get_resonance_summary() -> dict:
    """Get resonance data from tool_router module."""
    try:
        from myalicia.skills.tool_router import get_resonance_summary
        return get_resonance_summary()
    except Exception as e:
        log.warning(f"Failed to get resonance summary: {e}")
        return {}


def _load_last_week_profiles() -> tuple:
    """Load last week's profiles if they exist."""
    cutoff = datetime.now() - timedelta(days=7)
    last_week_id = _get_week_identifier(cutoff)

    user_path = os.path.join(PROFILES_DIR, f"{last_week_id}-user.md")
    alicia_path = os.path.join(PROFILES_DIR, f"{last_week_id}-alicia.md")

    user = _load_file_content(user_path)
    alicia = _load_file_content(alicia_path)

    return (user, alicia)


def _build_synthesis_prompt(all_data: dict, last_profiles: tuple) -> str:
    """Build the comprehensive Opus prompt for paired diarization."""

    last_user, last_alicia = last_profiles
    last_week_context = ""
    if last_user and last_alicia:
        last_week_context = f"""
## Last Week's Profiles (for comparison)

### Last Week — {USER_NAME} Profile
{last_user}

### Last Week — Alicia Profile
{last_alicia}
"""

    memory_context = f"""
## Memory System

### Core Memory Files
- **Memory**: {len(all_data['memory'])} chars
- **Patterns**: {len(all_data['patterns'])} chars
- **Insights**: {len(all_data['insights'])} chars
- **Preferences**: {len(all_data['preferences'])} chars
- **Concepts**: {len(all_data['concepts'])} chars
- **Resonance**: {len(all_data['resonance'])} chars
- **Procedures**: {len(all_data['procedures'])} chars

### Memory Content
**Patterns:**
{all_data['patterns'][:2000]}...

**Insights:**
{all_data['insights'][:2000]}...

**Preferences:**
{all_data['preferences'][:1500]}...

**Concepts:**
{all_data['concepts'][:1500]}...
"""

    trajectories_context = (
        f"\n## Recent Trajectories (7 days)\n{all_data['trajectories'][:3000]}..."
        if all_data["trajectories"]
        else "\n## Recent Trajectories\nNo recent trajectory data."
    )

    episodes_context = (
        f"\n## Reflection Episodes (7 days)\n{all_data['episodes'][:2000]}..."
        if all_data["episodes"]
        else "\n## Reflection Episodes\nNo recent episode data."
    )

    curiosity = all_data["curiosity"]
    curiosity_context = f"""
## Curiosity Engagement
- Total entries: {curiosity['total_entries']}
- Recent (7 days): {curiosity['recent_entries']}
- Recent entries: {json.dumps(curiosity['entries'][:10], indent=2)}
"""

    effectiveness = all_data["effectiveness"]
    effectiveness_context = f"""
## Proactive Message Effectiveness
- Total entries: {effectiveness['total_entries']}
- Recent (7 days): {effectiveness['recent_entries']}
- Recent avg score: {effectiveness['recent_avg_score']:.2f}
- Recent messages: {json.dumps(effectiveness['recent'][:8], indent=2)}
"""

    vault_context = f"""
## Vault Metrics
{json.dumps(all_data['vault_metrics'], indent=2)}
"""

    emergence_context = f"""
## Emergence State
{json.dumps(all_data['emergence_state'], indent=2)}
"""

    archetype_context = f"""
## Archetype Weights
{json.dumps(all_data['archetype_weights'], indent=2)}
"""

    resonance_context = f"""
## Resonance Summary
{json.dumps(all_data['resonance_data'], indent=2)}
"""

    prompt = f"""You are Alicia, an AI agent in deep partnership with {USER_NAME}. This week, you're generating paired diarization — structured profiles of both {USER_NAME} and yourself that reference each other and track the intellectual and calibration arc across a week.

Your task is to synthesize across ALL the data below and produce TWO profiles:
1. A "{USER_NAME} This Week" profile — capturing his intellectual obsessions, evolved positions, engagement patterns, blind spots, emotional weather, and open threads
2. An "Alicia This Week" profile — capturing your capability growth, calibration quality, archetype balance, resonance alignment, emergence state, and self-corrections

Then produce a DELTA section that compares this week to last week.

---

## Data Inputs

{memory_context}

{trajectories_context}

{episodes_context}

{curiosity_context}

{effectiveness_context}

{vault_context}

{emergence_context}

{archetype_context}

{resonance_context}

{last_week_context}

---

## Instructions

Generate BOTH profiles in a single response. Use markdown format. Each profile should be ~500-800 words, densely packed with specific observations grounded in the data above.

### {USER_NAME} This Week Profile

Structure:
- **Current Intellectual Obsessions** — What topics dominate conversations? What vault growth? Specifics from memory and trajectories.
- **Evolving Positions** — What shifted this week? New ideas, changed views, resolved tensions from open threads?
- **Engagement Patterns** — Voice vs text signals? Time of day preference? Depth of responses to proactive messages? Use effectiveness data.
- **Blind Spots** — What clusters/topics has he not engaged with? What vault categories are dormant? Dropped threads?
- **Emotional Weather** — Inferred from voice patterns, message rhythm, reflection depth. Is he energized, analytical, wandering, synthesizing?
- **Open Threads** — Unresolved questions, threads that span multiple conversations. What needs continuation?

### Alicia This Week Profile

Structure:
- **Capability Growth** — Which skills improved? New procedures discovered or refined? Integration improvements?
- **Calibration Report** — Where did curiosity questions land vs miss? Which proactive messages resonated? Effectiveness trends.
- **Archetype Balance** — Which archetypes surfaced most? Weight shifts from last week? Is the archetype mix serving the partnership?
- **Resonance Alignment** — Are you surfacing what {USER_NAME} actually cares about? Gaps between your curiosity direction and his focus?
- **Emergence State** — Current season, score, trajectory. Are you growing, consolidating, or shifting?
- **Self-Corrections** — What did the reflexion system flag? What trajectory analysis revealed about your own patterns?

### Delta Section

Compare to last week (if profiles exist):
- **{USER_NAME}'s Intellectual Focus Shift** — What changed? New obsessions, abandoned threads, deepened interests?
- **Alicia's Calibration Arc** — Where did you improve or degrade? Effectiveness trajectory?
- **Partnership Alignment** — Tension or synergy between {USER_NAME}'s interests and your curiosity direction? Are you tracking him well?

---

## Output Format

Respond ONLY with the three markdown sections below. No preamble, no explanation. Use markdown headers and formatting.

# {USER_NAME} This Week
[profile content here]

# Alicia This Week
[profile content here]

# Delta from Last Week
[delta content here]
"""

    return prompt


def run_paired_diarization() -> dict:
    """
    Weekly paired diarization pass. Generates both profiles.
    Returns dict with user_profile, alicia_profile, delta (what changed from last week).
    Called from Sunday weekly pass in scheduler.
    """
    log.info("Starting paired diarization...")

    week_id = _get_week_identifier()
    log.info(f"Week identifier: {week_id}")

    memory_data = _gather_memory_data()
    all_data = {
        **memory_data,  # flattens memory, patterns, insights, etc. as top-level keys
        "trajectories": _gather_recent_trajectories(7),
        "episodes": _gather_recent_episodes(7),
        "curiosity": _gather_curiosity_data(),
        "effectiveness": _gather_effectiveness_data(),
        "vault_metrics": _get_vault_metrics(),
        "emergence_state": _get_emergence_state(),
        "archetype_weights": _get_archetype_weights(),
        "resonance_data": _get_resonance_summary(),
    }

    last_profiles = _load_last_week_profiles()

    prompt = _build_synthesis_prompt(all_data, last_profiles)

    log.info("Calling Opus for paired diarization...")
    response = client.messages.create(
        model=MODEL_OPUS,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    full_response = response.content[0].text

    user_profile, alicia_profile, delta = _parse_profiles(full_response)

    os.makedirs(PROFILES_DIR, exist_ok=True)

    user_path = os.path.join(PROFILES_DIR, f"{week_id}-user.md")
    alicia_path = os.path.join(PROFILES_DIR, f"{week_id}-alicia.md")
    delta_path = os.path.join(PROFILES_DIR, f"{week_id}-delta.md")

    atomic_write_text(user_path, user_profile)
    log.info(f"Saved {USER_NAME} profile to {user_path}")

    atomic_write_text(alicia_path, alicia_profile)
    log.info(f"Saved Alicia profile to {alicia_path}")

    # Persist delta so Telegram's build_system_prompt can read it between runs.
    # Previously delta lived only in the return value and vanished at process exit.
    atomic_write_text(delta_path, delta)
    log.info(f"Saved Delta to {delta_path}")

    return {
        "week_id": week_id,
        "user_profile": user_profile,
        "alicia_profile": alicia_profile,
        "delta": delta,
        "user_path": user_path,
        "alicia_path": alicia_path,
        "delta_path": delta_path,
    }


def _parse_profiles(response_text: str) -> tuple:
    """Parse the three markdown sections from Opus response."""

    sections = {"user": "", "alicia": "", "delta": ""}

    lines = response_text.split("\n")
    current_section = None
    buffer = []

    for line in lines:
        if line.startswith(f"# {USER_NAME} This Week"):
            if current_section and buffer:
                sections[current_section] = "\n".join(buffer).strip()
            current_section = "user"
            buffer = []
        elif line.startswith("# Alicia This Week"):
            if current_section and buffer:
                sections[current_section] = "\n".join(buffer).strip()
            current_section = "alicia"
            buffer = []
        elif line.startswith("# Delta from Last Week"):
            if current_section and buffer:
                sections[current_section] = "\n".join(buffer).strip()
            current_section = "delta"
            buffer = []
        elif current_section:
            buffer.append(line)

    if current_section and buffer:
        sections[current_section] = "\n".join(buffer).strip()

    week_id = _get_week_identifier()
    timestamp = datetime.now().isoformat()

    user_full = f"# {USER_NAME} This Week\n**Week:** {week_id}\n**Generated:** {timestamp}\n\n{sections['user']}"
    alicia_full = f"# Alicia This Week\n**Week:** {week_id}\n**Generated:** {timestamp}\n\n{sections['alicia']}"
    delta_full = f"# Delta from Last Week\n{sections['delta']}"

    return (user_full, alicia_full, delta_full)


def get_latest_profiles() -> dict:
    """Return the most recent the user and Alicia profiles, or None."""
    if not os.path.exists(PROFILES_DIR):
        return None

    profile_files = glob.glob(os.path.join(PROFILES_DIR, "*.md"))
    if not profile_files:
        return None

    profile_files.sort(reverse=True)

    user_candidates = [f for f in profile_files if "user" in f]
    alicia_candidates = [f for f in profile_files if "alicia" in f]

    if not user_candidates or not alicia_candidates:
        return None

    try:
        user = _load_file_content(user_candidates[0])
        alicia = _load_file_content(alicia_candidates[0])

        return {
            "user": user,
            "alicia": alicia,
            "user_path": user_candidates[0],
            "alicia_path": alicia_candidates[0],
            "timestamp": datetime.fromtimestamp(
                os.path.getmtime(user_candidates[0])
            ).isoformat(),
        }
    except Exception as e:
        log.warning(f"Failed to load latest profiles: {e}")
        return None


def get_profile_delta_context() -> str:
    """Return a brief context string from the latest delta for use in proactive messages."""
    latest = get_latest_profiles()
    if not latest:
        return "No profile context available yet."

    try:
        alicia_profile = latest.get("alicia", "")

        if "Resonance Alignment" in alicia_profile:
            start = alicia_profile.find("Resonance Alignment")
            end = alicia_profile.find("\n##", start + 1)
            if end == -1:
                end = alicia_profile.find("\n#", start + 1)
            if end == -1:
                end = len(alicia_profile)
            resonance_section = alicia_profile[start:end].strip()
            return f"**Recent Calibration Context:**\n{resonance_section[:500]}"

        return "Recent profile data available but parsing incomplete."
    except Exception as e:
        log.warning(f"Failed to extract delta context: {e}")
        return "Profile context extraction failed."


def _extract_markdown_section(text: str, header: str) -> str:
    """
    Extract a single markdown section by its leading header.

    Matches the exact header line (case-sensitive, trimmed). The section ends
    at the next same-or-higher-level header or end of document. Handles both
    '## Open Threads' and '**Open Threads**' bold-label styles used in
    person_diarization output.
    """
    if not text or not header:
        return ""

    lines = text.split("\n")
    header_patterns = (
        f"## {header}",
        f"### {header}",
        f"**{header}**",
        f"- **{header}**",
    )
    start_idx = -1
    matched_pattern = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in header_patterns:
            if stripped.startswith(pat):
                start_idx = i
                matched_pattern = pat
                break
        if start_idx >= 0:
            break

    if start_idx < 0:
        return ""

    # For bullet-style labels (- **Open Threads**), take the rest of that
    # bullet plus any continuation until the next top-level bullet / header.
    if matched_pattern and matched_pattern.startswith("- **"):
        section_lines = [lines[start_idx]]
        for j in range(start_idx + 1, len(lines)):
            nxt = lines[j]
            nxt_stripped = nxt.strip()
            if nxt_stripped.startswith("- **") or nxt_stripped.startswith("## ") or nxt_stripped.startswith("# "):
                break
            section_lines.append(nxt)
        return "\n".join(section_lines).strip()

    # For header-style sections, walk until next header of same-or-higher level.
    section_lines = [lines[start_idx]]
    for j in range(start_idx + 1, len(lines)):
        nxt_stripped = lines[j].strip()
        if nxt_stripped.startswith("# ") or nxt_stripped.startswith("## ") or nxt_stripped.startswith("### "):
            break
        section_lines.append(lines[j])
    return "\n".join(section_lines).strip()


def get_profile_context_for_prompt(max_chars: int = 1800) -> str:
    """
    Build a compact "This Week's Calibration" block for build_system_prompt.

    Pulls:
      - "Open Threads" from the latest user profile (unresolved questions
        that span conversations — the continuity hook).
      - The full "Delta from Last Week" file (what changed, calibration arc,
        partnership alignment).

    Returns a trimmed markdown string ready to inject after a
    "## This Week's Calibration" header, or "" if no profile data exists yet.
    This is the H1 "close the diarization loop" feature: refinements
    written on Sunday actually land back in Telegram's running context.
    """
    if not os.path.exists(PROFILES_DIR):
        return ""

    profile_files = sorted(
        glob.glob(os.path.join(PROFILES_DIR, "*.md")), reverse=True
    )
    if not profile_files:
        return ""

    user_files = [f for f in profile_files if f.endswith("-user.md")]
    delta_files = [f for f in profile_files if f.endswith("-delta.md")]

    parts: list[str] = []

    if user_files:
        try:
            user_text = Path(user_files[0]).read_text()
            open_threads = _extract_markdown_section(user_text, "Open Threads")
            if open_threads:
                parts.append(open_threads)
        except Exception as e:
            log.warning(f"Failed to read user profile: {e}")

    if delta_files:
        try:
            delta_text = Path(delta_files[0]).read_text().strip()
            if delta_text:
                parts.append(delta_text)
        except Exception as e:
            log.warning(f"Failed to read delta file: {e}")

    if not parts:
        # Fallback — better than nothing. Use the old resonance extractor.
        fallback = get_profile_delta_context()
        if fallback and "No profile context" not in fallback:
            parts.append(fallback)

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[: max_chars - 3].rstrip() + "..."
    return combined


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = run_paired_diarization()
    print(f"\nDiarization complete for week {result['week_id']}")
    print(f"{USER_NAME} profile: {result['user_path']}")
    print(f"Alicia profile: {result['alicia_path']}")
    print(f"\n--- Delta Summary ---\n{result['delta'][:500]}...")
