"""
Alicia's Muse — Serendipity Engine

The Muse archetype made manifest: random vault walks, quote echoes that
rhyme with recent conversation, and cross-cluster beauty detection.

Where other modules are about learning and discipline, the Muse is about
delight — surfacing the unexpected, celebrating distant connections,
and reminding the user that the vault is alive with resonance.
"""

import os
import json
import random
import logging
from datetime import datetime, timezone, timedelta

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

logger = logging.getLogger("alicia")

VAULT_ROOT = str(config.vault.root)
QUOTES_FOLDER = os.path.join(VAULT_ROOT, "Quotes")
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")
MEMORY_DIR = str(MEMORY_DIR)
MUSE_STATE = os.path.join(MEMORY_DIR, "muse_state.json")
RESONANCE_LOG = os.path.join(MEMORY_DIR, "resonance.md")

# Folders that hold the vault's living ideas
IDEA_FOLDERS = [
    "Quotes", "Short reads", "Books", "Authors",
    "meaning crisis", "Stoic", "my writings",
    "Questions", "Wisdom", "Leadership", "AI thoughts",
    "Design", "Podcasts", "Knowledge Vault",
]

# How many serendipity moments per day (max)
MAX_SERENDIPITY_PER_DAY = 3

# Minimum semantic similarity for a quote echo to feel meaningful
ECHO_THRESHOLD = 0.30

# Cross-cluster bridge: minimum folders apart to count as "distant"
MIN_CLUSTER_DISTANCE = 2


# ── Serendipity Walks ──────────────────────────────────────────────────────

def random_vault_walk(steps: int = 3) -> list:
    """
    Take a random walk through the vault.

    Start from a random note, then follow wikilinks. If a note has no
    outgoing links, jump to a random note in a different folder.

    Returns:
        list of dicts: [{title, folder, snippet, path}, ...]
    """
    walk = []
    visited = set()

    try:
        # Gather all notes
        all_notes = []
        for folder in IDEA_FOLDERS:
            folder_path = os.path.join(VAULT_ROOT, folder)
            if not os.path.isdir(folder_path):
                continue
            for root, _, files in os.walk(folder_path):
                for fname in files:
                    if fname.endswith(".md") and not fname.startswith("."):
                        full_path = os.path.join(root, fname)
                        rel_folder = os.path.relpath(root, VAULT_ROOT).split(os.sep)[0]
                        all_notes.append({
                            "title": fname[:-3],
                            "folder": rel_folder,
                            "path": full_path,
                        })

        if not all_notes:
            return []

        # Start from a random note
        current = random.choice(all_notes)

        for _ in range(steps):
            if current["path"] in visited:
                # Jump to a different folder
                other_folder_notes = [n for n in all_notes
                                      if n["folder"] != current["folder"]
                                      and n["path"] not in visited]
                if not other_folder_notes:
                    break
                current = random.choice(other_folder_notes)

            visited.add(current["path"])

            # Read a snippet
            snippet = _read_snippet(current["path"])
            walk.append({
                "title": current["title"],
                "folder": current["folder"],
                "snippet": snippet,
                "path": current["path"],
            })

            # Follow a wikilink if possible
            links = _extract_wikilinks(current["path"])
            unvisited_links = [l for l in links if l not in visited]

            if unvisited_links:
                # Find the note for a random link
                link_name = random.choice(unvisited_links).lower()
                matched = [n for n in all_notes if n["title"].lower() == link_name]
                if matched:
                    current = matched[0]
                    continue

            # No links or no match — jump to different folder
            other_folder_notes = [n for n in all_notes
                                  if n["folder"] != current["folder"]
                                  and n["path"] not in visited]
            if other_folder_notes:
                current = random.choice(other_folder_notes)
            else:
                break

    except Exception as e:
        logger.debug(f"Vault walk error: {e}")

    return walk


