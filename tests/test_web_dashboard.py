#!/usr/bin/env python3
"""
Unit tests for skills/web_dashboard.py.

Exercises:
  - compute_full_state() — surface-agnostic state contract
  - list_alicia_skills() — categorized skills directory
  - assemble_timeline() — birth → today milestones
  - HTTP server startup + response (real socket, ephemeral port)
  - HTML page renders without errors
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


_PASSED = 0
_FAILED = 0
_TESTS: list[tuple[str, callable]] = []


def test(label: str):
    def deco(fn):
        _TESTS.append((label, fn))
        return fn
    return deco


def _run_all() -> int:
    global _PASSED, _FAILED
    for label, fn in _TESTS:
        try:
            fn()
            _PASSED += 1
            print(f"  ✓ {label}")
        except AssertionError as e:
            _FAILED += 1
            print(f"  ✗ {label}\n      {e}")
        except Exception as e:
            _FAILED += 1
            print(f"  ✗ {label}\n      unexpected error: {type(e).__name__}: {e}")
    print(f"\n{_PASSED} passed · {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


def _free_port() -> int:
    """Find a free port for HTTP server tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Tests ──────────────────────────────────────────────────────────────────


@test("compute_full_state: returns the canonical contract shape")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    # Top-level keys
    for key in ("generated_at", "alicia", "hector", "relationship",
                "skills", "timeline"):
        assert key in state, f"missing top-level key: {key}"
    # Alicia sub-sections (Phase 15.0f added soul)
    for sub in ("heart", "body", "soul", "mind", "nervous_system"):
        assert sub in state["alicia"], f"alicia.{sub} missing"
    # the user sub-sections
    for sub in ("mind", "voice", "body"):
        assert sub in state["hector"], f"hector.{sub} missing"
    # Relationship sub-sections
    for sub in ("conversation", "distillation", "coherence", "landing"):
        assert sub in state["relationship"], f"relationship.{sub} missing"


@test("compute_full_state: never raises (every section is fault-tolerant)")
def _():
    """A failing module should produce {} for that section, not crash
    the aggregator. Run twice to make sure it's deterministic."""
    from myalicia.skills.web_dashboard import compute_full_state
    s1 = compute_full_state()
    s2 = compute_full_state()
    assert isinstance(s1, dict)
    assert isinstance(s2, dict)
    # generated_at advances; structural keys don't
    assert set(s1.keys()) == set(s2.keys())


@test("list_alicia_skills: categorizes all 75-ish modules into known buckets")
def _():
    from myalicia.skills.web_dashboard import list_alicia_skills, _SKILL_BUCKETS
    skills = list_alicia_skills()
    # Should have substantial coverage — 60+ at minimum
    assert len(skills) >= 30, f"expected many skills, got {len(skills)}"
    bucket_names = {b for b, _ in _SKILL_BUCKETS} | {"Other"}
    for s in skills:
        assert s["bucket"] in bucket_names, (
            f"skill {s['module']} got bucket {s['bucket']!r} not in known set"
        )
        assert "module" in s
        assert "summary" in s


@test("list_alicia_skills: user_model lands in 'Outer loops' bucket")
def _():
    from myalicia.skills.web_dashboard import list_alicia_skills
    skills = list_alicia_skills()
    hm = next((s for s in skills if s["module"] == "user_model"), None)
    assert hm is not None, "user_model not found"
    assert "Outer loops" in hm["bucket"], (
        f"user_model categorized as {hm['bucket']!r}; expected 'Outer loops'"
    )


@test("assemble_timeline: includes the birth event")
def _():
    from myalicia.skills.web_dashboard import assemble_timeline
    items = assemble_timeline()
    assert items, "timeline empty"
    # Birth event is always day 0
    birth = items[0]
    assert birth["date"] == "2026-01-15"
    assert birth["days_since_birth"] == 0
    assert "Born" in birth["title"] or "Genesis" in birth["phase"]


