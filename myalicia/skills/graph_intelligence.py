#!/usr/bin/env python3
"""
Alicia — Knowledge Graph Self-Organization

Makes the Obsidian vault self-aware: detects structural gaps,
predicts missing connections via embedding similarity, suggests
reorganization, and tracks graph health over time.

Based on:
- Ontology learning from LLMs (arXiv 2025)
- Knowledge graph completion via link prediction
- Existing vault-synthesis architecture
"""

import os
import re
import json
import logging
from datetime import datetime
from collections import Counter, defaultdict

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config

log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")
MEMORY_DIR = os.path.expanduser("~/alicia/memory")
GRAPH_REPORT_FILE = os.path.join(MEMORY_DIR, "graph_health.md")
LINK_SUGGESTIONS_FILE = os.path.join(MEMORY_DIR, "link_suggestions.json")

# Folders to exclude from graph analysis
EXCLUDED_FOLDERS = {'.obsidian', '.trash', 'DwH', 'Amazon', 'BITC', 'CIID', 'People', 'templates', 'Alejandra', 'Ana Julia', 'Benefits'}

# The 8 knowledge clusters
CLUSTERS = ["Quality", "Mastery", "Environment", "Measurement",
            "Relationships", "Compounding", "Technology", "Depth"]


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_graph() -> dict:
    """
    Build a graph representation of the vault.
    Returns dict with nodes (note paths) and edges (wikilinks).
    """
    nodes = {}  # name -> {path, links_out, links_in, word_count, folder}
    edges = []  # (source, target)

    for root, dirs, files in os.walk(VAULT_ROOT):
        # Skip excluded folders
        dirs[:] = [d for d in dirs if d not in EXCLUDED_FOLDERS and not d.startswith('.')]

        rel_root = os.path.relpath(root, VAULT_ROOT)
        folder = rel_root.split(os.sep)[0] if rel_root != '.' else 'root'

        for fname in files:
            if not fname.endswith('.md'):
                continue

            name = fname.replace('.md', '')
            path = os.path.join(root, fname)

            try:
                with open(path, encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            # Extract wikilinks
            links = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', content)
            word_count = len(content.split())

            nodes[name.lower()] = {
                "name": name,
                "path": path,
                "links_out": [l.lower().strip() for l in links],
                "links_in": [],
                "word_count": word_count,
                "folder": folder,
            }

    # Build reverse links
    for name, data in nodes.items():
        for target in data["links_out"]:
            if target in nodes:
                nodes[target]["links_in"].append(name)
                edges.append((name, target))

    return {"nodes": nodes, "edges": edges}


# ══════════════════════════════════════════════════════════════════════════════
# GAP DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_gaps() -> dict:
    """
    Detect structural gaps in the knowledge graph.
    Returns dict with orphans, dead_links, weak_nodes, and thin_folders.
    """
    graph = build_graph()
    nodes = graph["nodes"]

    # 1. Orphan notes — no incoming OR outgoing links
    orphans = []
    for name, data in nodes.items():
        if not data["links_out"] and not data["links_in"]:
            if data["word_count"] > 50:  # Skip stubs
                orphans.append({
                    "name": data["name"],
                    "folder": data["folder"],
                    "word_count": data["word_count"],
                })

    # 2. Dead links — wikilinks pointing to non-existent notes
    dead_links = []
    seen_dead = set()
    for name, data in nodes.items():
        for target in data["links_out"]:
            if target not in nodes and target not in seen_dead:
                dead_links.append({
                    "target": target,
                    "source": data["name"],
                    "source_folder": data["folder"],
                })
                seen_dead.add(target)

    # 3. Weak nodes — have links but very few (1 in or 1 out)
    weak_nodes = []
    for name, data in nodes.items():
        total_connections = len(data["links_out"]) + len(data["links_in"])
        if total_connections == 1 and data["word_count"] > 100:
            weak_nodes.append({
                "name": data["name"],
                "folder": data["folder"],
                "connections": total_connections,
            })

    # 4. Thin folders — folders with few notes or few cross-links
    folder_stats = defaultdict(lambda: {"notes": 0, "internal_links": 0, "external_links": 0})
    for name, data in nodes.items():
        folder = data["folder"]
        folder_stats[folder]["notes"] += 1
        for target in data["links_out"]:
            if target in nodes:
                if nodes[target]["folder"] == folder:
                    folder_stats[folder]["internal_links"] += 1
                else:
                    folder_stats[folder]["external_links"] += 1

    thin_folders = []
    for folder, stats in folder_stats.items():
        if folder in ('root', '.'):
            continue
        if stats["external_links"] == 0 and stats["notes"] > 2:
            thin_folders.append({
                "folder": folder,
                "notes": stats["notes"],
                "internal_links": stats["internal_links"],
                "external_links": 0,
                "issue": "no cross-folder connections",
            })

    return {
        "orphans": sorted(orphans, key=lambda x: x["word_count"], reverse=True)[:10],
        "dead_links": dead_links[:15],
        "weak_nodes": weak_nodes[:10],
        "thin_folders": thin_folders,
        "total_notes": len(nodes),
        "total_edges": len(graph["edges"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LINK PREDICTION
# ══════════════════════════════════════════════════════════════════════════════

def predict_links(top_n: int = 10) -> list:
    """
    Use sentence-transformers embeddings to find semantically similar notes
    that have no wikilink between them. These are candidate connections.

    Returns list of dicts with source, target, similarity, and reason.
    """
    try:
        from myalicia.skills.semantic_search import semantic_search
    except ImportError:
        log.warning("semantic_search not available for link prediction")
        return []

    graph = build_graph()
    nodes = graph["nodes"]

    # Get notes with enough content to be meaningful
    meaningful_notes = {
        name: data for name, data in nodes.items()
        if data["word_count"] > 100
    }

    suggestions = []

    # For each synthesis note, find semantically similar non-linked notes
    synthesis_notes = {
        name: data for name, data in meaningful_notes.items()
        if data["folder"] in ("Synthesis", "Wisdom")
        or "synthesis" in data["folder"].lower()
    }

    # Also check root-level concept notes
    concept_notes = {
        name: data for name, data in meaningful_notes.items()
        if data["folder"] == "root"
    }

    # Search for potential connections from concept notes
    target_notes = list(concept_notes.items())[:20]  # Cap to keep it fast

    for name, data in target_notes:
        try:
            # Use the note title as a search query
            results = semantic_search(data["name"], n_results=5)
        except Exception:
            continue

        existing_links = set(data["links_out"] + data["links_in"])

        for result in results:
            result_name = os.path.basename(result.get("path", "")).replace(".md", "").lower()
            if (result_name != name
                    and result_name not in existing_links
                    and result_name in nodes):
                similarity = result.get("score", 0)
                if similarity > 0.3:  # Threshold for meaningful similarity
                    suggestions.append({
                        "source": data["name"],
                        "target": nodes[result_name]["name"],
                        "similarity": round(similarity, 3),
                        "source_folder": data["folder"],
                        "target_folder": nodes[result_name]["folder"],
                    })

    # Deduplicate and sort by similarity
    seen = set()
    unique_suggestions = []
    for s in sorted(suggestions, key=lambda x: x["similarity"], reverse=True):
        pair = frozenset([s["source"].lower(), s["target"].lower()])
        if pair not in seen:
            seen.add(pair)
            unique_suggestions.append(s)

    result = unique_suggestions[:top_n]

    # Save suggestions (atomic — crash-safe)
    atomic_write_json(LINK_SUGGESTIONS_FILE, {
        "generated": datetime.now().isoformat(),
        "suggestions": result,
    })

    return result


# ══════════════════════════════════════════════════════════════════════════════
# ONTOLOGY EVOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def analyze_ontology() -> dict:
    """
    Track how the vault's category structure is evolving.
    Detect emerging themes, category health, and potential merges.
    """
    graph = build_graph()
    nodes = graph["nodes"]

    # Folder distribution
    folder_counts = Counter(data["folder"] for data in nodes.values())

    # Cross-folder link density
    cross_links = defaultdict(lambda: defaultdict(int))
    for name, data in nodes.items():
        src_folder = data["folder"]
        for target in data["links_out"]:
            if target in nodes:
                tgt_folder = nodes[target]["folder"]
                if src_folder != tgt_folder:
                    pair = tuple(sorted([src_folder, tgt_folder]))
                    cross_links[pair[0]][pair[1]] += 1

    # Find highly connected folder pairs (potential merges)
    merge_candidates = []
    for f1 in cross_links:
        for f2, count in cross_links[f1].items():
            f1_size = folder_counts.get(f1, 0)
            f2_size = folder_counts.get(f2, 0)
            if f1_size > 0 and f2_size > 0:
                link_density = count / min(f1_size, f2_size)
                if link_density > 0.5:  # More than half of smaller folder links to bigger
                    merge_candidates.append({
                        "folder_a": f1,
                        "folder_b": f2,
                        "cross_links": count,
                        "density": round(link_density, 2),
                    })

    # Tag frequency analysis (find emerging themes)
    tag_counts = Counter()
    for name, data in nodes.items():
        try:
            with open(data["path"], encoding='utf-8') as f:
                content = f.read()
            tags = re.findall(r'#(\w+(?:/\w+)*)', content)
            tag_counts.update(tags)
        except Exception:
            continue

    # Cluster coverage
    cluster_representation = {}
    for cluster in CLUSTERS:
        cluster_lower = cluster.lower()
        matching = [
            name for name, data in nodes.items()
            if cluster_lower in name
            or cluster_lower in data.get("folder", "").lower()
            or any(cluster_lower in link for link in data["links_out"])
        ]
        cluster_representation[cluster] = len(matching)

    return {
        "folder_distribution": dict(folder_counts.most_common(15)),
        "merge_candidates": merge_candidates,
        "top_tags": dict(tag_counts.most_common(15)),
        "cluster_coverage": cluster_representation,
        "total_notes": len(nodes),
        "total_links": len(graph["edges"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY GRAPH HEALTH REPORT
# ══════════════════════════════════════════════════════════════════════════════

def run_graph_health_report() -> str:
    """
    Run the complete graph intelligence scan.
    Generates a markdown report and returns it.
    Called weekly by scheduler.
    """
    log.info("Running graph health report...")

    gaps = detect_gaps()
    ontology = analyze_ontology()

    # Link prediction (uses semantic search — heavier operation)
    try:
        link_suggestions = predict_links(top_n=8)
    except Exception as e:
        log.error(f"Link prediction failed: {e}")
        link_suggestions = []

    # Build report
    date = datetime.now().strftime("%Y-%m-%d")
    report = f"\n## Graph Health — {date}\n\n"

    report += f"**Total:** {gaps['total_notes']} notes, {gaps['total_edges']} links\n\n"

    if gaps["orphans"]:
        report += f"### Orphan Notes ({len(gaps['orphans'])})\n"
        for o in gaps["orphans"][:5]:
            report += f"- {o['name']} ({o['folder']}, {o['word_count']} words)\n"
        report += "\n"

    if gaps["dead_links"]:
        report += f"### Dead Links ({len(gaps['dead_links'])})\n"
        for d in gaps["dead_links"][:5]:
            report += f"- [[{d['target']}]] referenced by {d['source']}\n"
        report += "\n"

    if gaps["thin_folders"]:
        report += f"### Isolated Folders\n"
        for tf in gaps["thin_folders"]:
            report += f"- {tf['folder']}: {tf['notes']} notes, {tf['issue']}\n"
        report += "\n"

    if link_suggestions:
        report += f"### Suggested Links ({len(link_suggestions)})\n"
        for s in link_suggestions[:5]:
            report += (f"- [[{s['source']}]] ↔ [[{s['target']}]] "
                      f"(similarity: {s['similarity']}, "
                      f"{s['source_folder']} → {s['target_folder']})\n")
        report += "\n"

    cluster_cov = ontology.get("cluster_coverage", {})
    if cluster_cov:
        report += "### Cluster Coverage\n"
        for cluster, count in sorted(cluster_cov.items(), key=lambda x: x[1]):
            bar = "█" * min(count, 20)
            report += f"- {cluster}: {bar} ({count})\n"
        report += "\n"

    # Save report
    with open(GRAPH_REPORT_FILE, 'a') as f:
        f.write(report)

    log.info(f"Graph health report: {gaps['total_notes']} notes, "
             f"{len(gaps['orphans'])} orphans, "
             f"{len(gaps['dead_links'])} dead links, "
             f"{len(link_suggestions)} link suggestions")

    return report


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_graph_stats() -> dict:
    """Quick graph stats without full analysis."""
    graph = build_graph()
    nodes = graph["nodes"]

    orphan_count = sum(
        1 for data in nodes.values()
        if not data["links_out"] and not data["links_in"] and data["word_count"] > 50
    )

    return {
        "total_notes": len(nodes),
        "total_links": len(graph["edges"]),
        "orphans": orphan_count,
        "avg_links_per_note": round(len(graph["edges"]) / max(len(nodes), 1), 1),
    }
