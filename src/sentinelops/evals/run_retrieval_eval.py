"""
Retrieval Benchmark Evaluation Suite for SentinelOps.

Executes 50 labeled operational knowledge queries across retrieval modes:
1. dense_only
2. sparse_only
3. hybrid (RRF)
4. hybrid_plus_rerank

Computes real measured IR metrics:
- Recall@5
- MRR (Mean Reciprocal Rank)
- nDCG@10
- Query Latency (ms)

Invariants:
- Zero fabricated metrics.
- Measures real retrieval results from live Qdrant / KnowledgeProvider.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

from sentinelops.config.settings import get_settings
from sentinelops.domain.models.knowledge import KnowledgeQuery, RetrievalMode
from sentinelops.evals.datasets.retrieval_queries import (
    RETRIEVAL_BENCHMARK_QUERIES,
    LabeledRetrievalQuery,
)
from sentinelops.integrations.knowledge.qdrant_provider import QdrantKnowledgeProvider


def compute_recall_at_k(retrieved_doc_ids: list[str], expected_doc_ids: list[str], k: int) -> float:
    """Compute Recall@k."""
    if not expected_doc_ids:
        return 1.0
    top_k = retrieved_doc_ids[:k]
    hits = sum(1 for doc_id in expected_doc_ids if doc_id in top_k)
    return hits / len(expected_doc_ids)


def compute_mrr(retrieved_doc_ids: list[str], expected_doc_ids: list[str]) -> float:
    """Compute Reciprocal Rank (RR) for a single query."""
    expected_set = set(expected_doc_ids)
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected_set:
            return 1.0 / rank
    return 0.0


def compute_ndcg_at_k(retrieved_doc_ids: list[str], expected_doc_ids: list[str], k: int) -> float:
    """Compute Normalized Discounted Cumulative Gain (nDCG@k)."""
    expected_set = set(expected_doc_ids)
    dcg = 0.0
    for i, doc_id in enumerate(retrieved_doc_ids[:k], start=1):
        rel = 1.0 if doc_id in expected_set else 0.0
        dcg += rel / math.log2(i + 1)

    # Ideal DCG
    idcg = 0.0
    ideal_hits = min(k, len(expected_doc_ids))
    for i in range(1, ideal_hits + 1):
        idcg += 1.0 / math.log2(i + 1)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


async def evaluate_mode(
    provider: QdrantKnowledgeProvider,
    mode: RetrievalMode,
    queries: list[LabeledRetrievalQuery],
) -> dict[str, Any]:
    """
    Evaluate all benchmark queries for a given retrieval mode.
    """
    recalls_at_5: list[float] = []
    mrrs: list[float] = []
    ndcgs_at_10: list[float] = []
    latencies_ms: list[float] = []

    for item in queries:
        query_obj = KnowledgeQuery(
            query=item.query,
            service=item.service_filter,
            document_type=item.document_type_filter,
            limit=10,
            mode=mode,
        )

        t0 = time.perf_counter()
        results = await provider.search(query_obj)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        retrieved_docs = [r.document_id for r in results]

        recall_5 = compute_recall_at_k(retrieved_docs, item.expected_document_ids, k=5)
        mrr = compute_mrr(retrieved_docs, item.expected_document_ids)
        ndcg_10 = compute_ndcg_at_k(retrieved_docs, item.expected_document_ids, k=10)

        recalls_at_5.append(recall_5)
        mrrs.append(mrr)
        ndcgs_at_10.append(ndcg_10)

    n = max(1, len(queries))
    return {
        "mode": mode.value,
        "query_count": len(queries),
        "recall_at_5": round(sum(recalls_at_5) / n, 4),
        "mrr": round(sum(mrrs) / n, 4),
        "ndcg_at_10": round(sum(ndcgs_at_10) / n, 4),
        "avg_latency_ms": round(sum(latencies_ms) / n, 2),
        "p95_latency_ms": round(sorted(latencies_ms)[int(n * 0.95)], 2) if n > 0 else 0.0,
    }


async def run_full_retrieval_evaluation(
    qdrant_url: str | None = None,
    collection_name: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Run complete evaluation across all 4 modes.
    """
    settings = get_settings()
    url = qdrant_url or settings.qdrant_url
    collection = collection_name or settings.qdrant_collection
    out_dir = output_dir or Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    provider = QdrantKnowledgeProvider(url=url, collection_name=collection)
    provider.ensure_collection()

    modes = [
        RetrievalMode.DENSE_ONLY,
        RetrievalMode.SPARSE_ONLY,
        RetrievalMode.HYBRID,
        RetrievalMode.HYBRID_PLUS_RERANK,
    ]

    results_by_mode: dict[str, Any] = {}
    print(f"\n=======================================================")
    print(f"SentinelOps Retrieval Benchmark (50 queries, live Qdrant)")
    print(f"=======================================================\n")

    for mode in modes:
        eval_result = await evaluate_mode(provider, mode, RETRIEVAL_BENCHMARK_QUERIES)
        results_by_mode[mode.value] = eval_result
        print(
            f"Mode: {mode.value:<18} | "
            f"Recall@5: {eval_result['recall_at_5']:.4f} | "
            f"MRR: {eval_result['mrr']:.4f} | "
            f"nDCG@10: {eval_result['ndcg_at_10']:.4f} | "
            f"Avg Latency: {eval_result['avg_latency_ms']:5.1f} ms"
        )

    # Save benchmark report to JSON
    report_path = out_dir / "retrieval_benchmark_results.json"
    report_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection": collection,
        "query_count": len(RETRIEVAL_BENCHMARK_QUERIES),
        "results": results_by_mode,
    }
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\nSaved machine-readable benchmark report to: {report_path}\n")

    return results_by_mode


def main() -> None:
    """CLI entrypoint for running retrieval evaluation."""
    parser = argparse.ArgumentParser(description="SentinelOps Knowledge Retrieval Benchmark")
    parser.add_argument("--qdrant-url", type=str, default="http://localhost:6333")
    parser.add_argument("--collection", type=str, default="sentinelops_knowledge")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/reports"))
    args = parser.parse_args()

    asyncio.run(
        run_full_retrieval_evaluation(
            qdrant_url=args.qdrant_url,
            collection_name=args.collection,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