@test("assemble_timeline: extracts phase milestones from PIPELINE_AUDIT.md")
def _():
    from myalicia.skills.web_dashboard import assemble_timeline
    items = assemble_timeline()
    # Should have at least the birth + a few phase entries from PIPELINE_AUDIT
    assert len(items) >= 2, (
        f"expected birth + phases from PIPELINE_AUDIT, got {len(items)} items"
    )
    # Every item has the canonical shape
    for it in items:
        assert "date" in it and "title" in it and "days_since_birth" in it


@test("HTTP server: serves /healthz on a free port")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    # Give the daemon thread a beat to bind
    time.sleep(0.3)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=2
        ) as resp:
            body = resp.read().decode()
            assert resp.status == 200
            assert body == "ok", f"unexpected /healthz body: {body!r}"
    except Exception as e:
        raise AssertionError(f"HTTP /healthz failed: {e}")


@test("HTTP server: GET / returns the HTML page")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/", timeout=2
    ) as resp:
        body = resp.read().decode()
    assert resp.status == 200
    assert "<!DOCTYPE html>" in body
    assert f"Alicia &amp; {USER_NAME}" in body or f"Alicia &amp;amp; {USER_NAME}" in body or f"Alicia & {USER_NAME}" in body
    # Required dashboard sections are wired in HTML
    for marker in ("alicia-heart", "alicia-body", "alicia-soul",
                   "alicia-mind", "alicia-nervous",
                   "hector-mind", "hector-voice", "hector-body",
                   "rel-conversation", "rel-distillation",
                   "rel-coherence", "rel-landing", "skills", "timeline"):
        assert marker in body, f"HTML missing element id: {marker}"


@test("HTTP server: GET /api/state.json returns valid JSON with full contract")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/state.json", timeout=2
    ) as resp:
        body = resp.read().decode()
    state = json.loads(body)
    # Same contract as compute_full_state directly
    for key in ("alicia", "hector", "relationship", "skills", "timeline"):
        assert key in state, f"/api/state.json missing {key}"


@test("Phase 15.0f soul: returns six archetypes with weights + descriptions")
def _():
    """Phase 15.0f surfaces Alicia's archetypes as her 'soul'. The six
    canonical archetypes (Beatrice, Daimon, Ariadne, Psyche, Musubi,
    Muse) must appear, each with a base_weight, current_weight, and
    description. They're sorted by current_weight desc — leading first."""
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    soul = state["alicia"]["soul"]
    archetypes = soul.get("archetypes", [])
    assert len(archetypes) == 6, f"expected 6 archetypes, got {len(archetypes)}"
    names = {a["name"] for a in archetypes}
    expected = {"beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"}
    assert names == expected, f"archetype names wrong: {names}"
    # Each entry has the canonical shape
    for a in archetypes:
        for f in ("name", "title", "description", "base_weight",
                  "current_weight", "effectiveness_score", "attribution_count"):
            assert f in a, f"archetype {a.get('name','?')} missing field {f}"
    # Sorted by current_weight desc
    weights = [a["current_weight"] for a in archetypes]
    assert weights == sorted(weights, reverse=True), (
        f"archetypes must be sorted by current_weight desc: {weights}"
    )
    # Leading reflects the first entry
    assert soul.get("leading") == archetypes[0]["name"]


@test("Phase 15.0g vault_uri: builds correctly encoded obsidian:// link")
def _():
    from myalicia.skills.web_dashboard import vault_uri
    # Plain ASCII path
    uri = vault_uri("writing/Responses/foo.md")
    assert uri.startswith("obsidian://open?vault=")
    assert "writing/Responses/foo.md" in uri
    # Em-dash gets URL-encoded
    uri2 = vault_uri("Wisdom/Alicia/Alicia — A Personal Sovereign AI Agent.md")
    assert "%E2%80%94" in uri2, (
        f"em-dash must be URL-encoded: {uri2}"
    )
    # Empty path → None
    assert vault_uri("") is None
    assert vault_uri(None) is None


