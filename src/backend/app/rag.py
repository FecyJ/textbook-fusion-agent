from __future__ import annotations

from datetime import datetime
import re
from uuid import uuid4

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .llm import llm_client
from .schemas import AppState, RagAnswer, RagChunk, RagCitation


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
        return RagAnswer(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[])
    ranked = retrieve(chunks, question, top_k=5)
    if not ranked:
        return RagAnswer(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[])
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
    combined = 0.65 * tfidf_scores + 0.35 * bm25_scores
    order = combined.argsort()[::-1][:top_k]
    return [(chunks[index], float(combined[index])) for index in order if combined[index] > 0.01]


async def generate_answer(question: str, ranked: list[tuple[RagChunk, float]]) -> str:
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
            return await llm_client.chat(system, user, temperature=0.1)
        except Exception:
            pass
    first = ranked[0][0]
    return f"{first.text[:260]}... [{first.textbook}, {first.chapter}, 第{first.page}页]"


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text.lower())
    return words

