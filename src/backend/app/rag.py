from __future__ import annotations

from datetime import datetime
import re
from uuid import uuid4

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .llm import llm_client
from .schemas import AppState, RagAnswer, RagChunk, RagCitation


NO_ANSWER = "当前知识库中未找到相关信息"
QUESTION_STOPWORDS = {
    "这个",
    "概念",
    "核心",
    "定义",
    "是什么",
    "什么",
    "请问",
    "教材",
    "知识点",
    "相关",
    "说明",
    "解释",
    "简述",
}


def build_rag_index(state: AppState) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    for textbook in state.textbooks.values():
        if textbook.status != "completed":
            continue
        for chapter in textbook.chapters:
            for offset, chunk_text in enumerate(split_text(chapter.content)):
                chunks.append(
                    RagChunk(
                        chunk_id=f"chunk_{uuid4().hex[:10]}",
                        textbook_id=textbook.textbook_id,
                        textbook=textbook.title,
                        chapter=chapter.title,
                        page=chapter.page_start,
                        text=chunk_text,
                        char_count=len(chunk_text),
                    )
                )
    state.rag_chunks = chunks
    state.rag_indexed_at = datetime.utcnow().isoformat()
    return chunks


async def query_rag(state: AppState, question: str) -> RagAnswer:
    chunks = state.rag_chunks or build_rag_index(state)
    if not chunks:
        return RagAnswer(answer=NO_ANSWER, citations=[], source_chunks=[])
    ranked = retrieve(chunks, question, top_k=5)
    if not ranked:
        return RagAnswer(answer=NO_ANSWER, citations=[], source_chunks=[])
    citations = [
        RagCitation(textbook=chunk.textbook, chapter=chunk.chapter, page=chunk.page, relevance_score=round(score, 4))
        for chunk, score in ranked
    ]
    answer = await generate_answer(question, ranked)
    return RagAnswer(answer=answer, citations=citations, source_chunks=[chunk.text for chunk, _ in ranked])


def split_text(text: str, chunk_size: int = 700, overlap: int = 80) -> list[str]:
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


def retrieve(chunks: list[RagChunk], question: str, top_k: int = 5) -> list[tuple[RagChunk, float]]:
    if not chunks:
        return []

    corpus = [chunk.text for chunk in chunks]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(corpus + [question])
    tfidf_scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()

    tokenized = [tokenize(text) for text in corpus]
    bm25 = BM25Okapi(tokenized)
    bm25_scores = bm25.get_scores(tokenize(question))
    max_bm25 = max(bm25_scores) if len(bm25_scores) else 0
    if max_bm25:
        bm25_scores = bm25_scores / max_bm25
    phrase_scores = exact_phrase_scores(chunks, question)
    combined = 0.48 * tfidf_scores + 0.27 * bm25_scores + 0.25 * phrase_scores
    order = combined.argsort()[::-1][:top_k]
    return [(chunks[index], float(combined[index])) for index in order if combined[index] > 0.005]


async def generate_answer(question: str, ranked: list[tuple[RagChunk, float]]) -> str:
    if any(evidence_terms(question, chunk.text) for chunk, _ in ranked):
        return evidence_answer(question, ranked)

    context = "\n\n".join(
        f"[{index}. {chunk.textbook}, {chunk.chapter}, 第{chunk.page}页]\n{chunk.text}"
        for index, (chunk, _) in enumerate(ranked, start=1)
    )
    if llm_client.configured:
        try:
            system = "你是严格基于教材上下文回答的 RAG 助手。禁止使用上下文之外的知识。回答必须包含来源引用。"
            user = f"""
问题：{question}

上下文：
{context}

要求：
1. 只基于上下文回答。
2. 每个关键结论后附引用，格式为 [教材名称, 章节, 第X页]。
3. 如果上下文中找不到答案，回复“当前知识库中未找到相关信息”。
"""
            return await llm_client.chat(system, user, temperature=0.1, timeout=12)
        except Exception:
            pass
    first = ranked[0][0]
    return f"{first.text[:260]}... [{first.textbook}, {first.chapter}, 第{first.page}页]"


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text.lower())
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    grams: list[str] = []
    for run in chinese_runs:
        for size in (2, 3, 4, 5):
            grams.extend(run[index : index + size] for index in range(0, max(0, len(run) - size + 1)))
    return words + grams


def exact_phrase_scores(chunks: list[RagChunk], question: str) -> np.ndarray:
    terms = query_terms(question)
    scores = np.zeros(len(chunks), dtype=float)
    if not terms:
        return scores
    for index, chunk in enumerate(chunks):
        text = chunk.text
        score = 0.0
        for term in terms:
            count = text.count(term)
            if count:
                score += min(1.0, 0.55 + 0.18 * count + 0.03 * min(len(term), 8))
        scores[index] = min(score, 1.0)
    return scores


def query_terms(question: str) -> list[str]:
    terms = []
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", question):
        normalized = token.strip().lower()
        if len(normalized) < 2 or normalized in QUESTION_STOPWORDS:
            continue
        for stopword in QUESTION_STOPWORDS:
            normalized = normalized.replace(stopword, "")
        normalized = normalized.strip("的是了呢吗呀")
        if len(normalized) >= 2:
            terms.append(normalized)
    terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", question))
    unique_terms = sorted(set(terms), key=lambda item: (-len(item), item))
    return unique_terms[:8]


def evidence_terms(question: str, text: str) -> list[str]:
    return [term for term in query_terms(question) if term in text]


def evidence_answer(question: str, ranked: list[tuple[RagChunk, float]]) -> str:
    for chunk, _ in ranked:
        terms = evidence_terms(question, chunk.text)
        if not terms:
            continue
        term = terms[0]
        sentence = best_sentence(chunk.text, term, question)
        if sentence:
            return f"{clean_answer_text(sentence)} [{chunk.textbook}, {chunk.chapter}, 第{chunk.page}页]"
    first = ranked[0][0]
    return f"{first.text[:260]}... [{first.textbook}, {first.chapter}, 第{first.page}页]"


def best_sentence(text: str, term: str, question: str = "") -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[。！？；;])\s*", normalized)
    containing = [sentence for sentence in sentences if term in sentence]
    if containing:
        return min(containing, key=lambda sentence: sentence_rank(sentence, question))[:260]
    index = normalized.find(term)
    if index < 0:
        return ""
    return normalized[max(0, index - 90) : index + 170]


def sentence_rank(sentence: str, question: str) -> tuple[int, int, int]:
    definition_question = any(keyword in question for keyword in ("定义", "是什么", "什么是", "概念"))
    definition_cues = ("是", "指", "属于", "称为", "来自", "分泌", "组成", "包括", "主要")
    action_cues = ("作用", "调节", "影响", "促进", "抑制")
    cue_penalty = 0 if definition_question and any(cue in sentence for cue in definition_cues) else 1
    action_penalty = 1 if definition_question and any(cue in sentence for cue in action_cues) else 0
    return (cue_penalty + action_penalty, abs(len(sentence) - 120), len(sentence))


def clean_answer_text(text: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text).strip()
