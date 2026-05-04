#!/usr/bin/env python3
"""
Layer 4 — Practice Runner.

Turns selected syntheses into 30-day lived experiments with structured
check-ins, and feeds the results back into the vault as citable source
material for future syntheses. This is the layer where the user's *life*
changes because of the knowledge graph.

Folder layout it owns:

    /Alicia/Practices/
      README.md                       # index (generated)
      <slug>/
        practice.md                   # descent synthesis + 30-day instrument
        log.md                        # daily/weekly entries (append-only)
        closeout.md                   # written on day 31

    /Alicia/Wisdom/Lived/
      <slug>.md                       # the lived-note emitted on close

Check-in cadence: days 3, 7, 14, 21, 30 after start. On day 31 the runner
writes a closeout + appends a Lived note. CI fails if a practice is
closed without its Lived note.

Cap: MAX_ACTIVE_PRACTICES = 3 (compounding depends on depth, not breadth).

Feature-flagged behind USE_PRACTICE_RUNNER (default False). When off, the
scheduled daily pass runs read-only.

Public API:
    USE_PRACTICE_RUNNER, PRACTICES_DIR, LIVED_DIR,
    MAX_ACTIVE_PRACTICES, CHECK_IN_DAYS
    Practice (dataclass)
    load_practices() -> list[Practice]
    active_practices() -> list[Practice]
    promote_synthesis_to_practice(...) -> Practice
    due_check_ins(now=None) -> list[tuple[Practice, int]]
    compose_check_in(practice, day_number) -> str
    record_check_in(slug, day_number, reply=None) -> None
    record_log_entry(slug, text) -> Path
    close_practice(slug, *, lived_note_text=None, now=None) -> Path
    check_invariants() -> list[dict]
    run_daily_pass(now=None) -> dict
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from myalicia.skills.safe_io import atomic_write_text, atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.practice")

# ── Config ──────────────────────────────────────────────────────────────────

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(str(MEMORY_DIR))
PRACTICES_DIR = VAULT_ROOT / "Alicia" / "Practices"
LIVED_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Lived"
CHECK_IN_LOG_FILE = MEMORY_DIR / "practice_check_ins.json"

# Feature flag. Default False — scheduler still runs the pass but in read-only
# mode until explicitly flipped in .env.
USE_PRACTICE_RUNNER = os.environ.get(
    "USE_PRACTICE_RUNNER", "false"
).lower() in ("1", "true", "yes", "on")

# Hard cap from the proposal — the compounding depends on depth, not breadth.
MAX_ACTIVE_PRACTICES = 3

# Cadence — days-since-start on which Alicia asks for a check-in.
CHECK_IN_DAYS: tuple[int, ...] = (3, 7, 14, 21, 30)

# Active statuses that count toward the cap.
ACTIVE_STATUS = "active"
CLOSED_STATUS = "closed"

# ── Types ───────────────────────────────────────────────────────────────────


@dataclass
class Practice:
    """An active or closed practice."""
    slug: str                         # stable filename-safe id
    title: str                        # human-readable title
    synthesis_title: str              # the synthesis it descends from
    synthesis_path: str               # path (relative to vault) or ""
    archetype: str                    # Daimon | Beatrice | Ariadne | Psyche | Musubi | Muse
    instrument: str                   # the concrete 30-day action
    started_at: str                   # ISO date (YYYY-MM-DD)
    status: str = ACTIVE_STATUS       # active | closed
    check_in_days: tuple[int, ...] = CHECK_IN_DAYS
    path: str = ""                    # absolute path to the practice folder


# ── Parsing + loading ───────────────────────────────────────────────────────


_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", title).strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s[:64] or "practice"


def _parse_practice_md(path: Path) -> Optional[Practice]:
    """Parse a practice.md's YAML front-matter block. Returns None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return None
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    try:
        return Practice(
            slug=fm.get("slug") or path.parent.name,
            title=fm.get("title") or "",
            synthesis_title=fm.get("synthesis_title") or "",
            synthesis_path=fm.get("synthesis_path") or "",
            archetype=fm.get("archetype") or "Beatrice",
            instrument=fm.get("instrument") or "",
            started_at=fm.get("started_at") or "",
            status=(fm.get("status") or ACTIVE_STATUS).lower(),
            check_in_days=CHECK_IN_DAYS,
            path=str(path.parent),
        )
    except Exception:
        return None


