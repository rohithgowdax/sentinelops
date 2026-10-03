"""
Corpus Manifest Generator and Validator for SentinelOps Knowledge Base.

Inspects all Markdown documents in `knowledge/`, extracts frontmatter, document types,
chunk counts, and emits a versioned `corpus_manifest.json`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinelops.knowledge.ingest import load_all_chunks


def generate_corpus_manifest(
    knowledge_dir: Path,
    corpus_version: str = "v2.0.0",
    dataset_version: str = "v2",
) -> dict[str, Any]:
    """
    Generate authoritative metadata manifest for the operational knowledge corpus.
    """
    chunks = load_all_chunks(knowledge_dir)
    doc_ids = sorted(list(set(c.document_id for c in chunks)))

    doc_class_counts: dict[str, int] = {}
    for c in chunks:
        dtype = c.document_type.value
        doc_class_counts[dtype] = doc_class_counts.get(dtype, 0) + 1

    # Document-level class mapping
    doc_to_type: dict[str, str] = {}
    for c in chunks:
        doc_to_type[c.document_id] = c.document_type.value

    classes_summary: dict[str, int] = {}
    for dtype in doc_to_type.values():
        classes_summary[dtype] = classes_summary.get(dtype, 0) + 1

    manifest = {
        "corpus_version": corpus_version,
        "dataset_version": dataset_version,
        "document_count": len(doc_ids),
        "chunk_count": len(chunks),
        "document_ids": doc_ids,
        "document_classes": classes_summary,
        "chunk_distribution_by_class": doc_class_counts,
        "source_directory": str(knowledge_dir),
        "generation_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    return manifest


def save_corpus_manifest(
    knowledge_dir: Path,
    output_path: Path,
    corpus_version: str = "v2.0.0",
) -> dict[str, Any]:
    manifest = generate_corpus_manifest(knowledge_dir, corpus_version=corpus_version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    out = Path("evals/datasets/v2/corpus_manifest.json")
    save_corpus_manifest(Path("knowledge"), out)
    print(f"Saved corpus manifest to {out}")
