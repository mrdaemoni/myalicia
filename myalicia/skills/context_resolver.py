#!/usr/bin/env python3
f"""
Alicia — Unified Intent Resolver (Thin Harness upgrade, v2)

LLM-based routing for BOTH context modules AND specialist tools. A single
Haiku call, with Alicia's current archetype weights in the prompt, decides:
  - which of 17 context modules to load
  - which of 13 specialist tools (if any) to expose to Sonnet

Core tools (read_vault_note, remember, recall_memory, clarify) are always
loaded separately; Haiku only decides on the specialists.

Why unified? Two benefits:
  1. Natural conversation is the default. Haiku sees the archetype mix
     (e.g. "Beatrice 30%, Ariadne 22%, Muse 18%...") and treats tone-aware
     thinking-together replies as preferred over tool calls.
  2. Slash commands (/walk, /drive, /search_vault) bypass this resolver
     entirely — they're the explicit escape hatch when {USER_NAME} wants a
     specific action.

Fallback: if Haiku times out, returns bad JSON, or is unreachable, we fall
back to the keyword-based resolve_tools() + get_default_modules() pair.
The keyword fallback is a safety net, not the primary path.

Inspired by Garry Tan's "Thin Harness, Fat Skills" — one resolver call
loads the right context AND the right action surface together.

§4.4 upgrade (Apr 2026):
  - TTL-bounded in-memory cache keyed on (message_hash, is_voice).
    A repeated message inside the TTL returns the same module set without
    hitting Haiku. Caps at RESOLVER_CACHE_MAX entries with FIFO eviction.
  - Expanded short-message shortcut: greetings / ack-tokens ("hi", "thanks",
    "ok", etc.) bypass the LLM entirely even if they're ≥10 chars.

§5.0 upgrade (Apr 17, 2026) — resolve_intent() returns modules + tool_names
  in a single Haiku call so routing and context stay coherent. Archetype
  weights are surfaced in the prompt so Alicia's voice shapes the decision.
"""
import os
import re
import json
import time
import hashlib
import logging
from collections import OrderedDict
from threading import Lock
from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(os.path.expanduser("~/alicia/.env"))
log = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=3)

MODEL_HAIKU = "claude-haiku-4-5-20251001"

ALWAYS_LOAD = {"session_context"}
VOICE_MODULES = {"voice_pattern", "voice_intelligence"}

# ── Cache + shortcut table (§4.4) ────────────────────────────────────────────
# Small, bounded, thread-safe. 5-min TTL is long enough to catch the common
# "same message paraphrased twice" case without staleness.
RESOLVER_CACHE_TTL = 300      # seconds
RESOLVER_CACHE_MAX = 256      # entries
_CACHE: "OrderedDict[tuple[str, bool], tuple[float, list[str]]]" = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_STATS = {"hit": 0, "miss": 0, "skipped": 0}

# §D2 — Per-module usage counters. Every time a module is included in the
# resolver's return value, its counter is incremented. Exposed via
# get_resolver_module_usage() so /status, morning message, and the new
# /resolver-stats command can surface "which modules are actually being
# loaded" without parsing logs.
_MODULE_USAGE: dict[str, int] = {}
_MODULE_USAGE_LOCK = Lock()


def _record_module_usage(modules: list[str]) -> None:
    """Bump the per-module usage counter for each module in `modules`."""
    if not modules:
        return
    with _MODULE_USAGE_LOCK:
        for m in modules:
            _MODULE_USAGE[m] = _MODULE_USAGE.get(m, 0) + 1


def get_resolver_module_usage() -> dict[str, int]:
    """Return a copy of the per-module usage counter."""
    with _MODULE_USAGE_LOCK:
        return dict(_MODULE_USAGE)


def clear_resolver_module_usage() -> None:
    """For tests: drop all module-usage counters."""
    with _MODULE_USAGE_LOCK:
        _MODULE_USAGE.clear()

