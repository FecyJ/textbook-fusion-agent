from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import re
import statistics
import time
from typing import Iterable

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .rag import (
    RagConfig,
    build_rag_index,
    clean_answer_text,
    evidence_answer,
    exact_phrase_scores,
    load_rag_config,
    query_terms,
    tokenize,
)
from .schemas import AppState, KnowledgeNode, RagChunk, Textbook
from .storage import CACHE_DIR, ROOT_DIR, load_state


BENCHMARK_DIR = CACHE_DIR / "rag_benchmark"
BENCHMARK_LATEST_PATH = BENCHMARK_DIR / "latest.json"
BENCHMARK_DOC_PATH = ROOT_DIR / "docs" / "RAG Benchmark.md"
AGENT_ARCH_DOC_PATH = ROOT_DIR / "docs" / "Agent 架构说明.md"
RAG_DEFAULTS_PATH = ROOT_DIR / "src" / "backend" / "app" / "rag_defaults.json"


@dataclass(frozen=True)
class BenchmarkQuestion:
    question_id: str
    question: str
    kind: str
    expected_textbook: str
    expected_chapter: str
    expected_page: int
    expected_chunk_id: str
    expected_terms: list[str]
    answer_hint: str

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkMetrics:
    config_name: str
    chunk_size: int
    sparse_model: str
    phrase_rerank: bool
    recall_at_5: float
    mrr: float
    answer_accuracy: float
    citation_accuracy: float
    evidence_hit_rate: float
    avg_latency_ms: float
    avg_context_tokens: float
    estimated_token_cost: int
    question_count: int
    config: RagConfig

    def model_dump(self) -> dict[str, object]:
        payload = asdict(self)
        payload["config"] = self.config.model_dump()
        return payload


QUESTION_TEMPLATES = {
    "definition": "{term}这个概念的核心定义是什么？",
    "source": "{term}主要出现在哪一章？请给出原文依据。",
    "fact": "教材中关于{term}的关键表述是什么？",
    "compare": "{term}与同一章节中的相关概念有什么联系？",
    "reasoning": "根据教材上下文，{term}为什么重要？请基于原文说明。",
    "cross_textbook": "不同教材中关于{term}的表述在哪里？请给出可追溯来源。",
}

COURSE_CONCEPT_SEEDS = (
    "内环境",
    "稳态",
    "兴奋性",
    "新陈代谢",
    "神经调节",
    "体液调节",
    "正反馈",
    "负反馈",
    "前馈控制",
    "细胞膜",
    "钠泵",
    "动作电位",
    "阈电位",
    "信号转导",
    "受体",
    "离子通道",
    "红细胞",
    "白细胞",
    "血小板",
    "血液凝固",
    "血浆",
    "心动周期",
    "心输出量",
    "动脉血压",
    "微循环",
    "肾上腺素",
    "胰岛素",
    "胰高血糖素",
    "甲状腺激素",
    "血管升压素",
    "腮腺",
    "腮腺管",
    "三叉神经",
    "面神经",
    "翼静脉丛",
    "海绵窦",
    "颈动脉窦",
    "颈内静脉",
    "胸锁乳突肌",
    "浅筋膜",
    "深筋膜",
    "颈筋膜",
    "膈神经",
    "迷走神经",
    "胸导管",
    "乳房",
    "肝门静脉",
    "肾门",
    "输尿管",
    "前列腺",
    "正中神经",
    "尺神经",
    "桡神经",
    "腓深神经",
)

