"""Pre-index corpus embeddings into the persistent cache (the ingestion-time step).

Run once after building or updating the corpus so each claim check reuses the stored vectors
instead of re-embedding every passage. Requires a local Ollama embedding model to be running;
if none is available nothing is written and assessments fall back to lexical-only retrieval.

    uv run python -m decidr.preindex
"""

from __future__ import annotations

from decidr.finding_shim import load_corpus_snapshot
from decidr.semantic import get_embedder, index_evidence


def main() -> None:
    embedder = get_embedder()
    if embedder is None:
        print("no local embedder available: start Ollama and pull the embedding model first")
        return

    snapshot = load_corpus_snapshot()
    evidence = [
        passage for passages in snapshot.evidence_by_source.values() for passage in passages
    ]
    indexed = index_evidence(evidence, embedder)
    print(f"model: {embedder.name} ({embedder.version})")
    print(f"embedded {indexed} new passage(s); {len(evidence)} total in the persistent cache")


if __name__ == "__main__":
    main()
