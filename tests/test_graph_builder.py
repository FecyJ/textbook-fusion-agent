import asyncio

import pytest

from src.backend.app import graph_builder
from src.backend.app.graph_builder import (
    extract_chapter_graph,
    extract_heuristic,
    is_useful_chapter,
    validate_candidate_name,
)
from src.backend.app.main import build_graph
from src.backend.app.schemas import Chapter, Textbook


def make_textbook() -> Textbook:
    return Textbook(
        textbook_id="book_1",
        filename="physiology.txt",
        title="03_生理学",
        file_format="txt",
        size_bytes=100,
        upload_path="/tmp/physiology.txt",
        status="completed",
    )


def make_chapter(content: str) -> Chapter:
    return Chapter(
        chapter_id="chapter_1",
        title="第三章 血液",
        page_start=91,
        page_end=92,
        content=content,
        char_count=len(content),
    )


def test_validate_candidate_rejects_table_number() -> None:
    assert validate_candidate_name("表11", "因素可参与这两种激素的分泌调节（见表11-5）") is None


def test_validate_candidate_trims_broken_parenthesis() -> None:
    candidate = validate_candidate_name("肝细胞（需", "肝细胞（需氧条件下）参与凝血因子合成。")

    assert candidate is not None
    assert candidate.name == "肝细胞"


def test_validate_candidate_rejects_chapter_and_sentence_fragments() -> None:
    assert validate_candidate_name("第一章绪论压均", "第一章 绪论 血压均是临床观察指标。") is None
    assert validate_candidate_name("称为细胞", "人体的基本单位称为细胞。") is None
    assert validate_candidate_name("内环境的稳态并不", "内环境的稳态并不是固定不变。") is None
    assert validate_candidate_name("如葡萄糖转运体参与", "如葡萄糖转运体参与跨膜转运。") is None
    assert validate_candidate_name("一种小", "一种小分子可穿过细胞膜。") is None
    assert validate_candidate_name("法国生理学家克劳德·伯纳德", "法国生理学家克劳德·伯纳德提出相关观点。") is None
    assert validate_candidate_name("具有转录因子", "具有转录因子样作用。") is None
    assert validate_candidate_name("+和K", "Na+和K+通道参与膜电位形成。") is None
    assert validate_candidate_name("第六章消化和吸收", "第六章 消化和吸收") is None
    assert validate_candidate_name("激活该受体", "配体结合后激活该受体。") is None
    assert validate_candidate_name("向上为外向驱动力", "箭头向上为外向驱动力。") is None
    connexin = validate_candidate_name("由连接蛋白", "缝隙连接由连接蛋白组成。")
    assert connexin is not None
    assert connexin.name == "连接蛋白"
    endothelial = validate_candidate_name("内膜由内皮细胞", "血管内膜由内皮细胞组成。")
    assert endothelial is not None
    assert endothelial.name == "内皮细胞"
    glomerulus = validate_candidate_name("肾小体由肾小球", "肾小体由肾小球和肾小囊组成。")
    assert glomerulus is not None
    assert glomerulus.name == "肾小球"
    assert validate_candidate_name("调控特定蛋白", "相关机制可调控特定蛋白表达。") is None
    voltage_clamp = validate_candidate_name("枪乌贼巨轴突上进行了电压钳", "在枪乌贼巨轴突上进行了电压钳实验。")
    assert voltage_clamp is not None
    assert voltage_clamp.name == "电压钳"
    peptide = validate_candidate_name("和脑利尿钠肽", "心房钠尿肽和脑利尿钠肽参与体液调节。")
    assert peptide is not None
    assert peptide.name == "脑利尿钠肽"
    cleaned = validate_candidate_name("核受体实质上", "核受体实质上是一类转录调节因子。")
    assert cleaned is not None
    assert cleaned.name == "核受体"


def test_heuristic_graph_filters_noise_and_keeps_concepts() -> None:
    content = (
        "因素可参与这两种激素的分泌调节（见表11-5）。"
        "肝细胞（需氧条件下）可合成多种凝血因子。"
        "凝血因子（coagulation factor）是血液凝固过程中发挥作用的蛋白质。"
        "血小板（platelet）参与生理性止血。"
    )

    nodes, _ = extract_heuristic(make_textbook(), make_chapter(content))
    names = {node.name for node in nodes}

    assert "表11" not in names
    assert "肝细胞（需" not in names
    assert "肝细胞" in names
    assert "凝血因子" in names
    assert all(node.quality_score >= 0.52 for node in nodes)