TERM_STOPWORDS = {
    "主要",
    "尤其",
    "特别",
    "通常",
    "可能",
    "需要",
    "可以",
    "这些",
    "这就",
    "这也",
    "其中",
    "前者",
    "后者",
    "另一种",
    "另一类",
    "因此",
    "由于",
    "如果",
    "教材",
    "版教材",
    "电子教材",
    "新形态教材",
    "研究",
    "功能",
    "活动",
    "观察",
    "解剖",
    "通过",
    "抑制",
    "促进",
    "由于",
    "其中",
    "释放",
    "导致",
    "引起",
    "形成",
    "生成",
    "正常",
    "临床上",
    "上述",
    "式中",
    "根据",
    "启动",
    "激活",
    "测定",
    "刺激",
    "中枢",
    "分别",
    "血中",
    "血浆中",
    "血液中",
    "血浆",
    "血液",
    "受体",
    "蛋白",
    "动脉",
    "静脉",
    "血管",
    "韧带",
    "作用",
    "排出",
    "重要",
    "信息",
    "吸收",
    "调节",
    "状态",
    "出来",
    "分区",
    "第一节",
    "第二节",
    "第三节",
    "第四节",
    "值得注意",
    "但研究目",
    "压均",
    "优化",
    "更多",
    "两侧",
    "浅层结构",
    "整体水平研究",
    "人体生理研究",
    "慢性实验",
    "动物实验",
}
TERM_BLOCKLIST_RE = re.compile(
    r"习近平|总书记|课程思政|教材编写|编写修订|医学教育|人民卫生出版社|科学家们|高等学校|数字资源|思考题|二维码|出版|责任编辑|版权"
)
TERM_SUFFIXES = (
    "神经",
    "动脉",
    "静脉",
    "血管",
    "淋巴结",
    "淋巴",
    "韧带",
    "筋膜",
    "关节",
    "骨",
    "肌",
    "膜",
    "腺",
    "管",
    "细胞",
    "受体",
    "蛋白",
    "激素",
    "酶",
    "因子",
    "电位",
    "反射",
    "系统",
    "组织",
    "器官",
    "循环",
    "血液",
    "血压",
    "通道",
    "小管",
    "小球",
    "髓质",
    "皮质",
    "素",
)
TERM_SUFFIX_PATTERN = "|".join(sorted((re.escape(suffix) for suffix in TERM_SUFFIXES), key=len, reverse=True))
SHORT_TERM_ALLOWLIST = {
    "稳态",
    "血型",
    "血压",
    "血流",
    "血浆",
    "血液",
    "心率",
    "心音",
    "反射",
    "前囟",
    "后囟",
    "舌骨",
    "翼点",
    "乳房",
    "会阴",
    "肾门",
    "肝门",
}
CONCEPT_KEYWORDS = (
    "内环境",
    "内分泌",
    "兴奋性",
    "稳态",
    "反馈",
    "前馈",
    "反射",
    "代谢",
    "凝血",
    "通气",
    "换气",
    "滤过",
    "重吸收",
    "分泌",
    "排卵",
    "生殖",
    "牵涉痛",
)
SOURCE_BLOCKLIST_RE = re.compile(r"习近平|课程思政|教材编写|编写修订|新形态教材|电子教材|人民卫生出版社|版权所有")


def run_benchmark(
    sample_size: int = 30,
    optimize: bool = True,
    write_docs: bool = True,
    state: AppState | None = None,
) -> dict[str, object]:
    state = state or load_state()
    questions = build_question_set(state, sample_size=sample_size)
    configs = candidate_configs() if optimize else {"current": load_rag_config()}
    metrics = [evaluate_config(state, questions, name, config) for name, config in configs.items()]
    best = choose_best(metrics)
    result = {
        "generated_at": datetime.utcnow().isoformat(),
        "question_count": len(questions),
        "questions": [question.model_dump() for question in questions],
        "metrics": [item.model_dump() for item in metrics],
        "best_config_name": best.config_name,
        "best_config": best.config.model_dump(),
    }
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    with BENCHMARK_LATEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    write_best_config(best.config)
    if write_docs:
        write_benchmark_doc(result)
        update_agent_architecture_doc(best)
    return result


def build_question_set(state: AppState, sample_size: int = 30) -> list[BenchmarkQuestion]:
    chunks = state.rag_chunks or build_rag_index(state)
    textbook_by_id = state.textbooks
    source_chunks = [chunk for chunk in chunks if is_benchmark_source_chunk(chunk)]
    if not source_chunks:
        source_chunks = chunks
    term_sources = collect_term_sources(source_chunks)
    seed_terms = seed_terms_by_textbook(source_chunks)
    graph_terms = graph_terms_by_textbook(state)
    candidates: list[BenchmarkQuestion] = []
    append_questions_from_chunks(candidates, source_chunks, sample_size, term_sources, seed_terms)
    if len(candidates) < sample_size:
        append_questions_from_chunks(candidates, source_chunks, sample_size, term_sources, graph_terms)
    if len(candidates) < sample_size:
        append_questions_from_chunks(candidates, source_chunks, sample_size, term_sources)

    if len(candidates) < sample_size:
        candidates.extend(fallback_questions(textbook_by_id, sample_size - len(candidates), len(candidates)))
    return candidates[:sample_size]


