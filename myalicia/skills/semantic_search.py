#!/usr/bin/env python3
"""
Alicia — Semantic Search (Step 2)
Embeds all vault notes locally using sentence-transformers
Stores vectors in chromadb (runs entirely on Mac Mini)
Provides semantic search: find notes by meaning, not just keywords
"""

import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv

from myalicia.skills.safe_io import atomic_write_json
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(os.path.expanduser("~/alicia/.env"))

VAULT_ROOT   = str(config.vault.root)
CHROMA_DIR   = os.path.expanduser("~/alicia/chromadb")
INDEX_LOG    = os.path.expanduser("~/alicia/memory/index_log.json")

# Folders to index (all relevant knowledge folders)
INDEX_FOLDERS = [
    "Quotes",
    "Short reads",
    "Books",
    "Authors",
    "John Vervaeke",
    "Stoic",
    "meaning crisis",
    "my writings",
    "Questions",
    "Wisdom",
    "Self",
    "Leadership",
    "AI thoughts",
    "Research",
    "writing",
    "Writing drafts",
    "Alicia",
    "Design",
    "Podcasts",
    "Knowledge Vault",
    "Inbox",
]

# Whether to also index root-level .md files (concept notes like Aretê.md, Gumption.md)
INDEX_ROOT_NOTES = True

# Lazy-loaded globals
_model      = None
_chroma     = None
_collection = None


