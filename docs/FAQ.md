# FAQ — Setup, Technical, and Practical Questions

Everything you might want to know before, during, or after setting up myalicia. If your question isn't answered here, [open an issue](https://github.com/mrdaemoni/myalicia/issues) or [start a discussion](https://github.com/mrdaemoni/myalicia/discussions).

---

## Getting started

### What exactly is myalicia?

An open-source pattern for building an AI teammate that grows into the shape of one specific person. Not a chatbot anyone can use — a relationship one person deepens over time. The architecture is three loops (Listen / Notice / Know) over a shared memory substrate (typically an Obsidian vault). See [PHILOSOPHY.md](./PHILOSOPHY.md) for the framing and [ARCHITECTURE.md](./ARCHITECTURE.md) for how it's built.

### What's the fastest way to try it?

```bash
git clone https://github.com/mrdaemoni/myalicia.git
cd myalicia
pip install -e .
myalicia init
```

The `init` flow takes about 5 minutes and walks you through configuration while explaining the three loops. After init, see "Connecting Telegram" below.

### Why isn't `pip install myalicia` working?

myalicia v0.1.0 is not yet on PyPI. The package skeleton, all 80 skill modules, the configuration layer, and the docs are public, but the legacy 7,951-line `alicia.py` runtime is still being split into the proper `core/` modules per [REFACTORING.md](../REFACTORING.md). Until v0.2 lands the runtime split, source-install is the supported path. Once we're on PyPI, `pip install myalicia` will be the one-liner.

### How long does setup take?

About 15 minutes the first time, mostly making decisions (which archetype, which surface, which folders). Subsequent setups on additional machines take about 2 minutes because your config follows you in `~/.alicia/config.yaml`.

---

## Minimum requirements

### What do I need on my machine?

- **Python 3.10 or newer** (3.12 recommended)
- **Disk**: ~50 MB for the package + dependencies, plus whatever your vault grows to (yours, not ours)
- **RAM**: 1–2 GB headroom while running. Voice features and vector search push that higher.
- **Network**: Anthropic API access. Telegram if you use that surface.

That's it. No GPU. No Docker required. No external database.

### Do I need an Obsidian vault to use myalicia?

Recommended but not required. myalicia treats the vault as a folder of markdown files — Obsidian just happens to use the same shape, and Obsidian's graph view is a nice way to see what's accumulating. If you don't want to install Obsidian:

- Make any folder of `.md` files (`mkdir ~/my-vault`)
- Point `config.vault.root` at it in `~/.alicia/config.yaml`
- myalicia will create `Alicia/Bridge/`, `Alicia/Wisdom/`, `Alicia/Self/` inside it on first run

Later, if you decide to install Obsidian, point Obsidian at the same folder and you get the graph view for free.

### Does it work on Windows / Linux / Mac?

Yes to all three.

- **macOS**: native Python install or Homebrew. Use the launchd example in `examples/deployments/launchd/`.
- **Linux**: native Python. Use the systemd example in `examples/deployments/systemd/`.
- **Windows**: Python from python.org. The Telegram surface, CLI, and skills all work; you'd write a small `myalicia.bat` launcher rather than using launchd/systemd.

For platform-agnostic deploys, use the Docker setup in `examples/deployments/docker/`.

---

## Open source / freedom / modification

### Is this really open source?

Yes. MIT licensed. You can fork it, modify it, sell products built on it, contribute back, or never speak to us again. See [LICENSE](../LICENSE).

### Can I use myalicia commercially?

Yes. MIT permits commercial use without restriction. You don't need to ask for permission, share modifications, or pay anyone.

### Can I run it offline?

Partially. The skill modules and core run locally — your vault stays on your machine, your memory files stay on your machine, the orchestration runs locally. **However**, the language model calls go to Anthropic's API, which requires internet. If you swap in a local model (Ollama, llama.cpp, etc.) by replacing the model client, the whole system can run offline. That swap isn't shipped today but is a community-friendly contribution path.

### Is my data sent anywhere?

Your **conversations and the relevant context Alicia builds for them** are sent to Anthropic's API for inference (this is how Claude works). Your **vault, memory files, and configuration stay local on your machine** unless you explicitly add a skill that uploads them somewhere. We never collect telemetry. There is no analytics endpoint. The project doesn't have a server you talk to — your install is your install.

