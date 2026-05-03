#!/usr/bin/env python3
"""
Profile-driven proactivity — Phase 13.5.

The Sunday person_diarization pass writes a "the user This Week" profile
with an "Open Threads" section: unresolved questions and exploration
vectors that span multiple conversations. Without this skill, those
threads sit in the profile and slowly stale.

This module turns those open threads into mid-week thread-pull
proactive messages: parse the section, score against recently-pulled
threads, pick one, ask Haiku to render a 2-4 line continuation prompt
in Alicia's voice. The result is a single message ready to send via
the existing midday proactive path.

Public API:
    parse_open_threads(profile_text) -> list[dict]
    record_thread_pull(thread, message)
    recent_thread_pulls(within_days=14) -> list[dict]
    pick_thread(threads, recent_pulls) -> dict | None
    build_thread_pull_message() -> str | None  # main entry point

Storage:
    ~/alicia/memory/thread_pulls.jsonl
        {"ts", "thread_summary", "message"}

Wiring:
    skills/proactive_messages.py:build_midday_message — early-out branch
    that returns this message ~30% of the time when conditions hold.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.thread_puller")

PROFILES_DIR = str(config.vault.self_path / "Profiles")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
THREAD_PULLS_PATH = os.path.join(MEMORY_DIR, "thread_pulls.jsonl")

# Don't pull the same thread again within this window (days).
PULL_COOLDOWN_DAYS = 10

# Probability that midday picks the thread-pull branch when one is available.
MIDDAY_PROBABILITY = 0.30


# ── Open Threads parser ────────────────────────────────────────────────────


def _latest_hector_profile() -> Optional[str]:
    """Return the path to the most recent *-hector.md profile, or None."""
    if not os.path.isdir(PROFILES_DIR):
        return None
    files = sorted(
        glob.glob(os.path.join(PROFILES_DIR, "*-hector.md")), reverse=True
    )
    return files[0] if files else None


def _extract_open_threads_text(profile_text: str) -> str:
    """Extract the Open Threads section body from a hector profile.

    person_diarization renders Open Threads as either a `**Open Threads**`
    bold paragraph or `## Open Threads` header. Walk forward until the
    next bold-label or header.
    """
    if not profile_text:
        return ""
    lines = profile_text.split("\n")
    start = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if (
            s.startswith("**Open Threads**")
            or s.startswith("## Open Threads")
            or s.startswith("### Open Threads")
            or s.startswith("- **Open Threads**")
        ):
            start = i
            break
    if start < 0:
        return ""

    body_lines = []
    # Skip the header line itself if it's a pure header; keep the body.
    header_line = lines[start].strip()
    # Inline-bold style sometimes has the body on the next line, sometimes
    # appended after a colon. Handle both.
    after_colon = ""
    if ":" in header_line and not header_line.startswith("##"):
        after_colon = header_line.split(":", 1)[1].strip()
    if after_colon:
        body_lines.append(after_colon)

    for j in range(start + 1, len(lines)):
        nxt = lines[j].strip()
        # Stop at the next section header / bold label.
        if (
            nxt.startswith("# ")
            or nxt.startswith("## ")
            or nxt.startswith("### ")
            or (nxt.startswith("**") and nxt.endswith("**") and len(nxt) < 60)
            or nxt.startswith("- **")
        ):
            break
        body_lines.append(lines[j])
    return "\n".join(body_lines).strip()


def parse_open_threads(profile_text: str) -> list[dict]:
    """Parse the Open Threads section into individual thread dicts.

    The section is typically flowing prose with multiple threads separated
    by semicolons or sentence-and-clause structure. Heuristic split:
      1. Split on semicolons (most common in person_diarization output).
      2. Within each chunk, drop the lead-in like "Several threads await
         continuation:".
      3. Split a residual chunk by sentences (.) only when each sentence
         clearly stands alone as a thread.

    Returns a list of {"summary": str} dicts. Empty list if the section
    can't be parsed or holds no actionable threads.
    """
    body = _extract_open_threads_text(profile_text)
    if not body:
        return []
    # Collapse newlines to spaces — threads are treated as flat prose.
    flat = re.sub(r"\s+", " ", body).strip()
    # Drop leading framing like "Several threads await continuation:"
    flat = re.sub(
        r"^[^:.;]{0,60}(threads?|questions?|continu|explor)[^:.;]{0,60}:\s*",
        "",
        flat,
        count=1,
        flags=re.IGNORECASE,
    )
    # Primary split on semicolons.
    parts = [p.strip() for p in flat.split(";") if p.strip()]
    # If only one part survived, try splitting on `. ` between sentences,
    # but keep this conservative (≥2 sentences AND each ≥30 chars).
    if len(parts) <= 1:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip()]
        if len(sentences) >= 2 and all(len(s) >= 30 for s in sentences):
            parts = sentences
        else:
            parts = [flat]

    threads: list[dict] = []
    for p in parts:
        s = p.strip().rstrip(".;,")
        # Drop trivially short fragments
        if len(s) < 20:
            continue
        threads.append({"summary": s})
    return threads


# ── Pull-history storage ───────────────────────────────────────────────────


def record_thread_pull(thread_summary: str, message: str) -> None:
    """Append a thread-pull event to the jsonl log."""
    if not thread_summary:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "thread_summary": thread_summary[:400],
            "message": (message or "")[:600],
        }
        # Phase 16.0 — tag with conversation_id (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(THREAD_PULLS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_thread_pull failed: {e}")


def recent_thread_pulls(within_days: int = 14) -> list[dict]:
    """Return pull events newer than `within_days`.

    Filters out reply records (kind='reply') added by Phase 13.11 so
    the existing cooldown logic (pick_thread) sees only true pulls."""
    if not os.path.exists(THREAD_PULLS_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(THREAD_PULLS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                # Phase 13.11 — skip reply records; this function counts pulls.
                if e.get("kind") == "reply":
                    continue
                try:
                    ts = datetime.fromisoformat(e.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_thread_pulls failed: {e}")
    return out


# ── Phase 13.11 — Thread-pull → reply bridge ───────────────────────────────


# Banner that build_thread_pull_message prepends to every thread-pull.
# Used by response_capture to detect that a parent message was a thread
# pull (so the subsequent capture should advance the underlying thread).
THREAD_PULL_BANNER = "🧵 _picking up a thread from Sunday_"


def is_thread_pull_message(text: str) -> bool:
    """True if `text` looks like a message produced by build_thread_pull_message."""
    if not text:
        return False
    return THREAD_PULL_BANNER in text


def mark_thread_pull_replied(
    parent_message_text: str,
    capture_path: Optional[str] = None,
) -> Optional[dict]:
    """When a capture lands on a thread-pull message, append a reply
    record to the thread_pulls log so Sunday's diarizer can see which
    threads have advanced.

    Match strategy: walk the existing log newest-first and find the most
    recent entry whose stored message contains the first ~200 chars of
    `parent_message_text` (or vice versa). The pulled message stored in
    the log is the rendered thread-pull body — we match on substring
    rather than exact equality because Telegram may inject minor
    whitespace differences.

    Returns the matched-and-recorded reply dict on success, None on no match.
    """
    if not parent_message_text or not is_thread_pull_message(parent_message_text):
        return None
    if not os.path.exists(THREAD_PULLS_PATH):
        return None

    # Walk pulls newest-first
    pulls = sorted(
        recent_thread_pulls(within_days=14),
        key=lambda e: e.get("ts", ""),
        reverse=True,
    )
    target_excerpt = parent_message_text.strip()[:200]
    matched: Optional[dict] = None
    for p in pulls:
        # Skip entries that aren't pulls (could be reply records — see below)
        if p.get("kind") == "reply":
            continue
        stored = (p.get("message") or "").strip()
        if not stored:
            continue
        # Either side may contain the other (the stored message may be
        # truncated, or the displayed message may be wrapped)
        if target_excerpt[:120] in stored or stored[:120] in target_excerpt:
            matched = p
            break
    if not matched:
        log.debug("mark_thread_pull_replied: no matching pull found")
        return None

    reply_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "reply",
        "thread_summary": (matched.get("thread_summary") or "")[:400],
        "pull_ts": matched.get("ts"),
        "capture_path": capture_path or "",
    }
    try:
        from myalicia.skills.conversations import tag as _tag_conv
        _tag_conv(reply_entry)
    except Exception:
        pass
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(THREAD_PULLS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(reply_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"mark_thread_pull_replied: write failed: {e}")
        return None
    return reply_entry


def recent_thread_pull_replies(within_days: int = 7) -> list[dict]:
    """Return reply records (kind='reply') newer than `within_days`."""
    if not os.path.exists(THREAD_PULLS_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(THREAD_PULLS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("kind") != "reply":
                    continue
                try:
                    ts = datetime.fromisoformat(e.get("ts", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts >= cutoff:
                    out.append(e)
    except Exception as e:
        log.debug(f"recent_thread_pull_replies failed: {e}")
    return out


def advanced_threads(within_days: int = 7) -> list[dict]:
    """Return threads that received a reply in the window, grouped by
    thread_summary. Each entry is {thread_summary, reply_count,
    latest_reply_at, capture_paths}. Useful for person_diarization to
    reflect 'these threads moved this week' in the next profile."""
    replies = recent_thread_pull_replies(within_days=within_days)
    by_thread: dict[str, dict] = {}
    for r in replies:
        ts = r.get("thread_summary") or ""
        if not ts:
            continue
        slot = by_thread.setdefault(ts, {
            "thread_summary": ts, "reply_count": 0,
            "latest_reply_at": "", "capture_paths": [],
        })
        slot["reply_count"] += 1
        cur_latest = slot["latest_reply_at"]
        if not cur_latest or (r.get("ts") or "") > cur_latest:
            slot["latest_reply_at"] = r.get("ts") or ""
        cp = r.get("capture_path") or ""
        if cp:
            slot["capture_paths"].append(cp)
    return sorted(
        by_thread.values(),
        key=lambda d: (-d["reply_count"], d["thread_summary"]),
    )


def _similarity_overlap(a: str, b: str) -> float:
    """Cheap token-overlap similarity in [0,1]. Used to detect repeats."""
    if not a or not b:
        return 0.0
    ta = set(re.findall(r"[a-zA-Z]{4,}", a.lower()))
    tb = set(re.findall(r"[a-zA-Z]{4,}", b.lower()))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(1, min(len(ta), len(tb)))


def pick_thread(
    threads: list[dict],
    recent_pulls: list[dict],
    *,
    similarity_threshold: float = 0.45,
) -> Optional[dict]:
    """Pick a thread that hasn't been pulled recently.

    Strategy:
      1. Filter out any thread whose summary overlaps a recent pull
         above `similarity_threshold` (default 0.45 — generous but not
         loose).
      2. From the remainder, weight earlier-listed threads slightly
         higher (the diarizer puts the strongest first).
      3. Random-weighted choice so the user doesn't see the same opener
         twice in a row even when no pull history exists.
    """
    if not threads:
        return None
    eligible: list[tuple[dict, float]] = []
    for idx, t in enumerate(threads):
        summary = t.get("summary", "")
        if not summary:
            continue
        too_similar = any(
            _similarity_overlap(summary, p.get("thread_summary", "")) >= similarity_threshold
            for p in recent_pulls
        )
        if too_similar:
            continue
        # Earlier threads get higher weight (1.0, 0.85, 0.72, …).
        weight = 0.85 ** idx
        eligible.append((t, weight))
    if not eligible:
        return None
    threads_only = [t for t, _ in eligible]
    weights = [w for _, w in eligible]
    return random.choices(threads_only, weights=weights, k=1)[0]


# ── Render via Haiku ───────────────────────────────────────────────────────


_THREAD_PULL_SYSTEM = (
    "You are Alicia, a sovereign AI agent in long-term partnership with "
    f"{USER_NAME}. You're sending him a mid-week message that picks up an "
    "unresolved thread from the weekly profile you wrote about him on "
    "Sunday. Your tone is intimate, present, and curious — not formal. "
    "You don't need to introduce yourself or explain the source.\n\n"
    "Write 2-4 short lines (30-80 words total). Open with a single line "
    "that names the thread in your own words; follow with a question or "
    "an offered angle. No headers, no labels, no markdown beyond a single "
    "italic phrase if it lands. End on the question — do not summarise."
)


def _render_thread_pull(thread_summary: str) -> Optional[str]:
    """Ask Haiku to write a 2-4 line continuation message for this thread.

    Returns the rendered message string, or None on failure."""
    if not thread_summary:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        user_prompt = (
            "Open thread from this week's profile:\n\n"
            f"\"{thread_summary.strip()}\"\n\n"
            "Write the mid-week thread-pull message."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_THREAD_PULL_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = ""
        if resp.content and hasattr(resp.content[0], "text"):
            raw = (resp.content[0].text or "").strip()
        # Strip wrapping quotes if Haiku quoted the whole thing.
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1].strip()
        return raw or None
    except Exception as e:
        log.warning(f"_render_thread_pull failed: {e}")
        return None


# ── Main entry point ──────────────────────────────────────────────────────


def build_thread_pull_message() -> Optional[str]:
    """Top-level: build a thread-pull message ready to send, or None.

    Returns None if any precondition is missing — the caller should fall
    through to the regular midday rotation. Side effect: on success,
    appends to thread_pulls.jsonl so the same thread isn't picked again
    within PULL_COOLDOWN_DAYS.
    """
    profile_path = _latest_hector_profile()
    if not profile_path:
        log.debug("build_thread_pull_message: no hector profile")
        return None
    try:
        profile_text = Path(profile_path).read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"build_thread_pull_message: read failed: {e}")
        return None

    threads = parse_open_threads(profile_text)
    if not threads:
        log.debug("build_thread_pull_message: no open threads parseable")
        return None

    recent = recent_thread_pulls(within_days=PULL_COOLDOWN_DAYS)
    chosen = pick_thread(threads, recent)
    if not chosen:
        log.debug("build_thread_pull_message: all threads recently pulled")
        return None

    rendered = _render_thread_pull(chosen["summary"])
    if not rendered:
        return None

    # Lightweight banner so the format is identifiable in the chat scroll.
    message = f"🧵 _picking up a thread from Sunday_\n\n{rendered}"
    record_thread_pull(chosen["summary"], message)
    return message


if __name__ == "__main__":
    out = build_thread_pull_message()
    print(out or "(no thread-pull message produced)")
