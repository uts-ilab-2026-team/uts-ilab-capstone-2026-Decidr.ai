"""Conservative, reviewable interpretation proposals for retrieved evidence.

The engine deliberately produces *proposals*, not final reviewer judgements.
It uses explicit, inspectable rules for polarity, rule-versus-event mode,
assessment target, scope, dates, source class and quality dimensions.  Every
proposal remains review-required and is shaped for the existing
``/api/corpus/assess-supplied`` endpoint.
"""

from dataclasses import dataclass
from datetime import date
import re
from typing import Literal

from decidr.approval_propositions import compare_approval_rules
from decidr.assessment_targets import AssessmentTarget, validate_target
from decidr.interpretation_models import InterpretationCitation
from decidr.retrieval_models import Evidence, Source
from decidr.source_metadata import approval_signals

Stance = Literal["support", "contradict", "qualify", "context", "unresolved"]
Mode = Literal["formal", "observed", "unresolved"]

IDENTIFIER_PATTERN = re.compile(
    r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![\w-])",
    flags=re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

OBSERVED_CUES = (
    "accessed",
    "approved",
    "assigned",
    "changed",
    "closed",
    "completed",
    "created",
    "deployed",
    "detected",
    "fixed",
    "opened",
    "occurred",
    "reassigned",
    "received",
    "rejected",
    "submitted",
    "tested",
    "timestamp",
    "updated",
    "verified",
)
REPORTING_CUES = (
    "audit log",
    "documented",
    "log states",
    "minutes state",
    "no linked",
    "record found",
    "record states",
    "recorded as",
    "reported",
)
NEGATION_PATTERN = re.compile(
    r"\b(no|not|never|without|did not|does not|is not|was not|were not)\b",
    flags=re.IGNORECASE,
)

# Values within one dictionary are mutually exclusive scope alternatives.
SCOPE_DIMENSIONS = (
    {
        "new_business": ("new-business", "new business"),
        "renewal": ("renewal", "renewals"),
    },
    {
        "production": ("production",),
        "staging": ("staging",),
        "development": ("development environment", "development system"),
    },
)

SOURCE_CLASS_BY_TYPE = {
    "policy": "approved_policy",
    "procedure": "approved_process",
    "technical": "approved_process",
    "audit_events": "system_verified",
    "audit": "system_verified",
    "crm_records": "structured_operational_record",
    "crm": "structured_operational_record",
    "project_tasks": "structured_operational_record",
    "meeting": "meeting_record",
    "interview": "interview",
    "internal_communication": "self_reported_communication",
    "organisational_information": "role_description",
    "role_description": "role_description",
    "annotation": "unknown",
}


@dataclass(frozen=True, slots=True)
class SourceJudgement:
    source_class: str
    approval_key: str
    authority_verified: bool | None
    basis: str


@dataclass(frozen=True, slots=True)
class InterpretationProposal:
    evidence_id: str
    source_id: str
    locator: str
    stance: Stance
    mode: Mode
    rationale: str
    citation: InterpretationCitation
    origin_id: str
    source_class: str
    approval_key: str
    scope_matches: bool | None
    temporal_matches: bool | None
    authority_verified: bool | None
    directness: float
    specificity: float
    completeness: float
    judgement_basis: str
    origin_basis: str
    independence_verified: bool
    independence_basis: str
    evidence_target: AssessmentTarget
    target_basis: str
    proposal_confidence: Literal["low", "medium", "high"]
    review_reasons: tuple[str, ...]
    review_required: bool = True
    comparison_method: str = "bounded-text-v1"
    field_comparison: dict | None = None

    def assessment_input(self) -> dict:
        """Return only fields accepted by ``SuppliedInput``."""
        return {
            "stance": self.stance,
            "mode": self.mode,
            "rationale": self.rationale,
            "citations": [self.citation.model_dump(mode="json")],
            "origin_id": self.origin_id,
            "source_class": self.source_class,
            "approval_key": self.approval_key,
            "scope_matches": self.scope_matches,
            "temporal_matches": self.temporal_matches,
            "authority_verified": self.authority_verified,
            "directness": self.directness,
            "specificity": self.specificity,
            "completeness": self.completeness,
            "judgement_basis": self.judgement_basis,
            "origin_basis": self.origin_basis,
            "independence_verified": self.independence_verified,
            "independence_basis": self.independence_basis,
            "evidence_target": self.evidence_target,
            "target_basis": self.target_basis,
        }

    def review_payload(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "locator": self.locator,
            "proposal_confidence": self.proposal_confidence,
            "review_required": self.review_required,
            "comparison_method": self.comparison_method,
            "field_comparison": self.field_comparison,
            "quality_status": "not_assessed",
            "review_reasons": list(self.review_reasons),
            "suggested_input": self.assessment_input(),
        }


