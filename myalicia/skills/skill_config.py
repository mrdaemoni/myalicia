#!/usr/bin/env python3
"""
Alicia — Skill Config Loader

Reads companion .md config files for skill modules. Each config holds
the judgment rules, parameters, and learned patterns that evolve over time.
The Python module stays deterministic; the markdown carries the intelligence.

Config files live in skills/configs/ inside the git repo, so every
self-rewrite by the /improve skill is a trackable commit.

Usage in a skill module:
    from myalicia.skills.skill_config import load_config, get_rules, get_param

    config = load_config("vault_intelligence")
    rules = get_rules(config)       # list of learned rules
    threshold = get_param(config, "relevance_threshold", default="0.25")
"""
import os
import re
import logging
from datetime import datetime

log = logging.getLogger(__name__)

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")


def load_config(skill_name: str) -> dict:
    """
    Load a skill's markdown config file and parse it into sections.

    Returns dict with keys: procedure, parameters, rules, evaluation, raw.
    Returns empty sections (not errors) if the file is missing or malformed.
    """
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")

    if not os.path.exists(config_path):
        log.debug(f"No config for {skill_name} at {config_path}")
        return _empty_config(skill_name)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        log.warning(f"Failed to read config {config_path}: {e}")
        return _empty_config(skill_name)

    return _parse_config(skill_name, raw)


def get_rules(config: dict) -> list[str]:
    """Extract learned rules as a list of strings (one per bullet)."""
    rules_text = config.get("rules", "")
    if not rules_text.strip():
        return []

    rules = []
    for line in rules_text.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            rules.append(line[2:].strip())
        elif line.startswith("1.") or re.match(r"^\d+\.", line):
            rules.append(re.sub(r"^\d+\.\s*", "", line).strip())
    return [r for r in rules if r]


