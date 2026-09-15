import pytest

from decidr.retrieval import (
    EvidenceCandidate,
    RetrievalMode,
    RetrievalQuery,
    retrieve_candidates,
)


def test_retrieval_query_defaults_to_lexical_boilerplate():
    query = RetrievalQuery(text="Who owns the onboarding process?")

    assert query.mode == RetrievalMode.LEXICAL
    assert query.top_k == 10
    assert query.include_superseded is True


def test_candidate_contract_preserves_document_and_graph_context():
    candidate = EvidenceCandidate(
        document_id="POL-001",
        locator="section:approval",
        text="Example evidence text.",
        fact_statement="discount-approval authority",
        fact_category="authority",
        matched_entity_ids=("ROLE:Finance", "PROCESS:P1"),
    )

    assert candidate.document_id == "POL-001"
    assert candidate.fact_category == "authority"
    assert candidate.matched_entity_ids == ("ROLE:Finance", "PROCESS:P1")


def test_retrieval_execution_is_explicitly_deferred():
    query = RetrievalQuery(text="What is the current discount approval rule?")

    with pytest.raises(NotImplementedError, match="boilerplate only"):
        retrieve_candidates(query)
