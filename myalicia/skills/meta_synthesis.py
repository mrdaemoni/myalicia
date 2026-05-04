#!/usr/bin/env python3
"""
Synthesis-of-syntheses outer loop — Phase 13.6.

When a single synthesis accumulates enough the user captures (responses or
unprompted reflections that reference it), the conversation around that
idea has become substantial enough to deserve its own distillation.
This module triggers a meta-synthesis pass: take the original synthesis
+ all of the user's captured responses on it, and ask Sonnet to compose a
new synthesis note that incorporates the user's lived response into the
conceptual frame.

The output is a brand-new synthesis file in the Wisdom/Synthesis/ folder
with frontmatter pointing back to its parent. It joins the regular
ecosystem — discoverable by surfacings, the contradiction detector, and
future passes — but visibly marked as a child of lived dialogue.

Design choices:
  * Trigger threshold: 3 captures on the same synthesis. Tunable via
    MIN_CAPTURES_FOR_META.
  * Cooldown: a parent synthesis won't be re-meta'd within
    META_COOLDOWN_DAYS (default 14d), AND not until at least
    MIN_NEW_CAPTURES_AFTER_META more captures land.
  * One meta-synthesis per nightly pass. Heavy operation — Sonnet call
    over multi-thousand-token context.

Public API:
    candidates_for_meta_synthesis() -> list[dict]
    build_meta_synthesis(parent_title) -> Optional[Path]
    run_meta_synthesis_pass() -> dict   # scheduler entry
    has_recent_meta(parent_title, within_days=14) -> bool
    record_meta_synthesis(parent_title, child_title, child_path, capture_count)
    recent_meta_syntheses(within_days=30) -> list[dict]

Storage:
    ~/alicia/memory/meta_synthesis_log.jsonl
    Wisdom/Synthesis/<child-title>.md  (with parent_synthesis frontmatter)
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
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.meta_synthesis")

VAULT_ROOT = Path(str(config.vault.root))
SYNTHESIS_DIR = VAULT_ROOT / "Alicia" / "Wisdom" / "Synthesis"
MEMORY_DIR = str(MEMORY_DIR)
META_LOG_PATH = os.path.join(MEMORY_DIR, "meta_synthesis_log.jsonl")

# Tunables
MIN_CAPTURES_FOR_META = 3
META_COOLDOWN_DAYS = 14
MIN_NEW_CAPTURES_AFTER_META = 3
MAX_PER_PASS = 1

# Phase 13.10 — recursion cap. Meta-syntheses can themselves accumulate
# captures and become parents of meta-meta-syntheses. We allow this so the
# vault's altitude can rise, but cap at MAX_META_LEVEL to prevent runaway
# recursion. Level 1 = first meta (parent is a regular synthesis).
# Level 2 = meta-meta. Level 3 = meta-meta-meta. Above that, returns None.
MAX_META_LEVEL = 3


# ── Synthesis file lookup ─────────────────────────────────────────────────


def _slugify_title_for_lookup(title: str) -> str:
    """Normalize a title for filename matching (case-fold, strip punctuation)."""
    t = title.strip().lower()
    t = re.sub(r"[^\w\s-]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def find_synthesis_path(title: str) -> Optional[Path]:
    """Locate a synthesis .md file by exact or normalized title match.

    First tries `<title>.md` directly. Falls back to scanning all .md files
    in SYNTHESIS_DIR and matching on slugified title (case-insensitive,
    punctuation-insensitive)."""
    if not title or not SYNTHESIS_DIR.is_dir():
        return None
    direct = SYNTHESIS_DIR / f"{title.strip()}.md"
    if direct.exists():
        return direct
    target = _slugify_title_for_lookup(title)
    if not target:
        return None
    for f in SYNTHESIS_DIR.glob("*.md"):
        if _slugify_title_for_lookup(f.stem) == target:
            return f
    return None


def read_synthesis(path: Path) -> str:
    """Read a synthesis file. Returns empty string on error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        log.debug(f"read_synthesis({path}) failed: {e}")
        return ""


