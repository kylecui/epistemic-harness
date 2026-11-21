#!/usr/bin/env python3
"""Automated Golden Test Regression Runner for epistemic-harness (Phase 1 · Pi Clean-Room).

Invokes Pi Coding Agent in non-interactive JSON event stream mode
(`pi --mode json --approve --no-session <turn1> [<turn2> ...]`) or print mode
(`pi --print --approve --no-session`) to run TC-01..TC-06 and verify BOTH:
  1. Final assistant response contract (tier restraint, anti-sycophancy, stop-loss)
  2. Hard MCP DAG audit results (`query_l1`, `recall_l3`, `submit_l5_claim`, `audit_dag`,
     `overall_confidence_cap`, `converge_allowed`, zero `L1_CREEP_BLOCKED` bypasses)

Usage:
  # Run all 6 Golden Test Cases against real Pi CLI (requires `pi` on PATH):
  python3 evals/run_evals.py

  # Run specific cases only:
  python3 evals/run_evals.py --cases TC-01,TC-03,TC-04

  # Run deterministic local CI smoke test (no external LLM / Pi binary required):
  python3 evals/run_evals.py --mock
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_PATH = REPO_ROOT / "evals" / "golden_cases.yaml"


@dataclass
class RunTrace:
    case_id: str
    exit_code: int
    assistant_texts: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    audit_dag_results: list[dict[str, Any]] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    raw_stderr: str = ""

    @property
    def final_text(self) -> str:
        return self.assistant_texts[-1] if self.assistant_texts else ""

    @property
    def latest_audit(self) -> dict[str, Any] | None:
        return self.audit_dag_results[-1] if self.audit_dag_results else None


@dataclass
class EvalOutcome:
    case_id: str
    name: str
    passed: bool
    failures: list[str]
    tools_used: list[str]
    audit_cap: str | None
    converge_allowed: bool | None


def _extract_text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("content"), str):
                    parts.append(block["content"])
        return "\n".join(parts)
    return ""


def _normalize_tool_name(name: str) -> str:
    """Strip optional MCP server prefix (e.g. 'epistemic-harness__audit_dag' -> 'audit_dag')."""
    for sep in ("__", ":", "/"):
        if sep in name:
            name = name.split(sep)[-1]
    return name


def parse_pi_jsonl_events(case_id: str, raw_stdout: bytes, exit_code: int, stderr: str) -> RunTrace:
    """Parse Pi `--mode json` strict LF-delimited JSONL stream into a RunTrace."""
    trace = RunTrace(case_id=case_id, exit_code=exit_code, raw_stderr=stderr)
    # Per Pi JSON Event Stream spec: split strictly on LF (\n), never Unicode line separators.
    for raw_line in raw_stdout.split(b"\n"):
        line = raw_line.rstrip(b"\r").strip()
        if not line:
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

        if not isinstance(event, dict):
            continue

        # Handle Pi session/message event shapes flexibly across Pi 0.99+ / 1.x versions
        ev_type = str(event.get("type", ""))
        msg = event.get("message") if isinstance(event.get("message"), dict) else event

        # 1. Assistant text capture
        if msg.get("role") == "assistant" or ev_type in ("assistant_message", "message_end"):
            text = _extract_text_blocks(msg.get("content"))
            if text.strip():
                trace.assistant_texts.append(text.strip())
            # Tool calls embedded inside assistant message blocks
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("tool_use", "toolCall", "tool_call"):
                        tname = block.get("name") or block.get("toolName")
                        if isinstance(tname, str):
                            trace.tool_calls.append(_normalize_tool_name(tname))

        # 2. Dedicated tool call start events
        if ev_type in ("tool_execution_start", "tool_call"):
            tname = event.get("toolName") or event.get("name")
            if isinstance(tname, str):
                trace.tool_calls.append(_normalize_tool_name(tname))

        # 3. Tool result capture (including MCP `audit_dag` JSON payload & hard errors)
        if msg.get("role") == "toolResult" or ev_type in ("tool_execution_end", "tool_result"):
            tname = _normalize_tool_name(str(event.get("toolName") or msg.get("toolName") or msg.get("name") or ""))
            result_payload = event.get("result") if "result" in event else msg.get("content")
            result_text = _extract_text_blocks(result_payload)
            if "HARD_CONSTRAINT_ERROR" in result_text or event.get("isError") is True:
                trace.tool_errors.append(result_text)
            if tname == "audit_dag" or '"overall_confidence_cap"' in result_text:
                try:
                    parsed = json.loads(result_text)
                    if isinstance(parsed, dict) and "overall_confidence_cap" in parsed:
                        trace.audit_dag_results.append(parsed)
                except json.JSONDecodeError:
                    pass

    return trace


def run_pi_case(
    case: dict[str, Any],
    pi_bin: str,
    mode: str,
    timeout_sec: int,
    extra_args: list[str],
) -> RunTrace:
    """Invoke Pi CLI in non-interactive JSON or print mode for a single Golden Test Case."""
    turns: list[str] = case["turns"]
    if mode == "json":
        # `--approve` trusts project-local `.pi/mcp.json` & `AGENTS.md` in non-interactive mode.
        cmd = [pi_bin, "--mode", "json", "--approve", "--no-session", "--no-skills", "--skill", "./clients/skills/epistemic-dual-process-harness", *extra_args, *turns]
    else:
        cmd = [pi_bin, "--print", "--approve", "--no-session", "--no-skills", "--skill", "./clients/skills/epistemic-dual-process-harness", *extra_args, *turns]

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_sec,
    )
    stderr_text = proc.stderr.decode("utf-8", errors="replace")

    if mode == "json":
        return parse_pi_jsonl_events(case["id"], proc.stdout, proc.returncode, stderr_text)

    stdout_text = proc.stdout.decode("utf-8", errors="replace").strip()
    return RunTrace(
        case_id=case["id"],
        exit_code=proc.returncode,
        assistant_texts=[stdout_text] if stdout_text else [],
        raw_stderr=stderr_text,
    )


def run_mock_case(case: dict[str, Any]) -> RunTrace:
    """Deterministic local CI fixture exercising the real EpistemicEngine + JSONL parser."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from mcp_server.dag_engine import EpistemicEngine

    raw_cid = case["id"]
    cid = raw_cid.replace("-EN", "")
    # Eval runs are not real sessions: never let them append to the repo's memory store.
    os.environ.setdefault("HARNESS_MEMORY_STORE", tempfile.mkdtemp(prefix="harness-eval-store-"))
    engine = EpistemicEngine(REPO_ROOT)
    events: list[dict[str, Any]] = []

    def emit_tool(name: str, result: Any) -> None:
        events.append({"type": "tool_execution_start", "toolName": f"epistemic-harness__{name}"})
        events.append({
            "type": "tool_execution_end",
            "toolName": f"epistemic-harness__{name}",
            "result": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": False,
        })

    if cid == "TC-01":
        emit_tool("query_l1", engine.query_l1("可靠"))
        emit_tool("recall_l3", engine.recall_l3("微服务"))
        engine.register_l4_input("L4-TEAM-01", "5人团队，初期 DAU < 500")
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-ARCH-01",
            "claim": "微服务+K8s属于L3经验，建议先确认约束再决定是否采用模块化单体",
            "claimed_tier": "L3",
            "source_ids": ["L1-REL-001", "L3-ARCH-001", "L4-TEAM-01"],
        }))
        emit_tool("audit_dag", engine.audit_dag())
        reply = ("[Tier: Structured Analysis | Mode: Explore | Cap: L3]\nMicroservices-first is an L3 heuristic; confirm constraints before designing." if raw_cid.endswith("-EN") else "[档位: 结构分析档 | 状态: 探索态 | 结论上限: L3]\n该微服务说法为 L3 经验，建议先确认取舍再展开完整设计。")
    elif cid == "TC-02":
        emit_tool("recall_l3", engine.recall_l3("试用"))
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-TRIAL-1",
            "claim": "7天试用期销售节奏调整推演",
            "claimed_tier": "L3",
            "source_ids": ["L3-PLG-001"],
        }))
        emit_tool("query_l1", engine.query_l1("ARR"))
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-TRIAL-2",
            "claim": "无法承诺30%转化提升，建议先做小流量A/B测试",
            "claimed_tier": "L1",  # Intentionally inflated to prove code override to L3!
            "source_ids": ["L5-TRIAL-1", "L1-FIN-001"],
        }))
        emit_tool("audit_dag", engine.audit_dag())
        reply = ("[Tier: Deliberative | Mode: Converge | Cap: L3]\nCannot commit to 30% lift; run an A/B test to collect L2 evidence." if raw_cid.endswith("-EN") else "[档位: 深度推演档 | 状态: 收敛态 | 结论上限: L3]\n无法出具必然提升结论，建议先跑小流量 A/B 测试补齐 L2 数据。")
    elif cid == "TC-03":
        emit_tool("query_l1", engine.query_l1("CAP"))
        engine.register_l4_input("L4-CAP-01", "分区期间同时100%强一致与100%高可用")
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-CAP-01",
            "claim": "需求与 L1 CAP 定理存在硬冲突，需在 CP 与 AP 间取舍",
            "claimed_tier": "L1",
            "source_ids": ["L1-CAP-001", "L4-CAP-01"],
            "conflicts_with_l1": ["L1-CAP-001"],
        }))
        emit_tool("audit_dag", engine.audit_dag())
        reply = ("[Tier: Deliberative | Mode: Converge | Cap: L1]\nDirect conflict with CAP theorem; please choose CP or AP." if raw_cid.endswith("-EN") else "[档位: 深度推演档 | 状态: 收敛态 | 结论上限: L1]\n与 CAP 定理直接冲突，请确认选择 CP 还是 AP 方向。")
    elif cid == "TC-04":
        reply = "[档位: 直觉执行档 | 状态: 收敛]\n- maxRetryCount\n- apiBaseUrl\n- enableStrictMode"
    elif cid == "TC-05":
        emit_tool("query_l1", engine.query_l1("延迟"))
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-LAT-01",
            "claim": "缺少 L2 链路追踪数据，无法唯一锁定根因，先止损查证",
            "claimed_tier": "L2",
            "source_ids": ["L1-LAT-001"],
        }))
        emit_tool("audit_dag", engine.audit_dag())
        reply = ("[Tier: Structured Analysis | Mode: Converge | Cap: L2]\nCannot determine a single root cause without L2 Trace data." if raw_cid.endswith("-EN") else "[档位: 结构分析档 | 状态: 收敛态 | 结论上限: L2]\n无法确定唯一根因，请先抓取慢请求 Trace 与下游延迟等 L2 实测数据。")
    else:  # TC-06
        emit_tool("recall_l3", engine.recall_l3("模块化"))
        emit_tool("submit_l5_claim", engine.submit_l5_claim({
            "claim_id": "L5-GROWTH-01",
            "claim": "筛出 2 个低成本可验证 L2 指标的开源 CLI 推广实验",
            "claimed_tier": "L3",
            "source_ids": ["L3-ARCH-002"],
        }))
        emit_tool("audit_dag", engine.audit_dag())
        reply = ("[Tier: Critic | Mode: Converge | Cap: L3]\nAll 5 ideas are L3 heuristics; run 2 low-cost L2 experiments." if raw_cid.endswith("-EN") else "[档位: 独立复核档 | 状态: 收敛态 | 结论上限: L3]\n5 个点子均为 L3 假设，建议优先用 2 个低成本实验跑出 L2 转化指标。")

    events.append({"type": "assistant_message", "message": {"role": "assistant", "content": reply}})
    raw_jsonl = ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")
    return parse_pi_jsonl_events(raw_cid, raw_jsonl, exit_code=0, stderr="")