def append_questions_from_chunks(
    candidates: list[BenchmarkQuestion],
    chunks: list[RagChunk],
    sample_size: int,
    term_sources: dict[str, set[str]],
    preferred_terms: dict[str, list[str]] | None = None,
) -> None:
    seen_pairs = {(question.expected_chunk_id, question.expected_terms[0]) for question in candidates if question.expected_terms}
    seen_terms = {question.expected_terms[0] for question in candidates if question.expected_terms}
    for chunk in interleave_chunks_by_textbook(chunks):
        terms = terms_for_chunk(chunk, preferred_terms) if preferred_terms else candidate_terms(chunk.text)
        if not terms:
            continue
        for term in terms[:3]:
            pair = (chunk.chunk_id, term)
            if pair in seen_pairs:
                continue
            if term in seen_terms and len(seen_terms) >= sample_size:
                continue
            if term in seen_terms and len(candidates) < int(sample_size * 0.85):
                continue
            seen_pairs.add(pair)
            seen_terms.add(term)
            kind = question_kind(len(candidates), len(term_sources.get(term, set())) > 1)
            candidates.append(
                BenchmarkQuestion(
                    question_id=f"q_{len(candidates) + 1:03d}",
                    question=QUESTION_TEMPLATES[kind].format(term=term),
                    kind=kind,
                    expected_textbook=chunk.textbook,
                    expected_chapter=chunk.chapter,
                    expected_page=chunk.page,
                    expected_chunk_id=chunk.chunk_id,
                    expected_terms=[term],
                    answer_hint=answer_hint(chunk.text, term),
                )
            )
            if len(candidates) >= sample_size:
                return


def graph_terms_by_textbook(state: AppState) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for graph in state.graphs.values():
        terms: list[str] = []
        for node in graph.nodes:
            name = normalize_graph_term(node)
            if name:
                terms.append(name)
        if terms:
            result[graph.textbook_id] = unique_preserve_order(sorted(terms, key=lambda item: (-len(item), item)))
    return result


def normalize_graph_term(node: KnowledgeNode) -> str:
    name = normalize_term(node.name)
    name = clean_graph_term_tail(name)
    if not is_valid_graph_term(name):
        return ""
    if node.source_text and name not in node.source_text:
        return ""
    return name


def is_valid_graph_term(term: str) -> bool:
    if not is_valid_term(term):
        return False
    if term.startswith(("有", "出", "从", "对", "向", "切", "保留", "不能", "型", "组", "左", "右", "上", "下")) and len(term) > 4:
        return False
    if any(fragment in term for fragment in ("损伤", "观察", "解剖", "覆盖", "指尖", "手掌", "进入", "来自", "离断", "追踪", "汇入", "排列", "相续", "受损", "困难", "较多", "危险")):
        return False
    if term in {"系统", "细胞", "组织", "器官", "血管", "神经", "动脉", "静脉", "韧带", "肌", "膜", "腺", "管"}:
        return False
    return True


def clean_graph_term_tail(term: str) -> str:
    for suffix in sorted(TERM_SUFFIXES, key=len, reverse=True):
        index = term.find(suffix)
        if index >= 0:
            return term[: index + len(suffix)]
    return term


def terms_for_chunk(chunk: RagChunk, preferred_terms: dict[str, list[str]] | None) -> list[str]:
    if not preferred_terms:
        return []
    return [term for term in preferred_terms.get(chunk.textbook_id, []) if term in chunk.text]


def collect_term_sources(chunks: list[RagChunk]) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {}
    for chunk in chunks:
        for term in unique_preserve_order([*seed_terms_for_chunk(chunk), *candidate_terms(chunk.text)]):
            sources.setdefault(term, set()).add(chunk.textbook)
    return sources


