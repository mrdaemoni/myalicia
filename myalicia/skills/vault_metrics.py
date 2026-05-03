#!/usr/bin/env python3
"""
Vault Metrics — Knowledge quality tracking for the user's Obsidian vault.

Computes:
- Synthesis note count and recent additions
- Cross-cluster bridge coverage (out of 28 possible cluster pairs)
- Source participation rate (% of vault pages connected to synthesis)
- the user's voice ratio (% of synthesis notes citing his own writing)
- Knowledge level (1-6 based on thresholds)

Designed to be called from vault_intelligence.py for the morning Telegram message.
"""

import os
import re
import csv
from datetime import datetime, timedelta
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

VAULT_ROOT = str(config.vault.root)
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")
RESULTS_TSV = os.path.join(VAULT_ROOT, "Alicia", "Bridge", "synthesis_results.tsv")

# The 8 knowledge clusters
CLUSTERS = [
    "Quality",
    "Mastery",
    "Environment",
    "Measurement",
    "Relationships",
    "Compounding",
    "Technology",
    "Depth",
]

# All 28 possible cluster pairs
ALL_CLUSTER_PAIRS = set()
for i, c1 in enumerate(CLUSTERS):
    for c2 in CLUSTERS[i + 1:]:
        ALL_CLUSTER_PAIRS.add(frozenset([c1, c2]))

# the user's own writing folders (relative to vault root)
HECTORS_VOICE_MARKERS = [
    "writing/",
    "Writing drafts/",
    f"{USER_NAME}",
    "my writings/",
]

# Level definitions — maps to the podcast season arc
LEVELS = [
    {
        "level": 1,
        "name": "Islands",
        "emoji": "🏝",
        "description": "Fragmented knowledge. Notes exist but don't talk to each other.",
        "min_synthesis": 0,
        "min_cluster_pairs": 0,
        "min_coverage": 0.0,
    },
    {
        "level": 2,
        "name": "Bridges",
        "emoji": "🌉",
        "description": "First connections forming. You're starting to see across books.",
        "min_synthesis": 5,
        "min_cluster_pairs": 3,
        "min_coverage": 0.05,
    },
    {
        "level": 3,
        "name": "Clusters",
        "emoji": "🕸",
        "description": "The graph gains density. Multiple paths between ideas.",
        "min_synthesis": 15,
        "min_cluster_pairs": 12,
        "min_coverage": 0.30,
    },
    {
        "level": 4,
        "name": "Superhighways",
        "emoji": "⚡",
        "description": "Cross-cluster bridges everywhere. Knowledge becomes participatory.",
        "min_synthesis": 30,
        "min_cluster_pairs": 20,
        "min_coverage": 0.50,
    },
    {
        "level": 5,
        "name": "Voice",
        "emoji": "🔥",
        "description": "Your own writing weaves through the graph. The loop closes.",
        "min_synthesis": 60,
        "min_cluster_pairs": 24,
        "min_coverage": 0.70,
    },
    {
        "level": 6,
        "name": "Generative",
        "emoji": "🧬",
        "description": "The vault thinks for itself. Alicia emerges.",
        "min_synthesis": 120,
        "min_cluster_pairs": 27,
        "min_coverage": 0.85,
    },
]


def count_synthesis_notes() -> int:
    """Count total synthesis notes in the vault."""
    if not os.path.exists(SYNTHESIS_DIR):
        return 0
    return len([f for f in os.listdir(SYNTHESIS_DIR) if f.endswith(".md")])


def get_recent_synthesis_notes(days: int = 1) -> list:
    """Get synthesis notes created in the last N days."""
    if not os.path.exists(SYNTHESIS_DIR):
        return []
    cutoff = datetime.now().timestamp() - (days * 86400)
    recent = []
    for f in os.listdir(SYNTHESIS_DIR):
        if not f.endswith(".md"):
            continue
        fp = os.path.join(SYNTHESIS_DIR, f)
        if os.path.getmtime(fp) >= cutoff:
            recent.append(f.replace(".md", ""))
    return recent


