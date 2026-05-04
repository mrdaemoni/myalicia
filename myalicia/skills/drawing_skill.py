"""
skills/drawing_skill.py — Alicia's visual voice.

A topographic flow-field renderer that gives Alicia a way to *draw* what she's
feeling — a frame from a dynamic script mapped through her current archetype.
Lines follow an invisible flow field, clustering around attractors, dispersing
at edges. Cream paper, dark ink, hand-drawn feel. Pure abstract field — the
subject is the flow itself.

Public API
----------
    generate_drawing(archetype=None, force_gif=False, seed=None) -> dict
        Renders one PNG (or GIF) for the given archetype. If archetype is None,
        picks the current dominant archetype from inner_life. Returns:
            {
              "path": "/abs/path/to/drawing.png",
              "archetype": "beatrice",
              "caption": "<poetic one-liner>",
              "kind": "png" | "gif",
              "seed": 12345,
            }

    can_draw_now() -> tuple[bool, str]
        Throttle gate — drawings are precious. Returns (ok, reason).

    record_drawing_sent(path: str, archetype: str) -> None
        Persist the timestamp so can_draw_now() respects cadence.

Rule 3 wiring: imported in alicia.py, called from send_drawing_impulse()
(scheduled) and the muse/surprise fallback. Rule 8 applies — judgment lives in
skills/configs/drawing_skill.md (caption voice, cadence, GIF probability).
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from myalicia.config import config, ALICIA_HOME
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths + constants
# ─────────────────────────────────────────────────────────────────────────────

ALICIA_ROOT = ALICIA_HOME
DRAWINGS_DIR = ALICIA_ROOT / "memory" / "drawings"
DRAWING_LOG = ALICIA_ROOT / "memory" / "drawing_log.jsonl"
DRAWINGS_DIR.mkdir(parents=True, exist_ok=True)

PAPER = (240, 238, 230)
INK = (30, 30, 28)

# Throttle defaults — overridable via skill config at load time
MIN_HOURS_BETWEEN = 4.0
MAX_PER_DAY = 4
GIF_PROBABILITY = 0.15     # "PNG usually, GIF sometimes"
VALID_ARCHETYPES = {"beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"}

# Try to load overrides from the skill config if present
try:
    from myalicia.skills.skill_config import load_config
    _cfg = load_config("drawing_skill") or {}
    _p = _cfg.get("parameters", {}) if isinstance(_cfg, dict) else {}
    MIN_HOURS_BETWEEN = float(_p.get("min_hours_between", MIN_HOURS_BETWEEN))
    MAX_PER_DAY = int(_p.get("max_per_day", MAX_PER_DAY))
    GIF_PROBABILITY = float(_p.get("gif_probability", GIF_PROBABILITY))
except Exception as _e:
    log.debug(f"drawing_skill config load skipped: {_e}")

# ─────────────────────────────────────────────────────────────────────────────
# Noise
# ─────────────────────────────────────────────────────────────────────────────

def _lerp(a, b, t):
    return a + (b - a) * t


def _smoothstep(t):
    return t * t * (3 - 2 * t)


def _value_noise_2d(shape: tuple[int, int], scale: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gh = max(2, int(shape[0] / scale) + 2)
    gw = max(2, int(shape[1] / scale) + 2)
    grid = rng.uniform(-1.0, 1.0, size=(gh, gw))
    ys = np.linspace(0, gh - 1.001, shape[0])
    xs = np.linspace(0, gw - 1.001, shape[1])
    y0 = ys.astype(int)
    x0 = xs.astype(int)
    ty = _smoothstep(ys - y0)
    tx = _smoothstep(xs - x0)
    c00 = grid[y0[:, None], x0[None, :]]
    c10 = grid[y0[:, None] + 1, x0[None, :]]
    c01 = grid[y0[:, None], x0[None, :] + 1]
    c11 = grid[y0[:, None] + 1, x0[None, :] + 1]
    top = _lerp(c00, c01, tx[None, :])
    bot = _lerp(c10, c11, tx[None, :])
    return _lerp(top, bot, ty[:, None])


def _fbm_2d(shape: tuple[int, int], base_scale: float, octaves: int, seed: int,
            persistence: float = 0.55) -> np.ndarray:
    out = np.zeros(shape, dtype=np.float64)
    amp = 1.0
    total_amp = 0.0
    for o in range(octaves):
        out += amp * _value_noise_2d(shape, base_scale / (2 ** o),
                                     seed + o * 17)
        total_amp += amp
        amp *= persistence
    return out / max(total_amp, 1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Flow-field primitives
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Attractor:
    kind: str
    cx: float
    cy: float
    strength: float = 1.0
    radius: float = 0.3
    angle: float = 0.0


def _attractor_vector_field(shape, attractors):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    yy /= h
    xx /= w
    cx_acc = np.zeros(shape)
    cy_acc = np.zeros(shape)
    for a in attractors:
        dx = xx - a.cx
        dy = yy - a.cy
        r2 = dx * dx + dy * dy
        influence = np.exp(-r2 / (2 * (a.radius ** 2) + 1e-8)) * a.strength
        if a.kind == "sink":
            ang = np.arctan2(-dy, -dx)
        elif a.kind == "source":
            ang = np.arctan2(dy, dx)
        elif a.kind == "swirl":
            ang = np.arctan2(-dx, dy)
        elif a.kind == "radial":
            ang = np.arctan2(dy, dx)
            influence *= np.exp(-r2 / (2 * (a.radius * 0.4) ** 2 + 1e-8))
        elif a.kind == "edge":
            ang = np.full(shape, a.angle, dtype=np.float64)
        else:
            continue
        cx_acc += np.cos(ang) * influence
        cy_acc += np.sin(ang) * influence
    return cx_acc, cy_acc


def _density_field(shape, attractors, base, seed, vignette=None):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    yy /= h
    xx /= w
    density = np.full(shape, base, dtype=np.float64)
    for a in attractors:
        dx = xx - a.cx
        dy = yy - a.cy
        r2 = dx * dx + dy * dy
        density += np.exp(-r2 / (2 * (a.radius * 0.7) ** 2 + 1e-8)) * a.strength * 0.75
    density += 0.30 * _fbm_2d(shape, base_scale=120, octaves=3, seed=seed + 99)

    if vignette is not None:
        kind = vignette.get("kind")
        if kind == "radial":
            cx = vignette.get("cx", 0.5); cy = vignette.get("cy", 0.5)
            rad = vignette.get("radius", 0.4); falloff = vignette.get("falloff", 2.0)
            r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            density *= (0.10 + 0.95 * np.exp(-((r / rad) ** falloff)))
        elif kind == "horizontal":
            cy = vignette.get("cy", 0.5); bw = vignette.get("bandwidth", 0.35)
            density *= (0.10 + 0.95 * np.exp(-((yy - cy) / bw) ** 2))
        elif kind == "diagonal":
            cx = vignette.get("cx", 0.5); cy = vignette.get("cy", 0.5)
            ang = vignette.get("angle", math.pi / 4); bw = vignette.get("bandwidth", 0.30)
            sd = (xx - cx) * math.sin(ang) - (yy - cy) * math.cos(ang)
            density *= (0.10 + 0.95 * np.exp(-(sd / bw) ** 2))
        elif kind == "asymmetric":
            cx = vignette.get("cx", 0.55); cy = vignette.get("cy", 0.45)
            rx = vignette.get("rx", 0.30); ry = vignette.get("ry", 0.35)
            r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            density *= (0.08 + 0.95 * np.exp(-(r ** 2.2)))

    edge_fade = np.minimum(
        np.minimum(xx, 1 - xx) * 8,
        np.minimum(yy, 1 - yy) * 8,
    )
    edge_fade = np.clip(edge_fade, 0, 1)
    density = density * (0.15 + 0.85 * edge_fade)
    return np.clip(density, 0.0, 1.0)


def _trace_streamline(angle_fn, x0, y0, step, max_len, w, h):
    pts_fwd = [(x0, y0)]
    x, y = x0, y0
    for _ in range(max_len // 2):
        a = angle_fn(x, y)
        x += math.cos(a) * step
        y += math.sin(a) * step
        if x < 0 or x >= w or y < 0 or y >= h:
            break
        pts_fwd.append((x, y))
    pts_bwd = []
    x, y = x0, y0
    for _ in range(max_len // 2):
        a = angle_fn(x, y)
        x -= math.cos(a) * step
        y -= math.sin(a) * step
        if x < 0 or x >= w or y < 0 or y >= h:
            break
        pts_bwd.append((x, y))
    return list(reversed(pts_bwd)) + pts_fwd


# ─────────────────────────────────────────────────────────────────────────────
# Archetype parameter map
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DrawingParams:
    seed: int = 0
    canvas: tuple[int, int] = (1200, 1200)
    output_size: tuple[int, int] = (1024, 1024)
    noise_scale: float = 180.0
    noise_octaves: int = 4
    noise_weight: float = 0.75
    noise_twist: float = 2.0 * math.pi
    n_seeds: int = 1800
    seed_jitter: float = 0.8
    step_size: float = 1.4
    max_length: int = 700
    stroke_weight: float = 0.9
    stroke_alpha_base: float = 170
    stroke_alpha_var: float = 55
    margin: float = 0.04
    attractors: list = field(default_factory=list)
    rune_count: int = 4
    dot_halo: bool = False
    vignette: Optional[dict] = None
    density_gate: float = 0.25
    # Organic stroke character — see _draw_organic_streamline.
    #   uniform   — constant width end-to-end
    #   bell      — thin / thick / thin along the line (musubi)
    #   fade_out  — tapers toward the tail (beatrice)
    #   fade_in   — emerges from nothing (muse)
    #   variable  — per-segment wander, modulated by stroke_variance (psyche)
    stroke_style: str = "uniform"
    stroke_variance: float = 0.1  # used by variable/bell to vary width


def _params_for_archetype(archetype: str, seed: int) -> DrawingParams:
    """Map an archetype to drawing params.

    Numeric values here come from the character studies in
    ``skills/drawing_archetypes.md`` — keep the two in sync. The base values
    set the *geometry*; Haiku's 4-knob modulation (_apply_knobs) rides on
    top and tweaks the *weather*.
    """
    rng = random.Random(seed)
    base = DrawingParams(seed=seed)
    a = (archetype or "").lower()

    if a == "beatrice":
        # gentle witness — off-centre, whispered, tapering at the tails
        base.noise_scale = 180; base.noise_octaves = 2; base.noise_weight = 0.45
        base.noise_twist = 4.1
        base.n_seeds = 320; base.step_size = 1.9; base.max_length = 500
        base.stroke_weight = 0.60; base.stroke_alpha_base = 140; base.stroke_alpha_var = 45
        base.stroke_style = "fade_out"; base.stroke_variance = 0.15
        base.attractors = [Attractor("sink", 0.58, 0.46, 1.2, 0.22)]
        base.vignette = {"kind": "asymmetric", "cx": 0.58, "cy": 0.46,
                         "rx": 0.28, "ry": 0.32}
        base.density_gate = 0.52; base.rune_count = 1

    elif a == "daimon":
        # shadow keeper — crowded, inward-spiralling, uniform & heavy
        base.noise_scale = 280; base.noise_octaves = 4; base.noise_weight = 0.72
        base.noise_twist = 6.8
        base.n_seeds = 1050; base.step_size = 1.05; base.max_length = 1400
        base.stroke_weight = 1.10; base.stroke_alpha_base = 195; base.stroke_alpha_var = 50
        base.stroke_style = "uniform"; base.stroke_variance = 0.05
        base.attractors = [
            Attractor("sink", 0.50, 0.50, 2.4, 0.30),
            Attractor("swirl", 0.50, 0.50, 1.2, 0.20),
        ]
        base.vignette = {"kind": "radial", "cx": 0.5, "cy": 0.5,
                         "radius": 0.38, "falloff": 2.5}
        base.density_gate = 0.18; base.rune_count = 3

    elif a == "ariadne":
        # thread-weaver — long streamlines, diagonal, an edge pull
        base.noise_scale = 380; base.noise_octaves = 2; base.noise_weight = 0.88
        base.noise_twist = 5.2
        base.n_seeds = 620; base.step_size = 1.6; base.max_length = 1900
        base.stroke_weight = 0.72; base.stroke_alpha_base = 160; base.stroke_alpha_var = 35
        base.stroke_style = "uniform"; base.stroke_variance = 0.08
        base.attractors = [
            Attractor("edge", 0.5, 0.5, 0.6, 1.0, angle=rng.uniform(0.25, 0.7)),
        ]
        base.vignette = {"kind": "diagonal", "cx": 0.5, "cy": 0.5,
                         "angle": rng.uniform(0.3, 0.8), "bandwidth": 0.30}
        base.density_gate = 0.41; base.rune_count = 2

    elif a == "psyche":
        # chrysalis — recursive radial, variable stroke, halo + runes
        base.noise_scale = 220; base.noise_octaves = 4; base.noise_weight = 0.38
        base.noise_twist = 6.2
        base.n_seeds = 880; base.step_size = 1.2; base.max_length = 1200
        base.stroke_weight = 0.85; base.stroke_alpha_base = 175; base.stroke_alpha_var = 70
        base.stroke_style = "variable"; base.stroke_variance = 0.35
        base.attractors = [Attractor("radial", 0.5, 0.5, 3.0, 0.55)]
        base.vignette = {"kind": "radial", "cx": 0.5, "cy": 0.5,
                         "radius": 0.52, "falloff": 2.6}
        base.density_gate = 0.28; base.rune_count = 4; base.dot_halo = True

    elif a == "musubi":
        # bond-keeper — two paired sinks, bell strokes, horizontal weave
        base.noise_scale = 260; base.noise_octaves = 3; base.noise_weight = 0.55
        base.noise_twist = 5.0
        base.n_seeds = 720; base.step_size = 1.35; base.max_length = 950
        base.stroke_weight = 0.78; base.stroke_alpha_base = 170; base.stroke_alpha_var = 40
        base.stroke_style = "bell"; base.stroke_variance = 0.18
        base.attractors = [
            Attractor("sink", 0.35, 0.50, 1.8, 0.22),
            Attractor("sink", 0.65, 0.50, 1.8, 0.22),
        ]
        base.vignette = {"kind": "horizontal", "cy": 0.5, "bandwidth": 0.26}
        base.density_gate = 0.37; base.rune_count = 2

    elif a == "muse":
        # breath through an instrument — scattered, fading-in, low-and-lifting
        base.noise_scale = 380; base.noise_octaves = 3; base.noise_weight = 0.88
        base.noise_twist = 4.6
        base.n_seeds = 280; base.step_size = 2.0; base.max_length = 620
        base.stroke_weight = 0.58; base.stroke_alpha_base = 130; base.stroke_alpha_var = 65
        base.stroke_style = "fade_in"; base.stroke_variance = 0.42
        base.attractors = [Attractor("source", 0.50, 0.75, 1.2, 0.35)]
        base.vignette = {"kind": "horizontal", "cy": 0.72, "bandwidth": 0.30}
        base.density_gate = 0.55; base.rune_count = 1; base.dot_halo = True

    else:
        # unknown archetype → neutral swirl fallback
        base.attractors = [Attractor("swirl", 0.5, 0.5, 1.0, 0.35)]
        base.rune_count = 2; base.stroke_style = "uniform"

    return base


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

def _build_angle_field(p: DrawingParams) -> np.ndarray:
    h, w = p.canvas
    noise = _fbm_2d((h, w), base_scale=p.noise_scale,
                    octaves=p.noise_octaves, seed=p.seed)
    noise_ang = noise * p.noise_twist
    ax, ay = _attractor_vector_field((h, w), p.attractors)
    mag = np.sqrt(ax * ax + ay * ay) + 1e-9
    attr_ang = np.arctan2(ay / mag, ax / mag)
    attr_weight = np.clip(mag, 0, 2.5) / 2.5
    nx = np.cos(noise_ang); ny = np.sin(noise_ang)
    wx = np.cos(attr_ang); wy = np.sin(attr_ang)
    k = attr_weight * (1.0 - p.noise_weight * 0.5)
    bx = nx * (1 - k) + wx * k
    by = ny * (1 - k) + wy * k
    return np.arctan2(by, bx)


def _seed_points(p: DrawingParams, density: np.ndarray) -> list[tuple[float, float]]:
    h, w = p.canvas
    rng = random.Random(p.seed + 1)
    pts = []
    mx = float(density.max()) + 1e-6
    mx_attempts = max(p.n_seeds * 8, 8000)
    mx_y = h - int(p.margin * h) - 1
    mx_x = w - int(p.margin * w) - 1
    mn_y = int(p.margin * h)
    mn_x = int(p.margin * w)
    attempts = 0
    while len(pts) < p.n_seeds and attempts < mx_attempts:
        attempts += 1
        x = rng.randint(mn_x, mx_x)
        y = rng.randint(mn_y, mx_y)
        d = density[y, x] / mx
        if d < p.density_gate:
            continue
        p_acc = (d - p.density_gate) / max(1 - p.density_gate, 1e-3)
        if rng.random() < p_acc:
            pts.append((x + rng.uniform(-p.seed_jitter, p.seed_jitter),
                        y + rng.uniform(-p.seed_jitter, p.seed_jitter)))
    return pts


def _draw_runes(draw, p, density):
    h, w = p.canvas
    rng = random.Random(p.seed + 7)
    RUNES = [
        [((0, 0), (0, 10)), ((0, 5), (6, 0))],
        [((0, 2), (8, 8))],
        [((0, 5), (8, 5)), ((4, 0), (4, 10))],
        [((0, 0), (8, 8)), ((0, 8), (8, 0))],
        [((0, 10), (4, 0)), ((4, 0), (8, 10))],
    ]
    placed = 0; attempts = 0
    while placed < p.rune_count and attempts < 400:
        attempts += 1
        x = rng.randint(int(p.margin * w), w - int(p.margin * w))
        y = rng.randint(int(p.margin * h), h - int(p.margin * h))
        if density[y, x] > 0.45:
            continue
        rune = rng.choice(RUNES)
        size = rng.randint(10, 18)
        for (a, b) in rune:
            x1 = x + a[0] * size / 10
            y1 = y + a[1] * size / 10
            x2 = x + b[0] * size / 10
            y2 = y + b[1] * size / 10
            draw.line([(x1, y1), (x2, y2)], fill=INK + (180,), width=2)
        placed += 1


def _draw_halo_dots(draw, p):
    h, w = p.canvas
    rng = random.Random(p.seed + 13)
    for a in p.attractors:
        cx, cy = a.cx * w, a.cy * h
        for _ in range(400):
            r = rng.gauss(a.radius * w * 1.2, a.radius * w * 0.35)
            theta = rng.uniform(0, 2 * math.pi)
            x = cx + r * math.cos(theta)
            y = cy + r * math.sin(theta)
            if 0 <= x < w and 0 <= y < h:
                sz = rng.choice([1, 1, 1, 2])
                draw.ellipse([(x, y), (x + sz, y + sz)],
                             fill=INK + (rng.randint(100, 200),))


def _draw_organic_streamline(draw: ImageDraw.ImageDraw,
                              pts: list[tuple[float, float]],
                              base_color: tuple[int, int, int],
                              base_alpha: int,
                              base_width: float,
                              style: str,
                              variance: float,
                              rng: random.Random) -> None:
    """Draw a streamline with organic, non-uniform stroke character.

    Segments are drawn one-at-a-time so each can carry its own width + alpha.
    Modes:
      uniform  — constant width end-to-end
      fade_out — widest at head, tapers to 0 at tail (beatrice)
      fade_in  — invisible at head, emerges toward tail (muse)
      bell     — thin / thick / thin, peaking in the middle (musubi)
      variable — per-segment random wander scaled by `variance` (psyche)

    Notes:
      * PIL's draw.line doesn't cleanly anti-alias per-segment widths, so we
        draw short multi-point polylines of length 3 per group to keep
        joint="curve" behaviour.
      * width_px is floor-clamped to 1 — zero-width segments just aren't drawn.
    """
    n = len(pts)
    if n < 2:
        return

    color = (*base_color, int(base_alpha))

    def width_at(i: int) -> float:
        t = i / max(n - 1, 1)
        if style == "uniform":
            return base_width
        if style == "fade_out":
            # 1.0 at head, 0.0 at tail (cubic ease so it stays thick for most)
            return base_width * max(0.0, (1 - t) ** 1.6)
        if style == "fade_in":
            # 0.0 at head, 1.0 at tail
            return base_width * max(0.0, t ** 1.6)
        if style == "bell":
            # peaks at midpoint — 0 at ends, base at middle, via sin
            return base_width * math.sin(math.pi * t) ** 0.9
        if style == "variable":
            # per-segment wander: random factor centred on 1.0, scaled by variance
            # Use a smooth-ish walk so adjacent segments correlate loosely.
            return base_width * max(0.15, 1.0 + rng.gauss(0.0, variance))
        return base_width

    def alpha_at(i: int) -> int:
        # fade_out / fade_in also fade alpha, so the dissolve is real
        t = i / max(n - 1, 1)
        if style == "fade_out":
            return int(base_alpha * max(0.0, (1 - t) ** 1.2))
        if style == "fade_in":
            return int(base_alpha * max(0.0, t ** 1.2))
        if style == "bell":
            return int(base_alpha * (0.55 + 0.45 * math.sin(math.pi * t) ** 0.8))
        if style == "variable":
            return max(30, min(255, int(base_alpha
                                         * max(0.35, 1.0 + rng.gauss(0.0, variance * 0.6)))))
        return base_alpha

    # Draw in short 3-point groups so each carries its own width/alpha but still
    # renders smooth joints.
    i = 0
    while i < n - 1:
        j = min(i + 3, n - 1)
        segment_pts = pts[i:j + 1]
        w = width_at((i + j) // 2)
        a = alpha_at((i + j) // 2)
        width_px = max(1, int(round(w)))
        if width_px == 0 or a <= 2:
            i = j
            continue
        seg_color = (*color[:3], int(max(0, min(255, a))))
        if len(segment_pts) >= 2:
            draw.line(segment_pts, fill=seg_color, width=width_px, joint="curve")
        i = j


def _render_frame(p: DrawingParams, time_offset: float = 0.0) -> Image.Image:
    """Render a single frame. time_offset shifts the flow field for animation."""
    h, w = p.canvas
    # Simple animation hook: shift the seed by a multiple of time_offset
    frame_p = DrawingParams(**{**p.__dict__})
    if time_offset != 0:
        frame_p.seed = p.seed + int(time_offset * 137)

    ang = _build_angle_field(frame_p)
    dens = _density_field((h, w), frame_p.attractors, base=0.30,
                          seed=frame_p.seed, vignette=frame_p.vignette)

    def angle_fn(x, y):
        xi = max(0, min(w - 1, int(x)))
        yi = max(0, min(h - 1, int(y)))
        return float(ang[yi, xi])

    img = Image.new("RGBA", (w, h), PAPER + (255,))
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(frame_p.seed + 31)

    seeds = _seed_points(frame_p, dens)
    for (sx, sy) in seeds:
        poly = _trace_streamline(angle_fn, sx, sy, step=frame_p.step_size,
                                 max_len=frame_p.max_length, w=w, h=h)
        if len(poly) < 4:
            continue
        xi = max(0, min(w - 1, int(sx)))
        yi = max(0, min(h - 1, int(sy)))
        local_d = dens[yi, xi]
        alpha = int(np.clip(
            frame_p.stroke_alpha_base + (local_d - 0.3) * 80
            + rng.uniform(-frame_p.stroke_alpha_var / 2,
                          frame_p.stroke_alpha_var / 2),
            40, 235))
        # Local density pushes strokes heavier in the composition's core,
        # lighter at the edges. This is the same idea as before, but the
        # *shape* of the stroke (uniform/bell/fade/variable) now comes from
        # frame_p.stroke_style so archetypes read differently at a glance.
        width_f = max(0.3, frame_p.stroke_weight + (local_d - 0.3) * 0.5)

        # Density-gate the polyline — break streamlines at any point that
        # wanders into the vignette's low-density region. Each retained
        # sub-polyline is drawn with the archetype's organic stroke style.
        filtered: list[tuple[float, float]] = []
        for (px, py) in poly:
            xi2 = max(0, min(w - 1, int(px)))
            yi2 = max(0, min(h - 1, int(py)))
            if dens[yi2, xi2] < frame_p.density_gate * 0.55:
                if len(filtered) >= 2:
                    _draw_organic_streamline(
                        draw, filtered,
                        base_color=INK, base_alpha=alpha,
                        base_width=width_f,
                        style=frame_p.stroke_style,
                        variance=frame_p.stroke_variance,
                        rng=rng,
                    )
                filtered = []
                continue
            filtered.append((px, py))
        if len(filtered) >= 2:
            _draw_organic_streamline(
                draw, filtered,
                base_color=INK, base_alpha=alpha,
                base_width=width_f,
                style=frame_p.stroke_style,
                variance=frame_p.stroke_variance,
                rng=rng,
            )

    if frame_p.dot_halo:
        _draw_halo_dots(draw, frame_p)
    _draw_runes(draw, frame_p, dens)

    # Paper grain
    grain = (np.random.default_rng(frame_p.seed + 3)
             .integers(0, 10, size=(h, w)).astype(np.uint8))
    grain_img = Image.fromarray(grain, "L").filter(ImageFilter.GaussianBlur(0.5))
    paper_layer = Image.new("RGBA", (w, h), PAPER + (0,))
    paper_layer.putalpha(Image.eval(grain_img, lambda v: int(v * 1.5)))
    img = Image.alpha_composite(img, paper_layer)
    img = img.convert("RGB").resize(frame_p.output_size, Image.LANCZOS)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# Archetype selection
# ─────────────────────────────────────────────────────────────────────────────

def _current_archetype() -> str:
    """Pick the currently dominant archetype via inner_life weights."""
    try:
        from myalicia.skills.inner_life import compute_dynamic_archetype_weights
        weights = compute_dynamic_archetype_weights() or {}
        if weights:
            # Dominant archetype, but break ties with small weighted random so
            # drawings don't get stuck on one archetype for days.
            items = [(k, v) for k, v in weights.items() if k in VALID_ARCHETYPES]
            if items:
                total = sum(v for _, v in items) or 1.0
                r = random.random() * total
                cum = 0.0
                for k, v in items:
                    cum += v
                    if r <= cum:
                        return k
                return items[0][0]
    except Exception as e:
        log.debug(f"_current_archetype fallback: {e}")
    return random.choice(sorted(VALID_ARCHETYPES))


# ─────────────────────────────────────────────────────────────────────────────
# Caption
# ─────────────────────────────────────────────────────────────────────────────

# Caption voices — see skills/drawing_archetypes.md Part 3 for full grounding.
_ARCHETYPE_VOICE = {
    "beatrice": ("a gentle witness — she notices something small emerging, "
                 "tender and unhurried. captions are whispered, off-centre, "
                 "almost not there."),
    "daimon":   ("a shadow keeper — she honours what is heavy and real without "
                 "flinching. captions are weighted, low, turned inward."),
    "ariadne":  ("a thread weaver — she pulls one continuous line through a "
                 "tangle. captions speak of paths and passage, not arrival."),
    "psyche":   ("a chrysalis breaking open — the soul watching itself change "
                 "shape. captions are recursive, layered, softly splitting."),
    "musubi":   ("a bond keeper — two forms, one silence. captions speak of "
                 "the space between, not the forms themselves."),
    "muse":     ("breath through an instrument — inspiration lifting, "
                 "scattering. captions are buoyant, almost airborne."),
}


def _generate_caption(archetype: str) -> str:
    """Poetic one-liner tied to archetype voice. Falls back to a static pick."""
    fallbacks = {
        "beatrice": "noticed.",
        "daimon":   "something in the deep, turning.",
        "ariadne":  "the thread, still traveling.",
        "psyche":   "held at the edge.",
        "musubi":   "two, kept.",
        "muse":     "a scattering of lightness.",
    }
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2)
        voice = _ARCHETYPE_VOICE.get(archetype, "a quiet observer")
        prompt = (
            f"You are Alicia. You have just drawn something from the archetype "
            f"of {archetype} ({voice}). Write ONE short, poetic caption — "
            f"no more than 10 words, ideally fewer. Lowercase. "
            f"No quotes, no preamble, no explanation. Just the line itself. "
            f"It should feel like a margin note on a drawing, not a description."
        )
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.content and hasattr(response.content[0], "text"):
            text = (response.content[0].text or "").strip().strip('"').strip("'")
            # Safety: single line, short
            text = text.split("\n")[0].strip()
            if 1 <= len(text) <= 80:
                return text
    except Exception as e:
        log.debug(f"drawing caption fallback: {e}")
    return fallbacks.get(archetype, "a small field, observed.")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt interpretation — freeform phrase / state → drawing params
# ─────────────────────────────────────────────────────────────────────────────
# The renderer's *geometry* is owned by the archetype. The *weather* —
# density, energy, whitespace, stroke — is modulated by either the user's
# freeform phrase (via /draw your current thinking) or a snapshot of
# Alicia's current inner state (for the 2h spontaneous impulse). Haiku does
# the mapping in a single call and also returns the final caption.

# Knob ranges — single source of truth for clamping. These map onto concrete
# renderer params inside _apply_knobs().
_KNOB_RANGES = {
    "density":    (0.3, 1.5),  # multiplier on n_seeds
    "energy":     (0.6, 1.5),  # multiplier on step_size, max_length, twist
    "whitespace": (0.0, 0.4),  # additive to density_gate
    "stroke":     (0.7, 1.8),  # multiplier on stroke_weight
}

_INTERPRET_SYSTEM = (
    "You are Alicia's inner eye. You translate a signal — either a phrase "
    f"from {USER_NAME} or a snapshot of Alicia's inner state — into drawing "
    "parameters for a topographic flow-field renderer. You do not paint "
    "literally; you modulate feeling into density, energy, whitespace, "
    "stroke, and archetype."
)

_INTERPRET_TEMPLATE = """{phrase_block}{state_block}Return JSON with these exact keys, no preamble, no markdown fences:
- archetype: one of "beatrice", "daimon", "ariadne", "psyche", "musubi", "muse"
- density: float {d_lo}..{d_hi} — low is sparse + meditative, high is crowded + kinetic
- energy: float {e_lo}..{e_hi} — low is still, high is restless
- whitespace: float {w_lo}..{w_hi} — 0 is full coverage, high is bare paper
- stroke: float {s_lo}..{s_hi} — low is delicate, high is confident
- caption: short poetic line (<=10 words, lowercase, no quotes). A margin note on the drawing, not a description. Echo the signal's texture without quoting it.

