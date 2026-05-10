from __future__ import annotations

import hashlib
import re
from collections import Counter

from .llm import llm_client
from .schemas import Chapter, GraphEdge, KnowledgeNode, Textbook, TextbookGraph


RELATION_TYPES = {"prerequisite", "parallel", "contains", "applies_to"}
STOPWORDS = set("的是和与及在对中为以由了其一个一种进行通过可以主要相关具有包括发生形成作用系统组织细胞".split())


async def build_graph_for_textbook(textbook: Textbook, use_llm: bool = True, llm_chapter_limit: int = 6, max_chapters: int = 80) -> TextbookGraph:
    nodes: list[KnowledgeNode] = []
    edges: list[GraphEdge] = []
    seen_names: set[str] = set()
    chapters = select_representative_chapters(textbook.chapters, max_chapters=max_chapters)
    for chapter_index, chapter in enumerate(chapters):
        should_use_llm = use_llm and chapter_index < llm_chapter_limit and len(chapter.content) <= 12000
        chapter_nodes, chapter_edges = await extract_chapter_graph(textbook, chapter, use_llm=should_use_llm)
        for node in chapter_nodes:
            key = normalize_name(node.name)
            if key in seen_names:
                continue
            seen_names.add(key)
            nodes.append(node)
        edges.extend(chapter_edges)
    node_ids = {node.id for node in nodes}
    edges = [edge for edge in edges if edge.source in node_ids and edge.target in node_ids]
    return TextbookGraph(textbook_id=textbook.textbook_id, nodes=nodes, edges=dedupe_edges(edges))


async def extract_chapter_graph(textbook: Textbook, chapter: Chapter, use_llm: bool = True) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    if use_llm and llm_client.configured and chapter.content.strip():
        try:
            return await extract_with_llm(textbook, chapter)
        except Exception:
            pass
    return extract_heuristic(textbook, chapter)


async def extract_with_llm(textbook: Textbook, chapter: Chapter) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    content = chapter.content[:4500]
    system = (
        "你是通用教材知识图谱抽取器，适用于不同学科的课程材料。只输出 JSON。"
        "从一个章节中抽取 4-8 个可独立讲授的核心知识点和关系，关系类型只允许 "
        "prerequisite, parallel, contains, applies_to。"
    )
    user = f"""
教材：{textbook.title}
章节：{chapter.title}
起始页：{chapter.page_start}

输出格式：
{{
  "nodes": [
    {{"name": "概念名", "definition": "一句话定义", "category": "核心概念", "page": {chapter.page_start}, "source_text": "原文短句"}}
  ],
  "edges": [
    {{"source": "概念名", "target": "概念名", "relation_type": "contains", "description": "关系说明"}}
  ]
}}

章节内容：
{content}
"""
    data = await llm_client.chat_json(system, user, timeout=12)
    raw_nodes = data.get("nodes", []) if isinstance(data, dict) else []
    raw_edges = data.get("edges", []) if isinstance(data, dict) else []
    nodes: list[KnowledgeNode] = []
    name_to_id: dict[str, str] = {}
    for raw in raw_nodes[:10]:
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        node_id = make_node_id(textbook.textbook_id, chapter.chapter_id, name)
        name_to_id[name] = node_id
        nodes.append(
            KnowledgeNode(
                id=node_id,
                name=name[:40],
                definition=str(raw.get("definition", "")).strip()[:240] or f"{name} 是本章涉及的核心知识点。",
                category=str(raw.get("category", "核心概念")).strip()[:20] or "核心概念",
                chapter=chapter.title,
                page=int(raw.get("page") or chapter.page_start),
                textbook_id=textbook.textbook_id,
                textbook_title=textbook.title,
                source_text=str(raw.get("source_text", "")).strip()[:260],
            )
        )
    edges: list[GraphEdge] = []
    for raw in raw_edges[:12]:
        relation_type = str(raw.get("relation_type", "")).strip()
        if relation_type not in RELATION_TYPES:
            continue
        source = name_to_id.get(str(raw.get("source", "")).strip())
        target = name_to_id.get(str(raw.get("target", "")).strip())
        if source and target and source != target:
            edges.append(GraphEdge(source=source, target=target, relation_type=relation_type, description=str(raw.get("description", ""))[:160]))
    if nodes and not edges:
        edges = sequential_edges(nodes)
    return nodes, edges


def extract_heuristic(textbook: Textbook, chapter: Chapter) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    keywords = find_keywords(chapter.content)
    nodes: list[KnowledgeNode] = []
    for keyword in keywords[:8]:
        source = find_source_sentence(chapter.content, keyword)
        node_id = make_node_id(textbook.textbook_id, chapter.chapter_id, keyword)
        nodes.append(
            KnowledgeNode(
                id=node_id,
                name=keyword,
                definition=source[:220] or f"{keyword} 是 {chapter.title} 中反复出现的核心知识点。",
                category="核心概念",
                chapter=chapter.title,
                page=chapter.page_start,
                textbook_id=textbook.textbook_id,
                textbook_title=textbook.title,
                source_text=source[:260],
            )
        )
    return nodes, sequential_edges(nodes)


def find_keywords(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9（）()]{2,12}", text)
    cleaned = []
    for item in candidates:
        if len(item) < 3 or item in STOPWORDS:
            continue
        if any(word in item for word in STOPWORDS) and len(item) <= 4:
            continue
        cleaned.append(item.strip("，。；：、"))
    counts = Counter(cleaned)
    return [word for word, _ in counts.most_common(12)]


def find_source_sentence(text: str, keyword: str) -> str:
    for sentence in re.split(r"[。！？\n]", text):
        if keyword in sentence and len(sentence.strip()) > 8:
            return sentence.strip()
    return ""


def sequential_edges(nodes: list[KnowledgeNode]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for left, right in zip(nodes, nodes[1:]):
        edges.append(
            GraphEdge(
                source=left.id,
                target=right.id,
                relation_type="parallel",
                description=f"{left.name} 与 {right.name} 同属本章核心知识点",
            )
        )
    return edges


def dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple[str, str, str]] = set()
    result: list[GraphEdge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.relation_type)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def normalize_name(name: str) -> str:
    return re.sub(r"\W+", "", name.lower())


def make_node_id(textbook_id: str, chapter_id: str, name: str) -> str:
    digest = hashlib.sha1(f"{textbook_id}:{chapter_id}:{name}".encode("utf-8")).hexdigest()[:10]
    return f"node_{digest}"


def select_representative_chapters(chapters: list[Chapter], max_chapters: int) -> list[Chapter]:
    useful = [chapter for chapter in chapters if chapter.content.strip()]
    if len(useful) <= max_chapters:
        return useful
    step = len(useful) / max_chapters
    selected: list[Chapter] = []
    seen: set[str] = set()
    for index in range(max_chapters):
        chapter = useful[int(index * step)]
        if chapter.chapter_id in seen:
            continue
        seen.add(chapter.chapter_id)
        selected.append(chapter)
    return selected