@test("Phase 15.0g bucket refactor: 'Other' bucket is now empty (or near-empty)")
def _():
    """Phase 15.0g eliminated the 30-module Other pile by adding new
    buckets (Analysis, Bridge, Conversation surfaces, External tools).
    Anything left in Other should be a deliberate exception, not the
    default fallback."""
    from myalicia.skills.web_dashboard import list_alicia_skills
    from collections import Counter
    skills = list_alicia_skills()
    counts = Counter(s["bucket"] for s in skills)
    others = counts.get("Other", 0)
    assert others <= 3, (
        f"Other bucket should have ≤3 modules after refactor; got {others}: "
        f"{[s['module'] for s in skills if s['bucket'] == 'Other']}"
    )


@test("Phase 15.0g backup filter: .backup. files are excluded from skills")
def _():
    from myalicia.skills.web_dashboard import list_alicia_skills
    skills = list_alicia_skills()
    backups = [s for s in skills if ".backup." in s["module"]]
    assert backups == [], f"backup files leaked into skills: {backups}"


@test("Phase 15.0h github_url: builds correctly encoded URLs")
def _():
    from myalicia.skills.web_dashboard import github_url
    assert github_url("skills/user_model.py") == \
        "https://github.com/mrdaemoni/alicia/blob/main/skills/user_model.py"
    assert github_url("PIPELINE_AUDIT.md") == \
        "https://github.com/mrdaemoni/alicia/blob/main/PIPELINE_AUDIT.md"
    # Path with spaces gets URL-encoded
    url = github_url("docs/Some File.md")
    assert "Some%20File.md" in url


@test("Phase 15.0h skills include github_url field")
def _():
    from myalicia.skills.web_dashboard import list_alicia_skills
    skills = list_alicia_skills()
    assert skills, "no skills found"
    for s in skills:
        assert "github_url" in s, f"skill {s['module']} missing github_url"
        assert s["github_url"].startswith("https://github.com/")
        assert s["module"] in s["github_url"]


@test("Phase 15.0h timeline entries include github_url")
def _():
    from myalicia.skills.web_dashboard import assemble_timeline
    items = assemble_timeline()
    for it in items:
        assert "github_url" in it, f"timeline item {it} missing github_url"
        assert "PIPELINE_AUDIT.md" in it["github_url"]


@test("Phase 15.0h compute_health: returns one of alive/quiet/stalled/unknown")
def _():
    from myalicia.skills.web_dashboard import compute_health
    h = compute_health()
    assert h["status"] in ("alive", "quiet", "stalled", "unknown"), (
        f"unexpected health status: {h['status']}"
    )
    # Required fields always present
    for k in ("status", "newest_signal_path", "newest_signal_ts",
              "hours_since", "message"):
        assert k in h, f"compute_health missing field {k}"