def _get_model():
    """Load embedding model lazily — only when first needed."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("Loading embedding model (first time only)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Model loaded.")
    return _model


def _get_collection():
    """Get or create chromadb collection."""
    global _chroma, _collection
    if _collection is None:
        import chromadb
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _chroma.get_or_create_collection(
            name="vault_notes",
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


# ── Note reading ──────────────────────────────────────────────────────────────

def _read_note(filepath: str) -> str:
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _make_note_id(filepath: str) -> str:
    """Create a stable ID from filepath."""
    relative = filepath.replace(VAULT_ROOT + "/", "")
    # Sanitise for chromadb — alphanumeric and hyphens only
    safe = re.sub(r'[^a-zA-Z0-9\-_]', '-', relative)
    return safe[:512]


def _get_all_vault_files() -> list:
    """Get all .md files from indexed folders + root-level notes."""
    files = []
    for folder in INDEX_FOLDERS:
        folder_path = os.path.join(VAULT_ROOT, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, filenames in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in filenames:
                if f.endswith(".md"):
                    files.append(os.path.join(root, f))
    # Root-level concept notes (Aretê.md, Gumption.md, etc.)
    if INDEX_ROOT_NOTES and os.path.exists(VAULT_ROOT):
        for f in os.listdir(VAULT_ROOT):
            fp = os.path.join(VAULT_ROOT, f)
            if f.endswith(".md") and os.path.isfile(fp):
                files.append(fp)
    return files


def _prepare_document(filepath: str, content: str) -> str:
    """Prepare text for embedding — title + first 500 chars of content."""
    title = os.path.basename(filepath).replace(".md", "")
    # Strip frontmatter
    content = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL)
    # Strip tags
    content = re.sub(r'#\w+', '', content)
    # Clean whitespace
    content = re.sub(r'\s+', ' ', content).strip()
    return f"{title}. {content[:500]}"


# ── Indexing ──────────────────────────────────────────────────────────────────

def index_vault(force_reindex: bool = False) -> dict:
    """
    Index all vault notes into chromadb.
    Skips notes that haven't changed since last index.
    Returns stats dict.
    """
    model      = _get_model()
    collection = _get_collection()

    # Load index log
    index_log = {}
    if os.path.exists(INDEX_LOG) and not force_reindex:
        try:
            with open(INDEX_LOG) as f:
                index_log = json.load(f)
        except Exception:
            index_log = {}

    all_files  = _get_vault_files_with_mtime()
    to_index   = []
    skipped    = 0

    for filepath, mtime in all_files:
        note_id    = _make_note_id(filepath)
        last_mtime = index_log.get(note_id, 0)
        if mtime > last_mtime or force_reindex:
            to_index.append((filepath, note_id, mtime))
        else:
            skipped += 1

    if not to_index:
        return {
            "indexed": 0,
            "skipped": skipped,
            "total": collection.count(),
            "message": "All notes up to date."
        }

    # Batch embed and upsert
    batch_size = 50
    indexed    = 0

    for i in range(0, len(to_index), batch_size):
        batch      = to_index[i:i + batch_size]
        ids        = []
        documents  = []
        metadatas  = []
        embeddings = []

        for filepath, note_id, mtime in batch:
            content = _read_note(filepath)
            if len(content.strip()) < 20:
                continue
            doc = _prepare_document(filepath, content)
            ids.append(note_id)
            documents.append(doc[:1000])
            metadatas.append({
                "filepath": filepath,
                "title":    os.path.basename(filepath).replace(".md", ""),
                "folder":   os.path.dirname(filepath).replace(VAULT_ROOT + "/", ""),
                "mtime":    str(mtime),
            })

        if not ids:
            continue

        # Generate embeddings
        vecs = model.encode(documents, show_progress_bar=False).tolist()
        embeddings.extend(vecs)

        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=vecs,
        )

        # Update index log
        for (filepath, note_id, mtime), _ in zip(batch, vecs):
            index_log[note_id] = mtime
        indexed += len(ids)

    # Save index log (atomic — crash-safe)
    atomic_write_json(INDEX_LOG, index_log, indent=None)

    return {
        "indexed":  indexed,
        "skipped":  skipped,
        "total":    collection.count(),
        "message":  f"Indexed {indexed} notes, skipped {skipped} unchanged."
    }


def _get_vault_files_with_mtime() -> list:
    """Get all vault files with their modification times."""
    files = []
    for folder in INDEX_FOLDERS:
        folder_path = os.path.join(VAULT_ROOT, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, filenames in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in filenames:
                if f.endswith(".md"):
                    filepath = os.path.join(root, f)
                    mtime    = os.path.getmtime(filepath)
                    files.append((filepath, mtime))
    # Root-level concept notes
    if INDEX_ROOT_NOTES and os.path.exists(VAULT_ROOT):
        for f in os.listdir(VAULT_ROOT):
            fp = os.path.join(VAULT_ROOT, f)
            if f.endswith(".md") and os.path.isfile(fp):
                mtime = os.path.getmtime(fp)
                files.append((fp, mtime))
    return files


# ── Semantic search ───────────────────────────────────────────────────────────

def semantic_search(query: str, n_results: int = 5, folder_filter: str = None) -> list:
    """
    Search vault by meaning using vector similarity.
    Returns list of dicts with title, filepath, folder, score, snippet.
    """
    model      = _get_model()
    collection = _get_collection()

    if collection.count() == 0:
        return []

    # Embed the query
    query_vec = model.encode([query], show_progress_bar=False).tolist()[0]

    # Build where clause if folder filter provided
    where = {"folder": {"$contains": folder_filter}} if folder_filter else None

    try:
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=min(n_results, collection.count()),
            where=where,
            include=["metadatas", "documents", "distances"]
        )
    except Exception as e:
        return []

    hits = []
    metadatas  = results.get("metadatas",  [[]])[0]
    documents  = results.get("documents",  [[]])[0]
    distances  = results.get("distances",  [[]])[0]

    for meta, doc, dist in zip(metadatas, documents, distances):
        # Convert cosine distance to similarity score (0-1, higher = more similar)
        score = round(1 - dist, 3)
        if score < 0.2:  # Skip low-relevance results
            continue
        hits.append({
            "title":    meta.get("title", ""),
            "filepath": meta.get("filepath", ""),
            "folder":   meta.get("folder", ""),
            "score":    score,
            "snippet":  doc[:200],
        })

    return hits


def semantic_search_formatted(query: str, n_results: int = 5) -> str:
    """Format semantic search results for Telegram — clean titles, no deep links."""
    hits = semantic_search(query, n_results=n_results)

    if not hits:
        return f"🔍 No semantic results for '{query}'. Try /searchvault for keyword search."

    lines = [f"🧠 *Semantic search: '{query}'*\n"]
    for i, h in enumerate(hits, 1):
        score_bar = "█" * int(h["score"] * 5)
        lines.append(
            f"{i}. *{h['title']}*\n"
            f"   {h['folder']} · relevance: {score_bar} {h['score']}\n"
            f"   {h['snippet'][:120]}...\n"
        )

    lines.append("_Open these notes in Obsidian to read the full content._")
    return "\n".join(lines)


# ── Context retrieval for Alicia's system prompt ──────────────────────────────

def get_relevant_context(query: str, n_results: int = 4) -> str:
    """
    Retrieve the most relevant vault notes for a query.
    Returns formatted context to inject into Alicia's system prompt.
    """
    hits = semantic_search(query, n_results=n_results)
    if not hits:
        return ""

    lines = [f"\n## Relevant notes from {USER_NAME}'s vault (retrieved by semantic search)\n"]
    for h in hits:
        content = _read_note(h["filepath"])
        # Strip frontmatter and tags, get first 400 chars
        content = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL)
        content = re.sub(r'#\w+\s*', '', content)
        content = re.sub(r'\s+', ' ', content).strip()[:400]
        lines.append(f"### [[{h['title']}]] (relevance: {h['score']})\n{content}\n")

    return "\n".join(lines)


# ── Index stats ───────────────────────────────────────────────────────────────

def get_index_stats() -> str:
    """Return index health for status reports."""
    try:
        collection = _get_collection()
        count      = collection.count()
        total_files = len(_get_all_vault_files())
        pct = int(count / max(total_files, 1) * 100)
        return f"Semantic index: {count}/{total_files} notes indexed ({pct}%)"
    except Exception:
        return "Semantic index: not yet built"


# ── CLI for initial indexing ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("Building semantic index of your vault...")
    print("This will take 10-15 minutes the first time.\n")
    start = datetime.now()
    result = index_vault(force_reindex=False)
    elapsed = (datetime.now() - start).seconds
    print(f"\n✅ Done in {elapsed}s")
    print(f"   Indexed:  {result['indexed']} notes")
    print(f"   Skipped:  {result['skipped']} (unchanged)")
    print(f"   Total:    {result['total']} notes in index")
    print(f"\nTest search:")
    hits = semantic_search("the relationship between quality and attention", n_results=3)
    for h in hits:
        print(f"  [{h['score']}] {h['title']} — {h['folder']}")