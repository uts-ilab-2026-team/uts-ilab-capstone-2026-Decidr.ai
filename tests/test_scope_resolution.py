"""Scope clarification uses evidence, not guessed intent or expected verdicts."""

import pytest

from decidr.claim_scope import scope_context
from decidr.retrieval_models import Evidence, Source


@pytest.fixture
def scope_corpus():
    rows = [
        (
            "customer",
            "Customer Onboarding Policy",
            "policy",
            "Formal requirements",
            "Standard onboarding is completed within 6 weeks of assignment.",
        ),
        (
            "employee",
            "New Hire Onboarding Policy",
            "policy",
            "Formal requirements",
            "Every new hire completes a documented onboarding checklist within two weeks.",
        ),
        (
            "expense",
            "Expense Approval Policy",
            "policy",
            "Formal requirements",
            "Expense claims over $500 require Finance approval. Expense claims of $500 or less may be approved by the manager.",
        ),
        (
            "renewal",
            "Contract Renewal Process",
            "procedure",
            "Steps",
            "Account Executive leads commercial renewal conversation. Customer Success provides relationship-health input.",
        ),
        (
            "product",
            "Product Change Intake Process",
            "procedure",
            "Responsible / Accountable",
            "Product Manager (prioritisation), Head of Engineering (feasibility/sequencing).",
        ),
        (
            "product",
            "Product Change Intake Process",
            "procedure",
            "Required approvals",
            "Head of Engineering sign-off for P1 cards entering a sprint.",
        ),
    ]
    sources, passages = {}, []
    for index, (key, title, kind, heading, text) in enumerate(rows):
        sources[key] = Source(
            source_id=key,
            title=title,
            source_type=kind,
            original_file_path=f"{key}.md",
            checksum="b" * 64,
            ingestion_status="ingested",
        )
        passages.append(
            Evidence(
                evidence_id=f"ev:{index}",
                source_id=key,
                locator=f"p:{index}",
                source_type=kind,
                heading=heading,
                text=text,
                extraction_method="test",
            )
        )
    return sources, passages


@pytest.mark.parametrize(
    ("claim", "option"),
    [
        ("Onboarding takes six weeks.", "Customer implementation"),
        ("Finance must approve this expense.", "Over $500"),
        ("Sales owns renewals.", "Final accountability"),
        ("Engineering approves product requests.", "P1 entry into a sprint"),
    ],
)
def test_question_requires_corpus_and_preserves_claim(scope_corpus, claim, option):
    result = scope_context(claim, None, *scope_corpus)
    assert result["status"] == "clarification_available"
    assert result["facet"] == claim
    assert result["answer"] is None
    assert option in result["options"]
    originals = {p.evidence_id: p for p in scope_corpus[1]}
    for item in result["basis"]:
        passage = originals[item["evidence_id"]]
        assert (item["quotation"], item["locator"], item["source_id"]) == (
            passage.text,
            passage.locator,
            passage.source_id,
        )
    assert scope_context(claim, None, {}, [])["status"] == "not_requested"
    answered = scope_context(claim, option, *scope_corpus)
    assert answered["facet"] == claim + "\n\nScope supplied by user: " + option
    assert answered["status"] == "scope_supplied"
    assert "assessment" not in answered


@pytest.mark.parametrize(
    "claim",
    [
        "Customer onboarding takes six weeks from contract signature.",
        "All new hires finish onboarding within two weeks.",
        "Onboarding for employees takes six weeks.",
        "All onboarding takes six weeks.",
        "Every expense requires Finance approval.",
        "Finance approves my $400 expense.",
        "Finance approves my expense of five hundred dollars.",
        "Sales owns commercial renewal negotiations.",
        "Sales has final accountability for renewals.",
        "Engineering approves all product requests.",
        "Engineering approves P1 entry into a sprint.",
        "Engineering owns product prioritisation.",
        "An invoice is generated when a deal closes.",
        "Employees can export customer data.",
        "Support always raises a ticket before escalation.",
        "The customer completed onboarding on time.",
        "DEAL-123 needs discount approval.",
        "deal-123 needs discount approval.",
        "The formally effective threshold on 19 May 2025 was 10%.",
    ],
)
def test_clear_claims_omitted_conditions_and_record_targets_not_rewritten(scope_corpus, claim):
    result = scope_context(claim, None, *scope_corpus)
    assert result["status"] == "not_requested"
    assert result["facet"] == claim


def test_question_not_derived_from_interview_or_unrelated_title(scope_corpus):
    sources, passages = scope_corpus
    sources["employee"].source_type = "interview"
    assert (
        scope_context("Onboarding takes six weeks.", None, sources, passages)["status"]
        == "not_requested"
    )
    sources["employee"].source_type = "policy"
    sources["employee"].title = " unrelated policy "
    assert (
        scope_context("Onboarding takes six weeks.", None, sources, passages)["status"]
        == "not_requested"
    )


def test_no_question_if_one_side_of_distinction_missing(scope_corpus):
    sources, passages = scope_corpus
    passages = [p for p in passages if p.heading != "Required approvals"]
    assert (
        scope_context("Engineering approves product requests.", None, sources, passages)["status"]
        == "not_requested"
    )


def test_unknown_free_text_is_retained_as_user_input(scope_corpus):
    claim = "Onboarding takes six weeks."
    result = scope_context(claim, "Contractors in another division", *scope_corpus)
    assert result["answer"] == "Contractors in another division"
    assert result["basis"] == []
    assert result["question"] is None
