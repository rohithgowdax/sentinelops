"""
Knowledge Document Parser and Ingestion Pipeline for SentinelOps.

Discovers operational Markdown documents with YAML frontmatter, applies section-aware
chunking, creates canonical `KnowledgeChunk` objects, and indexes them idempotently
into Qdrant (or any configured `KnowledgeProvider`).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from sentinelops.config.settings import get_settings
from sentinelops.domain.models.knowledge import DocumentType, KnowledgeChunk
from sentinelops.integrations.knowledge.qdrant_provider import QdrantKnowledgeProvider

logger = logging.getLogger(__name__)


def parse_markdown_with_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Extract YAML frontmatter and body from a Markdown document.
    """
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if not match:
        return {}, content.strip()

    frontmatter_raw = match.group(1)
    body = match.group(2).strip()
    try:
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
    except Exception as exc:
        logger.warning("Failed to parse YAML frontmatter: %s", exc)
        frontmatter = {}

    return frontmatter, body


def chunk_markdown_document(
    filepath: Path,
    frontmatter: dict[str, Any],
    body: str,
) -> list[KnowledgeChunk]:
    """
    Section-aware chunking preserving Markdown headings and document hierarchy.
    """
    doc_id = str(frontmatter.get("document_id") or filepath.stem)
    doc_type_str = str(frontmatter.get("document_type") or "runbook").lower()
    try:
        doc_type = DocumentType(doc_type_str)
    except ValueError:
        doc_type = DocumentType.RUNBOOK

    title = str(frontmatter.get("title") or filepath.stem.replace("-", " ").title())
    service = frontmatter.get("service")
    environment = frontmatter.get("environment")
    severity = frontmatter.get("severity")
    source_ref = str(filepath)

    # Split body on Markdown headers (#, ##, ###)
    # Regex splits while keeping delimiter or matching sections
    sections = re.split(r"\n(?=#{1,3}\s+)", body)
    chunks: list[KnowledgeChunk] = []

    for idx, raw_section in enumerate(sections):
        section_text = raw_section.strip()
        if not section_text:
            continue

        # Extract section heading if present
        header_match = re.match(r"^#{1,3}\s+(.+)$", section_text.splitlines()[0])
        section_name = header_match.group(1).strip() if header_match else "main"

        chunk_id = f"{doc_id}-chk-{idx + 1:02d}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                document_id=doc_id,
                document_type=doc_type,
                title=title,
                service=service,
                environment=environment,
                severity=severity,
                section=section_name,
                content=section_text,
                source=source_ref,
                chunk_index=idx,
                total_chunks=len(sections),
                metadata=frontmatter,
            )
        )

    return chunks


def load_all_chunks(knowledge_dir: Path) -> list[KnowledgeChunk]:
    """
    Discover and chunk all Markdown files in knowledge directory tree.
    """
    all_chunks: list[KnowledgeChunk] = []
    if not knowledge_dir.exists():
        logger.warning("Knowledge directory does not exist: %s", knowledge_dir)
        return all_chunks

    for md_path in sorted(knowledge_dir.rglob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        frontmatter, body = parse_markdown_with_frontmatter(text)
        chunks = chunk_markdown_document(md_path, frontmatter, body)
        all_chunks.extend(chunks)

    return all_chunks


async def run_ingestion(
    knowledge_dir: Path | None = None,
    qdrant_url: str | None = None,
    collection_name: str | None = None,
) -> int:
    """
    Execute full ingestion into Qdrant vector database.
    """
    settings = get_settings()
    target_dir = knowledge_dir or Path(settings.knowledge_dir)
    target_url = qdrant_url or settings.qdrant_url
    target_coll = collection_name or settings.qdrant_collection

    logger.info("Discovering knowledge documents in: %s", target_dir)
    chunks = load_all_chunks(target_dir)
    logger.info("Parsed %d chunks across documents.", len(chunks))

    provider = QdrantKnowledgeProvider(
        url=target_url,
        api_key=settings.qdrant_api_key,
        collection_name=target_coll,
    )

    indexed_count = await provider.index_chunks(chunks)
    logger.info("Ingestion completed: %d chunks indexed into '%s'.", indexed_count, target_coll)
    return indexed_count


def main() -> None:
    """CLI entrypoint for knowledge ingestion."""
    parser = argparse.ArgumentParser(description="SentinelOps Knowledge Ingestion Pipeline")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("knowledge"),
        help="Path to knowledge directory containing markdown documents",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default="http://localhost:6333",
        help="Qdrant database endpoint URL",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="sentinelops_knowledge",
        help="Target Qdrant collection name",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(
        run_ingestion(
            knowledge_dir=args.dir,
            qdrant_url=args.qdrant_url,
            collection_name=args.collection,
        )
    )


if __name__ == "__main__":
    main()
