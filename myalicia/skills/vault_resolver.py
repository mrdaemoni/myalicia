#!/usr/bin/env python3
"""
Alicia — Smart Vault File Resolver

Finds vault notes by fuzzy matching, aliases, semantic similarity, and common patterns.
Shared across all skills that need to locate vault files.

Handles:
- Exact names: "From Measurement to Meaning"
- Partial/coded: "S3E01", "s3e01", "quality before objects"
- Conversational: "the alicia note", "that podcast episode", "my measurement essay"
- Path fragments: "Synthesis/Presence is not preparation"
- Underscores, hyphens, mixed case: all normalized
"""

import os
import re
import logging
from difflib import SequenceMatcher
from myalicia.config import config

log = logging.getLogger(__name__)

VAULT_ROOT = str(config.vault.root)

# Folders to skip during search
SKIP_DIRS = {'.obsidian', '.trash', 'venv', '__pycache__', 'node_modules', '.git'}


def resolve_note(query: str) -> dict:
    """
    Find a vault note matching the query.

    Returns dict:
        {
            'found': bool,
            'path': str or None,       # full path to .md file
            'title': str or None,       # filename without .md
            'score': float,             # match confidence 0-1
            'method': str,              # how it was found
        }
    """
    if not query or not query.strip():
        return {'found': False, 'path': None, 'title': None, 'score': 0, 'method': 'empty'}

    query = query.strip()

    # ── 1. Exact path (absolute or relative to vault) ────────────────────
    for candidate in [query, query + ".md", os.path.join(VAULT_ROOT, query), os.path.join(VAULT_ROOT, query + ".md")]:
        if os.path.isfile(candidate) and candidate.endswith('.md'):
            return {
                'found': True,
                'path': candidate,
                'title': os.path.basename(candidate).replace('.md', ''),
                'score': 1.0,
                'method': 'exact_path',
            }

    # ── 2. Build index of all vault .md files ────────────────────────────
    vault_files = _scan_vault()
    if not vault_files:
        return {'found': False, 'path': None, 'title': None, 'score': 0, 'method': 'no_vault'}

    # ── 3. Exact filename match (case-insensitive) ───────────────────────
    query_normalized = _normalize(query)
    for fpath, fname in vault_files:
        if _normalize(fname) == query_normalized:
            return {
                'found': True,
                'path': fpath,
                'title': fname,
                'score': 1.0,
                'method': 'exact_name',
            }

    # ── 4. Substring containment (query in filename or filename in query) ─
    substring_matches = []
    for fpath, fname in vault_files:
        fn = _normalize(fname)
        qn = query_normalized
        if qn in fn:
            # Query is contained in filename — score by coverage
            score = len(qn) / max(len(fn), 1)
            substring_matches.append((score, fpath, fname, 'substring'))
        elif fn in qn:
            # Filename is contained in query
            score = len(fn) / max(len(qn), 1) * 0.8
            substring_matches.append((score, fpath, fname, 'reverse_substring'))

    if substring_matches:
        substring_matches.sort(key=lambda x: x[0], reverse=True)
        best = substring_matches[0]
        if best[0] > 0.15:  # minimum threshold
            return {
                'found': True,
                'path': best[1],
                'title': best[2],
                'score': best[0],
                'method': best[3],
            }

    # ── 5. Token overlap (handles word reordering) ───────────────────────
    query_tokens = set(_tokenize(query))
    token_matches = []
    for fpath, fname in vault_files:
        fname_tokens = set(_tokenize(fname))
        if not fname_tokens:
            continue
        overlap = query_tokens & fname_tokens
        if overlap:
            # Jaccard-ish score weighted toward query coverage
            score = len(overlap) / max(len(query_tokens), 1) * 0.9
            token_matches.append((score, fpath, fname))

    if token_matches:
        token_matches.sort(key=lambda x: x[0], reverse=True)
        best = token_matches[0]
        if best[0] > 0.3:
            return {
                'found': True,
                'path': best[1],
                'title': best[2],
                'score': best[0],
                'method': 'token_overlap',
            }

    # ── 6. Fuzzy string similarity (handles typos, abbreviations) ────────
    fuzzy_matches = []
    for fpath, fname in vault_files:
        ratio = SequenceMatcher(None, query_normalized, _normalize(fname)).ratio()
        if ratio > 0.5:
            fuzzy_matches.append((ratio, fpath, fname))

    if fuzzy_matches:
        fuzzy_matches.sort(key=lambda x: x[0], reverse=True)
        best = fuzzy_matches[0]
        return {
            'found': True,
            'path': best[1],
            'title': best[2],
            'score': best[0],
            'method': 'fuzzy',
        }

    # ── 7. Nothing found ─────────────────────────────────────────────────
    # Return closest fuzzy match as a suggestion even if below threshold
    all_ratios = []
    for fpath, fname in vault_files:
        ratio = SequenceMatcher(None, query_normalized, _normalize(fname)).ratio()
        all_ratios.append((ratio, fpath, fname))
    all_ratios.sort(key=lambda x: x[0], reverse=True)

    suggestion = all_ratios[0] if all_ratios else None
    return {
        'found': False,
        'path': None,
        'title': None,
        'score': 0,
        'method': 'not_found',
        'suggestion': suggestion[2] if suggestion and suggestion[0] > 0.3 else None,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize a string for comparison: lowercase, strip extensions, collapse separators."""
    text = text.lower().strip()
    text = text.replace('.md', '')
    # Replace underscores, hyphens, multiple spaces with single space
    text = re.sub(r'[_\-]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _tokenize(text: str) -> list:
    """Split text into meaningful tokens, removing common words."""
    normalized = _normalize(text)
    tokens = re.split(r'\s+', normalized)
    # Keep tokens of 2+ chars, remove noise
    stop = {'the', 'a', 'an', 'of', 'for', 'in', 'on', 'to', 'by', 'and', 'or', 'my', 'is', 'it'}
    return [t for t in tokens if len(t) >= 2 and t not in stop]


_vault_cache = None
_vault_cache_time = 0

def _scan_vault() -> list:
    """
    Scan the vault and return list of (full_path, filename_without_ext).
    Cached for 60 seconds.
    """
    global _vault_cache, _vault_cache_time
    import time

    now = time.time()
    if _vault_cache and (now - _vault_cache_time) < 60:
        return _vault_cache

    files = []
    if not os.path.exists(VAULT_ROOT):
        return files

    for root, dirs, filenames in os.walk(VAULT_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith('.md') and not f.startswith('.'):
                fpath = os.path.join(root, f)
                fname = f.replace('.md', '')
                files.append((fpath, fname))

    _vault_cache = files
    _vault_cache_time = now
    return files


def list_matching_notes(query: str, top_n: int = 5) -> list:
    """
    Return top N matching vault notes for a query.
    Useful for disambiguation: "did you mean one of these?"
    """
    vault_files = _scan_vault()
    query_normalized = _normalize(query)

    scored = []
    for fpath, fname in vault_files:
        fn = _normalize(fname)
        # Combine multiple signals
        substring_score = 0
        if query_normalized in fn:
            substring_score = len(query_normalized) / max(len(fn), 1)
        elif fn in query_normalized:
            substring_score = len(fn) / max(len(query_normalized), 1) * 0.7

        fuzzy_score = SequenceMatcher(None, query_normalized, fn).ratio()

        query_tokens = set(_tokenize(query))
        fname_tokens = set(_tokenize(fname))
        token_score = len(query_tokens & fname_tokens) / max(len(query_tokens), 1) if query_tokens else 0

        combined = max(substring_score, fuzzy_score * 0.9, token_score * 0.85)
        if combined > 0.2:
            scored.append((combined, fpath, fname))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [{'path': p, 'title': t, 'score': s} for s, p, t in scored[:top_n]]
