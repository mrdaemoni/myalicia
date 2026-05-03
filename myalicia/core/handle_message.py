"""
core.handle_message — the 10-step message pipeline.

PLANNED CONTENT (currently lives in myalicia/alicia.py around line 843):

The handle_message function is the heart of the Listen loop. Every
incoming message — text, voice, command — flows through these ten steps:

  1. Security gate           — classify_security_level() → L1-L4
  2. Retrieval               — vault context + reflections + curiosity
  3. Metacognition           — assess_confidence + Sonnet→Opus escalation
  4. Tool routing            — function-calling dispatch via tool_router
  5. Tool execution          — execute_tool loop with email confirmation
  6. Response formatting     — credential redaction, vault sources
  7. Memory extraction       — extract_from_message [background thread]
  8. Reflexion               — should_reflect → reflect_on_task [bg]
  9. Constitutional eval     — should_evaluate → evaluate_output [bg]
  10. Trajectory + curiosity — trajectory.save + detect_novelty [bg]

EXTRACTION RECIPE:

  - Source: myalicia/alicia.py:843-1922 (handle_message function + helpers)
  - Add explicit imports for: anthropic.Anthropic, telegram.Update, ...
  - Keep _append_history near handle_message (line 826)
  - Helpers chat_guard, detect_email_intent stay close

Status: not yet extracted.
"""
