"""
surfaces.cli — terminal-based surface.

PLANNED: a thin adapter that lets you talk to My Alicia from the
command line, without needing Telegram or any other channel set up.
Useful for testing skills, debugging, and quick interactions.

Currently a stub. The full implementation will:

  - Read a single message from stdin or argv
  - Pass it through handle_message() with surface='cli'
  - Print the response to stdout
  - Optionally support REPL mode for interactive sessions

Usage (planned):

    myalicia run --surface cli
    > hi who are you
    < I'm your AI teammate. We've been working on...

Status: not yet implemented. The myalicia CLI (`myalicia run`) currently
delegates to the legacy alicia.py runtime which only supports Telegram.
"""