def format_vault_walk(walk: list) -> str:
    """
    Format a vault walk into a poetic message for the user.

    Returns:
        str: Formatted message with the walk's narrative.
    """
    if not walk:
        return ""

    parts = ["*A walk through the vault...*\n"]
    for i, step in enumerate(walk):
        marker = "→" if i > 0 else "•"
        snippet = step["snippet"][:120].strip()
        if snippet:
            parts.append(f"{marker} **{step['title']}** ({step['folder']})\n  _{snippet}..._")
        else:
            parts.append(f"{marker} **{step['title']}** ({step['folder']})")

    # Add a connective observation if walk spans multiple folders
    folders = list(dict.fromkeys(s["folder"] for s in walk))
    if len(folders) >= 2:
        parts.append(f"\n_A path from {folders[0]} through {', '.join(folders[1:])}._")

    return "\n".join(parts)


# ── Quote Echoes ───────────────────────────────────────────────────────────

def find_quote_echo(recent_text: str, n_candidates: int = 8) -> dict | None:
    """
    Find a quote that echoes the mood or theme of recent conversation.

    Uses semantic search to find quotes similar to what the user has been
    talking about, then picks one that hasn't been surfaced recently.

    Args:
        recent_text: Recent conversation text to echo against.
        n_candidates: Number of candidates to pull from search.

    Returns:
        dict with keys: quote, author, title, similarity, folder
        OR None if nothing resonates above threshold.
    """
    try:
        from myalicia.skills.semantic_search import semantic_search
    except ImportError:
        logger.debug("Semantic search not available for quote echo")
        return None

    try:
        # Search quotes folder specifically
        results = semantic_search(
            query=recent_text[:500],
            n_results=n_candidates,
            folder_filter="Quotes",
        )

        if not results:
            return None

        # Filter by threshold and exclude recently surfaced
        recent_echoes = _get_recent_echoes(days=7)

        for result in results:
            score = result.get("score", 0)
            title = result.get("title", "")

            if score < ECHO_THRESHOLD:
                continue
            if title in recent_echoes:
                continue

            # Extract the actual quote content
            filepath = result.get("filepath", "")
            quote_data = _extract_quote_from_file(filepath) if filepath else None

            if quote_data and quote_data.get("quote"):
                _record_echo(title, score)
                return {
                    "quote": quote_data["quote"],
                    "author": quote_data.get("author", ""),
                    "title": title,
                    "similarity": round(score, 3),
                    "folder": result.get("folder", "Quotes"),
                }

        return None

    except Exception as e:
        logger.debug(f"Quote echo error: {e}")
        return None


def format_quote_echo(echo: dict) -> str:
    """
    Format a quote echo into a message.

    Returns:
        str: Formatted echo message.
    """
    if not echo:
        return ""

    quote = echo["quote"]
    author = echo.get("author", "")
    sim = echo.get("similarity", 0)

    parts = []
    if sim > 0.5:
        parts.append("_Something from the vault resonates deeply..._\n")
    else:
        parts.append("_An echo from the vault..._\n")

    parts.append(f"> {quote}")

    if author:
        parts.append(f"\n— {author}")

    return "\n".join(parts)


# ── Cross-Cluster Beauty Detection ─────────────────────────────────────────

def detect_cross_cluster_bridges(max_bridges: int = 5) -> list:
    """
    Find synthesis notes that bridge distant parts of the vault.

    A "beautiful bridge" is a synthesis note that connects concepts from
    clusters/folders that rarely overlap. These represent the moments
    where ideas from very different domains find common ground.

    Returns:
        list of dicts: [{title, clusters, bridge_distance, snippet, path}, ...]
    """
    bridges = []

    try:
        if not os.path.isdir(SYNTHESIS_DIR):
            return []

        # Read all synthesis notes and their cluster tags
        for fname in os.listdir(SYNTHESIS_DIR):
            if not fname.endswith(".md"):
                continue

            filepath = os.path.join(SYNTHESIS_DIR, fname)
            clusters = _extract_clusters_from_note(filepath)

            if len(clusters) < 2:
                continue

            # Compute "distance" — how many unique top-level folders
            # the linked clusters span
            distance = len(set(clusters))

            if distance >= MIN_CLUSTER_DISTANCE:
                snippet = _read_snippet(filepath, max_chars=150)
                bridges.append({
                    "title": fname[:-3],
                    "clusters": clusters,
                    "bridge_distance": distance,
                    "snippet": snippet,
                    "path": filepath,
                })

        # Sort by bridge distance (most distant first), then alphabetically
        bridges.sort(key=lambda b: (-b["bridge_distance"], b["title"]))
        return bridges[:max_bridges]

    except Exception as e:
        logger.debug(f"Cross-cluster detection error: {e}")
        return []


