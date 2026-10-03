"""
Retrieval Benchmark Evaluation Suite for SentinelOps.

Executes 50 labeled operational knowledge queries across retrieval modes:
1. dense_only
2. sparse_only
3. hybrid (RRF k=60)
4. hybrid_plus_rerank

Computes real measured IR metrics:
- Recall@5 & Recall@10
- MRR (Mean Reciprocal Rank)
- Standard nDCG@10 (strictly bounded in [0.0, 1.0])
- Query Latencies (mean, median, p95) with stage-level profiling

Artifacts generated:
- evals/results/retrieval/benchmark_manifest.json
- evals/results/retrieval/per_query_results.jsonl
- evals/results/retrieval/aggregate_results.json
- docs/reports/retrieval_benchmark_results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
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
    """
    Compute Recall@k at the document level.
    Evaluates whether expected documents appear in the top-k retrieved chunks.
    """
    if not expected_doc_ids:
        return 1.0
    top_k_docs = set(retrieved_doc_ids[:k])
    hits = sum(1 for doc_id in expected_doc_ids if doc_id in top_k_docs)
    return hits / len(expected_doc_ids)


def compute_mrr(retrieved_doc_ids: list[str], expected_doc_ids: list[str]) -> tuple[float, int | None]:
    """
    Compute Reciprocal Rank (RR) and rank of first relevant document.
    """
    expected_set = set(expected_doc_ids)
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected_set:
            return 1.0 / rank, rank
    return 0.0, None


def compute_ndcg_at_k(
    retrieved_doc_ids: list[str],
    expected_doc_ids: list[str],
    k: int,
) -> tuple[float, float, float]:
    """
    Compute mathematically standard Normalized Discounted Cumulative Gain at rank cutoff k (nDCG@k).

    Returns:
        (ndcg, dcg, idcg) strictly bounded: 0.0 <= ndcg <= 1.0

    Document-level deduplication:
        Multiple chunks from the same document only receive relevance credit on their first occurrence,
        preventing duplicate chunks from inflating DCG beyond IDCG.
    """
    if not expected_doc_ids:
        return 0.0, 0.0, 0.0

    expected_set = set(expected_doc_ids)

    # Deduplicate document IDs preserving first rank
    seen: set[str] = set()
    unique_docs: list[str] = []
    for d in retrieved_doc_ids:
        if d not in seen:
            seen.add(d)
            unique_docs.append(d)

    dcg = 0.0
    for i, doc_id in enumerate(unique_docs[:k], start=1):
        rel = 1.0 if doc_id in expected_set else 0.0
        dcg += rel / math.log2(i + 1)

    idcg = 0.0
    ideal_hits = min(k, len(expected_doc_ids))
    for i in range(1, ideal_hits + 1):
        idcg += 1.0 / math.log2(i + 1)

    if idcg == 0.0:
        return 0.0, dcg, idcg

    ndcg = dcg / idcg
    return ndcg, dcg, idcg


async def evaluate_mode(
    provider: QdrantKnowledgeProvider,
    mode: RetrievalMode,
    queries: list[LabeledRetrievalQuery],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Evaluate all benchmark queries for a given retrieval mode.
    Returns (aggregate_dict, per_query_records).
    """
    recalls_at_5: list[float] = []
    recalls_at_10: list[float] = []
    mrrs: list[float] = []
    ndcgs_at_10: list[float] = []
    latencies_ms: list[float] = []
    stage_profiles: list[dict[str, float]] = []
    per_query_records: list[dict[str, Any]] = []

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

        profile = getattr(provider, "last_search_profile", {})
        stage_profiles.append(profile)

        retrieved_chunks = [r.chunk_id for r in results]
        retrieved_docs = [r.document_id for r in results]

        recall_5 = compute_recall_at_k(retrieved_docs, item.expected_document_ids, k=5)
        recall_10 = compute_recall_at_k(retrieved_docs, item.expected_document_ids, k=10)
        mrr, first_rank = compute_mrr(retrieved_docs, item.expected_document_ids)
        ndcg_10, dcg, idcg = compute_ndcg_at_k(retrieved_docs, item.expected_document_ids, k=10)

        recalls_at_5.append(recall_5)
        recalls_at_10.append(recall_10)
        mrrs.append(mrr)
        ndcgs_at_10.append(ndcg_10)

        per_query_records.append({
            "mode": mode.value,
            "query_id": item.query_id,
            "query": item.query,
            "category": item.category,
            "service_filter": item.service_filter,
            "expected_document_ids": item.expected_document_ids,
            "retrieved_document_ids": retrieved_docs,
            "retrieved_chunk_ids": retrieved_chunks,
            "rank_of_first_relevant": first_rank,
            "recall_at_5": round(recall_5, 4),
            "recall_at_10": round(recall_10, 4),
            "reciprocal_rank": round(mrr, 4),
            "dcg_at_10": round(dcg, 4),
            "idcg_at_10": round(idcg, 4),
            "ndcg_at_10": round(ndcg_10, 4),
            "latency_ms": round(elapsed_ms, 2),
            "stage_profile": profile,
        })

    n = max(1, len(queries))
    sorted_latencies = sorted(latencies_ms)
    p50_idx = int(n * 0.50)
    p95_idx = min(n - 1, int(n * 0.95))

    aggregate = {
        "mode": mode.value,
        "query_count": len(queries),
        "recall_at_5": round(sum(recalls_at_5) / n, 4),
        "recall_at_10": round(sum(recalls_at_10) / n, 4),
        "mrr": round(sum(mrrs) / n, 4),
        "ndcg_at_10": round(sum(ndcgs_at_10) / n, 4),
        "latency_ms": {
            "mean": round(statistics.mean(latencies_ms), 2),
            "median": round(sorted_latencies[p50_idx], 2),
            "p95": round(sorted_latencies[p95_idx], 2),
        },
        "stage_latency_means_ms": {
            "embedding": round(statistics.mean([p.get("embedding_ms", 0.0) for p in stage_profiles]), 2),
            "dense": round(statistics.mean([p.get("dense_ms", 0.0) for p in stage_profiles]), 2),
            "sparse": round(statistics.mean([p.get("sparse_ms", 0.0) for p in stage_profiles]), 2),
            "fusion": round(statistics.mean([p.get("fusion_ms", 0.0) for p in stage_profiles]), 2),
            "rerank": round(statistics.mean([p.get("rerank_ms", 0.0) for p in stage_profiles]), 2),
        },
    }
    return aggregate, per_query_records