### Can I run it on someone else's behalf?

Technically yes — you could run a myalicia instance for a parent, partner, or friend. But the design assumes one user per instance. Multi-user support is not on the roadmap because it cuts against the central thesis (an AI shaped to one person, deeply).

---

## Telegram bot setup

### How do I create a Telegram bot?

1. Open Telegram, search for `@BotFather`, start a conversation.
2. Send `/newbot`. BotFather asks for a name (display name) and a username (must end in `bot`).
3. BotFather replies with a token like `123456789:AAH...`. **Copy this** — you only see it once.
4. Set the token in your environment: `export TELEGRAM_BOT_TOKEN='123456789:AAH...'`
5. Find your new bot in Telegram and send it any message (this registers your chat).

### How do I find my chat ID?

After step 5 above, run this in Python:

```python
import requests
TOKEN = "your-token-here"
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates").json()
print(r['result'][-1]['message']['chat']['id'])
```

Add the resulting integer to `~/.alicia/config.yaml` under `surfaces.telegram.allowed_chat_ids: [your_id_here]`. This locks the bot to only respond to you.

### Can I use multiple chats?

Yes — `allowed_chat_ids` is a list. You could have a personal chat and a "work" chat that go to the same myalicia instance. Most people don't need this.

### Why Telegram and not WhatsApp / iMessage / Signal?

Telegram has a free, stable bot API that any developer can use without app-store review or paid tiers. The other platforms either don't have public bot APIs (iMessage outside macOS), require business approval (WhatsApp), or aren't designed for it (Signal). The pattern is the same regardless — see `myalicia/surfaces/` for adapters and `CONTRIBUTING.md` for how to write one for your platform.

---

## API keys and cost

### Where do I get an Anthropic API key?

