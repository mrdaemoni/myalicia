"""
Configuration loader for Alicia.

Resolves config from three sources, in priority order:

    1. Environment variables (ALICIA_*)
    2. User config file at ~/.alicia/config.yaml (created by `alicia init`)
    3. Shipped defaults at alicia/defaults.yaml

Every personalization knob in the codebase resolves through this loader. No
module should hardcode a path, identifier, or vault layout assumption — that
was the original sin of the private codebase, and the open-source version
makes it structurally impossible.

Usage:

    from alicia.config import config

    vault_root = config.vault.root
    user_name = config.user.name
    if config.surfaces.telegram.enabled:
        ...

The config object is read-only at runtime. To change values, edit
~/.alicia/config.yaml and restart the process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as e:
    raise ImportError(
        "alicia requires PyYAML. Install with: pip install pyyaml"
    ) from e


# -- Paths -------------------------------------------------------------------

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULTS_PATH = PACKAGE_ROOT / "defaults.yaml"
USER_CONFIG_DIR = Path(os.environ.get("ALICIA_HOME", str(Path.home() / ".alicia")))
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"


# -- Typed config sections ---------------------------------------------------

@dataclass(frozen=True)
class UserConfig:
    """Identity of the human Alicia is in relationship with."""
    name: str = "friend"
    handle: str = "user"
    timezone: str = "UTC"


@dataclass(frozen=True)
class VaultConfig:
    """Filesystem layout of the user's knowledge vault (typically Obsidian)."""
    root: Path = Path.home() / "alicia-vault"
    inner: str = "Alicia"          # subfolder where Alicia writes her own notes
    bridge: str = "Bridge"         # surfacing queue / inbox between user and Alicia
    wisdom: str = "Wisdom"         # synthesis output
    self_dir: str = "Self"         # archetype + profile data

    @property
    def inner_path(self) -> Path:
        return self.root / self.inner

    @property
    def bridge_path(self) -> Path:
        return self.root / self.inner / self.bridge

    @property
    def wisdom_path(self) -> Path:
        return self.root / self.inner / self.wisdom

    @property
    def self_path(self) -> Path:
        return self.root / self.inner / self.self_dir


@dataclass(frozen=True)
class ArchetypeConfig:
    """Which personality Alicia wears in this instance."""
    name: str = "curious-builder"
    path: Path | None = None  # custom archetype file; None = use shipped example


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_chat_ids: tuple[int, ...] = ()
    emoji_reactions: bool = True


@dataclass(frozen=True)
class ClaudeCodeConfig:
    enabled: bool = False


@dataclass(frozen=True)
class CLIConfig:
    enabled: bool = True


@dataclass(frozen=True)
class SurfacesConfig:
    """Channels through which Alicia can be reached."""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)
    cli: CLIConfig = field(default_factory=CLIConfig)


@dataclass(frozen=True)
class ModelsConfig:
    """Which Anthropic models drive each loop. Cheap by default, expensive by choice."""
    listen: str = "claude-haiku-4-5-20251001"   # inner / conversation
    notice: str = "claude-sonnet-4-6"           # medium / synthesis
    know: str = "claude-opus-4-6"               # outer / autonomous reflection
    api_key_env: str = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool = False
    tts_engine: str = "edge-tts"
    voice_id: str = "en-US-JennyNeural"


@dataclass(frozen=True)
class PodcastConfig:
    """Weekly podcast generation from the vault — Notice loop in audio form."""
    enabled: bool = False
    schedule_cron: str = "0 9 * * 0"  # Sunday 9 AM
    target_minutes: int = 10


@dataclass(frozen=True)
class LoopsConfig:
    """Cadences for the three relationship loops."""
    listen_enabled: bool = True
    notice_enabled: bool = True
    know_enabled: bool = True
    morning_message_time: str = "06:30"
    midday_message_time: str = "12:30"
    evening_reflection_time: str = "21:00"
    weekly_synthesis_day: str = "Sunday"
    weekly_synthesis_time: str = "20:00"


@dataclass(frozen=True)
class Config:
    """Top-level configuration. Constructed once at import, read-only thereafter."""
    user: UserConfig = field(default_factory=UserConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    archetype: ArchetypeConfig = field(default_factory=ArchetypeConfig)
    surfaces: SurfacesConfig = field(default_factory=SurfacesConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    podcast: PodcastConfig = field(default_factory=PodcastConfig)
    loops: LoopsConfig = field(default_factory=LoopsConfig)

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get(self.models.api_key_env)


# -- Loader ------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override values win."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """ALICIA_<SECTION>_<KEY> env vars override config values."""
    result = dict(data)
    env_prefix = "ALICIA_"
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(env_prefix):
            continue
        path = env_key[len(env_prefix):].lower().split("_", 1)
        if len(path) == 2:
            section, key = path
            result.setdefault(section, {})[key] = env_val
    return result


def _build_config(data: dict[str, Any]) -> Config:
    """Construct typed Config from a merged dict. Unknown keys are ignored."""
    user = UserConfig(**data.get("user", {}))

    vault_data = data.get("vault", {})
    if "root" in vault_data:
        vault_data["root"] = Path(vault_data["root"]).expanduser()
    vault = VaultConfig(**vault_data)

    archetype_data = data.get("archetype", {})
    if archetype_data.get("path"):
        archetype_data["path"] = Path(archetype_data["path"]).expanduser()
    archetype = ArchetypeConfig(**archetype_data)

    surfaces_data = data.get("surfaces", {})
    surfaces = SurfacesConfig(
        telegram=TelegramConfig(**surfaces_data.get("telegram", {})),
        claude_code=ClaudeCodeConfig(**surfaces_data.get("claude_code", {})),
        cli=CLIConfig(**surfaces_data.get("cli", {})),
    )

    models = ModelsConfig(**data.get("models", {}))
    voice = VoiceConfig(**data.get("voice", {}))
    podcast = PodcastConfig(**data.get("podcast", {}))
    loops = LoopsConfig(**data.get("loops", {}))

    return Config(
        user=user,
        vault=vault,
        archetype=archetype,
        surfaces=surfaces,
        models=models,
        voice=voice,
        podcast=podcast,
        loops=loops,
    )


def load_config() -> Config:
    """Load config from defaults + user file + env, in that order of priority."""
    defaults = _load_yaml(DEFAULTS_PATH)
    user = _load_yaml(USER_CONFIG_PATH)
    merged = _deep_merge(defaults, user)
    merged = _apply_env_overrides(merged)
    return _build_config(merged)


# Eagerly load at import. Importing alicia.config gives you a ready Config.
config: Config = load_config()
