# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/mrdaemoni/myalicia/releases/tag/v0.1.0
