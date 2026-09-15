# Retrieval process boilerplate

**Status:** Structure only — retrieval logic and technology choices are intentionally deferred.

**Owners:** Mohanned Habib and Saif Muzaffar Parkar

## Purpose

The retrieval component will accept a structured organisational-knowledge query and return a
ranked set of candidate evidence. It will not decide whether evidence is credible, determine a
final answer, update the Facts Register, or construct the knowledge graph.

## Proposed boundary

```text
query or claim
    -> query preparation
    -> candidate retrieval backend(s)
    -> optional ranking or fusion
    -> evidence candidates with provenance
    -> applicability and credibility framework
```

Each returned candidate should retain its document identifier, exact locator, text, retrieval
score, and any Fact or knowledge-graph entities that helped retrieve it. Superseded material is
retained by default so the later credibility framework—not retrieval—can decide whether it is
applicable.

## Knowledge-graph handoff

The current graph draft contains these entity types:

- `DOCUMENT`: source type, status, source class, and relevant dates;
- `FACT`: a retrievable topic statement and category;
- `PERSON`, `ROLE`, `PROCESS`, `FUNCTION`, and `SYSTEM`: organisational context;
- relationships such as ownership, participation, access, reporting, governance, and
  supersession.

Future graph-aware retrieval may use entity identifiers or relationship paths as additional
search context. This boilerplate only reserves those fields; it does not define the final graph
schema, generate graph edges, or assume a graph database.

## Repository structure

```text
configs/retrieval.example.json  Placeholder configuration
decidr/retrieval.py             Typed retrieval contracts and backend interface
docs/retrieval_boilerplate.md   Scope, boundaries, and handoff notes
tests/test_retrieval.py         Contract and intentional-placeholder tests
```

## Deferred decisions

- lexical search implementation;
- embedding model and semantic search implementation;
- hybrid-ranking or score-fusion method;
- graph expansion rules and hop limits;
- evaluation dataset and measures such as Recall@k;
- final integration with the Facts Register, credibility framework, and frontend.

The next implementation step should be agreed jointly with the relevant component owners after
the interfaces and graph schema are reviewed.
