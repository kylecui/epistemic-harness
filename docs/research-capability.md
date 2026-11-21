# Research Capability (external retrieval before design answers)

> Goal: "retrieve before judging" for design/selection/SOTA questions is an executable harness constraint, not a verbal one.
> Basis: `harness.yaml` → `research_discipline` (compiled into AGENTS.md/SKILL.md) + the deterministic grounding check + retrieval tooling.
> 中文辅助版见 git 历史；规范以本文为准。

## 1. Available retrieval surface (verified against primary docs, 2026-11-20)

Source: Zhipu GLM Coding Plan official docs (`docs.bigmodel.cn/cn/coding-plan/mcp/*`).

| Server | Type | Tools | Endpoint |
|---|---|---|---|
| web-search-prime | Remote HTTP | `webSearchPrime` (title / URL / summary / site) | `https://open.bigmodel.cn/api/mcp/web_search_prime/mcp` |
| web-reader | Remote HTTP | `webReader` (title / body / metadata / links) | `https://open.bigmodel.cn/api/mcp/web_reader/mcp` |
| zread | Remote HTTP | `search_doc` (repo docs, issues/PRs, contributors), `get_repo_structure`, `read_file` | `https://open.bigmodel.cn/api/mcp/zread/mcp` |
| zai-mcp-server | local stdio (`npx -y @z_ai/mcp-server`) | `ui_to_artifact`, `extract_text_from_screenshot`, `diagnose_error_screenshot`, `understand_technical_diagram`, `analyze_data_visualization`, `ui_diff_check`, `image_analysis`, `video_analysis` | needs `Z_AI_API_KEY`, `Z_AI_MODE=ZHIPU｜ZAI` |

Auth header for the three remote servers: `Authorization: Bearer <API_KEY>`; legacy clients can use `.../sse?Authorization=<API_KEY>`. Claude Code on GLM models has search/reader built in server-side; other models require explicit installation.

**Zero-dependency fallback (proven in this repo)**: `curl` + the arXiv Atom API
(`https://export.arxiv.org/api/query?search_query=abs:%22agent+memory%22&sortBy=submittedDate&sortOrder=descending`)
plus the GitHub REST search API (stars/push dates as activity evidence). Semantic Scholar's free tier rate-limits (429) and is unsuitable for automation.

## 2. Wiring

```bash
export ZHIPU_API_KEY=...            # from the coding-plan console
export Z_AI_API_KEY=...             # optional, local vision server
python scripts/install_research_mcp.py --target pi --dry-run   # preview the merge
python scripts/install_research_mcp.py --target pi             # idempotent write
```

Targets: `pi | claude | opencode`. The script merges without overwriting and never commits keys to the repo. After writing, `pi mcp list` should show the new servers.

## 3. What we borrowed from opencode / Zhipu MCP design

- **Tools are the enforcer**: retrieval exists as tools the model can call; "remember to search" is replaced by "the tool exists".
- **Fetch, cite, move on**: retrieved content becomes citable fragments immediately; it is not parked in long-term context.
- **Client-side gating**: the external-read entry is switchable and auditable; writes go through a separate approval path.

Mapped here: research MCP + `check_external_grounding` + `traces/`.

## 4. Hard rules in the contract

- Triggers: design / selection / best-practice / SOTA / memory-retrieval-loop-eval-scheduling questions.
- Minimum bar: ≥2 independent sources, ≥1 primary source, each with URL or arXiv ID + the date read.
- No retrieval → say "未检索 / from memory" explicitly and cap that answer's confidence at L3.
- Code check: `check_external_grounding` (mirrored in `proxy_gateway/response_guard.py` and `orchestrator/exit_gate.py`). A reply containing an unanchored superlative claim (SOTA / 最佳方案 / 最流行 / 业界标准) with no URL/arXiv/DOI/read-date and no "no search" declaration is a contract violation.

## 5. Acceptance

```bash
python -m unittest tests.test_underdetermination_tc20_22 -v   # includes grounding cases
python -m unittest discover -s tests
python scripts/build_memory_index.py --check
```