def find_new_bridge_opportunity() -> dict | None:
    """
    Use link prediction to find a potential new cross-cluster bridge.

    Returns:
        dict with keys: source, target, source_folder, target_folder, similarity
        OR None if no interesting bridges found.
    """
    try:
        from myalicia.skills.graph_intelligence import predict_links
    except ImportError:
        logger.debug("Graph intelligence not available for bridge detection")
        return None

    try:
        predictions = predict_links(top_n=15)

        if not predictions:
            return None

        # Filter for cross-folder predictions (distant ideas)
        for pred in predictions:
            source_folder = pred.get("source_folder", "")
            target_folder = pred.get("target_folder", "")
            similarity = pred.get("similarity", 0)

            if source_folder != target_folder and similarity >= 0.3:
                return {
                    "source": pred.get("source", ""),
                    "target": pred.get("target", ""),
                    "source_folder": source_folder,
                    "target_folder": target_folder,
                    "similarity": round(similarity, 3),
                }

        return None

    except Exception as e:
        logger.debug(f"Bridge opportunity error: {e}")
        return None


def format_bridge_celebration(bridge: dict) -> str:
    """
    Format a bridge discovery into a celebratory message.
    """
    if not bridge:
        return ""

    clusters = bridge.get("clusters", [])
    title = bridge.get("title", "")
    snippet = bridge.get("snippet", "")

    cluster_str = " × ".join(clusters[:4])
    parts = [f"_A bridge across {cluster_str}_\n"]
    parts.append(f"**{title}**")

    if snippet:
        parts.append(f"_{snippet}_")

    return "\n".join(parts)


def format_bridge_opportunity(opportunity: dict) -> str:
    """
    Format a potential bridge as an invitation to explore.
    """
    if not opportunity:
        return ""

    source = opportunity.get("source", "")
    target = opportunity.get("target", "")
    src_folder = opportunity.get("source_folder", "")
    tgt_folder = opportunity.get("target_folder", "")

    return (
        f"_The Muse sees a connection forming..._\n\n"
        f"**{source}** ({src_folder}) ↔ **{target}** ({tgt_folder})\n\n"
        f"_These ideas live in different worlds but speak the same language._"
    )


# ── Serendipity Engine (Scheduled Task) ────────────────────────────────────