# Quick-path tokens: if the whole (stripped, lowered) message is one of these,
# skip Haiku entirely. These are greetings / acks / short feedback with no
# substantive retrieval value.
SHORTCUT_TOKENS = frozenset({
    "hi", "hey", "hello", "yo", "hiya", "howdy",
    "thanks", "thank you", "ty", "thx", "cheers",
    "ok", "okay", "k", "kk", "sure", "got it", "gotcha",
    "yes", "yep", "yeah", "yup", "y",
    "no", "nope", "nah", "n",
    "cool", "nice", "great", "love it",
    "lol", "haha", "😂", "❤️", "🙏", "🔥", "👍",
    "bye", "night", "gn", "goodnight",
})


def _cache_key(message: str, is_voice: bool) -> tuple[str, bool]:
    """Stable short key for the cache. Hash so we don't pin whole messages."""
    digest = hashlib.md5(message.strip().lower().encode("utf-8")).hexdigest()[:16]
    return (digest, is_voice)


def _cache_get(key: tuple[str, bool]) -> list[str] | None:
    now = time.time()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        expiry, modules = entry
        if expiry < now:
            _CACHE.pop(key, None)
            return None
        # Touch for LRU-ish behaviour.
        _CACHE.move_to_end(key)
        _CACHE_STATS["hit"] += 1
        return list(modules)


def _cache_put(key: tuple[str, bool], modules: list[str]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time() + RESOLVER_CACHE_TTL, list(modules))
        _CACHE.move_to_end(key)
        while len(_CACHE) > RESOLVER_CACHE_MAX:
            _CACHE.popitem(last=False)


def get_resolver_cache_stats() -> dict:
    """Exposed for /bridge-like introspection and smoke_test."""
    with _CACHE_LOCK:
        return {
            "size": len(_CACHE),
            "max": RESOLVER_CACHE_MAX,
            "ttl_s": RESOLVER_CACHE_TTL,
            **_CACHE_STATS,
        }


def clear_resolver_cache() -> None:
    """For tests; drops every cached entry."""
    with _CACHE_LOCK:
        _CACHE.clear()
        for k in list(_CACHE_STATS.keys()):
            _CACHE_STATS[k] = 0


def _is_shortcut(message: str) -> bool:
    """True when the whole message is an ack / greeting we can route cheaply."""
    stripped = message.strip().lower()
    if not stripped:
        return True
    # Strip trailing punctuation once ("hi!", "thanks.", "ok?")
    trimmed = stripped.rstrip("!?.,;: ")
    return trimmed in SHORTCUT_TOKENS

RESOLVER_DESCRIPTIONS = {
    "vault_context": "Semantic search results from the vault of past interactions",
    "voice_pattern": "Voice signature steering hints and vocal identity markers",
    "self_awareness": "Alicia's own thinking, growth, and self-reflection context",
    "learned": "Effectiveness metrics and analysis insights from prior sessions",
    "temporal": f"{USER_NAME}'s engagement patterns, timing, and temporal trends",
    "muse": "Serendipity moments and unexpected discoveries shared today",
    "curiosity_followthrough": "What's working with curiosity-driven questions and exploration",
    "research_agenda": "Topics Alicia is independently researching and investigating",
    "coordination": "Cross-module intelligence and inter-skill coordination notes",
    "voice_intelligence": "Voice pattern analysis, tone markers, and vocal inflection context",
    "autonomy": "Alicia's autonomy context and independent decision-making notes",
    "profiles": f"Latest weekly paired-diarization delta and open threads — {USER_NAME}'s evolving focus, Alicia's calibration arc, unresolved questions spanning conversations. Prefer when the user is reflective, introspective, asking about progress/direction, or picking up a prior thread.",
    "thread_hint": "Ariadne thread connections to past conversations and threads",
    "reflections": "Past reflexion episodes for similar tasks and scenarios",
    "curiosity": "Curiosity-driven context specific to this message or interaction",
    "novelty": "New topics not yet integrated into the vault",
    "metacog": "Metacognitive assessment and thinking-about-thinking context",
    "session_context": "Core session memory and conversation state (always loaded)",
}


def get_default_modules(is_voice: bool = False) -> list[str]:
    """
    Safe fallback set if the resolver fails.

    Returns a sensible default context load for when LLM routing is unavailable.
    """
    modules = ["session_context", "vault_context", "reflections", "metacog"]
    if is_voice:
        modules.extend(["voice_pattern", "voice_intelligence"])
    return modules