def read_synthesis_log() -> list:
    """Read the synthesis results TSV log."""
    if not os.path.exists(RESULTS_TSV):
        return []
    rows = []
    try:
        with open(RESULTS_TSV, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(row)
    except Exception:
        return []
    return rows


def get_cluster_pairs_bridged() -> tuple:
    """
    Read all synthesis notes and determine which cluster pairs are bridged.
    Returns (set of bridged pairs, total possible pairs).
    """
    if not os.path.exists(SYNTHESIS_DIR):
        return set(), 28

    bridged_pairs = set()
    cluster_pattern = re.compile(r"#theme/(\w+)")
    cluster_map = {
        "quality": "Quality",
        "mastery": "Mastery",
        "environment": "Environment",
        "measurement": "Measurement",
        "relationships": "Relationships",
        "compounding": "Compounding",
        "technology": "Technology",
        "depth": "Depth",
    }

    for f in os.listdir(SYNTHESIS_DIR):
        if not f.endswith(".md"):
            continue
        fp = os.path.join(SYNTHESIS_DIR, f)
        try:
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            continue

        themes = cluster_pattern.findall(content)
        mapped = set()
        for t in themes:
            if t.lower() in cluster_map:
                mapped.add(cluster_map[t.lower()])

        # Generate pairs from this note's clusters
        mapped = list(mapped)
        for i, c1 in enumerate(mapped):
            for c2 in mapped[i + 1:]:
                bridged_pairs.add(frozenset([c1, c2]))

    return bridged_pairs, len(ALL_CLUSTER_PAIRS)


def get_source_coverage() -> tuple:
    """
    Count what % of vault source pages are connected to at least one synthesis note.
    Returns (connected_count, total_sources, percentage).
    """
    # Gather all wikilinks from synthesis notes
    synthesis_links = set()
    if os.path.exists(SYNTHESIS_DIR):
        for f in os.listdir(SYNTHESIS_DIR):
            if not f.endswith(".md"):
                continue
            fp = os.path.join(SYNTHESIS_DIR, f)
            try:
                with open(fp, encoding="utf-8") as fh:
                    content = fh.read()
                links = re.findall(r"\[\[([^\]]+)\]\]", content)
                synthesis_links.update(links)
            except Exception:
                continue

    # Count total source pages across key folders
    source_folders = ["Books", "Quotes", "writing", "Writing drafts", "Short reads"]
    total_sources = 0
    connected_sources = 0

    for folder in source_folders:
        folder_path = os.path.join(VAULT_ROOT, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if not f.endswith(".md"):
                    continue
                total_sources += 1
                # Check if this file is referenced by any synthesis note
                name_no_ext = f.replace(".md", "")
                rel_path = os.path.relpath(os.path.join(root, f), VAULT_ROOT)
                # Check various link formats
                if any(
                    name_no_ext in link or rel_path.replace(".md", "") in link
                    for link in synthesis_links
                ):
                    connected_sources += 1

    # Also count root-level concept notes
    if os.path.exists(VAULT_ROOT):
        for f in os.listdir(VAULT_ROOT):
            if f.endswith(".md") and os.path.isfile(os.path.join(VAULT_ROOT, f)):
                total_sources += 1
                name_no_ext = f.replace(".md", "")
                if any(name_no_ext in link for link in synthesis_links):
                    connected_sources += 1

    pct = (connected_sources / total_sources * 100) if total_sources > 0 else 0
    return connected_sources, total_sources, pct


def get_voice_ratio() -> tuple:
    """
    What % of synthesis notes reference the user's own writing?
    Returns (count_with_voice, total_synthesis, percentage).
    """
    if not os.path.exists(SYNTHESIS_DIR):
        return 0, 0, 0.0

    total = 0
    with_voice = 0
    for f in os.listdir(SYNTHESIS_DIR):
        if not f.endswith(".md"):
            continue
        fp = os.path.join(SYNTHESIS_DIR, f)
        try:
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            continue
        total += 1
        # Check if any of the user's voice markers appear
        if any(marker.lower() in content.lower() for marker in HECTORS_VOICE_MARKERS):
            with_voice += 1

    pct = (with_voice / total * 100) if total > 0 else 0
    return with_voice, total, pct


def determine_level(synthesis_count: int, cluster_pairs: int, coverage_pct: float) -> dict:
    """
    Determine current knowledge level based on metrics.
    Must meet ALL thresholds to qualify for a level.
    Returns the level dict plus progress toward next level.
    """
    current = LEVELS[0]
    for lvl in LEVELS:
        if (
            synthesis_count >= lvl["min_synthesis"]
            and cluster_pairs >= lvl["min_cluster_pairs"]
            and coverage_pct >= lvl["min_coverage"] * 100
        ):
            current = lvl
        else:
            break

    # Calculate progress to next level
    next_level = None
    progress = {}
    for lvl in LEVELS:
        if lvl["level"] == current["level"] + 1:
            next_level = lvl
            break

    if next_level:
        progress = {
            "synthesis": min(100, int(synthesis_count / max(1, next_level["min_synthesis"]) * 100)),
            "cluster_pairs": min(100, int(cluster_pairs / max(1, next_level["min_cluster_pairs"]) * 100)),
            "coverage": min(100, int(coverage_pct / max(0.01, next_level["min_coverage"] * 100) * 100)),
        }
        progress["overall"] = min(progress.values())

    return {
        "current": current,
        "next": next_level,
        "progress": progress,
    }


def compute_all_metrics() -> dict:
    """Compute all vault metrics. Main entry point."""
    synthesis_count = count_synthesis_notes()
    recent_notes = get_recent_synthesis_notes(days=1)
    log_entries = read_synthesis_log()
    bridged_pairs, total_pairs = get_cluster_pairs_bridged()
    connected, total_sources, coverage_pct = get_source_coverage()
    voice_count, voice_total, voice_pct = get_voice_ratio()
    level_info = determine_level(synthesis_count, len(bridged_pairs), coverage_pct)

    # Recent log entries (last 24h)
    recent_log = []
    cutoff = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for entry in log_entries:
        if entry.get("timestamp", "") >= cutoff:
            recent_log.append(entry)

    # Unbridged cluster pairs (opportunities)
    unbridged = ALL_CLUSTER_PAIRS - bridged_pairs
    unbridged_names = [" ↔ ".join(sorted(pair)) for pair in list(unbridged)[:5]]

    return {
        "synthesis_count": synthesis_count,
        "recent_notes": recent_notes,
        "recent_kept": [e for e in recent_log if e.get("status") == "keep"],
        "recent_discarded": [e for e in recent_log if e.get("status") == "discard"],
        "cluster_pairs_bridged": len(bridged_pairs),
        "cluster_pairs_total": total_pairs,
        "cluster_pairs_pct": int(len(bridged_pairs) / total_pairs * 100) if total_pairs > 0 else 0,
        "unbridged_opportunities": unbridged_names,
        "source_connected": connected,
        "source_total": total_sources,
        "source_coverage_pct": round(coverage_pct, 1),
        "voice_count": voice_count,
        "voice_total": voice_total,
        "voice_pct": round(voice_pct, 1),
        "level": level_info,
    }


def format_knowledge_dashboard(metrics: dict) -> str:
    """Format metrics as a Telegram-friendly dashboard string."""
    level = metrics["level"]["current"]
    next_lvl = metrics["level"]["next"]
    progress = metrics["level"].get("progress", {})

    lines = []

    # Level header
    lines.append(f"{level['emoji']} *Level {level['level']}: {level['name']}*")
    lines.append(f"_{level['description']}_\n")

    # Core metrics
    lines.append(f"🧠 Synthesis notes: *{metrics['synthesis_count']}*")
    lines.append(f"🔗 Cluster pairs bridged: *{metrics['cluster_pairs_bridged']}/{metrics['cluster_pairs_total']}* ({metrics['cluster_pairs_pct']}%)")
    lines.append(f"📡 Source coverage: *{metrics['source_connected']}/{metrics['source_total']}* ({metrics['source_coverage_pct']}%)")
    lines.append(f"🎙 Your voice in synthesis: *{metrics['voice_count']}/{metrics['voice_total']}* ({metrics['voice_pct']}%)")

    # New notes from overnight synthesis
    if metrics["recent_notes"]:
        lines.append(f"\n✨ *New synapses overnight:*")
        for title in metrics["recent_notes"][:4]:
            lines.append(f"  • _{title}_")
        kept = len(metrics.get("recent_kept", []))
        discarded = len(metrics.get("recent_discarded", []))
        if kept or discarded:
            lines.append(f"  _({kept} kept, {discarded} discarded)_")

    # Progress to next level
    if next_lvl and progress:
        lines.append(f"\n📈 *Progress to Level {next_lvl['level']} ({next_lvl['name']}):*")
        bar_synthesis = _progress_bar(progress.get("synthesis", 0))
        bar_pairs = _progress_bar(progress.get("cluster_pairs", 0))
        bar_coverage = _progress_bar(progress.get("coverage", 0))
        lines.append(f"  Synthesis: {bar_synthesis} {progress.get('synthesis', 0)}%")
        lines.append(f"  Bridges:   {bar_pairs} {progress.get('cluster_pairs', 0)}%")
        lines.append(f"  Coverage:  {bar_coverage} {progress.get('coverage', 0)}%")

    # Unbridged opportunities
    if metrics.get("unbridged_opportunities"):
        lines.append(f"\n🗺 *Unexplored bridges:*")
        for pair in metrics["unbridged_opportunities"][:3]:
            lines.append(f"  • {pair}")

    return "\n".join(lines)


def _progress_bar(pct: int, width: int = 10) -> str:
    """Generate a text progress bar."""
    filled = int(width * min(pct, 100) / 100)
    empty = width - filled
    return "▓" * filled + "░" * empty


METRICS_NOTE_PATH = os.path.join(VAULT_ROOT, "Alicia", "Alicia metrics towards wisdom.md")


def append_weekly_snapshot(metrics: dict = None) -> str:
    """
    Append a weekly snapshot to the Obsidian metrics tracking note.
    Called by the weekly scheduled task.
    Returns the snapshot text that was appended.
    """
    if metrics is None:
        metrics = compute_all_metrics()

    level = metrics["level"]["current"]
    next_lvl = metrics["level"]["next"]
    progress = metrics["level"].get("progress", {})

    today = datetime.now().strftime("%B %d, %Y")
    week_num = _get_week_number()

    lines = []
    lines.append(f"### Week {week_num} — {today}\n")
    lines.append(f"{level['emoji']} **Level {level['level']}: {level['name']}**\n")

    # Metrics table
    lines.append("| Metric | Value | Target (Next Level) | Progress |")
    lines.append("|--------|-------|---------------------|----------|")

    synth_bar = _progress_bar(progress.get("synthesis", 100))
    pairs_bar = _progress_bar(progress.get("cluster_pairs", 100))
    cov_bar = _progress_bar(progress.get("coverage", 100))

    next_synth = next_lvl["min_synthesis"] if next_lvl else "—"
    next_pairs = f"{next_lvl['min_cluster_pairs']}/28" if next_lvl else "—"
    next_cov = f"{int(next_lvl['min_coverage'] * 100)}%" if next_lvl else "—"

    synth_check = " ✅" if progress.get("synthesis", 0) >= 100 else ""
    pairs_check = " ✅" if progress.get("cluster_pairs", 0) >= 100 else ""
    cov_check = " ✅" if progress.get("coverage", 0) >= 100 else ""

    lines.append(f"| Synthesis notes | {metrics['synthesis_count']} | {next_synth} | {synth_bar} {progress.get('synthesis', 100)}%{synth_check} |")
    lines.append(f"| Cluster pairs bridged | {metrics['cluster_pairs_bridged']}/{metrics['cluster_pairs_total']} | {next_pairs} | {pairs_bar} {progress.get('cluster_pairs', 100)}%{pairs_check} |")
    lines.append(f"| Source coverage | {metrics['source_connected']}/{metrics['source_total']} ({metrics['source_coverage_pct']}%) | {next_cov} | {cov_bar} {progress.get('coverage', 100)}%{cov_check} |")
    lines.append(f"| Voice ratio | {metrics['voice_count']}/{metrics['voice_total']} ({metrics['voice_pct']}%) | — | — |")
    lines.append("")

    # Bottleneck
    if progress:
        bottleneck_name = min(progress, key=progress.get)
        bottleneck_map = {"synthesis": "Synthesis notes", "cluster_pairs": "Cluster pair coverage", "coverage": "Source coverage"}
        lines.append(f"**Bottleneck:** {bottleneck_map.get(bottleneck_name, bottleneck_name)} ({progress[bottleneck_name]}%)")
        lines.append("")

    # Unbridged
    if metrics.get("unbridged_opportunities"):
        lines.append("**Unbridged cluster pairs:**")
        for pair in metrics["unbridged_opportunities"]:
            lines.append(f"- {pair}")
        lines.append("")

    # Recent synthesis activity (last 7 days)
    kept = metrics.get("recent_kept", [])
    discarded = metrics.get("recent_discarded", [])
    if kept or discarded:
        lines.append(f"**This week's synthesis ({len(kept)} kept, {len(discarded)} discarded):**")
        for e in kept:
            score = e.get("score", "?")
            title = e.get("title", "untitled")
            notes = e.get("notes", "")
            lines.append(f'- ✅ "{title}" (score {score}) — {notes}')
        for e in discarded:
            score = e.get("score", "?")
            title = e.get("title", "untitled")
            notes = e.get("notes", "")
            lines.append(f'- ❌ "{title}" (score {score}) — {notes}')
        lines.append("")

    lines.append("---\n")

    snapshot_text = "\n".join(lines)

    # Append to the tracking note
    if os.path.exists(METRICS_NOTE_PATH):
        with open(METRICS_NOTE_PATH, "r", encoding="utf-8") as f:
            existing = f.read()
        # Insert before the Wisdom Schema footer
        if "*Wisdom themes:*" in existing:
            parts = existing.rsplit("---\n", 1)
            if len(parts) == 2 and "*Wisdom themes:*" in parts[1]:
                updated = parts[0] + snapshot_text + "\n---\n" + parts[1]
            else:
                updated = existing.rstrip() + "\n\n" + snapshot_text
        else:
            updated = existing.rstrip() + "\n\n" + snapshot_text
        with open(METRICS_NOTE_PATH, "w", encoding="utf-8") as f:
            f.write(updated)

    return snapshot_text


def _get_week_number() -> int:
    """
    Get the week number for this vault by counting existing snapshots.
    """
    if not os.path.exists(METRICS_NOTE_PATH):
        return 1
    try:
        with open(METRICS_NOTE_PATH, encoding="utf-8") as f:
            content = f.read()
        import re as _re
        weeks = _re.findall(r"### Week (\d+)", content)
        if weeks:
            return max(int(w) for w in weeks) + 1
        return 1
    except Exception:
        return 1