def build_serendipity_moment() -> dict | None:
    """
    Build a serendipity moment for proactive messages.

    Randomly chooses between:
    - A quote echo (if recent conversation text is available)
    - A vault walk
    - A cross-cluster bridge celebration

    Rate-limited to MAX_SERENDIPITY_PER_DAY.

    Returns:
        dict with keys: type, message, style
        OR None if rate-limited or nothing interesting found.
    """
    try:
        state = _load_muse_state()
        # LOCAL date — serendipity cap resets at the user's midnight, not UTC.
        today = datetime.now().date().isoformat()

        if state.get("date") != today:
            state = {"date": today, "moments": [], "echoes_surfaced": []}

        if len(state.get("moments", [])) >= MAX_SERENDIPITY_PER_DAY:
            return None

        # Choose a moment type with weighted randomness
        moment_types = [
            ("quote_echo", 0.35),
            ("vault_walk", 0.35),
            ("bridge", 0.30),
        ]
        chosen_type = random.choices(
            [t[0] for t in moment_types],
            weights=[t[1] for t in moment_types],
            k=1,
        )[0]

        result = None

        if chosen_type == "quote_echo":
            # Try to find a quote echo based on recent context
            recent_text = _get_recent_conversation_context()
            if recent_text:
                echo = find_quote_echo(recent_text)
                if echo:
                    result = {
                        "type": "quote_echo",
                        "message": format_quote_echo(echo),
                        "style": "gentle",
                        "data": echo,
                    }

        elif chosen_type == "vault_walk":
            walk = random_vault_walk(steps=3)
            if walk:
                result = {
                    "type": "vault_walk",
                    "message": format_vault_walk(walk),
                    "style": "warm",
                    "data": {"steps": len(walk)},
                }

        elif chosen_type == "bridge":
            bridges = detect_cross_cluster_bridges(max_bridges=3)
            recent_bridges = [m.get("title", "") for m in state.get("moments", [])
                              if m.get("type") == "bridge"]
            for bridge in bridges:
                if bridge["title"] not in recent_bridges:
                    result = {
                        "type": "bridge",
                        "message": format_bridge_celebration(bridge),
                        "style": "excited",
                        "data": bridge,
                    }
                    break

        # Fallback: try the other types
        if result is None:
            # Try vault walk as universal fallback
            walk = random_vault_walk(steps=3)
            if walk:
                result = {
                    "type": "vault_walk",
                    "message": format_vault_walk(walk),
                    "style": "warm",
                    "data": {"steps": len(walk)},
                }

        if result:
            state["moments"].append({
                "type": result["type"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "title": result.get("data", {}).get("title", ""),
            })
            _save_muse_state(state)

        return result

    except Exception as e:
        logger.debug(f"Serendipity moment error: {e}")
        return None


def get_muse_context() -> str:
    """
    Build a Muse context string for system prompt injection.

    Returns:
        str: Brief note about recent serendipity moments.
    """
    try:
        state = _load_muse_state()
        # LOCAL date — match the write-side day boundary in record_* above.
        today = datetime.now().date().isoformat()

        if state.get("date") != today:
            return ""

        moments = state.get("moments", [])
        if not moments:
            return ""

        types = [m["type"] for m in moments]
        type_counts = {t: types.count(t) for t in set(types)}

        parts = []
        if type_counts.get("quote_echo"):
            parts.append("a quote echo was surfaced")
        if type_counts.get("vault_walk"):
            parts.append("a vault walk was taken")
        if type_counts.get("bridge"):
            parts.append("a cross-cluster bridge was celebrated")

        if parts:
            return f"Today the Muse has already offered: {', '.join(parts)}."

        return ""

    except Exception:
        return ""


# ── Aesthetic Moment Detection ─────────────────────────────────────────────

def detect_aesthetic_moment(text: str) -> str | None:
    """
    Detect when the user is in an aesthetic/contemplative mode based on
    language patterns. Returns a Muse-flavored response nudge.

    Args:
        text: the user's message text.

    Returns:
        str: A brief Muse nudge, or None if no aesthetic moment detected.
    """
    # Aesthetic indicators — language that suggests contemplation
    AESTHETIC_PATTERNS = [
        "beautiful", "elegant", "sublime", "resonates",
        "something about", "there's a quality", "feels like",
        "reminds me of", "echoes", "rhythm", "harmony",
        "poetic", "lyrical", "aesthetic", "delicate",
        "depth", "layers", "texture", "luminous",
    ]

    text_lower = text.lower()
    matches = [p for p in AESTHETIC_PATTERNS if p in text_lower]

    if len(matches) < 1:
        return None

    # Don't fire too often — check state
    try:
        state = _load_muse_state()
        last_aesthetic = state.get("last_aesthetic_nudge", "")
        if last_aesthetic:
            last_ts = datetime.fromisoformat(last_aesthetic)
            if datetime.now(timezone.utc) - last_ts < timedelta(hours=4):
                return None

        state["last_aesthetic_nudge"] = datetime.now(timezone.utc).isoformat()
        _save_muse_state(state)
    except Exception:
        pass

    # Generate a light Muse nudge
    nudges = [
        "The vault hums when you speak like this.",
        "Stay here a moment — this is where the good thinking lives.",
        "There's a thread worth pulling in what you just said.",
        "The Muse notices you're seeing something.",
    ]

    return random.choice(nudges)


# ── Internal Helpers ───────────────────────────────────────────────────────

def _read_snippet(filepath: str, max_chars: int = 200) -> str:
    """Read the first meaningful lines of a file as a snippet."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        content_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip frontmatter, headers, empty lines, tags
            if stripped.startswith("---") or stripped.startswith("#"):
                continue
            if stripped.startswith("*Wisdom themes") or stripped.startswith("tags:"):
                continue
            if not stripped:
                continue
            content_lines.append(stripped)
            if len(" ".join(content_lines)) > max_chars:
                break

        return " ".join(content_lines)[:max_chars]

    except Exception:
        return ""


def _extract_wikilinks(filepath: str) -> list:
    """Extract all [[wikilink]] targets from a file."""
    import re
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]', content)
    except Exception:
        return []


def _extract_clusters_from_note(filepath: str) -> list:
    """
    Extract cluster/theme tags from a synthesis note.

    Looks for: tags in YAML frontmatter, #cluster tags, or [[links]]
    to cluster concepts.
    """
    clusters = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(3000)

        # Check for tags in frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                frontmatter = content[3:end]
                for line in frontmatter.split("\n"):
                    if line.strip().startswith("- "):
                        tag = line.strip()[2:].strip().strip('"').strip("'")
                        if tag and len(tag) > 1:
                            clusters.append(tag)

        # Check for #cluster tags in body
        import re
        hashtags = re.findall(r'#(\w[\w-]+)', content)
        for tag in hashtags:
            if tag.lower() not in ("quotes", "synthesis", "draft", "todo"):
                if tag not in clusters:
                    clusters.append(tag)

        # Check for [[links]] to known cluster concepts
        links = _extract_wikilinks(filepath)
        known_clusters = [
            "Quality", "Mastery", "Environment", "Measurement",
            "Relationships", "Compounding", "Technology", "Depth",
            "Meaning Crisis", "Stoicism", "Antifragility", "Leadership",
        ]
        for link in links:
            for kc in known_clusters:
                if kc.lower() in link.lower() and kc not in clusters:
                    clusters.append(kc)

    except Exception:
        pass

    return clusters


def _extract_quote_from_file(filepath: str) -> dict | None:
    """Extract quote content from a quote file."""
    try:
        from myalicia.skills.quote_skill import extract_quote_content
        return extract_quote_content(filepath)
    except ImportError:
        # Fallback: basic extraction
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(2000)

            import re
            # Look for quoted text
            quoted = re.findall(r'"([^"]{20,})"', content)
            if quoted:
                return {"quote": quoted[0], "author": "", "filename": os.path.basename(filepath)}

            # Look for bold text
            bold = re.findall(r'\*\*([^*]{20,})\*\*', content)
            if bold:
                return {"quote": bold[0], "author": "", "filename": os.path.basename(filepath)}

            return None
        except Exception:
            return None


def _get_recent_echoes(days: int = 7) -> set:
    """Get titles of quotes surfaced as echoes in the last N days."""
    try:
        state = _load_muse_state()
        echoes = set()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        for echo in state.get("echoes_surfaced", []):
            try:
                ts = datetime.fromisoformat(echo.get("timestamp", ""))
                if ts > cutoff:
                    echoes.add(echo.get("title", ""))
            except (ValueError, TypeError):
                continue

        return echoes
    except Exception:
        return set()


def _record_echo(title: str, score: float):
    """Record that a quote was surfaced as an echo."""
    try:
        state = _load_muse_state()
        echoes = state.get("echoes_surfaced", [])
        echoes.append({
            "title": title,
            "score": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 50
        state["echoes_surfaced"] = echoes[-50:]
        _save_muse_state(state)
    except Exception:
        pass


def _get_recent_conversation_context() -> str:
    """
    Get recent conversation text for quote echo matching.

    Reads the last few interactions from the log file.
    """
    log_file = str(LOGS_DIR / "interactions.jsonl")
    try:
        if not os.path.exists(log_file):
            return ""

        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Take last 5 interactions
        recent_texts = []
        for line in lines[-5:]:
            try:
                entry = json.loads(line)
                text = entry.get("user_text", entry.get("text", ""))
                if text:
                    recent_texts.append(text)
            except json.JSONDecodeError:
                continue

        return " ".join(recent_texts)[:1000]

    except Exception:
        return ""


def _load_muse_state() -> dict:
    """Load the muse state file."""
    try:
        if os.path.exists(MUSE_STATE):
            with open(MUSE_STATE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_muse_state(state: dict):
    """Save the muse state file."""
    try:
        atomic_write_json(MUSE_STATE, state)
    except Exception as e:
        logger.debug(f"Could not save muse state: {e}")
