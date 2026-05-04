#!/usr/bin/env python3
"""
Response Capture — turn the user's Telegram replies into Tier-3 *writing*.

When Alicia sends a proactive message (a surfacing, a contradiction, a
practice check-in, a resonance ping) and the user replies, that reply
should not vanish into chat history. It is canonical the user-voice content
about a specific source — the same kind of material his vault essays in
`writing/` are made of.

This module captures those replies as a new note under
`writing/Responses/YYYY-MM-DD-HHMM-<slug>.md`, with frontmatter linking
back to the proactive that prompted it (decision_id + source synthesis +
archetype + channel). The body contains a wikilink to the source so
Obsidian's backlinks panel naturally surfaces the response when looking
at the synthesis.

Public API:
    capture_response(
        response_text, channel="text", *,
        proactive_decision_id=None, proactive_synthesis_title=None,
        proactive_prompt_text=None, archetype=None,
        voice_audio_path=None, now=None,
    ) -> Path

    find_recent_proactive_context(now=None, window_minutes=30) -> Optional[dict]
    capture_if_responsive(response_text, channel="text", *, now=None) -> Optional[Path]
    capture_unprompted(text, channel="text", *, voice_audio_path=None, now=None) -> Path

    # Read-back queries (Phase 11.5 — make captures queryable):
    parse_capture_file(path) -> Optional[dict]
    get_responses_for_synthesis(synthesis_title, *, max_recent=5) -> list[dict]
    get_recent_captures(*, n=10) -> list[dict]
    most_responded_syntheses(*, n=3) -> list[tuple[str, int]]

    # Composer-driven enrichment (Phase 11.7 — close the inner reply loop):
    enrich_proactive_with_past_responses(message, synthesis_title, *,
        max_recent=3, excerpt_chars=120) -> str

    # Morning capture resurface (Phase 11.10 — captures come back):
    pick_capture_for_morning_resurface(*, now=None, min_age_days=2,
        max_age_days=14) -> Optional[dict]
    mark_capture_resurfaced(capture_path, *, now=None) -> None
    render_morning_capture_resurface(capture_meta) -> str
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

log = logging.getLogger("alicia.response_capture")

# ── Config ──────────────────────────────────────────────────────────────────

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(str(MEMORY_DIR))
RESPONSES_DIR = VAULT_ROOT / "writing" / "Responses"
CIRCULATION_LOG_FILE = MEMORY_DIR / "circulation_log.json"

# How long after a proactive send a reply still counts as "responsive".
DEFAULT_RESPONSE_WINDOW_MINUTES = 30


# ── Slug builder ────────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 60) -> str:
    """Lowercase-hyphen slug for filenames. Keeps it readable, capped."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "response"


# ── Reading the circulation log (most-recent proactive) ─────────────────────


def _load_circulation_log() -> list[dict]:
    if not CIRCULATION_LOG_FILE.exists():
        return []
    try:
        return json.loads(CIRCULATION_LOG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"could not read circulation_log: {e}")
        return []


