from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import re
from uuid import uuid4

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .schemas import AppState, GraphEdge, IntegrationDecision, IntegrationState, IntegrationStats, KnowledgeNode


def run_integration(state: AppState) -> IntegrationState:
    all_nodes = [node for graph in state.graphs.values() for node in graph.nodes]
    all_edges = [edge for graph in state.graphs.values() for edge in graph.edges]
    if not all_nodes:
        integration = IntegrationState(updated_at=datetime.utcnow().isoformat())
        state.integration = integration
        return integration

    groups = group_similar_nodes(all_nodes)
    decisions: list[IntegrationDecision] = []
    integrated_nodes: list[KnowledgeNode] = []
    node_map: dict[str, str] = {}

    for group in groups:
        if len(group) > 1:
            best = max(group, key=lambda node: len(node.definition) + len(node.source_text))
            merged = best.model_copy(deep=True)
            merged.id = f"merged_{uuid4().hex[:10]}"
            merged.frequency = len(group)
            merged.definition = select_definition(group)
            merged.source_text = best.source_text
            integrated_nodes.append(merged)
            for node in group:
                node_map[node.id] = merged.id
            decisions.append(
                IntegrationDecision(
                    decision_id=f"merge_{uuid4().hex[:8]}",
                    action="merge",
                    affected_nodes=[node.id for node in group],
                    result_node=merged.id,
                    reason=f"{len(group)} 本/处教材知识点语义相近，保留“{best.textbook_title}”中更完整的表述。",
                    confidence=min(0.96, 0.72 + 0.04 * len(group)),
                )
            )
        else:
            node = group[0].model_copy(deep=True)
            node.frequency = 1
            integrated_nodes.append(node)
            node_map[group[0].id] = node.id
            decisions.append(
                IntegrationDecision(
                    decision_id=f"keep_{uuid4().hex[:8]}",
                    action="keep",
                    affected_nodes=[node.id],
                    result_node=node.id,
                    reason=f"“{node.name}”未发现高置信重复知识点，保留以维持教学完整性。",
                    confidence=0.7,
                )
            )

    integrated_edges = remap_edges(all_edges, node_map)
    stats = compute_stats(state, all_nodes, all_edges, integrated_nodes, integrated_edges, decisions)
    if stats.compression_ratio > 0.3:
        trim_to_compression(integrated_nodes, decisions, stats.original_chars)
        integrated_edges = [edge for edge in integrated_edges if edge.source in {node.id for node in integrated_nodes} and edge.target in {node.id for node in integrated_nodes}]
        stats = compute_stats(state, all_nodes, all_edges, integrated_nodes, integrated_edges, decisions)

    integration = IntegrationState(
        decisions=decisions,
        nodes=integrated_nodes,
        edges=integrated_edges,
        stats=stats,
        updated_at=datetime.utcnow().isoformat(),
        conversation=state.integration.conversation,
    )
    state.integration = integration
    return integration


def group_similar_nodes(nodes: list[KnowledgeNode]) -> list[list[KnowledgeNode]]:
    normalized: dict[str, list[KnowledgeNode]] = defaultdict(list)
    for node in nodes:
        normalized[normalize(node.name)].append(node)

    groups = list(normalized.values())
    singletons = [group[0] for group in groups if len(group) == 1]
    merged_groups = [group for group in groups if len(group) > 1]
    if len(singletons) < 2:
        return merged_groups + [[node] for node in singletons]

    corpus = [f"{node.name} {node.definition}" for node in singletons]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(corpus)
    similarity = cosine_similarity(matrix)
    used: set[int] = set()
    for index, node in enumerate(singletons):
        if index in used:
            continue
        group = [node]
        used.add(index)
        for other_index in range(index + 1, len(singletons)):
            if other_index in used:
                continue
            other = singletons[other_index]
            if node.textbook_id == other.textbook_id:
                continue
            if similarity[index, other_index] >= 0.62:
                group.append(other)
                used.add(other_index)
        merged_groups.append(group)
    return merged_groups


