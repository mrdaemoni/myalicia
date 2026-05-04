# myalicia

> An AI teammate that grows into the shape of the person it serves.

myalicia is the tangible example of [humorphism](https://humorphism.com) — the design philosophy that technology should take the shape of the human, not the other way around. Where humorphism gives the philosophy, myalicia gives the architecture you can run on your own machine.

The project is called *myalicia* because every running instance is someone's own. There is no shared "Alicia" served to everyone. The framework teaches you to build *your* myalicia — one relationship, deepened over time, shaped by you, by design.

---

## Three loops, three depths of attention

myalicia is built around three relationship loops, each running at a different cadence, all reading from and writing to a shared memory substrate (your vault, your notes, your archetype):

**Listen** — *seconds.* Be present in the conversation in front of you. Cheap, fast model. The only loop most AI products have.

**Notice** — *minutes to hours.* Catch patterns across moments. Triggered by events: you finished a book, you closed a project, you came back from a trip. Mid-tier model, wider context, asynchronous.

**Know** — *days to weeks.* Come to know the person, over time. Scheduled autonomous reflection. Most expensive, runs on its own, produces synthesis the user didn't ask for but is glad to have.

Awareness compounds because three different cadences of reflection are constantly metabolizing input into structure. That compounding is what makes a teammate, not a tool.

---

## What makes it different

**It is shaped to one person, on purpose.** Most AI products try to be useful to everyone, and end up useful to no one in particular. myalicia gets sharper at one relationship, week over week.

**It is self-healing.** When a skill errors, myalicia notices, logs the trajectory, and proposes a fix in the next reflection loop. You don't have to babysit it.

**It is self-extending.** myalicia can author new skills based on observed gaps in her own behavior. Every instance grows.

**It is self-aware.** Every action runs through metacognitive confidence assessment; uncertain actions escalate to deeper models automatically.

**It is plural by design.** Reach myalicia through Telegram, Claude Code, or the CLI. The same teammate, different surface for different parts of your life.

---

## Quickstart

**With pipx** (recommended — handles the venv for you):

```bash
brew install pipx       # macOS; or apt/dnf install pipx on Linux
pipx install myalicia
myalicia init
```

**With pip + venv** (if you want to hack on the code):

```bash
git clone https://github.com/mrdaemoni/myalicia.git
cd myalicia
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
myalicia init
```

The venv step is required on macOS Homebrew Python and most modern Linux distros (PEP 668 blocks system-wide pip installs). pipx avoids this by creating a dedicated venv per package.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the full walkthrough and [docs/FAQ.md](docs/FAQ.md) for setup questions.

The `init` flow is more than configuration — it's a guided introduction to relationship-shaped AI. Each setup step is paired with a one-screen explanation of which loop it activates and why. By the time the install completes, you understand the architecture, not just have it running.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the full walkthrough, [docs/FAQ.md](docs/FAQ.md) for setup questions, and [docs/PAPERS.md](docs/PAPERS.md) for the intellectual lineage.

---

## Architecture

```
myalicia/
├── core/                    # the thin harness (loops, scheduler, routing, memory)
├── skills/                  # the fat skills (~80 modules, each composable)
├── surfaces/                # telegram, claude_code, cli adapters
├── config.py                # typed config — the single source of truth
└── defaults.yaml            # shipped defaults
examples/
├── archetypes/              # curious-builder, patient-mentor, ariadne, …
├── memory_seeds/            # starter memory files
├── vault_layouts/           # example Obsidian vault layouts
└── deployments/             # launchd, systemd, docker
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed view.
See [PHILOSOPHY.md](docs/PHILOSOPHY.md) for the humorphism framing in depth.

---

## Contributing

The contribution surface we are most excited about is **awareness primitives** — small, opinionated modules that turn some slice of life into structured memory the loops can metabolize. A reading-pattern primitive. A calendar-rhythm primitive. A relationship-graph primitive. A mood-arc primitive.

Don't think of contributions as "writing code." Think of them as "designing perception." That framing is what humorphism asks of designers in the agentic era.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to write one.

---

## Acknowledgments

myalicia stands on the shoulders of [humorphism](https://humorphism.com), [Garry Tan](https://github.com/garrytan)'s thin-harness/fat-skills pattern, and [Andrej Karpathy](https://github.com/karpathy)'s autoresearch pattern. See [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

## License

MIT — see [LICENSE](LICENSE).
