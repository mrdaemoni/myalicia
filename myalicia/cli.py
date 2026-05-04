"""
myalicia CLI — the entry point installed when you run `pip install -e .`
(or `pip install myalicia` once we're on PyPI in v0.2).

Subcommands:
    init    — guided setup that teaches the three loops as it configures them
    run     — start the agent (Telegram + Listen/Notice/Know loops)
    status  — show current config and connectivity
    version — print the installed version

The `init` flow is the single most important UX in this project. It's not
just configuration; it's a guided introduction to relationship-shaped AI.
Each setup step is paired with a one-screen explanation of which loop it
activates and why.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from myalicia import __version__


# ── init ──────────────────────────────────────────────────────────────────

INIT_INTRO = """
Welcome to myalicia. We're going to set up an AI teammate that grows to
know you. Three depths of attention shape this:

  Listen — the conversation in front of you, happening now
  Notice — the patterns she catches across your week
  Know   — the long-arc understanding that compounds month over month

Each setup step below activates one of these. We'll say which.
"""


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix} > ").strip()
    return answer or (default or "")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    answer = input(f"{prompt}{suffix} > ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "1", "true")


def cmd_init(args: argparse.Namespace) -> int:
    """Walk a new user through configuring their myalicia instance."""
    try:
        import yaml  # imported lazily for nicer error if missing
    except ImportError:
        print("ERROR: PyYAML is required. Install with: pip install pyyaml")
        return 1

    print(INIT_INTRO)

    name = _ask("What should I call you?", default="friend")
    print("  [Activates Listen — she'll use your name in conversation]\n")

    vault_default = str(Path.home() / "alicia-vault")
    vault = _ask("Where should I keep your vault?", default=vault_default)
    vault_path = Path(vault).expanduser()
    print("  [Activates Notice + Know — the vault is the substrate the deeper loops read from]\n")

    print("Pick a starting archetype:")
    print("  1. curious-builder — for engineers and tinkerers")
    print("  2. patient-mentor — for teachers and writers")
    print("  3. ariadne (mythological) — for those who guide through complexity")
    archetype_map = {"1": "curious-builder", "2": "patient-mentor", "3": "ariadne"}
    choice = _ask("Your choice", default="1")
    archetype = archetype_map.get(choice, "curious-builder")
    print(f"  [Selected: {archetype} — shapes her voice across all three loops]\n")

    enable_telegram = _ask_yes_no("Connect Telegram surface?", default=True)
    print("  [Telegram is the conversational reach — Listen loop's primary channel]\n")

    enable_voice = _ask_yes_no("Enable voice mode (TTS for morning messages)?", default=False)
    if enable_voice:
        print("  [Voice gives Listen a body — your morning briefing arrives spoken]\n")

    enable_loops = _ask_yes_no("Enable scheduled tasks (morning, midday, evening, weekly)?", default=True)
    if enable_loops:
        print("  [These are the heartbeats of Notice and Know]\n")

    # Write config
    config_dir = Path.home() / ".alicia"
    config_dir.mkdir(parents=True, exist_ok=True)
    vault_path.mkdir(parents=True, exist_ok=True)
    (vault_path / "Alicia").mkdir(exist_ok=True)
    (vault_path / "Alicia" / "Bridge").mkdir(exist_ok=True)
    (vault_path / "Alicia" / "Wisdom").mkdir(exist_ok=True)
    (vault_path / "Alicia" / "Self").mkdir(exist_ok=True)

    config_data: dict = {
        "user": {"name": name, "handle": name.lower().replace(" ", ""), "timezone": "UTC"},
        "vault": {"root": str(vault_path)},
        "archetype": {"name": archetype},
        "surfaces": {
            "telegram": {"enabled": enable_telegram},
            "cli": {"enabled": True},
        },
        "voice": {"enabled": enable_voice},
        "loops": {
            "listen_enabled": True,
            "notice_enabled": enable_loops,
            "know_enabled": enable_loops,
        },
    }

    config_path = config_dir / "config.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

    print()
    print(f"Setup complete.")
    print(f"  Config:    {config_path}")
    print(f"  Vault:     {vault_path}")
    print()
    print("Set your API keys in environment variables:")
    print("  export ANTHROPIC_API_KEY='sk-ant-...'")
    if enable_telegram:
        print("  export TELEGRAM_BOT_TOKEN='...'  (from @BotFather)")
    print()
    print("Then run: myalicia run")
    print()
    print("First message suggestion: \"Hi, who are you?\"")
    return 0


# ── run ───────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    """Start the agent — boots Telegram polling + the three relationship loops."""
    from myalicia.config import config

    # Pre-flight checks
    import os
    if not os.environ.get(config.models.api_key_env):
        print(f"ERROR: {config.models.api_key_env} not set in the environment.")
        print(f"Get a key at https://console.anthropic.com and:")
        print(f"  export {config.models.api_key_env}='sk-ant-...'")
        return 1

    if config.surfaces.telegram.enabled and not os.environ.get(
        config.surfaces.telegram.bot_token_env
    ):
        print(f"ERROR: Telegram is enabled but {config.surfaces.telegram.bot_token_env} not set.")
        print(f"Get a token from @BotFather and:")
        print(f"  export {config.surfaces.telegram.bot_token_env}='...'")
        return 1

    print(f"Starting myalicia for {config.user.name}...")
    print(f"  Vault:     {config.vault.root}")
    print(f"  Archetype: {config.archetype.name}")
    print(f"  Listen:    {config.models.listen}")
    print(f"  Notice:    {config.models.notice}")
    print(f"  Know:      {config.models.know}")
    print()

    # Boot the runtime. As of v0.1.x the entry point is still the legacy
    # alicia.py main(); as core/ extraction completes (see REFACTORING.md)
    # this will move to myalicia.core.main.
    try:
        from myalicia.alicia import main as legacy_main
    except ImportError as e:
        print(f"ERROR: failed to import the runtime: {e}")
        print()
        print("If you see a 'No module named X' error, install the matching extra:")
        print("  pip install -e '.[all]'")
        return 1

    legacy_main()
    return 0


# ── status ────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> int:
    """Show config and connectivity."""
    from myalicia.config import config
    print(f"myalicia v{__version__}")
    print()
    print("USER")
    print(f"  name:     {config.user.name}")
    print(f"  handle:   {config.user.handle}")
    print(f"  timezone: {config.user.timezone}")
    print()
    print("VAULT")
    print(f"  root:   {config.vault.root}")
    print(f"  exists: {Path(config.vault.root).exists()}")
    print()
    print("ARCHETYPE")
    print(f"  {config.archetype.name}")
    print()
    print("LOOPS (cadence · model)")
    print(f"  Listen — seconds       · {config.models.listen}")
    print(f"  Notice — minutes/hours · {config.models.notice}")
    print(f"  Know   — days/weeks    · {config.models.know}")
    print()
    print("SURFACES")
    print(f"  CLI:        {'on' if config.surfaces.cli.enabled else 'off'}")
    print(f"  Telegram:   {'on' if config.surfaces.telegram.enabled else 'off'}")
    print(f"  ClaudeCode: {'on' if config.surfaces.claude_code.enabled else 'off'}")
    return 0


# ── version ───────────────────────────────────────────────────────────────

def cmd_version(args: argparse.Namespace) -> int:
    print(f"myalicia {__version__}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myalicia",
        description="An AI teammate that grows into the shape of the person it serves.",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_init = sub.add_parser("init", help="guided setup that teaches the three loops")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="start the agent")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="show current config")
    p_status.set_defaults(func=cmd_status)

    p_version = sub.add_parser("version", help="print version")
    p_version.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
