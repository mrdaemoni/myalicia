# Alicia Test Suite Report

**Date:** 2026-03-28
**Suite Version:** 1.0
**Result:** 97 passed, 48 skipped (live-only), 0 failures

---

## Architecture Under Test

Alicia is a sovereign AI agent running on a Mac Mini M4 with dual interfaces (Telegram via Sonnet, Cowork via Opus), 18 skill modules, a three-layer memory system, and deep Obsidian vault integration. The test suite validates every subsystem without making real API calls or sending Telegram messages.

The system runs under Python 3.14 (Homebrew) with a project venv at `~/alicia/venv`.

---

## Test Suite Inventory

### Unit Tests (pytest, run anywhere)

| Suite | File | Tests | What it covers |
|-------|------|-------|----------------|
| Markdown Safety | test_markdown_safety.py | 11 | `safe_reply_md()` / `safe_send_md()` helpers, real-world crash inputs (vault titles with underscores, email bodies, research output) |
| Memory System | test_memory_system.py | 8 | `ensure_memory_structure`, `load_memory_files`, `sync_to_vault`, `remember` truncation bug fix, `extract_from_message`, `append_to_memory_file` |
| Tool Router | test_tool_router.py | 11 | `route_message()` text/tool_use/error parsing, `execute_tool()` for remember/search_vault/send_email/research, unknown tool handling, None results |
| Security & Routing | test_security_and_routing.py | 18 | Security levels 1-4, case insensitivity, context window sizing, email/PDF/voice intent detection, credential redaction, conversation windowing, message chunking |
| Proactive Messages | test_proactive_messages.py | 10 | `build_startup_stats`, `build_startup_greeting`, API failure fallback, Markdown sanitization, Telegram message length limits, scheduler timing (morning/daily/curiosity/consolidation) |
| Reflexion & Metacognition | test_reflexion_and_metacog.py | 14 | `should_reflect()` gating, `should_evaluate()` gating, `TrajectoryRecorder` (creation/recording/significance/save), `assess_confidence`, prompt injection handling, `should_use_opus`, novelty detection |
| Vault Operations | test_vault_operations.py | 10 | `resolve_note`, `determine_level`, `format_knowledge_dashboard`, `get_random_quote`, vault writing (file creation, special chars in filenames) |
| Voice Pipeline | test_voice_pipeline.py | 6 | `get_voice_status`, ffmpeg detection, TTS text cleaning, empty text handling, voice request phrase matching |
| Integration Flows | test_integration_flows.py | 10 | Full text→route→response flow, route→tool→execute, error type fallback, memory extraction→store→sync, short/long result formatting, email confirmation (requires confirmation, data preserved), conversation history management |

### Live Smoke Tests (Mac Mini only, no pytest needed)

| File | Tests | What it covers |
|------|-------|----------------|
| smoke_test.py | 46 | All skill module imports, critical path/file existence, memory file integrity, env var validation, tool router wiring (TOOLS list, critical tools, route_message, execute_tool), reflexion/constitution/trajectory wiring, proactive message wiring, vault system wiring, Markdown safety helpers in source, raw parse_mode audit, Python syntax validation |

---

## How to Run

### Unit tests (Cowork VM or any machine with pytest)

```bash
cd ~/alicia
pip install pytest pytest-asyncio anthropic python-dotenv
python3 -m pytest tests/ -v --tb=short
```

### Live smoke tests (Mac Mini with venv)

```bash
cd ~/alicia
source venv/bin/activate
python tests/smoke_test.py
```

---

## Bugs Found and Fixed

### BUG 1: Telegram Markdown crash on vault source titles (CRITICAL)

**Symptom:** "Something went wrong. Check the logs." when asking Alicia about vault content with underscore-heavy titles.

**Root cause:** Vault note titles like `Zen_and_the_Art_of_Motorcycle_Maintenance` contain unbalanced underscores which Telegram Markdown V1 interprets as italic markers. This caused `TelegramBadRequest: Can't parse entities` inside the outer try/except, triggering the generic error.

**Fix:** Created `safe_reply_md()` and `safe_send_md()` helpers that try Markdown first, catch `TelegramBadRequest`, strip formatting, retry as plain text. Converted all 21 raw `parse_mode="Markdown"` sends across alicia.py (only the 2 inside the helpers themselves remain).

### BUG 2: Python 3.14 f-string backslash syntax error

**Symptom:** `SyntaxError: f-string expression part cannot include a backslash` on startup.

**Root cause:** Python 3.14 removed support for backslashes inside f-string expressions. Line 629 of `vault_intelligence.py` had `.replace(' ', '-')` inline inside an f-string.

**Fix:** Extracted the slug computation to a variable before the f-string.

### BUG 3: `route_message()` error type falls through silently

**Symptom:** When the Anthropic API is unreachable, `route_message()` returns `{"type": "error"}` which falls through both `text` and `tool_use` checks to the else branch showing "Something went wrong."

**Status:** By design (the error display IS the fallback), but now explicitly tested so future refactors don't break this path.

---

## Architecture Observations

### Import-time side effects

Every skills module creates an `Anthropic()` client at module level during import. If `.env` is missing or corrupted, no skill will import. This is also why the test suite needs `conftest.py` to set fake env vars and strip SOCKS proxy vars before any import.

**Recommendation:** Consider lazy client initialization or a shared client singleton.

### Memory sync has no conflict resolution

`sync_to_vault()` does a blind copy from `~/alicia/memory/` to the vault. If the vault copy is edited directly in Obsidian, those changes get silently overwritten.

### Remaining `parse_mode="Markdown"` audit

After the fix, exactly 2 `parse_mode="Markdown"` references remain — both inside the safe helper functions themselves. The smoke test audits this count automatically.

---

## Test Infrastructure Notes

**conftest.py** sets up fake environment variables and strips SOCKS proxy vars before any skill imports (critical for the Anthropic client). It also provides shared fixtures (`tmp_memory_dir`, `tmp_vault`) and test data arrays (`MARKDOWN_BREAKING_INPUTS`, `SAFE_MARKDOWN_INPUTS`).

**smoke_test.py** is a zero-dependency script (no pytest) that runs directly with `python`. It loads `.env` manually, imports all skill modules through the venv, and validates the entire system's wiring.