def find_recent_proactive_context(
    now: Optional[datetime] = None,
    *,
    window_minutes: int = DEFAULT_RESPONSE_WINDOW_MINUTES,
) -> Optional[dict]:
    """
    Find the most recent send=True circulation decision within the window.
    Returns the decision dict or None if there's no proactive context.

    "Proactive context" means: was Alicia the one who spoke last? If yes,
    the user's next message is plausibly a response to that.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    cutoff = now_utc - timedelta(minutes=window_minutes)

    for entry in reversed(_load_circulation_log()):
        if not entry.get("send"):
            continue
        try:
            decided_at = datetime.fromisoformat(entry["decided_at"])
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if decided_at < cutoff:
            return None  # log is reverse-chronological enough; oldest in window
        if decided_at <= now_utc:
            return entry
    return None


# ── Writing the capture ─────────────────────────────────────────────────────


def _build_frontmatter(
    *,
    captured_at: datetime,
    channel: str,
    decision_id: Optional[str],
    synthesis_title: Optional[str],
    source_kind: Optional[str],
    archetype: Optional[str],
    voice_audio_path: Optional[str],
) -> str:
    lines = ["---"]
    lines.append(f"captured_at: {captured_at.isoformat()}")
    lines.append(f"channel: {channel}")
    if decision_id:
        lines.append(f"proactive_decision_id: {decision_id}")
    if source_kind:
        lines.append(f"in_response_to: {source_kind}")
    if synthesis_title:
        # YAML-safe quote in case the title has colons / quotes
        safe = synthesis_title.replace('"', '\\"')
        lines.append(f'synthesis_referenced: "{safe}"')
    if archetype:
        lines.append(f"archetype: {archetype}")
    if voice_audio_path:
        lines.append(f"voice_audio: {voice_audio_path}")
    lines.append("source_tier: writing  # Tier 3 of canonical hierarchy")
    # Phase 16.0 — conversation tag (default for now). Future phases
    # will route messages through different conversations (work,
    # philosophy, family) and this field will be how captures find
    # their home.
    try:
        from myalicia.skills.conversations import current_conversation_id
        lines.append(f"conversation_id: {current_conversation_id()}")
    except Exception:
        lines.append("conversation_id: default")
    lines.append("---")
    return "\n".join(lines)


def _build_body(
    *,
    response_text: str,
    synthesis_title: Optional[str],
    proactive_prompt_text: Optional[str],
    channel: str,
) -> str:
    lines = []
    # Heading: short summary of the reply
    short = response_text.strip().split("\n", 1)[0]
    if len(short) > 60:
        short = short[:57] + "..."
    lines.append(f"# {short}")
    lines.append("")
    # Context block
    if synthesis_title:
        lines.append(f"*In response to:* [[{synthesis_title}]]")
    if proactive_prompt_text:
        prompt_excerpt = proactive_prompt_text.strip()
        if len(prompt_excerpt) > 280:
            prompt_excerpt = prompt_excerpt[:277] + "..."
        lines.append("")
        lines.append(f"**Alicia asked:** {prompt_excerpt}")
    lines.append("")
    lines.append("---")
    lines.append("")
    if channel == "voice":
        lines.append("*(spoken response — transcription below)*")
        lines.append("")
    lines.append(response_text.strip())
    lines.append("")
    return "\n".join(lines)


def capture_response(
    response_text: str,
    *,
    channel: str = "text",
    proactive_decision_id: Optional[str] = None,
    proactive_synthesis_title: Optional[str] = None,
    proactive_prompt_text: Optional[str] = None,
    proactive_source_kind: Optional[str] = None,
    archetype: Optional[str] = None,
    voice_audio_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Path:
    """
    Write a Tier-3 writing capture for a Telegram response.

    Returns the path of the created file. Caller is responsible for
    deciding whether to call this (e.g. only on inbound messages that
    follow a recent proactive — see capture_if_responsive).
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    # Local date stamp for the filename — use the user's local clock.
    stamp = now_utc.astimezone().strftime("%Y-%m-%d-%H%M")
    slug = _slug(response_text)
    filename = f"{stamp}-{slug}.md"
    path = RESPONSES_DIR / filename
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

    fm = _build_frontmatter(
        captured_at=now_utc,
        channel=channel,
        decision_id=proactive_decision_id,
        synthesis_title=proactive_synthesis_title,
        source_kind=proactive_source_kind,
        archetype=archetype,
        voice_audio_path=voice_audio_path,
    )
    body = _build_body(
        response_text=response_text,
        synthesis_title=proactive_synthesis_title,
        proactive_prompt_text=proactive_prompt_text,
        channel=channel,
    )

    path.write_text(fm + "\n\n" + body, encoding="utf-8")
    log.info(
        f"Captured response → writing/Responses/{filename} "
        f"(channel={channel}, synthesis={proactive_synthesis_title!r:.40})"
    )
    return path