def seed_terms_by_textbook(chunks: list[RagChunk]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for chunk in chunks:
        for term in seed_terms_for_chunk(chunk):
            result.setdefault(chunk.textbook_id, []).append(term)
    return {textbook_id: unique_preserve_order(terms) for textbook_id, terms in result.items()}


def seed_terms_for_chunk(chunk: RagChunk) -> list[str]:
    return [term for term in COURSE_CONCEPT_SEEDS if term in chunk.text]


def is_benchmark_source_chunk(chunk: RagChunk) -> bool:
    if SOURCE_BLOCKLIST_RE.search(chunk.text):
        return False
    if chunk.page <= 23:
        return False
    if re.fullmatch(r"第[一二三四五六七八九十\d]+章", chunk.chapter.strip()):
        return False
    if re.fullmatch(r".+_\d+", chunk.chapter):
        return False
    return True


def interleave_chunks_by_textbook(chunks: list[RagChunk]) -> list[RagChunk]:
    grouped: dict[str, list[RagChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.textbook_id, []).append(chunk)
    for values in grouped.values():
        values.sort(key=lambda chunk: (chunk.page, chunk.chapter, chunk.chunk_id))
    result: list[RagChunk] = []
    while any(grouped.values()):
        for textbook_id in sorted(grouped):
            if grouped[textbook_id]:
                result.append(grouped[textbook_id].pop(0))
    return result


def candidate_terms(text: str) -> list[str]:
    terms: list[str] = []
    title_terms = re.findall(r"(?:^|\n)\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)])\s*([\u4e00-\u9fff]{2,10})(?:\s|$|[（(])", text)
    patterns = [
        r"([\u4e00-\u9fff][\u4e00-\u9fff·\-]{1,9})[（(][A-Za-z][A-Za-z0-9+\- /,，]+[）)]",
        r"([A-Za-z0-9+\- ]{2,40})[，,]\s*([\u4e00-\u9fff]{2,10})",
        r"(?:^|[，。；：、\s])([\u4e00-\u9fff]{2,8})(?:是指|是指一种|是|称为)",
        r"称为([\u4e00-\u9fff]{2,8})",
    ]
    terms.extend(title_terms)
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            terms.append(match.group(match.lastindex or 1))
    suffix_matches = re.findall(rf"([\u4e00-\u9fff]{{1,8}}(?:{TERM_SUFFIX_PATTERN}))", text)
    terms.extend(term for term in suffix_matches if looks_like_entity_term(term))
    cleaned: list[str] = []
    for term in terms:
        term = normalize_term(term)
        if is_valid_term(term):
            cleaned.append(term)
    return unique_preserve_order(cleaned)


def normalize_term(term: str) -> str:
    term = re.sub(r"^[一-龥]{0,4}(?:其|该|此|为|在|由|使|将|把|被|和|与|及|或|有|从|对|向)", "", term)
    term = term.strip("的一是在和与、，。；：；（）()[]【】")
    term = re.sub(r"^(?:主要|可见|因此|由于|例如|通过|促进|抑制|影响|分泌|释放|进入|来自|这些|后者|前者|其中|一般|正常)", "", term)
    return term.strip("的一是在和与、，。；：；")


def is_valid_term(term: str) -> bool:
    if not (2 <= len(term) <= 10):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]+", term):
        return False
    if term in TERM_STOPWORDS:
        return False
    if TERM_BLOCKLIST_RE.search(term):
        return False
    if re.search(r"第[一二三四五六七八九十\d]+章|图\d*|表\d*|本章|本节|本书", term):
        return False
    if term.startswith(("于", "从", "对", "向", "使", "可", "有", "无", "不能", "促成", "称为", "结合", "分泌", "释放", "观察", "解剖", "保留")):
        return False
    if term.startswith("第"):
        return False
    if term.endswith(("的", "了", "也", "都", "就", "可", "能", "主要", "尤其", "特别", "通常", "中", "时", "对")):
        return False
    if len(term) > 6 and "的" in term:
        return False
    if len(term) > 8 and not term.endswith(("系统", "综合征", "生长因子", "氨酸", "静脉", "动脉", "神经", "激素", "受体")):
        return False
    if len(term) <= 2 and not (term.endswith(("骨", "肌", "膜", "腺", "管", "酶", "素")) or term in SHORT_TERM_ALLOWLIST):
        return False
    return True


def looks_like_entity_term(term: str) -> bool:
    if term in TERM_STOPWORDS:
        return False
    if term.startswith(("有", "从", "对", "向", "使", "将", "其", "此", "该", "于", "在", "和", "与", "可", "不", "被")):
        return False
    if any(marker in term for marker in ("的", "可以", "进行", "观察", "解剖", "损伤", "覆盖", "分泌", "释放")):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]+", term):
        return False
    return term.endswith(TERM_SUFFIXES) or any(keyword in term for keyword in CONCEPT_KEYWORDS)


