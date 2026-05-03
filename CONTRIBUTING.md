# Contributing to myalicia

Thanks for being here. The contribution surface we are most excited about is **awareness primitives** — small, opinionated modules that turn some slice of life into structured memory the loops can metabolize.

Don't think of contributions as "writing code." Think of them as **designing perception**. That framing is what humorphism asks of designers in the agentic era.

## What we want

### Awareness primitives

Each primitive is a small module under `myalicia/skills/` that does one of:

- Detects a pattern in the user's vault, conversation, or behavior
- Surfaces those patterns at the right moment in the right loop
- Feeds insight back into the user's understanding of themselves

Examples that already ship: `curiosity_engine` (novelty detection), `temporal_patterns` (rhythm detection), `emotion_model` (mood arc tracking), `way_of_being` (consistency over time).

Examples that don't yet exist but would be welcome:

- A reading-pattern primitive that notices what books you finish vs. abandon
- A calendar-rhythm primitive that catches when your week's shape changes
- A relationship-graph primitive built from messages and meetings
- A friction primitive that notices when a recurring task is becoming heavier
- A delight primitive that catches what you keep coming back to

### Surface adapters

New ways to reach myalicia — Discord, iMessage, voice, Apple Watch, terminal. Each adapter lives in `myalicia/surfaces/` and wraps the same `handle_message` pipeline. Each is roughly 200 lines of integration code.

### Archetypes

Each archetype is a small YAML file in `examples/archetypes/`. New voices, new personalities. We'd love a community library here. See `examples/archetypes/curious-builder.yaml` for the structure.

### Diagrams and docs

Visual or written explanations for designers and builders. The repo and the [myalicia.com](https://myalicia.com) site both welcome these.

## How to write a skill

1. Read 2-3 existing skills in `myalicia/skills/` to absorb the patterns. `curiosity_engine.py` and `temporal_patterns.py` are good starting points.
2. Each skill is a Python module that exposes a small handful of public functions.
3. Use `from myalicia.config import config` for any user-specific data (paths, identity, timezone).
4. **Never hardcode personal information.** Everything user-specific must come from config.
5. Write a docstring at the top of the module that answers: *what slice of life does this primitive perceive, and at which loop does it surface?*
6. If your primitive runs on a schedule, document the cadence (Listen / Notice / Know).

## How to write a surface adapter

1. Look at `myalicia/skills/proactive_messages.py` for an example of how messages flow.
2. Your adapter wraps `handle_message(text) -> response` with whatever protocol your surface speaks.
3. Add a section to `myalicia/config.py` for adapter-specific config.
4. Document deployment in `examples/deployments/`.

## Pull request flow

1. Fork the repo, branch off `main`
2. Make your change
3. Verify: `python -m py_compile myalicia/skills/your_skill.py`
4. Open a PR with:
   - A one-paragraph description of what your primitive perceives and why
   - An example of the kind of thing it would notice
   - Which loop it surfaces in (Listen / Notice / Know)

## Code review priorities

We care most about, in order:

1. **Personal data hygiene** — does anything in this PR hardcode info about a specific person?
2. **Loop placement** — is this surfacing at the right cadence?
3. **Idiom fit** — does it read like it belongs in this codebase?
4. **Tests / examples** — is there a way to see it working?

## Code of conduct

Be kind. Build with care. The goal is a teammate that fits one human at a time — that means we treat each other like teammates too.
