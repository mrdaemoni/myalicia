#!/usr/bin/env python3
"""
Alicia — Skill 04: Deep Research
Researches topics using Claude, writes structured notes to Obsidian
"""

import os
import re
from datetime import datetime
import anthropic
from dotenv import load_dotenv
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

OBSIDIAN_VAULT = str(config.vault.inner_path)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

RESEARCH_SYSTEM = f"""You are Alicia's research engine. You produce structured, insightful research briefs.

When given a topic, you:
1. Synthesise what is known about it clearly and honestly
2. Present multiple perspectives where they exist
3. Flag what is uncertain or debated
4. Make it personally relevant and actionable
5. Suggest connections to adjacent ideas

Format your response as a structured Obsidian markdown note using exactly this template:

## Core Question
[What is really being asked here]

## Key Findings
[3-7 bullet points of the most important things to know, each with a confidence marker: (High) (Medium) (Low)]

## Different Perspectives
[Where smart people disagree, and why — be fair to each side]

## Alicia's Synthesis
[Your honest overall read of the evidence — what it suggests, with appropriate uncertainty]

## What This Means For {USER_NAME}
[Practical relevance — how this connects to life, decisions, or growth]

## Open Questions
[What remains genuinely unclear or worth investigating further]

## Connections
[2-4 related concepts or ideas worth exploring — formatted as [[concept]] for Obsidian links]

Be intellectually honest. Never pretend certainty you don't have. Be concise but never shallow."""


QUICK_SYSTEM = """You are Alicia's research engine. Give a quick, sharp overview — 4-6 sentences max.
Be direct. Lead with the most important thing. Flag anything uncertain.
No headers, no bullet points — just clear prose for a Telegram message."""


def slugify(text: str) -> str:
    """Convert title to safe filename."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text[:60]


def write_research_note(topic: str, content: str, depth: str) -> str:
    """Write a research note to Obsidian and return the filepath."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # Determine subfolder based on topic keywords
    topic_lower = topic.lower()
    if any(w in topic_lower for w in ["health", "sleep", "exercise", "diet", "body", "mind", "mental"]):
        subfolder = "Knowledge Vault/Research/Health & Body"
    elif any(w in topic_lower for w in ["money", "invest", "finance", "wealth", "tax", "budget"]):
        subfolder = "Knowledge Vault/Research/Finance & Wealth"
    elif any(w in topic_lower for w in ["tech", "ai", "software", "code", "app", "digital"]):
        subfolder = "Knowledge Vault/Research/Technology"
    elif any(w in topic_lower for w in ["philosophy", "wisdom", "meaning", "stoic", "ethics", "life"]):
        subfolder = "Knowledge Vault/Research/Philosophy & Wisdom"
    elif any(w in topic_lower for w in ["psychology", "habit", "behaviour", "emotion", "motivation"]):
        subfolder = "Knowledge Vault/Research/Mind & Psychology"
    else:
        subfolder = "Knowledge Vault/Research"

    # Build full note with frontmatter
    full_note = f"""# {topic}
**Type:** Research Brief
**Created:** {date_str} at {time_str}
**Depth:** {depth}
**Status:** Complete
**Tags:** #research #alicia-generated

---

{content}

---
*Research by Alicia · {date_str}*
"""

    # Write to Obsidian
    folder_path = os.path.join(OBSIDIAN_VAULT, subfolder)
    os.makedirs(folder_path, exist_ok=True)
    filename = f"{date_str}-{slugify(topic)}.md"
    filepath = os.path.join(folder_path, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_note)

    return filepath


def research_quick(topic: str) -> str:
    """Depth 1 — Quick scan, returns Telegram message only."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=QUICK_SYSTEM,
        messages=[{"role": "user", "content": f"Quick overview: {topic}"}]
    )
    return response.content[0].text


def research_brief(topic: str) -> tuple[str, str]:
    """Depth 2 — Solid brief, writes to Obsidian. Returns (telegram_summary, obsidian_path)."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": f"Research this topic thoroughly: {topic}"}]
    )
    full_content = response.content[0].text
    filepath = write_research_note(topic, full_content, "Depth 2 — Solid Brief")

    # Extract just Key Findings for Telegram summary
    findings_match = re.search(r'## Key Findings\n(.*?)(?=\n##)', full_content, re.DOTALL)
    if findings_match:
        findings = findings_match.group(1).strip()
    else:
        findings = full_content[:400]

    telegram_summary = (
        f"📚 *Research complete: {topic}*\n\n"
        f"{findings}\n\n"
        f"_Full note saved to Obsidian._"
    )
    return telegram_summary, filepath


def research_deep(topic: str) -> tuple[str, str]:
    """Depth 3 — Deep investigation with multiple angles. Returns (telegram_summary, obsidian_path)."""
    # First pass — broad overview
    pass1 = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": f"Research this topic thoroughly: {topic}"}]
    ).content[0].text

    # Second pass — go deeper on gaps and connections
    pass2 = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        system="You are a research synthesiser. Given an initial research brief, identify what's missing, what's debatable, and what the most important practical insight is. Be direct and add genuine value beyond what's already there.",
        messages=[
            {"role": "user", "content": f"Initial research on '{topic}':\n\n{pass1}\n\nNow: what's missing? What's the sharpest insight? What's most actionable for someone who wants to deeply understand this?"}
        ]
    ).content[0].text

    full_content = f"{pass1}\n\n## Deeper Analysis\n{pass2}"
    filepath = write_research_note(topic, full_content, "Depth 3 — Deep Investigation")

    telegram_summary = (
        f"🔬 *Deep research complete: {topic}*\n\n"
        f"Two-pass analysis done. Key synthesis:\n\n"
        f"_{pass2[:300]}..._\n\n"
        f"_Full note saved to Obsidian._"
    )
    return telegram_summary, filepath


def search_vault(query: str) -> str:
    """Search existing Obsidian notes for a topic."""
    results = []
    research_path = os.path.join(OBSIDIAN_VAULT, "Knowledge Vault/Research")

    if not os.path.exists(research_path):
        return f"📭 No research notes found yet. Try researching '{query}' first."

    query_lower = query.lower()
    for root, dirs, files in os.walk(research_path):
        for f in files:
            if f.endswith(".md") and query_lower in f.lower():
                results.append(os.path.join(root, f).replace(OBSIDIAN_VAULT + "/", ""))

    if not results:
        # Search inside files
        for root, dirs, files in os.walk(research_path):
            for f in files:
                if not f.endswith(".md"):
                    continue
                filepath = os.path.join(root, f)
                try:
                    content = open(filepath).read().lower()
                    if query_lower in content:
                        results.append(filepath.replace(OBSIDIAN_VAULT + "/", ""))
                except Exception:
                    pass

    if not results:
        return f"🔍 Nothing found for '{query}' in your vault yet."

    lines = [f"🔍 *Found {len(results)} note(s) for '{query}':*\n"]
    for r in results[:8]:
        name = os.path.basename(r).replace(".md", "").replace("-", " ")
        lines.append(f"• {name}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing research skill...")
    result = research_quick("the benefits of cold exposure for recovery")
    print(result)