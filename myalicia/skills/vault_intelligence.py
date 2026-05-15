#!/usr/bin/env python3
"""
Alicia — Vault Intelligence System
Three capabilities:
1. Daily light pass: tag untagged notes following Wisdom Schema, add wikilinks
2. Weekly deep pass: find gaps in 8 clusters, generate new concept notes
3. Podcast generator: create new episodes in S1E01 format
"""

import os
import re
import json
from datetime import datetime
from urllib.parse import quote
from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_ROOT  = str(config.vault.root)
VAULT_NAME  = f"{USER_HANDLE}-alicia"
WISDOM_DIR  = os.path.join(VAULT_ROOT, "Wisdom")
QUOTES_DIR  = os.path.join(VAULT_ROOT, "Quotes")
ALICIA_DIR  = os.path.join(VAULT_ROOT, "Alicia")
PODCAST_DIR = os.path.join(WISDOM_DIR, "Podcasts")
ALICIA_WISDOM_DIR = os.path.join(WISDOM_DIR, "Alicia")

# Source folders for daily pass
DAILY_PASS_FOLDERS = [
    os.path.join(VAULT_ROOT, "Quotes"),
    os.path.join(VAULT_ROOT, "Short reads"),
]

# Source folders for the weekly deep pass. Starter list — adapt to your
# vault's shape. Folders that don't exist are silently skipped.
WEEKLY_PASS_FOLDERS = [
    os.path.join(VAULT_ROOT, "Books"),
    os.path.join(VAULT_ROOT, "Authors"),
    os.path.join(VAULT_ROOT, "Stoic"),
    os.path.join(VAULT_ROOT, "Writing"),
]

# ── Deep link generator ───────────────────────────────────────────────────────

def make_deep_link(filepath: str) -> str:
    """Generate an obsidian:// deep link for a vault file."""
    relative = filepath.replace(VAULT_ROOT + "/", "")
    encoded = quote(relative, safe="/")
    return f"obsidian://open?vault={VAULT_NAME}&file={encoded}"


def make_deep_link_name(filepath: str) -> str:
    """Return just the note name for display."""
    return os.path.basename(filepath).replace(".md", "")


# ── Wisdom Schema ─────────────────────────────────────────────────────────────

WISDOM_SCHEMA = f"""
# The 7 Themes and their tags
#
# These are starter themes. Replace the labels, descriptions, and anchor
# wikilinks with whatever organizes your own vault — the downstream tagging
# pass only needs a stable set of "#theme/<slug>" identifiers; the human
# names are just for prompting Sonnet.

1. Theme A — #theme/a
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

2. Theme B — #theme/b
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

3. Theme C — #theme/c
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

4. Theme D — #theme/d
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]], [[80yrs old {USER_NAME}]]

5. Theme E — #theme/e
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

6. Theme F — #theme/f
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

7. Theme G — #theme/g
   What belongs: <a one-line description of this theme>
   Anchors: [[<a representative note in your vault>]]

Tag format: Add at bottom of note, separated by ---
*Wisdom themes:* #theme/a #theme/b
*Connects to:* [[<anchor note>]] · [[<anchor note>]]

Cross-theme bridges are the most valuable connections. Always look for them.
"""

# ── Helper: read/check notes ──────────────────────────────────────────────────

def is_tagged(content: str) -> bool:
    """Check if a note already has Wisdom Schema tags."""
    return "#theme/" in content


def get_untagged_notes(folder: str, limit: int = 30) -> list:
    """Get untagged .md files from a folder."""
    if not os.path.exists(folder):
        return []
    untagged = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, encoding="utf-8") as fh:
                    content = fh.read()
                if not is_tagged(content) and len(content.strip()) > 20:
                    untagged.append(filepath)
                    if len(untagged) >= limit:
                        return untagged
            except Exception:
                pass
    return untagged


def read_note(filepath: str) -> str:
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def write_note(filepath: str, content: str):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


# ── Layer 1: Daily tagging pass ───────────────────────────────────────────────

