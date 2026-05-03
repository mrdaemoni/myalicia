"""
myalicia.surfaces — pluggable input/output channels.

Each surface is a small adapter that wraps the same handle_message
pipeline (in myalicia.core.handle_message — currently myalicia.alicia)
with whatever protocol that surface speaks.

Shipped surfaces:
    surfaces.cli       — terminal-based, used for testing and ops
    surfaces.telegram  — primary conversational surface

Planned community surfaces:
    surfaces.claude_code   — when running inside Claude Code (technical context)
    surfaces.discord       — Discord bot
    surfaces.imessage      — Apple Messages on macOS
    surfaces.voice         — voice-first surface (web-based or hardware)

To add a new surface:

    1. Create myalicia/surfaces/your_surface.py
    2. Implement: register(application) -> None  (wires up the runtime)
    3. Implement: send(chat_id, text) -> None    (sends a message out)
    4. Read your config from myalicia.config.config.surfaces.<your_surface>
    5. Add a section to myalicia/defaults.yaml
    6. Document deployment in examples/deployments/

Surfaces should be thin. The skill / pipeline logic stays in core/ and
skills/ — surfaces only translate between the agent and the channel.
"""

__all__: list[str] = []
