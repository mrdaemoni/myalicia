#!/usr/bin/env python3
"""
Layer 3 — Contradiction Detector.

Daily scheduled pass that keeps the structured contradiction ledger alive:

  1. Reads the last 7 days of reflections (reflexion_log.tsv + episodes/*.json)
     and memory updates (MEMORY.md, concepts.md, insights.md).
  2. Parses the active entries in /Alicia/Self/Contradictions.md.
  3. Scores each signal against each active entry's Pole A / Pole B. Matches
     ≥ EVIDENCE_THRESHOLD bump the entry's `Last updated` field and append a
     brief evidence-line.
  4. Optionally drafts new entries when an injected `llm` callable is
     available — v1 ships without the LLM path wired, keeping the pass
     deterministic and API-free.
  5. Runs a lineage-unused scan: walks /Alicia/Wisdom/Lineages/*.md, greps
     the vault for the lineage tag, and flags any lineage whose tag has not
     appeared in a synthesis within LINEAGE_UNUSED_DAYS days.

By keeping the ledger fresh, the Circulation Composer (Layer 2) picks up
new contradiction candidates on its next evening slot — no additional
wiring needed between modules.

Feature-flagged behind USE_CONTRADICTION_DETECTOR (default False). When
off, `run_daily_pass` performs a dry-run scan and writes nothing.

See /Alicia/Bridge/WISDOM_ENGINE_PROPOSAL.md §Layer 3 for the why.

Public API:
    collect_recent_signals(days=7, now=None) -> dict
    load_active_contradictions() -> list[dict]
    detect_contradictions(signals, active, *, llm=None) -> dict
    apply_drafts(detections, *, ledger_path=None, now=None) -> dict
    detect_lineage_unused(days=30, now=None) -> list[dict]
    mark_lineage_unused(unused) -> int
    check_invariants() -> list[dict]
    run_daily_pass(now=None, *, llm=None, dry_run=None) -> dict
    ContradictionDraft, EvidenceBump (dataclasses)
    USE_CONTRADICTION_DETECTOR (flag)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from myalicia.skills.safe_io import atomic_write_text
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.contradiction")

# ── Config ──────────────────────────────────────────────────────────────────

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", os.path.expanduser("~/alicia/memory")
))
CONTRADICTIONS_PATH = VAULT_ROOT / "Alicia" / "Self" / "Contradictions.md"
LINEAGES_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Lineages"
SYNTHESIS_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"
PREFERENCES_PATH = MEMORY_DIR / "preferences.md"
REFLEXION_LOG = MEMORY_DIR / "reflexion_log.tsv"
EPISODES_DIR = MEMORY_DIR / "episodes"
MEMORY_FILES = ("MEMORY.md", "concepts.md", "insights.md", "analysis_insights.md")

# Feature flag — default False, same rollout pattern as the composer.
USE_CONTRADICTION_DETECTOR = os.environ.get(
    "USE_CONTRADICTION_DETECTOR", "false"
).lower() in ("1", "true", "yes", "on")

# Evidence-bump threshold. Overlap score ≥ this triggers a Last-updated bump.
# Computed as Jaccard-like overlap on keyword sets (see _score_overlap).
EVIDENCE_THRESHOLD = 0.22

# Active-entry must be updated within this many days or it's flagged stale.
STALE_ACTIVE_DAYS = 60

# Lineage considered unused if its tag hasn't appeared in a synthesis within
# this window.
LINEAGE_UNUSED_DAYS = 30
UNUSED_LINEAGE_TAG = "#lineage/unused"

# Simple stopword set for keyword overlap scoring — English-only, tuned for
# the vault's prose register (short essays, reflections, syntheses).
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "else", "while", "is", "are",
    "was", "were", "be", "been", "being", "do", "does", "did", "have", "has",
    "had", "of", "in", "on", "at", "to", "for", "from", "with", "without",
    "by", "as", "into", "onto", "over", "under", "than", "that", "this",
    "these", "those", "it", "its", "itself", "you", "your", "i", "my", "me",
    "we", "our", "he", "she", "him", "her", "they", "them", "their",
    "not", "no", "nor", "so", "too", "very", "just", "can", "could", "would",
    "should", "will", "shall", "may", "might", "must", "about", "up", "out",
    "here", "there", "when", "where", "why", "how", "what", "which", "who",
    "whom", "whose", "only", "own", "same", "other", "another", "any",
    "some", "all", "most", "more", "less", "few", "several", "each", "every",
    "yet", "one", "two", "like", "also", "still", "even", "then", "now",
    "already", "often", "sometimes", "always", "never", "because", "though",
    "although", "rather", "quite", "well", "really", "thing", "things", "way",
})

# Tension cue phrases that — when they appear in a reflection — indicate a
# new ungrouped tension (even if no existing pole matches). Used for the
# draft-new-entry heuristic.
_TENSION_CUES: tuple[str, ...] = (
    "on the one hand",
    "on the other hand",
    "torn between",
    "can't decide",
    "but also",
    "at the same time",
    "simultaneously",
    "contradicts",
    "conflicts with",
    "in tension with",
    "tension between",
    # Phrase forms of "paradox" — bare keyword removed (over-fired in
    # <earlier development> dogfood: 8 of 14 noise drafts were system self-reflection
    # like "successfully captured the paradox of..." which isn't a real
    # the user tension — it's the system patting itself on the back).
    "the paradox is",
    "paradox of",
    "paradoxical situation",
)


# Phrases that suppress draft creation even if a tension cue is present.
# the user's tensions are HIS — they read like "I'm torn between X and Y" or
# "this contradicts what I said yesterday", not "successfully captured the
# paradox" (system self-praise) or "love that paradox" (affirmation) or
# "help me find" (a query).
_NOT_TENSION_PATTERNS: tuple[str, ...] = (
    # System self-praise (reflexion-style) — the system reporting on its
    # own successful processing. Never a the user tension.
    "successfully captured",
    "effectively captured",
    "successfully identified",
    "search effectively",
    "search successfully",
    "the system captured",
    # User affirmations — saying yes, not naming a tension
    "love that",
    "love this",
    "great paradox",
    "beautiful paradox",
    # User queries / requests — asking for something, not stating tension
    "help me find",
    "tell me your",
    "show me your",
    "what is your favorite",
    "what's your favorite",
    # Voice-tone-tagged positive states — signal the user is in a state of
    # discovery / delight, not internal conflict
    "[excited]",
    "[happy]",
    "[playful]",
    "[delighted]",
)


# Minimum signal length to be eligible for drafting. Short fragments like
# "Tell me your favorite one" (24 chars) or single-line reactions don't
# carry enough context to frame a tension's two poles.
DRAFT_MIN_LENGTH = 80


# Signal sources that may contribute evidence-bumps to existing entries but
# CANNOT generate new drafts. `reflexion` is the system's own self-talk
# about its processing — by construction it's not a the user tension.
_DRAFT_BLOCKED_SOURCES: frozenset[str] = frozenset({"reflexion"})


def _signal_passes_tension_filter(text: str) -> bool:
    """True iff the signal looks like a plausible new tension."""
    if not text:
        return False
    if len(text.strip()) < DRAFT_MIN_LENGTH:
        return False
    lower = text.lower()
    if not any(cue in lower for cue in _TENSION_CUES):
        return False
    if any(p in lower for p in _NOT_TENSION_PATTERNS):
        return False
    return True


def _signal_can_generate_draft(s: dict) -> bool:
    """True iff this signal source is eligible for new-draft generation.
    Reflexion-only signals can still bump existing entries via
    `_rule_detect`'s overlap-scoring path — they just can't spawn new ones.
    """
    return (s.get("source") or "") not in _DRAFT_BLOCKED_SOURCES


def _existing_draft_evidence_prefixes(
    ledger_path: Path, prefix_len: int = 100
) -> set[str]:
    """Read the ledger and return the set of `Evidence A` prefixes already
    drafted. Used to dedup so we don't regenerate the same draft daily.
    """
    if not ledger_path.exists():
        return set()
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except Exception:
        return set()
    prefixes: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^- \*\*Evidence A\*\* —\s*(.+)$", line)
        if m:
            ev = m.group(1).strip().lower()
            prefixes.add(ev[:prefix_len])
    return prefixes

# ── Types ───────────────────────────────────────────────────────────────────


@dataclass
class EvidenceBump:
    """An active contradiction whose Last updated should be bumped today."""
    title: str
    pole: str               # "A" | "B"
    archetype: str
    evidence_snippet: str   # short human-readable quote
    score: float
    signal_source: str      # "reflexion" | "episode" | "memory:<file>"
    signal_ts: Optional[str] = None


@dataclass
class ContradictionDraft:
    """A candidate new entry, flagged for human review."""
    title: str
    pole_a: str
    pole_b: str
    evidence_a: str
    evidence_b: str
    archetype: str = "Psyche"   # default — draft status, the user re-homes
    status: str = "draft"        # not `active` until human review
    rationale: str = ""
    score: float = 0.0


# ── Signal collection ───────────────────────────────────────────────────────


def _iso_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _read_text_safe(path: Path, limit: int = 200_000) -> str:
    try:
        if path.exists():
            data = path.read_text(encoding="utf-8", errors="replace")
            return data[:limit]
    except Exception as e:
        log.debug(f"could not read {path}: {e}")
    return ""


def _collect_reflections(cutoff: datetime) -> list[dict]:
    """Pull reflection rows from reflexion_log.tsv whose ts >= cutoff."""
    out: list[dict] = []
    if not REFLEXION_LOG.exists():
        return out
    try:
        with REFLEXION_LOG.open(encoding="utf-8") as f:
            header = f.readline()  # noqa: F841 — skip header
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 4:
                    continue
                ts_str, task_type, went_well, to_improve = cols[0], cols[1], cols[2], cols[3]
                # ts format is "YYYY-MM-DD HH:MM" (local naive)
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                out.append({
                    "source": "reflexion",
                    "ts": ts.isoformat(),
                    "task_type": task_type,
                    "text": f"{went_well}\n{to_improve}".strip(),
                })
    except Exception as e:
        log.warning(f"reflexion_log parse error: {e}")
    return out


def _collect_episodes(cutoff: datetime, max_files: int = 400) -> list[dict]:
    """Pull episode input/output text from episodes/*.json whose ts >= cutoff."""
    out: list[dict] = []
    if not EPISODES_DIR.exists():
        return out
    try:
        files = sorted(EPISODES_DIR.glob("*.json"))[-max_files:]
    except Exception:
        files = []
    for p in files:
        try:
            ep = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ts = _parse_iso(str(ep.get("timestamp") or ""))
        if ts is None or ts < cutoff:
            continue
        parts = [ep.get("input") or "", ep.get("output") or ""]
        refl = ep.get("reflection") or {}
        if isinstance(refl, dict):
            parts.append(refl.get("went_well") or "")
            parts.append(refl.get("to_improve") or "")
        text = "\n".join(x for x in parts if x).strip()
        if not text:
            continue
        out.append({
            "source": "episode",
            "ts": ts.isoformat(),
            "task_type": ep.get("task_type") or "",
            "text": text[:4_000],
        })
    return out


def _collect_memory_snapshots() -> list[dict]:
    """Read current memory files. Whole-file snapshots are scored as a unit."""
    out: list[dict] = []
    for name in MEMORY_FILES:
        path = MEMORY_DIR / name
        text = _read_text_safe(path, limit=60_000)
        if text:
            out.append({
                "source": f"memory:{name}",
                "ts": None,
                "text": text,
            })
    return out


def collect_recent_signals(
    days: int = 7, *, now: Optional[datetime] = None
) -> dict:
    """
    Gather all signals the detector scores against active contradictions.

    Returns:
        {
            "cutoff":       ISO datetime of the window start,
            "reflections":  list of {source, ts, task_type, text},
            "episodes":     list of {source, ts, task_type, text},
            "memory":       list of {source, ts, text},
            "preferences":  str,   # preferences.md contents
        }

    Pure — does no writes. Safe to call from tests.
    """
    now_utc = now or _iso_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    cutoff = now_utc - timedelta(days=days)
    return {
        "cutoff": cutoff.isoformat(),
        "reflections": _collect_reflections(cutoff),
        "episodes": _collect_episodes(cutoff),
        "memory": _collect_memory_snapshots(),
        "preferences": _read_text_safe(PREFERENCES_PATH, limit=40_000),
    }


# ── Contradictions ledger — parse + write ───────────────────────────────────


_HEADER_RE = re.compile(r"^###\s+(\d+)\.\s*(.+?)\s*$")
_LAST_UPDATED_RE = re.compile(r"^-\s+\*\*Last updated\*\*\s+—\s+(.+?)\s*$")
_POLE_A_RE = re.compile(r"^-\s+\*\*Pole A\*\*\s+—\s*(.+?)\s*$")
_POLE_B_RE = re.compile(r"^-\s+\*\*Pole B\*\*\s+—\s*(.+?)\s*$")
_ARCHETYPE_RE = re.compile(r"^-\s+\*\*Archetype home\*\*\s+—\s*(.+?)\s*$")
_STATUS_RE = re.compile(r"^-\s+\*\*Status\*\*\s+—\s*(.+?)\s*$")
_EVIDENCE_A_RE = re.compile(r"^-\s+\*\*Evidence A\*\*\s+—\s*(.+?)\s*$")
_EVIDENCE_B_RE = re.compile(r"^-\s+\*\*Evidence B\*\*\s+—\s*(.+?)\s*$")


def load_active_contradictions(
    path: Optional[Path] = None,
) -> list[dict]:
    """
    Parse Contradictions.md. Returns a list of dicts for ALL entries (not
    just active) so consumers can filter as needed. Each dict:

        {
            "idx":          "1",
            "title":        "Acquisition urge vs...",
            "pole_a":       "...",
            "pole_b":       "...",
            "evidence_a":   "...",
            "evidence_b":   "...",
            "archetype":    "Daimon",
            "status":       "active",
            "last_updated": "2026-04-22",
            "header_line":  original header text (for write-back),
            "block_start":  int line index,
            "block_end":    int line index,   # exclusive
        }
    """
    p = path or CONTRADICTIONS_PATH
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    entries: list[dict] = []
    cur: Optional[dict] = None
    cur_start = 0
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if m:
            if cur is not None:
                cur["block_end"] = i
                entries.append(cur)
            cur = {
                "idx": m.group(1),
                "title": m.group(2).strip(),
                "pole_a": "",
                "pole_b": "",
                "evidence_a": "",
                "evidence_b": "",
                "archetype": "",
                "status": "",
                "last_updated": "",
                "header_line": line,
                "block_start": i,
                "block_end": None,
            }
            cur_start = i
            continue
        if cur is None:
            continue
        for regex, field_name in (
            (_POLE_A_RE, "pole_a"),
            (_POLE_B_RE, "pole_b"),
            (_EVIDENCE_A_RE, "evidence_a"),
            (_EVIDENCE_B_RE, "evidence_b"),
            (_ARCHETYPE_RE, "archetype"),
            (_STATUS_RE, "status"),
            (_LAST_UPDATED_RE, "last_updated"),
        ):
            mm = regex.match(line)
            if mm:
                val = mm.group(1).strip()
                if field_name == "status":
                    # strip backticks
                    val = val.strip("`").strip()
                elif field_name == "archetype":
                    # take the first Archetype token found
                    for a in ("Daimon", "Beatrice", "Ariadne", "Psyche", "Musubi", "Muse"):
                        if a in val:
                            val = a
                            break
                cur[field_name] = val
                break
    if cur is not None:
        cur["block_end"] = len(lines)
        entries.append(cur)
    return entries


# ── Keyword overlap scoring ─────────────────────────────────────────────────


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    toks = {t.lower() for t in _WORD_RE.findall(text)}
    return {t for t in toks if t not in _STOPWORDS and len(t) >= 4}


def _score_overlap(pole: str, signal: str) -> float:
    """
    Containment score: what fraction of the pole's content tokens appear in
    the signal. Asymmetric by design — poles are short dense sentences,
    signals are long messy text. Jaccard would drown the pole in signal
    entropy; containment answers the right question ("does this signal
    engage with this pole's concept space?").
    """
    tp, ts = _tokens(pole), _tokens(signal)
    if not tp or not ts:
        return 0.0
    inter = tp & ts
    return len(inter) / len(tp)


def _best_snippet(signal_text: str, max_len: int = 180) -> str:
    """Return a compact single-line snippet of the signal for Evidence lines."""
    first = (signal_text or "").strip().split("\n", 1)[0].strip()
    if len(first) > max_len:
        first = first[: max_len - 1].rstrip() + "…"
    return first


# ── Detection (rule-based; LLM path optional) ───────────────────────────────


def _rule_detect(
    signals: dict, active: list[dict]
) -> tuple[list[EvidenceBump], list[ContradictionDraft]]:
    """
    Rule-based detector.

    Evidence bumps: for every (signal × active entry) pair, score against
    Pole A and Pole B. The higher-scoring pole wins if it clears the
    threshold. Ties are broken toward Pole A (no-op in practice — rare).

    New drafts: any reflection that contains a tension cue AND doesn't score
    above threshold against any existing pole becomes a draft with
    status='draft' — not written active, just queued for human review.
    """
    active_entries = [e for e in active if (e.get("status") or "").lower() == "active"]

    bumps: list[EvidenceBump] = []
    drafts: list[ContradictionDraft] = []

    # Flatten all signals into one iterable with provenance preserved
    all_signals: list[dict] = []
    for key in ("reflections", "episodes", "memory"):
        for s in signals.get(key, []) or []:
            all_signals.append(s)

    for s in all_signals:
        text = s.get("text") or ""
        if not text:
            continue

        best_entry: Optional[dict] = None
        best_pole: Optional[str] = None
        best_score = 0.0

        for entry in active_entries:
            # NB: _score_overlap is asymmetric — (pole, signal), not (signal, pole).
            pa = _score_overlap(entry.get("pole_a") or "", text)
            pb = _score_overlap(entry.get("pole_b") or "", text)
            sc, pole = (pa, "A") if pa >= pb else (pb, "B")
            if sc > best_score:
                best_entry = entry
                best_pole = pole
                best_score = sc

        if best_entry is not None and best_score >= EVIDENCE_THRESHOLD:
            bumps.append(EvidenceBump(
                title=best_entry["title"],
                pole=best_pole or "A",
                archetype=best_entry.get("archetype") or "Daimon",
                evidence_snippet=_best_snippet(text),
                score=round(best_score, 3),
                signal_source=s.get("source") or "",
                signal_ts=s.get("ts"),
            ))
            continue

        # No active match → propose a draft only when ALL precision filters
        # agree. Phase 11.3 hardening (<earlier development> dogfood):
        #   1. Reflexion-source signals never spawn drafts (system self-talk
        #      isn't a the user tension).
        #   2. The text must contain a tightened tension cue AND not contain
        #      any NOT-tension pattern (system self-praise, affirmations,
        #      user queries, voice-tone tags signaling positive states).
        #   3. Signal must be at least DRAFT_MIN_LENGTH chars long — short
        #      fragments don't carry enough context to frame two poles.
        if not _signal_can_generate_draft(s):
            continue
        if not _signal_passes_tension_filter(text):
            continue
        snippet = _best_snippet(text, max_len=220)
        drafts.append(ContradictionDraft(
            title=f"Draft — {snippet[:60]}",
            pole_a="(needs human phrasing)",
            pole_b="(needs human phrasing)",
            evidence_a=snippet,
            evidence_b="",
            archetype="Psyche",
            status="draft",
            rationale=f"Tension cue detected in {s.get('source','')} at {s.get('ts','')}",
            score=0.0,
        ))

    return bumps, drafts


def _llm_detect(
    signals: dict,
    active: list[dict],
    llm: Callable[[str], str],
) -> tuple[list[EvidenceBump], list[ContradictionDraft]]:
    """
    Optional LLM path. `llm(prompt) -> str` should return JSON:

        {"bumps": [...], "drafts": [...]}

    Schema matches the dataclasses. Failures fall back to rule-based.
    """
    try:
        prompt = (
            f"You are auditing {USER_NAME}'s contradiction ledger. Given the active "
            "entries and recent signals below, return JSON with two arrays:\n"
            "  bumps:  [{title, pole, archetype, evidence_snippet, score, signal_source}]\n"
            "  drafts: [{title, pole_a, pole_b, evidence_a, evidence_b, archetype, rationale}]\n\n"
            f"ACTIVE ENTRIES:\n{json.dumps(active, indent=2)[:8000]}\n\n"
            f"SIGNALS:\n{json.dumps(signals, indent=2)[:8000]}\n"
        )
        raw = llm(prompt)
        parsed = json.loads(raw)
        bumps = [EvidenceBump(**b) for b in parsed.get("bumps", [])]
        drafts = [ContradictionDraft(**d) for d in parsed.get("drafts", [])]
        return bumps, drafts
    except Exception as e:
        log.warning(f"LLM detect failed ({e}); falling back to rule-based")
        return _rule_detect(signals, active)


def detect_contradictions(
    signals: Optional[dict] = None,
    active: Optional[list[dict]] = None,
    *,
    llm: Optional[Callable[[str], str]] = None,
) -> dict:
    """
    Main entry. Returns:
        {"bumps": [EvidenceBump...], "drafts": [ContradictionDraft...]}

    Both lists may be empty. This function is pure — no writes.
    """
    if signals is None:
        signals = collect_recent_signals()
    if active is None:
        active = load_active_contradictions()
    if llm is not None:
        bumps, drafts = _llm_detect(signals, active, llm)
    else:
        bumps, drafts = _rule_detect(signals, active)
    # De-duplicate bumps by (title, pole), keep highest score
    dedup: dict[tuple[str, str], EvidenceBump] = {}
    for b in bumps:
        key = (b.title, b.pole)
        if key not in dedup or b.score > dedup[key].score:
            dedup[key] = b
    return {
        "bumps": list(dedup.values()),
        "drafts": drafts,
    }


# ── Ledger writer ───────────────────────────────────────────────────────────


def apply_drafts(
    detections: dict,
    *,
    ledger_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Write detections back to the ledger.

      * Evidence bumps update the matched entry's Last updated field (today).
      * Draft entries are APPENDED to a "## Drafts (pending human review)"
        section — never merged into `## Entries` without a human stamp.

    Returns {"bumps_applied": int, "drafts_appended": int, "ledger_path": str}.
    """
    p = ledger_path or CONTRADICTIONS_PATH
    bumps: list[EvidenceBump] = list(detections.get("bumps", []))
    drafts: list[ContradictionDraft] = list(detections.get("drafts", []))
    if not bumps and not drafts:
        return {"bumps_applied": 0, "drafts_appended": 0, "ledger_path": str(p)}

    if not p.exists():
        log.warning(f"apply_drafts: ledger missing at {p}; skipping writes")
        return {"bumps_applied": 0, "drafts_appended": 0, "ledger_path": str(p)}

    now_utc = now or _iso_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")

    lines = p.read_text(encoding="utf-8").splitlines()
    entries = load_active_contradictions(path=p)
    # Index entries by title for quick lookup
    by_title: dict[str, dict] = {e["title"]: e for e in entries}

    # Apply bumps — only modify the Last updated line of the matched block.
    bumps_applied = 0
    for b in bumps:
        entry = by_title.get(b.title)
        if not entry:
            log.debug(f"bump for unknown title (dropped): {b.title!r}")
            continue
        start, end = entry["block_start"], entry["block_end"]
        touched = False
        for j in range(start, end):
            if _LAST_UPDATED_RE.match(lines[j]):
                lines[j] = f"- **Last updated** — {today}"
                touched = True
                break
        if touched:
            bumps_applied += 1

    # Append drafts block — idempotent header, append-only body.
    # Dedup against existing drafts by Evidence A prefix so daily re-runs
    # don't regenerate the same draft when the underlying signal hasn't
    # changed (<earlier development> produced 4 dupes across
    # day-23/day-24).
    drafts_appended = 0
    drafts_skipped_duplicate = 0
    if drafts:
        existing_prefixes = _existing_draft_evidence_prefixes(p)
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "## Drafts (pending human review)":
                header_idx = i
                break
        if header_idx is None:
            # Append at end, before the schema footer if present.
            lines.append("")
            lines.append("## Drafts (pending human review)")
            lines.append("")
            lines.append(
                "_Auto-generated by `skills/contradiction_detector.py`. "
                f"Promote to `## Entries` only after {USER_NAME} confirms pole framing._"
            )
            lines.append("")
        for d in drafts:
            ev_prefix = (d.evidence_a or "").strip().lower()[:100]
            if ev_prefix in existing_prefixes:
                drafts_skipped_duplicate += 1
                continue
            existing_prefixes.add(ev_prefix)
            lines.append(f"### DRAFT {today} — {d.title[:120]}")
            lines.append("")
            lines.append(f"- **Pole A** — {d.pole_a}")
            lines.append(f"- **Pole B** — {d.pole_b}")
            lines.append(f"- **Evidence A** — {d.evidence_a}")
            if d.evidence_b:
                lines.append(f"- **Evidence B** — {d.evidence_b}")
            lines.append(f"- **Archetype home** — {d.archetype} (draft)")
            lines.append(f"- **Status** — `draft`")
            lines.append(f"- **Last updated** — {today}")
            if d.rationale:
                lines.append(f"- **Detector note** — {d.rationale}")
            lines.append("")
            drafts_appended += 1

    atomic_write_text(str(p), "\n".join(lines).rstrip() + "\n")
    return {
        "bumps_applied": bumps_applied,
        "drafts_appended": drafts_appended,
        "drafts_skipped_duplicate": drafts_skipped_duplicate,
        "ledger_path": str(p),
    }


# ── Lineage-unused detector ─────────────────────────────────────────────────


_LINEAGE_TAG_RE = re.compile(r"`?#lineage/([a-z0-9][a-z0-9_-]*)`?", re.IGNORECASE)


def _lineage_slug_from_file(lineage_md: Path) -> Optional[str]:
    """Extract the `#lineage/<slug>` declared inside the lineage note."""
    text = _read_text_safe(lineage_md, limit=8_000)
    m = _LINEAGE_TAG_RE.search(text)
    if m:
        return m.group(1).lower()
    # Fallback: derive from filename (e.g. Pirsig-line.md → pirsig)
    name = lineage_md.stem.lower().replace("-line", "").replace("_line", "")
    return name or None


def detect_lineage_unused(
    days: int = LINEAGE_UNUSED_DAYS,
    *,
    now: Optional[datetime] = None,
    synthesis_dir: Optional[Path] = None,
) -> list[dict]:
    """
    Walk the Lineages/ directory, cross-reference each lineage tag against
    synthesis notes, and return a list of lineages whose tag hasn't appeared
    in a synthesis modified within `days`. Each result dict:

        {"lineage": "Pirsig-line", "slug": "pirsig", "last_seen": ISO | None,
         "path": "/.../Pirsig-line.md"}
    """
    sd = synthesis_dir or SYNTHESIS_DIR
    if not LINEAGES_DIR.exists():
        return []

    now_utc = now or _iso_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    results: list[dict] = []
    lineage_files = [p for p in LINEAGES_DIR.glob("*.md") if p.name != "README.md"]
    # Precompute the synthesis corpus once.
    synth_files: list[tuple[Path, str]] = []
    if sd.exists():
        for sp in sd.rglob("*.md"):
            try:
                synth_files.append((sp, sp.read_text(encoding="utf-8", errors="replace")))
            except Exception:
                continue

    for lf in lineage_files:
        slug = _lineage_slug_from_file(lf)
        if not slug:
            continue
        tag_pattern = re.compile(rf"#lineage/{re.escape(slug)}\b", re.IGNORECASE)
        last_seen: Optional[datetime] = None
        for sp, stext in synth_files:
            if not tag_pattern.search(stext):
                continue
            try:
                mtime = datetime.fromtimestamp(sp.stat().st_mtime, tz=timezone.utc)
            except Exception:
                continue
            if last_seen is None or mtime > last_seen:
                last_seen = mtime
        if last_seen is None or last_seen < cutoff:
            results.append({
                "lineage": lf.stem,
                "slug": slug,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "path": str(lf),
            })
    return results


def mark_lineage_unused(unused: Iterable[dict]) -> int:
    """
    Append the `#lineage/unused` tag to each unused lineage note (once).
    Returns the count of files actually modified.
    """
    modified = 0
    for item in unused:
        path = Path(item.get("path") or "")
        if not path.exists():
            continue
        text = _read_text_safe(path, limit=200_000)
        if not text or UNUSED_LINEAGE_TAG in text:
            continue
        stamp = _iso_now().strftime("%Y-%m-%d")
        addition = (
            f"\n\n---\n*Detector flag:* {UNUSED_LINEAGE_TAG} "
            f"— no syntheses cited this lineage in the last {LINEAGE_UNUSED_DAYS} days "
            f"(flagged {stamp}).\n"
        )
        try:
            atomic_write_text(str(path), text.rstrip() + addition)
            modified += 1
        except Exception as e:
            log.warning(f"failed to tag lineage {path}: {e}")
    return modified


# ── Invariants ──────────────────────────────────────────────────────────────


def check_invariants(
    *, now: Optional[datetime] = None, ledger_path: Optional[Path] = None
) -> list[dict]:
    """
    Invariant violations for the contradictions ledger:

      - stale_active_contradiction: `active` entry whose Last updated is
        older than STALE_ACTIVE_DAYS days.
      - resolved_freshly_updated:   `resolved` entry touched within
        STALE_ACTIVE_DAYS days (resolved should be frozen).
      - missing_archetype_home:     `active` entry without a known archetype.
      - malformed_last_updated:     `active` entry whose Last updated can't
        be parsed as YYYY-MM-DD.
    """
    now_utc = now or _iso_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    violations: list[dict] = []
    entries = load_active_contradictions(path=ledger_path)
    known_archetypes = {"Daimon", "Beatrice", "Ariadne", "Psyche", "Musubi", "Muse"}

    for e in entries:
        status = (e.get("status") or "").lower()
        title = e.get("title") or ""
        lu_raw = (e.get("last_updated") or "").strip()
        lu_dt: Optional[datetime] = None
        if lu_raw:
            try:
                lu_dt = datetime.strptime(lu_raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                lu_dt = None

        if status == "active":
            if not e.get("archetype") or e["archetype"] not in known_archetypes:
                violations.append({
                    "kind": "missing_archetype_home", "title": title,
                    "archetype": e.get("archetype"),
                })
            if lu_raw and lu_dt is None:
                violations.append({
                    "kind": "malformed_last_updated", "title": title, "value": lu_raw,
                })
            elif lu_dt is not None:
                age_days = (now_utc - lu_dt).days
                if age_days > STALE_ACTIVE_DAYS:
                    violations.append({
                        "kind": "stale_active_contradiction", "title": title,
                        "last_updated": lu_raw, "age_days": age_days,
                    })
        elif status == "resolved":
            if lu_dt is not None:
                age_days = (now_utc - lu_dt).days
                if 0 <= age_days <= STALE_ACTIVE_DAYS:
                    violations.append({
                        "kind": "resolved_freshly_updated", "title": title,
                        "last_updated": lu_raw, "age_days": age_days,
                    })

    return violations


# ── Orchestrator ────────────────────────────────────────────────────────────


def run_daily_pass(
    *,
    now: Optional[datetime] = None,
    llm: Optional[Callable[[str], str]] = None,
    dry_run: Optional[bool] = None,
) -> dict:
    """
    Daily scheduled entry point. When USE_CONTRADICTION_DETECTOR is False
    (default), runs in dry-run mode: reads + detects but performs no writes.

    When `dry_run` is passed explicitly, it wins over the flag.

    Returns a summary dict:
        {
            "dry_run": bool,
            "signals_total": int,
            "active_entries": int,
            "bumps": int,
            "drafts": int,
            "bumps_applied": int,
            "drafts_appended": int,
            "lineages_unused": int,
            "lineages_tagged": int,
            "invariant_violations": int,
        }
    """
    effective_dry = (not USE_CONTRADICTION_DETECTOR) if dry_run is None else bool(dry_run)
    signals = collect_recent_signals(now=now)
    active = load_active_contradictions()
    detections = detect_contradictions(signals, active, llm=llm)
    bumps = detections.get("bumps", [])
    drafts = detections.get("drafts", [])

    applied = {"bumps_applied": 0, "drafts_appended": 0}
    tagged = 0
    unused = detect_lineage_unused(now=now)

    if not effective_dry:
        applied = apply_drafts(detections, now=now)
        tagged = mark_lineage_unused(unused)

    violations = check_invariants(now=now)

    summary = {
        "dry_run": effective_dry,
        "signals_total": (
            len(signals.get("reflections", []))
            + len(signals.get("episodes", []))
            + len(signals.get("memory", []))
        ),
        "active_entries": sum(1 for e in active if (e.get("status") or "").lower() == "active"),
        "bumps": len(bumps),
        "drafts": len(drafts),
        "bumps_applied": applied.get("bumps_applied", 0),
        "drafts_appended": applied.get("drafts_appended", 0),
        "lineages_unused": len(unused),
        "lineages_tagged": tagged,
        "invariant_violations": len(violations),
    }
    log.info(f"[contradiction_detector] {summary}")
    return summary


# ── CLI (debug / dry-run) ──────────────────────────────────────────────────


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Contradiction Detector (debug)")
    parser.add_argument("--run", action="store_true", help="Run the daily pass honoring the feature flag")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run (no writes)")
    parser.add_argument("--check", action="store_true", help="Run invariant check and print violations")
    parser.add_argument("--signals", action="store_true", help="Dump recent signals (last 7 days)")
    parser.add_argument("--lineages", action="store_true", help="Dump unused-lineage candidates")
    args = parser.parse_args()

    if args.check:
        vs = check_invariants()
        by_kind: dict[str, int] = {}
        for v in vs:
            by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
        print("Invariant check:")
        for k, n in by_kind.items():
            print(f"  {k}: {n}")
        print(f"  total violations: {len(vs)}")
        return
    if args.signals:
        sig = collect_recent_signals()
        print(f"cutoff           {sig['cutoff']}")
        print(f"reflections      {len(sig['reflections'])}")
        print(f"episodes         {len(sig['episodes'])}")
        print(f"memory snapshots {len(sig['memory'])}")
        return
    if args.lineages:
        unused = detect_lineage_unused()
        for u in unused:
            print(f"  [unused] {u['lineage']:25s} last_seen={u['last_seen']}")
        print(f"total unused: {len(unused)}")
        return
    if args.run or args.dry_run:
        summary = run_daily_pass(dry_run=True if args.dry_run else None)
        print(json.dumps(summary, indent=2))
        return
    parser.print_help()


if __name__ == "__main__":
    _main()