def remap_edges(edges: list[GraphEdge], node_map: dict[str, str]) -> list[GraphEdge]:
    result: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        source = node_map.get(edge.source)
        target = node_map.get(edge.target)
        if not source or not target or source == target:
            continue
        key = (source, target, edge.relation_type)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge.model_copy(update={"source": source, "target": target}))
    return result


def compute_stats(
    state: AppState,
    original_nodes: list[KnowledgeNode],
    original_edges: list[GraphEdge],
    integrated_nodes: list[KnowledgeNode],
    integrated_edges: list[GraphEdge],
    decisions: list[IntegrationDecision],
) -> IntegrationStats:
    original_chars = sum(textbook.total_chars for textbook in state.textbooks.values())
    integrated_chars = sum(len(node.definition) for node in integrated_nodes)
    counts = {action: sum(1 for decision in decisions if decision.action == action and decision.status == "active") for action in ("merge", "keep", "remove")}
    return IntegrationStats(
        original_chars=original_chars,
        integrated_chars=integrated_chars,
        compression_ratio=round(integrated_chars / original_chars, 4) if original_chars else 0,
        original_nodes=len(original_nodes),
        integrated_nodes=len(integrated_nodes),
        original_edges=len(original_edges),
        integrated_edges=len(integrated_edges),
        merge_count=counts["merge"],
        keep_count=counts["keep"],
        remove_count=counts["remove"],
    )


def trim_to_compression(nodes: list[KnowledgeNode], decisions: list[IntegrationDecision], original_chars: int) -> None:
    target_chars = int(original_chars * 0.3)
    current = sum(len(node.definition) for node in nodes)
    if current <= target_chars:
        return
    nodes.sort(key=lambda node: (node.frequency, len(node.definition)))
    min_keep = max(1, min(len(nodes), target_chars // 40)) if target_chars else 1
    removed: list[KnowledgeNode] = []
    while len(nodes) > min_keep and current > target_chars:
        node = nodes.pop(0)
        removed.append(node)
        current -= len(node.definition)
    if current > target_chars and nodes:
        per_node = max(1, target_chars // len(nodes)) if target_chars else 1
        for node in nodes:
            if len(node.definition) > per_node:
                node.definition = node.definition[:per_node]
    for node in removed:
        decisions.append(
            IntegrationDecision(
                decision_id=f"remove_{uuid4().hex[:8]}",
                action="remove",
                affected_nodes=[node.id],
                reason=f"为满足 30% 压缩比，删除低频知识点“{node.name}”的冗余摘要；原始来源仍可通过 RAG 检索。",
                confidence=0.68,
            )
        )


def select_definition(group: list[KnowledgeNode]) -> str:
    best = max(group, key=lambda node: len(node.definition))
    sources = "；".join(sorted({node.textbook_title for node in group})[:4])
    return f"{best.definition}（整合来源：{sources}）"


def normalize(name: str) -> str:
    text = re.sub(r"[\W_]+", "", name.lower())
    aliases = {"白blood细胞": "白细胞", "leukocyte": "白细胞"}
    return aliases.get(text, text)


def apply_teacher_feedback(state: AppState, message: str) -> IntegrationState:
    state.integration.conversation.append({"role": "teacher", "content": message, "time": datetime.utcnow().isoformat()})
    lowered = message.lower()
    for decision in state.integration.decisions:
        names = [node.name for node in state.integration.nodes if node.id == decision.result_node or node.id in decision.affected_nodes]
        matched = any(name and name in message for name in names)
        if matched and any(keyword in lowered or keyword in message for keyword in ["保留", "不应该删除", "keep"]):
            decision.status = "overridden"
            decision.reason = f"教师反馈要求保留相关知识点：{message}"
        if matched and any(keyword in message for keyword in ["分开", "拆分", "不是同一个"]):
            decision.status = "overridden"
            decision.reason = f"教师反馈要求拆分该整合决策：{message}"
    state.integration.conversation.append({"role": "assistant", "content": "已记录反馈，并将匹配到的整合决策标记为教师覆盖。", "time": datetime.utcnow().isoformat()})
    state.integration.updated_at = datetime.utcnow().isoformat()
    return state.integration
