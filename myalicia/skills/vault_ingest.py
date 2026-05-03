"""
vault_ingest.py — Cascading Ingest Pipeline

When new sources arrive in the vault, this module:
1. Detects new/modified files via scheduled scan (diffing against last-known state)
2. Reads and summarizes each new source
3. Updates existing entity/concept pages with new references
4. Updates existing synthesis notes that relate to the new source
5. Checks for contradictions with existing knowledge
6. Updates Wisdom/index.md (structured catalog of all wiki pages)
7. Appends to Wisdom/log.md (chronological vault evolution timeline)
8. Notifies Telegram with a summary of all changes

Inspired by the LLM Wiki pattern: every new source should touch every
relevant page, making the vault a truly compounding knowledge artifact.

Created: 2026-04-05
"""

import json
import logging
import os
import re
import time
from datetime import datetime

from myalicia.skills.safe_io import atomic_write_json
from urllib.parse import quote

from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(os.path.expanduser("~/alicia/.env"))
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

log = logging.getLogger("alicia.vault_ingest")

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
VAULT_NAME = f"{USER_HANDLE}-alicia"
WISDOM_DIR = os.path.join(VAULT_ROOT, "Wisdom")
SYNTHESIS_DIR = os.path.join(WISDOM_DIR, "Synthesis")
ALICIA_DIR = os.path.join(VAULT_ROOT, "Alicia")
ALICIA_WISDOM_DIR = os.path.join(WISDOM_DIR, "Alicia")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")

INDEX_FILE = os.path.join(WISDOM_DIR, "index.md")
LOG_FILE = os.path.join(WISDOM_DIR, "log.md")
INGEST_STATE_FILE = os.path.join(MEMORY_DIR, "ingest_state.json")

MODEL_SONNET = "claude-sonnet-4-20250514"

# Source folders to monitor for new content
SOURCE_FOLDERS = {
    "Books":         os.path.join(VAULT_ROOT, "Books"),
    "Quotes":        os.path.join(VAULT_ROOT, "Quotes"),
    "Short reads":   os.path.join(VAULT_ROOT, "Short reads"),
    "Authors":       os.path.join(VAULT_ROOT, "Authors"),
    "Stoic":         os.path.join(VAULT_ROOT, "Stoic"),
    "John Vervaeke": os.path.join(VAULT_ROOT, "John Vervaeke"),
    "meaning crisis": os.path.join(VAULT_ROOT, "meaning crisis"),
    "my writings":   os.path.join(VAULT_ROOT, "my writings"),
    "Inbox":         os.path.join(VAULT_ROOT, "Alicia", "Inbox"),
}

# Folders to index for the wiki index
INDEX_FOLDERS = {
    "Synthesis":      SYNTHESIS_DIR,
    "Concepts":       os.path.join(ALICIA_DIR, "Knowledge Vault", "Concepts"),
    "Research":       os.path.join(ALICIA_DIR, "Knowledge Vault", "Research"),
    "Frameworks":     os.path.join(WISDOM_DIR, "Frameworks"),
    "Principles":     os.path.join(WISDOM_DIR, "Principles"),
    "Contradictions": os.path.join(WISDOM_DIR, "Contradictions"),
    "Podcasts":       os.path.join(WISDOM_DIR, "Podcasts"),
    "Alicia Notes":   ALICIA_WISDOM_DIR,
}

# Excluded from scanning
# Dirs excluded from ingest. Generic defaults only — users extend
# in their own config for personal subfolders.
EXCLUDED_DIRS = {'.obsidian', '.trash', '.git', '__pycache__', 'templates'}

# The 8 knowledge clusters for context
CLUSTERS = [
    "Quality", "Self-Mastery", "Environment", "Measurement",
    "Relationships", "Compounding", "Technology & Humanity", "Depth of Knowing",
]


# ── State Management ──────────────────────────────────────────────────────────

