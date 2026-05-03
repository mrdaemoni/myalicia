#!/usr/bin/env python3
"""
Wisdom Engine observability dashboard — `/wisdom` Telegram command.

Renders a compact single-screen view of all five circulation surfaces:

  1. Active practices + next check-in date
  2. Active contradictions with last-7-day pick counts (proves Fix 1's
     differentiation by showing time-share spread)
  3. Recent composer decisions (slot, archetype, source_kind, excerpt)
  4. Recent captures (writing/Responses/ + writing/Captures/)
  5. Surfacing queue depth (synthesis | lived | practice_progress)

Built from data already on disk — no new state files, no new schemas.
Pure read-only assembler. Failures degrade gracefully: a layer that
errors is skipped with a note, the rest still render.

Public API:
    render_wisdom_dashboard(now=None) -> str
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.wisdom_dashboard")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", os.path.expanduser("~/alicia/memory")
))
CIRCULATION_LOG_FILE = MEMORY_DIR / "circulation_log.json"
SURFACING_QUEUE_FILE = MEMORY_DIR / "synthesis_surfacing_queue.json"
CONTRADICTIONS_PATH = VAULT_ROOT / "Alicia" / "Self" / "Contradictions.md"
RESPONSES_DIR = VAULT_ROOT / "writing" / "Responses"
CAPTURES_DIR = VAULT_ROOT / "writing" / "Captures"
PRACTICES_DIR = VAULT_ROOT / "Alicia" / "Practices"


# ── Section renderers ──────────────────────────────────────────────────────


def _render_practices_section(now_utc: datetime) -> str:
    """Active practices + day count + next check-in date."""
    try:
        from myalicia.skills.practice_runner import (
            active_practices, _days_since, CHECK_IN_DAYS,
            MAX_ACTIVE_PRACTICES,
        )
    except Exception as e:
        return f"*Practices:* (error: {e})"
    try:
        ap = active_practices()
    except Exception as e:
        return f"*Practices:* (load error: {e})"
    if not ap:
        return f"*Practices ({0}/{MAX_ACTIVE_PRACTICES}):* none active"
    lines = [f"*Practices ({len(ap)}/{MAX_ACTIVE_PRACTICES}):*"]
    for p in ap:
        days = _days_since(p.started_at, now_utc)
        # Find next CHECK_IN_DAYS value > today's day
        future = [d for d in CHECK_IN_DAYS if d > days]
        if future:
            next_day = future[0]
            from datetime import datetime as _dt
            try:
                started = _dt.strptime(p.started_at, "%Y-%m-%d")
                target = started + timedelta(days=next_day)
                next_str = (
                    f"day {next_day} ({target.strftime('%a %b %d')})"
                )
            except Exception:
                next_str = f"day {next_day}"
        else:
            next_str = "closeout window"
        lines.append(
            f"• {p.slug} · {p.archetype} · day {days}, next: {next_str}"
        )
    return "\n".join(lines)


def _render_contradictions_section(now_utc: datetime) -> str:
    """Active contradictions with last-7-day composer pick counts.

    This makes Fix 1 (recency + practice-link scoring) visible: ideally
    multiple contradictions get time-share rather than one winning every
    send.
    """
    try:
        from myalicia.skills.circulation_composer import _parse_active_contradictions
    except Exception as e:
        return f"*Contradictions:* (error: {e})"
    try:
        active = _parse_active_contradictions()
    except Exception as e:
        return f"*Contradictions:* (parse error: {e})"
    if not active:
        return "*Contradictions:* (ledger missing or empty)"

    # Count last-7-day picks per contradiction title
    cutoff = now_utc - timedelta(days=7)
    pick_counts: Counter = Counter()
    try:
        if CIRCULATION_LOG_FILE.exists():
            entries = json.loads(CIRCULATION_LOG_FILE.read_text(encoding="utf-8"))
            for e in entries:
                if e.get("source_kind") != "contradiction":
                    continue
                if not e.get("send"):
                    continue
                try:
                    decided_at = datetime.fromisoformat(e["decided_at"])
                    if decided_at.tzinfo is None:
                        decided_at = decided_at.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if decided_at >= cutoff:
                    pick_counts[e.get("source_id") or ""] += 1
    except Exception:
        pass

    lines = [f"*Contradictions ({len(active)}, last-7d picks):*"]
    # Sort: most-recently-updated first, picks as tiebreak
    def _sort_key(e):
        return (e.get("last_updated") or "", -pick_counts.get(e["title"], 0))
    for e in sorted(active, key=_sort_key, reverse=True):
        title = e["title"]
        n = pick_counts.get(title, 0)
        marker = "🔥" if n >= 2 else " ·" if n == 1 else "  "
        lines.append(f"{marker} {title[:60]} ({n})")
    return "\n".join(lines)


def _render_composer_section(now_utc: datetime, *, n: int = 5) -> str:
    """Last N composer decisions — what voice has been speaking."""
    if not CIRCULATION_LOG_FILE.exists():
        return "*Composer:* (no log yet)"
    try:
        entries = json.loads(CIRCULATION_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return f"*Composer:* (read error: {e})"
    recent = entries[-n:][::-1]  # newest first
    if not recent:
        return "*Composer:* (log empty)"
    lines = [f"*Composer (last {len(recent)}):*"]
    for e in recent:
        try:
            decided_at = datetime.fromisoformat(e["decided_at"])
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
            local = decided_at.astimezone()
            time_str = local.strftime("%a %H:%M")
        except Exception:
            time_str = "??:??"
        slot = e.get("slot", "?")
        if e.get("send"):
            arch = e.get("archetype") or "—"
            sk = e.get("source_kind") or "—"
            sid = (e.get("source_id") or "")[:40]
            prompt = (e.get("prompt_text") or e.get("reason") or "")
            prompt_excerpt = re.sub(r"\s+", " ", prompt).strip()[:50]
            line = (f"  {time_str} {slot:<11} {arch:<8} {sk:<14} "
                    f"{sid}")
            if prompt_excerpt and prompt_excerpt != sid[:50]:
                line += f"\n    └─ {prompt_excerpt}…"
            lines.append(line)
        else:
            reason = (e.get("reason") or "quiet")
            short = re.sub(r"surfacings_(?:ready|after_dedup)=\d+\s*", "", reason)
            short = short.replace("active_contradictions=", "ctr=")[:55]
            lines.append(f"  {time_str} {slot:<11} NO_SEND   {short}")
    return "\n".join(lines)


def _render_captures_section(
    *, n: int = 5, conversation_id: Optional[str] = None,
) -> str:
    """Recent files in writing/Responses/ + writing/Captures/.

    Phase 16.4 — when `conversation_id` is set, filter captures to
    that conversation only. None preserves whole-vault behavior.
    Backwards-compat: captures missing the conversation_id field
    are treated as 'default' (Phase 16.0 schema-compat baked in).
    """
    items: list[tuple[float, str, Path]] = []
    for label, d in (("R", RESPONSES_DIR), ("C", CAPTURES_DIR)):
        if not d.is_dir():
            continue
        try:
            for f in d.glob("*.md"):
                # Phase 16.4 — apply conversation filter when set
                if conversation_id is not None:
                    try:
                        # Light frontmatter scan — read first ~30 lines
                        with open(f, encoding="utf-8") as fh:
                            head = []
                            for i, ln in enumerate(fh):
                                if i > 30:
                                    break
                                head.append(ln)
                        text = "".join(head)
                        m_cid = re.search(
                            r"^conversation_id:\s*(\S+)\s*$",
                            text, re.MULTILINE,
                        )
                        entry_cid = (
                            m_cid.group(1).strip().strip('"').strip("'")
                            if m_cid else "default"
                        )
                        if entry_cid != conversation_id:
                            continue
                    except Exception:
                        # If frontmatter read fails, treat as default
                        if conversation_id != "default":
                            continue
                items.append((f.stat().st_mtime, label, f))
        except Exception:
            continue
    items.sort(reverse=True)
    if not items:
        return "*Captures:* (none yet)"
    lines = [f"*Captures (last {min(n, len(items))} of {len(items)}):*"]
    for mtime, label, f in items[:n]:
        local = datetime.fromtimestamp(mtime).astimezone()
        # Trim leading date-time stamp from the slug for compactness
        stem = f.stem
        m = re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-(.+)$", stem)
        slug = m.group(1) if m else stem
        lines.append(f"  [{label}] {local.strftime('%a %H:%M')} {slug[:60]}")
    return "\n".join(lines)


def _render_drawings_section(now_utc: datetime, *, days: int = 7,
                             max_show: int = 5) -> str:
    """Recent drawing decisions from circulation_log (Phase 13.0).

    Drawings now write to circulation_log with channel='drawing' alongside
    text/voice composer decisions. This section surfaces them as a
    first-class circulation surface — what Alicia drew, in which voice,
    with what caption.
    """
    if not CIRCULATION_LOG_FILE.exists():
        return f"*Drawings (last {days}d):* (no circulation log yet)"
    try:
        entries = json.loads(CIRCULATION_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return f"*Drawings:* (read error: {e})"
    cutoff = now_utc - timedelta(days=days)
    drawings: list[dict] = []
    for e in entries:
        if e.get("channel") != "drawing":
            continue
        try:
            decided_at = datetime.fromisoformat(e["decided_at"])
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if decided_at < cutoff:
            continue
        drawings.append((decided_at, e))
    if not drawings:
        return f"*Drawings (last {days}d):* none"
    drawings.sort(key=lambda x: x[0], reverse=True)
    lines = [f"*Drawings (last {days}d, n={len(drawings)}):*"]
    for decided_at, e in drawings[:max_show]:
        local = decided_at.astimezone()
        archetype = (e.get("archetype") or "—").lower()
        sk = (e.get("source_kind") or "").replace("drawing_", "")
        prompt = (e.get("prompt_text") or e.get("reason") or "")
        prompt_excerpt = re.sub(r"\s+", " ", prompt).strip()[:60]
        lines.append(
            f"  · _{local.strftime('%a %H:%M')}_ "
            f"{archetype:<9} ({sk}) \"{prompt_excerpt}\""
        )
    if len(drawings) > max_show:
        lines.append(f"  _… and {len(drawings) - max_show} more_")
    return "\n".join(lines)


def _render_most_responded_section(
    *, n: int = 3, conversation_id: Optional[str] = None,
) -> str:
    f"""Top-n syntheses with the most captured {USER_NAME} responses.

    Phase 16.6 — `conversation_id` filters captures to one conversation.
    None preserves whole-vault behavior."""
    try:
        from myalicia.skills.response_capture import most_responded_syntheses
    except Exception as e:
        return f"*Most-responded:* (error: {e})"
    try:
        ranked = most_responded_syntheses(
            n=n, conversation_id=conversation_id,
        )
    except Exception as e:
        return f"*Most-responded:* (query error: {e})"
    if not ranked:
        return "*Most-responded:* (no responses yet — captures still need a synthesis_referenced field)"
    lines = [f"*Most-responded syntheses (top {len(ranked)}):*"]
    for title, count in ranked:
        marker = "💬"
        lines.append(f"  {marker} ×{count}  {title[:65]}")
    return "\n".join(lines)


def _render_surfacing_section() -> str:
    """Surfacing queue depth by kind."""
    if not SURFACING_QUEUE_FILE.exists():
        return "*Surfacings:* queue empty"
    try:
        entries = json.loads(SURFACING_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return f"*Surfacings:* (read error: {e})"
    if not entries:
        return "*Surfacings:* queue empty"
    by_kind: Counter = Counter()
    ready_now = 0
    now_utc = datetime.now(timezone.utc)
    for e in entries:
        kind = e.get("kind", "synthesis")
        # Count entries with at least one undelivered, ripe, non-expired stage
        expires_raw = e.get("expires_at")
        if expires_raw:
            try:
                ex = datetime.fromisoformat(expires_raw)
                if ex.tzinfo is None:
                    ex = ex.replace(tzinfo=timezone.utc)
                if now_utc >= ex:
                    continue  # expired — don't count
            except Exception:
                pass
        by_kind[kind] += 1
        for stage in e.get("stages", []):
            if stage.get("delivered"):
                continue
            try:
                ready = datetime.fromisoformat(stage["deliver_after"])
                if ready.tzinfo is None:
                    ready = ready.replace(tzinfo=timezone.utc)
                if now_utc >= ready:
                    ready_now += 1
                    break
            except Exception:
                pass
    if not by_kind:
        return "*Surfacings:* queue empty (all expired)"
    parts = [f"{n} {k}" for k, n in by_kind.most_common()]
    return f"*Surfacings:* {', '.join(parts)} · {ready_now} ready now"


# ── Main entry point ────────────────────────────────────────────────────────


def render_wisdom_dashboard(
    now: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
) -> str:
    """Compose the full /wisdom dashboard message.

    Each section is independently fault-tolerant — if one fails, the others
    still render. Output fits in a single Telegram message (<4000 chars).

    Phase 16.4 — `conversation_id` scopes the captures section. Other
    sections (practices, contradictions, composer state, drawings,
    surfacing queue) are inherently global so they remain whole-vault.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    # Phase 16.4 — scope banner
    header_lines = ["🌀 *Wisdom Engine — live state*"]
    if conversation_id is not None:
        try:
            from myalicia.skills.conversations import get_conversation_meta
            meta = get_conversation_meta(conversation_id) or {}
            label = meta.get("label", conversation_id)
            header_lines.append(
                f"_captures scoped to:_ *{label}* (`{conversation_id}`) — "
                f"`/wisdom all` for whole-vault"
            )
        except Exception:
            header_lines.append(f"_captures scoped to:_ `{conversation_id}`")
    sections = [
        "\n".join(header_lines),
        "",
        _render_practices_section(now_utc),
        "",
        _render_contradictions_section(now_utc),
        "",
        _render_composer_section(now_utc),
        "",
        _render_drawings_section(now_utc),
        "",
        _render_surfacing_section(),
        "",
        _render_captures_section(conversation_id=conversation_id),
        "",
        _render_most_responded_section(conversation_id=conversation_id),
    ]
    return "\n".join(sections)
