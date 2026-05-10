from src.backend.app.rag import evidence_answer, retrieve
from src.backend.app.schemas import RagChunk


def make_chunk(index: int, text: str) -> RagChunk:
    return RagChunk(
        chunk_id=f"chunk_{index}",
        textbook_id="book_1",
        textbook="生理学",
        chapter="第十一章 内分泌",
        page=360 + index,
        text=text,
        char_count=len(text),
    )


def test_retrieve_prioritizes_explicit_concept_phrase() -> None:
    chunks = [
        make_chunk(index, "核心 概念 定义 是什么 生理学 系统 机制 教材 问题 " * 20)
        for index in range(8)
    ]
    target = make_chunk(
        99,
        "肾上腺髓质分泌儿茶酚胺。循环血液中的肾上腺素和去甲肾上腺素主要来自肾上腺髓质，其中肾上腺素约占80%。",
    )
    chunks.append(target)

    ranked = retrieve(chunks, "肾上腺素这个概念的核心定义是什么？", top_k=5)

    assert ranked
    assert any("肾上腺素" in chunk.text for chunk, _ in ranked)
    assert "肾上腺素" in ranked[0][0].text


def test_evidence_answer_uses_matching_sentence_with_citation() -> None:
    chunk = make_chunk(
        1,
        "循环血液中的肾上腺素和去甲肾上腺素主要来自肾上腺髓质，其中肾上腺 素约占80%。",
    )

    answer = evidence_answer("肾上腺素这个概念的核心定义是什么？", [(chunk, 0.9)])

    assert "肾上腺素" in answer
    assert "肾上腺 素" not in answer
    assert "[生理学, 第十一章 内分泌, 第361页]" in answer
