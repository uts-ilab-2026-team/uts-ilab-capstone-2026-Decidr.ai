"""References cannot silently become verified sign-off or authority."""

from datetime import date

import pytest

from decidr.authority_links import explicit_authority_links
from decidr.retrieval_models import Evidence, Source


def source(identifier, title, **changes):
    return Source(source_id=identifier, title=title, source_type="meeting",
                  original_file_path="test.md", checksum="a" * 64,
                  ingestion_status="ingested", **changes)


def evidence(identifier, owner, text):
    return Evidence(evidence_id=identifier, source_id=owner, text=text,
                    locator="heading:Decision#block:001", source_type="meeting",
                    extraction_method="test")


def run(text="Do not approve POL-77 until reviewed.", **changes):
    target = source("phase2:policy", "POL-77 — Arbitrary Policy")
    other = source("phase2:meeting", "Meeting", creation_date=date(2026, 7, 1))
    args = dict(source=target, sources=[target, other],
                passages=[evidence("e", other.source_id, text)], as_of=date(2026, 6, 1))
    args.update(changes)
    return explicit_authority_links(**args)


def test_negative_reference_preserved_without_adoption_inference():
    result = run()
    link = result["links"][0]
    assert link["citation"]["quotation"] == "Do not approve POL-77 until reviewed."
    assert link["adoption_status"] == "unresolved"
    assert result["authority_verified"] is None
    assert result["scope_matches"] is None
    assert result["temporal_matches"] is None
    assert link["date_context"]["status"] == "recorded_after_assessment"


@pytest.mark.parametrize("text", ["POL-770", "X-POL-77", "POL-77-OLD", "Similar policy"])
def test_no_partial_code_or_topic_links(text):
    assert run(text)["total_matches"] == 0


def test_same_source_and_other_release_are_not_links():
    passages = [evidence("a", "phase2:policy", "POL-77"),
                evidence("b", "phase1:meeting", "POL-77")]
    assert run(passages=passages)["total_matches"] == 0


def test_ambiguous_code_stays_unresolved():
    sources = [source("phase2:policy", "POL-77 — One"),
               source("phase2:other", "POL-77 — Two")]
    result = run(sources=sources)
    assert result["status"] == "unresolved"
    assert result["links"] == []


def test_bounds_disclose_omissions_and_stable_order():
    passages = [evidence(str(i), "phase2:meeting", "POL-77 approved") for i in range(15)]
    result = run(passages=passages, limit=2)
    assert result["total_matches"] == 15
    assert result["omitted_matches"] == 13
    assert len(result["links"]) == 2
    assert result == run(passages=list(reversed(passages)), limit=2)


def test_excluded_source_is_not_used():
    sources = [source("phase2:policy", "POL-77 — One"),
               source("phase2:meeting", "Meeting")]
    sources[1].ingestion_status = "excluded"
    assert run(sources=sources)["total_matches"] == 0


def test_undated_source_remains_unresolved():
    sources = [source("phase2:policy", "POL-77 — One"),
               source("phase2:meeting", "Meeting")]
    assert run(sources=sources)["links"][0]["date_context"]["status"] == "unresolved"


def test_positive_reference_also_does_not_verify_authority():
    result = run("POL-77 was approved by the committee.")
    assert result["links"][0]["adoption_status"] == "unresolved"
    assert result["authority_verified"] is None