def load_ingest_state() -> dict:
    """Load the last-known file state (path → mtime mapping)."""
    if os.path.exists(INGEST_STATE_FILE):
        try:
            with open(INGEST_STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_ingest_state(state: dict):
    """Persist the current file state."""
    atomic_write_json(INGEST_STATE_FILE, state)


# ── Detection ─────────────────────────────────────────────────────────────────

def scan_for_new_sources(limit: int = 10) -> list:
    """
    Scan source folders and return list of new or modified files
    since last scan. Each item: {path, folder, name, is_new}.
    """
    state = load_ingest_state()
    new_sources = []

    for folder_name, folder_path in SOURCE_FOLDERS.items():
        if not os.path.exists(folder_path):
            continue

        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]

            for fname in files:
                if not fname.endswith(".md"):
                    continue

                filepath = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(filepath)
                    prev_mtime = state.get(filepath)

                    if prev_mtime is None or mtime > prev_mtime:
                        # Check minimum content length
                        with open(filepath, encoding="utf-8") as fh:
                            content = fh.read()
                        if len(content.strip()) < 50:
                            continue

                        new_sources.append({
                            "path": filepath,
                            "folder": folder_name,
                            "name": fname.replace(".md", ""),
                            "is_new": prev_mtime is None,
                            "mtime": mtime,
                        })

                        if len(new_sources) >= limit:
                            return new_sources
                except Exception:
                    continue

    return new_sources