def test_front_matter_chapter_is_not_representative() -> None:
    chapter = make_chapter("前言 本教材由人民卫生出版社组织编写，配套电子教材和数字资源。")
    chapter.page_start = 1
    chapter.title = "03_生理学_3"

    assert not is_useful_chapter(chapter)


def test_heuristic_edges_use_relation_evidence() -> None:
    content = (
        "血液系统包括红细胞和白细胞。"
        "红细胞（erythrocyte）是运输氧气的血细胞。"
        "白细胞（leukocyte）参与免疫防御。"
    )

    nodes, edges = extract_heuristic(make_textbook(), make_chapter(content))
    node_by_name = {node.name: node for node in nodes}
    relation_keys = {(edge.source, edge.target, edge.relation_type) for edge in edges}

    assert "红细胞" in node_by_name
    assert "白细胞" in node_by_name
    assert (
        node_by_name["红细胞"].id,
        node_by_name["白细胞"].id,
        "parallel",
    ) in relation_keys or (
        node_by_name["白细胞"].id,
        node_by_name["红细胞"].id,
        "parallel",
    ) in relation_keys


def test_llm_empty_result_falls_back_to_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConfiguredClient:
        configured = True

    async def fake_extract_with_llm(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(graph_builder, "llm_client", ConfiguredClient())
    monkeypatch.setattr(graph_builder, "extract_with_llm", fake_extract_with_llm)

    content = "肝细胞（hepatocyte）可合成多种血浆蛋白。血浆蛋白（plasma protein）维持胶体渗透压。"
    nodes, _ = asyncio.run(extract_chapter_graph(make_textbook(), make_chapter(content), use_llm=True))
    names = {node.name for node in nodes}

    assert "肝细胞" in names
    assert "血浆蛋白" in names


def test_build_graph_defaults_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def fake_build_graph_for_textbook(textbook, use_llm=True, llm_chapter_limit=6, max_chapters=80):
        calls.append(use_llm)
        return graph_builder.TextbookGraph(textbook_id=textbook.textbook_id, nodes=[], edges=[])

    textbook = make_textbook()
    textbook.chapters = [make_chapter("肝细胞（hepatocyte）是核心概念。")]
    fake_app_state = type(
        "FakeState",
        (),
        {"textbooks": {textbook.textbook_id: textbook}, "graphs": {}, "integration": None},
    )()

    monkeypatch.setattr("src.backend.app.main.load_state", lambda: fake_app_state)
    monkeypatch.setattr("src.backend.app.main.save_state", lambda _state: None)
    monkeypatch.setattr("src.backend.app.main.build_graph_for_textbook", fake_build_graph_for_textbook)

    asyncio.run(build_graph({}))

    assert calls == [True]


def test_build_graph_timeout_falls_back_to_local_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    async def slow_build_graph_for_textbook(textbook, use_llm=True, llm_chapter_limit=6, max_chapters=80):
        calls.append(use_llm)
        return graph_builder.TextbookGraph(textbook_id=textbook.textbook_id, nodes=[], edges=[])

    textbook = make_textbook()
    textbook.chapters = [make_chapter("肝细胞（hepatocyte）是核心概念。")]
    fake_app_state = type(
        "FakeState",
        (),
        {"textbooks": {textbook.textbook_id: textbook}, "graphs": {}, "integration": None},
    )()

    monkeypatch.setattr("src.backend.app.main.load_state", lambda: fake_app_state)
    monkeypatch.setattr("src.backend.app.main.save_state", lambda _state: None)
    monkeypatch.setattr("src.backend.app.main.build_graph_for_textbook", slow_build_graph_for_textbook)
    monkeypatch.setattr("src.backend.app.main.asyncio.wait_for", fake_wait_for)

    result = asyncio.run(build_graph({"build_timeout_seconds": 0}))

    assert result["built"][0]["fallback"] == "llm_timeout"
    assert calls == [False]
