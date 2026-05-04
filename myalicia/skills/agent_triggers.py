"""
agent_triggers.py — on-demand agent-task harness.

Gives Telegram slash commands (/synthesisnow, /researchnow <topic>,
/briefingnow) a uniform way to launch long-running agent work in a
background thread, with:

  - Per-name concurrency guard — one /synthesisnow at a time, but
    /synthesisnow and /researchnow can run in parallel.
  - Immediate ack when started ("running, ETA ~Nmin").
  - Single final Telegram reply on completion, formatted by the caller.
  - Uniform error reporting (RuntimeError/APIError/etc.) with a log hint.
  - running_summary() for /tasks to list in-flight agent runs.

v1 intentionally does NOT stream progress pings. When/if we want that,
run_weekly_deep_pass + research_deep need instrumentation with a
`progress_callback` parameter; agent_triggers would then schedule those
pings onto the main asyncio loop. See the `format_started`/`format_result`
callback pattern below — `format_progress(step, total)` would slot in
symmetrically.

Architecture notes:
  - Background work runs in a plain threading.Thread — NOT asyncio.
    (run_weekly_deep_pass etc. are synchronous Python; executing them
    on the asyncio loop would block every other message.)
  - The final Telegram send is scheduled back onto the main asyncio loop
    via asyncio.run_coroutine_threadsafe(). The caller passes its loop
    (captured with asyncio.get_event_loop() inside the handler).
  - safe_send_md is imported lazily to avoid a circular import
    (alicia.py imports this module at top-level).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import traceback
from typing import Any, Callable
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

# Per-name registry of in-flight triggers.
# Shape: {name: {"thread": Thread, "started_at": float, "label": str}}
_lock = threading.Lock()
_running: dict[str, dict] = {}


def is_running(name: str) -> bool:
    """Return True if a trigger with this name is currently executing."""
    with _lock:
        entry = _running.get(name)
        return bool(entry and entry["thread"].is_alive())


def running_summary() -> list[dict]:
    """Snapshot of currently-running triggers for /tasks etc.

    Returns: [{"name": "synthesis", "label": "...", "elapsed_s": 42}, ...]
    """
    now = time.time()
    out = []
    with _lock:
        for name, entry in list(_running.items()):
            if entry["thread"].is_alive():
                out.append({
                    "name": name,
                    "label": entry.get("label", name),
                    "elapsed_s": int(now - entry["started_at"]),
                })
    return out


def trigger(
    name: str,
    fn: Callable[..., Any],
    fn_args: tuple = (),
    *,
    bot: Any,
    chat_id: int,
    loop: asyncio.AbstractEventLoop,
    format_result: Callable[[Any, float], str],
    format_started: Callable[[], str] | None = None,
    label: str | None = None,
) -> tuple[bool, str]:
    """Launch fn(*fn_args) in a background thread and ping Telegram when done.

    Args:
        name:          Unique per-kind key ("synthesis", "research",
                       "briefing"). Concurrent triggers with the same
                       name are rejected.
        fn:            Synchronous callable that does the actual work.
        fn_args:       Positional args for fn.
        bot:           python-telegram-bot Bot instance (thread-safe send).
        chat_id:       Telegram chat to reply to (typically TELEGRAM_CHAT_ID).
        loop:          The asyncio event loop the bot runs on. The
                       background thread schedules its final send onto
                       this loop via run_coroutine_threadsafe.
        format_result: Called on success: format_result(fn_return, duration_s)
                       → Telegram text. Keep under 4000 chars (Telegram cap).
        format_started: Optional. Called for the ack text. Defaults to a
                       generic "started" line.
        label:         Optional human label for running_summary() /
                       /tasks. Defaults to name.

    Returns:
        (started, ack_text)
        started=True — background thread launched; ack_text tells the user
                       it's running.
        started=False — already a run with this name; ack_text says
                       "already running, ETA Xs elapsed."
    """
    with _lock:
        existing = _running.get(name)
        if existing and existing["thread"].is_alive():
            elapsed = int(time.time() - existing["started_at"])
            return False, (
                f"⏳ `{name}` already running ({elapsed}s elapsed). "
                f"Wait for it to finish; I'll ping automatically."
            )

        def _worker():
            start = time.time()
            try:
                result = fn(*fn_args)
                duration = time.time() - start
                text = format_result(result, duration)
                _schedule_send(loop, bot, chat_id, text)
            except Exception as e:
                duration = time.time() - start
                tb = traceback.format_exc(limit=4)
                log.error(
                    f"trigger[{name}] failed after {duration:.1f}s: {e}\n{tb}"
                )
                err_text = (
                    f"⚠️ `{name}` failed after {int(duration)}s\n"
                    f"`{type(e).__name__}: {str(e)[:200]}`\n"
                    f"_Check logs: tail -f ~/alicia/logs/stderr.log_"
                )
                _schedule_send(loop, bot, chat_id, err_text)

        t = threading.Thread(
            target=_worker, name=f"trigger-{name}", daemon=True
        )
        _running[name] = {
            "thread": t,
            "started_at": time.time(),
            "label": label or name,
        }
        t.start()

    ack = format_started() if format_started else (
        f"🚀 `{name}` started — I'll ping when done."
    )
    return True, ack


def _schedule_send(loop: asyncio.AbstractEventLoop, bot, chat_id: int, text: str):
    """Schedule safe_send_md onto the main asyncio loop from a worker thread.

    Lazy-imports safe_send_md to avoid a circular import at module load.
    Falls back to bot.send_message (plain text) if safe_send_md isn't
    importable (e.g. during isolated smoke tests).
    """
    async def _send():
        try:
            # Lazy import — alicia.py is the top-level package and it
            # imports this module, so we can't import from it at file load.
            from alicia import safe_send_md  # type: ignore
            await safe_send_md(bot, chat_id, text)
        except ImportError:
            # Fallback for test harnesses or isolated imports.
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception as inner:
                log.error(f"agent_triggers fallback send failed: {inner}")

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop)
    except RuntimeError as e:
        # Loop closed / not running. Log; there's no other channel.
        log.error(f"agent_triggers cannot schedule send: {e}")