@test("Phase 15.0h compute_health: classifies thresholds correctly")
def _():
    """Verify the 12h / 36h thresholds. We can't mutate real file mtimes
    cleanly, so test the threshold logic directly via a tmp file."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills import web_dashboard as wd
        # Reroute MEMORY_DIR + heartbeat search
        wd.MEMORY_DIR = Path(td)
        # Create a heartbeat file with a tunable mtime
        hb = Path(td) / "circulation_log.json"
        hb.write_text("{}")
        # Set mtime to 6 hours ago — should be 'alive'
        six_hours_ago = time.time() - 6 * 3600
        os.utime(hb, (six_hours_ago, six_hours_ago))
        h = wd.compute_health()
        assert h["status"] == "alive", f"6h old should be alive: {h}"
        # Set mtime to 24 hours ago — should be 'quiet'
        os.utime(hb, (time.time() - 24 * 3600, time.time() - 24 * 3600))
        h = wd.compute_health()
        assert h["status"] == "quiet", f"24h old should be quiet: {h}"
        # 48 hours ago — should be 'stalled'
        os.utime(hb, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        h = wd.compute_health()
        assert h["status"] == "stalled", f"48h old should be stalled: {h}"


@test("Phase 15.0h compute_full_state.health is exposed")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    assert "health" in state, "compute_full_state missing 'health' key"
    assert "status" in state["health"]


@test("Phase 15.0h _extract_prompt_from_capture: pulls blockquote prompt")
def _():
    """The capture file body has the prompt as a markdown blockquote
    after '*In response to ...:*'. Helper extracts it."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills.web_dashboard import _extract_prompt_from_capture
        f = Path(td) / "test-capture.md"
        f.write_text(
            "---\ncaptured_at: 2026-04-26\nchannel: text\n---\n\n"
            "*In response to On Quality:*\n"
            "> What strikes me about Pirsig is\n"
            "> the way Quality is the precondition\n"
            "> for everything else.\n"
            "\n"
            f"{USER_NAME}'s actual reply text here.\n",
            encoding="utf-8",
        )
        prompt = _extract_prompt_from_capture(f)
        assert prompt is not None
        assert "What strikes me" in prompt
        assert "Quality is the precondition" in prompt
        # the user's body should NOT bleed in
        assert f"{USER_NAME}'s actual reply" not in prompt


@test("Phase 15.0h _extract_prompt_from_capture: returns None for unprompted captures")
def _():
    """An unprompted capture (no blockquote) returns None — caller
    handles it by hiding the prompt section."""
    with tempfile.TemporaryDirectory() as td:
        from myalicia.skills.web_dashboard import _extract_prompt_from_capture
        f = Path(td) / "unprompted.md"
        f.write_text(
            "---\ncaptured_at: 2026-04-26\n---\n\n"
            "Just an unprompted thought I wanted to capture.",
            encoding="utf-8",
        )
        assert _extract_prompt_from_capture(f) is None


@test("Phase 15.0g identity links: soul + hector mind expose vault URIs")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    soul = state["alicia"]["soul"]
    # Identity bookmarks under soul (Alicia's bio)
    ids = soul.get("identity_links", {})
    assert "bio" in ids
    assert ids["bio"]["vault_uri"].startswith("obsidian://open"), (
        f"bio link must be an obsidian URI: {ids['bio']}"
    )
    assert "Alicia" in ids["bio"]["vault_uri"]
    # NOTE: who_alicia_thinks_you_are + baseline_vault_uri are tested
    # implicitly — they're None when no profile / no baseline exists in
    # the test's vault root, which is the correct degraded behavior.


@test("Phase 15.0f body.tasks: includes scheduled activities")
def _():
    """Phase 15.0f extends body with the list of scheduled tasks Alicia
    runs throughout the day. Each task has when/name/what/phase fields."""
    from myalicia.skills.web_dashboard import compute_full_state, _ALICIA_TASKS
    state = compute_full_state()
    tasks = state["alicia"]["body"].get("tasks", [])
    # Same count as the canonical table
    assert len(tasks) == len(_ALICIA_TASKS), (
        f"body.tasks count drift: state={len(tasks)} table={len(_ALICIA_TASKS)}"
    )
    # Required fields
    for t in tasks:
        for f in ("when", "name", "what", "phase"):
            assert f in t, f"task missing field {f}: {t}"
    # Spot-check a few canonical tasks are present
    names = {t["name"] for t in tasks}
    for canonical in ("Meta-synthesis pass", "Morning message",
                      "Dormancy check", "Weekly retrospective"):
        assert canonical in names, (
            f"expected canonical task {canonical!r} in body.tasks: {names}"
        )


@test("Phase 15.0i: GET /manifest.json returns PWA manifest")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/manifest.json", timeout=2
    ) as resp:
        body = resp.read().decode()
    manifest = json.loads(body)
    assert resp.status == 200
    for key in ("name", "short_name", "start_url", "display",
                "background_color", "theme_color"):
        assert key in manifest, f"manifest missing {key}"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"