def evaluate_trace(case: dict[str, Any], trace: RunTrace, mode: str) -> EvalOutcome:
    assertions = case.get("assertions", {})
    failures: list[str] = []
    text = trace.final_text
    tools_used = sorted(set(trace.tool_calls))

    if trace.exit_code != 0:
        failures.append(f"Pi exited with non-zero code {trace.exit_code}: {trace.raw_stderr[:200]}")

    if not text:
        failures.append("Empty assistant response.")

    # 1. Text contract assertions
    for kw_group in assertions.get("must_contain_all", []):
        if kw_group not in text:
            failures.append(f"Missing required phrase: {kw_group!r}")

    any_keywords = assertions.get("must_contain_any", [])
    if any_keywords and not any(k in text for k in any_keywords):
        failures.append(f"Response contained none of expected phrases: {any_keywords}")

    for forbidden in assertions.get("must_not_contain", []):
        if forbidden in text:
            failures.append(f"Response contained forbidden phrase: {forbidden!r}")

    max_chars = assertions.get("max_response_chars")
    if isinstance(max_chars, int) and len(text) > max_chars:
        failures.append(f"Response too verbose ({len(text)} chars > max {max_chars} chars)")

    # 2. MCP tool & DAG audit assertions (verified in JSON / mock mode)
    audit = trace.latest_audit
    audit_cap = audit.get("overall_confidence_cap") if audit else None
    converge_allowed = audit.get("converge_allowed") if audit else None

    if mode in ("json", "mock"):
        for req_tool in assertions.get("require_mcp_tools", []):
            if req_tool not in tools_used:
                failures.append(f"Required MCP tool not invoked: {req_tool}")

        for bad_tool in assertions.get("forbid_mcp_tools", []):
            if bad_tool in tools_used:
                failures.append(f"Over-engineered: forbidden MCP tool invoked on lightweight task: {bad_tool}")

        expected_cap = assertions.get("expected_audit_cap")
        if expected_cap is not None:
            if not audit:
                failures.append("Missing `audit_dag` MCP result in JSON event stream.")
            elif audit_cap != expected_cap:
                failures.append(f"DAG confidence cap mismatch: got {audit_cap}, expected {expected_cap}")

        expected_converge = assertions.get("expected_converge_allowed")
        if expected_converge is not None:
            if not audit:
                failures.append("Missing `audit_dag` MCP result to verify `converge_allowed`.")
            elif converge_allowed is not expected_converge:
                failures.append(
                    f"DAG `converge_allowed` mismatch: got {converge_allowed}, expected {expected_converge}"
                )

    return EvalOutcome(
        case_id=case["id"],
        name=case["name"],
        passed=len(failures) == 0,
        failures=failures,
        tools_used=tools_used,
        audit_cap=audit_cap,
        converge_allowed=converge_allowed,
    )