async def run_full_retrieval_evaluation(
    qdrant_url: str | None = None,
    collection_name: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Run complete evaluation across all 4 modes with machine-readable logging.
    """
    settings = get_settings()
    url = qdrant_url or settings.qdrant_url
    collection = collection_name or settings.qdrant_collection
    out_dir = output_dir or Path("evals/results/retrieval")
    reports_dir = Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    provider = QdrantKnowledgeProvider(url=url, collection_name=collection)
    provider.ensure_collection()

    modes = [
        RetrievalMode.DENSE_ONLY,
        RetrievalMode.SPARSE_ONLY,
        RetrievalMode.HYBRID,
        RetrievalMode.HYBRID_PLUS_RERANK,
    ]

    results_by_mode: dict[str, Any] = {}
    all_query_records: list[dict[str, Any]] = []

    print(f"\n=======================================================")
    print(f"SentinelOps Retrieval Benchmark (50 queries, live Qdrant)")
    print(f"=======================================================\n")

    per_mode_query_map: dict[str, dict[str, list[str]]] = {}

    for mode in modes:
        eval_result, query_records = await evaluate_mode(provider, mode, RETRIEVAL_BENCHMARK_QUERIES)
        results_by_mode[mode.value] = eval_result
        all_query_records.extend(query_records)
        per_mode_query_map[mode.value] = {
            r["query_id"]: r["retrieved_chunk_ids"][:5] for r in query_records
        }

        print(
            f"Mode: {mode.value:<18} | "
            f"Recall@5: {eval_result['recall_at_5']:.4f} | "
            f"Recall@10: {eval_result['recall_at_10']:.4f} | "
            f"MRR: {eval_result['mrr']:.4f} | "
            f"nDCG@10: {eval_result['ndcg_at_10']:.4f} | "
            f"Latency (mean/p50/p95): {eval_result['latency_ms']['mean']:.1f}/{eval_result['latency_ms']['median']:.1f}/{eval_result['latency_ms']['p95']:.1f} ms"
        )

    # 10-query representative sample audit & overlap statistics
    sample_ids = [f"Q{i:02d}" for i in range(1, 11)]
    print("\n--- Representative 10-Query Top-5 Chunk Audit ---")
    overlap_dense_sparse: list[float] = []
    overlap_dense_hybrid: list[float] = []
    overlap_sparse_hybrid: list[float] = []

    for qid in sample_ids:
        dense_top5 = per_mode_query_map["dense_only"].get(qid, [])
        sparse_top5 = per_mode_query_map["sparse_only"].get(qid, [])
        hybrid_top5 = per_mode_query_map["hybrid"].get(qid, [])
        rerank_top5 = per_mode_query_map["hybrid_plus_rerank"].get(qid, [])

        ds_over = len(set(dense_top5) & set(sparse_top5)) / 5.0
        dh_over = len(set(dense_top5) & set(hybrid_top5)) / 5.0
        sh_over = len(set(sparse_top5) & set(hybrid_top5)) / 5.0
        overlap_dense_sparse.append(ds_over)
        overlap_dense_hybrid.append(dh_over)
        overlap_sparse_hybrid.append(sh_over)

        print(f"[{qid}]")
        print(f"  dense top-5:          {dense_top5}")
        print(f"  sparse top-5:         {sparse_top5}")
        print(f"  hybrid top-5:         {hybrid_top5}")
        print(f"  hybrid+rerank top-5:  {rerank_top5}")
        print(f"  overlaps: dense∩sparse={ds_over:.2f}, dense∩hybrid={dh_over:.2f}, sparse∩hybrid={sh_over:.2f}")

    mean_ds = sum(overlap_dense_sparse) / len(overlap_dense_sparse)
    mean_dh = sum(overlap_dense_hybrid) / len(overlap_dense_hybrid)
    mean_sh = sum(overlap_sparse_hybrid) / len(overlap_sparse_hybrid)
    print(f"\nMean Top-5 Overlap on Sample: dense∩sparse={mean_ds:.2%}, dense∩hybrid={mean_dh:.2%}, sparse∩hybrid={mean_sh:.2%}\n")

    # Save benchmark manifest
    manifest = {
        "benchmark_name": "sentinelops-knowledge-retrieval",
        "benchmark_version": "slice3-v2-hardened",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection_name": collection,
        "query_count": len(RETRIEVAL_BENCHMARK_QUERIES),
        "embedding_provider": "DeterministicEmbeddingProvider-128d",
        "sparse_provider": "BM25Encoder-k1.5-b0.75",
        "fusion_algorithm": "ReciprocalRankFusion-k60",
        "reranker": "CrossFeatureReranker",
        "ndcg_formula": "standard_deduplicated_document_ndcg_bounded_0_to_1",
    }
    manifest_path = out_dir / "benchmark_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Save per-query results jsonl
    jsonl_path = out_dir / "per_query_results.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in all_query_records:
            f.write(json.dumps(rec) + "\n")

    # Save aggregate results json
    agg_path = out_dir / "aggregate_results.json"
    agg_path.write_text(json.dumps(results_by_mode, indent=2), encoding="utf-8")

    # Save legacy report path for docs
    legacy_path = reports_dir / "retrieval_benchmark_results.json"
    report_data = {
        "manifest": manifest,
        "overlap_sample": {
            "mean_dense_sparse_overlap": round(mean_ds, 4),
            "mean_dense_hybrid_overlap": round(mean_dh, 4),
            "mean_sparse_hybrid_overlap": round(mean_sh, 4),
        },
        "results": results_by_mode,
    }
    legacy_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    print(f"Saved artifacts:")
    print(f"  - {manifest_path}")
    print(f"  - {jsonl_path}")
    print(f"  - {agg_path}")
    print(f"  - {legacy_path}\n")

    return results_by_mode


def main() -> None:
    """CLI entrypoint for running retrieval evaluation."""
    parser = argparse.ArgumentParser(description="SentinelOps Knowledge Retrieval Benchmark")
    parser.add_argument("--qdrant-url", type=str, default="http://localhost:6333")
    parser.add_argument("--collection", type=str, default="sentinelops_knowledge")
    parser.add_argument("--output-dir", type=Path, default=Path("evals/results/retrieval"))
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
