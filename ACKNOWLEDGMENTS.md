# Acknowledgments

myalicia stands on the shoulders of work by people who saw something the rest of us hadn't yet. The architecture, the framing, and the philosophy here are deliberate echoes of theirs.

## Humorphism

myalicia is a tangible example of **humorphism** — the design philosophy that technology should take the shape of the human, not the other way around. Where humorphism gives the philosophy, myalicia gives the architecture.

The framework reframes AI design from "build a chatbot" to "design a relationship," and that reframing is the entire reason this project exists in the form it does. The three relationship loops (Listen, Notice, Know) are humorphism made buildable.

Read more at [humorphism.com](https://humorphism.com).

## Garry Tan — Thin Harness, Fat Skills

The architectural pattern of a thin orchestration core surrounded by fat, composable skill modules comes from [Garry Tan](https://github.com/garrytan)'s thinking on agent design. myalicia's `myalicia/core/` (small, opinionated) and `myalicia/skills/` (many, replaceable) is a direct application of that pattern.

The pattern matters because it makes contribution natural: people don't need to understand the whole system to add a skill. Skills are the contribution surface; the core is intentionally small to keep them so.

## Andrej Karpathy — Autoresearch

The autonomous synthesis loops — the ones that run while you sleep and produce notes you didn't ask for but find yourself glad to have — draw on [Andrej Karpathy](https://github.com/karpathy)'s autoresearch pattern. The Notice and Know loops are myalicia's local, personal, single-user version of that idea: an agent doing work on your behalf, by itself, that compounds over time.

## The wider community

myalicia is also indirectly shaped by years of work in:

- The Obsidian vault community, for showing what a personal knowledge graph looks like in practice
- The Anthropic Claude Agent SDK, which makes the runtime possible
- Every contributor who files an issue, sends a PR, or shares an archetype

If you've used any of those, your thinking is somewhere in this codebase.
