from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.app.rag_benchmark import BENCHMARK_DOC_PATH, BENCHMARK_LATEST_PATH, run_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local RAG benchmark and optional pipeline optimization.")
    parser.add_argument("--sample-size", type=int, default=30, help="Number of benchmark questions to generate, 20-50 recommended.")
    parser.add_argument("--optimize", action="store_true", help="Compare candidate chunk/retrieval/rerank configurations.")
    parser.add_argument("--no-optimize", action="store_true", help="Evaluate only the current configured RAG defaults.")
    parser.add_argument("--write-docs", action="store_true", help="Write docs/RAG Benchmark.md and update docs/Agent 架构说明.md.")
    parser.add_argument("--no-write-docs", action="store_true", help="Skip markdown documentation updates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    optimize = args.optimize or not args.no_optimize
    write_docs = args.write_docs or not args.no_write_docs
    result = run_benchmark(sample_size=args.sample_size, optimize=optimize, write_docs=write_docs)
    best = next(item for item in result["metrics"] if item["config_name"] == result["best_config_name"])
    print(f"questions={result['question_count']}")
    print(f"best_config={result['best_config_name']}")
    print(
        "metrics="
        f"recall_at_5={best['recall_at_5']}, "
        f"mrr={best['mrr']}, "
        f"answer_accuracy={best['answer_accuracy']}, "
        f"citation_accuracy={best['citation_accuracy']}, "
        f"evidence_hit_rate={best['evidence_hit_rate']}, "
        f"avg_latency_ms={best['avg_latency_ms']}, "
        f"avg_context_tokens={best['avg_context_tokens']}, "
        f"estimated_token_cost={best['estimated_token_cost']}"
    )
    print(f"latest_json={BENCHMARK_LATEST_PATH}")
    if write_docs:
        print(f"doc={BENCHMARK_DOC_PATH}")


if __name__ == "__main__":
    main()