TAGGING_SYSTEM = f"""You are Alicia, an intelligent knowledge assistant for {USER_NAME}'s Obsidian vault.
Your job is to tag a note following the Wisdom Schema exactly.

{WISDOM_SCHEMA}

Given a note's content, return ONLY a JSON object with this structure:
{{
  "themes": ["#theme/quality", "#theme/mastery"],
  "connects_to": ["[[Aretê]]", "[[Meditations]]"],
  "bridge_note": "One sentence explaining the most interesting cross-theme connection, or empty string if none"
}}

Rules:
- Choose 1-3 themes maximum. Most notes map to 1-2.
- Choose anchor notes that genuinely connect
- Look especially for cross-theme bridges — those are gold
- Return valid JSON only, no other text"""


def _get_tagging_system_with_rules() -> str:
    """Build tagging system prompt with any learned rules from skill config."""
    try:
        from myalicia.skills.skill_config import load_config, get_rules_as_prompt
        config = load_config("vault_intelligence")
        rules_prompt = get_rules_as_prompt(config)
        if rules_prompt:
            return TAGGING_SYSTEM + "\n\n" + rules_prompt
    except Exception:
        pass
    return TAGGING_SYSTEM


def tag_single_note(filepath: str) -> dict:
    """Tag a single note using the Wisdom Schema. Returns result dict."""
    content = read_note(filepath)
    if not content or is_tagged(content):
        return {"skipped": True}

    note_name = os.path.basename(filepath).replace(".md", "")

    # Build system prompt with learned rules from skill config
    system = _get_tagging_system_with_rules()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Note title: {note_name}\n\nContent:\n{content[:800]}"
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        result = json.loads(raw)

        # Build tag block
        themes_str = " ".join(result.get("themes", []))
        connects_str = " · ".join(result.get("connects_to", []))

        tag_block = f"\n\n---\n*Wisdom themes:* {themes_str}\n*Connects to:* {connects_str}"
        if result.get("bridge_note"):
            tag_block += f"\n*Bridge:* {result['bridge_note']}"
        tag_block += f"\n*Tagged by Alicia:* {datetime.now().strftime('%Y-%m-%d')}"

        # Append to note
        updated_content = content.rstrip() + tag_block
        write_note(filepath, updated_content)

        return {
            "success": True,
            "note": note_name,
            "themes": result.get("themes", []),
            "connects_to": result.get("connects_to", []),
            "bridge": result.get("bridge_note", ""),
            "deep_link": make_deep_link(filepath)
        }

    except Exception as e:
        return {"success": False, "note": note_name, "error": str(e)}


def run_daily_tagging_pass() -> dict:
    """
    Daily light pass:
    - Scan Quotes and Short reads for untagged notes
    - Tag each one following Wisdom Schema
    - Return summary for Telegram report
    """
    os.makedirs(ALICIA_WISDOM_DIR, exist_ok=True)

    all_untagged = []
    for folder in DAILY_PASS_FOLDERS:
        all_untagged.extend(get_untagged_notes(folder, limit=20))

    if not all_untagged:
        return {
            "tagged": 0,
            "connections": 0,
            "bridges": [],
            "notes": [],
            "message": "No untagged notes found today — vault is fully tagged! 🎉"
        }

    results = []
    bridges = []
    connections_added = 0

    for filepath in all_untagged[:15]:  # Cap at 15 per day
        result = tag_single_note(filepath)
        if result.get("success"):
            results.append(result)
            connections_added += len(result.get("connects_to", []))
            if result.get("bridge"):
                bridges.append({
                    "note": result["note"],
                    "bridge": result["bridge"],
                    "deep_link": result["deep_link"]
                })

    # Save daily pass log to vault
    date = datetime.now().strftime("%Y-%m-%d")
    log_lines = [f"# Daily Tagging Pass — {date}\n"]
    for r in results:
        log_lines.append(f"- [[{r['note']}]] → {' '.join(r.get('themes', []))}")
        if r.get("bridge"):
            log_lines.append(f"  Bridge: {r['bridge']}")
    log_content = "\n".join(log_lines)

    log_path = os.path.join(ALICIA_WISDOM_DIR, f"{date}-daily-pass.md")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_content)

    return {
        "tagged": len(results),
        "connections": connections_added,
        "bridges": bridges,
        "notes": results,
        "log_deep_link": make_deep_link(log_path)
    }