def _lower(text: str) -> str:
    return text.casefold().replace("–", "-").replace("—", "-")


def _canonical(text: str) -> str:
    """Normalise typography and inclusive percentage spelling, retaining word order.

    No bag-of-words, stemming, actor substitution or inequality implication.
    Internal punctuation, dates, negation and scope remain part of the comparison.
    """
    text = _lower(text).strip()
    text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\bat least\s+(\d+(?:\.\d+)?)\s*%", r"\1% or greater", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s+or more\b", r"\1% or greater", text)
    return " ".join(text.rstrip(".!?").split())


def _sentences(text: str) -> list[tuple[int, int]]:
    """Exact spans; decimal points and identifiers are not sentence boundaries."""
    spans = []
    start = 0
    for match in re.finditer(r"[.!?](?=\s|$)|\n+", text):
        end = match.start() if match.group().startswith("\n") else match.start() + 1
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right and _canonical(text[left:right]):
            spans.append((left, right))
        start = match.end()
    if text[start:].strip():
        left = start + len(text[start:]) - len(text[start:].lstrip())
        spans.append((left, len(text.rstrip())))
    return spans or [(0, len(text))]


def infer_mode(text: str) -> Mode:
    lowered = _lower(text)
    if re.search(r"\b(reported|said|told|stated|wrote|asked|according to)\b", lowered):
        return "observed"
    if re.search(r"\b(must|shall|required|requires|require|prohibited)\b|\bmay only\b", lowered):
        return "formal"
    if re.search(r"\b(" + "|".join(OBSERVED_CUES) + r")\b", lowered):
        return "observed"
    return "unresolved"


def infer_target(text: str, mode: Mode | None = None) -> AssessmentTarget:
    lowered = _lower(text)
    if re.search(r"\b(reported|said|told|stated|wrote|asked|according to)\b", lowered):
        return "recorded_statement"
    if any(cue in lowered for cue in REPORTING_CUES):
        return "recorded_statement"
    selected = mode or infer_mode(text)
    return {"formal": "formal_rule", "observed": "underlying_event"}.get(selected, "unspecified")


