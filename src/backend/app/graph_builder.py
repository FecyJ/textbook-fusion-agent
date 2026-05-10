from __future__ import annotations

import hashlib
import re
from collections import Counter

from .llm import llm_client
from .schemas import Chapter, GraphEdge, KnowledgeNode, Textbook, TextbookGraph


RELATION_TYPES = {"prerequisite", "parallel", "contains", "applies_to"}
STOPWORDS = set("的是和与及在对中为以由了其一个一种进行通过可以主要相关具有包括发生形成作用系统组织细胞".split())
NOISE_PATTERNS = (
    re.compile(r"^表\s*\d+"),
    re.compile(r"^图\s*\d+"),
    re.compile(r"^第[一二三四五六七八九十\d]+[章节篇]?.*"),
    re.compile(r"^\d+[-–]\d+"),
    re.compile(r"^[A-Za-z]{1,3}$"),
    re.compile(r"^[+\-]"),
    re.compile(r".*[A-Za-z][+\-].*"),
    re.compile(r".*\d.*单位时间内.*"),
)
BAD_FRAGMENTS = {
    "见表",
    "因素",
    "本章",
    "本节",
    "思考题",
    "数字资源",
    "二维码",
    "需要指出",
    "值得注意",
    "值得一提",
    "主要",
    "尤其",
    "特别",
    "教材",
    "前言",
    "第版",
    "一流本科",
    "新增",
    "编写",
    "出版社",
    "第一章",
    "第二章",
    "第三章",
    "第四章",
    "第五章",
    "绪论",
    "因此他",
    "公元前",
    "称为",
    "也称",
    "并不",
    "总",
    "属于",
    "组成",
    "底物",
    "最大",
    "一种小",
    "通常指",
    "实质上",
    "胞质侧",
    "招募",
    "转接",
    "生理学家",
    "转录因子",
    "单位时间内",
    "向上为",
    "外向驱动力",
    "内流",
    "外流",
    "进行了",
    "调控特定",
    "便可",
    "可逆性损伤",
    "制不同",
    "垂体促",
}
BAD_PREFIXES = (
    "如",
    "例如",
    "一种",
    "通常指",
    "在",
    "由",
    "对",
    "与",
    "将",
    "使",
    "可",
    "能",
    "和",
    "并",
    "且",
    "以及",
    "具有",
    "含有",
    "激活",
    "致",
    "便",
)
VERB_PHRASE_MARKERS = (
    "参与",
    "调节",
    "促进",
    "抑制",
    "引起",
    "导致",
    "形成",
    "发生",
    "产生",
    "释放",
    "分泌",
    "转运",
    "招募",
    "结合",
    "具有",
    "含有",
    "激活",
    "致",
    "潴留",
    "进行",
    "调控",
)
CONCEPT_SUFFIXES = (
    "概念",
    "理论",
    "定理",
    "方法",
    "现象",
    "机制",
    "过程",
    "反应",
    "调节",
    "系统",
    "结构",
    "功能",
    "细胞",
    "组织",
    "器官",
    "因子",
    "激素",
    "受体",
    "蛋白",
    "酶",
    "通道",
    "电位",
    "反射",
    "循环",
    "血压",
    "血流",
    "神经",
    "动脉",
    "静脉",
    "血管",
    "筋膜",
    "韧带",
    "间隙",
    "窦",
    "腺",
    "管",
    "肌",
    "骨",
)
PERSON_NAME_MARKERS = ("学家", "作者", "教授", "博士", "院士")
PRONOUN_FRAGMENTS = ("该", "这", "此", "其")
SHORT_CONCEPTS = {"稳态", "血型", "血压", "血浆", "血液", "前囟", "后囟", "翼点", "腮腺", "乳房", "肾门", "肝门", "会阴"}
FEW_SHOT_JSON = """
示例：
{
  "nodes": [
    {"name": "静息电位", "definition": "细胞未受刺激时膜两侧存在的稳定电位差。", "category": "核心概念", "page": 35, "source_text": "静息电位是细胞安静状态下膜两侧的电位差。"},
    {"name": "动作电位", "definition": "细胞受刺激后膜电位快速、可逆倒转并传播的过程。", "category": "核心概念", "page": 36, "source_text": "动作电位是在阈刺激作用下产生的快速膜电位变化。"}
  ],
  "edges": [
    {"source": "静息电位", "target": "动作电位", "relation_type": "prerequisite", "description": "理解动作电位需要先掌握静息电位。"}
  ]
}
"""


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
    edges = enrich_relation_diversity(nodes, dedupe_edges(edges))
    return TextbookGraph(textbook_id=textbook.textbook_id, nodes=nodes, edges=edges)


