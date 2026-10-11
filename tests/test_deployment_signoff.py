"""Requirement wording never establishes an individual deployment's compliance."""

from datetime import date
import json

import pytest

from decidr.approval_context import check_approval_context
from decidr.approval_propositions import compare_approval_rules
from decidr.deployment_signoff import deployment_event_findings
from decidr.retrieval_models import Evidence

RULE = "Production deployments touching customer billing require Head of Engineering sign-off before release."
EVENT = "The emergency billing deployment recorded on 18 February 2026 received Head of Engineering sign-off before release."


@pytest.mark.parametrize(
    "text",
    [
        RULE.replace("Production", "Staging"),
        RULE.replace("before", "after"),
        RULE.replace("Head of Engineering", "Head of Sales"),
        RULE + " Except emergencies.",
    ],
)
def test_other_requirements_abstain(text):
    assert compare_approval_rules(text, RULE) is None


def test_explicit_requirement_and_bounded_pronoun():
    assert compare_approval_rules(RULE, RULE)["evidence_entails_claim"]
    pronoun = RULE.replace("Head of Engineering", "his")
    assert compare_approval_rules(RULE, pronoun) is None
    assert compare_approval_rules(RULE, pronoun, "Head of Sales — Pat Jones") is None
    assert compare_approval_rules(RULE, pronoun, "Head of Engineering — Pat Jones")[
        "evidence_entails_claim"
    ]
    assert not check_approval_context(
        pronoun + " Emergency changes may bypass approval.",
        0,
        len(pronoun),
        "Head of Engineering — Pat Jones",
    )["compatible"]


def audit(**changes):
    row = {
        "event_id": "AUD-X",
        "related_record": "INC-X",
        "action": "Deployed emergency fix to billing integration",
        "object": "Production deployment - billing module",
        "timestamp": "2026-02-18 16:30",
        "notes": "No linked deployment sign-off record found for this change",
        **changes,
    }
    return Evidence(
        evidence_id="audit",
        source_id="s",
        source_type="audit_events",
        locator="row:1",
        extraction_method="test",
        text=json.dumps(row),
    )


def test_missing_record_is_not_negative_verdict_and_citation_is_exact():
    p = audit()
    r = deployment_event_findings(EVENT, [p], date(2026, 10, 11))
    assert len(r) == 1 and r[0]["status"] == "unresolved"
    assert "not proof" in r[0]["message"]
    c = r[0]["citation"]
    assert p.text[c["start"] : c["end"]] == c["quotation"]
    assert deployment_event_findings(EVENT, [p], date(2026, 2, 17)) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": "2026-02-19 16:30"},
        {"timestamp": "invalid"},
        {"object": "Staging deployment - billing module"},
        {"action": "Approved expense"},
    ],
)
def test_wrong_event_does_not_bind(changes):
    assert deployment_event_findings(EVENT, [audit(**changes)], date(2026, 10, 11)) == []


@pytest.mark.parametrize(
    "notes",
    [
        "Approved earlier that day",
        "Sign-off after release",
        "Approved by Head of Engineering at 17:00",
    ],
)
def test_free_text_cannot_prove_timing_or_authority(notes):
    r = deployment_event_findings(EVENT, [audit(notes=notes)], date(2026, 10, 11))
    assert r[0]["status"] == "unresolved"
    assert "alone does not establish" in r[0]["message"]


@pytest.mark.parametrize("padding", ["\n\n", " ", "\t\r\n"])
def test_trailing_whitespace_does_not_change_rule(padding):
    assert compare_approval_rules(RULE + padding, RULE)["evidence_entails_claim"]
    assert compare_approval_rules(RULE, RULE + padding)["evidence_entails_claim"]