def load_practices() -> list[Practice]:
    """Scan PRACTICES_DIR/*/practice.md. Returns all practices (any status)."""
    out: list[Practice] = []
    if not PRACTICES_DIR.exists():
        return out
    for sub in sorted(PRACTICES_DIR.iterdir()):
        if not sub.is_dir():
            continue
        pmd = sub / "practice.md"
        if not pmd.exists():
            continue
        p = _parse_practice_md(pmd)
        if p:
            out.append(p)
    return out


def active_practices() -> list[Practice]:
    return [p for p in load_practices() if p.status == ACTIVE_STATUS]


# ── Promotion (synthesis → practice) ────────────────────────────────────────


def _render_practice_md(practice: Practice) -> str:
    front_matter = (
        "---\n"
        f"slug: {practice.slug}\n"
        f"title: {practice.title}\n"
        f"synthesis_title: {practice.synthesis_title}\n"
        f"synthesis_path: {practice.synthesis_path}\n"
        f"archetype: {practice.archetype}\n"
        f"instrument: {practice.instrument}\n"
        f"started_at: {practice.started_at}\n"
        f"status: {practice.status}\n"
        "---\n\n"
    )
    synthesis_link = ""
    if practice.synthesis_title:
        synthesis_link = f"[[{practice.synthesis_title}]]"
    body = (
        f"# {practice.title}\n\n"
        f"**Descent.** {synthesis_link or practice.synthesis_title}\n\n"
        f"**Archetype home.** {practice.archetype}\n\n"
        f"**The 30-day instrument.** {practice.instrument}\n\n"
        f"**Started.** {practice.started_at}  \n"
        f"**Check-ins.** Days 3, 7, 14, 21, 30 — Alicia will ask for a report; "
        f"{USER_NAME}'s job is to log the attempt and the exposure felt.\n\n"
        f"**Close.** On day 31, Alicia composes `closeout.md` and appends a lived "
        f"note to `Alicia/Wisdom/Lived/{practice.slug}.md`. That lived note is "
        "first-class source material for future syntheses — the loop closes.\n\n"
        "---\n\n"
        "## How to log\n\n"
        "- Add one line per attempt to `log.md` in this folder. Format:\n"
        "  `YYYY-MM-DD — <what I attempted> — <the exposure felt>`.\n"
        "- Alicia's check-ins will include the last few log lines as context.\n\n"
        "## Principle\n\n"
        "A practice is not a project. A project has an endpoint. A practice has a "
        "cadence, a reporter, and a witness. Alicia is the witness. The log is the "
        "record. The closeout is what the practice *taught* — phrased as a sentence "
        "the vault can cite.\n"
    )
    return front_matter + body


