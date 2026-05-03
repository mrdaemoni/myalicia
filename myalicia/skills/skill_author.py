#!/usr/bin/env python3
"""
Alicia — Skill Author (Memento-Skills Pattern)

The offensive complement to /improve. When reflexion identifies a
failure that no existing skill claims responsibility for, this module
drafts a markdown skill stub from the failure trace and queues it in
~/alicia/skills/_pending/<slug>.md for one-tap the user approval.

Inspired by Memento-Skills (arxiv 2603.18743):
  Read → Execute → Reflect → Write
  On GAIA, the agent grew a 41-skill library and gained +13.7pp
  (52.3 → 66.0%). On HLE, it dynamically scaled to 235 distinct skills
  and more than doubled performance (17.9 → 38.7%).

The key safety constraint: stubs are never auto-merged. They go to a
pending folder, surface in the morning message, and only become real
skills when the user accepts them. This preserves the SSGM rule that all
memory writes are reversible.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# See memory_audit.py — same package-bootstrap shim so `python skills/skill_author.py`
# works without the user having to remember `python -m skills.skill_author`.
if __name__ == "__main__" and __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)

import dotenv
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

ALICIA_HOME = Path.home() / "alicia"
SKILLS_DIR = ALICIA_HOME / "skills"
PENDING_DIR = SKILLS_DIR / "_pending"
MEMORY_DIR = ALICIA_HOME / "memory"
EPISODES_DIR = MEMORY_DIR / "episodes"
SKILL_AUTHOR_LOG = MEMORY_DIR / "skill_author_log.jsonl"

# Avoid drafting more than one stub for the same failure cluster too often.
MIN_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours
MAX_PENDING_STUBS = 5

dotenv.load_dotenv(os.path.expanduser("~/alicia/.env"))


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "unnamed"


def _existing_skill_names() -> set[str]:
    """Skills already living in skills/ — used to avoid duplicate stubs."""
    out: set[str] = set()
    for p in SKILLS_DIR.glob("*.py"):
        if p.name.startswith("_"):
            continue
        out.add(p.stem)
    return out


def _existing_pending() -> list[Path]:
    if not PENDING_DIR.exists():
        return []
    return sorted(PENDING_DIR.glob("*.md"))


def _last_draft_time() -> float:
    """Most recent skill_author write time, or 0 if none."""
    if not SKILL_AUTHOR_LOG.exists():
        return 0.0
    try:
        with open(SKILL_AUTHOR_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return 0.0
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                ts = rec.get("ts")
                if ts:
                    return float(ts)
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return 0.0


def _log_draft(record: dict) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(SKILL_AUTHOR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error(f"skill_author log write failed: {e}")


def _load_similar_episodes(task_type: str, limit: int = 5) -> list[dict]:
    """Most recent episodes for this task type — context for the stub."""
    if not EPISODES_DIR.exists():
        return []
    out: list[dict] = []
    try:
        for ep_path in sorted(EPISODES_DIR.glob(f"*_{task_type}.json"), reverse=True):
            try:
                with open(ep_path, "r", encoding="utf-8") as f:
                    ep = json.load(f)
                ep["_file"] = ep_path.name
                out.append(ep)
            except Exception:
                continue
            if len(out) >= limit:
                break
    except Exception as e:
        log.warning(f"skill_author similar-episode scan failed: {e}")
    return out


def _draft_stub_text(
    failure: dict,
    similar: list[dict],
    proposed_name: str,
) -> str:
    """
    Build the markdown stub content. Pure formatting — no LLM call so
    the stub draft path stays cheap and offline-safe. the user edits the
    stub on approval; the LLM-quality polish happens at merge time.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    failure_input = (failure.get("input") or "")[:300]
    failure_output = (failure.get("output") or "")[:300]
    failure_to_improve = (failure.get("reflection", {}) or {}).get("to_improve", "")
    confidence = (failure.get("reflection", {}) or {}).get("confidence", "?")
    decision_attr = (failure.get("reflection", {}) or {}).get("decision_attribution", [])

    # Build trigger guesses from the failure's task_type + improvement notes.
    triggers: list[str] = []
    triggers.append(failure.get("task_type", ""))
    for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", failure_to_improve)[:6]:
        if w.lower() not in {"the", "this", "that", "with", "from", "into", "would"}:
            triggers.append(w.lower())
    triggers = [t for t in triggers if t]

    examples: list[str] = []
    for s in similar[:2]:
        ref = s.get("reflection", {}) or {}
        examples.append(
            f"- **{s.get('_file', '?')}** "
            f"(score={s.get('score', '?')}, confidence={ref.get('confidence', '?')}): "
            f"to_improve = {(ref.get('to_improve') or '')[:160]}"
        )

    decision_lines: list[str] = []
    for d in decision_attr or []:
        try:
            decision_lines.append(
                f"- ({d.get('attribution', '?')}) {d.get('step', '?')} — "
                f"{d.get('reason', '?')}"
            )
        except Exception:
            continue

    body = [
        f"# {proposed_name}",
        "",
        f"_Drafted by skill_author on {today} — pending {USER_NAME}'s review._",
        "",
        "## Why this stub exists",
        "",
        "Reflexion identified a failure no existing skill claims responsibility for.",
        f"Failing task type: `{failure.get('task_type', 'unknown')}`. Confidence in "
        f"the failing reflection: {confidence}/5. The reflexion engine declined to "
        "name an owning skill, which Memento-Skills (arxiv 2603.18743) treats as the "
        "moment to author a new one rather than overload an existing skill.",
        "",
        "## Source episode",
        "",
        f"- file: `{failure.get('_file', '(unknown)')}`",
        f"- task_type: `{failure.get('task_type', 'unknown')}`",
        f"- input (truncated): {failure_input}",
        f"- output (truncated): {failure_output}",
        f"- to_improve: {failure_to_improve}",
        "",
        "## Decision attribution (TIMG)",
        "",
        ("\n".join(decision_lines) if decision_lines else "_No per-step trace was recorded._"),
        "",
        "## Similar prior episodes",
        "",
        ("\n".join(examples) if examples else "_None found in the last 5 task-type matches._"),
        "",
        "## Proposed responsibility",
        "",
        "- name: " + _slugify(proposed_name),
        "- triggers: " + (", ".join(sorted(set(triggers))) or "_none yet_"),
        "- dependencies: _to be filled in on review_",
        "",
        f"## Open questions for {USER_NAME}",
        "",
        "1. Is this a real new responsibility, or should an existing skill absorb it?",
        "2. Which existing skill is the closest neighbor (so the new one can copy its config layout)?",
        "3. What success criterion would let you know this skill is working?",
        "",
        "## Provenance",
        "",
        f"- source_episode_id: {failure.get('_file', 'none')}",
        f"- source_task_type: {failure.get('task_type', 'unknown')}",
        f"- drafted_at: {datetime.now().isoformat()}",
        "- status: pending_review",
        "",
        "_To accept: rename this file to `<name>.md`, move to `skills/configs/`, write the matching `<name>.py`. "
        "To reject: delete this file. To defer: leave in place — the morning message will keep surfacing it._",
        "",
    ]
    return "\n".join(body)


