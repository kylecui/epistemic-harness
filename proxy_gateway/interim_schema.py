"""Dependency-free JSON-Schema subset validator for structured interim outputs.

Research branch: structured-interim-contracts (Paper 2, P1). The gateway and
the orchestrator must validate SubagentReport / ReasoningRecord payloads
without adding a jsonschema dependency to the container image, so this module
implements the small subset the interim schemas actually use: type, required,
properties, items, enum, const, minLength, minItems. Anything outside the
subset is ignored (documented boundary); interim schemas are self-contained
(no external $schema dereferencing).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "contracts" / "schemas"

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate(schema: dict[str, Any], payload: Any, path: str = "$") -> list[str]:
    """Return human-readable violations; empty list means valid."""
    violations: list[str] = []

    if "const" in schema and payload != schema["const"]:
        violations.append(f"{path}: expected const {schema['const']!r}, got {payload!r}")
    if "enum" in schema and payload not in schema["enum"]:
        violations.append(f"{path}: {payload!r} not in enum {schema['enum']}")

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_TYPE_CHECKS.get(t, lambda v: False)(payload) for t in expected_type):
            violations.append(f"{path}: expected type {'/'.join(expected_type)}, got {type(payload).__name__}")
            return violations
    elif expected_type and expected_type in _TYPE_CHECKS:
        if not _TYPE_CHECKS[expected_type](payload):
            violations.append(f"{path}: expected type {expected_type}, got {type(payload).__name__}")
            return violations  # downstream checks would be noise

    if isinstance(payload, str) and "minLength" in schema and len(payload) < schema["minLength"]:
        violations.append(f"{path}: shorter than minLength {schema['minLength']}")
    if isinstance(payload, list):
        if "minItems" in schema and len(payload) < schema["minItems"]:
            violations.append(f"{path}: fewer than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(payload):
                violations.extend(validate(item_schema, item, f"{path}[{i}]"))

    if isinstance(payload, dict):
        for key in schema.get("required") or []:
            if key not in payload:
                violations.append(f"{path}: missing required field {key!r}")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in payload:
                violations.extend(validate(sub, payload[key], f"{path}.{key}"))

    return violations
