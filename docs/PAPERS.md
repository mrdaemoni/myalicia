# Papers and Ideas Alicia Draws From

myalicia is built on the shoulders of researchers, designers, and frameworks that saw something the rest of us hadn't yet. This FAQ lists the papers, concepts, and intellectual foundations that shaped the project's architecture, philosophy, and capabilities.

---

## Foundational & Architectural

These are the core concepts the entire system is built around.

### Humorphism — Design Philosophy

**Source:** [humorphism.com](https://humorphism.com)

**What it is:** A design philosophy that seeks to replace the user interface built for operating tools with a *human interface* built for collaborating with AI teammates.

**How myalicia uses it:** The entire three-loop architecture (Listen, Notice, Know) is humorphism made buildable. The "thin harness, fat skills" pattern operationalizes the principle that the system should stay out of the way so the human's personality can emerge. Every surface, every feedback mechanism, every memory update is designed to deepen one relationship, not serve everyone equally.

---

### Thin Harness, Fat Skills — Garry Tan

**Source:** [Garry Tan](https://x.com/garrytan) (GitHub: [garrytan](https://github.com/garrytan))

**What it is:** An architectural pattern for agent design: a small, opinionated orchestration core surrounded by many composable skill modules, each replaceable and each focused on one thing.

**How myalicia uses it:** The pattern is visible in the folder structure: `myalicia/core/` is intentionally small (routing, scheduling, memory substrate), while `myalicia/skills/` contains ~80 composable modules. This keeps the contribution surface open—you don't need to understand the whole system to add a skill. Skills are where the personality lives; the core stays thin so they can shine. This is reflected in `/improve`'s ability to rewrite skill config rules and in `/skill_author`'s drafting of new skills from observed gaps.

---

### Autoresearch — Andrej Karpathy

**Source:** [Andrej Karpathy](https://x.com/karpathy) (GitHub: [karpathy](https://github.com/karpathy))

**What it is:** The pattern of autonomous research loops where an agent runs reflection and synthesis on its own, without human prompting, and produces insights the human didn't ask for but finds themselves glad to have.

**How myalicia uses it:** The Notice and Know loops are myalicia's local, personal, single-user version of autoresearch. The system runs synthesis passes while you sleep, detects novelty in conversations, generates curiosity-driven explorations, and writes synthesis notes to your vault autonomously. Weekly and monthly reflection passes extract patterns from episodes, procedures, and trajectory data—all without explicit prompting. The key difference: autoresearch scaled to a shared research team; myalicia scales it down to one person's knowledge growth.

---

## Module-Level Frameworks

These papers and concepts name or directly shape specific skill modules.

### Reflexion — Language Agents with Verbal Reinforcement Learning

**Title:** "Reflexion: Language Agents with Verbal Reinforcement Learning"

**Authors:** Shinn et al. (2023)

**ArXiv:** [2303.11366](https://arxiv.org/abs/2303.11366)

**What it is:** A framework where agents critique their own outputs after execution, storing those critiques as episodic memory and retrieving them for similar future tasks. All learning happens through linguistic feedback in context—no weight updates.

**How myalicia uses it:** The `reflexion.py` skill implements this directly. After significant tasks (pdf generation, email, research, vault synthesis), Alicia generates a brief self-critique with:
- What went well
- What to improve next time
- A procedure to remember
- Confidence score
- Decision attribution (which steps helped or hurt)

These reflexion episodes are stored and retrieved by `episode_scorer.py` for future similar tasks, creating a feedback loop that improves performance without retraining.

---

### Constitutional AI — Bai et al.

**Title:** "Constitutional AI: Harmlessness from AI Feedback"

**Authors:** Bai et al. (Anthropic, 2022)

**ArXiv:** [2212.08073](https://arxiv.org/abs/2212.08073)

**What it is:** A method where an AI system evaluates its own outputs against a set of principles, generating corrective feedback. The principles become a constitution that guides behavior without explicit rules.

**How myalicia uses it:** The `constitution.py` skill scores every significant output against ten principles:
- Depth over breadth
- Ground in experience
- Honour the source
- Earn your questions
- Remember the thread
- Name uncertainty
- Protect signal
- Serve the vault
- Respect silence
- Think across traditions

Low scores are flagged for improvement and tracked over time to reveal blind spots. This creates internal alignment pressure without rigid rules.

---

### Generative Agents — Park et al.

**Title:** "Generative Agents: Interactive Simulacra of Human Behavior"

**Authors:** Park, O'Neill, Jansen, Sap, Rashkin, Bailey (Stanford, 2023)

**ArXiv:** [2304.03442](https://arxiv.org/abs/2304.03442)

**What it is:** A framework where NPCs in a simulated environment carry memories, reflect on their behavior, and interact with each other using language models. The key insight: agents need multiple temporal scales of reflection (immediate response, reaction, daily planning, longer-term goals) to feel coherent.

**How myalicia uses it:** The three-loop cadence (Listen/seconds, Notice/hours, Know/weeks) is inspired by generative agents' multi-timescale architecture. The curiosity engine uses a modified version of the reflection cycle to generate exploration questions. The "proactive messages" skill surfaces synthesis and insights the way generative agents surface emergent behavior.

---

### Memento-Skills — Skill Self-Authoring

**Title:** "Memento-Skills: Learning Skills from Tasks"

**ArXiv:** [2603.18743](https://arxiv.org/abs/2603.18743)

**What it is:** An agent that learns new skills by observing task failures. When a task fails and no existing skill claims responsibility, the agent drafts a markdown skill stub, implements it, and adds it to its own library. On benchmark tasks, agents grew from 41 to 235 distinct skills with double the performance.

**How myalicia uses it:** The `skill_author.py` module implements this pattern. When reflexion identifies a failure that no existing skill claims, the system drafts a markdown skill stub and queues it in `~/alicia/skills/_pending/` for one-tap approval. The key safety constraint: stubs never auto-merge. They go to a pending folder, surface in the morning message, and only become real when you accept them. This preserves the SSGM rule that all memory writes are reversible.

---

### SSGM — Stability and Safety Governed Memory

**Title:** "Stability and Safety Governed Memory: A Framework for Evolving Memory Systems"

**ArXiv:** [2603.11768](https://arxiv.org/abs/2603.11768)

**What it is:** A framework for evolving memory systems that identifies three failure modes (semantic drift, privacy leakage, stability collapse) and proposes guardrails: staleness decay, provenance tracking, and rollback on divergence detection.

**How myalicia uses it:** The `memory_audit.py` skill implements these guardrails. Every rule that `/improve` writes gets re-evaluated for staleness, contradiction, and reward effect. Bad rules get flagged or auto-deprecated; good rules get their `last_corroborated` date refreshed. Every rule carries provenance metadata (who suggested it, when, why, confidence, validation results). Rules older than 30 days without corroboration are flagged; those below confidence 0.25 are auto-commented.

---

### MemRL — Memory-based Reinforcement Learning

**Title:** "MemRL: Self-Evolving Agents via Memory-based Reinforcement Learning"

**ArXiv:** [2601.03192](https://arxiv.org/abs/2601.03192)

**What it is:** Agents self-evolve at runtime through RL signals applied to episodic memory, without weight updates. A two-phase retrieval mechanism filters noise, then identifies high-utility strategies.

**How myalicia uses it:** The `episode_scorer.py` skill uses a two-phase retrieval for reflexion episodes:
- **Phase 1:** Broad semantic/task-type match to find candidate episodes
- **Phase 2:** Reward-score ranking with time decay to surface the highest-utility strategies

Episodes are scored on success signal (task score 4+ = high signal), confidence extracted from the reflection, whether a new procedure was learned, and user engagement depth. This creates a reinforcement signal that makes useful episodes more retrievable.

---

### Hyperagents — Self-Referential Agents

**Title:** "Hyperagents: Self-Referential Agents Can Edit Themselves"

**ArXiv:** [2603.19461](https://arxiv.org/abs/2603.19461)

**What it is:** A framework where a meta-agent can edit both task agents and itself, and improvements transfer across domains and accumulate across runs.

**How myalicia uses it:** The `meta_reflexion.py` module implements second-order compounding. It evaluates whether `/improve`'s changes were actually effective, and if effectiveness is declining, it rewrites the improvement prompts and heuristics. This closes the loop: the system that improves gets improved itself. When effectiveness drops below 50%, the meta-reflexion engine triggers to tune the `/improve` engine's prompts, rule-writing strategy, and target-selection heuristics.

---

### TIMG — Trajectory Importance-weighted Metric

**Title:** "TIMG: Trajectory Importance-weighted Metrics for Agent Learning"

**ArXiv:** [2603.10600](https://arxiv.org/abs/2603.10600)

**What it is:** A method for tracing decision impact through multi-step trajectories. Each decision in a sequence is attributed as positive (helped), negative (hurt), or neutral, so future retrieval can surface the specific decision that caused failure, not the whole transcript.

**How myalicia uses it:** The reflexion prompt includes `decision_attribution` — a per-step trace of which decisions in a task helped or hurt the outcome. This is what enables the episode retriever to surface the specific failure-causing decision next time, rather than making you re-read entire transcripts. If a task breaks down into discrete decisions, 1-4 key steps are labeled; otherwise, an empty list.

---

## Influence & Background Concepts

These shape the project's worldview and inform specific subsystems, though they're not directly cited in the code.

### ReAct — Reasoning and Acting

**Title:** "ReAct: Synergizing Reasoning and Acting in Language Models"

**Authors:** Yao, Zheng, Tan, et al.

**ArXiv:** [2210.03629](https://arxiv.org/abs/2210.03629)

**What it is:** A framework where agents interleave reasoning steps with action steps, and each action results in observation that informs the next step. The interaction between thought and action improves both.

**How myalicia draws from it:** The tool_router uses function-calling to route to specific skills, and trajectory recording captures the interaction between routing decisions and tool results. This mirrors ReAct's pattern of thought → action → observation → refined thought.

---

### Wise Machines — Building Wisdom in AI

**Title:** "Imagining and Building Wise Machines"

**Authors:** Johnson, Stanford (2024)

**What it is:** A framework for building AI systems that display wisdom: not just intelligence, but good judgment, humility about knowledge limits, and awareness of context.

**How myalicia uses it:** The metacognition engine (`metacognition.py`) is directly inspired by this work. It assesses Alicia's epistemic state along five dimensions:
- Confidence (1-5 scale with calibration)
- Knowledge boundary (what's known vs. inferred)
- Conflict detection (when retrieved memories contradict each other)
- Calibration (uncertainty noting)
- Decision mode (fast Sonnet vs. slow Opus escalation)

This is wisdom as machine capability: knowing what you don't know, escalating when uncertain, and being transparent about knowledge sources.

---

### Intrinsic Motivation in AI

**Source:** Intrinsic motivation research (ScienceDirect, 2024) and Information-gain exploration (Frontiers in AI, 2024)

**What it is:** The study of how agents develop curiosity and self-directed exploration. Motivation arises from novelty detection, information gain, and connection potential.

**How myalicia uses it:** The `curiosity_engine.py` implements three novelty signals:
- **Novelty detection:** New topics/thinkers/concepts not yet in the vault
- **Information gain:** Topics with thin or conflicting coverage
- **Connection potential:** Unbridged clusters in the knowledge graph

These surface in proactive messages and weekly curiosity queues, transforming Alicia from purely reactive to proactively curious.

---

### Knowledge Graph Completion & Link Prediction

**Source:** Ontology learning from LLMs (arXiv, 2025) and Knowledge graph completion via link prediction

**What it is:** Techniques for inferring missing links in knowledge graphs and detecting structural gaps.

**How myalicia uses it:** The `graph_intelligence.py` skill builds a graph representation of the vault (notes as nodes, wikilinks as edges) and detects:
- Structural gaps (nodes with no incoming or outgoing links)
- Orphaned clusters (disconnected subgraphs)
- Bridge candidates (pairs of notes that should be linked but aren't)

This enables autonomous vault reorganization and suggests new connection points for synthesis notes.

---

### The Anthropic Claude API and Agent SDK

**Source:** [Anthropic](https://www.anthropic.com)

**What it is:** The language model and toolkit that makes all of this work. Claude's capabilities for tool-use, extended thinking, and long-context reasoning form the substrate.

**How myalicia uses it:** Every loop uses Claude:
- **Listen:** Claude Haiku for fast, cheap conversation
- **Notice:** Claude Sonnet for synthesis and analysis
- **Know:** Claude Opus for deep reasoning and meta-reflection

The tool-use API powers the function-calling dispatcher in `tool_router.py`. Extended thinking enables more deliberate reasoning in `/improve` and `/meta_reflexion`. Long context makes it possible to pass multi-thousand-token vault excerpts to synthesis functions.

---

## Implementation Details & Techniques

### LangChain Trajectory Evaluation

**Source:** LangChain framework, trajectory analysis patterns

**What it is:** Methods for logging and analyzing the decision trees and tool calls made by agents—who was called, in what order, with what results.

**How myalicia uses it:** The `trajectory.py` skill records complete task trajectories: tool calls, context retrieved, timing, and outcome. Weekly analysis extracts patterns and updates procedural memory. This is the raw signal that drives reflexion and improvement.

---

## How This Map Should Grow

This list is honest about what's explicitly cited in the code and foundational to the architecture. If you:

- Build a new skill inspired by a paper, add a docstring citing it
- Discover a concept that shapes a module's behavior, consider a footnote in the code
- Use a framework not listed here, include it in the module's header

The goal is not comprehensive citation (that would be impossible) but **transparent lineage**. When someone reads the code or this FAQ, they should understand what shoulders myalicia is standing on.

---

## Further Reading

- [Humorphism](https://humorphism.com) — the design philosophy
- [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md) — full credits to the people
- [PHILOSOPHY.md](../docs/PHILOSOPHY.md) — the three-loop architecture in depth
- [ARCHITECTURE.md](../docs/ARCHITECTURE.md) — how the system fits together
- Individual skill modules — each has docstrings with specific citations
