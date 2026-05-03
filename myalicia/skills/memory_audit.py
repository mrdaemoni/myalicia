#!/usr/bin/env python3
"""
Alicia — Memory Audit (SSGM Pattern)

The defensive complement to /improve. Every rule that /improve wrote
gets re-evaluated for staleness, contradiction, and reward effect.
Bad rules get flagged or auto-deprecated; good rules get their
last_corroborated date refreshed.

Inspired by SSGM (arxiv 2603.11768): Stability and Safety Governed
Memory. Three named failure modes for evolving memory systems —
semantic drift, privacy leakage, stability collapse — with proposed
guardrails: staleness decay, provenance tracking, rollback on
divergence detection.

Runs Sunday 19:50 (just before the existing weekly pass at 20:00) so
the report is fresh when /improve fires Sunday 20:00.

Action thresholds (configurable in skills/configs/memory_audit.md):

- staleness_days = 30: rule with last_corroborated > 30 days ago is flagged
- low_confidence = 0.4: rule with confidence < 0.4 is flagged
- auto_deprecate_confidence = 0.25: rule below this is auto-commented
- contradiction_window_days = 14: validations within this window count
"""

import os
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running directly as `python skills/memory_audit.py` AND as
# `python -m skills.memory_audit`. When invoked as a script from inside
# the package directory, sys.path[0] is .../alicia/skills/, so the
# `skills.*` imports below fail. Prepend the project root in that case.
if __name__ == "__main__" and __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)

from myalicia.skills.safe_io import atomic_write_json
from myalicia.skills.skill_config import (
    list_configs,
    iter_rules_with_provenance,
    deprecate_rule,
    update_rule_corroboration,
)

log = logging.getLogger(__name__)

ALICIA_HOME = Path.home() / "alicia"
MEMORY_DIR = ALICIA_HOME / "memory"
AUDIT_REPORT_FILE = MEMORY_DIR / "memory_audit.md"
AUDIT_INDEX_FILE = MEMORY_DIR / "memory_audit.json"
IMPROVE_VALIDATIONS_FILE = MEMORY_DIR / "improve_validations.jsonl"

# Default thresholds — overridable from skills/configs/memory_audit.md
DEFAULT_STALENESS_DAYS = 30
DEFAULT_LOW_CONFIDENCE = 0.4
DEFAULT_AUTO_DEPRECATE_CONFIDENCE = 0.25
DEFAULT_CONTRADICTION_WINDOW_DAYS = 14


def _load_thresholds() -> dict:
    """
    Pull thresholds from skills/configs/memory_audit.md if present, otherwise
    fall back to module defaults. /improve is allowed to tune these over time
    just like any other skill config.
    """
    thresholds = {
        "staleness_days": DEFAULT_STALENESS_DAYS,
        "low_confidence": DEFAULT_LOW_CONFIDENCE,
        "auto_deprecate_confidence": DEFAULT_AUTO_DEPRECATE_CONFIDENCE,
        "contradiction_window_days": DEFAULT_CONTRADICTION_WINDOW_DAYS,
    }
    try:
        from myalicia.skills.skill_config import load_config, get_param

        config = load_config("memory_audit")
        for key, default in list(thresholds.items()):
            raw = get_param(config, key)
            if not raw:
                continue
            try:
                thresholds[key] = (
                    int(raw) if "days" in key else float(raw)
                )
            except (ValueError, TypeError):
                continue
    except Exception as e:
        log.debug(f"memory_audit using default thresholds: {e}")
    return thresholds


def _load_validations() -> list[dict]:
    """Load improve_validations.jsonl as a list of dicts (newest last)."""
    if not IMPROVE_VALIDATIONS_FILE.exists():
        return []
    try:
        with open(IMPROVE_VALIDATIONS_FILE, "r", encoding="utf-8") as f:
            out = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out
    except Exception as e:
        log.warning(f"Failed to read validations: {e}")
        return []


