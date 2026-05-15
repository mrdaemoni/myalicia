#!/usr/bin/env python3
"""
the user-model evolution + delta tracking — Phase 12.0 foundation.

The system tracks who the user was vs who he's becoming. Three artefacts:

  1. Baseline (Alicia/Self/Baselines/<date>.md) — snapshot of MEMORY.md +
     patterns/insights/preferences/concepts at the moment Phase 12 ships.
     The reference frame against which the delta is computed.

  2. Learnings log (~/alicia/memory/user_learnings.jsonl) — append-only
     record of every new insight Alicia derives about the user since the
     baseline. Each entry tagged with a dimension + confidence + source.

  3. Delta (computed live) — diff between baseline content and accumulated
     learnings. Surfaced via /becoming Telegram command.

Phase 12.0 ships the foundation: baseline init, learnings append/query,
dimension-aware delta computation, gap finding, and /becoming dashboard.

Phase 12.1+ will wire this into:
  - memory_skill.extract_from_message → auto-append learnings
  - 3am research_skill scheduled task → gaps drive research topics
  - archetype effectiveness EMA → learnings about archetype-relevant
    dimensions bump them
  - proactive question generation → thin/stale dimensions drive questions

Public API (Phase 12.0):
    init_baseline(label=None) -> Path
    get_active_baseline() -> Optional[Path]
    append_learning(claim, dimension, confidence, *, source=None) -> dict
    get_learnings(*, dimension=None, since_days=None) -> list[dict]
    DIMENSIONS  # canonical list — keep in sync with MEMORY.md sections
    compute_dimension_counts(*, since_days=None) -> dict[str, int]
    find_thin_dimensions(*, stale_after_days=14) -> list[str]
    days_since_baseline() -> Optional[int]
    render_becoming_dashboard() -> str
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.user_model")


# ── Config ──────────────────────────────────────────────────────────────────


VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(str(MEMORY_DIR))

# Baselines live in the vault — they're a Tier-3 record of the user's arc.
BASELINES_DIR = VAULT_ROOT / "Alicia" / "Self" / "Baselines"

# Learnings log lives in agent memory — it's append-only operational state.
LEARNINGS_LOG = MEMORY_DIR / "user_learnings.jsonl"

# Files that contribute to a baseline snapshot. Each is a section of
# Alicia's understanding; the baseline copies the *current* contents into a
# single timestamped doc so future deltas can compare.
BASELINE_SOURCES: list[tuple[str, Path]] = [
    ("Master Memory",   MEMORY_DIR / "MEMORY.md"),
    ("Patterns",        MEMORY_DIR / "patterns.md"),
    ("Insights",        MEMORY_DIR / "insights.md"),
    ("Preferences",     MEMORY_DIR / "preferences.md"),
    ("Concepts",        MEMORY_DIR / "concepts.md"),
]


# Canonical dimensions of the user's life that the model tracks. Derived from
# MEMORY.md's structure + the four pillars in ALICIA_ONTOLOGY.md (Health &
# Mind, Wealth, Knowledge, Security) + the major activities Alicia
# observes. Each learning gets tagged with one (or more) of these.
#
# Keep this list short and stable — too many dimensions = no signal.
DIMENSIONS: tuple[str, ...] = (
    "identity",       # who the user is at the level of values + self-image
    "knowledge",      # what he's learning, reading, synthesizing
    "practice",       # disciplines, rituals, daily structure
    "relationships",  # family, friends, professional
    "work",           # work, leadership, career arc
    "voice",          # writing, speaking, expression
    "body",           # health, fitness, embodiment
    "wealth",         # money, planning, accumulation
    "creative",       # making, podcasts, art, drawing
    "shadow",         # blind spots, contradictions, growth edges
)


# Phase 12.1 — keyword-based dimension classification. Cheap fallback so
# every kept extraction can be auto-appended to the learnings log without
# an extra Haiku call. Order matters: more specific first, default last.
#
# Phase 12.3 — keywords are now matched with \b word-boundary regex (not
# substring). This eliminates the substring-bug class that previously
# caused false positives like:
#   "production" matched "product"  (work)
#   "executive review" matched "execute"  (no current keyword, but same class)
#   "fasting protocol" matched "fast"  (now: only matches "fasting" because
#       we explicitly added it; "fast car" no longer false-positives body)
#
# Keywords ending in `~` become prefix matchers (\bkw\w*) — used for the
# small set of intentional substring matches like "synthesi~" → matches
# synthesis, synthesise, synthesised, synthesizing, etc. without the
# false-positive class.
_DIMENSION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("body",          ("body", "sleep", "exercise", "fitness", "health",
                       "tired", "energy", "muscle", "diet", "fast",
                       "fasting", "sauna", "cold plunge", "embodi~",
                       "workout", "yoga", "ran", "running", "walk",
                       "walked", "walking")),
    ("wealth",        ("money", "wealth", "spending", "budget", "saving",
                       "invest", "investing", "salary", "income",
                       "expense", "stock", "401k", "retirement")),
    ("relationships", ("wife", "husband", "spouse", "partner", "kid",
                       "kids", "child", "children", "son", "daughter",
                       "father", "mother", "family", "friend", "friends",
                       "marriage", "parenting", "love", "intimacy")),
    ("work",          ("manager", "team", "career", "promotion",
                       "1:1", "sprint", "stakeholder", "leadership",
                       "coworker", "colleague", "boss")),
    ("voice",         ("writing", "essay", "voice note", "podcast",
                       "speak", "publish", "draft", "post", "share",
                       "newsletter", "talk", "voice")),
    ("creative",      ("draw", "drawing", "render", "image", "art",
                       "make", "build", "create", "creative",
                       "design", "alicia draws")),
    ("practice",      ("practice", "ritual", "discipline", "routine",
                       "habit", "daily", "morning routine", "meditation",
                       "journaling", "checkin", "showed up")),
    ("shadow",        ("avoid~", "blind spot", "denial", "resist~",
                       "shadow", "afraid", "fear", "shame",
                       "contradict~", "tension", "growth edge",
                       "struggl~")),
    ("knowledge",     ("read", "book", "learn", "synthesi~", "concept",
                       "idea", "thinker", "philosopher", "author",
                       "study", "research")),
    # identity = default fallback (values, self-image, becoming)
)


def _compile_dimension_patterns() -> list[tuple[str, "re.Pattern"]]:
    """Compile each dimension's keyword tuple into a single \\b-anchored regex.

    A keyword ending in `~` becomes a prefix matcher: `synthesi~` →
    \\bsynthesi\\w* (matches synthesis, synthesise, synthesised, etc.).
    Multi-word phrases like 'design team' compile cleanly because \\b
    only requires a word-boundary at start/end, not between internal spaces.
    """
    import re as _re
    out: list[tuple[str, _re.Pattern]] = []
    for dim, kws in _DIMENSION_KEYWORDS:
        parts: list[str] = []
        for kw in kws:
            kw = kw.strip()
            if not kw:
                continue
            if kw.endswith("~"):
                # Prefix matcher: \bstem\w*
                stem = _re.escape(kw[:-1])
                parts.append(rf"\b{stem}\w*")
            else:
                # Full word(s): \bphrase\b
                parts.append(rf"\b{_re.escape(kw)}\b")
        if not parts:
            continue
        pattern = _re.compile("|".join(parts), _re.IGNORECASE)
        out.append((dim, pattern))
    return out


# Compile once at import time.
_DIMENSION_PATTERNS: list[tuple[str, "re.Pattern"]] = _compile_dimension_patterns()


def classify_dimension(text: str, *, ext_type: str = "") -> str:
    """Best-effort dimension assignment by \\b-anchored keyword matching.
    Defaults to 'identity' (the most general) when nothing matches.

    Phase 12.1 uses this to auto-tag every kept memory extraction without
    an extra LLM call. The classification is intentionally coarse — the
    delta surface (compute_dimension_counts, find_thin_dimensions) cares
    about RELATIVE distribution across dimensions, not perfect tagging.

    Phase 12.3: word-boundary regex replaces substring matching to kill
    the substring-bug class (e.g. 'production' no longer matches 'product').
    """
    if not text:
        return "identity"
    # ext_type hint — preferences often map to body/wealth/practice/voice
    if ext_type == "preference":
        for dim, pattern in _DIMENSION_PATTERNS:
            if dim in ("body", "wealth", "practice", "voice"):
                if pattern.search(text):
                    return dim
    for dim, pattern in _DIMENSION_PATTERNS:
        if pattern.search(text):
            return dim
    # Concepts default to knowledge; everything else to identity.
    if ext_type == "concept":
        return "knowledge"
    return "identity"


# ── Baseline init ──────────────────────────────────────────────────────────


def get_active_baseline() -> Optional[Path]:
    """Return the most recent baseline file, or None if no baseline yet."""
    if not BASELINES_DIR.is_dir():
        return None
    files = sorted(BASELINES_DIR.glob("*.md"))
    return files[-1] if files else None


def init_baseline(label: Optional[str] = None,
                  *, now: Optional[datetime] = None) -> Path:
    """Create a baseline snapshot of the current memory state.

    Concatenates MEMORY.md + patterns + insights + preferences + concepts
    into a single timestamped vault file. Future deltas compare against
    this snapshot. If a baseline already exists for today, raises — Phase 12
    treats the baseline as a foundational moment, not a daily refresh.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    stamp = now_utc.astimezone().strftime("%Y-%m-%d")
    label_part = f"-{label}" if label else ""
    target = BASELINES_DIR / f"baseline-{stamp}{label_part}.md"
    if target.exists():
        raise RuntimeError(
            f"Baseline already exists for {stamp}: {target}. "
            f"Pass label= for a second baseline today."
        )
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    parts: list[str] = [
        f"# {USER_NAME} Baseline — {stamp}",
        "",
        f"*Snapshot of who Alicia thought {USER_NAME} was on {stamp}.*",
        "",
        f"**Captured at:** {now_utc.isoformat()}",
        "",
        "*Phase 12 reference frame. Future learnings get logged in "
        "`user_learnings.jsonl`; the delta between this baseline and "
        f"the accumulated learnings is the arc of {USER_NAME}'s becoming.*",
        "",
        "---",
        "",
    ]
    for label_str, src in BASELINE_SOURCES:
        parts.append(f"## {label_str} — `{src.name}`")
        parts.append("")
        if src.exists():
            try:
                parts.append(src.read_text(encoding="utf-8").rstrip())
            except Exception as e:
                parts.append(f"_(read error: {e})_")
        else:
            parts.append(f"_(file not present at baseline time: {src})_")
        parts.append("")
        parts.append("---")
        parts.append("")

    target.write_text("\n".join(parts), encoding="utf-8")
    log.info(f"{USER_NAME} baseline initialised → {target}")
    return target


