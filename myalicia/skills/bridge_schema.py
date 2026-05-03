#!/usr/bin/env python3
"""
Alicia — Bridge + State Schemas (§6.5)

JSON-schema validation for the ~12 persisted state files that the system
reads back into its own personality (season, archetype weights, episode
scores, muse state, etc.). A bad `/improve` rewrite — or a future
migration that forgets a field — can silently corrupt the file shape
without this. With this, each read/write validates against a schema and
either *fails loudly* or *logs a warning and continues*, depending on the
entry point.

Why schemas matter here more than in most codebases:
  /improve can rewrite skill configs autonomously. `meta_reflexion` will
  extend that to state files eventually. Without a schema, a malformed
  rewrite corrupts state that took weeks to accrete. With a schema, we
  refuse the corruption and keep the last-good version.

API:
  validate(filename, payload)         — raises ValidationError on drift.
  validate_strict(filename, payload)  — same, but raises instead of warning
                                        when a schema isn't registered.
  has_schema(filename) -> bool
  register(filename, schema_dict)     — late-bound registration hook.
  list_schemas() -> list[str]

Dependencies:
  - `jsonschema` is a soft dep. If it's missing the validator degrades
    to a shallow type/required-field checker that's good enough to catch
    most drift. This means bridge_protocol never hard-fails on import.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


# ── Soft dep on jsonschema ──────────────────────────────────────────────────
try:
    import jsonschema as _jsonschema  # type: ignore
    from jsonschema import ValidationError as _JsonValidationError  # type: ignore
    _HAS_JSONSCHEMA = True
except ImportError:
    _jsonschema = None
    _JsonValidationError = Exception  # type: ignore
    _HAS_JSONSCHEMA = False
    log.info(
        "bridge_schema: jsonschema library not installed — falling back "
        "to shallow structural checks. pip install jsonschema to enable "
        "full draft-07 validation."
    )


class ValidationError(Exception):
    """Raised by `validate_strict` / `validate` when a payload doesn't
    match the registered schema for a filename."""


# ── Schemas ─────────────────────────────────────────────────────────────────
# All schemas follow draft-07 subset conventions. Keep them minimal — we
# want to catch shape drift, not lock down every field. Additional fields
# are allowed by default (additionalProperties unset = True).

SCHEMAS: Dict[str, dict] = {
    # --- Bridge snapshot (H2) ---
    "alicia-state.json": {
        "type": "object",
        "required": [
            "generated_at", "season", "emergence_score",
            "archetype_weights", "mood_signal", "hot_threads",
        ],
        "properties": {
            "generated_at": {"type": "string"},
            "season": {"type": "string"},
            "emergence_score": {"type": "number"},
            "archetype_weights": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
            "last_voice_at": {"type": "string"},
            "mood_signal": {"type": "string"},
            "hot_threads": {
                "type": "array",
                "items": {"type": "string"},
            },
            "last_score5_at": {"type": "string"},
        },
    },

    # --- Memory state files (~/alicia/memory/*.json) ---
    "emergence_state.json": {
        "type": "object",
        "required": ["season", "score"],
        "properties": {
            "season": {"type": "string"},
            "score": {"type": "number"},
            "last_transition_at": {"type": "string"},
            "archetype_weights": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
        },
    },

    "episode_scores.json": {
        "type": "object",
        "additionalProperties": {
            # Keyed by episode filename; value is the score record.
            "type": "object",
            "required": ["reward_score"],
            "properties": {
                "reward_score": {"type": "number"},
                "scored_at": {"type": "string"},
                "task_type": {"type": "string"},
            },
        },
    },

    "muse_state.json": {
        "type": "object",
        "properties": {
            "last_moment_at": {"type": "string"},
            "moments_today": {"type": "integer"},
            "recent_topics": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },

    "daily_rhythm.json": {
        "type": "object",
        "properties": {
            "last_morning_at": {"type": "string"},
            "last_midday_at": {"type": "string"},
            "last_evening_at": {"type": "string"},
            "skip_today": {"type": "boolean"},
        },
    },

    "session_threads.json": {
        "type": "object",
        "properties": {
            "threads": {"type": "array"},
            "most_common_themes": {"type": "array"},
            "updated_at": {"type": "string"},
        },
    },

    "effectiveness_state.json": {
        "type": "object",
        "properties": {
            "overall_effectiveness": {"type": "number"},
            "by_skill": {"type": "object"},
            "last_computed_at": {"type": "string"},
        },
    },

    "temporal_patterns.json": {
        "type": "object",
        "properties": {
            "hourly": {"type": "object"},
            "by_weekday": {"type": "object"},
            "trajectory": {"type": "object"},
        },
    },

    "voice_intelligence.json": {
        "type": "object",
        "properties": {
            "markers": {"type": "object"},
            "last_updated": {"type": "string"},
        },
    },

    "curiosity_queue.json": {
        "type": "object",
        "properties": {
            "pending": {"type": "array"},
            "asked": {"type": "array"},
        },
    },

    "autonomy_state.json": {
        "type": "object",
        "properties": {
            "last_pulse_at": {"type": "string"},
            "last_season_check_at": {"type": "string"},
        },
    },

    "voice_signature.json": {
        "type": "object",
        "properties": {
            "voice_hint": {"type": "string"},
            "updated_at": {"type": "string"},
        },
    },

    # ── §D3 Round 2 — state files that were previously flying blind ────
    "challenge_log.json": {
        # way_of_being/Psyche reciprocal-challenge log. Cooldowns depend
        # on `last_sent`, so a missing / malformed entry would silently
        # break the weekly challenge cadence.
        "type": "object",
        "properties": {
            "last_sent": {"type": "string"},
            "last_tension": {"type": "string"},
        },
    },

    "overnight_state.json": {
        # overnight_synthesis output used by Musubi bond reflection. The
        # `insights` array is what matters — if its shape drifts the
        # morning message silently drops overnight context.
        "type": "object",
        "properties": {
            "insights": {
                "type": "array",
                "items": {"type": "string"},
            },
            "generated_at": {"type": "string"},
        },
    },
}


# ── §D3 — Per-line JSONL schemas ────────────────────────────────────────────
# Unlike JSON files (one object ⇒ one schema), JSONL files consist of
# per-line JSON objects. We register a schema for the shape of ONE line;
# `validate_jsonl_line(filename, line_payload)` applies it. Callers that
# want to audit a whole file can iterate lines and validate each.

JSONL_LINE_SCHEMAS: Dict[str, dict] = {
    # /improve rule-change validation. One line per rule change, written
    # Monday 22:00 by meta_reflexion.validate_improve_outputs.
    "improve_validations.jsonl": {
        "type": "object",
        "required": [
            "validated_at", "skill", "assessment", "delta",
        ],
        "properties": {
            "validated_at": {"type": "string"},
            "improve_run_at": {"type": "string"},
            "skill": {"type": "string"},
            "change_type": {"type": "string"},
            "reasoning": {"type": "string"},
            "episodes_before": {"type": "integer"},
            "reward_before": {"type": "number"},
            "episodes_after": {"type": "integer"},
            "reward_after": {"type": "number"},
            "delta": {"type": "number"},
            "assessment": {"type": "string"},
            "window_days": {"type": "integer"},
        },
    },

    # way_of_being depth-signal log. Consumed by daimon-warning cooldown
    # and by vault_metrics trajectory analysis.
    "depth_signals.jsonl": {
        "type": "object",
        "required": ["timestamp", "topic", "source"],
        "properties": {
            "timestamp": {"type": "string"},
            "topic": {"type": "string"},
            "word_count": {"type": "integer"},
            "source": {"type": "string"},
        },
    },

    # voice_metadata_log — one line per voice message, feeds
    # voice_signature.compute_voice_signature() and voice_intelligence.
    "voice_metadata_log.jsonl": {
        "type": "object",
        "required": ["timestamp"],
        "properties": {
            "timestamp": {"type": "string"},
            "wpm": {"type": "number"},
            "duration_s": {"type": "number"},
            "word_count": {"type": "integer"},
            "style": {"type": "string"},
            # Gap 2 Phase B.2 — prosody feature snapshot. Optional so
            # legacy rows without features (pre-B.2) still validate.
            "features": {
                "type": "object",
                "properties": {
                    "mean_rms_db": {"type": "number"},
                    "peak_rms_db": {"type": "number"},
                    "f0_stdev_hz": {"type": "number"},
                    "voiced_duration_sec": {"type": "number"},
                    "long_pauses": {"type": "number"},
                    "max_pause_sec": {"type": "number"},
                },
            },
        },
    },

    # curiosity_followthrough — asked/answered events for
    # curiosity_engine + analysis_coordination.
    "curiosity_followthrough.jsonl": {
        "type": "object",
        "required": ["timestamp", "event"],
        "properties": {
            "timestamp": {"type": "string"},
            "event": {"type": "string"},
            "question": {"type": "string"},
            "type": {"type": "string"},
            "target": {"type": "string"},
        },
    },
}


# ── Late-bound registration for skills that want to declare their own ──────

def register(filename: str, schema: dict) -> None:
    """
    Register a schema for a filename at runtime. Later calls overwrite
    earlier ones — useful for tests.
    """
    SCHEMAS[filename] = schema


def has_schema(filename: str) -> bool:
    return filename in SCHEMAS


def list_schemas() -> list[str]:
    return sorted(SCHEMAS.keys())


# ── Validation ──────────────────────────────────────────────────────────────

def _validate_shallow(filename: str, payload: Any, schema: dict) -> None:
    """
    Fallback validator when `jsonschema` isn't installed. Checks:
      - top-level `type` (object | array | string | number | boolean)
      - `required` fields present when top-level is object
      - `properties[field].type` for each present field (one level deep)

    Good enough to catch "someone wrote an empty dict" or "someone
    dropped the `season` field" without a hard dep.
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(payload, dict):
            raise ValidationError(
                f"{filename}: expected object, got {type(payload).__name__}"
            )
        for req in schema.get("required", []):
            if req not in payload:
                raise ValidationError(
                    f"{filename}: required field '{req}' missing"
                )
        props = schema.get("properties", {})
        for field, sub in props.items():
            if field not in payload:
                continue
            sub_type = sub.get("type")
            if sub_type == "string" and not isinstance(payload[field], str):
                raise ValidationError(
                    f"{filename}.{field}: expected string"
                )
            if sub_type == "number" and not isinstance(
                payload[field], (int, float)
            ):
                raise ValidationError(
                    f"{filename}.{field}: expected number"
                )
            if sub_type == "integer" and not isinstance(
                payload[field], int
            ):
                raise ValidationError(
                    f"{filename}.{field}: expected integer"
                )
            if sub_type == "boolean" and not isinstance(
                payload[field], bool
            ):
                raise ValidationError(
                    f"{filename}.{field}: expected boolean"
                )
            if sub_type == "array" and not isinstance(
                payload[field], list
            ):
                raise ValidationError(
                    f"{filename}.{field}: expected array"
                )
            if sub_type == "object" and not isinstance(
                payload[field], dict
            ):
                raise ValidationError(
                    f"{filename}.{field}: expected object"
                )
    elif expected == "array":
        if not isinstance(payload, list):
            raise ValidationError(
                f"{filename}: expected array, got {type(payload).__name__}"
            )