Sign up at [console.anthropic.com](https://console.anthropic.com). New accounts get free credits. After verification you can add a payment method and create an API key. Set it as `ANTHROPIC_API_KEY` in your environment.

### How much does it cost to run?

Cheap by default. The three loops use different model tiers:

- **Listen** (real-time conversation): Haiku — about $0.80 per million input tokens. A typical conversation is a few hundred tokens. **Pennies per day** for normal use.
- **Notice** (event-triggered synthesis): Sonnet — about $3 per million input tokens. Runs a few times a day. **A few dollars per month**.
- **Know** (autonomous deep reflection): Opus — about $15 per million input tokens. Runs once a day or once a week. **Maybe $5–10 per month** if you let it run on a full vault every weekend.

Realistic monthly cost for a steady user with a moderate-sized vault: **$10–20 per month**. You can dial down by switching loops to cheaper models in `config.yaml`, or disabling the Notice/Know loops entirely.

### Can I limit my spending?

Yes, in three ways:

1. **Anthropic console**: set a hard monthly spend cap on the API key
2. **Disable loops**: in `~/.alicia/config.yaml`, set `loops.notice_enabled: false` and `loops.know_enabled: false` to keep only the cheap Listen loop
3. **Downgrade models**: in `~/.alicia/config.yaml`, set `models.know: claude-sonnet-4-6` (or even Haiku) instead of Opus

### Are there free model alternatives?

Yes if you swap in a local model. The codebase is designed around the Anthropic SDK, but the model client is wrapped — you can write a small adapter for Ollama, LM Studio, llama.cpp, vLLM, etc. The skill logic doesn't care which model serves it. Community contributions for these adapters are welcome.

---

## Vault setup

### What's the right vault structure?

See [examples/vault_layouts/obsidian-default.md](../examples/vault_layouts/obsidian-default.md). The defaults assume:

```
{vault.root}/
├── Books/          # your book notes
├── People/         # notes about people
├── Daily/          # daily logs
├── Captures/       # quick ideas
└── Alicia/
    ├── Bridge/     # her queue to surface things to you
    ├── Wisdom/     # her synthesis output
    └── Self/       # her archetype + profile data
```

You don't need to create the `Alicia/` subfolders — myalicia creates them on first run.

### Can I customize the layout?

Yes. Override in `~/.alicia/config.yaml`:

```yaml
vault:
  root: ~/Documents/my-vault
  inner: AI                # subfolder for myalicia's notes
  bridge: Inbox            # rename the surfacing folder
  wisdom: Synthesis        # rename the synthesis folder
  self_dir: Profile        # rename the archetype folder
```

The skill modules read these via `config.vault.*_path` properties — no hardcoded folder names anywhere.

### What if my vault has tens of thousands of notes?

myalicia handles vaults at that scale, but the first indexing pass (semantic search) can take a few minutes. After that, incremental updates are fast. The `EXCLUDED_FOLDERS` config lets you skip subdirectories that aren't relevant (templates, attachments, archives).

### Do I have to use markdown?

The skills are written for markdown. You can extend them to other formats (org-mode, reStructuredText, plain text) but that's a meaningful piece of work — the parsing assumes markdown headings, links, and frontmatter.

---

## Customization

### How do I change Alicia's voice / personality?

Edit your archetype. Default is `curious-builder` (`examples/archetypes/curious-builder.yaml`). You can:

1. **Use a shipped archetype**: change `archetype.name` in `~/.alicia/config.yaml` to `patient-mentor`, `ariadne`, etc.
2. **Author your own**: copy one of the YAML files, edit the voice/character/openers, save it as `~/.alicia/archetypes/my-archetype.yaml`, point `archetype.path` at it.

### Can I add my own skills?

Yes — that's the contribution surface. See [CONTRIBUTING.md](../CONTRIBUTING.md) for writing an "awareness primitive". The pattern: small Python module under `myalicia/skills/`, reads from the substrate, writes back, plugs into one of the three loops.

### Can I add a new surface (Discord, Slack, voice device)?

Yes. See `myalicia/surfaces/__init__.py` for the planned structure and existing surface stubs. Each surface is roughly 200 lines of integration code wrapping the same `handle_message` pipeline.

---

## Troubleshooting

### `myalicia init` says "PyYAML is required"

Run: `pip install pyyaml`. It's a dependency, but if you installed via `pip install -e .` from a sparse checkout it might have been skipped.

### "ANTHROPIC_API_KEY not set"

Set it in your shell: `export ANTHROPIC_API_KEY='sk-ant-...'`. Add this line to your `~/.zshrc` or `~/.bashrc` so it persists across sessions. Or use a `.env` file in your project root and `python-dotenv` will pick it up.

### Telegram bot doesn't respond

Check three things:

1. `TELEGRAM_BOT_TOKEN` is set in the same shell where you ran `myalicia run`
2. Your chat ID is in `~/.alicia/config.yaml` under `surfaces.telegram.allowed_chat_ids`
3. The bot is running — check `myalicia status`

### Tests don't run on my machine

The legacy tests are designed for the original codebase's environment. Many require API keys, vault state, or the full runtime to be wired up. The CI workflow (`.github/workflows/ci.yml`) only runs syntax checks, which is what's reliably testable today. For the v0.2 split, we'll factor tests to be fully isolated.

### Something else broke

Open an issue at [github.com/mrdaemoni/myalicia/issues](https://github.com/mrdaemoni/myalicia/issues) with the error message, your OS, your Python version, and what you ran.

---

## Where to find more

### How can I see what's planned?

- [REFACTORING.md](../REFACTORING.md) for the alicia.py → core/ split
- [CHANGELOG.md](../CHANGELOG.md) for what's shipped
- [GitHub Issues](https://github.com/mrdaemoni/myalicia/issues) for active work

### Where's the philosophy?

- [PHILOSOPHY.md](./PHILOSOPHY.md) — the humorphism framing in repo
- [myalicia.com/philosophy](https://www.myalicia.com/philosophy) — same content + the personal narrative
- [humorphism.com](https://humorphism.com) — the design philosophy this project embodies

### Where's the academic lineage?

- [PAPERS.md](./PAPERS.md) — the papers, frameworks, and researchers that shaped Alicia, with explicit "how myalicia uses it" notes for each

### How do I contribute?

- [CONTRIBUTING.md](../CONTRIBUTING.md) — the contribution guide
- [Issue templates](https://github.com/mrdaemoni/myalicia/issues/new/choose) — bug report, feature request, or awareness-primitive proposal
- [GitHub Discussions](https://github.com/mrdaemoni/myalicia/discussions) — questions, ideas, show-and-tell

### What if I just want to read more about the loops / altitudes / self-traits?

- [myalicia.com](https://www.myalicia.com) — the visual story with all four diagrams
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md) — the same content, in repo

---

If you got this far, you've absorbed the surface area. From here it's mostly install + iterate.