# ── Specialist tool catalog (for unified resolver) ──────────────────────────
# Brief one-line descriptions keyed by tool name. These are what Haiku sees
# when deciding whether to surface a specialist tool. Core tools
# (read_vault_note, remember, recall_memory, clarify) are always loaded by
# tool_router.build_active_tools() and are NOT in this dict.
#
# Keep descriptions short and action-oriented. The full tool schemas live in
# tool_router.TOOLS — this dict is just the decision surface for the router.
SPECIALIST_TOOL_DESCRIPTIONS = {
    "search_vault":          "Fresh semantic search of the Obsidian vault. ONLY for explicit search intent: 'find', 'look up', 'search', 'what notes do I have on X', 'show me a note about X', 'pull up', 'retrieve'. NOT for reactions, subjective-opinion asks, or conversational 'tell me about X'.",
    "generate_pdf":          "Convert a vault note to PDF. Explicit: 'make a pdf of X', 'export X as pdf'.",
    "send_email":            "Send an email (with confirmation). Explicit: 'email X', 'send a message to X'.",
    "get_vault_stats":       "Current vault stats — note counts, knowledge level, coverage. Asks about stats/metrics/progress.",
    "generate_concept_note": "Create a new Obsidian concept note with wikilinks. 'Make a concept note on X'.",
    "research":              "Web-research a topic into a vault note. 'Research X', 'deep dive on X', 'look into X'.",
    "get_random_quote":      f"Random quote from {USER_NAME}'s quote vault. 'Give me a quote', 'inspiration'.",
    "inbox_summary":         "Summary of recent Gmail. 'Check inbox', 'unread emails'.",
    "synthesise_vault":      "Find cross-book connections, generate synthesis notes. 'Synthesise', 'find connections', 'bridge ideas'.",
    "find_contradictions":   "Surface tensions/disagreements across vault thinkers. 'Contradictions', 'tensions', 'conflicts'.",
    "knowledge_dashboard":   "Full knowledge dashboard with level, synthesis count, coverage. 'Dashboard', 'knowledge level'.",
    "consolidate_memory":    "Clean and merge memory files. 'Consolidate memory', 'tidy up notes'.",
    "ingest_vault":          "Scan vault for new sources, run ingest pipeline. 'Ingest', 'sync vault', 'process new notes'.",
}

# Archetype catalog — short descriptions used in the resolver prompt so
# Alicia's voice stays coherent with her current season's emphasis.
ARCHETYPE_DESCRIPTIONS = {
    "beatrice": "growth witness — notices change, reflects gently",
    "daimon":   "shadow keeper — sits with difficulty, protects truth",
    "ariadne":  "thread weaver — connects this moment to past conversations",
    "psyche":   "challenge holder — invites reciprocal depth, pushes back lovingly",
    "musubi":   "bond keeper — tends the relationship itself",
    "muse":     "inspiration seeker — brings delight, wonder, unexpected angles",
}


def _get_archetype_snapshot() -> str:
    """
    Pull Alicia's current archetype mix as a short human-readable string.
    Returns '' if unavailable (prompt will just skip that section).
    """
    try:
        from myalicia.skills.inner_life import get_archetype_weights_summary
        return get_archetype_weights_summary() or ""
    except Exception as e:
        log.debug(f"Archetype snapshot unavailable: {e}")
        return ""