def get_param(config: dict, key: str, default: str = "") -> str:
    """Extract a named parameter from the parameters section."""
    params_text = config.get("parameters", "")
    for line in params_text.split("\n"):
        line = line.strip()
        # Match "key: value" or "- key: value" or "**key**: value"
        patterns = [
            rf"^[-*]?\s*\**{re.escape(key)}\**\s*:\s*(.+)$",
            rf"^{re.escape(key)}\s*=\s*(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return default


def get_section(config: dict, section_name: str) -> str:
    """Get raw text of any named section."""
    return config.get(section_name, "")


def get_rules_as_prompt(config: dict) -> str:
    """Format rules as a prompt-injectable string for system prompts."""
    rules = get_rules(config)
    if not rules:
        return ""
    lines = ["### Learned Rules (from experience)"]
    for i, rule in enumerate(rules, 1):
        lines.append(f"{i}. {rule}")
    return "\n".join(lines)


def append_rule(
    skill_name: str,
    rule: str,
    source: str = "improve",
    source_episode_id: str | None = None,
    confidence: float | None = None,
    last_corroborated: str | None = None,
) -> bool:
    """
    Append a new learned rule to a skill's config file.
    Creates the rules section if it doesn't exist.

    SSGM provenance (arxiv 2603.11768): every /improve write carries
    enough context for a memory_audit pass to detect drift, evaluate
    staleness, and propose rollback. The provenance fields are optional
    so existing callers (seed rules, manual edits) keep working — but
    /improve callers should always supply them.

    Args:
        skill_name: target skill config (e.g. "vault_intelligence")
        rule: human-readable rule text
        source: who/what authored the rule ("improve", "manual", "seed")
        source_episode_id: filename of the reflexion episode that justified
            this rule, when source="improve". Lets memory_audit query
            episode_scorer for the originating reward signal.
        confidence: 0.0-1.0 score from /improve's analysis (or normalised
            from reflexion confidence). Rules with confidence < 0.4 become
            candidates for auto-deprecation in memory_audit.
        last_corroborated: ISO date of the most recent episode that
            corroborated the rule. Defaults to today on first write.
            memory_audit refreshes this as new episodes arrive.

    Returns True on success.
    """
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")

    if not os.path.exists(config_path):
        log.warning(f"Cannot append rule: no config for {skill_name}")
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        timestamp = datetime.now().strftime("%Y-%m-%d")

        # Build provenance suffix. Keep existing format ("_(added DATE by SRC)_")
        # so historical rules and the skill_library rule counter still parse;
        # extend with HTML comment carrying machine-readable provenance.
        prov_corroborated = last_corroborated or timestamp
        prov_parts = [f"src_episode={source_episode_id or 'none'}"]
        if confidence is not None:
            prov_parts.append(f"confidence={confidence:.2f}")
        prov_parts.append(f"last_corroborated={prov_corroborated}")
        provenance_comment = f"<!-- {' '.join(prov_parts)} -->"

        new_rule = (
            f"- {rule} _(added {timestamp} by {source})_ {provenance_comment}"
        )

        if "## Learned Rules" in content:
            # Append to existing rules section
            content = content.replace(
                "## Learned Rules",
                "## Learned Rules",
                1,
            )
            # Find the end of the rules section (next ## or end of file)
            rules_start = content.index("## Learned Rules")
            next_section = content.find("\n## ", rules_start + 1)
            if next_section == -1:
                # Rules is the last section — append at end
                content = content.rstrip() + "\n" + new_rule + "\n"
            else:
                # Insert before the next section
                content = (
                    content[:next_section].rstrip()
                    + "\n"
                    + new_rule
                    + "\n\n"
                    + content[next_section:]
                )
        else:
            # Create rules section at the end
            content = (
                content.rstrip()
                + "\n\n## Learned Rules\n\n"
                + new_rule
                + "\n"
            )

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        log.info(f"Appended rule to {skill_name}: {rule[:60]}")
        return True

    except Exception as e:
        log.error(f"Failed to append rule to {skill_name}: {e}")
        return False


def update_param(skill_name: str, key: str, value: str) -> bool:
    """Update a parameter value in a skill's config file."""
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")

    if not os.path.exists(config_path):
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            patterns = [
                rf"^([-*]?\s*\**{re.escape(key)}\**\s*:\s*).+$",
                rf"^({re.escape(key)}\s*=\s*).+$",
            ]
            for pattern in patterns:
                match = re.match(pattern, stripped, re.IGNORECASE)
                if match:
                    prefix = match.group(1)
                    indent = line[: len(line) - len(line.lstrip())]
                    lines[i] = f"{indent}{prefix}{value}\n"
                    updated = True
                    break
            if updated:
                break

        if updated:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log.info(f"Updated {skill_name} param {key}={value}")

        return updated

    except Exception as e:
        log.error(f"Failed to update param in {skill_name}: {e}")
        return False


def list_configs() -> list[str]:
    """List all available skill config names."""
    if not os.path.isdir(CONFIGS_DIR):
        return []
    return [
        f.replace(".md", "")
        for f in os.listdir(CONFIGS_DIR)
        if f.endswith(".md")
    ]


def parse_rule_provenance(rule_line: str) -> dict:
    """
    Parse the SSGM provenance comment from a rule line.

    Returns a dict with keys: source_episode, confidence, last_corroborated,
    added_date, source. Missing fields are None. Returns {} if the line is
    not a rule or has no provenance.

    A rule line looks like:
        - rule text _(added 2026-04-27 by improve)_ <!-- src_episode=2026-04-26_103045_search_vault.json confidence=0.72 last_corroborated=2026-04-27 -->
    """
    if not rule_line.strip().startswith(("- ", "* ", "1.")):
        return {}

    out: dict = {
        "source_episode": None,
        "confidence": None,
        "last_corroborated": None,
        "added_date": None,
        "source": None,
    }

    # Match the human-readable suffix
    added_match = re.search(
        r"_\(added (\d{4}-\d{2}-\d{2}) by ([^)]+)\)_", rule_line
    )
    if added_match:
        out["added_date"] = added_match.group(1)
        out["source"] = added_match.group(2).strip()

    # Match the machine-readable provenance comment
    comment_match = re.search(r"<!--\s*(.*?)\s*-->", rule_line)
    if comment_match:
        body = comment_match.group(1)
        for token in body.split():
            if "=" not in token:
                continue
            key, _, val = token.partition("=")
            if key == "src_episode":
                out["source_episode"] = None if val == "none" else val
            elif key == "confidence":
                try:
                    out["confidence"] = float(val)
                except ValueError:
                    pass
            elif key == "last_corroborated":
                out["last_corroborated"] = val

    return out


def update_rule_corroboration(
    skill_name: str,
    rule_substring: str,
    new_corroborated_date: str | None = None,
) -> bool:
    """
    Refresh the `last_corroborated` field on a single rule. Used by
    memory_audit when a new episode confirms an existing rule.

    Matches by substring (the first ~60 chars of the rule text are usually
    enough to be unique). Returns True if a rule was updated.
    """
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")
    if not os.path.exists(config_path):
        return False

    new_date = new_corroborated_date or datetime.now().strftime("%Y-%m-%d")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"Failed to read {config_path}: {e}")
        return False

    updated = False
    for i, line in enumerate(lines):
        if rule_substring not in line:
            continue
        if "<!--" not in line:
            # No provenance comment to update; add one at end of line.
            lines[i] = (
                line.rstrip()
                + f" <!-- src_episode=none last_corroborated={new_date} -->\n"
            )
        else:
            lines[i] = re.sub(
                r"last_corroborated=\d{4}-\d{2}-\d{2}",
                f"last_corroborated={new_date}",
                line,
            )
        updated = True
        break

    if updated:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log.info(f"Refreshed corroboration for {skill_name}: {rule_substring[:40]}")
        except Exception as e:
            log.error(f"Failed to write {config_path}: {e}")
            return False

    return updated