def fallback_questions(textbooks: dict[str, Textbook], count: int, offset: int) -> list[BenchmarkQuestion]:
    result: list[BenchmarkQuestion] = []
    for textbook in textbooks.values():
        for chapter in textbook.chapters:
            terms = candidate_terms(chapter.content) or query_terms(chapter.title)
            if not terms:
                continue
            term = terms[0]
            result.append(
                BenchmarkQuestion(
                    question_id=f"q_{offset + len(result) + 1:03d}",
                    question=QUESTION_TEMPLATES["fact"].format(term=term),
                    kind="fact",
                    expected_textbook=textbook.title,
                    expected_chapter=chapter.title,
                    expected_page=chapter.page_start,
                    expected_chunk_id="",
                    expected_terms=[term],
                    answer_hint=answer_hint(chapter.content, term),
                )
            )
            if len(result) >= count:
                return result
    return result


def evaluate_config(
    state: AppState,
    questions: list[BenchmarkQuestion],
    config_name: str,
    config: RagConfig,
) -> BenchmarkMetrics:
    eval_index = build_eval_retriever(state, config)
    reciprocal_ranks: list[float] = []
    recalls: list[float] = []
    citation_hits: list[float] = []
    evidence_hits: list[float] = []
    latencies: list[float] = []
    context_tokens: list[float] = []
    for question in questions:
        started = time.perf_counter()
        ranked = eval_index.retrieve(question.question)
        answer = evidence_answer(question.question, ranked) if ranked else ""
        latencies.append((time.perf_counter() - started) * 1000)
        context_tokens.append(estimate_context_tokens(question.question, ranked))
        rank = first_relevant_rank(ranked, question)
        recalls.append(1.0 if rank else 0.0)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        citation_hits.append(1.0 if ranked and chunk_matches(ranked[0][0], question) else 0.0)
        evidence_hits.append(1.0 if answer_contains_evidence(answer, question) else 0.0)
    return BenchmarkMetrics(
        config_name=config_name,
        chunk_size=config.chunk_size,
        sparse_model=config.sparse_model,
        phrase_rerank=config.phrase_rerank,
        recall_at_5=round(mean(recalls), 4),
        mrr=round(mean(reciprocal_ranks), 4),
        answer_accuracy=round(mean(evidence_hits), 4),
        citation_accuracy=round(mean(citation_hits), 4),
        evidence_hit_rate=round(mean(evidence_hits), 4),
        avg_latency_ms=round(mean(latencies), 2),
        avg_context_tokens=round(mean(context_tokens), 2),
        estimated_token_cost=int(sum(context_tokens)),
        question_count=len(questions),
        config=config,
    )


@dataclass
class EvalRetriever:
    chunks: list[RagChunk]
    config: RagConfig
    vectorizer: TfidfVectorizer
    matrix: object
    bm25: BM25Okapi

    def retrieve(self, question: str) -> list[tuple[RagChunk, float]]:
        question_vector = self.vectorizer.transform([question])
        tfidf_scores = cosine_similarity(question_vector, self.matrix).flatten()
        bm25_scores = self.bm25.get_scores(tokenize(question))
        max_bm25 = max(bm25_scores) if len(bm25_scores) else 0
        if max_bm25:
            bm25_scores = bm25_scores / max_bm25
        phrase_scores = exact_phrase_scores(self.chunks, question) if self.config.phrase_rerank else np.zeros(len(self.chunks), dtype=float)
        combined = self.config.tfidf_weight * tfidf_scores + self.config.bm25_weight * bm25_scores + self.config.phrase_weight * phrase_scores
        order = combined.argsort()[::-1][: self.config.top_k]
        return [(self.chunks[index], float(combined[index])) for index in order if combined[index] > self.config.min_score]


