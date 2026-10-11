"""Linked meetings retain decision context without asserting adoption."""

from datetime import date

from decidr.authority_links import explicit_authority_links
from decidr.retrieval_models import Evidence, Source


def passage(identifier, heading, text, parent="Meeting > Agenda A", source_id="phase2:meeting"):
    return Evidence(
        evidence_id=identifier, source_id=source_id, text=text,
        section=f"{parent} > {heading}", heading=heading,
        locator=f"heading:{parent} > {heading}#block:{identifier}",
        source_type="meeting", extraction_method="test",
    )


def run(passages, source_type="meeting"):
    def source(identifier, title, kind):
        return Source(source_id=identifier, title=title, source_type=kind,
                      original_file_path="test.md", checksum="a" * 64,
                      ingestion_status="ingested")
    target = source("phase2:policy", "POL-88 — Example", "policy")
    return explicit_authority_links(
        source=target, sources=[target, source("phase2:meeting", "Meeting", source_type)],
        passages=passages, as_of=date(2026, 6, 1),
    )


def test_decision_and_signoff_are_cited_without_promoting_authority():
    seed = passage("a", "Actions", "Update POL-88 after approval.")
    decision = passage("b", "Final decision", "Not approved; review next month.")
    owner = passage("c", "Decision owner", "Morgan, subject to committee sign-off.")
    exception = passage("d", "Conditions or exceptions", "Pilot only.")
    unresolved = passage("e", "Unresolved matters", "Scope remains unsettled.")
    result = run([seed, decision, owner, exception, unresolved])
    link = result["links"][0]
    contexts = link["meeting_context"]["passages"]
    assert {p["citation"]["evidence_id"] for p in contexts} == {"b", "c", "d", "e"}
    originals = {p.evidence_id: p for p in [decision, owner, exception, unresolved]}
    for item in contexts:
        citation = item["citation"]
        original = originals[citation["evidence_id"]]
        assert citation["quotation"] == original.text[citation["start"]:citation["end"]]
        assert citation["locator"] == original.locator
    assert result["total_matches"] == 1
    assert link["adoption_status"] == "unresolved"
    assert result["authority_verified"] is None


def test_other_agenda_sources_and_options_are_not_expanded():
    seed = passage("a", "Actions", "Update POL-88.")
    unrelated = [
        passage("b", "Final decision", "Approved", parent="Meeting > Agenda B"),
        passage("c", "Final decision", "Approved", source_id="phase2:other"),
        passage("d", "Options considered", "Approve, reject or defer."),
    ]
    assert run([seed, *unrelated])["links"][0]["meeting_context"]["passages"] == []


def test_nonmeeting_does_not_expand_sibling_sections():
    items = [passage("a", "Actions", "POL-88"), passage("b", "Final decision", "Approved")]
    assert run(items, "internal_communication")["links"][0]["meeting_context"]["status"] == "not_expanded"


def test_missing_hierarchy_does_not_guess_context():
    seed = passage("a", "Actions", "POL-88").model_copy(update={"section": None})
    assert run([seed])["links"][0]["meeting_context"]["status"] == "not_expanded"


def test_context_bound_is_disclosed_and_order_is_stable():
    items = [passage("a", "Actions", "POL-88")]
    items += [passage(str(i), "Final decision", f"Decision {i}") for i in range(10)]
    context = run(items)["links"][0]["meeting_context"]
    assert context["total_matches"] == 10
    assert len(context["passages"]) == 8
    assert context["omitted_matches"] == 2
    assert run(items) == run(list(reversed(items)))
