# Refactoring plan: splitting `alicia.py`

`myalicia/alicia.py` is the legacy monolith carried over from the original private codebase — 7,951 lines, sanitized but still single-file. Splitting it into the `myalicia/core/` package is the major outstanding refactor for v0.2.0.

This doc describes the planned split, the extraction order, and the rationale. It exists so contributors can pick up a focused chunk of the work without needing to hold the whole picture in their head.

## The end state

```
myalicia/
├── core/
│   ├── security.py            # security level + chat_guard decorator
│   ├── vault_io.py            # write_to_obsidian, get_vault_context
│   ├── system_prompt.py       # build_system_prompt
│   ├── handle_message.py      # the 10-step message pipeline
│   ├── voice.py               # handle_voice, _handle_call_voice, _handle_unpack_voice
│   ├── telegram_commands.py   # all the cmd_* handlers
│   ├── scheduler.py           # scheduled tasks (morning/midday/evening/weekly)
│   └── main.py                # bot setup + main() entry point
├── skills/                    # already extracted (80 modules)
├── config.py                  # already extracted
├── cli.py                     # already extracted
└── alicia.py                  # → eventually deleted, becomes a 1-line shim
```

## Why incremental, not big-bang

A big-bang split risks breaking the runtime in subtle ways. Each function in `alicia.py` references state, imports, and behavior that may not be obvious from a casual read. The safer path is one function (or one cluster of related functions) per PR, with verification at each step.

## Suggested extraction order

The order is chosen so each extraction has its dependencies already in place.

### Phase 1 — leaves first (low-risk, no internal callers to fix)

These are small, self-contained, and don't depend on other alicia.py logic:

1. **`core.security`** — `classify_security_level`, `get_context_size`, `security_emoji`, `log_interaction`, `chat_guard` (alicia.py:402–490)
2. **`core.vault_io`** — `write_to_obsidian`, `write_daily_log`, `get_vault_context` (alicia.py:493–528)

After Phase 1, the public package surface gets two clean modules and `alicia.py` shrinks slightly.

### Phase 2 — system prompt

3. **`core.system_prompt`** — `build_system_prompt` and its helpers (alicia.py:528–826). It's large but pure: text in, text out. Make sure all hardcoded archetype paths route through `config.archetype.path`.

### Phase 3 — the pipeline

4. **`core.handle_message`** — `handle_message`, `_append_history`, `detect_email_intent` (alicia.py:826–1922). This is the biggest single chunk (~1100 lines). Extract carefully; verify by sending a message through a running instance after each move.

### Phase 4 — voice flows

5. **`core.voice`** — `handle_voice`, `_handle_call_voice`, `_handle_unpack_voice`, `handle_message_reaction` (alicia.py:1922–2393). Depends on `handle_message`, so extract after Phase 3.

### Phase 5 — Telegram commands

6. **`core.telegram_commands`** — all `cmd_*` functions (alicia.py:2393 to roughly 3500). Roughly 40 commands; can be done as one big PR or split into thematic groups (vault commands, memory commands, research commands, voice commands).

### Phase 6 — scheduler

7. **`core.scheduler`** — the `schedule.every().*.do(...)` registrations and the `safe_run` wrapper. Should expose a single `register_all(scheduler)` function called from main.

### Phase 7 — main

8. **`core.main`** — bot construction, command registration, scheduler startup, polling loop. After this, `alicia.py` becomes:

   ```python
   from myalicia.core.main import main
   main()
   ```

   Or deleted entirely, and `pyproject.toml` points `[project.scripts]` directly at `myalicia.core.main:main`.

## Extraction recipe (per PR)

For each function or cluster:

1. **Read** the function in `alicia.py` end-to-end. Note its imports, helpers it calls, state it touches.
2. **Add** it to the target `core/<module>.py` with explicit imports. Don't rely on alicia.py's import side-effects.
3. **Replace** the function body in `alicia.py` with `from myalicia.core.<module> import <name>` (so existing imports keep working during the transition).
4. **Test** by importing and calling the function from a clean Python session: `python3 -c "from myalicia.core.<module> import <name>; ..."`.
5. **Run** the smoke tests (when they exist — currently the legacy `tests/` folder is gitignored awaiting its own sanitization pass).
6. **Commit** with a message like `Extract <function> from alicia.py to core.<module>`.

## What stays in alicia.py during transition

Things that haven't been extracted yet stay in `alicia.py`. Nothing forces a flag-day. The package works in a half-extracted state because `core/` re-exports during transition.

## When the extraction is done

When `alicia.py` is empty (or a 1-line shim), update:

- `pyproject.toml` → `[project.scripts]` to point at `myalicia.core.main:main`
- `myalicia/cli.py` `cmd_run` to call `myalicia.core.main:main`
- `docs/ARCHITECTURE.md` → describe the actual realized core/
- `README.md` → remove any mention of the monolith
- Delete `alicia.py` (or leave a 1-line shim for backwards compat)

## Why it matters

The thin-harness/fat-skills pattern is the architectural soul of myalicia (with thanks to [Garry Tan](https://x.com/garrytan)). The skills layer is already there — 80 composable modules in `myalicia/skills/`. The core layer needs to *be* a thin harness, not a monolith. This refactor is what makes that real, and it's what makes the project welcoming to contributors who shouldn't have to read 8,000 lines to understand how to add a feature.
