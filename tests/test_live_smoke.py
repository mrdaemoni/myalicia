"""
Live Integration Smoke Tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run ON the Mac Mini where Alicia lives. These test real imports,
real file paths, real .env loading, and real module wiring.

Usage:
    cd ~/alicia/alicia
    python3 -m pytest tests/test_live_smoke.py -v --tb=short

These do NOT make API calls or send Telegram messages.
They verify that the system boots and wires correctly.
"""
import os
import sys
import importlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── GATE: only run on the real Mac Mini ─────────────────────────────────────
IS_MAC_MINI = os.path.exists(os.path.expanduser("~/alicia/alicia/alicia.py"))

pytestmark = pytest.mark.skipif(
    not IS_MAC_MINI,
    reason="Live smoke tests only run on Mac Mini with real .env"
)


class TestAllSkillsImport:
    """Every skill module should import without crashing."""

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
    ]

    @pytest.mark.parametrize("module_name", SKILL_MODULES)
    def test_skill_imports(self, module_name):
        """Each skill module should import without errors."""
        mod = importlib.import_module(module_name)
        assert mod is not None


class TestCriticalPathsExist:
    """Verify that all directories and files Alicia needs are present."""

    REQUIRED_DIRS = [
        "~/alicia/memory",
        "~/alicia/logs",
        "~/alicia/alicia/skills",
    ]

    REQUIRED_FILES = [
        "~/alicia/alicia/alicia.py",
        "~/alicia/alicia/skills/tool_router.py",
        "~/alicia/alicia/skills/memory_skill.py",
    ]

    @pytest.mark.parametrize("dirpath", REQUIRED_DIRS)
    def test_directory_exists(self, dirpath):
        expanded = os.path.expanduser(dirpath)
        assert os.path.isdir(expanded), f"Missing directory: {expanded}"

    @pytest.mark.parametrize("filepath", REQUIRED_FILES)
    def test_file_exists(self, filepath):
        expanded = os.path.expanduser(filepath)
        assert os.path.isfile(expanded), f"Missing file: {expanded}"


class TestMemoryFilesIntact:
    """Verify memory files exist and have content."""

    MEMORY_FILES = ["MEMORY.md", "patterns.md", "insights.md", "preferences.md", "concepts.md"]

    @pytest.mark.parametrize("filename", MEMORY_FILES)
    def test_memory_file_exists_and_nonempty(self, filename):
        path = os.path.expanduser(f"~/alicia/memory/{filename}")
        assert os.path.isfile(path), f"Missing: {path}"
        assert os.path.getsize(path) > 0, f"Empty: {path}"


class TestToolRouterWiring:
    """Verify tool_router has all expected tools defined."""

    def test_tools_list_populated(self):
        from skills.tool_router import TOOLS
        assert len(TOOLS) >= 10, f"Expected 10+ tools, got {len(TOOLS)}"

    def test_all_expected_tools_present(self):
        from skills.tool_router import TOOLS
        tool_names = {t["name"] for t in TOOLS}
        expected = {
            "remember", "search_vault", "send_email",
            "generate_pdf", "research", "get_random_quote",
        }
        missing = expected - tool_names
        assert not missing, f"Missing tools: {missing}"

    def test_execute_tool_exists(self):
        from skills.tool_router import execute_tool
        assert callable(execute_tool)

    def test_route_message_exists(self):
        from skills.tool_router import route_message
        assert callable(route_message)


class TestReflexionConstitutionWiring:
    """Verify reflexion and constitution modules have expected gating functions."""

    def test_reflexion_gating_functions_exist(self):
        from skills.reflexion import should_reflect
        assert callable(should_reflect)

    def test_constitution_gating_functions_exist(self):
        from skills.constitution import should_evaluate
        assert callable(should_evaluate)

    def test_trajectory_recorder_class_exists(self):
        from skills.trajectory import TrajectoryRecorder
        assert TrajectoryRecorder is not None


class TestProactiveMessageWiring:
    """Verify proactive message system is wired correctly."""

    def test_get_startup_stats_exists(self):
        from skills.proactive_messages import get_startup_stats
        assert callable(get_startup_stats)

    def test_generate_morning_greeting_exists(self):
        from skills.proactive_messages import generate_morning_greeting
        assert callable(generate_morning_greeting)


class TestVaultSystemWiring:
    """Verify vault operations modules are functional."""

    def test_vault_resolver_has_resolve(self):
        from skills.vault_resolver import resolve_note
        assert callable(resolve_note)

    def test_vault_metrics_has_determine_level(self):
        from skills.vault_metrics import determine_level
        assert callable(determine_level)

    def test_vault_metrics_has_dashboard(self):
        from skills.vault_metrics import format_knowledge_dashboard
        assert callable(format_knowledge_dashboard)


class TestSafeMarkdownHelpersExist:
    """Verify that safe_reply_md and safe_send_md are defined in alicia.py."""

    def test_safe_helpers_in_source(self):
        """The Markdown safety helpers must be present in alicia.py source."""
        alicia_path = os.path.expanduser("~/alicia/alicia/alicia.py")
        with open(alicia_path) as f:
            source = f.read()
        assert "async def safe_reply_md(" in source, "safe_reply_md not found"
        assert "async def safe_send_md(" in source, "safe_send_md not found"

    def test_no_unsafe_dynamic_markdown_sends(self):
        """
        Check that dynamic content sends use safe helpers, not raw parse_mode.
        Any remaining parse_mode='Markdown' should be on static strings only.
        """
        alicia_path = os.path.expanduser("~/alicia/alicia/alicia.py")
        with open(alicia_path) as f:
            lines = f.readlines()

        unsafe = []
        for i, line in enumerate(lines, 1):
            if 'parse_mode="Markdown"' in line or "parse_mode='Markdown'" in line:
                # Skip if it's inside the safe helpers themselves
                if "def safe_reply_md" in line or "def safe_send_md" in line:
                    continue
                # Skip the try: line inside the helpers
                stripped = line.strip()
                if stripped.startswith("return await") and ("safe_reply_md" in stripped or "safe_send_md" in stripped):
                    continue
                unsafe.append((i, stripped))

        # There might be a few static-content sends that are OK,
        # but flag them for review if there are more than ~5
        assert len(unsafe) <= 8, (
            f"Found {len(unsafe)} raw Markdown sends — review these:\n"
            + "\n".join(f"  L{n}: {l}" for n, l in unsafe[:15])
        )


class TestEnvConfiguration:
    """Verify .env has all required keys (without exposing values)."""

    REQUIRED_KEYS = [
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_env_var_set(self, key):
        val = os.getenv(key)
        assert val is not None, f"Missing env var: {key}"
        assert len(val) > 5, f"Env var {key} looks too short: '{val[:3]}...'"
        # Verify it's not the test fake
        assert "fake" not in val.lower(), f"Env var {key} still has test fake value!"


class TestAliciaPySyntax:
    """Verify alicia.py has valid Python syntax (catches accidental edit damage)."""

    def test_syntax_valid(self):
        import py_compile
        alicia_path = os.path.expanduser("~/alicia/alicia/alicia.py")
        try:
            py_compile.compile(alicia_path, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Syntax error in alicia.py: {e}")