def update_state_for_all_sources():
    """Snapshot current state of all source folders (for initial baseline)."""
    state = {}
    for folder_name, folder_path in SOURCE_FOLDERS.items():
        if not os.path.exists(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                filepath = os.path.join(root, fname)
                try:
                    state[filepath] = os.path.getmtime(filepath)
                except Exception:
                    continue
    save_ingest_state(state)
    return len(state)


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_note(filepath: str) -> str:
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def write_note(filepath: str, content: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def make_deep_link(filepath: str) -> str:
    relative = filepath.replace(VAULT_ROOT + "/", "")
    encoded = quote(relative, safe="/")
    return f"obsidian://open?vault={VAULT_NAME}&file={encoded}"


def extract_wikilinks(content: str) -> list:
    """Extract all [[wikilink]] targets from content."""
    return re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', content)


def find_synthesis_notes() -> list:
    """Return list of (filepath, name, content) for all synthesis notes."""
    notes = []
    if not os.path.exists(SYNTHESIS_DIR):
        return notes
    for fname in os.listdir(SYNTHESIS_DIR):
        if not fname.endswith(".md"):
            continue
        fp = os.path.join(SYNTHESIS_DIR, fname)
        content = read_note(fp)
        if content:
            notes.append((fp, fname.replace(".md", ""), content))
    return notes


def find_concept_notes() -> list:
    """Return list of (filepath, name, content) for concept notes."""
    notes = []
    concept_dir = os.path.join(ALICIA_DIR, "Knowledge Vault", "Concepts")
    if not os.path.exists(concept_dir):
        return notes
    for fname in os.listdir(concept_dir):
        if not fname.endswith(".md"):
            continue
        fp = os.path.join(concept_dir, fname)
        content = read_note(fp)
        if content:
            notes.append((fp, fname.replace(".md", ""), content))
    return notes


# ── Ingest Step 1: Summarize ─────────────────────────────────────────────────

SUMMARIZE_SYSTEM = f"""You are Alicia, an intelligence agent that maintains {USER_NAME}'s knowledge vault.

You are processing a new source that has entered the vault. Your job is to extract the key information for integration into the knowledge base.

Return a JSON object with:
{{
  "summary": "2-3 sentence summary of the core ideas",
  "key_concepts": ["concept1", "concept2", ...],  // 3-7 key concepts/ideas
  "thinkers": ["name1", "name2", ...],  // authors/thinkers mentioned or relevant
  "clusters": ["cluster1", ...],  // which of the 8 knowledge clusters this relates to
  "claims": ["claim1", "claim2", ...],  // 2-5 specific claims or insights that could be cross-referenced
  "potential_links": ["existing note name", ...]  // vault notes this should link to (use your best guess)
}}

The 8 knowledge clusters are: Quality, Self-Mastery, Environment, Measurement, Relationships, Compounding, Technology & Humanity, Depth of Knowing.

Return ONLY valid JSON, no markdown fences."""


def summarize_source(name: str, content: str, folder: str) -> dict:
    """Read a source and extract structured summary for integration."""
    truncated = content[:3000]  # Keep within context limits

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=800,
            system=SUMMARIZE_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Source folder: {folder}\nNote title: {name}\n\nContent:\n{truncated}"
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        log.error(f"Summarize failed for {name}: {e}")
        return {
            "summary": "",
            "key_concepts": [],
            "thinkers": [],
            "clusters": [],
            "claims": [],
            "potential_links": [],
        }


# ── Ingest Step 2: Update Synthesis Notes ─────────────────────────────────────

UPDATE_SYNTHESIS_SYSTEM = f"""You are Alicia. A new source has entered {USER_NAME}'s vault. You're checking if an existing synthesis note should be updated to reference this new source.

You'll receive:
- The new source's summary and key concepts
- An existing synthesis note's content

If the new source is relevant to this synthesis note, return a JSON object:
{{
  "relevant": true,
  "update_section": "A 1-2 sentence addition to weave into the synthesis note, referencing the new source with a [[wikilink]]",
  "where": "after which existing paragraph or section this should be added (quote first 5 words)"
}}

If the new source is NOT relevant, return:
{{"relevant": false}}

Be selective — only flag genuine conceptual connections, not superficial keyword overlap.
Return ONLY valid JSON."""


def update_synthesis_notes(source_name: str, summary: dict) -> list:
    """Check all synthesis notes and update those relevant to the new source."""
    updates = []
    synthesis_notes = find_synthesis_notes()

    if not synthesis_notes or not summary.get("key_concepts"):
        return updates

    source_context = (
        f"New source: [[{source_name}]]\n"
        f"Summary: {summary.get('summary', '')}\n"
        f"Key concepts: {', '.join(summary.get('key_concepts', []))}\n"
        f"Claims: {'; '.join(summary.get('claims', []))}\n"
        f"Clusters: {', '.join(summary.get('clusters', []))}"
    )

    for filepath, note_name, content in synthesis_notes:
        # Quick relevance filter: check if any key concept appears in the note
        content_lower = content.lower()
        concepts_lower = [c.lower() for c in summary.get("key_concepts", [])]
        clusters_lower = [c.lower() for c in summary.get("clusters", [])]

        has_overlap = any(c in content_lower for c in concepts_lower)
        has_cluster_overlap = any(c in content_lower for c in clusters_lower)

        if not has_overlap and not has_cluster_overlap:
            continue

        # Ask Sonnet if this synthesis note should be updated
        try:
            response = client.messages.create(
                model=MODEL_SONNET,
                max_tokens=400,
                system=UPDATE_SYNTHESIS_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"{source_context}\n\n---\n\n"
                        f"Existing synthesis note: [[{note_name}]]\n\n{content[:2000]}"
                    )
                }]
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            result = json.loads(raw)

            if result.get("relevant"):
                update_text = result.get("update_section", "")
                if update_text:
                    # Append the update to the synthesis note
                    timestamp = datetime.now().strftime("%Y-%m-%d")
                    addition = f"\n\n> *[{timestamp} — updated via ingest of [[{source_name}]]]*\n{update_text}\n"
                    updated_content = content.rstrip() + addition
                    write_note(filepath, updated_content)

                    # Close the circulatory loop (Wisdom Engine · Layer 1).
                    # An ingest update may pull in new source wikilinks — re-run
                    # the Finalizer to catch them. Idempotent + non-blocking.
                    try:
                        from myalicia.skills.synthesis_finalizer import finalize as _finalize_synthesis
                        _finalize_synthesis(filepath, skip_surfacings=True)
                    except Exception as e:
                        log.warning(f"synthesis_finalizer failed for {note_name}: {e}")

                    updates.append({
                        "synthesis_note": note_name,
                        "update": update_text,
                        "deep_link": make_deep_link(filepath),
                    })
                    log.info(f"Updated synthesis note: {note_name} with reference to {source_name}")

        except Exception as e:
            log.warning(f"Failed to check synthesis note {note_name}: {e}")
            continue

    return updates


