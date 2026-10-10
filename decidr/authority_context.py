"""Cited authority assertions, kept separate from verified decision authority."""

from collections.abc import Iterable

from decidr.approval_propositions import parse_approval_rule
from decidr.interpretation_models import InterpretationCitation
from decidr.retrieval_models import Evidence, Source
from decidr.source_metadata import HEADER, approval_lifecycle


def _finding(status="unresolved", value=None, citations=(), reason=""):
    return {
        "status": status,
        "value": value,
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "reason": reason,
    }


def _header_citations(source: Source, passages: list[Evidence], key: str):
    """Only ingestion-scoped header quotations that match stored evidence exactly."""
    found = []
    for entry in source.header_evidence:
        if entry.get("scope") != "document_header" or entry.get("key") != key:
            continue
        quote = entry.get("quote")
        if not isinstance(quote, str) or not quote:
            continue
        parsed = HEADER.fullmatch(quote)
        if (
            not parsed
            or parsed["key"].strip().casefold() != key
            or parsed["value"].strip() != entry.get("value", "").strip()
        ):
            continue
        for passage in passages:
            start = passage.text.find(quote)
            if start < 0:
                continue
            # Ambiguous duplicate occurrences cannot establish a unique span.
            if passage.text.find(quote, start + 1) >= 0:
                continue
            found.append(
                (
                    entry,
                    InterpretationCitation(
                        evidence_id=passage.evidence_id,
                        source_id=passage.source_id,
                        locator=passage.locator,
                        quotation=quote,
                        start=start,
                        end=start + len(quote),
                    ),
                )
            )
            break
    return found


def authority_context(
    *,
    source: Source,
    focal: Evidence,
    citation: InterpretationCitation,
    passages: Iterable[Evidence],
    facet: str,
    as_of: str,
) -> dict:
    """Expose assertions and gaps; never set authority_verified or scoring inputs.

    Header metadata must be grounded in an original same-source passage. The
    rule approver is extracted only from the already selected focal quotation.
    This neither authenticates a document nor proves policy-making authority.
    """
    if focal.source_id != source.source_id or citation.evidence_id != focal.evidence_id:
        raise ValueError("Authority context identities do not match")
    if (
        citation.source_id != focal.source_id
        or citation.locator != focal.locator
        or focal.text[citation.start : citation.end] != citation.quotation
    ):
        raise ValueError("Authority context citation does not match evidence")
    local = sorted(
        (p for p in passages if p.source_id == source.source_id), key=lambda p: p.evidence_id
    )
    owner_rows = _header_citations(source, local, "document owner")
    approval_rows = _header_citations(source, local, "approval status")
    owner_values = {entry.get("value", "").strip() for entry, _ in owner_rows}
    owner_values.discard("")
    owner = _finding(
        citations=[c for _, c in owner_rows],
        reason="No uniquely documented owner could be grounded in stored passages.",
    )
    if len(owner_values) == 1:
        owner = _finding(
            "documented_assertion",
            next(iter(owner_values)),
            [c for _, c in owner_rows],
            "The header names an owner; ownership does not establish adoption authority.",
        )
    elif len(owner_values) > 1:
        owner["status"] = "conflicting_assertions"

    # Use ingestion's own-document attribution rather than approval substrings.
    own_clauses = [c for c in source.approval_clauses if c.get("scope") == "own_document"]
    approval = _finding(
        citations=[c for _, c in approval_rows],
        reason="Document-scoped approval clauses and exact header evidence are required.",
    )
    raw_values = {entry.get("value", "").strip() for entry, _ in approval_rows}
    raw_values.discard("")
    grounded = len(raw_values) == 1 and source.approval_status in raw_values
    if grounded and own_clauses:
        raw = source.approval_status
        valid = all(
            isinstance(c.get("start"), int)
            and isinstance(c.get("end"), int)
            and 0 <= c["start"] < c["end"] <= len(raw)
            and raw[c["start"] : c["end"]] == c.get("quote")
            for c in own_clauses
        )
        if valid:
            local_status, _, conflicts = approval_lifecycle(
                " ".join(c["quote"] for c in own_clauses), ""
            )
            approval = _finding(
                "unresolved" if conflicts or source.metadata_conflicts else "documented_assertion",
                local_status,
                [c for _, c in approval_rows],
                "This is the document's recorded status, not independent verification of its authorisation.",
            )

    rule = parse_approval_rule(citation.quotation)
    operational = _finding(
        reason="The focal quotation is outside the supported complete approval-rule grammar."
    )
    if rule and source.source_type in {"policy", "procedure"}:
        operational = _finding(
            "documented_assertion",
            rule.model_dump(),
            [citation],
            "The rule names an operational approver and conditions; it does not establish policy-making authority or historical role occupancy.",
        )
    return {
        "version": "authority-context-v1",
        "facet": facet,
        "as_of": as_of,
        "source_id": source.source_id,
        "evidence_id": focal.evidence_id,
        "document_owner": owner,
        "document_approval": approval,
        "operational_approver": operational,
        "policy_adoption": _finding(
            reason="Cross-document adoption and sign-off evidence has not been resolved by this component."
        ),
        "authority_verified": None,
        "review_required": True,
        "evidence_scope": "same_source_headers_and_focal_quotation",
        "limitations": [
            "Assertions do not establish independence, authenticity or temporal applicability.",
            "Role occupancy, delegation and cross-document decision rights are not resolved.",
            "Context citations are not additional support votes and do not change assessment inputs.",
            "This context is returned for inspection; supplied-assessment history does not yet store it as a separate authority record.",
        ],
    }