def deprecate_rule(skill_name: str, rule_substring: str, reason: str = "") -> bool:
    """
    Mark a rule as deprecated by commenting it out in the config file
    (preserved for audit but ignored by get_rules). Used by memory_audit
    when a rule's confidence drops or it consistently hurts.
    """
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")
    if not os.path.exists(config_path):
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"Failed to read {config_path}: {e}")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    deprecated = False
    for i, line in enumerate(lines):
        if rule_substring in line and line.strip().startswith(("- ", "* ")):
            # Convert to HTML comment so get_rules ignores but file keeps history.
            tag = f"<!-- DEPRECATED {today}: {reason or 'memory_audit'} | "
            content = line.rstrip("\n")
            # Strip leading "- " so the deprecated entry doesn't accidentally
            # render as a Markdown bullet inside the HTML comment.
            stripped = content.lstrip("-* ").rstrip()
            lines[i] = f"{tag}{stripped} -->\n"
            deprecated = True
            break

    if deprecated:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log.info(f"Deprecated rule in {skill_name}: {rule_substring[:40]} ({reason})")
        except Exception as e:
            log.error(f"Failed to write {config_path}: {e}")
            return False

    return deprecated


def iter_rules_with_provenance(skill_name: str) -> list[dict]:
    """
    Read every rule line in a skill config, returning a list of dicts:
        {"text": str, "line_no": int, "provenance": {...}}

    Non-rule lines and deprecated rules (HTML-commented) are skipped.
    Drives memory_audit's main loop.
    """
    config_path = os.path.join(CONFIGS_DIR, f"{skill_name}.md")
    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"Failed to read {config_path}: {e}")
        return []

    out: list[dict] = []
    in_rules = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## Learned Rules") or stripped.startswith("## Rules"):
            in_rules = True
            continue
        if stripped.startswith("## ") and in_rules:
            in_rules = False
            continue
        if not in_rules:
            continue
        if not stripped.startswith(("- ", "* ", "1.")):
            continue
        # Skip seed-only rules (no provenance) — they're not /improve writes
        # and don't have an episode to corroborate against.
        prov = parse_rule_provenance(line)
        out.append(
            {
                "text": stripped.lstrip("-* ").strip(),
                "line_no": i,
                "provenance": prov,
            }
        )
    return out


def _empty_config(skill_name: str) -> dict:
    return {
        "skill_name": skill_name,
        "procedure": "",
        "parameters": "",
        "rules": "",
        "evaluation": "",
        "raw": "",
    }


def _parse_config(skill_name: str, raw: str) -> dict:
    """Parse markdown config into sections by ## headers."""
    config = _empty_config(skill_name)
    config["raw"] = raw

    # Map section headers to dict keys
    section_map = {
        "procedure": "procedure",
        "parameters": "parameters",
        "learned rules": "rules",
        "rules": "rules",
        "evaluation": "evaluation",
        "evaluation criteria": "evaluation",
    }

    current_key = None
    buffer = []

    for line in raw.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_key:
                config[current_key] = "\n".join(buffer).strip()
            # Start new section
            header = line[3:].strip().lower()
            current_key = section_map.get(header)
            buffer = []
        elif current_key:
            buffer.append(line)

    # Save last section
    if current_key and buffer:
        config[current_key] = "\n".join(buffer).strip()

    return config