def days_since_baseline(*, now: Optional[datetime] = None) -> Optional[int]:
    """Days since the active baseline was captured, or None if no baseline."""
    p = get_active_baseline()
    if p is None:
        return None
    # Filename format: baseline-YYYY-MM-DD[-label].md
    m = re.match(r"^baseline-(\d{4}-\d{2}-\d{2})", p.stem)
    if not m:
        return None
    try:
        baseline_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return None
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return max(0, (now_utc - baseline_date).days)


# ── Learnings log (append-only) ─────────────────────────────────────────────


def append_learning(
    claim: str,
    dimension: str,
    confidence: float = 0.7,
    *,
    source: Optional[str] = None,
    evidence: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Append a learning to the log. Validates inputs but never raises on
    valid input — the log is best-effort write-through state.

    Args:
        claim:       short statement of what Alicia learned ("the user prefers
                     evening practice to morning practice")
        dimension:   one of DIMENSIONS — the slot this learning lands in
        confidence:  0.0–1.0; subjective signal of how sure Alicia is
        source:      optional pointer ("memory_skill", "reflexion:<path>",
                     "capture:<filename>", "manual", etc.)
        evidence:    optional supporting quote / context

    Returns the dict that was appended.
    """
    if not claim or not claim.strip():
        raise ValueError("claim is required")
    if dimension not in DIMENSIONS:
        raise ValueError(
            f"dimension must be one of {DIMENSIONS}, got {dimension!r}"
        )
    confidence = max(0.0, min(1.0, float(confidence)))
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    entry = {
        "ts": now_utc.isoformat(),
        "claim": claim.strip(),
        "dimension": dimension,
        "confidence": round(confidence, 3),
        "source": source or "manual",
        "evidence": (evidence or "").strip()[:500] or None,
    }
    # Phase 16.0 — conversation tag (default for now)
    try:
        from myalicia.skills.conversations import tag as _tag_conv
        _tag_conv(entry)
    except Exception:
        pass
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with LEARNINGS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning(f"append_learning failed: {e}")
    return entry


def get_learnings(
    *,
    dimension: Optional[str] = None,
    since_days: Optional[int] = None,
    now: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
) -> list[dict]:
    """Return matching learnings, newest-first.

    Args:
        dimension:  filter to one DIMENSIONS value (None = all)
        since_days: only include learnings within the last N days (None = all)
        conversation_id: Phase 16.2 — filter to one conversation. None means
            'all conversations' (whole-vault view). Pass a specific id (or
            current_conversation_id()) to scope the becoming-arc to that
            thread. Entries written before Phase 16.0 (no conversation_id
            field) are treated as belonging to 'default'.
    """
    if not LEARNINGS_LOG.exists():
        return []
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    cutoff = now_utc - timedelta(days=since_days) if since_days else None
    out: list[dict] = []
    try:
        with LEARNINGS_LOG.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if dimension and entry.get("dimension") != dimension:
                    continue
                # Phase 16.2 — conversation scoping. None = no filter.
                if conversation_id is not None:
                    entry_cid = (entry.get("conversation_id") or "default")
                    if entry_cid != conversation_id:
                        continue
                if cutoff is not None:
                    try:
                        ts = datetime.fromisoformat(entry["ts"])
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts < cutoff:
                            continue
                    except Exception:
                        continue
                out.append(entry)
    except Exception as e:
        log.warning(f"get_learnings read error: {e}")
        return []
    out.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return out


# ── Delta + gap analysis ───────────────────────────────────────────────────


def compute_dimension_counts(
    *,
    since_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """{dimension: count} of learnings, optionally restricted to last N days."""
    counts: dict[str, int] = {d: 0 for d in DIMENSIONS}
    for entry in get_learnings(since_days=since_days, now=now):
        d = entry.get("dimension")
        if d in counts:
            counts[d] += 1
    return counts


def find_thin_dimensions(
    *,
    stale_after_days: int = 14,
    now: Optional[datetime] = None,
) -> list[str]:
    """Return the list of dimensions with NO learnings in the last
    `stale_after_days` days.

    These are the gaps that drive Phase 12.1 — research scheduler,
    archetype EMA, and question generation will use this list to
    prioritise where Alicia next reaches.
    """
    recent_counts = compute_dimension_counts(
        since_days=stale_after_days, now=now,
    )
    return [d for d in DIMENSIONS if recent_counts.get(d, 0) == 0]


def find_dimensions_movement(
    *,
    recent_days: int = 14,
    older_days: int = 90,
    now: Optional[datetime] = None,
) -> list[tuple[str, int, int]]:
    """For each dimension, return (dimension, recent_count, older_count).
    Sorted by recent count desc — the dimensions most active right now
    appear first. Together with find_thin_dimensions, this is the basic
    delta surface."""
    now_utc = now or datetime.now(timezone.utc)
    recent = compute_dimension_counts(since_days=recent_days, now=now_utc)
    older = compute_dimension_counts(since_days=older_days, now=now_utc)
    rows = [(d, recent[d], older[d]) for d in DIMENSIONS]
    rows.sort(key=lambda r: (-r[1], -r[2]))
    return rows


# ── /becoming dashboard ────────────────────────────────────────────────────


def render_becoming_dashboard(
    *, now: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
) -> str:
    """Render the /becoming Telegram dashboard. Surfaces the arc:
       - baseline date + days since
       - total learnings + recent vs all-time
       - top moving dimensions (most learnings in last 14 days)
       - thin dimensions (no learning in last 14 days — Phase 12.1 gap fuel)

    Phase 16.2 — `conversation_id` scopes the view:
        - None: all conversations (whole-vault becoming arc)
        - "default" / "work" / etc.: only learnings tagged with that
          conversation. Dimensions counts + recent/thin are all scoped.
    The header surfaces which conversation is active so the view is
    unambiguous.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    lines = ["📈 *Becoming — who you were vs who you're becoming*"]

    # Phase 16.2 — conversation scope banner
    if conversation_id is not None:
        try:
            from myalicia.skills.conversations import get_conversation_meta
            meta = get_conversation_meta(conversation_id) or {}
            label = meta.get("label", conversation_id)
            lines.append(f"_scoped to conversation:_ *{label}* (`{conversation_id}`)")
        except Exception:
            lines.append(f"_scoped to:_ `{conversation_id}`")
    else:
        lines.append("_scope:_ all conversations")
    lines.append("")

    # Baseline status
    baseline = get_active_baseline()
    if baseline is None:
        lines.append("*Baseline:* not yet established.")
        lines.append(
            "_Run `init_baseline()` once to capture the current state of "
            "MEMORY.md as the reference frame for future deltas._"
        )
        lines.append("")
        return "\n".join(lines)

    days = days_since_baseline(now=now_utc) or 0
    lines.append(
        f"*Baseline:* `{baseline.name}` · {days} day{'s' if days != 1 else ''} ago"
    )
    lines.append("")

    # Totals (Phase 16.2 — pass conversation_id through to filter)
    all_learnings = get_learnings(now=now_utc, conversation_id=conversation_id)
    recent_learnings = get_learnings(
        since_days=14, now=now_utc, conversation_id=conversation_id,
    )
    lines.append(
        f"*Learnings logged since baseline:* {len(all_learnings)} "
        f"(last 14d: {len(recent_learnings)})"
    )
    lines.append("")

    if not all_learnings:
        lines.append(
            "_No learnings appended yet. Phase 12.1 will wire auto-extraction "
            "from memory_skill + reflexion. For now, append manually via the "
            "`append_learning(claim, dimension)` API._"
        )
        return "\n".join(lines)

    # Top moving dimensions (last 14d)
    moving = find_dimensions_movement(now=now_utc)
    lines.append("*Most active (last 14 days):*")
    shown = 0
    for d, recent, older in moving:
        if recent == 0:
            continue
        lines.append(f"  · {d:<14} {recent} new (90d total: {older})")
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        lines.append("  _(no recent activity)_")
    lines.append("")

    # Thin dimensions
    thin = find_thin_dimensions(now=now_utc)
    if thin:
        lines.append(f"*Gap dimensions (no learning in 14d, n={len(thin)}):*")
        lines.append(f"  {' · '.join(thin)}")
        lines.append(
            "  _These are the gaps Phase 12.1 will turn into research "
            "topics, archetype-EMA bumps, and morning questions._"
        )
        lines.append("")

    # Last 3 learnings (raw flavour)
    lines.append("*Most recent learnings:*")
    for entry in all_learnings[:3]:
        ts = (entry.get("ts") or "")[:10]
        d = entry.get("dimension", "?")
        claim = (entry.get("claim") or "")[:90]
        lines.append(f"  · _{ts}_ [{d}] {claim}")

    return "\n".join(lines)
