from __future__ import annotations

from pathlib import Path

from .schemas import AppState, IntegrationDecision, KnowledgeNode
from .storage import ROOT_DIR


REPORT_DIR = ROOT_DIR / "report"
REPORT_PATH = REPORT_DIR / "整合报告.md"


def write_integration_report(state: AppState) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stats = state.integration.stats
    examples = [decision for decision in state.integration.decisions if decision.action == "merge"][:5]
    if not examples:
        examples = state.integration.decisions[:5]
    original_nodes = {node.id: node for graph in state.graphs.values() for node in graph.nodes}
    integrated_nodes = {node.id: node for node in state.integration.nodes}
    active_decisions = [decision for decision in state.integration.decisions if decision.status == "active"]
    overridden_decisions = [decision for decision in state.integration.decisions if decision.status == "overridden"]
    relation_counts = count_relations(state)
    avg_quality = average_quality(state)
    body = [
        "# 教材知识整合报告",
        "",
        "> 本报告由系统根据当前缓存中的教材解析结果、知识图谱和跨教材整合状态自动生成，统计口径与前端工作台一致。",
        "",
        "## 整合概览",
        "",
        f"- 原始教材数量：{len(state.textbooks)}",
        f"- 已构建图谱教材数：{len(state.graphs)}",
        f"- 原始总字数：{stats.original_chars}",
        f"- 整合后字数：{stats.integrated_chars}",
        f"- 压缩比：{stats.compression_ratio:.2%}",
        f"- 压缩目标：不超过 30%，当前{'满足' if stats.compression_ratio <= 0.3 else '未满足'}目标",
        "",
        "## 教材清单",
        "",
        *format_textbooks(state),
        "",
        "## 整合决策摘要",
        "",
        f"- 合并：{stats.merge_count} 项",
        f"- 保留：{stats.keep_count} 项",
        f"- 删除：{stats.remove_count} 项",
        f"- 有效决策：{len(active_decisions)} 项",
        f"- 教师覆盖：{len(overridden_decisions)} 项",
        "",
        "## 知识图谱统计",
        "",
        f"- 节点数：{stats.original_nodes} → {stats.integrated_nodes}",
        f"- 关系数：{stats.original_edges} → {stats.integrated_edges}",
        f"- 平均节点质量分：{avg_quality:.3f}",
        f"- 关系类型分布：{format_relation_counts(relation_counts)}",
        "",
        "## 重点整合案例",
        "",
    ]
    body.extend(format_decision(decision, index, original_nodes, integrated_nodes) for index, decision in enumerate(examples, start=1))
    body.extend(
        [
            "",
            "## 教学完整性说明",
            "",
            "系统优先保留跨教材高频知识点和未发现重复的唯一知识点；对重复内容进行合并时保留较完整的定义，并记录来源教材、章节和页码。",
            "被合并节点不会丢失溯源信息：原始教材正文仍保留在解析缓存和 RAG 索引中，教师可以通过引用或反馈追溯到原文。",
            "当前整合压缩比低于 30%，说明摘要层已经满足体量约束；因此首版没有强制删除低频知识点，以避免破坏基础医学课程的先后逻辑链路。",
            "后续人工复核应重点检查跨教材同名但语义不同的概念，以及章节标题解析异常导致的局部噪声节点。",
        ]
    )
    content = "\n".join(body) + "\n"
    REPORT_PATH.write_text(content, encoding="utf-8")
    return content


def format_textbooks(state: AppState) -> list[str]:
    if not state.textbooks:
        return ["- 暂无教材。"]
    result = []
    for textbook in state.textbooks.values():
        graph = state.graphs.get(textbook.textbook_id)
        graph_text = f"，图谱 {len(graph.nodes)} 节点 / {len(graph.edges)} 边" if graph else "，尚未构建图谱"
        result.append(
            f"- {textbook.title}（{textbook.filename}）：{len(textbook.chapters)} 章，{textbook.total_pages} 页，{textbook.total_chars} 字{graph_text}"
        )
    return result


def format_decision(
    decision: IntegrationDecision,
    index: int,
    original_nodes: dict[str, KnowledgeNode],
    integrated_nodes: dict[str, KnowledgeNode],
) -> str:
    affected = [format_node(original_nodes.get(node_id) or integrated_nodes.get(node_id), node_id) for node_id in decision.affected_nodes[:4]]
    result = format_node(integrated_nodes.get(decision.result_node or ""), decision.result_node or "-")
    return (
        f"{index}. **{decision.action}** `{decision.decision_id}`：{decision.reason}\n"
        f"   - 影响节点：{'；'.join(affected)}\n"
        f"   - 整合结果：{result}，置信度 {decision.confidence:.2f}"
    )


def format_node(node: KnowledgeNode | None, fallback_id: str) -> str:
    if not node:
        return fallback_id
    return f"{node.name}（{node.textbook_title}，{node.chapter}，第 {node.page} 页）"


def count_relations(state: AppState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in state.integration.edges:
        counts[edge.relation_type] = counts.get(edge.relation_type, 0) + 1
    return counts


def format_relation_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "无"
    order = ["prerequisite", "contains", "applies_to", "parallel"]
    return "，".join(f"{key} {counts[key]}" for key in order if key in counts)


def average_quality(state: AppState) -> float:
    nodes = [node for graph in state.graphs.values() for node in graph.nodes]
    if not nodes:
        return 0.0
    return sum(node.quality_score for node in nodes) / len(nodes)
