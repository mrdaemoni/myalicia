# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] — 2026-05-14

A privacy and identity hardening pass. The shipped wheel up through v0.1.4 contained leftover references that narrowed who the maintainer is (first name in lowercase identifiers, employer-internal product names, device model, named-thinker defaults, gendered pronouns). v0.1.5 ships the cleaned tree as the canonical install path; older versions are yanked.

### Changed

- **Identifier rename**: `hector` → `user` across 14 tracked files (functions, dict keys, file-name conventions, prompt strings, test fixtures).
- **Surface rename**: `Cowork` → `Desktop` across 7 tracked files. The architectural pattern (a longer-running synthesis surface paired with a conversational surface) is unchanged; only the label is generic now.
- **Web dashboard security**: server binds to `127.0.0.1` by default. Set `DASHBOARD_HOST=0.0.0.0` to opt into broader binding. The `POST /api/capture` endpoint now requires a loopback client OR a matching `X-Dashboard-Token` header (token in `DASHBOARD_TOKEN`).
- **`run_scheduler` docstring**: clarifies that the wall-clock times are starter defaults staggered to spread API load, not personal cadence — customize them in your config.

### Removed

- **Hardcoded thinker fingerprints**: named-author defaults (`_AUTHOR_ALIASES` in `tool_router`, source-folder lists in `semantic_search` / `vault_ingest` / `vault_intelligence`, knowledge-cluster labels in 4 modules, prompt-template anchor lists) replaced with empty defaults or neutral placeholders. The pattern is unchanged — your live MEMORY.md and synthesis notes are the source of truth for which authors your instance "thinks with."
- **`tests/TEST_REPORT.md`**: stale test report that leaked device, employer-internal product, Python version, venv path, and proxy infrastructure.
- **Employer-specific keywords**: `amazon` / `rsu` removed from `user_model.py` work-classifier keywords.
- **Gendered pronouns**: `his wife / his daughter / him` etc. replaced with `their / them` in `dimension_research.py`, `memory_skill.py`, `proactive_messages.py`.

### Fixed

- **`alicia.py`** was missing `from myalicia.config import ENV_FILE, LOGS_DIR, MEMORY_DIR, ALICIA_HOME, config` — would have raised `NameError` on import for anyone using the package as installed.
- **`web_dashboard.py`** was missing the same imports.
- **`proactive_messages.py`** was shadowing `MEMORY_DIR` (a `Path`) with `str(MEMORY_DIR)`, then trying to use the `/` operator on it later in the file.

### CI

- **Personal-data scan** now reads its regression patterns from the `PERSONAL_DATA_PATTERNS` GitHub secret instead of inlining them in the workflow file. The patterns no longer ship inside the public repo. The scan auto-skips on forks where the secret isn't set.

## [0.1.2] — 2026-05-04

A polish release covering Phase 2e–2g extractions, the cross-skill path sweep, install-friction fixes, and a small clarifying tweak to the Papers page.

### Added

- **`myalicia.core.main`** populated: `ALICIA_MENU_COMMANDS` and `set_alicia_menu_commands` extracted from `alicia.py`. First real content for what will eventually be the runtime entry point.
- **`config.py` constants**: `ALICIA_HOME`, `LOGS_DIR`, `MEMORY_DIR`, `ENV_FILE` — per-instance paths derived from `USER_CONFIG_DIR` (`~/.alicia/` by default, overridable via `ALICIA_HOME` env var).

### Changed

- **Cross-skill path sweep**: 99 hardcoded `~/alicia/` references across 56 skill files replaced with config-driven equivalents (`MEMORY_DIR`, `LOGS_DIR`, `ENV_FILE`, etc.). Without this, `pip install myalicia` would have failed for any user not running on the original codebase's machine layout.
- **`alicia.py` paths**: 12 sites updated to use config-driven paths (load_dotenv, LOG_FILE, voice cache, hot_topics.md, analytical_briefing.md, user-facing log-tail messages).
- **Quickstart docs**: README and `docs/QUICKSTART.md` now lead with `pipx install myalicia` and document the venv path for developers — fixes the PEP 668 externally-managed-environment friction every new macOS user was hitting.

### Fixed

- **Papers page**: corrected the humorphism source citation to use humorphism.com's own definition rather than an external write-up.

### Internal

- `alicia.py` shrunk a further ~3 KB (cumulative shrink ~16 KB since v0.1.0).

## [0.1.1] — 2026-05-04

A consolidation release that extends Phase 1 of the `core/` extraction with several leaf moves, makes `myalicia run` actually wire up the runtime, and fixes a Python 3.12 syntax-check regression.

### Added