def promote_synthesis_to_practice(
    *,
    title: str,
    synthesis_title: str,
    synthesis_path: str,
    instrument: str,
    archetype: str = "Beatrice",
    slug: Optional[str] = None,
    started_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Practice:
    """
    Create a new active practice. Enforces MAX_ACTIVE_PRACTICES. The practice
    folder is created under PRACTICES_DIR/<slug>/ with practice.md and an
    empty log.md.
    """
    if len(active_practices()) >= MAX_ACTIVE_PRACTICES:
        raise RuntimeError(
            f"Cap reached: at most {MAX_ACTIVE_PRACTICES} active practices. "
            "Close one before promoting another."
        )
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    started = started_at or now_utc.strftime("%Y-%m-%d")

    the_slug = slug or _slugify(title)
    folder = PRACTICES_DIR / the_slug
    if folder.exists():
        raise RuntimeError(f"Practice slug already exists: {the_slug}")
    folder.mkdir(parents=True, exist_ok=True)

    practice = Practice(
        slug=the_slug,
        title=title,
        synthesis_title=synthesis_title,
        synthesis_path=synthesis_path,
        archetype=archetype,
        instrument=instrument,
        started_at=started,
        status=ACTIVE_STATUS,
        path=str(folder),
    )
    atomic_write_text(str(folder / "practice.md"), _render_practice_md(practice))
    if not (folder / "log.md").exists():
        atomic_write_text(
            str(folder / "log.md"),
            f"# Log — {practice.title}\n\n"
            f"_One line per attempt: `YYYY-MM-DD — attempt — exposure felt`._\n\n",
        )
    _write_readme()
    return practice


# ── Check-ins ───────────────────────────────────────────────────────────────


def _days_since(started_at: str, now: datetime) -> int:
    try:
        start = datetime.strptime(started_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return -1
    return (now - start).days


def _load_check_in_log() -> dict:
    try:
        if CHECK_IN_LOG_FILE.exists():
            return json.loads(CHECK_IN_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Could not read check-in log: {e}")
    return {}


def _save_check_in_log(data: dict) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(CHECK_IN_LOG_FILE), data)
    except Exception as e:
        log.warning(f"Could not write check-in log: {e}")


def due_check_ins(now: Optional[datetime] = None) -> list[tuple[Practice, int]]:
    """
    Returns (practice, day_number) for every active practice where
    day_number ∈ CHECK_IN_DAYS AND no check-in yet recorded for that day.

    When today's day_since_start lands exactly on a CHECK_IN_DAYS value, it
    fires. If a check-in was missed (e.g. Alicia was offline), the function
    also emits it the next day (single-day grace) so it isn't lost.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    ledger = _load_check_in_log()
    out: list[tuple[Practice, int]] = []
    for p in active_practices():
        days = _days_since(p.started_at, now_utc)
        if days < 0:
            continue
        done = set((ledger.get(p.slug) or {}).get("done", []))
        for d in CHECK_IN_DAYS:
            if d in done:
                continue
            # Fire on exact day or one-day grace window.
            if days == d or days == d + 1:
                out.append((p, d))
    return out


def compose_check_in(practice: Practice, day_number: int) -> str:
    """Render the text of the check-in prompt. Not sent — returned.

    Day-specific framing (Phase 11.3+):
      - Day 3:  baseline reading — what have the first attempts looked like?
      - Day 7:  pattern reading — what's repeating? what's hardest? what
                surprised you?
      - Day 14: midpoint reflection — is the practice changing how you
                relate to the parent synthesis?
      - Day 21: integration check — what's becoming automatic vs. effortful?
      - Day 30: closeout signal — what did this teach? phrase it as a
                sentence the vault can cite.

    The check-in prompt is the most important conversational surface the
    practice has — getting the question right is what lets the closing
    Lived note carry real signal.
    """
    tail = _tail_log(practice, lines=3)
    tail_block = f"\n\nLast few log lines:\n{tail}" if tail else ""

    header = (
        f"📓 Practice check-in — day {day_number} of *{practice.title}*\n\n"
        f"Archetype: {practice.archetype}\n"
        f"Instrument: {practice.instrument}\n\n"
    )

    if day_number == 3:
        body = (
            "How has it actually gone? One line per attempt if you can — "
            "the attempt and the exposure felt. No polish; this is the "
            "reporter talking to the witness."
        )
    elif day_number == 7:
        body = (
            "A week in. What's *repeating*? Which kind of attempt is "
            "easiest to reach for, and which one keeps slipping past? "
            "Anything you tried this week that surprised you — either "
            "because it landed harder than expected or because it didn't "
            "land at all? Pattern reading, not polish."
        )
    elif day_number == 14:
        body = (
            "Midpoint. Two weeks of attempts in the log. Is this practice "
            "changing how you relate to the parent synthesis "
            f"({practice.synthesis_title or '(no descent)'}) — or are you "
            "just executing the instrument? If something's shifted, name "
            "it in one sentence. If nothing's shifted, name what you'd "
            "have to do differently for it to."
        )
    elif day_number == 21:
        body = (
            "Three weeks. What's becoming *automatic* — the attempts that "
            "no longer cost you anything to make? And what's still "
            "*effortful* — the ones you're still resisting or fumbling? "
            "The split between the two is the signal of what this "
            "practice has actually been integrating."
        )
    elif day_number == 30:
        body = (
            "Thirty days. The practice closes tomorrow and what you write "
            "next becomes the Lived note that re-enters circulation as "
            "Tier-6 source material. *What did this practice teach?* "
            "Compress it. One sentence the vault can cite — phrased as "
            "what you now know that you didn't on day 1. The Lived note "
            "carries that sentence forward; future syntheses will stand "
            "on it."
        )
    else:
        # Defensive fallback for any non-canonical day number
        body = (
            "How has it actually gone? One line per attempt if you can — "
            "the attempt and the exposure felt. No polish; this is the "
            "reporter talking to the witness."
        )

    return header + body + tail_block


def record_check_in(
    slug: str, day_number: int, reply: Optional[str] = None,
    *, now: Optional[datetime] = None,
) -> None:
    """Mark a check-in as sent (and optionally store the user's reply)."""
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    ledger = _load_check_in_log()
    row = ledger.get(slug) or {"done": [], "history": []}
    if day_number not in row["done"]:
        row["done"].append(day_number)
    row["history"].append({
        "day": day_number,
        "at": now_utc.isoformat(),
        "reply": reply or "",
    })
    ledger[slug] = row
    _save_check_in_log(ledger)


def _tail_log(practice: Practice, lines: int = 3) -> str:
    p = Path(practice.path) / "log.md"
    if not p.exists():
        return ""
    try:
        text_lines = [
            ln for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        return "\n".join(f"  · {ln}" for ln in text_lines[-lines:])
    except Exception:
        return ""


def record_log_entry(slug: str, text: str, *, now: Optional[datetime] = None) -> Path:
    """
    Append a timestamped line to the practice's log.md AND queue a single
    short-lived surfacing tagged `kind='practice_progress'` so the Circulation
    Composer (Layer 2) can hear the practice's voice during the next ~24h.

    The surfacing failure is non-fatal — if the queue write errors, the log
    entry is still recorded. Practice progress is signal-driven, not strict.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    folder = PRACTICES_DIR / slug
    log_path = folder / "log.md"
    if not folder.exists():
        raise FileNotFoundError(f"Unknown practice: {slug}")
    prior = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    line = f"{now_utc.strftime('%Y-%m-%d')} — {text.strip()}"
    new_text = (prior.rstrip() + "\n" + line + "\n") if prior else (line + "\n")
    atomic_write_text(str(log_path), new_text)

    # Surface to the Composer — Beatrice (or whoever the practice's archetype
    # is) gets a fresh-stage voice slot for the next ~24h.
    try:
        practice = _parse_practice_md(folder / "practice.md")
        if practice and practice.archetype:
            from myalicia.skills.synthesis_finalizer import queue_practice_progress_surfacing
            queue_practice_progress_surfacing(
                practice_slug=slug,
                practice_title=practice.title,
                practice_path=str(folder / "practice.md"),
                archetype_hint=practice.archetype,
                log_excerpt=text.strip(),
            )
    except Exception as e:
        log.debug(f"could not queue practice-progress surfacing for {slug}: {e}")

    return log_path


# ── Closeout + Lived note ──────────────────────────────────────────────────


def _render_closeout(practice: Practice, *, now: datetime) -> str:
    return (
        f"# Closeout — {practice.title}\n\n"
        f"**Started.** {practice.started_at}  \n"
        f"**Closed.** {now.strftime('%Y-%m-%d')}\n\n"
        f"**Descended from.** [[{practice.synthesis_title}]]\n\n"
        f"**Instrument.** {practice.instrument}\n\n"
        "## What the practice taught\n\n"
        "_(One paragraph, phrased as a sentence the vault can cite. "
        f"Written by {USER_NAME} or co-drafted with Alicia on day 31.)_\n\n"
        "## Lived note\n\n"
        f"This closeout emits `Alicia/Wisdom/Lived/{practice.slug}.md` — "
        "first-class source material for future syntheses.\n"
    )


def _render_lived_note(practice: Practice, *, body: str, now: datetime) -> str:
    link = f"[[{practice.synthesis_title}]]" if practice.synthesis_title else "(no descent)"

    # Phase 11.12 — embed captures the user made during the practice as raw
    # material. The closeout author (or future the user) reads these as the
    # voice-side log of the practice; the log.md attempt-lines are the
    # action-side. Captures section appears between 'What the body learned'
    # and the Sources line.
    captures_block = ""
    try:
        from myalicia.skills.response_capture import get_captures_during_practice
        captures = get_captures_during_practice(
            practice.started_at, now=now,
        )
    except Exception as e:
        log.debug(f"_render_lived_note: captures lookup failed: {e}")
        captures = []
    if captures:
        lines = ["## Captures during this practice\n"]
        lines.append(
            "_Hector's spontaneous voice during the practice window — "
            "raw material the body learned alongside the log.md attempts._\n"
        )
        for c in captures:
            ts_short = (c.get("captured_at") or "").split("T")[0] or "?"
            kind = c.get("kind") or "capture"
            tag = "[R]" if kind == "response" else "[C]"
            excerpt = (c.get("body_excerpt") or "").strip()
            if len(excerpt) > 160:
                excerpt = excerpt[:159].rstrip() + "…"
            file_stem = c["path"].stem if c.get("path") else "?"
            lines.append(
                f'- {tag} _{ts_short}_ — "{excerpt}" '
                f'([[writing/{ "Captures" if kind == "capture" else "Responses" }/{file_stem}]])'
            )
        captures_block = "\n".join(lines) + "\n\n"

    return (
        f"# {practice.title}\n\n"
        f"*Lived note — emitted {now.strftime('%Y-%m-%d')} from 30-day practice.*\n\n"
        f"**Descent.** {link}\n"
        f"**Archetype home.** {practice.archetype}\n"
        f"**Duration.** {practice.started_at} → {now.strftime('%Y-%m-%d')}\n\n"
        "## What the body learned\n\n"
        f"{body.strip() or '_(awaiting {USER_NAME}&apos;s sentence-length statement)_'}\n\n"
        f"{captures_block}"
        "---\n"
        f"*Sources.* [[{practice.synthesis_title}]] · "
        f"[[Alicia/Practices/{practice.slug}/practice]] · "
        f"[[Alicia/Practices/{practice.slug}/log]]\n"
    )


def close_practice(
    slug: str,
    *,
    lived_note_text: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Path:
    """
    Close a practice. Writes closeout.md + Lived/<slug>.md and sets
    front-matter status=closed. The Lived note is the contract that makes
    Layer 4 worth having — CI fails if it's missing.

    Returns the path of the emitted Lived note.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    folder = PRACTICES_DIR / slug
    if not folder.exists():
        raise FileNotFoundError(f"Unknown practice: {slug}")
    pmd = folder / "practice.md"
    practice = _parse_practice_md(pmd)
    if practice is None:
        raise RuntimeError(f"Could not parse practice.md for {slug}")

    # closeout.md
    atomic_write_text(str(folder / "closeout.md"), _render_closeout(practice, now=now_utc))

    # Lived note — the contract.
    LIVED_DIR.mkdir(parents=True, exist_ok=True)
    lived_path = LIVED_DIR / f"{slug}.md"
    atomic_write_text(
        str(lived_path),
        _render_lived_note(practice, body=lived_note_text or "", now=now_utc),
    )

    # Flip status=closed on the practice.md front matter (preserve body).
    text = pmd.read_text(encoding="utf-8")
    text = re.sub(
        r"^status:\s*.+$", f"status: {CLOSED_STATUS}", text,
        count=1, flags=re.MULTILINE,
    )
    atomic_write_text(str(pmd), text)

    # Lived → Synthesis feedback loop (Layer 4 closes the circuit).
    # Feed the fresh Lived note to the Finalizer so it gets the same
    # circulation parity as a newly-finalized synthesis: Bridge TSV row,
    # weekly-digest paragraph, 5-stage surfacing schedule. Non-fatal on
    # any error — the contract (Lived note written, practice.md flipped)
    # has already held.
    try:
        from myalicia.skills.synthesis_finalizer import finalize_lived_note
        result = finalize_lived_note(lived_path)
        log.info(
            f"[practice_runner] Lived note circulated: {slug} "
            f"(bridge={result.get('bridge_log')}, "
            f"digest={result.get('digest')}, "
            f"surfacing={result.get('surfacing_id')})"
        )
    except Exception as e:
        log.warning(
            f"[practice_runner] Could not finalize Lived note for {slug}: {e}"
        )

    _write_readme()
    return lived_path


# ── README index ────────────────────────────────────────────────────────────


def _write_readme() -> None:
    try:
        PRACTICES_DIR.mkdir(parents=True, exist_ok=True)
        practices = load_practices()
        active = [p for p in practices if p.status == ACTIVE_STATUS]
        closed = [p for p in practices if p.status == CLOSED_STATUS]
        lines = [
            "# Practices",
            "",
            "Layer 4 of the Wisdom Engine — 30-day lived experiments that descend "
            "from syntheses and emit citable Lived notes. One folder per practice; "
            f"cap is {MAX_ACTIVE_PRACTICES} active at a time.",
            "",
            f"## Active ({len(active)}/{MAX_ACTIVE_PRACTICES})",
            "",
        ]
        for p in active:
            lines.append(f"- [[{p.slug}/practice]] — {p.title} (started {p.started_at}, {p.archetype})")
        if not active:
            lines.append("_(none)_")
        lines += ["", f"## Closed ({len(closed)})", ""]
        for p in closed:
            lines.append(f"- [[{p.slug}/practice]] → [[Alicia/Wisdom/Lived/{p.slug}]]")
        if not closed:
            lines.append("_(none yet)_")
        lines += [
            "",
            "---",
            "*Generated by `skills/practice_runner.py`. Do not edit by hand — it is overwritten on each practice mutation.*",
            "",
        ]
        atomic_write_text(str(PRACTICES_DIR / "README.md"), "\n".join(lines))
    except Exception as e:
        log.warning(f"Could not write Practices/README.md: {e}")


# ── Invariants ──────────────────────────────────────────────────────────────


def check_invariants() -> list[dict]:
    """
    Layer 4 invariants:
      - max_active_practices_exceeded: too many active at once
      - closed_practice_missing_lived_note: the contract that matters
      - active_practice_missing_practice_md: folder exists but no practice.md
      - overdue_check_in: an expected check-in day is >2 days past with no record
    """
    violations: list[dict] = []
    practices = load_practices()
    active = [p for p in practices if p.status == ACTIVE_STATUS]
    if len(active) > MAX_ACTIVE_PRACTICES:
        violations.append({
            "kind": "max_active_practices_exceeded",
            "count": len(active),
            "cap": MAX_ACTIVE_PRACTICES,
            "slugs": [p.slug for p in active],
        })

    for p in practices:
        if p.status == CLOSED_STATUS:
            lived = LIVED_DIR / f"{p.slug}.md"
            if not lived.exists():
                violations.append({
                    "kind": "closed_practice_missing_lived_note",
                    "slug": p.slug,
                    "expected_path": str(lived),
                })

    # Check folder-only practices (no practice.md).
    if PRACTICES_DIR.exists():
        for sub in PRACTICES_DIR.iterdir():
            if not sub.is_dir():
                continue
            if not (sub / "practice.md").exists():
                violations.append({
                    "kind": "active_practice_missing_practice_md",
                    "slug": sub.name,
                    "path": str(sub),
                })

    now_utc = datetime.now(timezone.utc)
    ledger = _load_check_in_log()
    for p in active:
        days = _days_since(p.started_at, now_utc)
        if days < 0:
            continue
        done = set((ledger.get(p.slug) or {}).get("done", []))
        for d in CHECK_IN_DAYS:
            if d < days - 2 and d not in done and d <= days:
                # only flag missed check-ins (grace window passed)
                violations.append({
                    "kind": "overdue_check_in",
                    "slug": p.slug,
                    "day": d,
                    "days_since_start": days,
                })
                break  # one overdue violation per practice is enough
    return violations


# ── Orchestrator ────────────────────────────────────────────────────────────


def run_daily_pass(
    *, now: Optional[datetime] = None,
) -> dict:
    """
    Scheduled daily entry point. Returns a summary dict:
        {
          "dry_run": bool,
          "active": int,
          "closed": int,
          "due_check_ins": [(slug, day)...],
          "invariant_violations": int,
          "readme_refreshed": bool,
        }

    The daily pass only *identifies* due check-ins and refreshes the README;
    sending the check-in message lives in alicia.py's scheduler handler so
    the runner stays free of Telegram coupling.
    """
    effective_dry = not USE_PRACTICE_RUNNER
    due = due_check_ins(now=now)
    practices = load_practices()
    active = [p for p in practices if p.status == ACTIVE_STATUS]
    closed = [p for p in practices if p.status == CLOSED_STATUS]
    violations = check_invariants()

    refreshed = False
    if not effective_dry:
        _write_readme()
        refreshed = True

    summary = {
        "dry_run": effective_dry,
        "active": len(active),
        "closed": len(closed),
        "due_check_ins": [(p.slug, d) for p, d in due],
        "invariant_violations": len(violations),
        "readme_refreshed": refreshed,
    }
    log.info(f"[practice_runner] {summary}")
    return summary


# ── CLI (debug) ────────────────────────────────────────────────────────────


def _main():
    import argparse
    parser = argparse.ArgumentParser(description="Practice Runner (debug)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--due", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--log", nargs=2, metavar=("SLUG", "TEXT"),
                        help="Append a log line to a practice")
    parser.add_argument("--close", metavar="SLUG",
                        help="Close a practice (writes closeout + Lived note)")
    args = parser.parse_args()

    if args.list:
        for p in load_practices():
            print(f"  [{p.status:>6s}] {p.slug:30s} day={_days_since(p.started_at, datetime.now(timezone.utc))} "
                  f"{p.archetype:>9s} — {p.title}")
        return
    if args.due:
        for p, d in due_check_ins():
            print(f"  {p.slug:30s} day {d}")
        return
    if args.check:
        for v in check_invariants():
            print(v)
        return
    if args.log:
        slug, text = args.log
        out = record_log_entry(slug, text)
        print(f"  logged → {out}")
        return
    if args.close:
        lived = close_practice(args.close)
        print(f"  closed → {lived}")
        return
    if args.run:
        print(json.dumps(run_daily_pass(), indent=2))
        return
    parser.print_help()


if __name__ == "__main__":
    _main()
