#!/usr/bin/env python3
"""
Alicia — Bridge Protocol (§6.4 single-owner I/O)

One module owns every read/write against `Alicia/Bridge/`.

Before this:
  Six files (`analysis_*.py`, `bridge_state.py`, `memory_skill.py`,
  `feedback_loop.py`, `way_of_being.py`) each hardcoded the Bridge path
  and did their own `open()` + `json.dump()` or `atomic_write_text`.
  Atomicity, locking, and schema safety were applied inconsistently.

After:
  One module — BRIDGE_DIR constant, helpers for JSON + text + discovery.
  Every helper routes through `safe_io.atomic_write_*` and
  `safe_io.locked_file`. Optional schema validation via
  `bridge_schema.validate(name, payload)` when `bridge_schema` is
  available (soft dep).

Design goals:
  1. *Additive:* existing code keeps working. New code and migrated code
     imports from here. We gradually flip writers over.
  2. *Uniform path:* `bridge_path("alicia-state.json")` is the only
     sanctioned way to resolve a bridge filename.
  3. *Crash-safe by default:* every write uses atomic_write_* plus an
     optional lock. Readers never see half-written files.
  4. *Self-describing:* `list_bridge_reports(prefix)` replaces ad-hoc
     `os.listdir` + filter patterns repeated across analysis modules.
  5. *Observable:* every write is logged with the filename + byte count
     so failing sidecars show up in stderr.log.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from myalicia.skills.safe_io import atomic_write_json, atomic_write_text, locked_file
from myalicia.config import config

log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────
# VAULT_ROOT mirrors alicia.py. Kept local so bridge_protocol has no
# dependency on the main process module.
VAULT_ROOT = Path(
    os.environ.get(
        "ALICIA_VAULT_ROOT",
        str(config.vault.root),
    )
)
BRIDGE_DIR = VAULT_ROOT / "Alicia" / "Bridge"
INDEX_FILE = BRIDGE_DIR / "_INDEX.jsonl"

PathLike = Union[str, os.PathLike]


# ── Path resolution ─────────────────────────────────────────────────────────

def bridge_path(filename: str) -> Path:
    """
    Resolve `filename` against the bridge directory, with containment.

    Refuses any filename that tries to escape BRIDGE_DIR (e.g.
    `../../etc/passwd`). Returns an absolute Path.
    """
    # Reject traversal outright — we never want `..` segments even if
    # resolve() would eventually keep us inside the bridge. Same for
    # absolute paths; they should always be filenames, not anchored paths.
    if ".." in Path(filename).parts:
        raise ValueError(
            f"Refused bridge path with traversal segment: {filename!r}"
        )
    if os.path.isabs(filename):
        raise ValueError(
            f"Refused absolute bridge path: {filename!r}"
        )
    target = (BRIDGE_DIR / filename).resolve()
    bridge_root = BRIDGE_DIR.resolve()
    if bridge_root not in target.parents and target != bridge_root:
        raise ValueError(
            f"Refused bridge path outside BRIDGE_DIR: {target}"
        )
    return target


def ensure_bridge_dir() -> None:
    """Idempotently create BRIDGE_DIR (and the `telegram-sessions` sub)."""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    (BRIDGE_DIR / "telegram-sessions").mkdir(parents=True, exist_ok=True)


# ── Schema hook (soft dep on bridge_schema — §6.5) ──────────────────────────

def _maybe_validate(filename: str, payload: Any) -> None:
    """
    If `bridge_schema` is importable and defines a schema for
    `filename`, validate `payload` against it.

    Failures are logged as warnings, not raised — we never want schema
    drift to *break* writes; we want it visible. Callers that need
    strict enforcement should call `bridge_schema.validate_strict`.
    """
    try:
        from myalicia.skills import bridge_schema  # noqa: WPS433
    except ImportError:
        return
    try:
        bridge_schema.validate(filename, payload)
    except Exception as e:
        log.warning(
            f"bridge schema validation failed for {filename}: {e}"
        )


# ── JSON I/O ────────────────────────────────────────────────────────────────

def write_bridge_json(
    filename: str,
    payload: Any,
    *,
    validate: bool = True,
    index: bool = True,
) -> Path:
    """
    Atomically write `payload` as JSON to `BRIDGE_DIR/filename`.

    Args:
        filename: Relative filename (e.g. `alicia-state.json`).
        payload: JSON-serialisable object.
        validate: When True, run the schema-validation hook (logs on
            failure; never raises). Pass False for ad-hoc scratch files.
        index: When True, append a line to `_INDEX.jsonl` (H6 of the
            review — Desktop can `tail` this to see new reports).

    Returns the absolute path that was written.
    """
    ensure_bridge_dir()
    target = bridge_path(filename)
    if validate:
        _maybe_validate(filename, payload)
    atomic_write_json(target, payload)
    if index:
        _append_index(filename, kind="json")
    log.info(f"bridge: wrote {filename} ({_size_hint(target)})")
    return target


def read_bridge_json(
    filename: str,
    *,
    default: Any = None,
) -> Any:
    """
    Read and parse a JSON file from the bridge. Returns `default`
    (or `{}` if not given) when the file is missing or unreadable.
    """
    target = bridge_path(filename)
    if not target.exists():
        return default if default is not None else {}
    try:
        with locked_file(target, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"bridge: read_bridge_json({filename}) failed: {e}")
        return default if default is not None else {}


# ── Text / markdown I/O ─────────────────────────────────────────────────────

def write_bridge_text(
    filename: str,
    text: str,
    *,
    index: bool = True,
) -> Path:
    """
    Atomically write plain text / markdown to `BRIDGE_DIR/filename`.

    This is the preferred path for every `analysis_*.py` writer. Uses
    `atomic_write_text` so readers never see half-written markdown.
    """
    ensure_bridge_dir()
    target = bridge_path(filename)
    atomic_write_text(target, text)
    if index:
        _append_index(filename, kind="text")
    log.info(f"bridge: wrote {filename} ({len(text)} chars)")
    return target


def read_bridge_text(
    filename: str,
    *,
    default: str = "",
) -> str:
    """Read a text file from the bridge; return `default` on miss."""
    target = bridge_path(filename)
    if not target.exists():
        return default
    try:
        with locked_file(target, "r") as f:
            return f.read()
    except OSError as e:
        log.warning(f"bridge: read_bridge_text({filename}) failed: {e}")
        return default


# ── Discovery helpers ───────────────────────────────────────────────────────

def list_bridge_reports(
    prefix: str = "",
    *,
    suffix: str = ".md",
    max_results: Optional[int] = None,
) -> list[Path]:
    """
    List bridge files whose basenames start with `prefix` and end with
    `suffix`, sorted newest-first by mtime.

    This replaces the repeated `os.listdir(BRIDGE_DIR)` + filter loops
    in `feedback_loop.py`, `analysis_coordination.py`, etc.
    """
    ensure_bridge_dir()
    matches = [
        p for p in BRIDGE_DIR.iterdir()
        if p.is_file()
        and p.name.startswith(prefix)
        and p.name.endswith(suffix)
    ]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if max_results is not None:
        matches = matches[:max_results]
    return matches


def get_latest_report(prefix: str, *, suffix: str = ".md") -> Optional[Path]:
    """Single most recent bridge file matching `prefix` + `suffix`."""
    results = list_bridge_reports(prefix, suffix=suffix, max_results=1)
    return results[0] if results else None


def reports_since(
    days: int = 7,
    *,
    prefix: str = "",
    suffix: str = ".md",
) -> list[Path]:
    """Files written within the last `days` — used by /bridge summary."""
    ensure_bridge_dir()
    cutoff = datetime.now().timestamp() - (days * 86400)
    matches = [
        p for p in BRIDGE_DIR.iterdir()
        if p.is_file()
        and p.name.startswith(prefix)
        and p.name.endswith(suffix)
        and p.stat().st_mtime >= cutoff
    ]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches


# ── Append-only INDEX (§2.3 H6) ─────────────────────────────────────────────

def _append_index(filename: str, *, kind: str) -> None:
    """
    Append one JSON line to `_INDEX.jsonl` describing the write.

    Consumers (Desktop's bridge-watcher skill, future `/bridge summary`,
    the observability file) can `tail` this cheaply without rescanning
    the directory.
    """
    try:
        entry = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "filename": filename,
            "kind": kind,
        }
        with locked_file(INDEX_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # Index is a convenience; never fail a real write because of it.
        log.debug(f"bridge index append skipped: {e}")


def tail_index(limit: int = 50) -> list[dict]:
    """Return the most recent `limit` entries from _INDEX.jsonl."""
    if not INDEX_FILE.exists():
        return []
    try:
        with locked_file(INDEX_FILE, "r") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    entries: list[dict] = []
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
        if len(entries) >= limit:
            break
    return entries


# ── Small utilities ─────────────────────────────────────────────────────────

def _size_hint(path: Path) -> str:
    try:
        b = path.stat().st_size
    except OSError:
        return "?"
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f}KB"
    return f"{b / (1024 * 1024):.1f}MB"


# ── Self-test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_bridge_dir()
    print("BRIDGE_DIR:", BRIDGE_DIR)
    print("exists:", BRIDGE_DIR.exists())

    # Round-trip
    p = write_bridge_json("_selftest.json", {"hello": "bridge"}, index=False)
    data = read_bridge_json("_selftest.json")
    assert data == {"hello": "bridge"}, data
    p.unlink()
    print("json round-trip: OK")

    p = write_bridge_text("_selftest.md", "# hi", index=False)
    text = read_bridge_text("_selftest.md")
    assert text == "# hi", text
    p.unlink()
    print("text round-trip: OK")

    # Containment
    try:
        bridge_path("../../../etc/passwd")
    except ValueError:
        print("containment: OK (rejected ../etc/passwd)")
    else:
        raise SystemExit("containment check did not fire")

    print("\nAll bridge_protocol self-tests passed.")
