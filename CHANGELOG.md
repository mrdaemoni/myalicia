# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.1]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.1
[0.1.0]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.0