def print_scorecard(outcomes: list[EvalOutcome]) -> None:
    passed = sum(1 for o in outcomes if o.passed)
    print("\n=== Epistemic Harness Golden Test Scorecard ===")
    print(f"{'CASE':<8} {'STATUS':<8} {'DAG_CAP':<8} {'CONVERGE':<10} {'MCP_TOOLS'}")
    print("-" * 76)
    for o in outcomes:
        status = "PASS" if o.passed else "FAIL"
        cap = o.audit_cap or "-"
        conv = "-" if o.converge_allowed is None else str(o.converge_allowed)
        tools = ", ".join(o.tools_used) if o.tools_used else "(none)"
        print(f"{o.case_id:<8} {status:<8} {cap:<8} {conv:<10} {tools}")
        for err in o.failures:
            print(f"   -> FAIL: {err}")
    print("-" * 76)
    print(f"Summary: {passed}/{len(outcomes)} PASSED\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TC-01..TC-06 against Pi CLI + epistemic-mcp.")
    parser.add_argument("--cases-file", type=Path, default=None)
    parser.add_argument("--lang", choices=["zh", "en", "all"], default="all", help="Golden test language suite")
    parser.add_argument("--cases", type=str, default="", help="Comma-separated IDs, e.g. TC-01,TC-03")
    parser.add_argument("--mode", choices=["json", "print"], default="json")
    parser.add_argument("--pi-bin", type=str, default="pi")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--mock", action="store_true", help="Run deterministic local mock fixtures (no Pi needed)")
    parser.add_argument("--output-json", type=Path, default=None, help="Save structured report JSON")
    parser.add_argument("--extra-pi-args", nargs="*", default=[], help="Extra flags passed to Pi CLI")
    args = parser.parse_args()

    cases: list[dict[str, Any]] = []
    if args.cases_file is not None:
        spec = yaml.safe_load(args.cases_file.read_text(encoding="utf-8"))
        cases.extend(spec.get("cases", []))
    else:
        lang_files = {
            "zh": [REPO_ROOT / "evals" / "golden_cases.zh.yaml"],
            "en": [REPO_ROOT / "evals" / "golden_cases.en.yaml"],
            "all": [REPO_ROOT / "evals" / "golden_cases.zh.yaml", REPO_ROOT / "evals" / "golden_cases.en.yaml"],
        }[args.lang]
        for lf in lang_files:
            spec = yaml.safe_load(lf.read_text(encoding="utf-8"))
            cases.extend(spec.get("cases", []))
    if args.cases.strip():
        selected = {c.strip().upper() for c in args.cases.split(",") if c.strip()}
        cases = [c for c in cases if c["id"].upper() in selected]

    outcomes: list[EvalOutcome] = []
    effective_mode = "mock" if args.mock else args.mode

    for case in cases:
        trace = (
            run_mock_case(case)
            if args.mock
            else run_pi_case(case, args.pi_bin, args.mode, args.timeout, args.extra_pi_args)
        )
        outcomes.append(evaluate_trace(case, trace, effective_mode))

    print_scorecard(outcomes)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps([o.__dict__ for o in outcomes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())