async def extract_chapter_graph(textbook: Textbook, chapter: Chapter, use_llm: bool = True) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    if use_llm and llm_client.configured and chapter.content.strip():
        try:
            nodes, edges = await extract_with_llm(textbook, chapter)
            if nodes:
                return nodes, edges
        except Exception:
            pass
    return extract_heuristic(textbook, chapter)


async def extract_with_llm(textbook: Textbook, chapter: Chapter) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    content = chapter.content[:4500]
    seed_candidates = find_knowledge_candidates(chapter)[:16]
    candidate_lines = "\n".join(
        f"- {candidate.name} | 来源:{candidate.method} | 证据:{candidate.source_text[:90]}"
        for candidate in seed_candidates
    )
    system = (
        "你是通用教材知识图谱抽取器，适用于不同学科的课程材料。只输出 JSON。"
        "从一个章节中抽取 4-8 个可独立讲授的核心知识点和关系。优先从候选知识点列表选择，"
        "只有当章节原文明确支持时才补充候选外知识点。"
        "知识点必须是概念、定理、方法、现象、结构、机制或过程；禁止输出表号、图号、页眉页脚、"
        "残缺括号片段、普通短语、句子残片或“见表11-5”这类引用说明。"
        "关系类型只允许 prerequisite, parallel, contains, applies_to。"
        "prerequisite 表示 source 是学习 target 的必要前置知识。"
        "parallel 表示 source 与 target 是同一层级的平行概念。"
        "contains 表示 source 是上位概念，target 是组成部分或下位概念。"
        "applies_to 表示 source 是方法、机制、工具或知识点，target 是其应用对象或场景。"
        "边的 source/target 必须使用节点 name，不要使用 id。"
    )
    user = f"""
教材：{textbook.title}
章节：{chapter.title}
起始页：{chapter.page_start}

候选知识点（已由程序预清洗，优先从中选择）：
{candidate_lines or "无候选；请仅从章节正文中抽取非常明确的核心知识点。"}

输出格式：
{{
  "nodes": [
    {{"name": "概念名", "definition": "一句话定义", "category": "核心概念", "page": {chapter.page_start}, "source_text": "原文短句"}}
  ],
  "edges": [
    {{"source": "概念名", "target": "概念名", "relation_type": "contains", "description": "关系说明"}}
  ]
}}

关系类型定义：
- prerequisite: A -> B 表示学习 B 之前必须先掌握 A。
- parallel: A -> B 表示 A 与 B 是同层级并列知识点。
- contains: A -> B 表示 A 包含 B，A 是上位概念。
- applies_to: A -> B 表示 A 应用于 B，B 是应用场景或对象。

{FEW_SHOT_JSON}

章节内容：
{content}
"""
    data = await llm_client.chat_json(system, user, timeout=12)
    raw_nodes = data.get("nodes", []) if isinstance(data, dict) else []
    raw_edges = data.get("edges", []) if isinstance(data, dict) else []
    nodes: list[KnowledgeNode] = []
    name_to_id: dict[str, str] = {}
    for raw in raw_nodes[:10]:
        candidate = validate_candidate_name(str(raw.get("name", "")).strip(), chapter.content)
        if not candidate:
            continue
        name = candidate.name
        source_text = str(raw.get("source_text", "")).strip()[:260]
        if source_text and looks_like_noise_source(source_text):
            source_text = find_source_sentence(chapter.content, name)
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
                source_text=source_text,
                quality_score=candidate.quality_score,
                extraction_method="llm",
                warnings=candidate.warnings,
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
        edges = infer_relation_edges(nodes)
    return nodes, edges