def maybe_draft_stub(failure: dict, episode_path: str | None = None) -> dict | None:
    """
    Conditional entry point called from reflexion._reflect_on_task when an
    episode has `responsibility_gap=True`. Applies rate limiting, queue
    capacity check, and de-dup against existing skills before writing a
    stub to skills/_pending/.

    Returns the draft record if a stub was written, otherwise None.
    """
    try:
        # Rate limit: don't author more than one stub per 6 hours.
        last = _last_draft_time()
        now = time.time()
        if now - last < MIN_INTERVAL_SECONDS:
            log.info(
                f"skill_author skip — last draft {int((now-last)/60)}m ago, min interval is "
                f"{MIN_INTERVAL_SECONDS // 60}m"
            )
            return None

        # Queue capacity: don't pile up unreviewed stubs.
        pending = _existing_pending()
        if len(pending) >= MAX_PENDING_STUBS:
            log.info(
                f"skill_author skip — {len(pending)} pending stubs already, "
                f"max is {MAX_PENDING_STUBS}"
            )
            return None

        task_type = failure.get("task_type", "unknown")
        existing = _existing_skill_names()

        # Build proposed skill name. Heuristic: derive from to_improve or
        # task_type. the user edits this on review.
        ref = failure.get("reflection", {}) or {}
        improve_hint = ref.get("to_improve", "")
        seed_name = improve_hint or task_type
        proposed_name = "skill_" + _slugify(seed_name)[:40]

        # If we'd collide with an existing skill name (or pending stub),
        # bail — the gap belongs in that skill, not a new file.
        if proposed_name in existing or proposed_name == task_type:
            log.info(f"skill_author skip — proposed name {proposed_name} collides with existing")
            return None
        for p in pending:
            if p.stem == proposed_name:
                log.info(f"skill_author skip — pending stub {p.name} already exists")
                return None

        # Pull a few similar episodes to enrich the stub.
        if episode_path:
            failure["_file"] = os.path.basename(episode_path)
        similar = _load_similar_episodes(task_type, limit=5)

        # Write the stub.
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        stub_path = PENDING_DIR / f"{proposed_name}.md"
        stub_path.write_text(_draft_stub_text(failure, similar, proposed_name), encoding="utf-8")

        record = {
            "ts": now,
            "drafted_at": datetime.now().isoformat(),
            "stub_path": str(stub_path),
            "proposed_name": proposed_name,
            "task_type": task_type,
            "source_episode": failure.get("_file"),
            "to_improve": (improve_hint or "")[:200],
        }
        _log_draft(record)
        log.info(f"skill_author drafted stub: {stub_path.name}")
        return record

    except Exception as e:
        log.error(f"skill_author draft failed: {e}")
        return None