def _scope_labels(text: str, dimension: dict[str, tuple[str, ...]]) -> set[str]:
    return {
        label
        for label, variants in dimension.items()
        if any(re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", _lower(text)) for v in variants)
    }


def infer_scope_match(claim: str, evidence: str, exact: bool) -> tuple[bool | None, str]:
    # Hyphenated ordinary words (e.g. new-business) are not record identifiers.
    def ids(text: str) -> set[str]:
        return {x.upper() for x in IDENTIFIER_PATTERN.findall(text) if any(c.isdigit() for c in x)}

    claim_ids, evidence_ids = ids(claim), ids(evidence)
    if claim_ids and evidence_ids and not claim_ids.issubset(evidence_ids):
        return False, "The cited passage does not match all requested record identifiers."
    for dimension in SCOPE_DIMENSIONS:
        left, right = _scope_labels(claim, dimension), _scope_labels(evidence, dimension)
        if left and right and left.isdisjoint(right):
            return False, "Explicit business or environment scopes conflict."
    if exact:
        return True, "Scope wording is preserved in the bounded proposition comparison."
    return None, "Shared words or identifiers alone do not verify scope."


def infer_temporal_match(
    claim: str,
    evidence_text: str,
    evidence: Evidence,
    source: Source,
    as_of: date,
    *,
    mode: Mode = "unresolved",
) -> tuple[bool | None, str]:
    if source.metadata_conflicts:
        return None, "Source metadata conflicts require review."
    try:
        claim_dates = {date.fromisoformat(x) for x in DATE_PATTERN.findall(claim)}
        passage_dates = {date.fromisoformat(x) for x in DATE_PATTERN.findall(evidence_text)}
    except ValueError:
        return None, "An invalid date appears in the claim or citation."
    if claim_dates and passage_dates and claim_dates.isdisjoint(passage_dates):
        return False, "Explicit dates differ; their event roles require review."
    if claim_dates and min(claim_dates) > as_of:
        return False, "The asserted date follows the assessment date."
    if mode == "formal":
        if source.effective_start_date and as_of < source.effective_start_date:
            return False, "The source is not yet effective."
        if source.effective_end_date and as_of > source.effective_end_date:
            return False, "The documented effective period has ended."
        if source.superseded_date:
            if as_of == source.superseded_date:
                return None, "Superseded-date boundary inclusion is unspecified."
            if as_of > source.superseded_date:
                return False, "The assessment follows the documented superseded date."
        bounded_history = source.effective_start_date and (
            source.effective_end_date or source.superseded_date
        )
        if source.lifecycle_status == "superseded" and not bounded_history:
            return None, "Historical applicability needs a documented interval."
        if source.effective_start_date:
            return True, "The assessment is within the documented effective interval."
    # A creation date, arbitrary *_date field or matching date substring cannot
    # establish which event occurred when. Leave that judgement to review.
    return None, "Temporal role of dates is not automatically verified for this proposition."


def classify_source(source: Source, evidence: Evidence) -> SourceJudgement:
    """Propose configured categories, never certify authority from source type.

    Historical approval and lifecycle are independent; the framework applies
    lifecycle at the requested assessment date.
    """
    source_type = source.source_type.casefold().strip()
    source_class = SOURCE_CLASS_BY_TYPE.get(source_type, "unknown")
    approval = (source.approval_status or "").casefold().strip()
    clauses = source.approval_clauses
    if clauses:
        approval = " ".join(
            c.get("quote", "") for c in clauses if c.get("scope") == "own_document"
        ).casefold()
    negative, positive = approval_signals(approval)
    if source.metadata_conflicts or (negative and positive):
        approval_key = "unknown"
    elif negative:
        approval_key = "unapproved"
    elif source.lifecycle_status == "draft":
        approval_key = "draft"
    elif positive:
        approval_key = "approved"
    elif approval in {"system record", "system_record"}:
        approval_key = "system_record"
    elif approval in {"accepted record", "accepted_record"}:
        approval_key = "accepted_record"
    else:
        approval_key = "unknown"
    return SourceJudgement(
        source_class,
        approval_key,
        None,
        f"Provisional type mapping: {source.source_type!r} -> {source_class!r}; "
        f"own approval={approval_key!r}. Authority requires external verification.",
    )


def _opposite(left: str, right: str) -> bool:
    """Only a complete explicit required/not-required proposition pair.

    Other negation (without, never, double negation, modality) remains unresolved.
    """
    pattern = r"(.+?) (is|are) (not )?required"
    a, b = re.fullmatch(pattern, left), re.fullmatch(pattern, right)
    if not a or not b:
        return False
    if NEGATION_PATTERN.search(a[1]) or NEGATION_PATTERN.search(b[1]):
        return False
    return a.group(1, 2) == b.group(1, 2) and bool(a[3]) != bool(b[3])


def _compare(left: str, right: str) -> Stance:
    if left == right:
        return "support"
    if _opposite(left, right):
        return "contradict"
    comparison = compare_approval_rules(left, right)
    if comparison is not None and comparison["equivalent"]:
        return "support"
    return "unresolved"


def propose_interpretation(
    *,
    claim_text: str,
    facet: str,
    assessment_target: AssessmentTarget,
    as_of: date,
    evidence: Evidence,
    source: Source,
) -> InterpretationProposal:
    """Compare a complete, explicit facet; preserve the original claim separately.

    This bounded comparator does not implement general entailment. Unknown
    authority and quality prevent the generated draft from deciding a verdict.
    """
    validate_target(assessment_target)
    if evidence.source_id != source.source_id:
        raise ValueError("Evidence and source identities do not match")
    if not claim_text.strip() or not facet.strip():
        raise ValueError("Claim and facet must not be blank")
    if type(as_of) is not date:
        raise ValueError("as_of must be an explicit date")

    proposition = _canonical(facet)
    spans = _sentences(evidence.text)
    comparisons = [(_compare(proposition, _canonical(evidence.text[a:b])), a, b) for a, b in spans]
    decisive = [x for x in comparisons if x[0] in {"support", "contradict"}]
    conflicting = len({x[0] for x in decisive}) > 1
    # Exact sentence matches are proposals only: other sentences can qualify them.
    if decisive and not conflicting:
        stance, start, end = decisive[0]
    else:
        stance, start, end = "unresolved", 0, len(evidence.text)
        if not conflicting:
            bounded = [
                (len(c["differences"]), a, b)
                for a, b in spans
                if (c := compare_approval_rules(proposition, evidence.text[a:b])) is not None
            ]
            if bounded:
                _, start, end = min(bounded)
    citation = InterpretationCitation(
        evidence_id=evidence.evidence_id,
        source_id=evidence.source_id,
        locator=evidence.locator,
        quotation=evidence.text[start:end],
        start=start,
        end=end,
    )
    text = citation.quotation
    mode = infer_mode(text)
    evidence_target = infer_target(text, mode)
    # A reported rule is evidence of a statement; being quoted in a policy does
    # not make it a rule. Interviews/communications cannot acquire rule authority
    # from the word "required".
    if source.source_type in {"interview", "internal_communication", "meeting"}:
        mode, evidence_target = "observed", "recorded_statement"
    scope, scope_basis = infer_scope_match(facet, text, bool(decisive) and not conflicting)
    temporal, temporal_basis = infer_temporal_match(
        facet, text, evidence, source, as_of, mode=mode
    )
    requested_target = (
        assessment_target if assessment_target != "unspecified" else infer_target(facet)
    )
    target_matches = requested_target != "unspecified" and requested_target == evidence_target
    mapping = classify_source(source, evidence)
    method = (
        "exact_proposition"
        if stance == "support"
        else "explicit_required_negation"
        if stance == "contradict"
        else "unresolved"
    )
    field_comparison = compare_approval_rules(proposition, text)
    if field_comparison is not None:
        method = "approval_fields_v1"
    rationale = {
        "support": "The citation preserves the facet's ordered wording under limited normalisation.",
        "contradict": "The complete proposition explicitly differs on required versus not required.",
        "unresolved": "No supported complete proposition comparison establishes this relationship.",
    }[stance]
    if field_comparison is not None:
        rationale = (
            "All extracted approval-rule fields agree under the bounded grammar."
            if field_comparison["equivalent"]
            else "Approval-rule fields differ; no general entailment is inferred: "
            + ", ".join(field_comparison["differences"])
            + "."
        )
    if conflicting:
        rationale = "The passage contains both matching and opposing propositions; review the full passage."
    elif scope is False or temporal is False:
        stance, rationale = "context", "Explicit scope or assessment-period constraints conflict."
    elif not target_matches and decisive:
        stance, rationale = (
            "context",
            "The matched wording establishes a different or unresolved evidence target.",
        )

    reasons = [
        scope_basis,
        temporal_basis,
        mapping.basis,
        "Confirm that the facet represents the submitted claim and is a complete proposition.",
        "Inspect the full passage and source context for qualifications or exceptions.",
        "Authority and independence are not verified by this engine.",
        "Quality is unassessed: zero placeholders must be replaced by justified review judgements.",
    ]
    if conflicting:
        reasons.append("Internal polarity conflict remains unresolved.")
    origin = source.duplicate_group or source.derived_from_source_id or source.source_id
    return InterpretationProposal(
        evidence_id=evidence.evidence_id,
        source_id=source.source_id,
        locator=evidence.locator,
        stance=stance,
        mode=mode,
        rationale=rationale,
        citation=citation,
        origin_id=origin,
        source_class=mapping.source_class,
        approval_key=mapping.approval_key,
        scope_matches=scope,
        temporal_matches=temporal,
        authority_verified=None,
        directness=0.0,
        specificity=0.0,
        completeness=0.0,
        judgement_basis="Unreviewed bounded comparison; authority and quality not assessed.",
        origin_basis=f"Provisional source-level origin from metadata: {origin}; review required.",
        independence_verified=False,
        independence_basis="",
        evidence_target=evidence_target,
        target_basis=f"Provisional target from source type and cited wording: {evidence_target}.",
        proposal_confidence="low",
        review_reasons=tuple(reasons),
        comparison_method=method,
        field_comparison=field_comparison,
    )