def extract_heuristic(textbook: Textbook, chapter: Chapter) -> tuple[list[KnowledgeNode], list[GraphEdge]]:
    candidates = find_knowledge_candidates(chapter)
    nodes: list[KnowledgeNode] = []
    for candidate in candidates[:10]:
        keyword = candidate.name
        source = candidate.source_text or find_source_sentence(chapter.content, keyword)
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
                quality_score=candidate.quality_score,
                extraction_method=candidate.method,
                warnings=candidate.warnings,
            )
        )
    return nodes, infer_relation_edges(nodes)


class Candidate:
    def __init__(self, name: str, source_text: str, method: str, quality_score: float, warnings: list[str] | None = None) -> None:
        self.name = name
        self.source_text = source_text
        self.method = method
        self.quality_score = quality_score
        self.warnings = warnings or []


def find_knowledge_candidates(chapter: Chapter) -> list[Candidate]:
    text = normalize_graph_text(chapter.content)
    candidates: list[Candidate] = []
    candidates.extend(extract_parenthetical_terms(text))
    candidates.extend(extract_definition_terms(text))
    candidates.extend(extract_heading_terms(text))
    candidates.extend(extract_frequency_terms(text))
    return rank_candidates(dedupe_candidates(candidates))


def normalize_graph_text(text: str) -> str:
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_parenthetical_terms(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    patterns = [
        r"([\u4e00-\u9fff][\u4e00-\u9fff·\-]{1,12})[（(][A-Za-z][A-Za-z0-9+\- /,，]{1,50}[）)]",
        r"([\u4e00-\u9fff][\u4e00-\u9fff·\-]{1,12})[（(][\u4e00-\u9fff]{1,12}(?:条件下|状态下|阶段|类型|形式)?[）)]",
        r"[A-Za-z][A-Za-z0-9+\- /]{1,50}[，,]\s*([\u4e00-\u9fff]{2,12})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(1)
            source = sentence_around(text, match.start(), match.end())
            candidate = validate_candidate_name(raw, text)
            if candidate:
                candidates.append(Candidate(candidate.name, source, "term_annotation", candidate.quality_score + 0.08, candidate.warnings))
    return candidates


def extract_definition_terms(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    pattern = r"(?:^|[。；\n])([\u4e00-\u9fff][\u4e00-\u9fff·\-]{1,10})(?:是指|是|指|称为|又称|定义为)"
    for match in re.finditer(pattern, text):
        source = sentence_around(text, match.start(), match.end())
        candidate = validate_candidate_name(match.group(1), text)
        if candidate:
            candidates.append(Candidate(candidate.name, source, "definition_sentence", candidate.quality_score + 0.12, candidate.warnings))
    return candidates


def extract_heading_terms(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for line in text.splitlines():
        stripped = re.sub(r"^[（(]?[一二三四五六七八九十\d]+[）)、.．]\s*", "", line.strip())
        stripped = re.sub(r"^第[一二三四五六七八九十\d]+节\s*[|｜]?\s*", "", stripped)
        if not 2 <= len(stripped) <= 18:
            continue
        candidate = validate_candidate_name(stripped, text)
        if candidate:
            candidates.append(Candidate(candidate.name, line.strip(), "heading", candidate.quality_score + 0.04, candidate.warnings))
    return candidates


def extract_frequency_terms(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    pattern = rf"([\u4e00-\u9fff]{{1,10}}(?:{'|'.join(map(re.escape, CONCEPT_SUFFIXES))}))"
    counts = Counter(match.group(1) for match in re.finditer(pattern, text))
    for raw, count in counts.most_common(32):
        candidate = validate_candidate_name(raw, text)
        if candidate and count >= 2:
            source = find_source_sentence(text, candidate.name)
            score = candidate.quality_score + min(0.16, count * 0.03)
            candidates.append(Candidate(candidate.name, source, "frequency_term", score, candidate.warnings))
    return candidates


def validate_candidate_name(raw_name: str, chapter_text: str = "") -> Candidate | None:
    name = clean_candidate_name(raw_name)
    warnings: list[str] = []
    if not name:
        return None
    if any(pattern.search(name) for pattern in NOISE_PATTERNS):
        return None
    if any(fragment in name for fragment in BAD_FRAGMENTS):
        return None
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9·+\-]+", name):
        return None
    if re.fullmatch(r"[A-Za-z0-9+\-]+", name):
        return None
    if len(name) < 2 or len(name) > 14:
        return None
    if name in STOPWORDS:
        return None
    if any(marker in name for marker in PERSON_NAME_MARKERS):
        return None
    if any(fragment in name for fragment in PRONOUN_FRAGMENTS) and any(marker in name for marker in VERB_PHRASE_MARKERS):
        return None
    if re.search(r"[A-Za-z]", name) and re.search(r"[\u4e00-\u9fff]", name) and not re.fullmatch(r"[A-Za-z0-9+\-·]+", name):
        return None
    if name.startswith(BAD_PREFIXES) and not name.endswith(CONCEPT_SUFFIXES):
        return None
    if name.endswith(("（", "(", "需", "见", "和", "与", "的", "为", "在", "中", "及", "或", "等")):
        warnings.append("trimmed_fragment")
        name = name.rstrip("（(需见和与的为在中及或等")
    if not name or len(name) < 2:
        return None
    if name.startswith(("因素", "这", "该", "其", "此", "上述", "下列", "本章", "本节")):
        return None
    if name.startswith(("称为", "也称", "简称", "因此", "约公元", "第一章", "第二章", "第三章", "第四章")):
        return None
    if any(prefix in name for prefix in ("第一章", "第二章", "第三章", "第四章", "绪论")):
        return None
    if any(marker in name for marker in ("是", "的", "并不", "之", "所", "属于", "组成", "总")) and name not in SHORT_CONCEPTS:
        return None
    if any(marker in name for marker in VERB_PHRASE_MARKERS) and not name.endswith(CONCEPT_SUFFIXES):
        return None
    if len(name) <= 2 and name not in SHORT_CONCEPTS and not name.endswith(("肌", "骨", "膜", "管", "腺", "窦")):
        return None
    if chapter_text and name not in chapter_text:
        warnings.append("not_in_source")
    quality = score_candidate_name(name, warnings)
    if quality < 0.52:
        return None
    return Candidate(name=name, source_text="", method="validated", quality_score=round(min(1.0, quality), 3), warnings=warnings)


def clean_candidate_name(raw_name: str) -> str:
    name = re.sub(r"\s+", "", raw_name.strip())
    name = re.sub(r"[：:，,。；;、]+$", "", name)
    name = name.strip("[]【】“”\"' ")
    name = re.sub(r"^(?:如|例如|即|其中|所谓|一种|通常指|和|与|及|以及|由|对|将|使|具有|含有)", "", name)
    name = re.sub(r"^.*?(?=电压钳|膜片钳|钠通道|钾通道|钙通道)", "", name)
    name = re.sub(r"^.*由(?=[\u4e00-\u9fff]{1,10}(?:细胞|小球|蛋白|通道|受体|激素|系统|结构|组织|器官))", "", name)
    name = re.sub(r"(?:实质上|通常指|主要是|可见|需)$", "", name)
    if "（" in name and "）" not in name:
        name = name.split("（", 1)[0]
    if "(" in name and ")" not in name:
        name = name.split("(", 1)[0]
    if "（" in name and "）" in name:
        name = re.sub(r"（[^）]{0,16}）", "", name)
    if "(" in name and ")" in name:
        name = re.sub(r"\([^)]{0,24}\)", "", name)
    name = trim_to_known_concept_suffix(name)
    name = re.sub(r"^.*?(?=肝细胞|红细胞|白细胞|血小板|胰岛素|肾上腺素|甲状腺|腮腺|面神经|三叉神经)", "", name)
    return name


def trim_to_known_concept_suffix(name: str) -> str:
    best = ""
    for suffix in CONCEPT_SUFFIXES:
        index = name.find(suffix)
        if index < 0:
            continue
        candidate = name[: index + len(suffix)]
        if len(candidate) > len(best):
            best = candidate
    if best and len(best) >= 2 and len(best) < len(name):
        return best
    return name


def score_candidate_name(name: str, warnings: list[str]) -> float:
    score = 0.58
    if name.endswith(CONCEPT_SUFFIXES):
        score += 0.18
    if name in SHORT_CONCEPTS:
        score += 0.12
    if 3 <= len(name) <= 8:
        score += 0.08
    if re.search(r"\d", name):
        score -= 0.22
    if warnings:
        score -= 0.08 * len(warnings)
    return score


def sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind("。", 0, start), text.rfind("\n", 0, start), text.rfind("；", 0, start))
    right_candidates = [index for index in (text.find("。", end), text.find("\n", end), text.find("；", end)) if index >= 0]
    right = min(right_candidates) if right_candidates else min(len(text), end + 180)
    return text[left + 1 : right + 1].strip()


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    by_name: dict[str, Candidate] = {}
    for candidate in candidates:
        previous = by_name.get(candidate.name)
        if not previous or candidate.quality_score > previous.quality_score:
            by_name[candidate.name] = candidate
    return list(by_name.values())


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    method_rank = {"definition_sentence": 3, "term_annotation": 2, "heading": 1, "frequency_term": 0}
    return sorted(candidates, key=lambda item: (item.quality_score, method_rank.get(item.method, 0), len(item.source_text)), reverse=True)


def find_keywords(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9（）()]{2,12}", text)
    cleaned = []
    for item in candidates:
        candidate = validate_candidate_name(item, text)
        if not candidate:
            continue
        cleaned.append(candidate.name)
    counts = Counter(cleaned)
    return [word for word, _ in counts.most_common(12)]


def find_source_sentence(text: str, keyword: str) -> str:
    for sentence in re.split(r"[。！？\n]", text):
        if keyword in sentence and len(sentence.strip()) > 8:
            return sentence.strip()
    return ""


def infer_relation_edges(nodes: list[KnowledgeNode]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for left_index, left in enumerate(nodes):
        for right in nodes[left_index + 1 :]:
            relation = infer_relation(left, right)
            if relation:
                edges.append(relation)
            if len(edges) >= max(4, len(nodes)):
                return dedupe_edges(edges)
    return dedupe_edges(edges)


def enrich_relation_diversity(nodes: list[KnowledgeNode], edges: list[GraphEdge]) -> list[GraphEdge]:
    if len(nodes) < 2:
        return edges
    relation_counts = Counter(edge.relation_type for edge in edges)
    if len(relation_counts) >= 3 and relation_counts.get("parallel", 0) <= max(8, len(edges) * 0.85):
        return edges
    existing = {(edge.source, edge.target, edge.relation_type) for edge in edges}
    additions: list[GraphEdge] = []
    for left_index, left in enumerate(nodes[:80]):
        for right in nodes[left_index + 1 : 80]:
            relation = infer_relation(left, right)
            if not relation or relation.relation_type == "parallel":
                continue
            key = (relation.source, relation.target, relation.relation_type)
            if key in existing:
                continue
            existing.add(key)
            additions.append(relation)
            if len(additions) >= 24:
                return dedupe_edges(edges + additions)
    return dedupe_edges(edges + additions)


def infer_relation(left: KnowledgeNode, right: KnowledgeNode) -> GraphEdge | None:
    text = relation_context(left, right)
    shared_source = f"{left.source_text}\n{right.source_text}"
    if contains_evidence(left.name, right.name, text):
        return GraphEdge(source=left.id, target=right.id, relation_type="contains", description=f"{left.name} 包含或统摄 {right.name}。")
    if contains_evidence(right.name, left.name, text):
        return GraphEdge(source=right.id, target=left.id, relation_type="contains", description=f"{right.name} 包含或统摄 {left.name}。")
    if prerequisite_evidence(left.name, right.name, text):
        return GraphEdge(source=left.id, target=right.id, relation_type="prerequisite", description=f"理解 {right.name} 之前需要掌握 {left.name}。")
    if prerequisite_evidence(right.name, left.name, text):
        return GraphEdge(source=right.id, target=left.id, relation_type="prerequisite", description=f"理解 {left.name} 之前需要掌握 {right.name}。")
    if applies_evidence(left.name, right.name, text):
        return GraphEdge(source=left.id, target=right.id, relation_type="applies_to", description=f"{left.name} 可应用于 {right.name}。")
    if applies_evidence(right.name, left.name, text):
        return GraphEdge(source=right.id, target=left.id, relation_type="applies_to", description=f"{right.name} 可应用于 {left.name}。")
    if parallel_evidence(left, right, shared_source):
        return GraphEdge(source=left.id, target=right.id, relation_type="parallel", description=f"{left.name} 与 {right.name} 是同层级相关知识点。")
    return None


def contains_evidence(parent: str, child: str, text: str) -> bool:
    return bool(
        re.search(rf"{re.escape(parent)}[^。；\n]{{0,28}}(?:包括|包含|分为|由.+组成|可分为)[^。；\n]{{0,36}}{re.escape(child)}", text)
        or re.search(rf"{re.escape(child)}[^。；\n]{{0,18}}(?:属于|是.+组成部分|为.+之一)[^。；\n]{{0,24}}{re.escape(parent)}", text)
        or is_likely_hierarchy(parent, child)
    )


def prerequisite_evidence(source: str, target: str, text: str) -> bool:
    return bool(
        re.search(rf"(?:理解|掌握|学习)[^。；\n]{{0,18}}{re.escape(target)}[^。；\n]{{0,28}}(?:需要|必须|先)[^。；\n]{{0,28}}{re.escape(source)}", text)
        or re.search(rf"{re.escape(source)}[^。；\n]{{0,28}}(?:基础|前提)[^。；\n]{{0,28}}{re.escape(target)}", text)
    )


def applies_evidence(source: str, target: str, text: str) -> bool:
    return bool(
        re.search(rf"{re.escape(source)}[^。；\n]{{0,28}}(?:应用于|用于|参与|调节|影响|抑制|促进)[^。；\n]{{0,36}}{re.escape(target)}", text)
        or re.search(rf"{re.escape(target)}[^。；\n]{{0,28}}(?:依赖|通过|利用)[^。；\n]{{0,36}}{re.escape(source)}", text)
    )


def parallel_evidence(left: KnowledgeNode, right: KnowledgeNode, text: str) -> bool:
    if left.chapter != right.chapter:
        return False
    if re.search(rf"{re.escape(left.name)}[^。；\n]{{0,18}}(?:和|与|及|或|、)[^。；\n]{{0,18}}{re.escape(right.name)}", text):
        return True
    if re.search(rf"{re.escape(right.name)}[^。；\n]{{0,18}}(?:和|与|及|或|、)[^。；\n]{{0,18}}{re.escape(left.name)}", text):
        return True
    if left.category == right.category and left.extraction_method == "heading" and right.extraction_method == "heading":
        return True
    if left.name.endswith(CONCEPT_SUFFIXES) and right.name.endswith(CONCEPT_SUFFIXES):
        return left.name[-2:] == right.name[-2:] or left.name[-1:] == right.name[-1:]
    return False


def relation_context(left: KnowledgeNode, right: KnowledgeNode) -> str:
    return "。".join(
        part
        for part in (
            left.name,
            left.definition,
            left.source_text,
            right.name,
            right.definition,
            right.source_text,
        )
        if part
    )


def is_likely_hierarchy(parent: str, child: str) -> bool:
    if parent == child or len(parent) >= len(child):
        return False
    parent_suffixes = ("系统", "组织", "结构", "过程", "机制", "反应", "调节", "循环", "血管", "神经")
    return parent.endswith(parent_suffixes) and child.endswith(parent[-2:])


def looks_like_noise_source(source_text: str) -> bool:
    compact = re.sub(r"\s+", "", source_text)
    if any(pattern.search(compact) for pattern in NOISE_PATTERNS):
        return True
    return any(fragment in compact for fragment in ("见表", "见图", "思考题", "二维码", "数字资源"))


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
    useful = [chapter for chapter in chapters if is_useful_chapter(chapter)]
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


def is_useful_chapter(chapter: Chapter) -> bool:
    if not chapter.content.strip():
        return False
    if chapter.page_start <= 23 and any(term in chapter.content for term in ("前言", "教材", "出版", "编写", "数字资源")):
        return False
    if re.fullmatch(r".+_\d+", chapter.title):
        return False
    return True