def validate(filename: str, payload: Any) -> None:
    """
    Validate `payload` against the schema registered for `filename`.

    Raises ValidationError on drift. If no schema is registered, this
    is a no-op (the caller can fall back to `validate_strict` for strict
    coverage). If `jsonschema` is installed we use it; otherwise we use
    the shallow fallback.
    """
    schema = SCHEMAS.get(filename)
    if schema is None:
        return
    if _HAS_JSONSCHEMA:
        try:
            _jsonschema.validate(instance=payload, schema=schema)
        except _JsonValidationError as e:
            # Normalise so callers don't need to know which exception
            # flavour was raised.
            raise ValidationError(
                f"{filename}: {e.message} at path {list(e.absolute_path)}"
            ) from e
    else:
        _validate_shallow(filename, payload, schema)


def validate_strict(filename: str, payload: Any) -> None:
    """Same as `validate` but raises ValidationError if no schema is
    registered for the filename. Use this when you want to guarantee a
    file shape is locked down."""
    if filename not in SCHEMAS:
        raise ValidationError(f"{filename}: no schema registered")
    validate(filename, payload)


# ── JSONL validation (§D3) ──────────────────────────────────────────────────

def has_jsonl_schema(filename: str) -> bool:
    return filename in JSONL_LINE_SCHEMAS