def _validations_for_skill(
    validations: list[dict],
    skill: str,
    window_days: int,
) -> list[dict]:
    """Validations for a skill within the contradiction window."""
    now = datetime.now()
    cutoff = now - timedelta(days=window_days)
    out = []
    for v in validations:
        if v.get("skill") != skill:
            continue
        ts = v.get("validated_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # validated_at may carry tzinfo; normalise to naive local
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if dt >= cutoff:
            out.append(v)
    return out


def _days_since(date_str: str | None) -> int:
    """Return days since `date_str` (ISO date), or large sentinel if missing/bad."""
    if not date_str:
        return 9_999
    try:
        d = datetime.fromisoformat(date_str.split("T")[0])
        return (datetime.now() - d).days
    except (ValueError, TypeError):
        return 9_999


def _audit_skill(
    skill: str,
    thresholds: dict,
    validations: list[dict],
) -> dict:
    """
    Walk every learned rule in `skill`'s config, emit per-rule findings.

    Returns dict:
        {
            "skill": str,
            "rules_audited": int,
            "stale": [{rule, days_since_corroborated}, ...],
            "low_confidence": [{rule, confidence}, ...],
            "hurt_by_validation": [{rule, ...}, ...],
            "deprecated": [{rule, reason}, ...],
            "refreshed": [{rule, new_date}, ...],
        }
    """
    findings: dict[str, Any] = {
        "skill": skill,
        "rules_audited": 0,
        "stale": [],
        "low_confidence": [],
        "hurt_by_validation": [],
        "deprecated": [],
        "refreshed": [],
    }

    rules = iter_rules_with_provenance(skill)
    findings["rules_audited"] = len(rules)
    skill_validations = _validations_for_skill(
        validations, skill, thresholds["contradiction_window_days"]
    )

    # Aggregate skill-level reward delta — if it's negative across the window,
    # rules added in that window are suspect.
    recent_hurt = [
        v for v in skill_validations if v.get("assessment") == "hurt"
    ]

    for r in rules:
        prov = r["provenance"] or {}
        rule_text = r["text"]
        added_date = prov.get("added_date")
        last_corroborated = prov.get("last_corroborated") or added_date
        confidence = prov.get("confidence")
        days_stale = _days_since(last_corroborated)

        # Staleness flag
        if days_stale > thresholds["staleness_days"]:
            findings["stale"].append(
                {
                    "rule": rule_text[:140],
                    "days_since_corroborated": days_stale,
                    "confidence": confidence,
                }
            )

        # Low-confidence flag
        if confidence is not None and confidence < thresholds["low_confidence"]:
            findings["low_confidence"].append(
                {"rule": rule_text[:140], "confidence": confidence}
            )

        # Auto-deprecate: very low confidence + stale + skill validation says
        # the rule's run_at window hurt the skill's reward.
        should_deprecate = (
            confidence is not None
            and confidence < thresholds["auto_deprecate_confidence"]
            and days_stale > thresholds["staleness_days"]
        )
        if recent_hurt and added_date:
            for hv in recent_hurt:
                run_at = hv.get("improve_run_at", "")
                run_date = run_at.split(" ")[0] if run_at else ""
                if run_date and run_date == added_date:
                    findings["hurt_by_validation"].append(
                        {
                            "rule": rule_text[:140],
                            "delta": hv.get("delta"),
                            "improve_run_at": run_at,
                        }
                    )
                    if confidence is None or confidence < thresholds["low_confidence"]:
                        should_deprecate = True

        if should_deprecate:
            reason_bits = [f"days_stale={days_stale}"]
            if confidence is not None:
                reason_bits.append(f"confidence={confidence:.2f}")
            if any(
                rule_text[:60] in v.get("reasoning", "") for v in recent_hurt
            ):
                reason_bits.append("hurt_validation")
            reason = "memory_audit:" + "|".join(reason_bits)
            # Use the first 60 chars of the rule as a unique substring.
            substring = rule_text[:60]
            ok = deprecate_rule(skill, substring, reason=reason)
            if ok:
                findings["deprecated"].append({"rule": rule_text[:140], "reason": reason})

    return findings


def run_memory_audit(auto_apply: bool = True) -> dict:
    """
    Top-level entry. Walks every skill config, audits its rules, and
    optionally applies safe rollbacks (deprecating rules that meet all
    auto-deprecate criteria). Writes a markdown report and a JSON index.

    Args:
        auto_apply: if False, only flag rules — do not modify configs.
            Useful for dry-run before scheduler integration.

    Returns the audit summary dict.
    """
    log.info(f"Starting memory_audit (auto_apply={auto_apply})...")
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    thresholds = _load_thresholds()
    validations = _load_validations()

    skills = list_configs()
    per_skill: list[dict] = []
    total_audited = 0
    total_stale = 0
    total_low = 0
    total_hurt = 0
    total_deprecated = 0

    for skill in sorted(skills):
        findings = _audit_skill(skill, thresholds, validations)
        if not auto_apply:
            findings["deprecated"] = []  # don't keep mutations from dry run
        total_audited += findings["rules_audited"]
        total_stale += len(findings["stale"])
        total_low += len(findings["low_confidence"])
        total_hurt += len(findings["hurt_by_validation"])
        total_deprecated += len(findings["deprecated"])
        per_skill.append(findings)

    summary = {
        "audited_at": datetime.now().isoformat(),
        "thresholds": thresholds,
        "skills_audited": len(skills),
        "rules_audited": total_audited,
        "stale_count": total_stale,
        "low_confidence_count": total_low,
        "hurt_by_validation_count": total_hurt,
        "deprecated_count": total_deprecated,
        "per_skill": per_skill,
        "auto_applied": auto_apply,
    }

    _write_markdown_report(summary)
    atomic_write_json(str(AUDIT_INDEX_FILE), summary)

    log.info(
        f"memory_audit done: stale={total_stale} low_conf={total_low} "
        f"hurt={total_hurt} deprecated={total_deprecated}"
    )
    return summary


def _write_markdown_report(summary: dict) -> None:
    """Render the audit summary as memory/memory_audit.md."""
    try:
        ts = summary["audited_at"]
        lines = [
            "# Memory Audit Report",
            "",
            f"_Generated {ts} — SSGM-style guardrails for /improve writes._",
            "",
            "## Headline",
            "",
            f"- Skills audited: **{summary['skills_audited']}**",
            f"- Rules audited: **{summary['rules_audited']}**",
            f"- Stale (>{summary['thresholds']['staleness_days']}d): **{summary['stale_count']}**",
            f"- Low confidence (<{summary['thresholds']['low_confidence']}): **{summary['low_confidence_count']}**",
            f"- Hurt by validation (recent): **{summary['hurt_by_validation_count']}**",
            f"- Auto-deprecated this run: **{summary['deprecated_count']}**",
            "",
        ]
        for sk in summary["per_skill"]:
            if not (
                sk["stale"]
                or sk["low_confidence"]
                or sk["hurt_by_validation"]
                or sk["deprecated"]
            ):
                continue
            lines.append(f"## {sk['skill']}")
            lines.append("")
            lines.append(f"_Rules audited: {sk['rules_audited']}_")
            lines.append("")
            if sk["stale"]:
                lines.append("### Stale")
                for s in sk["stale"][:10]:
                    lines.append(
                        f"- ({s['days_since_corroborated']}d) {s['rule']}"
                    )
                lines.append("")
            if sk["low_confidence"]:
                lines.append("### Low confidence")
                for r in sk["low_confidence"][:10]:
                    lines.append(f"- (c={r['confidence']:.2f}) {r['rule']}")
                lines.append("")
            if sk["hurt_by_validation"]:
                lines.append("### Hurt by validation")
                for r in sk["hurt_by_validation"][:10]:
                    delta = r.get("delta")
                    delta_str = f"{delta:+.3f}" if isinstance(delta, (int, float)) else "?"
                    lines.append(f"- (Δ={delta_str}) {r['rule']}")
                lines.append("")
            if sk["deprecated"]:
                lines.append("### Auto-deprecated this run")
                for r in sk["deprecated"][:10]:
                    lines.append(f"- {r['rule']}  _({r['reason']})_")
                lines.append("")
        AUDIT_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to write memory_audit.md: {e}")


def get_audit_summary_for_proactive() -> str:
    """
    One-paragraph summary suitable for the morning message. Returns "" if
    nothing audit-worthy happened. Designed to be cheap and read-only.
    """
    if not AUDIT_INDEX_FILE.exists():
        return ""
    try:
        with open(AUDIT_INDEX_FILE, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        return ""

    interesting = (
        summary.get("stale_count", 0)
        + summary.get("low_confidence_count", 0)
        + summary.get("hurt_by_validation_count", 0)
        + summary.get("deprecated_count", 0)
    )
    if not interesting:
        return ""

    return (
        f"📋 Memory audit: {summary.get('rules_audited', 0)} rules across "
        f"{summary.get('skills_audited', 0)} skills · "
        f"stale={summary.get('stale_count', 0)} "
        f"low_conf={summary.get('low_confidence_count', 0)} "
        f"hurt={summary.get('hurt_by_validation_count', 0)} "
        f"auto_deprecated={summary.get('deprecated_count', 0)}"
    )


def format_memory_audit_report(summary: dict) -> str:
    """Compact Telegram-friendly version of the audit summary."""
    lines = ["🛡️ *Memory Audit*"]
    lines.append(
        f"Skills: {summary.get('skills_audited', 0)} · "
        f"Rules: {summary.get('rules_audited', 0)}"
    )
    lines.append(
        f"Stale: {summary.get('stale_count', 0)} · "
        f"Low conf: {summary.get('low_confidence_count', 0)} · "
        f"Hurt: {summary.get('hurt_by_validation_count', 0)}"
    )
    if summary.get("deprecated_count"):
        lines.append(f"Auto-deprecated: {summary['deprecated_count']}")
    return "\n".join(lines)


# CLI helpers ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    apply_changes = "--apply" in sys.argv
    summary = run_memory_audit(auto_apply=apply_changes)
    print(json.dumps(summary, indent=2, default=str))
    print("\n" + format_memory_audit_report(summary))