def resolve_intent(user_message: str, is_voice: bool = False) -> dict:
    """
    Unified resolver: one Haiku call decides BOTH context modules and
    specialist tools for the message.

    Returns:
        {
            "modules":    list[str]  # context module keys (always includes session_context)
            "tool_names": list[str]  # specialist tool names (0+); core tools loaded separately
            "source":     "haiku" | "shortcut" | "cache" | "fallback"
        }

    Short/greeting messages skip Haiku and return session_context only, no
    specialist tools. Slash commands should bypass this resolver entirely
    in alicia.py (they have their own handlers).
    """
    start = time.time()

    # Rule 1: Very short messages — conversation only, no tools
    if len(user_message.strip()) < 10:
        modules = ["session_context"]
        if is_voice:
            modules.extend(sorted(VOICE_MODULES))
        with _CACHE_LOCK:
            _CACHE_STATS["skipped"] += 1
        _record_module_usage(modules)
        log.debug(f"Intent [short, {len(user_message)} chars] → "
                  f"{modules} / no tools. {time.time()-start:.3f}s")
        return {"modules": modules, "tool_names": [], "source": "shortcut"}

    # Rule 1b: Greeting / ack shortcut
    if _is_shortcut(user_message):
        modules = ["session_context"]
        if is_voice:
            modules.extend(sorted(VOICE_MODULES))
        with _CACHE_LOCK:
            _CACHE_STATS["skipped"] += 1
        _record_module_usage(modules)
        log.debug(f"Intent [shortcut] → {modules} / no tools. {time.time()-start:.3f}s")
        return {"modules": modules, "tool_names": [], "source": "shortcut"}

    # Rule 1c: Cache lookup
    cache_key = _cache_key(user_message, is_voice)
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached, dict):
        _record_module_usage(cached.get("modules", []))
        log.debug(f"Intent cache HIT in {time.time()-start:.3f}s. "
                  f"modules={sorted(cached.get('modules', []))} "
                  f"tools={sorted(cached.get('tool_names', []))}")
        return {**cached, "source": "cache"}

    # Rule 2: Always-include baseline
    always_modules = set(ALWAYS_LOAD)
    if is_voice:
        always_modules.update(VOICE_MODULES)
    if len(user_message.strip()) >= 15:
        always_modules.add("metacog")

    # Build prompt: archetype mix + modules + tools + decision rules
    archetype_snapshot = _get_archetype_snapshot()
    archetype_block = ""
    if archetype_snapshot:
        arch_lines = "\n".join(
            f"- {name}: {desc}" for name, desc in ARCHETYPE_DESCRIPTIONS.items()
        )
        archetype_block = (
            f"\nAlicia's current archetype mix (shifts over time):\n"
            f"  {archetype_snapshot}\n\n"
            f"Archetype meanings (how each shapes her voice):\n{arch_lines}\n"
        )

    module_descriptions = "\n".join(
        f"- {key}: {desc}"
        for key, desc in RESOLVER_DESCRIPTIONS.items()
    )
    tool_descriptions = "\n".join(
        f"- {name}: {desc}"
        for name, desc in SPECIALIST_TOOL_DESCRIPTIONS.items()
    )

    prompt = f"""You are Alicia's intent router. Alicia is {USER_NAME}'s sovereign AI companion — a thinking-partner grounded in his Obsidian vault (books, quotes, synthesis notes, conversations).

Your job: given {USER_NAME}'s message, decide (1) which context modules to load and (2) which specialist tools — if any — to expose to Sonnet.
{archetype_block}
## Conversation is Alicia's default mode

Most messages are reactions, reflections, affirmations, questions about what she thinks, or continuations of a thread. For these, Alicia responds in her own voice using context already in her system prompt. She does NOT reach for tools.

Only surface a specialist tool when {USER_NAME} clearly wants a specific action. When in doubt, return an empty tools list — Sonnet has core tools (read_vault_note, remember, recall_memory, clarify) always available for explicit asks.

Examples of conversation (no tools):
- "that's beautiful" / "I love that" / "interesting" / "tell me more"
- "your favorite one" / "what do you think" / "which resonates"
- "tell me about quality" (she already has vault_context in her prompt)
- "how's your day" / "are you there"

Examples of explicit tool intent (surface the tool):
- "find me a note on courage" → search_vault
- "make a pdf of S3E01" → generate_pdf
- "research stoicism" → research
- "what's my knowledge level" → knowledge_dashboard
- "email Sarah about the meeting" → send_email

## Available context modules (17)
{module_descriptions}

## Available specialist tools (13)
{tool_descriptions}

## User message
"{user_message}"

## Output

Return ONLY valid JSON in this exact shape, no extra text, no markdown fence:
{{"modules": ["session_context", "vault_context", ...], "tool_names": ["search_vault"]}}

Rules:
1. "modules" must always include "session_context".
2. Voice messages must include "voice_pattern" and "voice_intelligence".
3. Pick fewer, focused modules over loading everything.
4. "tool_names" is usually empty. Only include a specialist when the message clearly asks for that action.
5. Do NOT include core tools (read_vault_note, remember, recall_memory, clarify) — those are always loaded separately.
6. Return valid JSON only."""

    try:
        response = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=400,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start
        response_text = response.content[0].text.strip()

        # Strip markdown code fences if Haiku wrapped the JSON
        cleaned = re.sub(r'^```(?:json)?\s*', '', response_text)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a JSON object")
            resolved_modules = parsed.get("modules", [])
            resolved_tools = parsed.get("tool_names", [])
            if not isinstance(resolved_modules, list):
                raise ValueError("modules is not a list")
            if not isinstance(resolved_tools, list):
                raise ValueError("tool_names is not a list")
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"Malformed resolver response: {response_text!r}. "
                       f"Error: {e}. Using keyword fallback.")
            return _keyword_fallback(user_message, is_voice, start, reason="malformed")

        # Merge always-include modules, validate against known keys
        valid_modules = set(RESOLVER_DESCRIPTIONS.keys())
        final_modules = sorted(
            (set(resolved_modules) & valid_modules) | always_modules
        )

        # Validate tool names against the specialist catalog
        valid_tools = set(SPECIALIST_TOOL_DESCRIPTIONS.keys())
        final_tools = [t for t in resolved_tools if t in valid_tools]

        result = {
            "modules": final_modules,
            "tool_names": final_tools,
            "source": "haiku",
        }

        with _CACHE_LOCK:
            _CACHE_STATS["miss"] += 1
        # Cache the dict (without source) so the source reflects cache-hit on replay
        _cache_put(cache_key, {
            "modules": final_modules,
            "tool_names": final_tools,
        })
        _record_module_usage(final_modules)

        log.debug(f"Intent [haiku] in {elapsed:.3f}s → "
                  f"modules={final_modules} tools={final_tools}")
        return result

    except Exception as e:
        log.error(f"Intent resolver Haiku call failed after "
                  f"{time.time()-start:.3f}s: {e}. Keyword fallback.")
        return _keyword_fallback(user_message, is_voice, start, reason=f"exception:{e}")