# ── Ingest Step 3: Update Entity/Concept Pages ───────────────────────────────

UPDATE_ENTITY_SYSTEM = f"""You are Alicia. A new source has entered {USER_NAME}'s vault. You need to update an existing concept/entity page to reference this new source.

Return a JSON object:
{{
  "relevant": true,
  "addition": "1-2 sentences to add, referencing the new source with [[wikilink]]. Should enrich the concept page with the new perspective or data point."
}}

Or if not relevant: {{"relevant": false}}

Return ONLY valid JSON."""


def update_entity_pages(source_name: str, summary: dict) -> list:
    """Update concept/entity pages that relate to the new source."""
    updates = []
    concept_notes = find_concept_notes()

    if not concept_notes or not summary.get("key_concepts"):
        return updates

    source_context = (
        f"New source: [[{source_name}]]\n"
        f"Summary: {summary.get('summary', '')}\n"
        f"Key concepts: {', '.join(summary.get('key_concepts', []))}"
    )

    for filepath, note_name, content in concept_notes:
        # Quick filter: does any key concept match this note's name?
        note_lower = note_name.lower()
        concepts_lower = [c.lower() for c in summary.get("key_concepts", [])]

        if not any(c in note_lower or note_lower in c for c in concepts_lower):
            continue

        try:
            response = client.messages.create(
                model=MODEL_SONNET,
                max_tokens=300,
                system=UPDATE_ENTITY_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"{source_context}\n\n---\n\n"
                        f"Concept page: [[{note_name}]]\n\n{content[:1500]}"
                    )
                }]
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            result = json.loads(raw)

            if result.get("relevant") and result.get("addition"):
                timestamp = datetime.now().strftime("%Y-%m-%d")
                addition = f"\n\n> *[{timestamp} — via [[{source_name}]]]*\n{result['addition']}\n"
                updated_content = content.rstrip() + addition
                write_note(filepath, updated_content)

                updates.append({
                    "concept": note_name,
                    "addition": result["addition"],
                    "deep_link": make_deep_link(filepath),
                })
                log.info(f"Updated concept page: {note_name}")

        except Exception as e:
            log.warning(f"Failed to update concept {note_name}: {e}")
            continue

    return updates


# ── Ingest Step 4: Contradiction Check ────────────────────────────────────────

CONTRADICTION_SYSTEM = f"""You are Alicia. A new source has entered {USER_NAME}'s vault. Check if any of its claims contradict existing knowledge.

You'll receive the new source's claims and a selection of existing vault content.

If you find contradictions, return:
{{
  "contradictions": [
    {{
      "new_claim": "what the new source says",
      "existing_claim": "what the vault currently says",
      "existing_note": "name of the note with the existing claim",
      "severity": "minor|moderate|major",
      "note": "brief explanation of the tension"
    }}
  ]
}}

If no contradictions: {{"contradictions": []}}

Be thoughtful — genuine intellectual tensions are valuable, not superficial wording differences.
Return ONLY valid JSON."""


