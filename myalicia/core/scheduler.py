"""
core.scheduler — scheduled tasks for the Notice and Know loops.

PLANNED CONTENT (currently lives in myalicia/alicia.py near the bottom):

The scheduled tasks are how Notice and Know loops run autonomously:

  Time       Task                  Loop      Source skill
  -----      ----                  ----      ------------
  05:30      curiosity scan        Notice    curiosity_engine
  06:00      daily vault pass      Notice    vault_intelligence
  06:05      morning message       Notice    proactive_messages
  12:30      midday nudge          Notice    proactive_messages
  21:00      evening reflection    Notice    proactive_messages
  Sun 20:00  weekly deep pass      Know      vault_intelligence + others

Each task is wrapped in safe_run() which alerts via Telegram on failure.

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py — the schedule.* registration calls
  - Define each scheduled function as a small wrapper that imports its
    underlying skill at call time (avoids circular imports)
  - register_all(scheduler) function that the main entry point calls

Status: not yet extracted.
"""