def capture_if_responsive(
    response_text: str,
    *,
    channel: str = "text",
    direct_prompt: Optional[str] = None,
    direct_prompt_telegram_id: Optional[int] = None,
    voice_audio_path: Optional[str] = None,
    now: Optional[datetime] = None,
    window_minutes: int = DEFAULT_RESPONSE_WINDOW_MINUTES,
) -> Optional[Path]:
    """
    Capture the user's inbound message as a writing/Responses/ note when
    there is a clear prompt context — in priority order:

      1. **Native Telegram reply** (`direct_prompt` provided): the user
         tapped Reply on an Alicia message. The reply target's text *is*
         the prompt — capture unconditionally, regardless of whether the
         message came from the composer.

      2. **Time-window fallback**: a composer-driven proactive send is
         within `window_minutes` of `now`. Captured against that
         circulation_log entry with its rendered prompt_text.

      3. Otherwise: return None (idle chat, no capture).

    Voice messages are captured the same way — `channel="voice"` flips a
    flag in the frontmatter and includes a "spoken response" marker.
    """
    if not response_text or not response_text.strip():
        return None

    # Path 1: native reply trumps everything. The user explicitly chose
    # what they were responding to.
    if direct_prompt is not None and direct_prompt.strip():
        # Phase 24.0 — if the reply targets a tracked portrait, override
        # source_kind so the capture lands with portrait_response
        # provenance (visible in the frontmatter).
        portrait_meta = None
        portrait_source_kind = "conversational_reply"
        try:
            from myalicia.skills.weekly_self_portrait import lookup_portrait_message
            if direct_prompt_telegram_id is not None:
                portrait_meta = lookup_portrait_message(
                    int(direct_prompt_telegram_id)
                )
                if portrait_meta:
                    portrait_source_kind = "portrait_response"
        except Exception:
            portrait_meta = None
        path = capture_response(
            response_text=response_text,
            channel=channel,
            proactive_decision_id=(
                f"telegram-reply:{direct_prompt_telegram_id}"
                if direct_prompt_telegram_id is not None else None
            ),
            proactive_synthesis_title=None,
            proactive_prompt_text=direct_prompt.strip(),
            proactive_source_kind=portrait_source_kind,
            archetype=("beatrice" if portrait_meta else None),
            voice_audio_path=voice_audio_path,
            now=now,
        )
        # Phase 24.0 — append portrait_date frontmatter so the next
        # portrait composer can look up "last week he replied to the
        # portrait: …" via this field.
        if path and portrait_meta:
            try:
                _append_portrait_metadata(
                    path,
                    portrait_ts=portrait_meta.get("portrait_ts", ""),
                    vault_path=portrait_meta.get("vault_path", ""),
                )
            except Exception as e:
                log.debug(f"_append_portrait_metadata skip: {e}")
        # Phase 13.11 — if the parent prompt was a thread-pull message,
        # advance the underlying Open Thread.
        _maybe_mark_thread_pull_replied(direct_prompt, path)
        return path

    # Path 2: composer-driven proactive in window.
    ctx = find_recent_proactive_context(now=now, window_minutes=window_minutes)
    if ctx is None:
        return None
    rendered_prompt = ctx.get("prompt_text") or ctx.get("reason")
    path = capture_response(
        response_text=response_text,
        channel=channel,
        proactive_decision_id=ctx.get("id"),
        proactive_synthesis_title=ctx.get("synthesis_title")
            or (ctx.get("source_id")
                if ctx.get("source_kind") == "contradiction" else None),
        proactive_prompt_text=rendered_prompt,
        proactive_source_kind=ctx.get("source_kind"),
        archetype=ctx.get("archetype"),
        voice_audio_path=voice_audio_path,
        now=now,
    )
    # Phase 13.11 — also check the rendered_prompt from the composer-window
    # path; if it carries the thread-pull banner, advance the thread.
    _maybe_mark_thread_pull_replied(rendered_prompt or "", path)
    return path


def _append_portrait_metadata(
    capture_path: Path,
    *,
    portrait_ts: str = "",
    vault_path: str = "",
) -> None:
    """Phase 24.0 — Append `portrait_ts` + `portrait_path` to the
    capture's YAML frontmatter so the next portrait composer can
    look up 'last week he replied to the portrait: …' via grep.

    Idempotent: if the fields already exist, leaves them as-is.
    Safe: best-effort. Any error is debug-logged."""
    if capture_path is None or not capture_path.exists():
        return
    try:
        text = capture_path.read_text(encoding="utf-8")
    except Exception:
        return
    if not text.startswith("---\n"):
        return  # No frontmatter — skip silently
    end = text.find("\n---", 4)
    if end < 0:
        return
    frontmatter = text[4:end]
    body = text[end + 4:]
    # Skip if already present
    if "portrait_ts:" in frontmatter or "portrait_path:" in frontmatter:
        return
    insert_lines: list[str] = []
    if portrait_ts:
        insert_lines.append(f"portrait_ts: {portrait_ts}")
    if vault_path:
        insert_lines.append(f"portrait_path: {vault_path}")
    insert_lines.append("kind: portrait_response")
    new_frontmatter = (
        frontmatter.rstrip() + "\n" + "\n".join(insert_lines) + "\n"
    )
    new_text = f"---\n{new_frontmatter}---{body}"
    try:
        capture_path.write_text(new_text, encoding="utf-8")
    except Exception:
        pass


