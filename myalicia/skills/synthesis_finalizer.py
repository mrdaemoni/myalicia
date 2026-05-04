#!/usr/bin/env python3
"""
Alicia — Skill: Synthesis Finalizer (Wisdom Engine · Layer 1)

Every time a new structured synthesis lands in /Alicia/Wisdom/Synthesis/, this
module closes the circulatory loop around it:

  1. Parses the `## The Claim Across Sources` section for cited sources.
  2. Appends a bidirectional backlink to each source's `*Connects to:*` footer
     (idempotent — skipped if already present).
  3. Appends the synthesis to each theme index under /Alicia/Wisdom/Themes/.
  4. Appends a row to /Alicia/Bridge/synthesis_results.tsv.
  5. Appends a paragraph to the current week's Bridge digest.
  6. Queues multi-stage surfacings (+4h, +24h, +72h, +7d, +21d) in
     `~/alicia/memory/synthesis_surfacing_queue.json`. The Circulation Composer
     (Layer 2, item #17) will consume these when it lands.

Design inheritance: this module is modelled on `afterglow.py`'s "seed → distributed
surfacing" pattern — but queued with a FIVE-stage schedule rather than a single
delivery, because a synthesis is a heavier object than a walk transcript.

Invariant (enforced by tests/test_synthesis_finalizer_invariant.py):
  Every wikilink in the `## The Claim Across Sources` section of every synthesis
  MUST have a reciprocal wikilink on the cited source's page. CI fails on any
  one-way edge.

Usage:
  - `finalize(path)` — finalize a single synthesis. Called by synthesis writers.
  - `finalize_all(dry_run=False)` — finalize every structured synthesis in the
     vault. Used by the backlink audit (item #15).
  - `check_invariant()` — returns a list of one-way edges. Used by tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Allow direct invocation (`python skills/synthesis_finalizer.py ...`) — when
# run as __main__ the `skills` package isn't on sys.path by default, which
# breaks the relative imports below. Prepending the repo root is harmless
# when invoked via `python -m skills.synthesis_finalizer` or from alicia.py.
if __package__ in (None, "") and __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from myalicia.skills.safe_io import atomic_write_json, locked_file
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────

VAULT_ROOT = Path(
    os.environ.get(
        "ALICIA_VAULT_ROOT",
        str(config.vault.root),
    )
)
SYNTHESIS_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"
THEMES_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Themes"
LIVED_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Lived"
PRACTICES_DIR = VAULT_ROOT / "Alicia" / "Practices"
BRIDGE_DIR = VAULT_ROOT / "Alicia" / "Bridge"
SYNTHESIS_LOG = BRIDGE_DIR / "synthesis_results.tsv"

# The canonical set of first-class source directories the Finalizer curates.
# Lived notes are the SIXTH tier — emitted by Layer 4 (practice_runner) on
# practice close. They get the same bidirectional graph treatment as Books,
# Quotes, writing, Wisdom concept notes, and the Synthesis corpus itself.
CANONICAL_SOURCE_DIRS: tuple[Path, ...] = (
    VAULT_ROOT / "Books",
    VAULT_ROOT / "Quotes",
    VAULT_ROOT / "writing",
    VAULT_ROOT / "Wisdom",
    SYNTHESIS_DIR,
    LIVED_DIR,
)

# Unused-Lived-note threshold. A Lived note older than this with zero
# syntheses citing it is flagged as an under-utilised source.
LIVED_UNUSED_DAYS = 90

MEMORY_DIR = Path(
    str(MEMORY_DIR)
)
SURFACING_QUEUE_FILE = MEMORY_DIR / "synthesis_surfacing_queue.json"

MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── Surfacing schedule ──────────────────────────────────────────────────────
# Each stage is a delay from synthesis finalize time. Stages fire in order;
# each has its own voice profile that the Circulation Composer (Layer 2) will
# interpret differently.
SURFACING_STAGES = [
    {"name": "fresh",        "delay_hours": 4,        "voice_hint": "still-warm"},
    {"name": "next_day",     "delay_hours": 24,       "voice_hint": "slept-on-it"},
    {"name": "three_days",   "delay_hours": 72,       "voice_hint": "settling"},
    {"name": "one_week",     "delay_hours": 24 * 7,   "voice_hint": "test-the-grip"},
    {"name": "three_weeks",  "delay_hours": 24 * 21,  "voice_hint": "test-of-time"},
]


# ── Parse layer ─────────────────────────────────────────────────────────────

# Matches a markdown wikilink, capturing the target (without .md):
#   [[Books/Lila/Lila-60]]  →  "Books/Lila/Lila-60"
#   [[80yrs old the user]]    →  "80yrs old the user"
#   [[writing/Flow]]        →  "writing/Flow"
# Does not capture alias syntax ([[target|alias]]) — takes target.
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?(?:#[^\]]*)?\]\]")

# Theme tags in frontmatter: `tags: [synthesis, alicia-generated, theme/quality, theme/mastery]`
_THEME_TAG_RE = re.compile(r"theme/([a-z0-9_\-]+)", re.IGNORECASE)


def parse_synthesis(path: str | Path) -> dict:
    """
    Parse a synthesis note file.

    Returns dict:
        {
            "path": Path,
            "title": str (from first '# ' heading),
            "themes": list[str] (lowercased, without 'theme/' prefix),
            "cited_sources": list[str] (wikilink targets from Claim section),
            "footer_connections": list[str] (wikilink targets from footer),
            "structured": bool (True if it has '## The Claim Across Sources'),
            "raw_text": str,
        }

    A synthesis is "structured" if it has '## The Claim Across Sources'. Only
    structured syntheses are eligible for full finalize (backlinks enforced on
    their cited sources).
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    # Title: first H1 heading
    title = p.stem
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    # Themes from frontmatter
    themes: list[str] = []
    # Only look at the first block between --- fences, if present
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    frontmatter = fm_match.group(1) if fm_match else ""
    for tm in _THEME_TAG_RE.finditer(frontmatter):
        themes.append(tm.group(1).lower())
    # Dedupe preserving order
    seen = set()
    themes = [t for t in themes if not (t in seen or seen.add(t))]

    # Extract `## The Claim Across Sources` block (until next `## ` or EOF)
    claim_block = ""
    structured = False
    cm = re.search(
        r"^##\s+The Claim Across Sources\s*\n(.+?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if cm:
        structured = True
        claim_block = cm.group(1)

    cited_sources = [w.strip() for w in _WIKILINK_RE.findall(claim_block)]
    # Dedupe preserving order
    seen = set()
    cited_sources = [s for s in cited_sources if not (s in seen or seen.add(s))]

    # Footer connections: last `*Connects to:*` line (anywhere in the file)
    footer_connections: list[str] = []
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("*Connects to:*"):
            footer_connections = [
                w.strip() for w in _WIKILINK_RE.findall(stripped)
            ]
            break

    return {
        "path": p,
        "title": title,
        "themes": themes,
        "cited_sources": cited_sources,
        "footer_connections": footer_connections,
        "structured": structured,
        "raw_text": text,
    }


# ── Wikilink resolution ─────────────────────────────────────────────────────

_RESOLVER_CACHE: dict[str, Path] | None = None


def _build_vault_index() -> dict[str, Path]:
    """
    Walk the vault once and build a {lowercase_basename_no_ext: Path} index.
    Used to resolve bare wikilinks like `[[80yrs old the user]]`.
    """
    idx: dict[str, Path] = {}
    for p in VAULT_ROOT.rglob("*.md"):
        key = p.stem.lower()
        # First-wins; Obsidian resolves by basename with ambiguity warnings,
        # so this is consistent with the vault author's mental model.
        if key not in idx:
            idx[key] = p
    return idx


def resolve_wikilink(wikilink: str, *, rebuild: bool = False) -> Optional[Path]:
    """
    Resolve a wikilink string to an absolute FILE Path in the vault, or None.

    Handles three shapes:
      1. `Books/Lila/Lila-60`         → VAULT_ROOT / "Books/Lila/Lila-60.md"
      2. `writing/Flow`               → VAULT_ROOT / "writing/Flow.md"
      3. `80yrs old the user`           → vault-wide basename lookup

    Returns None for directory-only references (aggregate book-level refs like
    `Books/The art of learning by Josh Waitzkin`, which points to a folder of
    per-page notes rather than a single file). Use classify_wikilink() when
    you need to distinguish "directory aggregate" from "genuinely broken."
    """
    global _RESOLVER_CACHE
    if rebuild or _RESOLVER_CACHE is None:
        _RESOLVER_CACHE = _build_vault_index()

    cleaned = wikilink.strip()
    if not cleaned:
        return None

    # Path-style: contains a slash → resolve relative to vault root
    if "/" in cleaned:
        direct = VAULT_ROOT / f"{cleaned}.md"
        if direct.exists() and direct.is_file():
            return direct
        direct_no_ext = VAULT_ROOT / cleaned
        if direct_no_ext.exists() and direct_no_ext.is_file():
            return direct_no_ext
        # Fall through to basename lookup in case the path is wrong but the
        # filename is unique in the vault.
        cleaned = cleaned.rsplit("/", 1)[-1]

    # Basename lookup
    return _RESOLVER_CACHE.get(cleaned.lower())


def classify_wikilink(wikilink: str) -> tuple[str, Optional[Path]]:
    """
    Classify a wikilink into one of four kinds:
      - ('file', Path)       — resolves to a specific markdown file
      - ('directory', Path)  — resolves to a folder (aggregate book-level ref)
      - ('missing', None)    — does not resolve to anything in the vault

    Directory refs are NOT invariant violations — they name the book/collection,
    not a specific page, and have no single canonical backlink target.
    """
    cleaned = wikilink.strip()
    if not cleaned:
        return ("missing", None)
    # Check directory reference first (path-style refs)
    if "/" in cleaned:
        as_dir = VAULT_ROOT / cleaned
        if as_dir.exists() and as_dir.is_dir():
            return ("directory", as_dir)
    # Otherwise try file resolution
    p = resolve_wikilink(cleaned)
    if p is not None:
        return ("file", p)
    return ("missing", None)


# ── Backlink layer ──────────────────────────────────────────────────────────

def _append_backlink_to_source(
    source_path: Path,
    synthesis_title: str,
    *,
    dry_run: bool = False,
) -> str:
    """
    Append ` · [[<synthesis_title>]]` to the last `*Connects to:*` line in the
    source. If no such line exists, create one with a horizontal-rule separator.

    Returns one of: "added", "already", "dry_run_would_add", "error:<reason>".
    Idempotent: if the link is already present anywhere in the file, skip.
    """
    try:
        text = source_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error:read:{e}"

    new_link = f"[[{synthesis_title}]]"
    if new_link in text:
        return "already"

    if dry_run:
        return "dry_run_would_add"

    lines = text.splitlines(keepends=False)
    updated = False

    # Walk from the END of the file backward to find the last `*Connects to:*`
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("*Connects to:*"):
            # Append with middle-dot separator (matches vault convention)
            if stripped.endswith("·") or stripped.endswith("・"):
                lines[i] = lines[i] + f" {new_link}"
            else:
                lines[i] = lines[i] + f" · {new_link}"
            updated = True
            break

    if not updated:
        # Append a fresh `*Connects to:*` footer section
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*Connects to:* {new_link}")
        updated = True

    new_text = "\n".join(lines)
    # Preserve trailing-newline shape of the original file
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    try:
        source_path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"error:write:{e}"
    return "added"


# ── Theme indices ───────────────────────────────────────────────────────────

def _update_theme_index(
    theme: str,
    synthesis_title: str,
    *,
    dry_run: bool = False,
) -> str:
    """
    Ensure /Alicia/Wisdom/Themes/<theme>.md exists and contains a wikilink to
    the synthesis. Idempotent.

    Returns "added" | "already" | "dry_run_would_add" | "error:<reason>".
    """
    if not theme:
        return "error:empty_theme"

    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    theme_path = THEMES_DIR / f"theme-{theme}.md"

    new_link = f"[[{synthesis_title}]]"

    if not theme_path.exists():
        if dry_run:
            return "dry_run_would_add"
        header = (
            f"---\ntags: [wisdom/theme-index, theme/{theme}]\n---\n\n"
            f"# Theme Index — {theme}\n\n"
            "Every synthesis tagged with this theme, newest first.\n\n"
            f"- {new_link}\n"
        )
        try:
            theme_path.write_text(header, encoding="utf-8")
        except Exception as e:
            return f"error:write:{e}"
        return "added"

    try:
        text = theme_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error:read:{e}"

    if new_link in text:
        return "already"

    if dry_run:
        return "dry_run_would_add"

    # Insert just below the "newest first" explanatory line, or at EOF
    lines = text.splitlines()
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith("- [["):
            insert_at = i
            break
    lines.insert(insert_at, f"- {new_link}")
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        theme_path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"error:write:{e}"
    return "added"


# ── Bridge logging ──────────────────────────────────────────────────────────

def _append_synthesis_log_row(
    synthesis_title: str,
    source_count: int,
    theme_count: int,
    *,
    dry_run: bool = False,
) -> str:
    """
    Append one row to /Alicia/Bridge/synthesis_results.tsv with today's date.
    Format matches the pirsig-blitz convention:
        <iso_timestamp>\t<title>\t<source_count>\t<theme_count>\t<status>
    """
    if dry_run:
        return "dry_run"
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Strip tabs/newlines from title to keep TSV well-formed
    safe_title = synthesis_title.replace("\t", " ").replace("\n", " ")
    row = f"{stamp}\t{safe_title}\t{source_count}\t{theme_count}\tfinalized\n"
    try:
        with locked_file(str(SYNTHESIS_LOG), "a") as f:
            f.write(row)
    except Exception as e:
        return f"error:{e}"
    return "appended"


def _week_digest_path(now: Optional[datetime] = None) -> Path:
    """
    Return the path for this week's Bridge digest file.
    ISO year-week ensures Sunday-evening reflections still live in the 'current'
    week on Monday morning.
    """
    now = now or datetime.now()
    year, week, _ = now.isocalendar()
    return BRIDGE_DIR / f"weekly-digest-{year}-W{week:02d}.md"


def _append_bridge_digest(
    synthesis_title: str,
    themes: list[str],
    source_count: int,
    *,
    dry_run: bool = False,
) -> str:
    """
    Append a one-paragraph note to this week's digest under
    'New syntheses this week.' Creates the file if it doesn't exist.
    """
    if dry_run:
        return "dry_run"
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    path = _week_digest_path()
    stamp = datetime.now().strftime("%a %Y-%m-%d %H:%M")
    theme_str = ", ".join(f"#theme/{t}" for t in themes) if themes else "(untagged)"
    paragraph = (
        f"- **{stamp}** · [[{synthesis_title}]] "
        f"— {source_count} sources · {theme_str}\n"
    )

    if not path.exists():
        header = (
            f"---\ntags: [bridge/weekly-digest]\n---\n\n"
            f"# Weekly Digest — {datetime.now().strftime('%Y · W%V')}\n\n"
            "## New syntheses this week\n\n"
        )
        try:
            path.write_text(header + paragraph, encoding="utf-8")
        except Exception as e:
            return f"error:write:{e}"
        return "created"

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error:read:{e}"

    # Insert after the '## New syntheses this week' heading, or append
    marker = "## New syntheses this week"
    if marker in text:
        # Append to the end of that section (stop at next '## ' heading)
        parts = text.split(marker, 1)
        tail = parts[1]
        next_section = re.search(r"\n##\s", tail)
        if next_section:
            before = tail[: next_section.start()].rstrip() + "\n"
            after = tail[next_section.start():]
            new_text = parts[0] + marker + before + paragraph + after
        else:
            new_text = text.rstrip() + "\n" + paragraph
    else:
        new_text = text.rstrip() + "\n\n" + marker + "\n\n" + paragraph

    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"error:write:{e}"
    return "appended"


# ── Surfacing queue ─────────────────────────────────────────────────────────

def _read_surfacing_queue() -> list[dict]:
    if not SURFACING_QUEUE_FILE.exists():
        return []
    try:
        return json.loads(SURFACING_QUEUE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Failed to read surfacing queue: {e}")
        return []


def _write_surfacing_queue(entries: list[dict]) -> None:
    try:
        atomic_write_json(str(SURFACING_QUEUE_FILE), entries)
    except IOError as e:
        log.error(f"Failed to write surfacing queue: {e}")


def queue_surfacings(
    synthesis_title: str,
    synthesis_path: str | Path,
    *,
    score: Optional[int] = None,
    kind: str = "synthesis",
    archetype_hint: Optional[str] = None,
) -> str:
    """
    Enqueue a multi-stage surfacing schedule for this source. Each entry
    carries its own source tag (`<kind>_finalize:<title>:<stage>`) so the
    Circulation Composer (Layer 2) can differentiate stage voice.

    Args:
        synthesis_title: display title; for Lived notes this is the Lived
            note's title (the practice's descent statement).
        synthesis_path: absolute path to the source file.
        score: optional numeric score propagated to the Composer.
        kind: "synthesis" (default) | "lived". Opaque to the queue; consumed
            by the Composer to shape voice and archetype assignment.
        archetype_hint: when known at queue time (e.g. Lived notes inherit
            the practice's archetype), pass it through so the Composer can
            respect it instead of falling back to the stage-default voice.

    Returns the queue entry ID.
    """
    queue = _read_surfacing_queue()
    now_utc = datetime.now(timezone.utc)
    entry_id = str(uuid.uuid4())

    stages = []
    for s in SURFACING_STAGES:
        deliver_after = now_utc + timedelta(hours=s["delay_hours"])
        stages.append({
            "name": s["name"],
            "voice_hint": s["voice_hint"],
            "deliver_after": deliver_after.isoformat(),
            "delivered": False,
        })

    entry = {
        "id": entry_id,
        "synthesis_title": synthesis_title,
        "synthesis_path": str(synthesis_path),
        "score": score,
        "kind": kind,
        "archetype_hint": archetype_hint,
        "created_at": now_utc.isoformat(),
        "source": f"{kind}_finalize:{synthesis_title}",
        "stages": stages,
    }
    queue.append(entry)
    _write_surfacing_queue(queue)
    log.info(
        f"Queued {len(stages)}-stage surfacing for {kind} "
        f"'{synthesis_title[:60]}' (id={entry_id})"
    )
    return entry_id


def queue_practice_progress_surfacing(
    practice_slug: str,
    practice_title: str,
    practice_path: str | Path,
    archetype_hint: str,
    *,
    log_excerpt: Optional[str] = None,
    expires_after_hours: int = 24,
) -> str:
    """
    Enqueue a single-stage, short-lived surfacing tagged
    `kind='practice_progress'`. Fired when the user logs a real attempt to a
    practice's log.md so the Circulation Composer can hear the practice's
    voice during the next ~24h instead of waiting until the practice closes.

    Unlike full synthesis surfacings (5 stages), practice-progress entries
    are present for ~24h then expire — they're a "Beatrice has something to
    say tonight" signal, not a multi-week resurfacing campaign. Once the
    practice closes, `finalize_lived_note` runs the full 5-stage queue for
    the resulting Lived note.
    """
    queue = _read_surfacing_queue()
    now_utc = datetime.now(timezone.utc)
    entry_id = str(uuid.uuid4())

    deliver_after = now_utc + timedelta(hours=4)  # fresh stage
    expires_at = now_utc + timedelta(hours=expires_after_hours)

    entry = {
        "id": entry_id,
        "synthesis_title": practice_title,
        "synthesis_path": str(practice_path),
        "score": None,
        "kind": "practice_progress",
        "archetype_hint": archetype_hint,
        "practice_slug": practice_slug,
        "log_excerpt": (log_excerpt or "")[:200] or None,
        "created_at": now_utc.isoformat(),
        "expires_at": expires_at.isoformat(),
        "source": f"practice_progress:{practice_slug}",
        "stages": [{
            "name": "fresh",
            "voice_hint": "still-warm",
            "deliver_after": deliver_after.isoformat(),
            "delivered": False,
        }],
    }
    queue.append(entry)
    _write_surfacing_queue(queue)
    log.info(
        f"Queued practice-progress surfacing for {practice_slug} "
        f"(archetype={archetype_hint}, id={entry_id})"
    )
    return entry_id


def get_ready_surfacings(now: Optional[datetime] = None) -> list[dict]:
    """
    Return a list of {entry_id, stage_name, synthesis_title, synthesis_path,
    voice_hint, source} for every stage that is due, undelivered, and (for
    entries with `expires_at`) not yet expired.

    Consumed by the Circulation Composer (item #17).
    """
    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    ready = []
    for entry in _read_surfacing_queue():
        # Honour optional expires_at — short-lived entries (e.g.
        # practice_progress) drop off the ready list once stale.
        expires_raw = entry.get("expires_at")
        if expires_raw:
            try:
                expires_at = datetime.fromisoformat(expires_raw)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now_utc >= expires_at:
                    continue
            except (KeyError, ValueError):
                pass
        for stage in entry.get("stages", []):
            if stage.get("delivered"):
                continue
            try:
                deliver_after = datetime.fromisoformat(stage["deliver_after"])
            except (KeyError, ValueError):
                continue
            if deliver_after.tzinfo is None:
                deliver_after = deliver_after.replace(tzinfo=timezone.utc)
            if now_utc >= deliver_after:
                ready.append({
                    "entry_id": entry["id"],
                    "stage_name": stage["name"],
                    "synthesis_title": entry["synthesis_title"],
                    "synthesis_path": entry["synthesis_path"],
                    "voice_hint": stage["voice_hint"],
                    "source": f"{entry['source']}:{stage['name']}",
                    # Layer-4 feedback. Values: "synthesis" | "lived" |
                    # "practice_progress" (default "synthesis" for backward
                    # compat with pre-existing queue entries).
                    "kind": entry.get("kind", "synthesis"),
                    "archetype_hint": entry.get("archetype_hint"),
                })
    return ready


def mark_surfacing_delivered(entry_id: str, stage_name: str) -> None:
    """Flip one stage on one queue entry to delivered=True."""
    queue = _read_surfacing_queue()
    for entry in queue:
        if entry.get("id") != entry_id:
            continue
        for stage in entry.get("stages", []):
            if stage.get("name") == stage_name:
                stage["delivered"] = True
                stage["delivered_at"] = datetime.now(timezone.utc).isoformat()
                break
        break
    _write_surfacing_queue(queue)


# ── Main entry ──────────────────────────────────────────────────────────────

def finalize(
    path: str | Path,
    *,
    score: Optional[int] = None,
    dry_run: bool = False,
    skip_surfacings: bool = False,
) -> dict:
    """
    Finalize a synthesis note. Idempotent — safe to call repeatedly.

    Args:
        path: Path to the synthesis note under /Alicia/Wisdom/Synthesis/.
        score: Optional quality score (1-5) if caller knows it.
        dry_run: If True, no writes happen — returns what would change.
        skip_surfacings: If True, skip queueing surfacings. Used by the backlink
            audit (item #15) when running across the whole corpus — we don't
            want to queue 272 surfacings at once.

    Returns a result dict:
        {
          "status": "finalized" | "skipped_unstructured" | "error",
          "title": str,
          "cited_sources": list[str],
          "themes": list[str],
          "backlinks": {"added": int, "already": int, "missing": int, "errors": int,
                        "missing_links": list[str]},
          "themes_updated": {"added": int, "already": int, "errors": int},
          "bridge_log": "appended" | "dry_run" | "error:...",
          "digest": "created" | "appended" | "dry_run" | "error:...",
          "surfacing_id": str | None,
          "error": str | None,
        }
    """
    try:
        info = parse_synthesis(path)
    except Exception as e:
        return {"status": "error", "error": f"parse_failed:{e}"}

    if not info["structured"]:
        log.info(f"Skipping unstructured synthesis: {info['path']}")
        return {
            "status": "skipped_unstructured",
            "title": info["title"],
            "cited_sources": [],
            "themes": info["themes"],
            "backlinks": {"added": 0, "already": 0, "missing": 0, "errors": 0, "missing_links": []},
            "themes_updated": {"added": 0, "already": 0, "errors": 0},
            "bridge_log": "skipped",
            "digest": "skipped",
            "surfacing_id": None,
            "error": None,
        }

    title = info["title"]
    cited = info["cited_sources"]
    themes = info["themes"]

    # 1. Backlinks
    bl = {
        "added": 0, "already": 0, "missing": 0, "aggregate": 0, "errors": 0,
        "missing_links": [], "aggregate_links": [],
    }
    for link in cited:
        kind, resolved = classify_wikilink(link)
        if kind == "directory":
            bl["aggregate"] += 1
            bl["aggregate_links"].append(link)
            continue
        if kind == "missing" or resolved is None:
            bl["missing"] += 1
            bl["missing_links"].append(link)
            continue
        result = _append_backlink_to_source(resolved, title, dry_run=dry_run)
        if result == "added" or result == "dry_run_would_add":
            bl["added"] += 1
        elif result == "already":
            bl["already"] += 1
        else:
            bl["errors"] += 1

    # 2. Theme indices
    th = {"added": 0, "already": 0, "errors": 0}
    for theme in themes:
        r = _update_theme_index(theme, title, dry_run=dry_run)
        if r in ("added", "dry_run_would_add"):
            th["added"] += 1
        elif r == "already":
            th["already"] += 1
        else:
            th["errors"] += 1

    # 3. Bridge log
    bridge_log_status = _append_synthesis_log_row(
        title, len(cited), len(themes), dry_run=dry_run
    )

    # 4. Weekly digest
    digest_status = _append_bridge_digest(
        title, themes, len(cited), dry_run=dry_run
    )

    # 5. Surfacings (not in dry_run, and opt-outable for bulk audit)
    surfacing_id: Optional[str] = None
    if not dry_run and not skip_surfacings:
        try:
            surfacing_id = queue_surfacings(title, info["path"], score=score)
        except Exception as e:
            log.warning(f"queue_surfacings failed for {title}: {e}")

    return {
        "status": "finalized",
        "title": title,
        "cited_sources": cited,
        "themes": themes,
        "backlinks": bl,
        "themes_updated": th,
        "bridge_log": bridge_log_status,
        "digest": digest_status,
        "surfacing_id": surfacing_id,
        "error": None,
    }


def finalize_all(
    *,
    dry_run: bool = False,
    skip_surfacings: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Run finalize() over every structured synthesis in /Alicia/Wisdom/Synthesis/.

    Used by the Backlink Audit (item #15). Skip-surfacings defaults to True
    here — we don't want to queue 300 surfacings at once on a bulk pass.

    Returns a summary dict with per-status counts and a list of any syntheses
    that had errors or missing wikilinks.
    """
    SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)
    counts = {
        "finalized": 0,
        "skipped_unstructured": 0,
        "error": 0,
        "backlinks_added": 0,
        "backlinks_already": 0,
        "backlinks_missing": 0,
        "backlinks_aggregate": 0,
        "themes_added": 0,
    }
    missing_per_synthesis: list[tuple[str, list[str]]] = []
    errors: list[tuple[str, str]] = []

    files = sorted(SYNTHESIS_DIR.glob("*.md"))
    for i, p in enumerate(files, 1):
        if verbose and i % 20 == 0:
            log.info(f"finalize_all: {i}/{len(files)}")
        r = finalize(p, dry_run=dry_run, skip_surfacings=skip_surfacings)
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] == "finalized":
            counts["backlinks_added"] += r["backlinks"]["added"]
            counts["backlinks_already"] += r["backlinks"]["already"]
            counts["backlinks_missing"] += r["backlinks"]["missing"]
            counts["backlinks_aggregate"] += r["backlinks"].get("aggregate", 0)
            counts["themes_added"] += r["themes_updated"]["added"]
            if r["backlinks"]["missing_links"]:
                missing_per_synthesis.append(
                    (r["title"], r["backlinks"]["missing_links"])
                )
        elif r["status"] == "error":
            errors.append((str(p), r.get("error", "unknown")))

    return {
        "counts": counts,
        "missing_per_synthesis": missing_per_synthesis,
        "errors": errors,
        "total_files": len(files),
    }


# ── Invariant check ─────────────────────────────────────────────────────────

def check_invariant() -> list[dict]:
    """
    Walk every structured synthesis and verify bidirectional edges.

    For each synthesis S and each wikilink W in S's `## The Claim Across Sources`:
      - Resolve W to a source file.
      - Assert S's title appears as a wikilink anywhere in that source file.
      - If not: record a violation.

    Wikilinks that do not resolve to a file are recorded as `unresolvable`.

    Returns a list of violation dicts. Empty list = invariant holds.
    Used by tests/test_synthesis_finalizer_invariant.py.
    """
    violations: list[dict] = []
    SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)

    for syn_path in sorted(SYNTHESIS_DIR.glob("*.md")):
        try:
            info = parse_synthesis(syn_path)
        except Exception as e:
            violations.append({
                "kind": "parse_error",
                "synthesis": syn_path.name,
                "detail": str(e),
            })
            continue

        if not info["structured"]:
            continue

        expected = f"[[{info['title']}]]"

        for link in info["cited_sources"]:
            kind, resolved = classify_wikilink(link)
            if kind == "directory":
                # Aggregate book-level refs — no single backlink target.
                # Not a violation; these are informational only.
                continue
            if kind == "missing" or resolved is None:
                violations.append({
                    "kind": "unresolvable",
                    "synthesis": info["title"],
                    "cited_link": link,
                })
                continue
            try:
                src_text = resolved.read_text(encoding="utf-8")
            except Exception as e:
                violations.append({
                    "kind": "source_read_error",
                    "synthesis": info["title"],
                    "source": str(resolved),
                    "detail": str(e),
                })
                continue
            if expected not in src_text:
                violations.append({
                    "kind": "one_way_edge",
                    "synthesis": info["title"],
                    "source": str(resolved.relative_to(VAULT_ROOT)),
                    "cited_link": link,
                })

    return violations


# ── Lived notes (Layer 4 feedback loop) ─────────────────────────────────────
#
# Lived notes are written by skills/practice_runner.py on practice close. They
# are first-class source material — a Lived note is the compressed statement
# of what a 30-day practice *taught*, phrased as a sentence the vault can cite.
# Future syntheses draw on them the same way they draw on books, quotes, and
# the user's own writing.
#
# `finalize_lived_note()` gives a fresh Lived note the same circulation parity
# as a synthesis: Bridge TSV row (kind=lived), weekly-digest paragraph,
# multi-stage surfacing schedule. That means when the Circulation Composer
# (Layer 2) runs, Lived notes compete for each slot alongside syntheses.

_LIVED_FRONT_META_RE = re.compile(
    r"\*Lived note[^*\n]*?emitted\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE
)
_LIVED_DESCENT_RE = re.compile(r"\*\*Descent\.\*\*\s+\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]")
_LIVED_ARCHETYPE_RE = re.compile(r"\*\*Archetype home\.\*\*\s+([A-Za-z]+)")


def parse_lived_note(path: str | Path) -> dict:
    """
    Parse a Lived note written by `practice_runner.close_practice`.

    Returns:
        {
          "path": Path,
          "title": str (from first '# ' heading),
          "slug": str (filename without .md),
          "emitted_at": str (YYYY-MM-DD) or "",
          "descent_synthesis_title": str or "",
          "archetype": str or "",
          "raw_text": str,
        }
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    title = p.stem
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    emitted_at = ""
    em = _LIVED_FRONT_META_RE.search(text)
    if em:
        emitted_at = em.group(1)

    descent = ""
    dm = _LIVED_DESCENT_RE.search(text)
    if dm:
        descent = dm.group(1).strip()

    archetype = ""
    am = _LIVED_ARCHETYPE_RE.search(text)
    if am:
        archetype = am.group(1).strip()

    return {
        "path": p,
        "title": title,
        "slug": p.stem,
        "emitted_at": emitted_at,
        "descent_synthesis_title": descent,
        "archetype": archetype,
        "raw_text": text,
    }


def list_lived_notes() -> list[dict]:
    """
    Return metadata for every Lived note in /Alicia/Wisdom/Lived/.
    Same shape as parse_lived_note() but omits raw_text.
    """
    out: list[dict] = []
    if not LIVED_DIR.exists():
        return out
    for p in sorted(LIVED_DIR.glob("*.md")):
        try:
            info = parse_lived_note(p)
        except Exception as e:
            log.warning(f"Could not parse Lived note {p}: {e}")
            continue
        info.pop("raw_text", None)
        out.append(info)
    return out


def find_syntheses_citing(target_title: str) -> list[Path]:
    """
    Return paths of structured syntheses whose `## The Claim Across Sources`
    section cites `target_title` (basename or path-style wikilink). Matching
    is on basename — the same convention Obsidian uses.
    """
    target = target_title.strip()
    # Comparison is case-insensitive on the final basename segment
    target_key = target.rsplit("/", 1)[-1].lower()
    hits: list[Path] = []
    if not SYNTHESIS_DIR.exists():
        return hits
    for syn_path in sorted(SYNTHESIS_DIR.glob("*.md")):
        try:
            info = parse_synthesis(syn_path)
        except Exception:
            continue
        if not info["structured"]:
            continue
        for link in info["cited_sources"]:
            link_key = link.strip().rsplit("/", 1)[-1].lower()
            if link_key == target_key:
                hits.append(syn_path)
                break
    return hits


def _append_lived_log_row(
    lived_title: str, descent_title: str, *, dry_run: bool = False
) -> str:
    """
    Append one row to /Alicia/Bridge/synthesis_results.tsv marking a Lived note
    as a new first-class source:
        <iso_timestamp>\tlived:<title>\t0\t0\tlived_finalized\t<descent>
    """
    if dry_run:
        return "dry_run"
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    safe_title = lived_title.replace("\t", " ").replace("\n", " ")
    safe_descent = (descent_title or "").replace("\t", " ").replace("\n", " ")
    row = f"{stamp}\tlived:{safe_title}\t0\t0\tlived_finalized\t{safe_descent}\n"
    try:
        with locked_file(str(SYNTHESIS_LOG), "a") as f:
            f.write(row)
    except Exception as e:
        return f"error:{e}"
    return "appended"


def _append_lived_to_digest(
    lived_title: str, descent_title: str, archetype: str, *, dry_run: bool = False
) -> str:
    """
    Append a one-line note under the weekly digest's 'New Lived notes this week'
    section. Creates the section if the digest exists but lacks it.
    """
    if dry_run:
        return "dry_run"
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    path = _week_digest_path()
    stamp = datetime.now().strftime("%a %Y-%m-%d %H:%M")
    descent_frag = f" (descent: [[{descent_title}]])" if descent_title else ""
    arch_frag = f" · {archetype}" if archetype else ""
    paragraph = f"- **{stamp}** · [[{lived_title}]]{arch_frag}{descent_frag}\n"

    marker = "## New Lived notes this week"

    if not path.exists():
        header = (
            f"---\ntags: [bridge/weekly-digest]\n---\n\n"
            f"# Weekly Digest — {datetime.now().strftime('%Y · W%V')}\n\n"
            f"{marker}\n\n"
        )
        try:
            path.write_text(header + paragraph, encoding="utf-8")
        except Exception as e:
            return f"error:write:{e}"
        return "created"

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error:read:{e}"

    if marker in text:
        parts = text.split(marker, 1)
        tail = parts[1]
        next_section = re.search(r"\n##\s", tail)
        if next_section:
            before = tail[: next_section.start()].rstrip() + "\n"
            after = tail[next_section.start():]
            new_text = parts[0] + marker + before + paragraph + after
        else:
            new_text = text.rstrip() + "\n" + paragraph
    else:
        new_text = text.rstrip() + "\n\n" + marker + "\n\n" + paragraph

    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"error:write:{e}"
    return "appended"


def finalize_lived_note(
    path: str | Path,
    *,
    dry_run: bool = False,
    skip_surfacings: bool = False,
) -> dict:
    """
    Give a Lived note the same circulation parity as a finalized synthesis.
    Idempotent-safe (re-calling only queues fresh surfacings; TSV row and
    digest paragraph are append-only on purpose — they're a ledger).

    Args:
        path: Path to the Lived note (e.g. /Alicia/Wisdom/Lived/<slug>.md).
        dry_run: If True, no writes happen.
        skip_surfacings: If True, don't queue the 5-stage surfacing schedule.

    Returns:
        {
          "status": "finalized" | "error",
          "title": str,
          "descent": str,
          "archetype": str,
          "bridge_log": str,
          "digest": str,
          "surfacing_id": str | None,
          "citing_syntheses": int,  # # of existing syntheses citing this Lived note
          "error": str | None,
        }
    """
    try:
        info = parse_lived_note(path)
    except Exception as e:
        return {"status": "error", "error": f"parse_failed:{e}"}

    title = info["title"]
    descent = info["descent_synthesis_title"]
    archetype = info["archetype"]

    # 1. Bridge TSV
    bridge_log_status = _append_lived_log_row(title, descent, dry_run=dry_run)

    # 2. Weekly digest — under "New Lived notes this week"
    digest_status = _append_lived_to_digest(
        title, descent, archetype, dry_run=dry_run
    )

    # 3. Multi-stage surfacing queue (kind hint = lived so Composer can
    #    differentiate voice and observability).
    surfacing_id: Optional[str] = None
    if not dry_run and not skip_surfacings:
        try:
            surfacing_id = queue_surfacings(
                title, info["path"],
                score=None,
                kind="lived",
                archetype_hint=archetype or None,
            )
        except Exception as e:
            log.warning(f"queue_surfacings (lived) failed for {title}: {e}")

    # 4. How many syntheses already cite this Lived note (informational)
    citing = find_syntheses_citing(title)

    return {
        "status": "finalized",
        "title": title,
        "descent": descent,
        "archetype": archetype,
        "bridge_log": bridge_log_status,
        "digest": digest_status,
        "surfacing_id": surfacing_id,
        "citing_syntheses": len(citing),
        "error": None,
    }


def finalize_all_lived_notes(
    *, dry_run: bool = False, skip_surfacings: bool = True
) -> dict:
    """
    Run finalize_lived_note across every Lived note. Used on first-time rollout
    so pre-existing Lived notes (if any) enter the graph as first-class sources.
    skip_surfacings=True by default — bulk rolls shouldn't spam the queue.
    """
    LIVED_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for p in sorted(LIVED_DIR.glob("*.md")):
        results.append(finalize_lived_note(
            p, dry_run=dry_run, skip_surfacings=skip_surfacings,
        ))
    counts = {"finalized": 0, "error": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"counts": counts, "total": len(results), "results": results}


def check_lived_invariants() -> list[dict]:
    """
    Layer 4 feedback-loop invariants on Lived notes themselves:
      - lived_missing_descent:  Lived note has no `**Descent.**` wikilink
      - lived_orphan_practice:  Lived note exists but no practice folder exists
      - lived_unused:           Lived note >LIVED_UNUSED_DAYS old and NO
                                synthesis cites it (signals neglected source)

    Syntheses citing missing-file Lived notes are caught by the main
    `check_invariant()` under kind=unresolvable — no duplication here.
    """
    violations: list[dict] = []
    if not LIVED_DIR.exists():
        return violations

    now_utc = datetime.now(timezone.utc)

    for p in sorted(LIVED_DIR.glob("*.md")):
        try:
            info = parse_lived_note(p)
        except Exception as e:
            violations.append({
                "kind": "parse_error",
                "lived_note": p.name,
                "detail": str(e),
            })
            continue

        if not info["descent_synthesis_title"]:
            violations.append({
                "kind": "lived_missing_descent",
                "lived_note": info["title"],
                "path": str(p.relative_to(VAULT_ROOT)),
            })

        # Does a matching practice folder exist? An orphan Lived note
        # (no practice.md) is a violation regardless of whether PRACTICES_DIR
        # itself has been created — the Lived note's existence implies a
        # practice was run, and the practice.md is its parent record.
        practice_md = PRACTICES_DIR / info["slug"] / "practice.md"
        if not practice_md.exists():
            violations.append({
                "kind": "lived_orphan_practice",
                "lived_note": info["title"],
                "expected_practice_md": str(practice_md),
            })

        # Aged-out + uncited?
        age_days: Optional[int] = None
        if info["emitted_at"]:
            try:
                emitted = datetime.strptime(info["emitted_at"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                age_days = (now_utc - emitted).days
            except Exception:
                age_days = None
        if age_days is not None and age_days >= LIVED_UNUSED_DAYS:
            if not find_syntheses_citing(info["title"]):
                violations.append({
                    "kind": "lived_unused",
                    "lived_note": info["title"],
                    "age_days": age_days,
                    "threshold_days": LIVED_UNUSED_DAYS,
                })

    return violations


# ── CLI / smoke ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Synthesis Finalizer")
    parser.add_argument("--check", action="store_true", help="Run invariant check and print violations")
    parser.add_argument("--audit", action="store_true", help="Run finalize_all (dry-run if --dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything")
    parser.add_argument("--finalize", metavar="PATH", help="Finalize a single synthesis file")
    parser.add_argument(
        "--finalize-lived", metavar="PATH",
        help="Finalize a single Lived note (Layer 4 feedback)",
    )
    parser.add_argument(
        "--audit-lived", action="store_true",
        help="Run finalize_lived_note across every Lived note (dry-run if --dry-run)",
    )
    parser.add_argument(
        "--check-lived", action="store_true",
        help="Run Lived-note invariants and print violations",
    )
    parser.add_argument(
        "--list-lived", action="store_true",
        help="List every Lived note with metadata",
    )
    args = parser.parse_args()

    if args.check:
        vs = check_invariant()
        print(f"Violations: {len(vs)}")
        for v in vs[:30]:
            print(f"  {v['kind']}: {v.get('synthesis', '')} → {v.get('source', v.get('cited_link', ''))}")
        if len(vs) > 30:
            print(f"  ... and {len(vs) - 30} more")
    elif args.audit:
        summary = finalize_all(dry_run=args.dry_run, skip_surfacings=True)
        print(json.dumps(summary["counts"], indent=2))
        print(f"Missing: {len(summary['missing_per_synthesis'])}  Errors: {len(summary['errors'])}")
    elif args.finalize:
        r = finalize(args.finalize, dry_run=args.dry_run)
        print(json.dumps({k: v for k, v in r.items() if k != "raw_text"}, indent=2, default=str))
    elif args.finalize_lived:
        r = finalize_lived_note(args.finalize_lived, dry_run=args.dry_run)
        print(json.dumps(r, indent=2, default=str))
    elif args.audit_lived:
        summary = finalize_all_lived_notes(
            dry_run=args.dry_run, skip_surfacings=True,
        )
        print(json.dumps(summary["counts"], indent=2))
        print(f"Total Lived notes processed: {summary['total']}")
    elif args.check_lived:
        vs = check_lived_invariants()
        print(f"Lived-note violations: {len(vs)}")
        for v in vs[:30]:
            print(f"  {v['kind']}: {v.get('lived_note', '')}")
    elif args.list_lived:
        rows = list_lived_notes()
        print(f"Lived notes: {len(rows)}")
        for r in rows:
            citing = len(find_syntheses_citing(r["title"]))
            print(
                f"  {r['slug']:30s}  emitted={r['emitted_at'] or '?':10s}  "
                f"archetype={r['archetype'] or '-':>9s}  cited_by={citing}"
            )
    else:
        parser.print_help()
