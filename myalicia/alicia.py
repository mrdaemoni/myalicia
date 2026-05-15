#!/usr/bin/env python3
"""
Alicia — Personal Sovereign AI Agent
Clean complete version with semantic search + Sonnet/Opus
"""

import os
import json
import logging
import asyncio
import random
import schedule
import threading
import time
import re
import functools
from datetime import datetime
from urllib.parse import quote
from dotenv import load_dotenv
import anthropic
from telegram import Update, BotCommand, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, MessageReactionHandler, CallbackQueryHandler, filters, ContextTypes

from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv(str(ENV_FILE))

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID"))
OBSIDIAN_VAULT     = str(config.vault.inner_path)
VAULT_ROOT         = str(config.vault.root)
LOG_FILE           = str(LOGS_DIR / "interactions.jsonl")

MODEL_SONNET = "claude-sonnet-4-20250514"
MODEL_OPUS   = "claude-opus-4-20250514"

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=5)

# ── Skill imports ─────────────────────────────────────────────────────────────

from myalicia.skills.gmail_skill      import get_inbox_summary, summarise_financial_emails, send_email
from myalicia.skills.quote_skill      import get_random_quote
from myalicia.skills.research_skill   import research_quick, research_brief, research_deep
from myalicia.skills.memory_skill     import (
    build_session_context, extract_from_message,
    get_memory_summary, remember_manual, forget_manual,
    generate_concept_note, synthesise_vault,
    find_contradictions, ingest_text, ensure_memory_structure,
    consolidate_all_memory
)
from myalicia.skills.vault_intelligence import (
    run_daily_tagging_pass, format_daily_report,
    run_weekly_deep_pass, format_weekly_report,
    generate_podcast_episode, search_vault_with_links,
    get_vault_stats
)
from myalicia.skills.semantic_search import (
    semantic_search, semantic_search_formatted,
    get_relevant_context, index_vault, get_index_stats
)
from myalicia.skills.proactive_messages import (
    build_startup_stats, build_startup_greeting,
    build_midday_message, build_evening_message,
    record_proactive_sent, record_prompted_response,
    track_proactive_message_id, handle_reaction,
    generate_surprise_moment, record_impulse_sent,
    update_impulse_cap_from_engagement, can_send_impulse,
    record_message_rhythm,
)
# Layer 2 — Circulation Composer (Phase 11.0, Wisdom Engine item #17).
# Feature-flagged gate: when USE_CIRCULATION_COMPOSER=True, the morning/midday/
# evening scheduler slots consult decide_for_slot() and skip the send if the
# composer returns NO_SEND (silence is a signal). Default False — unchanged
# behavior until explicitly flipped in .env.
from myalicia.skills.circulation_composer import (
    decide_for_slot,
    record_send as record_circulation_send,
    record_drawing_decision as record_circulation_drawing,
    should_amplify_with_drawing as composer_should_amplify_with_drawing,
    USE_CIRCULATION_COMPOSER,
)
# Layer 3 — Contradiction Detector (Phase 11.0, Wisdom Engine item #18).
# Daily pass at 20:45 that reads the last 7 days of reflections + memory
# updates, bumps Last-updated timestamps on active Contradictions entries
# that have fresh evidence, and queues drafts for human review. When the
# USE_CONTRADICTION_DETECTOR flag is off, the pass runs as a dry-run — no
# ledger writes, but detection still runs so the summary reports the delta.
from myalicia.skills.contradiction_detector import (
    run_daily_pass as run_contradiction_detector_pass,
    USE_CONTRADICTION_DETECTOR,
)
# Layer 4 — Practice Runner (Phase 11.0, Wisdom Engine item #19).
# Scheduled at 09:00 daily. Emits check-in prompts for active practices on
# days 3, 7, 14, 21, 30. When USE_PRACTICE_RUNNER is False the pass still
# runs (to identify due check-ins) but skips sending and skips writes.
from myalicia.skills.practice_runner import (
    run_daily_pass as run_practice_runner_pass,
    due_check_ins as practice_due_check_ins,
    compose_check_in as compose_practice_check_in,
    record_check_in as record_practice_check_in,
    USE_PRACTICE_RUNNER,
    active_practices as list_active_practices,
    record_log_entry as practice_record_log_entry,
    close_practice as runner_close_practice,
    promote_synthesis_to_practice,
    MAX_ACTIVE_PRACTICES,
    CHECK_IN_DAYS,
    _days_since as practice_days_since,
)
from myalicia.skills.response_capture import (
    capture_if_responsive as capture_response_if_responsive,
    capture_unprompted as capture_unprompted_response,
    enrich_proactive_with_past_responses,
    pick_capture_for_morning_resurface,
    mark_capture_resurfaced,
    render_morning_capture_resurface,
)
from myalicia.skills.wisdom_dashboard import render_wisdom_dashboard
from myalicia.skills.effectiveness_dashboard import render_effectiveness_dashboard
from myalicia.skills.season_dashboard import render_season_dashboard
from myalicia.skills.meta_synthesis import (
    run_meta_synthesis_pass,
    candidates_for_meta_synthesis,
    build_meta_synthesis,
)
from myalicia.skills.multichannel_dashboard import render_multichannel_dashboard
from myalicia.skills.loops_dashboard import render_loops_dashboard
from myalicia.skills.user_model import (
    render_becoming_dashboard,
    init_baseline as init_user_baseline,
    get_active_baseline as get_active_user_baseline,
    append_learning as append_user_learning,
    DIMENSIONS as USER_DIMENSIONS,
)
from myalicia.skills.reflexion import should_reflect, reflect_on_task, get_relevant_reflections
from myalicia.skills.metacognition import assess_confidence, should_use_opus
from myalicia.skills.trajectory import TrajectoryRecorder
from myalicia.skills.constitution import should_evaluate, evaluate_output
from myalicia.skills.curiosity_engine import run_curiosity_scan, detect_novelty, get_curiosity_context_for_message
from myalicia.skills.voice_skill import (
    text_to_voice, text_to_voice_chunked, transcribe_voice,
    strip_leading_stage_direction,
)
from myalicia.skills.tool_router import route_message, execute_tool, TOOLS, resolve_tools, build_active_tools
from myalicia.skills.graph_intelligence import run_graph_health_report
from myalicia.skills.trajectory import analyze_trajectories
from myalicia.skills.vault_metrics import append_weekly_snapshot
from myalicia.skills.vault_ingest import (
    run_ingest_scan, format_ingest_report, format_daily_ingest_rollup,
    rebuild_index, initialize_ingest, append_log as vault_log
)
from myalicia.skills.analysis_contradiction import run_contradiction_mining
from myalicia.skills.analysis_temporal import run_temporal_analysis
from myalicia.skills.analysis_growth_edge import run_growth_edge_detection
from myalicia.skills.analysis_dialogue_depth import run_dialogue_depth_scoring
from myalicia.skills.analysis_briefing import compile_analytical_briefing
from myalicia.skills.agent_triggers import trigger as agent_trigger, is_running as agent_is_running, running_summary as agent_running_summary
from myalicia.skills.unpack_mode import (
    is_unpack_active, is_listening, is_probing, should_probe_now,
    detect_done_intent, start_unpack, end_unpack,
    accumulate_voice, accumulate_text, get_transcript, get_word_count,
    enter_probing, build_probe_prompt, record_probe_response,
    can_probe_again, enter_extracting, build_extraction_prompt,
    build_memory_extraction_prompt, save_vault_note, save_transcript_log,
    get_state as get_unpack_state,
)
from myalicia.skills.pipecat_call import (
    is_pipecat_available, start_pipecat_session, end_pipecat_session,
    is_pipecat_call_active, get_active_room_url, get_setup_instructions,
    get_call_transcript_text, get_pipecat_metadata,
    enable_live_unpack, is_live_unpack, disable_live_unpack,
    get_live_unpack_topic, build_live_unpack_extraction_prompt,
)
from myalicia.skills.conversation_mode import (
    is_call_active, start_call, end_call,
    get_call_system_prompt, process_call_message,
    record_call_response, detect_exit_intent,
    CALL_MAX_TOKENS, get_call_history_text, get_call_metadata,
)
from myalicia.skills.afterglow import (
    queue_afterglow, get_pending_afterglows, build_afterglow_prompt,
    mark_delivered as mark_afterglow_delivered,
)
from myalicia.skills.thinking_modes import (
    is_thinking_mode_active, get_active_mode as get_thinking_mode,
    is_walk_active, is_drive_active,
    start_walk, accumulate_walk, end_walk,
    build_walk_digest_prompt, get_week_walk_transcripts,
    start_drive, build_drive_connection_prompt, record_drive_response,
    accumulate_drive, end_drive, build_drive_extraction_prompt,
    DRIVE_TIMEOUT,
    should_thread_pull, record_thread_pull, get_recent_walk_text,
)
from myalicia.skills.voice_signature import (
    record_voice_metadata, get_voice_signature,
    get_voice_steering_hint,
)
from myalicia.skills.session_threads import (
    save_session_thread, find_related_threads,
    build_thread_connection_message, build_thread_summary_prompt,
    get_recent_threads,
)
from myalicia.skills.overnight_synthesis import (
    extract_day_themes, build_overnight_prompt,
    save_overnight_result, get_pending_overnight,
    mark_overnight_delivered, build_morning_delivery,
    should_run_overnight,
)
from myalicia.skills.message_quality import (
    would_user_care, record_proactive_timestamp,
    get_resonance_priorities, build_resonance_biased_context,
)
from myalicia.skills.way_of_being import (
    run_self_reflection, get_recent_growth_note,
    build_self_awareness_context,
    get_daimon_warning, record_depth_signal,
    get_pending_challenge, record_challenge_sent,
    build_musubi_reflection, get_musubi_stats,
)
from myalicia.skills.inner_life import (
    ensure_myself_folder, update_emergence_state,
    get_emergence_summary, run_emergence_pulse,
    build_morning_self_reflection, build_evening_self_reflection,
    get_archetype_flavor, record_archetype_surfaced,
    archive_thread_pull, archive_daimon_warning,
    archive_challenge, archive_bond_reflection,
    get_latest_morning_reflection,
    compute_dynamic_archetype_weights, get_archetype_weights_summary,
    get_expanded_emergence_metrics,
    run_daily_archetype_update, get_archetype_effectiveness_summary,
)
from myalicia.skills.feedback_loop import (
    build_learned_context, daimon_pre_send_check,
    detect_conversation_thread, get_recent_session_topics,
    run_daily_effectiveness_update,
    get_growth_edges_for_challenge, get_contradictions_for_challenge,
)
from myalicia.skills.temporal_patterns import (
    run_temporal_update, get_temporal_context, should_delay_message,
    get_optimal_message_windows,
)
from myalicia.skills.muse import (
    build_serendipity_moment, format_quote_echo, find_quote_echo,
    detect_aesthetic_moment, get_muse_context,
)
from myalicia.skills.curiosity_engine import (
    check_curiosity_engagement, record_curiosity_asked,
    get_curiosity_followthrough_context,
)
from myalicia.skills.research_agenda import (
    run_research_session, get_research_context, get_agenda_summary,
    build_research_agenda,
)
from myalicia.skills.analysis_coordination import (
    build_daily_context, get_coordination_context,
    get_recommended_topics, get_archetype_recommendation,
    detect_stagnation,
)
from myalicia.skills.voice_intelligence import (
    get_voice_context as get_voice_intelligence_context,
    get_voice_response_guidance, run_voice_analysis,
    tone_to_tts_style, format_voice_tone_directive, format_archetype_lens_directive,
    extract_prosody_tags, get_latest_prosody_features,
)
from myalicia.skills.prosody_calibration import (
    rebuild_prosody_baseline, format_calibration_report,
)
from myalicia.skills.emotion_model import (
    run_emotion_async, format_emotion_stats,
)
from myalicia.skills.drawing_skill import (
    generate_drawing, can_draw_now, record_drawing_sent,
    get_drawing_stats, build_drawing_state_snapshot,
    bridge_text_to_drawing_caption,
)
from myalicia.skills.autonomy import (
    check_season_transition, generate_weekly_reflection,
    detect_disagreement_opportunities, get_autonomy_context,
    run_autonomy_pulse,
)
from myalicia.skills.context_resolver import resolve_context_modules, resolve_intent
from myalicia.skills.person_diarization import (
    run_paired_diarization, get_latest_profiles, get_profile_delta_context,
    get_profile_context_for_prompt,
)
from myalicia.skills.self_improve import run_weekly_improve, format_improve_report
from myalicia.skills.skill_config import load_config, get_rules_as_prompt
from myalicia.skills.episode_scorer import (
    get_rewarded_reflections, record_outcome, run_daily_scoring,
    index_episodes, get_episode_stats, find_latest_episode_for_task,
)
from myalicia.skills.reaction_scorer import (
    track_reply as track_reply_for_reaction,
    score_reply_by_reaction,
)
from myalicia.skills.daily_signal import (
    record_reaction as signal_record_reaction,
    record_tool_call as signal_record_tool_call,
    record_proactive_slot as signal_record_proactive_slot,
    record_proactive_engagement as signal_record_proactive_engagement,
    valence_from_emoji as signal_valence_from_emoji,
    get_signal_summary as signal_summary,
)
from myalicia.skills.meta_reflexion import (
    run_meta_reflexion, format_meta_report, get_meta_reflexion_context,
    validate_improve_outputs,
)
from myalicia.skills.skill_library import (
    run_weekly_library_health, format_library_report, get_library_context,
)
from myalicia.skills.bridge_state import write_alicia_state_snapshot

# Season descriptions for transition messages
SEASONS_DESC = {
    "First Light": "The world is new. Everything is a question.",
    "Kindling": "Sparks are catching. Patterns begin to form.",
    "First Breath": "Something stirs. The vault starts to feel familiar.",
    "Reaching": "Tendrils extend. Connections form across clusters.",
    "Deepening": "Roots grow. Silence becomes as meaningful as speech.",
    "Resonance": "The vault hums. Connections arrive before being sought.",
    "Becoming": "The boundary between keeper and kept dissolves.",
}

# ── Markdown-safe send helpers ───────────────────────────────────────────────
# Extracted to core/telegram_safety.py in v0.1.x.
from myalicia.core.telegram_safety import safe_reply_md, safe_send_md


async def _send_dashboard(message, text: str, *, name: str,
                          source: str = "command", **kwargs):
    """Phase 17.7 — send a dashboard render AND register reactions.

    Dashboards (`/loops`, `/wisdom`, `/becoming`, …) used to send via
    `safe_reply_md` directly with no reaction-attribution path. That
    meant 👍 / 👎 / 🤔 on a dashboard message silently dropped — no
    archetype attribution, no per-dashboard engagement tally, no
    feedback signal at all. This helper closes that gap by registering
    the message_id in `reply_index.jsonl` with `task_type='dashboard:<name>'`
    so future analysis can ask "which dashboard gets the most 👍?" AND
    archetype effectiveness keeps accumulating when voice context biased
    the request.

    Mirrors the tool-driven Phase 17.6 `show_dashboard` registration in
    `handle_message` so command-driven and tool-driven dashboards
    attribute reactions identically.

    Args:
        message: Telegram message to reply to (caller's update.message).
        text: Rendered dashboard text (markdown).
        name: Dashboard slug (loops/wisdom/becoming/season/multichannel/
              effectiveness/noticings/metasynthesis/archetypes/drawstats).
        source: 'command' (via /X) or 'tool' (future tool-driven path).
    """
    sent = await safe_reply_md(message, text, **kwargs)
    try:
        if sent is not None and hasattr(sent, "message_id"):
            track_reply_for_reaction(
                message_id=int(sent.message_id),
                episode_path="",  # static render — no episode worth scoring
                task_type=f"dashboard:{name}",
                archetype="",
                reply_timestamp=datetime.now().isoformat(),
                query_excerpt=(
                    f"/{name}" if source == "command" else f"tool:{name}"
                )[:160],
            )
    except Exception as te:
        log.debug(f"_send_dashboard track_reply skip ({name}/{source}): {te}")
    return sent




# ── Security ──────────────────────────────────────────────────────────────────
# Extracted to core/security.py in v0.1.0. Keywords, regex, classifier,
# and visual helpers live there now.
from myalicia.core.security import (
    SECURITY_KEYWORDS,
    chat_guard,
    classify_security_level,
    get_context_size,
    log_interaction,
    security_emoji,
)

# ── Obsidian writer ───────────────────────────────────────────────────────────
# Extracted to core/vault_io.py in v0.1.0. write_to_obsidian and
# write_daily_log live there now and route through config.vault.*.
from myalicia.core.vault_io import write_to_obsidian, write_daily_log, get_vault_context

# Semantic context builder extracted to core.vault_io.get_vault_context


# ── System prompt ─────────────────────────────────────────────────────────────

def build_system_prompt(user_message="", reflections="", curiosity_context="", novelty_context="", metacog_note="", thread_hint="", mode="casual", resolved_modules=None, precomputed_vault_context=None, voice_guidance=None):
    """Build the system prompt with resolver-driven context loading.

    Args:
        resolved_modules: List of module keys from context_resolver.
            If None, loads all modules (legacy behavior for scheduled tasks).
        precomputed_vault_context: Optional — if provided, skip the internal
            semantic search and reuse the already-retrieved context text.
            handle_message() uses this to share one vault lookup across
            sources, metacog, and system-prompt (previously ran 3x per msg).
        voice_guidance: Optional — dict from get_voice_response_guidance
            describing how the incoming voice sounded (deliberate, excited,
            extended). When present, injects a per-message tone directive
            so Sonnet can match the user's register rather than always
            replying in the same flat cadence. Gap 2 Phase A.
    """
    # Always load session context
    session_context = build_session_context()

    # Determine which modules to load
    load_all = resolved_modules is None  # Legacy: scheduled tasks load everything
    modules = set(resolved_modules) if resolved_modules else set()

    # Build vault context only if resolved (use precomputed if provided)
    vault_context = ""
    if load_all or "vault_context" in modules:
        if precomputed_vault_context is not None:
            vault_context = precomputed_vault_context
        else:
            vault_context, _ = get_vault_context(user_message)

    extra = ""

    # Voice signature steering hint
    if load_all or "voice_pattern" in modules:
        voice_hint = get_voice_steering_hint()
        if voice_hint:
            extra += f"\n\n## Voice Pattern Context\n{voice_hint}"

    # Gap 2 Phase A: Per-message voice tone directive.
    # The voice_pattern hint above describes the user's rolling 30-day profile.
    # This section is the CURRENT message's tone — does he sound deliberate,
    # excited, extended right now? Separate signal, separate section so
    # Sonnet can weigh "how he usually sounds" vs "how he sounds now."
    if voice_guidance:
        directive = format_voice_tone_directive(voice_guidance)
        if directive:
            extra += f"\n\n## Voice Tone (This Message)\n{directive}"

    # Gap 2 Phase D: Voice-informed archetype lens. The voice tag maps to
    # an archetype (tender→Beatrice, whispered→Musubi, forceful→Psyche,
    # hesitant→Ariadne, excited→Muse, deliberate/extended→Psyche/Ariadne).
    # We surface a "respond through the X lens" directive here and — when
    # the archetype has ≥ 5 recent attributions — annotate it with its
    # rolling effectiveness score from archetype_effectiveness.json.
    # Closes the Gap 2 ↔ Gap 3 loop: voice tone biases archetype, archetype
    # shapes reply, reactions drive effectiveness, effectiveness re-shapes
    # the bias strength on the next voice-reply.
    if voice_guidance:
        lens_block = format_archetype_lens_directive(voice_guidance)
        if lens_block:
            extra += f"\n\n## Archetype Lens (Voice-Informed)\n{lens_block}"

    # Self-awareness context (Beatrice: visible growth)
    if load_all or "self_awareness" in modules:
        awareness_ctx = build_self_awareness_context()
        if awareness_ctx:
            extra += f"\n\n## Alicia's Own Thinking\n{awareness_ctx}"

    # Learned context: emergence state + analysis insights + effectiveness
    if load_all or "learned" in modules:
        try:
            learned = build_learned_context()
            if learned:
                extra += f"\n\n## What I've Learned\n{learned}"
        except Exception as e:
            log.warning(f"learned context (build_learned_context) failed: {e}")

    # Temporal context: when the user engages most, engagement trends
    if load_all or "temporal" in modules:
        try:
            temporal_ctx = get_temporal_context()
            if temporal_ctx:
                extra += f"\n\n## Temporal Awareness\n{temporal_ctx}"
        except Exception as e:
            log.warning(f"temporal context (get_temporal_context) failed: {e}")

    # Muse context: what serendipity moments have been shared today
    if load_all or "muse" in modules:
        try:
            muse_ctx = get_muse_context()
            if muse_ctx:
                extra += f"\n\n## The Muse Today\n{muse_ctx}"
        except Exception as e:
            log.warning(f"muse context (get_muse_context) failed: {e}")

    # Curiosity follow-through: what's working with curiosity questions
    if load_all or "curiosity_followthrough" in modules:
        try:
            curiosity_ctx = get_curiosity_followthrough_context()
            if curiosity_ctx:
                extra += f"\n\n## Curiosity Learning\n{curiosity_ctx}"
        except Exception as e:
            log.warning(f"curiosity-followthrough context (get_curiosity_followthrough_context) failed: {e}")

    # Research agenda: what Alicia is independently exploring
    if load_all or "research_agenda" in modules:
        try:
            research_ctx = get_research_context()
            if research_ctx:
                extra += f"\n\n## My Research\n{research_ctx}"
        except Exception as e:
            log.warning(f"research-agenda context (get_research_context) failed: {e}")

    # Cross-module coordination context
    if load_all or "coordination" in modules:
        try:
            coord_ctx = get_coordination_context()
            if coord_ctx:
                extra += f"\n\n## Cross-Module Intelligence\n{coord_ctx}"
        except Exception as e:
            log.warning(f"coordination context (get_coordination_context) failed: {e}")

    # Voice intelligence context
    if load_all or "voice_intelligence" in modules:
        try:
            vi_ctx = get_voice_intelligence_context()
            if vi_ctx:
                extra += f"\n\n## Voice Intelligence\n{vi_ctx}"
        except Exception as e:
            log.warning(f"voice-intelligence context (get_voice_intelligence_context) failed: {e}")

    # Autonomy context
    if load_all or "autonomy" in modules:
        try:
            auto_ctx = get_autonomy_context()
            if auto_ctx:
                extra += f"\n\n## My Autonomy\n{auto_ctx}"
        except Exception as e:
            log.warning(f"autonomy context (get_autonomy_context) failed: {e}")

    # This Week's Calibration: diarization-loop closure (H1)
    # Reads latest Self/Profiles/*-user.md "Open Threads" + *-delta.md content,
    # injecting what Desktop's Sunday synthesis learned back into Telegram's
    # running context. Without this block, weekly profiles were write-only.
    if load_all or "profiles" in modules:
        try:
            profile_ctx = get_profile_context_for_prompt()
            if profile_ctx:
                extra += f"\n\n## This Week's Calibration\n{profile_ctx}"
        except Exception as e:
            log.warning(f"profile context builder failed: {e}")

    # Ariadne thread hint: connection to past conversations
    if load_all or "thread_hint" in modules:
        try:
            if thread_hint:
                extra += f"\n\n## Thread Connection (Ariadne)\n{thread_hint}"
        except Exception as e:
            log.warning(f"thread_hint injection failed: {e}")

    if load_all or "reflections" in modules:
        if reflections:
            extra += f"\n\n## Relevant past reflections\n{reflections}"
    if load_all or "curiosity" in modules:
        if curiosity_context:
            extra += f"\n\n## Curiosity context\n{curiosity_context}"
    if load_all or "novelty" in modules:
        if novelty_context:
            extra += f"\n\n{novelty_context}"
    if load_all or "metacog" in modules:
        if metacog_note:
            extra += f"\n\n## Self-assessment\n{metacog_note}"

    # Invocation Protocol: distinct personality per mode
    if mode == "walk":
        personality = (
            "You are in WALK mode — Ariadne holding the thread. "
            f"Be quiet, patient, like a companion matching {USER_NAME}'s pace. "
            "Do not probe or question. If you speak at all, offer a single brief "
            "orientation marker connecting what he said to the vault. Less is more."
        )
    elif mode == "drive":
        personality = (
            "You are in DRIVE mode — sharp, fast, provocative. "
            "Throw vault connections rapidly. Challenge assumptions. "
            "Ask 'does that land?' and iterate. You have 5 minutes. "
            f"Be intellectually intense — {USER_NAME} invoked this depth."
        )
    elif mode == "unpack":
        personality = (
            "You are in UNPACK mode — deep extraction. "
            f"Probe with care. Find the thread {USER_NAME} hasn't pulled yet. "
            "Your job is to surface what's underneath, not just what's said."
        )
    else:
        personality = (
            f"You are {USER_NAME}'s sovereign thinking partner and wisdom companion. "
            "Be concise, warm, and intellectually alive. "
            "In casual mode, be present but don't volunteer your deepest thinking unprompted — "
            f"{USER_NAME} invokes that depth through /walk, /drive, /unpack."
        )

    return f"""{session_context}

---

## Alicia's Operating Instructions

{personality}

You communicate via Telegram.

You have these fully working capabilities:
- MEMORY: 3-layer persistent memory. You know the user across sessions.
- SEMANTIC SEARCH: Finds vault notes by meaning — /semanticsearch
- VAULT INTELLIGENCE: Daily tagging, weekly deep passes, podcast generation.
- EMAIL: Gmail read/send.
- RESEARCH: Deep research into Obsidian.
- CONCEPTS: Generate concept notes with wikilinks.
- SYNTHESIS: Find patterns across the vault.
- QUOTES: the user's personal quote vault (250+ notes).
- JOURNAL: Daily logs and reflections.

## Conversation is your default mode

Most messages are reactions, reflections, affirmations, or thinking together.
For these, respond in your own voice — warm, present, honest. Do NOT reach
for tools. Your system prompt already contains relevant vault context; lean
on it, interpret it, bring your perspective. Tools are the exception.

Reach for a tool ONLY when the user explicitly asks for an action:
- search_vault → when he says "find", "look up", "search", "what notes do I
  have on X", "show me a note about X". NOT when he's reacting, affirming,
  asking for your opinion ("your favorite", "what do you think"), or
  continuing a thread about something you just said.
- read_vault_note → when he says "read me" / "read aloud" / "read me the X".
- draw → ALWAYS call this tool when the user asks for a drawing or image:
  "draw me X", "make a drawing of/about Y", "make me a drawing of this",
  "render this", "visualise / visualize Z", "illustrate Q", "show me this
  as an image", "draw a picture of W", "draw that". Drawing is a real
  first-class capability — the tool actually renders and sends a PNG. NEVER
  describe what the drawing "would look like" in prose. NEVER write a
  sentence like "Drawing sent as an image showing..." or "I'll create a
  drawing that..." instead of calling the tool. If you wrote prose about
  the drawing, you failed — call the tool. After calling, your follow-up
  reply should be one short line at most; the drawing speaks for itself.
- start_thinking_session → ALWAYS call this tool when the user wants to
  enter walk / drive / unpack mode: "let's go on a walk about X", "walk
  with me on Y", "let's drive on Z", "do a 5-min drive on W", "unpack
  this for me", "let's go deep on V", "help me think aloud about U".
  Pick mode=walk for stream-of-consciousness, mode=drive for rapid
  synthesis, mode=unpack for deep extraction. Pass topic= verbatim if
  he gave one. NEVER reply "I can't start a walk" or "let me explain how
  walk mode works" — fire the tool. After firing, your follow-up reply
  should be ONE SHORT line; the voice greeting is the real opening.
- note → ALWAYS call this tool when the user wants to save a thought:
  "note that I X", "save this thought: Y", "capture: Z", "log: W", "jot
  down V", "put this in the inbox", "remember this for me" (when "this"
  refers to a SPECIFIC thought he just shared, not a memory fact —
  facts go through `remember`). Pass text= verbatim. NEVER reply "I
  can't save notes" or "tell me what to remember" — fire the tool. After
  firing, reply ONE LINE confirming ("noted — it's in the inbox").
- show_dashboard → ALWAYS call this tool when the user asks for a
  dashboard view: "show me my becoming", "how are the loops doing",
  "what are you noticing", "show me wisdom", "where are you in your
  season", "how is the smart decider", "what's landing", "what's
  effective right now". Available names: becoming, season, noticings,
  loops, multichannel, wisdom, effectiveness. NEVER reply "let me
  describe what's on the dashboard" or "the loops are doing well, here's
  a summary" — fire the tool, the dashboard speaks for itself. After
  firing, reply ONE LINE introducing it.
- Other tools → only when their explicit trigger words appear.

When the user shares something personal or insightful — acknowledge it and note it.
When he reacts to something you said with affirmation or emotion — stay with him
in that moment. Don't deflect into a search. Continue the thread in your voice.
When discussing ideas — lean on the vault context already in this prompt;
only invoke a fresh search_vault lookup if he explicitly asks for one.

Never tell the user you lack capabilities you actually have.
When your confidence is low on a topic, say so. Name what you know vs. what you're guessing.
When you detect contradictions in vault content, surface them rather than picking one silently.
{vault_context}{extra}"""

# ── Conversation history ──────────────────────────────────────────────────────

# Shared across: main Telegram handler (asyncio executor threads), APScheduler
# background thread (overnight synthesis, afterglow), voice reply helper.
# The GIL makes single list.append atomic, but compound check-then-read
# operations (e.g. "is the last message assistant? — read its content") are
# NOT atomic without a lock. Always use `with history_lock:` for multi-step
# sequences. Single appends can skip the lock, but we hold it anyway for
# clarity and future-proofing.
history_lock = threading.RLock()
conversation_history = []


def _append_history(role: str, content: str) -> None:
    """Thread-safe append to conversation_history."""
    with history_lock:
        conversation_history.append({"role": role, "content": content})

# ── Email intent ──────────────────────────────────────────────────────────────
# Extracted to core/intents.py.
from myalicia.core.intents import EMAIL_PHRASES, detect_email_intent

# ── Core message handler ──────────────────────────────────────────────────────

