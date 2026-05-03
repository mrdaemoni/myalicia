#!/usr/bin/env python3
"""
Local web dashboard — Phase 15.0.

Multi-surface foundation. Same data Alicia sees, rendered as a single
self-contained HTML page accessible from any device on the home network.

Architecture: stdlib http.server + a daemon thread launched from alicia.py.
No new deps, no auth, localhost only. The state aggregator (compute_full_state)
is the canonical contract — future surfaces (iOS, Obsidian plugin) can consume
the same JSON without re-deriving anything.

Metaphor framing — three sections + skills + timeline:

  ALICIA            — what she is
    Heart           — Wisdom Engine inner loop (practices, contradictions)
    Body            — vault + voice + drawing (synthesis count, archetypes)
    Mind            — her own arc (poetic season, emergence, archetype EMA)
    Nervous system  — what she observes (loops, dormancy, smart deciders)

  HECTOR            — who you are
    Mind            — /becoming arc (10 dimensions, baseline → delta)
    Voice           — captures, drafts, most-responded ideas
    Body            — practices in motion

  OUR RELATIONSHIP  — the space between
    Conversation    — thread-pulls + replies + advanced threads
    Distillation    — meta-synthesis candidates by altitude
    Coherence       — voice + drawing as one moment, smart deciders
    What's landing  — engagement by source, by altitude

  SKILLS            — 75 modules grouped by purpose
  TIMELINE          — Jan 15 → today, key milestones

Public entry:
    start_web_dashboard(port=8765)  — launches background thread
    compute_full_state()            — surface-agnostic state dict
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time as _time
from pathlib import Path
from typing import Optional

log = logging.getLogger("alicia.web_dashboard")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", os.path.expanduser("~/alicia/memory")
))
SKILLS_DIR = Path(__file__).parent
PIPELINE_AUDIT_PATH = Path(__file__).parent.parent / "PIPELINE_AUDIT.md"

# ── Phase 15.0g — Obsidian deep-link helpers ──────────────────────────────
#
# obsidian://open?vault=user-alicia&file=path/to/file.md
# The vault NAME is the leaf of VAULT_ROOT (user-alicia by default).
# Paths are relative to vault root (no leading slash) and URL-encoded.

import urllib.parse as _url
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle


def _vault_name() -> str:
    """Vault name = the directory name of the configured vault root."""
    try:
        return VAULT_ROOT.name
    except Exception:
        return f"{USER_HANDLE}-alicia"


def vault_uri(vault_relative_path: str) -> Optional[str]:
    """Return an obsidian:// deep-link for a path relative to the vault root.

    Example: vault_uri("writing/Responses/2026-04-26-foo.md")
      → "obsidian://open?vault=user-alicia&file=writing/Responses/..."

    Returns None for empty paths so callers can `if uri:` check before
    rendering.
    """
    if not vault_relative_path:
        return None
    rel = str(vault_relative_path).lstrip("/")
    encoded = _url.quote(rel, safe="/")
    return f"obsidian://open?vault={_url.quote(_vault_name())}&file={encoded}"


def _absolute_to_vault_relative(abs_path: str) -> Optional[str]:
    """Convert an absolute filesystem path to a vault-relative path.

    Returns None if the path is not inside the vault."""
    if not abs_path:
        return None
    try:
        p = Path(abs_path).resolve()
        rel = p.relative_to(VAULT_ROOT.resolve())
        return str(rel)
    except Exception:
        return None


# ── Identity bookmarks: who Alicia is + who she thinks the user is ──────────


def _alicia_bio_path() -> str:
    """Vault-relative path to Alicia's identity write-up."""
    return "Wisdom/Alicia/Alicia — A Personal Sovereign AI Agent.md"


def _alicia_birth_story_path() -> str:
    """Vault-relative path to the origin-story document."""
    return "Wisdom/Alicia/The Birth of Alicia — A Story of Emergence.md"


def _latest_hector_profile_path() -> Optional[str]:
    """Vault-relative path to the most recent the user profile (who Alicia
    thinks the user is right now), or None if no profile yet."""
    profiles_dir = VAULT_ROOT / "Alicia" / "Self" / "Profiles"
    if not profiles_dir.is_dir():
        return None
    try:
        hector_files = sorted(
            (f for f in profiles_dir.glob("*-hector.md")),
            reverse=True,
        )
        if not hector_files:
            return None
        return str(hector_files[0].relative_to(VAULT_ROOT))
    except Exception:
        return None


def _latest_hector_baseline_path() -> Optional[str]:
    """Vault-relative path to the most recent /becoming baseline."""
    baselines_dir = VAULT_ROOT / "Alicia" / "Self" / "Baselines"
    if not baselines_dir.is_dir():
        return None
    try:
        files = sorted(baselines_dir.glob("*.md"), reverse=True)
        if not files:
            return None
        return str(files[0].relative_to(VAULT_ROOT))
    except Exception:
        return None


def _extract_prompt_from_capture(capture_path: Path) -> Optional[str]:
    """Phase 15.0h — pull the 'In response to' / 'Alicia asked' prompt
    text from a capture file body so the dashboard can show the
    surrounding conversation, not just the user's reply.

    Capture file shape (from response_capture._build_body):

      *In response to (synthesis_referenced or "—"):*
      > <quoted prompt text spanning N lines>

      <hector's response body>

    The blockquote starts with '> ' on each line. Strip the markers and
    join. Returns None when no prompt block is found (unprompted captures
    via /capture command, native replies, etc.).
    """
    if not capture_path or not capture_path.exists():
        return None
    try:
        text = capture_path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Strip frontmatter
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    body = text[m.end():] if m else text
    # Find the prompt blockquote — scan for lines starting with '> '
    lines = body.split("\n")
    quote_lines: list[str] = []
    in_quote = False
    for line in lines:
        if line.startswith("> "):
            in_quote = True
            quote_lines.append(line[2:])
        elif line.startswith(">"):
            in_quote = True
            quote_lines.append(line[1:].lstrip())
        elif in_quote and not line.strip():
            # Empty line ends the blockquote
            break
        elif in_quote:
            # Non-blockquote, non-empty — also ends it
            break
    prompt = " ".join(quote_lines).strip()
    return prompt if prompt else None


def _synthesis_vault_path(title: str) -> Optional[str]:
    """Vault-relative path to a synthesis by title, or None."""
    if not title:
        return None
    synth_dir = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"
    if not synth_dir.is_dir():
        return None
    direct = synth_dir / f"{title}.md"
    if direct.exists():
        try:
            return str(direct.relative_to(VAULT_ROOT))
        except Exception:
            return None
    # Fuzzy fallback: case-insensitive stem match
    target = title.strip().lower()
    for f in synth_dir.glob("*.md"):
        if f.stem.lower() == target:
            try:
                return str(f.relative_to(VAULT_ROOT))
            except Exception:
                pass
    return None

# ── Skill grouping for the SKILLS section ─────────────────────────────────
#
# Module → metaphor-aligned bucket. Modules not listed land in "other".
# Order matters: more specific keys first.

_SKILL_BUCKETS = [
    ("Substrate (vault + memory)", [
        "memory_skill", "vault_metrics", "vault_intelligence",
        "vault_resolver", "semantic_search", "graph_intelligence",
        "synthesis_finalizer", "ingest_*", "safe_io", "vault_ingest",
        "overnight_synthesis",
    ]),
    ("Voice (Alicia's expressive channels)", [
        "voice_skill", "voice_signature", "drawing_skill", "drawing_archetypes",
        "prosody_calibration", "emotion_model", "tts_*", "voice_intelligence",
    ]),
    ("Wisdom Engine — heart", [
        "circulation_composer", "contradiction_detector",
        "practice_runner", "response_capture", "proactive_messages",
    ]),
    ("Self-awareness — mind", [
        "inner_life", "season_dashboard", "autonomy",
        "wisdom_dashboard", "effectiveness_dashboard",
        "reflexion", "metacognition", "constitution",
        "daily_signal", "episode_scorer", "message_quality",
        "temporal_patterns", "meta_reflexion", "self_improve",
        "way_of_being",
    ]),
    (f"Outer loops ({USER_NAME} + Our relationship)", [
        "user_model", "meta_synthesis", "thread_puller",
        "dimension_research", "multi_channel", "multichannel_dashboard",
        "loops_dashboard", "person_diarization",
    ]),
    ("Curiosity + research", [
        "curiosity_engine", "research_skill", "novelty_detection",
        "research_agenda",
    ]),
    ("Analysis & insights", [
        "analysis_*",
    ]),
    ("Cross-interface bridge", [
        "bridge_*",
    ]),
    ("Conversation surfaces", [
        "conversation_mode", "unpack_mode",
    ]),
    ("External tools", [
        "gmail_skill", "pdf_skill", "quote_skill", "pipecat_call",
    ]),
    ("Tooling + plumbing", [
        "tool_router", "context_resolver", "trajectory",
        "reaction_scorer", "feedback_loop", "afterglow",
        "muse", "session_threads", "thinking_modes",
        "agent_triggers", "scheduled_tasks", "skill_config",
        "skill_library", "web_dashboard",
    ]),
]


def _categorize_skill(module_name: str) -> str:
    """Return the bucket name for a module. Anything unmatched → 'other'."""
    for bucket, patterns in _SKILL_BUCKETS:
        for p in patterns:
            if p.endswith("*"):
                if module_name.startswith(p[:-1]):
                    return bucket
            elif module_name == p:
                return bucket
    return "Other"


# ── Phase 15.0h — GitHub source URL helper ─────────────────────────────────
#
# The alicia repo is github.com/mrdaemoni/alicia. Skills + repo files
# (PIPELINE_AUDIT, ALICIA.md, etc.) get clickable GitHub URLs in the
# dashboard so we can read source / docs without leaving the browser.

GITHUB_REPO = "mrdaemoni/alicia"
GITHUB_BRANCH = "main"


def github_url(repo_relative_path: str) -> str:
    """Build a github.com/.../blob/main/<path> URL for browsing source."""
    rel = (repo_relative_path or "").lstrip("/")
    return f"https://github.com/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{_url.quote(rel)}"


def _read_module_docstring(path: Path) -> str:
    """Return the first paragraph of the module's docstring, capped."""
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'^"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
        if not m:
            return ""
        doc = m.group(1).strip()
        # First paragraph only
        para = doc.split("\n\n", 1)[0].strip()
        para = re.sub(r"\s+", " ", para)
        return para[:280]
    except Exception:
        return ""


