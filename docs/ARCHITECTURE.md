# Architecture

myalicia is a thin core surrounded by composable skills, with three loops running over a shared memory substrate.

## The shape of the system

```
                Listen  (seconds, conversation)
         ┌───────────────────────────────┐
         │                               │
         │        Notice  (synthesis)    │
         │   ┌───────────────────────┐   │
         │   │                       │   │
         │   │      Know  (slow)     │   │
         │   │   ┌───────────────┐   │   │
   Telegram   │   │    Memory     │   │   Claude Code
        ────────►│   substrate   │◄────────
         │   │   │  vault·notes  │   │   │
         │   │   │   archetype   │   │   │
         │   │   └───────────────┘   │   │
         │   │                       │   │
         │   └───────────────────────┘   │
         │                               │
         └───────────────────────────────┘
```

Three loops. One memory. Two surfaces (so far).

## Thin harness, fat skills

The architectural pattern (with thanks to [Garry Tan](https://x.com/garrytan)) is a small, opinionated core that handles orchestration and routing, surrounded by many composable skill modules that each do one thing well. The core is intentionally small because the skills are the contribution surface.

```
myalicia/
├── __init__.py              # package identity, version
├── config.py                # the typed configuration layer (single source of truth)
├── defaults.yaml            # shipped defaults, copied to ~/.alicia/config.yaml on init
├── cli.py                   # the `myalicia` command — init / run / status / version
├── alicia.py                # legacy monolith (368KB) — being split into core/ over time
└── skills/                  # ~80 composable modules
    ├── __init__.py
    ├── tool_router.py       # function-calling dispatcher
    ├── reflexion.py         # post-task self-critique
    ├── metacognition.py     # confidence assessment + Opus escalation
    ├── memory_skill.py      # 3-tier memory primitives
    ├── vault_intelligence.py
    ├── curiosity_engine.py  # novelty detection
    ├── ...
    └── (many more)
```

## The three loops in detail

| Loop | Cadence | Model | What it does |
|---|---|---|---|
| **Listen** | seconds | Haiku | Conversation in the moment. The only loop most AI products have. |
| **Notice** | minutes–hours | Sonnet | Event-triggered synthesis: you finished a book, you closed a project, you came back from a trip. |
| **Know** | days–weeks | Opus | Scheduled autonomous reflection: morning briefings, weekly synthesis, monthly archetype review. |

Cheap by default — turn the dial up only where depth matters.

Each loop writes to memory. The next loop reads from memory. Awareness compounds.

## Self-healing, self-extending, self-aware

Three traits surfaced as teammate qualities, not internal plumbing:

- **Self-healing** (`self_improve.py`, `meta_reflexion.py`) — when a skill errors, the system notices, logs the trajectory, and proposes a fix in the next reflection.
- **Self-extending** (`skill_author.py`) — myalicia can author new skills based on observed gaps in her own behavior.
- **Self-aware** (`metacognition.py`) — every action runs through confidence assessment; uncertain actions escalate to deeper models.

## Surfaces

Surfaces are pluggable. Each is a small adapter wrapping the same `handle_message` pipeline.

Currently shipped:

- Telegram (conversational) — primary Listen-loop channel
- CLI — for testing and dev

Planned:

- Claude Code (technical / coding context)
- Discord, iMessage, voice — community contributions welcome

See [CONTRIBUTING.md](../CONTRIBUTING.md) for how to add a surface.

## Memory substrate

The substrate is the user's knowledge vault — typically an Obsidian-formatted folder. The shape:

```
{user_vault}/
└── Alicia/
    ├── Bridge/        # surfacing queue between Alicia and the user
    ├── Wisdom/        # synthesis output (Notice and Know loops write here)
    └── Self/          # archetype + profile data
```

The shape is configurable — see `myalicia.config.VaultConfig`. Different users may have different vault layouts, and the framework adapts.

## Configuration

Everything user-specific resolves through `myalicia.config.config`:

- `config.user.name` — what to call you
- `config.vault.root` — where your vault lives
- `config.archetype.name` — which personality file to load
- `config.models.{listen,notice,know}` — model assignments per loop
- `config.surfaces.{telegram,cli,claude_code}` — which channels are active

Resolution order: env vars (`ALICIA_*`) override `~/.alicia/config.yaml`, which overrides shipped `defaults.yaml`. The `config` object is loaded once at import and is read-only at runtime.