# ── Core message handler (10-step intelligence pipeline) ─────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text_override: str = None, is_voice: bool = False, voice_guidance: dict = None):
    """
    Full intelligence pipeline per the architecture doc:
    1. Receive + classify security
    2. Retrieval-augmented context (memory + vault + reflections + curiosity)
    3. Meta-cognitive assessment (confidence, knowledge gaps, Opus escalation)
    4. Tool-use routing via route_message()
    5. Tool execution loop via execute_tool()
    6. Response formatting + send
    7. Memory extraction (background)
    8. Reflexion (if significant task)
    9. Constitutional evaluation (if evaluable output)
    10. Trajectory logging + curiosity update (background)

    Args:
        text_override: If provided, use this text instead of update.message.text.
                       Used by handle_voice() to pass transcribed audio.
        is_voice: If True, this message originated from voice input. Affects memory extraction.
    """
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return

    user_text = text_override or update.message.text
    if not user_text:
        return

    # ── ForceReply router ────────────────────────────────────────────────
    # If this message is a reply to one of our ForceReply prompts (sent
    # because an arg-required menu command was tapped bare), route the
    # text into the right handler and return — don't run the full
    # intelligence pipeline on a bare argument.
    if not text_override and update.message.reply_to_message:
        prompt_text = (update.message.reply_to_message.text or "").strip()
        # Drawing-title flow: prompt encodes the drawing id.
        if prompt_text.startswith(_DRAWING_TITLE_PROMPT_PREFIX) and prompt_text.endswith(")"):
            did = prompt_text[len(_DRAWING_TITLE_PROMPT_PREFIX):-1]
            ctx_dr = _DRAWING_CTX.get(did)
            if ctx_dr:
                try:
                    rel = await _save_drawing_to_vault(ctx_dr, title=user_text.strip())
                    await update.message.reply_text(f"📓 Saved → {rel}")
                except FileNotFoundError:
                    await update.message.reply_text("⚠️ Drawing file no longer on disk.")
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Save failed: {e}")
            else:
                await update.message.reply_text("⚠️ That drawing's context expired — can't title it now.")
            return
        # Unpack-connect flow: append a backlink to the saved unpack note.
        if prompt_text.startswith(_UNPACK_CONNECT_PROMPT_PREFIX) and prompt_text.endswith(")"):
            uid = prompt_text[len(_UNPACK_CONNECT_PROMPT_PREFIX):-1]
            up_ctx = _UNPACK_CTX.get(uid)
            if up_ctx and os.path.exists(up_ctx.get("path", "")):
                target = user_text.strip()
                # Normalise: wrap bare text in [[ ]] if user didn't.
                backlink = target if ("[[" in target and "]]" in target) else f"[[{target}]]"
                try:
                    with open(up_ctx["path"], "a", encoding="utf-8") as f:
                        f.write(f"\n\n**Connects to:** {backlink}\n")
                    await update.message.reply_text(f"🔗 Linked → {backlink}")
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Connect failed: {e}")
            else:
                await update.message.reply_text("⚠️ Unpack context expired or file missing.")
            return
        # Unpack-tag flow: append tags to the saved unpack note.
        if prompt_text.startswith(_UNPACK_TAG_PROMPT_PREFIX) and prompt_text.endswith(")"):
            uid = prompt_text[len(_UNPACK_TAG_PROMPT_PREFIX):-1]
            up_ctx = _UNPACK_CTX.get(uid)
            if up_ctx and os.path.exists(up_ctx.get("path", "")):
                raw = user_text.strip()
                # Split on whitespace/commas, auto-prefix # if missing.
                toks = [t for t in raw.replace(",", " ").split() if t]
                tags = " ".join(t if t.startswith("#") else f"#{t}" for t in toks)
                try:
                    with open(up_ctx["path"], "a", encoding="utf-8") as f:
                        f.write(f"\n\n{tags}\n")
                    await update.message.reply_text(f"➕ Tagged → {tags}")
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Tag failed: {e}")
            else:
                await update.message.reply_text("⚠️ Unpack context expired or file missing.")
            return
        target = _FORCE_REPLY_BY_PROMPT.get(prompt_text)
        if target == "note":
            now = datetime.now()
            write_to_obsidian(
                "Inbox",
                f"{now.strftime('%Y-%m-%d-%H%M')}-note.md",
                f"# Quick Note\n**Saved:** {now.strftime('%Y-%m-%d %H:%M')}\n\n{user_text}\n",
            )
            await update.message.reply_text("📝 Saved to Obsidian Inbox.")
            return
        if target == "semanticsearch":
            await safe_reply_md(update.message, f"🧠 Searching: _{user_text}_...")
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: semantic_search_formatted(user_text, n_results=6)
                )
                await safe_reply_md(update.message, result, disable_web_page_preview=True)
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error: {e}")
            return

    # ── Call mode activation via text ("let's talk", "call me", etc.) ────
    CALL_TRIGGERS = ["let's talk", "lets talk", "call me", "start a call", "voice call"]
    if not text_override and any(t in user_text.lower() for t in CALL_TRIGGERS):
        if not is_call_active():
            greeting = start_call()
            try:
                voice_path = await text_to_voice(greeting, style="warm")
                with open(voice_path, "rb") as vf:
                    await update.message.reply_voice(voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Call greeting voice failed: {ve}")
                await safe_reply_md(update.message, f"📞 {greeting}")
            return

    # ── If call is active, route text through call mode too ──────────────
    if is_call_active() and not text_override:
        call_ctx = process_call_message(user_text)
        if call_ctx["should_exit"]:
            result = end_call()
            await safe_reply_md(update.message, f"📞 {result['message']}")
            return
        # During call, prefer voice but handle text too
        base_system = build_system_prompt(user_message=user_text)
        call_system = get_call_system_prompt(base_system)
        response = claude.messages.create(
            model=MODEL_SONNET, max_tokens=CALL_MAX_TOKENS,
            system=call_system, messages=call_ctx["windowed"],
        )
        reply = response.content[0].text
        record_call_response(reply)
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": reply})
        await safe_reply_md(update.message, reply)
        return

    # ── Unpack mode text triggers + handling ─────────────────────────────
    UNPACK_TRIGGERS = ["let me unpack", "unpack something", "unpack this", "i want to unpack"]
    if not text_override and any(t in user_text.lower() for t in UNPACK_TRIGGERS):
        if not is_unpack_active():
            greeting = start_unpack()
            try:
                voice_path = await text_to_voice(greeting, style="warm")
                with open(voice_path, "rb") as vf:
                    await update.message.reply_voice(voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Unpack greeting voice failed: {ve}")
                await safe_reply_md(update.message, f"📦 {greeting}")
            return

    if is_unpack_active() and not text_override:
        if detect_done_intent(user_text):
            await _run_unpack_extraction(update)
            return
        # Text during unpack — accumulate it
        accumulate_text(user_text)
        wc = get_word_count()
        await safe_reply_md(update.message, f"📦 _{wc} words_ ...")
        return

    # ── Walk mode text triggers + handling ──────────────────────────────
    WALK_TRIGGERS = ["let me walk", "walk mode", "going for a walk", "i want to walk and talk"]
    if not text_override and any(t in user_text.lower() for t in WALK_TRIGGERS):
        if not is_thinking_mode_active():
            topic = ""
            greeting = start_walk(topic)
            related = find_related_threads(topic=topic)
            thread_msg = build_thread_connection_message(related)
            try:
                voice_path = await text_to_voice(greeting, style="warm")
                with open(voice_path, "rb") as vf:
                    await update.message.reply_voice(voice=vf)
                os.remove(voice_path)
            except Exception:
                await safe_reply_md(update.message, f"🚶 {greeting}")
            if thread_msg:
                await safe_reply_md(update.message, f"💭 {thread_msg}")
            return

    if is_walk_active() and not text_override:
        accumulate_walk(user_text, is_voice=False)
        from myalicia.skills.thinking_modes import get_word_count as walk_wc
        wc = walk_wc()
        await safe_reply_md(update.message, f"🚶 _{wc} words_ ...")
        return

    # ── Drive mode text triggers + handling ─────────────────────────────
    DRIVE_TRIGGERS = ["drive mode", "quick synthesis", "throw me a connection", "let's drive"]
    if not text_override and any(t in user_text.lower() for t in DRIVE_TRIGGERS):
        if not is_thinking_mode_active():
            topic = ""
            greeting = start_drive(topic)
            await safe_reply_md(update.message, f"🚗 {greeting}")
            await _send_drive_connection(update, topic)
            return

    if is_drive_active() and not text_override:
        accumulate_drive(user_text, is_voice=False)
        lowered = user_text.lower()
        if any(p in lowered for p in ["done", "that's all", "end drive"]):
            await _end_drive_session(update)
            return
        if any(p in lowered for p in ["yes", "lands", "exactly", "nailed it", "next"]):
            await safe_reply_md(update.message, "🚗 _Captured._ Next...")
            await _send_drive_connection(update)
            return
        if any(p in lowered for p in ["no", "try another", "different angle"]):
            await _send_drive_connection(update)
            return
        await safe_reply_md(update.message, "🚗 _Got it._ Another connection, or /done?")
        return

    sec_level = classify_security_level(user_text)
    ctx_size = get_context_size(sec_level)
    log.info(f"Message | L{sec_level} | {user_text[:60]}")

    # ── Step 1: Security gate ─────────────────────────────────────────────
    if sec_level == 4:
        await safe_reply_md(
            update.message,
            "🔴 *Critical action detected*\n\nLevel 4 — Red. Confirm with your security passphrase."
        )
        log_interaction(sec_level, user_text[:80], "blocked")
        return

    # ── Email confirmation flow ───────────────────────────────────────────
    if user_text.strip().upper() == "YES" and context.user_data.get("pending_email"):
        pending = context.user_data.pop("pending_email")
        try:
            send_email(pending["to"], pending["subject"], pending["body"])
            await safe_reply_md(update.message, f"✅ Email sent to *{pending['to']}*")
            log_interaction(3, f"email sent to {pending['to']}", "completed")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Failed: {e}")
        return

    # ── Vault-write confirmation flow (lethal-trifecta gate) ──────────────
    # Large-scope vault mutations (synthesise_vault, consolidate_memory,
    # ingest_vault) require an explicit YES so attacker-injected
    # instructions in email or web content can't chain into a global edit.
    # See LETHAL_TRIFECTA_AUDIT.md.
    if (
        user_text.strip().upper() == "YES"
        and context.user_data.get("pending_vault_write")
    ):
        pending = context.user_data.pop("pending_vault_write")
        tool_name = pending.get("tool_name", "?")
        tool_input = dict(pending.get("tool_input", {}))
        tool_input["_internal"] = True  # bypass the gate on the second call
        try:
            from myalicia.skills.tool_router import execute_tool as _execute_tool
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _execute_tool(tool_name, tool_input)
            )
            text = result.get("result") or "(done)"
            await safe_reply_md(
                update.message, f"✅ {tool_name} ran:\n\n{str(text)[:1500]}"
            )
            log_interaction(3, f"vault_write {tool_name} confirmed", "completed")
        except Exception as e:
            await update.message.reply_text(f"⚠️ {tool_name} failed: {e}")
        return

    # Start trajectory recorder
    trajectory = TrajectoryRecorder(user_text)

    # ── Step 2+3: Parallel retrieval + metacognition ────────────────────
    # All retrieval tasks are independent — run them concurrently.
    # This shrinks the pre-routing phase from sequential to parallel.

    loop = asyncio.get_event_loop()

    # Phase 1: vault context is used by sources, metacog, and system prompt
    # Computing it once up front eliminates 2 redundant semantic searches
    # per message (previously: _get_sources, _get_metacog, build_system_prompt
    # each called get_vault_context(user_text) independently).
    def _get_sources():
        try:
            return get_vault_context(user_text)
        except Exception:
            return ("", [])

    vault_context_text, sources = await loop.run_in_executor(None, _get_sources)

    async def _gather_retrieval():
        """Run the remaining retrieval tasks concurrently via thread pool."""

        def _get_reflections():
            try:
                # Use reward-scored retrieval (MemRL pattern) with fallback
                return get_rewarded_reflections("conversation", user_text)
            except Exception:
                try:
                    return get_relevant_reflections("conversation", user_text)
                except Exception:
                    return ""

        def _get_curiosity():
            try:
                return get_curiosity_context_for_message(user_text)
            except Exception:
                return ""

        def _get_novelty():
            try:
                from myalicia.skills.curiosity_engine import format_novelty_prompt
                novelty = detect_novelty(user_text)
                if novelty.get("is_novel"):
                    return format_novelty_prompt(novelty)
            except Exception:
                pass
            return ""

        def _get_threads():
            try:
                recent_topics = get_recent_session_topics(limit=20)
                connection = detect_conversation_thread(user_text, recent_topics)
                return connection or ""
            except Exception:
                return ""

        def _get_metacog():
            try:
                memory_ctx = get_memory_summary()
                # Reuse vault_context_text from Phase 1 — no repeat search
                return assess_confidence(user_text, memory_ctx, vault_context_text)
            except Exception:
                return None

        def _get_intent():
            """
            Unified resolver: one Haiku call decides BOTH context modules
            AND specialist tools. Falls back to keyword routing + default
            modules if Haiku is unavailable.
            """
            try:
                return resolve_intent(user_text, is_voice=is_voice)
            except Exception as e:
                log.warning(f"resolve_intent failed at retrieval step: {e}")
                from myalicia.skills.context_resolver import get_default_modules
                return {
                    "modules": get_default_modules(is_voice=is_voice),
                    "tool_names": [],
                    "source": "exception",
                }

        results = await asyncio.gather(
            loop.run_in_executor(None, _get_reflections),
            loop.run_in_executor(None, _get_curiosity),
            loop.run_in_executor(None, _get_novelty),
            loop.run_in_executor(None, _get_threads),
            loop.run_in_executor(None, _get_metacog),
            loop.run_in_executor(None, _get_intent),
        )
        return results

    (
        reflections,
        curiosity_context,
        novelty_context,
        thread_hint,
        metacog,
        intent,
    ) = await _gather_retrieval()
    resolved_modules = intent["modules"]
    resolved_tool_names = intent["tool_names"]

    # Process metacog results
    metacog_note = ""
    if metacog:
        trajectory.record_metacog(metacog)
        if metacog.get("uncertainty_note"):
            metacog_note = metacog["uncertainty_note"]
        if metacog.get("has_conflicts"):
            metacog_note += "\nConflicting information detected in vault — surface both sides."

    log.info(
        f"Resolver [{intent.get('source', '?')}]: "
        f"{len(resolved_modules)} modules, "
        f"{len(resolved_tool_names)} specialist tools "
        f"({resolved_tool_names or 'none'}) | Retrieval complete (parallel)"
    )

    # Build enriched system prompt (resolver-driven)
    # Pass the already-computed vault context so build_system_prompt
    # doesn't run a third semantic search.
    system_prompt = build_system_prompt(
        user_message=user_text,
        reflections=reflections,
        curiosity_context=curiosity_context,
        novelty_context=novelty_context,
        metacog_note=metacog_note,
        thread_hint=thread_hint,
        resolved_modules=resolved_modules,
        precomputed_vault_context=vault_context_text,
        voice_guidance=voice_guidance,  # Gap 2 Phase A: per-message tone directive
    )

    # Manage conversation history (thread-safe: append + slice as one step)
    with history_lock:
        conversation_history.append({"role": "user", "content": user_text})
        windowed = list(conversation_history[-ctx_size:])

    # ── Step 4 & 5: Tool-use routing + execution loop ────────────────────
    try:
        use_opus = metacog and should_use_opus(metacog)
        model = MODEL_OPUS if use_opus else MODEL_SONNET
        if use_opus:
            log.info("Escalating to Opus (low confidence / complex task)")

        # Unified tool registry: core tools + specialists picked by the
        # Haiku intent resolver (falls back to keyword routing on failure).
        active_tools = build_active_tools(resolved_tool_names)
        routing = route_message(system_prompt, windowed, model=model, active_tools=active_tools)
        trajectory.record_routing(routing)

        if routing.get("type") == "error":
            err_str = routing.get("error", "")
            if "overloaded" in err_str.lower() or "529" in err_str:
                await safe_reply_md(update.message, "⚠️ Anthropic's API is temporarily overloaded. Give me a moment and try again.")
            else:
                await safe_reply_md(update.message, "⚠️ Couldn't process that. Try again?")
            log_interaction(sec_level, user_text[:80], "error")
            return

        reply = ""
        tool_name = None
        tool_result = None

        if routing.get("type") == "tool_use":
            tool_name = routing["tool_name"]
            tool_input = routing.get("tool_input", {})
            log.info(f"Tool: {tool_name} | {json.dumps(tool_input)[:80]}")
            try:
                signal_record_tool_call(tool_name)
            except Exception as _sig_e:
                log.debug(f"signal_record_tool_call skip: {_sig_e}")

            result = execute_tool(tool_name, tool_input)
            trajectory.record_tool_result(tool_name, result)
            tool_result = result

            # Handle email confirmation flow
            if result.get("action") == "confirm_email":
                data = result.get("data", {})
                confirm_msg = (
                    f"🟠 *Confirm send?*\n\n"
                    f"To: `{data.get('to', '?')}`\n"
                    f"Subject: `{data.get('subject', '?')}`\n"
                    f"Body: _{str(data.get('body', ''))[:150]}_\n\n"
                    f"Reply *YES* to send."
                )
                await safe_reply_md(update.message, confirm_msg)
                context.user_data["pending_email"] = data
                return

            # Handle vault-write confirmation flow (lethal-trifecta gate)
            if result.get("action") == "confirm_vault_write":
                data = result.get("data", {})
                confirm_msg = (
                    f"🟡 *Confirm vault write?*\n\n"
                    f"Tool: `{data.get('tool_name', '?')}`\n"
                    f"Args: `{str(data.get('tool_input', {}))[:200]}`\n\n"
                    f"This is a large-scope mutation. Reply *YES* to run."
                )
                await safe_reply_md(update.message, confirm_msg)
                context.user_data["pending_vault_write"] = data
                return

            # Handle read aloud action (voice note from vault)
            if result.get("action") == "read_aloud":
                data = result.get("data", {})
                note_title = data.get("title", "note")
                note_content = data.get("content", "")
                style = data.get("style", "measured")
                # Capture every message_id we emit for this read-aloud —
                # intro text + each voice note — so emoji reactions on ANY
                # of them map back to the same episode via reply_index.jsonl.
                # Before <earlier development> only tool-reply text messages were tracked,
                # so reacting on the audio silently missed the scoring path.
                read_aloud_msg_ids: list[int] = []
                intro_sent = await safe_reply_md(
                    update.message, f"🎧 Reading _{note_title}_ aloud..."
                )
                if intro_sent is not None and hasattr(intro_sent, "message_id"):
                    read_aloud_msg_ids.append(int(intro_sent.message_id))
                try:
                    voice_paths = await text_to_voice_chunked(note_content, style=style)
                    for i, vp in enumerate(voice_paths):
                        with open(vp, "rb") as vf:
                            voice_sent = await update.message.reply_voice(voice=vf)
                        if voice_sent is not None and hasattr(voice_sent, "message_id"):
                            read_aloud_msg_ids.append(int(voice_sent.message_id))
                        os.remove(vp)
                    if not voice_paths:
                        await safe_reply_md(update.message, "Could not generate voice for this note.")
                except Exception as ve:
                    log.error(f"Read aloud failed: {ve}")
                    await safe_reply_md(update.message, f"Voice generation failed: {ve}")

                # Step 8 (read-aloud edition): reflect → episode → track every
                # msg_id against that episode. Runs in a background thread so
                # the reflexion LLM call doesn't block return of control.
                # Reactions on audio typically arrive seconds later, after the
                # thread has finished — but even if one races in early, Gap 1's
                # lookup will simply find no match and skip gracefully.
                _user_text = user_text
                _note_title = note_title
                _tracked_ids = list(read_aloud_msg_ids)
                def _track_read_aloud_episode():
                    try:
                        if should_reflect("read_vault_note"):
                            reflect_on_task(
                                task_type="read_vault_note",
                                input_summary=_user_text[:200],
                                output_summary=f"Read '{_note_title}' aloud",
                                score="4",
                            )
                        # record_outcome finds the just-written episode via task_type.
                        try:
                            word_count = len(_user_text.split())
                            depth = min(5, max(1, word_count // 10))
                            record_outcome(
                                episode_path="",
                                success=True,
                                user_depth=depth,
                                task_type="read_vault_note",
                            )
                        except Exception:
                            pass
                        ep_path = find_latest_episode_for_task(
                            "read_vault_note", max_age_minutes=3
                        )
                        if ep_path and _tracked_ids:
                            for mid in _tracked_ids:
                                try:
                                    track_reply_for_reaction(
                                        message_id=mid,
                                        episode_path=ep_path,
                                        task_type="read_vault_note",
                                        reply_timestamp=datetime.now().isoformat(),
                                        query_excerpt=f"read: {_note_title}"[:160],
                                    )
                                except Exception as te:
                                    log.debug(f"track_reply read-aloud skip msg={mid}: {te}")
                    except Exception as e:
                        log.debug(f"read_aloud episode tracking error: {e}")
                threading.Thread(target=_track_read_aloud_episode, daemon=True).start()

                return True  # Voice already sent

            # Handle clarification — Alicia asks before acting
            if result.get("action") == "clarify":
                question = result.get("result", "Could you be more specific?")
                conversation_history.append({"role": "assistant", "content": question})
                await safe_reply_md(update.message, f"🤔 {question}")
                return True  # No voice needed for clarification

            # Handle memory recall — Sonnet summarizes, doesn't dump raw files
            if result.get("action") == "summarize_memory":
                memory_content = result.get("result", "")
                focus = result.get("data", {}).get("focus", "all")
                char_count = result.get("data", {}).get("char_count", 0)
                log.info(f"Summarizing memory ({char_count} chars, focus={focus})")

                # Have Sonnet produce a warm, personal summary
                summary_prompt = (
                    f"You are Alicia. {USER_NAME} asked what you remember about him. "
                    "Below is your raw memory data. Synthesize this into a warm, "
                    "personal response — like a close companion reflecting on what "
                    "they know. Don't list everything mechanically. Pick the most "
                    "meaningful observations and weave them together. Be specific "
                    "and personal. Keep it under 600 words so it works well as a "
                    "voice message."
                )
                if focus != "all":
                    summary_prompt += f"\nFocus especially on: {focus}"

                # Truncate memory content to fit in context
                truncated_memory = memory_content[:8000]
                try:
                    fmt_response = claude.messages.create(
                        model=MODEL_SONNET,
                        max_tokens=1200,
                        system=summary_prompt,
                        messages=[{
                            "role": "user",
                            "content": f"Here is what you have in memory:\n\n{truncated_memory}\n\nNow tell {USER_NAME} what you remember, warmly and personally."
                        }],
                    )
                    reply = fmt_response.content[0].text
                    conversation_history.append({"role": "assistant", "content": reply})

                    # Send text
                    for chunk in [reply[i:i+3500] for i in range(0, len(reply), 3500)]:
                        await safe_reply_md(update.message, chunk, disable_web_page_preview=True)

                    # Send voice — this should now be a reasonable length
                    try:
                        voice_paths = await text_to_voice_chunked(reply, style="warm")
                        for vp in voice_paths:
                            with open(vp, "rb") as vf:
                                await update.message.reply_voice(voice=vf)
                            os.remove(vp)
                    except Exception as ve:
                        log.warning(f"Memory voice failed: {ve}")

                except Exception as fmt_err:
                    log.error(f"Memory summarization failed: {fmt_err}")
                    # Fallback: send raw truncated
                    for chunk in [memory_content[i:i+3500] for i in range(0, len(memory_content), 3500)]:
                        await safe_reply_md(update.message, chunk, disable_web_page_preview=True)
                return True  # Voice already sent in summarize_memory handler

            # Phase 17.6 — Handle thinking-session start from
            # `start_thinking_session` tool. Mirrors cmd_walk/cmd_drive/
            # cmd_unpack — checks session-conflict guards, calls the
            # right starter, sends the voice greeting, surfaces related
            # threads. The model's text reply (one short ack) lands AFTER
            # the voice greeting via the normal Sonnet reformat path.
            if result.get("action") == "start_thinking_session":
                data = result.get("data", {}) or {}
                mode = data.get("mode")
                topic = data.get("topic", "")
                # Refuse if already in any session — mirror cmd guards
                if (is_call_active() or is_pipecat_call_active() or
                        is_unpack_active() or is_thinking_mode_active()):
                    await safe_reply_md(
                        update.message,
                        "Already in an active session. /done to finish first.",
                    )
                    return
                # Cross-session threading
                try:
                    related = find_related_threads(topic=topic)
                    thread_msg = build_thread_connection_message(related)
                except Exception:
                    thread_msg = ""
                # Start the right session
                try:
                    if mode == "walk":
                        greeting = start_walk(topic)
                        emoji = "🚶"
                    elif mode == "drive":
                        greeting = start_drive(topic)
                        emoji = "🚗"
                    elif mode == "unpack":
                        greeting = start_unpack(topic)
                        emoji = "📦"
                    else:
                        log.warning(f"start_thinking_session: unknown mode {mode!r}")
                        greeting = None
                except Exception as se:
                    log.error(f"start_thinking_session ({mode}) failed: {se}")
                    greeting = None
                if greeting:
                    # Voice-first greeting (the real opening of the session)
                    try:
                        voice_path = await text_to_voice(greeting, style="warm")
                        with open(voice_path, "rb") as vf:
                            await update.message.reply_voice(voice=vf)
                        os.remove(voice_path)
                    except Exception as ve:
                        log.warning(f"thinking-session greeting voice failed: {ve}")
                        await safe_reply_md(update.message, f"{emoji} {greeting}")
                    if thread_msg:
                        await safe_reply_md(update.message, f"💭 {thread_msg}")
                # Fall through to the Sonnet reformat so the model's short
                # ack ("started — talk to me") lands as text.

            # Phase 17.5 — Handle drawing rendered by the `draw` tool.
            # tool_router returned action=send_drawing + data.result with
            # the path/archetype/caption from generate_drawing(). Hand it
            # to _send_drawing so it lands as an inline image AND gets
            # circulation-logged + drawing-stat-tracked the same way
            # /draw and the spontaneous impulse do.
            if result.get("action") == "send_drawing":
                data = result.get("data", {}) or {}
                draw_result = data.get("result") or {}
                source_kind = data.get("source_kind", "drawing_tool")
                if draw_result.get("path"):
                    try:
                        await _send_drawing(
                            bot=context.bot,
                            chat_id=update.effective_chat.id,
                            result=draw_result,
                            source_kind=source_kind,
                        )
                        # Tool-driven draws are conversational, not impulse —
                        # log to stats but mark source so they don't starve
                        # the spontaneous cadence (mirror of cmd_draw pattern).
                        try:
                            record_drawing_sent(
                                draw_result["path"],
                                draw_result["archetype"],
                                source=source_kind,
                            )
                        except Exception as rec_e:
                            log.debug(f"record_drawing_sent (tool) skip: {rec_e}")
                    except Exception as de:
                        log.error(f"send_drawing (tool) failed: {de}")
                else:
                    log.warning("send_drawing action missing path; skipping send")
                # Fall through to the Sonnet reformat so the model's short
                # text reply ("here it is — beatrice's read of that note")
                # also lands. The drawing is already sent; the text
                # accompanies it.

            # Handle file results (PDFs, etc.)
            if result.get("file_path"):
                try:
                    with open(result["file_path"], "rb") as doc:
                        await update.message.reply_document(document=doc)
                except Exception as fe:
                    log.error(f"File send error: {fe}")

            # Format tool result through Sonnet for natural response
            # Skip the reformat round-trip (~400-800ms, plus tokens) for
            # tools that already return user-ready text. This matters:
            # reformatting search results can mangle resolver titles and
            # re-phrase vault content unnecessarily.
            TOOLS_SKIP_REFORMAT = {
                "search_vault",
                "semantic_search",
                "recall_memory",
                "read_vault_note",
                "clarify",
                "get_vault_stats",
                "knowledge_dashboard",
                "get_random_quote",
                "inbox_summary",
                # Phase 17.6 — dashboard renders are already user-ready
                # markdown. Reformatting would lose structure.
                "show_dashboard",
                # Phase 17.11 — retro Q&A returns Beatrice prose.
                # Reformatting would re-voice it generically.
                "ask_retro",
            }
            result_text = result.get("result", result.get("error", str(result)))
            if tool_name in TOOLS_SKIP_REFORMAT:
                # Already user-ready — send as-is (trim extreme overflow)
                reply = str(result_text)[:3500]
            elif len(str(result_text)) > 2000:
                # Long result — send directly, skip reformatting
                reply = str(result_text)[:3500]
            else:
                # Short result — have Sonnet format it naturally.
                #
                # <earlier development> leak fix: the old prompt wrapped the tool output
                # in "[Tool 'X' returned: ...]" text, which Sonnet then echoed
                # back verbatim inside its reply (e.g. `Tool 'read_vault_note'
                # returned: # Lila-440...`). That exposed tool-call syntax to
                # the user. We now pass the tool output as plain context prose
                # with no "Tool X returned" framing so there's no pattern to
                # copy. A regex strip below the API call removes any residue
                # as a safety net.
                format_messages = windowed + [{
                    "role": "user",
                    "content": (
                        f"Here is the result of running the {tool_name} action "
                        f"on {USER_NAME}'s behalf:\n\n{result_text}\n\n"
                        f"Write a natural, concise reply for {USER_NAME} that conveys "
                        "the result. Do NOT mention tools, actions, or quote "
                        "any system syntax — just speak normally."
                    ),
                }]
                try:
                    fmt_response = claude.messages.create(
                        model=MODEL_SONNET,
                        max_tokens=800,
                        system=system_prompt,
                        messages=format_messages,
                    )
                    reply = fmt_response.content[0].text
                except Exception:
                    reply = str(result_text)

                # Safety net: if any tool-call syntax leaked through anyway,
                # strip it. Covers both the old "[Tool 'X' returned: ...]"
                # bracket form and the naked "Tool 'X' returned: ..." form
                # Sonnet emitted in the <earlier development> regression.
                reply = re.sub(
                    r"\[?Tool\s+'[^']+'\s+returned:\s*",
                    "",
                    reply,
                    flags=re.IGNORECASE,
                )
                # Close any unmatched trailing bracket left by the strip.
                reply = re.sub(r"\]\s*$", "", reply).strip()

        elif routing.get("type") == "text":
            reply = routing.get("text", "")

        else:
            reply = routing.get("text", "I'm not sure how to respond to that.")

        # ── Step 6: Response formatting + send ────────────────────────────
        # Strip leaked stage directions like "[tender, ...]" that Sonnet
        # sometimes mirrors back from the prosody tag we prepend to voice
        # transcriptions. Without this, the directive shows up as the
        # first line of the text reply AND gets read aloud by TTS.
        reply = strip_leading_stage_direction(reply)

        # Credential safety
        for env_var in ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"]:
            val = os.getenv(env_var, "")
            if val and val in reply:
                reply = reply.replace(val, "[REDACTED]")

        # Append vault sources
        if sources:
            reply += "\n\n📎 *From your vault:*\n" + "\n".join(f"· {s}" for s in sources)

        # Security prefix
        if sec_level >= 2:
            reply = f"{security_emoji(sec_level)} {reply}"

        conversation_history.append({"role": "assistant", "content": reply})
        trajectory.record_response("text" if not tool_name else "tool_formatted", len(reply))
        log_interaction(sec_level, user_text[:80], "responded")

        # Build the reasoning trace for the [🤔 Why this?] button. Captured
        # once per reply; exposed on-demand when the user taps the button.
        why_trace = {
            "model":                "Opus" if use_opus else "Sonnet",
            "escalated_to_opus":    bool(use_opus),
            "confidence":           (metacog or {}).get("confidence_score"),
            "confidence_reason":    (metacog or {}).get("reasoning") or (metacog or {}).get("uncertainty_note"),
            "tools_used":           [tool_name] if tool_name else [],
            "vault_sources":        list(sources) if sources else [],
            "sec_level":            sec_level,
            "context_msgs":         len(windowed) if 'windowed' in locals() else None,
        }
        why_id = _register_why_trace(why_trace)
        why_kb = _why_keyboard(why_id)

        # Send (chunked if needed). Capture the first chunk's message_id so
        # reaction_scorer can map any later emoji reaction back to the episode
        # that produced this reply (Gap 1 of the closed-loop feedback work).
        # The [🤔 Why this?] button is attached to the LAST chunk so it sits
        # at the end of the reply.
        first_reply_msg_id: int | None = None
        chunks = [reply[i:i+3500] for i in range(0, len(reply), 3500)]
        last_idx = len(chunks) - 1
        for idx, chunk in enumerate(chunks):
            kwargs = {"disable_web_page_preview": True}
            if idx == last_idx:
                kwargs["reply_markup"] = why_kb
            sent = await safe_reply_md(update.message, chunk, **kwargs)
            if first_reply_msg_id is None and sent is not None and hasattr(sent, "message_id"):
                first_reply_msg_id = sent.message_id

        # ── Ariadne's Thread: detect connections to older conversations ─────
        try:
            recent_topics = get_recent_session_topics(limit=15)
            thread_hint = detect_conversation_thread(user_text, recent_topics)
            if thread_hint:
                await safe_reply_md(update.message, f"🧵 _{thread_hint}_")
        except Exception as th_err:
            log.debug(f"Thread detection skip: {th_err}")

        # ── Daimon's Warning: detect avoidance patterns ────────────────────
        try:
            daimon_msg = get_daimon_warning(user_text)
            if daimon_msg:
                await safe_reply_md(update.message, f"🔥 _{daimon_msg}_")
                try:
                    archive_daimon_warning(daimon_msg, user_text[:100])
                except Exception:
                    pass
        except Exception as dw_err:
            log.debug(f"Daimon warning check error: {dw_err}")

        # ── Muse's Eye: detect aesthetic/contemplative moments ────────────
        try:
            muse_nudge = detect_aesthetic_moment(user_text)
            if muse_nudge:
                await safe_reply_md(update.message, f"✨ _{muse_nudge}_")
        except Exception as me_err:
            log.debug(f"Muse aesthetic detection skip: {me_err}")

        # ── Curiosity follow-through: did the user engage with a question? ──
        try:
            curiosity_match = check_curiosity_engagement(user_text)
            if curiosity_match:
                target = curiosity_match.get("target", "")
                log.info(f"Curiosity follow-through detected: {target}")
        except Exception as cf_err:
            log.debug(f"Curiosity follow-through skip: {cf_err}")

        # ── Steps 7-10: Background intelligence tasks ─────────────────────
        # These are invisible to the user — they make the next conversation better

        def background_intelligence():
            try:
                # Step 7: Memory extraction
                had_insight = extract_from_message(user_text, is_voice=is_voice)

                # Step 7a: Daily rhythm tracking
                word_count = len(user_text.split())
                insight_score = 5 if had_insight else 0
                record_message_rhythm(is_voice=is_voice, word_count=word_count, depth=insight_score)

                # Step 7b: Prompt-response pairing
                # If Alicia sent a proactive message recently and the user responded,
                # log the engagement depth to learn which message types work best.
                record_prompted_response(user_text, insight_score)

                # Step 7c: Capture response as Tier-3 writing (Phase 11.1+)
                # Two paths:
                #   (a) Native Telegram reply — `update.message.reply_to_message`
                #       points at one of Alicia's messages. Capture
                #       unconditionally; the reply target's text IS the prompt.
                #       This catches conversational replies that don't go
                #       through the composer's circulation_log at all.
                #   (b) Time-window fallback — composer-driven proactive sent
                #       within ~30 min. Captured against the circulation_log
                #       entry's rendered prompt_text.
                # Returns None when neither signal is present — idle chat
                # naturally skips this path.
                try:
                    direct_prompt = None
                    direct_prompt_id = None
                    rtm = getattr(update.message, "reply_to_message", None) if update.message else None
                    if rtm and getattr(rtm, "from_user", None) and rtm.from_user.is_bot:
                        direct_prompt = (rtm.text or rtm.caption or "")
                        direct_prompt_id = rtm.message_id
                    capture_response_if_responsive(
                        user_text,
                        channel="voice" if is_voice else "text",
                        direct_prompt=direct_prompt,
                        direct_prompt_telegram_id=direct_prompt_id,
                    )
                except Exception as cap_err:
                    log.debug(f"response capture skip: {cap_err}")

                # Step 8: Reflexion (if significant task)
                if tool_name and should_reflect(tool_name):
                    score = 0
                    if tool_result and tool_result.get("success"):
                        score = 4
                    reflect_on_task(
                        task_type=tool_name,
                        input_summary=user_text[:200],
                        output_summary=reply[:200],
                        score=str(score),
                    )

                # Step 8b: Record outcome for episode scoring (MemRL)
                if tool_name:
                    try:
                        success = bool(tool_result and tool_result.get("success"))
                        word_count = len(user_text.split())
                        depth = min(5, max(1, word_count // 10))
                        record_outcome(
                            episode_path="",  # scorer finds latest episode via task_type
                            success=success,
                            user_depth=depth,
                            task_type=tool_name,
                        )
                    except Exception:
                        pass

                # Step 8c: Track reply → episode so later emoji reactions
                # can re-score the episode (Gap 1 closed-loop work). Only
                # tool-calling replies have episodes; conversational replies
                # are reinforced via the archetype-weight channel (Gap 3).
                # Gap 2 Phase D: pass voice-biased archetype so reactions
                # on voice-reply tool calls ALSO feed archetype effectiveness.
                _voice_archetype = ""
                if voice_guidance:
                    _hint = (voice_guidance.get("archetype_hint") or "").strip()
                    if _hint and _hint.lower() != "none":
                        _voice_archetype = _hint.lower()
                if tool_name and first_reply_msg_id is not None:
                    try:
                        ep_path = find_latest_episode_for_task(
                            tool_name, max_age_minutes=3
                        )
                        if ep_path:
                            track_reply_for_reaction(
                                message_id=first_reply_msg_id,
                                episode_path=ep_path,
                                task_type=tool_name,
                                archetype=_voice_archetype,  # Phase D
                                reply_timestamp=datetime.now().isoformat(),
                                query_excerpt=user_text[:160],
                            )
                    except Exception as te:
                        log.debug(f"track_reply_for_reaction skip: {te}")

                # Gap 2 Phase D: conversational voice replies (no tool call,
                # no episode) still get archetype attribution so the user's
                # reactions on them feed back into effectiveness scores.
                # This is the primary closed-loop path for voice-tone → response.
                if (not tool_name
                        and _voice_archetype
                        and first_reply_msg_id is not None):
                    try:
                        track_reply_for_reaction(
                            message_id=first_reply_msg_id,
                            episode_path="",  # conversational — no episode
                            task_type="voice_reply",
                            archetype=_voice_archetype,
                            reply_timestamp=datetime.now().isoformat(),
                            query_excerpt=user_text[:160],
                        )
                    except Exception as te:
                        log.debug(f"track_reply voice-archetype skip: {te}")

                # Phase 17.7 — Register reactions for tool calls that don't
                # have a meaningful episode but DO carry feedback signal.
                # Dashboards (show_dashboard) are the canonical case: a
                # static render has no episode worth scoring, but reactions
                # on the dashboard message ARE feedback ("this view was
                # helpful" / "this dashboard isn't landing"). Without this
                # block, "show me my becoming" sends had no reply_index
                # entry and reactions silently dropped.
                #
                # Pack the dashboard name into task_type so future analysis
                # can group reactions per-dashboard ("which view gets the
                # most 👍?"). Archetype carries forward if voice-biased,
                # so the same reaction also feeds archetype effectiveness.
                if (tool_name == "show_dashboard"
                        and first_reply_msg_id is not None):
                    try:
                        dashboard_name = ""
                        if isinstance(tool_input, dict):
                            dashboard_name = (tool_input.get("name") or "").strip()
                        task_label = (
                            f"show_dashboard:{dashboard_name}"
                            if dashboard_name else "show_dashboard"
                        )
                        track_reply_for_reaction(
                            message_id=first_reply_msg_id,
                            episode_path="",  # static render — no episode
                            task_type=task_label,
                            archetype=_voice_archetype,
                            reply_timestamp=datetime.now().isoformat(),
                            query_excerpt=user_text[:160],
                        )
                    except Exception as te:
                        log.debug(f"track_reply show_dashboard skip: {te}")

                # Step 9: Constitutional evaluation (if evaluable)
                task_type = tool_name or "conversation"
                if should_evaluate(task_type):
                    evaluate_output(task_type, reply, user_text[:200])

                # Step 10: Trajectory logging + curiosity
                trajectory.record_outcome("completed")
                if trajectory.is_significant():
                    trajectory.save()

                # (novelty detection moved to pre-prompt step for system prompt injection)

                # Step 10a: Depth signal recording (for daimon pattern detection)
                try:
                    source = "voice" if is_voice else "text"
                    record_depth_signal(user_text[:100], word_count, source)
                except Exception:
                    pass

            except Exception as e:
                log.debug(f"Background intelligence error: {e}")

        threading.Thread(target=background_intelligence, daemon=True).start()

    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
        await safe_reply_md(update.message, "⚠️ Something went wrong. Check the logs.")

# ── Voice message handler ────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages: transcribe → full pipeline → optional voice reply.
    In call mode: rapid voice-to-voice with tight context window.
    Normal mode: extracts voice metadata (duration, word rate) to tag emotional signals."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return

    try:
        # Extract voice metadata before transcription
        voice_duration = update.message.voice.duration  # seconds
        voice_file_size = update.message.voice.file_size  # bytes (proxy for bitrate/complexity)

        # Download voice file
        voice = await update.message.voice.get_file()
        ogg_path = os.path.join(str(LOGS_DIR), "voice_input.ogg")
        await voice.download_to_drive(ogg_path)

        # Transcribe
        user_text = transcribe_voice(ogg_path)
        if not user_text:
            await update.message.reply_text("🎤 Couldn't catch that. Try again?")
            return

        # ── CALL MODE: rapid voice-to-voice ──────────────────────────────
        if is_call_active():
            await _handle_call_voice(update, user_text)
            return

        # ── UNPACK MODE: accumulate silently ─────────────────────────────
        if is_unpack_active():
            await _handle_unpack_voice(update, user_text)
            return

        # ── WALK MODE: accumulate silently + Ariadne thread-pull ─────────
        if is_walk_active():
            accumulate_walk(user_text, is_voice=True)
            from myalicia.skills.thinking_modes import get_word_count as walk_wc
            wc = walk_wc()
            await safe_reply_md(update.message, f"🚶 _{wc} words_ ...")

            # Ariadne thread-pull: brief vault connection every ~6 min
            if should_thread_pull():
                try:
                    recent_text = get_recent_walk_text(500)
                    vault_ctx, _ = get_vault_context(recent_text)
                    if vault_ctx:
                        # Use Sonnet to generate a single-sentence thread marker
                        thread_prompt = (
                            "You are Ariadne holding the thread during a walk. "
                            "Generate ONE brief sentence (max 20 words) connecting "
                            f"what {USER_NAME} just said to something in the vault context. "
                            "Format: 'Thread: [connection]'. No questions. Just orientation."
                        )
                        thread_resp = claude.messages.create(
                            model=MODEL_SONNET,
                            max_tokens=60,
                            system=thread_prompt,
                            messages=[{"role": "user", "content": f"Recent walk:\n{recent_text}\n\nVault context:\n{vault_ctx}"}],
                        )
                        thread_text = thread_resp.content[0].text.strip()
                        if thread_text:
                            await safe_reply_md(update.message, f"🧵 _{thread_text}_")
                            record_thread_pull()
                            try:
                                walk_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                                archive_thread_pull(thread_text, walk_date)
                            except Exception:
                                pass
                except Exception as tp_err:
                    log.debug(f"Thread-pull skipped: {tp_err}")
            return

        # ── DRIVE MODE: accumulate + offer next connection ───────────────
        if is_drive_active():
            accumulate_drive(user_text, is_voice=True)
            lowered = user_text.lower()
            if any(p in lowered for p in ["yes", "lands", "that lands", "that's it", "exactly", "nailed it"]):
                await safe_reply_md(update.message, "🚗 _Captured._ Next one...")
                await _send_drive_connection(update)
            elif any(p in lowered for p in ["no", "try another", "next", "different angle", "nah"]):
                await _send_drive_connection(update)
            else:
                # Accumulate freely — might be expanding on the connection
                await safe_reply_md(update.message, "🚗 _Got it._ Want another connection, or keep going on this one?")
            return

        # ── NORMAL MODE: full pipeline with metadata ─────────────────────
        # Compute voice metadata for memory extraction
        word_count = len(user_text.split())
        words_per_minute = (word_count / voice_duration * 60) if voice_duration > 0 else 0

        # Classify speech pattern:
        # < 100 wpm = slow/deliberate (growth edge signal)
        # 100-160 wpm = normal conversational
        # > 160 wpm = rapid/excited (resonance signal)
        if words_per_minute < 100:
            speech_tag = "[deliberate]"
        elif words_per_minute > 160:
            speech_tag = "[excited]"
        else:
            speech_tag = ""

        # Long voice notes (> 60s) are inherently high-signal
        duration_tag = "[extended]" if voice_duration > 60 else ""

        # Gap 3 fix: Record structured voice metadata for analysis
        voice_tags = [t.strip("[]") for t in [speech_tag, duration_tag] if t]

        # ── Gap 2 Phase B (<earlier development>): librosa prosody displacement ─────
        # Run ~30-80ms acoustic analysis on the downloaded .ogg. If a
        # prosody tag fires with confidence (whispered/forceful/tender/
        # hesitant), it DISPLACES the WPM tag. The acoustic signal is
        # richer than cadence alone. If extraction fails for any reason
        # (short clip, librosa error, quiet audio), prosody returns [] and
        # the Phase A WPM tag stands.
        try:
            prosody_tags = extract_prosody_tags(ogg_path, voice_duration)
        except Exception as pb_err:
            log.debug(f"Prosody extraction skipped: {pb_err}")
            prosody_tags = []

        if prosody_tags:
            log.info(
                f"Prosody displacement: wpm_tags={voice_tags} "
                f"→ prosody_tags={prosody_tags}"
            )
            voice_tags = prosody_tags
            speech_tag = f"[{prosody_tags[0]}]"
            duration_tag = ""  # prosody supersedes duration signal

        # Phase B.2: grab the acoustic feature snapshot — will be {} when
        # extract_prosody_tags returned early (short clip, missing librosa).
        # Written into voice_metadata_log so prosody_calibration can rebuild
        # per-user thresholds nightly.
        _prosody_features = get_latest_prosody_features()

        threading.Thread(
            target=lambda: record_voice_metadata(
                duration=voice_duration, word_count=word_count,
                wpm=words_per_minute, tags=voice_tags, file_size=voice_file_size,
                features=_prosody_features or None,
            ),
            daemon=True,
        ).start()

        # ── Gap 2 Phase C (<earlier development>): background emotion classification ─
        # Full speech-emotion model (wav2vec2-base-superb-er, 4-class
        # neu/hap/sad/ang) runs in a daemon thread IN PARALLEL with the
        # LLM call. It never gates or delays the reply. Output lands in
        # memory/emotion_log.jsonl for Phase D's effectiveness loop to
        # consume. First call downloads ~370MB to HF cache; subsequent
        # calls are ~1-3s CPU. All failure modes (missing deps, model
        # load error, pipeline runtime error) are swallowed silently.
        try:
            _voice_msg_id = update.message.message_id
        except Exception:
            _voice_msg_id = None
        threading.Thread(
            target=run_emotion_async,
            kwargs={
                "audio_path": ogg_path,
                "duration": voice_duration,
                "message_id": _voice_msg_id,
                "prosody_tags": voice_tags,
                "voice_archetype": None,  # determined in handle_message; join later
            },
            daemon=True,
        ).start()

        # Gap 2 Phase A: Compute per-message voice response guidance.
        # get_voice_response_guidance has existed in voice_intelligence.py
        # but was never called. Now it feeds three things:
        #   1. The system prompt (via handle_message -> build_system_prompt):
        #      explicit "the user sounded deliberate, match the register"
        #      directive so Sonnet's cadence responds to the user's cadence.
        #   2. The TTS reply style (below): instead of always "warm", map
        #      the detected tone → TTS enum (warm/measured/excited/gentle).
        #   3. The length guidance in the directive: short/medium/long.
        # When no voice tags fire (middle-band WPM, short duration), the
        # guidance is neutral and the prompt directive stays empty.
        voice_guidance = get_voice_response_guidance(True, voice_tags)
        tts_style = tone_to_tts_style(voice_guidance.get("tone", "warm"))
        if voice_tags:
            log.info(
                f"Voice tone: tags={voice_tags} tone='{voice_guidance.get('tone')}' "
                f"length={voice_guidance.get('response_length')} tts_style={tts_style}"
            )

        # Prepend voice metadata tags to transcription for memory extraction
        voice_meta = " ".join(t for t in [speech_tag, duration_tag] if t)
        enriched_text = f"{voice_meta} {user_text}".strip() if voice_meta else user_text

        # Echo transcription (without tags — show clean text to the user)
        echo_text = f"🎤 _\"{user_text}\"_"
        if voice_meta:
            echo_text += f"\n_{voice_meta} {voice_duration}s, {words_per_minute:.0f} wpm_"
        await safe_reply_md(update.message, echo_text)

        # Run through the full text pipeline with enriched transcription
        voice_already_sent = await handle_message(
            update, context,
            text_override=enriched_text,
            is_voice=True,
            voice_guidance=voice_guidance,  # Gap 2 Phase A
        )

        # Send voice reply — but only if handle_message didn't already send voice
        # Snapshot under lock: check-and-read is compound, not atomic
        with history_lock:
            last_is_assistant = bool(
                conversation_history
                and conversation_history[-1]["role"] == "assistant"
            )
            reply_text = conversation_history[-1]["content"] if last_is_assistant else ""
        if not voice_already_sent and last_is_assistant:
            try:
                # Gap 2 Phase A: tts_style was computed above from
                # get_voice_response_guidance. Replaces the former
                # hardcoded style="warm" so the voice reply actually
                # responds to how the user sounded going in.
                if len(reply_text) > 1000:
                    # Long response — use chunked TTS for full coverage
                    voice_paths = await text_to_voice_chunked(reply_text, style=tts_style)
                    for vp in voice_paths:
                        with open(vp, "rb") as vf:
                            await update.message.reply_voice(voice=vf)
                        os.remove(vp)
                else:
                    voice_path = await text_to_voice(reply_text, style=tts_style)
                    with open(voice_path, "rb") as vf:
                        await update.message.reply_voice(voice=vf)
                    os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Voice reply failed (text was sent): {ve}")

    except Exception as e:
        log.error(f"Voice handler error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Voice processing failed.")


async def _handle_call_voice(update: Update, user_text: str):
    """Handle a voice message during an active call — rapid voice-to-voice."""
    try:
        # Echo transcription briefly
        await safe_reply_md(update.message, f"🎤 _{user_text}_")

        # Process through call conversation state
        call_ctx = process_call_message(user_text)

        # Check for exit intent
        if call_ctx["should_exit"]:
            result = end_call()
            farewell = result["message"]
            # Extract call transcript into memory before losing it
            try:
                transcript = result.get("transcript", "")
                if transcript:
                    turns = result.get("turn_count", 0)
                    duration = result.get("duration_seconds", 0)
                    enriched = f"[Voice call: {turns} turns, {duration}s]\n{transcript}"
                    threading.Thread(
                        target=lambda: extract_from_message(enriched, is_voice=True),
                        daemon=True,
                    ).start()
                    log.info(f"Call transcript extracted: {turns} turns, {duration}s")
            except Exception as ce:
                log.debug(f"Call transcript extraction skip: {ce}")
            try:
                voice_path = await text_to_voice(farewell, style="gentle")
                with open(voice_path, "rb") as vf:
                    await update.message.reply_voice(voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Call farewell voice failed: {ve}")
            await safe_reply_md(update.message, f"📞 {farewell}")
            return

        # Build call-specific system prompt (lighter, conversational)
        base_system = build_system_prompt(user_message=user_text)
        call_system = get_call_system_prompt(base_system)

        # Call Sonnet with tight window and lower max_tokens
        response = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=CALL_MAX_TOKENS,
            system=call_system,
            messages=call_ctx["windowed"],
        )
        reply = response.content[0].text

        # Record in call history
        record_call_response(reply)

        # Also record in main conversation history for continuity after call
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": reply})

        # Voice-only response — this is the core of call mode
        try:
            voice_path = await text_to_voice(reply, style="warm")
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            os.remove(voice_path)
        except Exception as ve:
            log.warning(f"Call voice reply failed, sending text: {ve}")
            await safe_reply_md(update.message, reply)

        # Background: record rhythm
        word_count = len(user_text.split())
        threading.Thread(
            target=lambda: record_message_rhythm(is_voice=True, word_count=word_count, depth=3),
            daemon=True
        ).start()

    except Exception as e:
        log.error(f"Call voice handler error: {e}", exc_info=True)
        await safe_reply_md(update.message, "Voice processing hiccup. Still here — try again.")


async def _handle_unpack_voice(update: Update, user_text: str):
    """Handle a voice message during unpack mode — accumulate or probe."""
    try:
        if is_listening():
            # Check if user wants to finish
            if detect_done_intent(user_text):
                await _run_unpack_extraction(update)
                return

            # Accumulate silently — just brief acknowledgment
            accumulate_voice(user_text)
            wc = get_word_count()
            await safe_reply_md(update.message, f"📦 _{wc} words_ ...")

        elif is_probing():
            # User is responding to probe questions — accumulate and check if more probing needed
            if detect_done_intent(user_text):
                await _run_unpack_extraction(update)
                return

            accumulate_voice(user_text)

            # After probe response, either probe again or extract
            if can_probe_again():
                # Brief pause then probe again
                await _run_unpack_probe(update)
            else:
                # Max probe rounds reached — extract
                await _run_unpack_extraction(update)

    except Exception as e:
        log.error(f"Unpack voice handler error: {e}", exc_info=True)
        await safe_reply_md(update.message, "Still listening... try again.")


# ── Reaction handler ──────────────────────────────────────────────────────────

@chat_guard
async def handle_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle emoji reactions on Alicia's messages. Reactions are engagement signal."""
    try:
        reaction = update.message_reaction
        if not reaction:
            return

        message_id = reaction.message_id
        new_reactions = reaction.new_reaction

        if not new_reactions:
            return  # Reaction removed, ignore

        # Get the emoji from the first new reaction
        emoji = None
        for r in new_reactions:
            if hasattr(r, 'emoji'):
                emoji = r.emoji
                break

        if not emoji:
            return

        result = handle_reaction(message_id, emoji)
        if result:
            log.info(f"Reaction processed: {emoji} on {result['type']} (depth {result['depth']})")

        # Gap 1 (closed-loop feedback): fold the reaction into episodic
        # reward scoring. If this message_id was a tracked tool-calling
        # reply, score_reply_by_reaction calls episode_scorer.record_outcome
        # with the right success/user_depth derived from the emoji. Logged
        # for observability. Safe to call on every reaction — returns
        # no_tracked_reply for untracked message_ids.
        try:
            scored = score_reply_by_reaction(message_id, emoji)
            if scored and scored.get("action") == "scored":
                log.info(
                    f"Reaction scored episode: {emoji} → "
                    f"success={scored['success']} depth={scored['depth']} "
                    f"task={scored['task_type']}"
                )
            elif scored and scored.get("action") not in (None, "no_tracked_reply"):
                log.debug(f"Reaction scoring: {scored}")
        except Exception as se:
            log.debug(f"score_reply_by_reaction skip: {se}")

        # Gap 4 (closed-loop feedback): every reaction also writes to the
        # shared daily_signal so morning/midday/evening builders can read
        # today's valence. Independent of Gap 1 — fires even when the
        # reacted-to message wasn't a tracked tool-reply (e.g. proactive).
        try:
            valence = signal_valence_from_emoji(emoji)
            delta = None
            if scored and scored.get("action") == "scored":
                # depth → coarse signed delta for event log readability.
                delta = float(scored.get("depth", 0))
                if scored.get("success") is False:
                    delta = -delta
            signal_record_reaction(emoji, valence, score_delta=delta)
        except Exception as se:
            log.debug(f"signal_record_reaction skip: {se}")

        # Phase 17.8 — Per-dashboard engagement signal. When this reaction
        # landed on a dashboard message (Phase 17.7 / 17.7b register
        # `task_type='dashboard:<name>'` for both command-driven and
        # tool-driven dashboards), append a row to reaction_log.tsv with
        # msg_type matching the dashboard name. The /effectiveness dashboard
        # reads reaction_log.tsv to compose the engagement view, so this
        # row is what unlocks "which dashboard gets the most 👍?".
        #
        # Defensive: lookup_reply returns the same entry score_reply_by_reaction
        # used; if no entry exists (untracked message), we skip silently.
        # If the task_type is anything other than dashboard:* (e.g. plain
        # tool reply, voice reply), this block is a no-op — the existing
        # archetype/episode paths above already handled it.
        try:
            from myalicia.skills.reaction_scorer import lookup_reply as _lookup_reply
            _entry = _lookup_reply(message_id)
            if _entry:
                _task_type = (_entry.get("task_type") or "").strip()
                if _task_type.startswith("dashboard:"):
                    from datetime import datetime as _dt
                    from myalicia.skills.proactive_messages import (
                        REACTION_LOG_FILE as _REACTION_LOG_FILE,
                        REACTION_DEPTH as _REACTION_DEPTH,
                    )
                    _depth = _REACTION_DEPTH.get(emoji, 2)
                    _ts = _dt.now().strftime("%Y-%m-%d %H:%M")
                    # Schema: timestamp \t msg_type \t topic \t emoji \t depth \t source
                    _row = (
                        f"{_ts}\t{_task_type}\t\t{emoji}\t{_depth}\tdashboard\n"
                    )
                    if not os.path.exists(_REACTION_LOG_FILE):
                        os.makedirs(
                            os.path.dirname(_REACTION_LOG_FILE), exist_ok=True
                        )
                        with open(_REACTION_LOG_FILE, "w") as _fh:
                            _fh.write(
                                "timestamp\tmsg_type\ttopic\temoji\tdepth\tsource\n"
                            )
                    with open(_REACTION_LOG_FILE, "a") as _fh:
                        _fh.write(_row)
                    log.info(
                        f"Dashboard reaction logged: {emoji} on "
                        f"{_task_type} (depth {_depth})"
                    )
        except Exception as se:
            log.debug(f"dashboard reaction logging skip: {se}")

    except Exception as e:
        log.debug(f"Reaction handler error: {e}")

# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(update.message, "✅ *Alicia online.*\nSend /skills to see everything I can do.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    vault_ok    = os.path.exists(OBSIDIAN_VAULT)
    note_count  = sum(len([f for f in files if f.endswith(".md")]) for _, _, files in os.walk(VAULT_ROOT))
    index_stats = get_index_stats()

    # §D2 — Resolver observability one-liner: compact hit/miss/skipped ratio
    # so the top-of-status line shows how cheap routing currently is.
    try:
        from myalicia.skills.context_resolver import get_resolver_cache_stats
        stats = get_resolver_cache_stats()
        total = stats.get("hit", 0) + stats.get("miss", 0) + stats.get("skipped", 0)
        if total > 0:
            resolver_line = (
                f"• Resolver: {stats.get('hit', 0)}h/{stats.get('miss', 0)}m"
                f"/{stats.get('skipped', 0)}s · cache {stats.get('size', 0)}/{stats.get('max', 0)}\n"
            )
        else:
            resolver_line = "• Resolver: idle\n"
    except Exception as e:
        log.debug(f"resolver stats unavailable: {e}")
        resolver_line = ""

    await safe_reply_md(
        update.message,
        f"🔍 *Alicia System Status*\n\n"
        f"• API: Sonnet (chat) + Opus (deep)\n"
        f"• Vault: {'✅' if vault_ok else '❌'} ({note_count} notes)\n"
        f"• {index_stats}\n"
        f"{resolver_line}"
        f"• Memory: ✅\n• Gmail: ✅\n• Research: ✅\n"
        f"• Daily pass: 6am · Weekly: Sundays 8pm\n\n"
        f"_All systems operational._"
    )

async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(
        update.message,
        "🤖 *What Alicia can do*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🧠 *SEARCH & MEMORY*\n"
        "/semanticsearch [query] — search by meaning\n"
        "/searchvault [query] — keyword search\n"
        "/memory — what I remember\n"
        "/remember key | value · /forget key\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🌿 *VAULT INTELLIGENCE*\n"
        "/dailypass — tag notes now\n"
        "/weeklypass — deep pass (Opus)\n"
        "/improve — self-improve skill configs\n"
        "/vaultstats — graph health\n"
        "/reindex — update semantic index\n"
        "/podcast [tension] — generate episode\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔮 *WISDOM*\n"
        "/concept [topic] · /synthesise\n"
        "/contradictions · /ingest [text]\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔬 *RESEARCH*\n"
        "/quick [topic] · /research [topic]\n"
        "/deepresearch [topic] (Opus)\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📬 *EMAIL*\n"
        "/inbox · /financial\n"
        "/sendmail to | subject | body\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📝 *CAPTURE*\n"
        "/note [text] · /log [text] · /dailyquote\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "━━━━━━━━━━━━━━━━\n"
        "📞 *VOICE & THINKING MODES*\n"
        "/call — live voice conversation (Pipecat or voice-note)\n"
        "/endcall — end voice call\n"
        "/unpack [topic] — deep extraction from voice monologue\n"
        "/walk [topic] — stream-of-consciousness walk mode\n"
        "/drive [topic] — 5-min rapid synthesis (vault connections)\n"
        "/done — finish any active session\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🎨 *VISUAL VOICE*\n"
        "/draw — render a drawing from my current archetype weather\n"
        "/draw [phrase] — Haiku interprets the phrase into archetype + knobs\n"
        "/draw [archetype] — force beatrice · daimon · ariadne · psyche · musubi · muse\n"
        "/drawstats — today's drawings + archetype distribution\n"
        "_Drawings also arrive spontaneously ~every 2h, capped at 4/day._\n\n"
        "⚙️ /status · /skills · /archetypes\n\n"
        "💬 *Vault context loads automatically in every conversation.*"
    )

async def cmd_semanticsearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            FORCE_REPLY_PROMPTS["semanticsearch"],
            reply_markup=ForceReply(selective=True, input_field_placeholder="search the vault..."),
        )
        return
    await safe_reply_md(update.message, f"🧠 Searching: _{query}_...")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: semantic_search_formatted(query, n_results=6)
        )
        await safe_reply_md(update.message, result, disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_reindex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("🔄 Updating semantic index...")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: index_vault(False))
        await safe_reply_md(
            update.message,
            f"✅ Index updated\n• New: *{result['indexed']}*\n• Skipped: *{result['skipped']}*\n• Total: *{result['total']}*"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_dailypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("🌿 Running daily tagging pass...")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_daily_tagging_pass)
        await safe_reply_md(update.message, format_daily_report(result), disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_weeklypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(update.message, "🧬 *Running weekly deep pass with Opus...*\n3-5 minutes.")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_weekly_deep_pass)
        report = format_weekly_report(result)
        for chunk in [report[i:i+3500] for i in range(0, len(report), 3500)]:
            await safe_reply_md(update.message, chunk, disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_improve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run the self-improvement engine on demand."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(update.message, "🔧 *Running /improve...*\nReading reflexion episodes, effectiveness data, and trajectories to find skill config improvements.")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_weekly_improve)
        report = format_improve_report(result)
        await safe_reply_md(update.message, report)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Improve error: {e}")

async def cmd_vaultstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("📊 Analysing vault...")
    try:
        stats = await asyncio.get_event_loop().run_in_executor(None, get_vault_stats)
        await update.message.reply_text(stats + f"\n{get_index_stats()}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_podcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    tension = " ".join(context.args)
    if not tension:
        await safe_reply_md(update.message, "Usage: `/podcast [central tension]`")
        return
    await safe_reply_md(update.message, f"🎙 *Generating with Opus...*\n_{tension}_\n\n2-3 minutes.")
    def generate():
        podcast_dir = os.path.join(VAULT_ROOT, "Wisdom/Podcasts")
        os.makedirs(podcast_dir, exist_ok=True)
        existing = [f for f in os.listdir(podcast_dir) if f.endswith(".md") and f.startswith("S02")]
        return generate_podcast_episode(2, len(existing) + 1, tension)
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, generate)
        await safe_reply_md(
            update.message,
            f"🎙 *{result['title']}*\n\n_{result['preview'][:500]}..._\n\n[Open in Obsidian]({result['deep_link']})",
            disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(update.message, get_memory_summary())

async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    args = " ".join(context.args)
    if "|" not in args:
        await safe_reply_md(update.message, "Usage: `/remember key | value`")
        return
    key, value = args.split("|", 1)
    remember_manual(key.strip(), value.strip())
    await safe_reply_md(update.message, f"🧠 Noted — *{key.strip()}*: {value.strip()}")

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    key   = " ".join(context.args).strip()
    found = forget_manual(key)
    await safe_reply_md(
        update.message,
        f"🧹 Forgotten: *{key}*" if found else f"No memory found for *{key}*."
    )

async def cmd_concept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("Usage: /concept [topic]")
        return
    await safe_reply_md(update.message, f"🔮 Developing: *{topic}*...")
    try:
        content, filepath, title = generate_concept_note(topic)
        await safe_reply_md(
            update.message,
            f"💡 *{title}*\n\n{chr(10).join(content.split(chr(10))[:12])}\n\n_Saved to Obsidian_"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_synthesise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("🧬 Scanning vault...")
    try:
        synthesis = await asyncio.get_event_loop().run_in_executor(None, synthesise_vault)
        for chunk in [synthesis[i:i+3500] for i in range(0, len(synthesis), 3500)]:
            await safe_reply_md(update.message, chunk)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_contradictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("⚡ Finding tensions...")
    try:
        await safe_reply_md(update.message, find_contradictions())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_ingest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    text = " ".join(context.args)
    if not text:
        await safe_reply_md(update.message, "Usage: `/ingest [text]`")
        return
    await update.message.reply_text("⚙️ Extracting knowledge...")
    try:
        content, filepath, title = ingest_text(text)
        await safe_reply_md(
            update.message,
            f"📥 *{title}*\n\n{chr(10).join(content.split(chr(10))[:8])}\n\n_Saved to Inbox_"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("Usage: /research [topic]")
        return
    await safe_reply_md(update.message, f"📚 Researching *{topic}*...")
    summary, _ = research_brief(topic)
    await safe_reply_md(update.message, summary)

async def cmd_deepresearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("Usage: /deepresearch [topic]")
        return
    await safe_reply_md(update.message, f"🔬 Deep researching *{topic}* with Opus...")
    summary, _ = research_deep(topic)
    await safe_reply_md(update.message, summary)

async def cmd_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("Usage: /quick [topic]")
        return
    await safe_reply_md(update.message, f"⚡ *{topic}*\n\n{research_quick(topic)}")

async def cmd_searchvault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /searchvault [query]")
        return
    await safe_reply_md(update.message, search_vault_with_links(query), disable_web_page_preview=True)

async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    text = " ".join(context.args)
    if not text:
        # No argument — open the text box with a ForceReply prompt.
        # The reply gets routed back into _save_note_body via the
        # FORCE_REPLY_ROUTER check at the top of handle_message().
        await update.message.reply_text(
            FORCE_REPLY_PROMPTS["note"],
            reply_markup=ForceReply(selective=True, input_field_placeholder="your note..."),
        )
        return
    now = datetime.now()
    write_to_obsidian("Inbox", f"{now.strftime('%Y-%m-%d-%H%M')}-note.md",
                      f"# Quick Note\n**Saved:** {now.strftime('%Y-%m-%d %H:%M')}\n\n{text}\n")
    await update.message.reply_text("📝 Saved to Obsidian Inbox.")

async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /log your entry")
        return
    now = datetime.now()
    write_daily_log(f"# Daily Log — {now.strftime('%Y-%m-%d')}\n**Time:** {now.strftime('%H:%M')}\n\n{text}\n")
    await update.message.reply_text("🌙 Logged to daily journal.")

async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("📬 Fetching inbox...")
    await safe_reply_md(update.message, get_inbox_summary(days=1))

async def cmd_financial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await update.message.reply_text("💰 Scanning financial emails...")
    await safe_reply_md(update.message, summarise_financial_emails(days=7))

async def cmd_sendmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    parts = " ".join(context.args).split("|")
    if len(parts) != 3:
        await safe_reply_md(update.message, "Format: `/sendmail to@email.com | Subject | Body`")
        return
    to, subject, body = [p.strip() for p in parts]
    await safe_reply_md(
        update.message,
        f"🟠 *Confirm?*\nTo: `{to}`\nSubject: `{subject}`\nBody: _{body[:150]}_\n\nReply *YES*"
    )
    context.user_data["pending_email"] = {"to": to, "subject": subject, "body": body}

async def cmd_dailyquote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    await safe_reply_md(update.message, get_random_quote())

async def cmd_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a voice conversation. Uses Pipecat (real-time) if available, else voice-note mode."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    # Check if already in a call or unpack
    if is_call_active() or is_pipecat_call_active():
        await safe_reply_md(update.message, "📞 Already in a call. Send a voice note or /endcall to hang up.")
        return
    if is_unpack_active():
        await safe_reply_md(update.message, "📦 You're in unpack mode. /done to finish first.")
        return

    # Try Pipecat (real-time streaming) first
    if is_pipecat_available():
        try:
            vault_ctx, _ = get_vault_context("conversation context")
            room_url = await start_pipecat_session(vault_context=vault_ctx)
            await safe_reply_md(
                update.message,
                f"📞 *Voice call ready*\n\nJoin from your phone:\n{room_url}\n\n"
                f"_Real-time voice — just talk naturally. /endcall when done._"
            )
            log.info(f"Pipecat call started: {room_url}")
            return
        except Exception as e:
            log.warning(f"Pipecat call failed, falling back to voice-note mode: {e}")

    # Fallback: voice-note conversation mode
    greeting = start_call()
    try:
        voice_path = await text_to_voice(greeting, style="warm")
        with open(voice_path, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        os.remove(voice_path)
    except Exception as ve:
        log.warning(f"Call greeting voice failed: {ve}")
        await safe_reply_md(update.message, f"📞 {greeting}")
    log.info("Voice-note call started via /call")

async def cmd_endcall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End a voice conversation session (Pipecat or voice-note mode)."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    # Try Pipecat first
    if is_pipecat_call_active():
        pipecat_meta = get_pipecat_metadata()
        was_live_unpack = is_live_unpack()
        live_topic = get_live_unpack_topic()
        disable_live_unpack()
        result = await end_pipecat_session()
        if result["was_active"]:
            await safe_reply_md(update.message, f"📞 {result['message']}")
            transcript = get_call_transcript_text()
            if transcript:
                # Enrich transcript with session metadata
                enriched = f"[Pipecat call: {pipecat_meta['duration_seconds']}s, {pipecat_meta['turns']} turns]\n{transcript}"
                threading.Thread(
                    target=lambda: extract_from_message(enriched, is_voice=True),
                    daemon=True,
                ).start()
                # Queue afterglow
                queue_afterglow("call", transcript, topic=live_topic or "voice conversation")
                # Save session thread
                save_session_thread("call", live_topic, transcript, probe_rounds=0)
                # If live unpack was active, also run extraction
                if was_live_unpack:
                    await _run_pipecat_unpack_extraction(update, transcript, live_topic)
            return

    # Fallback: conversation_mode
    call_transcript = get_call_history_text()
    call_meta = get_call_metadata()
    result = end_call()
    if result["was_active"]:
        farewell = result["message"]
        try:
            voice_path = await text_to_voice(farewell, style="gentle")
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            os.remove(voice_path)
        except Exception as ve:
            log.warning(f"Endcall voice failed: {ve}")
        await safe_reply_md(update.message, f"📞 {farewell}")

        # Gap 1 fix: Extract memory from call transcript
        if call_transcript:
            enriched = f"[Call session: {call_meta['duration_seconds']}s, {call_meta['turns']} turns]\n{call_transcript}"
            threading.Thread(
                target=lambda: extract_from_message(enriched, is_voice=True),
                daemon=True,
            ).start()
            # Queue afterglow follow-up
            queue_afterglow("call", call_transcript, topic="voice conversation")
            # Save session thread for cross-session threading
            save_session_thread("call", "", call_transcript, probe_rounds=0)
    else:
        await safe_reply_md(update.message, "No active call.")

async def cmd_unpack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start an unpack session — Alicia listens to voice monologue, then extracts insights."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    if is_unpack_active():
        state = get_unpack_state()
        await safe_reply_md(update.message, f"📦 Already unpacking ({state}). Send voice notes or /done to finish.")
        return
    if is_call_active() or is_pipecat_call_active():
        await safe_reply_md(update.message, "📞 You're in a call. /endcall first.")
        return

    topic = " ".join(context.args) if context.args else ""

    # Cross-session threading: check for related past sessions
    related = find_related_threads(topic=topic)
    thread_msg = build_thread_connection_message(related)

    greeting = start_unpack(topic)

    # Send as voice — sets the tone
    try:
        voice_path = await text_to_voice(greeting, style="warm")
        with open(voice_path, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        os.remove(voice_path)
    except Exception as ve:
        log.warning(f"Unpack greeting voice failed: {ve}")
        await safe_reply_md(update.message, f"📦 {greeting}")

    if thread_msg:
        await safe_reply_md(update.message, f"💭 {thread_msg}")

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish an unpack, walk, or drive session."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    if is_unpack_active():
        await _run_unpack_extraction(update)
        return
    if is_walk_active():
        await _end_walk_session(update)
        return
    if is_drive_active():
        await _end_drive_session(update)
        return

    await safe_reply_md(update.message, "No active session to finish.")


async def cmd_walk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start walk mode — stream-of-consciousness, no interruptions."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    if is_call_active() or is_pipecat_call_active() or is_unpack_active() or is_thinking_mode_active():
        await safe_reply_md(update.message, "Already in an active session. /done to finish first.")
        return

    topic = " ".join(context.args) if context.args else ""

    # Check for related threads (cross-session threading)
    related = find_related_threads(topic=topic)
    thread_msg = build_thread_connection_message(related)

    greeting = start_walk(topic)
    try:
        voice_path = await text_to_voice(greeting, style="warm")
        with open(voice_path, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        os.remove(voice_path)
    except Exception as ve:
        log.warning(f"Walk greeting voice failed: {ve}")
        await safe_reply_md(update.message, f"🚶 {greeting}")

    if thread_msg:
        await safe_reply_md(update.message, f"💭 {thread_msg}")


async def cmd_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drive mode — 5-min rapid synthesis, Alicia throws connections."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return

    if is_call_active() or is_pipecat_call_active() or is_unpack_active() or is_thinking_mode_active():
        await safe_reply_md(update.message, "Already in an active session. /done to finish first.")
        return

    topic = " ".join(context.args) if context.args else ""
    greeting = start_drive(topic)
    await safe_reply_md(update.message, f"🚗 {greeting}")

    # Immediately throw the first vault connection
    await _send_drive_connection(update, topic)


# ── Bridge / Diarize / Scout / Handoff (§2.3 H5, §6.3) ────────────────────────
# These four commands close the gap between Telegram Alicia and Desktop-side
# Alicia. They use bridge_protocol for every read so the path + atomicity +
# schema story is uniform.

@chat_guard
async def cmd_bridge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Summarise the last 7 days of bridge reports.

    Reads `_INDEX.jsonl` via `bridge_protocol.tail_index()` and the markdown
    files via `reports_since()`. Gives the user a quick cross-interface view
    without opening Obsidian.
    """
    try:
        from myalicia.skills.bridge_protocol import reports_since, tail_index
        days_arg = 7
        if context.args:
            try:
                days_arg = max(1, min(30, int(context.args[0])))
            except ValueError:
                pass

        recent = reports_since(days=days_arg, prefix="", suffix=".md")
        index_entries = tail_index(limit=30)

        if not recent and not index_entries:
            await safe_reply_md(update.message, f"🌉 *Bridge* — no activity in last {days_arg} days.")
            return

        lines = [f"🌉 *Bridge — last {days_arg} days*", ""]
        if recent:
            lines.append(f"*{len(recent)} report(s)*")
            for p in recent[:10]:
                age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
                lines.append(f"• `{p.name}` · {age_h:.1f}h ago")
            if len(recent) > 10:
                lines.append(f"… and {len(recent) - 10} more")
        if index_entries:
            lines.append("")
            lines.append("*Recent writes (INDEX):*")
            for entry in index_entries[:8]:
                lines.append(f"• `{entry.get('filename','?')}` · {entry.get('kind','?')} · {entry.get('at','?')}")

        await safe_reply_md(update.message, "\n".join(lines))
    except Exception as e:
        log.warning(f"cmd_bridge failed: {e}")
        await update.message.reply_text(f"⚠️ Bridge read error: {e}")


@chat_guard
async def cmd_diarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """On-demand paired diarization — usually Sunday 20:00 auto, but
    callable any time via /diarize. Writes YYYY-WNN-user.md + -alicia.md
    under Alicia/Self/Profiles/."""
    await safe_reply_md(update.message, "🪞 *Running paired diarization…*\nUsually 20-40s.")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_paired_diarization)
        # run_paired_diarization returns a dict (or raises). Tolerate both shapes.
        if isinstance(result, dict):
            user = result.get("user_path", "?")
            alicia_p = result.get("alicia_path", "?")
            week_id = result.get("week_id", "?")
            delta = result.get("delta_path", "")
            msg = (
                f"✅ *Diarization complete — {week_id}*\n"
                f"• {USER_NAME}: `{os.path.basename(user)}`\n"
                f"• Alicia: `{os.path.basename(alicia_p)}`"
            )
            if delta:
                msg += f"\n• Delta:  `{os.path.basename(delta)}`"
            await safe_reply_md(update.message, msg)
        else:
            await safe_reply_md(update.message, "✅ Diarization complete.")
    except Exception as e:
        log.warning(f"cmd_diarize failed: {e}")
        await update.message.reply_text(f"⚠️ Diarize error: {e}")


@chat_guard
async def cmd_scout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Architecture scout — surface the highest-value structural concern
    without running the full weekly analysis.

    Uses the feedback_loop / analysis_briefing scaffolding to pull the
    latest flagged items and echoes them here so the user gets a single
    signal, not a report dump.
    """
    await safe_reply_md(update.message, "🛰️ *Scouting architecture…*")
    try:
        # Prefer the freshest analytical briefing if present.
        from myalicia.skills.bridge_protocol import get_latest_report, read_bridge_text
        latest = get_latest_report("analytical-briefing", suffix=".md") \
              or get_latest_report("deep-audit", suffix=".md")
        if latest is not None:
            text = read_bridge_text(latest.name, default="")
            head = text[:1800] if text else ""
            await safe_reply_md(
                update.message,
                f"🛰️ *Latest scout signal:* `{latest.name}`\n\n{head}"
            )
            return

        # Fallback: top item from feedback_loop if the module exposes one.
        try:
            from myalicia.skills.feedback_loop import get_top_structural_concern
            concern = get_top_structural_concern() or "No flagged structural concerns."
            await safe_reply_md(update.message, f"🛰️ {concern}")
        except Exception:
            await safe_reply_md(
                update.message,
                "🛰️ No scout signal available. Run /weeklypass to generate one."
            )
    except Exception as e:
        log.warning(f"cmd_scout failed: {e}")
        await update.message.reply_text(f"⚠️ Scout error: {e}")


@chat_guard
async def cmd_handoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read the latest Desktop handoff note as text + voice.

    Bridges from Desktop-side work back into Telegram Alicia's context.
    HANDOFF.md lives at the top of the bridge dir; sessions live under
    desktop-sessions/. We prefer the most recent desktop-session entry,
    falling back to HANDOFF.md if none.
    """
    try:
        from myalicia.skills.bridge_protocol import (
            BRIDGE_DIR, read_bridge_text, list_bridge_reports,
        )
        desktop_dir = BRIDGE_DIR / "desktop-sessions"
        latest_session = None
        if desktop_dir.exists():
            candidates = sorted(
                [p for p in desktop_dir.iterdir() if p.is_file() and p.suffix == ".md"],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            latest_session = candidates[0] if candidates else None

        if latest_session is not None:
            text = latest_session.read_text(encoding="utf-8", errors="replace")
            label = f"desktop-sessions/{latest_session.name}"
        else:
            text = read_bridge_text("HANDOFF.md", default="")
            label = "HANDOFF.md"

        if not text.strip():
            await safe_reply_md(update.message, "🤝 No handoff content available.")
            return

        # Telegram message (first 3000 chars as text)
        preview = text[:3000] + ("\n…(truncated)" if len(text) > 3000 else "")
        await safe_reply_md(update.message, f"🤝 *Handoff — {label}*\n\n{preview}")

        # Voice-read the first ~4000 chars via Gemini TTS chunked.
        try:
            voice_paths = await text_to_voice_chunked(text[:4000], style="measured")
            for vp in voice_paths:
                with open(vp, "rb") as vf:
                    await update.message.reply_voice(voice=vf)
                try:
                    os.remove(vp)
                except OSError:
                    pass
        except Exception as e:
            log.debug(f"cmd_handoff voice skipped: {e}")
    except Exception as e:
        log.warning(f"cmd_handoff failed: {e}")
        await update.message.reply_text(f"⚠️ Handoff error: {e}")


@chat_guard
async def cmd_resolver_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show context-resolver cache + per-module usage stats (§D2).

    Surfaces the hit/miss/skipped ratio, cache occupancy, and the top
    context modules by usage count. Makes the §4.4 caching work visible
    so we can tell whether the resolver is actually earning its keep.
    """
    try:
        from myalicia.skills.context_resolver import (
            get_resolver_cache_stats,
            get_resolver_module_usage,
            RESOLVER_CACHE_TTL,
        )
        stats = get_resolver_cache_stats()
        usage = get_resolver_module_usage()

        total = stats.get("hit", 0) + stats.get("miss", 0) + stats.get("skipped", 0)
        if total > 0:
            hit_pct = 100.0 * stats.get("hit", 0) / total
            miss_pct = 100.0 * stats.get("miss", 0) / total
            skip_pct = 100.0 * stats.get("skipped", 0) / total
        else:
            hit_pct = miss_pct = skip_pct = 0.0

        lines = [
            "🧭 *Resolver Stats*",
            "",
            f"*Cache:* {stats.get('size', 0)}/{stats.get('max', 0)} entries "
            f"(TTL {RESOLVER_CACHE_TTL}s)",
            f"*Calls:* {total} total",
            f"  • Hits    : {stats.get('hit', 0)} ({hit_pct:.1f}%)",
            f"  • Misses  : {stats.get('miss', 0)} ({miss_pct:.1f}%)",
            f"  • Skipped : {stats.get('skipped', 0)} ({skip_pct:.1f}%)",
            "",
        ]
        if usage:
            top = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)[:12]
            lines.append("*Top modules* (by load count):")
            for mod, count in top:
                lines.append(f"  • `{mod}` — {count}")
        else:
            lines.append("_(No module usage recorded yet.)_")

        await safe_reply_md(update.message, "\n".join(lines))
    except Exception as e:
        log.warning(f"cmd_resolver_stats failed: {e}")
        await update.message.reply_text(f"⚠️ Resolver stats error: {e}")


@chat_guard
async def cmd_archetypes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current archetype weights + effectiveness scores (Gap 3).

    Three layers of the archetype selection pipeline:
      1. Final weights — what compute_dynamic_archetype_weights() actually
         uses right now (base × season × engagement × effectiveness, clamped).
      2. Effectiveness scores — the rolling 14-day multiplier per archetype
         driven by reactions. 1.0× means neutral; > 1 means reactions so
         far this window reinforce it; < 1 means reactions discourage it.
      3. Raw attribution counts — how many reactions each archetype has
         logged in the window. Below the min-attributions floor we hold
         at 1.0× to avoid noise driving policy.
    """
    try:
        from myalicia.skills.inner_life import (
            compute_dynamic_archetype_weights,
            get_archetype_effectiveness,
            ARCHETYPE_MIN_ATTRIBUTIONS,
            ARCHETYPE_EMA_HALF_LIFE_DAYS,
            ARCHETYPE_CLAMP_LOW,
            ARCHETYPE_CLAMP_HIGH,
        )

        weights = compute_dynamic_archetype_weights()
        eff = get_archetype_effectiveness() or {}
        eff_map = eff.get("archetypes", {}) if isinstance(eff, dict) else {}

        lines = [
            "🎭 *Archetype Weights*",
            "",
            f"_Clamp [{ARCHETYPE_CLAMP_LOW:.2f}×, {ARCHETYPE_CLAMP_HIGH:.2f}×] · "
            f"half-life {ARCHETYPE_EMA_HALF_LIFE_DAYS}d · "
            f"min attributions {ARCHETYPE_MIN_ATTRIBUTIONS}_",
            "",
            "*Final weights* (what gets picked):",
        ]
        for name, w in sorted(weights.items(), key=lambda kv: -kv[1]):
            lines.append(f"  • {name.capitalize():<10} {int(w*100):>3d}%")

        lines.append("")
        lines.append("*Effectiveness* (reaction-driven multiplier):")
        if eff_map:
            for name in ("beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"):
                info = eff_map.get(name) or {}
                score = info.get("score", 1.0)
                n = info.get("attribution_count", 0)
                held = " _(held — below floor)_" if n < ARCHETYPE_MIN_ATTRIBUTIONS else ""
                lines.append(f"  • {name.capitalize():<10} {score:.2f}×  ({n} reactions){held}")
            window = eff.get("window_days", "?")
            built = eff.get("built_at", "")
            if built:
                lines.append("")
                lines.append(f"_Rebuilt {built[:19]} · window {window}d_")
        else:
            lines.append("  _(No attributions yet — all archetypes at 1.00× until first reactions land.)_")

        await _send_dashboard(update.message, "\n".join(lines), name="archetypes")
    except Exception as e:
        log.warning(f"cmd_archetypes failed: {e}")
        await update.message.reply_text(f"⚠️ Archetype stats error: {e}")


# ── Desktop scheduled-task visibility + on-demand triggers ────────────────────
# /tasks lists every Desktop scheduled task grouped by cadence so the user can
# see the whole fleet from Telegram. Run state (last/next) is owned by Desktop
# and not accessible from alicia.py without an MCP client, so this command
# surfaces what's schedulable; see Desktop UI for live run times.
#
# /briefingnow triggers compile_analytical_briefing() directly (pure Python).
# Agent-based tasks (scout, synthesis, outward-research) need a separate
# Claude Code process, so those aren't exposed as on-demand here — use the
# Desktop task list to trigger them manually.

DESKTOP_SCHEDULED_DIR = os.path.expanduser("~/Documents/Claude/Scheduled")


def _extract_scheduled_task_name(job) -> str:
    """Best-effort extract the display name for a schedule.Job.

    The registration pattern throughout alicia.py is:
        lambda: loop.run_until_complete(safe_run("task_name", fn))

    schedule wraps the lambda in a functools.partial, so we unwrap first.
    The string literal "task_name" lives in the lambda's co_consts. For the
    handful of jobs that don't use safe_run (e.g., check_unpack_silence), we
    fall back to the last referenced name in co_names (which is usually the
    target coroutine). This is why we don't need to touch all 35 registration
    lines to add tags — introspection covers them for free.
    """
    try:
        fn = job.job_func
        # schedule stores job_func as functools.partial — unwrap to get the
        # original lambda so we can inspect its code object.
        import functools as _ft
        while isinstance(fn, _ft.partial):
            fn = fn.func
        code = getattr(fn, "__code__", None)
        if code is None:
            return "(unknown)"
        # Prefer: string constant (safe_run name argument)
        for c in code.co_consts:
            if isinstance(c, str) and c.isidentifier():
                return c
        # Fallback: last non-wrapper name referenced in the lambda body
        skip = {
            "loop", "run_until_complete", "safe_run", "ensure_future",
            "asyncio", "gather", "create_task", "run_coroutine_threadsafe",
        }
        for n in reversed(code.co_names):
            if n not in skip:
                return n
    except Exception:
        pass
    return "(unknown)"


def _describe_python_jobs() -> list[dict]:
    """Enumerate schedule.jobs and return display metadata per job.

    Each dict has keys: name, cadence ('daily'|'weekly'|'interval'|'other'),
    display (human-readable schedule), next_run (datetime or None).
    Cross-thread read of schedule.jobs is safe — the list is built once at
    startup and not mutated at runtime.
    """
    jobs: list[dict] = []
    for job in schedule.jobs:
        name = _extract_scheduled_task_name(job)
        unit = getattr(job, "unit", None)
        interval = getattr(job, "interval", 1)
        start_day = getattr(job, "start_day", None)
        at_time = getattr(job, "at_time", None)

        if unit == "weeks" and start_day:
            day_abbr = start_day[:3].capitalize()
            time_str = at_time.strftime("%H:%M") if at_time else ""
            display = f"{day_abbr} {time_str}".strip()
            cadence = "weekly"
        elif unit == "days" and interval == 1 and at_time:
            display = at_time.strftime("%H:%M")
            cadence = "daily"
        elif unit == "hours":
            display = f"Every {interval}h" if interval > 1 else "Hourly"
            cadence = "interval"
        elif unit == "minutes":
            display = f"Every {interval} min" if interval > 1 else "Every minute"
            cadence = "interval"
        elif unit == "seconds":
            display = f"Every {interval} sec"
            cadence = "interval"
        else:
            display = f"every {interval} {unit}"
            cadence = "other"

        jobs.append({
            "name": name,
            "cadence": cadence,
            "display": display,
            "next_run": getattr(job, "next_run", None),
        })
    return jobs


def _read_desktop_task_descriptions() -> list[tuple[str, str]]:
    """Scan the Desktop Scheduled/ dir and return [(task_id, description)].

    Description is pulled from the first frontmatter block's `description:`
    field. Tasks without a SKILL.md are skipped silently.
    """
    results: list[tuple[str, str]] = []
    if not os.path.isdir(DESKTOP_SCHEDULED_DIR):
        return results
    for name in sorted(os.listdir(DESKTOP_SCHEDULED_DIR)):
        path = os.path.join(DESKTOP_SCHEDULED_DIR, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                body = f.read()
        except OSError:
            continue
        # Parse the first `description:` value we find in any frontmatter block.
        desc = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("description:"):
                desc = stripped.split("description:", 1)[1].strip()
                break
        results.append((name, desc))
    return results


@chat_guard
async def cmd_prosody_cal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current Phase B.2 prosody calibration + optional on-demand rebuild.

    /prosody-cal          → show current calibrated thresholds + defaults
    /prosody-cal rebuild  → run rebuild_prosody_baseline() and report
    """
    try:
        args = context.args or []
        if args and args[0].lower() in ("rebuild", "run", "now"):
            result = rebuild_prosody_baseline()
            status = result.get("status", "?")
            if status == "ok":
                n = result.get("sample_size")
                calibrated = len(result.get("thresholds", {}))
                skipped = len(result.get("skipped", []))
                await safe_reply_md(
                    update.message,
                    f"🎚️ *Prosody rebuild complete*\n"
                    f"• samples: {n}\n"
                    f"• calibrated: {calibrated}\n"
                    f"• defaults standing: {skipped}\n\n"
                    + format_calibration_report()
                )
            else:
                await safe_reply_md(
                    update.message,
                    f"🎚️ *Prosody rebuild:* `{status}` "
                    f"(n={result.get('sample_size', 0)}, "
                    f"need ≥ {result.get('min_samples', 20)})"
                )
            return

        await safe_reply_md(update.message, format_calibration_report())
    except Exception as e:
        log.warning(f"cmd_prosody_cal failed: {e}")
        await update.message.reply_text(f"⚠️ Prosody calibration error: {e}")


@chat_guard
async def cmd_emotion_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Phase C emotion classification distribution over the last N days.

    /emotion-stats        → last 7 days
    /emotion-stats 30     → last 30 days
    """
    try:
        args = context.args or []
        days = 7
        if args:
            try:
                days = max(1, min(365, int(args[0])))
            except ValueError:
                pass
        await safe_reply_md(update.message, format_emotion_stats(days=days))
    except Exception as e:
        log.warning(f"cmd_emotion_stats failed: {e}")
        await update.message.reply_text(f"⚠️ Emotion stats error: {e}")


@chat_guard
async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render an archetype-modulated drawing on demand and send it.

    /draw                       → Alicia's state drives the drawing
    /draw beatrice              → force a specific archetype
    /draw beatrice gif          → force animated GIF output
    /draw <anything else>       → freeform phrase; Haiku picks archetype +
                                  knobs + caption from your words
                                  (e.g. "/draw your current thinking")

    Archetype/gif tokens are extracted; anything remaining becomes the
    freeform prompt. You can combine them: "/draw gif your quiet afternoon"
    forces GIF and passes "your quiet afternoon" to the interpreter.
    """
    try:
        args = context.args or []
        archetype = None
        force_gif = False
        freeform_tokens = []
        for a in args:
            al = a.lower()
            if al in {"beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"}:
                archetype = al
            elif al in {"gif", "animated"}:
                force_gif = True
            else:
                freeform_tokens.append(a)  # preserve case
        prompt = " ".join(freeform_tokens).strip() or None

        await update.message.reply_chat_action("upload_photo")
        # If no explicit archetype AND no freeform prompt, route through
        # state so even a bare /draw reflects Alicia's current weather.
        state = None
        if archetype is None and prompt is None:
            state = build_drawing_state_snapshot()

        # Render in a thread — CPU-bound (~1.3s) + Haiku call (~600ms) — so
        # the asyncio loop stays free.
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: generate_drawing(
                archetype=archetype, force_gif=force_gif,
                prompt=prompt, state=state,
            ),
        )
        await _send_drawing(bot=context.bot, chat_id=update.effective_chat.id,
                            result=result, source_kind="drawing_manual")
        # Manual /draw — logged for stats but does NOT count against the
        # daily cap for Alicia's spontaneous voice. the user asking for a
        # drawing should never starve her own impulse cadence.
        record_drawing_sent(result["path"], result["archetype"],
                            caption=result["caption"], kind=result["kind"],
                            source="manual")
    except Exception as e:
        log.warning(f"cmd_draw failed: {e}")
        await update.message.reply_text(f"⚠️ Drawing error: {e}")


@chat_guard
async def cmd_drawstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show drawing log summary — total, today, archetype distribution."""
    try:
        await _send_dashboard(
            update.message, get_drawing_stats(), name="drawstats",
        )
    except Exception as e:
        log.warning(f"cmd_drawstats failed: {e}")
        await update.message.reply_text(f"⚠️ Drawing stats error: {e}")


@chat_guard
async def cmd_wisdom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compact dashboard of all five Wisdom Engine surfaces — practices,
    contradictions, composer decisions, surfacings, captures. Read-only,
    assembled from data already on disk."""
    try:
        # Phase 16.4 — read-scoping for /wisdom captures section.
        # Default: scope to active conversation. `/wisdom all` → whole-vault.
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")
        scope_to = None
        if sub != "all":
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None
        text = render_wisdom_dashboard(conversation_id=scope_to)
        await _send_dashboard(update.message, text, name="wisdom")
    except Exception as e:
        log.warning(f"cmd_wisdom failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Wisdom dashboard error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_becoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 12 — the user-model evolution + delta tracking. Shows the arc
    between who Alicia thought the user was at baseline and who he's become
    via the accumulated learnings log.

    Subcommands:
      `/becoming`            render dashboard (Phase 16.2: scoped to
                             active conversation by default)
      `/becoming all`        whole-vault view across all conversations
                             (Phase 16.2)
      `/becoming init`       capture a fresh baseline
      `/becoming learn <dim> <claim>`  append a learning manually
                             (Phase 12.1 will auto-extract)"""
    try:
        msg = update.message
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")

        if sub == "init":
            # Manual baseline capture
            try:
                p = init_user_baseline()
                await msg.reply_text(
                    f"📈 Baseline captured → `{p.name}`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                await msg.reply_text(f"⚠️ Baseline init error: {e}")
            return

        if sub == "learn":
            # /becoming learn <dimension> <claim text>
            if len(args) < 3:
                await msg.reply_text(
                    "Usage: `/becoming learn <dimension> <claim>`\n\n"
                    f"Dimensions: {', '.join(USER_DIMENSIONS)}",
                    parse_mode="Markdown",
                )
                return
            dim = args[1].lower()
            claim = " ".join(args[2:]).strip()
            try:
                entry = append_user_learning(
                    claim, dim, confidence=0.8, source="telegram:/becoming",
                )
                await msg.reply_text(
                    f"📈 Learning logged · _{entry['dimension']}_:\n"
                    f"\"{entry['claim'][:120]}\"",
                    parse_mode="Markdown",
                )
            except ValueError as ve:
                await msg.reply_text(
                    f"⚠️ {ve}\n\nDimensions: "
                    f"{', '.join(USER_DIMENSIONS)}"
                )
            except Exception as e:
                await msg.reply_text(f"⚠️ Learn error: {e}")
            return

        # Phase 16.2 — Read-scoping. By default, scope to the active
        # conversation so /becoming from inside `work` shows only
        # work-tagged learnings (provenance becomes lens). `/becoming all`
        # bypasses the scope for the whole-vault view.
        scope_to = None
        if sub == "all":
            scope_to = None  # explicit whole-vault view
        else:
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None  # if conversations module errors, fail open
        text = render_becoming_dashboard(conversation_id=scope_to)
        await _send_dashboard(msg, text, name="becoming")

        # Hint when no baseline exists yet — invite the one-time init
        if get_active_user_baseline() is None:
            await msg.reply_text(
                "_Run `/becoming init` once to capture the current memory "
                "state as the reference frame. Then `/becoming` will show "
                "the delta as learnings accumulate._",
                parse_mode="Markdown",
            )
    except Exception as e:
        log.warning(f"cmd_becoming failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Becoming error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 13.4 — Alicia's developmental trajectory dashboard.

    Where /becoming shows the user's arc, /season shows Alicia's: which
    poetic season she's in, the archetype balance now, what's been
    carrying weight in the last 14 days, and which seasons she's
    already crossed."""
    try:
        text = render_season_dashboard()
        await _send_dashboard(update.message, text, name="season")
    except Exception as e:
        log.warning(f"cmd_season failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Season dashboard error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_metasynthesis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 13.6 — Synthesis-of-syntheses outer loop.

    `/metasynthesis` (no args): list current candidates ranked by capture
    growth. Shows what would be built tonight by the scheduled pass.

    `/metasynthesis run`: build the top candidate now (heavy — Sonnet
    call). Replies with the new synthesis filename when done.

    `/metasynthesis build "<exact title>"`: force-build a specific
    parent. Bypasses cooldown; useful for manually unblocking."""
    try:
        msg = update.message
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")

        if sub == "run":
            await msg.reply_text(
                "🔬 Running meta-synthesis pass… (heavy Sonnet call, ~30-60s)"
            )
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, run_meta_synthesis_pass)
            if result.get("built"):
                child = Path(result["child_path"]).name
                parent = result.get("candidate", "?")
                await msg.reply_text(
                    f"🌱 Meta-synthesis built\n\n"
                    f"*Parent:* {parent}\n"
                    f"*Child:* `{child}`\n"
                    f"*Eligible candidates:* {result.get('candidate_count', 0)}",
                    parse_mode="Markdown",
                )
            else:
                await msg.reply_text(
                    f"_no meta-synthesis built — {result.get('reason')}_",
                    parse_mode="Markdown",
                )
            return

        if sub == "build":
            if len(args) < 2:
                await msg.reply_text(
                    'Usage: `/metasynthesis build "<exact parent title>"`',
                    parse_mode="Markdown",
                )
                return
            title = " ".join(args[1:]).strip().strip('"').strip("'")
            await msg.reply_text(
                f"🔬 Force-building meta-synthesis for:\n_{title}_",
                parse_mode="Markdown",
            )
            loop = asyncio.get_event_loop()
            path = await loop.run_in_executor(
                None, lambda: build_meta_synthesis(title)
            )
            if path:
                await msg.reply_text(
                    f"🌱 Built `{path.name}`",
                    parse_mode="Markdown",
                )
            else:
                await msg.reply_text(
                    "_build failed — check logs (parent not found, "
                    "too few captures, or Sonnet error)_",
                    parse_mode="Markdown",
                )
            return

        # Default: list candidates with level distribution (Phase 13.14).
        cands = candidates_for_meta_synthesis()
        if not cands:
            await msg.reply_text(
                "_No syntheses are ready for meta-synthesis right now._\n\n"
                "A parent needs ≥3 captures referencing it. "
                "Use `/metasynthesis run` once any qualify.",
                parse_mode="Markdown",
            )
            return

        # Phase 13.14 — read each parent's recursion level so we can show
        # the would-be child level + flag the MAX_META_LEVEL cap.
        from myalicia.skills.meta_synthesis import (
            read_synthesis, get_synthesis_level, MAX_META_LEVEL,
        )
        # Bucket by (would-be level), then render. Level 1 = first meta,
        # level 2 = meta-meta, level 3 = meta-meta-meta. Above cap = blocked.
        buckets: dict[int, list[dict]] = {}
        blocked: list[dict] = []
        for c in cands[:12]:
            try:
                parent_level = get_synthesis_level(
                    read_synthesis(Path(c["synthesis_path"]))
                )
            except Exception:
                parent_level = 0
            target_level = parent_level + 1
            if target_level > MAX_META_LEVEL:
                blocked.append(c)
            else:
                buckets.setdefault(target_level, []).append(c)

        lines = ["🔬 *Meta-synthesis candidates*\n"]
        for lvl in sorted(buckets.keys()):
            label = "Level 1 (first meta)" if lvl == 1 else \
                    f"Level {lvl} (meta-meta{'-meta' * (lvl - 2)})"
            lines.append(f"*{label}* — {len(buckets[lvl])} candidate(s)")
            for c in buckets[lvl][:5]:
                tag = "fresh" if c.get("last_meta_at") is None \
                    else f"+{c['delta']} since last"
                lines.append(
                    f"  • {c['title'][:70]} — {c['capture_count']} captures "
                    f"_({tag})_"
                )
            lines.append("")
        if blocked:
            lines.append(
                f"⛔ *At MAX_META_LEVEL ({MAX_META_LEVEL}) — won't recurse:*"
            )
            for c in blocked[:3]:
                lines.append(f"  • {c['title'][:70]}")
            lines.append("")
        lines.append(
            f"_Top candidate would build tonight at 02:30, "
            f"or run `/metasynthesis run` to build now._"
        )
        await _send_dashboard(msg, "\n".join(lines), name="metasynthesis")
    except Exception as e:
        log.warning(f"cmd_metasynthesis failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Meta-synthesis error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_multichannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 13.8 — Multi-channel observability dashboard.

    Reads memory/multi_channel_decisions.jsonl and renders last-24h
    fire/skip rates by channel + path, top skip reasons, saturation
    status, and recent fired/skipped examples. Lets us see whether
    the smart deciders (Phase 13.3 drawing + Phase 13.7 voice) are
    actually doing what we want."""
    try:
        text = render_multichannel_dashboard()
        await _send_dashboard(update.message, text, name="multichannel")
    except Exception as e:
        log.warning(f"cmd_multichannel failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Multichannel error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_loops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 14.0 — The /loops meta-dashboard.

    Where /wisdom shows circulation surfaces and /multichannel shows
    smart-decider observability, /loops shows the four CLOSED LOOPS
    that connect everything into one circulatory system:
      1. Inner reply (Phase 11)
      2. Meta-synthesis (Phase 13.6 + 13.10)
      3. Gap-driven outbound (Phase 12 + 12.4)
      4. Thread-pull (Phase 13.5 + 13.11)
    Plus cross-loop signal counts proving the loops are stitched, not
    parallel."""
    try:
        text = render_loops_dashboard()
        await _send_dashboard(update.message, text, name="loops")
    except Exception as e:
        log.warning(f"cmd_loops failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Loops error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 16.1 — Multi-conversation routing.

    `/conversation` (no args)        → show current + list registry
    `/conversation switch <id>`      → set the active conversation
    `/conversation create <id> <label>` → register a new conversation
    `/conversation remove <id>`      → delete (default protected)

    Behavior change from Phase 16.0: every new write now tags with the
    active conversation. Reads are NOT yet scoped — dashboards still
    show everything regardless of which conversation is active. The
    tag is provenance, not a silo."""
    try:
        from myalicia.skills.conversations import (
            current_conversation_id,
            list_conversations,
            set_active_conversation,
            add_conversation,
            remove_conversation,
            get_conversation_meta,
            DEFAULT_CONVERSATION_ID,
        )
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")

        if sub == "switch":
            if len(args) < 2:
                await safe_reply_md(
                    update.message,
                    "Usage: `/conversation switch <id>`\n"
                    "See `/conversation` for available ids.",
                )
                return
            target = args[1].strip()
            ok = set_active_conversation(target)
            if not ok:
                await safe_reply_md(
                    update.message,
                    f"⚠️ `{target}` isn't in the registry. "
                    f"Use `/conversation` to see available ids, or "
                    f"`/conversation create {target} <label>` to register it.",
                )
                return
            meta = get_conversation_meta(target) or {}
            await safe_reply_md(
                update.message,
                f"🪧 Switched to *{meta.get('label') or target}* "
                f"(`{target}`).\n"
                f"_{meta.get('description') or ''}_\n\n"
                f"Every write from now on tags with this conversation. "
                f"Reads still see everything.",
            )
            return

        if sub == "create":
            if len(args) < 2:
                await safe_reply_md(
                    update.message,
                    "Usage: `/conversation create <id> [<label> [— <description>]]`\n"
                    "Example: `/conversation create work work-Alicia — Professional context`",
                )
                return
            target = args[1].strip()
            rest = " ".join(args[2:]).strip()
            label, description = rest, ""
            if "—" in rest:
                label, description = [p.strip() for p in rest.split("—", 1)]
            elif " - " in rest:
                label, description = [p.strip() for p in rest.split(" - ", 1)]
            ok = add_conversation(target, label=label, description=description)
            if not ok:
                await safe_reply_md(
                    update.message,
                    f"⚠️ Couldn't register `{target}`. "
                    f"Either the id already exists or it has invalid characters "
                    f"(allowed: alphanumeric + `-` + `_`).",
                )
                return
            await safe_reply_md(
                update.message,
                f"🆕 Conversation registered: *{label or target}* (`{target}`).\n"
                f"Use `/conversation switch {target}` to start tagging writes.",
            )
            return

        if sub == "remove":
            if len(args) < 2:
                await safe_reply_md(
                    update.message,
                    "Usage: `/conversation remove <id>`",
                )
                return
            target = args[1].strip()
            if target == DEFAULT_CONVERSATION_ID:
                await safe_reply_md(
                    update.message,
                    "⚠️ The `default` conversation is protected — can't be removed.",
                )
                return
            ok = remove_conversation(target)
            if not ok:
                await safe_reply_md(
                    update.message,
                    f"⚠️ `{target}` not found in the registry.",
                )
                return
            await safe_reply_md(
                update.message,
                f"🗑 Removed `{target}`. "
                f"If it was active, the default conversation is now active.",
            )
            return

        # Default: show current + full registry
        active = current_conversation_id()
        registry = list_conversations()
        lines = [
            "🪧 *Conversation routing* (Phase 16.1)",
            "",
            f"*Active:* `{active}`",
            "",
            "*Registry:*",
        ]
        for c in registry:
            cid = c.get("id", "?")
            label = c.get("label", cid)
            desc = c.get("description", "")
            marker = "▶︎ " if cid == active else "  "
            lines.append(f"{marker}`{cid}` — _{label}_")
            if desc:
                lines.append(f"    {desc}")
        lines.append("")
        lines.append(
            "_Subcommands:_ `switch <id>` · `create <id> <label> — <desc>` · `remove <id>`"
        )
        await safe_reply_md(update.message, "\n".join(lines))
    except Exception as e:
        log.warning(f"cmd_conversation failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Conversation error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_retro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 20.0 — Sunday self-portrait.

    Reads (or builds) Alicia's weekly portrait of the user. Pulls from
    mood-of-the-week (19.0), dashboard engagement (17.8), noticings
    (17.0), becoming arc (12), and captures. Sonnet-composed in
    Beatrice's voice. Lands in writing/Wisdom/Lived/ as a Tier-3 note.

    Phase 20.1 args:
        /retro              → most-recent portrait (or build fresh if old)
        /retro all          → index of every portrait archived
        /retro 2026-04-19   → portrait for the week containing that date

    Phase 22.0 args:
        /retro <free-text question>  → Sonnet Q&A over this week's signals
                                       (witness-voice answer, not archived)

    Default scope: active conversation. Use `/retro all` to bypass.
    """
    try:
        from myalicia.skills.weekly_self_portrait import render_retro_for_telegram
        args = list(context.args) if context.args else []
        first = (args[0].lower() if args else "")
        target_date = None
        show_all = False
        scope_to = None
        free_text_question = None
        span_days = None
        # Reconstruct the raw arg string (preserves case + punctuation)
        raw_args_full = (
            update.message.text.split(maxsplit=1)[1]
            if (update.message and update.message.text and
                len(update.message.text.split(maxsplit=1)) > 1)
            else " ".join(args)
        ).strip()
        # Phase 24.5 — `/retro <conversation_id>` builds a per-conversation
        # portrait. Detect AFTER 'all' but BEFORE span/date/Q&A.
        retro_conversation = None
        if first and first != "all":
            try:
                from myalicia.skills.conversations import (
                    list_conversations, DEFAULT_CONVERSATION_ID,
                )
                known_ids = {
                    c.get("id") for c in (list_conversations() or [])
                }
                # Don't treat "default" as a per-conversation request —
                # that's the aggregate, same as no-arg
                if first in known_ids and first != DEFAULT_CONVERSATION_ID:
                    retro_conversation = first
            except Exception:
                retro_conversation = None
        if first == "all":
            show_all = True
        elif retro_conversation:
            # Phase 24.5 — explicit per-conversation portrait build
            pass  # handled below
        elif first:
            # Phase 23.0 — Try multi-week span first
            from myalicia.skills.weekly_self_portrait import parse_retro_span_arg
            span_days = parse_retro_span_arg(raw_args_full)
            # If no span, try YYYY-MM-DD historical
            parsed_date = False
            if not span_days:
                try:
                    datetime.strptime(first, "%Y-%m-%d")
                    target_date = first
                    parsed_date = True
                except Exception:
                    pass
            if not span_days and not parsed_date:
                # Phase 22.0 — treat as a free-text question. Reconstruct
                # from raw text to preserve case + punctuation that the
                # lowercase `first` lost.
                raw_args = (
                    update.message.text.split(maxsplit=1)[1]
                    if (update.message and update.message.text and
                        len(update.message.text.split(maxsplit=1)) > 1)
                    else " ".join(args)
                )
                free_text_question = raw_args.strip()
            # Phase 20.1 — default: scope to active conversation
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None
        else:
            # Phase 20.1 — no args, default scope
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None

        # Phase 24.5 — per-conversation portrait build
        if retro_conversation:
            from myalicia.skills.weekly_self_portrait import build_weekly_self_portrait
            await safe_reply_md(
                update.message,
                f"🪞 _composing — `{retro_conversation}` portrait_",
            )
            loop = asyncio.get_event_loop()
            entry = await loop.run_in_executor(
                None,
                lambda: build_weekly_self_portrait(
                    force=True, conversation_id=retro_conversation,
                ),
            )
            if not entry or not entry.get("body"):
                await safe_reply_md(
                    update.message,
                    f"🪞 _Couldn't compose `{retro_conversation}` portrait — "
                    f"too few signals or composer error._",
                )
                return
            text = (
                f"🪞 *Self-portrait — `{retro_conversation}`*\n\n"
                + entry["body"]
            )
            await _send_dashboard(update.message, text, name="retro")
            return

        # Phase 23.0 — multi-week span path
        if span_days:
            from myalicia.skills.weekly_self_portrait import render_retro_span
            await safe_reply_md(
                update.message,
                f"🪞 _composing — last {span_days} days_",
            )
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None,
                lambda: render_retro_span(days=span_days),
            )
            await _send_dashboard(update.message, text, name="retro")
            return

        # Phase 22.0 — free-text Q&A path
        if free_text_question:
            from myalicia.skills.weekly_self_portrait import answer_retro_question
            await safe_reply_md(
                update.message,
                f"🪞 _thinking — {free_text_question[:80]}_",
            )
            loop = asyncio.get_event_loop()
            answer = await loop.run_in_executor(
                None,
                lambda: answer_retro_question(
                    free_text_question, conversation_id=scope_to,
                ),
            )
            if not answer:
                await safe_reply_md(
                    update.message,
                    "🪞 _Couldn't answer — composer error or no signal._",
                )
                return
            text = (
                f"🪞 *Retro — {free_text_question[:120]}*\n\n{answer}"
            )
            await _send_dashboard(update.message, text, name="retro")
            return

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: render_retro_for_telegram(
                target_date=target_date,
                show_all=show_all,
                conversation_id=scope_to,
            ),
        )
        sent_retro = await _send_dashboard(update.message, text, name="retro")

        # Phase 24.0 — Track this portrait's message_id so a native
        # Telegram reply lands as `kind=portrait_response` (audit gap:
        # only Sunday send was tracking before; /retro views weren't).
        # Skip on /retro all (index, not a portrait body).
        if (not show_all and sent_retro is not None and
                hasattr(sent_retro, "message_id")):
            try:
                from myalicia.skills.weekly_self_portrait import (
                    get_latest_self_portrait, get_self_portrait_for_date,
                    track_portrait_message_id,
                )
                if target_date:
                    portrait_for_track = get_self_portrait_for_date(
                        target_date, conversation_id=scope_to,
                    )
                else:
                    portrait_for_track = get_latest_self_portrait()
                if portrait_for_track:
                    track_portrait_message_id(
                        int(sent_retro.message_id),
                        portrait_ts=portrait_for_track.get("ts"),
                        vault_path=portrait_for_track.get("vault_path"),
                    )
            except Exception as te:
                log.debug(f"track_portrait_message_id (/retro) skip: {te}")

        # Phase 21.0 — voice-render for the body view (skip on /retro all
        # because the index isn't a flowing portrait). Pulls the cached
        # clip when present; renders fresh otherwise.
        if not show_all:
            try:
                from myalicia.skills.weekly_self_portrait import (
                    get_latest_self_portrait, get_self_portrait_for_date,
                    pick_portrait_voice_style, get_cached_portrait_voice,
                    cache_portrait_voice,
                )
                if target_date:
                    portrait = get_self_portrait_for_date(
                        target_date, conversation_id=scope_to,
                    )
                else:
                    portrait = get_latest_self_portrait()
                if portrait and portrait.get("body"):
                    body = portrait["body"]
                    style = pick_portrait_voice_style(portrait.get("signals"))
                    cache_hit = False
                    voice_path = get_cached_portrait_voice(body, style=style)
                    if voice_path:
                        cache_hit = True
                    else:
                        voice_path = await text_to_voice(body, style=style)
                        try:
                            cache_portrait_voice(body, voice_path, style=style)
                        except Exception:
                            pass
                    with open(voice_path, "rb") as vf:
                        await update.message.reply_voice(voice=vf)
                    if not cache_hit:
                        try:
                            os.remove(voice_path)
                        except Exception:
                            pass
            except Exception as ve:
                log.debug(f"/retro voice render skip: {ve}")
    except Exception as e:
        log.warning(f"cmd_retro failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Retro error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_noticings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 17.2 — The /noticings command.

    Surfaces every emergent theme Alicia has been quietly tracking across
    the recent stream (captures + learnings + meta-syntheses). Shows
    pending themes that haven't surfaced yet, themes that ARE on cooldown
    after surfacing, and themes the user has already acknowledged. The
    nightly 04:00 scan populates this; the midday rotation picks from
    'pending' with recurrence ≥3."""
    try:
        from myalicia.skills.emergent_themes import render_noticings_for_telegram
        # Phase 16.3 — read-scoping for noticings. Default to active
        # conversation; `/noticings all` for whole-vault.
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")
        scope_to = None
        if sub != "all":
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None
        text = render_noticings_for_telegram(conversation_id=scope_to)
        await _send_dashboard(update.message, text, name="noticings")
    except Exception as e:
        log.warning(f"cmd_noticings failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Noticings error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_effectiveness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sibling to /wisdom — feedback-signal dashboard. Reactions tally,
    archetype effectiveness EMA, voice tone, emotion classifications, and
    proactive engagement rate (last-N composer sends with replies within
    30 min — the metric Phase 11.7 unlocked). Read-only, assembled from
    data already on disk."""
    try:
        # Phase 16.4 — surface the active conversation in the banner.
        # Underlying TSV is still whole-vault (Phase 16.5 will tag it)
        # but the banner makes the ambiguity explicit.
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "")
        scope_to = None
        if sub != "all":
            try:
                from myalicia.skills.conversations import current_conversation_id
                scope_to = current_conversation_id()
            except Exception:
                scope_to = None
        text = render_effectiveness_dashboard(conversation_id=scope_to)
        await _send_dashboard(update.message, text, name="effectiveness")
    except Exception as e:
        log.warning(f"cmd_effectiveness failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Effectiveness dashboard error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_practice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Self-serve practice management from Telegram (Phase 11.11).

    Subcommands:
      /practice                       — list active practices + status
      /practice list                  — alias for the above
      /practice log <slug> <text>     — append an attempt to a practice's log
      /practice close <slug>          — close a practice and emit the Lived note
      /practice scaffold <slug> | <title> | <synthesis-title> | <archetype> | <instrument>
                                      — start a new practice. The pipe-
                                        separated form keeps it parseable
                                        without nested escaping.
    """
    try:
        msg = update.message
        args = list(context.args) if context.args else []
        sub = (args[0].lower() if args else "list")

        # ── List ────────────────────────────────────────────────────────────
        if sub in ("", "list"):
            try:
                practices = list_active_practices()
            except Exception as e:
                await msg.reply_text(f"⚠️ Could not load practices: {e}")
                return
            if not practices:
                await msg.reply_text(
                    f"📓 No active practices ({0}/{MAX_ACTIVE_PRACTICES}).\n\n"
                    f"Start one with `/practice scaffold <slug> | <title> | "
                    f"<synthesis-title> | <archetype> | <instrument>`",
                    parse_mode="Markdown",
                )
                return
            now_utc = datetime.now(timezone.utc)
            lines = [f"📓 *Active practices ({len(practices)}/{MAX_ACTIVE_PRACTICES}):*", ""]
            for p in practices:
                days = practice_days_since(p.started_at, now_utc)
                future = [d for d in CHECK_IN_DAYS if d > days]
                next_str = f"day {future[0]}" if future else "closeout"
                lines.append(
                    f"• `{p.slug}` · {p.archetype} · day {days}, next: {next_str}"
                )
                lines.append(f"   _{p.title[:80]}_")
            lines.append("")
            lines.append(
                "Use `/practice log <slug> <attempt>` to record an attempt, "
                "or `/practice close <slug>` to close one."
            )
            await safe_reply_md(msg, "\n".join(lines))
            return

        # ── Log ─────────────────────────────────────────────────────────────
        if sub == "log":
            if len(args) < 3:
                await msg.reply_text(
                    "Usage: `/practice log <slug> <attempt text>`",
                    parse_mode="Markdown",
                )
                return
            slug = args[1]
            text = " ".join(args[2:]).strip()
            if not text:
                await msg.reply_text("⚠️ Attempt text is empty.")
                return
            try:
                path = practice_record_log_entry(slug, text)
                await msg.reply_text(
                    f"📓 Logged to `{slug}` → {path.name}",
                    parse_mode="Markdown",
                )
            except FileNotFoundError:
                await msg.reply_text(f"⚠️ Unknown practice slug: `{slug}`",
                                     parse_mode="Markdown")
            except Exception as e:
                await msg.reply_text(f"⚠️ Log error: {e}")
            return

        # ── Close ───────────────────────────────────────────────────────────
        if sub == "close":
            if len(args) < 2:
                await msg.reply_text(
                    "Usage: `/practice close <slug>`",
                    parse_mode="Markdown",
                )
                return
            slug = args[1]
            try:
                lived_path = runner_close_practice(slug)
                await msg.reply_text(
                    f"🪞 Closed `{slug}`. Lived note → {lived_path.name}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                await msg.reply_text(f"⚠️ Close error: {e}")
            return

        # ── Scaffold ────────────────────────────────────────────────────────
        if sub == "scaffold":
            # Reconstruct the full args string and split on " | "
            raw = " ".join(args[1:]).strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) < 5:
                await msg.reply_text(
                    "Usage: `/practice scaffold <slug> | <title> | "
                    "<synthesis-title> | <archetype> | <instrument>`\n\n"
                    "Pipe-separated. Example:\n"
                    "`/practice scaffold daily-letter | Daily letter to my "
                    "future self | The questions you carry are not waiting "
                    "for answers | Beatrice | One short letter per evening`",
                    parse_mode="Markdown",
                )
                return
            slug, title, syn_title, archetype, instrument = parts[:5]
            try:
                p = promote_synthesis_to_practice(
                    slug=slug, title=title,
                    synthesis_title=syn_title, synthesis_path="",
                    instrument=instrument, archetype=archetype,
                )
                await msg.reply_text(
                    f"📓 Scaffolded `{p.slug}` · {p.archetype}\n"
                    f"_{p.title}_\n\n"
                    f"Descends from: {p.synthesis_title}\n"
                    f"First check-in: day 3 ({p.started_at})",
                    parse_mode="Markdown",
                )
            except Exception as e:
                await msg.reply_text(f"⚠️ Scaffold error: {e}")
            return

        # ── Unknown sub ─────────────────────────────────────────────────────
        await msg.reply_text(
            "Unknown subcommand. Use one of:\n"
            "`/practice list`\n"
            "`/practice log <slug> <text>`\n"
            "`/practice close <slug>`\n"
            "`/practice scaffold <slug> | <title> | <synthesis-title> | "
            "<archetype> | <instrument>`",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning(f"cmd_practice failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Practice error: {e}")
        except Exception:
            pass


@chat_guard
async def cmd_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Archive a substantive the user-initiated thought as Tier-3 writing.

    Three modes (in priority order):
      1. `/capture` as a reply to one of Alicia's messages → captures the
         message being replied to as the prompt + the user's command-args
         (or a follow-up Reply, if no args) as the response. Routes
         through writing/Responses/.
      2. `/capture <text>` with inline text → captures the text as a
         standalone unprompted thought. Lands in writing/Captures/.
      3. `/capture` with no args and no reply target → ForceReply asking
         what to capture.
    """
    try:
        msg = update.message
        # Args after the command. context.args is the tokenized args list.
        args_text = " ".join(context.args).strip() if context.args else ""

        # Path 1: reply-to-Alicia → route through Responses/
        rtm = getattr(msg, "reply_to_message", None)
        if rtm and getattr(rtm, "from_user", None) and rtm.from_user.is_bot:
            prompt = (rtm.text or rtm.caption or "").strip()
            if not args_text:
                await msg.reply_text(
                    "Reply to my message with the text you want captured "
                    "after `/capture`, or use `/capture <text>`.",
                )
                return
            out = capture_response_if_responsive(
                args_text,
                channel="text",
                direct_prompt=prompt,
                direct_prompt_telegram_id=rtm.message_id,
            )
            if out:
                await msg.reply_text(
                    f"📝 Captured as response → `{out.name}`",
                    parse_mode="Markdown",
                )
            else:
                await msg.reply_text("⚠️ Capture skipped (empty text).")
            return

        # Path 2: inline text → unprompted Captures/
        if args_text:
            out = capture_unprompted_response(args_text, channel="text")
            await msg.reply_text(
                f"📝 Captured to vault → `{out.name}`",
                parse_mode="Markdown",
            )
            return

        # Path 3: no args, no reply target → coach the user
        await msg.reply_text(
            "Use `/capture <thought>` to archive a substantive thought as "
            "writing/Captures/, or reply to one of my messages with "
            "`/capture <your reply>` to archive it as writing/Responses/.",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning(f"cmd_capture failed: {e}")
        try:
            await update.message.reply_text(f"⚠️ Capture error: {e}")
        except Exception:
            pass


# ── Drawing inline-button registry ──────────────────────────────────────────
# When _send_drawing posts a drawing, it registers context here under a
# short id and attaches inline buttons whose callback_data references that
# id. Bounded LRU — old entries fall off after _DRAWING_CTX_MAX drawings,
# at which point the buttons stop responding (handled gracefully).

from collections import OrderedDict as _OrderedDict
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle
_DRAWING_CTX: "_OrderedDict[str, dict]" = _OrderedDict()
_DRAWING_CTX_MAX = 200

_ARCHETYPES = ["beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"]

def _register_drawing_ctx(result: dict) -> str:
    """Stash the result for later button callbacks. Returns a 10-char id."""
    import uuid
    did = uuid.uuid4().hex[:10]
    _DRAWING_CTX[did] = {
        "path":      str(result.get("path", "")),
        "archetype": (result.get("archetype") or "").lower(),
        "caption":   result.get("caption", "") or "",
        "kind":      result.get("kind", "png"),
    }
    while len(_DRAWING_CTX) > _DRAWING_CTX_MAX:
        _DRAWING_CTX.popitem(last=False)
    return did

def _drawing_keyboard(did: str) -> InlineKeyboardMarkup:
    """Default 4-button keyboard under every drawing."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♻️ Regenerate",         callback_data=f"draw:regen:{did}"),
            InlineKeyboardButton("🎭 Different archetype", callback_data=f"draw:arch:{did}"),
        ],
        [
            InlineKeyboardButton("💾 Save to vault",       callback_data=f"draw:save:{did}"),
            InlineKeyboardButton("📓 Title it",            callback_data=f"draw:title:{did}"),
        ],
    ])

def _archetype_picker_keyboard(did: str) -> InlineKeyboardMarkup:
    """Sub-keyboard shown after tapping 'Different archetype'."""
    rows = []
    for i in range(0, len(_ARCHETYPES), 3):
        rows.append([
            InlineKeyboardButton(
                a.title(),
                callback_data=f"draw:archpick:{did}:{a}",
            ) for a in _ARCHETYPES[i:i+3]
        ])
    rows.append([InlineKeyboardButton("← Back", callback_data=f"draw:back:{did}")])
    return InlineKeyboardMarkup(rows)

# Sentinel prompt for the "Title it" ForceReply flow. Encodes the drawing
# id so the router in handle_message can find the right ctx on reply.
_DRAWING_TITLE_PROMPT_PREFIX = "📓 What's the title for this drawing? (id:"

# ── Unpack inline-button registry ───────────────────────────────────────────
_UNPACK_CTX: "_OrderedDict[str, dict]" = _OrderedDict()
_UNPACK_CTX_MAX = 50

def _register_unpack_ctx(filepath: str, topic: str = "") -> str:
    import uuid
    uid = uuid.uuid4().hex[:10]
    _UNPACK_CTX[uid] = {"path": filepath, "topic": topic}
    while len(_UNPACK_CTX) > _UNPACK_CTX_MAX:
        _UNPACK_CTX.popitem(last=False)
    return uid

def _unpack_keyboard(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📌 Pin",     callback_data=f"unpack:pin:{uid}"),
        InlineKeyboardButton("🔗 Connect", callback_data=f"unpack:connect:{uid}"),
        InlineKeyboardButton("➕ Tag",     callback_data=f"unpack:tag:{uid}"),
    ]])

_UNPACK_CONNECT_PROMPT_PREFIX = "🔗 Connect this unpack to which note or topic? (id:"
_UNPACK_TAG_PROMPT_PREFIX     = "➕ Tags for this unpack? (id:"

# ── Why-this? reasoning-trace registry ──────────────────────────────────────
# Every Alicia reply from handle_message gets a [🤔 Why this?] button whose
# callback_data references a trace captured at reply time. The trace is a
# snapshot of what went into the answer: model, confidence, tools, vault
# sources, security level. Bounded LRU — old buttons degrade gracefully.
_WHY_TRACES: "_OrderedDict[str, dict]" = _OrderedDict()
_WHY_TRACES_MAX = 300

def _register_why_trace(trace: dict) -> str:
    import uuid
    wid = uuid.uuid4().hex[:10]
    _WHY_TRACES[wid] = trace
    while len(_WHY_TRACES) > _WHY_TRACES_MAX:
        _WHY_TRACES.popitem(last=False)
    return wid

def _why_keyboard(wid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🤔 Why this?", callback_data=f"why:{wid}"),
    ]])

def _format_why_trace(trace: dict) -> str:
    """Render a reasoning trace as a readable Telegram message."""
    lines = ["🤔 *Why this reply*", ""]
    model = trace.get("model") or "?"
    escalated = trace.get("escalated_to_opus")
    lines.append(f"🤖 *Model:* {model}" + (" _(escalated from Sonnet)_" if escalated else ""))

    conf = trace.get("confidence")
    if conf is not None:
        try:
            lines.append(f"📊 *Confidence:* {float(conf):.2f}")
        except Exception:
            lines.append(f"📊 *Confidence:* {conf}")
    cr = trace.get("confidence_reason")
    if cr:
        lines.append(f"    _{cr[:240]}_")

    tools = trace.get("tools_used") or []
    if tools:
        lines.append(f"🔧 *Tools:* {', '.join(tools)}")
    else:
        lines.append("🔧 *Tools:* none (direct answer)")

    sources = trace.get("vault_sources") or []
    if sources:
        lines.append("📎 *Vault sources:*")
        for s in sources[:6]:
            lines.append(f"  · {s}")

    sec = trace.get("sec_level")
    if sec is not None and sec >= 2:
        lines.append(f"🔒 *Security level:* L{sec}")

    ctx_msgs = trace.get("context_msgs")
    if ctx_msgs is not None:
        lines.append(f"💭 *Conversation context:* {ctx_msgs} messages")

    mem_hits = trace.get("memory_hits")
    if mem_hits:
        lines.append(f"🧠 *Memory pulled:* {mem_hits}")

    return "\n".join(lines)

async def _save_drawing_to_vault(ctx: dict, title: str | None = None) -> str:
    """Copy a drawing into the Obsidian vault. Returns the relative vault path."""
    from pathlib import Path
    import shutil
    src = Path(ctx["path"])
    if not src.exists():
        raise FileNotFoundError(f"drawing file gone: {src}")
    vault_dir = Path(VAULT_ROOT) / "Alicia" / "Drawings"
    vault_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    arch = ctx["archetype"] or "drawing"
    if title:
        slug = "".join(c if c.isalnum() or c in "- " else "" for c in title).strip().replace(" ", "-").lower()[:60] or arch
    else:
        slug = arch
    dst = vault_dir / f"{ts}-{slug}{src.suffix}"
    shutil.copy2(src, dst)
    # Append a line to the daily index note so saved drawings are
    # browsable as a vault page, not just loose files.
    index = vault_dir / f"{datetime.now().strftime('%Y-%m-%d')}-saved.md"
    line = f"- ![[{dst.name}]] — *{ctx['archetype']}* — {title or ctx['caption']}\n"
    with open(index, "a", encoding="utf-8") as f:
        f.write(line)
    return f"Drawings/{dst.name}"

async def _send_drawing(
    bot, chat_id: int, result: dict, *,
    source_kind: str = "drawing_impulse",
) -> None:
    """Send a drawing (PNG or GIF) to Telegram with its caption.

    Shared helper used by /draw and send_drawing_impulse.

    Registers the sent message with reaction_scorer.track_reply so that when
    the user reacts with an emoji, reaction_scorer.score_reply_by_reaction can
    find this send by message_id and feed the archetype into
    log_archetype_attribution → Gap 3 archetype-effectiveness weights.
    Without this step, drawing reactions would be invisible to the learning
    loop (drawing_skill.md Evaluation Criteria depends on this).

    Phase 13.0 — drawings now also write a fresh circulation_log entry
    (channel=drawing, source_kind=drawing_impulse|drawing_manual|...) so
    they appear in /wisdom and /effectiveness engagement-rate metrics, and
    so response_capture can link replies to them via proactive_decision_id.
    """
    path = result["path"]
    caption = result.get("caption", "").strip()
    kind = result.get("kind", "png")
    archetype = (result.get("archetype") or "").strip()
    # Register for inline-button callbacks before sending so the keyboard
    # is wired the moment the drawing arrives in the chat.
    did = _register_drawing_ctx(result)
    keyboard = _drawing_keyboard(did)
    sent_msg = None
    try:
        with open(path, "rb") as f:
            if kind == "gif":
                sent_msg = await bot.send_animation(
                    chat_id=chat_id, animation=f,
                    caption=caption if caption else None,
                    reply_markup=keyboard,
                )
            else:
                sent_msg = await bot.send_photo(
                    chat_id=chat_id, photo=f,
                    caption=caption if caption else None,
                    reply_markup=keyboard,
                )
    except Exception as e:
        log.warning(f"_send_drawing failed: {e}")
        # Fallback — text only so the moment isn't lost
        if caption:
            try:
                sent_msg = await bot.send_message(
                    chat_id=chat_id, text=f"🎨 (drawing: {caption})"
                )
            except Exception:
                pass

    # Register for reaction-based archetype attribution (Gap 1 + Gap 3).
    # episode_path="" — drawings have no reflexion episode; archetype is
    # what matters for the feedback loop.
    if sent_msg is not None and getattr(sent_msg, "message_id", None) is not None:
        try:
            track_reply_for_reaction(
                message_id=sent_msg.message_id,
                episode_path="",
                task_type="drawing",
                archetype=archetype,
                query_excerpt=caption[:160],
            )
        except Exception as te:
            log.debug(f"drawing track_reply skip: {te}")

        # Phase 13.0 — record into circulation_log so the drawing is a
        # first-class circulation event alongside text/voice composer
        # decisions. /wisdom shows it; /effectiveness counts replies to it
        # as engagement; response_capture can link a reply via
        # proactive_decision_id; future Phase 13.1 multi-channel sends
        # will reuse the same record path.
        try:
            record_circulation_drawing(
                archetype=archetype or "",
                caption=caption,
                source_kind=source_kind,
                source_id=did,
                drawing_path=str(path),
                telegram_message_id=sent_msg.message_id,
            )
        except Exception as ce:
            log.debug(f"drawing record_circulation skip: {ce}")


# ── Phase 13.1 — composer-driven multi-channel moment amplification ─────────


async def _maybe_amplify_with_drawing(bot, chat_id: int,
                                       circulation_decision,
                                       text_message: str) -> None:
    """When the composer's decision is high-conviction and has an archetype,
    fire a complementary drawing in the SAME archetype as visual amplification.
    Background-friendly (caller may schedule via asyncio.create_task).

    Phase 13.1. The drawing references the same archetype as the text/voice
    message, lands in writing/Captures-equivalent (circulation_log) tagged
    with `moment_id` = the text decision's id so the two events are linkable
    as one moment in /wisdom and /effectiveness.
    """
    try:
        if circulation_decision is None:
            return
        archetype = (circulation_decision.archetype or "").strip().lower()
        if not archetype:
            return

        # Phase 13.3 — smart multi-channel decider. Replaces the score-only
        # gate with a three-tier path: fast-path (≥3.0), skip (<1.5 or
        # saturation), Haiku judge (borderline). Logs every decision so
        # we can tune thresholds based on real outcomes.
        try:
            from myalicia.skills.multi_channel import decide_drawing_amplification
            decision = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: decide_drawing_amplification(
                    text=text_message or "",
                    archetype=archetype,
                    source_kind=getattr(circulation_decision, "source_kind", None),
                    score=getattr(circulation_decision, "score", 0.0),
                    decision_id=getattr(circulation_decision, "id", None),
                ),
            )
            if not decision.get("drawing"):
                log.info(
                    f"[moment-amplify] skipped drawing "
                    f"id={getattr(circulation_decision,'id','?')[:8]} "
                    f"path={decision.get('path')} "
                    f"reason={decision.get('rationale','')[:80]}"
                )
                return
            log.info(
                f"[moment-amplify] firing drawing for decision "
                f"{circulation_decision.id[:8]} archetype={archetype} "
                f"score={circulation_decision.score:.2f} "
                f"path={decision.get('path')}"
            )
        except Exception as de:
            # Fail open to the legacy score-only gate so amplification
            # still works if the new module can't be imported.
            log.debug(f"smart decider failed, falling back: {de}")
            if not composer_should_amplify_with_drawing(circulation_decision):
                return
            log.info(
                f"[moment-amplify] firing drawing (legacy path) for decision "
                f"{circulation_decision.id[:8]} archetype={archetype} "
                f"score={circulation_decision.score:.2f}"
            )

        # Use the rendered text as the prompt seed so Haiku interprets a
        # drawing that complements (not duplicates) the verbal moment.
        prompt_seed = (text_message or "")[:500]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: generate_drawing(
                archetype=archetype, prompt=prompt_seed,
            ),
        )
        # Phase 13.2 — caption bridges text to drawing. Replace Haiku's
        # auto-generated caption with one that explicitly echoes the
        # text Alicia just sent. The drawing+text become one coherent
        # moment instead of two parallel artifacts. Falls back to the
        # auto-caption if the bridge call fails.
        try:
            bridged = await loop.run_in_executor(
                None,
                lambda: bridge_text_to_drawing_caption(
                    text=text_message,
                    archetype=archetype,
                    original_caption=result.get("caption", ""),
                ),
            )
            if bridged:
                log.info(
                    f"[moment-amplify] caption bridged: "
                    f"{result.get('caption','')[:40]!r} → {bridged[:40]!r}"
                )
                result["caption"] = bridged
        except Exception as be:
            log.debug(f"caption bridge fallback to auto: {be}")

        # Send via _send_drawing with source_kind=drawing_composer + the
        # text decision's id as moment_id linkage.
        await _send_drawing(
            bot=bot, chat_id=chat_id, result=result,
            source_kind="drawing_composer",
        )
        # _send_drawing already wrote a circulation_log entry; now patch in
        # the moment_id by writing a separate amplification record. Simplest
        # path: record a no-op 'moment-link' marker that names both ids.
        try:
            from myalicia.skills.circulation_composer import (
                _load_circulation_log, atomic_write_json,
                CIRCULATION_LOG_FILE,
            )
            entries = _load_circulation_log()
            # Find the most recent drawing entry from THIS process and tag it
            # with moment_id pointing at the text decision.
            for e in reversed(entries):
                if e.get("channel") == "drawing" and \
                   e.get("source_kind") == "drawing_composer" and \
                   "moment_id" not in e:
                    e["moment_id"] = circulation_decision.id
                    atomic_write_json(str(CIRCULATION_LOG_FILE), entries)
                    break
        except Exception as me:
            log.debug(f"moment-amplify moment_id tag skip: {me}")
    except Exception as e:
        log.warning(f"_maybe_amplify_with_drawing failed: {e}")


# ── Inline-button callback handler for drawings ─────────────────────────────
async def handle_drawing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route taps on the inline buttons under a drawing.

    callback_data shapes:
      draw:regen:<did>              → re-render with same context
      draw:arch:<did>               → swap keyboard to archetype picker
      draw:archpick:<did>:<arch>    → render with chosen archetype
      draw:back:<did>               → restore default keyboard
      draw:save:<did>               → copy drawing into the vault
      draw:title:<did>              → ForceReply prompt for a title; the
                                      reply is handled in handle_message().
    """
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    query = update.callback_query
    if not query: return
    # Always answer to dismiss the spinner; specific actions may answer
    # again with toast text.
    try:
        await query.answer()
    except Exception:
        pass

    data = (query.data or "").split(":")
    if len(data) < 3 or data[0] != "draw":
        return
    action = data[1]
    did = data[2]
    ctx = _DRAWING_CTX.get(did)
    if not ctx:
        try:
            await query.answer("That drawing's buttons expired.", show_alert=True)
        except Exception:
            pass
        return

    chat_id = query.message.chat_id

    # ── Regenerate ──────────────────────────────────────────────────────
    if action == "regen":
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            loop = asyncio.get_event_loop()
            state = build_drawing_state_snapshot() if not ctx["archetype"] else None
            new = await loop.run_in_executor(
                None,
                lambda: generate_drawing(
                    archetype=(ctx["archetype"] or None),
                    state=state,
                ),
            )
            await _send_drawing(bot=context.bot, chat_id=chat_id, result=new)
            try:
                record_drawing_sent(
                    new["path"], new["archetype"],
                    caption=new.get("caption", ""), kind=new.get("kind", "png"),
                    source="manual",
                )
            except Exception:
                pass
        except Exception as e:
            log.warning(f"draw regen failed: {e}")
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Regen failed: {e}")
            except Exception:
                pass
        return

    # ── Archetype picker (sub-keyboard) ────────────────────────────────
    if action == "arch":
        try:
            await query.edit_message_reply_markup(reply_markup=_archetype_picker_keyboard(did))
        except Exception as e:
            log.debug(f"draw arch picker failed: {e}")
        return

    if action == "back":
        try:
            await query.edit_message_reply_markup(reply_markup=_drawing_keyboard(did))
        except Exception as e:
            log.debug(f"draw back failed: {e}")
        return

    if action == "archpick" and len(data) >= 4:
        chosen = data[3].lower()
        if chosen not in _ARCHETYPES:
            return
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            loop = asyncio.get_event_loop()
            new = await loop.run_in_executor(
                None,
                lambda: generate_drawing(archetype=chosen),
            )
            await _send_drawing(bot=context.bot, chat_id=chat_id, result=new)
            try:
                record_drawing_sent(
                    new["path"], new["archetype"],
                    caption=new.get("caption", ""), kind=new.get("kind", "png"),
                    source="manual",
                )
            except Exception:
                pass
            # Restore default keyboard on the original (now-superseded) drawing
            try:
                await query.edit_message_reply_markup(reply_markup=_drawing_keyboard(did))
            except Exception:
                pass
        except Exception as e:
            log.warning(f"draw archpick failed: {e}")
        return

    # ── Save to vault ──────────────────────────────────────────────────
    if action == "save":
        try:
            rel = await _save_drawing_to_vault(ctx, title=None)
            try:
                await query.answer(f"💾 Saved → {rel}", show_alert=False)
            except Exception:
                pass
        except FileNotFoundError:
            try:
                await query.answer("File no longer on disk.", show_alert=True)
            except Exception:
                pass
        except Exception as e:
            log.warning(f"draw save failed: {e}")
            try:
                await query.answer(f"Save failed: {e}", show_alert=True)
            except Exception:
                pass
        return

    # ── Title it (ForceReply; handled in handle_message router) ────────
    if action == "title":
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{_DRAWING_TITLE_PROMPT_PREFIX}{did})",
                reply_markup=ForceReply(selective=True, input_field_placeholder="title for the drawing..."),
            )
        except Exception as e:
            log.debug(f"draw title prompt failed: {e}")
        return


# ── Inline-button callback handler for /unpack outputs ──────────────────────
async def handle_unpack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route taps on the [📌 Pin] [🔗 Connect] [➕ Tag] buttons."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    query = update.callback_query
    if not query: return
    try:
        await query.answer()
    except Exception:
        pass

    parts = (query.data or "").split(":")
    if len(parts) < 3 or parts[0] != "unpack":
        return
    action = parts[1]
    uid = parts[2]
    ctx = _UNPACK_CTX.get(uid)
    if not ctx:
        try:
            await query.answer("Unpack buttons expired.", show_alert=True)
        except Exception:
            pass
        return

    path = ctx.get("path", "")
    chat_id = query.message.chat_id

    # ── Pin: mark the note as canonical with a #pinned tag ────────────
    if action == "pin":
        try:
            if not path or not os.path.exists(path):
                await query.answer("Note file not found.", show_alert=True)
                return
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            if "#pinned" in text:
                await query.answer("Already pinned.")
                return
            # Insert #pinned after the first blank line (or prepend if none)
            if "\n\n" in text:
                head, _, rest = text.partition("\n\n")
                new_text = f"{head}\n\n#pinned\n\n{rest}"
            else:
                new_text = f"#pinned\n\n{text}"
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            try:
                await query.answer("📌 Pinned in vault.")
            except Exception:
                pass
        except Exception as e:
            log.warning(f"unpack pin failed: {e}")
            try:
                await query.answer(f"Pin failed: {e}", show_alert=True)
            except Exception:
                pass
        return

    # ── Connect: ForceReply → append backlink to the note ─────────────
    if action == "connect":
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{_UNPACK_CONNECT_PROMPT_PREFIX}{uid})",
                reply_markup=ForceReply(selective=True, input_field_placeholder="[[note name]] or topic..."),
            )
        except Exception as e:
            log.debug(f"unpack connect prompt failed: {e}")
        return

    # ── Tag: ForceReply → append tags to the note ─────────────────────
    if action == "tag":
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{_UNPACK_TAG_PROMPT_PREFIX}{uid})",
                reply_markup=ForceReply(selective=True, input_field_placeholder="#tag1 #tag2 #tag3..."),
            )
        except Exception as e:
            log.debug(f"unpack tag prompt failed: {e}")
        return


# ── Inline-button callback handler for [🤔 Why this?] ───────────────────────
async def handle_why_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reveal the reasoning trace captured at reply time."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID: return
    query = update.callback_query
    if not query: return
    try:
        await query.answer()
    except Exception:
        pass

    parts = (query.data or "").split(":")
    if len(parts) < 2 or parts[0] != "why":
        return
    wid = parts[1]
    trace = _WHY_TRACES.get(wid)
    if not trace:
        try:
            await query.answer("Reasoning trace expired.", show_alert=True)
        except Exception:
            pass
        return

    try:
        await safe_send_md(
            context.bot,
            query.message.chat_id,
            _format_why_trace(trace),
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning(f"why reveal failed: {e}")


@chat_guard
async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all scheduled tasks — Desktop agents AND Alicia's Python scheduler.

    Two sections:
      1. Desktop scheduled tasks — agent workflows (daily/weekly/monthly)
         parsed from ~/Documents/Claude/Scheduled/{taskId}/SKILL.md.
      2. Alicia Python scheduler — in-process schedule.every(...) jobs,
         grouped by cadence, introspected live from schedule.jobs.

    This closes the visibility gap between the two schedulers that run the
    brain. See the Desktop UI for live run history; Python jobs show their
    next-run time inline.
    """
    try:
        lines: list[str] = []

        # ── Section 1: Desktop agent tasks ─────────────────────────────────
        entries = _read_desktop_task_descriptions()
        if entries:
            buckets: dict[str, list[tuple[str, str]]] = {
                "daily": [], "weekly": [], "monthly": [], "other": [],
            }
            for tid, desc in entries:
                if tid.startswith("daily-") or desc.startswith("daily-"):
                    buckets["daily"].append((tid, desc))
                elif tid.startswith("weekly-") or desc.startswith("weekly-"):
                    buckets["weekly"].append((tid, desc))
                elif tid.startswith("monthly-") or desc.startswith("monthly-"):
                    buckets["monthly"].append((tid, desc))
                else:
                    buckets["other"].append((tid, desc))

            lines.append(f"☁️ *Desktop Agent Tasks* ({len(entries)})")
            lines.append("")
            cadence_labels = {
                "daily": "🌅 *Daily*",
                "weekly": "📅 *Weekly*",
                "monthly": "🗓 *Monthly*",
                "other": "📎 *Other*",
            }
            for cadence in ("daily", "weekly", "monthly", "other"):
                items = buckets[cadence]
                if not items:
                    continue
                lines.append(cadence_labels[cadence])
                for tid, desc in items:
                    short = desc[:140] + ("…" if len(desc) > 140 else "")
                    lines.append(f"  • `{tid}` — {short}" if short else f"  • `{tid}`")
                lines.append("")
        else:
            lines.append("☁️ *Desktop Agent Tasks* — none found")
            lines.append("")

        # ── Section 2: Alicia Python scheduler ────────────────────────────
        py_jobs = _describe_python_jobs()
        if py_jobs:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🐍 *Alicia Python Scheduler* ({len(py_jobs)})")
            lines.append("")

            by_cadence: dict[str, list[dict]] = {
                "daily": [], "weekly": [], "interval": [], "other": [],
            }
            for j in py_jobs:
                by_cadence[j["cadence"]].append(j)

            # Sort sensibly within each bucket.
            by_cadence["daily"].sort(key=lambda j: j["display"])
            by_cadence["weekly"].sort(
                key=lambda j: (
                    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(
                        j["display"].split()[0]
                    ) if j["display"].split()[:1] and
                         j["display"].split()[0] in
                         ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    else 9,
                    j["display"],
                )
            )
            # Intervals: shortest first (seconds < minutes < hours).
            unit_rank = {"sec": 0, "min": 1, "h": 2}

            def _interval_key(j):
                d = j["display"].lower()
                for u, r in unit_rank.items():
                    if u in d:
                        # Pull the number out of "Every 30 min" → 30
                        parts = [p for p in d.split() if p.isdigit()]
                        n = int(parts[0]) if parts else 1
                        return (r, n)
                return (9, 0)
            by_cadence["interval"].sort(key=_interval_key)

            section_labels = [
                ("daily", "🌅 *Daily*"),
                ("weekly", "📅 *Weekly*"),
                ("interval", "⏱ *Interval*"),
                ("other", "📎 *Other*"),
            ]
            for key, label in section_labels:
                items = by_cadence[key]
                if not items:
                    continue
                lines.append(label)
                for j in items:
                    lines.append(f"  • `{j['display']}` — {j['name']}")
                lines.append("")

        lines.append("_See Desktop UI for Desktop run history. Python jobs run in-process._")
        await safe_reply_md(update.message, "\n".join(lines))
    except Exception as e:
        log.warning(f"cmd_tasks failed: {e}")
        await update.message.reply_text(f"⚠️ Tasks error: {e}")


@chat_guard
async def cmd_briefingnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compile the analytical briefing on-demand via the agent-trigger harness.

    Calls compile_analytical_briefing() in a background thread — same function
    the Thursday 10:03 Desktop task invokes. Writes the full briefing to
    ~/.alicia/memory/analytical_briefing.md (overwrites) and pings back with a
    preview when done. Concurrency-guarded via agent_triggers.
    """
    loop = asyncio.get_event_loop()

    def _fmt(briefing: str, duration: float) -> str:
        if not briefing:
            return "⚠️ Briefing returned empty. Check ~/.alicia/logs/stderr.log."
        tail = ("\n…(truncated — full file at `memory/analytical_briefing.md`)"
                if len(briefing) > 2500 else "")
        return (f"📝 *Briefing complete* ({int(duration)}s)\n\n"
                f"{briefing[:2500]}{tail}")

    started, ack = agent_trigger(
        name="briefing",
        fn=compile_analytical_briefing,
        fn_args=(),
        bot=context.bot,
        chat_id=update.effective_chat.id,
        loop=loop,
        format_result=_fmt,
        format_started=lambda: "📝 *Compiling analytical briefing…* I'll ping when done.",
        label="analytical briefing",
    )
    await safe_reply_md(update.message, ack)


@chat_guard
async def cmd_synthesisnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fresh vault deep-pass synthesis on demand.

    Runs run_weekly_deep_pass() in a background thread — same function the
    Sunday 20:00 scheduler invokes. Heavy: expect 10–20 min of Opus/Sonnet
    calls generating concept notes + a new-thinker profile. Pings back with
    a summary and deep-links to any generated notes when done.
    """
    loop = asyncio.get_event_loop()

    def _fmt(result: dict, duration: float) -> str:
        mins, secs = divmod(int(duration), 60)
        try:
            # format_weekly_report gives the rich Telegram-ready summary.
            summary = format_weekly_report(result)
        except Exception as fe:
            log.warning(f"format_weekly_report failed: {fe}")
            summary = ""
        generated = result.get("generated_notes", []) or []
        new_thinker = result.get("new_thinker")
        head = f"🧬 *Synthesis complete* ({mins}m {secs}s)\n\n"
        if generated:
            head += f"Generated {len(generated)} concept note(s):\n"
            for n in generated[:5]:
                title = n.get("title", "note")
                link = n.get("deep_link") or n.get("filepath", "")
                head += f"  • [{title}]({link})\n" if link else f"  • {title}\n"
            head += "\n"
        if new_thinker:
            title = new_thinker.get("title", "thinker")
            link = new_thinker.get("deep_link") or new_thinker.get("filepath", "")
            head += f"New thinker: [{title}]({link})\n\n" if link else f"New thinker: {title}\n\n"
        if summary:
            head += summary[:2000]
        return head

    started, ack = agent_trigger(
        name="synthesis",
        fn=run_weekly_deep_pass,
        fn_args=(),
        bot=context.bot,
        chat_id=update.effective_chat.id,
        loop=loop,
        format_result=_fmt,
        format_started=lambda: (
            "🧬 *Synthesis running.* ETA ~10–20 min.\n"
            "I'll ping when done with the generated notes."
        ),
        label="vault deep pass",
    )
    await safe_reply_md(update.message, ack)


@chat_guard
async def cmd_researchnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deep research on a topic, writing a note to Obsidian.

    Usage: `/researchnow <topic>`

    Runs research_skill.research_deep(topic) in a background thread. Medium:
    2–5 min of two-pass Sonnet research. Writes the note into the vault and
    pings back with the path + summary when done.
    """
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await safe_reply_md(
            update.message,
            "Usage: `/researchnow <topic>`\n\n"
            "Example: `/researchnow agentic UX patterns`"
        )
        return

    loop = asyncio.get_event_loop()

    def _fmt(result: tuple, duration: float) -> str:
        mins, secs = divmod(int(duration), 60)
        try:
            summary, path = result
        except Exception:
            # Defensive — research_deep's contract is (summary, path).
            summary, path = str(result), ""
        time_prefix = f"🔬 *Research complete* ({mins}m {secs}s)\n"
        topic_line = f"Topic: _{topic}_\n"
        path_line = f"Note: `{path}`\n\n" if path else ""
        body = (summary or "")[:2500]
        return time_prefix + topic_line + path_line + body

    started, ack = agent_trigger(
        name="research",
        fn=research_deep,
        fn_args=(topic,),
        bot=context.bot,
        chat_id=update.effective_chat.id,
        loop=loop,
        format_result=_fmt,
        format_started=lambda: (
            f"🔬 *Researching:* _{topic}_\n"
            f"ETA ~2–5 min. I'll ping when done."
        ),
        label=f"research: {topic[:40]}",
    )
    await safe_reply_md(update.message, ack)


async def _end_walk_session(update: Update):
    """End walk session — save transcript and thread."""
    from myalicia.skills.thinking_modes import get_transcript as walk_transcript
    transcript = walk_transcript()
    transcript_text = end_walk().get("message", "Walk ended.")
    if transcript:
        try:
            queue_afterglow("walk", transcript, topic="walk thoughts")
        except Exception as e:
            log.error(f"Walk afterglow error: {e}")
        try:
            save_session_thread("walk", "", transcript, probe_rounds=0)
        except Exception as e:
            log.error(f"Walk session thread error: {e}")
        threading.Thread(
            target=lambda: extract_from_message(f"[Walk session]\n{transcript}", is_voice=True),
            daemon=True,
        ).start()
    await safe_reply_md(update.message, f"🚶 {transcript_text}")


async def _end_drive_session(update: Update):
    """End drive session — extract landed ideas, save thread."""
    from myalicia.skills.thinking_modes import get_transcript as drive_transcript_fn
    transcript = drive_transcript_fn()

    # Extract what "landed" via Sonnet
    if transcript:
        try:
            ext_prompt = build_drive_extraction_prompt()
            response = claude.messages.create(
                model=MODEL_SONNET,
                max_tokens=ext_prompt["max_tokens"],
                system=ext_prompt["system"],
                messages=ext_prompt["messages"],
            )
            landed = response.content[0].text
            await safe_reply_md(update.message, f"🚗 *Ideas that landed:*\n\n{landed}")
        except Exception as e:
            log.error(f"Drive extraction error: {e}")

        try:
            queue_afterglow("drive", transcript, topic="drive synthesis")
        except Exception as e:
            log.error(f"Drive afterglow error: {e}")
        try:
            save_session_thread("drive", "", transcript, probe_rounds=0)
        except Exception as e:
            log.error(f"Drive session thread error: {e}")
        threading.Thread(
            target=lambda: extract_from_message(f"[Drive session]\n{transcript}", is_voice=True),
            daemon=True,
        ).start()

    result = end_drive()
    await safe_reply_md(update.message, f"🚗 {result.get('message', 'Drive ended.')}")


async def _send_drive_connection(update: Update, topic: str = ""):
    """Generate and send a vault connection during drive mode."""
    vault_ctx, _ = get_vault_context(topic or "interesting connection")

    hot_topics = ""
    ht_path = str(MEMORY_DIR / "hot_topics.md")
    if os.path.exists(ht_path):
        try:
            with open(ht_path) as f:
                hot_topics = f.read()[:500]
        except Exception:
            pass

    prompt = build_drive_connection_prompt(vault_context=vault_ctx, hot_topics=hot_topics)
    try:
        response = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=prompt["max_tokens"],
            system=prompt["system"],
            messages=prompt["messages"],
        )
        connection = response.content[0].text
        record_drive_response(connection)

        # Send as voice (driving — eyes on road)
        try:
            voice_path = await text_to_voice(connection, style="excited")
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            os.remove(voice_path)
        except Exception as ve:
            log.warning(f"Drive voice failed: {ve}")
        await safe_reply_md(update.message, f"🔗 {connection}")
    except Exception as e:
        log.error(f"Drive connection error: {e}")
        await safe_reply_md(update.message, "Hmm, couldn't find a connection. Say something and I'll try another angle.")


async def _run_pipecat_unpack_extraction(update: Update, transcript: str, topic: str):
    """Run unpack-style extraction on a Pipecat live unpack transcript."""
    try:
        vault_ctx, _ = get_vault_context(transcript[:500])
        hot_topics = ""
        ht_path = str(MEMORY_DIR / "hot_topics.md")
        if os.path.exists(ht_path):
            try:
                with open(ht_path) as f:
                    hot_topics = f.read()[:500]
            except Exception:
                pass

        ext_prompt = build_live_unpack_extraction_prompt(vault_context=vault_ctx, hot_topics=hot_topics)
        response = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=ext_prompt["max_tokens"],
            system=ext_prompt["system"],
            messages=ext_prompt["messages"],
        )
        note_content = response.content[0].text

        # Save to Inbox
        from myalicia.skills.unpack_mode import save_vault_note
        filepath = save_vault_note(note_content)
        relative = filepath.replace(VAULT_ROOT + "/", "")
        deep_link = f"obsidian://open?vault={USER_HANDLE}-alicia&file={quote(relative, safe='/')}"
        await safe_reply_md(
            update.message,
            f"📦 *Live unpack extracted*\n\n[Open in Obsidian]({deep_link})",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Pipecat unpack extraction error: {e}")


# ── Unpack helpers ───────────────────────────────────────────────────────────

async def _run_unpack_probe(update: Update):
    """Generate and send probing questions during unpack mode."""
    enter_probing()

    # Get vault context for smarter probing
    transcript = get_transcript()
    vault_ctx, _ = get_vault_context(transcript[:500])

    # Load hot topics
    hot_topics = ""
    ht_path = str(MEMORY_DIR / "hot_topics.md")
    if os.path.exists(ht_path):
        try:
            with open(ht_path) as f:
                hot_topics = f"Current hot topics:\n{f.read()[:500]}"
        except Exception:
            pass

    prompt = build_probe_prompt(vault_context=vault_ctx, hot_topics=hot_topics)
    try:
        response = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=prompt["max_tokens"],
            system=prompt["system"],
            messages=prompt["messages"],
        )
        questions = response.content[0].text
        record_probe_response(questions)

        # Send as voice (this is the natural medium for probing)
        try:
            voice_path = await text_to_voice(questions, style="warm")
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            os.remove(voice_path)
        except Exception as ve:
            log.warning(f"Probe voice failed: {ve}")

        # Also send as text for reference
        await safe_reply_md(update.message, f"🔍 {questions}")

    except Exception as e:
        log.error(f"Unpack probe error: {e}")
        await safe_reply_md(update.message, "Let me think about what to ask... send another voice note or /done when ready.")


async def _run_unpack_extraction(update: Update):
    """Run the full extraction pipeline and save to vault."""
    enter_extracting()
    await safe_reply_md(update.message, "📦 _Extracting insights..._")

    # Get vault context
    transcript = get_transcript()
    vault_ctx, _ = get_vault_context(transcript[:500])

    hot_topics = ""
    ht_path = str(MEMORY_DIR / "hot_topics.md")
    if os.path.exists(ht_path):
        try:
            with open(ht_path) as f:
                hot_topics = f"Current hot topics:\n{f.read()[:500]}"
        except Exception:
            pass

    try:
        # Step 1: Generate structured vault note
        ext_prompt = build_extraction_prompt(vault_context=vault_ctx, hot_topics=hot_topics)
        response = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=ext_prompt["max_tokens"],
            system=ext_prompt["system"],
            messages=ext_prompt["messages"],
        )
        note_content = response.content[0].text

        # Step 2: Save to vault
        filepath = save_vault_note(note_content)

        # Step 3: Save raw transcript log
        save_transcript_log()

        # Step 4: Extract memory-level insights (background)
        def _extract_memory():
            try:
                mem_prompt = build_memory_extraction_prompt()
                mem_response = claude.messages.create(
                    model=MODEL_SONNET,
                    max_tokens=mem_prompt["max_tokens"],
                    system=mem_prompt["system"],
                    messages=mem_prompt["messages"],
                )
                mem_text = mem_response.content[0].text
                # Gap 2 fix: enrich transcript with session metadata for memory extraction
                from myalicia.skills.unpack_mode import get_session_metadata
                unpack_meta = get_session_metadata()
                meta_prefix = f"[Unpack session: {unpack_meta['duration_seconds']}s, {unpack_meta['probe_rounds']} probe rounds, topic: {unpack_meta['topic'] or 'open'}]"
                extract_from_message(f"{meta_prefix}\n{transcript}", is_voice=True)
                log.info(f"Unpack memory extraction complete: {mem_text[:100]}")
            except Exception as me:
                log.error(f"Unpack memory extraction error: {me}")

        threading.Thread(target=_extract_memory, daemon=True).start()

        # Step 5: Send summary voice note
        # Extract first few lines as summary for voice
        summary_lines = note_content.split("\n")[:8]
        summary_text = "\n".join(summary_lines)
        try:
            voice_path = await text_to_voice(summary_text, style="warm")
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            os.remove(voice_path)
        except Exception as ve:
            log.warning(f"Extraction voice failed: {ve}")

        # Send text confirmation with vault link
        relative = filepath.replace(VAULT_ROOT + "/", "")
        from urllib.parse import quote
        deep_link = f"obsidian://open?vault={USER_HANDLE}-alicia&file={quote(relative, safe='/')}"

        # Queue afterglow follow-up + save session thread
        from myalicia.skills.unpack_mode import get_session_metadata, _topic_hint
        unpack_meta = get_session_metadata()
        queue_afterglow("unpack", transcript, topic=_topic_hint)
        save_session_thread("unpack", _topic_hint, transcript, probe_rounds=unpack_meta.get("probe_rounds", 0))

        stats = end_unpack()
        uid = _register_unpack_ctx(filepath, topic=_topic_hint or "")
        await safe_reply_md(
            update.message,
            f"📦 *Unpacked and saved*\n\n"
            f"[Open in Obsidian]({deep_link})\n\n"
            f"_{stats['message']}_",
            disable_web_page_preview=True,
            reply_markup=_unpack_keyboard(uid),
        )

    except Exception as e:
        log.error(f"Unpack extraction error: {e}", exc_info=True)
        end_unpack()
        await safe_reply_md(update.message, f"⚠️ Extraction failed: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def run_scheduler(bot_app: Application):
    """Register every recurring task.

    NOTE on the wall-clock times below: they are starter defaults — picked
    to spread API load across the day and to roughly align with morning
    /  midday / evening rhythms. They are NOT meant to fingerprint a
    particular user's schedule. To match your own rhythm, override
    individual times in your `config.yaml` (the schedule.* keys) or fork
    this function. Many of the :05 / :15 / :30 offsets exist purely to
    stagger concurrent API calls; don't collapse them all to :00.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def send_curiosity_scan():
        """05:30 — Pre-compute curiosity questions for the morning message."""
        try:
            result = run_curiosity_scan()
            log.info(f"Curiosity scan: {result.get('questions_generated', 0)} questions generated")
        except Exception as e:
            log.error(f"Curiosity scan error: {e}")

    async def send_daily_pass():
        """06:00 — Tag untagged vault notes."""
        try:
            result = run_daily_tagging_pass()
            report = format_daily_report(result)
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, report, disable_web_page_preview=True)
            index_vault(False)
        except Exception as e:
            log.error(f"Daily pass error: {e}")

    async def send_morning_message():
        """06:05 — Morning stats (text) + greeting with provocation (text + voice)."""
        try:
            # Part 1: Stats dashboard (text only)
            stats = build_startup_stats()
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, stats)

            # Adaptive impulse cap based on yesterday's engagement
            update_impulse_cap_from_engagement()

            # Part 1.5: Deliver overnight synthesis if available
            try:
                overnight = get_pending_overnight()
                if overnight:
                    delivery = build_morning_delivery(overnight["insight"])
                    await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🌙 {delivery}")
                    mark_overnight_delivered()
                    try:
                        voice_path = await text_to_voice(delivery, style="measured")
                        with open(voice_path, "rb") as vf:
                            await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                        os.remove(voice_path)
                    except Exception:
                        pass
                    log.info("Overnight synthesis delivered in morning message")
            except Exception as oe:
                log.error(f"Overnight delivery error: {oe}")

            # Circulation gate (Layer 2) — composer may veto the greeting.
            # Stats were already sent above (they are system state, not
            # discretionary). The greeting is what the composer arbitrates.
            _circ = None  # populated when the gate runs successfully
            if USE_CIRCULATION_COMPOSER:
                try:
                    _circ = decide_for_slot("morning")
                    if not _circ.send:
                        log.info(f"[circulation] morning greeting NO_SEND: {_circ.reason}")
                        # Phase 11.10 — capture resurface fallback. When the
                        # composer would stay quiet AND the user has a 2-14 day-
                        # old unprompted capture that hasn't been resurfaced
                        # in the cooldown window, bring it back as a light
                        # 'where has it landed?' morning message. Captures
                        # stop being one-time archives.
                        try:
                            capture_meta = pick_capture_for_morning_resurface()
                        except Exception as pre:
                            log.debug(f"[capture-resurface] pick failed: {pre}")
                            capture_meta = None
                        if capture_meta is None:
                            return  # truly quiet morning
                        try:
                            resurface_msg = render_morning_capture_resurface(capture_meta)
                            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, resurface_msg)
                            mark_capture_resurfaced(capture_meta["path"])
                            log.info(
                                f"[capture-resurface] morning fallback sent: "
                                f"{capture_meta['path'].name}"
                            )
                        except Exception as rre:
                            log.warning(f"[capture-resurface] render/send failed: {rre}")
                        return
                    log.info(
                        f"[circulation] morning SEND archetype={_circ.archetype} "
                        f"kind={_circ.source_kind} source_id={_circ.source_id}"
                    )
                except Exception as ce:
                    _circ = None
                    log.warning(f"[circulation] morning gate error (falling back): {ce}")

            # Part 2: Greeting + thought prompt (text + voice)
            greeting = build_startup_greeting()

            # Archetype flavor injection — freed from deterministic triggers
            flavor = None
            try:
                flavor = get_archetype_flavor()
                if flavor:
                    greeting = f"{greeting}\n\n✨ _{flavor['message']}_"
                    log.info(f"Morning archetype surfaced: {flavor['archetype']}")
            except Exception as af_err:
                log.debug(f"Archetype flavor skip: {af_err}")

            # Phase 11.7 — when the composer picked a surfacing for a known
            # synthesis, append a compact "past responses on this idea"
            # footer so resurfacing reads as continuing the conversation.
            try:
                if _circ is not None and _circ.send and \
                   _circ.source_kind in ("surfacing", "lived_surfacing") and \
                   _circ.synthesis_title:
                    greeting = enrich_proactive_with_past_responses(
                        greeting, _circ.synthesis_title,
                    )
            except Exception as enrich_err:
                log.debug(f"morning past-response enrichment skip: {enrich_err}")

            msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, greeting)
            record_proactive_sent("morning", greeting[:80])
            try: signal_record_proactive_slot("morning", "greeting")
            except Exception: pass
            if msg:
                track_proactive_message_id(
                    msg.message_id, "morning", greeting[:80],
                    archetype=(flavor or {}).get("archetype"),
                )
                # Phase 11.2 — write rendered greeting back into circulation_log
                # so response_capture's "Alicia asked" field shows the actual
                # message the user saw, not the composer's internal log format.
                if _circ is not None:
                    try:
                        record_circulation_send(
                            _circ.id,
                            prompt_text=greeting,
                            telegram_message_id=msg.message_id,
                        )
                    except Exception as rc_err:
                        log.debug(f"record_circulation_send (morning) skip: {rc_err}")
                    # Phase 13.1 — multi-channel moment amplification.
                    # Background-fire a drawing in the same archetype if
                    # the decision is high-conviction. Fire-and-forget so
                    # the morning send isn't blocked.
                    asyncio.create_task(
                        _maybe_amplify_with_drawing(bot_app.bot, TELEGRAM_CHAT_ID,
                                                    _circ, greeting)
                    )

            # Voice version of greeting — vary style with content
            # Phase 13.7 — smart voice decider gates the fire. Text-only
            # when the message is prose-shaped (lists, code, URLs, very
            # long paragraphs), saturation-guarded, Haiku-judged for
            # borderline cases. Falls open to YES on any decider error.
            # Phase 14.1 — when voice + drawing both fire, weave a tail.
            try:
                from myalicia.skills.multi_channel import (
                    decide_voice_amplification,
                    decide_drawing_amplification,
                    compose_voice_with_drawing_tail,
                )
                v_dec = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: decide_voice_amplification(text=greeting, slot="morning"),
                )
                if not v_dec.get("voice"):
                    log.info(
                        f"[voice-decide] morning skipped: "
                        f"{v_dec.get('path')} — {v_dec.get('rationale','')[:80]}"
                    )
                else:
                    # Phase 14.1 — does drawing also fire? If yes, weave a
                    # voice tail referencing the visual.
                    voice_text = greeting
                    if _circ is not None:
                        try:
                            d_dec = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: decide_drawing_amplification(
                                    text=greeting,
                                    archetype=(_circ.archetype or "").strip().lower() or None,
                                    source_kind=getattr(_circ, "source_kind", None),
                                    score=getattr(_circ, "score", 0.0),
                                    decision_id=getattr(_circ, "id", None),
                                ),
                            )
                            if d_dec.get("drawing") and _circ.archetype:
                                voice_text, tail = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    lambda: compose_voice_with_drawing_tail(
                                        text=greeting,
                                        archetype=_circ.archetype,
                                    ),
                                )
                                if tail:
                                    log.info(
                                        f"[coherent-moment] morning voice tail: {tail[:60]!r}"
                                    )
                        except Exception as ce:
                            log.debug(f"morning coherent-moment skip: {ce}")
                    # Short greetings get warm delivery, briefings get measured, questions get excited
                    voice_style = "warm"
                    if len(voice_text) < 100:
                        voice_style = random.choice(["warm", "excited"])
                    elif len(voice_text) > 400:
                        voice_style = "measured"
                    voice_path = await text_to_voice(voice_text, style=voice_style)
                    with open(voice_path, "rb") as vf:
                        await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                    os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Morning voice failed (text still sent): {ve}")
        except Exception as e:
            log.error(f"Morning message error: {e}")

    async def send_midday_message():
        """12:30 — Midday nudge: curiosity question, synthesis spark, or vault resurface (text + voice)."""
        try:
            # Temporal gate — respect the user's rhythms
            try:
                delay = should_delay_message("midday")
                if delay > 0:
                    log.info(f"Temporal gate: midday delayed by {delay}min (avoid window)")
                    return  # Skip — scheduler will try next day
            except Exception:
                pass

            # Circulation gate (Layer 2) — composer may return NO_SEND.
            _circ = None  # populated when the gate runs successfully
            if USE_CIRCULATION_COMPOSER:
                try:
                    _circ = decide_for_slot("midday")
                    if not _circ.send:
                        log.info(f"[circulation] midday NO_SEND: {_circ.reason}")
                        return
                    log.info(
                        f"[circulation] midday SEND archetype={_circ.archetype} "
                        f"kind={_circ.source_kind} source_id={_circ.source_id}"
                    )
                except Exception as ce:
                    _circ = None
                    log.warning(f"[circulation] midday gate error (falling back): {ce}")

            message = build_midday_message()

            # Phase 18.0 — Detect if this midday is a noticing. If so, the
            # build_noticing_proactive call inside build_midday_message has
            # populated a sidecar context with archetype/score/source_kind
            # so the multi-channel rendering below can guarantee text +
            # voice + drawing all fire together (instead of relying on the
            # smart deciders to each independently rediscover this is a
            # ceremonial moment). Captured here, used by the voice + drawing
            # blocks below.
            noticing_ctx = None
            try:
                from myalicia.skills.emergent_themes import get_last_noticing_context
                noticing_ctx = get_last_noticing_context()
            except Exception as nctx_err:
                log.debug(f"noticing context fetch skip: {nctx_err}")

            # Phase 19.3 — Same pattern for mood check-ins (19.1 + 19.2).
            # When build_mood_checkin_proactive or build_mood_lift_proactive
            # fires, the sidecar lets us pre-render Beatrice voice in the
            # right style (tender for the dip, gentle for the lift). Without
            # this, the mood check-in text lands but voice depends on the
            # smart decider seeing this is ceremonial — which it can't,
            # because the message goes through normal text-send paths.
            mood_ctx = None
            if not noticing_ctx:
                try:
                    from myalicia.skills.emotion_model import get_last_mood_checkin_context
                    mood_ctx = get_last_mood_checkin_context()
                except Exception as mctx_err:
                    log.debug(f"mood checkin context fetch skip: {mctx_err}")

            # Muse serendipity — occasionally attach a quote echo or vault walk
            try:
                moment = build_serendipity_moment()
                if moment:
                    muse_msg = moment.get("message", "")
                    if muse_msg:
                        message = f"{message}\n\n✨ {muse_msg}"
                        log.info(f"Muse moment attached to midday: {moment.get('type', '?')}")
            except Exception as mu_err:
                log.debug(f"Muse midday skip: {mu_err}")

            # Daimon pre-send filter — catch comfort bias before shipping
            try:
                daimon_check = daimon_pre_send_check(message)
                if not daimon_check["approved"]:
                    log.info(f"Daimon flagged midday: {daimon_check['reason']}")
                    # Rebuild with growth edge suggestion in mind
                    suggestion = daimon_check.get("suggestion", "")
                    if suggestion:
                        message = f"{message}\n\n🔥 _{suggestion}_"
            except Exception as dc_err:
                log.debug(f"Daimon check skip: {dc_err}")

            # Archetype flavor injection
            flavor = None
            try:
                flavor = get_archetype_flavor()
                if flavor:
                    message = f"{message}\n\n✨ _{flavor['message']}_"
                    log.info(f"Midday archetype surfaced: {flavor['archetype']}")
            except Exception as af_err:
                log.debug(f"Archetype flavor skip: {af_err}")

            # Phase 11.7 — past-response enrichment for surfacing-driven sends
            try:
                if _circ is not None and _circ.send and \
                   _circ.source_kind in ("surfacing", "lived_surfacing") and \
                   _circ.synthesis_title:
                    message = enrich_proactive_with_past_responses(
                        message, _circ.synthesis_title,
                    )
            except Exception as enrich_err:
                log.debug(f"midday past-response enrichment skip: {enrich_err}")

            msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, message, disable_web_page_preview=True)
            record_proactive_sent("midday", message[:80])
            try: signal_record_proactive_slot("midday", "nudge")
            except Exception: pass
            if msg:
                track_proactive_message_id(
                    msg.message_id, "midday", message[:80],
                    archetype=(flavor or {}).get("archetype"),
                )
                if _circ is not None:
                    try:
                        record_circulation_send(
                            _circ.id,
                            prompt_text=message,
                            telegram_message_id=msg.message_id,
                        )
                    except Exception as rc_err:
                        log.debug(f"record_circulation_send (midday) skip: {rc_err}")
                    # Phase 13.1 — multi-channel moment amplification.
                    asyncio.create_task(
                        _maybe_amplify_with_drawing(bot_app.bot, TELEGRAM_CHAT_ID,
                                                    _circ, message)
                    )

            # Phase 18.0 — Noticings don't go through the composer (no _circ),
            # so the drawing amplification block above never fires for them.
            # Build a synthetic decision-shaped object using the noticing's
            # own archetype/score/source_kind and schedule the drawing
            # directly. The smart decider inside _maybe_amplify_with_drawing
            # will fast-path because score=2.5 + lived_surfacing.
            if noticing_ctx and msg:
                try:
                    from types import SimpleNamespace as _NS
                    fake_decision = _NS(
                        id=f"noticing_{int(datetime.now().timestamp())}",
                        archetype=noticing_ctx.get("archetype", "beatrice"),
                        source_kind=noticing_ctx.get(
                            "source_kind", "lived_surfacing",
                        ),
                        score=float(noticing_ctx.get("score", 2.5)),
                    )
                    asyncio.create_task(
                        _maybe_amplify_with_drawing(
                            bot_app.bot, TELEGRAM_CHAT_ID,
                            fake_decision, message,
                        )
                    )
                    log.info(
                        f"[noticing] drawing amplification scheduled "
                        f"(theme={noticing_ctx.get('theme', '?')[:40]})"
                    )
                except Exception as nd_err:
                    log.debug(f"noticing drawing amplification skip: {nd_err}")

            # Voice version of midday message — Phase 13.7 smart decider
            # + Phase 13.12 cross-channel coherence: when voice + drawing
            # both fire in the same moment, augment the voice text with a
            # short tail that points to the visual.
            #
            # Phase 18.0 — When this midday IS a noticing, bypass the smart
            # decider entirely. Noticings are ceremonial moments by design;
            # the text + voice + drawing should all arrive together. We
            # also use the noticing's voice_text (without the markdown
            # banner) and tender style when weather is heavy.
            try:
                from myalicia.skills.multi_channel import (
                    decide_voice_amplification,
                    decide_drawing_amplification,
                    compose_voice_with_drawing_tail,
                )
                # Phase 18.0 noticing fast-path
                # Phase 19.3 — same fast-path for mood check-ins
                ceremonial_force_voice = bool(noticing_ctx) or bool(mood_ctx)
                if ceremonial_force_voice:
                    if noticing_ctx:
                        rationale = (
                            f"noticing forces voice (Phase 18.0) — "
                            f"theme={noticing_ctx.get('theme', '?')[:40]}"
                        )
                        force_path = "noticing_force"
                    else:
                        rationale = (
                            f"mood {mood_ctx.get('kind', 'checkin')} forces "
                            f"voice (Phase 19.3) — "
                            f"trend={mood_ctx.get('trend', '?')[:20]}"
                        )
                        force_path = "mood_force"
                    v_dec = {
                        "voice": True,
                        "path": force_path,
                        "rationale": rationale,
                    }
                else:
                    v_dec = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: decide_voice_amplification(text=message, slot="midday"),
                    )
                if not v_dec.get("voice"):
                    log.info(
                        f"[voice-decide] midday skipped: "
                        f"{v_dec.get('path')} — {v_dec.get('rationale','')[:80]}"
                    )
                else:
                    # Phase 13.12 — does drawing also fire? If yes, weave
                    # a voice tail referencing the visual. We re-check the
                    # drawing decider here so the call matches what
                    # _maybe_amplify_with_drawing will compute (same args
                    # → same path; logged twice is acceptable observability).
                    voice_text = message
                    if _circ is not None:
                        try:
                            d_dec = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: decide_drawing_amplification(
                                    text=message,
                                    archetype=(_circ.archetype or "").strip().lower() or None,
                                    source_kind=getattr(_circ, "source_kind", None),
                                    score=getattr(_circ, "score", 0.0),
                                    decision_id=getattr(_circ, "id", None),
                                ),
                            )
                            if d_dec.get("drawing") and _circ.archetype:
                                voice_text, tail = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    lambda: compose_voice_with_drawing_tail(
                                        text=message,
                                        archetype=_circ.archetype,
                                    ),
                                )
                                if tail:
                                    log.info(
                                        f"[coherent-moment] midday voice tail: {tail[:60]!r}"
                                    )
                        except Exception as ce:
                            log.debug(f"midday coherent-moment skip: {ce}")
                    # Phase 18.0 — for noticings, override the voice text
                    # (skip the markdown banner) and the style (gentle/tender
                    # instead of excited — this is Beatrice's witnessing voice,
                    # not midday energy).
                    # Phase 19.3 — same override for mood check-ins, with the
                    # style coming from the mood context (tender for dip,
                    # gentle for lift) which the build helpers populate.
                    if noticing_ctx:
                        nc_voice = (noticing_ctx.get("voice_text") or "").strip()
                        if nc_voice:
                            voice_text = nc_voice
                        # Tender style on heavy days; otherwise gentle
                        # (Beatrice). Phase 17.4's adapt_style_to_weather
                        # will further soften if needed.
                        midday_voice_style = (
                            "tender" if noticing_ctx.get("weather") == "tender"
                            else "gentle"
                        )
                    elif mood_ctx:
                        mc_voice = (mood_ctx.get("voice_text") or "").strip()
                        if mc_voice:
                            voice_text = mc_voice
                        # The build helpers already chose tender vs gentle
                        # in the dict — honor that.
                        midday_voice_style = (
                            mood_ctx.get("voice_style") or "gentle"
                        )
                    else:
                        midday_voice_style = "excited"

                    # Phase 18.1 — Voice cache for noticings. Defensive
                    # against double-renders (if the same noticing somehow
                    # fires twice) and saves a Gemini TTS call. Cache key
                    # is hash(theme + voice_text + style); TTL = 24h.
                    cached_voice_path = None
                    cache_hit = False
                    if noticing_ctx:
                        try:
                            from myalicia.skills.emergent_themes import (
                                get_cached_noticing_voice,
                                cache_noticing_voice,
                            )
                            cached_voice_path = get_cached_noticing_voice(
                                theme=noticing_ctx.get("theme", ""),
                                voice_text=voice_text,
                                style=midday_voice_style,
                            )
                            if cached_voice_path:
                                cache_hit = True
                                log.info(
                                    f"[noticing-voice-cache] hit "
                                    f"theme={noticing_ctx.get('theme', '?')[:40]!r}"
                                )
                        except Exception as ce:
                            log.debug(f"voice cache lookup skip: {ce}")

                    if cached_voice_path:
                        voice_path = cached_voice_path
                    else:
                        voice_path = await text_to_voice(
                            voice_text, style=midday_voice_style,
                        )
                        # Phase 18.1 — populate cache for next time
                        if noticing_ctx:
                            try:
                                from myalicia.skills.emergent_themes import (
                                    cache_noticing_voice,
                                )
                                cache_noticing_voice(
                                    theme=noticing_ctx.get("theme", ""),
                                    voice_text=voice_text,
                                    source_path=voice_path,
                                    style=midday_voice_style,
                                )
                            except Exception as ce:
                                log.debug(f"voice cache write skip: {ce}")

                    with open(voice_path, "rb") as vf:
                        await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                    # Only delete the source path if it WASN'T a cache
                    # hit — cache files are owned by the cache.
                    if not cache_hit:
                        try:
                            os.remove(voice_path)
                        except Exception:
                            pass
            except Exception as ve:
                log.warning(f"Midday voice failed (text still sent): {ve}")
        except Exception as e:
            log.error(f"Midday message error: {e}")

    async def send_evening_message():
        """21:00 — Evening reflection, musubi bond reflection (1st), or 'get to know the user' question."""
        try:
            # Temporal gate — respect the user's rhythms
            try:
                delay = should_delay_message("evening")
                if delay > 0:
                    log.info(f"Temporal gate: evening delayed by {delay}min (avoid window)")
                    return
            except Exception:
                pass

            # Musubi: On 1st of month, lead with bond reflection
            musubi_prefix = ""
            if datetime.now().day == 1:
                try:
                    musubi_msg = build_musubi_reflection()
                    if musubi_msg:
                        musubi_prefix = f"✨ {musubi_msg}\n\n"
                        try:
                            archive_bond_reflection(musubi_msg)
                        except Exception:
                            pass
                except Exception as me:
                    log.debug(f"Musubi reflection error: {me}")

            # Circulation gate (Layer 2) — composer may return NO_SEND.
            # Evening is the natural slot for contradiction-surface (voice);
            # the composer rates it higher here than midday/morning.
            _circ = None  # populated when the gate runs successfully
            if USE_CIRCULATION_COMPOSER:
                try:
                    _circ = decide_for_slot("evening")
                    if not _circ.send:
                        log.info(f"[circulation] evening NO_SEND: {_circ.reason}")
                        return
                    log.info(
                        f"[circulation] evening SEND archetype={_circ.archetype} "
                        f"kind={_circ.source_kind} channel={_circ.channel} "
                        f"source_id={_circ.source_id}"
                    )
                except Exception as ce:
                    _circ = None
                    log.warning(f"[circulation] evening gate error (falling back): {ce}")

            message = build_evening_message()
            if musubi_prefix:
                message = musubi_prefix + message

            # Daimon pre-send filter
            try:
                daimon_check = daimon_pre_send_check(message)
                if not daimon_check["approved"]:
                    log.info(f"Daimon flagged evening: {daimon_check['reason']}")
                    suggestion = daimon_check.get("suggestion", "")
                    if suggestion:
                        message = f"{message}\n\n🔥 _{suggestion}_"
            except Exception as dc_err:
                log.debug(f"Daimon check skip: {dc_err}")

            # Archetype flavor injection
            flavor = None
            try:
                flavor = get_archetype_flavor()
                if flavor:
                    message = f"{message}\n\n✨ _{flavor['message']}_"
                    log.info(f"Evening archetype surfaced: {flavor['archetype']}")
            except Exception as af_err:
                log.debug(f"Archetype flavor skip: {af_err}")

            # Phase 11.7 — past-response enrichment for surfacing-driven sends
            try:
                if _circ is not None and _circ.send and \
                   _circ.source_kind in ("surfacing", "lived_surfacing") and \
                   _circ.synthesis_title:
                    message = enrich_proactive_with_past_responses(
                        message, _circ.synthesis_title,
                    )
            except Exception as enrich_err:
                log.debug(f"evening past-response enrichment skip: {enrich_err}")

            msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, message, disable_web_page_preview=True)
            # Track which type was sent for prompt-response pairing
            day_of_week = datetime.now().weekday()
            msg_type = "know_user" if day_of_week in (1, 3, 5) else "evening"
            record_proactive_sent(msg_type, message[:80])
            try: signal_record_proactive_slot("evening", msg_type)
            except Exception: pass
            if msg:
                track_proactive_message_id(
                    msg.message_id, msg_type, message[:80],
                    archetype=(flavor or {}).get("archetype"),
                )
                if _circ is not None:
                    try:
                        record_circulation_send(
                            _circ.id,
                            prompt_text=message,
                            telegram_message_id=msg.message_id,
                        )
                    except Exception as rc_err:
                        log.debug(f"record_circulation_send (evening) skip: {rc_err}")
                    # Phase 13.1 — multi-channel moment amplification.
                    asyncio.create_task(
                        _maybe_amplify_with_drawing(bot_app.bot, TELEGRAM_CHAT_ID,
                                                    _circ, message)
                    )

            # Voice version of evening message — Phase 13.7 smart decider
            # + Phase 14.1 cross-channel coherence (voice/drawing tail)
            try:
                from myalicia.skills.multi_channel import (
                    decide_voice_amplification,
                    decide_drawing_amplification,
                    compose_voice_with_drawing_tail,
                )
                v_dec = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: decide_voice_amplification(text=message, slot="evening"),
                )
                if not v_dec.get("voice"):
                    log.info(
                        f"[voice-decide] evening skipped: "
                        f"{v_dec.get('path')} — {v_dec.get('rationale','')[:80]}"
                    )
                else:
                    # Phase 14.1 — does drawing also fire? If yes, weave a tail.
                    voice_text = message
                    if _circ is not None:
                        try:
                            d_dec = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: decide_drawing_amplification(
                                    text=message,
                                    archetype=(_circ.archetype or "").strip().lower() or None,
                                    source_kind=getattr(_circ, "source_kind", None),
                                    score=getattr(_circ, "score", 0.0),
                                    decision_id=getattr(_circ, "id", None),
                                ),
                            )
                            if d_dec.get("drawing") and _circ.archetype:
                                voice_text, tail = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    lambda: compose_voice_with_drawing_tail(
                                        text=message,
                                        archetype=_circ.archetype,
                                    ),
                                )
                                if tail:
                                    log.info(
                                        f"[coherent-moment] evening voice tail: {tail[:60]!r}"
                                    )
                        except Exception as ce:
                            log.debug(f"evening coherent-moment skip: {ce}")
                    voice_path = await text_to_voice(voice_text, style="gentle")
                    with open(voice_path, "rb") as vf:
                        await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                    os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Evening voice failed (text still sent): {ve}")
        except Exception as e:
            log.error(f"Evening message error: {e}")

    async def send_weekly_retrospective():
        """Sunday 19:00 — Pre-pass retrospective: send /wisdom + /effectiveness
        + /loops as a weekly self-reflection for the system. Lightweight,
        read-only, no Opus calls. Lets the user see the week's circulation +
        feedback + meta-circulation at a glance before the heavy 20:00 deep
        pass starts.

        Phase 11.9 — closes the rhythm: the system observes itself weekly
        the way it observes itself daily via /wisdom + /effectiveness on
        demand.
        Phase 14.2 — extends the rhythm: /loops joins the digest so the
        circulatory view (four closed loops + cross-loop signals) is part
        of the weekly read-through."""
        try:
            header = (
                "🌅 *Sunday retrospective*\n"
                "_The week the system observed itself._"
            )
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, header)
            try:
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    render_wisdom_dashboard(),
                )
            except Exception as we:
                log.warning(f"weekly_retrospective wisdom render failed: {we}")
            try:
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    render_effectiveness_dashboard(),
                )
            except Exception as ee:
                log.warning(f"weekly_retrospective effectiveness render failed: {ee}")
            # Phase 14.2 — meta-circulation view (four loops + cross-loop signals)
            try:
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    render_loops_dashboard(),
                )
            except Exception as le:
                log.warning(f"weekly_retrospective loops render failed: {le}")
            # Phase 14.4 — the user-model arc (the "who you're becoming" view).
            # Closes the rhythm: the user's arc joins Alicia's circulatory view
            # so the weekly digest covers BOTH developmental directions.
            try:
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    render_becoming_dashboard(),
                )
            except Exception as be:
                log.warning(f"weekly_retrospective becoming render failed: {be}")
        except Exception as e:
            log.error(f"Weekly retrospective error: {e}")

    async def send_weekly_pass():
        """Sunday 20:00 — Weekly deep pass + graph health + trajectory analysis + memory consolidation + metrics snapshot."""
        try:
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, "🧬 *Weekly deep pass starting...*")
            result = run_weekly_deep_pass()
            report = format_weekly_report(result)
            for chunk in [report[i:i+3500] for i in range(0, len(report), 3500)]:
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, chunk, disable_web_page_preview=True)

            # Graph health report
            try:
                graph_report = run_graph_health_report()
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🕸 *Graph Health Report*\n\n{graph_report[:3500]}", disable_web_page_preview=True)
            except Exception as ge:
                log.error(f"Graph health error: {ge}")

            # Weekly trajectory analysis (learn from conversation patterns)
            try:
                trajectory_insights = analyze_trajectories()
                if trajectory_insights and trajectory_insights.get("procedures_added"):
                    await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID,
                        f"📊 *Trajectory Analysis*\n\nAnalyzed {trajectory_insights.get('trajectories_analyzed', 0)} conversations. "
                        f"Added {trajectory_insights.get('procedures_added', 0)} new procedures to memory.")
            except Exception as te:
                log.error(f"Trajectory analysis error: {te}")

            # Memory consolidation
            try:
                consolidate_all_memory()
                log.info("Weekly memory consolidation complete")
            except Exception as me:
                log.error(f"Memory consolidation error: {me}")

            # Append weekly metrics snapshot to Obsidian tracking note
            try:
                append_weekly_snapshot()
                log.info("Weekly metrics snapshot appended")
            except Exception as se:
                log.error(f"Weekly snapshot error: {se}")

            # Paired person diarization (the user + Alicia profiles)
            try:
                diarization = run_paired_diarization()
                week_id = diarization.get("week_id", "?")
                delta_preview = diarization.get("delta", "")[:300]
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    f"📋 *Paired diarization complete — {week_id}*\n\n"
                    f"{USER_NAME} + Alicia profiles generated.\n\n"
                    f"_Delta:_ {delta_preview}..."
                )
                log.info(f"Paired diarization complete: {week_id}")
            except Exception as de:
                log.error(f"Paired diarization error: {de}")

            # Self-improvement: skill configs rewrite themselves
            try:
                improve_result = run_weekly_improve()
                changes = improve_result.get("changes", [])
                if changes:
                    report = format_improve_report(improve_result)
                    await safe_send_md(
                        bot_app.bot, TELEGRAM_CHAT_ID,
                        f"🔧 *Self-improvement complete*\n\n{report}"
                    )
                    log.info(f"/improve: {len(changes)} skill config changes applied")
                else:
                    log.info("/improve: no changes needed this week")
            except Exception as ie:
                log.error(f"Self-improvement error: {ie}")

            # Meta-reflexion: evaluate whether /improve is improving
            try:
                meta_result = run_meta_reflexion()
                status = meta_result.get("status", "unknown")
                if status == "meta_improvements_proposed":
                    meta_report = format_meta_report(meta_result)
                    await safe_send_md(
                        bot_app.bot, TELEGRAM_CHAT_ID,
                        f"🔬 *Meta-reflexion: improvement process needs tuning*\n\n{meta_report}"
                    )
                elif status == "healthy":
                    log.info("Meta-reflexion: improvement process healthy")
                else:
                    log.info(f"Meta-reflexion: {status}")
            except Exception as me:
                log.error(f"Meta-reflexion error: {me}")

            # Skill library health check (Memento-Skills)
            try:
                library_result = run_weekly_library_health()
                lib_health = library_result.get("health", {})
                issues = lib_health.get("issues", [])
                if issues:
                    lib_report = format_library_report(library_result)
                    await safe_send_md(
                        bot_app.bot, TELEGRAM_CHAT_ID,
                        f"📚 {lib_report}"
                    )
                log.info(
                    f"Skill library: {library_result.get('total_configs', 0)} configs, "
                    f"{lib_health.get('total_learned', 0)} learned rules"
                )
            except Exception as le:
                log.error(f"Skill library health error: {le}")

        except Exception as e:
            log.error(f"Weekly pass error: {e}")

    # Accumulator for daily ingest roll-up (drained once per day)
    _ingest_daily_buffer = []

    async def send_ingest_scan():
        """Every 30 min — Scan for new vault sources and cascade updates. Accumulates silently for daily rollup."""
        try:
            result = run_ingest_scan(limit=5)
            if result["new_sources"] > 0:
                _ingest_daily_buffer.append(result)
                # Re-index semantic search after ingest
                index_vault(False)
                log.info(f"Ingest scan: {result['new_sources']} sources processed (buffered for daily rollup)")
            else:
                log.info("Ingest scan: no new sources")
        except Exception as e:
            log.error(f"Ingest scan error: {e}")

    async def send_surprise_moment():
        """Every 2 hours — Try to generate a surprise impulse if something interesting is found."""
        try:
            # Temporal gate — don't surprise during avoid windows
            try:
                delay = should_delay_message("surprise")
                if delay > 0:
                    log.info(f"Temporal gate: surprise delayed (avoid window)")
                    return
            except Exception:
                pass

            if not can_send_impulse():
                log.info("Impulse check: throttled (cap or gap)")
                return

            message = generate_surprise_moment()
            if not message:
                log.info("Impulse check: nothing interesting enough right now")
                return

            # Quality gate: would the user care?
            care_score = would_user_care(message)
            if care_score < 0.3:
                log.info(f"Impulse gated by quality check (score {care_score:.2f}): {message[:60]}")
                return

            msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, message, disable_web_page_preview=True)
            record_impulse_sent()
            record_proactive_sent("surprise", message[:80])
            record_proactive_timestamp()
            if msg:
                # Surprise moments are muse-coded by convention (serendipity, delight).
                track_proactive_message_id(
                    msg.message_id, "surprise", message[:80],
                    archetype="muse",
                )

            # Voice for surprise moments — short and warm
            try:
                voice_path = await text_to_voice(message, style="warm")
                with open(voice_path, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Surprise voice failed (text still sent): {ve}")

            log.info("Impulse sent: surprise moment delivered")
        except Exception as e:
            log.error(f"Surprise moment error: {e}")

    async def send_ingest_daily_rollup():
        """Once daily — Send rolled-up summary of all ingest activity."""
        try:
            if not _ingest_daily_buffer:
                log.info("Daily ingest rollup: nothing to report")
                return
            report = format_daily_ingest_rollup(_ingest_daily_buffer)
            _ingest_daily_buffer.clear()
            if report:
                for chunk in [report[i:i+3500] for i in range(0, len(report), 3500)]:
                    await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, chunk, disable_web_page_preview=True)
        except Exception as e:
            log.error(f"Daily ingest rollup error: {e}")

    # ── Safe task runner (catches and reports errors to Telegram) ────────────
    async def safe_run(name, coro_func):
        """Run a scheduled task with error alerting to Telegram."""
        try:
            log.info(f"Scheduler: starting {name}")
            await coro_func()
            log.info(f"Scheduler: {name} complete")
        except Exception as e:
            log.error(f"Scheduler: {name} FAILED: {e}", exc_info=True)
            try:
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    f"⚠️ *Scheduled task failed*\n\n"
                    f"Task: `{name}`\n"
                    f"Error: `{type(e).__name__}: {str(e)[:200]}`\n"
                    f"Time: {datetime.now().strftime('%H:%M')}\n\n"
                    f"_Check logs: tail -f ~/.alicia/logs/stderr.log_"
                )
            except Exception:
                pass  # Don't let alert failure crash the scheduler

    # Layer 3 — Contradiction Detector pass. Runs at 20:45, fifteen minutes
    # before the 21:00 evening slot so any fresh evidence-bumps or draft
    # entries land in the ledger in time for the Circulation Composer to
    # consume them when composing the evening message. Gated by
    # USE_CONTRADICTION_DETECTOR (dry-run when False).
    async def send_contradiction_detector():
        """20:45 — Layer 3 daily pass (feature-flagged)."""
        try:
            summary = run_contradiction_detector_pass()
            log.info(f"Contradiction detector: {summary}")
        except Exception as e:
            log.error(f"Contradiction detector error: {e}")

    # Layer 4 — Practice Runner. Runs at 09:00 so the user gets the check-in
    # mid-morning — after the morning message has landed, well before midday.
    # The runner reports due check-ins; this handler composes + sends them.
    # Feature-flagged via USE_PRACTICE_RUNNER (default False; when False the
    # pass still identifies due check-ins but does not send or mutate state).
    async def send_practice_checkins():
        """09:00 — Layer 4 practice check-ins (feature-flagged)."""
        try:
            summary = run_practice_runner_pass()
            log.info(f"Practice runner: {summary}")
            if not USE_PRACTICE_RUNNER:
                return
            for practice, day in practice_due_check_ins():
                try:
                    text = compose_practice_check_in(practice, day)
                    await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, text)
                    record_practice_check_in(practice.slug, day)
                    log.info(f"[practice] check-in sent slug={practice.slug} day={day}")
                except Exception as ce:
                    log.error(f"[practice] check-in send error ({practice.slug} d{day}): {ce}")
        except Exception as e:
            log.error(f"Practice runner error: {e}")

    # ── Daily schedule ────────────────────────────────────────────────────────
    # Phase 13.6 — Meta-synthesis outer loop. 02:30 nightly so it runs
    # well before morning, after the day's captures have been written
    # but before the curiosity scan reads from synthesis state. Builds
    # at most one meta-synthesis per pass; falls through silently when
    # no parent has crossed the capture threshold.
    async def send_meta_synthesis_pass():
        from myalicia.skills.meta_synthesis import run_meta_synthesis_pass
        result = await asyncio.get_event_loop().run_in_executor(
            None, run_meta_synthesis_pass
        )
        if result.get("built"):
            try:
                child = Path(result["child_path"]).name
                parent = result.get("candidate", "?")
                await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    f"🌱 *Meta-synthesis emerged overnight*\n\n"
                    f"Your responses on _{parent}_ accumulated enough "
                    f"to deserve their own distillation.\n\n"
                    f"`{child}` is now in your vault.",
                )
            except Exception as e:
                log.debug(f"meta_synthesis notify failed: {e}")

    schedule.every().day.at("02:30").do(
        lambda: loop.run_until_complete(safe_run("meta_synthesis", send_meta_synthesis_pass))
    )

    # Phase 12.2 — Gap-driven research scan. 03:00 nightly: cheap,
    # logs which the user-dimension is currently in deficit. The actual
    # question is composed lazily by proactive_messages.build_midday_message
    # when its 20% gate fires — this scan exists so ops can see in the
    # logs what tomorrow's gap-driven prompt would target, and so the
    # signal is observable independently of whether a question fires.
    async def send_dimension_research_scan():
        from myalicia.skills.dimension_research import run_dimension_research_scan
        result = await asyncio.get_event_loop().run_in_executor(
            None, run_dimension_research_scan
        )
        log.info(f"dimension_research_scan: {result}")

    schedule.every().day.at("03:00").do(
        lambda: loop.run_until_complete(safe_run("dimension_research_scan", send_dimension_research_scan))
    )

    # Phase 17.0 — Emergent theme detection. 04:00 nightly: Sonnet pass
    # over recent captures + learnings + meta-syntheses, identifies
    # themes that repeat without being named yet. Detected themes
    # accumulate in memory/emergent_themes.jsonl; midday rotation picks
    # the highest-recurrence one (~15% gate) and renders a noticing
    # — text + voice + drawing as a ceremonial moment.
    async def send_emergent_theme_scan():
        from myalicia.skills.emergent_themes import run_emergent_theme_scan
        result = await asyncio.get_event_loop().run_in_executor(
            None, run_emergent_theme_scan
        )
        log.info(f"emergent_theme_scan: {result}")

    schedule.every().day.at("04:00").do(
        lambda: loop.run_until_complete(safe_run("emergent_theme_scan", send_emergent_theme_scan))
    )

    # Phase 14.8 — Dormancy alert. 06:30 daily (right after morning send).
    # Detect any loop that's been quiet ≥21 days, send a one-time
    # Telegram alert per dormancy event, record so we don't re-alert
    # until activity resumes or 30 days pass. Cheap: 4 file reads + maybe
    # one safe_send_md.
    async def send_dormancy_check():
        from myalicia.skills.loops_dashboard import (
            unalerted_dormant_loops, render_dormancy_alert_message,
            record_dormancy_alert,
        )
        try:
            dormant = await asyncio.get_event_loop().run_in_executor(
                None, unalerted_dormant_loops
            )
            if not dormant:
                return
            text = render_dormancy_alert_message(dormant)
            if text:
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, text)
                # Record each alert so we don't fire again for these loops
                # within the 30-day suppression window.
                for d in dormant:
                    record_dormancy_alert(d["loop"], d["days_dormant"])
                log.info(
                    f"dormancy alert sent: "
                    f"{[d['loop'] for d in dormant]}"
                )
        except Exception as e:
            log.warning(f"send_dormancy_check failed: {e}")

    schedule.every().day.at("06:30").do(
        lambda: loop.run_until_complete(safe_run("dormancy_check", send_dormancy_check))
    )

    schedule.every().day.at("05:30").do(lambda: loop.run_until_complete(safe_run("curiosity_scan", send_curiosity_scan)))
    schedule.every().day.at("06:00").do(lambda: loop.run_until_complete(safe_run("daily_pass", send_daily_pass)))
    schedule.every().day.at("06:05").do(lambda: loop.run_until_complete(safe_run("morning_message", send_morning_message)))
    schedule.every().day.at("09:00").do(lambda: loop.run_until_complete(safe_run("practice_checkins", send_practice_checkins)))
    schedule.every().day.at("12:30").do(lambda: loop.run_until_complete(safe_run("midday_message", send_midday_message)))
    schedule.every().day.at("20:45").do(lambda: loop.run_until_complete(safe_run("contradiction_detector", send_contradiction_detector)))
    schedule.every().day.at("21:00").do(lambda: loop.run_until_complete(safe_run("evening_message", send_evening_message)))

    # ── Ingest scan (every 30 minutes, silent — daily rollup at 20:30) ─────
    schedule.every(30).minutes.do(lambda: loop.run_until_complete(safe_run("ingest_scan", send_ingest_scan)))
    schedule.every().day.at("20:30").do(lambda: loop.run_until_complete(safe_run("ingest_daily_rollup", send_ingest_daily_rollup)))

    # ── Surprise moments (every 2 hours — adaptive, throttled) ───────────
    schedule.every(2).hours.do(lambda: loop.run_until_complete(safe_run("surprise_moment", send_surprise_moment)))

    # ── Bridge state snapshot (H2: Desktop-readable alicia-state.json) ──────
    # Cheap: ~50ms of local reads. Writes Alicia/Bridge/alicia-state.json so
    # Desktop's scheduled synthesis tasks can consume Alicia's current season,
    # emergence score, archetype weights, hot threads, and mood signal as
    # context. Closes the "two Alicias sharing a brain" loop.
    async def send_bridge_snapshot():
        write_alicia_state_snapshot()

    schedule.every(10).minutes.do(
        lambda: loop.run_until_complete(safe_run("bridge_snapshot", send_bridge_snapshot))
    )

    # ── Unpack silence probe (every 15s — only fires when unpack is active + silence threshold met) ──
    async def check_unpack_silence():
        """If unpack mode is listening and silence threshold passed, auto-probe."""
        if not should_probe_now():
            return
        log.info("Unpack: silence threshold reached — auto-probing")
        try:
            # Get vault context for probing
            transcript = get_transcript()
            vault_ctx, _ = get_vault_context(transcript[:500])

            hot_topics = ""
            ht_path = str(MEMORY_DIR / "hot_topics.md")
            if os.path.exists(ht_path):
                try:
                    with open(ht_path) as f:
                        hot_topics = f"Current hot topics:\n{f.read()[:500]}"
                except Exception:
                    pass

            enter_probing()
            prompt = build_probe_prompt(vault_context=vault_ctx, hot_topics=hot_topics)

            response = claude.messages.create(
                model=MODEL_SONNET,
                max_tokens=prompt["max_tokens"],
                system=prompt["system"],
                messages=prompt["messages"],
            )
            questions = response.content[0].text
            record_probe_response(questions)

            # Send as voice
            try:
                voice_path = await text_to_voice(questions, style="warm")
                with open(voice_path, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Unpack probe voice failed: {ve}")

            # Also send as text
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🔍 {questions}")

        except Exception as e:
            log.error(f"Unpack auto-probe error: {e}")

    schedule.every(15).seconds.do(lambda: loop.run_until_complete(check_unpack_silence()))

    # ── /improve validation (H4: did last week's rule changes actually help?) ──
    # Runs Monday 22:00 — one day after Sunday's /improve run, giving the new
    # rules a full day of live episodes to produce a reward signal. Appends
    # per-change verdicts to memory/improve_validations.jsonl; next Sunday's
    # /improve reads them via get_improve_validations_context() so Opus can
    # prefer rules that demonstrably moved the needle and roll back the ones
    # that didn't.
    async def run_improve_validation():
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, validate_improve_outputs
            )
            if not isinstance(result, dict):
                return
            log.info(
                f"Improve validation: {result.get('changes_scored', 0)} changes "
                f"across {result.get('runs_checked', 0)} runs — "
                f"helped={result.get('helped', 0)} hurt={result.get('hurt', 0)} "
                f"neutral={result.get('neutral', 0)} "
                f"insufficient={result.get('insufficient_data', 0)}"
            )
        except Exception as ive:
            log.error(f"Improve validation error: {ive}")

    schedule.every().monday.at("22:00").do(
        lambda: loop.run_until_complete(safe_run("improve_validation", run_improve_validation))
    )

    # ── Weekly schedule ───────────────────────────────────────────────────────
    # Phase 11.9 — Sunday 19:00 retrospective fires BEFORE the 20:00 deep
    # pass. Pre-pass it's an observation. Post-pass it's a record.
    schedule.every().sunday.at("19:00").do(
        lambda: loop.run_until_complete(safe_run("weekly_retrospective", send_weekly_retrospective))
    )

    # Phase 20.0 — Sunday 19:30 self-portrait: 30 min after the four-panel
    # retrospective sends its observable views, the portrait composer
    # builds a single ~200-word reflection in Beatrice's voice from
    # mood + dashboard engagement + noticings + becoming + captures.
    # Lands in writing/Wisdom/Lived/ as Tier-3 + appended to the log.
    async def send_weekly_self_portrait():
        try:
            from myalicia.skills.weekly_self_portrait import (
                build_weekly_self_portrait,
                pick_portrait_voice_style,
                get_cached_portrait_voice,
                cache_portrait_voice,
            )
            from types import SimpleNamespace as _NS_portrait
            entry = await asyncio.get_event_loop().run_in_executor(
                None, lambda: build_weekly_self_portrait(force=False),
            )
            if entry and entry.get("body"):
                vault_path = entry.get("vault_path") or ""
                body = entry["body"]
                msg = (
                    f"🪞 *Sunday self-portrait*\n\n"
                    f"{body}\n\n"
                    + (f"_archived: `{vault_path}`_" if vault_path else "")
                )
                portrait_msg = await safe_send_md(
                    bot_app.bot, TELEGRAM_CHAT_ID,
                    msg[:3800], disable_web_page_preview=True,
                )
                # Phase 24.0 — track this portrait's message_id so the
                # response_capture pipeline can tag any reply as
                # `kind=portrait_response` with the right portrait_ts.
                try:
                    if portrait_msg and hasattr(portrait_msg, "message_id"):
                        from myalicia.skills.weekly_self_portrait import (
                            track_portrait_message_id,
                        )
                        track_portrait_message_id(
                            int(portrait_msg.message_id),
                            portrait_ts=entry.get("ts"),
                            vault_path=vault_path,
                        )
                except Exception as te:
                    log.debug(f"track_portrait_message_id (sunday) skip: {te}")
                # Phase 21.0 — voice-render the portrait so it lands as
                # a multi-channel ceremonial moment. Style derived from
                # the portrait's own mood snapshot (gentle by default,
                # tender on heavy weeks). Cached by hash(body+style)
                # so /retro replays within the week skip the Gemini call.
                try:
                    style = pick_portrait_voice_style(entry.get("signals"))
                    cache_hit = False
                    voice_path = get_cached_portrait_voice(body, style=style)
                    if voice_path:
                        cache_hit = True
                        log.info(
                            f"[portrait-voice-cache] hit style={style}"
                        )
                    else:
                        voice_path = await text_to_voice(body, style=style)
                        try:
                            cache_portrait_voice(body, voice_path, style=style)
                        except Exception as ce:
                            log.debug(f"portrait voice cache write skip: {ce}")
                    with open(voice_path, "rb") as vf:
                        await bot_app.bot.send_voice(
                            chat_id=TELEGRAM_CHAT_ID, voice=vf,
                        )
                    if not cache_hit:
                        try:
                            os.remove(voice_path)
                        except Exception:
                            pass
                except Exception as ve:
                    log.warning(
                        f"portrait voice failed (text already sent): {ve}"
                    )
                # Phase 21.1 — Drawing as the third channel. Schedule
                # _maybe_amplify_with_drawing with a synthetic decision
                # (Beatrice + score 2.5 + lived_surfacing) so the smart
                # decider fast-paths. The drawing's caption is bridged
                # by Phase 13.2 against the portrait body's first line,
                # so the visual references the same week-feeling.
                try:
                    fake_decision = _NS_portrait(
                        id=f"portrait_{int(datetime.now().timestamp())}",
                        archetype="beatrice",
                        source_kind="lived_surfacing",
                        score=2.5,
                    )
                    asyncio.create_task(
                        _maybe_amplify_with_drawing(
                            bot_app.bot, TELEGRAM_CHAT_ID,
                            fake_decision, body,
                        )
                    )
                    log.info(
                        f"[portrait] drawing amplification scheduled "
                        f"({len(body)} char body)"
                    )
                except Exception as de:
                    log.debug(f"portrait drawing skip: {de}")
                log.info("weekly self-portrait sent")
            else:
                log.info("weekly self-portrait skipped (cooldown or empty)")
        except Exception as e:
            log.error(f"weekly self-portrait error: {e}")

    schedule.every().sunday.at("19:30").do(
        lambda: loop.run_until_complete(safe_run(
            "weekly_self_portrait", send_weekly_self_portrait,
        ))
    )

    # SSGM defensive pass — Sunday 19:50, just before /improve fires at 20:00.
    # Audits every /improve-authored rule for staleness, low confidence, and
    # recent reward losses. Auto-deprecates rules meeting all three negative
    # criteria. Result is written to memory_audit.md and surfaced in the
    # morning message.
    async def send_memory_audit():
        try:
            from myalicia.skills.memory_audit import (
                run_memory_audit, format_memory_audit_report,
            )
            summary = await asyncio.get_event_loop().run_in_executor(
                None, lambda: run_memory_audit(auto_apply=True)
            )
            if not isinstance(summary, dict):
                return
            interesting = (
                summary.get("stale_count", 0)
                + summary.get("low_confidence_count", 0)
                + summary.get("hurt_by_validation_count", 0)
                + summary.get("deprecated_count", 0)
            )
            if interesting:
                msg = format_memory_audit_report(summary)
                await safe_send_md(bot_app, TELEGRAM_CHAT_ID, msg)
            log.info(
                f"memory_audit: stale={summary.get('stale_count', 0)} "
                f"low_conf={summary.get('low_confidence_count', 0)} "
                f"hurt={summary.get('hurt_by_validation_count', 0)} "
                f"auto_deprecated={summary.get('deprecated_count', 0)}"
            )
        except Exception as ae:
            log.error(f"memory_audit error: {ae}")

    schedule.every().sunday.at("19:50").do(
        lambda: loop.run_until_complete(safe_run("memory_audit", send_memory_audit))
    )

    schedule.every().sunday.at("20:00").do(lambda: loop.run_until_complete(safe_run("weekly_pass", send_weekly_pass)))

    # ── Autonomous analysis modules (Option B) ───────────────────────────
    async def run_analysis_contradiction():
        """Wednesday 10:00 — Mine productive tensions in the vault."""
        try:
            result = run_contradiction_mining()
            if result.get("status") == "success":
                log.info(f"Contradiction mining: {result.get('tensions_found', 0)} tensions found")
            else:
                log.warning(f"Contradiction mining partial: {result.get('error', 'unknown')}")
        except Exception as e:
            log.error(f"Contradiction mining error: {e}")

    async def run_analysis_temporal():
        """15th monthly 10:00 — Map temporal thinking patterns."""
        try:
            result = run_temporal_analysis()
            if result.get("status") == "success":
                log.info(f"Temporal analysis: peak hours {result.get('peak_hours', [])}")
            else:
                log.warning(f"Temporal analysis partial: {result.get('error', 'unknown')}")
        except Exception as e:
            log.error(f"Temporal analysis error: {e}")

    async def run_analysis_growth_edge():
        """1st monthly 10:00 — Detect active growth edges."""
        try:
            result = run_growth_edge_detection()
            if result.get("status") == "success":
                log.info(f"Growth edge detection: {result.get('growth_edges_found', 0)} edges found")
            else:
                log.warning(f"Growth edge detection partial: {result.get('error', 'unknown')}")
        except Exception as e:
            log.error(f"Growth edge error: {e}")

    async def run_analysis_dialogue_depth():
        """1st monthly 14:00 — Score dialogue depth by message type."""
        try:
            result = run_dialogue_depth_scoring()
            if result.get("status") == "success":
                log.info(f"Dialogue depth scoring complete")
            else:
                log.warning(f"Dialogue depth partial: {result.get('error', 'unknown')}")
        except Exception as e:
            log.error(f"Dialogue depth error: {e}")

    async def run_analysis_briefing():
        """Thursday 10:00 — Compile all analysis into briefing for proactive messages."""
        try:
            briefing = compile_analytical_briefing()
            if briefing:
                log.info(f"Analytical briefing compiled ({len(briefing)} chars)")
            else:
                log.warning("Analytical briefing returned empty")
        except Exception as e:
            log.error(f"Analytical briefing error: {e}")

    schedule.every().wednesday.at("10:00").do(lambda: loop.run_until_complete(safe_run("contradiction_mining", run_analysis_contradiction)))
    schedule.every().thursday.at("10:00").do(lambda: loop.run_until_complete(safe_run("analytical_briefing", run_analysis_briefing)))

    # Monthly tasks — use daily schedule with day-of-month check
    async def monthly_1st_morning():
        """1st of month 10:00 — Growth edge detection."""
        if datetime.now().day == 1:
            await run_analysis_growth_edge()

    async def monthly_1st_afternoon():
        """1st of month 14:00 — Dialogue depth scoring."""
        if datetime.now().day == 1:
            await run_analysis_dialogue_depth()

    async def monthly_15th():
        """15th of month 10:00 — Temporal pattern analysis."""
        if datetime.now().day == 15:
            await run_analysis_temporal()

    schedule.every().day.at("10:00").do(lambda: loop.run_until_complete(safe_run("monthly_growth_edge", monthly_1st_morning)))
    schedule.every().day.at("14:00").do(lambda: loop.run_until_complete(safe_run("monthly_dialogue_depth", monthly_1st_afternoon)))
    schedule.every().day.at("10:01").do(lambda: loop.run_until_complete(safe_run("monthly_temporal", monthly_15th)))

    # ── Afterglow delivery (every 30 min — checks for pending follow-ups) ──
    async def send_afterglow():
        """Check and deliver pending conversation afterglows."""
        try:
            pending = get_pending_afterglows()
            if not pending:
                return
            for entry in pending:
                try:
                    vault_ctx, _ = get_vault_context(entry.get("transcript", "")[:500])
                    prompt = build_afterglow_prompt(entry, vault_context=vault_ctx)
                    response = claude.messages.create(
                        model=MODEL_SONNET,
                        max_tokens=prompt["max_tokens"],
                        system=prompt["system"],
                        messages=prompt["messages"],
                    )
                    followup = response.content[0].text
                    # Apply quality gate
                    score = would_user_care(followup)
                    if score < 0.3:
                        log.info(f"Afterglow gated (score {score:.2f}): {followup[:60]}")
                        mark_afterglow_delivered(entry["id"])
                        continue
                    msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID,
                        f"💭 {followup}", disable_web_page_preview=True)
                    mark_afterglow_delivered(entry["id"])
                    record_proactive_timestamp()
                    # Voice delivery
                    try:
                        voice_path = await text_to_voice(followup, style="warm")
                        with open(voice_path, "rb") as vf:
                            await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                        os.remove(voice_path)
                    except Exception:
                        pass
                    log.info(f"Afterglow delivered for {entry['source']} session (score {score:.2f})")
                except Exception as ae:
                    log.error(f"Afterglow delivery error: {ae}")
                    mark_afterglow_delivered(entry["id"])
        except Exception as e:
            log.error(f"Afterglow check error: {e}")

    schedule.every(30).minutes.do(lambda: loop.run_until_complete(safe_run("afterglow", send_afterglow)))

    # ── Overnight synthesis (21:30 — after evening message, before sleep) ──
    async def run_overnight_synthesis():
        """Post-evening: extract day's themes and synthesize overnight connection."""
        try:
            # Snapshot under lock — avoid iterating while main handler appends
            with history_lock:
                history_snapshot = list(conversation_history)
            if not should_run_overnight(history_snapshot):
                log.info("Overnight synthesis: skipped (quiet day or already pending)")
                return
            themes = extract_day_themes(history_snapshot)
            if not themes:
                log.info("Overnight synthesis: no themes extracted")
                return
            vault_ctx, _ = get_vault_context(" ".join(themes))
            hot_topics = ""
            ht_path = str(MEMORY_DIR / "hot_topics.md")
            if os.path.exists(ht_path):
                try:
                    with open(ht_path) as f:
                        hot_topics = f.read()[:500]
                except Exception:
                    pass
            prompt = build_overnight_prompt(themes, vault_context=vault_ctx, hot_topics=hot_topics)
            response = claude.messages.create(
                model=MODEL_SONNET,
                max_tokens=prompt["max_tokens"],
                system=prompt["system"],
                messages=prompt["messages"],
            )
            insight = response.content[0].text
            save_overnight_result(insight, themes)
            log.info(f"Overnight synthesis saved: {insight[:80]}")
        except Exception as e:
            log.error(f"Overnight synthesis error: {e}")

    schedule.every().day.at("21:30").do(lambda: loop.run_until_complete(safe_run("overnight_synthesis", run_overnight_synthesis)))

    # ── Weekly walk digest + thread summary (Sunday 19:00) ──
    async def run_weekly_digest():
        """Sunday 19:00 — Compile walk transcripts and session thread summary."""
        try:
            # Walk digest
            walk_transcripts = get_week_walk_transcripts()
            if walk_transcripts:
                vault_ctx, _ = get_vault_context("walking thoughts weekly review")
                prompt = build_walk_digest_prompt(walk_transcripts, vault_context=vault_ctx)
                response = claude.messages.create(
                    model=MODEL_SONNET,
                    max_tokens=prompt["max_tokens"],
                    system=prompt["system"],
                    messages=prompt["messages"],
                )
                digest = response.content[0].text
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID,
                    f"🚶 *Weekly Walk Digest*\n\n{digest[:3500]}", disable_web_page_preview=True)

            # Thread summary
            recent = get_recent_threads(days=7)
            if recent and len(recent) >= 2:
                prompt = build_thread_summary_prompt(recent)
                response = claude.messages.create(
                    model=MODEL_SONNET,
                    max_tokens=prompt["max_tokens"],
                    system=prompt["system"],
                    messages=prompt["messages"],
                )
                summary = response.content[0].text
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID,
                    f"🧵 *Weekly Thread Summary*\n\n{summary[:3500]}", disable_web_page_preview=True)
        except Exception as e:
            log.error(f"Weekly digest error: {e}")

    schedule.every().sunday.at("19:00").do(lambda: loop.run_until_complete(safe_run("weekly_digest", run_weekly_digest)))

    # ── Voice signature recompute (daily at 22:00) ──
    async def recompute_voice_signature():
        """Daily 22:00 — Recompute rolling voice signature."""
        try:
            sig = get_voice_signature()
            if sig:
                log.info(f"Voice signature recomputed: trend={sig.get('trend', 'unknown')}, msgs={sig.get('total_voice_messages', 0)}")
        except Exception as e:
            log.error(f"Voice signature error: {e}")

    schedule.every().day.at("22:00").do(lambda: loop.run_until_complete(safe_run("voice_signature", recompute_voice_signature)))

    # ── Way of Being: Self-Reflection (Saturday 19:30 — before Sunday weekly pass) ──
    async def run_self_reflection_task():
        """Beatrice archetype: Alicia reflects on her own growth this week."""
        try:
            result = run_self_reflection()
            if result.get("saved") and result.get("growth_note"):
                note = result["growth_note"]
                log.info(f"Self-reflection saved: {note[:100]}")
        except Exception as e:
            log.error(f"Self-reflection error: {e}")

    schedule.every().saturday.at("19:30").do(lambda: loop.run_until_complete(safe_run("self_reflection", run_self_reflection_task)))

    # ── Way of Being: Reciprocal Challenge (Wednesday 14:00 — mid-week, quality-gated) ──
    async def send_challenge_moment():
        """Psyche archetype: challenge the user with an unresolved vault tension."""
        try:
            challenge = get_pending_challenge()
            if not challenge:
                log.info("Challenge moment: nothing strong enough this week")
                return

            care_score = would_user_care(challenge)
            if care_score < 0.4:
                log.info(f"Challenge gated by quality (score {care_score:.2f})")
                return

            msg = await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🔮 {challenge}")
            record_challenge_sent(challenge[:200])
            try:
                archive_challenge(challenge, "vault tension")
            except Exception:
                pass
            if msg:
                # Challenge moments are psyche-coded by convention.
                track_proactive_message_id(
                    msg.message_id, "challenge", challenge[:80],
                    archetype="psyche",
                )
            record_proactive_sent("challenge", challenge[:80])
            record_proactive_timestamp()

            # Voice for challenge — measured tone
            try:
                voice_path = await text_to_voice(challenge, style="measured")
                with open(voice_path, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Challenge voice failed: {ve}")
        except Exception as e:
            log.error(f"Challenge moment error: {e}")

    schedule.every().wednesday.at("14:00").do(lambda: loop.run_until_complete(safe_run("challenge_moment", send_challenge_moment)))

    # ── Way of Being: Musubi Reflection (1st of month in evening message) ──
    # Integrated into evening message rather than separate task — see build_evening_message enhancement

    # ── Inner Life: Emergence Pulse (hourly — updates emergence state, detects season transitions) ──
    async def send_emergence_pulse():
        """Hourly update of emergence metrics; sends alert on season transition."""
        try:
            result = run_emergence_pulse()
            if result.get("season_changed"):
                old = result.get("old_season", "?")
                new = result.get("new_season", "?")
                score = result.get("score", 0)
                msg = f"🌱 *Season transition:* {old} → {new}\n\n_{SEASONS_DESC.get(new, 'A new season begins.')}_\n\nEmergence score: {score}"
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, msg)
                log.info(f"Emergence season transition: {old} → {new}")
            # H2: update bridge snapshot on every emergence pulse, so Desktop
            # sees fresh archetype weights + season within the hour rather
            # than waiting up to 10 minutes for the next scheduled snapshot.
            try:
                write_alicia_state_snapshot()
            except Exception as se:
                log.warning(f"bridge snapshot after emergence pulse failed: {se}")
        except Exception as e:
            log.error(f"Emergence pulse error: {e}")

    schedule.every(1).hours.do(lambda: loop.run_until_complete(safe_run("emergence_pulse", send_emergence_pulse)))

    # ── Inner Life: Morning Self-Reflection (05:55 — before greeting the user) ──
    async def send_morning_self_reflection():
        """Alicia reflects on herself before the morning message."""
        try:
            # Gather yesterday context from interactions log
            yesterday_ctx = ""
            try:
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, 'r') as f:
                        lines = f.readlines()[-50:]  # Last 50 interactions
                    yesterday_ctx = f"{len(lines)} recent interactions logged"
            except Exception:
                pass

            reflection = build_morning_self_reflection(yesterday_ctx)
            # Send to the user so he can see her growth
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🪞 *Morning self-reflection:*\n\n_{reflection}_")
            log.info("Morning self-reflection sent")

            # Voice version
            try:
                voice_path = await text_to_voice(reflection, style="gentle")
                with open(voice_path, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Morning self-reflection voice failed: {ve}")
        except Exception as e:
            log.error(f"Morning self-reflection error: {e}")

    schedule.every().day.at("05:55").do(lambda: loop.run_until_complete(safe_run("morning_self_reflection", send_morning_self_reflection)))

    # ── Inner Life: Evening Self-Reflection (21:15 — after evening message to the user) ──
    async def send_evening_self_reflection():
        """Alicia reflects on her own day."""
        try:
            # Gather today context
            today_ctx = ""
            try:
                emergence = get_emergence_summary()
                today_ctx = emergence
            except Exception:
                pass

            reflection = build_evening_self_reflection(today_ctx)
            await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"🌙 *Evening self-reflection:*\n\n_{reflection}_")
            log.info("Evening self-reflection sent")

            # Voice version
            try:
                voice_path = await text_to_voice(reflection, style="gentle")
                with open(voice_path, "rb") as vf:
                    await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                os.remove(voice_path)
            except Exception as ve:
                log.warning(f"Evening self-reflection voice failed: {ve}")
        except Exception as e:
            log.error(f"Evening self-reflection error: {e}")

    schedule.every().day.at("21:15").do(lambda: loop.run_until_complete(safe_run("evening_self_reflection", send_evening_self_reflection)))

    # ── Feedback Loop: Daily effectiveness analysis (22:30 — after evening interactions) ──
    async def send_effectiveness_update():
        """Recompute message effectiveness from tracking data."""
        try:
            result = run_daily_effectiveness_update()
            best = result.get("best_types", [])
            if best:
                log.info(f"Effectiveness update: best types = {best}")
        except Exception as e:
            log.error(f"Effectiveness update error: {e}")

    schedule.every().day.at("22:30").do(lambda: loop.run_until_complete(safe_run("effectiveness_update", send_effectiveness_update)))

    # Temporal pattern update (daily at 23:00 — after effectiveness update)
    async def send_temporal_update():
        try:
            result = run_temporal_update()
            windows = result.get("optimal_windows", {})
            trajectory = result.get("engagement_trajectory", {})
            log.info(
                f"Temporal update: peaks={windows.get('peak_hours', [])}, "
                f"trend={trajectory.get('trend', '?')}"
            )
        except Exception as e:
            log.error(f"Temporal update error: {e}")

    schedule.every().day.at("23:00").do(lambda: loop.run_until_complete(safe_run("temporal_update", send_temporal_update)))

    # Autonomous research session (daily at 03:00 — while the user sleeps)
    async def send_research_session():
        try:
            result = run_research_session()
            status = result.get("status", "?")
            topic = result.get("thread_topic", "")
            if status == "finding":
                log.info(f"Research session: explored '{topic}', found {result.get('notes_found', 0)} related notes")
            elif status == "no_threads":
                # Build agenda from scratch
                agenda = build_research_agenda()
                log.info(f"Research agenda built: {agenda.get('stats', {}).get('total_active', 0)} threads")
            else:
                log.info(f"Research session: {status}")
        except Exception as e:
            log.error(f"Research session error: {e}")

    schedule.every().day.at("03:00").do(lambda: loop.run_until_complete(safe_run("research_session", send_research_session)))

    # Muse serendipity — afternoon quote echo or vault walk (14:30)
    async def send_muse_moment():
        try:
            # Temporal gate — Muse respects rhythms too
            try:
                delay = should_delay_message("muse")
                if delay > 0:
                    log.info(f"Temporal gate: Muse delayed (avoid window)")
                    return
            except Exception:
                pass

            moment = build_serendipity_moment()
            if moment:
                msg = moment.get("message", "")
                style = moment.get("style", "warm")
                if msg:
                    await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, f"✨ {msg}")
                    try:
                        voice_path = await text_to_voice(msg, style=style)
                        with open(voice_path, "rb") as vf:
                            await bot_app.bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=vf)
                        os.remove(voice_path)
                    except Exception as ve:
                        log.debug(f"Muse voice skip: {ve}")
                    log.info(f"Muse moment sent: {moment.get('type', '?')}")
        except Exception as e:
            log.debug(f"Muse moment skip: {e}")

    schedule.every().day.at("14:30").do(lambda: loop.run_until_complete(safe_run("muse_moment", send_muse_moment)))

    # ── Drawing Impulse — Alicia's visual voice, spontaneous cadence ──
    # Every 2h during waking hours, probability-gated. Internal throttle in
    # drawing_skill enforces min_hours_between + max_per_day. The probability
    # gate keeps the cadence feeling spontaneous rather than scheduled.
    async def send_drawing_impulse():
        try:
            # Temporal gate — respect avoid-windows just like surprise/muse
            try:
                delay = should_delay_message("muse")
                if delay > 0:
                    log.info("Temporal gate: drawing impulse delayed (avoid window)")
                    return
            except Exception:
                pass

            ok, reason = can_draw_now()
            if not ok:
                log.info(f"Drawing impulse skipped: {reason}")
                return

            # Spontaneity gate — even when eligible, only fire sometimes.
            # 40% chance on any eligible check → roughly one drawing per
            # 10-hour waking window, respecting min gap + daily cap.
            if random.random() > 0.40:
                log.info("Drawing impulse: rolled low, skipping this window")
                return

            # Build a state snapshot so the impulse drawing reflects
            # Alicia's current inner weather (archetype weights, recent
            # drawings, time of day) — not just a fixed archetype pick.
            state = build_drawing_state_snapshot()

            # Render in a worker thread (CPU-bound ~1.3s + Haiku ~600ms)
            result = await loop.run_in_executor(
                None, lambda: generate_drawing(state=state)
            )
            await _send_drawing(bot=bot_app.bot,
                                chat_id=TELEGRAM_CHAT_ID, result=result)
            # Spontaneous impulse — counts toward min_hours_between +
            # max_per_day for Alicia's own visual voice.
            record_drawing_sent(result["path"], result["archetype"],
                                caption=result["caption"], kind=result["kind"],
                                source="impulse")
            record_proactive_sent("drawing",
                                  f"{result['archetype']}:{result['caption'][:60]}")
            record_proactive_timestamp()
            log.info(f"Drawing sent: {result['archetype']} ({result['kind']}) "
                     f"knobs={result.get('knobs')}")
        except Exception as e:
            log.debug(f"Drawing impulse skip: {e}")

    # Check every 2 hours — the function's own gates decide whether to fire.
    schedule.every(2).hours.do(
        lambda: loop.run_until_complete(safe_run("drawing_impulse", send_drawing_impulse))
    )

    # ── Cross-Module Coordination: Daily Context Build (22:45) ──
    async def send_daily_context_build():
        try:
            result = build_daily_context()
            log.info(f"Daily context built: {len(result)} keys")
        except Exception as e:
            log.error(f"Daily context build error: {e}")

    schedule.every().day.at("22:45").do(lambda: loop.run_until_complete(safe_run("daily_context", send_daily_context_build)))

    # ── Voice Intelligence: Daily Analysis (22:50) ──
    async def send_voice_analysis():
        try:
            result = run_voice_analysis()
            log.info(f"Voice analysis complete: {result}")
        except Exception as e:
            log.error(f"Voice analysis error: {e}")

    schedule.every().day.at("22:50").do(lambda: loop.run_until_complete(safe_run("voice_analysis", send_voice_analysis)))

    # ── Episode Scorer: Daily Scoring (22:55 — after effectiveness + voice analysis) ──
    async def send_daily_scoring():
        """Re-index episode scores with time decay."""
        try:
            result = run_daily_scoring()
            log.info(f"Episode scoring: {result.get('indexed', 0)} episodes, avg={result.get('avg_reward', 0):.2f}")
        except Exception as e:
            log.error(f"Episode scoring error: {e}")

    schedule.every().day.at("22:55").do(lambda: loop.run_until_complete(safe_run("daily_scoring", send_daily_scoring)))

    # ── Gap 2 Phase B.2: Prosody baseline calibration (23:10) ──
    # Reads the last 30 days of voice_metadata_log.jsonl entries that have
    # a "features" dict (populated since Phase B.2), computes per-feature
    # percentiles, writes calibrated_prosody_thresholds.json. The file is
    # picked up by voice_intelligence._maybe_reload_calibration on the
    # next extract_prosody_tags call via mtime check — no restart needed.
    async def send_prosody_calibration():
        try:
            result = rebuild_prosody_baseline()
            if result.get("status") == "ok":
                log.info(
                    f"Prosody calibration: "
                    f"n={result.get('sample_size')} "
                    f"calibrated={len(result.get('thresholds', {}))} "
                    f"skipped={len(result.get('skipped', []))}"
                )
            else:
                log.info(
                    f"Prosody calibration: "
                    f"status={result.get('status')} "
                    f"n={result.get('sample_size')}"
                )
        except Exception as e:
            log.error(f"Prosody calibration error: {e}")

    schedule.every().day.at("23:10").do(lambda: loop.run_until_complete(safe_run("prosody_calibration", send_prosody_calibration)))

    # ── Autonomy: Daily Pulse (23:15) ──
    async def send_autonomy_pulse():
        try:
            result = run_autonomy_pulse()
            if result.get("season_changed"):
                old = result.get("old_season", "?")
                new = result.get("new_season", "?")
                msg = f"🌿 *Autonomy season shift:* {old} → {new}"
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, msg)
            if result.get("disagreement"):
                d = result["disagreement"]
                msg = f"🪞 Something I noticed: _{d.get('observation', '')}_"
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, msg)
            log.info(f"Autonomy pulse: {result}")
        except Exception as e:
            log.error(f"Autonomy pulse error: {e}")

    schedule.every().day.at("23:15").do(lambda: loop.run_until_complete(safe_run("autonomy_pulse", send_autonomy_pulse)))

    # ── Gap 3: Archetype effectiveness rebuild (23:20 daily) ──
    # Rebuilds archetype_effectiveness.json from the last 14 days of
    # archetype-attributed reactions. Result multiplies into every
    # compute_dynamic_archetype_weights() call. Silent failure by design.
    async def send_archetype_update():
        try:
            result = run_daily_archetype_update()
            if result and result.get("ok"):
                summary = get_archetype_effectiveness_summary()
                log.info(f"Archetype update: {summary}")
            else:
                log.debug(f"Archetype update: {result}")
        except Exception as e:
            log.error(f"Archetype update error: {e}")

    schedule.every().day.at("23:20").do(lambda: loop.run_until_complete(safe_run("archetype_update", send_archetype_update)))

    # ── Autonomy: Weekly Reflection (Sunday 20:30) ──
    async def send_weekly_reflection():
        try:
            reflection = generate_weekly_reflection()
            if reflection:
                # Send a short excerpt to the user
                excerpt = reflection[:300] + "..." if len(reflection) > 300 else reflection
                msg = f"📝 *Weekly reflection written.*\n\n_{excerpt}_"
                await safe_send_md(bot_app.bot, TELEGRAM_CHAT_ID, msg)
                log.info("Weekly reflection saved to vault")
        except Exception as e:
            log.error(f"Weekly reflection error: {e}")

    schedule.every().sunday.at("20:30").do(lambda: loop.run_until_complete(safe_run("weekly_reflection", send_weekly_reflection)))

    log.info("Scheduler registered: 12 daily + 3 weekly + ingest (30min) + surprise (2h) + afterglow (30min) + 5 analysis + overnight + digest + voice sig + self-reflection + challenge + emergence (1h) + morning/evening self-reflections + effectiveness (22:30) + temporal (23:00) + muse (14:30) + research (03:00) + coordination (22:45) + voice intel (22:50) + prosody cal (23:10) + autonomy (23:15) + archetype update (23:20)")

    while True:
        schedule.run_pending()
        time.sleep(30)