def check_contradictions(source_name: str, summary: dict) -> list:
    """Check if new source contradicts existing vault knowledge."""
    claims = summary.get("claims", [])
    if not claims:
        return []

    # Gather relevant existing content for comparison
    synthesis_notes = find_synthesis_notes()
    existing_context = []
    for _, note_name, content in synthesis_notes[:15]:  # Check up to 15 synthesis notes
        existing_context.append(f"[[{note_name}]]: {content[:300]}")

    if not existing_context:
        return []

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=600,
            system=CONTRADICTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"New source: [[{source_name}]]\n"
                    f"Claims:\n" + "\n".join(f"- {c}" for c in claims) +
                    f"\n\n---\n\nExisting vault knowledge:\n\n" +
                    "\n\n".join(existing_context[:5000])
                )
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        result = json.loads(raw)

        contradictions = result.get("contradictions", [])

        # Write contradictions to vault if any found
        if contradictions:
            contradiction_dir = os.path.join(WISDOM_DIR, "Contradictions")
            os.makedirs(contradiction_dir, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            filename = f"{date}-{source_name[:40]}-contradictions.md"
            filepath = os.path.join(contradiction_dir, filename)

            lines = [f"# Contradictions from [[{source_name}]]\n"]
            lines.append(f"*Detected: {date}*\n")
            for c in contradictions:
                lines.append(f"## {c.get('severity', 'unknown').title()} tension\n")
                lines.append(f"**New claim** ([[{source_name}]]): {c.get('new_claim', '')}\n")
                lines.append(f"**Existing claim** ([[{c.get('existing_note', '?')}]]): {c.get('existing_claim', '')}\n")
                lines.append(f"*{c.get('note', '')}*\n")
            write_note(filepath, "\n".join(lines))

            for c in contradictions:
                c["deep_link"] = make_deep_link(filepath)

        return contradictions

    except Exception as e:
        log.warning(f"Contradiction check failed for {source_name}: {e}")
        return []


# ── Index: Structured Catalog ─────────────────────────────────────────────────

def rebuild_index() -> int:
    """Rebuild Wisdom/index.md — a structured catalog of all wiki pages."""
    os.makedirs(WISDOM_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    sections = []
    total_pages = 0

    for category, folder_path in INDEX_FOLDERS.items():
        if not os.path.exists(folder_path):
            continue

        entries = []
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in sorted(files):
                if not fname.endswith(".md"):
                    continue
                filepath = os.path.join(root, fname)
                name = fname.replace(".md", "")
                content = read_note(filepath)

                # Extract first meaningful line as summary
                summary_line = ""
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("---") and not line.startswith("*") and len(line) > 20:
                        summary_line = line[:120]
                        if len(line) > 120:
                            summary_line += "..."
                        break

                # Count wikilinks as a rough connectivity metric
                link_count = len(extract_wikilinks(content))

                entries.append(f"- [[{name}]] — {summary_line} ({link_count} links)")
                total_pages += 1

        if entries:
            sections.append(f"## {category} ({len(entries)})\n\n" + "\n".join(entries))

    # Also count source folders
    source_counts = {}
    for folder_name, folder_path in SOURCE_FOLDERS.items():
        if os.path.exists(folder_path):
            count = sum(1 for _, _, files in os.walk(folder_path)
                       for f in files if f.endswith(".md"))
            if count > 0:
                source_counts[folder_name] = count

    source_section = "## Source Folders\n\n"
    for name, count in sorted(source_counts.items()):
        source_section += f"- **{name}**: {count} notes\n"

    index_content = (
        f"# Vault Index\n\n"
        f"*Auto-maintained by Alicia. Last updated: {date}*\n"
        f"*Total wiki pages: {total_pages} | Source notes: {sum(source_counts.values())}*\n\n"
        f"---\n\n"
        + "\n\n---\n\n".join(sections)
        + f"\n\n---\n\n{source_section}"
    )

    write_note(INDEX_FILE, index_content)
    log.info(f"Rebuilt index.md: {total_pages} wiki pages cataloged")
    return total_pages


# ── Log: Chronological Timeline ───────────────────────────────────────────────

def append_log(event_type: str, title: str, details: str = ""):
    """Append a timestamped entry to Wisdom/log.md."""
    os.makedirs(WISDOM_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"## [{timestamp}] {event_type} | {title}\n"
    if details:
        entry += f"{details}\n"
    entry += "\n"

    # Create log file if it doesn't exist
    if not os.path.exists(LOG_FILE):
        header = (
            "# Vault Log\n\n"
            "*Chronological record of vault evolution. Auto-maintained by Alicia.*\n"
            "*Grep-parseable: `grep \"^## \\[\" log.md | tail -10`*\n\n"
            "---\n\n"
        )
        write_note(LOG_FILE, header + entry)
    else:
        # Append to existing log
        existing = read_note(LOG_FILE)
        write_note(LOG_FILE, existing.rstrip() + "\n\n" + entry)

    log.info(f"Log appended: [{event_type}] {title}")


# ── Main Ingest Pipeline ─────────────────────────────────────────────────────

def ingest_single_source(source: dict) -> dict:
    """
    Full cascading ingest for a single source.
    Returns a report of all changes made.
    """
    filepath = source["path"]
    name = source["name"]
    folder = source["folder"]
    content = read_note(filepath)

    log.info(f"Ingesting: {name} from {folder}")

    report = {
        "name": name,
        "folder": folder,
        "is_new": source.get("is_new", False),
        "deep_link": make_deep_link(filepath),
        "summary": {},
        "synthesis_updates": [],
        "entity_updates": [],
        "contradictions": [],
        "pages_touched": 0,
    }

    # Step 1: Summarize the source
    summary = summarize_source(name, content, folder)
    report["summary"] = summary

    if not summary.get("summary"):
        log.warning(f"Empty summary for {name}, skipping cascade")
        return report

    # Step 2: Update synthesis notes
    synthesis_updates = update_synthesis_notes(name, summary)
    report["synthesis_updates"] = synthesis_updates

    # Step 3: Update entity/concept pages
    entity_updates = update_entity_pages(name, summary)
    report["entity_updates"] = entity_updates

    # Step 4: Check for contradictions
    contradictions = check_contradictions(name, summary)
    report["contradictions"] = contradictions

    # Count total pages touched
    report["pages_touched"] = (
        len(synthesis_updates) +
        len(entity_updates) +
        (1 if contradictions else 0)
    )

    # Step 5: Log the ingest
    details_parts = []
    if summary.get("key_concepts"):
        details_parts.append(f"Concepts: {', '.join(summary['key_concepts'][:5])}")
    if summary.get("clusters"):
        details_parts.append(f"Clusters: {', '.join(summary['clusters'])}")
    if synthesis_updates:
        updated_names = [u["synthesis_note"] for u in synthesis_updates]
        details_parts.append(f"Updated synthesis: {', '.join(updated_names)}")
    if entity_updates:
        updated_names = [u["concept"] for u in entity_updates]
        details_parts.append(f"Updated concepts: {', '.join(updated_names)}")
    if contradictions:
        details_parts.append(f"Contradictions found: {len(contradictions)}")

    event_type = "ingest_new" if source.get("is_new") else "ingest_update"
    append_log(event_type, f"[[{name}]] ({folder})", "\n".join(f"- {d}" for d in details_parts))

    log.info(f"Ingest complete: {name} — {report['pages_touched']} pages touched")
    return report


def run_ingest_scan(limit: int = 10) -> dict:
    """
    Main entry point: scan for new sources, ingest each one,
    update the index, return a full report.
    """
    log.info("Starting ingest scan...")
    start = time.time()

    # Detect new sources
    new_sources = scan_for_new_sources(limit=limit)

    if not new_sources:
        log.info("No new sources detected")
        return {
            "new_sources": 0,
            "reports": [],
            "total_pages_touched": 0,
            "duration_sec": round(time.time() - start, 1),
        }

    log.info(f"Found {len(new_sources)} new/modified sources")

    # Ingest each source
    reports = []
    for source in new_sources:
        try:
            report = ingest_single_source(source)
            reports.append(report)
        except Exception as e:
            log.error(f"Ingest failed for {source['name']}: {e}", exc_info=True)
            reports.append({
                "name": source["name"],
                "folder": source["folder"],
                "error": str(e),
            })

    # Update ingest state for successfully processed sources
    state = load_ingest_state()
    for source in new_sources:
        state[source["path"]] = source["mtime"]
    save_ingest_state(state)

    # Rebuild index after all ingests
    try:
        index_count = rebuild_index()
        append_log("index_rebuild", f"Rebuilt index.md ({index_count} pages)")
    except Exception as e:
        log.error(f"Index rebuild failed: {e}")

    total_touched = sum(r.get("pages_touched", 0) for r in reports)
    duration = round(time.time() - start, 1)

    log.info(f"Ingest scan complete: {len(reports)} sources, {total_touched} pages touched, {duration}s")

    return {
        "new_sources": len(new_sources),
        "reports": reports,
        "total_pages_touched": total_touched,
        "duration_sec": duration,
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def format_ingest_report(result: dict) -> str:
    """
    Format ingest scan result as a compact single-message rollup for Telegram.
    Keeps it short: one line per source, total stats, highlights only.
    """
    if result["new_sources"] == 0:
        return "📭 *Ingest scan* — no new sources detected."

    n_sources = result["new_sources"]
    n_pages = result["total_pages_touched"]
    duration = result["duration_sec"]

    # Count synthesis updates, entity updates, contradictions across all reports
    n_synthesis = 0
    n_entities = 0
    n_contradictions = 0
    source_names = []
    errors = []

    for report in result.get("reports", []):
        if report.get("error"):
            errors.append(report["name"])
            continue
        status = "🆕" if report.get("is_new") else "📝"
        source_names.append(f"{status} {report['name']}")
        n_synthesis += len(report.get("synthesis_updates", []))
        n_entities += len(report.get("entity_updates", []))
        n_contradictions += len(report.get("contradictions", []))

    # Build compact message
    lines = [f"📥 *Vault Ingest* — {n_sources} source(s), {n_pages} pages, {duration}s"]

    # Source names on one line
    if source_names:
        lines.append(", ".join(source_names))

    # Highlights in a compact row (only non-zero)
    highlights = []
    if n_synthesis > 0:
        highlights.append(f"{n_synthesis} synthesis updated")
    if n_entities > 0:
        highlights.append(f"{n_entities} concepts updated")
    if n_contradictions > 0:
        highlights.append(f"⚡ {n_contradictions} contradiction(s)")
    if highlights:
        lines.append(" · ".join(highlights))

    if errors:
        lines.append(f"❌ Errors: {', '.join(errors)}")

    return "\n".join(lines)


def format_daily_ingest_rollup(accumulated: list) -> str:
    """
    Format a full day's ingest results into a single contextual Telegram message.
    Takes a list of run_ingest_scan() result dicts accumulated throughout the day.
    """
    # Flatten all reports across all scan runs
    all_reports = []
    total_duration = 0
    for result in accumulated:
        all_reports.extend(result.get("reports", []))
        total_duration += result.get("duration_sec", 0)

    if not all_reports:
        return ""  # Nothing to report

    # Group sources by folder
    by_folder = {}
    all_concepts = set()
    all_clusters = set()
    n_synthesis = 0
    n_entities = 0
    n_contradictions = 0
    errors = []
    highlights = []

    for report in all_reports:
        if report.get("error"):
            errors.append(report["name"])
            continue

        folder = report.get("folder", "Unknown")
        name = report.get("name", "?")
        by_folder.setdefault(folder, []).append(name)

        summary = report.get("summary", {})
        for c in summary.get("key_concepts", []):
            all_concepts.add(c)
        for c in summary.get("clusters", []):
            all_clusters.add(c)

        synth_updates = report.get("synthesis_updates", [])
        n_synthesis += len(synth_updates)
        n_entities += len(report.get("entity_updates", []))
        n_contradictions += len(report.get("contradictions", []))

        # Collect synthesis update highlights
        for su in synth_updates:
            note_name = su.get("synthesis_note", "")
            if note_name:
                highlights.append(f"Updated [[{note_name}]] via {name}")

    n_total = sum(len(names) for names in by_folder.values())

    # Build the message
    lines = [f"📥 *Daily Vault Ingest* — {n_total} source{'s' if n_total != 1 else ''} processed"]
    lines.append("")

    # Sources grouped by folder, with short names
    for folder, names in sorted(by_folder.items()):
        # Shorten names that share a common prefix (e.g. OnQuality-55, -71, -100)
        if len(names) > 3:
            # Find common prefix
            prefix = os.path.commonprefix(names)
            if len(prefix) > 3:
                short = [names[0]] + [n[len(prefix):] if n.startswith(prefix) else n for n in names[1:]]
                lines.append(f"📚 *{folder}*: {', '.join(short)}")
            else:
                lines.append(f"📚 *{folder}*: {', '.join(names)}")
        else:
            lines.append(f"📚 *{folder}*: {', '.join(names)}")

    # Concepts and clusters
    if all_clusters:
        lines.append(f"\n🕸 *Clusters touched:* {', '.join(sorted(all_clusters))}")
    if all_concepts:
        # Show top 8 concepts to keep it readable
        concept_list = sorted(all_concepts)[:8]
        suffix = f" (+{len(all_concepts) - 8} more)" if len(all_concepts) > 8 else ""
        lines.append(f"🧠 *Key concepts:* {', '.join(concept_list)}{suffix}")

    # Impact stats
    impact = []
    if n_synthesis > 0:
        impact.append(f"{n_synthesis} synthesis note{'s' if n_synthesis != 1 else ''} updated")
    if n_entities > 0:
        impact.append(f"{n_entities} concept page{'s' if n_entities != 1 else ''} enriched")
    if n_contradictions > 0:
        impact.append(f"⚡ {n_contradictions} contradiction{'s' if n_contradictions != 1 else ''} detected")
    if impact:
        lines.append(f"\n🔗 {' · '.join(impact)}")
    else:
        lines.append(f"\n🔗 No existing pages updated (sources indexed for future synthesis)")

    # Top 3 highlights
    if highlights:
        lines.append("")
        lines.append("*Highlights:*")
        for h in highlights[:3]:
            lines.append(f"  • {h}")
        if len(highlights) > 3:
            lines.append(f"  _…and {len(highlights) - 3} more updates_")

    if errors:
        lines.append(f"\n❌ Errors: {', '.join(errors)}")

    return "\n".join(lines)


def format_index_status() -> str:
    """Quick status of the index for dashboard/reporting."""
    if not os.path.exists(INDEX_FILE):
        return "Index not yet built. Run ingest scan to create."
    content = read_note(INDEX_FILE)
    lines = content.split("\n")
    # Extract the status line
    for line in lines:
        if "Total wiki pages" in line:
            return line.strip("*").strip()
    return f"Index exists ({len(lines)} lines)"


# ── Initialize ────────────────────────────────────────────────────────────────

def initialize_ingest():
    """
    First-time setup: snapshot current state of all source folders
    so the next scan only picks up truly new files.
    Also build the initial index and log.
    """
    count = update_state_for_all_sources()
    index_count = rebuild_index()
    append_log("init", f"Ingest pipeline initialized — {count} source files baselined, {index_count} wiki pages indexed")
    return {
        "sources_baselined": count,
        "wiki_pages_indexed": index_count,
    }
