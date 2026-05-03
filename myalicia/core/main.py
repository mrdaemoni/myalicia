"""
core.main — bot setup, command registration, and main entry point.

PLANNED CONTENT (currently lives at the bottom of myalicia/alicia.py:7950+):

Functions:

  build_application() -> telegram.ext.Application
      Construct the Telegram bot application, register message
      handlers, command handlers, reaction handlers, and error
      handlers.

  register_scheduler() -> None
      Wire up all scheduled tasks via core.scheduler.

  main() -> None
      The runtime entry point. Sets up logging, builds the
      application, registers commands, starts the scheduler thread,
      and runs the bot's polling loop.

This is the LAST piece to extract — it depends on everything else.
Once all the previous core/ modules are populated, main.py becomes
the wiring layer that ties them together.

After this extraction, alicia.py becomes a single line:
    from myalicia.core.main import main
    main()

Or it can be deleted entirely, and pyproject.toml's [project.scripts]
points directly at myalicia.core.main:main.

Status: not yet extracted.
"""