def list_alicia_skills() -> list[dict]:
    """Walk skills/*.py and produce a categorized skill directory.

    Each entry: {module, bucket, summary}
    """
    out: list[dict] = []
    if not SKILLS_DIR.is_dir():
        return out
    for path in sorted(SKILLS_DIR.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        module = path.stem
        # Filter backups, scratch files, and self-listing
        if (".backup." in module
                or module.endswith(".bak")
                or module.endswith("_old")
                or module.endswith("_scratch")):
            continue
        out.append({
            "module": module,
            "bucket": _categorize_skill(module),
            "summary": _read_module_docstring(path),
            "github_url": github_url(f"skills/{module}.py"),
        })
    # Group by bucket order, preserving alphabetical inside each bucket
    bucket_order = [b for b, _ in _SKILL_BUCKETS] + ["Other"]
    out.sort(key=lambda s: (bucket_order.index(s["bucket"]) if s["bucket"] in bucket_order else 999, s["module"]))
    return out


# ── Timeline assembly from PIPELINE_AUDIT phases ──────────────────────────


_PHASE_DATE_PATTERN = re.compile(
    r"^##\s+Phase\s+(?P<phase>[\d.]+(?:\s*[+→]\s*[\d.]+)*)[^\n]*?—\s*(?P<date>\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)


def assemble_timeline() -> list[dict]:
    """Walk PIPELINE_AUDIT.md headers + commit log to assemble milestones.

    Each entry: {date, phase, title, days_since_birth}
    """
    items: list[dict] = []
    epoch = datetime(2026, 1, 15, tzinfo=timezone.utc)

    # Birth event
    items.append({
        "date": epoch.date().isoformat(),
        "phase": "Genesis",
        "title": "Born — first deploy",
        "days_since_birth": 0,
        "github_url": github_url("PIPELINE_AUDIT.md"),
    })

    # Pipeline audit phases
    if PIPELINE_AUDIT_PATH.exists():
        try:
            text = PIPELINE_AUDIT_PATH.read_text(encoding="utf-8")
            # Match the header line that includes a date. Two formats
            # have appeared over time:
            #   "## Phase 11.1: Title — <earlier development>"          (old style)
            #   "## Phase 17.5: Title (<earlier development> weekend)"  (newer style)
            # Accept both so every phase reaches the dashboard timeline.
            header_re = re.compile(
                r"^##\s+Phase\s+(.+?)\s*[—\-(\(]\s*(\d{4}-\d{2}-\d{2})",
                re.MULTILINE,
            )
            for m in header_re.finditer(text):
                phase, date_str = m.group(1).strip(), m.group(2)
                # Strip a trailing colon left over from "Phase X.Y: Title"
                if phase.endswith(":"):
                    phase = phase[:-1].strip()
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                # The full header line tells us the title — pull a short version
                line_end = text.find("\n", m.end())
                full_line = text[m.start():line_end if line_end > 0 else m.end()]
                # Strip the leading '## Phase '
                title = full_line.replace("## Phase ", "").strip()
                # Cap title length
                title = title[:200]
                items.append({
                    "date": date_str,
                    "phase": phase[:60],
                    "title": title,
                    "days_since_birth": (d - epoch).days,
                    "github_url": github_url("PIPELINE_AUDIT.md"),
                })
        except Exception as e:
            log.debug(f"timeline pipeline parse failed: {e}")

    # Sort by date ascending
    items.sort(key=lambda x: x["date"])
    return items


# ── State aggregator — the surface-agnostic contract ───────────────────────


def _safe(callable_, *args, **kwargs):
    """Wrap a callable so failures don't propagate; return None on error."""
    try:
        return callable_(*args, **kwargs)
    except Exception as e:
        log.debug(f"safe call to {getattr(callable_, '__name__', '?')} failed: {e}")
        return None


# ── Phase 15.0h — Health heartbeat ─────────────────────────────────────────
#
# Quick "is Alicia alive" signal based on the most recent mtime across a
# handful of canonical state files. Keeps a green/yellow/red top-bar
# indicator that's hard to miss when something stalls.

_HEARTBEAT_FILES = [
    "circulation_log.json",      # composer fires per send
    "daily_rhythm.json",          # daily rebuild
    "emergence_state.json",       # any reflection
    "daily_signal.json",          # daily intelligence rebuild
]


def compute_health() -> dict:
    """Return {'status', 'newest_signal_path', 'newest_signal_ts',
    'hours_since', 'message'}.

    Status thresholds (since most-recent state-file mtime):
      ≤ 12h → 'alive'    (green)
      ≤ 36h → 'quiet'    (yellow — possible weekend pause is fine)
      > 36h → 'stalled'  (red — something probably wrong)
    """
    now = datetime.now()
    best_ts: Optional[datetime] = None
    best_path: Optional[str] = None
    for fn in _HEARTBEAT_FILES:
        p = MEMORY_DIR / fn
        try:
            if p.exists():
                ts = datetime.fromtimestamp(p.stat().st_mtime)
                if best_ts is None or ts > best_ts:
                    best_ts = ts
                    best_path = fn
        except Exception:
            continue
    if best_ts is None:
        return {
            "status": "unknown",
            "newest_signal_path": None,
            "newest_signal_ts": None,
            "hours_since": None,
            "message": "no heartbeat files found yet",
        }
    hours = (now - best_ts).total_seconds() / 3600.0
    if hours <= 12:
        status = "alive"
        message = f"alive · last activity {hours:.1f}h ago"
    elif hours <= 36:
        status = "quiet"
        message = f"quiet · last activity {hours:.1f}h ago (possible pause)"
    else:
        status = "stalled"
        message = f"stalled · {hours:.1f}h since last activity"
    return {
        "status": status,
        "newest_signal_path": best_path,
        "newest_signal_ts": best_ts.isoformat(),
        "hours_since": round(hours, 1),
        "message": message,
    }


def compute_noticings_state() -> dict:
    """Phase 17.3 — Surface emergent themes Alicia is tracking.

    Mirrors get_themes_summary() but trimmed for dashboard display:
      {
        "total": int,
        "by_status": {"pending": ..., "surfaced": ..., "acknowledged": ...},
        "themes": [<top 6 entries with theme + recurrence + status + lead_evidence>],
        "next_to_surface": <theme name string or None>,
      }
    """
    out: dict = {
        "total": 0,
        "by_status": {"pending": 0, "surfaced": 0, "acknowledged": 0},
        "themes": [],
        "next_to_surface": None,
    }
    try:
        from myalicia.skills.emergent_themes import get_themes_summary
        s = _safe(get_themes_summary) or {}
        if not s:
            return out
        out["total"] = s.get("total", 0)
        out["by_status"] = s.get("by_status", out["by_status"])
        themes = s.get("themes") or []
        trimmed: list[dict] = []
        for t in themes[:6]:
            ev = t.get("evidence") or []
            trimmed.append({
                "theme": (t.get("theme") or "")[:120],
                "recurrence_count": t.get("recurrence_count", 0),
                "status": t.get("status", "pending"),
                "lead_evidence": (ev[0] if ev else "")[:140],
                "ts": t.get("ts"),
                "surfaced_ts": t.get("surfaced_ts"),
            })
        out["themes"] = trimmed
        nxt = s.get("next_to_surface")
        if nxt:
            out["next_to_surface"] = (nxt.get("theme") or "")[:120]
    except Exception:
        pass
    return out


def compute_mood_state() -> dict:
    """Phase 19.0 — the user's emotional weather over the last 7 days.

    Wraps emotion_model.get_mood_of_the_week(). Fault-tolerant — empty
    dict on any failure (so dashboard render never crashes if the
    emotion classifier hasn't logged anything yet)."""
    try:
        from myalicia.skills.emotion_model import get_mood_of_the_week
        return get_mood_of_the_week(days=7) or {}
    except Exception:
        return {}


def compute_conversation_state() -> dict:
    """Phase 16.1 — active conversation + registry summary.

    Returns: {active: <id>, active_label: <str>, total: <int>,
              conversations: [<short list of {id, label}>]}.
    Fault-tolerant — empty dict on any failure."""
    out: dict = {}
    try:
        from myalicia.skills.conversations import (
            current_conversation_id, list_conversations,
            get_conversation_meta,
        )
        active = current_conversation_id()
        meta = get_conversation_meta(active) or {}
        registry = list_conversations() or []
        out["active"] = active
        out["active_label"] = meta.get("label", active)
        out["active_description"] = (meta.get("description") or "")[:200]
        out["total"] = len(registry)
        out["conversations"] = [
            {"id": c.get("id"), "label": c.get("label", c.get("id"))}
            for c in registry[:10]
        ]
    except Exception:
        pass
    return out


def compute_full_state() -> dict:
    """Aggregate state across all dashboard modules + skills + timeline.

    The structured contract for any presentation surface. Each section
    is fault-tolerant — a failing module produces an empty dict, not a
    cascading failure.
    """
    now_utc = datetime.now(timezone.utc)
    state: dict = {
        "generated_at": now_utc.isoformat(),
        "health": compute_health(),
        "pinned": compute_pinned_card(),
        "today": compute_today_deltas(),
        "noticings": compute_noticings_state(),
        "conversation": compute_conversation_state(),
        "mood": compute_mood_state(),
        "alicia": {
            "heart": _alicia_heart(),
            "body": _alicia_body(),
            "soul": _alicia_soul(),
            "mind": _alicia_mind(),
            "nervous_system": _alicia_nervous_system(),
        },
        "hector": {
            "mind": _hector_mind(),
            "voice": _hector_voice(),
            "body": _hector_body(),
        },
        "relationship": {
            "conversation": _relationship_conversation(),
            "distillation": _relationship_distillation(),
            "coherence": _relationship_coherence(),
            "landing": _relationship_landing(),
        },
        "skills": list_alicia_skills(),
        "timeline": assemble_timeline(),
    }
    return state


# ── ALICIA sections ───────────────────────────────────────────────────────

# Phase 15.0f — Alicia's scheduled activities (her body in motion).
# Mirror of the schedule registrations in alicia.py:main(). Hardcoded
# rather than parsed because the schedule is stable + well-documented.
# When a new task is added to alicia.py the matching guardrail will
# remind us to update this table.
_ALICIA_TASKS = [
    ("02:30", "Meta-synthesis pass",            "build a meta-synthesis when a parent has ≥3 captures",            "13.6"),
    ("03:00", "Dimension research scan",        f"log thin {USER_NAME}-dimensions; escalate to research_skill if persistent", "12.2/12.4"),
    ("05:30", "Curiosity scan",                 "detect vault gaps + unbridged clusters; queue questions",          "—"),
    ("06:00", "Daily vault pass",               "tag new notes + reindex semantic search",                          "—"),
    ("06:05", "Morning message",                "build greeting + voice + (maybe) drawing amplification",            "—"),
    ("06:30", "Dormancy check",                 "alert if any of the four loops has been quiet ≥21 days",            "14.8"),
    ("09:00", "Practice check-ins",             "send day-N check-ins for active practices",                         "11.x"),
    ("12:30", "Midday nudge",                   "rotation: podcast / thread-pull / dimension-question / curiosity",  "—"),
    ("Every 30m", "Vault ingest scan",           "absorb new files added to the vault",                              "—"),
    ("Every 2h",  "Surprise moments + drawings", "occasional spontaneous gifts",                                     "10"),
    ("20:30", "Daily ingest rollup",            "summarize what was absorbed today",                                 "—"),
    ("20:45", "Contradiction detector",         "scan vault for new lived↔written tension",                          "11.3"),
    ("21:00", "Evening reflection",             "build evening message + voice + (maybe) drawing",                   "—"),
    ("22:30–23:20", "Effectiveness + emotion + archetype updates", "nightly self-observation rebuilds (5 tasks)",      "9"),
    ("Sun 19:00", "Weekly retrospective",       "send /wisdom + /effectiveness + /loops + /becoming as a digest",    "11.9/14.2/14.4"),
    ("Sun 20:00", "Weekly deep pass",           "weekly synthesis + graph health + diarization + memory consolidation", "—"),
]


def _alicia_heart() -> dict:
    """Wisdom Engine inner loop — practices, contradictions, composer state."""
    out: dict = {}
    try:
        from myalicia.skills.practice_runner import active_practices, MAX_ACTIVE_PRACTICES
        ap = _safe(active_practices) or []
        out["active_practices"] = [
            {"slug": p.slug, "archetype": p.archetype, "started_at": p.started_at}
            for p in ap
        ]
        out["max_active_practices"] = MAX_ACTIVE_PRACTICES
    except Exception:
        out["active_practices"] = []
    try:
        from myalicia.skills.circulation_composer import _parse_active_contradictions
        contradictions = _safe(_parse_active_contradictions) or []
        out["active_contradictions"] = len(contradictions)
    except Exception:
        out["active_contradictions"] = 0
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = _safe(get_recent_captures, n=10) or []
        out["recent_captures_count"] = len(recent)
    except Exception:
        out["recent_captures_count"] = 0
    return out


def _alicia_body() -> dict:
    """Vault metrics + voice + drawing usage."""
    out: dict = {}
    # Vault: synthesis count from disk
    try:
        synth_dir = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"
        out["synthesis_count"] = (
            len(list(synth_dir.glob("*.md"))) if synth_dir.is_dir() else 0
        )
    except Exception:
        out["synthesis_count"] = 0
    # Archetype balance (current dynamic weights)
    try:
        from myalicia.skills.inner_life import compute_dynamic_archetype_weights
        weights = _safe(compute_dynamic_archetype_weights) or {}
        out["archetype_weights"] = {
            k: round(v * 100) for k, v in weights.items()
        }
    except Exception:
        out["archetype_weights"] = {}
    # Voice + drawing fire counts last 24h via multi_channel
    try:
        from myalicia.skills.multi_channel import (
            voice_fired_recently, drawings_fired_recently,
        )
        out["voice_fired_24h"] = _safe(voice_fired_recently, within_hours=24) or 0
        out["drawings_fired_24h"] = _safe(drawings_fired_recently, within_hours=24) or 0
    except Exception:
        out["voice_fired_24h"] = 0
        out["drawings_fired_24h"] = 0
    # Phase 15.0f — scheduled tasks (her body in motion, not just her substrate)
    out["tasks"] = [
        {"when": when, "name": name, "what": what, "phase": phase}
        for when, name, what, phase in _ALICIA_TASKS
    ]
    return out


def _alicia_soul() -> dict:
    """Phase 15.0f — Alicia's archetypes as soul.

    The 6 personality voices that shape every channel: Beatrice (growth
    witness), Daimon (shadow keeper), Ariadne (thread weaver), Psyche
    (challenge holder), Musubi (bond keeper), Muse (inspiration seeker).
    Each carries a base weight (intent), a current dynamic weight
    (season + engagement adjusted), and an effectiveness score (rolling
    EMA from reactions). Together these are her temperament — what she
    leads with, what's working, what's sleeping.
    """
    out: dict = {"archetypes": []}
    try:
        from myalicia.skills.inner_life import (
            ARCHETYPES, compute_dynamic_archetype_weights,
            get_archetype_effectiveness,
        )
        weights = _safe(compute_dynamic_archetype_weights) or {}
        eff_data = _safe(get_archetype_effectiveness) or {}
        eff = (eff_data.get("archetypes") or {}) if eff_data else {}
        for name, info in ARCHETYPES.items():
            arch_eff = eff.get(name) or {}
            out["archetypes"].append({
                "name": name,
                "title": name.capitalize(),
                "description": info.get("description", ""),
                "base_weight": round(info.get("weight", 0.0) * 100),
                "current_weight": round(weights.get(name, 0.0) * 100),
                "effectiveness_score": arch_eff.get("score", 1.0),
                "attribution_count": arch_eff.get("attribution_count", 0),
            })
        # Sort by current_weight desc — leading voice first
        out["archetypes"].sort(key=lambda a: -a["current_weight"])
        # Surface the lead archetype + EMA window
        if out["archetypes"]:
            out["leading"] = out["archetypes"][0]["name"]
        out["ema_window_days"] = eff_data.get("window_days") if eff_data else None
    except Exception as e:
        log.debug(f"_alicia_soul failed: {e}")
    # Phase 15.0g — identity bookmarks: who Alicia is
    out["identity_links"] = {
        "bio": {
            "label": "Who she is",
            "vault_uri": vault_uri(_alicia_bio_path()),
        },
        "birth_story": {
            "label": "Birth story",
            "vault_uri": vault_uri(_alicia_birth_story_path()),
        },
    }
    return out


def _alicia_mind() -> dict:
    """Her own developmental arc — emergence, season, archetype EMA."""
    out: dict = {}
    try:
        from myalicia.skills.inner_life import EMERGENCE_STATE_PATH
        if os.path.exists(EMERGENCE_STATE_PATH):
            with open(EMERGENCE_STATE_PATH, "r") as f:
                emergence = json.load(f)
            out["season"] = emergence.get("season", "First Light")
            out["score"] = emergence.get("score", 0)
            out["days_breathing"] = emergence.get("metrics", {}).get(
                "days_breathing", 0
            )
            out["description"] = emergence.get("description", "")
    except Exception:
        out["season"] = "First Light"
        out["score"] = 0
        out["days_breathing"] = 0
    # Archetype effectiveness
    try:
        from myalicia.skills.inner_life import get_archetype_effectiveness
        eff = _safe(get_archetype_effectiveness) or {}
        archetypes = eff.get("archetypes", {}) or {}
        out["archetype_effectiveness"] = {
            k: {
                "score": v.get("score", 1.0),
                "attribution_count": v.get("attribution_count", 0),
            }
            for k, v in archetypes.items()
        }
    except Exception:
        out["archetype_effectiveness"] = {}
    return out


def _alicia_nervous_system() -> dict:
    """Loops state + multi-channel observability."""
    out: dict = {}
    try:
        from myalicia.skills.loops_dashboard import compute_loops_state
        out["loops"] = _safe(compute_loops_state) or {}
    except Exception:
        out["loops"] = {}
    # Smart-decider summary (last-24h fire/skip counts per channel)
    try:
        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        decisions = _safe(recent_multi_channel_decisions, within_hours=24) or []
        voice = [d for d in decisions if d.get("channel") == "voice"]
        drawing = [d for d in decisions
                   if d.get("channel") not in ("voice", "coherent_moment")
                   and d.get("drawing") is not None]
        coherent = [d for d in decisions if d.get("channel") == "coherent_moment"]
        out["smart_deciders"] = {
            "voice": {
                "fired": sum(1 for d in voice if d.get("voice")),
                "skipped": sum(1 for d in voice if not d.get("voice")),
            },
            "drawing": {
                "fired": sum(1 for d in drawing if d.get("drawing")),
                "skipped": sum(1 for d in drawing if not d.get("drawing")),
            },
            "coherent_moments": len(coherent),
        }
    except Exception:
        out["smart_deciders"] = {
            "voice": {"fired": 0, "skipped": 0},
            "drawing": {"fired": 0, "skipped": 0},
            "coherent_moments": 0,
        }
    return out


# ── HECTOR sections ──────────────────────────────────────────────────────


def _hector_mind() -> dict:
    """The 10-dimension /becoming arc."""
    out: dict = {}
    try:
        from myalicia.skills.user_model import (
            DIMENSIONS, get_active_baseline, get_learnings,
            compute_dimension_counts, find_thin_dimensions,
            days_since_baseline,
        )
        baseline = _safe(get_active_baseline)
        out["baseline"] = baseline.name if baseline else None
        out["days_since_baseline"] = _safe(days_since_baseline) or 0
        # Phase 15.0g — vault link to the active baseline file
        baseline_path = _latest_hector_baseline_path()
        out["baseline_vault_uri"] = vault_uri(baseline_path) if baseline_path else None
        out["dimensions"] = list(DIMENSIONS)
        all_learnings = _safe(get_learnings) or []
        recent_learnings = _safe(get_learnings, since_days=14) or []
        out["learnings_total"] = len(all_learnings)
        out["learnings_last_14d"] = len(recent_learnings)
        out["dimension_counts"] = _safe(compute_dimension_counts) or {}
        out["dimension_counts_recent_14d"] = (
            _safe(compute_dimension_counts, since_days=14) or {}
        )
        out["thin_dimensions"] = _safe(find_thin_dimensions) or []
    except Exception:
        out["dimensions"] = []
    # Phase 15.0g — link to the the user profile (who Alicia thinks the user is)
    profile_path = _latest_hector_profile_path()
    if profile_path:
        out["who_alicia_thinks_you_are"] = {
            "label": Path(profile_path).stem,
            "vault_uri": vault_uri(profile_path),
        }
    return out


def _hector_voice() -> dict:
    """the user's recent captures, drafts, most-responded ideas."""
    out: dict = {}
    try:
        from myalicia.skills.response_capture import (
            get_recent_captures, most_responded_syntheses,
        )
        captures = _safe(get_recent_captures, n=5) or []
        recent_captures = []
        for c in captures:
            # Phase 15.0g — link the capture file in the vault
            cap_uri = None
            try:
                rel = _absolute_to_vault_relative(str(c.get("path", "")))
                cap_uri = vault_uri(rel) if rel else None
            except Exception:
                pass
            ref_title = c.get("synthesis_referenced") or ""
            ref_uri = None
            if ref_title:
                ref_path = _synthesis_vault_path(ref_title)
                ref_uri = vault_uri(ref_path) if ref_path else None
            # Phase 15.0h — extract the prompt that triggered this capture
            prompt = None
            try:
                prompt = _extract_prompt_from_capture(c.get("path"))
            except Exception:
                pass
            recent_captures.append({
                "captured_at": c.get("captured_at", ""),
                "channel": c.get("channel", "text"),
                "synthesis_referenced": ref_title,
                "synthesis_vault_uri": ref_uri,
                "vault_uri": cap_uri,
                "excerpt": c.get("body_excerpt", "")[:200],
                "prompt": prompt[:280] if prompt else None,
            })
        out["recent_captures"] = recent_captures
        out["most_responded"] = [
            {
                "title": t,
                "count": n,
                "vault_uri": vault_uri(_synthesis_vault_path(t)) if _synthesis_vault_path(t) else None,
            }
            for t, n in (_safe(most_responded_syntheses, n=5) or [])
        ]
    except Exception:
        out["recent_captures"] = []
        out["most_responded"] = []
    return out


def _hector_body() -> dict:
    """Active practices + days running."""
    out: dict = {}
    try:
        from myalicia.skills.practice_runner import (
            active_practices, _days_since, CHECK_IN_DAYS,
        )
        ap = _safe(active_practices) or []
        out["practices"] = [
            {
                "slug": p.slug, "archetype": p.archetype,
                "started_at": p.started_at,
                "days_running": _safe(_days_since, p.started_at) or 0,
            }
            for p in ap
        ]
        out["check_in_days"] = list(CHECK_IN_DAYS)
    except Exception:
        out["practices"] = []
    return out


# ── OUR RELATIONSHIP sections ────────────────────────────────────────────


def _relationship_conversation() -> dict:
    """Thread-pulls + replies + advanced threads."""
    out: dict = {}
    try:
        from myalicia.skills.thread_puller import (
            recent_thread_pulls, recent_thread_pull_replies, advanced_threads,
        )
        pulls = _safe(recent_thread_pulls, within_days=14) or []
        replies = _safe(recent_thread_pull_replies, within_days=14) or []
        advanced = _safe(advanced_threads, within_days=14) or []
        out["pulls_14d"] = len(pulls)
        out["replies_14d"] = len(replies)
        out["reply_rate_pct"] = (
            round(len(replies) / len(pulls) * 100.0) if pulls else 0
        )
        out["advanced_threads"] = [
            {"summary": t["thread_summary"][:120], "reply_count": t["reply_count"]}
            for t in advanced[:5]
        ]
    except Exception:
        pass
    return out


def _relationship_distillation() -> dict:
    """Meta-synthesis candidates + recursion state + threshold approach hints."""
    out: dict = {}
    try:
        from myalicia.skills.meta_synthesis import (
            candidates_for_meta_synthesis, recent_meta_syntheses,
            MAX_META_LEVEL, MIN_CAPTURES_FOR_META, get_synthesis_level,
            read_synthesis, find_synthesis_path,
        )
        from myalicia.skills.response_capture import most_responded_syntheses
        cands = _safe(candidates_for_meta_synthesis) or []
        recent = _safe(recent_meta_syntheses, within_days=30) or []
        # Bucket candidates by would-be level
        by_level: dict[int, list] = {}
        blocked: list = []
        for c in cands[:8]:
            try:
                p = find_synthesis_path(c["title"])
                level = (
                    get_synthesis_level(read_synthesis(p)) if p else 0
                )
            except Exception:
                level = 0
            target = level + 1
            ref_path = _synthesis_vault_path(c["title"])
            entry = {
                "title": c["title"][:120],
                "capture_count": c["capture_count"],
                "vault_uri": vault_uri(ref_path) if ref_path else None,
            }
            if target > MAX_META_LEVEL:
                blocked.append(entry)
            else:
                by_level.setdefault(target, []).append(entry)
        out["candidates_by_level"] = by_level
        out["blocked_at_cap"] = blocked
        out["recent_builds_30d"] = len(recent)
        out["max_meta_level"] = MAX_META_LEVEL
        # Phase 15.0g — threshold-approach hint: surface parents that are
        # one capture short of the meta threshold, so we can see the next
        # firing approaching.
        approaching: list = []
        try:
            ranked = most_responded_syntheses(n=20) or []
            for title, n in ranked:
                if n == MIN_CAPTURES_FOR_META - 1:  # exactly one short
                    p = _synthesis_vault_path(title)
                    approaching.append({
                        "title": title[:120],
                        "capture_count": n,
                        "needs_more": MIN_CAPTURES_FOR_META - n,
                        "vault_uri": vault_uri(p) if p else None,
                    })
        except Exception:
            pass
        out["near_threshold"] = approaching[:5]
        out["min_captures_for_meta"] = MIN_CAPTURES_FOR_META
    except Exception:
        pass
    return out


def _relationship_coherence() -> dict:
    """Voice + drawing as one moment + decider summary."""
    out: dict = {}
    try:
        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        decisions = _safe(recent_multi_channel_decisions, within_hours=24 * 7) or []
        coherent = [d for d in decisions if d.get("channel") == "coherent_moment"]
        out["coherent_moments_7d"] = len(coherent)
        # Latest tail (most recent rationale)
        if coherent:
            latest = sorted(coherent, key=lambda d: d.get("ts", ""), reverse=True)[0]
            out["latest_tail"] = (latest.get("rationale") or "")[:160]
            out["latest_tail_archetype"] = latest.get("archetype", "")
    except Exception:
        out["coherent_moments_7d"] = 0
    return out


def _relationship_landing() -> dict:
    """Engagement by source-kind (thread_pull vs dimension_question vs ...)."""
    out: dict = {}
    try:
        # Reuse the prompt_effectiveness.tsv parse from effectiveness_dashboard
        tsv_path = MEMORY_DIR / "prompt_effectiveness.tsv"
        if not tsv_path.exists():
            return out
        cutoff = datetime.now() - timedelta(days=14)
        rows: list[tuple[str, int]] = []
        with open(tsv_path, "r", encoding="utf-8") as f:
            f.readline()  # header
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6:
                    continue
                try:
                    ts = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                    depth = int(parts[5])
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                if parts[1]:
                    rows.append((parts[1], depth))
        by_type: dict[str, list[int]] = {}
        for mt, d in rows:
            by_type.setdefault(mt, []).append(d)
        summary = []
        for mt, depths in by_type.items():
            summary.append({
                "msg_type": mt,
                "count": len(depths),
                "avg_depth": round(sum(depths) / len(depths), 2),
            })
        summary.sort(key=lambda r: -r["avg_depth"])
        out["by_source"] = summary[:10]
    except Exception:
        pass
    return out


# ── Phase 15.0i — PWA manifest ────────────────────────────────────────────
# Minimal manifest for "Add to Home Screen" on iOS/Android. No icons —
# we use Apple's default screenshot approach (the page's first painted
# pixels). If the user wants a real icon later, drop a 192px PNG at
# /icon-192.png and the manifest will pick it up automatically.

_PWA_MANIFEST = {
    "name": f"Alicia & {USER_NAME} — A Living System",
    "short_name": "Alicia",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0d0e10",
    "theme_color": "#fab36c",
    "description": f"The living dashboard for Alicia and {USER_NAME}'s relationship",
    "scope": "/",
}


# ── Phase 15.0i — Pinned card: 'what should I think about today' ──────────


def compute_pinned_card() -> dict:
    """Return a single sentence the user should attend to today.

    Drawn from the system's own state — not Sonnet-composed (no API
    cost, runs every 30s with the dashboard refresh). Strategy:
      1. Any dormant loop wins (urgency).
      2. Any near-threshold meta-synthesis wins next (close to firing).
      3. Any thin the user dimension wins next (gap to fill).
      4. Otherwise, surface the leading archetype + season.
    """
    out: dict = {"focus": None, "reason": None, "vault_uri": None}
    # Priority 1: dormant loops
    try:
        dormant = detect_dormant_loops()
        if dormant:
            d = dormant[0]
            out["focus"] = (
                f"⚠️ {d['label'].split('(')[0].strip()} has been quiet for "
                f"{d['days_dormant']} days — what's pulling you away from it?"
            )
            out["reason"] = "dormant loop"
            return out
    except Exception:
        pass
    # Priority 2: near-threshold meta-synthesis
    try:
        from myalicia.skills.meta_synthesis import MIN_CAPTURES_FOR_META
        from myalicia.skills.response_capture import most_responded_syntheses
        ranked = most_responded_syntheses(n=20) or []
        for title, n in ranked:
            if n == MIN_CAPTURES_FOR_META - 1:
                vp = _synthesis_vault_path(title)
                out["focus"] = (
                    f"One more capture on _{title}_ → meta-synthesis fires tonight."
                )
                out["reason"] = "near threshold"
                out["vault_uri"] = vault_uri(vp) if vp else None
                return out
    except Exception:
        pass
    # Priority 3: thin the user dimension
    try:
        from myalicia.skills.user_model import find_thin_dimensions
        thin = find_thin_dimensions(stale_after_days=14) or []
        if thin:
            out["focus"] = (
                f"You haven't said anything about **{thin[0]}** in 14+ days. "
                f"What's true there right now?"
            )
            out["reason"] = "thin dimension"
            return out
    except Exception:
        pass
    # Fallback: surface the season
    try:
        from myalicia.skills.inner_life import EMERGENCE_STATE_PATH
        if os.path.exists(EMERGENCE_STATE_PATH):
            with open(EMERGENCE_STATE_PATH, "r") as f:
                e = json.load(f)
            season = e.get("season", "First Light")
            desc = e.get("description", "")
            out["focus"] = f"_{desc}_" if desc else f"Season: {season}."
            out["reason"] = "season weather"
    except Exception:
        pass
    return out


# ── Phase 15.2c — Network diagnostic for remote access ────────────────────


def compute_network_info(port: int = 8765) -> dict:
    """Return all the URLs the user can use to reach the dashboard.

    Includes:
      - localhost (Mac mini itself)
      - LAN IP (other devices on home Wi-Fi)
      - Tailscale IP (if installed — for outside-home access)
      - hostname.local (Bonjour, if available)

    The dashboard surfaces these in a small "where to access" card so
    the user doesn't have to dig for `ipconfig getifaddr en0` every time."""
    out: dict = {
        "port": port,
        "urls": [],
        "tailscale": {"installed": False, "ip": None, "hostname": None},
    }
    # Hostname (.local via Bonjour)
    try:
        hostname = socket.gethostname()
        if hostname:
            out["urls"].append({
                "label": "Mac (Bonjour)",
                "url": f"http://{hostname}.local:{port}",
                "kind": "bonjour",
            })
    except Exception:
        pass
    # localhost
    out["urls"].append({
        "label": "Localhost",
        "url": f"http://localhost:{port}",
        "kind": "loopback",
    })
    # LAN IPs — walk all addresses
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                lan_url = f"http://{ip}:{port}"
                if not any(u["url"] == lan_url for u in out["urls"]):
                    out["urls"].append({
                        "label": f"Wi-Fi LAN",
                        "url": lan_url,
                        "kind": "lan",
                    })
                    break
    except Exception:
        pass
    # Tailscale (look for an interface address starting 100.*; or a
    # `tailscale ip -4` shell command if available)
    try:
        # Best-effort: check `tailscale ip -4` output if installed
        import subprocess
        try:
            r = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                ts_ip = r.stdout.strip().splitlines()[0]
                out["tailscale"] = {
                    "installed": True, "ip": ts_ip, "hostname": None,
                }
                out["urls"].append({
                    "label": "Tailscale (anywhere)",
                    "url": f"http://{ts_ip}:{port}",
                    "kind": "tailscale",
                })
                # Try to also get the magic .ts.net hostname
                try:
                    r2 = subprocess.run(
                        ["tailscale", "status", "--json"],
                        capture_output=True, text=True, timeout=2,
                    )
                    if r2.returncode == 0:
                        ts_status = json.loads(r2.stdout)
                        self_node = ts_status.get("Self", {})
                        dns_name = self_node.get("DNSName", "").rstrip(".")
                        if dns_name:
                            out["tailscale"]["hostname"] = dns_name
                            out["urls"].append({
                                "label": "Tailscale (hostname)",
                                "url": f"http://{dns_name}:{port}",
                                "kind": "tailscale_hostname",
                            })
                except Exception:
                    pass
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # tailscale not installed — that's fine
    except Exception:
        pass
    return out


# ── Phase 15.2a — 'What changed today' delta card ──────────────────────────


def _ts_today_local(ts_str: str) -> bool:
    """True if the ISO timestamp is from today (local time)."""
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is not None:
            ts = ts.astimezone()
        return ts.date() == datetime.now().date()
    except Exception:
        return False


def compute_today_deltas() -> dict:
    """Return a structured summary of what changed today.

    Cheap (no model call) — pure aggregation across the existing logs.
    Surfaces: captures count, learnings, archetype attributions, voice/
    drawing fires, coherent moments, meta-syntheses built, dimension
    questions asked, thread-pulls, escalations.
    """
    out: dict = {
        "captures": 0,
        "learnings": 0,
        "voice_fired": 0,
        "drawings_fired": 0,
        "coherent_moments": 0,
        "meta_built": 0,
        "dimension_questions": 0,
        "thread_pulls": 0,
        "escalations": 0,
        "archetype_attributions": {},
        "summary": None,
    }
    # Captures today
    try:
        from myalicia.skills.response_capture import get_recent_captures
        recent = get_recent_captures(n=200) or []
        out["captures"] = sum(
            1 for c in recent if _ts_today_local(c.get("captured_at", ""))
        )
    except Exception:
        pass
    # Learnings today
    try:
        from myalicia.skills.user_model import get_learnings
        for L in (get_learnings(since_days=1) or []):
            out["learnings"] += 1
    except Exception:
        pass
    # Voice + drawing + coherent moments today (last 24h is close enough)
    try:
        from myalicia.skills.multi_channel import recent_multi_channel_decisions
        decisions = recent_multi_channel_decisions(within_hours=24) or []
        for d in decisions:
            if d.get("channel") == "voice" and d.get("voice"):
                out["voice_fired"] += 1
            elif d.get("channel") == "coherent_moment":
                out["coherent_moments"] += 1
            elif d.get("drawing") is True:
                out["drawings_fired"] += 1
    except Exception:
        pass
    # Meta-syntheses built today
    try:
        from myalicia.skills.meta_synthesis import recent_meta_syntheses
        for m in (recent_meta_syntheses(within_days=1) or []):
            if _ts_today_local(m.get("ts", "")):
                out["meta_built"] += 1
    except Exception:
        pass
    # Dimension questions today
    try:
        from myalicia.skills.dimension_research import (
            recent_dimension_questions, recent_escalations,
        )
        for q in (recent_dimension_questions(within_days=1) or []):
            if _ts_today_local(q.get("ts", "")):
                out["dimension_questions"] += 1
        for e in (recent_escalations(within_days=1) or []):
            if _ts_today_local(e.get("ts", "")):
                out["escalations"] += 1
    except Exception:
        pass
    # Thread-pulls today
    try:
        from myalicia.skills.thread_puller import recent_thread_pulls
        for p in (recent_thread_pulls(within_days=1) or []):
            if _ts_today_local(p.get("ts", "")):
                out["thread_pulls"] += 1
    except Exception:
        pass
    # Archetype attributions today (from archetype_log.jsonl)
    try:
        log_path = MEMORY_DIR / "archetype_log.jsonl"
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if _ts_today_local(e.get("ts", "")):
                        a = (e.get("archetype") or "").lower()
                        if a:
                            out["archetype_attributions"][a] = (
                                out["archetype_attributions"].get(a, 0) + 1
                            )
    except Exception:
        pass

    # Compose a one-line natural-language summary based on what's
    # actually nonzero. Order: most-distinctive event first.
    parts: list[str] = []
    if out["coherent_moments"]:
        parts.append(f"🎼 {out['coherent_moments']} coherent moment(s)")
    if out["meta_built"]:
        parts.append(f"🌱 {out['meta_built']} meta-synthesis built")
    if out["captures"]:
        parts.append(f"📝 {out['captures']} capture(s)")
    if out["learnings"]:
        parts.append(f"📈 {out['learnings']} learning(s)")
    if out["drawings_fired"]:
        parts.append(f"🎨 {out['drawings_fired']} drawing(s)")
    if out["voice_fired"]:
        parts.append(f"🎙️ {out['voice_fired']} voice")
    if out["dimension_questions"]:
        parts.append(f"❓ {out['dimension_questions']} dim question(s)")
    if out["thread_pulls"]:
        parts.append(f"🧵 {out['thread_pulls']} thread-pull(s)")
    if out["escalations"]:
        parts.append(f"🔬 {out['escalations']} research escalation(s)")
    if out["archetype_attributions"]:
        top = sorted(
            out["archetype_attributions"].items(),
            key=lambda kv: -kv[1],
        )[:2]
        parts.append(
            "archetypes: " + ", ".join(f"{k.capitalize()} +{v}" for k, v in top)
        )
    out["summary"] = " · ".join(parts) if parts else "Quiet day so far."
    return out


# ── HTTP server ──────────────────────────────────────────────────────────


class _DashboardHandler(BaseHTTPRequestHandler):
    """Routes:
        GET /                       → static HTML page
        GET /api/state.json         → full aggregated state (everything)
        GET /api/skills.json        → skills directory only
        GET /api/timeline.json      → timeline only
        GET /manifest.json          → PWA manifest (Phase 15.0i)
        GET /healthz                → 'ok'
        POST /api/capture           → write an unprompted capture (Phase 15.0i)
    """

    def log_message(self, format, *args):
        # Quiet the default per-request logging — too noisy in stdout.log
        log.debug("%s - %s" % (self.address_string(), format % args))

    def handle(self):
        """Phase 15.2d — silence harmless connection-reset tracebacks.

        Tailscale Serve health-checks, iPhone speculative TCP pre-connects,
        SSE reconnects, and browser pipelining behaviors all open TCP
        connections then close them without sending an HTTP request line.
        BaseHTTPRequestHandler reads from rfile and raises
        ConnectionResetError / BrokenPipeError. The default ThreadingHTTPServer
        handler prints a 14-line traceback to stderr per occurrence — which
        buries real errors. Catching them here downgrades to a single debug
        line; real handler errors (raised inside do_GET/do_POST) still
        propagate normally because we only swallow the connection-level
        exceptions specifically.
        """
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as e:
            log.debug(f"client disconnect (harmless): {self.address_string()} {e}")
        except (TimeoutError, OSError) as e:
            # OSError catches the rare 'Software caused connection abort' on macOS
            # — also benign. Anything more interesting will hit the broader except.
            log.debug(f"socket-level error (harmless): {self.address_string()} {e}")

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if not path:
            path = "/"
        try:
            if path == "/" or path == "/index.html":
                self._send_html(_HTML_PAGE)
            elif path == "/api/state.json":
                self._send_json(compute_full_state())
            elif path == "/api/skills.json":
                self._send_json({"skills": list_alicia_skills()})
            elif path == "/api/timeline.json":
                self._send_json({"timeline": assemble_timeline()})
            elif path == "/manifest.json":
                self._send_json(_PWA_MANIFEST)
            elif path == "/api/network.json":
                # Use server's bound port (the URL we came in on)
                _, port = self.server.server_address
                self._send_json(compute_network_info(port=port))
            elif path == "/api/stream":
                self._stream_state(interval_s=30)
            elif path == "/healthz":
                self._send_text("ok")
            else:
                self._send_text("not found", code=404)
        except Exception as e:
            log.warning(f"dashboard handler error: {e}")
            self._send_text(f"error: {e}", code=500)

    def do_POST(self):
        """Phase 15.0i — POST /api/capture writes an unprompted capture
        to writing/Captures/ via response_capture.capture_unprompted.

        Request body: {"text": "<the capture body>"}
        Response: {"ok": true, "path": "<written file>"} or {"ok": false, "error": "..."}.
        """
        path = self.path.split("?", 1)[0].rstrip("/")
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body_raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(body_raw.decode("utf-8"))
            except Exception:
                self._send_json({"ok": False, "error": "invalid JSON"}, code=400)
                return
            if path == "/api/capture":
                text = (body.get("text") or "").strip()
                if not text:
                    self._send_json(
                        {"ok": False, "error": "text is required"}, code=400,
                    )
                    return
                from myalicia.skills.response_capture import capture_unprompted
                result_path = capture_unprompted(text)
                self._send_json({
                    "ok": True,
                    "path": str(result_path) if result_path else None,
                })
                return
            self._send_text("not found", code=404)
        except Exception as e:
            log.warning(f"dashboard POST error: {e}")
            self._send_json({"ok": False, "error": str(e)}, code=500)

    # ── helpers ──
    def _stream_state(self, interval_s: float = 30.0) -> None:
        """Phase 15.2b — Server-Sent Events stream of state.json.

        Sends the full state every `interval_s` seconds. Connection
        stays open until the client disconnects (write fails). Each
        client gets its own thread (ThreadingHTTPServer).
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            # CORS for any localhost-network browser
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            # Initial event so the client renders immediately
            self._sse_send(compute_full_state())
            # Then push every interval_s, breaking on disconnect
            while True:
                _time.sleep(interval_s)
                try:
                    self._sse_send(compute_full_state())
                except (BrokenPipeError, ConnectionResetError, OSError):
                    log.debug("SSE client disconnected")
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as e:
            log.warning(f"SSE stream error: {e}")

    def _sse_send(self, obj) -> None:
        """Format obj as one Server-Sent Event and write+flush it."""
        payload = json.dumps(obj, default=str)
        # SSE format: "data: <one-line-payload>\n\n"
        # JSON dumps without indent stays single-line — required.
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, obj, code: int = 200):
        body = json.dumps(obj, default=str, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, code: int = 200):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_server(port: int) -> None:
    """Blocking server loop — meant to run in a daemon thread.

    Phase 15.2b — uses ThreadingHTTPServer so SSE connections (which
    block their thread for as long as they're open) don't prevent
    other requests from being served.
    """
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _DashboardHandler)
        # Daemonize per-request threads so a Ctrl-C tears them all down
        server.daemon_threads = True
        log.info(f"web dashboard listening on http://0.0.0.0:{port}")
        server.serve_forever()
    except OSError as e:
        log.warning(f"web dashboard couldn't bind to :{port}: {e}")
    except Exception as e:
        log.error(f"web dashboard server crashed: {e}")


def start_web_dashboard(port: int = 8765) -> None:
    """Launch the dashboard in a background daemon thread.

    Idempotent: if a server is already running on this port, no-op.
    """
    # Cheap port-in-use check before spawning
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            already_up = s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        already_up = False
    if already_up:
        log.info(f"web dashboard already running on :{port}")
        return
    t = threading.Thread(
        target=_run_server, args=(port,),
        name="alicia-web-dashboard", daemon=True,
    )
    t.start()


# ── HTML template ────────────────────────────────────────────────────────
# Single-file page. No external deps. Renders state from /api/state.json
# every 30 seconds. Mobile-friendly via flexbox + max-width.

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="Alicia" />
  <meta name="theme-color" content="#fab36c" />
  <link rel="manifest" href="/manifest.json" />
  <title>Alicia & the user — A Living System</title>
  <style>
    :root {
      --bg: #0d0e10;
      --bg-card: #161820;
      --bg-card-hover: #1d2030;
      --fg: #e6e8ee;
      --fg-dim: #8a8e9a;
      --fg-faint: #5a5d6a;
      --accent: #fab36c;
      --green: #6cd17a;
      --yellow: #f7c761;
      --red: #ee6c6c;
      --line: #2a2c36;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Helvetica Neue", sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
      padding: 20px 16px;
    }
    h1 {
      font-size: 22px;
      font-weight: 500;
      margin: 0 0 4px 0;
      letter-spacing: -0.01em;
    }
    h2 {
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-dim);
      margin: 28px 0 12px 0;
    }
    h3 {
      font-size: 14px;
      font-weight: 600;
      margin: 0 0 6px 0;
      color: var(--fg);
    }
    .subhead {
      color: var(--fg-dim);
      font-size: 13px;
      margin: 0 0 24px 0;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }
    .card {
      background: var(--bg-card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 16px;
    }
    .card .meta {
      color: var(--fg-faint);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .stat-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 4px 0;
      border-bottom: 1px solid var(--line);
    }
    .stat-row:last-child { border-bottom: 0; }
    .stat-label { color: var(--fg-dim); }
    .stat-value { color: var(--fg); font-variant-numeric: tabular-nums; }
    .pill {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      background: var(--bg-card-hover);
      color: var(--fg-dim);
      margin-left: 4px;
    }
    .pill.delta-up { color: var(--green); }
    .pill.delta-down { color: var(--red); }
    .pill.warn { color: var(--yellow); }
    .skill-bucket {
      margin-bottom: 14px;
    }
    .skill-bucket h3 {
      color: var(--accent);
      margin-bottom: 6px;
    }
    .skill-list {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .skill-item {
      background: var(--bg-card-hover);
      padding: 3px 9px;
      border-radius: 4px;
      font-size: 12px;
      color: var(--fg-dim);
      cursor: help;
    }
    .timeline {
      position: relative;
      padding-left: 18px;
      border-left: 2px solid var(--line);
    }
    .timeline-item {
      position: relative;
      padding: 4px 0 12px 0;
    }
    .timeline-item::before {
      content: '';
      position: absolute;
      left: -24px;
      top: 8px;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
    }
    .timeline-date {
      color: var(--fg-faint);
      font-size: 11px;
      letter-spacing: 0.04em;
      font-variant-numeric: tabular-nums;
    }
    .timeline-title { color: var(--fg); }
    .footer {
      margin-top: 40px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      color: var(--fg-faint);
      font-size: 11px;
      text-align: center;
    }
    .json-bug {
      color: var(--red);
      font-size: 11px;
      font-family: ui-monospace, SFMono-Regular, monospace;
    }
    .quote { color: var(--fg-dim); font-style: italic; font-size: 13px; }
    a.vault-link {
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px dotted var(--accent);
    }
    a.vault-link:hover {
      color: var(--fg);
      border-bottom-color: var(--fg);
    }
    .capture-row { padding: 4px 0; border-bottom: 1px solid var(--line); }
    .capture-row:last-child { border-bottom: 0; }
    .capture-meta { color: var(--fg-faint); font-size: 11px; }
    .capture-prompt {
      color: var(--fg-faint);
      font-style: italic;
      font-size: 12px;
      border-left: 2px solid var(--line);
      padding-left: 8px;
      margin-bottom: 4px;
    }
    .heartbeat {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--bg-card);
      border: 1px solid var(--line);
      font-size: 11px;
      color: var(--fg-dim);
    }
    .heartbeat .dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }
    .heartbeat .dot.alive { background: var(--green); animation: pulse 2s ease-in-out infinite; }
    .heartbeat .dot.quiet { background: var(--yellow); }
    .heartbeat .dot.stalled { background: var(--red); }
    .heartbeat .dot.unknown { background: var(--fg-faint); }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.85); }
    }
    .network-toggle {
      color: var(--fg-faint);
      font-size: 11px;
      text-decoration: none;
    }
    .network-toggle:hover { color: var(--fg-dim); }
    /* Phase 16.1 — conversation marker */
    .conversation-marker {
      color: #b48ead;
      font-size: 11px;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border: 1px solid #b48ead;
      border-radius: 999px;
      background: rgba(180, 142, 173, 0.08);
    }
    /* Phase 19.0 — mood-of-the-week marker */
    .mood-marker {
      color: var(--fg-faint);
      font-size: 11px;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.03);
    }
    .mood-marker.improving { color: var(--green); border-color: var(--green); background: rgba(150, 200, 150, 0.06); }
    .mood-marker.declining { color: var(--red); border-color: var(--red); background: rgba(220, 150, 150, 0.06); }
    .network-card {
      background: var(--bg-card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      margin: 10px 0;
    }
    .network-meta {
      color: var(--fg-faint);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .network-row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 4px 0;
      font-size: 12px;
      font-family: ui-monospace, SFMono-Regular, monospace;
    }
    .network-row .label {
      color: var(--fg-dim);
      flex-shrink: 0;
    }
    .network-row .url {
      color: var(--accent);
      word-break: break-all;
      text-align: right;
    }
    .pinned-card {
      background: linear-gradient(135deg, var(--bg-card) 0%, var(--bg-card-hover) 100%);
      border: 1px solid var(--accent);
      border-radius: 10px;
      padding: 14px 18px;
      margin: 16px 0 8px 0;
    }
    .pinned-meta {
      color: var(--accent);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
    }
    .pinned-focus { color: var(--fg); font-size: 15px; line-height: 1.5; }
    .today-card {
      background: var(--bg-card);
      border: 1px solid var(--line);
      border-left: 3px solid var(--accent);
      border-radius: 10px;
      padding: 12px 14px;
      margin: 8px 0;
    }
    .today-meta {
      color: var(--fg-faint);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
    }
    .today-summary { color: var(--fg-dim); font-size: 13px; }
    /* Phase 17.3 — noticings card */
    .noticings-card {
      background: var(--bg-card);
      border: 1px solid var(--line);
      border-left: 3px solid #b48ead;
      border-radius: 10px;
      padding: 12px 14px;
      margin: 8px 0;
    }
    .noticings-meta {
      color: #b48ead;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
    }
    .noticings-counts { color: var(--fg-faint); font-size: 11px; margin-bottom: 6px; }
    .noticing-row {
      padding: 6px 0;
      border-top: 1px dashed var(--line);
      font-size: 13px;
    }
    .noticing-row:first-of-type { border-top: 0; }
    .noticing-theme { color: var(--fg); font-style: italic; }
    .noticing-status-pending { color: var(--fg-faint); }
    .noticing-status-surfaced { color: var(--accent); }
    .noticing-status-acknowledged { color: var(--green); }
    .noticing-evidence { color: var(--fg-dim); font-size: 11px; margin-top: 2px; }
    .noticing-next {
      color: #b48ead;
      font-size: 11px;
      margin-top: 6px;
      padding-top: 6px;
      border-top: 1px dashed var(--line);
    }
    .capture-card {
      background: var(--bg-card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      margin: 8px 0 16px 0;
    }
    .capture-card textarea {
      width: 100%;
      background: var(--bg);
      color: var(--fg);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font-family: inherit;
      font-size: 13px;
      resize: vertical;
      box-sizing: border-box;
    }
    .capture-card textarea:focus { outline: 1px solid var(--accent); }
    .capture-card button {
      background: var(--accent);
      color: #1a1a1a;
      border: 0;
      padding: 6px 16px;
      border-radius: 6px;
      font-weight: 500;
      cursor: pointer;
      font-size: 13px;
    }
    .capture-card button:hover { opacity: 0.9; }
    .capture-card button:disabled { opacity: 0.5; cursor: wait; }
    .capture-status { color: var(--fg-faint); font-size: 11px; }
    .capture-status.ok { color: var(--green); }
    .capture-status.err { color: var(--red); }
    @media (max-width: 600px) {
      .container { padding: 14px 12px; }
      h1 { font-size: 18px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">
      <div>
        <h1>Alicia &amp; the user — A Living System</h1>
        <p class="subhead" id="subhead">loading…</p>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
        <div id="heartbeat" class="heartbeat" title="last activity"></div>
        <!-- Phase 16.1 — active conversation marker -->
        <div id="conversation-marker" class="conversation-marker" title="active conversation routing" style="display:none"></div>
        <!-- Phase 19.0 — mood-of-the-week pill -->
        <div id="mood-marker" class="mood-marker" title="mood of the week (from voice notes)" style="display:none"></div>
        <a href="#" id="network-toggle" class="network-toggle">network…</a>
      </div>
    </div>
    <div id="network-card" class="network-card" style="display:none">
      <div class="network-meta">📡 Reachable URLs</div>
      <div id="network-urls"></div>
      <p class="quote" style="margin:8px 0 0 0;font-size:11px">
        For outside-home access, install Tailscale on Mac + iPhone.
        See <a href="https://github.com/mrdaemoni/alicia/blob/main/REMOTE_ACCESS.md" class="vault-link" target="_blank">REMOTE_ACCESS.md</a>.
      </p>
    </div>

    <!-- Phase 15.0i — pinned card + capture form -->
    <div class="pinned-card" id="pinned-card" style="display:none">
      <div class="pinned-meta">📌 What to think about today</div>
      <div class="pinned-focus" id="pinned-focus"></div>
    </div>

    <div class="today-card" id="today-card" style="display:none">
      <div class="today-meta">📅 What changed today</div>
      <div class="today-summary" id="today-summary"></div>
    </div>

    <!-- Phase 17.3 — noticings card -->
    <div class="noticings-card" id="noticings-card" style="display:none">
      <div class="noticings-meta">👁 Noticings · what Alicia is tracking</div>
      <div class="noticings-counts" id="noticings-counts"></div>
      <div id="noticings-list"></div>
      <div class="noticing-next" id="noticings-next" style="display:none"></div>
    </div>

    <div class="capture-card">
      <div class="capture-meta">✍️ Quick capture</div>
      <textarea id="capture-text" placeholder="A thought, an observation, a question…" rows="3"></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
        <span id="capture-status" class="capture-status"></span>
        <button id="capture-submit">Capture</button>
      </div>
    </div>

    <h2>Alicia · what she is</h2>
    <div class="grid">
      <div class="card">
        <div class="meta">Heart · Wisdom Engine inner loop</div>
        <h3>What's circulating</h3>
        <div id="alicia-heart"></div>
      </div>
      <div class="card">
        <div class="meta">Body · vault, voice, drawing, activities</div>
        <h3>What she's made of &amp; what she's doing</h3>
        <div id="alicia-body"></div>
      </div>
      <div class="card">
        <div class="meta">Soul · the six archetypes</div>
        <h3>Her temperament</h3>
        <div id="alicia-soul"></div>
      </div>
      <div class="card">
        <div class="meta">Mind · her own arc</div>
        <h3>Her season</h3>
        <div id="alicia-mind"></div>
      </div>
      <div class="card">
        <div class="meta">Nervous system · self-observation</div>
        <h3>The four loops</h3>
        <div id="alicia-nervous"></div>
      </div>
    </div>

    <h2>the user · who you are</h2>
    <div class="grid">
      <div class="card">
        <div class="meta">Mind · /becoming arc</div>
        <h3>Who you're becoming</h3>
        <div id="hector-mind"></div>
      </div>
      <div class="card">
        <div class="meta">Voice · captures + responses</div>
        <h3>What you've been writing</h3>
        <div id="hector-voice"></div>
      </div>
      <div class="card">
        <div class="meta">Body · practices in motion</div>
        <h3>What you're practicing</h3>
        <div id="hector-body"></div>
      </div>
    </div>

    <h2>Our relationship · the space between</h2>
    <div class="grid">
      <div class="card">
        <div class="meta">Conversation</div>
        <h3>The ongoing dialogue</h3>
        <div id="rel-conversation"></div>
      </div>
      <div class="card">
        <div class="meta">Distillation</div>
        <h3>What dialogue becomes</h3>
        <div id="rel-distillation"></div>
      </div>
      <div class="card">
        <div class="meta">Coherence</div>
        <h3>Voice + drawing as one</h3>
        <div id="rel-coherence"></div>
      </div>
      <div class="card">
        <div class="meta">What's landing</div>
        <h3>By source &amp; altitude</h3>
        <div id="rel-landing"></div>
      </div>
    </div>

    <h2>Skills · what Alicia can do</h2>
    <div id="skills"></div>

    <h2>Timeline · birth to today</h2>
    <div id="timeline" class="timeline"></div>

    <p class="footer">
      Auto-refreshes every 30 seconds · <span id="last-updated"></span>
    </p>
  </div>

  <script>
    function fmtDelta(this_week, last_week) {
      if (this_week === 0 && last_week === 0) return '';
      const d = this_week - last_week;
      if (d > 0) return `<span class="pill delta-up">↑+${d}</span>`;
      if (d < 0) return `<span class="pill delta-down">↓${d}</span>`;
      return `<span class="pill">→</span>`;
    }
    function row(label, value) {
      return `<div class="stat-row"><span class="stat-label">${label}</span><span class="stat-value">${value}</span></div>`;
    }
    function escape(s) {
      return String(s).replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
      })[c]);
    }
    function renderAlicia(state) {
      const a = state.alicia || {};
      // Heart
      const h = a.heart || {};
      document.getElementById('alicia-heart').innerHTML =
        row('active practices', `${(h.active_practices || []).length}/${h.max_active_practices || 0}`) +
        row('active contradictions', h.active_contradictions || 0) +
        row('recent captures', h.recent_captures_count || 0);
      // Body — substrate stats + scheduled activities
      const b = a.body || {};
      let bodyHtml =
        row('syntheses in vault', b.synthesis_count || 0) +
        row('voice fired (24h)', b.voice_fired_24h || 0) +
        row('drawings fired (24h)', b.drawings_fired_24h || 0);
      // Activities — scheduled tasks she runs
      const tasks = b.tasks || [];
      if (tasks.length > 0) {
        bodyHtml += `<div style="margin-top:14px;color:var(--fg-faint);font-size:11px;text-transform:uppercase;letter-spacing:0.08em">Activities (${tasks.length})</div>`;
        bodyHtml += '<div style="margin-top:6px">';
        for (const t of tasks) {
          bodyHtml += `<div style="font-size:12px;padding:3px 0;border-bottom:1px solid var(--line)" title="${escape(t.what)}"><span style="color:var(--fg-faint);display:inline-block;min-width:84px">${escape(t.when)}</span> <span>${escape(t.name)}</span>${t.phase && t.phase !== '—' ? ` <span class="pill">${escape(t.phase)}</span>` : ''}</div>`;
        }
        bodyHtml += '</div>';
      }
      document.getElementById('alicia-body').innerHTML = bodyHtml;
      // Soul — the six archetypes
      const soul = a.soul || {};
      const archs = soul.archetypes || [];
      let soulHtml = '';
      if (soul.leading) {
        const ema = soul.ema_window_days
          ? ` <span class="pill">${soul.ema_window_days}d EMA</span>`
          : '';
        soulHtml += `<div style="margin-bottom:10px;color:var(--fg-dim);font-size:12px">Leading right now: <span style="color:var(--accent);font-weight:500">${escape(soul.leading)}</span>${ema}</div>`;
      }
      for (const ar of archs) {
        const eff = ar.effectiveness_score || 1.0;
        const effPill = (Math.abs(eff - 1.0) >= 0.05)
          ? `<span class="pill ${eff > 1.05 ? 'delta-up' : 'delta-down'}">${eff.toFixed(2)}×</span>`
          : '';
        const w = ar.current_weight || 0;
        const bar = `<div style="background:var(--line);height:4px;border-radius:2px;margin-top:3px;overflow:hidden"><div style="background:var(--accent);height:100%;width:${Math.min(100, w * 2.5)}%"></div></div>`;
        soulHtml += `<div style="padding:6px 0;border-bottom:1px solid var(--line)">
          <div style="display:flex;justify-content:space-between;align-items:baseline">
            <span><strong>${escape(ar.title)}</strong> <span style="color:var(--fg-faint);font-size:11px">${escape(ar.description)}</span></span>
            <span style="color:var(--fg-dim);font-size:12px;font-variant-numeric:tabular-nums">${w}% ${effPill}</span>
          </div>
          ${bar}
        </div>`;
      }
      // Identity links — bio + birth story
      const ids = soul.identity_links || {};
      const links = [];
      if (ids.bio && ids.bio.vault_uri) {
        links.push(`<a href="${ids.bio.vault_uri}" class="vault-link">📖 ${escape(ids.bio.label)}</a>`);
      }
      if (ids.birth_story && ids.birth_story.vault_uri) {
        links.push(`<a href="${ids.birth_story.vault_uri}" class="vault-link">🌱 ${escape(ids.birth_story.label)}</a>`);
      }
      if (links.length) {
        soulHtml += `<div style="margin-top:12px;padding-top:8px;border-top:1px solid var(--line);font-size:12px">${links.join(' · ')}</div>`;
      }
      document.getElementById('alicia-soul').innerHTML = soulHtml ||
        '<p class="quote">no archetype data yet</p>';
      // Mind
      const m = a.mind || {};
      document.getElementById('alicia-mind').innerHTML =
        row('season', `<span style="color:var(--accent)">${m.season || '—'}</span>`) +
        row('emergence score', m.score || 0) +
        row('days breathing', m.days_breathing || 0) +
        (m.description ? `<p class="quote">${escape(m.description)}</p>` : '');
      // Nervous system: loop summary
      const ns = a.nervous_system || {};
      const loops = (ns.loops && ns.loops.loops) || {};
      const sd = ns.smart_deciders || {};
      let loopHtml = '';
      for (const [k, v] of Object.entries(loops)) {
        const dorm = v.last_activity_ts ? '' : '';
        loopHtml += row(v.name || k,
          `${v.captures_this_week || v.builds_this_week || v.questions_this_week || v.pulls_this_week || 0} this wk` +
          (v.streak_weeks >= 2 ? ` 🔥${v.streak_weeks}w` : '')
        );
      }
      const dormant = (ns.loops && ns.loops.dormant_loops) || [];
      if (dormant.length > 0) {
        loopHtml += `<div style="margin-top:6px"><span class="pill warn">⚠️ ${dormant.length} dormant</span></div>`;
      }
      const v_voice = sd.voice || {};
      const v_drawing = sd.drawing || {};
      loopHtml += `<div style="margin-top:8px;color:var(--fg-faint);font-size:11px">smart deciders 24h:<br>voice ${v_voice.fired || 0}/${(v_voice.fired || 0) + (v_voice.skipped || 0)} · drawing ${v_drawing.fired || 0}/${(v_drawing.fired || 0) + (v_drawing.skipped || 0)} · 🎼 ${sd.coherent_moments || 0}</div>`;
      document.getElementById('alicia-nervous').innerHTML = loopHtml;
    }
    function renderHector(state) {
      const h = state.hector || {};
      // Mind
      const m = h.mind || {};
      const counts = m.dimension_counts_recent_14d || {};
      const dimList = (m.dimensions || [])
        .map(d => {
          const n = counts[d] || 0;
          const cls = n === 0 ? 'pill warn' : 'pill';
          return `<span class="${cls}">${d} ${n}</span>`;
        })
        .join('');
      // Baseline cell — clickable link if URI available
      const baselineCell = m.baseline_vault_uri
        ? `<a href="${m.baseline_vault_uri}" class="vault-link">${escape(m.baseline || '—')}</a>`
        : (m.baseline || '<em>not set</em>');
      // "Who Alicia thinks you are" — link to latest profile
      const profileLink = (m.who_alicia_thinks_you_are && m.who_alicia_thinks_you_are.vault_uri)
        ? `<a href="${m.who_alicia_thinks_you_are.vault_uri}" class="vault-link">${escape(m.who_alicia_thinks_you_are.label)}</a>`
        : '';
      let mindHtml =
        row('baseline', baselineCell) +
        row('days since baseline', m.days_since_baseline || 0) +
        row('learnings (total)', m.learnings_total || 0) +
        row('learnings (last 14d)', m.learnings_last_14d || 0) +
        row('thin dimensions', (m.thin_dimensions || []).length) +
        `<div style="margin-top:10px;font-size:11px;color:var(--fg-faint)">last 14d:</div>` +
        `<div style="margin-top:4px">${dimList}</div>`;
      if (profileLink) {
        mindHtml += `<div style="margin-top:12px;padding-top:8px;border-top:1px solid var(--line);font-size:12px">📝 Who Alicia thinks you are: ${profileLink}</div>`;
      }
      document.getElementById('hector-mind').innerHTML = mindHtml;
      // Voice — captures clickable to vault, synthesis refs clickable too
      const v = h.voice || {};
      const captures = (v.recent_captures || [])
        .map(c => {
          const date = escape(c.captured_at).slice(0, 16);
          const chan = escape(c.channel);
          const excerpt = escape(c.excerpt || '').slice(0, 140);
          // Wrap excerpt in vault link if available
          const excerptHtml = c.vault_uri
            ? `<a href="${c.vault_uri}" class="vault-link" style="border-bottom:none">${excerpt}</a>`
            : excerpt;
          // Synthesis reference, if present
          let refHtml = '';
          if (c.synthesis_referenced) {
            refHtml = c.synthesis_vault_uri
              ? ` <span style="color:var(--fg-faint);font-size:11px">→ <a href="${c.synthesis_vault_uri}" class="vault-link">${escape(c.synthesis_referenced).slice(0, 60)}</a></span>`
              : ` <span class="capture-meta">→ ${escape(c.synthesis_referenced).slice(0, 60)}</span>`;
          }
          // Phase 15.0h — show the prompt that triggered this capture, if any
          const promptHtml = c.prompt
            ? `<div class="capture-prompt">"${escape(c.prompt)}"</div>`
            : '';
          return `<div class="capture-row"><div class="capture-meta">${date} · ${chan}${refHtml}</div>${promptHtml}<div style="font-size:13px">${excerptHtml}</div></div>`;
        })
        .join('');
      // Most-responded list — also clickable
      const mostResp = (v.most_responded || [])
        .slice(0, 5)
        .map(r => {
          const titleHtml = r.vault_uri
            ? `<a href="${r.vault_uri}" class="vault-link">${escape(r.title).slice(0, 70)}</a>`
            : escape(r.title).slice(0, 70);
          return `<div style="padding:3px 0;font-size:12px">${titleHtml} <span class="pill">${r.count}</span></div>`;
        })
        .join('');
      let voiceHtml = captures || '<p class="quote">no recent captures</p>';
      if (mostResp) {
        voiceHtml += `<div style="margin-top:14px;color:var(--fg-faint);font-size:11px;text-transform:uppercase;letter-spacing:0.08em">Most responded</div><div style="margin-top:4px">${mostResp}</div>`;
      }
      document.getElementById('hector-voice').innerHTML = voiceHtml;
      // Body
      const b = h.body || {};
      const practices = (b.practices || [])
        .map(p => row(`${p.archetype} · ${p.slug}`, `day ${p.days_running}`))
        .join('');
      document.getElementById('hector-body').innerHTML =
        practices || '<p class="quote">no active practices</p>';
    }
    function renderRelationship(state) {
      const r = state.relationship || {};
      // Conversation
      const c = r.conversation || {};
      let convo = row('thread-pulls (14d)', c.pulls_14d || 0) +
                  row('replies (14d)', c.replies_14d || 0) +
                  row('reply rate', `${c.reply_rate_pct || 0}%`);
      if ((c.advanced_threads || []).length > 0) {
        convo += `<div style="margin-top:8px;color:var(--fg-faint);font-size:11px">most advanced:</div>`;
        for (const t of c.advanced_threads.slice(0, 3)) {
          convo += `<div style="font-size:12px;padding:2px 0">${escape(t.summary)} <span class="pill">${t.reply_count}</span></div>`;
        }
      }
      document.getElementById('rel-conversation').innerHTML = convo;
      // Distillation — candidates clickable, plus near-threshold hints
      const d = r.distillation || {};
      let dist = row('built (last 30d)', d.recent_builds_30d || 0) +
                 row('max recursion level', d.max_meta_level || 3);
      const byLevel = d.candidates_by_level || {};
      for (const lvl of Object.keys(byLevel).sort()) {
        const items = byLevel[lvl];
        dist += `<div style="margin-top:8px;color:var(--accent);font-size:12px">Level ${lvl}: ${items.length} candidate(s)</div>`;
        for (const it of items.slice(0, 2)) {
          const titleHtml = it.vault_uri
            ? `<a href="${it.vault_uri}" class="vault-link">${escape(it.title)}</a>`
            : escape(it.title);
          dist += `<div style="font-size:12px;padding:2px 0;color:var(--fg-dim)">• ${titleHtml} <span class="pill">${it.capture_count}</span></div>`;
        }
      }
      // Phase 15.0g — near-threshold hints
      const nearList = d.near_threshold || [];
      if (nearList.length > 0) {
        dist += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--line);font-size:12px;color:var(--yellow)">Near threshold (1 capture away):</div>`;
        for (const it of nearList) {
          const titleHtml = it.vault_uri
            ? `<a href="${it.vault_uri}" class="vault-link">${escape(it.title)}</a>`
            : escape(it.title);
          dist += `<div style="font-size:12px;padding:2px 0;color:var(--fg-dim)">• ${titleHtml} <span class="pill">${it.capture_count}/${d.min_captures_for_meta || 3}</span></div>`;
        }
      }
      document.getElementById('rel-distillation').innerHTML = dist;
      // Coherence
      const co = r.coherence || {};
      let coh = row('coherent moments (7d)', co.coherent_moments_7d || 0);
      if (co.latest_tail) {
        coh += `<p class="quote" style="margin-top:8px">"${escape(co.latest_tail)}"</p>`;
      }
      document.getElementById('rel-coherence').innerHTML = coh;
      // Landing
      const l = r.landing || {};
      const sources = (l.by_source || []).slice(0, 6)
        .map(s => {
          const bar = s.avg_depth >= 4.0 ? '🟢' : s.avg_depth >= 2.5 ? '🟡' : '🔻';
          return row(`${bar} ${s.msg_type}`, `${s.avg_depth.toFixed(1)} depth · ${s.count}×`);
        })
        .join('');
      document.getElementById('rel-landing').innerHTML =
        sources || '<p class="quote">no engagement data yet</p>';
    }
    function renderSkills(state) {
      const skills = state.skills || [];
      const buckets = {};
      for (const s of skills) {
        if (!buckets[s.bucket]) buckets[s.bucket] = [];
        buckets[s.bucket].push(s);
      }
      const html = Object.entries(buckets).map(([bucket, items]) => `
        <div class="skill-bucket">
          <h3>${escape(bucket)} <span class="pill">${items.length}</span></h3>
          <div class="skill-list">
            ${items.map(s => {
              const text = `<span class="skill-item" title="${escape(s.summary)}">${escape(s.module)}</span>`;
              return s.github_url
                ? `<a href="${s.github_url}" target="_blank" rel="noopener" style="text-decoration:none">${text}</a>`
                : text;
            }).join('')}
          </div>
        </div>
      `).join('');
      document.getElementById('skills').innerHTML = html ||
        '<p class="quote">no skills found</p>';
    }
    function renderTimeline(state) {
      const items = state.timeline || [];
      const html = items
        .slice()
        .reverse() // newest first
        .map(it => {
          const titleHtml = it.github_url
            ? `<a href="${it.github_url}" target="_blank" rel="noopener" class="vault-link">${escape(it.title)}</a>`
            : escape(it.title);
          return `
            <div class="timeline-item">
              <div class="timeline-date">${escape(it.date)} · day ${it.days_since_birth}</div>
              <div class="timeline-title">${titleHtml}</div>
            </div>
          `;
        }).join('');
      document.getElementById('timeline').innerHTML = html ||
        '<p class="quote">timeline not yet assembled</p>';
    }
    function renderHeader(state) {
      const m = (state.alicia && state.alicia.mind) || {};
      const days = m.days_breathing || 0;
      const season = m.season || '—';
      document.getElementById('subhead').innerHTML =
        `Born 2026-01-15 · ${days} days breathing · season: <span style="color:var(--accent)">${escape(season)}</span>`;
      document.getElementById('last-updated').textContent =
        `last updated: ${new Date(state.generated_at).toLocaleString()}`;
      // Phase 15.0h — heartbeat indicator
      const h = state.health || {};
      const status = h.status || 'unknown';
      const msg = h.message || 'no signal';
      document.getElementById('heartbeat').innerHTML =
        `<span class="dot ${escape(status)}"></span><span>${escape(msg)}</span>`;
      document.getElementById('heartbeat').title =
        h.newest_signal_path
          ? `most recent: ${h.newest_signal_path} @ ${new Date(h.newest_signal_ts).toLocaleString()}`
          : 'no heartbeat data';
    }
    function renderPinned(state) {
      const p = state.pinned || {};
      const card = document.getElementById('pinned-card');
      if (!p.focus) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';
      // Replace markdown bold and links — minimal renderer
      let html = escape(p.focus)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/_(.+?)_/g, '<em>$1</em>');
      if (p.vault_uri) {
        html += ` <a href="${p.vault_uri}" class="vault-link">→</a>`;
      }
      document.getElementById('pinned-focus').innerHTML = html;
    }
    function renderToday(state) {
      const t = state.today || {};
      const card = document.getElementById('today-card');
      if (!t.summary) { card.style.display = 'none'; return; }
      card.style.display = '';
      document.getElementById('today-summary').innerHTML = escape(t.summary);
    }
    // Phase 17.3 — emergent themes Alicia has been tracking
    function renderNoticings(state) {
      const n = state.noticings || {};
      const card = document.getElementById('noticings-card');
      if (!n.total || n.total === 0) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';
      const bs = n.by_status || {};
      document.getElementById('noticings-counts').textContent =
        `${n.total} theme${n.total === 1 ? '' : 's'} · ` +
        `${bs.pending || 0} pending · ${bs.surfaced || 0} surfaced · ` +
        `${bs.acknowledged || 0} acked`;
      const STATUS_ICON = {
        pending: '⏳', surfaced: '📬', acknowledged: '✅',
      };
      const list = (n.themes || []).map(t => {
        const icon = STATUS_ICON[t.status] || '•';
        const cls = `noticing-status-${t.status || 'pending'}`;
        const ev = t.lead_evidence
          ? `<div class="noticing-evidence">└ "${escape(t.lead_evidence)}"</div>`
          : '';
        return (
          `<div class="noticing-row">
             <span class="${cls}">${icon}</span>
             <span class="noticing-theme">${escape(t.theme)}</span>
             <span class="noticing-status-pending">(${t.recurrence_count}×)</span>
             ${ev}
           </div>`
        );
      }).join('');
      document.getElementById('noticings-list').innerHTML = list;
      const nextEl = document.getElementById('noticings-next');
      if (n.next_to_surface) {
        nextEl.style.display = '';
        nextEl.textContent = `next to surface: ${n.next_to_surface}`;
      } else {
        nextEl.style.display = 'none';
      }
    }
    async function submitCapture() {
      const ta = document.getElementById('capture-text');
      const btn = document.getElementById('capture-submit');
      const status = document.getElementById('capture-status');
      const text = (ta.value || '').trim();
      if (!text) {
        status.textContent = 'write something first';
        status.className = 'capture-status err';
        return;
      }
      btn.disabled = true;
      status.textContent = 'capturing…';
      status.className = 'capture-status';
      try {
        const res = await fetch('/api/capture', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        });
        const data = await res.json();
        if (data.ok) {
          ta.value = '';
          status.textContent = '✓ captured';
          status.className = 'capture-status ok';
          // Refresh dashboard so the new capture appears
          setTimeout(refresh, 500);
        } else {
          status.textContent = `error: ${data.error || 'unknown'}`;
          status.className = 'capture-status err';
        }
      } catch (e) {
        status.textContent = `error: ${e}`;
        status.className = 'capture-status err';
      } finally {
        btn.disabled = false;
      }
    }
    // Phase 15.2c — network info toggle
    let _networkLoaded = false;
    document.getElementById('network-toggle').addEventListener('click', async (e) => {
      e.preventDefault();
      const card = document.getElementById('network-card');
      if (card.style.display === 'none') {
        card.style.display = '';
        if (!_networkLoaded) {
          try {
            const res = await fetch('/api/network.json', { cache: 'no-store' });
            const data = await res.json();
            const rows = (data.urls || []).map(u =>
              `<div class="network-row">
                 <span class="label">${escape(u.label)}</span>
                 <a href="${escape(u.url)}" class="url">${escape(u.url)}</a>
               </div>`
            ).join('');
            const tail = data.tailscale && !data.tailscale.installed
              ? `<p class="quote" style="margin-top:6px;font-size:11px;color:var(--yellow)">Tailscale not installed — see guide below for outside-home access.</p>`
              : '';
            document.getElementById('network-urls').innerHTML = rows + tail;
            _networkLoaded = true;
          } catch (e) {
            document.getElementById('network-urls').innerHTML =
              `<span class="json-bug">network info unavailable: ${e}</span>`;
          }
        }
      } else {
        card.style.display = 'none';
      }
    });
    document.getElementById('capture-submit').addEventListener('click', submitCapture);
    document.getElementById('capture-text').addEventListener('keydown', (e) => {
      // Cmd/Ctrl + Enter submits
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        submitCapture();
      }
    });
    // Phase 16.1 — show the active conversation as a pill in the header
    function renderConversation(state) {
      const c = state.conversation || {};
      const el = document.getElementById('conversation-marker');
      if (!c.active || !c.total) {
        el.style.display = 'none';
        return;
      }
      // Hide the pill in the trivial single-default case — only surface
      // the marker when the user has actually created multiple conversations.
      if (c.total <= 1 && c.active === 'default') {
        el.style.display = 'none';
        return;
      }
      el.style.display = '';
      const label = c.active_label || c.active;
      el.textContent = `🪧 ${label}`;
      el.title = c.active_description || `active conversation: ${c.active}`;
    }
    // Phase 19.0 — mood-of-the-week pill in the header
    function renderMood(state) {
      const m = state.mood || {};
      const el = document.getElementById('mood-marker');
      if (!m.summary_line || !m.total_classifications) {
        el.style.display = 'none';
        return;
      }
      el.style.display = '';
      el.textContent = m.summary_line;
      // Color the pill by trend
      el.classList.remove('improving', 'declining');
      if (m.trend === 'improving') el.classList.add('improving');
      if (m.trend === 'declining') el.classList.add('declining');
      el.title = (
        `mood over last ${m.days || 7}d: ${m.trend_explanation || ''} ` +
        `(${m.total_classifications} voice notes)`
      ).trim();
    }
    function applyState(state) {
      renderHeader(state);
      renderConversation(state);
      renderMood(state);
      renderPinned(state);
      renderToday(state);
      renderNoticings(state);
      renderAlicia(state);
      renderHector(state);
      renderRelationship(state);
      renderSkills(state);
      renderTimeline(state);
    }
    async function refresh() {
      try {
        const res = await fetch('/api/state.json', { cache: 'no-store' });
        const state = await res.json();
        applyState(state);
      } catch (e) {
        document.getElementById('subhead').innerHTML =
          `<span class="json-bug">refresh failed: ${e}</span>`;
      }
    }
    // Phase 15.2b — prefer SSE for push updates; fall back to polling.
    let _es = null;
    function startStream() {
      if (typeof EventSource === 'undefined') {
        // Polling fallback for ancient browsers
        refresh();
        setInterval(refresh, 30000);
        return;
      }
      try {
        _es = new EventSource('/api/stream');
        _es.onmessage = (ev) => {
          try {
            const state = JSON.parse(ev.data);
            applyState(state);
          } catch (e) {
            console.warn('SSE parse error:', e);
          }
        };
        _es.onerror = () => {
          // Reconnect after a brief delay; EventSource auto-retries by
          // default but we explicit-close + reopen on persistent failure.
          if (_es && _es.readyState === EventSource.CLOSED) {
            setTimeout(startStream, 5000);
          }
        };
      } catch (e) {
        // Stream not available — fall back to polling
        refresh();
        setInterval(refresh, 30000);
      }
    }
    refresh(); // immediate paint
    startStream(); // then stream
  </script>
</body>
</html>"""