def get_synthesis_level(text: str) -> int:
    """Phase 13.10 — read the meta-synthesis level from frontmatter.

    Returns 0 for plain syntheses (no frontmatter or no `level` field),
    or the integer level for meta-syntheses written by this module:
      level 1 = first meta (parent is plain)
      level 2 = meta-meta (parent is level 1)
      level 3 = meta-meta-meta (parent is level 2)

    Level reads from the YAML frontmatter `level:` field. Falls back to
    detecting `kind: meta_synthesis` (treated as level 1) when no
    explicit level is present (back-compat with pre-13.10 metas).
    """
    if not text:
        return 0
    # Match the leading `---\n...---\n` frontmatter block
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return 0
    fm_block = m.group(1)
    # Look for explicit level field
    lm = re.search(r"^\s*level\s*:\s*(\d+)\s*$", fm_block, re.MULTILINE)
    if lm:
        try:
            return int(lm.group(1))
        except Exception:
            pass
    # Fallback: detect kind: meta_synthesis (pre-13.10 → level 1)
    if re.search(r"^\s*kind\s*:\s*meta_synthesis\s*$", fm_block, re.MULTILINE):
        return 1
    return 0


# ── Meta-synthesis log (cooldown + dedup) ──────────────────────────────────


def record_meta_synthesis(
    parent_title: str, child_title: str, child_path: str, capture_count: int
) -> None:
    """Append a meta-synthesis event to the jsonl log."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "parent_title": parent_title[:300],
            "child_title": child_title[:300],
            "child_path": child_path,
            "captures_at_build": int(capture_count),
        }
        # Phase 16.0 — conversation tag (default for now)
        try:
            from myalicia.skills.conversations import tag as _tag_conv
            _tag_conv(entry)
        except Exception:
            pass
        with open(META_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"record_meta_synthesis failed: {e}")


def recent_meta_syntheses(within_days: int = 30) -> list[dict]:
    """Return meta-synthesis log entries newer than `within_days`."""
    if not os.path.exists(META_LOG_PATH):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[dict] = []
    try:
        with open(META_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
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
        log.debug(f"recent_meta_syntheses failed: {e}")
    return out


def has_recent_meta(parent_title: str, within_days: int = META_COOLDOWN_DAYS) -> dict | None:
    """Return the most recent log entry for this parent within `within_days`,
    or None if no such recent meta-synthesis exists."""
    if not parent_title:
        return None
    target = parent_title.strip()
    for entry in recent_meta_syntheses(within_days=within_days):
        if entry.get("parent_title", "").strip() == target:
            return entry
    return None


# ── Candidate selection ──────────────────────────────────────────────────


def candidates_for_meta_synthesis(
    *, min_captures: int = MIN_CAPTURES_FOR_META,
) -> list[dict]:
    """Return a ranked list of synthesis titles eligible for meta-synthesis.

    A title is eligible iff:
      - It has >= min_captures captures referencing it, AND
      - Either no meta exists yet within META_COOLDOWN_DAYS, OR the
        capture count has grown by >= MIN_NEW_CAPTURES_AFTER_META since
        the last meta was built.

    Returns: [{"title", "capture_count", "last_meta_at", "last_meta_count",
               "delta", "synthesis_path"}, ...]
    Ranked by `delta` descending (largest growth since last meta first).
    """
    try:
        from myalicia.skills.response_capture import most_responded_syntheses
    except Exception as e:
        log.debug(f"candidates_for_meta_synthesis: import failed: {e}")
        return []

    # Pull a generous window — most_responded_syntheses returns top-N, so
    # ask for many to find anything past the threshold.
    try:
        ranked = most_responded_syntheses(n=50)
    except Exception as e:
        log.debug(f"most_responded_syntheses failed: {e}")
        return []

    out: list[dict] = []
    for title, n in ranked:
        if n < min_captures:
            continue
        # Must locate the synthesis on disk to be buildable
        path = find_synthesis_path(title)
        if not path:
            log.debug(f"candidates: title not found on disk: {title!r}")
            continue
        recent = has_recent_meta(title, within_days=META_COOLDOWN_DAYS)
        if recent:
            prior_n = int(recent.get("captures_at_build", 0))
            delta = n - prior_n
            if delta < MIN_NEW_CAPTURES_AFTER_META:
                # On cooldown AND not enough new captures
                continue
            out.append({
                "title": title,
                "capture_count": n,
                "last_meta_at": recent.get("ts"),
                "last_meta_count": prior_n,
                "delta": delta,
                "synthesis_path": str(path),
            })
        else:
            out.append({
                "title": title,
                "capture_count": n,
                "last_meta_at": None,
                "last_meta_count": 0,
                "delta": n,
                "synthesis_path": str(path),
            })
    # Sort: largest delta first; tie-break on capture_count
    out.sort(key=lambda c: (-c["delta"], -c["capture_count"]))
    return out


# ── Sonnet composer ──────────────────────────────────────────────────────


_META_SYSTEM = (
    f"You are Alicia, distilling a meta-synthesis. The user, {USER_NAME}, "
    "has been writing back to a single synthesis note across multiple "
    "responses. His captured replies have accumulated enough that the "
    "conversation around the idea has crossed a threshold — it's no "
    "longer a single claim, it's a living thread. Your job: weave his "
    "responses INTO the original frame to produce a new synthesis note "
    "that reads as 'what this idea has become through being lived'.\n\n"
    "FORMAT — produce a complete markdown synthesis note in EXACTLY this shape:\n"
    f"# <title — a single line, ~10-18 words, in {USER_NAME}'s epigrammatic "
    "synthesis voice (claim-as-title, not a description)>\n\n"
    "<one-paragraph opening: what the original synthesis claimed AND "
    f"what {USER_NAME}'s responses have done to it. ~120-180 words.>\n\n"
    f"## How {USER_NAME} Has Lived This\n\n"
    "<2-4 short paragraphs that quote or paraphrase his captured "
    "responses (using > blockquote for direct quotes when fitting) and "
    "show what each one did to the original idea — extended it, "
    "complicated it, embodied it, or contradicted it.>\n\n"
    "## What This Idea Has Become\n\n"
    "<one paragraph: the meta-synthesis. The new claim that emerges "
    f"when the original is read THROUGH {USER_NAME}'s responses. ~120-180 "
    "words. End on the strongest single sentence.>\n\n"
    "---\n\n"
    "*Wisdom themes:* <2-4 #theme/X tags inherited or adapted>\n"
    "*Built from:* [[<exact original title>]]\n\n"
    f"TONE: {USER_NAME}'s voice. Aphoristic, claim-bearing, no scaffolding "
    "words like 'overall' or 'in conclusion'. Don't introduce yourself."
)


def _build_user_prompt(
    parent_title: str,
    parent_text: str,
    captures: list[dict],
) -> str:
    """Assemble the user-message body for the meta-synthesis call."""
    parts: list[str] = []
    parts.append(f"# Parent synthesis: {parent_title}\n")
    # Cap parent text to keep context bounded — most syntheses are <2000 words
    parent_excerpt = parent_text.strip()
    if len(parent_excerpt) > 6000:
        parent_excerpt = parent_excerpt[:5999].rstrip() + "…"
    parts.append(parent_excerpt)
    parts.append(f"\n\n# {USER_NAME}'s captured responses on this idea:\n")
    for i, cap in enumerate(captures, 1):
        ts = cap.get("captured_at", "")
        chan = cap.get("channel", "text")
        excerpt = cap.get("body_excerpt", "").strip()
        # Try the full body if available — pull from path
        try:
            full = Path(cap["path"]).read_text(encoding="utf-8")
            # Strip frontmatter
            full = re.sub(r"^---\n.*?\n---\n", "", full, count=1, flags=re.DOTALL).strip()
            # Cap each at 1500 chars
            if len(full) > 1500:
                full = full[:1499].rstrip() + "…"
            body = full
        except Exception:
            body = excerpt
        parts.append(
            f"\n## Response {i} — {ts} ({chan})\n\n{body}"
        )
    parts.append(
        "\n\n---\n\nNow write the meta-synthesis as instructed."
    )
    return "\n".join(parts)


def _sanitize_title_for_filename(title: str) -> str:
    """Strip line-1 of generated text down to a filesystem-safe filename."""
    t = title.strip()
    if t.startswith("# "):
        t = t[2:].strip()
    # Drop trailing punctuation that hurts filenames
    t = t.rstrip(".:;,")
    # Replace forbidden chars with " — " or strip
    t = re.sub(r'[\\/:"*?<>|]', "—", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Cap length to keep paths sane
    if len(t) > 180:
        t = t[:180].rstrip() + "…"
    return t


def _compose_meta_synthesis(
    parent_title: str, parent_text: str, captures: list[dict]
) -> Optional[str]:
    """Call Sonnet to produce the full markdown of the meta-synthesis.

    Returns the rendered markdown, or None on failure."""
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        user_prompt = _build_user_prompt(parent_title, parent_text, captures)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2400,
            system=_META_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return None
        out = (resp.content[0].text or "").strip()
        return out or None
    except Exception as e:
        log.warning(f"_compose_meta_synthesis failed: {e}")
        return None


def _attach_frontmatter(
    body_md: str,
    *,
    parent_title: str,
    parent_path: Path,
    capture_count: int,
    level: int = 1,
) -> str:
    """Prepend YAML frontmatter that marks this as a meta-synthesis.

    Phase 13.10 — `level` is the recursion depth: 1 = first meta, 2 = meta-meta,
    3 = meta-meta-meta. `kind` reflects the level: meta_synthesis | meta_meta_synthesis |
    meta_meta_meta_synthesis. The `level:` integer is the canonical field that
    get_synthesis_level reads on subsequent passes.
    """
    if level == 1:
        kind = "meta_synthesis"
    elif level == 2:
        kind = "meta_meta_synthesis"
    elif level == 3:
        kind = "meta_meta_meta_synthesis"
    else:
        kind = f"meta_x{level}_synthesis"  # defensive — shouldn't reach
    fm = (
        "---\n"
        f"kind: {kind}\n"
        f"level: {level}\n"
        f"parent_synthesis: \"{parent_title.replace(chr(34), chr(39))}\"\n"
        f"parent_path: \"{parent_path.name}\"\n"
        f"captures_at_build: {capture_count}\n"
        f"built_at: {datetime.now(timezone.utc).isoformat()}\n"
        "built_by: alicia.meta_synthesis\n"
        "---\n\n"
    )
    return fm + body_md.lstrip()


# ── Phase 13.9 — Cross-loop bridge to the user-model ─────────────────────


_BRIDGE_SYSTEM = (
    "You are Alicia, reading a meta-synthesis you just composed about "
    f"{USER_NAME}. Your job: extract 1-3 specific facts ABOUT HECTOR (not "
    "about the idea) that this meta-synthesis revealed. These facts "
    f"feed his ongoing {USER_NAME}-model — an append-only log of who he's "
    "becoming.\n\n"
    "FORMAT — reply with EXACTLY one JSON line:\n"
    "{\"learnings\": [{\"dimension\": \"<one of: identity, knowledge, "
    "practice, relationships, work, voice, body, wealth, creative, "
    "shadow>\", \"claim\": \"<one specific sentence ABOUT HECTOR>\", "
    "\"confidence\": <0.5-0.95 float>}]}\n\n"
    "RULES:\n"
    f"- Each claim must be about {USER_NAME} specifically, not a general "
    f"principle. '{USER_NAME} returns to McGilchrist when he wants to think "
    "about hemispheric balance' YES. 'McGilchrist describes hemispheric "
    "balance' NO.\n"
    "- Bias toward fewer, more specific learnings. Empty list "
    "(\"learnings\": []) is valid when nothing about HECTOR (vs. the "
    "idea itself) is revealed.\n"
    "- Confidence reflects how much the meta-synthesis text supports "
    "the claim. 0.6 = inferred. 0.85 = stated."
)


def _extract_learnings_from_meta(body: str, parent_title: str) -> list[dict]:
    """Sonnet call to pull dimension-tagged learnings from meta text.

    Returns a list of {dimension, claim, confidence} dicts. Empty list
    on any error or when the model returns an empty list. Keeps the
    bridge fail-soft — the meta-synthesis is already written before
    this runs.
    """
    if not body:
        return []
    try:
        from anthropic import Anthropic
        client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=2,
        )
        body_excerpt = body.strip()
        if len(body_excerpt) > 4000:
            body_excerpt = body_excerpt[:3999].rstrip() + "…"
        user_prompt = (
            f"# Meta-synthesis just built (parent: {parent_title})\n\n"
            f"{body_excerpt}\n\n"
            "Extract the JSON line."
        )
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=_BRIDGE_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not resp.content or not hasattr(resp.content[0], "text"):
            return []
        raw = (resp.content[0].text or "").strip()
        # Best-effort JSON extraction
        import re as _re
        m = _re.search(r"\{[\s\S]*?\"learnings\"[\s\S]*\}", raw)
        if not m:
            log.debug(f"_extract_learnings_from_meta: no JSON in: {raw[:120]}")
            return []
        try:
            parsed = json.loads(m.group(0))
        except Exception as je:
            log.debug(f"_extract_learnings_from_meta: bad JSON ({je}): {raw[:120]}")
            return []
        learnings = parsed.get("learnings") or []
        if not isinstance(learnings, list):
            return []
        # Light validation — drop malformed entries silently
        out: list[dict] = []
        for item in learnings:
            if not isinstance(item, dict):
                continue
            dim = (item.get("dimension") or "").strip().lower()
            claim = (item.get("claim") or "").strip()
            try:
                conf = float(item.get("confidence", 0.7))
            except Exception:
                conf = 0.7
            if dim and claim:
                out.append({
                    "dimension": dim,
                    "claim": claim[:600],
                    "confidence": max(0.0, min(1.0, conf)),
                })
        return out
    except Exception as e:
        log.warning(f"_extract_learnings_from_meta failed: {e}")
        return []


def bridge_meta_to_hector_model(
    *, body: str, parent_title: str, child_title: str,
) -> int:
    """Bridge the new meta-synthesis to the the user-model.

    1. Sonnet extracts up to 3 dimension-tagged learnings from `body`.
    2. Each learning is appended to user_learnings.jsonl with source
       set to 'meta_synthesis:<parent_title>' so /becoming can show
       provenance.

    Returns the count of learnings actually appended (0 on any error or
    empty extraction). Caller should treat any positive return as
    informational — the meta-synthesis itself is the primary artifact."""
    if not body:
        return 0
    try:
        from myalicia.skills.user_model import (
            append_learning as _hm_append_learning,
            DIMENSIONS as HM_DIMENSIONS,
        )
    except Exception as e:
        log.debug(f"bridge_meta_to_hector_model: user_model import failed: {e}")
        return 0

    learnings = _extract_learnings_from_meta(body, parent_title)
    if not learnings:
        return 0

    n = 0
    src = f"meta_synthesis:{parent_title[:200]}"
    for L in learnings:
        dim = L["dimension"]
        if dim not in HM_DIMENSIONS:
            log.debug(f"bridge: unknown dimension {dim!r}, skipping")
            continue
        try:
            _hm_append_learning(
                claim=L["claim"],
                dimension=dim,
                confidence=L["confidence"],
                source=src,
                evidence=child_title[:200],
            )
            n += 1
        except Exception as ae:
            log.debug(f"bridge append_learning failed for dim={dim!r}: {ae}")
    return n


# ── Main builder ─────────────────────────────────────────────────────────


def build_meta_synthesis(parent_title: str) -> Optional[Path]:
    """End-to-end: locate parent + captures, compose meta, write file, log.

    Returns the Path to the new synthesis file on success, or None.
    Caller is responsible for any user-facing notification."""
    if not parent_title:
        return None
    try:
        from myalicia.skills.response_capture import get_responses_for_synthesis
    except Exception as e:
        log.warning(f"build_meta_synthesis: import failed: {e}")
        return None

    parent_path = find_synthesis_path(parent_title)
    if not parent_path:
        log.warning(f"build_meta_synthesis: parent not found: {parent_title!r}")
        return None
    parent_text = read_synthesis(parent_path)
    if not parent_text:
        log.warning(f"build_meta_synthesis: parent unreadable: {parent_path}")
        return None

    # Phase 13.10 — recursion guard. Compute the new level (parent level + 1)
    # and refuse to build above MAX_META_LEVEL. Plain syntheses (no meta
    # frontmatter) report level 0, so the first meta gets level 1.
    parent_level = get_synthesis_level(parent_text)
    new_level = parent_level + 1
    if new_level > MAX_META_LEVEL:
        log.info(
            f"build_meta_synthesis: refusing to build level {new_level} "
            f"meta (cap {MAX_META_LEVEL}) for {parent_title!r}"
        )
        return None

    # Pull ALL captures for this parent — meta-synthesis needs the full
    # arc, not just the most-recent N.
    captures = get_responses_for_synthesis(parent_title, max_recent=999)
    if len(captures) < MIN_CAPTURES_FOR_META:
        log.info(
            f"build_meta_synthesis: not enough captures yet "
            f"({len(captures)}/{MIN_CAPTURES_FOR_META}) for {parent_title!r}"
        )
        return None

    body = _compose_meta_synthesis(parent_title, parent_text, captures)
    if not body:
        return None

    # Extract the title line and use it as the filename.
    first_line = body.split("\n", 1)[0]
    child_title = _sanitize_title_for_filename(first_line)
    if not child_title:
        log.warning(f"build_meta_synthesis: empty child title from output")
        return None

    full_md = _attach_frontmatter(
        body,
        parent_title=parent_title,
        parent_path=parent_path,
        capture_count=len(captures),
        level=new_level,
    )

    try:
        SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)
        child_path = SYNTHESIS_DIR / f"{child_title}.md"
        # Avoid clobber: if file exists, append a short suffix
        if child_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            child_path = SYNTHESIS_DIR / f"{child_title} ({stamp}).md"
        child_path.write_text(full_md, encoding="utf-8")
    except Exception as e:
        log.error(f"build_meta_synthesis: write failed: {e}")
        return None

    record_meta_synthesis(
        parent_title=parent_title,
        child_title=child_title,
        child_path=str(child_path),
        capture_count=len(captures),
    )
    log.info(
        f"meta_synthesis built: parent={parent_title!r} "
        f"child={child_title!r} captures={len(captures)}"
    )

    # Phase 13.9 — Cross-loop bridge: extract dimension-tagged learnings
    # from the new meta-synthesis text and append them to the the user-model.
    # The meta-synthesis already distilled the conversation; another small
    # Sonnet call surfaces the parts of that distillation that are facts
    # ABOUT the user (not facts about the idea). Each extraction lands in
    # user_learnings.jsonl with source="meta_synthesis:<parent>" so the
    # provenance is traceable in /becoming.
    try:
        n_bridged = bridge_meta_to_hector_model(
            body=body,
            parent_title=parent_title,
            child_title=child_title,
        )
        if n_bridged:
            log.info(
                f"meta_synthesis bridge: appended {n_bridged} learning(s) "
                f"to {USER_NAME}-model from {child_title!r}"
            )
    except Exception as e:
        log.debug(f"meta_synthesis bridge skip: {e}")

    return child_path


# ── Scheduler entry point ────────────────────────────────────────────────


def run_meta_synthesis_pass() -> dict:
    """Scheduled nightly: pick the top candidate (largest growth since last
    meta) and build one meta-synthesis if any are eligible.

    Returns a result dict with keys:
        {"built": bool, "candidate": str|None, "child_path": str|None,
         "candidate_count": int, "reason": str}
    """
    candidates = candidates_for_meta_synthesis()
    if not candidates:
        return {
            "built": False, "candidate": None, "child_path": None,
            "candidate_count": 0, "reason": "no_eligible_candidates",
        }
    # Build only MAX_PER_PASS (default 1) to stay polite on Sonnet quota.
    built_paths: list[str] = []
    last_candidate = None
    for c in candidates[:MAX_PER_PASS]:
        last_candidate = c["title"]
        path = build_meta_synthesis(c["title"])
        if path:
            built_paths.append(str(path))
    if built_paths:
        return {
            "built": True,
            "candidate": last_candidate,
            "child_path": built_paths[-1],
            "candidate_count": len(candidates),
            "reason": "ok",
        }
    return {
        "built": False, "candidate": last_candidate, "child_path": None,
        "candidate_count": len(candidates), "reason": "compose_or_write_failed",
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(run_meta_synthesis_pass(), indent=2))
