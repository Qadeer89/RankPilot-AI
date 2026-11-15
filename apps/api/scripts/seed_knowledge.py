#!/usr/bin/env python
"""Run the AI Knowledge Assistant's seed-docs ingestion once, standalone.

Usage: python -m scripts.seed_knowledge
(run from apps/api, with RANKPILOT_OPENAI_API_KEY set)
"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.knowledge.ingestion import ingest_seed_docs


def main() -> None:
    db = SessionLocal()
    try:
        job = ingest_seed_docs(db)
        db.commit()
        print(f"Ingestion job {job.id}: {job.status.value}, {job.documents_processed} docs, {job.chunks_created} chunks created")
    finally:
        db.close()


if __name__ == "__main__":
    main()