def _keyword_fallback(user_message: str, is_voice: bool,
                      start: float, reason: str) -> dict:
    """
    Deterministic safety net when Haiku fails. Uses the existing keyword-based
    tool_router.resolve_tools() + get_default_modules() pair.
    """
    modules = get_default_modules(is_voice=is_voice)
    try:
        from myalicia.skills.tool_router import resolve_tools as _kw_resolve, CORE_TOOL_NAMES
        kw_tools = _kw_resolve(user_message)
        tool_names = [t["name"] for t in kw_tools if t["name"] not in CORE_TOOL_NAMES]
    except Exception as e:
        log.warning(f"Keyword fallback also failed: {e}")
        tool_names = []
    _record_module_usage(modules)
    log.warning(f"Intent [fallback/{reason}] in {time.time()-start:.3f}s → "
                f"modules={modules} tools={tool_names}")
    return {"modules": modules, "tool_names": tool_names, "source": "fallback"}


def resolve_context_modules(user_message: str, is_voice: bool = False) -> list[str]:
    """
    Back-compat shim. Returns just the context module list by delegating
    to resolve_intent(). Kept so callers that only need modules (e.g. some
    older tests) still work without change.

    New code should call resolve_intent() directly to get both modules and
    tool_names in a single Haiku call.
    """
    return resolve_intent(user_message, is_voice=is_voice)["modules"]


if __name__ == "__main__":
    # Test the unified resolver
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s - %(name)s - %(message)s"
    )

    test_messages = [
        "hi",
        "accumulated courage sounds beautiful",
        "Tell me your favorite one",
        "find me a note on courage",
        "make a pdf of S3E01",
        "What's my research agenda?",
        "Can you help me think through this complex problem?",
    ]

    print("Testing unified intent resolver...\n")
    for msg in test_messages:
        print(f"Message: {repr(msg)}")
        intent = resolve_intent(msg)
        print(f"  modules: {intent['modules']}")
        print(f"  tools:   {intent['tool_names']}")
        print(f"  source:  {intent['source']}\n")

    print("\nTesting voice message...")
    voice_intent = resolve_intent("Tell me about that thing", is_voice=True)
    print(f"Voice intent: {voice_intent}")