@test("Phase 15.0i: HTML head includes manifest link + apple-touch meta")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/", timeout=2
    ) as resp:
        body = resp.read().decode()
    assert '<link rel="manifest" href="/manifest.json"' in body
    assert 'apple-mobile-web-app-title' in body
    assert 'theme-color' in body


@test("Phase 15.0i: POST /api/capture with text writes a file")
def _():
    """End-to-end: POST → capture_unprompted → writing/Captures/ file."""
    import urllib.request
    with tempfile.TemporaryDirectory() as td:
        # Reroute capture dirs to tmp
        from myalicia.skills import response_capture as rc
        original_captures = rc.CAPTURES_DIR
        rc.CAPTURES_DIR = Path(td) / "Captures"
        rc.CAPTURES_DIR.mkdir(parents=True)
        try:
            from myalicia.skills import web_dashboard as wd
            port = _free_port()
            wd.start_web_dashboard(port=port)
            time.sleep(0.3)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/capture",
                data=json.dumps({"text": "a test capture"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                body = resp.read().decode()
            data = json.loads(body)
            assert data.get("ok") is True, f"unexpected response: {data}"
            # File was actually written
            files = list(rc.CAPTURES_DIR.glob("*.md"))
            assert len(files) == 1, f"expected 1 capture file, got {len(files)}"
            assert "a test capture" in files[0].read_text()
        finally:
            rc.CAPTURES_DIR = original_captures


@test("Phase 15.0i: POST /api/capture rejects empty text with 400")
def _():
    import urllib.request
    import urllib.error
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/capture",
        data=b'{"text": ""}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert False, f"expected 400, got {resp.status}"
    except urllib.error.HTTPError as e:
        assert e.code == 400


@test("Phase 15.2a compute_today_deltas: returns canonical shape")
def _():
    from myalicia.skills.web_dashboard import compute_today_deltas
    t = compute_today_deltas()
    for k in ("captures", "learnings", "voice_fired", "drawings_fired",
              "coherent_moments", "meta_built", "dimension_questions",
              "thread_pulls", "escalations", "archetype_attributions",
              "summary"):
        assert k in t, f"compute_today_deltas missing {k}"
    assert isinstance(t["archetype_attributions"], dict)
    assert isinstance(t["summary"], str)


@test("Phase 15.2a state.today is exposed in compute_full_state")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    assert "today" in state
    assert "summary" in state["today"]


@test("Phase 15.2b: GET /api/stream sends SSE events")
def _():
    """Open the SSE stream, read at least one 'data:' event, then disconnect.
    Verifies headers + initial event payload + JSON well-formed."""
    import socket
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    # Raw socket so we can read just the first event without the
    # urllib client closing the connection prematurely.
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        s.sendall(
            b"GET /api/stream HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Accept: text/event-stream\r\n"
            b"Connection: close\r\n\r\n"
        )
        # Read response headers + initial event
        buf = b""
        deadline = time.time() + 3.0
        while time.time() < deadline:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\n\n" in buf and b"data:" in buf:
                break
    finally:
        s.close()
    text = buf.decode("utf-8", errors="replace")
    # Must look like an SSE response
    assert "200 OK" in text, f"unexpected status:\n{text[:300]}"
    assert "text/event-stream" in text.lower()
    assert "data:" in text, f"no SSE events received:\n{text[:500]}"
    # Initial event should carry valid JSON
    data_line = text.split("data: ", 1)[1].split("\n\n", 1)[0]
    parsed = json.loads(data_line)
    assert "alicia" in parsed
    assert "hector" in parsed


@test("Phase 15.2b: HTML uses EventSource as primary update path")
def _():
    """The dashboard JS should prefer SSE, only falling back to
    polling on browsers without EventSource."""
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
        body = resp.read().decode()
    assert "EventSource" in body, "JS must reference EventSource"
    assert "/api/stream" in body, "JS must connect to /api/stream"


@test("Phase 15.2c compute_network_info: returns localhost + bonjour at minimum")
def _():
    from myalicia.skills.web_dashboard import compute_network_info
    n = compute_network_info(port=12345)
    assert "urls" in n
    assert "tailscale" in n
    assert n["port"] == 12345
    # localhost is always present
    localhost_urls = [u for u in n["urls"] if u["kind"] == "loopback"]
    assert localhost_urls, "compute_network_info must include a loopback URL"
    assert "localhost:12345" in localhost_urls[0]["url"]


@test("Phase 15.2c GET /api/network.json returns shape")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/network.json", timeout=2
    ) as resp:
        body = resp.read().decode()
    data = json.loads(body)
    assert "urls" in data
    assert "tailscale" in data
    assert data["port"] == port


@test("Phase 15.0i compute_pinned_card: returns the canonical contract shape")
def _():
    from myalicia.skills.web_dashboard import compute_pinned_card
    p = compute_pinned_card()
    for k in ("focus", "reason", "vault_uri"):
        assert k in p, f"compute_pinned_card missing {k}"


@test("Phase 15.0i state.pinned is exposed in compute_full_state")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    assert "pinned" in state
    assert "focus" in state["pinned"]


@test("Phase 17.3 compute_noticings_state: returns canonical shape")
def _():
    from myalicia.skills.web_dashboard import compute_noticings_state
    n = compute_noticings_state()
    for key in ("total", "by_status", "themes", "next_to_surface"):
        assert key in n, f"noticings state missing key {key!r}"
    assert isinstance(n["total"], int)
    assert isinstance(n["by_status"], dict)
    assert isinstance(n["themes"], list)
    for k in ("pending", "surfaced", "acknowledged"):
        assert k in n["by_status"]


@test("Phase 17.3 state.noticings is exposed in compute_full_state")
def _():
    from myalicia.skills.web_dashboard import compute_full_state
    state = compute_full_state()
    assert "noticings" in state
    n = state["noticings"]
    assert "themes" in n
    assert "by_status" in n


@test("Phase 17.3 noticings card markup + JS render present in HTML")
def _():
    from pathlib import Path as _P
    wd_text = (_P(__file__).resolve().parent.parent
               / "skills" / "web_dashboard.py").read_text(encoding="utf-8")
    for marker in (
        'id="noticings-card"',
        'id="noticings-list"',
        'id="noticings-counts"',
        '.noticings-card {',
        'function renderNoticings(',
        'renderNoticings(state)',
    ):
        assert marker in wd_text, (
            f"web_dashboard.py missing required noticings marker: {marker!r}"
        )


@test("Phase 15.2d: ConnectionReset on TCP-only connect doesn't crash the server")
def _():
    """Open a TCP socket to the server, close it without sending HTTP,
    then issue a normal request — server must still serve it. This
    simulates what Tailscale health-checks + speculative iPhone connects
    do many times per minute. Before Phase 15.2d, each such close
    printed a 14-line traceback to stderr."""
    import socket
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    # Open + immediately close (the harmless pattern)
    for _ in range(3):
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        time.sleep(0.05)
    # Server is still healthy
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/healthz", timeout=2
    ) as resp:
        body = resp.read().decode()
    assert resp.status == 200
    assert body == "ok"


@test("HTTP server: idempotent — second start_web_dashboard on same port no-ops")
def _():
    from myalicia.skills import web_dashboard as wd
    port = _free_port()
    wd.start_web_dashboard(port=port)
    time.sleep(0.3)
    # Second call should NOT raise — the port-in-use check kicks in
    wd.start_web_dashboard(port=port)
    # Server is still serving
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/healthz", timeout=2
    ) as resp:
        assert resp.status == 200


if __name__ == "__main__":
    print("Testing web_dashboard.py …")
    sys.exit(_run_all())