def list_pending_stubs() -> list[dict]:
    """
    Return one dict per pending stub: {file, name, drafted_at, headline,
    task_type}. Used by the morning message to render the inbox.
    """
    out: list[dict] = []
    for p in _existing_pending():
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m_drafted = re.search(r"drafted_at:\s*(\S+)", text)
        m_task = re.search(r"task_type:\s*`([^`]+)`", text)
        m_headline = re.search(r"^# (.+)$", text, re.MULTILINE)
        out.append(
            {
                "file": p.name,
                "name": p.stem,
                "drafted_at": m_drafted.group(1) if m_drafted else "?",
                "task_type": m_task.group(1) if m_task else "?",
                "headline": m_headline.group(1) if m_headline else p.stem,
            }
        )
    return out


def get_pending_stubs_summary() -> str:
    """One-paragraph summary for proactive_messages morning slot."""
    pending = list_pending_stubs()
    if not pending:
        return ""
    lines = [
        f"📝 *Skill stubs awaiting review* ({len(pending)})",
        "",
    ]
    for s in pending:
        lines.append(
            f"- `{s['name']}` (from {s['task_type']}, drafted {s['drafted_at'][:10]})"
        )
    lines.append("")
    lines.append(
        "_Edit the stub in `skills/_pending/`, then move it to "
        "`skills/configs/` to accept — or delete to reject._"
    )
    return "\n".join(lines)


def discard_stub(name: str) -> bool:
    """Delete a pending stub. Used when the user types `/discard_stub <name>`."""
    p = PENDING_DIR / f"{name}.md"
    if not p.exists():
        return False
    try:
        p.unlink()
        log.info(f"skill_author discarded stub: {name}")
        return True
    except Exception as e:
        log.error(f"discard_stub failed: {e}")
        return False


# CLI ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in list_pending_stubs():
            print(f"{s['file']}\t{s['task_type']}\t{s['drafted_at']}\t{s['headline']}")
    elif len(sys.argv) > 2 and sys.argv[1] == "discard":
        ok = discard_stub(sys.argv[2])
        print("ok" if ok else "not found")
    else:
        print("Usage: python skill_author.py [list | discard <name>]")