def format_daily_report(result: dict) -> str:
    """Format daily pass result as Telegram message."""
    if result.get("message"):
        return f"🌿 *Daily Vault Pass*\n\n{result['message']}"

    lines = [
        f"🌿 *Daily Vault Pass — {datetime.now().strftime('%b %d')}*\n",
        f"📎 Tagged: *{result['tagged']} notes*",
        f"🔗 New connections: *{result['connections']}*",
    ]

    if result.get("bridges"):
        lines.append(f"\n✨ *Cross-theme bridges found:*")
        for b in result["bridges"][:3]:
            lines.append(f"• [{b['note']}]({b['deep_link']})")
            lines.append(f"  _{b['bridge']}_")

    if result.get("notes"):
        lines.append(f"\n*Notes tagged:*")
        for n in result["notes"][:8]:
            themes = " ".join(n.get("themes", []))
            lines.append(f"• [{n['note']}]({n['deep_link']}) {themes}")

    if result.get("log_deep_link"):
        lines.append(f"\n[View full log in Obsidian]({result['log_deep_link']})")

    return "\n".join(lines)


# ── Layer 2: Weekly deep pass ─────────────────────────────────────────────────

CLUSTER_GAPS_SYSTEM = ("""You are Alicia, {USER_NAME}'s wisdom partner. You know their 8 knowledge clusters deeply.

The clusters are configured starter placeholders — replace these labels with
the themes that organize the user's own thinking. The downstream code only
cares about the cluster names; the descriptions are prompt context for you.

1. Cluster A (anchor authors / concepts)
2. Cluster B (anchor authors / concepts)
3. Cluster C (anchor authors / concepts)
4. Cluster D (anchor authors / concepts)
5. Cluster E (anchor authors / concepts)
6. Cluster F (anchor authors / concepts)
7. Cluster G (anchor authors / concepts)
8. Cluster H (anchor authors / concepts)

Given a list of vault notes, identify:
1. Which clusters are underrepresented this week
2. What thinkers in those clusters haven't been engaged recently
3. Suggest 3 specific new concept notes to generate (as claim-names)
4. Suggest 1 external thinker not yet in the vault whose work would extend the weakest cluster

Return JSON:
{
  "weak_clusters": ["cluster name"],
  "new_concepts": ["concept as claim", "concept as claim", "concept as claim"],
  "new_thinker": {"name": "Name", "why": "one sentence", "cluster": "cluster name"},
  "synthesis_prompt": "One sentence describing the most interesting connection across this week's notes"
}""".replace("{USER_NAME}", USER_NAME))


DEEP_CONCEPT_SYSTEM = f"""You are Alicia, {USER_NAME}'s wisdom partner. Create a rich concept note for their Obsidian vault.

{USER_NAME}'s style: metaphorical, layered, bridges philosophy and practice, thinks in systems.
Their deepest anchors are whatever appears most often in their MEMORY.md
and synthesis notes — read from the live context, don't hardcode authors.

Rules:
- Title must be a CLAIM: "curiosity compounds faster than discipline" not "notes on curiosity"
- Develop the idea with intellectual rigour — non-obvious insights only
- Connect explicitly to his existing vault using [[wikilinks]]
- Find the tension inside the concept — where does it get complicated?
- End with "What this means for {USER_NAME}" — specific and personal
- Suggest 2 follow-on questions

Format exactly:
# [claim as title]
**Created:** [date]
**Cluster:** [cluster name]
**Tags:** #theme/[tag] #concept #alicia-generated

## The Core Idea
[2-3 sentences capturing the essential claim]

## Why This Is Non-Obvious
[what makes this insight valuable — what it challenges or extends]

## The Tension
[where this idea gets complicated or conflicts with something in the vault]

## Connections
[wikilinks written as sentences, minimum 3 connections to existing vault notes]

## What This Means for {USER_NAME}
[specific, personal, actionable]

## Questions Worth Exploring
- [question 1]
- [question 2]"""


