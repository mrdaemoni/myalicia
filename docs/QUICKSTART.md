# Quickstart

Get from zero to a running myalicia in about 15 minutes.

## Install

`myalicia` is not yet on PyPI for v0.1.0. Install from source:

```bash
git clone https://github.com/mrdaemoni/myalicia.git
cd myalicia
pip install -e .
```

For optional integrations (voice, Gmail, vector search, PDF):

```bash
pip install -e '.[voice,gmail,search,pdf]'
# or everything at once:
pip install -e '.[all]'
```

Once v0.2 lands, `pip install myalicia` will work directly.

## Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com), create an API key, then:

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
```

(Add this to your shell profile so it persists across terminal sessions.)

## Run init

```bash
myalicia init
```

The init flow walks you through:

1. **Your name** — activates Listen (she'll use your name in conversation)
2. **Your vault location** — activates Notice + Know (the substrate the deeper loops read from)
3. **An archetype** — picks the voice she'll wear (curious-builder, patient-mentor, ariadne)
4. **Surfaces** — Telegram (recommended), CLI, etc.
5. **Voice mode** — optional TTS for morning messages
6. **Scheduled tasks** — the heartbeats of Notice and Know

By the time init finishes, your vault scaffold is created (`Alicia/Bridge/`, `Alicia/Wisdom/`, `Alicia/Self/`), your config lives at `~/.alicia/config.yaml`, and you're ready to run.

## Connect Telegram (recommended)

If you said yes to Telegram in init:

1. Open [@BotFather](https://t.me/botfather) in Telegram and send `/newbot`
2. Pick a name and a username
3. BotFather gives you a token. Set it:
   ```bash
   export TELEGRAM_BOT_TOKEN='...'
   ```
4. Find your bot in Telegram and send it any message — that handshake registers your chat ID.

## Run her

```bash
myalicia run
```

She'll greet you. Try:

- "Hi, who are you?" — gets a Listen-loop response
- "What did I do yesterday?" — pulls from your vault
- Wait until tomorrow morning — Know-loop produces a morning briefing

## Verify

```bash
myalicia status
```

You should see your config: name, vault, archetype, model assignments per loop, which surfaces are on.

## Next steps

- Read [PHILOSOPHY.md](./PHILOSOPHY.md) to understand the framework
- Read [ARCHITECTURE.md](./ARCHITECTURE.md) to understand the code
- Read [../CONTRIBUTING.md](../CONTRIBUTING.md) to write your first awareness primitive
- Visit [myalicia.com](https://myalicia.com) for the visual story

## Troubleshooting

**"command not found: myalicia"** — pip might have installed to a directory not on your PATH. Try `python -m myalicia.cli init` instead.

**"PyYAML is required"** — `pip install pyyaml`.

**No response when you message the bot** — confirm `TELEGRAM_BOT_TOKEN` is set in the same shell where you run `myalicia run`. Confirm your chat ID is in `~/.alicia/config.yaml` under `surfaces.telegram.allowed_chat_ids`.

**"ANTHROPIC_API_KEY not set"** — see step 1 above.
