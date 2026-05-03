"""
myalicia.skills — composable skill modules.

Each skill is a small, opinionated module that does one thing well.
Skills are the contribution surface of the project: people add a skill
without needing to understand the whole system.

The core (in myalicia.core) handles orchestration, routing, and the three
relationship loops. Skills are what those loops call.

Skills are migrated here one file at a time as they pass sanitization.
The legacy unsanitized versions live outside the package in /skills/
and are gitignored until each one is cleared.
"""
