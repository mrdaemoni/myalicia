#!/usr/bin/env python3
"""
Alicia — Safe I/O Primitives

Atomic writes and advisory file locking for Alicia's shared state.

Why this exists:
  Alicia has multiple concurrent writers against the same files —
    * Telegram handler (main thread)
    * asyncio event loop + ThreadPoolExecutor workers
    * Scheduler APScheduler jobs
    * Background vault watchers
  A naive `open(path, 'w').write(...)` is interruptible. A crash or
  concurrent write can leave a state file half-written, corrupting
  state that takes hours of conversation to rebuild (emergence_state,
  episode_scores, session_threads, muse_state).

Two primitives:
  * atomic_write_json(path, data) — write to temp file, fsync, rename.
    Either the old version or the new version is visible; never a
    half-written file.
  * locked_file(path, mode) — context manager that takes an fcntl
    advisory lock (shared for 'r', exclusive for 'w'/'a'). Cross-
    process safe on the same filesystem.

Dependencies: stdlib only (json, os, tempfile, fcntl, contextlib).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator, Union

log = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]


# ── Atomic JSON write ────────────────────────────────────────────────────────

def atomic_write_json(
    path: PathLike,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """
    Atomically write `data` as JSON to `path`.

    Writes to a sibling tempfile, fsyncs, then os.replace()s into place.
    Readers will see either the old or the new version — never partial.

    Safe against:
      * Crashes mid-write (old file remains intact)
      * Concurrent readers (os.replace is atomic on POSIX)
      * Partial disk flushes (fsync on the temp file)

    NOT safe against:
      * Two concurrent writers racing — the last one wins, but the
        result will still be a valid JSON file. For serialized writes,
        combine with locked_file().

    Args:
        path: Destination path.
        data: Any JSON-serialisable object.
        indent: JSON indent level (default 2 for readability).
        ensure_ascii: Passed to json.dump.
        sort_keys: Passed to json.dump.
    """
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_",
        suffix=".json",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=indent,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file if anything went wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(
    path: PathLike,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """
    Atomically write a string to `path`. Same semantics as
    atomic_write_json but for plain text (memory files, hot_topics.md,
    bridge reports, etc.).
    """
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_",
        suffix=".txt",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Advisory file locking ────────────────────────────────────────────────────

@contextmanager
def locked_file(
    path: PathLike,
    mode: str = "r",
    *,
    encoding: str = "utf-8",
) -> Iterator:
    """
    Open `path` with an fcntl advisory lock held for the duration of
    the context manager.

    Lock type:
      * 'r', 'rb'           → LOCK_SH (shared — many readers OK)
      * 'w', 'a', 'r+', etc → LOCK_EX (exclusive — one writer at a time)

    Concurrent readers can proceed in parallel. A writer blocks until
    all readers release. Other writers block until the current one
    releases. Releases automatically on context-manager exit, even if
    an exception is raised inside the block.

    Cross-process safe (fcntl locks are held on the inode). Local
    filesystems only — NFS has known edge cases with flock().

    Usage:
        with locked_file("/path/to/state.json", "r") as f:
            data = json.load(f)

        with locked_file("/path/to/state.json", "w") as f:
            json.dump(data, f)

    Note: For writes, prefer combining locked_file() to serialize
    writers with atomic_write_json() for crash safety:

        with locked_file("/path/to/state.json", "a"):
            atomic_write_json("/path/to/state.json", new_data)
    """
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    # 'a' will create the file if missing; 'r' will error — so touch
    # if locking an absent file for read (rare, but helpful for tests).
    if mode.startswith("r") and not os.path.exists(path):
        open(path, "a").close()

    # Binary vs text
    binary = "b" in mode
    if binary:
        f = open(path, mode)
    else:
        f = open(path, mode, encoding=encoding)

    # Shared lock for read-only modes, exclusive otherwise
    lock_type = fcntl.LOCK_SH if mode in ("r", "rb") else fcntl.LOCK_EX

    try:
        fcntl.flock(f.fileno(), lock_type)
    except OSError as exc:
        f.close()
        raise OSError(f"Could not lock {path}: {exc}") from exc

    try:
        yield f
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


@contextmanager
def locked_update_json(path: PathLike, *, default: Any = None) -> Iterator:
    """
    Read-modify-write helper for JSON state files.

    Holds an exclusive lock on `path` for the duration of the block,
    yields the current contents (or `default` if missing/empty), and
    atomically writes whatever the caller assigned back into `path`.

    The caller must mutate the yielded object IN PLACE, or assign to
    `.value` on the returned handle. We yield a small mutable wrapper
    to make this ergonomic.

    Usage:
        with locked_update_json(STATE_PATH, default={}) as state:
            state.value["last_run"] = now
            state.value.setdefault("runs", []).append(run_info)

    On exit: the yielded object is serialised back via atomic_write_json
    under the same lock — so concurrent writers serialize cleanly and
    a crash mid-update leaves the file intact.
    """
    path = os.fspath(path)
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    # Touch lock file separately so we lock even when path doesn't exist
    lock_path = path + ".lock"
    lf = open(lock_path, "a+")
    try:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        lf.close()
        raise OSError(f"Could not lock {path}: {exc}") from exc

    try:
        # Read current value
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("locked_update_json: %s unreadable (%s) — using default", path, exc)
                current = default if default is not None else {}
        else:
            current = default if default is not None else {}

        handle = _UpdateHandle(current)
        yield handle

        # Write back atomically
        atomic_write_json(path, handle.value)
    finally:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lf.close()


class _UpdateHandle:
    """Mutable wrapper for locked_update_json; lets callers either
    mutate .value in place or replace it entirely."""
    __slots__ = ("value",)

    def __init__(self, initial: Any):
        self.value = initial


# ── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile as _t

    logging.basicConfig(level=logging.INFO)
    with _t.TemporaryDirectory() as d:
        p = os.path.join(d, "state.json")

        # Atomic write
        atomic_write_json(p, {"a": 1, "b": [1, 2, 3]})
        with open(p) as f:
            assert json.load(f) == {"a": 1, "b": [1, 2, 3]}
        print("atomic_write_json: OK")

        # Atomic text
        tp = os.path.join(d, "memo.txt")
        atomic_write_text(tp, "hello\nworld\n")
        with open(tp) as f:
            assert f.read() == "hello\nworld\n"
        print("atomic_write_text: OK")

        # locked_file read
        with locked_file(p, "r") as f:
            data = json.load(f)
            assert data["a"] == 1
        print("locked_file (read): OK")

        # locked_update_json round trip
        with locked_update_json(p, default={}) as h:
            h.value["c"] = "new"
        with open(p) as f:
            assert json.load(f)["c"] == "new"
        print("locked_update_json: OK")

        print("\nAll safe_io self-tests passed.")
