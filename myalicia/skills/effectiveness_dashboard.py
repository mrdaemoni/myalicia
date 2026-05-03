#!/usr/bin/env python3
"""
Feedback-signal dashboard — `/effectiveness` Telegram command.

Sibling to /wisdom (which shows what the system DID — circulation,
captures, surfacings). /effectiveness shows how it LANDED — feedback
signals from the user and from the system's own classifiers.

Sections:
  1. Reactions last 7 days (emoji tally from reaction_log.tsv)
  2. Archetype effectiveness EMA (top scores from
     archetype_effectiveness.json)
  3. Voice tone tags last 7 days (prosody tags from
     voice_metadata_log.jsonl)
  4. Emotion classifications last 7 days (label distribution from
     emotion_log.jsonl)
  5. Proactive engagement rate — NEW metric (Phase 11.7+):
     of the last N composer-driven sends, what fraction got a the user
     reply within 30 min? Computed by joining circulation_log.json
     against writing/Responses/ frontmatter.

Built read-only from data already on disk. Each section is independently
fault-tolerant — a layer that errors is replaced with a one-line note
and the rest still render.

Public API:
    render_effectiveness_dashboard(now=None) -> str
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger("alicia.effectiveness_dashboard")

VAULT_ROOT = Path(str(config.vault.root))
MEMORY_DIR = Path(os.environ.get(
    "ALICIA_MEMORY_DIR", os.path.expanduser("~/alicia/memory")
))
REACTION_LOG = MEMORY_DIR / "reaction_log.tsv"
ARCHETYPE_EFFECTIVENESS = MEMORY_DIR / "archetype_effectiveness.json"
VOICE_METADATA_LOG = MEMORY_DIR / "voice_metadata_log.jsonl"
EMOTION_LOG = MEMORY_DIR / "emotion_log.jsonl"
CIRCULATION_LOG_FILE = MEMORY_DIR / "circulation_log.json"
RESPONSES_DIR = VAULT_ROOT / "writing" / "Responses"
# Phase 12.5 — proactive engagement TSV (record_proactive_sent → record_prompted_response)
PROMPT_EFFECTIVENESS_TSV = MEMORY_DIR / "prompt_effectiveness.tsv"


# ── Section renderers ──────────────────────────────────────────────────────


# Map raw reaction emojis to a coarse positive/negative/neutral split so the
# tally reads at a glance.
_POSITIVE_EMOJIS = {"❤", "❤️", "👍", "🔥", "🤩", "😍", "🥰"}
_NEGATIVE_EMOJIS = {"👎", "😕", "🤨", "😢", "😞"}


def _render_reactions_section(now_utc: datetime, *, days: int = 7) -> str:
    """Reaction tally last `days` days, plus a positive/negative split."""
    if not REACTION_LOG.exists():
        return f"*Reactions (last {days}d):* (no log yet)"
    cutoff = now_utc - timedelta(days=days)
    counter: Counter = Counter()
    pos = neg = neu = 0
    try:
        with REACTION_LOG.open(encoding="utf-8") as f:
            f.readline()  # skip header
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 4:
                    continue
                ts_str, _, _, emoji = cols[0], cols[1], cols[2], cols[3]
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M") \
                        .replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                counter[emoji] += 1
                if emoji in _POSITIVE_EMOJIS:
                    pos += 1
                elif emoji in _NEGATIVE_EMOJIS:
                    neg += 1
                else:
                    neu += 1
    except Exception as e:
        return f"*Reactions:* (read error: {e})"
    if not counter:
        return f"*Reactions (last {days}d):* none"
    top = " ".join(f"{e}×{n}" for e, n in counter.most_common(6))
    return (
        f"*Reactions (last {days}d):*\n"
        f"  {top}\n"
        f"  +{pos} positive · −{neg} negative · ={neu} neutral"
    )


def _render_archetype_ema_section(*, n: int = 6) -> str:
    """Top archetype effectiveness EMA scores."""
    if not ARCHETYPE_EFFECTIVENESS.exists():
        return "*Archetype EMA:* (not yet computed)"
    try:
        data = json.loads(ARCHETYPE_EFFECTIVENESS.read_text(encoding="utf-8"))
    except Exception as e:
        return f"*Archetype EMA:* (read error: {e})"
    archs = data.get("archetypes") or {}
    if not archs:
        return "*Archetype EMA:* empty"
    rows = []
    for name, info in archs.items():
        score = info.get("score", 1.0)
        attrs = info.get("attribution_count", 0)
        rows.append((name, score, attrs))
    # Sort by score desc, then attribution count desc
    rows.sort(key=lambda r: (-r[1], -r[2]))
    lines = [f"*Archetype EMA (top {min(n, len(rows))}):*"]
    for name, score, attrs in rows[:n]:
        bar = ""
        if score >= 1.3:
            bar = "🟢"
        elif score >= 1.1:
            bar = "🟡"
        elif score <= 0.85:
            bar = "🔻"
        else:
            bar = " ·"
        lines.append(f"  {bar} {name:<10} {score:.2f}  (n={attrs})")
    return "\n".join(lines)


def _render_voice_tone_section(now_utc: datetime, *, days: int = 7) -> str:
    """Distribution of prosody tags from voice_metadata_log over last N days."""
    if not VOICE_METADATA_LOG.exists():
        return f"*Voice tone (last {days}d):* (no log)"
    cutoff = now_utc - timedelta(days=days)
    tags: Counter = Counter()
    total = 0
    try:
        with VOICE_METADATA_LOG.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts_str = entry.get("timestamp") or ""
                try:
                    # Voice log uses Z suffix
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                total += 1
                for t in entry.get("tags") or []:
                    tags[t] += 1
    except Exception as e:
        return f"*Voice tone:* (read error: {e})"
    if not total:
        return f"*Voice tone (last {days}d):* no voice messages"
    top = " ".join(f"{t}×{n}" for t, n in tags.most_common(5))
    return f"*Voice tone (last {days}d, n={total}):* {top or '(no tags)'}"


def _render_emotion_section(now_utc: datetime, *, days: int = 7) -> str:
    """Emotion-class distribution from the wav2vec2 classifier."""
    if not EMOTION_LOG.exists():
        return f"*Emotion (last {days}d):* (no log)"
    cutoff = now_utc - timedelta(days=days)
    labels: Counter = Counter()
    total = 0
    try:
        with EMOTION_LOG.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts_str = entry.get("timestamp") or ""
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                label = entry.get("emotion_label") or "?"
                labels[label] += 1
                total += 1
    except Exception as e:
        return f"*Emotion:* (read error: {e})"
    if not total:
        return f"*Emotion (last {days}d):* no voice classifications"
    top = " ".join(f"{l}×{n}" for l, n in labels.most_common(4))
    return f"*Emotion (last {days}d, n={total}):* {top}"


def _render_meta_synthesis_quality_section() -> str:
    """Phase 13.15 — engagement on meta-syntheses vs plain syntheses.

    Aggregates capture counts by synthesis recursion level so we can see
    if meta-syntheses (higher-altitude distillations) land deeper than
    plain syntheses. If yes, the Phase 13.13 surfacing bonus is justified.
    If no, it may be misaligned.

    Reads:
      - most_responded_syntheses for per-title capture counts
      - meta_synthesis.find_synthesis_path + get_synthesis_level for level
    """
    try:
        from myalicia.skills.response_capture import most_responded_syntheses
        from myalicia.skills.meta_synthesis import (
            find_synthesis_path, read_synthesis, get_synthesis_level,
        )
    except Exception as e:
        return f"*Meta-synthesis quality:* (import error: {e})"
    try:
        ranked = most_responded_syntheses(n=100)
    except Exception as e:
        return f"*Meta-synthesis quality:* (load error: {e})"
    if not ranked:
        return "*Meta-synthesis quality:* no responded syntheses yet"

    # Bucket: level → (count of syntheses, total captures, top title)
    buckets: dict[int, dict] = {}
    for title, n in ranked:
        try:
            path = find_synthesis_path(title)
            if path is None:
                continue
            level = get_synthesis_level(read_synthesis(path))
        except Exception:
            level = 0
        slot = buckets.setdefault(level, {
            "syntheses": 0, "total_captures": 0, "top_title": "", "top_n": 0,
        })
        slot["syntheses"] += 1
        slot["total_captures"] += n
        if n > slot["top_n"]:
            slot["top_n"] = n
            slot["top_title"] = title

    if not buckets or all(b["syntheses"] == 0 for b in buckets.values()):
        return "*Meta-synthesis quality:* no responded syntheses found on disk"

    lines = ["*Meta-synthesis quality:*"]
    for lvl in sorted(buckets.keys()):
        slot = buckets[lvl]
        if slot["syntheses"] == 0:
            continue
        avg = slot["total_captures"] / slot["syntheses"]
        label = "Plain" if lvl == 0 else f"Level {lvl}"
        # Visual: green if avg > 2.0 captures/synth, yellow > 1.0, red ≤ 1.0
        bar = "🟢" if avg >= 2.0 else "🟡" if avg >= 1.0 else "🔻"
        lines.append(
            f"  {bar} {label}: {slot['syntheses']} syntheses · "
            f"{slot['total_captures']} captures · {avg:.1f} avg"
        )
    # If both plain and meta exist, surface the comparison explicitly
    if 0 in buckets and any(k > 0 for k in buckets.keys()):
        plain_avg = (buckets[0]["total_captures"] / buckets[0]["syntheses"]
                     if buckets[0]["syntheses"] else 0)
        meta_total_caps = sum(
            b["total_captures"] for k, b in buckets.items() if k > 0
        )
        meta_total_synths = sum(
            b["syntheses"] for k, b in buckets.items() if k > 0
        )
        meta_avg = meta_total_caps / meta_total_synths if meta_total_synths else 0
        if meta_avg > 0 and plain_avg > 0:
            ratio = meta_avg / plain_avg
            comparison = (
                f"  _meta vs plain: {ratio:.2f}× — "
                f"{'higher altitude lands deeper' if ratio >= 1.0 else 'plain syntheses landing deeper today'}_"
            )
            lines.append(comparison)
    return "\n".join(lines)


def _render_engagement_by_source_section(
    *, within_days: int = 14,
    conversation_id: Optional[str] = None,
) -> str:
    """Phase 12.5 — engagement rate broken down by message-source kind.

    The existing _render_engagement_rate_section gives the overall
    composer-driven number. This helper reads prompt_effectiveness.tsv
    (written by record_prompted_response on every the user reply within
    4h of a proactive) and groups rows by msg_type so we can see what's
    landing best:
      thread_pull, dimension_question, podcast_followup, synthesis_review,
      morning, midday, evening, ...

    Each row of the TSV is one PROMPTED response — depth (1-5) is set
    from response length + insight score. So the rate isn't 'how many
    sends got a reply' (that's the other section); it's 'of the prompted
    replies that landed, which sources produced the deepest engagement.'

    Phase 16.5 — TSV writes are now tagged with conversation_id (7th
    column). When `conversation_id` is None: whole-vault. Otherwise
    filter to that conversation; rows without the column (pre-16.5)
    are treated as 'default'.
    """
    if not PROMPT_EFFECTIVENESS_TSV.exists():
        return "*By source (depth):* (no prompt_effectiveness.tsv yet)"
    cutoff = datetime.now() - timedelta(days=within_days)
    rows: list[tuple[str, int]] = []  # (msg_type, depth)
    try:
        with open(PROMPT_EFFECTIVENESS_TSV, "r", encoding="utf-8") as f:
            header = f.readline()  # skip header
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6:
                    continue
                ts_str = parts[0]
                msg_type = parts[1]
                try:
                    depth = int(parts[5])
                except (ValueError, IndexError):
                    continue
                # Phase 16.5 — 7th column is conversation_id. Pre-16.5
                # rows have only 6 cols → treat as 'default'.
                row_cid = parts[6] if len(parts) >= 7 else "default"
                if conversation_id is not None and row_cid != conversation_id:
                    continue
                # Lenient timestamp parsing — TSV uses naive local time
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                if msg_type:
                    rows.append((msg_type, depth))
    except Exception as e:
        return f"*By source (depth):* (read error: {e})"
    if not rows:
        return f"*By source (depth):* no replies in last {within_days}d"

    # Group: msg_type -> (count, sum_depth)
    by_type: dict[str, list[int]] = {}
    for mt, d in rows:
        by_type.setdefault(mt, []).append(d)
    # Compute avg depth + count per type, sorted by avg depth desc
    summary = []
    for mt, depths in by_type.items():
        avg = sum(depths) / len(depths)
        summary.append((mt, len(depths), avg))
    summary.sort(key=lambda r: -r[2])

    lines = [f"*By source (depth, last {within_days}d):*"]
    for mt, count, avg in summary[:8]:
        # Visual signal: green if avg ≥ 4.0, yellow ≥ 2.5, else red
        bar = "🟢" if avg >= 4.0 else "🟡" if avg >= 2.5 else "🔻"
        lines.append(f"  {bar} {mt}: {avg:.1f} depth · {count} repl{'y' if count==1 else 'ies'}")
    return "\n".join(lines)


def _render_engagement_rate_section(
    now_utc: datetime, *, last_n_sends: int = 14, window_minutes: int = 30,
) -> str:
    """NEW metric (Phase 11.7+): of the last N composer sends, what
    fraction got a the user reply within `window_minutes` of decision time?

    Reply detection joins circulation_log.json (composer decisions with
    `id`) against writing/Responses/ files (whose frontmatter records
    `proactive_decision_id`). Captures with a `telegram-reply:<id>` prefix
    don't match a circulation_log id and are conservatively excluded.
    """
    if not CIRCULATION_LOG_FILE.exists():
        return f"*Engagement rate:* (no circulation log yet)"
    try:
        log_entries = json.loads(
            CIRCULATION_LOG_FILE.read_text(encoding="utf-8")
        )
    except Exception as e:
        return f"*Engagement rate:* (log read error: {e})"
    sends = [e for e in log_entries if e.get("send")]
    sends = sends[-last_n_sends:]
    if not sends:
        return "*Engagement rate:* (no sends yet)"

    # Build set of decision_ids that have a matching capture
    captured_ids: set[str] = set()
    if RESPONSES_DIR.is_dir():
        try:
            from myalicia.skills.response_capture import parse_capture_file
            for f in RESPONSES_DIR.glob("*.md"):
                meta = parse_capture_file(f)
                if not meta:
                    continue
                pid = meta.get("proactive_decision_id") or ""
                if pid and not pid.startswith("telegram-reply:"):
                    captured_ids.add(pid)
        except Exception as e:
            log.debug(f"engagement: capture parse skip: {e}")

    # Count: of `sends`, how many have id in captured_ids?
    replied = sum(1 for s in sends if s.get("id") in captured_ids)
    n = len(sends)
    pct = (replied / n) * 100 if n else 0.0
    bar = "🟢" if pct >= 50 else "🟡" if pct >= 25 else "🔻"
    return (
        f"*Engagement rate (last {n} sends):*\n"
        f"  {bar} {replied}/{n} replied within window  ({pct:.0f}%)"
    )


# ── Main entry point ────────────────────────────────────────────────────────


def _render_dashboard_engagement_section(
    now_utc: datetime, *, days: int = 14,
) -> str:
    """Phase 17.8 — Per-dashboard engagement.

    Reads reaction_log.tsv filtered to rows with msg_type='dashboard:*'
    (written by alicia.py handle_message_reaction when a reaction lands
    on a dashboard message — both command-driven and tool-driven paths
    via Phase 17.7 / 17.7b). Groups by dashboard name and tallies
    positive/negative/neutral reactions.

    Answers: "which dashboard is landing right now?" and "is anything
    getting 🤔 (puzzled / needs work)?"
    """
    if not REACTION_LOG.exists():
        return f"*Dashboard engagement (last {days}d):* (no log yet)"
    cutoff = now_utc - timedelta(days=days)
    # dashboard_name → Counter(emoji)
    per_dashboard: dict[str, Counter] = {}
    try:
        with REACTION_LOG.open(encoding="utf-8") as f:
            f.readline()  # header
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 4:
                    continue
                ts_str, msg_type, _topic, emoji = (
                    cols[0], cols[1], cols[2], cols[3]
                )
                if not msg_type.startswith("dashboard:"):
                    continue
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M") \
                        .replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                name = msg_type.split(":", 1)[1] or "unknown"
                per_dashboard.setdefault(name, Counter())[emoji] += 1
    except Exception as e:
        return f"*Dashboard engagement:* (read error: {e})"

    if not per_dashboard:
        return (
            f"*Dashboard engagement (last {days}d):* none yet\n"
            f"  _Phase 17.7 wired reactions on every dashboard send. "
            f"This section fills in once {USER_NAME} reacts to one._"
        )

    lines = [f"*Dashboard engagement (last {days}d):*"]
    # Sort by total reactions descending — most-engaged dashboards first
    ranked = sorted(
        per_dashboard.items(),
        key=lambda kv: -sum(kv[1].values()),
    )
    for name, counter in ranked[:8]:
        total = sum(counter.values())
        pos = sum(n for e, n in counter.items() if e in _POSITIVE_EMOJIS)
        neg = sum(n for e, n in counter.items() if e in _NEGATIVE_EMOJIS)
        neu = total - pos - neg
        # Compact emoji rollup — top 4
        top = " ".join(f"{e}×{n}" for e, n in counter.most_common(4))
        lines.append(
            f"  • _{name}_ — {total} ({top})"
            + (f"  +{pos}/−{neg}/={neu}" if total > 0 else "")
        )

    # Phase 17.9 — Puzzlement signal. A dashboard that draws
    # disproportionate 🤔 (or net-negative reactions) is one that's
    # landing badly — the user's reading it but not finding what he
    # needs. Surface it as a "needs work" callout so refinements get
    # prioritised.
    #
    # Two rules:
    #   1. ≥3 reactions AND 🤔 fraction ≥40% → "puzzling"
    #   2. ≥3 reactions AND negative > positive → "net-negative"
    # Threshold of ≥3 prevents a single thumbs-down from flagging a
    # dashboard that has barely been seen.
    PUZZLE_EMOJI = "🤔"
    needs_work: list[tuple[str, str, int, int]] = []  # (name, reason, total, signal_count)
    for name, counter in per_dashboard.items():
        total = sum(counter.values())
        if total < 3:
            continue
        puzzled = counter.get(PUZZLE_EMOJI, 0)
        pos = sum(n for e, n in counter.items() if e in _POSITIVE_EMOJIS)
        neg = sum(n for e, n in counter.items() if e in _NEGATIVE_EMOJIS)
        if puzzled and (puzzled / total) >= 0.4:
            needs_work.append(
                (name, f"{puzzled}/{total} 🤔", total, puzzled)
            )
        elif neg > pos and neg >= 2:
            needs_work.append(
                (name, f"−{neg} > +{pos}", total, neg)
            )
    if needs_work:
        # Rank by signal count descending
        needs_work.sort(key=lambda x: -x[3])
        lines.append("")
        lines.append("*🚧 Needs work* (puzzlement / net-negative):")
        for name, reason, total, _sig in needs_work[:5]:
            lines.append(f"  • _{name}_ — {reason} _(total {total})_")
        lines.append(
            "  _These views aren't landing. Worth refining the render "
            "or rethinking what they answer._"
        )
    return "\n".join(lines)


def _render_mood_of_the_week_section(now_utc: datetime) -> str:
    """Phase 19.0 — the user's emotional weather over the last 7 days.

    Wraps emotion_model.get_mood_of_the_week() into a one-block summary
    on /effectiveness. Surfaces dominant label, distribution, and trend
    so the same signal in the dashboard pill is also legible from
    Telegram."""
    try:
        from myalicia.skills.emotion_model import get_mood_of_the_week
        mood = get_mood_of_the_week(days=7) or {}
    except Exception as e:
        return f"*Mood (last 7d):* (read error: {e})"
    if not mood.get("total_classifications"):
        return (
            "*Mood (last 7d):* no voice notes classified yet\n"
            "  _The 4-class emotion model fills this in as voice notes "
            "land._"
        )
    label = mood.get("dominant_label", "?")
    share = int(mood.get("dominant_share", 0) * 100)
    trend = mood.get("trend", "unknown")
    explain = mood.get("trend_explanation", "")
    total = mood.get("total_classifications", 0)
    dist = mood.get("distribution", {})
    dist_str = " · ".join(
        f"{lab}×{n}"
        for lab, n in sorted(dist.items(), key=lambda kv: -kv[1])
    )
    return (
        f"*Mood (last 7d):* {mood.get('summary_line', '?')}\n"
        f"  {total} voice notes · _{dist_str}_\n"
        f"  _{explain}_" if explain else
        f"*Mood (last 7d):* {mood.get('summary_line', '?')}\n"
        f"  {total} voice notes · _{dist_str}_"
    )


def render_effectiveness_dashboard(
    now: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
) -> str:
    """Compose the full /effectiveness dashboard message.

    Single-screen Telegram-friendly view. Each section is independently
    fault-tolerant; a layer with no data prints a 'no log yet' note and
    the rest still render. Output fits well under the Telegram message
    cap (4000 chars).
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    # Phase 16.4/16.5 — scope banner. As of 16.5 the by-source section
    # actually filters by conversation_id (TSV gained a 7th column).
    # Other sections (reactions, archetype EMA, voice tone, emotion,
    # engagement rate) read different sources that haven't been tagged
    # yet — those stay whole-vault and the banner makes that explicit.
    header_lines = ["📊 *Effectiveness — feedback signals*"]
    if conversation_id is not None:
        try:
            from myalicia.skills.conversations import get_conversation_meta
            meta = get_conversation_meta(conversation_id) or {}
            label = meta.get("label", conversation_id)
            header_lines.append(
                f"_active conversation:_ *{label}* (`{conversation_id}`) — "
                f"_by-source scoped (16.5); other sections whole-vault_"
            )
        except Exception:
            header_lines.append(f"_active conversation:_ `{conversation_id}`")
    sections = [
        "\n".join(header_lines),
        "",
        _render_reactions_section(now_utc),
        "",
        _render_archetype_ema_section(),
        "",
        _render_voice_tone_section(now_utc),
        "",
        _render_emotion_section(now_utc),
        "",
        _render_engagement_rate_section(now_utc),
        "",
        _render_engagement_by_source_section(
            conversation_id=conversation_id,
        ),
        "",
        _render_meta_synthesis_quality_section(),
        "",
        _render_dashboard_engagement_section(now_utc),
        "",
        _render_mood_of_the_week_section(now_utc),
    ]
    return "\n".join(sections)
