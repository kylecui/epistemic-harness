#!/usr/bin/env python3
"""Regenerate docs/skills-inventory.md with block-scalar-aware description parsing."""
import re
from pathlib import Path


def desc_of(fm: str) -> str:
    lines = fm.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("description:"):
            v = l.split(":", 1)[1].strip()
            if not v or set(v) <= set(">|-+"):
                buf = []
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith((" ", "\t")) and lines[j].strip():
                        buf.append(lines[j].strip())
                    else:
                        break
                return " ".join(buf)
            return v.strip("\"'")
    return ""


def main() -> None:
    rows = []
    for root, src in [(Path.home() / ".agents" / "skills", "agents-shared"),
                      (Path.home() / ".pi" / "agent" / "skills", "pi-user")]:
        for md in sorted(root.glob("*/SKILL.md")):
            t = md.read_text(encoding="utf-8", errors="ignore")
            m = re.match(r"^---\n(.*?)\n---", t, re.S)
            d = desc_of(m.group(1)) if m else ""
            rows.append({"dir": md.parent.name, "desc": d, "src": src, "desc_len": len(d)})

    AUTO = {
        "epistemic-dual-process-harness", "code-review-annotate", "doc-reader", "ppt-reader",
        "generate-test-cases", "generate-usage-docs", "repo-runtime-discovery",
        "security-risk-review", "compliance-check", "done-gate", "done-ledger", "research-router",
    }
    NOTES = {
        "fish-brain": "与 skill-finder 功能重叠（重型 pack 管理器），二选一即可",
        "fish-market": "跨 13 源市场搜索，需要时装用时再调",
        "skill-finder": "新增：Tier 0 本地技能索引，已设 disable-model-invitation 仅手动调用",
    }

    def verdict(d):
        if d in AUTO:
            return "自动", "高频日常，模型自动触发收益大"
        return "手动", "/skill:name 显式调用；建议 disable-model-invocation 隐藏广告位"

    CAT = [
        ("核心治理", ["epistemic", "skill-finder"]),
        ("编码与仓库", ["code-review", "generate-", "repo-", "deployment", "service-operations", "incident", "target-host", "opencode-"]),
        ("文档阅读与写作", ["doc-reader", "ppt-", "typst", "style-extractor", "de-ai-detector"]),
        ("收尾治理", ["done-"]),
        ("个人 fish 生态", ["fish-"]),
        ("决策支持", ["decision-", "option-comparison", "council", "adoption"]),
        ("研究流水线", ["research-", "scientific-"]),
        ("规划战略", ["planning-"]),
        ("学习设计", ["learning-"]),
        ("产品", ["product-"]),
        ("活动/差旅", ["conference", "event-", "travel", "venue", "schedule", "logistics", "participant", "experience-", "content-selection", "training-event"]),
        ("风险/采购/尽调", ["risk-", "tco-", "vendor-", "compliance", "security"]),
        ("工具 CLI", ["hf-cli"]),
    ]

    def cat_of(d):
        for name, keys in CAT:
            if any(k in d for k in keys):
                return name
        return "其他"

    lines = [
        "# Skills 清单与初步处置建议（供 review）",
        "",
        "> v2（修正）：v1 把 fish-brain/fish-market 的 YAML 折叠块标量（`description: >`）误判为损坏——两技能实际合法（desc 各 402/502 字符），已修正解析器并重新归类。",
        "> 判断标准：**自动** = 高频日常，模型自动触发收益大；**手动** = 领域型/偶发，`disable-model-invocation: true` 隐藏广告位、保留 `/skill:name`。",
        "> 处置方式待定：你 review 后给规则，我批量执行（留备份）。",
        "",
    ]
    total = {"自动": 0, "手动": 0}
    for cat, keys in CAT + [("其他", [])]:
        grp = [r for r in rows if cat_of(r["dir"]) == cat]
        if not grp:
            continue
        lines += [f"## {cat}（{len(grp)}）", "",
                  "| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |",
                  "|---|---|---|---|---|---|"]
        for r in sorted(grp, key=lambda x: -x["desc_len"]):
            v, note = verdict(r["dir"])
            total[v] += 1
            desc = r["desc"][:90].replace("|", "/") + ("…" if len(r["desc"]) > 90 else "")
            extra = NOTES.get(r["dir"], "")
            src = "共享" if r["src"] == "agents-shared" else "Pi用户级"
            lines.append(f"| `{r['dir']}` | {src} | {desc} | {r['desc_len']} | **{v}** | {extra or note} |")
        lines.append("")
    auto_desc = sum(r["desc_len"] for r in rows if r["dir"] in AUTO)
    all_desc = sum(r["desc_len"] for r in rows)
    lines += ["## 统计", "",
              f"- 总数：{len(rows)}（修正后全部为合法技能，无待修项）",
              f"- 自动（保留广告位）：**{total['自动']}** ≈ {auto_desc // 4} tokens",
              f"- 手动（建议隐藏广告位）：**{total['手动']}**",
              f"- 全部隐藏后广告位 ≈ {auto_desc // 4} tokens（当前全量 ≈ {all_desc // 4} tokens）"]
    Path("docs/skills-inventory.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"inventory v2 written, {len(rows)} skills")


if __name__ == "__main__":
    main()
