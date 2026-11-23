"""Interim-output schema guard for the gateway (research P1.5, structured-interim-contracts).

Off by default. Modes via HARNESS_INTERIM_SCHEMA:
  off     no interception (default — zero behavior change)
  warn    when the request declares `X-Harness-Interim: <schema>`, the response
          body must be JSON validating against that schema; violations are
          appended to the response as a note and recorded in traces
  enforce (P2) bounce once with a corrective directive, then degrade

The header opt-in keeps ordinary chat traffic untouched: only callers that
explicitly ask for a structured interim are policed.
"""

from __future__ import annotations

import json
import os

from proxy_gateway.interim_schema import load_schema, validate

SCHEMAS = {
    "subagent-report/v1": "subagent-report.schema.json",
    "reasoning-record/v1": "reasoning-record.schema.json",
}


def interim_mode() -> str:
    return os.getenv("HARNESS_INTERIM_SCHEMA", "off").strip().lower()


def requested_interim_schema(header_value: str | None) -> str | None:
    name = (header_value or "").strip()
    return name if name in SCHEMAS else None


def check_interim_response(text: str, schema_name: str) -> tuple[bool, list[str]]:
    """Validate a response body against the declared interim schema."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False, ["$: response is not valid JSON"]
    violations = validate(load_schema(SCHEMAS[schema_name]), payload)
    return not violations, violations


def interim_note(schema_name: str, violations: list[str]) -> str:
    return f"[HARNESS_INTERIM] schema {schema_name} violations: " + "; ".join(violations[:5])