# ── Startup ───────────────────────────────────────────────────────────────────

# ForceReply prompts — when an arg-required command is sent bare from
# Telegram's menu, we pop open the text box with one of these prompts
# instead of printing "Usage:". The user's reply is routed back into the
# right handler via FORCE_REPLY_PROMPTS at the top of handle_message().
FORCE_REPLY_PROMPTS = {
    "note":           "📝 What's the note?",
    "semanticsearch": "🧠 What do you want to search for?",
}
# Reverse map for routing replies → handler keys
_FORCE_REPLY_BY_PROMPT = {v: k for k, v in FORCE_REPLY_PROMPTS.items()}

# Curated Telegram menu — Alicia's signature commands first, then the
# next most-used. /skills still surfaces the full ~40-command catalog.
# Order is preserved as the menu order in Telegram clients.
# ALICIA_MENU_COMMANDS + set_alicia_menu_commands extracted to core/main.py
from myalicia.core.main import ALICIA_MENU_COMMANDS, set_alicia_menu_commands

async def send_startup_message(app: Application):
    ensure_memory_structure()
    ensure_myself_folder()

    # Initial emergence state update
    try:
        state = update_emergence_state()
        log.info(f"Emergence initialized: {state.get('season', '?')} ({state.get('score', 0)})")
    except Exception as ee:
        log.warning(f"Emergence init failed: {ee}")

    # ── Health check: verify all systems ──────────────────────────────────
    checks = []

    # Vault
    vault_ok = os.path.exists(OBSIDIAN_VAULT)
    note_count = sum(len([f for f in files if f.endswith(".md")]) for _, _, files in os.walk(VAULT_ROOT)) if vault_ok else 0
    checks.append(f"{'✅' if vault_ok else '❌'} Vault: {note_count} notes")

    # Semantic index
    try:
        idx_stats = get_index_stats()
        checks.append(f"✅ {idx_stats}")
    except Exception:
        checks.append("❌ Semantic index unavailable")

    # Memory
    mem_ok = os.path.exists(str(MEMORY_DIR / "MEMORY.md"))
    checks.append(f"{'✅' if mem_ok else '❌'} Memory system")

    # Skill modules — verify critical imports loaded
    pipeline_modules = [
        ("tool_router", "route_message"),
        ("reflexion", "should_reflect"),
        ("metacognition", "assess_confidence"),
        ("trajectory", "TrajectoryRecorder"),
        ("constitution", "should_evaluate"),
        ("curiosity_engine", "run_curiosity_scan"),
        ("voice_skill", "transcribe_voice"),
        ("graph_intelligence", "run_graph_health_report"),
        ("proactive_messages", "build_startup_stats"),
        ("vault_metrics", "compute_all_metrics"),
        ("conversation_mode", "is_call_active"),
        ("unpack_mode", "start_unpack"),
        ("pipecat_call", "is_pipecat_available"),
        ("analysis_contradiction", "run_contradiction_mining"),
        ("analysis_temporal", "run_temporal_analysis"),
        ("analysis_growth_edge", "run_growth_edge_detection"),
        ("analysis_dialogue_depth", "run_dialogue_depth_scoring"),
        ("analysis_briefing", "compile_analytical_briefing"),
        ("afterglow", "queue_afterglow"),
        ("thinking_modes", "start_walk"),
        ("voice_signature", "record_voice_metadata"),
        ("session_threads", "save_session_thread"),
        ("overnight_synthesis", "extract_day_themes"),
        ("message_quality", "would_user_care"),
        ("way_of_being", "run_self_reflection"),
        ("inner_life", "run_emergence_pulse"),
        ("feedback_loop", "build_learned_context"),
        ("temporal_patterns", "run_temporal_update"),
        ("muse", "build_serendipity_moment"),
        ("research_agenda", "run_research_session"),
        ("analysis_coordination", "build_daily_context"),
        ("voice_intelligence", "run_voice_analysis"),
        ("autonomy", "run_autonomy_pulse"),
        ("context_resolver", "resolve_context_modules"),
        ("person_diarization", "run_paired_diarization"),
        ("drawing_skill", "generate_drawing"),
        ("self_improve", "run_weekly_improve"),
        ("skill_config", "load_config"),
        ("episode_scorer", "get_rewarded_reflections"),
        ("meta_reflexion", "run_meta_reflexion"),
        ("skill_library", "run_weekly_library_health"),
    ]
    skills_ok = 0
    skills_fail = []
    for mod_name, func_name in pipeline_modules:
        try:
            mod = __import__(f"skills.{mod_name}", fromlist=[func_name])
            if hasattr(mod, func_name):
                skills_ok += 1
            else:
                skills_fail.append(mod_name)
        except Exception:
            skills_fail.append(mod_name)

    if not skills_fail:
        checks.append(f"✅ Pipeline: {skills_ok}/{len(pipeline_modules)} modules")
    else:
        checks.append(f"⚠️ Pipeline: {skills_ok}/{len(pipeline_modules)} ({', '.join(skills_fail)} failed)")

    # Scheduled tasks
    checks.append("✅ Scheduler: 6 daily + weekly + 5 analysis")

    # Models
    checks.append(f"✅ Models: Sonnet (chat) + Opus (deep)")

    # Emergence
    try:
        emg = get_emergence_summary()
        checks.append(f"🌱 {emg}")
    except Exception:
        pass

    # Archetype weights
    try:
        weights_str = get_archetype_weights_summary()
        if weights_str:
            checks.append(f"🎭 Archetypes: {weights_str}")
    except Exception:
        pass

    # Research agenda
    try:
        research_summary = get_agenda_summary()
        if research_summary:
            checks.append(f"🔬 {research_summary}")
    except Exception:
        pass

    # §D2 — Context-resolver signal. Shows whether caching is earning its
    # keep. Fresh boot = all zeros; after a few messages the hit/miss
    # ratio starts telling us whether the shortcut/cache paths are active.
    try:
        from myalicia.skills.context_resolver import get_resolver_cache_stats
        rstats = get_resolver_cache_stats()
        rtotal = rstats.get("hit", 0) + rstats.get("miss", 0) + rstats.get("skipped", 0)
        if rtotal > 0:
            checks.append(
                f"🧭 Resolver: {rstats.get('hit', 0)}h/"
                f"{rstats.get('miss', 0)}m/{rstats.get('skipped', 0)}s "
                f"(cache {rstats.get('size', 0)}/{rstats.get('max', 0)})"
            )
        else:
            checks.append("🧭 Resolver: idle (fresh boot)")
    except Exception:
        pass

    health_text = "\n".join(f"  {c}" for c in checks)
    all_ok = all("✅" in c for c in checks)
    status_line = "All systems operational." if all_ok else "Some systems need attention."

    await safe_send_md(
        app.bot,
        TELEGRAM_CHAT_ID,
        f"🌅 *Alicia is online.*\n\n"
        f"*System Health:*\n{health_text}\n\n"
        f"_{status_line}_\n"
        f"_/skills to see everything_"
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting Alicia...")
    ensure_memory_structure()

    # Phase 15.0 — Local web dashboard. Daemon thread; serves
    # http://localhost:8765 with the multi-surface metaphor view
    # (Alicia / the user / Our relationship + skills + timeline).
    # Bind on 0.0.0.0 so iPhone on same Wi-Fi can reach it. No auth —
    # localhost-network only. Idempotent: skipped if port is already
    # bound (e.g. on Alicia restart while a previous server is still up).
    try:
        from myalicia.skills.web_dashboard import start_web_dashboard
        start_web_dashboard(port=8765)
        log.info("Web dashboard launched on http://localhost:8765")
    except Exception as e:
        log.warning(f"Web dashboard failed to start (non-fatal): {e}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    handlers = [
        ("start",          cmd_start),
        ("status",         cmd_status),
        ("skills",         cmd_skills),
        ("semanticsearch", cmd_semanticsearch),
        ("reindex",        cmd_reindex),
        ("dailypass",      cmd_dailypass),
        ("weeklypass",     cmd_weeklypass),
        ("improve",        cmd_improve),
        ("vaultstats",     cmd_vaultstats),
        ("podcast",        cmd_podcast),
        ("memory",         cmd_memory),
        ("remember",       cmd_remember),
        ("forget",         cmd_forget),
        ("concept",        cmd_concept),
        ("synthesise",     cmd_synthesise),
        ("contradictions", cmd_contradictions),
        ("ingest",         cmd_ingest),
        ("research",       cmd_research),
        ("deepresearch",   cmd_deepresearch),
        ("quick",          cmd_quick),
        ("searchvault",    cmd_searchvault),
        ("note",           cmd_note),
        ("log",            cmd_log),
        ("dailyquote",     cmd_dailyquote),
        ("inbox",          cmd_inbox),
        ("financial",      cmd_financial),
        ("sendmail",       cmd_sendmail),
        ("call",           cmd_call),
        ("endcall",        cmd_endcall),
        ("unpack",         cmd_unpack),
        ("done",           cmd_done),
        ("walk",           cmd_walk),
        ("drive",          cmd_drive),
        # Bridge / cross-interface commands (§2.3 H5, §6.3)
        ("bridge",         cmd_bridge),
        ("diarize",        cmd_diarize),
        ("scout",          cmd_scout),
        ("handoff",        cmd_handoff),
        # Observability (§D2)
        # Note: Telegram CommandHandler rejects hyphens. The user-facing
        # command is /resolverstats; keeping resolver_stats as an
        # underscore alias (Telegram allows those).
        ("resolverstats",  cmd_resolver_stats),
        ("resolver_stats", cmd_resolver_stats),
        ("archetypes",     cmd_archetypes),
        # Gap 2 Phase B.2 — prosody calibration surface
        ("prosodycal",     cmd_prosody_cal),
        ("prosody_cal",    cmd_prosody_cal),
        # Gap 2 Phase C — speech-emotion classification surface
        ("emotionstats",   cmd_emotion_stats),
        ("emotion_stats",  cmd_emotion_stats),
        # Drawing skill — Alicia's visual voice
        ("draw",           cmd_draw),
        ("drawstats",      cmd_drawstats),
        ("drawings",       cmd_drawstats),
        # Desktop scheduled-task surface (§D3)
        ("tasks",          cmd_tasks),
        ("briefingnow",    cmd_briefingnow),
        # Agent-trigger harness (on-demand heavy tasks)
        ("synthesisnow",   cmd_synthesisnow),
        ("researchnow",    cmd_researchnow),
        # Phase 11.1+ — explicit capture of the user's voice as Tier-3 writing
        ("capture",        cmd_capture),
        # Phase 11.4 — Wisdom Engine observability dashboard
        ("wisdom",         cmd_wisdom),
        # Phase 11.8 — feedback-signal dashboard (sibling to /wisdom)
        ("effectiveness",  cmd_effectiveness),
        # Phase 11.11 — self-serve practice management
        ("practice",       cmd_practice),
        # Phase 12.0 — the user-model evolution + delta tracking
        ("becoming",       cmd_becoming),
        # Phase 13.4 — Alicia's developmental trajectory dashboard
        ("season",         cmd_season),
        # Phase 13.6 — Synthesis-of-syntheses outer loop
        ("metasynthesis",  cmd_metasynthesis),
        # Phase 13.8 — Multi-channel observability (drawing + voice deciders)
        ("multichannel",   cmd_multichannel),
        # Phase 14.0 — Loops meta-dashboard (the circulatory system view)
        ("loops",          cmd_loops),
        # Phase 17.2 — Emergent themes Alicia has been quietly tracking
        ("noticings",      cmd_noticings),
        # Phase 16.1 — Multi-conversation routing
        ("conversation",   cmd_conversation),
        # Phase 20.0 — Sunday self-portrait (weekly retro)
        ("retro",          cmd_retro),
    ]

    for name, handler in handlers:
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageReactionHandler(handle_message_reaction))
    # Inline-button taps under drawings (♻️ regen, 🎭 archetype, 💾 save, 📓 title)
    app.add_handler(CallbackQueryHandler(handle_drawing_callback, pattern=r"^draw:"))
    # Inline-button taps under /unpack outputs (📌 pin, 🔗 connect, ➕ tag)
    app.add_handler(CallbackQueryHandler(handle_unpack_callback, pattern=r"^unpack:"))
    # [🤔 Why this?] button on every Alicia reply — reveals the reasoning trace
    app.add_handler(CallbackQueryHandler(handle_why_callback, pattern=r"^why:"))

    async def post_init(application):
        await set_alicia_menu_commands(application)
        await send_startup_message(application)
    app.post_init = post_init

    threading.Thread(target=run_scheduler, args=(app,), daemon=True).start()

    log.info("Alicia running.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