- **`myalicia.core.telegram_safety`**: `safe_reply_md`, `safe_send_md`, `_strip_markdown` (extracted from `alicia.py`).
- **`myalicia.core.intents`**: `detect_email_intent`, `EMAIL_PHRASES` (extracted from `alicia.py`). Planned home for future intent classifiers.
- **`myalicia.core.security` extensions**: `chat_guard`, `log_interaction` joined the existing module. Both now config-driven; `chat_guard` reads from `config.surfaces.telegram.allowed_chat_ids` (a tuple, supporting multi-chat instances).
- **`myalicia.core.vault_io.get_vault_context`**: the semantic vault retrieval + Obsidian deep-link formatter, now config-driven (vault name derives from `config.user.handle`, overridable via `ALICIA_VAULT_NAME` env var).
- **CI**: GitHub Actions workflow now uses `python -m compileall` (reliable, reports failing filenames) and bumps to `actions/checkout@v5`, `actions/setup-python@v6`, etc.
- **Auto-publish to PyPI**: tag-driven release workflow at `.github/workflows/publish.yml` using PyPI's Trusted Publisher OIDC flow. See `PUBLISHING.md` for the one-time setup.

### Changed

- **`myalicia run` actually runs**: `cmd_run` now boots the legacy `alicia.py` main with pre-flight environment checks for `ANTHROPIC_API_KEY` and `TELEGRAM_BOT_TOKEN`, and prints active config before starting. Once `core/main.py` extraction lands in v0.2, this swaps to `myalicia.core.main:main` without changing the user-facing CLI.
- **Quickstart honesty**: README and QUICKSTART now reflect the source-install path for v0.1.0/v0.1.1, with the v0.2 PyPI path noted.

### Fixed

- **Python 3.12 syntax check**: 26 docstrings across 19 skill files were inadvertently f-stringified by the original v2 sanitizer (before its v3 fix). Python 3.12 strictly rejects f-strings as docstrings; reverted them all to plain triple-quoted strings with `{USER_NAME}` → `the user` substitution. Compileall now passes on 3.10/3.11/3.12.

### Internal

- `alicia.py` shrunk from 367 KB to 355 KB across the small extractions.

## [0.1.0] — 2026-05-03

The initial public release.

### Added

- **Package skeleton**: `myalicia` Python package with typed config layer (`config.py`, `defaults.yaml`), CLI entry point (`cli.py`), and 80 composable skill modules in `myalicia/skills/`
- **Three relationship loops**: Listen / Notice / Know — the core architectural primitive, documented across the README, philosophy page, and architecture page
- **Skill modules**: 80 sanitized skill modules covering conversation, memory, vault intelligence, synthesis, voice, dashboards, self-improvement, and surfacing
- **Legacy runtime**: `myalicia/alicia.py` (the 7951-line monolith) — sanitized end-to-end, parses cleanly, will be split into `core/` modules incrementally per `REFACTORING.md`
- **Bootstrap CLI**: `myalicia init` walks new users through configuration while teaching the three loops as it configures them. Plus `myalicia run`, `myalicia status`, `myalicia version`.
- **Example archetypes**: `curious-builder`, `patient-mentor`, `ariadne` — three voices to choose from at install, plus instructions for authoring custom ones
- **Documentation**: README, ACKNOWLEDGMENTS, CONTRIBUTING, PHILOSOPHY, ARCHITECTURE, QUICKSTART, REFACTORING, GIT_SETUP, EXTRACTION_PLAN
- **Companion site**: [www.myalicia.com](https://www.myalicia.com) — Astro static site explaining humorphism and the project, with four diagrams (loops, altitudes, self-growth, skill anatomy)
- **License**: MIT
- **pyproject.toml**: pip-installable, with optional extras for `telegram`, `voice`, `gmail`, `search`, `pdf`, `schedule`, plus `all`

### Acknowledgments

Built on [humorphism](https://humorphism.com), [Garry Tan](https://x.com/garrytan)'s thin-harness/fat-skills pattern, and [Andrej Karpathy](https://x.com/karpathy)'s autoresearch idea. See [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md) for full credit.

### Known limitations

- `alicia.py` is still a single 7951-line file. Splitting it into `core/` modules is the major work for v0.2.0 — see [REFACTORING.md](./REFACTORING.md).
- Tests folder (`tests/`) included with the package, sanitized. Some tests require API keys or runtime state and are best run after a full `myalicia init`.
- Apex domain `myalicia.com` redirects to `www.myalicia.com` via Namecheap; full apex HTTPS requires moving DNS to Cloudflare (planned).

[0.1.2]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.2
[0.1.1]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.1
[0.1.0]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.0