def run_weekly_deep_pass() -> dict:
    """
    Weekly deep pass:
    - Traverse source folders, read recent notes
    - Identify gaps in 8 clusters
    - Generate 3 new concept notes
    - Research one new external thinker
    - Return Telegram summary with deep links
    """
    os.makedirs(ALICIA_WISDOM_DIR, exist_ok=True)

    # Gather recent notes from source folders
    all_files = []
    for folder in WEEKLY_PASS_FOLDERS + [WISDOM_DIR, QUOTES_DIR]:
        if not os.path.exists(folder):
            continue
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.endswith(".md"):
                    fp = os.path.join(root, f)
                    all_files.append((os.path.getmtime(fp), fp))

    all_files.sort(reverse=True)
    recent_files = all_files[:40]

    # Build note list for gap analysis
    note_summaries = []
    for _, fp in recent_files[:30]:
        try:
            content = read_note(fp)[:300]
            name = os.path.basename(fp).replace(".md", "")
            themes = re.findall(r'#theme/\w+', content)
            note_summaries.append(f"{name}: {' '.join(themes)} | {content[:150]}")
        except Exception:
            pass

    notes_text = "\n".join(note_summaries)

    # Identify gaps
    try:
        gap_response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=CLUSTER_GAPS_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Recent vault notes:\n\n{notes_text}"
            }]
        )
        raw = gap_response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        gaps = json.loads(raw)
    except Exception:
        gaps = {
            "weak_clusters": ["Depth of Knowing"],
            "new_concepts": [
                "attention is the only resource that cannot be recovered",
                "wisdom requires a body to be wisdom",
                "the gap between knowing and doing is always an emotional gap"
            ],
            "new_thinker": {"name": "Pierre Hadot", "why": "Decoded Marcus Aurelius as spiritual exercises", "cluster": "Self-Mastery"},
            "synthesis_prompt": "Quality and knowing are two faces of the same attentiveness"
        }

    # Generate new concept notes
    date = datetime.now().strftime("%Y-%m-%d")
    generated_notes = []

    for concept in gaps.get("new_concepts", [])[:3]:
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1200,
                system=DEEP_CONCEPT_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"Generate a concept note for: {concept}\nDate: {date}"
                }]
            )
            content = response.content[0].text

            # Extract title from first line
            title = content.split("\n")[0].replace("# ", "").strip()
            slug = re.sub(r'[^\w\s-]', '', title.lower())
            slug = re.sub(r'[\s_]+', '-', slug)[:60]
            filename = f"{date}-{slug}.md"
            filepath = os.path.join(ALICIA_WISDOM_DIR, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            generated_notes.append({
                "title": title,
                "filepath": filepath,
                "deep_link": make_deep_link(filepath)
            })
        except Exception as e:
            pass

    # Research new thinker
    new_thinker = gaps.get("new_thinker", {})
    thinker_note = None
    if new_thinker.get("name"):
        try:
            thinker_response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=f"""You are researching a thinker for {USER_NAME}'s Obsidian vault.
Write a rich profile note connecting this thinker to {USER_NAME}'s existing knowledge clusters.
Format as a vault note with: profile, key concepts, bridges to existing vault notes using [[wikilinks]].
Always name the note as: # [Thinker Name]""",
                messages=[{
                    "role": "user",
                    "content": f"Write a vault profile for: {new_thinker['name']}\nWhy relevant: {new_thinker.get('why', '')}\nCluster: {new_thinker.get('cluster', '')}\nDate: {date}"
                }]
            )
            thinker_content = thinker_response.content[0].text
            thinker_filename = f"{new_thinker['name'].replace(' ', '-')}.md"
            thinker_path = os.path.join(ALICIA_WISDOM_DIR, thinker_filename)
            with open(thinker_path, "w", encoding="utf-8") as f:
                f.write(thinker_content)
            thinker_note = {
                "name": new_thinker["name"],
                "why": new_thinker.get("why", ""),
                "deep_link": make_deep_link(thinker_path)
            }
        except Exception:
            pass

    return {
        "weak_clusters": gaps.get("weak_clusters", []),
        "synthesis": gaps.get("synthesis_prompt", ""),
        "generated_notes": generated_notes,
        "new_thinker": thinker_note,
        "date": date
    }


