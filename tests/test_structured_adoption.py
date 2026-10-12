"""Corpus-shaped policy/meeting joins with contrastive evidence mutations."""

from test_authority_resolution import chain, resolve
import pytest


def structured_chain():
    sources, passages = chain()
    policy, meeting = sources["test:POL-01"], sources["test:MTG-01"]
    policy.header_evidence.append(
        {
            "scope": "document_header",
            "key": "document owner",
            "value": "Pat Jones, Finance",
            "quote": "- **Document owner:** Pat Jones, Finance",
        }
    )
    passages[1].text += "\n- **Document owner:** Pat Jones, Finance"
    meeting.header_evidence = [
        {
            "scope": "document_header",
            "key": "date",
            "value": "2025-02-24",
            "quote": "- **Date:** 2025-02-24",
        }
    ]
    decision = passages[2]
    decision.section = "Meeting > Final decision"
    decision.text = "Raise the Finance approval threshold from 10% to 20%, effective 2025-03-01. Option 3 (25%) was discussed but not adopted — Pat felt it removed too much oversight."

    def add(id, heading, text, source=None):
        p = decision.model_copy(
            update={
                "evidence_id": id,
                "locator": id,
                "heading": heading,
                "section": "Meeting > " + heading,
                "text": text,
                "source_id": source or meeting.source_id,
            }
        )
        passages.append(p)

    add("meeting-header", "Meeting", "- **Date:** 2025-02-24")
    add("owner", "Decision owner", "Pat Jones (policy owner), with Alex Smith's sign-off.")
    add(
        "action",
        "Actions",
        "- Pat Jones to update and circulate POL-01 by 2025-03-01. (Done — see POL-01.)\n- Sales to brief the team.",
    )
    add("conditions", "Conditions or exceptions", "None discussed or agreed.")
    add("unresolved", "Unresolved matters", "None recorded at the time.")
    add(
        "history",
        "Version history",
        "| Version | Effective | Change |\n|---|---|---|\n| 3.0 | 2025-03-01 | Threshold raised from 10% to 20%, approved at leadership/finance meeting 2025-02-24 |",
        policy.source_id,
    )
    return sources, passages


def test_adoption_understood_without_inventing_rights():
    sources, passages = structured_chain()
    passages = [p for p in passages if p.evidence_id != "rights"]
    result = resolve(sources, passages)
    assert next(c for c in result["checks"] if c["name"] == "adoption")["passed"]
    assert result["adoption_findings"][0]["actor"] == "Alex Smith"
    assert result["authority_verified"] is None
    assert any(g["kind"] == "evidence_gap" for g in result["gaps"])
    assert not any(g["kind"] == "interpretation_limit" for g in result["gaps"])


def test_structural_adoption_plus_rights_resolves():
    sources, passages = structured_chain()
    result = resolve(sources, passages)
    assert result["authority_verified"] is True
    assert {"history", "action", "owner", "meeting-header"} <= {
        c["evidence_id"] for c in result["citations"]
    }
    for c in result["citations"]:
        p = next(p for p in passages if p.evidence_id == c["evidence_id"])
        assert p.text[c["start"] : c["end"]] == c["quotation"]


@pytest.mark.parametrize(
    "id,before,after",
    [
        ("history", "| 3.0 |", "| 2.0 |"),
        ("history", "2025-02-24", "2025-02-25"),
        ("history", "10% to 20%", "15% to 20%"),
        ("action", "POL-01", "POL-02"),
        ("action", "Done", "Not done"),
        ("action", "2025-03-01", "2025-03-02"),
        ("owner", "Alex Smith's sign-off", "Alex Smith declined sign-off"),
        ("adoption", "Option 3 (25%)", "Option 3 (20%)"),
        ("adoption", "Raise the Finance", "Do not raise the Finance"),
        ("conditions", "None discussed or agreed.", "Subject to board ratification."),
        ("unresolved", "None recorded at the time.", "Adoption remains undecided."),
    ],
)
def test_contrastive_cases_do_not_verify(id, before, after):
    sources, passages = structured_chain()
    p = next(p for p in passages if p.evidence_id == id)
    p.text = p.text.replace(before, after)
    assert resolve(sources, passages)["authority_verified"] is None


def test_wrong_agenda_item_cannot_supply_signoff():
    sources, passages = structured_chain()
    next(
        p for p in passages if p.evidence_id == "owner"
    ).section = "Other agenda item > Decision owner"
    assert resolve(sources, passages)["authority_verified"] is None


def test_duplicate_version_with_unknown_change_blocks_join():
    sources, passages = structured_chain()
    history = next(p for p in passages if p.evidence_id == "history")
    history.text += "\n| 3.0 | 2025-03-01 | Approval withdrawn |"
    assert resolve(sources, passages)["authority_verified"] is None