def list_jsonl_schemas() -> list[str]:
    return sorted(JSONL_LINE_SCHEMAS.keys())


def register_jsonl(filename: str, schema: dict) -> None:
    """Register a per-line schema for a JSONL file at runtime."""
    JSONL_LINE_SCHEMAS[filename] = schema


def validate_jsonl_line(filename: str, payload: Any) -> None:
    """
    Validate a single JSONL line (already parsed to a Python object)
    against the per-line schema registered for `filename`.

    No-op if no schema is registered — mirrors `validate`.
    """
    schema = JSONL_LINE_SCHEMAS.get(filename)
    if schema is None:
        return
    if _HAS_JSONSCHEMA:
        try:
            _jsonschema.validate(instance=payload, schema=schema)
        except _JsonValidationError as e:
            raise ValidationError(
                f"{filename}: line {e.message} at path {list(e.absolute_path)}"
            ) from e
    else:
        _validate_shallow(filename, payload, schema)


def validate_jsonl_line_strict(filename: str, payload: Any) -> None:
    """Strict variant — raises if no JSONL schema is registered."""
    if filename not in JSONL_LINE_SCHEMAS:
        raise ValidationError(f"{filename}: no JSONL schema registered")
    validate_jsonl_line(filename, payload)


# ── Self-test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    good = {
        "generated_at": "2026-04-16T17:00:00Z",
        "season": "First Light",
        "emergence_score": 9.2,
        "archetype_weights": {"beatrice": 0.28},
        "mood_signal": "contemplative",
        "hot_threads": ["abstraction", "unity-division"],
    }
    validate("alicia-state.json", good)
    print("alicia-state.json valid payload: OK")

    try:
        validate("alicia-state.json", {"season": "First Light"})
    except ValidationError as e:
        print(f"alicia-state.json missing fields rejected: {e}")
    else:
        raise SystemExit("should have raised")

    try:
        validate_strict("nonexistent-file.json", {})
    except ValidationError as e:
        print(f"strict rejection for unknown schema: {e}")

    print(f"\nRegistered schemas ({len(SCHEMAS)}):")
    for name in list_schemas():
        print(f"  - {name}")
    print("\nAll bridge_schema self-tests passed.")
