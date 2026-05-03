"""
core.telegram_commands — all the /cmd_* Telegram handlers.

PLANNED CONTENT (currently lives in myalicia/alicia.py:2393-~3500):

Roughly 40 cmd_* functions, each a thin wrapper that takes a Telegram
update + context and delegates to a skill. Examples:

  cmd_start            — /start, the bot intro
  cmd_status           — /status, current state
  cmd_skills           — /skills, list available skills
  cmd_semanticsearch   — /search, run a semantic vault search
  cmd_dailypass        — /daily, run the daily synthesis manually
  cmd_weeklypass       — /weekly, run the weekly synthesis
  cmd_improve          — /improve, run the self-improve cycle
  cmd_vaultstats       — /stats, vault metrics
  cmd_podcast          — /podcast, generate the weekly audio
  cmd_memory           — /memory, dump memory state
  cmd_remember         — /remember, persist a fact
  cmd_concept          — /concept, look up a concept
  cmd_synthesise       — /synthesise, kick off synthesis
  cmd_contradictions   — /contradictions, run contradiction detector
  cmd_research         — /research, web research
  cmd_deepresearch     — /deepresearch, longer expedition
  cmd_inbox            — /inbox, gmail summary
  cmd_financial        — /financial, financial-only inbox view
  cmd_sendmail         — /sendmail, draft + confirm + send
  cmd_dailyquote       — /quote, today's quote
  cmd_call             — /call, start voice call mode
  cmd_endcall          — /endcall, exit voice call mode
  ... (and more)

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py:2393-3500ish
  - Group all cmd_* into this module
  - register_all(application) function that adds them to the bot
  - Each cmd_* should be a thin wrapper — heavy logic stays in skills

Status: not yet extracted.
"""