def format_weekly_report(result: dict) -> str:
    """Format weekly deep pass as Telegram message."""
    lines = [
        f"🧬 *Weekly Deep Pass — {result['date']}*\n",
        f"Clusters explored. Gaps found. New knowledge generated.\n",
    ]

    if result.get("weak_clusters"):
        lines.append(f"🔍 *Underrepresented clusters:* {', '.join(result['weak_clusters'])}")

    if result.get("synthesis"):
        lines.append(f"\n💡 *This week's synthesis:*\n_{result['synthesis']}_")

    if result.get("generated_notes"):
        lines.append(f"\n✨ *New concept notes generated:*")
        for n in result["generated_notes"]:
            lines.append(f"• [{n['title']}]({n['deep_link']})")

    if result.get("new_thinker"):
        t = result["new_thinker"]
        lines.append(f"\n🧠 *New thinker added:* [{t['name']}]({t['deep_link']})")
        lines.append(f"  _{t['why']}_")

    lines.append(f"\n_All notes in Obsidian → Wisdom/Alicia/_")

    return "\n".join(lines)


# ── Layer 3: Podcast generator ────────────────────────────────────────────────

PODCAST_SYSTEM = f"""You are Alicia, generating an episode of "Memories from My Future Self" for {USER_NAME}.

SHOW FORMAT (follow this exactly):
- Title: S[season]E[episode] — "[Evocative Title]"
- Opening: Brief narrator setup — who {USER_NAME} is, what the vault represents, what this episode is about
- The Battle: A genuine dialectical tension — two honest, rigorous positions fighting over something {USER_NAME} actually carries
  - Voice 1: The conventional/first-rung position — articulate and not straw-manned
  - Voice 2: The deeper/counter position — draws from vault thinkers
  - Three Moments: Concrete sensory situations that make abstract ideas visceral
  - Pushback: Voice 1 responds with real force
  - The Deeper Problem: Voice 2 goes further
  - The Honest Question: Voice 1 asks what replaces what they're giving up
  - The Answer That Isn't An Answer: Voice 2 gives the honest, unsatisfying, true response
- The Turn: What this season is about — the arc
- The Provocation: What the listener takes away tonight. End with a question.
- Show Notes: From the Vault (actual notes), Deep Research (external thinkers), Further Reading

QUALITY STANDARDS (improvements over S1):
- Entry point must be sharper — start with a specific situation, not a general claim
- Each Voice must be more rigorous — no soft strawmen
- The Three Moments must be different from measurement/quality — find new concrete situations
- Deep Research section must include at least 2 thinkers not in the vault
- The tension must feel genuinely unresolved — don't soften it

{USER_NAME}'s vault anchors to draw from come from their live context —
their MEMORY.md, their synthesis notes, and the authors and concepts most
referenced in the recent capture pool. Pull those anchors at runtime rather
than hardcoding them here, so the prompt adapts to whoever's running it.

Write the full episode. This is real content for a real podcast."""


