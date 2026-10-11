"""Explicit authority chains and fail-closed boundary cases."""

from datetime import date

import pytest

from decidr.authority_resolution import resolve_authority
from decidr.interpretation_models import InterpretationCitation
from decidr.retrieval_models import Evidence, Source

RULE = "Any discount of at least 20% off list price on a new-business deal requires written approval from Finance before the deal is marked won."
ADOPT = "On 2025-02-24, Alex Smith adopted POL-01 version 3.0 for new-business deals, effective 2025-03-01."
RIGHT = "Alex Smith has authority to adopt POL-01 version 3.0 for new-business deals from 2024-01-01 through 2025-12-31."


def chain():
    def source(id, title, kind, checksum):
        return Source(
            source_id=id,
            title=title,
            source_type=kind,
            checksum=checksum * 64,
            original_file_path=id + ".md",
            ingestion_status="ingested",
            lifecycle_status="current",
            creation_date=date(2024, 1, 1),
        )

    policy = source("test:POL-01", "POL-01 Policy", "policy", "a")
    policy.version = "3.0"
    policy.effective_start_date = date(2025, 3, 1)
    policy.approval_status = "Approved"
    policy.approval_clauses = [
        {"scope": "own_document", "quote": "Approved", "start": 0, "end": 8}
    ]
    rows = [("version", "3.0"), ("approval status", "Approved"), ("effective date", "2025-03-01")]
    header = "\n".join(f"- **{k}:** {v}" for k, v in rows)
    policy.header_evidence = [
        {"scope": "document_header", "key": k, "value": v, "quote": f"- **{k}:** {v}"}
        for k, v in rows
    ]
    meeting = source("test:MTG-01", "Meeting", "meeting", "b")
    meeting.creation_date = date(2025, 2, 24)
    rights = source("test:rights", "Rights", "organisational_information", "c")

    def passage(id, source, text, heading):
        return Evidence(
            evidence_id=id,
            source_id=source.source_id,
            text=text,
            locator=id,
            heading=heading,
            source_type=source.source_type,
            extraction_method="test",
        )

    focal = passage("rule", policy, RULE, "Formal requirements")
    passages = [
        focal,
        passage("header", policy, header, "Header"),
        passage("adoption", meeting, ADOPT, "Final decision"),
        passage("rights", rights, RIGHT, "Decision rights"),
    ]
    sources = {s.source_id: s for s in (policy, meeting, rights)}
    return sources, passages


def resolve(sources, passages):
    focal = passages[0]
    return resolve_authority(
        source=sources[focal.source_id],
        focal=focal,
        citation=InterpretationCitation(
            evidence_id=focal.evidence_id,
            source_id=focal.source_id,
            locator=focal.locator,
            quotation=focal.text,
            start=0,
            end=len(focal.text),
        ),
        sources=sources,
        passages=passages,
        as_of=date(2026, 6, 17),
    )


def test_complete_dated_chain_and_exact_citations():
    sources, passages = chain()
    result = resolve(sources, passages)
    assert result["authority_verified"] is True
    for citation in result["citations"]:
        text = next(p.text for p in passages if p.evidence_id == citation["evidence_id"])
        assert text[citation["start"] : citation["end"]] == citation["quotation"]


@pytest.mark.parametrize(
    "before,after",
    [
        ("Alex Smith", "Pat Jones"),
        ("version 3.0", "version 2.0"),
        ("new-business", "renewal"),
        ("2024-01-01", "2025-03-01"),
        ("2025-12-31", "2025-01-01"),
        ("has authority", "has no authority"),
        ("to adopt", "to approve transactions under"),
        ("2025-12-31", "2025-99-99"),
    ],
)
def test_mismatching_or_unsupported_rights_abstain(before, after):
    sources, passages = chain()
    passages[3].text = RIGHT.replace(before, after)
    assert resolve(sources, passages)["authority_verified"] is None


@pytest.mark.parametrize(
    "which,field,value",
    [
        ("test:rights", "creation_date", None),
        ("test:rights", "creation_date", date(2025, 3, 1)),
        ("test:MTG-01", "creation_date", date(2027, 1, 1)),
        ("test:MTG-01", "lifecycle_status", "draft"),
        ("test:POL-01", "lifecycle_status", "draft"),
        ("test:rights", "derived_from_source_id", "test:POL-01"),
        ("test:rights", "checksum", "a" * 64),
        ("test:rights", "metadata_conflicts", [{"field": "date"}]),
        ("test:POL-01", "header_evidence", []),
        ("test:POL-01", "superseded_date", date(2026, 6, 17)),
    ],
)
def test_source_safeguards(which, field, value):
    sources, passages = chain()
    setattr(sources[which], field, value)
    assert resolve(sources, passages)["authority_verified"] is None


def test_exception_is_not_ignored():
    sources, passages = chain()
    passages.append(
        passages[2].model_copy(
            update={"evidence_id": "negative", "text": "POL-01 version 3.0 was not adopted."}
        )
    )
    result = resolve(sources, passages)
    assert result["authority_verified"] is None
    assert "negative" in result["blocking_evidence_ids"]


def test_missing_rights_and_circular_records():
    sources, passages = chain()
    assert resolve(sources, passages[:3])["authority_verified"] is None
    sources["test:MTG-01"].duplicate_group = "copy"
    sources["test:rights"].duplicate_group = "copy"
    assert resolve(sources, passages)["authority_verified"] is None


def test_unreferenced_condition_blocks_an_otherwise_complete_chain():
    sources, passages = chain()
    passages.append(
        passages[2].model_copy(
            update={
                "evidence_id": "condition",
                "heading": "Conditions or exceptions",
                "text": "Approval is conditional on board ratification.",
            }
        )
    )
    result = resolve(sources, passages)
    assert result["authority_verified"] is None
    assert "condition" in result["blocking_evidence_ids"]


def test_cross_release_rights_cannot_verify_adoption():
    sources, passages = chain()
    source = sources.pop("test:rights")
    source.source_id = "other:rights"
    sources[source.source_id] = source
    passages[3].source_id = source.source_id
    assert resolve(sources, passages)["authority_verified"] is None


@pytest.mark.parametrize("heading", ["Revocations", "Notes"])
def test_revocation_in_another_heading_blocks_resolution(heading):
    sources, passages = chain()
    passages.append(
        passages[3].model_copy(
            update={
                "evidence_id": "revocation",
                "heading": heading,
                "text": "Alex Smith's authority to adopt POL-01 was revoked on 2025-02-01.",
            }
        )
    )
    assert resolve(sources, passages)["authority_verified"] is None