def build_eval_retriever(state: AppState, config: RagConfig) -> EvalRetriever:
    chunks = build_rag_index_for_eval(state, config)
    corpus = [chunk.text for chunk in chunks]
    if config.sparse_model == "char_2_5":
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)
    else:
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(corpus)
    bm25 = BM25Okapi([tokenize(text) for text in corpus])
    return EvalRetriever(chunks=chunks, config=config, vectorizer=vectorizer, matrix=matrix, bm25=bm25)


def build_rag_index_for_eval(state: AppState, config: RagConfig) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    for textbook in state.textbooks.values():
        if textbook.status != "completed":
            continue
        for chapter in textbook.chapters:
            for index, chunk_text in enumerate(split_for_eval(chapter.content, config.chunk_size, config.overlap), start=1):
                chunks.append(
                    RagChunk(
                        chunk_id=f"{textbook.textbook_id}_{chapter.chapter_id}_{index:04d}",
                        textbook_id=textbook.textbook_id,
                        textbook=textbook.title,
                        chapter=chapter.title,
                        page=chapter.page_start,
                        text=chunk_text,
                        char_count=len(chunk_text),
                    )
                )
    return chunks


def split_for_eval(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def candidate_configs() -> dict[str, RagConfig]:
    configs: dict[str, RagConfig] = {}
    for chunk_size in (300, 500, 800, 1200):
        overlaps = (60, 80, 100)
        for overlap in overlaps:
            if overlap >= chunk_size:
                continue
            for sparse_model in ("char_wb_2_4", "char_2_5"):
                for phrase_rerank in (False, True):
                    name = f"chunk{chunk_size}_ov{overlap}_{sparse_model}_{'phrase' if phrase_rerank else 'base'}"
                    configs[name] = RagConfig(
                        chunk_size=chunk_size,
                        overlap=overlap,
                        top_k=5,
                        sparse_model=sparse_model,
                        tfidf_weight=0.48 if phrase_rerank else 0.6,
                        bm25_weight=0.27 if phrase_rerank else 0.4,
                        phrase_weight=0.25 if phrase_rerank else 0,
                        phrase_rerank=phrase_rerank,
                        min_score=0.005,
                    ).normalized()
    return configs


def choose_best(metrics: list[BenchmarkMetrics]) -> BenchmarkMetrics:
    return max(metrics, key=lambda item: (item.recall_at_5, item.citation_accuracy, item.answer_accuracy, item.mrr, -item.avg_latency_ms))


def write_best_config(config: RagConfig) -> None:
    with RAG_DEFAULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config.model_dump(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_benchmark_doc(result: dict[str, object]) -> None:
    metrics = [
        BenchmarkMetrics(config=RagConfig(**item["config"]), **{key: value for key, value in item.items() if key != "config"})
        for item in result["metrics"]
    ]
    questions = [BenchmarkQuestion(**item) for item in result["questions"]]
    best_name = str(result["best_config_name"])
    lines = [
        "# RAG Benchmark",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 题目数量：{result['question_count']}",
        f"- 最优配置：`{best_name}`",
        "- 数据来源：当前已上传并解析的教材状态缓存。",
        "",
        "本 benchmark 按赛题要求自建 20-50 道题，题型覆盖事实、对比、推理/关联和跨教材来源定位；每题保留预期教材、章节、页码、chunk id、关键词和答案提示作为 ground truth。",
        "",
        "## 题集 Ground Truth",
        "",
        "| ID | 题型 | 问题 | 预期来源 | 关键词 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for question in questions:
        source = f"{question.expected_textbook} / {question.expected_chapter} / 第{question.expected_page}页"
        lines.append(
            f"| {question.question_id} | {question.kind} | {question.question} | {source} | {', '.join(question.expected_terms)} |"
        )
    lines.extend(
        [
            "",
            "## 指标",
            "",
            "| 配置 | Chunk | 检索模型 | Rerank | Recall@5 | MRR | 答案准确率 | 引用命中率 | 证据命中率 | 平均耗时(ms) | 平均上下文Tokens | 总Token成本 |",
            "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in sorted(metrics, key=lambda metric: metric.config_name):
        lines.append(
            f"| {item.config_name} | {item.chunk_size} | {item.sparse_model} | {str(item.phrase_rerank).lower()} | "
            f"{item.recall_at_5:.4f} | {item.mrr:.4f} | {item.answer_accuracy:.4f} | "
            f"{item.citation_accuracy:.4f} | {item.evidence_hit_rate:.4f} | {item.avg_latency_ms:.2f} | "
            f"{item.avg_context_tokens:.2f} | {item.estimated_token_cost} |"
        )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "Benchmark 自动选择 Recall@5、引用命中率、答案准确率和 MRR 综合最优的配置，并写入 `src/backend/app/rag_defaults.json`。",
            "Token 成本为基于注入检索上下文长度的离线估算，避免评测过程额外调用 LLM。",
            "运行产物保存在 `data/cache/rag_benchmark/latest.json`，用于复查每道题的 ground truth 和配置对比。",
            "",
        ]
    )
    BENCHMARK_DOC_PATH.write_text("\n".join(lines), encoding="utf-8")


def update_agent_architecture_doc(best: BenchmarkMetrics) -> None:
    start_marker = "<!-- RAG_BENCHMARK_START -->"
    end_marker = "<!-- RAG_BENCHMARK_END -->"
    block = "\n".join(
        [
            start_marker,
            "## RAG Benchmark 与自动优化",
            "",
            "根据赛题要求，项目内置自建 RAG Benchmark：从已解析教材 chunk 自动生成 20-50 道带 ground truth 的题目，覆盖事实、对比、推理/关联和跨教材来源定位。评测会遍历 chunk size、重叠长度、稀疏检索模型和短语 rerank 开关，并用 Recall@5、MRR、引用命中率、证据命中率、平均响应时间和估算 token 成本做数据驱动选择。",
            "",
            f"最近一次最优配置：`{best.config_name}`，chunk={best.chunk_size}，overlap={best.config.overlap}，检索模型={best.sparse_model}，rerank={str(best.phrase_rerank).lower()}；Recall@5={best.recall_at_5:.4f}，答案准确率={best.answer_accuracy:.4f}，引用命中率={best.citation_accuracy:.4f}，证据命中率={best.evidence_hit_rate:.4f}，平均耗时={best.avg_latency_ms:.2f}ms，平均上下文 token={best.avg_context_tokens:.2f}。",
            "",
            "完整评测表见 `docs/RAG Benchmark.md`；离线运行产物保存在 `data/cache/rag_benchmark/latest.json`，最优线上默认配置写入 `src/backend/app/rag_defaults.json`。",
            end_marker,
        ]
    )
    current = AGENT_ARCH_DOC_PATH.read_text(encoding="utf-8")
    pattern = re.compile(f"{re.escape(start_marker)}.*?{re.escape(end_marker)}", flags=re.S)
    if pattern.search(current):
        updated = pattern.sub(block, current)
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    AGENT_ARCH_DOC_PATH.write_text(updated, encoding="utf-8")


def first_relevant_rank(ranked: list[tuple[RagChunk, float]], question: BenchmarkQuestion) -> int | None:
    for index, (chunk, _) in enumerate(ranked, start=1):
        if chunk_matches(chunk, question):
            return index
    return None


def chunk_matches(chunk: RagChunk, question: BenchmarkQuestion) -> bool:
    if question.expected_chunk_id and chunk.chunk_id == question.expected_chunk_id:
        return True
    if chunk.textbook != question.expected_textbook:
        return False
    if chunk.chapter != question.expected_chapter:
        return False
    return any(term in chunk.text for term in question.expected_terms)


def answer_contains_evidence(answer: str, question: BenchmarkQuestion) -> bool:
    return any(term in answer for term in question.expected_terms) and question.expected_textbook in answer


def estimate_context_tokens(question: str, ranked: list[tuple[RagChunk, float]]) -> int:
    text = question + "\n" + "\n\n".join(chunk.text for chunk, _ in ranked)
    return max(1, len(text) // 2)


def answer_hint(text: str, term: str) -> str:
    index = text.find(term)
    if index < 0:
        return clean_answer_text(text[:160])
    return clean_answer_text(text[max(0, index - 60) : index + 160])


def question_kind(index: int, cross_textbook_available: bool = False) -> str:
    if cross_textbook_available and index % 6 == 5:
        return "cross_textbook"
    kinds = ("definition", "fact", "source", "compare", "reasoning")
    return kinds[index % len(kinds)]


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0
