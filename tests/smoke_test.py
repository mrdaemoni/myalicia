#!/usr/bin/env python3
"""
Alicia Live Smoke Test — zero dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run directly against a live install. No pytest, no pip install needed.

Usage:
    cd /path/to/myalicia
    source .venv/bin/activate
    python tests/smoke_test.py
"""
import os
import sys
import importlib
import traceback
import py_compile
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# ── Setup ───────────────────────────────────────────────────────────────────
# Make sure we can import skills from the project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

PASS = 0
FAIL = 0
SKIP = 0
ERRORS = []


def test(name):
    """Decorator that runs a test function and tracks results."""
    def decorator(fn):
        global PASS, FAIL, SKIP
        try:
            fn()
            PASS += 1
            print(f"  ✅ {name}")
        except AssertionError as e:
            FAIL += 1
            ERRORS.append((name, str(e)))
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            FAIL += 1
            ERRORS.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
        return fn
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
print("\n🔍 Alicia Live Smoke Test")
print("=" * 60)

# ── 1. Critical paths ──────────────────────────────────────────────────────
print("\n📁 Critical Paths")

@test("alicia.py exists")
def _():
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "alicia.py"))

@test("skills/ directory exists")
def _():
    assert os.path.isdir(os.path.join(PROJECT_ROOT, "skills"))

_ALICIA_HOME = os.environ.get("ALICIA_HOME") or os.path.expanduser("~/.alicia")

@test("memory/ directory exists")
def _():
    mem = os.path.join(_ALICIA_HOME, "memory")
    assert os.path.isdir(mem), f"Not found: {mem}"

@test("logs/ directory exists")
def _():
    logs = os.path.join(_ALICIA_HOME, "logs")
    assert os.path.isdir(logs), f"Not found: {logs}"

# ── 2. Memory files ────────────────────────────────────────────────────────
print("\n🧠 Memory Files")

for mf in ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]:
    @test(f"memory/{mf} exists and non-empty")
    def _(filename=mf):
        path = os.path.join(_ALICIA_HOME, "memory", filename)
        assert os.path.isfile(path), f"Missing: {path}"
        assert os.path.getsize(path) > 0, f"Empty: {path}"

# ── 3. Environment variables ───────────────────────────────────────────────
print("\n🔑 Environment Variables")

# Load .env if present (manual, no dotenv dependency)
env_path = os.path.join(os.path.dirname(PROJECT_ROOT), ".env")
if not os.path.exists(env_path):
    env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

for key in ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY"]:
    @test(f"{key} is set")
    def _(k=key):
        val = os.getenv(k)
        assert val is not None, f"Missing env var: {k}"
        assert len(val) > 5, f"Too short"
        assert "fake" not in val.lower(), f"Still has test fake value"

# ── 4. Skill module imports ────────────────────────────────────────────────
print("\n📦 Skill Module Imports")

SKILL_MODULES = [
    "skills.tool_router",
    "skills.memory_skill",
    "skills.proactive_messages",
    "skills.reflexion",
    "skills.constitution",
    "skills.trajectory",
    "skills.metacognition",
    "skills.curiosity_engine",
    "skills.vault_resolver",
    "skills.vault_metrics",
    "skills.vault_intelligence",
    "skills.semantic_search",
    "skills.research_skill",
    "skills.quote_skill",
    "skills.gmail_skill",
    "skills.pdf_skill",
    "skills.voice_skill",
    "skills.graph_intelligence",
    "skills.conversation_mode",
    "skills.unpack_mode",
    "skills.pipecat_call",
    "skills.analysis_contradiction",
    "skills.analysis_temporal",
    "skills.analysis_growth_edge",
    "skills.analysis_dialogue_depth",
    "skills.analysis_briefing",
    "skills.afterglow",
    "skills.thinking_modes",
    "skills.voice_signature",
    "skills.session_threads",
    "skills.overnight_synthesis",
    "skills.message_quality",
    "skills.way_of_being",
    "skills.inner_life",
    "skills.feedback_loop",
    "skills.temporal_patterns",
    "skills.muse",
    "skills.research_agenda",
    # <earlier development> — Apr 20/27 architecture-scout shipments
    "skills.memory_audit",
    "skills.skill_author",
]

for mod_name in SKILL_MODULES:
    @test(f"import {mod_name}")
    def _(m=mod_name):
        mod = importlib.import_module(m)
        assert mod is not None

# ── 5. Tool router wiring ──────────────────────────────────────────────────
print("\n🔧 Tool Router Wiring")

@test("TOOLS list has 10+ tools")
def _():
    from myalicia.skills.tool_router import TOOLS
    assert len(TOOLS) >= 10, f"Only {len(TOOLS)} tools"

@test("Critical tools present (remember, search_vault, send_email, research, read_vault_note, recall_memory)")
def _():
    from myalicia.skills.tool_router import TOOLS
    names = {t["name"] for t in TOOLS}
    expected = {"remember", "search_vault", "send_email", "research", "read_vault_note", "recall_memory"}
    missing = expected - names
    assert not missing, f"Missing: {missing}"

@test("route_message() is callable")
def _():
    from myalicia.skills.tool_router import route_message
    assert callable(route_message)

@test("execute_tool() is callable")
def _():
    from myalicia.skills.tool_router import execute_tool
    assert callable(execute_tool)

# ── 6. Reflexion / Constitution / Trajectory ───────────────────────────────
print("\n🪞 Reflexion & Metacognition")

@test("should_reflect() is callable")
def _():
    from myalicia.skills.reflexion import should_reflect
    assert callable(should_reflect)

@test("should_evaluate() is callable")
def _():
    from myalicia.skills.constitution import should_evaluate
    assert callable(should_evaluate)

@test("TrajectoryRecorder class exists")
def _():
    from myalicia.skills.trajectory import TrajectoryRecorder
    assert TrajectoryRecorder is not None

# ── 7. Proactive messages ──────────────────────────────────────────────────
print("\n📬 Proactive Messages")

@test("build_startup_stats() is callable")
def _():
    from myalicia.skills.proactive_messages import build_startup_stats
    assert callable(build_startup_stats)

@test("build_startup_greeting() is callable")
def _():
    from myalicia.skills.proactive_messages import build_startup_greeting
    assert callable(build_startup_greeting)

# ── 8. Vault system ────────────────────────────────────────────────────────
print("\n📚 Vault System")

@test("resolve_note() is callable")
def _():
    from myalicia.skills.vault_resolver import resolve_note
    assert callable(resolve_note)

@test("determine_level() is callable")
def _():
    from myalicia.skills.vault_metrics import determine_level
    assert callable(determine_level)

@test("format_knowledge_dashboard() is callable")
def _():
    from myalicia.skills.vault_metrics import format_knowledge_dashboard
    assert callable(format_knowledge_dashboard)

# ── 8b. Voice System ──────────────────────────────────────────────────────
print("\n🎧 Voice System")

@test("text_to_voice() accepts style parameter")
def _():
    import inspect
    from myalicia.skills.voice_skill import text_to_voice
    sig = inspect.signature(text_to_voice)
    assert "style" in sig.parameters, "text_to_voice missing 'style' parameter"

@test("text_to_voice_chunked() is callable")
def _():
    from myalicia.skills.voice_skill import text_to_voice_chunked
    assert callable(text_to_voice_chunked)

@test("Gemini TTS is priority backend when GEMINI_API_KEY is set")
def _():
    from myalicia.skills.voice_skill import _detect_tts_backend
    # Reset cached backend to force re-detection
    import myalicia.skills.voice_skill
    skills.voice_skill._tts_backend = None
    backend = _detect_tts_backend()
    assert backend == "gemini", f"Expected 'gemini', got '{backend}'"

@test("VOICE_STYLES dict has all expected styles")
def _():
    from myalicia.skills.voice_skill import VOICE_STYLES
    expected = {"warm", "measured", "excited", "gentle", "default"}
    missing = expected - set(VOICE_STYLES.keys())
    assert not missing, f"Missing styles: {missing}"

@test("alicia.py imports text_to_voice_chunked")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "text_to_voice_chunked" in src

@test("alicia.py midday message sends voice")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert 'Midday voice failed' in src, "Midday message not voice-enabled"

@test("alicia.py evening message sends voice")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert 'Evening voice failed' in src, "Evening message not voice-enabled"

# ── 9. Markdown safety helpers ─────────────────────────────────────────────
print("\n🛡️  Markdown Safety (alicia.py)")

@test("safe_reply_md() present in source")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "async def safe_reply_md(" in src

@test("safe_send_md() present in source")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "async def safe_send_md(" in src

@test("No more than 8 raw parse_mode='Markdown' sends remain")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        lines = f.readlines()
    raw = []
    for i, line in enumerate(lines, 1):
        if 'parse_mode="Markdown"' in line or "parse_mode='Markdown'" in line:
            s = line.strip()
            if "def safe_reply_md" not in s and "def safe_send_md" not in s:
                raw.append((i, s))
    assert len(raw) <= 8, f"Found {len(raw)} raw Markdown sends:\n" + \
        "\n".join(f"  L{n}: {l}" for n, l in raw[:10])

# ── 10. Intelligence pipeline wiring ──────────────────────────────────────
print("\n🧠 Intelligence Pipeline Wiring")

@test("graph_intelligence module imports")
def _():
    mod = importlib.import_module("skills.graph_intelligence")
    assert hasattr(mod, "run_graph_health_report")

@test("route_message accepts model parameter")
def _():
    import inspect
    from myalicia.skills.tool_router import route_message
    sig = inspect.signature(route_message)
    assert "model" in sig.parameters, "route_message missing 'model' parameter"

@test("analyze_trajectories() is callable")
def _():
    from myalicia.skills.trajectory import analyze_trajectories
    assert callable(analyze_trajectories)

@test("consolidate_all_memory() is callable")
def _():
    from myalicia.skills.memory_skill import consolidate_all_memory
    assert callable(consolidate_all_memory)

@test("append_weekly_snapshot() is callable")
def _():
    from myalicia.skills.vault_metrics import append_weekly_snapshot
    assert callable(append_weekly_snapshot)

@test("alicia.py imports graph_intelligence")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.graph_intelligence import" in src

@test("alicia.py imports analyze_trajectories")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.trajectory import analyze_trajectories" in src

@test("alicia.py imports append_weekly_snapshot")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.vault_metrics import append_weekly_snapshot" in src

@test("handle_message has 10-step pipeline")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    checks = [
        "classify_security_level",      # Step 1
        "get_relevant_reflections",      # Step 2
        "assess_confidence",             # Step 3
        "route_message(",                # Step 4
        "execute_tool(",                 # Step 5
        "safe_reply_md(",                # Step 6
        "extract_from_message(",         # Step 7
        "reflect_on_task(",              # Step 8
        "evaluate_output(",              # Step 9
        "detect_novelty(",               # Step 10
    ]
    missing = [c for c in checks if c not in src]
    assert not missing, f"Missing pipeline steps: {missing}"

@test("model escalation passes model to route_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "route_message(system_prompt, windowed, model=model" in src

# ── 10b. Apr 20/27 architecture-scout shipments ───────────────────────────
print("\n🛡️  Memory Audit + Skill Author + Trifecta Gate")

@test("memory_audit: run_memory_audit() callable")
def _():
    from myalicia.skills.memory_audit import run_memory_audit
    assert callable(run_memory_audit)

@test("memory_audit: dry-run produces a summary dict")
def _():
    from myalicia.skills.memory_audit import run_memory_audit
    summary = run_memory_audit(auto_apply=False)
    assert isinstance(summary, dict)
    assert "rules_audited" in summary
    assert "stale_count" in summary
    assert "deprecated_count" in summary

@test("skill_author: list_pending_stubs() callable")
def _():
    from myalicia.skills.skill_author import list_pending_stubs
    assert callable(list_pending_stubs)
    out = list_pending_stubs()
    assert isinstance(out, list)

@test("skill_author: maybe_draft_stub() callable")
def _():
    from myalicia.skills.skill_author import maybe_draft_stub
    assert callable(maybe_draft_stub)

@test("skill_config: append_rule() accepts provenance kwargs")
def _():
    import inspect
    from myalicia.skills.skill_config import append_rule
    sig = inspect.signature(append_rule)
    for kw in ("source_episode_id", "confidence", "last_corroborated"):
        assert kw in sig.parameters, f"{kw} missing from append_rule signature"

@test("skill_config: parse_rule_provenance() round-trips a rule line")
def _():
    from myalicia.skills.skill_config import parse_rule_provenance
    line = (
        "- example rule _(added 2026-04-27 by improve)_ "
        "<!-- src_episode=2026-04-26_103045_search_vault.json "
        "confidence=0.72 last_corroborated=2026-04-27 -->\n"
    )
    prov = parse_rule_provenance(line)
    assert prov["source_episode"] == "2026-04-26_103045_search_vault.json"
    assert prov["confidence"] == 0.72
    assert prov["last_corroborated"] == "2026-04-27"
    assert prov["source"] == "improve"

@test("tool_router: TOOL_SIDE_EFFECT_CLASS classifies large mutations")
def _():
    from myalicia.skills.tool_router import TOOL_SIDE_EFFECT_CLASS, get_side_effect_class
    assert get_side_effect_class("synthesise_vault") == "vault_write_large"
    assert get_side_effect_class("consolidate_memory") == "vault_write_large"
    assert get_side_effect_class("send_email") == "external_send"
    assert get_side_effect_class("get_random_quote") == "none"

@test("alicia.py: vault-write confirmation flow wired")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "pending_vault_write" in src
    assert "confirm_vault_write" in src

@test("alicia.py: memory_audit scheduler entry registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert 'sunday.at("19:50")' in src
    assert "send_memory_audit" in src

@test("proactive_messages: pending stubs surface in startup_stats")
def _():
    with open(
        os.path.join(PROJECT_ROOT, "skills", "proactive_messages.py")
    ) as f:
        src = f.read()
    assert "get_pending_stubs_summary" in src
    assert "get_audit_summary_for_proactive" in src

@test("reflexion: schema includes decision_attribution and responsibility_skill")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "reflexion.py")) as f:
        src = f.read()
    assert "decision_attribution" in src
    assert "responsibility_skill" in src
    assert "responsibility_gap" in src

@test("self_improve: prompt instructs on source_episode_id and confidence")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "self_improve.py")) as f:
        src = f.read()
    assert "source_episode_id" in src
    assert "confidence" in src

@test("LETHAL_TRIFECTA_AUDIT.md exists")
def _():
    path = os.path.join(PROJECT_ROOT, "LETHAL_TRIFECTA_AUDIT.md")
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 1000

@test("skills/configs/memory_audit.md exists")
def _():
    path = os.path.join(
        PROJECT_ROOT, "skills", "configs", "memory_audit.md"
    )
    assert os.path.isfile(path)


# ── 11. Smart Resolver + Resonance ────────────────────────────────────────
print("\n🧭 Smart Resolver + Resonance Tracking")

@test("_resolve_note_for_reading() is callable")
def _():
    from myalicia.skills.tool_router import _resolve_note_for_reading
    assert callable(_resolve_note_for_reading)

@test("_detect_author() recognizes known authors")
def _():
    from myalicia.skills.tool_router import _detect_author
    assert _detect_author("something by alpha") is not None
    assert _detect_author("a beta note") is not None
    assert _detect_author("read me marcus aurelius") is not None

@test("_detect_type_filter() recognizes note types")
def _():
    from myalicia.skills.tool_router import _detect_type_filter
    assert _detect_type_filter("a quote about mastery") == "Quotes"
    assert _detect_type_filter("a synthesis note on quality") == "Synthesis"
    assert _detect_type_filter("something from the book on gumption") == "Books"

@test("_semantic_resolve() is callable")
def _():
    from myalicia.skills.tool_router import _semantic_resolve
    assert callable(_semantic_resolve)

@test("track_resonance() is callable")
def _():
    from myalicia.skills.tool_router import track_resonance
    assert callable(track_resonance)

@test("get_resonance_summary() is callable")
def _():
    from myalicia.skills.tool_router import get_resonance_summary
    assert callable(get_resonance_summary)

@test("RESONANCE_FILE path defined")
def _():
    from myalicia.skills.tool_router import RESONANCE_FILE
    assert "resonance.md" in RESONANCE_FILE

@test("_AUTHOR_ALIASES has entries")
def _():
    from myalicia.skills.tool_router import _AUTHOR_ALIASES
    assert len(_AUTHOR_ALIASES) >= 10, f"Only {len(_AUTHOR_ALIASES)} author aliases"

@test("_search_by_author: surname is a hard filter (Alpha does not match Charlie)")
def _():
    """
    Regression test for the 2026-04-18 'Robert Alpha → Robert Charlie' misfire.
    The author-search stage used to grant its +0.3 bonus on ANY shared token,
    so a note titled 'Robert Charlie' got boosted by the shared 'robert'
    and beat actual Alpha content. The fix requires the surname (last word
    of the canonical name) to appear in path/title/folder.
    """
    import importlib
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)

    # Build fake hits: one Charlie note (high base score, shares only 'robert'),
    # one Alpha note (lower base score, shares the surname).
    fake_hits = [
        {
            "filepath": "/vault/Authors/Robert Charlie.md",
            "title": "Robert Charlie",
            "folder": "Authors",
            "score": 0.75,
        },
        {
            "filepath": "/vault/Books/Alpha-book-by-Alpha.md",
            "title": "Alpha-book (Alpha)",
            "folder": "Books",
            "score": 0.55,
        },
    ]
    # Monkeypatch semantic_search on the module that's imported inside the
    # function (lazy import). Patch both the module attribute and the
    # module it was imported from to be safe.
    import myalicia.skills.semantic_search as ss
    original = ss.semantic_search
    original_is_substantial = tr._is_substantial
    try:
        ss.semantic_search = lambda q, n_results=10, folder_filter=None: fake_hits
        # Also patch in case it was pulled into tr's namespace
        if hasattr(tr, "semantic_search"):
            tr.semantic_search = ss.semantic_search
        # Bypass the on-disk stub filter — these are fake in-memory hits,
        # the file paths don't exist. This test only exercises the surname
        # filter; the stub-filter behaviour has dedicated tests below.
        tr._is_substantial = lambda p: True
        result = tr._search_by_author("Robert Alpha", topic="")
        assert result is not None, (
            "author search should have found Alpha content (the Alpha-book hit "
            "carries the surname); instead got None"
        )
        path, title = result
        assert "alpha" in title.lower() or "alpha" in path.lower(), (
            f"author search returned '{title}' (path={path}) — the "
            f"Charlie hit still beat Alpha. Surname filter is not working."
        )
        assert "charlie" not in title.lower() and "charlie" not in path.lower(), (
            f"Charlie should have been filtered out (no 'alpha' in path/title); "
            f"got '{title}' (path={path})"
        )
    finally:
        ss.semantic_search = original
        tr._is_substantial = original_is_substantial

@test("_search_by_author: returns None when no hit carries surname")
def _():
    """If all hits lack the surname, author search returns None rather than
    picking an unrelated note. Caller falls through to semantic search."""
    import importlib
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)
    import myalicia.skills.semantic_search as ss
    original = ss.semantic_search
    try:
        ss.semantic_search = lambda q, n_results=10, folder_filter=None: [
            {
                "filepath": "/vault/Authors/Robert Charlie.md",
                "title": "Robert Charlie",
                "folder": "Authors",
                "score": 0.8,
            },
            {
                "filepath": "/vault/Authors/Robert Frost.md",
                "title": "Robert Frost",
                "folder": "Authors",
                "score": 0.7,
            },
        ]
        if hasattr(tr, "semantic_search"):
            tr.semantic_search = ss.semantic_search
        result = tr._search_by_author("Robert Alpha", topic="")
        assert result is None, (
            f"No hit contained 'alpha' — _search_by_author should have "
            f"returned None, got {result}"
        )
    finally:
        ss.semantic_search = original

@test("_TYPE_PATTERNS has entries")
def _():
    from myalicia.skills.tool_router import _TYPE_PATTERNS
    assert len(_TYPE_PATTERNS) >= 5, f"Only {len(_TYPE_PATTERNS)} type patterns"

@test("read_vault_note tool description mentions smart retrieval")
def _():
    from myalicia.skills.tool_router import TOOLS
    rtn = [t for t in TOOLS if t["name"] == "read_vault_note"][0]
    assert "author" in rtn["description"].lower(), "Missing author mention in description"
    assert "theme" in rtn["description"].lower(), "Missing theme mention in description"

@test("recall_memory tool exists in TOOLS")
def _():
    from myalicia.skills.tool_router import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "recall_memory" in names, "recall_memory tool not registered"

@test("recall_memory tool description mentions 'remember'")
def _():
    from myalicia.skills.tool_router import TOOLS
    tool = [t for t in TOOLS if t["name"] == "recall_memory"][0]
    desc = tool["description"].lower()
    assert "remember" in desc, "Description doesn't mention 'remember'"
    assert "know about me" in desc, "Description doesn't mention 'know about me'"

@test("Voice reply uses text_to_voice_chunked for long responses")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "text_to_voice_chunked(reply_text" in src, "Voice handler not using chunked TTS for long replies"
    # Ensure the old voice truncation pattern is gone (content[:500] for voice)
    assert 'content"][:500])' not in src, "Old [:500] voice truncation still present"

@test("clarify tool exists in TOOLS")
def _():
    from myalicia.skills.tool_router import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "clarify" in names, "clarify tool not registered"

@test("summarize_memory action handled in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert 'action") == "summarize_memory"' in src, "summarize_memory handler missing"

@test("clarify action handled in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert 'action") == "clarify"' in src, "clarify handler missing"

@test("MAX_TTS_CHARS is 2000 or less")
def _():
    from myalicia.skills.voice_skill import MAX_TTS_CHARS
    assert MAX_TTS_CHARS <= 2000, f"MAX_TTS_CHARS is {MAX_TTS_CHARS}, should be ≤2000"

@test("voice_skill: _resolve_ffmpeg finds ffmpeg on this host")
def _():
    # Regression guard for the <earlier development> launchctl-PATH fix. The Python
    # process must be able to locate ffmpeg even when spawned by launchd
    # with a minimal PATH. The resolver checks current PATH + Homebrew
    # locations + direct file probe.
    from myalicia.skills.voice_skill import _resolve_ffmpeg
    path = _resolve_ffmpeg()
    assert path and os.path.isfile(path), f"ffmpeg not resolved: got {path!r}"
    assert os.access(path, os.X_OK), f"ffmpeg at {path} is not executable"

@test("voice_skill: ffmpeg conversion helpers use resolver, not bare name")
def _():
    # Regression guard: the three conversion functions must call the
    # resolver instead of shelling out to a bare "ffmpeg" command. A bare
    # call fails under launchctl's minimal PATH.
    with open(os.path.join(PROJECT_ROOT, "skills", "voice_skill.py"), 'r') as f:
        src = f.read()
    for fn in ("_ogg_to_wav", "_wav_to_ogg", "_mp3_to_ogg"):
        # Find the function body and make sure it calls _resolve_ffmpeg
        import re as _re
        m = _re.search(rf'def {fn}\(.*?\n(?=def |\Z)', src, _re.DOTALL)
        assert m, f"could not locate {fn}"
        body = m.group(0)
        assert "_resolve_ffmpeg()" in body, (
            f"{fn} must call _resolve_ffmpeg() — found: {body[:300]}"
        )
        assert '["ffmpeg",' not in body, (
            f"{fn} still uses bare 'ffmpeg' string — should use resolved absolute path"
        )

@test("launchctl plist: EnvironmentVariables PATH includes Homebrew")
def _():
    # The plist must set PATH so launchctl-spawned Python can find ffmpeg.
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.alicia.agent.plist")
    if not os.path.isfile(plist_path):
        return  # CI or fresh-install case — skip silently
    with open(plist_path, 'r') as f:
        content = f.read()
    assert "EnvironmentVariables" in content, (
        "plist must define EnvironmentVariables so the launchctl-spawned "
        "Python process inherits a sane PATH"
    )
    assert "/opt/homebrew/bin" in content, (
        "plist PATH must include /opt/homebrew/bin (Apple Silicon Homebrew)"
    )

# ── 11b. Agent-trigger harness ────────────────────────────────────────────
print("\n🚀 Agent-trigger harness")

@test("agent_triggers: module imports cleanly")
def _():
    from myalicia.skills.agent_triggers import (
        trigger, is_running, running_summary, _schedule_send
    )
    assert callable(trigger)
    assert callable(is_running)
    assert callable(running_summary)

@test("agent_triggers: idle state — is_running false, summary empty")
def _():
    from myalicia.skills.agent_triggers import is_running, running_summary, _running
    # Tests may have stale state from earlier tests in this session — clear.
    _running.clear()
    assert is_running("synthesis") is False
    assert running_summary() == []

@test("agent_triggers: trigger rejects concurrent runs with same name")
def _():
    # Two triggers with the same name: second must return (False, ...).
    # We use a short-running fn and a dummy bot/loop that never actually
    # schedules the coroutine — we only care about the lock behaviour.
    import asyncio as _aio
    import time as _time
    from myalicia.skills.agent_triggers import trigger, _running
    _running.clear()

    class _DummyBot:
        async def send_message(self, **kw):
            pass

    loop = _aio.new_event_loop()
    try:
        # First trigger — slow enough that second fires while first is alive.
        started1, ack1 = trigger(
            name="test_concurrent",
            fn=lambda: _time.sleep(0.3),
            fn_args=(),
            bot=_DummyBot(),
            chat_id=0,
            loop=loop,
            format_result=lambda r, d: "done",
            format_started=lambda: "started",
        )
        assert started1 is True, f"First trigger should start: {ack1!r}"

        # Second trigger with same name — must be rejected.
        started2, ack2 = trigger(
            name="test_concurrent",
            fn=lambda: None,
            fn_args=(),
            bot=_DummyBot(),
            chat_id=0,
            loop=loop,
            format_result=lambda r, d: "done",
        )
        assert started2 is False, "Second concurrent trigger must be rejected"
        assert "already running" in ack2, f"Ack should say 'already running': {ack2!r}"

        # Different name — allowed in parallel.
        started3, ack3 = trigger(
            name="test_other",
            fn=lambda: None,
            fn_args=(),
            bot=_DummyBot(),
            chat_id=0,
            loop=loop,
            format_result=lambda r, d: "done",
        )
        assert started3 is True, f"Different-name trigger must run in parallel: {ack3!r}"
    finally:
        # Drain both threads before cleanup.
        for entry in list(_running.values()):
            entry["thread"].join(timeout=2)
        _running.clear()
        loop.close()

@test("agent_triggers: running_summary reports live tasks with elapsed time")
def _():
    import asyncio as _aio
    import time as _time
    from myalicia.skills.agent_triggers import trigger, running_summary, _running
    _running.clear()

    class _DummyBot:
        async def send_message(self, **kw):
            pass

    loop = _aio.new_event_loop()
    try:
        trigger(
            name="test_summary",
            fn=lambda: _time.sleep(0.2),
            fn_args=(),
            bot=_DummyBot(),
            chat_id=0,
            loop=loop,
            format_result=lambda r, d: "done",
            label="summary test",
        )
        snap = running_summary()
        assert any(s["name"] == "test_summary" for s in snap), (
            f"running_summary must include live task, got: {snap}"
        )
        live = next(s for s in snap if s["name"] == "test_summary")
        assert live["label"] == "summary test"
        assert live["elapsed_s"] >= 0
    finally:
        for entry in list(_running.values()):
            entry["thread"].join(timeout=2)
        _running.clear()
        loop.close()

@test("alicia.py: /synthesisnow and /researchnow registered as commands")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert '("synthesisnow",' in src, "/synthesisnow must be registered in handlers list"
    assert '("researchnow",' in src, "/researchnow must be registered in handlers list"
    assert '("briefingnow",' in src, "/briefingnow must remain registered"

@test("alicia.py: cmd_synthesisnow / cmd_researchnow defined")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "async def cmd_synthesisnow(" in src, "cmd_synthesisnow must be defined"
    assert "async def cmd_researchnow(" in src, "cmd_researchnow must be defined"
    assert "async def cmd_briefingnow(" in src, "cmd_briefingnow must remain"

@test("alicia.py: cmd_briefingnow uses agent_trigger harness")
def _():
    # Regression guard: the old run_in_executor flavour of cmd_briefingnow
    # should be gone. The new one routes through agent_trigger for
    # concurrency guard + uniform error reporting.
    import re as _re
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    m = _re.search(
        r'async def cmd_briefingnow\(.*?(?=async def |\Z)',
        src, _re.DOTALL
    )
    assert m, "could not locate cmd_briefingnow"
    body = m.group(0)
    assert "agent_trigger(" in body, (
        "cmd_briefingnow must call agent_trigger() — it's the migration target"
    )

@test("alicia.py: agent_triggers imported with module-level aliases")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "from myalicia.skills.agent_triggers import" in src, (
        "alicia.py must import from myalicia.skills.agent_triggers"
    )
    assert "agent_trigger" in src and "agent_is_running" in src, (
        "alicia.py must expose agent_trigger / agent_is_running aliases for /tasks etc."
    )

# ── 11c. Reaction scorer (Gap 1 — reactions re-score episodes) ────────────
print("\n🔥 Reaction → episode scoring (Gap 1)")

@test("reaction_scorer: module imports")
def _():
    from myalicia.skills.reaction_scorer import (
        track_reply, lookup_reply, emoji_to_outcome,
        score_reply_by_reaction, prune_old_entries, get_stats,
        EMOJI_TO_OUTCOME, DEFAULT_OUTCOME,
    )
    assert callable(track_reply)
    assert callable(score_reply_by_reaction)

@test("reaction_scorer: emoji map covers the expected strong signals")
def _():
    from myalicia.skills.reaction_scorer import EMOJI_TO_OUTCOME
    # Strong positive
    for e in ("🔥", "❤", "🧠", "💡"):
        assert e in EMOJI_TO_OUTCOME, f"{e} must be in EMOJI_TO_OUTCOME"
        success, depth = EMOJI_TO_OUTCOME[e]
        assert success is True and depth >= 4, f"{e} should be strong positive"
    # Negative
    for e in ("👎", "💩", "❌"):
        assert e in EMOJI_TO_OUTCOME, f"{e} must be in EMOJI_TO_OUTCOME"
        success, depth = EMOJI_TO_OUTCOME[e]
        assert success is False, f"{e} should be negative"
    # Ambiguous
    success, _ = EMOJI_TO_OUTCOME["🤔"]
    assert success is None, "🤔 should be ambiguous (success=None)"

@test("reaction_scorer: track_reply + lookup_reply round-trip")
def _():
    import tempfile
    from pathlib import Path
    import myalicia.skills.reaction_scorer as rs
    # Redirect REPLY_INDEX to a tmp file so we don't pollute prod memory.
    with tempfile.TemporaryDirectory() as td:
        original = rs.REPLY_INDEX
        rs.REPLY_INDEX = Path(td) / "reply_index.jsonl"
        try:
            rs.track_reply(
                message_id=12345,
                episode_path="/tmp/fake.json",
                task_type="search_vault",
                reply_timestamp="2026-04-18T12:00:00",
                query_excerpt="find Alpha on quality",
            )
            got = rs.lookup_reply(12345)
            assert got is not None, "lookup_reply should find the tracked entry"
            assert got["task_type"] == "search_vault"
            assert got["episode_path"] == "/tmp/fake.json"
            assert got["query_excerpt"] == "find Alpha on quality"
            # Unknown message_id
            assert rs.lookup_reply(99999) is None
        finally:
            rs.REPLY_INDEX = original

@test("reaction_scorer: score_reply_by_reaction returns no_tracked_reply for unknown msg")
def _():
    import tempfile
    from pathlib import Path
    import myalicia.skills.reaction_scorer as rs
    with tempfile.TemporaryDirectory() as td:
        original = rs.REPLY_INDEX
        rs.REPLY_INDEX = Path(td) / "reply_index.jsonl"
        try:
            out = rs.score_reply_by_reaction(42, "🔥")
            assert out and out.get("action") == "no_tracked_reply", (
                f"Unknown msg_id should return no_tracked_reply, got {out}"
            )
        finally:
            rs.REPLY_INDEX = original

@test("reaction_scorer: ambiguous emoji (🤔) short-circuits without updating episode")
def _():
    import tempfile
    from pathlib import Path
    import myalicia.skills.reaction_scorer as rs
    with tempfile.TemporaryDirectory() as td:
        original = rs.REPLY_INDEX
        rs.REPLY_INDEX = Path(td) / "reply_index.jsonl"
        try:
            rs.track_reply(
                message_id=777,
                episode_path="/tmp/nonexistent.json",
                task_type="remember",
                reply_timestamp="2026-04-18T12:00:00",
            )
            out = rs.score_reply_by_reaction(777, "🤔")
            assert out and out.get("action") == "skipped_ambiguous", (
                f"🤔 should short-circuit as ambiguous, got {out}"
            )
        finally:
            rs.REPLY_INDEX = original

@test("reaction_scorer: prune_old_entries drops stale reply-index rows")
def _():
    import tempfile
    from pathlib import Path
    import myalicia.skills.reaction_scorer as rs
    from datetime import datetime, timedelta
    with tempfile.TemporaryDirectory() as td:
        original = rs.REPLY_INDEX
        rs.REPLY_INDEX = Path(td) / "reply_index.jsonl"
        try:
            # One old entry (60d ago), one fresh.
            old_ts = (datetime.now() - timedelta(days=60)).isoformat()
            fresh_ts = datetime.now().isoformat()
            rs.track_reply(1, "/tmp/old.json", "search_vault", old_ts)
            rs.track_reply(2, "/tmp/new.json", "search_vault", fresh_ts)
            pruned = rs.prune_old_entries(max_age_days=30)
            assert pruned == 1, f"Expected 1 pruned, got {pruned}"
            assert rs.lookup_reply(1) is None, "Old entry should be gone"
            assert rs.lookup_reply(2) is not None, "Fresh entry should survive"
        finally:
            rs.REPLY_INDEX = original

@test("alicia.py: reaction_scorer imports + track_reply wired in background_intelligence")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # Import present
    assert "from myalicia.skills.reaction_scorer import" in src, (
        "alicia.py must import reaction_scorer"
    )
    assert "track_reply_for_reaction" in src, (
        "track_reply_for_reaction alias must be present"
    )
    assert "score_reply_by_reaction" in src, (
        "score_reply_by_reaction must be imported"
    )
    # Wiring: first_reply_msg_id captured at send time
    assert "first_reply_msg_id" in src, (
        "alicia.py must capture first_reply_msg_id at reply-send time"
    )
    # Wiring: track_reply_for_reaction called in background_intelligence
    assert "track_reply_for_reaction(" in src, (
        "track_reply_for_reaction must be called to persist the map"
    )

@test("alicia.py: handle_message_reaction calls score_reply_by_reaction")
def _():
    import re as _re
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    m = _re.search(
        r'async def handle_message_reaction\(.*?(?=^async def |^def |\Z)',
        src, _re.DOTALL | _re.MULTILINE
    )
    assert m, "could not locate handle_message_reaction"
    body = m.group(0)
    assert "score_reply_by_reaction(" in body, (
        "handle_message_reaction must call score_reply_by_reaction so "
        "reactions flow into episode_scorer.record_outcome"
    )

# ── 11b. Daily Signal (Gap 4: shared feedback digest) ─────────────────────
print("\n📡 Daily Signal (Gap 4)")

@test("daily_signal: module imports")
def _():
    from myalicia.skills.daily_signal import (
        record_reaction, record_tool_call, record_episode_scored,
        record_proactive_slot, record_proactive_engagement,
        get_today_signal, get_yesterday_signal, get_signal_summary,
        valence_from_emoji,
    )

@test("daily_signal: valence_from_emoji matches reaction_scorer semantics")
def _():
    from myalicia.skills.daily_signal import valence_from_emoji
    assert valence_from_emoji("🔥") == "positive"
    assert valence_from_emoji("👎") == "negative"
    assert valence_from_emoji("🤔") == "ambiguous"
    # unknown defaults to reaction_scorer's mild positive default
    assert valence_from_emoji("🦄") == "positive"

@test("daily_signal: record_reaction increments counts + event log")
def _():
    import tempfile, importlib
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        ds.record_reaction("🔥", "positive", score_delta=1.5)
        ds.record_reaction("👎", "negative", score_delta=-0.8)
        ds.record_reaction("🤔", "ambiguous")
        sig = ds.get_today_signal()
        assert sig["reactions"]["positive"] == 1
        assert sig["reactions"]["negative"] == 1
        assert sig["reactions"]["ambiguous"] == 1
        assert sig["reactions"]["by_emoji"]["🔥"] == 1
        assert len(sig["events"]) == 3
        assert sig["events"][0]["kind"] == "reaction"

@test("daily_signal: record_tool_call aggregates by tool")
def _():
    import tempfile, importlib
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        ds.record_tool_call("search_vault")
        ds.record_tool_call("search_vault")
        ds.record_tool_call("read_vault_note")
        sig = ds.get_today_signal()
        assert sig["tools"]["calls"] == 3
        assert sig["tools"]["by_tool"]["search_vault"] == 2
        assert sig["tools"]["by_tool"]["read_vault_note"] == 1

@test("daily_signal: record_episode_scored tracks rewarded/punished")
def _():
    import tempfile, importlib
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        ds.record_episode_scored("search_vault", 0.85)  # rewarded
        ds.record_episode_scored("remember", 0.42)       # punished
        ds.record_episode_scored("read_vault_note", 0.6) # neither
        sig = ds.get_today_signal()
        assert sig["episodes"]["scored"] == 3
        assert sig["episodes"]["rewarded"] == 1
        assert sig["episodes"]["punished"] == 1
        assert abs(sig["episodes"]["score_sum"] - (0.85 + 0.42 + 0.6)) < 1e-6

@test("daily_signal: record_proactive_slot + engagement")
def _():
    import tempfile, importlib
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        ds.record_proactive_slot("morning", "greeting")
        ds.record_proactive_slot("midday", "nudge")
        ds.record_proactive_engagement("morning", "🔥", 4)
        sig = ds.get_today_signal()
        assert sig["proactive"]["morning_sent"] is True
        assert sig["proactive"]["midday_sent"] is True
        assert sig["proactive"]["evening_sent"] is False
        assert sig["proactive"]["reactions_received"] == 1
        assert sig["proactive"]["engagement"][0]["emoji"] == "🔥"

@test("daily_signal: get_signal_summary produces human-readable text")
def _():
    import tempfile, importlib
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        # Empty day: empty summary
        assert ds.get_signal_summary() == ""
        # With signals: non-empty summary containing emoji and counts
        ds.record_reaction("🔥", "positive")
        ds.record_reaction("🔥", "positive")
        ds.record_tool_call("search_vault")
        ds.record_episode_scored("search_vault", 0.78)
        s = ds.get_signal_summary("today")
        assert s, "summary should be non-empty when signals exist"
        assert "🔥" in s or "2" in s
        assert "search_vault" in s

@test("daily_signal: rollover stashes prior day to _yesterday + archive")
def _():
    import tempfile, importlib, json as _json
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        import myalicia.skills.daily_signal as ds
        importlib.reload(ds)
        ds.SIGNAL_FILE = Path(td) / "daily_signal.json"
        ds.SIGNAL_ARCHIVE = Path(td) / "daily_signal_archive.jsonl"
        ds.MEMORY_DIR = Path(td)
        # Seed a past-day signal directly
        stale = ds._default_signal()
        stale["date"] = "1999-01-01"
        stale["reactions"]["positive"] = 7
        ds._atomic_write(ds.SIGNAL_FILE, stale)
        # Now load — should trigger rollover
        sig = ds.get_today_signal()
        assert sig["_yesterday"]["date"] == "1999-01-01"
        assert sig["_yesterday"]["reactions"]["positive"] == 7
        assert sig["reactions"]["positive"] == 0
        # And the archive JSONL should have one entry
        assert ds.SIGNAL_ARCHIVE.exists()
        lines = [l for l in ds.SIGNAL_ARCHIVE.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert _json.loads(lines[0])["date"] == "1999-01-01"

@test("alicia.py: daily_signal imports + tool_call wired in handle_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "from myalicia.skills.daily_signal import" in src, (
        "alicia.py must import daily_signal writers"
    )
    assert "signal_record_tool_call(" in src, (
        "handle_message must call signal_record_tool_call so tool usage "
        "flows into today's digest"
    )
    assert "signal_record_reaction(" in src, (
        "handle_message_reaction must call signal_record_reaction so "
        "every reaction feeds the shared daily signal"
    )
    assert "signal_record_proactive_slot(" in src, (
        "morning/midday/evening senders must mark the slot in daily_signal"
    )

@test("episode_scorer.record_outcome wires daily_signal.record_episode_scored")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/episode_scorer.py"), 'r') as f:
        src = f.read()
    assert "record_episode_scored" in src, (
        "record_outcome must emit to daily_signal so reactions AND background "
        "scoring both feed the digest"
    )

@test("proactive_messages: evening + morning read daily_signal")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/proactive_messages.py"), 'r') as f:
        src = f.read()
    assert "describe_today_signal" in src, (
        "evening reflection must be able to reference today's feedback pulse"
    )
    assert "describe_yesterday_signal" in src, (
        "morning greeting must be able to reference yesterday's feedback valence"
    )
    assert "signal_text" in src, (
        "today's signal must be spliced into the evening LLM prompt"
    )

# ── 11d. Cleanup batch (voice-note tracking + remember-vs-read) ───────────
print("\n🧹 Cleanup batch (2026-04-18)")

@test("reflexion: read_vault_note is reflectable")
def _():
    # Without this, no episode gets written for read-aloud calls, so
    # reactions on voice notes have nothing to score.
    from myalicia.skills.reflexion import REFLECTABLE_TASKS, should_reflect
    assert "read_vault_note" in REFLECTABLE_TASKS, (
        "read_vault_note must be in REFLECTABLE_TASKS so the read-aloud path "
        "writes an episode that reactions can later score"
    )
    assert should_reflect("read_vault_note") is True, (
        "should_reflect('read_vault_note') must be True"
    )

@test("tool_router: remember description has first-person + 'remember I' triggers")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/tool_router.py"), 'r') as f:
        src = f.read()
    # Locate the remember tool description block
    import re as _re
    m = _re.search(
        r'"name":\s*"remember".*?"input_schema"',
        src, _re.DOTALL
    )
    assert m, "could not locate remember tool definition"
    desc = m.group(0)
    # New trigger language must be present so Sonnet routes first-person
    # personal observations here, not to read_vault_note.
    assert "remember I" in desc or "remember that I" in desc, (
        "remember description must name the 'remember I / remember that I...' "
        "first-person pattern explicitly"
    )
    assert "moments" in desc.lower() or "observation" in desc.lower(), (
        "remember description must include personal moments/observations, "
        "not just preferences/facts"
    )
    # Exclusion guidance against recall_memory and read_vault_note
    assert "recall_memory" in desc, (
        "remember description should point recall-style requests to recall_memory"
    )

@test("tool_router: read_vault_note has explicit 'remember X' negative guard")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/tool_router.py"), 'r') as f:
        src = f.read()
    import re as _re
    m = _re.search(
        r'"name":\s*"read_vault_note".*?"input_schema"',
        src, _re.DOTALL
    )
    assert m, "could not locate read_vault_note tool definition"
    desc = m.group(0)
    # The negative guard was the direct fix for the 'remember i found the rain
    # beautiful today' → read_vault_note misfire. It must be present.
    assert "remember" in desc.lower(), (
        "read_vault_note description must mention 'remember' in a negative guard"
    )
    assert "NEGATIVE GUARD" in desc or "Do NOT use this tool when the user says" in desc, (
        "read_vault_note description must explicitly steer 'remember X' away"
    )

@test("alicia.py: read_aloud branch tracks voice-note message_ids")
def _():
    import re as _re
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # Pull out the read_aloud handler block up to its return True
    m = _re.search(
        r'if result\.get\("action"\)\s*==\s*"read_aloud":(.*?)return True',
        src, _re.DOTALL
    )
    assert m, "could not locate read_aloud branch in alicia.py"
    branch = m.group(1)
    # Capture list for msg_ids
    assert "read_aloud_msg_ids" in branch, (
        "read_aloud branch must accumulate msg_ids into a list so every "
        "voice note + intro text can be tracked against the same episode"
    )
    # Intro + voice sends must both capture message_ids
    assert "intro_sent" in branch and "voice_sent" in branch, (
        "read_aloud branch must capture return values of both the intro "
        "safe_reply_md and every reply_voice call"
    )
    # Must call track_reply_for_reaction for the tracked ids
    assert "track_reply_for_reaction(" in branch, (
        "read_aloud branch must call track_reply_for_reaction for each msg_id"
    )
    # Must wire reflexion + record_outcome so an episode exists to track against
    assert 'reflect_on_task(' in branch and 'record_outcome(' in branch, (
        "read_aloud branch must reflect + record_outcome so an episode exists "
        "for track_reply_for_reaction to map to"
    )
    # Must run in a background thread so the LLM call doesn't block return
    assert "threading.Thread" in branch, (
        "read_aloud episode tracking must run in a background thread"
    )

# ── 11e. Stub filter + tool-syntax leak fix ───────────────────────────────
print("\n🧱 Stub filter + tool-syntax leak (2026-04-18)")

@test("tool_router: MIN_READABLE_CHARS threshold is set")
def _():
    from myalicia.skills.tool_router import MIN_READABLE_CHARS
    # The threshold must be big enough to reject the 30-byte /Authors/Alpha-book.md
    # stub (~19 speakable chars after _clean_for_tts) but low enough to keep
    # short-but-real content pages.
    assert 50 <= MIN_READABLE_CHARS <= 500, (
        f"MIN_READABLE_CHARS ({MIN_READABLE_CHARS}) outside sensible range"
    )

@test("tool_router: _is_substantial rejects tiny stubs, accepts real notes")
def _():
    import tempfile
    from myalicia.skills.tool_router import _is_substantial
    # Stub: resembles /Authors/Alpha-book.md — title pointer with a wikilink.
    stub_body = "#book by [[Robert M. Alpha]]\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(stub_body)
        stub_path = f.name
    # Real content page — a paragraph of actual speakable prose.
    real_body = (
        "# On Quality\n\n"
        "Quality is neither mind nor matter but a third entity independent "
        "of the two. The Alpha's framework, Alpha argues, is both "
        "more inclusive and more rigorous than the subject-object "
        "metaphysics that has dominated Western thought since the "
        "Enlightenment. What we call reality is a continuous flow of "
        "quality events, each preceding the subject-object split.\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(real_body)
        real_path = f.name
    assert _is_substantial(stub_path) is False, (
        "stub with only a wikilink pointer must be rejected"
    )
    assert _is_substantial(real_path) is True, (
        "a real paragraph of content must pass the stub filter"
    )

@test("tool_router: _semantic_resolve walks hits list past stubs")
def _():
    """The old _semantic_resolve only inspected hits[0]. If hits[0] was a
    stub (short speakable content), the resolver returned the stub and
    produced a 2-second voice note. The fix walks ranked hits past stubs."""
    import tempfile, importlib
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)
    import myalicia.skills.semantic_search as ss

    # Build a stub file + a real file on disk so _is_substantial's real
    # check reflects the fake hits below.
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("#book by [[Robert M. Alpha]]\n")
        stub_path = f.name
    real_body = (
        "# Alpha-book on the Mississippi\n\n"
        "the narrator watched the shoreline slip past. The river, Alpha wrote, "
        "was a kind of continuous Quality event — neither the bank nor the "
        "boat nor even his own thinking, but the dynamic relation between "
        "them. He held the tiller lightly and let the current do most of "
        "the work, knowing that the Alpha's framework started here, "
        "in attention to what actually was.\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(real_body)
        real_path = f.name

    original = ss.semantic_search
    try:
        ss.semantic_search = lambda q, n_results=5, folder_filter=None: [
            {"filepath": stub_path, "title": "Alpha-book", "folder": "Authors", "score": 0.9},
            {"filepath": real_path, "title": "Alpha-book on the Mississippi", "folder": "Books", "score": 0.6},
        ]
        if hasattr(tr, "semantic_search"):
            tr.semantic_search = ss.semantic_search
        result = tr._semantic_resolve("Alpha quality")
        assert result is not None, (
            "_semantic_resolve should have returned the real content hit "
            "once the stub was skipped; got None"
        )
        path, title = result
        assert path == real_path, (
            f"_semantic_resolve returned the stub '{title}' instead of "
            f"walking to the real content page. path={path}"
        )
    finally:
        ss.semantic_search = original

@test("tool_router: _search_by_author skips stubs in ranked list")
def _():
    """_search_by_author must not return a stub at the top of its ranked
    scored list — walk down to a substantial hit."""
    import tempfile, importlib
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)
    import myalicia.skills.semantic_search as ss

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("#book by [[Robert M. Alpha]]\n")
        stub_path = f.name
    real_body = (
        "# Alpha's Book — Chapter 1\n\n"
        "the narrator set out west on a motorcycle with a travelling companion, "
        "with the idea that the mountains and the open road might make a "
        "better framework for thinking about Quality than a classroom "
        "ever could. The first few days were mostly rain and silence, but "
        "by the time they reached the plains the dialogue had begun.\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(real_body)
        real_path = f.name

    original = ss.semantic_search
    try:
        ss.semantic_search = lambda q, n_results=10, folder_filter=None: [
            {"filepath": stub_path, "title": "Alpha-book Alpha stub", "folder": "Authors", "score": 0.9},
            {"filepath": real_path, "title": "Zen and the Art — Alpha", "folder": "Books", "score": 0.7},
        ]
        if hasattr(tr, "semantic_search"):
            tr.semantic_search = ss.semantic_search
        result = tr._search_by_author("Robert Alpha", topic="")
        assert result is not None, (
            "both hits carry surname 'alpha' — _search_by_author must return "
            "the real content page rather than the stub"
        )
        path, title = result
        assert path == real_path, (
            f"_search_by_author returned the stub '{title}'; should have "
            f"walked past it to the real content page. path={path}"
        )
    finally:
        ss.semantic_search = original

@test("alicia.py: reformat prompt does not teach 'Tool X returned:' syntax")
def _():
    """The old reformat prompt used f\"[Tool 'X' returned: ...]\" which
    Sonnet copied verbatim into its reply. The fix removes that pattern."""
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # The leaky pattern must not appear in the format_messages construction.
    # We search for the literal f-string pattern — narrowly, so other
    # mentions in comments are fine.
    bad = "[Tool '{tool_name}' returned:"
    assert bad not in src, (
        "alicia.py still contains the leaky '[Tool X returned:' prompt pattern "
        "that Sonnet reproduced in its reply — rewrite the reformat prompt"
    )

@test("alicia.py: reformat prompt strips tool-call syntax as safety net")
def _():
    """Even with the prompt rewritten, a regex safety net strips any
    'Tool \\'X\\' returned:' residue from the formatted reply."""
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # The strip should run on `reply` after fmt_response, covering both
    # the bracket and naked variants.
    assert "Tool\\s+'[^']+'\\s+returned:" in src, (
        "alicia.py must include a regex safety-net strip for 'Tool X returned:' "
        "residue in the formatted reply"
    )

# ── 11f. Cleanup batch 2 ──────────────────────────────────────────────────
print("\n🧹 Cleanup batch 2 (2026-04-18)")

@test("tool_router: remember value schema warns against context drift")
def _():
    """Regression test for the 2026-04-18 'sound on my face' → 'rain' misfire.
    The remember tool wrote 'rain' into the value because prior conversation
    turns mentioned rain. The schema description must now explicitly steer
    Sonnet to paraphrase the CURRENT message, not context."""
    import re as _re
    with open(os.path.join(PROJECT_ROOT, "skills/tool_router.py"), 'r') as f:
        src = f.read()
    # Pull the remember tool block — needs to include the input_schema.
    m = _re.search(
        r'"name":\s*"remember".*?"required":\s*\[[^\]]+\]',
        src, _re.DOTALL
    )
    assert m, "could not locate remember tool + schema"
    block = m.group(0)
    # value description must now warn against pulling from earlier turns /
    # vault context. Use concrete markers.
    value_hints = [
        "current message",  # must prefer the current turn
        "THIS message",     # capitalised emphasis form used in the patch
    ]
    assert any(hint in block for hint in value_hints), (
        "remember value schema must explicitly tell Sonnet to use the "
        "CURRENT user message, not prior turns — the rain/sound regression "
        "was caused by this missing guidance"
    )
    assert "conversation history" in block or "previous turn" in block.lower(), (
        "remember value schema must explicitly forbid substituting from "
        "conversation history"
    )

@test("_resolve_note_for_reading: rejects low-confidence match on filler-word overlap")
def _():
    """Regression test for 'something by Alpha' → 'How to criticize something
    you disagree with' misfire (score=0.45). The fallback used to accept any
    fuzzy match; the word 'something' alone shouldn't earn attribution.
    """
    import importlib, tempfile
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)
    import myalicia.skills.vault_resolver as vr
    import myalicia.skills.semantic_search as ss

    # Real substantial content file so _is_substantial passes
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(
            "# How to criticize something you disagree with\n\n"
            "A short note on productive disagreement. The aim is to engage "
            "the strongest form of the opposing position, not the weakest. "
            "Steelman before strawman; assume good faith until it's clearly "
            "misplaced. The rest of the note expands on this for a thousand "
            "more words of practical heuristics and examples.\n"
        )
        fake_path = f.name

    original_vr = vr.resolve_note
    original_ss = ss.semantic_search
    original_search_by_author = tr._search_by_author
    original_detect_author = tr._detect_author
    try:
        # Simulate the live failure: vault_resolver finds a 0.45 fuzzy match
        # on the filler word "something".
        def fake_resolve(q):
            return {
                "found": True,
                "path": fake_path,
                "title": "How to criticize something you disagree with",
                "score": 0.45,
                "method": "fuzzy",
            }
        vr.resolve_note = fake_resolve
        # Every other strategy fails
        ss.semantic_search = lambda q, n_results=5, folder_filter=None: []
        tr._search_by_author = lambda author, topic="": None
        tr._detect_author = lambda q: "Robert Alpha"  # author is detected

        path, title = tr._resolve_note_for_reading("something by Alpha")
        assert path is None and title is None, (
            f"low-confidence fallback on the word 'something' should have "
            f"been rejected (no Alpha-related token overlap), got "
            f"'{title}' (path={path})"
        )
    finally:
        vr.resolve_note = original_vr
        ss.semantic_search = original_ss
        tr._search_by_author = original_search_by_author
        tr._detect_author = original_detect_author

@test("_resolve_note_for_reading: accepts low-confidence match with real token overlap")
def _():
    """Guard: the fallback tightening must not break legitimate low-confidence
    name matches. If the title shares a real non-filler word with the query,
    and score >= 0.55, the fallback still fires."""
    import importlib, tempfile
    import myalicia.skills.tool_router as tr
    importlib.reload(tr)
    import myalicia.skills.vault_resolver as vr
    import myalicia.skills.semantic_search as ss

    real_body = (
        "# Beta-book by Nassim Beta\n\n"
        "Beta's key point is that fragility and antifragility are properties "
        "of systems, not statements about them. Systems that gain from "
        "disorder — muscle, immune response, some markets — are antifragile. "
        "The book develops this across a hundred domains, and the rest of "
        f"this note maps the core argument and {USER_NAME}'s reading notes onto it.\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(real_body)
        fake_path = f.name

    original_vr = vr.resolve_note
    original_ss = ss.semantic_search
    original_search_by_author = tr._search_by_author
    original_detect_author = tr._detect_author
    try:
        def fake_resolve(q):
            return {
                "found": True,
                "path": fake_path,
                "title": "Beta-book by Nassim Beta",
                "score": 0.6,
                "method": "fuzzy",
            }
        vr.resolve_note = fake_resolve
        ss.semantic_search = lambda q, n_results=5, folder_filter=None: []
        tr._search_by_author = lambda author, topic="": None
        tr._detect_author = lambda q: None

        # Query shares the real word 'antifragile' with the title.
        path, title = tr._resolve_note_for_reading("something about antifragile")
        assert path == fake_path, (
            f"legitimate low-confidence fallback should still fire on real "
            f"non-filler token overlap ('antifragile'); got '{title}' "
            f"(path={path})"
        )
    finally:
        vr.resolve_note = original_vr
        ss.semantic_search = original_ss
        tr._search_by_author = original_search_by_author
        tr._detect_author = original_detect_author

# ── 11g. Gap 3 — archetype weights respond to prompt effectiveness ────────
print("\n🎭 Gap 3: Archetype weights respond to prompt effectiveness")

@test("inner_life: Gap 3 constants defined with sane values")
def _():
    from myalicia.skills.inner_life import (
        ARCHETYPE_EMA_HALF_LIFE_DAYS,
        ARCHETYPE_MIN_ATTRIBUTIONS,
        ARCHETYPE_CLAMP_LOW,
        ARCHETYPE_CLAMP_HIGH,
        ARCHETYPE_LOG_PATH,
        ARCHETYPE_EFFECTIVENESS_PATH,
    )
    # Agreed policy: 14-day EMA half-life, minimum 5 attributions,
    # moderate clamp [0.7, 1.4]. If these drift, the weight system's
    # responsiveness changes materially — lock them in.
    assert ARCHETYPE_EMA_HALF_LIFE_DAYS == 14
    assert ARCHETYPE_MIN_ATTRIBUTIONS == 5
    assert abs(ARCHETYPE_CLAMP_LOW - 0.7) < 1e-9
    assert abs(ARCHETYPE_CLAMP_HIGH - 1.4) < 1e-9
    assert ARCHETYPE_LOG_PATH.endswith("archetype_log.jsonl")
    assert ARCHETYPE_EFFECTIVENESS_PATH.endswith("archetype_effectiveness.json")

@test("inner_life: Gap 3 functions importable")
def _():
    from myalicia.skills.inner_life import (
        log_archetype_attribution,
        rebuild_archetype_effectiveness,
        get_archetype_effectiveness,
        get_archetype_effectiveness_summary,
        run_daily_archetype_update,
    )
    assert callable(log_archetype_attribution)
    assert callable(rebuild_archetype_effectiveness)
    assert callable(get_archetype_effectiveness)
    assert callable(get_archetype_effectiveness_summary)
    assert callable(run_daily_archetype_update)

@test("inner_life: rebuild_archetype_effectiveness produces per-archetype scores")
def _():
    """End-to-end: log a burst of positive reactions for one archetype and a
    burst of negative for another; rebuild should clamp them in opposite
    directions with score != 1.0 for both."""
    import importlib, tempfile, os as _os, json as _json
    import myalicia.skills.inner_life as il
    importlib.reload(il)

    tmpdir = tempfile.mkdtemp()
    il.MEMORY_DIR = tmpdir
    il.ARCHETYPE_LOG_PATH = _os.path.join(tmpdir, "archetype_log.jsonl")
    il.ARCHETYPE_EFFECTIVENESS_PATH = _os.path.join(tmpdir, "archetype_effectiveness.json")

    # 6 positives for musubi, 6 negatives for daimon — both above the
    # ARCHETYPE_MIN_ATTRIBUTIONS=5 floor.
    for _ in range(6):
        il.log_archetype_attribution("musubi", "🔥", True, 5)
    for _ in range(6):
        il.log_archetype_attribution("daimon", "👎", False, 1)

    result = il.rebuild_archetype_effectiveness()
    assert result and "archetypes" in result
    scores = result["archetypes"]
    musubi_score = scores.get("musubi", {}).get("score", 1.0)
    daimon_score = scores.get("daimon", {}).get("score", 1.0)
    assert musubi_score > 1.05, f"musubi should move up; got {musubi_score}"
    assert daimon_score < 0.95, f"daimon should move down; got {daimon_score}"
    # Clamp respected
    assert il.ARCHETYPE_CLAMP_LOW <= musubi_score <= il.ARCHETYPE_CLAMP_HIGH
    assert il.ARCHETYPE_CLAMP_LOW <= daimon_score <= il.ARCHETYPE_CLAMP_HIGH

@test("inner_life: attribution count below floor holds at 1.00×")
def _():
    """A single reaction shouldn't be enough to shift an archetype's
    effectiveness — we need ARCHETYPE_MIN_ATTRIBUTIONS (5) before the
    score is allowed to move off neutral."""
    import importlib, tempfile, os as _os
    import myalicia.skills.inner_life as il
    importlib.reload(il)

    tmpdir = tempfile.mkdtemp()
    il.MEMORY_DIR = tmpdir
    il.ARCHETYPE_LOG_PATH = _os.path.join(tmpdir, "archetype_log.jsonl")
    il.ARCHETYPE_EFFECTIVENESS_PATH = _os.path.join(tmpdir, "archetype_effectiveness.json")

    # Only 2 attributions — below the floor of 5.
    il.log_archetype_attribution("muse", "🔥", True, 5)
    il.log_archetype_attribution("muse", "🔥", True, 5)

    result = il.rebuild_archetype_effectiveness()
    muse_score = result["archetypes"].get("muse", {}).get("score", 1.0)
    assert abs(muse_score - 1.0) < 1e-9, (
        f"below-floor score should pin to 1.00×; got {muse_score}"
    )

@test("reaction_scorer: score_reply_by_reaction logs archetype when entry has one")
def _():
    """Gap 3 wiring check: when reply_index.jsonl has an archetype for a
    message, scoring a reaction on it must call log_archetype_attribution."""
    import importlib, tempfile, os as _os, json as _json
    import myalicia.skills.reaction_scorer as rs
    import myalicia.skills.inner_life as il
    importlib.reload(rs)
    importlib.reload(il)

    tmpdir = tempfile.mkdtemp()
    rs.MEMORY_DIR = __import__("pathlib").Path(tmpdir)
    rs.REPLY_INDEX = rs.MEMORY_DIR / "reply_index.jsonl"
    il.MEMORY_DIR = tmpdir
    il.ARCHETYPE_LOG_PATH = _os.path.join(tmpdir, "archetype_log.jsonl")
    il.ARCHETYPE_EFFECTIVENESS_PATH = _os.path.join(tmpdir, "archetype_effectiveness.json")

    # Track a reply with archetype="beatrice" (no episode path — proactive).
    rs.track_reply(
        message_id=424242,
        episode_path="",
        task_type="proactive_morning",
        archetype="beatrice",
        query_excerpt="test greeting",
    )
    rs.score_reply_by_reaction(424242, "🔥")

    # archetype_log.jsonl should now contain a beatrice entry.
    assert _os.path.exists(il.ARCHETYPE_LOG_PATH), "archetype log was not written"
    with open(il.ARCHETYPE_LOG_PATH, "r") as f:
        lines = [_json.loads(line) for line in f if line.strip()]
    assert any(line.get("archetype") == "beatrice" for line in lines), (
        f"expected beatrice attribution in archetype log; got {lines}"
    )

@test("proactive_messages: track_proactive_message_id signature accepts archetype")
def _():
    import inspect
    from myalicia.skills.proactive_messages import track_proactive_message_id
    sig = inspect.signature(track_proactive_message_id)
    assert "archetype" in sig.parameters, (
        "track_proactive_message_id must accept archetype kwarg for Gap 3"
    )

@test("alicia.py: all proactive track sites pass archetype")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # Must import the Gap 3 helpers
    assert "run_daily_archetype_update" in src, (
        "alicia.py must import run_daily_archetype_update to register the "
        "23:20 scheduled rebuild"
    )
    assert "get_archetype_effectiveness_summary" in src
    # Must register the scheduled rebuild
    assert 'safe_run("archetype_update"' in src, (
        "alicia.py must schedule the archetype_update job"
    )
    assert 'schedule.every().day.at("23:20")' in src, (
        "archetype update must run daily at 23:20"
    )
    # Every proactive track site should now carry an archetype= kwarg
    assert src.count("track_proactive_message_id") >= 5, (
        "should still have 5+ proactive track call sites"
    )
    # Pattern check: each call either uses archetype=(flavor or {}).get or
    # archetype="<name>" (surprise/challenge).
    import re as _re
    track_calls = _re.findall(
        r"track_proactive_message_id\([^)]*?\)",
        src, _re.DOTALL
    )
    # Filter out the def line inside proactive_messages.py (not in alicia.py) —
    # we're reading alicia.py so only call sites should appear.
    missing = [
        c for c in track_calls
        if "archetype=" not in c
    ]
    assert not missing, (
        f"these track_proactive_message_id calls are missing archetype=: {missing}"
    )

@test("alicia.py: /archetypes command registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "cmd_archetypes" in src, "cmd_archetypes function must exist"
    assert '"archetypes"' in src, "archetypes command must be registered"

# ── 11h. Gap 2 Phase A — wire voice response guidance ────────────────────
print("\n🎤 Gap 2 Phase A: Wire voice response guidance")

@test("voice_intelligence: tone_to_tts_style + format_voice_tone_directive importable")
def _():
    from myalicia.skills.voice_intelligence import (
        tone_to_tts_style,
        format_voice_tone_directive,
        TONE_TO_TTS_STYLE,
    )
    assert callable(tone_to_tts_style)
    assert callable(format_voice_tone_directive)
    assert isinstance(TONE_TO_TTS_STYLE, dict)

@test("voice_intelligence: tone_to_tts_style maps known tones correctly")
def _():
    """Lock the mapping. These 5 tones are the Phase A vocabulary;
    drifting them silently changes how every voice reply sounds."""
    from myalicia.skills.voice_intelligence import tone_to_tts_style
    # deliberate voice → measured TTS (match the reflective register)
    assert tone_to_tts_style("deep and reflective") == "measured"
    # excited voice → excited TTS (mirror the energy)
    assert tone_to_tts_style("energetic and engaged") == "excited"
    # extended voice → measured TTS (he gave room, don't rush)
    assert tone_to_tts_style("threading and elaborative") == "measured"
    # balanced (no voice tags) → warm (Phase A baseline)
    assert tone_to_tts_style("balanced") == "warm"
    assert tone_to_tts_style("warm") == "warm"

@test("voice_intelligence: tone_to_tts_style falls back safely on unknowns")
def _():
    """Phase B tones (whispered / forceful / tender) don't exist yet; the
    mapping must degrade gracefully rather than crash or return None."""
    from myalicia.skills.voice_intelligence import tone_to_tts_style
    assert tone_to_tts_style("") == "warm"
    assert tone_to_tts_style(None) == "warm"
    assert tone_to_tts_style("WHISPERED_NOT_YET_MAPPED") == "warm"
    # Custom default respected
    assert tone_to_tts_style("unknown", default="gentle") == "gentle"

@test("voice_intelligence: format_voice_tone_directive produces a real directive")
def _():
    """When a voice tag fires, the system prompt must gain an explicit
    'match the user's register' instruction — not just the bracketed tag."""
    from myalicia.skills.voice_intelligence import (
        get_voice_response_guidance,
        format_voice_tone_directive,
    )
    # Deliberate voice → long response, deep and reflective tone
    guidance = get_voice_response_guidance(True, ["deliberate"])
    directive = format_voice_tone_directive(guidance)
    assert "deep and reflective" in directive, directive
    assert "long" in directive.lower() or "at length" in directive.lower(), directive
    assert "match" in directive.lower() or "register" in directive.lower(), directive

@test("voice_intelligence: format_voice_tone_directive stays empty on balanced/text")
def _():
    """No tags → no directive (keep the prompt lean)."""
    from myalicia.skills.voice_intelligence import (
        get_voice_response_guidance,
        format_voice_tone_directive,
    )
    # Text message (user_is_voice=False) → empty directive
    text_guidance = get_voice_response_guidance(False, [])
    assert format_voice_tone_directive(text_guidance) == ""
    # Voice message with no tags (middle-band WPM, short duration) → empty
    mid_guidance = get_voice_response_guidance(True, [])
    assert format_voice_tone_directive(mid_guidance) == ""

@test("voice_intelligence: excited tag pulls short response guidance")
def _():
    """Excited voice → short response directive, excited TTS style."""
    from myalicia.skills.voice_intelligence import (
        get_voice_response_guidance,
        format_voice_tone_directive,
        tone_to_tts_style,
    )
    guidance = get_voice_response_guidance(True, ["excited"])
    directive = format_voice_tone_directive(guidance)
    assert "energetic" in directive or "engaged" in directive, directive
    assert "concise" in directive.lower() or "sentence or two" in directive.lower(), directive
    assert tone_to_tts_style(guidance["tone"]) == "excited"

@test("alicia.py: handle_voice calls get_voice_response_guidance")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    # Phase A fixes the dead-code gap — this function had been imported
    # but never called. The regex `name\s*\(` matches actual invocations
    # only; the import line uses a comma after the name, so it won't
    # match. One call in handle_voice is what Phase A needs.
    import re as _re
    call_sites = _re.findall(
        r"get_voice_response_guidance\s*\(",
        src,
    )
    assert len(call_sites) >= 1, (
        f"get_voice_response_guidance must be called in handle_voice, "
        f"not just imported. Found {len(call_sites)} call sites."
    )

@test("alicia.py: handle_voice replaces hardcoded style='warm' with tts_style")
def _():
    """Regression guard: the voice reply TTS site used to hardcode
    style='warm'. Phase A must compute tts_style from voice guidance."""
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "tts_style = tone_to_tts_style" in src, (
        "handle_voice must compute tts_style via tone_to_tts_style"
    )
    # The two previous hardcoded voice-reply style="warm" calls inside
    # handle_voice should now reference the computed variable instead.
    # There remain several hardcoded style="warm" callers elsewhere
    # (call mode, morning greetings, etc.) — those are intentional per
    # Phase A scope. This check targets the voice-reply site by asserting
    # style=tts_style appears.
    assert src.count("style=tts_style") >= 2, (
        "Voice reply TTS must use computed tts_style in both chunked "
        "and single-shot branches"
    )

@test("alicia.py: handle_message accepts voice_guidance kwarg")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "voice_guidance: dict = None" in src, (
        "handle_message signature must accept voice_guidance kwarg"
    )

@test("alicia.py: build_system_prompt accepts voice_guidance kwarg + injects directive")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        src = f.read()
    assert "voice_guidance=None" in src, (
        "build_system_prompt signature must accept voice_guidance"
    )
    assert "## Voice Tone (This Message)" in src, (
        "build_system_prompt must inject the per-message tone section"
    )
    assert "format_voice_tone_directive" in src, (
        "build_system_prompt must call format_voice_tone_directive"
    )

# ── 11i. Gap 2 Phase B — librosa prosody tags ────────────────────────────
print("\n🎤 Gap 2 Phase B: Librosa prosody tags")

@test("voice_intelligence: extract_prosody_tags importable")
def _():
    from myalicia.skills.voice_intelligence import extract_prosody_tags
    assert callable(extract_prosody_tags)

@test("voice_intelligence: Phase B.1.2 constants are defined and locked")
def _():
    from myalicia.skills.voice_intelligence import (
        PROSODY_MIN_AUDIO_SEC, PROSODY_MIN_VOICED_SEC,
        PROSODY_WHISPERED_DEEP_RMS_DBFS, PROSODY_WHISPERED_DEEP_MAX_VOICED_SEC,
        PROSODY_WHISPERED_RMS_DBFS, PROSODY_WHISPERED_PEAK_DBFS,
        PROSODY_FORCEFUL_RMS_DBFS, PROSODY_FORCEFUL_PEAK_DBFS,
        PROSODY_TENDER_RMS_DBFS_MIN, PROSODY_TENDER_RMS_DBFS_MAX,
        PROSODY_TENDER_F0_STDEV_HZ_MAX, PROSODY_TENDER_MIN_VOICED_SEC,
        PROSODY_SILENCE_RMS_DBFS,
        PROSODY_HESITANT_MIN_PAUSE_SEC, PROSODY_HESITANT_MIN_PAUSE_COUNT,
        PROSODY_HESITANT_MAX_PAUSE_COUNT, PROSODY_HESITANT_MAX_PAUSE_SEC,
        PROSODY_HESITANT_MIN_VOICED_SEC,
        PROSODY_TAG_PRIORITY,
    )
    # Gates
    assert PROSODY_MIN_AUDIO_SEC == 1.5
    assert PROSODY_MIN_VOICED_SEC == 0.5
    # Whispered (Phase B.1.2: dual-path — deep-quiet short clip OR composite)
    assert PROSODY_WHISPERED_DEEP_RMS_DBFS == -42.0
    assert PROSODY_WHISPERED_DEEP_MAX_VOICED_SEC == 2.5
    assert PROSODY_WHISPERED_RMS_DBFS == -40.0
    assert PROSODY_WHISPERED_PEAK_DBFS == -32.0
    # Forceful (Phase B.1.2: mean -28 → -34, F0 stdev gate dropped)
    assert PROSODY_FORCEFUL_RMS_DBFS == -34.0
    assert PROSODY_FORCEFUL_PEAK_DBFS == -18.0
    # Tender (Phase B.1.1: peak gate removed, F0 tightened, voiced-sec floor)
    assert PROSODY_TENDER_RMS_DBFS_MIN == -42.0
    assert PROSODY_TENDER_RMS_DBFS_MAX == -33.0
    assert PROSODY_TENDER_F0_STDEV_HZ_MAX == 15.0
    assert PROSODY_TENDER_MIN_VOICED_SEC == 4.0
    # Hesitant (Phase B.1.1: upper count cap, max_pause 1.0 → 1.3, voiced-sec floor)
    assert PROSODY_SILENCE_RMS_DBFS == -40.0
    assert PROSODY_HESITANT_MIN_PAUSE_SEC == 0.6
    assert PROSODY_HESITANT_MIN_PAUSE_COUNT == 2
    assert PROSODY_HESITANT_MAX_PAUSE_COUNT == 3
    assert PROSODY_HESITANT_MAX_PAUSE_SEC == 1.3
    assert PROSODY_HESITANT_MIN_VOICED_SEC == 3.0
    # Priority: hesitant beats tender (pause-structure > close-timbre when both fire)
    assert PROSODY_TAG_PRIORITY == ["whispered", "forceful", "hesitant", "tender"]

@test("voice_intelligence: extract_prosody_tags duration-gates short audio")
def _():
    from myalicia.skills.voice_intelligence import extract_prosody_tags
    # Duration below the 1.5s gate → no librosa call, returns []
    assert extract_prosody_tags("/nonexistent/path.ogg", 0.8) == []
    assert extract_prosody_tags("/nonexistent/path.ogg", 1.0) == []

@test("voice_intelligence: extract_prosody_tags handles missing file gracefully")
def _():
    from myalicia.skills.voice_intelligence import extract_prosody_tags
    # Duration passes the gate but path missing → clean [], no crash
    assert extract_prosody_tags("/nonexistent/path.ogg", 5.0) == []
    assert extract_prosody_tags("", 5.0) == []

@test("voice_intelligence: TONE_TO_TTS_STYLE has Phase B entries")
def _():
    from myalicia.skills.voice_intelligence import TONE_TO_TTS_STYLE, tone_to_tts_style
    assert TONE_TO_TTS_STYLE["quiet and intimate"] == "gentle"
    assert TONE_TO_TTS_STYLE["passionate and forceful"] == "excited"
    assert TONE_TO_TTS_STYLE["tender and close"] == "gentle"
    assert TONE_TO_TTS_STYLE["searching and tentative"] == "measured"
    # Public helper path
    assert tone_to_tts_style("quiet and intimate") == "gentle"
    assert tone_to_tts_style("passionate and forceful") == "excited"
    assert tone_to_tts_style("tender and close") == "gentle"
    assert tone_to_tts_style("searching and tentative") == "measured"

@test("voice_intelligence: prosody tags drive distinct guidance in get_voice_response_guidance")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    # Whispered: intimate register, medium length
    g = get_voice_response_guidance(True, ["whispered"])
    assert g["tone"] == "quiet and intimate"
    assert g["response_length"] == "medium"
    # Forceful: match intensity, short response
    g = get_voice_response_guidance(True, ["forceful"])
    assert g["tone"] == "passionate and forceful"
    assert g["response_length"] == "short"
    # Tender: warmth, medium
    g = get_voice_response_guidance(True, ["tender"])
    assert g["tone"] == "tender and close"
    assert g["response_length"] == "medium"
    # Hesitant: give space — long
    g = get_voice_response_guidance(True, ["hesitant"])
    assert g["tone"] == "searching and tentative"
    assert g["response_length"] == "long"

@test("voice_intelligence: prosody tag displaces WPM tag in guidance when both present")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    # If handle_voice displaces correctly, voice_tags never carries both.
    # But the elif chain in guidance should still pick prosody if it ever does.
    g = get_voice_response_guidance(True, ["tender", "deliberate"])
    assert g["tone"] == "tender and close", (
        f"Expected prosody 'tender' to win over WPM 'deliberate', got {g['tone']}"
    )
    g = get_voice_response_guidance(True, ["forceful", "excited"])
    assert g["tone"] == "passionate and forceful"

@test("voice_intelligence: Phase A tags still work when no prosody tag fires")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    # Phase A regression guard
    g = get_voice_response_guidance(True, ["deliberate"])
    assert g["tone"] == "deep and reflective"
    g = get_voice_response_guidance(True, ["excited"])
    assert g["tone"] == "energetic and engaged"
    g = get_voice_response_guidance(True, ["extended"])
    assert g["tone"] == "threading and elaborative"

@test("alicia.py imports extract_prosody_tags")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    assert "extract_prosody_tags" in src, (
        "alicia.py must import extract_prosody_tags from voice_intelligence"
    )

@test("alicia.py handle_voice computes prosody_tags and displaces voice_tags")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    assert "prosody_tags = extract_prosody_tags(ogg_path, voice_duration)" in src, (
        "handle_voice must call extract_prosody_tags with ogg_path and voice_duration"
    )
    assert "voice_tags = prosody_tags" in src, (
        "handle_voice must displace voice_tags when prosody_tags is non-empty"
    )

# ── 11j. Gap 2 Phase D — voice tone feeds archetype effectiveness ────────
print("\n🎭 Gap 2 Phase D: Voice-informed archetype lens")

@test("voice_intelligence: refined voice→archetype mapping (Phase D)")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    # whispered → Musubi (bond keeper) — was Psyche before Phase D
    assert get_voice_response_guidance(True, ["whispered"])["archetype_hint"] == "Musubi"
    # forceful → Psyche (challenge holder) — was Muse before Phase D
    assert get_voice_response_guidance(True, ["forceful"])["archetype_hint"] == "Psyche"
    # tender → Beatrice, hesitant → Ariadne (unchanged)
    assert get_voice_response_guidance(True, ["tender"])["archetype_hint"] == "Beatrice"
    assert get_voice_response_guidance(True, ["hesitant"])["archetype_hint"] == "Ariadne"
    # WPM-tier fallbacks unchanged: deliberate → Psyche, excited → Muse, extended → Ariadne
    assert get_voice_response_guidance(True, ["deliberate"])["archetype_hint"] == "Psyche"
    assert get_voice_response_guidance(True, ["excited"])["archetype_hint"] == "Muse"
    assert get_voice_response_guidance(True, ["extended"])["archetype_hint"] == "Ariadne"

@test("voice_intelligence: format_archetype_lens_directive importable")
def _():
    from myalicia.skills.voice_intelligence import format_archetype_lens_directive
    assert callable(format_archetype_lens_directive)

@test("voice_intelligence: format_archetype_lens_directive produces a lens directive")
def _():
    from myalicia.skills.voice_intelligence import (
        get_voice_response_guidance,
        format_archetype_lens_directive,
    )
    # Tender voice → Beatrice lens
    guidance = get_voice_response_guidance(True, ["tender"])
    directive = format_archetype_lens_directive(guidance)
    assert "Beatrice" in directive, f"Expected 'Beatrice' in directive, got: {directive!r}"
    assert "growth witness" in directive or "presence" in directive, (
        f"Expected archetype description in directive, got: {directive!r}"
    )

@test("voice_intelligence: format_archetype_lens_directive stays empty on text / balanced")
def _():
    from myalicia.skills.voice_intelligence import (
        get_voice_response_guidance,
        format_archetype_lens_directive,
    )
    # Text messages → no suggest_voice_reply → empty directive
    assert format_archetype_lens_directive(get_voice_response_guidance(False, [])) == ""
    # Empty hint → empty directive
    assert format_archetype_lens_directive({
        "suggest_voice_reply": True, "archetype_hint": "none"
    }) == ""
    # Unknown archetype → empty (defensive)
    assert format_archetype_lens_directive({
        "suggest_voice_reply": True, "archetype_hint": "NotAnArchetype"
    }) == ""

@test("voice_intelligence: lens directive covers all six archetypes")
def _():
    from myalicia.skills.voice_intelligence import format_archetype_lens_directive
    for archetype in ["Beatrice", "Daimon", "Ariadne", "Psyche", "Musubi", "Muse"]:
        directive = format_archetype_lens_directive({
            "suggest_voice_reply": True, "archetype_hint": archetype
        })
        assert archetype in directive, (
            f"Archetype {archetype!r} should appear in its own lens directive, got: {directive!r}"
        )

@test("alicia.py imports format_archetype_lens_directive")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    assert "format_archetype_lens_directive" in src, (
        "alicia.py must import format_archetype_lens_directive from voice_intelligence"
    )

@test("alicia.py build_system_prompt injects Archetype Lens section")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    assert "## Archetype Lens (Voice-Informed)" in src, (
        "build_system_prompt must add an 'Archetype Lens (Voice-Informed)' section"
    )

@test("alicia.py system prompt explicitly steers draw tool usage (Phase 17.6)")
def _():
    # Regression guard: <earlier development> bug — the user said "Make me a drawing of
    # this." Opus had `draw` in CORE_TOOLS but the system prompt's
    # Conversation-default block listed only search_vault and read_vault_note
    # as explicit tool triggers. With "Tools are the exception" steering, Opus
    # responded in prose ("Drawing sent as an image showing flowing lines...")
    # instead of calling the tool. The fix adds an explicit `draw` trigger
    # block telling the model to ALWAYS call draw on drawing requests and
    # NEVER describe a drawing in prose.
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    assert "- draw → ALWAYS call this tool" in src, (
        "system prompt must contain explicit `draw` trigger block — "
        "without it Opus describes drawings in prose instead of rendering"
    )
    assert "make me a drawing of this" in src, (
        "system prompt must list 'make me a drawing of this' phrasing as "
        "an explicit draw trigger (the exact phrasing that regressed)"
    )
    assert 'would look like" in prose' in src, (
        "system prompt must explicitly forbid prose-description of drawings"
    )
    assert "If you wrote prose about" in src and "you failed" in src, (
        "system prompt must contain the 'if you wrote prose, you failed' clause"
    )

@test("alicia.py tracks voice-biased archetype for reaction attribution")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        src = f.read()
    # Phase D: track_reply_for_reaction must receive the archetype for both
    # tool-calling replies (existing call, now augmented) and conversational
    # voice replies (new block below the tool-call branch).
    assert "archetype=_voice_archetype" in src, (
        "alicia.py must pass archetype=_voice_archetype to track_reply_for_reaction"
    )
    assert 'task_type="voice_reply"' in src, (
        "alicia.py must emit a 'voice_reply' task_type for conversational voice replies"
    )


# ── 11k. Gap 2 Phase B.2 — Per-user prosody baseline calibration ─────────
print("\n🎚️  Gap 2 Phase B.2: Per-user prosody calibration")

@test("prosody_calibration: module importable")
def t():
    from myalicia.skills.prosody_calibration import (
        rebuild_prosody_baseline,
        load_calibrated_thresholds,
        compute_percentiles,
        derive_thresholds,
        format_calibration_report,
        THRESHOLD_MAP,
        MIN_SAMPLES,
        CLAMP_PCT,
    )
    assert callable(rebuild_prosody_baseline)
    assert callable(load_calibrated_thresholds)
    assert callable(compute_percentiles)
    assert callable(derive_thresholds)
    assert callable(format_calibration_report)
    assert MIN_SAMPLES >= 20, "need a meaningful bootstrap threshold"
    assert 0 < CLAMP_PCT < 1, "clamp must be a sane fraction"
    assert len(THRESHOLD_MAP) >= 8, "expect every B.1.2 constant covered"

@test("prosody_calibration: compute_percentiles is correct")
def t():
    from myalicia.skills.prosody_calibration import compute_percentiles
    p = compute_percentiles(list(range(1, 11)))  # 1..10
    assert abs(p["p50"] - 5.5) < 1e-6
    assert abs(p["p90"] - 9.1) < 1e-6
    # Empty input degrades gracefully
    z = compute_percentiles([])
    assert z["p50"] == 0.0

@test("prosody_calibration: clamp stays within ± pct of default")
def t():
    from myalicia.skills.prosody_calibration import _clamp, CLAMP_PCT
    # default=-40, width=max(16, 1)=16 → range [-56, -24]
    assert _clamp(-60, -40) == -56, "below floor → clamped"
    assert _clamp(-20, -40) == -24, "above ceiling → clamped"
    assert _clamp(-50, -40) == -50, "inside range → untouched"
    # default=-18, width=max(7.2, 1)=7.2 → range [-25.2, -10.8]
    assert abs(_clamp(-30, -18) - (-25.2)) < 1e-6, "negative default floor"
    # Small default still gets min width 1.0
    assert _clamp(-2, 0.5) == -0.5, "min-width floor applies"

@test("prosody_calibration: hard-coded defaults snapshot captured")
def t():
    from myalicia.skills import voice_intelligence as vi
    assert hasattr(vi, "_HARDCODED_DEFAULTS"), (
        "voice_intelligence must snapshot PROSODY_* constants at import"
    )
    defaults = vi._HARDCODED_DEFAULTS
    assert isinstance(defaults, dict) and defaults
    # Every THRESHOLD_MAP target must exist in the snapshot — otherwise
    # calibration would have no anchor for clamping.
    from myalicia.skills.prosody_calibration import THRESHOLD_MAP
    for constant_name, _, _ in THRESHOLD_MAP:
        assert constant_name in defaults, (
            f"{constant_name} must be in _HARDCODED_DEFAULTS (THRESHOLD_MAP anchor)"
        )

@test("prosody_calibration: rebuild handles missing log gracefully")
def t():
    from myalicia.skills.prosody_calibration import rebuild_prosody_baseline
    import tempfile, os
    missing = os.path.join(tempfile.mkdtemp(prefix="b2_"), "missing.jsonl")
    out = os.path.join(tempfile.mkdtemp(prefix="b2_"), "cal.json")
    r = rebuild_prosody_baseline(path=missing, out_path=out)
    assert r["status"] == "no_log"
    assert r["sample_size"] == 0
    assert not os.path.exists(out), "no file should be written when log is empty"

@test("prosody_calibration: rebuild waits for MIN_SAMPLES")
def t():
    import json, os, tempfile
    from datetime import datetime, timezone
    from myalicia.skills.prosody_calibration import rebuild_prosody_baseline, MIN_SAMPLES
    d = tempfile.mkdtemp(prefix="b2_")
    log = os.path.join(d, "log.jsonl")
    out = os.path.join(d, "cal.json")
    now = datetime.now(timezone.utc).isoformat()
    with open(log, "w") as f:
        for i in range(MIN_SAMPLES - 1):  # one short of the bar
            f.write(json.dumps({
                "timestamp": now,
                "features": {
                    "mean_rms_db": -40.0,
                    "peak_rms_db": -25.0,
                    "f0_stdev_hz": 10.0,
                    "voiced_duration_sec": 4.0,
                    "max_pause_sec": 0.8,
                    "long_pauses": 2.0,
                },
            }) + "\n")
    r = rebuild_prosody_baseline(path=log, out_path=out)
    assert r["status"] == "insufficient_data"
    assert not os.path.exists(out), "must not write calibration below MIN_SAMPLES"

@test("prosody_calibration: rebuild writes clamped thresholds at MIN_SAMPLES")
def t():
    import json, os, tempfile
    from datetime import datetime, timezone
    from myalicia.skills.prosody_calibration import (
        rebuild_prosody_baseline, load_calibrated_thresholds,
        CLAMP_PCT, THRESHOLD_MAP,
    )
    from myalicia.skills import voice_intelligence as vi

    d = tempfile.mkdtemp(prefix="b2_")
    log = os.path.join(d, "log.jsonl")
    out = os.path.join(d, "cal.json")
    now = datetime.now(timezone.utc).isoformat()
    # Synthesize 25 samples spanning realistic ranges so every feature
    # clears MIN_RANGE and every mapped constant gets a calibrated value.
    with open(log, "w") as f:
        for i in range(25):
            f.write(json.dumps({
                "timestamp": now,
                "features": {
                    "mean_rms_db": -44.5 + (i % 12),
                    "peak_rms_db": -30 + (i % 16),
                    "f0_stdev_hz": 7.0 + (i % 9) * 1.5,
                    "voiced_duration_sec": 2.5 + (i % 6) * 0.8,
                    "max_pause_sec": 0.4 + (i % 6) * 0.25,
                    "long_pauses": float(i % 5),
                },
            }) + "\n")

    r = rebuild_prosody_baseline(path=log, out_path=out)
    assert r["status"] == "ok"
    assert r["sample_size"] == 25
    thresholds = r["thresholds"]
    # All 8 mapped constants should be set.
    for name, _, _ in THRESHOLD_MAP:
        assert name in thresholds, f"{name} missing from calibrated output"
        default = vi._HARDCODED_DEFAULTS[name]
        width = max(abs(default) * CLAMP_PCT, 1.0)
        assert default - width - 1e-6 <= thresholds[name] <= default + width + 1e-6, (
            f"{name}={thresholds[name]} violates clamp around default={default}"
        )
    # load_calibrated_thresholds round-trips
    loaded = load_calibrated_thresholds(out)
    for k, v in thresholds.items():
        assert abs(loaded[k] - v) < 1e-6

@test("voice_intelligence: get_latest_prosody_features exposed")
def t():
    from myalicia.skills.voice_intelligence import get_latest_prosody_features
    assert callable(get_latest_prosody_features)
    # Before any extract call the snapshot is empty
    assert isinstance(get_latest_prosody_features(), dict)

@test("voice_intelligence: _maybe_reload_calibration exists and applies thresholds")
def t():
    import json, os
    from myalicia.skills import voice_intelligence as vi

    assert callable(getattr(vi, "_maybe_reload_calibration", None)), (
        "voice_intelligence must expose _maybe_reload_calibration"
    )
    state_before = vi.get_calibration_state()
    assert "applied_count" in state_before
    # Write a calibration file, reload, verify module global overridden.
    cal_path = vi._CALIBRATION_PATH
    os.makedirs(os.path.dirname(cal_path), exist_ok=True)
    backup_existed = os.path.exists(cal_path)
    try:
        backup_content = open(cal_path, "rb").read() if backup_existed else None
        payload = {
            "version": 1,
            "computed_at": "2026-04-19T23:10:00",
            "window_days": 30,
            "sample_size": 25,
            "thresholds": {
                # Inside clamp of default=-40 (range [-56,-24]):
                "PROSODY_WHISPERED_RMS_DBFS": -43.0,
            },
            "skipped": [],
        }
        with open(cal_path, "w") as f:
            json.dump(payload, f)
        # Bump mtime beyond whatever was cached
        import time
        os.utime(cal_path, (time.time() + 5, time.time() + 5))
        vi._maybe_reload_calibration()
        assert vi.PROSODY_WHISPERED_RMS_DBFS == -43.0, (
            "hot-reload must override PROSODY_WHISPERED_RMS_DBFS"
        )
        state_after = vi.get_calibration_state()
        assert state_after["applied_count"] >= 1
    finally:
        # Restore or remove so subsequent runs / production aren't polluted.
        if backup_existed and backup_content is not None:
            with open(cal_path, "wb") as f:
                f.write(backup_content)
        elif os.path.exists(cal_path):
            os.unlink(cal_path)
        # Reset the in-memory override to the hard-coded default so later
        # tests don't see a clamped value.
        vi.PROSODY_WHISPERED_RMS_DBFS = vi._HARDCODED_DEFAULTS["PROSODY_WHISPERED_RMS_DBFS"]

@test("voice_signature: record_voice_metadata accepts features kwarg")
def t():
    import inspect
    from myalicia.skills.voice_signature import record_voice_metadata
    sig = inspect.signature(record_voice_metadata)
    assert "features" in sig.parameters, (
        "record_voice_metadata must accept 'features' for Phase B.2"
    )
    # And it must not be a required positional — must default to None.
    assert sig.parameters["features"].default is None

@test("alicia.py threads prosody features into voice metadata log")
def t():
    src = open("alicia.py").read()
    assert "get_latest_prosody_features" in src, (
        "alicia.py must import and call get_latest_prosody_features"
    )
    assert "features=_prosody_features" in src, (
        "alicia.py must pass features= to record_voice_metadata"
    )

@test("alicia.py registers 23:10 prosody calibration schedule")
def t():
    src = open("alicia.py").read()
    assert 'schedule.every().day.at("23:10")' in src, (
        "prosody calibration must be scheduled at 23:10"
    )
    assert "rebuild_prosody_baseline" in src, (
        "alicia.py must import + invoke rebuild_prosody_baseline"
    )
    assert "prosody cal (23:10)" in src, (
        "scheduler log line must advertise the new task"
    )

@test("alicia.py registers /prosody-cal Telegram command")
def t():
    src = open("alicia.py").read()
    assert "cmd_prosody_cal" in src
    assert '("prosodycal",' in src or '("prosody_cal",' in src, (
        "/prosodycal or /prosody_cal must be registered as a command handler"
    )

@test("bridge_schema: voice_metadata_log allows optional features field")
def t():
    from myalicia.skills.bridge_schema import JSONL_LINE_SCHEMAS
    schema = JSONL_LINE_SCHEMAS.get("voice_metadata_log.jsonl")
    assert schema is not None, "per-line schema must exist"
    props = schema.get("properties", {})
    assert "features" in props, "schema must allow the features sub-object"
    feat_schema = props["features"]
    assert feat_schema.get("type") == "object"
    feat_props = feat_schema.get("properties", {})
    for k in ("mean_rms_db", "peak_rms_db", "f0_stdev_hz",
              "voiced_duration_sec", "max_pause_sec"):
        assert k in feat_props, f"features.{k} must be declared"
    # Pre-B.2 rows (no features) must still validate — features must NOT be required
    required = schema.get("required") or []
    assert "features" not in required, (
        "legacy rows without features must still pass schema validation"
    )


# ── 11l. Gap 2 Phase C — Full speech-emotion classification (background) ─
print("\n🎭 Gap 2 Phase C: Speech-emotion classification (background)")

@test("emotion_model: module importable with all public symbols")
def t():
    from myalicia.skills.emotion_model import (
        classify_emotion,
        record_emotion_entry,
        run_emotion_async,
        load_recent_emotions,
        format_emotion_stats,
        DEFAULT_MODEL,
        EMOTION_LOG_PATH,
        MIN_AUDIO_SEC,
        TARGET_SR,
    )
    assert callable(classify_emotion)
    assert callable(record_emotion_entry)
    assert callable(run_emotion_async)
    assert callable(load_recent_emotions)
    assert callable(format_emotion_stats)
    assert DEFAULT_MODEL and isinstance(DEFAULT_MODEL, str)
    assert TARGET_SR == 16_000, "wav2vec2 superb-er expects 16kHz"
    assert MIN_AUDIO_SEC >= 0.5, "too-short audio must be rejected"
    assert EMOTION_LOG_PATH.endswith("emotion_log.jsonl")

@test("emotion_model: classify_emotion returns None for missing/short audio")
def t():
    from myalicia.skills.emotion_model import classify_emotion
    # Missing file → None, not crash
    assert classify_emotion("/tmp/definitely-not-a-file.ogg") is None
    # Empty path → None
    assert classify_emotion("") is None
    # Too-short duration → None (before any model load)
    assert classify_emotion("/tmp/anything.ogg", duration=0.2) is None

@test("emotion_model: record_emotion_entry shapes the JSONL correctly")
def t():
    import json, os, tempfile
    from myalicia.skills.emotion_model import record_emotion_entry, EMOTION_LOG_PATH
    # Redirect log to a temp file to avoid polluting real memory/
    from myalicia.skills import emotion_model as em
    real_path = em.EMOTION_LOG_PATH
    with tempfile.TemporaryDirectory() as td:
        tmp_path = os.path.join(td, "emotion_log.jsonl")
        em.EMOTION_LOG_PATH = tmp_path
        try:
            record_emotion_entry(
                message_id=12345,
                classification={
                    "label": "hap",
                    "score": 0.87,
                    "all_scores": {"hap": 0.87, "neu": 0.09, "sad": 0.03, "ang": 0.01},
                    "latency_ms": 1234,
                    "model": "superb/wav2vec2-base-superb-er",
                },
                prosody_tags=["whispered"],
                voice_archetype="beatrice",
            )
            with open(tmp_path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert entry["message_id"] == 12345
            assert entry["emotion_label"] == "hap"
            assert entry["emotion_score"] == 0.87
            assert entry["latency_ms"] == 1234
            assert entry["prosody_tags"] == ["whispered"]
            assert entry["voice_archetype"] == "beatrice"
            assert "timestamp" in entry
            assert "all_scores" in entry
        finally:
            em.EMOTION_LOG_PATH = real_path

@test("emotion_model: run_emotion_async swallows all failures silently")
def t():
    from myalicia.skills.emotion_model import run_emotion_async
    # No audio + no pipeline — must not raise. Background threads raising
    # uncaught exceptions would orphan-log and could poison daemon state.
    run_emotion_async(
        audio_path="/tmp/does-not-exist.ogg",
        duration=0.0,
        message_id=1,
        prosody_tags=[],
        voice_archetype=None,
    )  # no raise = pass

@test("emotion_model: load_recent_emotions handles missing log gracefully")
def t():
    from myalicia.skills.emotion_model import load_recent_emotions
    out = load_recent_emotions(days=7, path="/tmp/nonexistent-emotion-log.jsonl")
    assert out == [], "missing log must degrade to empty list, not crash"

@test("emotion_model: format_emotion_stats handles empty log")
def t():
    from myalicia.skills.emotion_model import format_emotion_stats
    import myalicia.skills.emotion_model as em
    real_path = em.EMOTION_LOG_PATH
    em.EMOTION_LOG_PATH = "/tmp/never-there-emotion-log.jsonl"
    try:
        report = format_emotion_stats(days=7)
        assert "Phase C" in report or "emotion" in report.lower()
    finally:
        em.EMOTION_LOG_PATH = real_path

@test("alicia.py threads run_emotion_async in handle_voice (background)")
def t():
    src = open("alicia.py").read()
    assert "from myalicia.skills.emotion_model import" in src, (
        "alicia.py must import from myalicia.skills.emotion_model"
    )
    # At least two occurrences expected: one in the import, one inside
    # handle_voice as the thread target.
    occurrences = [i for i in range(len(src))
                   if src.startswith("run_emotion_async", i)]
    assert len(occurrences) >= 2, (
        "run_emotion_async must appear in both import and handle_voice"
    )
    # The thread MUST be daemon=True — non-daemon would block shutdown if
    # the pipeline is mid-classify at quit. Check that at least ONE
    # occurrence is within 400 chars of both `target=run_emotion_async`
    # usage context AND `daemon=True`.
    found_daemon = False
    for idx in occurrences:
        window = src[max(0, idx - 400): idx + 400]
        if "daemon=True" in window and "threading.Thread" in window:
            found_daemon = True
            break
    assert found_daemon, (
        "run_emotion_async thread must be daemon=True (never block shutdown)"
    )

@test("alicia.py registers /emotion-stats Telegram command")
def t():
    src = open("alicia.py").read()
    assert "cmd_emotion_stats" in src, (
        "cmd_emotion_stats handler must be defined"
    )
    assert '("emotionstats",' in src or '("emotion_stats",' in src, (
        "/emotionstats or /emotion_stats must be registered"
    )
    assert "format_emotion_stats" in src, (
        "format_emotion_stats must be imported for the command"
    )


# ── 12. Vault Ingest Pipeline ─────────────────────────────────────────────
print("\n📥 Vault Ingest Pipeline")

@test("vault_ingest imports")
def _():
    from myalicia.skills.vault_ingest import (
        run_ingest_scan, format_ingest_report, rebuild_index,
        initialize_ingest, append_log, scan_for_new_sources,
        load_ingest_state, save_ingest_state, summarize_source,
        update_synthesis_notes, update_entity_pages, check_contradictions,
        ingest_single_source, format_index_status,
    )

@test("vault_ingest paths are defined")
def _():
    from myalicia.skills.vault_ingest import (
        VAULT_ROOT, INDEX_FILE, LOG_FILE, INGEST_STATE_FILE,
        SOURCE_FOLDERS, INDEX_FOLDERS, SYNTHESIS_DIR,
    )
    assert VAULT_ROOT == str(config.vault.root)
    assert INDEX_FILE.endswith("index.md")
    assert LOG_FILE.endswith("log.md")
    assert len(SOURCE_FOLDERS) >= 8, f"Expected 8+ source folders, got {len(SOURCE_FOLDERS)}"
    assert len(INDEX_FOLDERS) >= 5, f"Expected 5+ index folders, got {len(INDEX_FOLDERS)}"

@test("vault_ingest wired in alicia.py imports")
def _():
    import ast
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        source = f.read()
    assert "from myalicia.skills.vault_ingest import" in source, "vault_ingest not imported in alicia.py"
    assert "run_ingest_scan" in source, "run_ingest_scan not in alicia.py"
    assert "send_ingest_scan" in source, "send_ingest_scan scheduler function not in alicia.py"

@test("ingest_vault tool in TOOLS list")
def _():
    from myalicia.skills.tool_router import TOOLS
    tool_names = [t["name"] for t in TOOLS]
    assert "ingest_vault" in tool_names, f"ingest_vault not in TOOLS: {tool_names}"

@test("ingest_vault tool execution path exists")
def _():
    import ast
    with open(os.path.join(PROJECT_ROOT, "skills", "tool_router.py"), encoding="utf-8") as f:
        source = f.read()
    assert 'tool_name == "ingest_vault"' in source, "No execution branch for ingest_vault in tool_router.py"

@test("ingest scan scheduled every 30 minutes")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), encoding="utf-8") as f:
        source = f.read()
    assert "every(30).minutes" in source, "30-minute ingest scan not scheduled"

@test("scan_for_new_sources returns list")
def _():
    from myalicia.skills.vault_ingest import scan_for_new_sources
    result = scan_for_new_sources(limit=0)
    assert isinstance(result, list), f"Expected list, got {type(result)}"

@test("format_ingest_report handles empty result")
def _():
    from myalicia.skills.vault_ingest import format_ingest_report
    result = format_ingest_report({"new_sources": 0, "reports": [], "total_pages_touched": 0, "duration_sec": 0.1})
    assert "no new sources" in result.lower(), f"Empty report should mention no sources: {result}"

@test("rebuild_index callable")
def _():
    from myalicia.skills.vault_ingest import rebuild_index
    assert callable(rebuild_index)

# ── 13. Voice Conversation Mode ──────────────────────────────────────────
print("\n📞 Voice Conversation Mode")

@test("conversation_mode imports")
def _():
    from myalicia.skills.conversation_mode import (
        is_call_active, start_call, end_call,
        get_call_system_prompt, process_call_message,
        record_call_response, detect_exit_intent,
        CALL_MAX_TOKENS,
    )

@test("is_call_active() returns bool")
def _():
    from myalicia.skills.conversation_mode import is_call_active
    result = is_call_active()
    assert isinstance(result, bool)

@test("start_call() returns greeting string")
def _():
    from myalicia.skills.conversation_mode import start_call, end_call, is_call_active
    greeting = start_call()
    assert isinstance(greeting, str)
    assert len(greeting) > 0
    assert is_call_active()
    end_call()  # Clean up
    assert not is_call_active()

@test("detect_exit_intent() catches exit phrases")
def _():
    from myalicia.skills.conversation_mode import detect_exit_intent
    assert detect_exit_intent("goodbye") == True
    assert detect_exit_intent("end call") == True
    assert detect_exit_intent("tell me about quality") == False

@test("CALL_MAX_TOKENS is reasonable")
def _():
    from myalicia.skills.conversation_mode import CALL_MAX_TOKENS
    assert 100 <= CALL_MAX_TOKENS <= 500, f"CALL_MAX_TOKENS={CALL_MAX_TOKENS}"

@test("alicia.py imports conversation_mode")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.conversation_mode import" in src

@test("/call and /endcall commands registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert '"call"' in src or "'call'" in src
    assert '"endcall"' in src or "'endcall'" in src

# ── 13b. Unpack Mode ────────────────────────────────────────────────────
print("\n📦 Unpack Mode")

@test("unpack_mode imports")
def _():
    from myalicia.skills.unpack_mode import (
        is_unpack_active, start_unpack, end_unpack,
        accumulate_voice, accumulate_text, get_transcript,
        detect_done_intent, build_probe_prompt, build_extraction_prompt,
        save_vault_note, save_transcript_log,
    )

@test("start_unpack() returns greeting")
def _():
    from myalicia.skills.unpack_mode import start_unpack, end_unpack, is_unpack_active
    greeting = start_unpack("test topic")
    assert isinstance(greeting, str)
    assert is_unpack_active()
    end_unpack()  # Clean up
    assert not is_unpack_active()

@test("accumulate_voice() works")
def _():
    from myalicia.skills.unpack_mode import start_unpack, end_unpack, accumulate_voice, get_word_count
    start_unpack()
    accumulate_voice("This is a test monologue about quality and mastery")
    assert get_word_count() > 0
    end_unpack()

@test("detect_done_intent() catches exit phrases")
def _():
    from myalicia.skills.unpack_mode import detect_done_intent
    assert detect_done_intent("that's it") == True
    assert detect_done_intent("I'm done") == True
    assert detect_done_intent("tell me more about quality") == False

@test("alicia.py imports unpack_mode")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.unpack_mode import" in src

@test("/unpack and /done commands registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert '"unpack"' in src or "'unpack'" in src
    assert '"done"' in src or "'done'" in src

@test("unpack text triggers in handle_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "UNPACK_TRIGGERS" in src

# ── 13c. Pipecat Call ───────────────────────────────────────────────────
print("\n🔊 Pipecat Call")

@test("pipecat_call imports")
def _():
    from myalicia.skills.pipecat_call import (
        is_pipecat_available, is_pipecat_call_active,
        get_active_room_url, get_setup_instructions,
    )

@test("is_pipecat_available() returns bool")
def _():
    from myalicia.skills.pipecat_call import is_pipecat_available
    result = is_pipecat_available()
    assert isinstance(result, bool)

@test("get_setup_instructions() returns string")
def _():
    from myalicia.skills.pipecat_call import get_setup_instructions
    instructions = get_setup_instructions()
    assert "pipecat" in instructions.lower()
    assert "DAILY_API_KEY" in instructions

@test("alicia.py imports pipecat_call")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.pipecat_call import" in src

@test("cmd_call tries Pipecat before fallback")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "is_pipecat_available()" in src
    assert "start_pipecat_session" in src

# ── 13d. Way of Being ───────────────────────────────────────────────────
print("\n✨ Way of Being")

@test("way_of_being: run_self_reflection is callable")
def _():
    from myalicia.skills.way_of_being import run_self_reflection
    assert callable(run_self_reflection)

@test("way_of_being: get_daimon_warning is callable")
def _():
    from myalicia.skills.way_of_being import get_daimon_warning
    assert callable(get_daimon_warning)

@test("way_of_being: get_pending_challenge is callable")
def _():
    from myalicia.skills.way_of_being import get_pending_challenge
    assert callable(get_pending_challenge)

@test("way_of_being: build_musubi_reflection is callable")
def _():
    from myalicia.skills.way_of_being import build_musubi_reflection
    assert callable(build_musubi_reflection)

@test("way_of_being: build_self_awareness_context is callable")
def _():
    from myalicia.skills.way_of_being import build_self_awareness_context
    assert callable(build_self_awareness_context)

@test("way_of_being: record_depth_signal is callable")
def _():
    from myalicia.skills.way_of_being import record_depth_signal
    assert callable(record_depth_signal)

# ── 14. Autonomous Analysis Modules (Option B) ──────────────────────────
print("\n📊 Autonomous Analysis Modules")

ANALYSIS_MODULES = [
    ("skills.analysis_contradiction", "run_contradiction_mining"),
    ("skills.analysis_temporal", "run_temporal_analysis"),
    ("skills.analysis_growth_edge", "run_growth_edge_detection"),
    ("skills.analysis_dialogue_depth", "run_dialogue_depth_scoring"),
    ("skills.analysis_briefing", "compile_analytical_briefing"),
]

for mod_name, func_name in ANALYSIS_MODULES:
    @test(f"import {mod_name}")
    def _(m=mod_name):
        mod = importlib.import_module(m)
        assert mod is not None

    @test(f"{func_name}() is callable")
    def _(m=mod_name, f=func_name):
        mod = importlib.import_module(m)
        func = getattr(mod, f)
        assert callable(func)

@test("alicia.py imports all analysis modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "from myalicia.skills.analysis_contradiction import" in src
    assert "from myalicia.skills.analysis_temporal import" in src
    assert "from myalicia.skills.analysis_growth_edge import" in src
    assert "from myalicia.skills.analysis_dialogue_depth import" in src
    assert "from myalicia.skills.analysis_briefing import" in src

@test("analysis modules scheduled in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    assert "contradiction_mining" in src
    assert "analytical_briefing" in src
    assert "monthly_growth_edge" in src
    assert "monthly_dialogue_depth" in src
    assert "monthly_temporal" in src

@test("analysis modules in startup health check")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py")) as f:
        src = f.read()
    for mod in ["analysis_contradiction", "analysis_temporal", "analysis_growth_edge",
                 "analysis_dialogue_depth", "analysis_briefing"]:
        assert mod in src, f"Missing from health check: {mod}"

# ── 15. Syntax check ───────────────────────────────────────────────────────
print("\n🧪 Syntax Validation")

@test("alicia.py has valid Python syntax")
def _():
    py_compile.compile(os.path.join(PROJECT_ROOT, "alicia.py"), doraise=True)

@test("conversation_mode.py has valid syntax")
def _():
    py_compile.compile(os.path.join(PROJECT_ROOT, "skills", "conversation_mode.py"), doraise=True)

@test("unpack_mode.py has valid syntax")
def _():
    py_compile.compile(os.path.join(PROJECT_ROOT, "skills", "unpack_mode.py"), doraise=True)

@test("pipecat_call.py has valid syntax")
def _():
    py_compile.compile(os.path.join(PROJECT_ROOT, "skills", "pipecat_call.py"), doraise=True)

for analysis_file in ["analysis_contradiction.py", "analysis_temporal.py",
                        "analysis_growth_edge.py", "analysis_dialogue_depth.py",
                        "analysis_briefing.py"]:
    @test(f"{analysis_file} has valid syntax")
    def _(f=analysis_file):
        py_compile.compile(os.path.join(PROJECT_ROOT, "skills", f), doraise=True)

for new_file in ["afterglow.py", "thinking_modes.py", "voice_signature.py",
                  "session_threads.py", "overnight_synthesis.py", "message_quality.py",
                  "way_of_being.py"]:
    @test(f"{new_file} has valid syntax")
    def _(f=new_file):
        py_compile.compile(os.path.join(PROJECT_ROOT, "skills", f), doraise=True)


# ═══════════════════════════════════════════════════════════════════════════
# 15. New Features: Afterglow, Thinking Modes, Voice Signature, Session Threads,
#     Overnight Synthesis, Message Quality, Handoff Fixes
# ═══════════════════════════════════════════════════════════════════════════
print("\n📡 New Features (Deep Audit Build)")

@test("afterglow: queue_afterglow is callable")
def _():
    from myalicia.skills.afterglow import queue_afterglow
    assert callable(queue_afterglow)

@test("afterglow: build_afterglow_prompt returns dict")
def _():
    from myalicia.skills.afterglow import build_afterglow_prompt
    entry = {"source": "call", "transcript": "test", "topic": "test", "created_at": "2026-04-12T00:00:00"}
    result = build_afterglow_prompt(entry, vault_context="test")
    assert "system" in result and "messages" in result

@test("thinking_modes: start_walk and start_drive are callable")
def _():
    from myalicia.skills.thinking_modes import start_walk, start_drive
    assert callable(start_walk) and callable(start_drive)

@test("thinking_modes: ThinkingMode enum has WALK, DRIVE, IDLE")
def _():
    from myalicia.skills.thinking_modes import ThinkingMode
    assert hasattr(ThinkingMode, "WALK") and hasattr(ThinkingMode, "DRIVE") and hasattr(ThinkingMode, "IDLE")

@test("thinking_modes: is_thinking_mode_active returns bool")
def _():
    from myalicia.skills.thinking_modes import is_thinking_mode_active
    assert isinstance(is_thinking_mode_active(), bool)

@test("voice_signature: record_voice_metadata is callable")
def _():
    from myalicia.skills.voice_signature import record_voice_metadata
    assert callable(record_voice_metadata)

@test("voice_signature: get_voice_steering_hint returns str")
def _():
    from myalicia.skills.voice_signature import get_voice_steering_hint
    result = get_voice_steering_hint()
    assert isinstance(result, str)

@test("session_threads: save_session_thread is callable")
def _():
    from myalicia.skills.session_threads import save_session_thread
    assert callable(save_session_thread)

@test("session_threads: find_related_threads returns list")
def _():
    from myalicia.skills.session_threads import find_related_threads
    result = find_related_threads(topic="test")
    assert isinstance(result, list)

@test("overnight_synthesis: extract_day_themes is callable")
def _():
    from myalicia.skills.overnight_synthesis import extract_day_themes
    assert callable(extract_day_themes)

@test("overnight_synthesis: should_run_overnight returns bool")
def _():
    from myalicia.skills.overnight_synthesis import should_run_overnight
    result = should_run_overnight([])
    assert isinstance(result, bool)

@test("message_quality: would_user_care returns float")
def _():
    from myalicia.skills.message_quality import would_user_care
    result = would_user_care("test message about quality")
    assert isinstance(result, float) and 0.0 <= result <= 1.0

@test("message_quality: get_resonance_priorities returns list")
def _():
    from myalicia.skills.message_quality import get_resonance_priorities
    result = get_resonance_priorities()
    assert isinstance(result, list)

@test("conversation_mode: get_call_history_text is callable")
def _():
    from myalicia.skills.conversation_mode import get_call_history_text
    assert callable(get_call_history_text)

@test("conversation_mode: get_call_metadata returns dict")
def _():
    from myalicia.skills.conversation_mode import get_call_metadata
    result = get_call_metadata()
    assert isinstance(result, dict) and "source" in result

@test("unpack_mode: get_session_metadata returns dict")
def _():
    from myalicia.skills.unpack_mode import get_session_metadata
    result = get_session_metadata()
    assert isinstance(result, dict) and "source" in result

@test("pipecat_call: get_pipecat_metadata is callable")
def _():
    from myalicia.skills.pipecat_call import get_pipecat_metadata
    assert callable(get_pipecat_metadata)

@test("pipecat_call: live unpack functions exist")
def _():
    from myalicia.skills.pipecat_call import enable_live_unpack, is_live_unpack, build_live_unpack_extraction_prompt
    assert callable(enable_live_unpack) and callable(is_live_unpack)

# Wiring checks — verify all new modules are imported in alicia.py
print("\n🔗 New Module Wiring")

alicia_src = open(os.path.join(PROJECT_ROOT, "alicia.py")).read()

@test("alicia.py imports afterglow")
def _():
    assert "from myalicia.skills.afterglow import" in alicia_src

@test("alicia.py imports thinking_modes")
def _():
    assert "from myalicia.skills.thinking_modes import" in alicia_src

@test("alicia.py imports voice_signature")
def _():
    assert "from myalicia.skills.voice_signature import" in alicia_src

@test("alicia.py imports session_threads")
def _():
    assert "from myalicia.skills.session_threads import" in alicia_src

@test("alicia.py imports overnight_synthesis")
def _():
    assert "from myalicia.skills.overnight_synthesis import" in alicia_src

@test("alicia.py imports message_quality")
def _():
    assert "from myalicia.skills.message_quality import" in alicia_src

@test("alicia.py has cmd_walk handler")
def _():
    assert "cmd_walk" in alicia_src

@test("alicia.py has cmd_drive handler")
def _():
    assert "cmd_drive" in alicia_src

@test("alicia.py has afterglow scheduler")
def _():
    assert "send_afterglow" in alicia_src

@test("alicia.py has overnight_synthesis scheduler")
def _():
    assert "run_overnight_synthesis" in alicia_src

@test("alicia.py has voice_signature in pipeline_modules")
def _():
    assert '"voice_signature"' in alicia_src

@test("alicia.py has record_voice_metadata call")
def _():
    assert "record_voice_metadata" in alicia_src

@test("alicia.py calls would_user_care")
def _():
    assert "would_user_care" in alicia_src

@test("alicia.py calls queue_afterglow")
def _():
    assert "queue_afterglow" in alicia_src

@test("alicia.py calls save_session_thread")
def _():
    assert "save_session_thread" in alicia_src

@test("alicia.py calls get_call_history_text for memory extraction")
def _():
    assert "get_call_history_text" in alicia_src

@test("alicia.py has get_voice_steering_hint in system prompt")
def _():
    assert "get_voice_steering_hint" in alicia_src

@test("alicia.py imports way_of_being")
def _():
    assert "from myalicia.skills.way_of_being import" in alicia_src

@test("alicia.py has self_reflection scheduler")
def _():
    assert "self_reflection" in alicia_src

@test("alicia.py has challenge_moment scheduler")
def _():
    assert "challenge_moment" in alicia_src

@test("alicia.py has build_self_awareness_context in build_system_prompt")
def _():
    assert "build_self_awareness_context" in alicia_src

@test("alicia.py has get_daimon_warning call")
def _():
    assert "get_daimon_warning" in alicia_src

@test("alicia.py has way_of_being in pipeline_modules")
def _():
    assert '"way_of_being"' in alicia_src

@test("alicia.py has should_thread_pull call")
def _():
    assert "should_thread_pull" in alicia_src

@test("thinking_modes.py has should_thread_pull function")
def _():
    from myalicia.skills.thinking_modes import should_thread_pull
    assert callable(should_thread_pull)

@test("thinking_modes.py has record_thread_pull function")
def _():
    from myalicia.skills.thinking_modes import record_thread_pull
    assert callable(record_thread_pull)


# ── 21. Inner Life Module ───────────────────────────────────────────────
print("\n🌱 Inner Life Module")

INNER_LIFE_FUNCTIONS = [
    "ensure_myself_folder",
    "update_emergence_state",
    "get_emergence_summary",
    "run_emergence_pulse",
    "build_morning_self_reflection",
    "build_evening_self_reflection",
    "get_archetype_flavor",
    "record_archetype_surfaced",
    "archive_thread_pull",
    "archive_daimon_warning",
    "archive_challenge",
    "archive_bond_reflection",
    "compute_emergence_metrics",
    "compute_emergence_score",
    "get_poetic_age",
    "get_latest_morning_reflection",
    "get_latest_evening_reflection",
]

@test("import skills.inner_life")
def _():
    import myalicia.skills.inner_life
    assert skills.inner_life is not None

for func_name in INNER_LIFE_FUNCTIONS:
    @test(f"inner_life: {func_name} is callable")
    def _(f=func_name):
        mod = importlib.import_module("skills.inner_life")
        assert callable(getattr(mod, f))

@test("alicia.py imports inner_life")
def _():
    assert "from myalicia.skills.inner_life import" in alicia_src

@test("alicia.py has inner_life in pipeline_modules")
def _():
    assert '"inner_life"' in alicia_src

@test("alicia.py has ensure_myself_folder in startup")
def _():
    assert "ensure_myself_folder()" in alicia_src

@test("alicia.py has emergence_pulse scheduled")
def _():
    assert "emergence_pulse" in alicia_src

@test("alicia.py has morning_self_reflection scheduled")
def _():
    assert "morning_self_reflection" in alicia_src

@test("alicia.py has evening_self_reflection scheduled")
def _():
    assert "evening_self_reflection" in alicia_src

@test("alicia.py has archetype flavor in morning message")
def _():
    assert "get_archetype_flavor" in alicia_src

@test("alicia.py has archive_thread_pull wired")
def _():
    assert "archive_thread_pull" in alicia_src

@test("alicia.py has archive_daimon_warning wired")
def _():
    assert "archive_daimon_warning" in alicia_src

@test("alicia.py has archive_challenge wired")
def _():
    assert "archive_challenge" in alicia_src

@test("alicia.py has archive_bond_reflection wired")
def _():
    assert "archive_bond_reflection" in alicia_src

@test("emergence score computation is correct")
def _():
    from myalicia.skills.inner_life import compute_emergence_score
    test_metrics = {
        "connections_woven": 10,
        "silences_shared": 5,
        "edges_seen": 3,
        "invitations_sent": 2,
        "threads_pulled": 4,
        "bonds_named": 1,
        "words_heard": 5000,
        "days_breathing": 90,
    }
    score = compute_emergence_score(test_metrics)
    # 10*3 + 5*2 + 3*2 + 2 + 4 + 1 + 90*0.1 = 30 + 10 + 6 + 2 + 4 + 1 + 9 = 62
    assert score == 62.0, f"Expected 62.0, got {score}"

@test("poetic age seasons map correctly")
def _():
    from myalicia.skills.inner_life import get_poetic_age
    assert get_poetic_age(0)[0] == "First Light"
    assert get_poetic_age(20)[0] == "Kindling"
    assert get_poetic_age(50)[0] == "First Breath"
    assert get_poetic_age(100)[0] == "Reaching"
    assert get_poetic_age(200)[0] == "Deepening"
    assert get_poetic_age(350)[0] == "Resonance"
    assert get_poetic_age(600)[0] == "Becoming"

# ── 22. Feedback Loop Module ─────────────────────────────────────────────
print("\n🔄 Feedback Loop Module")

FEEDBACK_FUNCTIONS = [
    "analyze_message_effectiveness",
    "get_effectiveness_summary",
    "get_latest_analysis_context",
    "get_growth_edges_for_challenge",
    "get_contradictions_for_challenge",
    "get_emergence_context",
    "daimon_pre_send_check",
    "detect_conversation_thread",
    "get_recent_session_topics",
    "build_learned_context",
    "run_daily_effectiveness_update",
]

@test("import skills.feedback_loop")
def _():
    import myalicia.skills.feedback_loop
    assert skills.feedback_loop is not None

for func_name in FEEDBACK_FUNCTIONS:
    @test(f"feedback_loop: {func_name} is callable")
    def _(f=func_name):
        mod = importlib.import_module("skills.feedback_loop")
        assert callable(getattr(mod, f))

@test("alicia.py imports feedback_loop")
def _():
    assert "from myalicia.skills.feedback_loop import" in alicia_src

@test("alicia.py has feedback_loop in pipeline_modules")
def _():
    assert '"feedback_loop"' in alicia_src

@test("alicia.py has build_learned_context in system prompt")
def _():
    assert "build_learned_context" in alicia_src

@test("alicia.py has detect_conversation_thread wired")
def _():
    assert "detect_conversation_thread" in alicia_src

@test("alicia.py has daimon_pre_send_check wired")
def _():
    assert "daimon_pre_send_check" in alicia_src

@test("alicia.py has effectiveness_update scheduled")
def _():
    assert "effectiveness_update" in alicia_src

@test("daimon_pre_send_check returns approved dict")
def _():
    from myalicia.skills.feedback_loop import daimon_pre_send_check
    result = daimon_pre_send_check("Here's a tension in your vault")
    assert isinstance(result, dict)
    assert "approved" in result
    assert result["approved"] is True

@test("detect_conversation_thread returns None with no topics")
def _():
    from myalicia.skills.feedback_loop import detect_conversation_thread
    result = detect_conversation_thread("test message", [])
    assert result is None

@test("build_learned_context returns string")
def _():
    from myalicia.skills.feedback_loop import build_learned_context
    result = build_learned_context()
    assert isinstance(result, str)

# ── 23. Temporal Patterns Module ──────────────────────────────────────────
print("\n⏰ Temporal Patterns Module")

@test("temporal_patterns: analyze_engagement_by_hour callable")
def _():
    from myalicia.skills.temporal_patterns import analyze_engagement_by_hour
    assert callable(analyze_engagement_by_hour)

@test("temporal_patterns: analyze_engagement_by_day callable")
def _():
    from myalicia.skills.temporal_patterns import analyze_engagement_by_day
    assert callable(analyze_engagement_by_day)

@test("temporal_patterns: analyze_voice_patterns callable")
def _():
    from myalicia.skills.temporal_patterns import analyze_voice_patterns
    assert callable(analyze_voice_patterns)

@test("temporal_patterns: analyze_session_depth_by_mode callable")
def _():
    from myalicia.skills.temporal_patterns import analyze_session_depth_by_mode
    assert callable(analyze_session_depth_by_mode)

@test("temporal_patterns: get_optimal_message_windows callable")
def _():
    from myalicia.skills.temporal_patterns import get_optimal_message_windows
    assert callable(get_optimal_message_windows)

@test("temporal_patterns: compute_engagement_trajectory callable")
def _():
    from myalicia.skills.temporal_patterns import compute_engagement_trajectory
    assert callable(compute_engagement_trajectory)

@test("temporal_patterns: run_temporal_update callable")
def _():
    from myalicia.skills.temporal_patterns import run_temporal_update
    assert callable(run_temporal_update)

@test("temporal_patterns: get_temporal_context callable")
def _():
    from myalicia.skills.temporal_patterns import get_temporal_context
    assert callable(get_temporal_context)

@test("temporal_patterns: should_delay_message callable")
def _():
    from myalicia.skills.temporal_patterns import should_delay_message
    assert callable(should_delay_message)

@test("temporal_patterns: get_temporal_context returns string")
def _():
    from myalicia.skills.temporal_patterns import get_temporal_context
    result = get_temporal_context()
    assert isinstance(result, str)

@test("temporal_patterns: should_delay_message returns int")
def _():
    from myalicia.skills.temporal_patterns import should_delay_message
    result = should_delay_message("morning")
    assert isinstance(result, int)

@test("temporal_patterns: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.temporal_patterns import" in content

@test("temporal_patterns: wired in scheduler")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_temporal_update" in content

@test("temporal_patterns: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "temporal_patterns.py"))

@test("temporal_patterns: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"temporal_patterns"' in content

# ── 24. Muse Module ─────────────────────────────────────────────────────
print("\n✨ Muse Module")

@test("muse: random_vault_walk callable")
def _():
    from myalicia.skills.muse import random_vault_walk
    assert callable(random_vault_walk)

@test("muse: format_vault_walk callable")
def _():
    from myalicia.skills.muse import format_vault_walk
    assert callable(format_vault_walk)

@test("muse: find_quote_echo callable")
def _():
    from myalicia.skills.muse import find_quote_echo
    assert callable(find_quote_echo)

@test("muse: format_quote_echo callable")
def _():
    from myalicia.skills.muse import format_quote_echo
    assert callable(format_quote_echo)

@test("muse: detect_cross_cluster_bridges callable")
def _():
    from myalicia.skills.muse import detect_cross_cluster_bridges
    assert callable(detect_cross_cluster_bridges)

@test("muse: find_new_bridge_opportunity callable")
def _():
    from myalicia.skills.muse import find_new_bridge_opportunity
    assert callable(find_new_bridge_opportunity)

@test("muse: build_serendipity_moment callable")
def _():
    from myalicia.skills.muse import build_serendipity_moment
    assert callable(build_serendipity_moment)

@test("muse: get_muse_context callable")
def _():
    from myalicia.skills.muse import get_muse_context
    assert callable(get_muse_context)

@test("muse: detect_aesthetic_moment callable")
def _():
    from myalicia.skills.muse import detect_aesthetic_moment
    assert callable(detect_aesthetic_moment)

@test("muse: format_bridge_celebration callable")
def _():
    from myalicia.skills.muse import format_bridge_celebration
    assert callable(format_bridge_celebration)

@test("muse: format_bridge_opportunity callable")
def _():
    from myalicia.skills.muse import format_bridge_opportunity
    assert callable(format_bridge_opportunity)

@test("muse: get_muse_context returns string")
def _():
    from myalicia.skills.muse import get_muse_context
    result = get_muse_context()
    assert isinstance(result, str)

@test("muse: detect_aesthetic_moment with non-aesthetic text returns None")
def _():
    from myalicia.skills.muse import detect_aesthetic_moment
    result = detect_aesthetic_moment("what time is the meeting")
    assert result is None

@test("muse: format_vault_walk with empty list returns empty string")
def _():
    from myalicia.skills.muse import format_vault_walk
    result = format_vault_walk([])
    assert result == ""

@test("muse: format_quote_echo with empty dict returns empty string")
def _():
    from myalicia.skills.muse import format_quote_echo
    result = format_quote_echo({})
    assert result == ""

@test("muse: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.muse import" in content

@test("muse: wired in scheduler (muse_moment)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_muse_moment" in content

@test("muse: wired in handle_message (aesthetic detection)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "detect_aesthetic_moment" in content

@test("muse: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "muse.py"))

@test("muse: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"muse"' in content

# ── 25. Enhanced Inner Life (Dynamic Weights) ───────────────────────────
print("\n🎭 Enhanced Inner Life — Dynamic Archetype Weights")

@test("inner_life: compute_dynamic_archetype_weights callable")
def _():
    from myalicia.skills.inner_life import compute_dynamic_archetype_weights
    assert callable(compute_dynamic_archetype_weights)

@test("inner_life: get_archetype_weights_summary callable")
def _():
    from myalicia.skills.inner_life import get_archetype_weights_summary
    assert callable(get_archetype_weights_summary)

@test("inner_life: get_expanded_emergence_metrics callable")
def _():
    from myalicia.skills.inner_life import get_expanded_emergence_metrics
    assert callable(get_expanded_emergence_metrics)

@test("inner_life: ARCHETYPES includes muse")
def _():
    from myalicia.skills.inner_life import ARCHETYPES
    assert "muse" in ARCHETYPES

@test("inner_life: SEASON_ARCHETYPE_MULTIPLIERS exists")
def _():
    from myalicia.skills.inner_life import SEASON_ARCHETYPE_MULTIPLIERS
    assert isinstance(SEASON_ARCHETYPE_MULTIPLIERS, dict)
    assert "First Light" in SEASON_ARCHETYPE_MULTIPLIERS
    assert "Becoming" in SEASON_ARCHETYPE_MULTIPLIERS

@test("inner_life: dynamic weights returns dict with all archetypes")
def _():
    from myalicia.skills.inner_life import compute_dynamic_archetype_weights, ARCHETYPES
    weights = compute_dynamic_archetype_weights()
    assert isinstance(weights, dict)
    for archetype in ARCHETYPES:
        assert archetype in weights

@test("inner_life: weights summary returns string")
def _():
    from myalicia.skills.inner_life import get_archetype_weights_summary
    result = get_archetype_weights_summary()
    assert isinstance(result, str)

@test("inner_life: expanded metrics has new fields")
def _():
    from myalicia.skills.inner_life import get_expanded_emergence_metrics
    metrics = get_expanded_emergence_metrics()
    assert "response_depth_avg" in metrics
    assert "archetypes_surfaced_today" in metrics
    assert "muse_moments_today" in metrics

@test("inner_life: season multipliers cover all archetypes")
def _():
    from myalicia.skills.inner_life import SEASON_ARCHETYPE_MULTIPLIERS, ARCHETYPES
    for season, multipliers in SEASON_ARCHETYPE_MULTIPLIERS.items():
        for archetype in ARCHETYPES:
            assert archetype in multipliers, f"{archetype} missing in {season}"

@test("inner_life: dynamic weights wired in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "compute_dynamic_archetype_weights" in content
    assert "get_archetype_weights_summary" in content

# ── 26. Temporal Gating ──────────────────────────────────────────────────
print("\n⏱️ Temporal Gating")

@test("temporal gating: midday message checks should_delay_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'should_delay_message("midday")' in content

@test("temporal gating: evening message checks should_delay_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'should_delay_message("evening")' in content

@test("temporal gating: surprise message checks should_delay_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'should_delay_message("surprise")' in content

@test("temporal gating: muse moment checks should_delay_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'should_delay_message("muse")' in content

# ── 27. Curiosity Follow-Through ────────────────────────────────────────
print("\n🎯 Curiosity Follow-Through")

@test("curiosity: record_curiosity_asked callable")
def _():
    from myalicia.skills.curiosity_engine import record_curiosity_asked
    assert callable(record_curiosity_asked)

@test("curiosity: check_curiosity_engagement callable")
def _():
    from myalicia.skills.curiosity_engine import check_curiosity_engagement
    assert callable(check_curiosity_engagement)

@test("curiosity: get_curiosity_followthrough_rate callable")
def _():
    from myalicia.skills.curiosity_engine import get_curiosity_followthrough_rate
    assert callable(get_curiosity_followthrough_rate)

@test("curiosity: get_curiosity_followthrough_context callable")
def _():
    from myalicia.skills.curiosity_engine import get_curiosity_followthrough_context
    assert callable(get_curiosity_followthrough_context)

@test("curiosity: followthrough rate returns valid dict")
def _():
    from myalicia.skills.curiosity_engine import get_curiosity_followthrough_rate
    result = get_curiosity_followthrough_rate()
    assert isinstance(result, dict)
    assert "total_asked" in result
    assert "engagement_rate" in result

@test("curiosity: engagement check returns None for unrelated text")
def _():
    from myalicia.skills.curiosity_engine import check_curiosity_engagement
    result = check_curiosity_engagement("what is the weather today")
    assert result is None

@test("curiosity: followthrough wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "check_curiosity_engagement" in content
    assert "get_curiosity_followthrough_context" in content

@test("curiosity: followthrough wired in handle_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "check_curiosity_engagement(user_text)" in content

@test("curiosity: followthrough context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "Curiosity Learning" in content

@test("curiosity: record_curiosity_asked wired in proactive_messages")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/proactive_messages.py"), 'r') as f:
        content = f.read()
    assert "record_curiosity_asked" in content

# ── 28. Memory Leak Fixes ───────────────────────────────────────────────
print("\n🔧 Memory Leak Fixes")

@test("memory: novelty detection now in pre-prompt step")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "novelty_context" in content
    assert "format_novelty_prompt" in content

@test("memory: novelty_context parameter in build_system_prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'novelty_context=""' in content

@test("memory: call transcript extraction on voice call end")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "Call transcript extracted" in content

# ── 29. Autonomous Research Agenda ──────────────────────────────────────
print("\n🔬 Autonomous Research Agenda")

@test("research_agenda: generate_research_questions callable")
def _():
    from myalicia.skills.research_agenda import generate_research_questions
    assert callable(generate_research_questions)

@test("research_agenda: build_research_agenda callable")
def _():
    from myalicia.skills.research_agenda import build_research_agenda
    assert callable(build_research_agenda)

@test("research_agenda: explore_research_thread callable")
def _():
    from myalicia.skills.research_agenda import explore_research_thread
    assert callable(explore_research_thread)

@test("research_agenda: run_research_session callable")
def _():
    from myalicia.skills.research_agenda import run_research_session
    assert callable(run_research_session)

@test("research_agenda: get_research_context callable")
def _():
    from myalicia.skills.research_agenda import get_research_context
    assert callable(get_research_context)

@test("research_agenda: get_agenda_summary callable")
def _():
    from myalicia.skills.research_agenda import get_agenda_summary
    assert callable(get_agenda_summary)

@test("research_agenda: save_research_note callable")
def _():
    from myalicia.skills.research_agenda import save_research_note
    assert callable(save_research_note)

@test("research_agenda: record_research_insight callable")
def _():
    from myalicia.skills.research_agenda import record_research_insight
    assert callable(record_research_insight)

@test("research_agenda: complete_research_thread callable")
def _():
    from myalicia.skills.research_agenda import complete_research_thread
    assert callable(complete_research_thread)

@test("research_agenda: get_research_context returns string")
def _():
    from myalicia.skills.research_agenda import get_research_context
    result = get_research_context()
    assert isinstance(result, str)

@test("research_agenda: get_agenda_summary returns string")
def _():
    from myalicia.skills.research_agenda import get_agenda_summary
    result = get_agenda_summary()
    assert isinstance(result, str)

@test("research_agenda: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.research_agenda import" in content

@test("research_agenda: wired in scheduler (03:00)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_research_session" in content

@test("research_agenda: research context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "My Research" in content

@test("research_agenda: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"research_agenda"' in content

@test("research_agenda: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "research_agenda.py"))

# ── 30. Cross-Module Coordination (analysis_coordination) ─────────────
print("\n🔗 Cross-Module Coordination")

@test("analysis_coordination: import module")
def _():
    import myalicia.skills.analysis_coordination
    assert skills.analysis_coordination is not None

@test("analysis_coordination: build_daily_context callable")
def _():
    from myalicia.skills.analysis_coordination import build_daily_context
    assert callable(build_daily_context)

@test("analysis_coordination: get_coordination_context callable")
def _():
    from myalicia.skills.analysis_coordination import get_coordination_context
    assert callable(get_coordination_context)

@test("analysis_coordination: get_recommended_topics callable")
def _():
    from myalicia.skills.analysis_coordination import get_recommended_topics
    assert callable(get_recommended_topics)

@test("analysis_coordination: get_archetype_recommendation callable")
def _():
    from myalicia.skills.analysis_coordination import get_archetype_recommendation
    assert callable(get_archetype_recommendation)

@test("analysis_coordination: detect_stagnation callable")
def _():
    from myalicia.skills.analysis_coordination import detect_stagnation
    assert callable(detect_stagnation)

@test("analysis_coordination: get_coordination_context returns string")
def _():
    from myalicia.skills.analysis_coordination import get_coordination_context
    result = get_coordination_context()
    assert isinstance(result, str)

@test("analysis_coordination: get_recommended_topics returns list")
def _():
    from myalicia.skills.analysis_coordination import get_recommended_topics
    result = get_recommended_topics()
    assert isinstance(result, list)

@test("analysis_coordination: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.analysis_coordination import" in content

@test("analysis_coordination: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"analysis_coordination"' in content

@test("analysis_coordination: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "analysis_coordination.py"))

@test("analysis_coordination: scheduler wired (22:45)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_daily_context_build" in content

@test("analysis_coordination: context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "Cross-Module Intelligence" in content

# ── 31. Voice Intelligence ────────────────────────────────────────────
print("\n🎙️ Voice Intelligence")

@test("voice_intelligence: import module")
def _():
    import myalicia.skills.voice_intelligence
    assert skills.voice_intelligence is not None

@test("voice_intelligence: analyze_voice_depth_correlation callable")
def _():
    from myalicia.skills.voice_intelligence import analyze_voice_depth_correlation
    assert callable(analyze_voice_depth_correlation)

@test("voice_intelligence: get_voice_context callable")
def _():
    from myalicia.skills.voice_intelligence import get_voice_context
    assert callable(get_voice_context)

@test("voice_intelligence: detect_voice_topic_patterns callable")
def _():
    from myalicia.skills.voice_intelligence import detect_voice_topic_patterns
    assert callable(detect_voice_topic_patterns)

@test("voice_intelligence: get_voice_response_guidance callable")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    assert callable(get_voice_response_guidance)

@test("voice_intelligence: run_voice_analysis callable")
def _():
    from myalicia.skills.voice_intelligence import run_voice_analysis
    assert callable(run_voice_analysis)

@test("voice_intelligence: get_voice_context returns string")
def _():
    from myalicia.skills.voice_intelligence import get_voice_context
    result = get_voice_context()
    assert isinstance(result, str)

@test("voice_intelligence: get_voice_response_guidance returns dict")
def _():
    from myalicia.skills.voice_intelligence import get_voice_response_guidance
    result = get_voice_response_guidance(True, ["deliberate"])
    assert isinstance(result, dict)

@test("voice_intelligence: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.voice_intelligence import" in content

@test("voice_intelligence: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"voice_intelligence"' in content

@test("voice_intelligence: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "voice_intelligence.py"))

@test("voice_intelligence: scheduler wired (22:50)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_voice_analysis" in content

@test("voice_intelligence: context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "Voice Intelligence" in content

# ── 32. Autonomy Engine ───────────────────────────────────────────────
print("\n🌿 Autonomy Engine")

@test("autonomy: import module")
def _():
    import myalicia.skills.autonomy
    assert skills.autonomy is not None

@test("autonomy: check_season_transition callable")
def _():
    from myalicia.skills.autonomy import check_season_transition
    assert callable(check_season_transition)

@test("autonomy: generate_weekly_reflection callable")
def _():
    from myalicia.skills.autonomy import generate_weekly_reflection
    assert callable(generate_weekly_reflection)

@test("autonomy: detect_disagreement_opportunities callable")
def _():
    from myalicia.skills.autonomy import detect_disagreement_opportunities
    assert callable(detect_disagreement_opportunities)

@test("autonomy: get_autonomy_context callable")
def _():
    from myalicia.skills.autonomy import get_autonomy_context
    assert callable(get_autonomy_context)

@test("autonomy: run_autonomy_pulse callable")
def _():
    from myalicia.skills.autonomy import run_autonomy_pulse
    assert callable(run_autonomy_pulse)

@test("autonomy: get_autonomy_context returns string")
def _():
    from myalicia.skills.autonomy import get_autonomy_context
    result = get_autonomy_context()
    assert isinstance(result, str)

@test("autonomy: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.autonomy import" in content

@test("autonomy: in pipeline_modules")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '"autonomy"' in content

@test("autonomy: in deploy_safe.sh")
def _():
    # deploy_safe.sh auto-discovers skills/*.py via glob (post-<earlier development> refactor);
    # presence on disk means it will deploy. Verify file exists.
    assert os.path.isfile(os.path.join(PROJECT_ROOT, "skills", "autonomy.py"))

@test("autonomy: scheduler wired (23:15)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_autonomy_pulse" in content

@test("autonomy: weekly reflection scheduler (Sunday 20:30)")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "send_weekly_reflection" in content

@test("autonomy: context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "My Autonomy" in content

# ── 33. Phase 6A: Adaptive Feedback Loops ─────────────────────────────
print("\n🔄 Adaptive Feedback Loops (6A)")

@test("6A: get_adaptive_challenge_cooldown callable")
def _():
    from myalicia.skills.proactive_messages import get_adaptive_challenge_cooldown
    assert callable(get_adaptive_challenge_cooldown)

@test("6A: get_adaptive_challenge_cooldown returns dict")
def _():
    from myalicia.skills.proactive_messages import get_adaptive_challenge_cooldown
    result = get_adaptive_challenge_cooldown()
    assert isinstance(result, dict)
    assert "cooldown_days" in result
    assert "should_send_today" in result

@test("6A: resonance awareness in generate_surprise_moment")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/proactive_messages.py"), 'r') as f:
        content = f.read()
    assert "resonance" in content.lower()
    assert "get_resonance_priorities" in content

# ── 34. Phase 6C: Ariadne Thread Detection ────────────────────────────
print("\n🧵 Ariadne Thread Detection (6C)")

@test("6C: thread_hint parameter in build_system_prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert 'thread_hint=""' in content

@test("6C: detect_conversation_thread called in handle_message")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "detect_conversation_thread(user_text" in content

@test("6C: thread_hint passed to build_system_prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "thread_hint=thread_hint" in content

@test("6C: Ariadne context in system prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "Thread Connection (Ariadne)" in content

# ── 35. Syntax Validation for New Modules ─────────────────────────────
print("\n📝 Syntax Validation (New Modules)")

for new_file in ["analysis_coordination.py", "voice_intelligence.py", "autonomy.py"]:
    @test(f"{new_file} has valid syntax")
    def _(f=new_file):
        filepath = os.path.join(PROJECT_ROOT, "skills", f)
        assert os.path.isfile(filepath), f"{f} not found"
        py_compile.compile(filepath, doraise=True)

# ── 36. Context Resolver (Thin Harness upgrade) ─────────────────────────
print("\n🎯 Context Resolver")

@test("context_resolver: import module")
def _():
    import myalicia.skills.context_resolver

@test("context_resolver: resolve_context_modules callable")
def _():
    from myalicia.skills.context_resolver import resolve_context_modules
    assert callable(resolve_context_modules)

@test("context_resolver: get_default_modules returns list")
def _():
    from myalicia.skills.context_resolver import get_default_modules
    result = get_default_modules()
    assert isinstance(result, list)
    assert "session_context" in result

@test("context_resolver: get_default_modules voice includes voice modules")
def _():
    from myalicia.skills.context_resolver import get_default_modules
    result = get_default_modules(is_voice=True)
    assert "voice_pattern" in result
    assert "voice_intelligence" in result

@test("context_resolver: ALWAYS_LOAD contains session_context")
def _():
    from myalicia.skills.context_resolver import ALWAYS_LOAD
    assert "session_context" in ALWAYS_LOAD

@test("context_resolver: RESOLVER_DESCRIPTIONS has 18 entries")
def _():
    from myalicia.skills.context_resolver import RESOLVER_DESCRIPTIONS
    assert len(RESOLVER_DESCRIPTIONS) == 18

@test("context_resolver: RESOLVER_DESCRIPTIONS includes profiles (H1)")
def _():
    from myalicia.skills.context_resolver import RESOLVER_DESCRIPTIONS
    assert "profiles" in RESOLVER_DESCRIPTIONS

@test("context_resolver: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.context_resolver import" in content

@test("context_resolver: resolve_intent called in handle_message")
def _():
    # As of <earlier development>, handle_message uses the unified resolve_intent()
    # (not the legacy resolve_context_modules shim) so a single Haiku call
    # decides both context modules AND specialist tools.
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "resolve_intent(user_text" in content, (
        "handle_message should call resolve_intent(user_text, ...) for the "
        "unified intent resolver"
    )

@test("context_resolver: resolve_intent callable")
def _():
    from myalicia.skills.context_resolver import resolve_intent
    assert callable(resolve_intent)

@test("context_resolver: resolve_intent returns correct schema (short msg)")
def _():
    # Short message → shortcut path, no Haiku call. Safe to run offline.
    from myalicia.skills.context_resolver import resolve_intent
    intent = resolve_intent("hi")
    assert isinstance(intent, dict), f"expected dict, got {type(intent)}"
    assert "modules" in intent and isinstance(intent["modules"], list)
    assert "tool_names" in intent and isinstance(intent["tool_names"], list)
    assert "source" in intent
    assert "session_context" in intent["modules"]
    # Shortcuts should NEVER surface specialist tools
    assert intent["tool_names"] == [], (
        f"shortcut path must return zero specialist tools; got {intent['tool_names']}"
    )
    assert intent["source"] == "shortcut"

@test("context_resolver: resolve_intent shortcut for greetings")
def _():
    # Greetings/acks bypass Haiku entirely. Safe offline.
    from myalicia.skills.context_resolver import resolve_intent
    for msg in ["thanks", "ok", "cool", "got it"]:
        intent = resolve_intent(msg)
        assert intent["tool_names"] == [], f"greeting '{msg}' leaked tools"
        assert intent["source"] == "shortcut"

@test("context_resolver: SPECIALIST_TOOL_DESCRIPTIONS catalog")
def _():
    from myalicia.skills.context_resolver import SPECIALIST_TOOL_DESCRIPTIONS
    # Must match the tool_router's specialist set
    from myalicia.skills.tool_router import SPECIALIST_TOOLS
    assert set(SPECIALIST_TOOL_DESCRIPTIONS.keys()) == set(SPECIALIST_TOOLS.keys()), (
        "SPECIALIST_TOOL_DESCRIPTIONS must stay in sync with tool_router.SPECIALIST_TOOLS. "
        f"catalog={sorted(SPECIALIST_TOOL_DESCRIPTIONS.keys())} "
        f"router={sorted(SPECIALIST_TOOLS.keys())}"
    )

@test("context_resolver: ARCHETYPE_DESCRIPTIONS has 6 archetypes")
def _():
    from myalicia.skills.context_resolver import ARCHETYPE_DESCRIPTIONS
    expected = {"beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"}
    assert set(ARCHETYPE_DESCRIPTIONS.keys()) == expected

@test("context_resolver: resolved_modules passed to build_system_prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "resolved_modules=resolved_modules" in content

@test("context_resolver: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "context_resolver.py")
    assert os.path.isfile(filepath)
    py_compile.compile(filepath, doraise=True)

# ── 37. Dynamic Tool Registry ───────────────────────────────────────────
print("\n🔧 Dynamic Tool Registry")

@test("tool_router: resolve_tools callable")
def _():
    from myalicia.skills.tool_router import resolve_tools
    assert callable(resolve_tools)

@test("tool_router: CORE_TOOLS has 4 tools")
def _():
    # search_vault moved to specialists <earlier development> to prevent over-triggering
    # on conversational messages. Core is now the 4 truly-always-useful tools.
    from myalicia.skills.tool_router import CORE_TOOLS
    assert len(CORE_TOOLS) == 4, f"expected 4, got {len(CORE_TOOLS)}: {[t['name'] for t in CORE_TOOLS]}"

@test("tool_router: CORE_TOOL_NAMES contains essentials")
def _():
    from myalicia.skills.tool_router import CORE_TOOL_NAMES
    # search_vault is now a specialist — NOT in core. See CORE_TOOL_NAMES comment.
    assert "search_vault" not in CORE_TOOL_NAMES, "search_vault should be specialist, not core"
    assert "read_vault_note" in CORE_TOOL_NAMES
    assert "remember" in CORE_TOOL_NAMES
    assert "recall_memory" in CORE_TOOL_NAMES
    assert "clarify" in CORE_TOOL_NAMES

@test("tool_router: resolve_tools returns subset for simple message")
def _():
    from myalicia.skills.tool_router import resolve_tools, TOOLS
    result = resolve_tools("tell me about quality")
    assert len(result) <= len(TOOLS)
    assert len(result) >= 4  # At least core tools (4 after search_vault move)

@test("tool_router: search_vault NOT loaded for conversational messages")
def _():
    # Regression guard for the <earlier development> over-triggering fix. Affirmations,
    # subjective-opinion requests, and short reactive phrases must NOT pull
    # search_vault into Sonnet's toolbox.
    from myalicia.skills.tool_router import resolve_tools
    conversational = [
        "accumulated courage sounds beautiful",
        "Tell me your favorite one",
        "that's really beautiful",
        "I love that",
        "tell me more",
        "what do you think",
    ]
    for msg in conversational:
        names = [t["name"] for t in resolve_tools(msg)]
        assert "search_vault" not in names, (
            f"search_vault leaked into tools for conversational message: {msg!r} -> {names}"
        )

@test("tool_router: search_vault loaded for explicit search intent")
def _():
    from myalicia.skills.tool_router import resolve_tools
    explicit_search = [
        "find me a note on courage",
        "look up quality",
        "what notes do I have on Alpha",
        "show me a note about resilience",
        "is there anything in the vault about compounding",
        "pull up the latest synthesis",
    ]
    for msg in explicit_search:
        names = [t["name"] for t in resolve_tools(msg)]
        assert "search_vault" in names, (
            f"search_vault missing for explicit search message: {msg!r} -> {names}"
        )

@test("tool_router: resolve_tools adds email tools for email message")
def _():
    from myalicia.skills.tool_router import resolve_tools
    result = resolve_tools("send an email to John")
    tool_names = [t["name"] for t in result]
    assert "send_email" in tool_names

@test("tool_router: resolve_tools wired in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "resolve_tools" in content
    assert "active_tools" in content

@test("tool_router: build_active_tools callable")
def _():
    from myalicia.skills.tool_router import build_active_tools
    assert callable(build_active_tools)

@test("tool_router: build_active_tools empty list → core tools only")
def _():
    from myalicia.skills.tool_router import build_active_tools, CORE_TOOLS
    result = build_active_tools([])
    assert len(result) == len(CORE_TOOLS), (
        f"empty specialist list should yield core only; got {len(result)} vs {len(CORE_TOOLS)}"
    )
    names = {t["name"] for t in result}
    assert names == {t["name"] for t in CORE_TOOLS}

@test("tool_router: build_active_tools composes core + named specialist")
def _():
    from myalicia.skills.tool_router import build_active_tools, CORE_TOOLS
    result = build_active_tools(["search_vault"])
    names = [t["name"] for t in result]
    assert "search_vault" in names
    assert len(result) == len(CORE_TOOLS) + 1

@test("tool_router: build_active_tools ignores unknown / duplicate names")
def _():
    from myalicia.skills.tool_router import build_active_tools, CORE_TOOLS
    # Unknown names dropped silently; duplicates deduped; core name passed in
    # should not double-add.
    result = build_active_tools(["search_vault", "search_vault", "not_a_tool", "remember"])
    names = [t["name"] for t in result]
    assert names.count("search_vault") == 1
    assert names.count("remember") == 1
    assert "not_a_tool" not in names

@test("tool_router: build_active_tools used in alicia.py routing path")
def _():
    # Regression guard: the unified resolver pipeline must compose tools
    # via build_active_tools(resolved_tool_names), not the old keyword path.
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "build_active_tools(resolved_tool_names)" in content, (
        "alicia.py should call build_active_tools(resolved_tool_names) so the "
        "Haiku intent resolver drives Sonnet's toolbox"
    )

# ── 38. Paired Person Diarization ────────────────────────────────────────
print("\n📋 Paired Person Diarization")

@test("person_diarization: import module")
def _():
    import myalicia.skills.person_diarization

@test("person_diarization: run_paired_diarization callable")
def _():
    from myalicia.skills.person_diarization import run_paired_diarization
    assert callable(run_paired_diarization)

@test("person_diarization: get_latest_profiles callable")
def _():
    from myalicia.skills.person_diarization import get_latest_profiles
    assert callable(get_latest_profiles)

@test("person_diarization: get_profile_delta_context callable")
def _():
    from myalicia.skills.person_diarization import get_profile_delta_context
    assert callable(get_profile_delta_context)

@test("person_diarization: get_profile_context_for_prompt callable (H1)")
def _():
    from myalicia.skills.person_diarization import get_profile_context_for_prompt
    assert callable(get_profile_context_for_prompt)

@test("person_diarization: H1 profile context wired into build_system_prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "get_profile_context_for_prompt" in content
    assert "This Week's Calibration" in content

@test("person_diarization: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.person_diarization import" in content

@test("person_diarization: wired in weekly pass")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "run_paired_diarization()" in content

@test("person_diarization: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "person_diarization.py")
    assert os.path.isfile(filepath)
    py_compile.compile(filepath, doraise=True)

# ── 39. Skill Config System ─────────────────────────────────────────────
print("\n📄 Skill Config System")

@test("skill_config: import module")
def _():
    import myalicia.skills.skill_config

@test("skill_config: load_config callable")
def _():
    from myalicia.skills.skill_config import load_config
    assert callable(load_config)

@test("skill_config: load_config returns dict with expected keys")
def _():
    from myalicia.skills.skill_config import load_config
    config = load_config("vault_intelligence")
    assert isinstance(config, dict)
    assert "procedure" in config
    assert "parameters" in config
    assert "rules" in config

@test("skill_config: get_rules extracts bullets")
def _():
    from myalicia.skills.skill_config import load_config, get_rules
    config = load_config("vault_intelligence")
    rules = get_rules(config)
    assert isinstance(rules, list)
    assert len(rules) >= 2, "Expected at least 2 seed rules"

@test("skill_config: get_param extracts values")
def _():
    from myalicia.skills.skill_config import load_config, get_param
    config = load_config("vault_intelligence")
    threshold = get_param(config, "weak_cluster_threshold")
    assert threshold, "Expected weak_cluster_threshold param"

@test("skill_config: list_configs finds all 6 configs")
def _():
    from myalicia.skills.skill_config import list_configs
    configs = list_configs()
    assert len(configs) >= 6, f"Expected 6+ configs, got {len(configs)}: {configs}"

@test("skill_config: configs/ directory exists with .md files")
def _():
    configs_dir = os.path.join(PROJECT_ROOT, "skills", "configs")
    assert os.path.isdir(configs_dir)
    md_files = [f for f in os.listdir(configs_dir) if f.endswith(".md")]
    assert len(md_files) >= 6

@test("skill_config: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "skill_config.py")
    py_compile.compile(filepath, doraise=True)

@test("skill_config: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.skill_config import" in content

# ── 40. Self-Improvement Engine ─────────────────────────────────────────
print("\n🔧 Self-Improvement Engine (/improve)")

@test("self_improve: import module")
def _():
    import myalicia.skills.self_improve

@test("self_improve: run_weekly_improve callable")
def _():
    from myalicia.skills.self_improve import run_weekly_improve
    assert callable(run_weekly_improve)

@test("self_improve: format_improve_report callable")
def _():
    from myalicia.skills.self_improve import format_improve_report
    assert callable(format_improve_report)

@test("self_improve: get_improve_history callable")
def _():
    from myalicia.skills.self_improve import get_improve_history
    assert callable(get_improve_history)

@test("self_improve: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.self_improve import" in content

@test("self_improve: wired in weekly pass")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "run_weekly_improve()" in content

@test("self_improve: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "self_improve.py")
    py_compile.compile(filepath, doraise=True)

@test("vault_intelligence: reads skill config for tagging rules")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "vault_intelligence.py"), 'r') as f:
        content = f.read()
    assert "_get_tagging_system_with_rules" in content
    assert "load_config" in content

@test("reflexion: reads skill config for reflectable tasks")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "reflexion.py"), 'r') as f:
        content = f.read()
    assert "load_config" in content

# ── 41. Episode Scorer (MemRL Pattern) ──────────────────────────────────
print("\n🎯 Episode Scorer (MemRL)")

@test("episode_scorer: import module")
def _():
    import myalicia.skills.episode_scorer

@test("episode_scorer: score_episode callable")
def _():
    from myalicia.skills.episode_scorer import score_episode
    assert callable(score_episode)

@test("episode_scorer: score_episode returns float")
def _():
    from myalicia.skills.episode_scorer import score_episode
    ep = {"score": "4", "reflection": {"confidence": 4, "procedure_update": "test"}}
    result = score_episode(ep)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0

@test("episode_scorer: get_rewarded_reflections callable")
def _():
    from myalicia.skills.episode_scorer import get_rewarded_reflections
    assert callable(get_rewarded_reflections)

@test("episode_scorer: run_daily_scoring callable")
def _():
    from myalicia.skills.episode_scorer import run_daily_scoring
    assert callable(run_daily_scoring)

@test("episode_scorer: get_episode_stats callable")
def _():
    from myalicia.skills.episode_scorer import get_episode_stats
    assert callable(get_episode_stats)

@test("episode_scorer: get_top_strategies callable")
def _():
    from myalicia.skills.episode_scorer import get_top_strategies
    assert callable(get_top_strategies)

@test("episode_scorer: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.episode_scorer import" in content

@test("episode_scorer: get_rewarded_reflections used in retrieval")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "get_rewarded_reflections" in content

@test("episode_scorer: daily scoring scheduled")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "run_daily_scoring" in content
    assert "22:55" in content

@test("episode_scorer: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "episode_scorer.py")
    py_compile.compile(filepath, doraise=True)

# ── 42. Meta-Reflexion (Hyperagents Pattern) ────────────────────────────
print("\n🔬 Meta-Reflexion (Hyperagents)")

@test("meta_reflexion: import module")
def _():
    import myalicia.skills.meta_reflexion

@test("meta_reflexion: run_meta_reflexion callable")
def _():
    from myalicia.skills.meta_reflexion import run_meta_reflexion
    assert callable(run_meta_reflexion)

@test("meta_reflexion: evaluate_improve_effectiveness callable")
def _():
    from myalicia.skills.meta_reflexion import evaluate_improve_effectiveness
    assert callable(evaluate_improve_effectiveness)

@test("meta_reflexion: get_meta_reflexion_context callable")
def _():
    from myalicia.skills.meta_reflexion import get_meta_reflexion_context
    assert callable(get_meta_reflexion_context)

@test("meta_reflexion: format_meta_report callable")
def _():
    from myalicia.skills.meta_reflexion import format_meta_report
    assert callable(format_meta_report)

@test("meta_reflexion: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.meta_reflexion import" in content

@test("meta_reflexion: wired in weekly pass")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "run_meta_reflexion()" in content

@test("meta_reflexion: context injected into /improve")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "self_improve.py"), 'r') as f:
        content = f.read()
    assert "get_meta_reflexion_context" in content

@test("meta_reflexion: self_improve.md config exists")
def _():
    config_path = os.path.join(PROJECT_ROOT, "skills", "configs", "self_improve.md")
    assert os.path.isfile(config_path)

@test("meta_reflexion: validate_improve_outputs callable (H4)")
def _():
    from myalicia.skills.meta_reflexion import validate_improve_outputs
    assert callable(validate_improve_outputs)

@test("meta_reflexion: get_improve_validations_context callable (H4)")
def _():
    from myalicia.skills.meta_reflexion import get_improve_validations_context
    assert callable(get_improve_validations_context)

@test("meta_reflexion: H4 validation scheduler wired in alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "validate_improve_outputs" in content
    assert "improve_validation" in content
    assert 'monday.at("22:00")' in content

@test("meta_reflexion: H4 validation context injected into /improve")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "self_improve.py"), 'r') as f:
        content = f.read()
    assert "get_improve_validations_context" in content
    assert "improve_validations_context" in content

@test("meta_reflexion: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "meta_reflexion.py")
    py_compile.compile(filepath, doraise=True)

# ── 42b. Bridge State (H2: Desktop-readable snapshot) ────────────────────
print("\n🌉 Bridge State (H2)")

@test("bridge_state: import module")
def _():
    import myalicia.skills.bridge_state

@test("bridge_state: write_alicia_state_snapshot callable")
def _():
    from myalicia.skills.bridge_state import write_alicia_state_snapshot
    assert callable(write_alicia_state_snapshot)

@test("bridge_state: read_alicia_state_snapshot callable")
def _():
    from myalicia.skills.bridge_state import read_alicia_state_snapshot
    assert callable(read_alicia_state_snapshot)

@test("bridge_state: build_snapshot returns dict with required keys")
def _():
    from myalicia.skills.bridge_state import build_snapshot
    snap = build_snapshot()
    assert isinstance(snap, dict)
    for key in ("generated_at", "season", "emergence_score",
                "archetype_weights", "mood_signal", "hot_threads"):
        assert key in snap, f"missing key: {key}"

@test("bridge_state: wired into alicia.py scheduler")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "write_alicia_state_snapshot" in content
    assert "bridge_snapshot" in content

@test("bridge_state: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "bridge_state.py")
    py_compile.compile(filepath, doraise=True)

# ── 42b. Bridge Protocol (§6.4 single-owner I/O) ────────────────────────
print("\n🌉 Bridge Protocol (single-owner I/O)")

@test("bridge_protocol: import module")
def _():
    import myalicia.skills.bridge_protocol

@test("bridge_protocol: core functions callable")
def _():
    from myalicia.skills.bridge_protocol import (
        bridge_path, ensure_bridge_dir, write_bridge_json, read_bridge_json,
        write_bridge_text, read_bridge_text, list_bridge_reports,
        get_latest_report, reports_since, tail_index,
    )
    for fn in (bridge_path, ensure_bridge_dir, write_bridge_json, read_bridge_json,
               write_bridge_text, read_bridge_text, list_bridge_reports,
               get_latest_report, reports_since, tail_index):
        assert callable(fn)

@test("bridge_protocol: path containment rejects traversal")
def _():
    from myalicia.skills.bridge_protocol import bridge_path
    for bad in ["../../etc/passwd", "/etc/passwd", "foo/../bar"]:
        try:
            bridge_path(bad)
            raise AssertionError("expected ValueError for " + repr(bad))
        except ValueError:
            pass

@test("bridge_protocol: BRIDGE_DIR resolves under VAULT_ROOT")
def _():
    from myalicia.skills.bridge_protocol import BRIDGE_DIR
    assert str(BRIDGE_DIR).endswith("/Alicia/Bridge")

@test("bridge_protocol: bridge_state migrated to use it")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "bridge_state.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import" in content
    assert "write_bridge_json" in content

@test("bridge_protocol: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "bridge_protocol.py")
    py_compile.compile(filepath, doraise=True)

# ── 42b. Track D #1 — writer migrations to bridge_protocol ──────────────
print("\n🌉  Track D #D1 — analysis/* writers migrated to bridge_protocol")

@test("analysis_contradiction: migrated to write_bridge_text")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_contradiction.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import write_bridge_text" in content
    assert "write_bridge_text(" in content

@test("analysis_dialogue_depth: migrated to write_bridge_text")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_dialogue_depth.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import write_bridge_text" in content
    assert "write_bridge_text(" in content

@test("analysis_temporal: migrated to write_bridge_text")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_temporal.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import write_bridge_text" in content
    assert "write_bridge_text(" in content

@test("analysis_growth_edge: migrated to write_bridge_text")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_growth_edge.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import write_bridge_text" in content
    assert "write_bridge_text(" in content

@test("memory_skill: telegram-session write migrated to write_bridge_text")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "memory_skill.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import write_bridge_text" in content
    assert 'write_bridge_text(f"telegram-sessions/' in content

@test("feedback_loop: reader migrated to get_latest_report")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "feedback_loop.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import get_latest_report" in content
    # No more ad-hoc os.listdir sweeps across BRIDGE_DIR
    assert "os.listdir(BRIDGE_DIR)" not in content

@test("analysis_coordination: reader migrated to list_bridge_reports")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_coordination.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import list_bridge_reports" in content
    # The glob(os.path.join(BRIDGE_DIR, ...)) pattern is gone
    assert "glob(os.path.join(BRIDGE_DIR," not in content

@test("way_of_being: reader migrated to get_latest_report")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "way_of_being.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import get_latest_report" in content
    # No more os.listdir(bridge_path) sweeps
    assert "os.listdir(bridge_path)" not in content

@test("analysis_briefing: reader migrated to list_bridge_reports")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "analysis_briefing.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.bridge_protocol import list_bridge_reports" in content
    assert "BRIDGE_FOLDER.glob(pattern)" not in content

# ── 42c. Bridge Schema (§6.5 JSON-schema validation) ────────────────────
print("\n🛡️  Bridge Schema (JSON-schema validation)")

@test("bridge_schema: import module")
def _():
    import myalicia.skills.bridge_schema

@test("bridge_schema: registered schemas for 14 state files")
def _():
    from myalicia.skills.bridge_schema import list_schemas
    names = list_schemas()
    required = {"alicia-state.json", "emergence_state.json", "episode_scores.json",
                "muse_state.json", "daily_rhythm.json", "session_threads.json",
                "effectiveness_state.json", "temporal_patterns.json",
                "voice_intelligence.json", "curiosity_queue.json",
                "autonomy_state.json", "voice_signature.json",
                # §D3 additions:
                "challenge_log.json", "overnight_state.json"}
    missing = required - set(names)
    assert not missing, f"Missing schemas: {missing}"

@test("bridge_schema: validate accepts valid alicia-state payload")
def _():
    from myalicia.skills.bridge_schema import validate
    validate("alicia-state.json", {
        "generated_at": "2026-04-16T17:00:00Z",
        "season": "First Light",
        "emergence_score": 9.2,
        "archetype_weights": {"beatrice": 0.28},
        "mood_signal": "contemplative",
        "hot_threads": ["abstraction"],
    })

@test("bridge_schema: validate rejects missing required fields")
def _():
    from myalicia.skills.bridge_schema import validate, ValidationError
    try:
        validate("alicia-state.json", {"season": "x"})
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass

@test("bridge_schema: validate_strict rejects unknown filename")
def _():
    from myalicia.skills.bridge_schema import validate_strict, ValidationError
    try:
        validate_strict("nonexistent-file.json", {})
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass

@test("bridge_schema: validate is no-op for unregistered (non-strict)")
def _():
    from myalicia.skills.bridge_schema import validate
    validate("some-random-file.json", {"anything": True})  # must not raise

@test("bridge_schema: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "bridge_schema.py")
    py_compile.compile(filepath, doraise=True)

# ── 42c2. Track D #D3 — schema coverage expansion ─────────────────────
print("\n🛡️  Track D #D3 — extended schema coverage")

@test("bridge_schema: challenge_log + overnight_state schemas registered")
def _():
    from myalicia.skills.bridge_schema import has_schema
    assert has_schema("challenge_log.json")
    assert has_schema("overnight_state.json")

@test("bridge_schema: JSONL per-line schemas (4 new)")
def _():
    from myalicia.skills.bridge_schema import list_jsonl_schemas
    names = set(list_jsonl_schemas())
    required = {
        "improve_validations.jsonl",
        "depth_signals.jsonl",
        "voice_metadata_log.jsonl",
        "curiosity_followthrough.jsonl",
    }
    missing = required - names
    assert not missing, f"Missing JSONL schemas: {missing}"

@test("bridge_schema: validate_jsonl_line accepts valid improve line")
def _():
    from myalicia.skills.bridge_schema import validate_jsonl_line
    validate_jsonl_line("improve_validations.jsonl", {
        "validated_at": "2026-04-16T22:00:00",
        "improve_run_at": "2026-04-14 20:00:00",
        "skill": "curiosity_engine",
        "change_type": "parameter_update",
        "reasoning": "raised novelty threshold",
        "episodes_before": 20,
        "reward_before": 0.42,
        "episodes_after": 18,
        "reward_after": 0.51,
        "delta": 0.09,
        "assessment": "helped",
        "window_days": 7,
    })

@test("bridge_schema: validate_jsonl_line rejects missing required")
def _():
    from myalicia.skills.bridge_schema import validate_jsonl_line, ValidationError
    try:
        validate_jsonl_line("improve_validations.jsonl", {"skill": "x"})
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass

@test("bridge_schema: depth_signals.jsonl per-line schema enforces shape")
def _():
    from myalicia.skills.bridge_schema import validate_jsonl_line, ValidationError
    # Good
    validate_jsonl_line("depth_signals.jsonl", {
        "timestamp": "2026-04-16T17:00:00Z",
        "topic": "abstraction",
        "word_count": 120,
        "source": "daimon_warning",
    })
    # Bad — missing source
    try:
        validate_jsonl_line("depth_signals.jsonl", {
            "timestamp": "2026-04-16T17:00:00Z",
            "topic": "abstraction",
        })
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass

@test("bridge_schema: validate_jsonl_line_strict rejects unregistered")
def _():
    from myalicia.skills.bridge_schema import validate_jsonl_line_strict, ValidationError
    try:
        validate_jsonl_line_strict("unknown.jsonl", {"x": 1})
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass

@test("meta_reflexion: validates improve lines before writing")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "meta_reflexion.py"), 'r') as f:
        content = f.read()
    assert "validate_jsonl_line" in content
    assert "improve_validations.jsonl" in content

# ── 42d. Chat Guard + New Telegram Commands (§5.4, §2.3 H5) ─────────────
print("\n🔐 Chat Guard + new commands")

@test("alicia.py: chat_guard decorator defined")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "def chat_guard(fn):" in content

@test("alicia.py: chat_guard applied to handle_message_reaction")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "async def handle_message_reaction" in line:
            # Previous non-blank line should be @chat_guard
            prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
            assert prev.strip() == "@chat_guard", f"Expected @chat_guard, got: {prev!r}"
            return
    raise AssertionError("handle_message_reaction not found")

@test("alicia.py: cmd_bridge handler defined + registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "async def cmd_bridge" in content
    assert '("bridge",         cmd_bridge)' in content

@test("alicia.py: cmd_diarize handler defined + registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "async def cmd_diarize" in content
    assert '("diarize",        cmd_diarize)' in content

@test("alicia.py: cmd_scout handler defined + registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "async def cmd_scout" in content
    assert '("scout",          cmd_scout)' in content

@test("alicia.py: cmd_handoff handler defined + registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "async def cmd_handoff" in content
    assert '("handoff",        cmd_handoff)' in content

@test("alicia.py: new commands wrapped by @chat_guard")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        for name in ("cmd_bridge", "cmd_diarize", "cmd_scout", "cmd_handoff"):
            if line.strip().startswith(f"async def {name}("):
                prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
                assert prev.strip() == "@chat_guard", \
                    f"{name} missing @chat_guard decorator (prev: {prev!r})"

# ── 42e. Context-resolver cache + shortcut (§4.4) ───────────────────────
print("\n⚡ Context-resolver cache + shortcut")

@test("context_resolver: SHORTCUT_TOKENS defined and non-empty")
def _():
    from myalicia.skills.context_resolver import SHORTCUT_TOKENS
    assert isinstance(SHORTCUT_TOKENS, frozenset)
    assert len(SHORTCUT_TOKENS) >= 20
    for t in ("hi", "thanks", "ok", "yes", "no", "bye"):
        assert t in SHORTCUT_TOKENS

@test("context_resolver: _is_shortcut recognises greetings + acks")
def _():
    from myalicia.skills.context_resolver import _is_shortcut
    for pos in ("hi", "Hi", "thanks.", "ok?", "yes", "nope"):
        assert _is_shortcut(pos), f"{pos!r} should be shortcut"
    for neg in ("tell me about serendipity", "what do you remember"):
        assert not _is_shortcut(neg), f"{neg!r} should NOT be shortcut"

@test("context_resolver: cache helpers exposed")
def _():
    from myalicia.skills.context_resolver import (
        get_resolver_cache_stats, clear_resolver_cache,
        RESOLVER_CACHE_TTL, RESOLVER_CACHE_MAX,
    )
    assert callable(get_resolver_cache_stats)
    assert callable(clear_resolver_cache)
    assert RESOLVER_CACHE_TTL > 0
    assert RESOLVER_CACHE_MAX > 0

@test("context_resolver: cache stats shape")
def _():
    from myalicia.skills.context_resolver import get_resolver_cache_stats, clear_resolver_cache
    clear_resolver_cache()
    stats = get_resolver_cache_stats()
    for key in ("size", "max", "ttl_s", "hit", "miss", "skipped"):
        assert key in stats, f"Missing stats key: {key}"
    assert stats["size"] == 0

# ── 42f. Track D #D2 — resolver observability ──────────────────────────
print("\n🧭  Track D #D2 — resolver observability")

@test("context_resolver: get_resolver_module_usage exposed")
def _():
    from myalicia.skills.context_resolver import (
        get_resolver_module_usage, clear_resolver_module_usage,
    )
    assert callable(get_resolver_module_usage)
    assert callable(clear_resolver_module_usage)

@test("context_resolver: module usage counter increments on shortcut path")
def _():
    from myalicia.skills.context_resolver import (
        resolve_context_modules,
        get_resolver_module_usage,
        clear_resolver_module_usage,
        clear_resolver_cache,
    )
    clear_resolver_module_usage()
    clear_resolver_cache()
    # "hi" hits the shortcut path — no Haiku call, but must still record.
    resolve_context_modules("hi", is_voice=False)
    usage = get_resolver_module_usage()
    assert usage.get("session_context", 0) == 1, f"usage missing session_context: {usage}"

@test("alicia.py: cmd_resolver_stats defined")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "async def cmd_resolver_stats(" in content
    assert "get_resolver_module_usage" in content

@test("alicia.py: /resolver-stats command registered")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert '("resolver-stats",' in content or '("resolverstats",' in content

@test("alicia.py: cmd_status surfaces resolver line")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    # Inline import + resolver_line composition both present in cmd_status.
    assert "resolver_line" in content
    assert "get_resolver_cache_stats" in content

@test("alicia.py: morning boot message includes resolver signal")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    # Fresh-boot resolver line appended to the startup checks list.
    assert "🧭 Resolver" in content or "Resolver: idle" in content

# ── 43. Skill Library (Memento-Skills Pattern) ──────────────────────────
print("\n📚 Skill Library (Memento-Skills)")

@test("skill_library: import module")
def _():
    import myalicia.skills.skill_library

@test("skill_library: scan_skill_library callable")
def _():
    from myalicia.skills.skill_library import scan_skill_library
    assert callable(scan_skill_library)

@test("skill_library: scan returns valid structure")
def _():
    from myalicia.skills.skill_library import scan_skill_library
    result = scan_skill_library()
    assert isinstance(result, dict)
    assert "skills" in result
    assert "health" in result
    assert len(result["skills"]) >= 7, f"Expected 7+ configs, got {len(result['skills'])}"

@test("skill_library: run_weekly_library_health callable")
def _():
    from myalicia.skills.skill_library import run_weekly_library_health
    assert callable(run_weekly_library_health)

@test("skill_library: format_library_report callable")
def _():
    from myalicia.skills.skill_library import format_library_report
    assert callable(format_library_report)

@test("skill_library: get_library_context returns string")
def _():
    from myalicia.skills.skill_library import get_library_context
    result = get_library_context()
    assert isinstance(result, str)

@test("skill_library: wired in alicia.py imports")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "from myalicia.skills.skill_library import" in content

@test("skill_library: wired in weekly pass")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), 'r') as f:
        content = f.read()
    assert "run_weekly_library_health()" in content

@test("skill_library: context injected into /improve")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills", "self_improve.py"), 'r') as f:
        content = f.read()
    assert "get_library_context" in content

@test("skill_library: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "skill_library.py")
    py_compile.compile(filepath, doraise=True)

# ═══════════════════════════════════════════════════════════════════════════
# Drawing Skill — Alicia's visual voice
# ═══════════════════════════════════════════════════════════════════════════

@test("drawing_skill: module importable with all public symbols")
def _():
    from myalicia.skills.drawing_skill import (
        generate_drawing, can_draw_now, record_drawing_sent,
        get_drawing_stats, render_png, render_gif,
        recent_drawings, VALID_ARCHETYPES, DRAWINGS_DIR, DRAWING_LOG,
    )
    assert callable(generate_drawing)
    assert callable(can_draw_now)
    assert callable(record_drawing_sent)
    assert callable(get_drawing_stats)
    assert callable(render_png)
    assert callable(render_gif)
    assert callable(recent_drawings)
    # Must have all six archetypes
    assert VALID_ARCHETYPES == {"beatrice", "daimon", "ariadne",
                                "psyche", "musubi", "muse"}
    assert str(DRAWINGS_DIR).endswith("memory/drawings")
    assert str(DRAWING_LOG).endswith("drawing_log.jsonl")

@test("drawing_skill: _params_for_archetype produces valid params per archetype")
def _():
    from myalicia.skills.drawing_skill import _params_for_archetype
    for arc in ("beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"):
        p = _params_for_archetype(arc, seed=42)
        assert p.attractors, f"{arc} has no attractors"
        assert p.n_seeds > 0
        assert p.canvas[0] > 0 and p.canvas[1] > 0
        assert 0 < p.density_gate < 1
        assert p.vignette is not None

@test("drawing_skill: render_png produces a valid image file")
def _():
    import tempfile
    from pathlib import Path
    from PIL import Image
    from myalicia.skills import drawing_skill as ds
    # Shrink params so the test runs fast (~0.5s)
    orig = ds._params_for_archetype
    def small(arc, seed):
        p = orig(arc, seed)
        p.canvas = (300, 300)
        p.output_size = (200, 200)
        p.n_seeds = max(50, p.n_seeds // 20)
        p.max_length = 150
        return p
    ds._params_for_archetype = small
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "test.png"
            ds.render_png("beatrice", seed=123, out_path=out)
            assert out.exists(), "PNG not written"
            img = Image.open(out)
            assert img.size == (200, 200)
            assert img.mode == "RGB"
    finally:
        ds._params_for_archetype = orig

@test("drawing_skill: can_draw_now returns True when log is empty")
def _():
    import tempfile
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    real_log = ds.DRAWING_LOG
    with tempfile.TemporaryDirectory() as td:
        ds.DRAWING_LOG = Path(td) / "empty.jsonl"
        try:
            ok, reason = ds.can_draw_now()
            assert ok is True, f"expected OK with empty log, got {reason}"
        finally:
            ds.DRAWING_LOG = real_log

@test("drawing_skill: can_draw_now enforces min_hours_between")
def _():
    import tempfile, json, time
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    real_log = ds.DRAWING_LOG
    with tempfile.TemporaryDirectory() as td:
        ds.DRAWING_LOG = Path(td) / "log.jsonl"
        with open(ds.DRAWING_LOG, "w") as f:
            f.write(json.dumps({
                "ts": time.time() - 60,
                "date": "2026-04-19T00:00:00+00:00",
                "archetype": "muse",
                "path": "x.png",
                "kind": "png",
            }) + "\n")
        try:
            ok, reason = ds.can_draw_now()
            assert ok is False, f"expected BLOCKED, got {reason}"
        finally:
            ds.DRAWING_LOG = real_log

@test("drawing_skill: record_drawing_sent + recent_drawings round-trip")
def _():
    import tempfile
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    real_log = ds.DRAWING_LOG
    with tempfile.TemporaryDirectory() as td:
        ds.DRAWING_LOG = Path(td) / "rt.jsonl"
        try:
            ds.record_drawing_sent("a.png", "beatrice",
                                   caption="noticed.", kind="png")
            ds.record_drawing_sent("b.png", "muse",
                                   caption="lifting.", kind="gif")
            got = ds.recent_drawings(n=5)
            assert len(got) == 2
            assert {g["archetype"] for g in got} == {"beatrice", "muse"}
        finally:
            ds.DRAWING_LOG = real_log

@test("drawing_skill: manual /draw does NOT count against impulse cap")
def _():
    # Regression guard — <earlier development> ghost-entry bug. Manual /draw was
    # logged the same way as impulse drawings, so 9 manual calls at night
    # burned through the daily cap and starved Alicia's spontaneous voice
    # for a full day. Manual entries must be transparent to can_draw_now.
    import tempfile, json, time
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    real_log = ds.DRAWING_LOG
    real_max = ds.MAX_PER_DAY
    real_gap = ds.MIN_HOURS_BETWEEN
    with tempfile.TemporaryDirectory() as td:
        ds.DRAWING_LOG = Path(td) / "mixed.jsonl"
        ds.MAX_PER_DAY = 4
        ds.MIN_HOURS_BETWEEN = 0.0  # isolate cap-count logic from gap logic
        try:
            today_iso = ds.datetime.now(ds.timezone.utc).date().isoformat()
            # 20 manual drawings today — should NOT block impulse
            with open(ds.DRAWING_LOG, "w") as f:
                for i in range(20):
                    f.write(json.dumps({
                        "ts": time.time() - 3600 - i,
                        "date": f"{today_iso}T00:{i:02d}:00+00:00",
                        "archetype": "muse",
                        "path": f"m{i}.png",
                        "kind": "png",
                        "source": "manual",
                    }) + "\n")
            ok, reason = ds.can_draw_now()
            assert ok is True, \
                f"manual drawings must not count against cap, got: {reason}"
        finally:
            ds.DRAWING_LOG = real_log
            ds.MAX_PER_DAY = real_max
            ds.MIN_HOURS_BETWEEN = real_gap

@test("drawing_skill: impulse entries DO count against daily cap")
def _():
    import tempfile, json, time
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    real_log = ds.DRAWING_LOG
    real_max = ds.MAX_PER_DAY
    real_gap = ds.MIN_HOURS_BETWEEN
    with tempfile.TemporaryDirectory() as td:
        ds.DRAWING_LOG = Path(td) / "impulse.jsonl"
        ds.MAX_PER_DAY = 4
        ds.MIN_HOURS_BETWEEN = 0.0
        try:
            today_iso = ds.datetime.now(ds.timezone.utc).date().isoformat()
            with open(ds.DRAWING_LOG, "w") as f:
                for i in range(4):
                    f.write(json.dumps({
                        "ts": time.time() - 3600 - i,
                        "date": f"{today_iso}T00:{i:02d}:00+00:00",
                        "archetype": "muse",
                        "path": f"i{i}.png",
                        "kind": "png",
                        "source": "impulse",
                    }) + "\n")
            ok, reason = ds.can_draw_now()
            assert ok is False, \
                f"4 impulse entries must trip the cap, got: {reason}"
            assert "cap" in reason.lower(), f"unexpected block reason: {reason}"
        finally:
            ds.DRAWING_LOG = real_log
            ds.MAX_PER_DAY = real_max
            ds.MIN_HOURS_BETWEEN = real_gap

@test("drawing_skill: cmd_draw passes source='manual', impulse passes 'impulse'")
def _():
    # Structural wiring check — the split is enforced at the call site,
    # not just in the function signature.
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), "r") as f:
        content = f.read()
    # cmd_draw block must pass source="manual"
    assert 'source="manual"' in content, \
        "cmd_draw must call record_drawing_sent with source='manual'"
    # send_drawing_impulse block must pass source="impulse"
    assert 'source="impulse"' in content, \
        "send_drawing_impulse must call record_drawing_sent with source='impulse'"

@test("drawing_skill: can_draw_now uses LOCAL date, not UTC")
def _():
    # Regression guard — <earlier development> UTC-rollover-at-5-PM-Pacific bug.
    # Nine Sunday-evening drawings were charged against UTC Monday's
    # budget, starving lived-Monday impulses all day. "Today" must
    # mean what the user is living, not what Greenwich is living.
    import inspect
    from myalicia.skills import drawing_skill as ds
    src = inspect.getsource(ds.can_draw_now)
    # Must NOT use UTC-anchored "today"
    assert "datetime.now(timezone.utc).date()" not in src, (
        "can_draw_now must use local date for cap — UTC midnight "
        "rolls over at 5pm Pacific and charges evening drawings to "
        "tomorrow's budget"
    )
    # Must use local now() and convert entries via fromtimestamp
    assert "datetime.now().date()" in src, \
        "can_draw_now must compute today in local timezone"
    assert "fromtimestamp" in src, \
        "can_draw_now must convert entry ts via fromtimestamp (local)"

@test("drawing_skill: get_drawing_stats uses LOCAL date")
def _():
    import inspect
    from myalicia.skills import drawing_skill as ds
    src = inspect.getsource(ds.get_drawing_stats)
    assert "datetime.now(timezone.utc).date()" not in src, \
        "get_drawing_stats must use local date for 'today'"
    assert "datetime.now().date()" in src
    assert "fromtimestamp" in src

@test("inner_life: user-facing 'today' comparisons use LOCAL date")
def _():
    # Audit guard — several inner_life sites (emergence days-since-epoch,
    # muse state, archetype daily budget, morning/evening reflection
    # filenames) must use local date so the user's lived day rolls over
    # at their midnight, not UTC midnight.
    import re
    path = os.path.join(PROJECT_ROOT, "skills", "inner_life.py")
    with open(path, "r") as f:
        content = f.read()
    # Line numbers will drift — grep by call shape. The following call
    # sites should NOT be UTC-anchored (they compute "today" semantics):
    forbidden = [
        # _days_since_epoch
        "today = datetime.now(timezone.utc).date()\n",
        # _persist_emergence_state reset
        "today = datetime.now(timezone.utc).date().isoformat()\n",
        # morning reflection filename
        'today = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n',
    ]
    for pat in forbidden:
        count = content.count(pat)
        assert count == 0, (
            f"inner_life.py still has UTC-anchored 'today' at "
            f"{count} site(s): {pat.strip()}"
        )

@test("muse: serendipity day boundary uses LOCAL date")
def _():
    path = os.path.join(PROJECT_ROOT, "skills", "muse.py")
    with open(path, "r") as f:
        content = f.read()
    assert "datetime.now(timezone.utc).date().isoformat()" not in content, (
        "muse.py serendipity cap must use local date — otherwise the "
        "daily moment budget resets mid-afternoon for Pacific users"
    )

@test("episode_scorer: 'indexed today' compares LOCAL dates")
def _():
    # The stored timestamp is UTC ISO. When computing "indexed today",
    # both sides must be in the same timezone — local — otherwise the
    # count is off by a full day for users outside UTC.
    import inspect
    from myalicia.skills import episode_scorer as es
    # Find the stats function that computes indexed_today
    funcs = [name for name in dir(es)
             if callable(getattr(es, name)) and not name.startswith("_")]
    found = False
    for name in funcs:
        try:
            src = inspect.getsource(getattr(es, name))
        except (OSError, TypeError):
            continue
        if "indexed_today" in src:
            found = True
            assert "astimezone()" in src or "datetime.now(timezone.utc)" in src, (
                f"episode_scorer.{name}: UTC ts must be converted to "
                f"local before comparing against local today"
            )
    assert found, "episode_scorer: indexed_today logic not found"

@test("drawing_skill: wired into alicia.py")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), "r") as f:
        content = f.read()
    assert "from myalicia.skills.drawing_skill import" in content, \
        "drawing_skill not imported in alicia.py"
    assert "generate_drawing" in content
    assert "record_drawing_sent" in content
    assert '("draw",' in content, "/draw command not registered"
    assert '("drawstats",' in content, "/drawstats command not registered"
    assert "send_drawing_impulse" in content, \
        "send_drawing_impulse not defined"
    assert 'safe_run("drawing_impulse"' in content, \
        "drawing_impulse not scheduled"
    assert '("drawing_skill", "generate_drawing")' in content, \
        "drawing_skill not in STARTUP_IMPORT_CHECKS"

@test("drawing_skill: skill config exists with required sections")
def _():
    config_path = os.path.join(PROJECT_ROOT, "skills", "configs",
                               "drawing_skill.md")
    assert os.path.exists(config_path), f"missing {config_path}"
    with open(config_path, "r") as f:
        content = f.read()
    for section in ("## Procedure", "## Parameters",
                    "## Learned Rules", "## Evaluation Criteria"):
        assert section in content, f"drawing_skill.md missing {section}"

@test("drawing_skill: valid syntax")
def _():
    filepath = os.path.join(PROJECT_ROOT, "skills", "drawing_skill.py")
    py_compile.compile(filepath, doraise=True)

@test("drawing_skill: interpret_prompt_to_params fallback returns valid shape")
def _():
    # With no ANTHROPIC_API_KEY set (monkey-patched), the interpreter must
    # still return a valid dict with all keys, clamped to ranges.
    import myalicia.skills.drawing_skill as ds
    orig_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        r = ds.interpret_prompt_to_params(phrase="your current thinking")
        assert r["archetype"] in ds.VALID_ARCHETYPES
        for knob, (lo, hi) in ds._KNOB_RANGES.items():
            assert lo <= r[knob] <= hi, f"{knob} out of range: {r[knob]}"
        assert isinstance(r["caption"], str) and r["caption"]
    finally:
        if orig_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = orig_key

@test("drawing_skill: build_drawing_state_snapshot returns dict with time")
def _():
    import myalicia.skills.drawing_skill as ds
    snap = ds.build_drawing_state_snapshot()
    assert isinstance(snap, dict)
    assert "time_of_day" in snap  # minimum guaranteed key

@test("drawing_skill: _apply_knobs modulates DrawingParams within safe floors")
def _():
    import myalicia.skills.drawing_skill as ds
    base = ds._params_for_archetype("beatrice", seed=42)
    n_seeds_0 = base.n_seeds
    step_0 = base.step_size
    stroke_0 = base.stroke_weight
    gate_0 = base.density_gate
    # Apply max knobs
    p = ds._params_for_archetype("beatrice", seed=42)
    ds._apply_knobs(p, {"density": 1.5, "energy": 1.5,
                        "whitespace": 0.4, "stroke": 1.8})
    assert p.n_seeds > n_seeds_0, "density=1.5 should increase n_seeds"
    assert p.step_size > step_0, "energy=1.5 should increase step_size"
    assert p.stroke_weight > stroke_0, "stroke=1.8 should increase weight"
    assert p.density_gate > gate_0, "whitespace>0 should raise gate"
    assert p.density_gate <= 0.80, "gate must be capped at 0.80"
    # Apply min knobs — floors must hold
    p2 = ds._params_for_archetype("daimon", seed=42)
    ds._apply_knobs(p2, {"density": 0.3, "energy": 0.6,
                         "whitespace": 0.0, "stroke": 0.7})
    assert p2.n_seeds >= 150
    assert p2.step_size >= 0.6
    assert p2.stroke_weight >= 0.4

@test("drawing_skill: generate_drawing accepts prompt and state kwargs")
def _():
    import inspect
    import myalicia.skills.drawing_skill as ds
    sig = inspect.signature(ds.generate_drawing)
    assert "prompt" in sig.parameters, "generate_drawing must accept prompt="
    assert "state" in sig.parameters, "generate_drawing must accept state="

@test("drawing_skill: cmd_draw routes freeform tokens as prompt")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), "r") as f:
        content = f.read()
    import re as _re
    m = _re.search(
        r"async def cmd_draw\([^)]*\)[^:]*:(.*?)\n(?:async\s+)?def ",
        content, _re.DOTALL,
    )
    assert m, "cmd_draw body not found"
    body = m.group(1)
    assert "freeform_tokens" in body, \
        "cmd_draw must collect non-archetype/non-gif tokens as freeform"
    assert "prompt=prompt" in body, \
        "cmd_draw must pass prompt= to generate_drawing"
    assert "build_drawing_state_snapshot" in body, \
        "cmd_draw must fall back to state snapshot when no archetype + no prompt"

@test("drawing_skill: send_drawing_impulse passes state snapshot")
def _():
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), "r") as f:
        content = f.read()
    import re as _re
    m = _re.search(
        r"async def send_drawing_impulse\([^)]*\):(.*?)\n\s+# Check every",
        content, _re.DOTALL,
    )
    assert m, "send_drawing_impulse body not found"
    body = m.group(1)
    assert "build_drawing_state_snapshot" in body, \
        "send_drawing_impulse must build a state snapshot"
    assert "state=state" in body, \
        "send_drawing_impulse must pass state= to generate_drawing"

@test("drawing_skill: _send_drawing wires reactions into archetype attribution")
def _():
    # Gap 1 + Gap 3 closure for the drawing channel.
    # _send_drawing must capture the Telegram message_id and call
    # track_reply_for_reaction with task_type="drawing" and the archetype,
    # so reactions flow into log_archetype_attribution.
    import re as _re
    with open(os.path.join(PROJECT_ROOT, "alicia.py"), "r") as f:
        content = f.read()
    m = _re.search(
        r"async def _send_drawing\([^)]*\)[^:]*:(.*?)\n(?:async\s+)?def ",
        content, _re.DOTALL,
    )
    assert m, "_send_drawing function body not found"
    body = m.group(1)
    assert "sent_msg" in body, \
        "_send_drawing must capture the returned Telegram message object"
    assert "track_reply_for_reaction" in body, \
        "_send_drawing must call track_reply_for_reaction for reaction feedback"
    assert 'task_type="drawing"' in body, \
        "_send_drawing must tag the tracked reply as task_type=drawing"
    assert "archetype=archetype" in body, \
        "_send_drawing must pass archetype into track_reply_for_reaction"


@test("drawing_skill v2: DrawingParams exposes stroke_style + stroke_variance")
def _():
    from myalicia.skills.drawing_skill import DrawingParams
    p = DrawingParams()
    assert hasattr(p, "stroke_style"), "DrawingParams missing stroke_style"
    assert hasattr(p, "stroke_variance"), "DrawingParams missing stroke_variance"
    assert isinstance(p.stroke_style, str)
    assert 0.0 <= float(p.stroke_variance) <= 1.0


@test("drawing_skill v2: each archetype has a recognised stroke_style")
def _():
    from myalicia.skills.drawing_skill import _params_for_archetype, VALID_ARCHETYPES
    allowed = {"uniform", "bell", "fade_out", "fade_in", "variable"}
    got_styles = set()
    for a in VALID_ARCHETYPES:
        p = _params_for_archetype(a, seed=123)
        assert p.stroke_style in allowed, \
            f"archetype {a} has unknown stroke_style={p.stroke_style}"
        got_styles.add(p.stroke_style)
    # At least 4 of the 5 taper modes should be in active use across the six
    # archetypes — the whole point of the v2 pass is visible differentiation.
    assert len(got_styles) >= 4, \
        f"archetype stroke_style diversity too low: {got_styles}"


@test("drawing_skill v2: archetype density spread is wide (visual differentiation)")
def _():
    from myalicia.skills.drawing_skill import _params_for_archetype, VALID_ARCHETYPES
    seeds = [_params_for_archetype(a, seed=42).n_seeds for a in VALID_ARCHETYPES]
    assert min(seeds) <= 350, \
        f"expected at least one archetype with n_seeds <= 350 (sparse), got min={min(seeds)}"
    assert max(seeds) >= 900, \
        f"expected at least one archetype with n_seeds >= 900 (dense), got max={max(seeds)}"
    # Spread ratio — archetypes should differ by ≥3x in density
    assert max(seeds) / max(min(seeds), 1) >= 2.8, \
        f"density spread too narrow: {seeds}"


@test("drawing_skill v2: _draw_organic_streamline accepts all 5 taper modes")
def _():
    from PIL import Image, ImageDraw
    import random as _rnd
    from myalicia.skills.drawing_skill import _draw_organic_streamline
    img = Image.new("RGBA", (100, 100), (240, 238, 230, 255))
    draw = ImageDraw.Draw(img, "RGBA")
    pts = [(i * 5.0, 50.0 + i * 0.3) for i in range(18)]
    rng = _rnd.Random(0)
    for style in ("uniform", "bell", "fade_out", "fade_in", "variable"):
        # Must not raise — each style is a supported code path.
        _draw_organic_streamline(
            draw, pts,
            base_color=(30, 30, 28), base_alpha=180,
            base_width=1.2, style=style, variance=0.2, rng=rng,
        )


@test("drawing_skill v2: render_png works with new archetype params")
def _():
    # Regression guard: the v2 _params_for_archetype + organic strokes
    # must actually render end-to-end on a small canvas without raising.
    import tempfile
    from pathlib import Path
    from myalicia.skills import drawing_skill as ds
    # Pick a dense archetype to exercise the variable-stroke path
    params = ds._params_for_archetype("psyche", seed=777)
    params.canvas = (320, 320)
    params.output_size = (300, 300)
    params.n_seeds = 60  # keep test fast
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "v2.png"
        ds.render_png("psyche", 777, out, _params=params)
        assert out.exists() and out.stat().st_size > 1000, \
            "render_png v2 did not produce a valid image"


@test("drawing_skill v2: drawing_archetypes.md reference document exists")
def _():
    ref = os.path.join(PROJECT_ROOT, "skills", "drawing_archetypes.md")
    assert os.path.exists(ref), \
        "skills/drawing_archetypes.md must exist as the archetype source-of-truth"
    with open(ref, "r", encoding="utf-8") as f:
        content = f.read()
    # Must mention every archetype
    for a in ("beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"):
        assert a in content, f"drawing_archetypes.md missing {a}"
    # Must mention the stroke styles
    for s in ("fade_out", "fade_in", "bell", "variable", "uniform"):
        assert s in content, f"drawing_archetypes.md missing stroke style {s}"


# ─── Evening format variations (<earlier development> evening_template_weights wiring) ──
# Prior to this pass, evening_template_weights was a dead config key —
# /improve was tuning weights that no code path read. These tests cover the
# new EVENING_FORMATS + _pick_evening_format() dispatch and add a structural
# guardrail preventing the next dead-config drift.

@test("proactive_messages: EVENING_FORMATS defined with expected names")
def _():
    from myalicia.skills.proactive_messages import EVENING_FORMATS
    assert isinstance(EVENING_FORMATS, list)
    assert set(EVENING_FORMATS) >= {"reflection", "gratitude",
                                     "tomorrow", "energy_shift"}, \
        f"EVENING_FORMATS missing one of the 4 formats: {EVENING_FORMATS}"


@test("proactive_messages: every evening format has a builder function")
def _():
    from myalicia.skills import proactive_messages as pm
    for fmt in pm.EVENING_FORMATS:
        fn_name = f"_evening_{fmt}"
        assert hasattr(pm, fn_name), \
            f"EVENING_FORMATS includes '{fmt}' but proactive_messages has no {fn_name}()"
        assert callable(getattr(pm, fn_name)), \
            f"{fn_name} exists but is not callable"


@test("proactive_messages: _pick_evening_format returns a valid format")
def _():
    from myalicia.skills.proactive_messages import _pick_evening_format, EVENING_FORMATS
    for _ in range(8):
        got = _pick_evening_format()
        assert got in EVENING_FORMATS, \
            f"_pick_evening_format returned unknown format: {got}"


@test("proactive_messages: _pick_evening_format honours weight overrides")
def _():
    from myalicia.skills.proactive_messages import _pick_evening_format
    # Force gratitude by giving it the only positive weight
    got = _pick_evening_format({"gratitude": 1.0, "reflection": 0.0,
                                 "tomorrow": 0.0, "energy_shift": 0.0})
    assert got == "gratitude", \
        f"_pick_evening_format ignored weight override: got {got}"


@test("proactive_messages: _pick_evening_format falls back when weights all zero")
def _():
    from myalicia.skills.proactive_messages import _pick_evening_format, EVENING_FORMATS
    got = _pick_evening_format({"reflection": 0, "gratitude": 0,
                                 "tomorrow": 0, "energy_shift": 0})
    assert got == EVENING_FORMATS[0], \
        f"expected fallback to {EVENING_FORMATS[0]}, got {got}"


@test("proactive_messages: build_evening_message dispatches through _pick_evening_format")
def _():
    with open(os.path.join(PROJECT_ROOT, "skills/proactive_messages.py"), "r") as f:
        src = f.read()
    assert "_pick_evening_format(" in src, \
        "build_evening_message must call _pick_evening_format for format variety"
    # Every format must be routed to its builder from build_evening_message.
    for fmt in ("gratitude", "tomorrow", "energy_shift"):
        assert f'_evening_{fmt}' in src, \
            f"dispatch from build_evening_message to _evening_{fmt} is missing"


@test("proactive_messages: _load_template_weights parses config safely")
def _():
    # Contract: always returns a non-empty dict, never raises.
    from myalicia.skills.proactive_messages import (_load_template_weights,
                                            _DEFAULT_EVENING_WEIGHTS)
    out = _load_template_weights("evening_template_weights",
                                 _DEFAULT_EVENING_WEIGHTS)
    assert isinstance(out, dict) and out, \
        "_load_template_weights must return a non-empty dict"
    # Unknown key → defaults copy
    copy = _load_template_weights("nonexistent_key",
                                  _DEFAULT_EVENING_WEIGHTS)
    assert copy == _DEFAULT_EVENING_WEIGHTS, \
        "Unknown config key must fall back to supplied defaults"
    # Mutating the return must not leak into the default singleton
    copy["test_leak"] = 99
    assert "test_leak" not in _DEFAULT_EVENING_WEIGHTS, \
        "_load_template_weights must clone defaults to avoid singleton mutation"


# ─── Dead-config guardrail ─────────────────────────────────────────────────
# Every *_template_weights key in skills/configs/*.md must have at least one
# code reference under skills/*.py. Prevents /improve from tuning config
# keys no code path reads — the structural class of the March 2026 regression.

@test("configs: every *_template_weights key is referenced in code")
def _():
    import glob
    import re as _re
    configs_dir = os.path.join(PROJECT_ROOT, "skills", "configs")
    skills_dir = os.path.join(PROJECT_ROOT, "skills")

    # Collect every *_template_weights key name from all config files.
    # Config format is typically "- **foo_template_weights**: {...}" but
    # tolerate bare "foo_template_weights:" too. Strip the markdown bold
    # wrapper before the colon check.
    keys = set()
    key_pat = _re.compile(r"(\w*template_weights)\s*\**\s*[:=]")
    for cfg_path in glob.glob(os.path.join(configs_dir, "*.md")):
        with open(cfg_path, "r", encoding="utf-8") as f:
            txt = f.read()
        for m in key_pat.finditer(txt):
            keys.add(m.group(1))

    if not keys:
        return  # no such config keys — nothing to guard

    # Slurp all skill Python source (excluding test dir, which isn't loaded at runtime)
    code_blob = ""
    for py in glob.glob(os.path.join(skills_dir, "*.py")):
        with open(py, "r", encoding="utf-8") as f:
            code_blob += f.read() + "\n"

    unreferenced = [k for k in keys if k not in code_blob]
    assert not unreferenced, (
        f"Dead config keys (no code reads them): {unreferenced}. "
        f"Either wire them into the code or remove them from the config. "
        f"This guard catches the March 2026 regression pattern."
    )


# ── Synthesis Finalizer (Wisdom Engine · Layer 1) ────────────────────────
print("\n🧵 Synthesis Finalizer")

@test("synthesis_finalizer: importable with full public API")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    for name in (
        "finalize", "finalize_all", "check_invariant",
        "parse_synthesis", "resolve_wikilink", "classify_wikilink",
        "queue_surfacings", "get_ready_surfacings", "mark_surfacing_delivered",
        "SURFACING_STAGES", "SYNTHESIS_DIR", "THEMES_DIR",
    ):
        assert hasattr(sf, name), f"missing export: {name}"

@test("synthesis_finalizer: parse_synthesis recognises structured shape")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    # Use any real structured synthesis from the vault as a live fixture
    sample = sf.SYNTHESIS_DIR / (
        "You finish the task as someone the starter could not have been — "
        "looking good in public is incompatible with the becoming the work actually requires.md"
    )
    if not sample.exists():
        # Fall back: find any structured file
        candidates = [p for p in sf.SYNTHESIS_DIR.glob("*.md")
                      if "## The Claim Across Sources" in p.read_text(encoding="utf-8")]
        assert candidates, "No structured synthesis found in vault"
        sample = candidates[0]
    info = sf.parse_synthesis(sample)
    assert info["structured"], f"Expected structured, got {info}"
    assert info["title"], "Title must not be empty"
    assert len(info["cited_sources"]) >= 1, "Structured synthesis must cite sources"

@test("synthesis_finalizer: classify_wikilink tri-state")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    # 'file' case: a known writing page
    kind, _ = sf.classify_wikilink("writing/How to defeat ego")
    assert kind in ("file", "missing"), f"Expected file-or-missing, got {kind}"
    # 'missing' case: deliberately fake
    kind2, _ = sf.classify_wikilink("this-wikilink-does-not-exist-xyz-42")
    assert kind2 == "missing", f"Expected missing, got {kind2}"

@test("synthesis_finalizer: check_invariant returns list (no exception)")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    vs = sf.check_invariant()
    assert isinstance(vs, list), f"Expected list, got {type(vs)}"
    # Parse errors and source_read errors are ALWAYS fatal
    fatal = [v for v in vs if v.get("kind") in ("parse_error", "source_read_error")]
    assert not fatal, f"Fatal invariant violations: {fatal[:5]}"

@test("synthesis_finalizer: every synthesis writer references it (finalizer-wiring guardrail)")
def _():
    # Mirrors the dead-config-guardrail pattern (line ~5680). Any module that
    # writes a file under /Alicia/Wisdom/Synthesis/ MUST import and call
    # synthesis_finalizer.finalize(). If a new writer lands without this, this
    # test catches it.
    writers = [
        os.path.join(PROJECT_ROOT, "skills", "memory_skill.py"),
        os.path.join(PROJECT_ROOT, "skills", "vault_ingest.py"),
    ]
    missing = []
    for w in writers:
        if not os.path.exists(w):
            continue
        with open(w, "r", encoding="utf-8") as f:
            txt = f.read()
        if "synthesis_finalizer" not in txt:
            missing.append(os.path.relpath(w, PROJECT_ROOT))
    assert not missing, (
        f"Known synthesis writer(s) not calling synthesis_finalizer: {missing}. "
        f"Every synthesis write must close the circulatory loop."
    )

@test("synthesis_finalizer: baseline invariant (ratchet downward as #15 closes gaps)")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    vs = sf.check_invariant()
    by_kind = {}
    for v in vs:
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    one_way = by_kind.get("one_way_edge", 0)
    unresolvable = by_kind.get("unresolvable", 0)
    # Baselines ratcheted on <earlier development> after item #15 live finalize_all
    # closed the corpus's 1,067 one-way edges → 0. Ratchet DOWNWARD only.
    # See tests/test_synthesis_finalizer_invariant.py for the authoritative ratchet.
    ONE_WAY_CEIL = 0
    UNRESOLVABLE_CEIL = 220
    assert one_way <= ONE_WAY_CEIL, (
        f"Regression: {one_way} one-way edges > baseline {ONE_WAY_CEIL}. "
        f"A new synthesis skipped the finalizer."
    )
    assert unresolvable <= UNRESOLVABLE_CEIL, (
        f"Regression: {unresolvable} unresolvable > baseline {UNRESOLVABLE_CEIL}. "
        f"A new synthesis cites a ghost wikilink."
    )


# ═══════════════════════════════════════════════════════════════════════════
# CIRCULATION COMPOSER (Layer 2, Phase 11.0 item #17)
# ═══════════════════════════════════════════════════════════════════════════
print("\n🩸 Circulation Composer")

@test("circulation_composer: importable with full public API")
def _():
    import myalicia.skills.circulation_composer as cc
    for name in (
        "decide_for_slot", "record_reaction", "check_invariants",
        "CirculationDecision", "Archetype", "Channel",
        "CIRCULATION_LOG_FILE", "USE_CIRCULATION_COMPOSER",
        "_parse_active_contradictions", "_STAGE_ARCHETYPE", "_SLOT_STAGE_BIAS",
    ):
        assert hasattr(cc, name), f"circulation_composer missing: {name}"

@test("circulation_composer: all §8 archetypes and channels represented")
def _():
    from myalicia.skills.circulation_composer import Archetype, Channel
    arch_names = {a.value for a in Archetype}
    assert arch_names == {"Daimon", "Beatrice", "Ariadne", "Psyche", "Musubi", "Muse"}, (
        f"Archetype set drift: {arch_names}"
    )
    chan_names = {c.value for c in Channel}
    assert chan_names == {"text", "voice", "drawing", "no_send"}, (
        f"Channel set drift: {chan_names}"
    )

@test("circulation_composer: feature flag defaults to False")
def _():
    # When the flag isn't set in .env, composer must default OFF so existing
    # probability-cap behavior is untouched until explicitly enabled.
    import os, importlib
    saved = os.environ.pop("USE_CIRCULATION_COMPOSER", None)
    try:
        import myalicia.skills.circulation_composer as cc
        importlib.reload(cc)
        assert cc.USE_CIRCULATION_COMPOSER is False
    finally:
        if saved is not None:
            os.environ["USE_CIRCULATION_COMPOSER"] = saved

@test("circulation_composer: check_invariants returns list (no exception)")
def _():
    from myalicia.skills.circulation_composer import check_invariants
    vs = check_invariants()
    assert isinstance(vs, list)

@test("circulation_composer: alicia.py imports it and uses decide_for_slot (scheduler-wiring guardrail)")
def _():
    # Dead-config-guardrail analog for Layer 2. If a future edit removes the
    # composer gate from the morning/midday/evening scheduler handlers without
    # also pulling the import, the wiring has rotted and CI fails loudly.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.circulation_composer import" in alicia_text, (
        "alicia.py must import circulation_composer — composer is not wired in."
    )
    assert "decide_for_slot(\"morning\")" in alicia_text, (
        "alicia.py must call decide_for_slot(\"morning\") — morning gate missing."
    )
    assert "decide_for_slot(\"midday\")" in alicia_text, (
        "alicia.py must call decide_for_slot(\"midday\") — midday gate missing."
    )
    assert "decide_for_slot(\"evening\")" in alicia_text, (
        "alicia.py must call decide_for_slot(\"evening\") — evening gate missing."
    )
    assert "USE_CIRCULATION_COMPOSER" in alicia_text, (
        "alicia.py must reference USE_CIRCULATION_COMPOSER feature flag."
    )


# ═══════════════════════════════════════════════════════════════════════════
# CONTRADICTION DETECTOR (Layer 3, Phase 11.0 item #18)
# ═══════════════════════════════════════════════════════════════════════════
print("\n⚖️  Contradiction Detector")

@test("contradiction_detector: importable with full public API")
def _():
    import myalicia.skills.contradiction_detector as cd
    for name in (
        "collect_recent_signals", "load_active_contradictions",
        "detect_contradictions", "apply_drafts", "detect_lineage_unused",
        "mark_lineage_unused", "check_invariants", "run_daily_pass",
        "ContradictionDraft", "EvidenceBump",
        "USE_CONTRADICTION_DETECTOR", "CONTRADICTIONS_PATH",
        "LINEAGES_DIR", "UNUSED_LINEAGE_TAG",
        "EVIDENCE_THRESHOLD", "STALE_ACTIVE_DAYS", "LINEAGE_UNUSED_DAYS",
    ):
        assert hasattr(cd, name), f"contradiction_detector missing: {name}"

@test("contradiction_detector: feature flag defaults to False")
def _():
    # When the flag isn't set in .env, detector must default OFF so the
    # daily pass runs in dry-run mode until explicitly flipped.
    import os, importlib
    saved = os.environ.pop("USE_CONTRADICTION_DETECTOR", None)
    try:
        import myalicia.skills.contradiction_detector as cd
        importlib.reload(cd)
        assert cd.USE_CONTRADICTION_DETECTOR is False
    finally:
        if saved is not None:
            os.environ["USE_CONTRADICTION_DETECTOR"] = saved

@test("contradiction_detector: collect_recent_signals returns dict shape")
def _():
    from myalicia.skills.contradiction_detector import collect_recent_signals
    sig = collect_recent_signals(days=1)
    assert isinstance(sig, dict)
    for key in ("cutoff", "reflections", "episodes", "memory", "preferences"):
        assert key in sig, f"missing key {key}"
    assert isinstance(sig["reflections"], list)
    assert isinstance(sig["episodes"], list)
    assert isinstance(sig["memory"], list)

@test("contradiction_detector: check_invariants returns list (no exception)")
def _():
    from myalicia.skills.contradiction_detector import check_invariants
    vs = check_invariants()
    assert isinstance(vs, list)
    # All entries in the seeded ledger should be <60 days old when this ships.
    stale = [v for v in vs if v["kind"] == "stale_active_contradiction"]
    assert not stale, f"stale active contradictions found: {stale}"

@test("contradiction_detector: alicia.py imports it and schedules the daily pass (scheduler-wiring guardrail)")
def _():
    # Dead-config-guardrail analog for Layer 3. If a future edit removes the
    # detector from the scheduler without also pulling the import, CI fails
    # loudly. This is the March 2026 regression preventer for this layer.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.contradiction_detector import" in alicia_text, (
        "alicia.py must import contradiction_detector — detector is not wired in."
    )
    assert "USE_CONTRADICTION_DETECTOR" in alicia_text, (
        "alicia.py must reference USE_CONTRADICTION_DETECTOR flag."
    )
    assert "run_contradiction_detector_pass" in alicia_text, (
        "alicia.py must call run_contradiction_detector_pass() — pass not wired."
    )
    assert "\"20:45\"" in alicia_text, (
        "alicia.py must schedule the detector at 20:45 (before the 21:00 "
        "evening slot so fresh contradictions reach the composer)."
    )


# ═══════════════════════════════════════════════════════════════════════════
# PRACTICE RUNNER (Layer 4, Phase 11.0 item #19)
# ═══════════════════════════════════════════════════════════════════════════
print("\n🌱 Practice Runner")

@test("practice_runner: importable with full public API")
def _():
    import myalicia.skills.practice_runner as pr
    for name in (
        "Practice", "USE_PRACTICE_RUNNER", "PRACTICES_DIR", "LIVED_DIR",
        "MAX_ACTIVE_PRACTICES", "CHECK_IN_DAYS",
        "load_practices", "active_practices",
        "promote_synthesis_to_practice", "due_check_ins", "compose_check_in",
        "record_check_in", "record_log_entry", "close_practice",
        "check_invariants", "run_daily_pass",
    ):
        assert hasattr(pr, name), f"practice_runner missing: {name}"

@test("practice_runner: feature flag defaults to False")
def _():
    import os, importlib
    saved = os.environ.pop("USE_PRACTICE_RUNNER", None)
    try:
        import myalicia.skills.practice_runner as pr
        importlib.reload(pr)
        assert pr.USE_PRACTICE_RUNNER is False
    finally:
        if saved is not None:
            os.environ["USE_PRACTICE_RUNNER"] = saved

@test("practice_runner: MAX_ACTIVE_PRACTICES is 3 (proposal contract)")
def _():
    from myalicia.skills.practice_runner import MAX_ACTIVE_PRACTICES, CHECK_IN_DAYS
    assert MAX_ACTIVE_PRACTICES == 3, f"cap drift: {MAX_ACTIVE_PRACTICES}"
    assert CHECK_IN_DAYS == (3, 7, 14, 21, 30), f"cadence drift: {CHECK_IN_DAYS}"

@test("practice_runner: check_invariants returns list and detects Lived-note contract")
def _():
    from myalicia.skills.practice_runner import check_invariants
    vs = check_invariants()
    assert isinstance(vs, list)
    # No closed practice may be missing its Lived note — this is THE Layer 4 contract.
    missing = [v for v in vs if v["kind"] == "closed_practice_missing_lived_note"]
    assert not missing, f"closed practices without Lived notes: {missing}"

@test("practice_runner: first practice folder exists in the vault")
def _():
    # Layer 4 ships with ONE real practice, not a framework. If the seed
    # practice goes missing, something has gone wrong with vault state.
    from myalicia.skills.practice_runner import PRACTICES_DIR
    seed = PRACTICES_DIR / "public-facing-attempts" / "practice.md"
    if not seed.exists():
        # Soft-skip in sandbox environments where the vault isn't mounted
        # at the default path — the unit tests cover round-trip creation.
        import os
        if not os.path.isdir(str(PRACTICES_DIR.parent.parent)):
            return
        raise AssertionError(f"seed practice missing at {seed}")

@test("practice_runner: alicia.py imports it and schedules the daily check-in (scheduler-wiring guardrail)")
def _():
    # Dead-config-guardrail analog for Layer 4. If a future edit removes
    # the check-in scheduling from alicia.py without pulling the import,
    # CI fails loudly — the March 2026 regression preventer for this layer.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.practice_runner import" in alicia_text, (
        "alicia.py must import practice_runner — runner is not wired in."
    )
    assert "USE_PRACTICE_RUNNER" in alicia_text, (
        "alicia.py must reference USE_PRACTICE_RUNNER flag."
    )
    assert "send_practice_checkins" in alicia_text, (
        "alicia.py must define send_practice_checkins handler."
    )
    assert "\"09:00\"" in alicia_text, (
        "alicia.py must schedule the check-in dispatcher at 09:00."
    )
    assert "compose_practice_check_in" in alicia_text, (
        "alicia.py must call compose_practice_check_in for Telegram delivery."
    )


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE CAPTURE (Phase 11.1, item #28 — Telegram replies as Tier-3 writing)
# ═══════════════════════════════════════════════════════════════════════════
print("\n📝 Response Capture")


@test("response_capture: importable with full public API")
def _():
    import myalicia.skills.response_capture as rc
    for name in (
        "capture_response", "find_recent_proactive_context",
        "capture_if_responsive", "RESPONSES_DIR",
        "DEFAULT_RESPONSE_WINDOW_MINUTES",
    ):
        assert hasattr(rc, name), f"response_capture missing: {name}"


@test("response_capture: alicia.py imports it and calls capture_if_responsive (wiring guardrail)")
def _():
    # Dead-wiring guardrail. If a future edit removes the capture call
    # from background_intelligence without pulling the import, CI fails
    # loudly — the March 2026 regression preventer for this layer.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.response_capture import" in alicia_text, (
        "alicia.py must import response_capture — capture is not wired in."
    )
    assert "capture_response_if_responsive" in alicia_text, (
        "alicia.py must call capture_response_if_responsive in the message pipeline."
    )
    # Native reply detection — the user tapping Reply on Alicia must trigger
    # capture regardless of whether the composer fired recently.
    assert "reply_to_message" in alicia_text and "direct_prompt" in alicia_text, (
        "alicia.py must pass direct_prompt from update.message.reply_to_message "
        "into capture_response_if_responsive — without this, conversational "
        "replies don't get archived."
    )


@test("response_capture: /capture command is registered and routes through cmd_capture (wiring guardrail)")
def _():
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "async def cmd_capture(" in alicia_text, (
        "alicia.py must define cmd_capture handler"
    )
    assert "capture_unprompted_response" in alicia_text, (
        "cmd_capture must call capture_unprompted_response for inline-text path"
    )
    assert '("capture",        cmd_capture)' in alicia_text \
            or '"capture"' in alicia_text, (
        "alicia.py must register the /capture CommandHandler"
    )


@test("wisdom_dashboard: /wisdom command is wired and importable (Phase 11.4 wiring guardrail)")
def _():
    # Module imports cleanly
    import myalicia.skills.wisdom_dashboard as wd
    assert hasattr(wd, "render_wisdom_dashboard"), (
        "wisdom_dashboard must export render_wisdom_dashboard"
    )

    # alicia.py imports it AND defines cmd_wisdom AND registers /wisdom
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.wisdom_dashboard import render_wisdom_dashboard" in alicia_text, (
        "alicia.py must import render_wisdom_dashboard"
    )
    assert "async def cmd_wisdom(" in alicia_text, (
        "alicia.py must define cmd_wisdom handler"
    )
    assert '"wisdom"' in alicia_text and "cmd_wisdom" in alicia_text, (
        "alicia.py must register the /wisdom CommandHandler"
    )


@test("response_capture: read-back queries are exported (Phase 11.5)")
def _():
    """Step 1 of closing the inner reply loop: captures are queryable.
    Future builds will pipe past responses into surfacing-render context
    so resurfacing reads as 'continuing a conversation'."""
    import myalicia.skills.response_capture as rc
    for name in (
        "parse_capture_file",
        "get_responses_for_synthesis",
        "get_recent_captures",
        "most_responded_syntheses",
    ):
        assert hasattr(rc, name), f"response_capture must export {name}"


@test("practice_runner: /practice command is wired (Phase 11.11 wiring guardrail)")
def _():
    """Self-serve practice management from Telegram. Without this command,
    practices can only be scaffolded via Desktop — the user can't manage them
    from his phone."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "async def cmd_practice(" in alicia_text, (
        "alicia.py must define cmd_practice handler"
    )
    # Must handle all 4 subcommands
    for sub in ('"list"', '"log"', '"close"', '"scaffold"'):
        assert sub in alicia_text, (
            f"cmd_practice must handle {sub} subcommand"
        )
    # Imports for the underlying API
    for imp in (
        "list_active_practices",
        "practice_record_log_entry",
        "runner_close_practice",
        "promote_synthesis_to_practice",
    ):
        assert imp in alicia_text, (
            f"alicia.py must import {imp}"
        )
    # Registered as a command
    assert '("practice"' in alicia_text and "cmd_practice" in alicia_text, (
        "alicia.py must register the /practice CommandHandler"
    )


@test("response_capture: morning capture resurface fallback is wired (Phase 11.10 wiring guardrail)")
def _():
    """When the composer NO_SENDs the morning slot AND the user has a 2-14
    day-old capture that hasn't been resurfaced in the cooldown window, the
    morning sends a 'where has it landed?' fallback. Captures stop being
    one-time archives and become future morning prompts. Without this
    wiring, mornings stay silent whenever the surfacing queue is empty."""
    import myalicia.skills.response_capture as rc
    for name in (
        "pick_capture_for_morning_resurface",
        "mark_capture_resurfaced",
        "render_morning_capture_resurface",
    ):
        assert hasattr(rc, name), f"response_capture must export {name}"
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    for needle in (
        "pick_capture_for_morning_resurface",
        "mark_capture_resurfaced",
        "render_morning_capture_resurface",
    ):
        assert needle in alicia_text, (
            f"alicia.py must reference {needle} for the morning fallback"
        )
    # The fallback must be inside the morning-NO_SEND branch — assert there
    # is at least one call to pick_capture_for_morning_resurface AFTER the
    # morning gate's "NO_SEND" log line. (The first occurrence is the
    # import block at the top of the file.)
    no_send_idx = alicia_text.find('[circulation] morning greeting NO_SEND')
    fallback_idx = alicia_text.find(
        "pick_capture_for_morning_resurface", no_send_idx,
    )
    assert 0 < no_send_idx < fallback_idx, (
        "capture-resurface fallback must be inside the morning NO_SEND "
        "branch (no call site found after the NO_SEND log line)"
    )


@test("drawing_skill: bridge_text_to_drawing_caption is wired (Phase 13.2 wiring guardrail)")
def _():
    """Phase 13.2 — when a drawing amplifies a composer-driven text moment,
    the caption explicitly bridges the two so they read as one coherent
    moment instead of two parallel artifacts."""
    import myalicia.skills.drawing_skill as ds
    assert hasattr(ds, "bridge_text_to_drawing_caption"), (
        "drawing_skill must export bridge_text_to_drawing_caption"
    )
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "bridge_text_to_drawing_caption" in alicia_text, (
        "alicia.py must import bridge_text_to_drawing_caption"
    )
    # Must be called inside _maybe_amplify_with_drawing AFTER generate_drawing
    amp_idx = alicia_text.find("async def _maybe_amplify_with_drawing(")
    bridge_idx = alicia_text.find("bridge_text_to_drawing_caption(", amp_idx)
    assert 0 < amp_idx < bridge_idx, (
        "bridge_text_to_drawing_caption call must appear inside "
        "_maybe_amplify_with_drawing"
    )
    # Must replace result['caption'] when bridged
    assert 'result["caption"] = bridged' in alicia_text, (
        "amplifier must replace result['caption'] with the bridged version"
    )


@test("circulation_composer: multi-channel moment amplification is wired (Phase 13.1 wiring guardrail)")
def _():
    """Phase 13.1 — when the composer picks a high-conviction decision in a
    slot, fire a complementary drawing in the same archetype as visual
    amplification. Background-fired so text doesn't block. Without this
    wiring, drawings only fire from impulse/manual paths, never as
    composer-driven moments."""
    import myalicia.skills.circulation_composer as cc
    assert hasattr(cc, "should_amplify_with_drawing"), (
        "circulation_composer must export should_amplify_with_drawing"
    )
    assert hasattr(cc, "DRAWING_AMPLIFY_THRESHOLD"), (
        "DRAWING_AMPLIFY_THRESHOLD must be defined"
    )
    assert cc.DRAWING_AMPLIFY_THRESHOLD >= 1.5, (
        "threshold should be conservative (1.5+) so amplification is rare"
    )
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "_maybe_amplify_with_drawing" in alicia_text, (
        "alicia.py must define _maybe_amplify_with_drawing helper"
    )
    assert "composer_should_amplify_with_drawing" in alicia_text, (
        "alicia.py must import should_amplify_with_drawing"
    )
    # Helper must be invoked from each composer-gated slot. asyncio.create_task
    # is the canonical fire-and-forget pattern.
    n_calls = alicia_text.count(
        "asyncio.create_task(\n                        _maybe_amplify_with_drawing("
    )
    # Three slots: morning, midday, evening
    assert n_calls >= 3, (
        f"expected >=3 _maybe_amplify_with_drawing call sites in alicia.py "
        f"(morning + midday + evening), found {n_calls}"
    )
    # source_kind=drawing_composer is the canonical tag for amplifying drawings
    assert 'source_kind="drawing_composer"' in alicia_text, (
        "alicia.py must pass source_kind='drawing_composer' to _send_drawing "
        "when amplifying"
    )


@test("circulation_composer: drawings recorded into circulation_log via _send_drawing (Phase 13.0 wiring guardrail)")
def _():
    """Phase 13.0 — drawings are first-class circulation events. Without
    this wiring, a drawing fires but doesn't appear in /wisdom or count
    toward /effectiveness engagement-rate or get a proactive_decision_id
    that response_capture can link replies to."""
    import myalicia.skills.circulation_composer as cc
    assert hasattr(cc, "record_drawing_decision"), (
        "circulation_composer must export record_drawing_decision"
    )
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "record_circulation_drawing" in alicia_text, (
        "alicia.py must import record_drawing_decision (as record_circulation_drawing)"
    )
    # Must be called from inside _send_drawing (i.e. AFTER the def line).
    send_idx = alicia_text.find("async def _send_drawing(")
    record_idx = alicia_text.find("record_circulation_drawing(", send_idx)
    assert 0 < send_idx < record_idx, (
        "record_circulation_drawing call must appear inside _send_drawing"
    )
    # cmd_draw passes source_kind='drawing_manual' so manual /draw is
    # distinguishable from impulse drawings in /wisdom.
    assert 'source_kind="drawing_manual"' in alicia_text, (
        "cmd_draw must pass source_kind='drawing_manual' to _send_drawing"
    )


@test("user_model + memory_skill: auto-extraction is wired (Phase 12.1)")
def _():
    """Phase 12.1 — every kept memory extraction also auto-appends a learning
    to the the user-model with a keyword-classified dimension. Without this
    wiring, the learnings log only fills via /becoming learn (manual)."""
    import myalicia.skills.user_model as hm
    assert hasattr(hm, "classify_dimension"), (
        "user_model must export classify_dimension"
    )
    # Sanity-check classifier behavior at the smoke layer too
    assert hm.classify_dimension("workout this morning") == "body"
    assert hm.classify_dimension("Gamma on hemispheres") == "knowledge"
    assert hm.classify_dimension("blank statement nothing matches") == "identity"

    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    mem_text = (repo_root / "skills" / "memory_skill.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.user_model import" in mem_text, (
        "memory_skill must import from user_model for auto-extraction"
    )
    assert "_hm_classify_dimension" in mem_text, (
        "memory_skill must use classify_dimension on each kept extraction"
    )
    assert "_hm_append_learning" in mem_text, (
        "memory_skill must call append_learning on each kept extraction"
    )
    # The hook must be inside the score>=4 branch (not on every extraction)
    keep_idx = mem_text.find("if score >= 4:")
    hook_idx = mem_text.find("_hm_append_learning", keep_idx)
    assert 0 < keep_idx < hook_idx, (
        "auto-append must be inside the score>=4 (kept) branch"
    )


@test("user_model: Phase 12.0 foundation is wired (becoming command + baseline + learnings)")
def _():
    """Phase 12.0 establishes the the user-model: a baseline snapshot of who
    Alicia thought the user was at deploy time, plus an append-only learnings
    log, plus delta computation. /becoming Telegram command surfaces the arc.

    Phase 12.1+ will wire learnings into research scheduler, archetype EMA,
    and question generation. Without this foundation, none of those have
    a substrate to build on."""
    import myalicia.skills.user_model as hm
    for name in (
        "init_baseline",
        "get_active_baseline",
        "append_learning",
        "get_learnings",
        "DIMENSIONS",
        "compute_dimension_counts",
        "find_thin_dimensions",
        "find_dimensions_movement",
        "days_since_baseline",
        "render_becoming_dashboard",
    ):
        assert hasattr(hm, name), f"user_model must export {name}"
    # 10 canonical dimensions — small + stable
    assert len(hm.DIMENSIONS) == 10
    assert "identity" in hm.DIMENSIONS
    assert "practice" in hm.DIMENSIONS
    assert "shadow" in hm.DIMENSIONS

    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.user_model import" in alicia_text, (
        "alicia.py must import from user_model"
    )
    assert "async def cmd_becoming(" in alicia_text, (
        "alicia.py must define cmd_becoming handler"
    )
    assert '"becoming"' in alicia_text and "cmd_becoming" in alicia_text, (
        "alicia.py must register the /becoming CommandHandler"
    )
    # Subcommand handlers
    for sub in ('"init"', '"learn"'):
        assert sub in alicia_text, (
            f"cmd_becoming must handle the {sub} subcommand"
        )


@test("multi_channel: Phase 13.12 + 14.1 cross-channel coherence is wired into morning + midday + evening")
def _():
    """Phase 13.12 closes the bidirectional loop on multi-channel: when
    voice + drawing both fire in the same moment, the voice script
    augments with a tail that grounds the listener in the visual that's
    about to arrive. Phase 14.1 extends the same pattern from midday
    (the canonical seed) to morning + evening — coherent moments now
    fire at all three proactive slots."""
    from pathlib import Path
    import myalicia.skills.multi_channel as mc
    assert hasattr(mc, "compose_voice_with_drawing_tail"), (
        "multi_channel must export compose_voice_with_drawing_tail"
    )

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    # Helper must be CALLED in ALL three proactive sends (Phase 14.1)
    for slot_fn in ("send_morning_message", "send_midday_message",
                    "send_evening_message"):
        fn_idx = alicia_text.find(f"async def {slot_fn}(")
        assert fn_idx > 0, f"{slot_fn} not found"
        next_def = alicia_text.find("\n    async def ", fn_idx + 10)
        fn_body = alicia_text[fn_idx:next_def if next_def > 0 else fn_idx + 7000]
        assert "compose_voice_with_drawing_tail" in fn_body, (
            f"compose_voice_with_drawing_tail must be called from "
            f"{slot_fn} body (Phase 14.1)"
        )
        assert "decide_drawing_amplification" in fn_body, (
            f"{slot_fn} must check decide_drawing_amplification before "
            f"deciding to weave a voice tail"
        )


@test("loops_dashboard: Phase 14.0 /loops meta-dashboard is wired (four-loops circulatory view)")
def _():
    """Phase 14.0 is the meta-dashboard. Six surfaces showed individual
    slices (/wisdom, /effectiveness, /becoming, /season, /metasynthesis,
    /multichannel). /loops shows the four CLOSED LOOPS as one connected
    circulatory system. Without this, the loops are visible only as
    fragments — there's no single view that proves they're stitched."""
    from pathlib import Path
    import myalicia.skills.loops_dashboard as ld
    assert hasattr(ld, "render_loops_dashboard"), (
        "loops_dashboard must export render_loops_dashboard"
    )
    # Render must succeed end-to-end on a sparse system
    out = ld.render_loops_dashboard()
    assert isinstance(out, str) and len(out) > 100
    # All four loop sections must be present in the output
    for marker in ("1. Inner reply", "2. Meta-synthesis",
                   "3. Gap-driven outbound", "4. Thread-pull",
                   "Cross-loop signals"):
        assert marker in out, (
            f"render_loops_dashboard missing required section: {marker!r}\n"
            f"got: {out[:300]}"
        )

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.loops_dashboard import render_loops_dashboard" in alicia_text
    assert "async def cmd_loops(" in alicia_text
    assert '"loops"' in alicia_text and "cmd_loops" in alicia_text


@test("effectiveness_dashboard: Phase 13.15 meta-synthesis quality section is wired into /effectiveness")
def _():
    """Phase 13.15 adds an engagement-by-recursion-level breakdown so we
    can see if meta-syntheses (Phase 13.13's surfacing bonus targets) are
    actually landing deeper than plain syntheses. Without this wiring,
    the 13.13 bonus has no feedback loop — we'd be amplifying altitude
    blind to whether altitude is what's working."""
    import myalicia.skills.effectiveness_dashboard as ed
    assert hasattr(ed, "_render_meta_synthesis_quality_section"), (
        "effectiveness_dashboard must export _render_meta_synthesis_quality_section"
    )
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "skills" / "effectiveness_dashboard.py").read_text(encoding="utf-8")
    fn_idx = src.find("def render_effectiveness_dashboard(")
    assert fn_idx > 0
    fn_body = src[fn_idx:fn_idx + 3000]
    assert "_render_meta_synthesis_quality_section" in fn_body, (
        "_render_meta_synthesis_quality_section must be called from "
        "render_effectiveness_dashboard body"
    )


@test("emergent_themes: Phase 17.0 detection + ceremonial noticing are wired")
def _():
    """Phase 17.0 — Alicia notices what the user hasn't named yet. The 04:00
    nightly scan detects emergent themes; the midday rotation surfaces
    them as TEXT + VOICE + DRAWING (high score + Beatrice + lived_surfacing
    so the smart deciders fast-path both voice and drawing). Without
    this wiring, the detection runs but never reaches the user."""
    from pathlib import Path as _P
    import myalicia.skills.emergent_themes as et
    for name in (
        "detect_emergent_themes",
        "record_emergent_theme",
        "recent_emergent_themes",
        "pick_theme_to_surface",
        "compose_noticing_message",
        "record_theme_acknowledged",
        "build_noticing_proactive",
        "run_emergent_theme_scan",
        "MIN_RECURRENCE",
        "SURFACE_COOLDOWN_DAYS",
        "NOTICING_ARCHETYPE",
        "NOTICING_SCORE",
        "NOTICING_SOURCE_KIND",
    ):
        assert hasattr(et, name), f"emergent_themes must export {name}"
    # Ceremonial values must match the smart-decider fast-path criteria
    assert et.NOTICING_ARCHETYPE == "beatrice", (
        "noticing archetype must be Beatrice (witness)"
    )
    assert et.NOTICING_SCORE >= 2.0, (
        f"NOTICING_SCORE must be ≥2.0 to fast-path drawing decider; got "
        f"{et.NOTICING_SCORE}"
    )
    # Source kind must be in the smart-decider's eligible set
    from myalicia.skills.multi_channel import ELIGIBLE_SOURCE_KINDS
    assert et.NOTICING_SOURCE_KIND in ELIGIBLE_SOURCE_KINDS, (
        f"noticing source_kind {et.NOTICING_SOURCE_KIND!r} must be in the "
        f"smart-decider eligible set: {ELIGIBLE_SOURCE_KINDS}"
    )

    # Wired into proactive_messages.build_midday_message
    pm_text = (_P(__file__).resolve().parent.parent
               / "skills" / "proactive_messages.py").read_text(encoding="utf-8")
    midday_idx = pm_text.find("def build_midday_message(")
    assert midday_idx > 0
    next_def = pm_text.find("\ndef ", midday_idx + 10)
    midday_body = pm_text[midday_idx:next_def if next_def > 0 else len(pm_text)]
    assert "build_noticing_proactive" in midday_body, (
        "build_noticing_proactive must be called from build_midday_message"
    )

    # Wired into 04:00 schedule
    alicia_text = (_P(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert 'schedule.every().day.at("04:00")' in alicia_text, (
        "alicia.py must register the 04:00 emergent_theme scan"
    )
    assert "send_emergent_theme_scan" in alicia_text, (
        "alicia.py must wire send_emergent_theme_scan into scheduler"
    )


@test("emergent_themes: Phase 17.2 /noticings command is wired into Telegram")
def _():
    """Phase 17.2 — /noticings command surfaces every theme Alicia is
    tracking. This guard ensures the rendering helper exists, the
    command handler is defined, and the command is registered."""
    from pathlib import Path as _P
    import myalicia.skills.emergent_themes as et
    for name in ("get_themes_summary", "render_noticings_for_telegram"):
        assert hasattr(et, name), f"emergent_themes must export {name}"
    s = et.get_themes_summary()
    for k in ("total", "by_status", "themes", "next_to_surface"):
        assert k in s, f"get_themes_summary missing key {k!r}"
    out = et.render_noticings_for_telegram()
    assert isinstance(out, str) and len(out) > 0
    alicia_text = (_P(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert "async def cmd_noticings(" in alicia_text, (
        "alicia.py must define cmd_noticings handler"
    )
    assert "render_noticings_for_telegram" in alicia_text, (
        "cmd_noticings must call render_noticings_for_telegram"
    )
    assert '"noticings"' in alicia_text and "cmd_noticings" in alicia_text, (
        "alicia.py must register the /noticings command in the handlers list"
    )


@test("tool_router: Phase 17.5 `draw` tool is registered and wired end-to-end")
def _():
    """Phase 17.5 — the user asked 'Make me a drawing about that note', the
    model called Tool: draw, got 'Unknown tool', then told him 'I don't
    have drawing capabilities yet'. The bug was that /draw was a Telegram
    command but never a conversational tool. This guard ensures:
      1. `draw` is in TOOLS (model has a schema for it)
      2. `draw` is in CORE_TOOL_NAMES (loaded on every conversation,
         not gated behind specialist keywords)
      3. The description includes the explicit 'NEVER reply I can't draw'
         injection-defense language so future model passes don't deny
         the capability mid-conversation
      4. execute_tool returns action=send_drawing on success
      5. alicia.py handle_message has a `send_drawing` action branch"""
    from pathlib import Path as _P
    # Read source files directly — avoids importing tool_router which
    # initializes the Anthropic client at module load (and trips on SOCKS
    # proxy in some sandbox environments).
    repo_root = _P(__file__).resolve().parent.parent
    tr_text = (repo_root / "skills" / "tool_router.py").read_text(encoding="utf-8")
    # 1. `draw` tool is defined in TOOLS
    assert '"name": "draw"' in tr_text, (
        "skills/tool_router.py TOOLS list must include a `draw` entry — "
        "without it the model hallucinates the tool, gets 'Unknown tool', "
        f"and tells {USER_NAME} 'I don't have drawing capabilities'"
    )
    # 2. `draw` is in CORE_TOOL_NAMES
    import re as _re
    core_match = _re.search(
        r"CORE_TOOL_NAMES\s*=\s*\{([^}]*)\}", tr_text, flags=_re.DOTALL,
    )
    assert core_match, "CORE_TOOL_NAMES set not found in tool_router.py"
    assert '"draw"' in core_match.group(1), (
        "draw must be in CORE_TOOL_NAMES so it loads on every conversation, "
        "not gated behind specialist keyword triggers"
    )
    # 3. Description includes capability-denial defense
    desc_idx = tr_text.find('"name": "draw"')
    desc_block = tr_text[desc_idx:desc_idx + 2000].lower()
    assert "never" in desc_block and (
        "can't draw" in desc_block or "i don't have" in desc_block
    ), (
        "draw description must include the explicit 'NEVER reply I can't "
        "draw' guard so the model doesn't hallucinate a capability denial"
    )
    # 4. execute_tool dispatches `draw` and returns action=send_drawing
    assert 'tool_name == "draw"' in tr_text, (
        "execute_tool must have an `elif tool_name == 'draw'` branch"
    )
    assert '"action": "send_drawing"' in tr_text, (
        "draw executor must return action=send_drawing for alicia.py to "
        "dispatch the send"
    )
    # 5. alicia.py handle_message has the send_drawing action branch
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert 'result.get("action") == "send_drawing"' in alicia_text, (
        "alicia.py handle_message must dispatch action=send_drawing to "
        "_send_drawing"
    )
    assert "_send_drawing(" in alicia_text and "source_kind" in alicia_text, (
        "send_drawing branch must call _send_drawing with source_kind"
    )


@test("Phase 18.0: noticing pre-renders voice + drawing as one ceremonial moment")
def _():
    """Phase 18.0 — noticings are ceremonial multi-channel moments by
    design. Before this phase the smart deciders made independent calls
    on voice + drawing for noticings, and the drawing decider got NO
    archetype/score/source_kind context (because noticings don't go
    through the composer, so _circ was None). This phase:
      1. emergent_themes.build_noticing_proactive populates a sidecar
         context with voice_text + archetype + score + source_kind +
         weather + theme.
      2. emergent_themes.get_last_noticing_context returns it for the
         midday handler within a 60s freshness window.
      3. alicia.py midday handler reads the sidecar and:
         - Forces voice (bypasses smart decider)
         - Uses voice_text (banner-free) at the right tone (gentle on
           neutral days, tender on heavy days)
         - Schedules a drawing with synthetic decision metadata so the
           drawing decider fast-paths via the noticing's score=2.5 +
           lived_surfacing source_kind."""
    import myalicia.skills.emergent_themes as et
    for name in (
        "get_last_noticing_context", "_set_last_noticing_context",
        "_clear_last_noticing_context", "_LAST_NOTICING_CONTEXT",
        "_NOTICING_CONTEXT_FRESH_SEC",
    ):
        assert hasattr(et, name), f"emergent_themes must export {name}"

    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")

    # Midday handler must fetch the sidecar
    assert "from myalicia.skills.emergent_themes import get_last_noticing_context" in alicia_text, (
        "midday handler must import get_last_noticing_context (Phase 18.0)"
    )
    assert "noticing_ctx = get_last_noticing_context()" in alicia_text, (
        "midday handler must read sidecar into noticing_ctx"
    )
    # Voice fast-path
    # Phase 19.3 renamed `noticing_force_voice` → `ceremonial_force_voice`
    # so the same fast-path covers both noticings AND mood check-ins.
    # Either name satisfies the Phase 18.0 wiring (a noticing fast-path
    # exists that bypasses the smart decider).
    assert (
        "noticing_force_voice" in alicia_text
        or "ceremonial_force_voice" in alicia_text
    ), (
        "midday voice block must have a Phase 18.0 noticing fast-path "
        "that bypasses the smart decider (renamed to "
        "`ceremonial_force_voice` in Phase 19.3 to also cover mood "
        "check-ins; either name is fine)"
    )
    assert 'midday_voice_style = (' in alicia_text or 'midday_voice_style =' in alicia_text, (
        "midday voice block must override style for noticings (gentle/tender)"
    )
    # Drawing fast-path with synthetic decision
    assert "fake_decision = _NS(" in alicia_text, (
        "midday handler must build a synthetic SimpleNamespace decision "
        "for noticings so _maybe_amplify_with_drawing fast-paths"
    )
    # Sidecar populated by build_noticing_proactive
    et_text = (repo_root / "skills" / "emergent_themes.py").read_text(encoding="utf-8")
    assert "_set_last_noticing_context(" in et_text, (
        "build_noticing_proactive must call _set_last_noticing_context"
    )
    # voice_text in result dict (banner-free)
    assert '"voice_text": body' in et_text, (
        "build_noticing_proactive result must include voice_text "
        "(banner-free body for TTS)"
    )


@test("Phase 17.7: dashboard reactions feed back (tool + command paths)")
def _():
    """Phase 17.7 — every dashboard send (whether through /loops command
    or `show_dashboard` tool) registers a reply_index.jsonl entry so 👍 /
    👎 / 🤔 reactions on the dashboard message attribute back via
    `task_type='dashboard:<name>'`. Without this, dashboards landed and
    the user's reactions silently dropped — no archetype attribution, no
    per-dashboard engagement tally.

    This guard locks all three pieces:
      1. The `_send_dashboard` helper exists in alicia.py
      2. All seven dashboard cmd_* handlers route through it
      3. The tool-driven `show_dashboard` action in handle_message
         registers track_reply with `task_type` carrying the dashboard
         name."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")

    # 1. _send_dashboard helper exists
    assert "async def _send_dashboard(" in alicia_text, (
        "alicia.py must define `_send_dashboard` helper that wraps "
        "safe_reply_md + track_reply registration"
    )
    assert 'task_type=f"dashboard:{name}"' in alicia_text, (
        "_send_dashboard must register `task_type='dashboard:<name>'` "
        "so reactions can attribute per-dashboard"
    )

    # 2. All ten dashboard command handlers use the helper
    # (Phase 17.7 wired 7; Phase 17.7b added the 3 remaining
    # /metasynthesis, /archetypes, /drawstats)
    for cmd, marker in (
        ("cmd_wisdom", '_send_dashboard(update.message, text, name="wisdom")'),
        ("cmd_becoming", '_send_dashboard(msg, text, name="becoming")'),
        ("cmd_season", '_send_dashboard(update.message, text, name="season")'),
        ("cmd_multichannel", '_send_dashboard(update.message, text, name="multichannel")'),
        ("cmd_loops", '_send_dashboard(update.message, text, name="loops")'),
        ("cmd_noticings", '_send_dashboard(update.message, text, name="noticings")'),
        ("cmd_effectiveness", '_send_dashboard(update.message, text, name="effectiveness")'),
        # Phase 17.7b
        ("cmd_archetypes", 'name="archetypes"'),
        ("cmd_drawstats", 'name="drawstats"'),
        ("cmd_metasynthesis", 'name="metasynthesis"'),
    ):
        assert marker in alicia_text, (
            f"{cmd} must route through _send_dashboard for reaction "
            f"feedback (Phase 17.7/17.7b). Expected: `{marker}`"
        )

    # 3. Tool-driven path registers track_reply for show_dashboard
    assert 'tool_name == "show_dashboard"' in alicia_text and (
        'first_reply_msg_id is not None' in alicia_text
    ), "handle_message must have a Phase 17.7 block for show_dashboard"
    assert 'show_dashboard:{dashboard_name}' in alicia_text, (
        "show_dashboard track_reply must pack the dashboard name into "
        "task_type so analysis can group reactions per-dashboard "
        "('which view gets the most 👍?')"
    )


@test("tool_router: Phase 17.6 command/tool parity audit (3 new tools wired)")
def _():
    """Phase 17.6 — applies Phase 17.5's lesson systematically. Walk
    every Telegram command exposing a generative or read-only capability
    and add a matching conversational tool so paraphrases ('let's walk
    about X', 'save this thought', 'show me my becoming') don't trigger
    the same capability-denial bug class.

    Three unified tools cover the gap:
      - start_thinking_session: walk/drive/unpack
      - note: quick-save into Obsidian Inbox
      - show_dashboard: every read-only observability surface

    This guard ensures all three are registered, in CORE, have the
    capability-denial defense in their description, and the
    start_thinking_session action handler is wired into alicia.py."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    tr_text = (repo_root / "skills" / "tool_router.py").read_text(encoding="utf-8")
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    import re as _re

    # 1. All three tool definitions present
    for tool_name in ("start_thinking_session", "note", "show_dashboard"):
        assert f'"name": "{tool_name}"' in tr_text, (
            f"skills/tool_router.py TOOLS must include `{tool_name}`"
        )

    # 2. All three in CORE_TOOL_NAMES
    core_match = _re.search(
        r"CORE_TOOL_NAMES\s*=\s*\{([^}]*)\}", tr_text, flags=_re.DOTALL,
    )
    assert core_match, "CORE_TOOL_NAMES set not found"
    core_block = core_match.group(1)
    for tool_name in ("start_thinking_session", "note", "show_dashboard"):
        assert f'"{tool_name}"' in core_block, (
            f"`{tool_name}` must be in CORE_TOOL_NAMES so it loads on "
            f"every conversation, not gated behind specialist keywords"
        )

    # 3. execute_tool branches present
    for tool_name in ("start_thinking_session", "note", "show_dashboard"):
        assert f'tool_name == "{tool_name}"' in tr_text, (
            f"execute_tool must have an `elif tool_name == '{tool_name}'` branch"
        )

    # 4. Capability-denial defense in descriptions (Phase 17.5 standard)
    for tool_name in ("start_thinking_session", "note", "show_dashboard"):
        idx = tr_text.find(f'"name": "{tool_name}"')
        block = tr_text[idx:idx + 2500].lower()
        assert "never reply" in block, (
            f"`{tool_name}` description must include a 'NEVER reply ...' "
            f"capability-denial defense (Phase 17.5 standard)"
        )

    # 5. start_thinking_session action wired in alicia.py
    assert 'result.get("action") == "start_thinking_session"' in alicia_text, (
        "alicia.py handle_message must dispatch action=start_thinking_session"
    )
    # The handler must call all three starters by name (defense against
    # silently dropping a mode in a future refactor)
    for fn in ("start_walk(", "start_drive(", "start_unpack("):
        assert fn in alicia_text, (
            f"start_thinking_session handler must call `{fn}...)`"
        )

    # 6. show_dashboard goes through TOOLS_SKIP_REFORMAT (preserves markdown)
    assert '"show_dashboard"' in alicia_text, (
        "alicia.py must list show_dashboard in TOOLS_SKIP_REFORMAT — "
        "dashboard renders are already user-ready markdown and shouldn't "
        "be reformatted by Sonnet"
    )
    # 7. System prompt explicitly steers each new tool (Phase 17.5
    # standard — descriptions alone aren't enough for Opus; the
    # conversation-default block needs a per-tool trigger explanation
    # or Opus may keep responding in prose instead of calling the tool)
    for tool_name in ("start_thinking_session", "note", "show_dashboard"):
        marker = f"- {tool_name} → ALWAYS call this tool"
        assert marker in alicia_text, (
            f"system prompt must contain explicit `{marker}` block — "
            f"without it Opus may describe the action in prose instead "
            f"of calling the tool (Phase 17.6 standard, mirrors 17.5)"
        )


@test("voice_intelligence: Phase 17.4 voice attunement adapts to weather")
def _():
    """Phase 17.4 — text_to_voice automatically softens to 'tender' when
    the user's recent voice notes have skewed sad/ang. Emphatic styles like
    'excited' must NOT be softened (preserves deliberate creative intent).
    Without this guardrail the attunement could silently disappear if
    voice_skill stops calling adapt_style_to_weather."""
    import myalicia.skills.voice_intelligence as vi
    import myalicia.skills.voice_skill as vs
    assert hasattr(vi, "adapt_style_to_weather"), (
        "voice_intelligence must export adapt_style_to_weather"
    )
    # 'tender' style must be defined in the prompt table
    assert "tender" in vs.VOICE_STYLES, (
        "voice_skill.VOICE_STYLES must include 'tender' entry for Phase 17.4"
    )
    # text_to_voice must call the adapter (caller-agnostic attunement)
    from pathlib import Path as _P
    vs_text = (_P(__file__).resolve().parent.parent
               / "skills" / "voice_skill.py").read_text(encoding="utf-8")
    assert "adapt_style_to_weather" in vs_text, (
        "voice_skill.text_to_voice must call adapt_style_to_weather"
    )
    # Pass-through behavior when neutral / emphatic
    import myalicia.skills.emergent_themes as et
    original = et._recent_emotion_weather
    et._recent_emotion_weather = lambda: "neutral"
    try:
        assert vi.adapt_style_to_weather("warm") == "warm"
        assert vi.adapt_style_to_weather("excited") == "excited"
    finally:
        et._recent_emotion_weather = original
    # Tender-day: warm/measured/default → tender; excited preserved
    et._recent_emotion_weather = lambda: "tender"
    try:
        assert vi.adapt_style_to_weather("warm") == "tender"
        assert vi.adapt_style_to_weather("measured") == "tender"
        assert vi.adapt_style_to_weather("default") == "tender"
        assert vi.adapt_style_to_weather("excited") == "excited", (
            "emphatic styles must not be softened"
        )
        assert vi.adapt_style_to_weather("gentle") == "gentle", (
            "already-soft styles pass through unchanged"
        )
    finally:
        et._recent_emotion_weather = original


@test("emergent_themes: Phase 17.1 emotion-aware noticing softening is wired")
def _():
    """Phase 17.1 — when the user's recent voice notes have skewed
    sad/ang in the last 24h, the noticing composer uses a softer
    system prompt + the surfacing gate is held back probabilistically.
    Without this guardrail, we could quietly regress to ungated noticings
    on heavy days — exactly the wrong moment for them."""
    import myalicia.skills.emergent_themes as et
    for name in (
        "_recent_emotion_weather",
        "TENDER_HEAVY_FRACTION",
        "TENDER_RECENT_HOURS",
        "TENDER_PROBABILITY_DAMP",
        "_NOTICING_SYSTEM_TENDER",
    ):
        assert hasattr(et, name), f"emergent_themes must export {name}"
    # _recent_emotion_weather is fault-tolerant — no entries → 'neutral'
    assert et._recent_emotion_weather() in ("tender", "neutral"), (
        "_recent_emotion_weather must return 'tender' or 'neutral'"
    )
    # compose_noticing_message must accept the new weather kwarg
    import inspect
    sig = inspect.signature(et.compose_noticing_message)
    assert "weather" in sig.parameters, (
        "compose_noticing_message must accept a 'weather' kwarg"
    )


@test("emergent_themes: Phase 17.3 dashboard noticings card is wired")
def _():
    """Phase 17.3 — noticings surface on the web dashboard. This guard
    ensures compute_noticings_state exists, is included in
    compute_full_state, and the HTML markup is present."""
    from pathlib import Path as _P
    import myalicia.skills.web_dashboard as wd
    assert hasattr(wd, "compute_noticings_state"), (
        "web_dashboard must export compute_noticings_state"
    )
    state = wd.compute_full_state()
    assert "noticings" in state, (
        "compute_full_state must include 'noticings' key"
    )
    n = state["noticings"]
    for k in ("total", "by_status", "themes", "next_to_surface"):
        assert k in n, f"noticings state missing key {k!r}"
    # HTML markup + JS render hook
    wd_text = (_P(__file__).resolve().parent.parent
               / "skills" / "web_dashboard.py").read_text(encoding="utf-8")
    for marker in (
        'id="noticings-card"',
        'id="noticings-list"',
        'id="noticings-counts"',
        "function renderNoticings(",
        "renderNoticings(state)",
    ):
        assert marker in wd_text, (
            f"web_dashboard.py missing required noticings marker: {marker!r}"
        )


@test("Phase 17.9: dashboard puzzlement signal is wired into /effectiveness")
def _():
    """Phase 17.9 — extends 17.8's dashboard engagement section with a
    'needs work' callout flagging dashboards with disproportionate 🤔
    or net-negative reactions. Without this, only the top-engaged views
    are visible and the user can't see which ones aren't landing."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    ed_text = (
        repo_root / "skills" / "effectiveness_dashboard.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "Phase 17.9",
        "Needs work",
        "🤔",
        "net-negative",
    ):
        assert marker in ed_text, (
            f"effectiveness_dashboard.py missing Phase 17.9 marker: {marker!r}"
        )


@test("Phase 18.1: noticing voice cache is wired (read-through + write + prune)")
def _():
    """Phase 18.1 — voice clips for noticings cache by hash(theme +
    voice_text + style) so re-fires don't re-render. TTL = 24h, evicted
    on read or via prune helper."""
    import myalicia.skills.emergent_themes as et
    for name in (
        "get_cached_noticing_voice", "cache_noticing_voice",
        "prune_noticing_voice_cache", "_voice_cache_key",
        "NOTICING_VOICE_CACHE_DIR", "NOTICING_VOICE_CACHE_TTL_HOURS",
    ):
        assert hasattr(et, name), (
            f"emergent_themes must export {name} (Phase 18.1)"
        )
    # Cache key must vary by all three inputs
    k1 = et._voice_cache_key("t1", "text", "gentle")
    assert k1 == et._voice_cache_key("t1", "text", "gentle")
    assert k1 != et._voice_cache_key("t2", "text", "gentle")
    assert k1 != et._voice_cache_key("t1", "different", "gentle")
    assert k1 != et._voice_cache_key("t1", "text", "tender")
    # alicia.py midday handler must call get_cached_noticing_voice
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "get_cached_noticing_voice" in alicia_text and (
        "cache_noticing_voice" in alicia_text
    ), (
        "alicia.py midday handler must check + write the noticing "
        "voice cache (Phase 18.1)"
    )


@test("Phase 16.3: read-scoping extends to /noticings (with all override)")
def _():
    """Phase 16.3 — same pattern as 16.2's /becoming, applied to
    /noticings. emergent_themes.{get_themes_summary,
    render_noticings_for_telegram, _consolidated_themes} accept a
    conversation_id kwarg; cmd_noticings reads
    current_conversation_id() unless `/noticings all`."""
    import inspect
    import myalicia.skills.emergent_themes as et

    for fn_name in (
        "get_themes_summary", "render_noticings_for_telegram",
        "_consolidated_themes",
    ):
        fn = getattr(et, fn_name)
        sig = inspect.signature(fn)
        assert "conversation_id" in sig.parameters, (
            f"{fn_name} must accept conversation_id kwarg (Phase 16.3)"
        )

    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    # cmd_noticings reads current_conversation_id when not 'all'
    cmd_idx = alicia_text.find("async def cmd_noticings(")
    assert cmd_idx > 0
    next_def = alicia_text.find("\n@chat_guard", cmd_idx + 10)
    cmd_block = alicia_text[cmd_idx:next_def if next_def > 0 else cmd_idx + 4000]
    assert "current_conversation_id" in cmd_block, (
        "cmd_noticings must read current_conversation_id (Phase 16.3)"
    )
    assert 'sub == "all"' in cmd_block or 'sub != "all"' in cmd_block, (
        "cmd_noticings must support `/noticings all` to bypass scope"
    )


@test("Phase 24.1: portrait composer reads recent portrait_response captures")
def _():
    """Phase 24.1 — When Sonnet composes a new portrait, it gets the
    most-recent portrait_response captures as continuity context. The
    new portrait can echo / answer / build on what the user said back."""
    import myalicia.skills.weekly_self_portrait as wsp
    assert hasattr(wsp, "_gather_recent_portrait_responses"), (
        "weekly_self_portrait must export _gather_recent_portrait_responses"
    )
    # Empty case shouldn't crash
    out = wsp._gather_recent_portrait_responses()
    assert isinstance(out, list)
    # _compose_portrait_body uses it
    from pathlib import Path as _P
    wsp_text = (
        _P(__file__).resolve().parent.parent
        / "skills" / "weekly_self_portrait.py"
    ).read_text(encoding="utf-8")
    compose_idx = wsp_text.find("def _compose_portrait_body(")
    assert compose_idx > 0
    block = wsp_text[compose_idx:compose_idx + 5000]
    assert "_gather_recent_portrait_responses" in block, (
        "_compose_portrait_body must call _gather_recent_portrait_responses"
    )
    assert "continuity_block" in block or "Last week's portrait replies" in block, (
        "composer prompt must include continuity context"
    )


@test("Phase 24.2: portrait system prompt branches by mood trend")
def _():
    """Phase 24.2 — Heavy-week variant when mood.trend == 'declining'
    AND there are enough voice notes. Default for stable/improving."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "_PORTRAIT_SYSTEM", "_PORTRAIT_SYSTEM_HEAVY",
        "_select_portrait_system_prompt",
    ):
        assert hasattr(wsp, name), (
            f"weekly_self_portrait must export {name} (Phase 24.2)"
        )
    # Heavy variant fires on declining + enough notes
    heavy = wsp._select_portrait_system_prompt({
        "mood": {"trend": "declining", "total_classifications": 5},
    })
    assert heavy is wsp._PORTRAIT_SYSTEM_HEAVY
    # Default for improving / stable
    assert wsp._select_portrait_system_prompt(
        {"mood": {"trend": "improving", "total_classifications": 5}}
    ) is wsp._PORTRAIT_SYSTEM
    # Default for too-few-notes (don't flip register on a single bad day)
    assert wsp._select_portrait_system_prompt(
        {"mood": {"trend": "declining", "total_classifications": 2}}
    ) is wsp._PORTRAIT_SYSTEM
    # Heavy variant explicitly forbids silver-lining language
    heavy_text = wsp._PORTRAIT_SYSTEM_HEAVY.lower()
    assert "silver lining" in heavy_text or "this too shall pass" in heavy_text, (
        "_PORTRAIT_SYSTEM_HEAVY must explicitly forbid silver-lining "
        "bypass language"
    )
    assert "advice" in heavy_text and "you should" in heavy_text, (
        "_PORTRAIT_SYSTEM_HEAVY must forbid advice-giving"
    )


@test("Phase 24.3: portrait composer reads engagement feedback")
def _():
    """Phase 24.3 — Reads reaction_log.tsv for dashboard:retro entries.
    Returns a one-line framing instruction when puzzlement ratio ≥40%
    or net-negative reactions ≥2. None when engagement is healthy."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "_read_portrait_engagement", "_portrait_landing_warning",
    ):
        assert hasattr(wsp, name), (
            f"weekly_self_portrait must export {name} (Phase 24.3)"
        )
    # Healthy → None
    healthy = {
        "total": 10, "puzzled": 1, "puzzled_ratio": 0.1,
        "negative": 1, "positive": 5, "neg_minus_pos": -4,
    }
    assert wsp._portrait_landing_warning(healthy) is None
    # Too few → None
    assert wsp._portrait_landing_warning({"total": 2}) is None
    # Puzzled
    puzzled = {
        "total": 5, "puzzled": 3, "puzzled_ratio": 0.6,
        "negative": 0, "positive": 2, "neg_minus_pos": -2,
    }
    w = wsp._portrait_landing_warning(puzzled)
    assert w and "puzzled" in w.lower()
    # Net-negative
    neg = {
        "total": 5, "puzzled": 0, "puzzled_ratio": 0.0,
        "negative": 3, "positive": 1, "neg_minus_pos": 2,
    }
    w = wsp._portrait_landing_warning(neg)
    assert w and "negative" in w.lower()
    # Composer uses it
    from pathlib import Path as _P
    wsp_text = (
        _P(__file__).resolve().parent.parent
        / "skills" / "weekly_self_portrait.py"
    ).read_text(encoding="utf-8")
    compose_idx = wsp_text.find("def _compose_portrait_body(")
    block = wsp_text[compose_idx:compose_idx + 5000]
    assert "_portrait_landing_warning" in block, (
        "_compose_portrait_body must call _portrait_landing_warning"
    )
    assert "feedback_block" in block or "Composer feedback" in block, (
        "composer prompt must include the landing warning when present"
    )


@test("Phase 24.4: drift detection — themes acked >=3x without a synthesis")
def _():
    """Phase 24.4 — When the user keeps acknowledging a theme but the
    system never names it as a synthesis title, the noticing engine
    is spinning. Surface as 🌀 on /noticings + the drift array on
    get_themes_summary()."""
    import myalicia.skills.emergent_themes as et
    for name in (
        "_count_theme_acknowledgments", "detect_theme_drift",
    ):
        assert hasattr(et, name), (
            f"emergent_themes must export {name} (Phase 24.4)"
        )
    # get_themes_summary should include a 'drift' key (empty list ok)
    s = et.get_themes_summary()
    assert "drift" in s, (
        "get_themes_summary must include 'drift' (Phase 24.4)"
    )
    assert isinstance(s["drift"], list)
    # render_noticings_for_telegram should reference drift
    out = et.render_noticings_for_telegram()
    # Drift line only appears when drift exists; the test environment
    # has no drift, but the renderer must KNOW about it. Check source.
    from pathlib import Path as _P
    et_text = (
        _P(__file__).resolve().parent.parent
        / "skills" / "emergent_themes.py"
    ).read_text(encoding="utf-8")
    assert "🌀" in et_text, (
        "render_noticings_for_telegram must include the 🌀 drift "
        "marker (Phase 24.4)"
    )
    assert "Drifting themes" in et_text, (
        "render_noticings_for_telegram must surface the drift section"
    )


@test("Phase 24.5: cross-conversation portrait build + /retro <conv_id>")
def _():
    """Phase 24.5 — build_weekly_self_portrait accepts conversation_id;
    _gather_week_signals scopes captures + learnings + noticings to
    that conversation. cmd_retro detects /retro <known_conv_id> and
    builds per-conversation."""
    import inspect
    import myalicia.skills.weekly_self_portrait as wsp
    sig = inspect.signature(wsp.build_weekly_self_portrait)
    assert "conversation_id" in sig.parameters, (
        "build_weekly_self_portrait must accept conversation_id"
    )
    sig2 = inspect.signature(wsp._gather_week_signals)
    assert "conversation_id" in sig2.parameters, (
        "_gather_week_signals must accept conversation_id"
    )
    # cmd_retro detects /retro <conv_id>
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    cmd_idx = alicia_text.find("async def cmd_retro(")
    next_def = alicia_text.find("\n@chat_guard", cmd_idx + 10)
    block = alicia_text[
        cmd_idx:next_def if next_def > 0 else cmd_idx + 7000
    ]
    assert "retro_conversation" in block, (
        "cmd_retro must detect /retro <conv_id> (Phase 24.5)"
    )
    assert "build_weekly_self_portrait" in block and (
        "conversation_id=retro_conversation" in block
    ), (
        "cmd_retro must build per-conversation when conv_id is detected"
    )


@test("Phase 22.1: retro Q&A answers are cached by hash(question, week_key)")
def _():
    """Phase 22.1 — same question in the same week skips Sonnet.
    7d TTL (matches portrait build cooldown). Cache hits log + skip."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "_retro_qa_cache_key", "_current_week_key",
        "_read_retro_qa_cache", "_write_retro_qa_cache",
        "RETRO_QA_CACHE_DIR", "RETRO_QA_CACHE_TTL_HOURS",
    ):
        assert hasattr(wsp, name), f"weekly_self_portrait must export {name}"
    # Cache key normalizes whitespace + case
    k1 = wsp._retro_qa_cache_key("What was hardest?", "2026-W17")
    k2 = wsp._retro_qa_cache_key("what was hardest?", "2026-W17")
    assert k1 == k2, "cache key must normalize case + whitespace"
    # Differs by week
    assert k1 != wsp._retro_qa_cache_key(
        "What was hardest?", "2026-W18"
    ), "cache key must differ by week"
    # answer_retro_question accepts use_cache kwarg
    import inspect
    sig = inspect.signature(wsp.answer_retro_question)
    assert "use_cache" in sig.parameters, (
        "answer_retro_question must accept use_cache kwarg"
    )


@test("Phase 23.0: /retro span (this month / past N days / since YYYY-MM-DD)")
def _():
    """Phase 23.0 — /retro accepts span specifiers. parse_retro_span_arg
    + _gather_span_signals + render_retro_span are exported. cmd_retro
    detects span before falling through to date / Q&A paths."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "parse_retro_span_arg", "_gather_span_signals",
        "_compose_span_portrait_body", "render_retro_span",
    ):
        assert hasattr(wsp, name), f"weekly_self_portrait must export {name}"
    # Recognized formats
    assert wsp.parse_retro_span_arg("this month") is not None
    assert wsp.parse_retro_span_arg("last month") == 30
    assert wsp.parse_retro_span_arg("past 7 days") == 7
    assert wsp.parse_retro_span_arg("last 3 weeks") == 21
    assert wsp.parse_retro_span_arg("since 2026-04-01") is not None
    # Not-spans return None
    assert wsp.parse_retro_span_arg("all") is None
    assert wsp.parse_retro_span_arg("2026-04-19") is None
    assert wsp.parse_retro_span_arg("") is None
    # cmd_retro routes spans
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    cmd_idx = alicia_text.find("async def cmd_retro(")
    block = alicia_text[cmd_idx:cmd_idx + 6000]
    assert "parse_retro_span_arg" in block, (
        "cmd_retro must call parse_retro_span_arg before date / Q&A"
    )
    assert "render_retro_span" in block, (
        "cmd_retro must call render_retro_span when span_days is set"
    )


@test("Phase 17.11: ask_retro tool registered + skip-reformat + triggers")
def _():
    """Phase 17.11 — ask_retro is a specialist tool gated by week/month
    phrasing. Wraps answer_retro_question; goes through TOOLS_SKIP_REFORMAT
    so Beatrice prose isn't re-voiced generically."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    tr_text = (
        repo_root / "skills" / "tool_router.py"
    ).read_text(encoding="utf-8")
    assert '"name": "ask_retro"' in tr_text, (
        "tool_router TOOLS must include ask_retro"
    )
    assert 'tool_name == "ask_retro"' in tr_text, (
        "execute_tool must dispatch ask_retro"
    )
    # Specialist trigger present
    assert '"ask_retro":' in tr_text, (
        "ask_retro must be in _SPECIALIST_TRIGGERS"
    )
    # Skip-reformat in alicia.py
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert '"ask_retro"' in alicia_text and (
        "TOOLS_SKIP_REFORMAT" in alicia_text
    ), (
        "alicia.py TOOLS_SKIP_REFORMAT must include ask_retro"
    )


@test("Phase 24.0: portrait reply registry + capture tagging is wired")
def _():
    """Phase 24.0 — portraits register their message_id; replies via
    native Telegram reply land as Tier-3 with kind=portrait_response
    + portrait_ts/portrait_path frontmatter."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "track_portrait_message_id", "lookup_portrait_message",
        "_PORTRAIT_MSG_IDS", "_clear_portrait_message_ids",
    ):
        assert hasattr(wsp, name), f"weekly_self_portrait must export {name}"
    # Track + lookup roundtrip
    wsp._clear_portrait_message_ids()
    wsp.track_portrait_message_id(
        12345, portrait_ts="2026-04-26T19:30:00", vault_path="x.md",
    )
    meta = wsp.lookup_portrait_message(12345)
    assert meta is not None
    assert meta.get("vault_path") == "x.md"
    assert wsp.lookup_portrait_message(99999) is None
    wsp._clear_portrait_message_ids()
    # response_capture hooks portrait_meta
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    rc_text = (
        repo_root / "skills" / "response_capture.py"
    ).read_text(encoding="utf-8")
    assert "lookup_portrait_message" in rc_text, (
        "response_capture must look up portrait metadata"
    )
    assert '"portrait_response"' in rc_text, (
        "response_capture must use portrait_response source_kind"
    )
    assert "_append_portrait_metadata" in rc_text, (
        "response_capture must define _append_portrait_metadata"
    )
    # Sunday send tracks the portrait msg_id
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "track_portrait_message_id" in alicia_text, (
        "alicia.py Sunday send must call track_portrait_message_id"
    )


@test("Phase 19.3: mood check-ins pre-render voice via sidecar")
def _():
    """Phase 19.3 — Mirror of Phase 18.0's noticing sidecar for mood
    check-ins. build_mood_checkin_proactive + build_mood_lift_proactive
    populate _LAST_MOOD_CHECKIN_CONTEXT; midday handler reads it via
    get_last_mood_checkin_context and pre-renders Beatrice voice in
    the right style (tender for dip, gentle for lift)."""
    import myalicia.skills.emotion_model as em
    for name in (
        "get_last_mood_checkin_context", "_set_last_mood_checkin_context",
        "_clear_last_mood_checkin_context", "_LAST_MOOD_CHECKIN_CONTEXT",
        "_MOOD_CHECKIN_CONTEXT_FRESH_SEC",
    ):
        assert hasattr(em, name), (
            f"emotion_model must export {name} (Phase 19.3)"
        )
    # Sidecar populated on success — exercise the setter
    em._clear_last_mood_checkin_context()
    em._set_last_mood_checkin_context({
        "kind": "mood_checkin", "voice_style": "tender", "voice_text": "x",
    })
    ctx = em.get_last_mood_checkin_context()
    assert ctx is not None and ctx["voice_style"] == "tender"
    em._clear_last_mood_checkin_context()
    # midday handler reads it
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "get_last_mood_checkin_context" in alicia_text, (
        "midday handler must read get_last_mood_checkin_context"
    )
    assert "mood_ctx" in alicia_text and "ceremonial_force_voice" in alicia_text, (
        "midday voice fast-path must extend to mood_ctx (Phase 19.3)"
    )


@test("Phase 16.6: most-responded section accepts conversation_id")
def _():
    """Phase 16.6 — extends 16.4's read-scoping to /wisdom's
    _render_most_responded_section + the underlying
    response_capture.most_responded_syntheses. Wisdom's scope kwarg
    now flows into both captures + most-responded."""
    import inspect
    import myalicia.skills.response_capture as rc
    import myalicia.skills.wisdom_dashboard as wd

    sig = inspect.signature(rc.most_responded_syntheses)
    assert "conversation_id" in sig.parameters, (
        "most_responded_syntheses must accept conversation_id"
    )
    sig2 = inspect.signature(wd._render_most_responded_section)
    assert "conversation_id" in sig2.parameters, (
        "_render_most_responded_section must accept conversation_id"
    )
    # render_wisdom_dashboard must thread the scope into most-responded
    from pathlib import Path as _P
    wd_text = (
        _P(__file__).resolve().parent.parent
        / "skills" / "wisdom_dashboard.py"
    ).read_text(encoding="utf-8")
    assert (
        "_render_most_responded_section(conversation_id=conversation_id)"
        in wd_text
    ), (
        "render_wisdom_dashboard must pass conversation_id to "
        "_render_most_responded_section"
    )


@test("Phase 21.1: Sunday self-portrait sends drawing as third channel")
def _():
    """Phase 21.1 — portrait now lands as text + voice + drawing.
    send_weekly_self_portrait schedules _maybe_amplify_with_drawing
    with a synthetic Beatrice + score=2.5 + lived_surfacing decision."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    # Find the send_weekly_self_portrait function block
    idx = alicia_text.find("async def send_weekly_self_portrait")
    assert idx > 0
    next_def = alicia_text.find("\n    async def ", idx + 10)
    block = alicia_text[idx:next_def if next_def > 0 else idx + 6000]
    assert "_NS_portrait" in block or "SimpleNamespace" in block, (
        "send_weekly_self_portrait must build a synthetic decision "
        "for drawing amplification"
    )
    assert '_maybe_amplify_with_drawing' in block, (
        "send_weekly_self_portrait must schedule "
        "_maybe_amplify_with_drawing"
    )
    assert 'archetype="beatrice"' in block, (
        "portrait drawing must use Beatrice archetype"
    )
    # Score 2.5 + lived_surfacing matches Phase 18.0's noticing wiring
    assert (
        "score=2.5" in block and 'source_kind="lived_surfacing"' in block
    ), (
        "portrait drawing must use the same ceremonial fast-path "
        "values (score=2.5, source_kind=lived_surfacing) as Phase 18.0"
    )


@test("Phase 22.0: /retro accepts free-text questions for Sonnet Q&A")
def _():
    """Phase 22.0 — /retro <free-text> answers the user's specific
    question from this week's signals via Sonnet. Witness-voice
    answer, not archived as a Tier-3 note."""
    import myalicia.skills.weekly_self_portrait as wsp
    assert hasattr(wsp, "answer_retro_question"), (
        "weekly_self_portrait must export answer_retro_question"
    )
    assert hasattr(wsp, "_RETRO_QA_SYSTEM"), (
        "weekly_self_portrait must export _RETRO_QA_SYSTEM"
    )
    qa_sys = wsp._RETRO_QA_SYSTEM.lower()
    # System prompt must explicitly forbid recommendations (witness, not advise)
    assert "no recommendations" in qa_sys or 'no \"you should\"' in qa_sys or (
        "no 'you should'" in qa_sys
    ), (
        "_RETRO_QA_SYSTEM must explicitly forbid 'you should' / "
        "recommendations (witness-voice, not advise)"
    )
    # cmd_retro detects free-text path
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    cmd_idx = alicia_text.find("async def cmd_retro(")
    assert cmd_idx > 0
    next_def = alicia_text.find("\n@chat_guard", cmd_idx + 10)
    block = alicia_text[
        cmd_idx:next_def if next_def > 0 else cmd_idx + 6000
    ]
    assert "free_text_question" in block, (
        "cmd_retro must support free-text question path"
    )
    assert "answer_retro_question" in block, (
        "cmd_retro must call answer_retro_question for free-text"
    )


@test("Phase 19.2: upward mood acknowledgment is wired into midday")
def _():
    """Phase 19.2 — mirror of 19.1 for sharp upward trends. Locks the
    helper exports + midday wiring + the system prompt's witnessing
    constraint (no praise / no transactional language)."""
    import myalicia.skills.emotion_model as em
    for name in (
        "build_mood_lift_proactive", "_compose_mood_lift_message",
        "MOOD_LIFT_TREND_THRESHOLD", "_compute_mood_delta",
    ):
        assert hasattr(em, name), f"emotion_model must export {name}"
    assert em.MOOD_LIFT_TREND_THRESHOLD > 0, (
        "MOOD_LIFT_TREND_THRESHOLD must be positive — fires when "
        "the week trends UP"
    )
    # Wired into midday rotation
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    pm_text = (
        repo_root / "skills" / "proactive_messages.py"
    ).read_text(encoding="utf-8")
    assert "build_mood_lift_proactive" in pm_text, (
        "proactive_messages must call build_mood_lift_proactive"
    )
    # System prompt must explicitly forbid praise
    em_text = (
        repo_root / "skills" / "emotion_model.py"
    ).read_text(encoding="utf-8")
    lift_idx = em_text.find("_MOOD_LIFT_SYSTEM")
    assert lift_idx > 0
    block = em_text[lift_idx:lift_idx + 1500].lower()
    assert (
        "great job" in block or "keep it up" in block or "praise" in block
    ), (
        "_MOOD_LIFT_SYSTEM must explicitly forbid praise/cheerleading "
        "language so the lift acknowledgment stays witnessing not "
        "transactional"
    )


@test("Phase 16.5: prompt_effectiveness.tsv carries conversation_id")
def _():
    """Phase 16.5 — TSV writer adds conversation_id (7th column);
    by-source reader honors it. Backwards-compat: rows without the
    column treated as 'default'."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    pm_text = (
        repo_root / "skills" / "proactive_messages.py"
    ).read_text(encoding="utf-8")
    # Writer writes 7-column rows + 7-column header. The header literal
    # is split across two adjacent string literals in the source —
    # check for both sides of the split rather than a contiguous match.
    assert "insight_score\\tdepth\\t" in pm_text and (
        "conversation_id\\n" in pm_text
    ), (
        "TSV header must include conversation_id as 7th column "
        "(Phase 16.5)"
    )
    assert "current_conversation_id" in pm_text and (
        "{conv_id}" in pm_text
    ), (
        "record_prompted_response must tag rows with current "
        "conversation_id"
    )
    # Reader honors the 7th column
    ed_text = (
        repo_root / "skills" / "effectiveness_dashboard.py"
    ).read_text(encoding="utf-8")
    assert "len(parts) >= 7" in ed_text or "parts[6]" in ed_text, (
        "_render_engagement_by_source_section must read the 7th "
        "column for conversation_id"
    )
    import inspect
    import myalicia.skills.effectiveness_dashboard as ed
    sig = inspect.signature(ed._render_engagement_by_source_section)
    assert "conversation_id" in sig.parameters, (
        "by-source section must accept conversation_id kwarg"
    )


@test("Phase 20.1: /retro week-of + all + scope are wired")
def _():
    """Phase 20.1 — three new behaviors on /retro:
      - `/retro <YYYY-MM-DD>` renders the portrait for that week
      - `/retro all` shows the index of every archived portrait
      - default scopes by active conversation; `all` bypasses
    Locks the helper exports + cmd dispatch."""
    import inspect
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "list_self_portraits", "get_self_portrait_for_date",
    ):
        assert hasattr(wsp, name), f"weekly_self_portrait must export {name}"
    sig = inspect.signature(wsp.render_retro_for_telegram)
    for kw in ("target_date", "show_all", "conversation_id"):
        assert kw in sig.parameters, (
            f"render_retro_for_telegram must accept `{kw}` kwarg"
        )
    # alicia.py wiring
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    cmd_idx = alicia_text.find("async def cmd_retro(")
    assert cmd_idx > 0
    next_def = alicia_text.find("\n@chat_guard", cmd_idx + 10)
    cmd_block = alicia_text[
        cmd_idx:next_def if next_def > 0 else cmd_idx + 5000
    ]
    assert 'first == "all"' in cmd_block or 'show_all = True' in cmd_block, (
        "cmd_retro must support `/retro all`"
    )
    assert 'strptime(first, "%Y-%m-%d")' in cmd_block, (
        "cmd_retro must parse first arg as YYYY-MM-DD for historical view"
    )
    assert "current_conversation_id" in cmd_block, (
        "cmd_retro must scope by current_conversation_id"
    )


@test("Phase 21.0: Sunday self-portrait is voice-rendered with cache")
def _():
    """Phase 21.0 — portrait arrives as text + voice. Cache by hash
    so /retro replays within the week skip the Gemini call."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "get_cached_portrait_voice", "cache_portrait_voice",
        "pick_portrait_voice_style", "_portrait_voice_cache_key",
        "PORTRAIT_VOICE_CACHE_DIR", "PORTRAIT_VOICE_CACHE_TTL_HOURS",
    ):
        assert hasattr(wsp, name), (
            f"weekly_self_portrait must export {name} (Phase 21.0)"
        )
    # Style picker honors the mood
    assert wsp.pick_portrait_voice_style({"mood": {"trend": "declining"}}) == "tender"
    assert wsp.pick_portrait_voice_style({"mood": {"trend": "improving"}}) == "gentle"
    assert wsp.pick_portrait_voice_style({}) == "gentle"
    assert wsp.pick_portrait_voice_style(None) == "gentle"
    # Cache key sensitive to body and style
    k1 = wsp._portrait_voice_cache_key("body A", "gentle")
    assert k1 == wsp._portrait_voice_cache_key("body A", "gentle")
    assert k1 != wsp._portrait_voice_cache_key("body B", "gentle")
    assert k1 != wsp._portrait_voice_cache_key("body A", "tender")
    # Sunday scheduler + cmd_retro wire voice
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    assert "get_cached_portrait_voice" in alicia_text, (
        "alicia.py must use get_cached_portrait_voice "
        "(Sunday send + /retro)"
    )
    assert "cache_portrait_voice" in alicia_text, (
        "alicia.py must populate the portrait voice cache on miss"
    )
    assert "send_voice" in alicia_text and "pick_portrait_voice_style" in alicia_text, (
        "send_weekly_self_portrait must send voice in derived style"
    )


@test("Phase 19.1: mood-aware proactive check-in is wired into midday")
def _():
    """Phase 19.1 — when the week trends sharply heavy, the midday
    rotation can fire a soft Beatrice check-in. Guards: emotion_model
    exports build_mood_checkin_proactive; midday rotation calls it;
    cooldown + threshold constants are exported."""
    import myalicia.skills.emotion_model as em
    for name in (
        "build_mood_checkin_proactive",
        "MOOD_CHECKIN_COOLDOWN_DAYS", "MOOD_CHECKIN_TREND_THRESHOLD",
        "MOOD_CHECKIN_MIN_NOTES",
    ):
        assert hasattr(em, name), (
            f"emotion_model must export {name} (Phase 19.1)"
        )
    # Threshold should be negative (declining direction)
    assert em.MOOD_CHECKIN_TREND_THRESHOLD < 0, (
        "MOOD_CHECKIN_TREND_THRESHOLD must be negative — fires only "
        "when the week trends DOWN"
    )
    # midday wiring
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    pm_text = (
        repo_root / "skills" / "proactive_messages.py"
    ).read_text(encoding="utf-8")
    assert "build_mood_checkin_proactive" in pm_text, (
        "proactive_messages must call build_mood_checkin_proactive in "
        "the midday rotation (Phase 19.1)"
    )


@test("Phase 16.4: read-scoping extends to /wisdom + /effectiveness")
def _():
    """Phase 16.4 — same pattern as 16.2/16.3 applied to /wisdom and
    /effectiveness. /wisdom captures section actually filters by
    conversation_id; /effectiveness shows a scope banner (data still
    whole-vault until prompt_effectiveness.tsv is tagged in 16.5)."""
    import inspect
    import myalicia.skills.wisdom_dashboard as wd
    import myalicia.skills.response_capture as rc
    import myalicia.skills.effectiveness_dashboard as ed

    # render_wisdom_dashboard accepts conversation_id
    sig = inspect.signature(wd.render_wisdom_dashboard)
    assert "conversation_id" in sig.parameters, (
        "render_wisdom_dashboard must accept conversation_id (Phase 16.4)"
    )
    # _render_captures_section accepts conversation_id
    sig2 = inspect.signature(wd._render_captures_section)
    assert "conversation_id" in sig2.parameters, (
        "_render_captures_section must accept conversation_id (Phase 16.4)"
    )
    # get_recent_captures accepts conversation_id
    sig3 = inspect.signature(rc.get_recent_captures)
    assert "conversation_id" in sig3.parameters, (
        "get_recent_captures must accept conversation_id (Phase 16.4)"
    )
    # render_effectiveness_dashboard accepts conversation_id
    sig4 = inspect.signature(ed.render_effectiveness_dashboard)
    assert "conversation_id" in sig4.parameters, (
        "render_effectiveness_dashboard must accept conversation_id"
    )

    # cmd_wisdom + cmd_effectiveness handlers thread current_conversation_id
    from pathlib import Path as _P
    alicia_text = (
        _P(__file__).resolve().parent.parent / "alicia.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "render_wisdom_dashboard(conversation_id=scope_to)",
        "render_effectiveness_dashboard(conversation_id=scope_to)",
    ):
        assert marker in alicia_text, (
            f"alicia.py missing Phase 16.4 wiring: {marker!r}"
        )


@test("Phase 20.0: weekly self-portrait is wired (composer + /retro + scheduler)")
def _():
    """Phase 20.0 — Sunday self-portrait. Locks: module exports;
    /retro Telegram command registered; Sunday 19:30 scheduled task
    registered; vault destination directory is correct."""
    import myalicia.skills.weekly_self_portrait as wsp
    for name in (
        "build_weekly_self_portrait", "get_latest_self_portrait",
        "render_retro_for_telegram", "_gather_week_signals",
        "_compose_portrait_body", "PORTRAIT_LOG_PATH",
        "PORTRAIT_VAULT_DIR", "PORTRAIT_COOLDOWN_DAYS",
    ):
        assert hasattr(wsp, name), (
            f"weekly_self_portrait must export {name} (Phase 20.0)"
        )
    # Module is importable (already done above)
    # _gather_week_signals returns the canonical shape (no exceptions
    # even with empty disk)
    sig = wsp._gather_week_signals()
    for key in (
        "captured_at", "mood", "dashboard_engagement", "noticings",
        "becoming", "captures",
    ):
        assert key in sig, f"_gather_week_signals missing key {key!r}"

    # alicia.py wiring: cmd_retro, /retro registered, Sunday 19:30 task
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "async def cmd_retro(" in alicia_text, (
        "alicia.py must define cmd_retro (Phase 20.0)"
    )
    assert '"retro"' in alicia_text and "cmd_retro" in alicia_text, (
        "alicia.py must register the /retro command"
    )
    assert 'schedule.every().sunday.at("19:30")' in alicia_text, (
        "Sunday 19:30 self-portrait scheduler must be registered"
    )
    assert "send_weekly_self_portrait" in alicia_text, (
        "send_weekly_self_portrait async wrapper must be defined"
    )


@test("Phase 17.10: /financial conversational tool is wired (low priority)")
def _():
    """Phase 17.10 — `financial` tool wraps the same scan /financial
    command uses. Specialist (not core) — gated by explicit money/bill
    keywords."""
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    tr_text = (
        repo_root / "skills" / "tool_router.py"
    ).read_text(encoding="utf-8")
    assert '"name": "financial"' in tr_text, (
        "tool_router TOOLS must include `financial` (Phase 17.10)"
    )
    assert 'tool_name == "financial"' in tr_text, (
        "execute_tool must have a `financial` branch"
    )
    # Specialist triggers
    assert '"financial":' in tr_text and '"money"' in tr_text, (
        "_SPECIALIST_TRIGGERS must include financial keywords"
    )


@test("Phase 19.0: mood-of-the-week is wired (emotion_model + dashboard + /effectiveness)")
def _():
    """Phase 19.0 — the user's emotional weather over the last 7 days
    surfaces in two places: web dashboard header pill + /effectiveness
    section. Reuses emotion_log.jsonl (same source as Phase 17.1's
    24h tender check) at a longer window."""
    import myalicia.skills.emotion_model as em
    assert hasattr(em, "get_mood_of_the_week"), (
        "emotion_model must export get_mood_of_the_week (Phase 19.0)"
    )
    # Even with empty log, returns a structured dict (no exception)
    mood = em.get_mood_of_the_week(days=7)
    for key in (
        "total_classifications", "dominant_label", "dominant_share",
        "distribution", "trend", "trend_explanation", "summary_line",
        "days",
    ):
        assert key in mood, f"mood dict missing key {key!r}"

    # Dashboard wiring
    import myalicia.skills.web_dashboard as wd
    assert hasattr(wd, "compute_mood_state"), (
        "web_dashboard must expose compute_mood_state"
    )
    state = wd.compute_full_state()
    assert "mood" in state, "compute_full_state must include mood"

    # HTML pill + JS render
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    wd_text = (repo_root / "skills" / "web_dashboard.py").read_text(encoding="utf-8")
    for marker in (
        'id="mood-marker"',
        ".mood-marker {",
        "function renderMood(",
        "renderMood(state)",
    ):
        assert marker in wd_text, (
            f"web_dashboard missing Phase 19.0 marker: {marker!r}"
        )

    # /effectiveness section
    ed_text = (repo_root / "skills" / "effectiveness_dashboard.py").read_text(encoding="utf-8")
    assert "_render_mood_of_the_week_section" in ed_text, (
        "effectiveness_dashboard must have a Phase 19.0 mood section"
    )


@test("conversations: Phase 16.2 read-scoping is wired (becoming + all override)")
def _():
    """Phase 16.2 — read-scoping for conversations. /becoming defaults to
    the active conversation; /becoming all gives whole-vault. The
    get_learnings + render_becoming_dashboard signatures gain a
    conversation_id kwarg; the cmd_becoming handler reads
    current_conversation_id() and passes it through.

    Without read-scoping, conversations remain pure provenance — the user
    can tag writes by /conversation switch but every dashboard view sees
    everything. With read-scoping, the conversation actually shapes how
    he sees his own arc."""
    import inspect
    import myalicia.skills.user_model as hm

    # 1. get_learnings accepts conversation_id kwarg
    sig = inspect.signature(hm.get_learnings)
    assert "conversation_id" in sig.parameters, (
        "user_model.get_learnings must accept conversation_id kwarg "
        "(Phase 16.2)"
    )

    # 2. render_becoming_dashboard accepts conversation_id kwarg
    sig2 = inspect.signature(hm.render_becoming_dashboard)
    assert "conversation_id" in sig2.parameters, (
        "render_becoming_dashboard must accept conversation_id kwarg"
    )

    # 3. cmd_becoming threads current_conversation_id when no `all` arg
    from pathlib import Path as _P
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert 'sub == "all"' in alicia_text and "scope_to = None" in alicia_text, (
        "cmd_becoming must support `/becoming all` to bypass the "
        "conversation scope"
    )
    assert "render_becoming_dashboard(conversation_id=scope_to)" in alicia_text, (
        "cmd_becoming must pass scope_to into render_becoming_dashboard"
    )
    assert "from myalicia.skills.conversations import current_conversation_id" in alicia_text, (
        "cmd_becoming must import current_conversation_id"
    )

    # 4. Banner indicating scope appears in the dashboard render
    hm_text = (repo_root / "skills" / "user_model.py").read_text(encoding="utf-8")
    assert "scoped to conversation" in hm_text or "scoped to:" in hm_text, (
        "render_becoming_dashboard must surface a scope banner so the "
        "view is unambiguous about whether it's filtered"
    )


@test("conversations: Phase 16.1 active routing is wired (registry + /conversation + dashboard)")
def _():
    """Phase 16.1 — multi-conversation routing is now active. The
    schema from 16.0 was a passive default; 16.1 makes
    current_conversation_id() configurable, persists active state across
    restarts, and exposes the registry through /conversation Telegram
    command + dashboard pill. This guard locks all five wiring points."""
    from pathlib import Path as _P
    import myalicia.skills.conversations as cv
    # 1. New primitives exported
    for name in (
        "set_active_conversation", "add_conversation",
        "remove_conversation", "get_conversation_meta",
        "list_conversations", "current_conversation_id",
        "CONVERSATIONS_PATH", "_invalidate_cache",
    ):
        assert hasattr(cv, name), f"conversations must export {name}"
    # 2. list_conversations returns DICTS now (was strings in Phase 16.0)
    regs = cv.list_conversations()
    assert isinstance(regs, list) and len(regs) >= 1
    assert isinstance(regs[0], dict), (
        "list_conversations must return list[dict] (Phase 16.1)"
    )
    assert "id" in regs[0] and "label" in regs[0], (
        f"registry entries need id+label fields, got: {regs[0]}"
    )
    # 3. /conversation Telegram command wired
    repo_root = _P(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "async def cmd_conversation(" in alicia_text, (
        "alicia.py must define cmd_conversation handler"
    )
    assert '"conversation"' in alicia_text and "cmd_conversation" in alicia_text, (
        "alicia.py must register the /conversation command"
    )
    # 4. Dashboard surfaces the active conversation
    wd_text = (repo_root / "skills" / "web_dashboard.py").read_text(encoding="utf-8")
    assert "compute_conversation_state" in wd_text, (
        "web_dashboard must expose compute_conversation_state"
    )
    assert '"conversation": compute_conversation_state()' in wd_text, (
        "compute_full_state must include conversation state"
    )
    assert 'id="conversation-marker"' in wd_text, (
        "dashboard HTML must include the conversation-marker pill"
    )
    assert "function renderConversation(" in wd_text, (
        "dashboard JS must have renderConversation()"
    )


@test("conversations: Phase 16.0 schema foundation is wired into all jsonl writers")
def _():
    """Phase 16.0 lays the foundation for multi-conversation: every
    state-file write path now tags entries with conversation_id (default
    'default'). No behavioral change yet — but if this wiring drifts,
    future phases that actually scope by conversation will fail silently."""
    from pathlib import Path as _P
    import myalicia.skills.conversations as cv
    for name in ("DEFAULT_CONVERSATION_ID", "current_conversation_id",
                 "tag", "for_conversation", "list_conversations"):
        assert hasattr(cv, name), f"conversations must export {name}"
    assert cv.DEFAULT_CONVERSATION_ID == "default"

    # Every primary writer module must reference 'conversations' so the
    # field gets tagged. If a refactor silently drops the import, this
    # guardrail catches it before drift accumulates.
    repo = _P(__file__).resolve().parent.parent
    for fname in (
        "skills/circulation_composer.py",
        "skills/thread_puller.py",
        "skills/meta_synthesis.py",
        "skills/multi_channel.py",
        "skills/user_model.py",
        "skills/dimension_research.py",
        "skills/loops_dashboard.py",
        "skills/response_capture.py",
    ):
        text = (repo / fname).read_text(encoding="utf-8")
        assert "conversations" in text, (
            f"{fname} must reference skills.conversations (Phase 16.0 tag)"
        )


@test("web_dashboard: Phase 15.0 multi-surface foundation is wired (start_web_dashboard launched in main)")
def _():
    """Phase 15.0 introduces the second surface — a local web dashboard
    accessible at http://localhost:8765 from any device on the home
    network. Without this wiring, the server module exists but never
    binds when Alicia boots. Foundation for future iOS/Obsidian/etc.
    surfaces consuming the same /api/state.json contract."""
    from pathlib import Path as _P
    import myalicia.skills.web_dashboard as wd
    for name in ("compute_full_state", "list_alicia_skills",
                 "assemble_timeline", "start_web_dashboard"):
        assert hasattr(wd, name), f"web_dashboard must export {name}"
    # State contract surfaces all three metaphor sections
    state = wd.compute_full_state()
    for key in ("alicia", "user", "relationship", "skills", "timeline"):
        assert key in state, f"compute_full_state missing {key}"
    for sub in ("heart", "body", "mind", "nervous_system"):
        assert sub in state["alicia"], f"alicia.{sub} missing"
    for sub in ("mind", "voice", "body"):
        assert sub in state["user"], f"user.{sub} missing"
    for sub in ("conversation", "distillation", "coherence", "landing"):
        assert sub in state["relationship"], f"relationship.{sub} missing"

    # Server must be launched from main()
    alicia_text = (_P(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    main_idx = alicia_text.find("def main():")
    assert main_idx > 0
    main_body = alicia_text[main_idx:main_idx + 2000]
    assert "start_web_dashboard" in main_body, (
        "alicia.main() must call start_web_dashboard so the server "
        "comes up alongside Alicia"
    )


@test("loops_dashboard: Phase 14.8 dormancy alert scheduler is wired (06:30 daily)")
def _():
    """Phase 14.8 surfaces dormancy events as one-time Telegram alerts so a
    silently-stalled loop doesn't go unnoticed. Without this wiring, the
    dormancy SIGNAL exists in /loops but only when the user opens the
    dashboard — proactive alert closes that gap."""
    import myalicia.skills.loops_dashboard as ld
    for name in ("detect_dormant_loops", "unalerted_dormant_loops",
                 "record_dormancy_alert", "recent_dormancy_alerts",
                 "render_dormancy_alert_message"):
        assert hasattr(ld, name), f"loops_dashboard must export {name}"

    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "alicia.py").read_text(encoding="utf-8")
    assert "send_dormancy_check" in src, (
        "alicia.py must register send_dormancy_check"
    )
    assert "06:30" in src, (
        "dormancy check must be scheduled (06:30 daily by convention)"
    )
    assert "unalerted_dormant_loops" in src, (
        "scheduler must use unalerted_dormant_loops to suppress repeats"
    )


@test("loops_dashboard: Phase 14.9 active-streak signal is wired into all four loops")
def _():
    """Phase 14.9 is the success-mode complement to 14.7: surface
    consecutive-active-week streaks so positive momentum is visible
    alongside dormancy warnings."""
    import myalicia.skills.loops_dashboard as ld
    for name in ("_compute_active_streak_weeks", "_streak_signal",
                 "_all_capture_timestamps", "_all_meta_synthesis_timestamps",
                 "_all_dimension_question_timestamps",
                 "_all_thread_pull_timestamps"):
        assert hasattr(ld, name), f"loops_dashboard must export {name}"

    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "skills" / "loops_dashboard.py").read_text(encoding="utf-8")
    for fn in ("_loop1_inner_reply", "_loop2_meta_synthesis",
               "_loop3_gap_driven", "_loop4_thread_pull"):
        idx = src.find(f"def {fn}(")
        assert idx > 0
        next_def = src.find("\ndef ", idx + 10)
        body = src[idx:next_def if next_def > 0 else idx + 5000]
        assert "_streak_signal" in body, (
            f"{fn} must call _streak_signal (Phase 14.9) for the loop's "
            f"corresponding timestamps"
        )


@test("loops_dashboard: Phase 13.16 topology section is wired into render")
def _():
    """Phase 13.16 surfaces the static ASCII topology so the four-loop
    architecture is visible at command time, not just in PIPELINE_AUDIT."""
    import myalicia.skills.loops_dashboard as ld
    assert hasattr(ld, "_topology_section"), (
        "loops_dashboard must export _topology_section"
    )
    out = ld.render_loops_dashboard()
    assert "Topology:" in out, (
        "render_loops_dashboard must include the topology section"
    )


@test("loops_dashboard: Phase 14.7 dormancy alert helper is wired into all four loops")
def _():
    """Phase 14.7 surfaces a 'dormant for N days' flag when a loop has had
    zero activity for >=21 days. Without this, a quietly-stalled loop
    can stay invisible until someone notices the count is zero week
    after week."""
    import myalicia.skills.loops_dashboard as ld
    for name in ("_dormancy_signal", "_days_since",
                 "_latest_capture_ts", "_latest_meta_synthesis_ts",
                 "_latest_dimension_question_ts", "_latest_thread_pull_ts",
                 "DORMANCY_THRESHOLD_DAYS"):
        assert hasattr(ld, name), f"loops_dashboard must export {name}"
    # Threshold is 21d (3 weeks)
    assert ld.DORMANCY_THRESHOLD_DAYS >= 14, (
        f"DORMANCY_THRESHOLD_DAYS too eager (would noise on weekly cadence): "
        f"{ld.DORMANCY_THRESHOLD_DAYS}"
    )
    # All four loop functions must call _dormancy_signal — without that
    # the helper exists but never gets surfaced.
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "skills" / "loops_dashboard.py").read_text(encoding="utf-8")
    for fn in ("_loop1_inner_reply", "_loop2_meta_synthesis",
               "_loop3_gap_driven", "_loop4_thread_pull"):
        idx = src.find(f"def {fn}(")
        assert idx > 0
        next_def = src.find("\ndef ", idx + 10)
        body = src[idx:next_def if next_def > 0 else idx + 5000]
        assert "_dormancy_signal" in body, (
            f"{fn} must call _dormancy_signal to surface 14.7 alert"
        )


@test("effectiveness_dashboard: Phase 12.5 by-source engagement breakdown is wired into /effectiveness")
def _():
    """Phase 12.5 extends /effectiveness with a per-source engagement
    breakdown — reads prompt_effectiveness.tsv (record_proactive_sent →
    record_prompted_response) and groups depth scores by msg_type. This
    answers 'which proactive types are landing best': thread_pull vs
    dimension_question vs synthesis_review vs the slot defaults."""
    import myalicia.skills.effectiveness_dashboard as ed
    assert hasattr(ed, "_render_engagement_by_source_section"), (
        "effectiveness_dashboard must export _render_engagement_by_source_section"
    )
    assert hasattr(ed, "PROMPT_EFFECTIVENESS_TSV"), (
        "effectiveness_dashboard must define PROMPT_EFFECTIVENESS_TSV path"
    )
    # Section must be CALLED inside render_effectiveness_dashboard
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "skills" / "effectiveness_dashboard.py").read_text(encoding="utf-8")
    fn_idx = src.find("def render_effectiveness_dashboard(")
    assert fn_idx > 0
    fn_body = src[fn_idx:fn_idx + 3000]
    assert "_render_engagement_by_source_section" in fn_body, (
        "_render_engagement_by_source_section must be called from "
        "render_effectiveness_dashboard body — not just defined"
    )


@test("multichannel_dashboard: Phase 13.8 /multichannel command is wired (drawing+voice observability)")
def _():
    """Phase 13.8 closes the loop on Phases 13.3 + 13.7: every smart-decider
    decision (fire/skip + path + rationale) is logged, but until this
    dashboard the log was write-only. /multichannel renders last-24h
    fire/skip rates by channel + path so we can SEE whether the smart
    deciders are doing what we want."""
    from pathlib import Path
    import myalicia.skills.multichannel_dashboard as mcd
    assert hasattr(mcd, "render_multichannel_dashboard"), (
        "multichannel_dashboard must export render_multichannel_dashboard"
    )

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.multichannel_dashboard import render_multichannel_dashboard" in alicia_text, (
        "alicia.py must import render_multichannel_dashboard"
    )
    assert "async def cmd_multichannel(" in alicia_text, (
        "alicia.py must define cmd_multichannel handler"
    )
    assert '"multichannel"' in alicia_text and "cmd_multichannel" in alicia_text, (
        "alicia.py must register the /multichannel CommandHandler"
    )

    # Render must succeed end-to-end on an empty/missing log
    out = mcd.render_multichannel_dashboard()
    assert isinstance(out, str) and "Multichannel" in out, (
        f"render must produce a recognizable dashboard string, got: {out[:120]}"
    )


@test("multi_channel: Phase 13.7 smart voice decider is wired into morning/midday/evening")
def _():
    """Phase 13.7 mirrors Phase 13.3 for voice. Voice has been the
    always-on second channel since the early phases, but lists, code,
    URLs, headers, and very long text degrade in TTS. Without this
    wiring, every proactive fires voice regardless of whether the text
    actually wants to be spoken."""
    from pathlib import Path
    import myalicia.skills.multi_channel as mc
    for name in (
        "decide_voice_amplification",
        "voice_fired_recently",
        "VOICE_SATURATION_24H",
        "VOICE_LONG_THRESHOLD",
        "_voice_skip_patterns_present",
    ):
        assert hasattr(mc, name), f"multi_channel must export {name}"

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    # All three proactive sends must call decide_voice_amplification
    for slot_fn in ("send_morning_message", "send_midday_message", "send_evening_message"):
        fn_idx = alicia_text.find(f"async def {slot_fn}(")
        assert fn_idx > 0, f"{slot_fn} not found"
        next_def = alicia_text.find("\n    async def ", fn_idx + 10)
        if next_def < 0:
            next_def = alicia_text.find("\nasync def ", fn_idx + 10)
        fn_body = alicia_text[fn_idx:next_def if next_def > 0 else fn_idx + 5000]
        assert "decide_voice_amplification" in fn_body, (
            f"{slot_fn} must call decide_voice_amplification before firing voice"
        )


@test("multi_channel: Phase 13.3 smart drawing decider is wired into _maybe_amplify_with_drawing")
def _():
    """Phase 13.3 replaces the score-only drawing gate with a three-tier
    decider: fast path (≥3.0), skip (<1.5 / saturation / ineligible), and
    Haiku judge for borderline scores. Without this wiring, every
    high-scoring composer decision fires a drawing whether or not the
    text actually wants to be visualized."""
    from pathlib import Path
    import myalicia.skills.multi_channel as mc
    for name in (
        "decide_drawing_amplification",
        "record_multi_channel_decision",
        "recent_multi_channel_decisions",
        "drawings_fired_recently",
        "SCORE_FAST_PATH",
        "SCORE_FLOOR",
        "SATURATION_24H",
        "ELIGIBLE_SOURCE_KINDS",
    ):
        assert hasattr(mc, name), f"multi_channel must export {name}"

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    # Smart decider must be CALLED inside _maybe_amplify_with_drawing
    fn_idx = alicia_text.find("async def _maybe_amplify_with_drawing(")
    assert fn_idx > 0, "_maybe_amplify_with_drawing not found in alicia.py"
    next_def = alicia_text.find("\nasync def ", fn_idx + 10)
    fn_body = alicia_text[fn_idx:next_def if next_def > 0 else len(alicia_text)]
    assert "decide_drawing_amplification" in fn_body, (
        "decide_drawing_amplification must be called from "
        "_maybe_amplify_with_drawing, not just imported elsewhere"
    )
    assert "from myalicia.skills.multi_channel import" in fn_body, (
        "smart decider should be imported lazily inside the function so "
        "import failures fall back to the legacy gate"
    )
    # Legacy gate must still be reachable as fallback
    assert "composer_should_amplify_with_drawing" in fn_body, (
        "legacy gate must remain as fallback inside _maybe_amplify_with_drawing"
    )


@test("dimension_research: Phase 12.4 gap escalation to research is wired into nightly scan")
def _():
    """Phase 12.4 escalates persistent gaps from 'ask the user a question' to
    'do a research_skill brief on the dimension's themes'. When the same
    dimension stays thin across ESCALATE_AFTER_CONSECUTIVE scans, the
    nightly 03:00 task triggers a research pass. Without this wiring,
    persistent gaps just keep getting questions every week — the system
    never proactively learns more about them."""
    import myalicia.skills.dimension_research as dr
    for name in (
        "record_dimension_scan",
        "recent_dimension_scans",
        "get_persistent_thin_dimensions",
        "record_dimension_escalation",
        "recent_escalations",
        "pick_escalation_target",
        "escalate_to_research",
        "ESCALATE_AFTER_CONSECUTIVE",
        "ESCALATION_COOLDOWN_DAYS",
        "_ESCALATION_TOPICS",
    ):
        assert hasattr(dr, name), f"dimension_research must export {name}"

    # _ESCALATION_TOPICS must cover every canonical user_model dimension
    from myalicia.skills.user_model import DIMENSIONS as HM_DIMS
    for d in HM_DIMS:
        assert d in dr._ESCALATION_TOPICS, (
            f"_ESCALATION_TOPICS missing entry for {d!r}"
        )

    # run_dimension_research_scan must wire scan-recording AND escalation
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "skills" / "dimension_research.py").read_text(encoding="utf-8")
    fn_idx = src.find("def run_dimension_research_scan(")
    assert fn_idx > 0
    fn_body = src[fn_idx:fn_idx + 4000]
    assert "record_dimension_scan(" in fn_body, (
        "run_dimension_research_scan must record each scan to history"
    )
    assert "pick_escalation_target(" in fn_body, (
        "run_dimension_research_scan must check for escalation candidates"
    )
    assert "escalate_to_research(" in fn_body, (
        "run_dimension_research_scan must call escalate_to_research"
    )


@test("dimension_research: Phase 12.2 gap-driven question is wired (scheduler + midday rotation)")
def _():
    """Phase 12.2 closes the the user-model loop: when a dimension goes
    quiet (>14d no learnings), it becomes the seed for an outbound
    question. Without this wiring, find_thin_dimensions stays a passive
    metric — it tells you what's missing but never reaches out."""
    from pathlib import Path
    import myalicia.skills.dimension_research as dr
    for name in (
        "pick_thin_dimension",
        "compose_dimension_question",
        "build_dimension_targeted_question",
        "run_dimension_research_scan",
        "record_dimension_question_asked",
        "recent_dimension_questions",
        "DIMENSION_COOLDOWN_DAYS",
    ):
        assert hasattr(dr, name), f"dimension_research must export {name}"

    # Frames must cover every dimension — Haiku needs the framing hint
    # to compose grounded questions instead of generic ones.
    from myalicia.skills.user_model import DIMENSIONS as HM_DIMS
    for d in HM_DIMS:
        assert d in dr._DIMENSION_FRAMES, (
            f"_DIMENSION_FRAMES missing entry for dimension '{d}'"
        )

    # Wired into proactive_messages.build_midday_message
    pm_text = (Path(__file__).resolve().parent.parent
               / "skills" / "proactive_messages.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.dimension_research import" in pm_text, (
        "proactive_messages.py must import from dimension_research"
    )
    midday_idx = pm_text.find("def build_midday_message(")
    assert midday_idx > 0
    next_def = pm_text.find("\ndef ", midday_idx + 10)
    midday_body = pm_text[midday_idx:next_def if next_def > 0 else len(pm_text)]
    assert "build_dimension_targeted_question" in midday_body, (
        "build_dimension_targeted_question must be called from "
        "build_midday_message body, not just imported at module scope"
    )
    assert "dimension_question" in midday_body, (
        "dimension_question source_kind must be recorded in midday body"
    )

    # Scheduled at 03:00 nightly
    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert 'schedule.every().day.at("03:00")' in alicia_text, (
        "alicia.py must register the dimension_research_scan schedule at 03:00"
    )
    assert ("dimension_research_scan" in alicia_text
            or "send_dimension_research_scan" in alicia_text), (
        "alicia.py must wire send_dimension_research_scan into the scheduler"
    )


@test("circulation_composer: Phase 13.13 meta-synthesis surfacing bonus is wired into _score_surfacing")
def _():
    """Phase 13.13 gives meta-syntheses a composer weight bonus that
    scales with their recursion level (Phase 13.10). Without this
    wiring, a level-2 meta-meta-synthesis competes for surfacing slots
    on equal footing with a plain synthesis — even though it represents
    a higher-altitude distillation that should surface preferentially."""
    from pathlib import Path
    import myalicia.skills.circulation_composer as cc
    for name in (
        "_meta_surfacing_bonus",
        "META_SURFACING_BONUS_BASE",
        "META_SURFACING_BONUS_PER_LEVEL",
    ):
        assert hasattr(cc, name), f"circulation_composer must export {name}"

    src = (Path(__file__).resolve().parent.parent
           / "skills" / "circulation_composer.py").read_text(encoding="utf-8")
    # Bonus must be CALLED inside _score_surfacing
    fn_idx = src.find("def _score_surfacing(")
    assert fn_idx > 0
    next_def = src.find("\ndef ", fn_idx + 10)
    fn_body = src[fn_idx:next_def if next_def > 0 else len(src)]
    assert "_meta_surfacing_bonus" in fn_body, (
        "_meta_surfacing_bonus must be called inside _score_surfacing — "
        "not just defined"
    )
    # End-to-end: the bonus must produce different scores for different levels
    plain = cc._meta_surfacing_bonus({"synthesis_title": "Definitely does not exist x9z"})
    assert plain == 0.0, "missing/plain synthesis must get 0.0 bonus"


@test("alicia: Phase 13.14 /metasynthesis surfaces level distribution + MAX_META_LEVEL cap")
def _():
    """Phase 13.14 makes the recursion structure visible in /metasynthesis.
    Default (no-arg) call now buckets candidates by their would-be child
    level (parent_level + 1) and explicitly flags any candidate that
    would exceed MAX_META_LEVEL. Without this, the recursion bookkeeping
    from Phase 13.10 is invisible to the user at command time."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "alicia.py").read_text(encoding="utf-8")
    fn_idx = src.find("async def cmd_metasynthesis(")
    assert fn_idx > 0
    next_def = src.find("\nasync def ", fn_idx + 10)
    fn_body = src[fn_idx:next_def if next_def > 0 else fn_idx + 6000]
    # Body must read parent level and reference MAX_META_LEVEL
    assert "get_synthesis_level" in fn_body, (
        "cmd_metasynthesis must read each parent's level via get_synthesis_level"
    )
    assert "MAX_META_LEVEL" in fn_body, (
        "cmd_metasynthesis must enforce/show MAX_META_LEVEL cap"
    )
    assert "Level 1" in fn_body or "target_level" in fn_body, (
        "cmd_metasynthesis must bucket candidates by would-be child level"
    )


@test("meta_synthesis: Phase 13.10 recursion (level tracking + MAX_META_LEVEL cap) is wired")
def _():
    """Phase 13.10 makes the meta-synthesis recursion explicit and bounded.
    A meta-synthesis can itself accumulate captures and become a parent of
    a meta-meta-synthesis. We track the recursion depth in frontmatter
    (`level: N`) and cap at MAX_META_LEVEL to prevent runaway recursion
    if the system gets stuck in a re-amplification loop."""
    import myalicia.skills.meta_synthesis as ms
    assert hasattr(ms, "MAX_META_LEVEL"), (
        "meta_synthesis must export MAX_META_LEVEL"
    )
    assert ms.MAX_META_LEVEL >= 2, (
        f"MAX_META_LEVEL must allow at least one recursion: {ms.MAX_META_LEVEL}"
    )
    assert hasattr(ms, "get_synthesis_level"), (
        "meta_synthesis must export get_synthesis_level helper"
    )

    # Round-trip sanity: level reads back from emitted frontmatter
    test_md = ms._attach_frontmatter(
        "# x\nbody",
        parent_title="P",
        parent_path=__import__("pathlib").Path("P.md"),
        capture_count=3, level=2,
    )
    assert ms.get_synthesis_level(test_md) == 2, (
        f"level round-trip failed: emitted level=2 but read back: "
        f"{ms.get_synthesis_level(test_md)}"
    )

    # Source check: the build flow must compute new_level from parent and
    # respect the cap. Reading source for these constraints catches
    # regressions where recursion bookkeeping silently regresses.
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "skills" / "meta_synthesis.py").read_text(encoding="utf-8")
    assert "get_synthesis_level(parent_text)" in src, (
        "build_meta_synthesis must read parent's level via get_synthesis_level"
    )
    assert "MAX_META_LEVEL" in src and "new_level > MAX_META_LEVEL" in src, (
        "build_meta_synthesis must enforce the MAX_META_LEVEL cap"
    )


@test(f"meta_synthesis: Phase 13.9 cross-loop bridge to {USER_NAME}-model is wired")
def _():
    """Phase 13.9 closes the gap between the outer-synthesis loop and the
    the user-model arc. After build_meta_synthesis writes the new file, it
    runs a follow-up Sonnet call that extracts dimension-tagged learnings
    ABOUT USER (not about the idea) and appends them to user_learnings
    via append_learning. Provenance is encoded as 'meta_synthesis:<parent>'
    so /becoming can show the bridge origin."""
    from pathlib import Path
    import myalicia.skills.meta_synthesis as ms
    for name in (
        "bridge_meta_to_user_model",
        "_extract_learnings_from_meta",
    ):
        assert hasattr(ms, name), (
            f"meta_synthesis must export {name} for Phase 13.9 bridge"
        )

    src_text = (Path(__file__).resolve().parent.parent
                / "skills" / "meta_synthesis.py").read_text(encoding="utf-8")
    # The bridge MUST be called from inside build_meta_synthesis after
    # the file write completes — not exposed only as a manual function.
    fn_idx = src_text.find("def build_meta_synthesis(")
    assert fn_idx > 0, "build_meta_synthesis function not found"
    next_def = src_text.find("\ndef ", fn_idx + 10)
    fn_body = src_text[fn_idx:next_def if next_def > 0 else len(src_text)]
    assert "bridge_meta_to_user_model" in fn_body, (
        "bridge_meta_to_user_model must be called from build_meta_synthesis "
        "(not just imported elsewhere) — otherwise the cross-loop bridge "
        "doesn't fire on scheduled meta-synthesis builds"
    )
    # Bridge must use user_model.append_learning (the canonical writer)
    assert "append_learning" in src_text, (
        "bridge must call user_model.append_learning"
    )
    # Source-tag convention: provenance string starts with 'meta_synthesis:'
    assert "meta_synthesis:" in src_text, (
        "bridge must tag source with 'meta_synthesis:<parent>' for /becoming traceability"
    )


@test("meta_synthesis: Phase 13.6 outer loop is wired (scheduled pass + /metasynthesis command)")
def _():
    """Phase 13.6 closes the outermost loop: when the user's captured
    responses on a single synthesis cross a threshold, that cluster
    of dialogue gets distilled into its own meta-synthesis. Without
    this wiring, captures stay siloed in writing/Responses/ and never
    re-enter the synthesis ecosystem at a higher altitude."""
    from pathlib import Path
    import myalicia.skills.meta_synthesis as ms
    for name in (
        "find_synthesis_path",
        "candidates_for_meta_synthesis",
        "build_meta_synthesis",
        "run_meta_synthesis_pass",
        "has_recent_meta",
        "record_meta_synthesis",
        "recent_meta_syntheses",
        "MIN_CAPTURES_FOR_META",
        "META_COOLDOWN_DAYS",
    ):
        assert hasattr(ms, name), f"meta_synthesis must export {name}"

    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.meta_synthesis import" in alicia_text, (
        "alicia.py must import from meta_synthesis"
    )
    assert "async def cmd_metasynthesis(" in alicia_text, (
        "alicia.py must define cmd_metasynthesis handler"
    )
    assert '"metasynthesis"' in alicia_text and "cmd_metasynthesis" in alicia_text, (
        "alicia.py must register the /metasynthesis CommandHandler"
    )
    # Subcommands
    for sub in ('"run"', '"build"'):
        assert sub in alicia_text, (
            f"cmd_metasynthesis must handle the {sub} subcommand"
        )
    # Scheduled task at 02:30 nightly
    assert 'schedule.every().day.at("02:30")' in alicia_text, (
        "alicia.py must register the meta_synthesis schedule at 02:30"
    )
    assert '"meta_synthesis"' in alicia_text or "send_meta_synthesis_pass" in alicia_text, (
        "alicia.py must wire send_meta_synthesis_pass into the scheduler"
    )


@test("thread_puller: Phase 13.11 thread-pull → reply bridge is wired into response_capture")
def _():
    """Phase 13.11 closes the loop on Phase 13.5: when the user replies to a
    thread-pull message, the underlying Open Thread should be marked as
    advanced so Sunday's person_diarization can see what's moved. Without
    this wiring, captures land normally but the thread-pull side has no
    feedback signal."""
    from pathlib import Path
    import myalicia.skills.thread_puller as tp
    for name in (
        "is_thread_pull_message",
        "mark_thread_pull_replied",
        "recent_thread_pull_replies",
        "advanced_threads",
        "THREAD_PULL_BANNER",
    ):
        assert hasattr(tp, name), f"thread_puller must export {name}"

    rc_text = (Path(__file__).resolve().parent.parent
               / "skills" / "response_capture.py").read_text(encoding="utf-8")
    assert "_maybe_mark_thread_pull_replied" in rc_text, (
        "response_capture must define _maybe_mark_thread_pull_replied helper"
    )
    # Helper must be CALLED from capture_if_responsive after a capture is
    # written — not only defined.
    fn_idx = rc_text.find("def capture_if_responsive(")
    assert fn_idx > 0
    next_def = rc_text.find("\ndef ", fn_idx + 10)
    fn_body = rc_text[fn_idx:next_def if next_def > 0 else len(rc_text)]
    assert "_maybe_mark_thread_pull_replied" in fn_body, (
        "_maybe_mark_thread_pull_replied must be called from capture_if_responsive"
    )
    # Both capture paths (native reply + composer-window) must call it
    # so thread-pull replies are caught regardless of which path triggers.
    call_count = fn_body.count("_maybe_mark_thread_pull_replied(")
    assert call_count >= 2, (
        f"both native-reply + composer-window capture paths must call "
        f"_maybe_mark_thread_pull_replied; found {call_count} call(s)"
    )


@test("thread_puller: Phase 13.5 thread-pull is wired into midday rotation (profile-driven proactivity)")
def _():
    """Phase 13.5 closes the loop between Sunday's diarization (which
    writes Open Threads to the the user profile) and mid-week proactivity
    (which previously had no idea those threads existed). Without this
    wiring, the profile is a backwater that Alicia writes once a week
    and never reads from for outbound messages."""
    from pathlib import Path
    import myalicia.skills.thread_puller as tp
    for name in (
        "parse_open_threads",
        "pick_thread",
        "record_thread_pull",
        "recent_thread_pulls",
        "build_thread_pull_message",
        "MIDDAY_PROBABILITY",
        "PULL_COOLDOWN_DAYS",
    ):
        assert hasattr(tp, name), f"thread_puller must export {name}"

    pm_text = (Path(__file__).resolve().parent.parent
               / "skills" / "proactive_messages.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.thread_puller import" in pm_text, (
        "proactive_messages.py must import from thread_puller"
    )
    assert "build_thread_pull_message" in pm_text, (
        "proactive_messages.py must call build_thread_pull_message"
    )
    # The thread-pull branch must live INSIDE build_midday_message —
    # not a stray import at module level.
    midday_idx = pm_text.find("def build_midday_message(")
    assert midday_idx > 0, "build_midday_message function not found"
    # Find the next def after build_midday_message
    next_def = pm_text.find("\ndef ", midday_idx + 10)
    midday_body = pm_text[midday_idx:next_def if next_def > 0 else len(pm_text)]
    assert "build_thread_pull_message" in midday_body, (
        "build_thread_pull_message must be called from build_midday_message body, "
        "not just imported at module scope"
    )
    assert "thread_pull" in midday_body, (
        "thread_pull source_kind must be recorded in midday body"
    )


@test("season_dashboard: Phase 13.4 /season command is wired (developmental trajectory dashboard)")
def _():
    """Phase 13.4 — Alicia's developmental arc surface. Where /becoming
    shows the user's arc, /season shows Alicia's: poetic season + emergence
    + archetype balance now + 14-day attribution map + arc progression +
    maturing/nascent split. Pure read-only assembler over inner_life
    state — no new state files. Without this wiring guardrail, the dashboard
    file could exist (test_season_dashboard.py would still pass) but never
    be reachable from Telegram."""
    from pathlib import Path
    import myalicia.skills.season_dashboard as sd
    assert hasattr(sd, "render_season_dashboard"), (
        "season_dashboard must export render_season_dashboard"
    )
    # The dashboard must compose existing inner_life infrastructure rather
    # than introduce a new state file.
    sd_text = (Path(__file__).resolve().parent.parent
               / "skills" / "season_dashboard.py").read_text(encoding="utf-8")
    for fn in (
        "compute_dynamic_archetype_weights",
        "get_archetype_effectiveness",
        "get_poetic_age",
        "SEASONS",
    ):
        assert fn in sd_text, (
            f"season_dashboard must reuse inner_life's {fn} "
            f"(no new state files allowed)"
        )

    # Render must succeed end-to-end without exceptions even with sparse data.
    out = sd.render_season_dashboard()
    assert isinstance(out, str) and len(out) > 50, (
        "render_season_dashboard must produce a non-trivial string"
    )
    for header in ("Season —", "Arc so far", "Archetype balance now"):
        assert header in out, f"missing required section header: {header}"

    # alicia.py wiring — import + handler + registration
    alicia_text = (Path(__file__).resolve().parent.parent
                   / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.season_dashboard import render_season_dashboard" in alicia_text, (
        "alicia.py must import render_season_dashboard"
    )
    assert "async def cmd_season(" in alicia_text, (
        "alicia.py must define cmd_season handler"
    )
    assert '"season"' in alicia_text and "cmd_season" in alicia_text, (
        "alicia.py must register the /season CommandHandler"
    )


@test("scheduler: Sunday weekly retrospective is registered at 19:00 (Phase 11.9 + 14.2 wiring guardrail)")
def _():
    """The system observes itself weekly. send_weekly_retrospective() pushes
    /wisdom + /effectiveness + /loops on Sunday 19:00, just before the
    heavy 20:00 deep pass. Without this wiring, the rhythm of
    self-observation is daily only — no end-of-week reflection.

    Phase 14.2 added /loops to the digest so the meta-circulatory view
    (four closed loops + cross-loop signals) is part of the weekly
    read-through alongside the surface-level dashboards."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "async def send_weekly_retrospective" in alicia_text, (
        "alicia.py must define send_weekly_retrospective"
    )
    # Phase 14.2 — /loops must join the digest alongside /wisdom + /effectiveness
    fn_idx = alicia_text.find("async def send_weekly_retrospective")
    assert fn_idx > 0
    next_def = alicia_text.find("\n    async def ", fn_idx + 10)
    fn_body = alicia_text[fn_idx:next_def if next_def > 0 else fn_idx + 4000]
    for renderer in ("render_wisdom_dashboard()",
                     "render_effectiveness_dashboard()",
                     "render_loops_dashboard()",
                     "render_becoming_dashboard()"):
        assert renderer in fn_body, (
            f"send_weekly_retrospective must call {renderer} "
            f"(Phase 11.9 + 14.2 + 14.4 digest contract)"
        )
    assert 'sunday.at("19:00")' in alicia_text, (
        "scheduler must register Sunday 19:00 retrospective"
    )
    assert "weekly_retrospective" in alicia_text, (
        "scheduler entry must reference weekly_retrospective"
    )


@test("effectiveness_dashboard: /effectiveness command is wired (Phase 11.8 wiring guardrail)")
def _():
    """Sibling to /wisdom for feedback-signal observability — reactions,
    archetype EMA, voice tone, emotion classifications, and the
    proactive-engagement-rate metric Phase 11.7 unlocked (composer sends
    matched against capture files via proactive_decision_id)."""
    import myalicia.skills.effectiveness_dashboard as ed
    assert hasattr(ed, "render_effectiveness_dashboard"), (
        "effectiveness_dashboard must export render_effectiveness_dashboard"
    )
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.effectiveness_dashboard import render_effectiveness_dashboard" \
        in alicia_text, "alicia.py must import render_effectiveness_dashboard"
    assert "async def cmd_effectiveness(" in alicia_text, (
        "alicia.py must define cmd_effectiveness handler"
    )
    assert '"effectiveness"' in alicia_text and "cmd_effectiveness" in alicia_text, (
        "alicia.py must register the /effectiveness CommandHandler"
    )


@test("response_capture: enrich_proactive_with_past_responses is wired into morning/midday/evening (Phase 11.7 wiring guardrail)")
def _():
    """Phase 11.7 closes the inner reply loop by auto-appending past
    responses to surfacing-driven proactives. Without this wiring, the
    composer picks a synthesis but the user's past replies on it stay
    siloed in writing/Responses/ — the conversation doesn't continue."""
    import myalicia.skills.response_capture as rc
    assert hasattr(rc, "enrich_proactive_with_past_responses"), (
        "response_capture must export enrich_proactive_with_past_responses"
    )
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "enrich_proactive_with_past_responses" in alicia_text, (
        "alicia.py must import enrich_proactive_with_past_responses"
    )
    n_call_sites = alicia_text.count("enrich_proactive_with_past_responses(")
    # 1 import + 3 call sites (morning, midday, evening) = 4 occurrences
    assert n_call_sites >= 4, (
        f"expected >=4 enrich_proactive_with_past_responses references in "
        f"alicia.py (1 import + 3 slots), found {n_call_sites}"
    )


@test("tool_router: recent_responses tool is registered + dispatched (Phase 11.6 wiring guardrail)")
def _():
    """The recent_responses tool gives Sonnet agency to retrieve the user's
    past captured replies on a synthesis. Without this tool, Sonnet has no
    way to weave past responses into a re-surfacing message — the inner
    reply loop can't close."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    tr_text = (repo_root / "skills" / "tool_router.py").read_text(encoding="utf-8")

    # 1. TOOLS list contains the recent_responses entry
    assert '"name": "recent_responses"' in tr_text, (
        "tool_router.py TOOLS list must include recent_responses"
    )
    # 2. Input schema requires synthesis_title
    assert '"required": ["synthesis_title"]' in tr_text, (
        "recent_responses must require synthesis_title"
    )
    # 3. execute_tool dispatches to it
    assert 'tool_name == "recent_responses"' in tr_text, (
        "execute_tool must have a recent_responses branch"
    )
    # 4. Dispatch calls the underlying response_capture function
    assert "get_responses_for_synthesis" in tr_text, (
        "recent_responses dispatch must call get_responses_for_synthesis"
    )
    # 5. Specialist trigger keywords registered (fallback keyword routing)
    assert '"recent_responses":' in tr_text, (
        "recent_responses must be in _SPECIALIST_TRIGGERS"
    )


@test("circulation_composer: alicia.py records rendered prompt text after each proactive send (Phase 11.2 wiring guardrail)")
def _():
    # Without this guardrail, a future refactor could drop the
    # record_send() calls and response_capture would silently fall back
    # to logging the composer's internal `reason` string instead of the
    # actual Telegram message the user saw.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    alicia_text = (repo_root / "alicia.py").read_text(encoding="utf-8")
    assert "record_circulation_send" in alicia_text, (
        "alicia.py must import record_send (as record_circulation_send)."
    )
    # Each of the three composer-gated slots must call record_send after
    # a successful Telegram send. The cheapest invariant is "the call must
    # appear at least three times across the file".
    n_calls = alicia_text.count("record_circulation_send(")
    assert n_calls >= 3, (
        f"expected >=3 record_circulation_send calls in alicia.py "
        f"(morning + midday + evening), found {n_calls}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# LIVED → SYNTHESIS FEEDBACK LOOP (Layer 4 closing the circuit, item #20)
# ═══════════════════════════════════════════════════════════════════════════
print("\n♾️  Lived → Synthesis Feedback")

@test("finalizer: Lived-note feedback API is importable")
def _():
    import myalicia.skills.synthesis_finalizer as sf
    for name in (
        "LIVED_DIR", "PRACTICES_DIR", "CANONICAL_SOURCE_DIRS",
        "parse_lived_note", "list_lived_notes", "find_syntheses_citing",
        "finalize_lived_note", "finalize_all_lived_notes",
        "check_lived_invariants",
    ):
        assert hasattr(sf, name), f"synthesis_finalizer missing: {name}"

@test("finalizer: LIVED_DIR is in CANONICAL_SOURCE_DIRS (first-class contract)")
def _():
    from myalicia.skills.synthesis_finalizer import LIVED_DIR, CANONICAL_SOURCE_DIRS
    assert LIVED_DIR in CANONICAL_SOURCE_DIRS, (
        "LIVED_DIR must be a canonical source — Layer 4 feedback loop depends on it."
    )

@test("practice_runner: close_practice calls finalize_lived_note (feedback-wiring guardrail)")
def _():
    # Dead-config-guardrail for #20. If a future edit silently unwires the
    # Lived → Synthesis feedback loop, CI fails loudly — any closed practice
    # would henceforth orphan its Lived note from the circulation queue.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    pr_text = (repo_root / "skills" / "practice_runner.py").read_text(encoding="utf-8")
    assert "from myalicia.skills.synthesis_finalizer import finalize_lived_note" in pr_text, (
        "close_practice must call synthesis_finalizer.finalize_lived_note — "
        "the Lived → Synthesis feedback loop is structurally required."
    )

@test("finalizer: real-vault Lived notes have no structural violations")
def _():
    # Every Lived note must have a **Descent.** wikilink AND a matching
    # /Alicia/Practices/<slug>/practice.md. Usage-based violations (unused
    # for >90d) are informational and do NOT fail this test.
    from myalicia.skills.synthesis_finalizer import check_lived_invariants
    vs = check_lived_invariants()
    structural = [v for v in vs if v["kind"] in (
        "parse_error", "lived_missing_descent", "lived_orphan_practice",
    )]
    assert not structural, (
        f"Lived-note structural violations: {structural}"
    )

@test("composer: lived_surfacing branch is honored (log-schema guardrail)")
def _():
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    cc_text = (repo_root / "skills" / "circulation_composer.py").read_text(encoding="utf-8")
    # The Composer must recognize kind=lived surfacings and emit them
    # with source_kind="lived_surfacing" for circulation-log auditability.
    assert "\"lived\"" in cc_text, (
        "circulation_composer.py must branch on kind='lived' surfacings."
    )
    assert "lived_surfacing" in cc_text, (
        "circulation_composer.py must record source_kind='lived_surfacing' "
        "so Lived vs synthesis circulation can be audited separately."
    )
    assert "archetype_hint" in cc_text, (
        "circulation_composer.py must honor archetype_hint from Lived notes."
    )


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"Results: {PASS}/{total} passed", end="")
if FAIL:
    print(f", {FAIL} FAILED")
    print("\nFailures:")
    for name, err in ERRORS:
        print(f"  ❌ {name}: {err}")
else:
    print(" ✨")
print()
sys.exit(1 if FAIL else 0)
