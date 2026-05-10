from src.backend.app.rag import RagConfig
from src.backend.app.rag_benchmark import build_question_set, candidate_terms, choose_best, evaluate_config
from src.backend.app.schemas import AppState, Chapter, Textbook


def make_state() -> AppState:
    content = (
        "循环血液中的肾上腺素和去甲肾上腺素主要来自肾上腺髓质，其中肾上腺素约占80%。"
        "肾上腺素是机体应激反应的重要激素，可影响心血管活动。"
    )
    textbook = Textbook(
        textbook_id="book_1",
        filename="physiology.txt",
        title="生理学",
        file_format=".txt",
        size_bytes=len(content),
        upload_path="/tmp/physiology.txt",
        status="completed",
        chapters=[
            Chapter(
                chapter_id="chapter_1",
                title="第十一章 内分泌",
                page_start=361,
                page_end=362,
                content=content,
                char_count=len(content),
            )
        ],
    )
    return AppState(textbooks={"book_1": textbook})


def test_build_question_set_keeps_ground_truth_metadata() -> None:
    questions = build_question_set(make_state(), sample_size=3)

    assert questions
    assert questions[0].expected_textbook == "生理学"
    assert questions[0].expected_chapter == "第十一章 内分泌"
    assert questions[0].expected_page == 361
    assert questions[0].expected_terms
    assert questions[0].answer_hint


def test_candidate_terms_filters_sentence_fragments() -> None:
    text = "此处可进行眶下神经阻滞麻醉。促成了经导管治疗的发展。胰岛素受体（insulin receptor）是酪氨酸激酶受体家族成员。"
    terms = candidate_terms(text)

    assert "胰岛素受体" in terms
    assert "促成了经导管" not in terms


def test_evaluate_config_scores_explicit_term_retrieval() -> None:
    state = make_state()
    questions = build_question_set(state, sample_size=1)
    metrics = evaluate_config(
        state,
        questions,
        "test",
        RagConfig(chunk_size=120, overlap=20, top_k=5, phrase_rerank=True).normalized(),
    )

    assert metrics.question_count == 1
    assert metrics.recall_at_5 == 1.0
    assert metrics.citation_accuracy == 1.0
    assert metrics.avg_latency_ms >= 0
    assert metrics.avg_context_tokens > 0


def test_choose_best_prefers_recall_then_latency() -> None:
    state = make_state()
    questions = build_question_set(state, sample_size=1)
    slower = evaluate_config(state, questions, "slower", RagConfig(chunk_size=300, overlap=60).normalized())
    faster = evaluate_config(state, questions, "faster", RagConfig(chunk_size=120, overlap=20).normalized())

    best = choose_best([slower, faster])

    assert best.recall_at_5 == 1.0
    assert best.config_name in {"slower", "faster"}