def _maybe_mark_thread_pull_replied(
    parent_text: str, capture_path: Optional[Path],
) -> None:
    """Phase 13.11 — quietly forward to thread_puller.mark_thread_pull_replied
    when the parent prompt looks like a thread-pull message. Best-effort:
    silently swallows any errors so capture writes are never blocked."""
    try:
        from myalicia.skills.thread_puller import (
            is_thread_pull_message, mark_thread_pull_replied,
        )
        if not is_thread_pull_message(parent_text):
            return
        cp = str(capture_path) if capture_path else None
        result = mark_thread_pull_replied(parent_text, capture_path=cp)
        if result:
            log.info(
                f"Thread-pull replied: thread="
                f"{result.get('thread_summary','')[:50]!r}"
            )
    except Exception as e:
        log.debug(f"_maybe_mark_thread_pull_replied skipped: {e}")


# ── Captures dir (unprompted /capture command) ──────────────────────────────


CAPTURES_DIR = VAULT_ROOT / "writing" / "Captures"


def capture_unprompted(
    text: str,
    *,
    channel: str = "text",
    voice_audio_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Path:
    """
    Archive a substantive the user-initiated thought (no Alicia prompt).
    Lands in `writing/Captures/YYYY-MM-DD-HHMM-<slug>.md` with frontmatter
    `source_tier: writing` and `kind: capture`. Used by the /capture
    Telegram command.
    """
    if not text or not text.strip():
        raise ValueError("capture_unprompted: empty text")
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    stamp = now_utc.astimezone().strftime("%Y-%m-%d-%H%M")
    slug = _slug(text)
    filename = f"{stamp}-{slug}.md"
    path = CAPTURES_DIR / filename
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    fm_lines = [
        "---",
        f"captured_at: {now_utc.isoformat()}",
        f"channel: {channel}",
        "kind: capture",
        "source_tier: writing  # Tier 3 of canonical hierarchy",
    ]
    if voice_audio_path:
        fm_lines.append(f"voice_audio: {voice_audio_path}")
    fm_lines.append("---")
    short = text.strip().split("\n", 1)[0]
    if len(short) > 60:
        short = short[:57] + "..."
    body = [f"# {short}", ""]
    if channel == "voice":
        body.append("*(spoken capture — transcription below)*")
        body.append("")
    body.append(text.strip())
    body.append("")
    path.write_text("\n".join(fm_lines) + "\n\n" + "\n".join(body),
                    encoding="utf-8")
    log.info(
        f"Captured unprompted → writing/Captures/{filename} "
        f"(channel={channel}, len={len(text)})"
    )
    return path


# ── Read-back queries (Phase 11.5 — make captures queryable) ────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FM_FIELD_RE = re.compile(r'^([a-z_]+):\s*(.*?)\s*$', re.MULTILINE)


def parse_capture_file(path: Path) -> Optional[dict]:
    """Read a writing/Responses/ or writing/Captures/ file and extract its
    frontmatter + body excerpt as a lightweight dict. Returns None if the
    file isn't readable or has no frontmatter.

    Returned dict shape:
        {
            "path": Path,
            "kind": "response" | "capture",  # by parent dir
            "captured_at": str (ISO),
            "channel": "text" | "voice",
            "synthesis_referenced": str | None,
            "archetype": str | None,
            "in_response_to": str | None,
            "proactive_decision_id": str | None,
            "body_excerpt": str (first ~200 chars of body),
        }
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        log.debug(f"parse_capture_file: read error on {path}: {e}")
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm_block = m.group(1)
    body = text[m.end():].strip()

    fields: dict[str, str] = {}
    for fm in _FM_FIELD_RE.finditer(fm_block):
        key, value = fm.group(1), fm.group(2)
        # Strip wrapping quotes if present (YAML-quoted strings)
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1].replace('\\"', '"')
        # Strip inline comments after the value
        if "#" in value and not value.startswith("#"):
            value = value.split("#", 1)[0].strip()
        fields[key] = value

    # Body excerpt: first non-heading line of the body, capped
    excerpt_lines = [
        ln for ln in body.split("\n")
        if ln.strip() and not ln.lstrip().startswith("#")
        and not ln.lstrip().startswith("*In response to")
        and not ln.lstrip().startswith("**Alicia asked")
        and not ln.lstrip().startswith("---")
        and not ln.lstrip().startswith("*(spoken")
    ]
    body_excerpt = " ".join(excerpt_lines)[:200].strip()

    return {
        "path": path,
        "kind": "capture" if path.parent.name == "Captures" else "response",
        "captured_at": fields.get("captured_at", ""),
        "channel": fields.get("channel", "text"),
        "synthesis_referenced": fields.get("synthesis_referenced") or None,
        "archetype": fields.get("archetype") or None,
        "in_response_to": fields.get("in_response_to") or None,
        "proactive_decision_id": fields.get("proactive_decision_id") or None,
        "body_excerpt": body_excerpt,
    }


def _walk_capture_files() -> list[Path]:
    """Yield every .md file under writing/Responses/ + writing/Captures/."""
    out: list[Path] = []
    for d in (RESPONSES_DIR, CAPTURES_DIR):
        if not d.is_dir():
            continue
        try:
            out.extend(d.glob("*.md"))
        except Exception as e:
            log.debug(f"_walk_capture_files: glob error on {d}: {e}")
    return out


def get_responses_for_synthesis(
    synthesis_title: str, *, max_recent: int = 5
) -> list[dict]:
    """Return up to `max_recent` capture entries that reference the given
    synthesis title (matched against the `synthesis_referenced` frontmatter
    field). Most recent first. Empty list if none.

    Used by future surfacing/render paths to inject the user's past responses
    into the context Sonnet uses to compose a re-surfacing message — making
    Alicia's resurfacing 'continuing a conversation' rather than 'asking
    again'.
    """
    if not synthesis_title:
        return []
    target = synthesis_title.strip()
    matches: list[dict] = []
    for f in _walk_capture_files():
        meta = parse_capture_file(f)
        if not meta:
            continue
        if (meta.get("synthesis_referenced") or "").strip() == target:
            matches.append(meta)
    # Sort by captured_at desc; fall back to file mtime when ts missing
    def _sort_key(m: dict):
        ts = m.get("captured_at") or ""
        if ts:
            return ts
        try:
            return datetime.fromtimestamp(m["path"].stat().st_mtime).isoformat()
        except Exception:
            return ""
    matches.sort(key=_sort_key, reverse=True)
    return matches[:max_recent]


def get_recent_captures(
    *, n: int = 10, conversation_id: Optional[str] = None,
) -> list[dict]:
    """Return the n most recent capture entries (responses + unprompted),
    parsed and sorted newest-first. Used by /wisdom and any audit pass.

    Phase 16.4 — `conversation_id` filters captures to one conversation.
    None (default) preserves whole-vault behavior. Capture frontmatter
    has been carrying conversation_id since Phase 16.0 (writes-only
    tagging), so backwards-compat: entries without the field are
    treated as 'default'.
    """
    parsed: list[dict] = []
    for f in _walk_capture_files():
        meta = parse_capture_file(f)
        if meta:
            # Phase 16.4 — conversation scoping
            if conversation_id is not None:
                entry_cid = (meta.get("conversation_id") or "default")
                if entry_cid != conversation_id:
                    continue
            parsed.append(meta)
    parsed.sort(
        key=lambda m: m.get("captured_at") or "", reverse=True
    )
    return parsed[:n]


def enrich_proactive_with_past_responses(
    message: str,
    synthesis_title: Optional[str],
    *,
    max_recent: int = 3,
    excerpt_chars: int = 120,
) -> str:
    """Append a compact 'past responses on this idea' footer to a proactive
    message when the synthesis has prior captured replies.

    Phase 11.7 — the closing move on the inner reply loop. When the
    Composer picks a surfacing whose synthesis the user has already
    responded to, the resurfacing message should READ as continuing the
    conversation, not asking again. This helper appends a quiet footer
    (📎 emoji, italicised) listing the most-recent N responses by date +
    excerpt — Sonnet/Opus can later lift this to first-class context, but
    deterministic append works as a baseline.

    Returns the message unchanged when:
      - synthesis_title is None or empty (e.g. contradiction-driven send)
      - no past responses exist for that synthesis
      - any error occurs (logged at debug, never raised)
    """
    if not synthesis_title or not synthesis_title.strip():
        return message
    try:
        responses = get_responses_for_synthesis(
            synthesis_title.strip(), max_recent=max_recent
        )
    except Exception as e:
        log.debug(f"enrich_proactive_with_past_responses: lookup failed: {e}")
        return message
    if not responses:
        return message

    # Voice-friendly framing: "And earlier on this:" reads cleanly aloud
    # because text_to_voice strips emoji/markdown but preserves the prose.
    # Each excerpt is preceded by a natural-language age ("3 days ago"
    # instead of the ISO date which would be spoken as digits).
    now_utc = datetime.now(timezone.utc)
    lines: list[str] = []
    for r in responses:
        excerpt = (r.get("body_excerpt") or "").strip()
        if not excerpt:
            continue
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[: excerpt_chars - 1].rstrip() + "…"
        # Compute natural-language age from captured_at
        age_label = "earlier"
        ts = r.get("captured_at") or ""
        try:
            captured_at = datetime.fromisoformat(ts)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
            days = max(0, (now_utc - captured_at).days)
            if days == 0:
                age_label = "earlier today"
            elif days == 1:
                age_label = "yesterday"
            elif days < 7:
                age_label = f"{days} days ago"
            elif days < 14:
                age_label = "last week"
            else:
                age_label = f"{days // 7} weeks ago"
        except Exception:
            pass
        lines.append(f'  · _{age_label}_ — "{excerpt}"')

    if not lines:
        return message
    header = "📎 _And earlier on this:_"
    return message.rstrip() + "\n\n" + header + "\n" + "\n".join(lines)


# ── Captures during a practice window (Phase 11.12) ─────────────────────────


def get_captures_during_practice(
    started_at: str,
    *,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Return all captures (writing/Responses/ + writing/Captures/) made
    between a practice's started_at date (inclusive) and `now` (default
    datetime.now), newest-first.

    Used by practice_runner.close_practice() to embed the captures the user
    made during the practice into the resulting Lived note as 'raw material'
    — the body text the user reaches for when composing what the practice
    taught will reference these naturally.

    Args:
      started_at: 'YYYY-MM-DD' string from practice.md frontmatter
      now: datetime cutoff (default = now)

    Returns: list of capture-meta dicts (same shape as parse_capture_file).
    """
    if not started_at:
        return []
    try:
        start = datetime.strptime(started_at, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return []
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    matches: list[dict] = []
    for f in _walk_capture_files():
        meta = parse_capture_file(f)
        if not meta:
            continue
        ts_str = meta.get("captured_at") or ""
        try:
            captured_at = datetime.fromisoformat(ts_str)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if start <= captured_at <= now_utc:
            matches.append(meta)
    matches.sort(key=lambda m: m.get("captured_at") or "", reverse=True)
    return matches


# ── Morning capture resurface (Phase 11.10) ─────────────────────────────────


# Tracks which capture files have been re-presented in the morning fallback,
# so the same capture isn't shown twice unless the user writes nothing new.
_RESURFACE_LOG = MEMORY_DIR / "capture_resurface_log.json"


def _load_resurface_log() -> dict:
    """{filename_stem: ISO_timestamp_of_last_resurface}"""
    if not _RESURFACE_LOG.exists():
        return {}
    try:
        return json.loads(_RESURFACE_LOG.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug(f"_load_resurface_log: {e}")
        return {}


def _save_resurface_log(data: dict) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        _RESURFACE_LOG.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
    except Exception as e:
        log.warning(f"_save_resurface_log failed: {e}")


def mark_capture_resurfaced(
    capture_path: Path, *, now: Optional[datetime] = None
) -> None:
    """Record that this capture was just resurfaced — guards against
    re-picking it tomorrow."""
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    data = _load_resurface_log()
    data[capture_path.stem] = now_utc.isoformat()
    _save_resurface_log(data)


def pick_capture_for_morning_resurface(
    *,
    now: Optional[datetime] = None,
    min_age_days: int = 2,
    max_age_days: int = 14,
    cooldown_days: int = 21,
) -> Optional[dict]:
    """Return one unprompted capture (kind='capture', no synthesis_referenced)
    that's old enough to feel returned-to, recent enough to feel alive, and
    hasn't been re-surfaced in the cooldown window.

    Logic:
      - Walk writing/Captures/ (not Responses/ — replies have their own loop)
      - Filter: age in [min_age_days, max_age_days]
      - Filter: not in resurface_log within cooldown_days
      - Pick: oldest qualifying first (so the deepest unresurfaced thought
        gets brought back before a fresher one)

    Returns None when no capture qualifies — caller stays quiet.
    """
    if not CAPTURES_DIR.is_dir():
        return None
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    min_age = timedelta(days=min_age_days)
    max_age = timedelta(days=max_age_days)
    cooldown = timedelta(days=cooldown_days)
    log_data = _load_resurface_log()

    candidates: list[tuple[datetime, dict]] = []
    for f in CAPTURES_DIR.glob("*.md"):
        meta = parse_capture_file(f)
        if not meta:
            continue
        # Captures/ entries are kind='capture' by parent dir; ignore Responses/
        if meta.get("kind") != "capture":
            continue
        ts_str = meta.get("captured_at") or ""
        try:
            captured_at = datetime.fromisoformat(ts_str)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        age = now_utc - captured_at
        if age < min_age or age > max_age:
            continue
        # Cooldown check
        last_resurfaced_str = log_data.get(f.stem)
        if last_resurfaced_str:
            try:
                last = datetime.fromisoformat(last_resurfaced_str)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now_utc - last) < cooldown:
                    continue
            except Exception:
                pass
        candidates.append((captured_at, meta))

    if not candidates:
        return None
    # Oldest qualifying first — bring deeper-shelved thoughts back first
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def render_morning_capture_resurface(capture_meta: dict) -> str:
    """Render a morning fallback message that re-presents a captured
    thought. Keeps the framing light — this is a 'where has it landed'
    follow-up, not a demand. Returns the full message text ready for
    safe_send_md."""
    excerpt = (capture_meta.get("body_excerpt") or "").strip()
    if not excerpt:
        excerpt = "(empty capture)"
    # Days-since label — "yesterday" / "N days ago"
    ts = capture_meta.get("captured_at") or ""
    days_label = "recently"
    try:
        captured_at = datetime.fromisoformat(ts)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - captured_at
        n = max(1, delta.days)
        days_label = f"{n} day{'s' if n != 1 else ''} ago"
    except Exception:
        pass
    return (
        f"📔 _A thought you captured {days_label}:_\n\n"
        f"\"{excerpt}\"\n\n"
        f"_Where has it landed?_"
    )


def most_responded_syntheses(
    *, n: int = 3, conversation_id: Optional[str] = None,
) -> list[tuple[str, int]]:
    """Return the n syntheses with the most captured responses, as
    (title, count) tuples. Used by /wisdom to show which ideas the user
    is engaging with most.

    Captures with no synthesis_referenced (e.g. unprompted /capture
    thoughts) are not counted toward any title.

    Phase 16.6 — `conversation_id` filters captures to one conversation.
    None preserves whole-vault behavior. Backwards-compat: entries
    without the field are treated as 'default'.
    """
    counts: dict[str, int] = {}
    for f in _walk_capture_files():
        meta = parse_capture_file(f)
        if not meta:
            continue
        # Phase 16.6 — conversation scoping
        if conversation_id is not None:
            entry_cid = (meta.get("conversation_id") or "default")
            if entry_cid != conversation_id:
                continue
        title = (meta.get("synthesis_referenced") or "").strip()
        if not title:
            continue
        counts[title] = counts.get(title, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:n]
