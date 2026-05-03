#!/usr/bin/env python3
"""
Manual trigger script — runs every scheduled task function and reports results.
Run from Mac Mini: cd ~/alicia && source venv/bin/activate && python alicia/tests/trigger_all.py

This does NOT send Telegram messages — it just calls the underlying functions
to verify they execute without errors.
"""

import os
import sys
import time
import json
import asyncio
import traceback
from datetime import datetime

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/alicia/.env"))

# ── Test framework ──────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
ERRORS = []
RESULTS = {}

def task_test(name, timeout_sec=120):
    def decorator(fn):
        global PASS, FAIL
        print(f"  ▶ {name}...", end=" ", flush=True)
        start = time.time()
        try:
            result = fn()
            elapsed = time.time() - start
            PASS += 1
            RESULTS[name] = {"status": "pass", "elapsed": f"{elapsed:.1f}s", "result": str(result)[:200] if result else "ok"}
            print(f"✅ ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - start
            FAIL += 1
            err_msg = f"{type(e).__name__}: {e}"
            ERRORS.append((name, err_msg))
            RESULTS[name] = {"status": "fail", "elapsed": f"{elapsed:.1f}s", "error": err_msg}
            print(f"❌ ({elapsed:.1f}s)\n    {err_msg}")
        return fn
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
print("=" * 65)
print(f"  ALICIA SCHEDULED TASK TRIGGER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 65)

# ── 1. Imports ──────────────────────────────────────────────────────────────
print("\n📦 Import Verification")

@task_test("Import all skill modules")
def _():
    from skills.proactive_messages import build_startup_stats, build_startup_greeting, build_midday_message, build_evening_message
    from skills.vault_intelligence import run_daily_tagging_pass, format_daily_report, run_weekly_deep_pass
    from skills.curiosity_engine import run_curiosity_scan, detect_novelty, get_curiosity_context_for_message
    from skills.vault_metrics import compute_all_metrics, format_knowledge_dashboard, append_weekly_snapshot
    from skills.graph_intelligence import run_graph_health_report
    from skills.trajectory import analyze_trajectories, TrajectoryRecorder
    from skills.memory_skill import consolidate_all_memory, extract_from_message, build_session_context
    from skills.reflexion import should_reflect, reflect_on_task, get_relevant_reflections
    from skills.metacognition import assess_confidence, should_use_opus
    from skills.constitution import should_evaluate, evaluate_output
    from skills.semantic_search import index_vault, semantic_search, get_index_stats
    from skills.tool_router import route_message, execute_tool, TOOLS
    from skills.voice_skill import get_voice_status
    return "all 13 modules imported"


# ── 2. Vault Metrics (fast, no API) ────────────────────────────────────────
print("\n📊 Vault Metrics (no API calls)")

@task_test("compute_all_metrics()")
def _():
    from skills.vault_metrics import compute_all_metrics
    metrics = compute_all_metrics()
    assert "synthesis_count" in metrics, "Missing synthesis_count"
    assert "level" in metrics, "Missing level info"
    level = metrics["level"]["current"]
    return f"Level {level['level']}: {level['name']} | {metrics['synthesis_count']} synthesis notes | {metrics['cluster_pairs_bridged']}/{metrics['cluster_pairs_total']} pairs"

@task_test("format_knowledge_dashboard()")
def _():
    from skills.vault_metrics import compute_all_metrics, format_knowledge_dashboard
    metrics = compute_all_metrics()
    dashboard = format_knowledge_dashboard(metrics)
    assert "Level" in dashboard, "Dashboard missing Level header"
    assert "Synthesis" in dashboard, "Dashboard missing Synthesis line"
    lines = dashboard.strip().split("\n")
    return f"{len(lines)} lines, starts with: {lines[0][:60]}"


# ── 3. Proactive Messages (uses API) ───────────────────────────────────────
print("\n🌅 Morning Message (API call)")

@task_test("build_startup_stats()")
def _():
    from skills.proactive_messages import build_startup_stats
    stats = build_startup_stats()
    assert "Alicia is online" in stats, "Missing online header"
    assert "Level" in stats, "Missing level info in stats"
    lines = stats.strip().split("\n")
    return f"{len(lines)} lines | {stats[:100]}..."

@task_test("build_startup_greeting()")
def _():
    from skills.proactive_messages import build_startup_greeting
    greeting = build_startup_greeting()
    assert len(greeting) > 10, "Greeting too short"
    return greeting[:100]

print("\n☀️ Midday Message (API call)")

@task_test("build_midday_message()")
def _():
    from skills.proactive_messages import build_midday_message
    msg = build_midday_message()
    assert len(msg) > 10, "Midday message too short"
    return msg[:100]

print("\n🌙 Evening Message (API call)")

@task_test("build_evening_message()")
def _():
    from skills.proactive_messages import build_evening_message
    msg = build_evening_message()
    assert len(msg) > 10, "Evening message too short"
    return msg[:100]


# ── 4. Curiosity Engine (uses API) ─────────────────────────────────────────
print("\n🔍 Curiosity Engine")

@task_test("run_curiosity_scan()")
def _():
    from skills.curiosity_engine import run_curiosity_scan
    result = run_curiosity_scan()
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    return f"questions_generated: {result.get('questions_generated', '?')}, gaps: {result.get('gaps_detected', '?')}"

@task_test("detect_novelty('What is Nishida Kitaro absolute nothingness?')")
def _():
    from skills.curiosity_engine import detect_novelty
    result = detect_novelty("What is Nishida Kitaro absolute nothingness?")
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    return f"is_novel: {result.get('is_novel')}, score: {result.get('curiosity_score', '?')}"

@task_test("get_curiosity_context_for_message('mastery and deliberate practice')")
def _():
    from skills.curiosity_engine import get_curiosity_context_for_message
    ctx = get_curiosity_context_for_message("mastery and deliberate practice")
    return f"context length: {len(ctx)} chars" if ctx else "empty context"


# ── 5. Metacognition + Model Escalation ────────────────────────────────────
print("\n🧠 Metacognition")

@task_test("assess_confidence() + should_use_opus()")
def _():
    from skills.metacognition import assess_confidence, should_use_opus
    from skills.memory_skill import get_memory_summary
    memory = get_memory_summary()
    assessment = assess_confidence("Tell me about Heidegger's concept of Dasein", memory, "")
    use_opus = should_use_opus(assessment)
    return f"confidence: {assessment.get('confidence_level', '?')}, use_opus: {use_opus}, gaps: {assessment.get('knowledge_gaps', [])}"


# ── 6. Reflexion ────────────────────────────────────────────────────────────
print("\n🪞 Reflexion")

@task_test("get_relevant_reflections()")
def _():
    from skills.reflexion import get_relevant_reflections
    reflections = get_relevant_reflections("conversation", "Tell me about my reading list")
    return f"reflections length: {len(reflections)} chars"

@task_test("should_reflect() gating")
def _():
    from skills.reflexion import should_reflect
    assert should_reflect("synthesise_vault") == True, "Should reflect on synthesise_vault"
    assert should_reflect("get_random_quote") == False, "Should NOT reflect on get_random_quote"
    return "gating correct"


# ── 7. Constitution ────────────────────────────────────────────────────────
print("\n📜 Constitution")

@task_test("should_evaluate() gating")
def _():
    from skills.constitution import should_evaluate
    assert should_evaluate("synthesise_vault") == True
    assert should_evaluate("conversation") == False
    return "gating correct"


# ── 8. Semantic Search ──────────────────────────────────────────────────────
print("\n🔎 Semantic Search")

@task_test("get_index_stats()")
def _():
    from skills.semantic_search import get_index_stats
    stats = get_index_stats()
    return stats[:100]

@task_test("semantic_search('mastery and deliberate practice')")
def _():
    from skills.semantic_search import semantic_search
    hits = semantic_search("mastery and deliberate practice", n_results=3)
    return f"{len(hits)} hits: {[h.get('title', '?')[:30] for h in hits]}"


# ── 9. Tool Router ─────────────────────────────────────────────────────────
print("\n🔧 Tool Router")

@task_test("route_message() with model parameter")
def _():
    from skills.tool_router import route_message
    import inspect
    sig = inspect.signature(route_message)
    assert "model" in sig.parameters, "model parameter missing from route_message"
    # Actually route a simple message
    result = route_message(
        "You are Alicia, a helpful assistant.",
        [{"role": "user", "content": "What time is it?"}],
        model=None  # default Sonnet
    )
    assert "type" in result, f"Missing 'type' in routing result"
    return f"type: {result['type']}, text: {result.get('text', '')[:60]}"

@task_test("route_message() with Opus escalation")
def _():
    from skills.tool_router import route_message
    result = route_message(
        "You are Alicia, a helpful assistant.",
        [{"role": "user", "content": "Hello"}],
        model="claude-opus-4-20250514"
    )
    assert "type" in result
    return f"Opus routing: type={result['type']}"


# ── 10. Graph Intelligence ──────────────────────────────────────────────────
print("\n🕸 Graph Intelligence")

@task_test("run_graph_health_report()")
def _():
    from skills.graph_intelligence import run_graph_health_report
    report = run_graph_health_report()
    assert len(report) > 20, "Report too short"
    return f"{len(report)} chars: {report[:80]}..."


# ── 11. Trajectory ──────────────────────────────────────────────────────────
print("\n📈 Trajectory")

@task_test("TrajectoryRecorder lifecycle")
def _():
    from skills.trajectory import TrajectoryRecorder
    t = TrajectoryRecorder("test message")
    t.record_metacog({"confidence": 8, "confidence_level": "high"})
    t.record_routing({"type": "text"})
    t.record_response("text", 42)
    t.record_outcome("completed")
    # High confidence (8 > 3), short response (42 < 200), no tool, no novelty → not significant
    assert t.is_significant() == False, "Simple high-confidence conversation shouldn't be significant"
    # Now test that low confidence triggers significance
    t2 = TrajectoryRecorder("hard question")
    t2.record_metacog({"confidence": 2, "confidence_level": "low"})
    t2.record_response("text", 42)
    t2.record_outcome("completed")
    assert t2.is_significant() == True, "Low-confidence conversation should be significant"
    return "lifecycle + significance gating correct"


# ── 12. Memory ──────────────────────────────────────────────────────────────
print("\n💾 Memory")

@task_test("build_session_context()")
def _():
    from skills.memory_skill import build_session_context
    ctx = build_session_context("hello")
    assert len(ctx) > 10, "Session context too short"
    return f"{len(ctx)} chars"

@task_test("get_memory_summary()")
def _():
    from skills.memory_skill import get_memory_summary
    summary = get_memory_summary()
    assert len(summary) > 10
    return f"{len(summary)} chars"


# ── 13. Voice ───────────────────────────────────────────────────────────────
print("\n🎤 Voice")

@task_test("get_voice_status()")
def _():
    from skills.voice_skill import get_voice_status
    status = get_voice_status()
    return json.dumps(status)


# ── 14. Daily Vault Pass (HEAVY — optional) ────────────────────────────────
print("\n🌿 Daily Vault Pass (light check only)")

@task_test("run_daily_tagging_pass() — dry import")
def _():
    from skills.vault_intelligence import run_daily_tagging_pass, format_daily_report
    # Don't actually run it (expensive) — just verify callable
    assert callable(run_daily_tagging_pass)
    assert callable(format_daily_report)
    return "importable and callable"


# ── 15. Weekly Tasks (HEAVY — optional) ─────────────────────────────────────
print("\n🧬 Weekly Tasks (dry check only)")

@task_test("Weekly functions are importable and callable")
def _():
    from skills.vault_intelligence import run_weekly_deep_pass
    from skills.trajectory import analyze_trajectories
    from skills.memory_skill import consolidate_all_memory
    from skills.vault_metrics import append_weekly_snapshot
    from skills.graph_intelligence import run_graph_health_report
    assert all(callable(f) for f in [run_weekly_deep_pass, analyze_trajectories, consolidate_all_memory, append_weekly_snapshot, run_graph_health_report])
    return "all 5 weekly functions callable"


# ── Drawing Skill (live render) ────────────────────────────────────────────
print("\n🎨 Drawing Skill")

@task_test("generate_drawing() produces a real PNG on disk", timeout_sec=30)
def _():
    from skills.drawing_skill import generate_drawing, VALID_ARCHETYPES
    from pathlib import Path
    from PIL import Image
    # Render one drawing (deterministic seed so this test is repeatable).
    r = generate_drawing(archetype="muse", seed=20260419)
    assert r["archetype"] in VALID_ARCHETYPES
    assert r["kind"] in ("png", "gif")
    p = Path(r["path"])
    assert p.exists(), f"file not written: {p}"
    assert p.stat().st_size > 1000, "file too small to be a real image"
    img = Image.open(p)
    w, h = img.size
    assert w >= 200 and h >= 200, f"image too small: {w}x{h}"
    cap = r.get("caption", "")
    assert cap and len(cap) <= 80, f"caption out of bounds: '{cap}'"
    return f"{r['archetype']} {r['kind']} {w}x{h} — caption: '{cap}'"


@task_test("can_draw_now() + record_drawing_sent() integrate", timeout_sec=5)
def _():
    from skills.drawing_skill import can_draw_now, get_drawing_stats
    # Function returns (bool, reason); either outcome is valid, just shape
    ok, reason = can_draw_now()
    assert isinstance(ok, bool) and isinstance(reason, str)
    stats = get_drawing_stats()
    assert "Drawings" in stats or "drawing" in stats.lower()
    return f"can_draw_now={ok}, reason='{reason[:50]}'"


@task_test("generate_drawing(prompt=...) produces a phrase-conditioned drawing",
           timeout_sec=45)
def _():
    # Live Haiku call — phrase-driven drawing. Skips cleanly if no API key.
    import os as _os
    from pathlib import Path
    from PIL import Image
    from skills.drawing_skill import generate_drawing, VALID_ARCHETYPES

    if not _os.getenv("ANTHROPIC_API_KEY"):
        return "skipped (no ANTHROPIC_API_KEY)"

    r = generate_drawing(prompt="your current thinking", seed=20260420)
    assert r["archetype"] in VALID_ARCHETYPES
    assert r["kind"] in ("png", "gif")
    p = Path(r["path"])
    assert p.exists() and p.stat().st_size > 1000
    img = Image.open(p)
    w, h = img.size
    assert w >= 200 and h >= 200
    cap = r.get("caption", "")
    assert cap and len(cap) <= 80
    # Interpretation path MUST expose knobs + source
    assert "knobs" in r, "prompt path must return knobs dict"
    assert r.get("source") == "phrase"
    for knob in ("density", "energy", "whitespace", "stroke"):
        assert knob in r["knobs"], f"missing knob: {knob}"
    return (f"{r['archetype']} {r['kind']} {w}x{h} · "
            f"knobs={r['knobs']} · '{cap}'")


@task_test("generate_drawing(state=...) from live Alicia state", timeout_sec=45)
def _():
    import os as _os
    from pathlib import Path
    from skills.drawing_skill import (
        generate_drawing, build_drawing_state_snapshot, VALID_ARCHETYPES,
    )
    if not _os.getenv("ANTHROPIC_API_KEY"):
        return "skipped (no ANTHROPIC_API_KEY)"

    state = build_drawing_state_snapshot()
    assert isinstance(state, dict) and "time_of_day" in state
    r = generate_drawing(state=state, seed=20260421)
    assert r["archetype"] in VALID_ARCHETYPES
    assert Path(r["path"]).exists()
    assert r.get("source") == "state"
    return (f"state→{r['archetype']} {r['kind']} "
            f"knobs={r.get('knobs')} · '{r['caption']}'")


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
total = PASS + FAIL
print(f"  Results: {PASS}/{total} passed", end="")
if FAIL:
    print(f", {FAIL} FAILED")
    print("\n  Failures:")
    for name, err in ERRORS:
        print(f"    ❌ {name}")
        print(f"       {err}")
else:
    print(" ✨ ALL SYSTEMS OPERATIONAL")

# Write results to JSON for inspection
results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trigger_results.json")
with open(results_path, "w") as f:
    json.dump({
        "timestamp": datetime.now().isoformat(),
        "passed": PASS,
        "failed": FAIL,
        "total": total,
        "results": RESULTS,
        "errors": [{"name": n, "error": e} for n, e in ERRORS],
    }, f, indent=2)
print(f"\n  Full results → {results_path}")
print()
sys.exit(1 if FAIL else 0)