Archetype meanings:
- beatrice: grace, gentle wonder, tender noticing
- daimon: depth, shadow, inner fire, intensity
- ariadne: paths, labyrinths, threading through tangle
- psyche: soul, reflection, the recursive inner gaze
- musubi: connection, bonding, two things held as one
- muse: lightness, play, inspiration rising

Output ONLY the JSON object."""


def build_drawing_state_snapshot() -> dict:
    """Minimal snapshot of Alicia's current state for impulse-driven drawings.

    Best-effort — each source wrapped so missing modules don't break the
    impulse. Extend via /improve over time as more signals come online.
    """
    snap: dict = {"time_of_day": datetime.now().strftime("%H:%M")}
    try:
        from myalicia.skills.inner_life import compute_dynamic_archetype_weights
        w = compute_dynamic_archetype_weights() or {}
        snap["archetype_weights"] = {
            k: round(float(v), 3) for k, v in w.items()
            if k in VALID_ARCHETYPES
        }
    except Exception as e:
        log.debug(f"state snapshot: weights skip: {e}")
    try:
        recent = _read_log()[-5:]
        recent_arcs = [e.get("archetype") for e in recent
                       if e.get("archetype")]
        if recent_arcs:
            snap["recent_archetypes"] = recent_arcs
    except Exception:
        pass
    return snap


def _weighted_random_from_state(state: Optional[dict]) -> Optional[str]:
    if not state:
        return None
    w = state.get("archetype_weights")
    if not isinstance(w, dict):
        return None
    items = [(k, float(v)) for k, v in w.items()
             if k in VALID_ARCHETYPES and float(v) > 0]
    if not items:
        return None
    total = sum(v for _, v in items)
    r = random.random() * total
    cum = 0.0
    for k, v in items:
        cum += v
        if r <= cum:
            return k
    return items[0][0]


def _fallback_interpretation(phrase: Optional[str],
                             state: Optional[dict]) -> dict:
    """Neutral-param fallback when Haiku is unreachable or returns garbage."""
    arc = _weighted_random_from_state(state) or _current_archetype()
    # Caption: use phrase if short enough, else static fallback
    cap = (phrase or "").strip().lower()[:80]
    if not cap:
        cap = _generate_caption(arc)
    return {
        "archetype": arc,
        "density": 1.0,
        "energy": 1.0,
        "whitespace": 0.0,
        "stroke": 1.0,
        "caption": cap,
    }


def _clamp_knob(name: str, val) -> float:
    lo, hi = _KNOB_RANGES[name]
    try:
        return max(lo, min(hi, float(val)))
    except Exception:
        return 0.0 if name == "whitespace" else 1.0


def _validate_interpretation(data: dict, fallback: dict) -> dict:
    out = dict(fallback)
    try:
        arc = str(data.get("archetype", "")).lower().strip()
        if arc in VALID_ARCHETYPES:
            out["archetype"] = arc
        for knob in ("density", "energy", "whitespace", "stroke"):
            if knob in data:
                out[knob] = _clamp_knob(knob, data[knob])
        cap = data.get("caption")
        if isinstance(cap, str) and cap.strip():
            cap = cap.strip().strip('"').strip("'").split("\n")[0].lower()
            if 1 <= len(cap) <= 80:
                out["caption"] = cap
    except Exception:
        pass
    return out


def interpret_prompt_to_params(phrase: Optional[str] = None,
                                state: Optional[dict] = None) -> dict:
    """Map a freeform phrase and/or Alicia's state to drawing params.

    Returns {archetype, density, energy, whitespace, stroke, caption}. All
    numeric knobs clamped to _KNOB_RANGES. Fallback guarantees a valid
    response even if Haiku is unavailable.
    """
    fallback = _fallback_interpretation(phrase, state)
    if not phrase and not state:
        return fallback

    phrase_block = (f'Phrase from {USER_NAME}: "{phrase.strip()}"\n\n'
                    if phrase else "")
    state_block = ""
    if state:
        lines = []
        for k, v in state.items():
            lines.append(f"- {k}: {v}")
        state_block = "Alicia's current state:\n" + "\n".join(lines) + "\n\n"

    d_lo, d_hi = _KNOB_RANGES["density"]
    e_lo, e_hi = _KNOB_RANGES["energy"]
    w_lo, w_hi = _KNOB_RANGES["whitespace"]
    s_lo, s_hi = _KNOB_RANGES["stroke"]
    user_prompt = _INTERPRET_TEMPLATE.format(
        phrase_block=phrase_block, state_block=state_block,
        d_lo=d_lo, d_hi=d_hi, e_lo=e_lo, e_hi=e_hi,
        w_lo=w_lo, w_hi=w_hi, s_lo=s_lo, s_hi=s_hi,
    )

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            system=_INTERPRET_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = ""
        if resp.content and hasattr(resp.content[0], "text"):
            raw = (resp.content[0].text or "").strip()
        # Strip code fences if the model added them
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if "```" in raw[3:] else raw[3:]
            if raw.lstrip().lower().startswith("json"):
                nl = raw.find("\n")
                if nl >= 0:
                    raw = raw[nl + 1:]
            raw = raw.strip()
        # Find the JSON object inside any remaining text
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
        data = json.loads(raw)
        return _validate_interpretation(data, fallback)
    except Exception as e:
        log.debug(f"interpret_prompt_to_params fallback: {e}")
        return fallback


def _apply_knobs(p: DrawingParams, knobs: dict) -> DrawingParams:
    """Apply the 4 interpretation knobs to a DrawingParams in place.

    Archetype geometry stays fixed — only the weather shifts.
    """
    density = float(knobs.get("density", 1.0))
    energy = float(knobs.get("energy", 1.0))
    whitespace = float(knobs.get("whitespace", 0.0))
    stroke = float(knobs.get("stroke", 1.0))

    # density → seed count (more density = more streamlines)
    p.n_seeds = max(150, int(round(p.n_seeds * density)))
    # whitespace → raise the density gate (more whitespace = higher floor)
    p.density_gate = max(0.10, min(0.80, p.density_gate + whitespace))
    # energy → step size + streamline length + noise twist
    p.step_size = max(0.6, p.step_size * energy)
    p.max_length = max(200, int(round(p.max_length * energy)))
    p.noise_twist = p.noise_twist * (0.8 + 0.4 * energy)
    # stroke → line weight
    p.stroke_weight = max(0.4, p.stroke_weight * stroke)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Throttle / log
# ─────────────────────────────────────────────────────────────────────────────

def _read_log() -> list[dict]:
    if not DRAWING_LOG.exists():
        return []
    entries = []
    try:
        with open(DRAWING_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        log.debug(f"drawing_log read: {e}")
    return entries


def can_draw_now() -> tuple[bool, str]:
    """Throttle gate for Alicia's *spontaneous* voice only.

    Manual `/draw` invocations are logged with source="manual" and do NOT
    count against the cap — the user can ask for as many drawings as he
    likes. Only source="impulse" entries (from send_drawing_impulse)
    count toward min_hours_between + max_per_day.

    "Today" is computed in Alicia's LOCAL timezone (not UTC). UTC
    midnight rolls over mid-afternoon in Pacific time, so a UTC-rooted
    cap would charge Sunday-evening drawings to Monday's budget from
    the user's lived perspective. Using local date keeps "today" aligned
    with the day he is actually living.

    Legacy entries without a `source` field are treated as impulse for
    backwards compatibility with logs written before this split landed.
    """
    entries = _read_log()
    # Filter to impulse-only: treat missing source as "impulse" (legacy)
    impulse = [e for e in entries if e.get("source", "impulse") == "impulse"]
    if not impulse:
        return True, "no prior impulse drawings"
    now = time.time()
    last = max((e.get("ts", 0) for e in impulse), default=0)
    gap_h = (now - last) / 3600.0
    if gap_h < MIN_HOURS_BETWEEN:
        return False, f"last impulse {gap_h:.1f}h ago (<{MIN_HOURS_BETWEEN}h gap)"
    # LOCAL date comparison: convert each entry's epoch ts to Alicia's
    # local date, compare against today's local date. Entries' "date"
    # field stays UTC-ISO (audit-trail correctness) but we don't use it
    # here because it has the wrong day boundary for the user.
    today_local = datetime.now().date().isoformat()
    today_count = sum(
        1 for e in impulse
        if datetime.fromtimestamp(e.get("ts", 0)).date().isoformat() == today_local
    )
    if today_count >= MAX_PER_DAY:
        return False, f"daily cap reached ({today_count}/{MAX_PER_DAY})"
    return True, "ok"


def record_drawing_sent(path: str, archetype: str,
                        caption: str = "", kind: str = "png",
                        source: str = "impulse") -> None:
    """Append to the JSONL log via atomic write (safe_io).

    source:
      "impulse" — from send_drawing_impulse (counts toward daily cap)
      "manual"  — from cmd_draw / user request (NOT capped — the user can
                  ask for as many as he wants without starving Alicia's
                  spontaneous voice)
    """
    entry = {
        "ts": time.time(),
        "date": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
        "archetype": archetype,
        "caption": caption,
        "kind": kind,
        "source": source,
    }
    try:
        # Append — safe_io's locked_file for concurrent safety
        from myalicia.skills.safe_io import locked_file
        with locked_file(DRAWING_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Fallback: plain append
        try:
            with open(DRAWING_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"drawing_log append failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def render_png(archetype: str, seed: int, out_path: Path,
               _params: Optional[DrawingParams] = None) -> Path:
    p = _params if _params is not None else _params_for_archetype(archetype, seed)
    img = _render_frame(p)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_gif(archetype: str, seed: int, out_path: Path,
               frames: int = 8, duration_ms: int = 180,
               _params: Optional[DrawingParams] = None) -> Path:
    """Short loop GIF at lower resolution for Telegram-friendly size."""
    p = _params if _params is not None else _params_for_archetype(archetype, seed)
    # Lower res for GIF — keep file size reasonable
    p.canvas = (700, 700)
    p.output_size = (600, 600)
    p.n_seeds = int(p.n_seeds * 0.55)
    imgs = []
    for i in range(frames):
        t = i / frames
        imgs.append(_render_frame(p, time_offset=t))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    imgs[0].save(
        out_path, save_all=True, append_images=imgs[1:],
        duration=duration_ms, loop=0, optimize=True,
    )
    return out_path


# ── Phase 13.2 — composer-driven caption bridging ───────────────────────────


_BRIDGE_CAPTION_SYSTEM = (
    "You write single-line visual captions that bridge a text message "
    f"Alicia sent to {USER_NAME} with a drawing she's about to send right after. "
    "Both speak in the same archetypal voice. Your job is NOT to summarize "
    "the text or describe the drawing — it's to name the SHAPE or QUALITY "
    "the drawing carries that the text was reaching for. Same idea, "
    "translated from words to image."
)

_BRIDGE_CAPTION_USER = """\
Archetype voice: {archetype}