def generate_podcast_episode(
    season: int,
    episode: int,
    tension: str,
    theme_tag: str = ""
) -> dict:
    """Generate a full podcast episode."""
    os.makedirs(PODCAST_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")

    # Load recent wisdom notes for context
    context_notes = []
    for root, dirs, files in os.walk(WISDOM_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files[:20]:
            if f.endswith(".md") and "Alicia" not in root:
                try:
                    fp = os.path.join(root, f)
                    content = read_note(fp)[:400]
                    context_notes.append(f"**{f.replace('.md','')}**\n{content[:200]}")
                except Exception:
                    pass

    vault_context = "\n\n".join(context_notes[:12])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=PODCAST_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"""Generate S{season}E{episode} of "Memories from My Future Self".

Central tension: {tension}
Theme: {theme_tag if theme_tag else 'draw from vault'}
Date: {date}

Recent vault notes to draw from:
{vault_context}

Write the complete episode. Be rigorous. Make it worth listening to."""
        }]
    )

    content = response.content[0].text

    # Extract episode title
    title_match = re.search(r'S\d+E\d+[:\s—-]+["""]?(.+?)["""]?\n', content)
    ep_title = title_match.group(1).strip() if title_match else f"Episode {episode}"

    slug = re.sub(r'[^\w\s-]', '', ep_title.lower()).replace(' ', '-')[:40]
    filename = f"S{season:02d}E{episode:02d}-{slug}.md"
    filepath = os.path.join(PODCAST_DIR, filename)

    # Add frontmatter
    full_content = f"""---
season: {season}
episode: {episode}
title: "{ep_title}"
tension: "{tension}"
created: {date}
tags: [podcast, wisdom, alicia-generated]
---

{content}"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)

    return {
        "title": ep_title,
        "filepath": filepath,
        "deep_link": make_deep_link(filepath),
        "preview": content[:500]
    }


# ── On-demand vault search with deep links ────────────────────────────────────

def search_vault_with_links(query: str, max_results: int = 8) -> str:
    """Search vault and return results with Obsidian deep links."""
    query_words = set(query.lower().split())
    results = []

    for root, dirs, files in os.walk(VAULT_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            name = f.replace(".md", "").lower()
            name_words = set(re.split(r'[\s\-_.,]+', name))
            overlap = len(query_words & name_words)
            if overlap > 0:
                results.append((overlap, 2, filepath, f.replace(".md", "")))
                continue
            # Search content
            try:
                content = read_note(filepath).lower()
                if query.lower() in content:
                    results.append((1, 1, filepath, f.replace(".md", "")))
            except Exception:
                pass

    results.sort(reverse=True)
    top = results[:max_results]

    if not top:
        return f"🔍 Nothing found for *{query}* in your vault."

    lines = [f"🔍 *Found {len(top)} note(s) for '{query}':*\n"]
    for _, _, filepath, name in top:
        deep_link = make_deep_link(filepath)
        folder = os.path.dirname(filepath).replace(VAULT_ROOT + "/", "")
        lines.append(f"• [{name}]({deep_link})\n  _{folder}_")

    return "\n".join(lines)


# ── Vault stats ───────────────────────────────────────────────────────────────

def get_vault_stats() -> str:
    """Return a snapshot of vault health."""
    total_notes = 0
    tagged_notes = 0
    theme_counts = {}
    cluster_files = {}

    for root, dirs, files in os.walk(VAULT_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if not f.endswith(".md"):
                continue
            total_notes += 1
            try:
                content = read_note(os.path.join(root, f))
                themes = re.findall(r'#theme/(\w+)', content)
                if themes:
                    tagged_notes += 1
                    for t in themes:
                        theme_counts[t] = theme_counts.get(t, 0) + 1
            except Exception:
                pass

    lines = [
        f"📊 *Vault Intelligence Report*\n",
        f"Total notes: *{total_notes}*",
        f"Tagged notes: *{tagged_notes}* ({int(tagged_notes/max(total_notes,1)*100)}%)",
        f"Untagged: *{total_notes - tagged_notes}*\n",
        f"*Theme distribution:*"
    ]

    for theme, count in sorted(theme_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(count // 5, 20)
        lines.append(f"  {theme}: {count} {bar}")

    alicia_notes = sum(
        1 for root, dirs, files in os.walk(ALICIA_WISDOM_DIR)
        for f in files if f.endswith(".md")
    ) if os.path.exists(ALICIA_WISDOM_DIR) else 0
    lines.append(f"\nAlicia-generated notes: *{alicia_notes}*")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing daily tagging pass...")
    result = run_daily_tagging_pass()
    print(format_daily_report(result))
