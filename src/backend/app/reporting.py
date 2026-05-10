from __future__ import annotations

from pathlib import Path

from .schemas import AppState, IntegrationDecision
from .storage import ROOT_DIR


REPORT_DIR = ROOT_DIR / "report"
REPORT_PATH = REPORT_DIR / "整合报告.md"


def write_integration_report(state: AppState) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stats = state.integration.stats
    examples = [decision for decision in state.integration.decisions if decision.action == "merge"][:5]
    if not examples:
        examples = state.integration.decisions[:5]
    body = [
        "# 教材知识整合报告",
        "",
        "## 整合概览",
        "",
        f"- 原始教材数量：{len(state.textbooks)}",
        f"- 原始总字数：{stats.original_chars}",
        f"- 整合后字数：{stats.integrated_chars}",
        f"- 压缩比：{stats.compression_ratio:.2%}",
        "",
        "## 整合决策摘要",
        "",
        f"- 合并：{stats.merge_count} 项",
        f"- 保留：{stats.keep_count} 项",
        f"- 删除：{stats.remove_count} 项",
        "",
        "## 知识图谱统计",
        "",
        f"- 节点数：{stats.original_nodes} → {stats.integrated_nodes}",
        f"- 关系数：{stats.original_edges} → {stats.integrated_edges}",
        "",
        "## 重点整合案例",
        "",
    ]
    body.extend(format_decision(decision, index) for index, decision in enumerate(examples, start=1))
    body.extend(
        [
            "",
            "## 教学完整性说明",
            "",
            "系统优先保留跨教材高频知识点和未发现重复的唯一知识点；对重复内容进行合并时保留较完整的定义，并记录来源教材。"
            "当压缩比超过 30% 时，仅删除低频摘要节点，原始教材 chunk 仍保留在 RAG 索引中，教师可通过对话反馈恢复或拆分整合决策。",
        ]
    )
    content = "\n".join(body) + "\n"
    REPORT_PATH.write_text(content, encoding="utf-8")
    return content


def format_decision(decision: IntegrationDecision, index: int) -> str:
    affected = "、".join(decision.affected_nodes[:4])
    return f"{index}. **{decision.action}** `{decision.decision_id}`：{decision.reason} 影响节点：{affected}"