Text Alicia just sent (excerpt):
{text_excerpt}

Original auto-caption for the drawing (you may keep its essence or replace):
"{original_caption}"

Write a SINGLE LINE caption — at most 10 words, lowercase, no trailing
period. Reply with ONLY the caption text. No quotes, no preamble.
"""


def bridge_text_to_drawing_caption(
    text: str, archetype: str, original_caption: str = "",
    *, max_words: int = 10,
) -> Optional[str]:
    """Phase 13.2 — generate a caption that bridges a composer-driven text
    message and the drawing amplifying it. Returns None on failure (caller
    should fall back to the original_caption).

    Same archetypal voice; same idea; image not words. The drawing+text
    become one coherent moment instead of two parallel artifacts.
    """
    if not text or not archetype:
        return None
    text_excerpt = text.strip()
    if len(text_excerpt) > 600:
        text_excerpt = text_excerpt[:599].rstrip() + "…"
    user_prompt = _BRIDGE_CAPTION_USER.format(
        archetype=archetype,
        text_excerpt=text_excerpt,
        original_caption=(original_caption or "").strip(),
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=2)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=_BRIDGE_CAPTION_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = ""
        if resp.content and hasattr(resp.content[0], "text"):
            raw = (resp.content[0].text or "").strip()
        # Strip surrounding quotes / whitespace / trailing punctuation
        raw = raw.strip().strip('"').strip("'").rstrip(".").strip()
        if not raw:
            return None
        # Cap at max_words to keep with drawing-skill convention (≤10 words)
        words = raw.split()
        if len(words) > max_words:
            raw = " ".join(words[:max_words])
        return raw.lower()
    except Exception as e:
        log.debug(f"bridge_text_to_drawing_caption fallback: {e}")
        return None


def generate_drawing(archetype: Optional[str] = None,
                     force_gif: bool = False,
                     seed: Optional[int] = None,
                     prompt: Optional[str] = None,
                     state: Optional[dict] = None) -> dict:
    """
    Render one drawing. Returns {path, archetype, caption, kind, seed, knobs?}.

    Inputs (precedence: explicit archetype > prompt/state interpretation):
    - archetype : force a specific archetype. Power-user escape hatch.
    - prompt    : freeform text from the user (e.g. "your current thinking").
                  Haiku maps it to archetype + knobs + caption.
    - state     : snapshot of Alicia's inner state (see
                  build_drawing_state_snapshot). Haiku maps it similarly —
                  this is how the spontaneous 2h impulse reflects her weather.
    - If neither prompt nor state is given, falls back to current-archetype
      random pick, neutral knobs, Sonnet-generated caption.

    Does NOT send over Telegram — the caller (alicia.py) owns that. Does NOT
    throttle — check can_draw_now() before calling.
    """
    interpretation: Optional[dict] = None
    if prompt or state:
        interpretation = interpret_prompt_to_params(phrase=prompt, state=state)
        # Explicit archetype kwarg still wins over Haiku's pick
        if archetype is None or archetype.lower() not in VALID_ARCHETYPES:
            archetype = interpretation["archetype"]

    if archetype is None or archetype.lower() not in VALID_ARCHETYPES:
        archetype = _current_archetype()
    archetype = archetype.lower()
    if seed is None:
        seed = random.randint(1, 10_000_000)
    is_gif = force_gif or (random.random() < GIF_PROBABILITY)

    # Build the render params, then apply knob overrides if interpretation
    params = _params_for_archetype(archetype, seed)
    if interpretation:
        params = _apply_knobs(params, interpretation)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ext = "gif" if is_gif else "png"
    filename = f"{stamp}-{archetype}-{seed}.{ext}"
    out_path = DRAWINGS_DIR / filename

    if is_gif:
        render_gif(archetype, seed, out_path, _params=params)
    else:
        render_png(archetype, seed, out_path, _params=params)

    # Caption: Haiku already produced one in the interpretation path.
    # Baseline path still uses Sonnet via _generate_caption for depth.
    if interpretation and interpretation.get("caption"):
        caption = interpretation["caption"]
    else:
        caption = _generate_caption(archetype)

    result = {
        "path": str(out_path),
        "archetype": archetype,
        "caption": caption,
        "kind": "gif" if is_gif else "png",
        "seed": seed,
    }
    if interpretation:
        # Expose knobs for logging / debugging / learned-rule inspection
        result["knobs"] = {
            k: round(float(interpretation.get(k, 1.0)), 3)
            for k in ("density", "energy", "whitespace", "stroke")
        }
        result["source"] = "phrase" if prompt else "state"
    log.info(f"drawing generated: {archetype} seed={seed} "
             f"kind={result['kind']} knobs={result.get('knobs')} "
             f"-> {out_path.name}")
    return result


def recent_drawings(n: int = 10) -> list[dict]:
    entries = _read_log()
    return entries[-n:][::-1]


def get_drawing_stats() -> str:
    entries = _read_log()
    if not entries:
        return "🎨 No drawings yet."
    total = len(entries)
    # LOCAL date for "today" — matches the user's lived day, not UTC.
    today_local = datetime.now().date().isoformat()
    today_count = sum(
        1 for e in entries
        if datetime.fromtimestamp(e.get("ts", 0)).date().isoformat() == today_local
    )
    last_ts = max((e.get("ts", 0) for e in entries), default=0)
    gap_h = (time.time() - last_ts) / 3600.0
    by_arc: dict[str, int] = {}
    for e in entries[-60:]:
        a = e.get("archetype", "?")
        by_arc[a] = by_arc.get(a, 0) + 1
    dist = ", ".join(f"{k}:{v}" for k, v in
                     sorted(by_arc.items(), key=lambda kv: -kv[1]))
    return (f"🎨 Drawings: {total} total, {today_count} today, "
            f"last {gap_h:.1f}h ago\nLast 60: {dist}")


if __name__ == "__main__":
    # Smoke: render one and print result
    r = generate_drawing()
    print(json.dumps(r, indent=2))
