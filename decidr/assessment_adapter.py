"""Isolated facet assessment using explicitly supplied judgements.

Citation validation establishes provenance,
not semantic correctness. Caller-supplied judgements require their own evaluation.
Version 1 uses source-level origins and accepts one source per interpretation.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

from framework.config import GraphCredibilityConfig
from framework.credibility import GraphCredibilityFramework
from framework.graph import OrganisationalGraph
from framework.models import FactAssessment, GraphEdge, GraphNode

from decidr.assessment_targets import AssessmentTarget, target_exclusion, validate_target
from decidr.interpretation_models import EvidenceInterpretation, validate_interpretation
from decidr.retrieval_models import Evidence, Source
from decidr.source_metadata import DOCUMENT_REFERENCE, approval_lifecycle, approval_signals


@dataclass(frozen=True)
class PreparedAttestation:
    interpretation: EvidenceInterpretation
    source: Source
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
    independence_verified: bool = False
    independence_basis: str = ""
    evidence_target: AssessmentTarget = "unspecified"
    target_basis: str = ""


@dataclass(frozen=True)
class InputDisposition:
    input_id: str
    interpretation: EvidenceInterpretation
    source: Source
    supplied_judgements: dict
    edge_id: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FacetAssessmentResult:
    claim_text: str
    facet: str
    as_of: date
    assessment: FactAssessment
    inputs: tuple[InputDisposition, ...]
    limitations: tuple[str, ...]
    assessment_target: AssessmentTarget = "unspecified"


def _apply_policy_precedence(nodes, edges, dispositions, *, as_of, config):
    """Prefer material applicable policies over contrary role/table summaries.

    All inputs already passed admission. Policy materiality is checked without
    summaries so a summary cannot bootstrap the policy that displaces it.
    """
    policy_ids = set()
    for item in dispositions:
        if item.edge_id is None or item.interpretation.mode != "formal":
            continue
        source = item.source
        supplied = item.supplied_judgements
        code = DOCUMENT_REFERENCE.match(source.title)
        _, clauses, _ = approval_lifecycle(source.approval_status, code[0] if code else "")
        negative, positive = approval_signals(
            " ".join(clause["quote"] for clause in clauses if clause["scope"] == "own_document")
        )
        if (
            source.source_type == "policy"
            and supplied["source_class"] == "approved_policy"
            and supplied["approval_key"] == "approved"
            and source.effective_start_date is not None
            and positive
            and not negative
        ):
            policy_ids.add(item.edge_id)
    policy_edges = [edge for edge in edges if edge.edge_id in policy_ids]
    if not policy_edges:
        return edges, dispositions, ()
    policy_graph = OrganisationalGraph(nodes, policy_edges, version="policy-precedence-v1")
    policy_assessment = GraphCredibilityFramework(policy_graph, config).evaluate_fact(
        "fact:facet", as_of=as_of
    )
    # Competing eligible policies must remain available for conflict reasoning,
    # even when one is below the materiality threshold.
    stances = {edge.attributes["agrees"] for edge in policy_edges}
    material_ids = {item.edge_id for item in policy_assessment.evidence if item.material}
    if len(stances) != 1 or not material_ids:
        return edges, dispositions, ()
    policy_stance = "support" if next(iter(stances)) else "contradict"
    governing = sorted(
        item.source.source_id for item in dispositions if item.edge_id in material_ids
    )
    excluded = set()
    updated = []
    notes = []
    for item in dispositions:
        if (
            item.edge_id is not None
            and item.interpretation.mode == "formal"
            and item.interpretation.stance != policy_stance
            and item.source.source_type == "organisational_information"
            and item.supplied_judgements["source_class"] in {"role_description", "decision_table"}
        ):
            reason = (
                "Policy precedence: conflicting role/table summary retained as a documentation "
                "inconsistency; applicable approved policy evidence governs this formal facet: "
                + ", ".join(governing)
                + "."
            )
            excluded.add(item.edge_id)
            updated.append(replace(item, edge_id=None, reasons=(*item.reasons, reason)))
            notes.append(f"{item.source.title}: {reason}")
        else:
            updated.append(item)
    return [edge for edge in edges if edge.edge_id not in excluded], updated, tuple(notes)


def assess_prepared_facet(
    *,
    claim_text: str,
    facet: str,
    as_of: date,
    prepared: Iterable[PreparedAttestation],
    evidence: Iterable[Evidence],
    config: GraphCredibilityConfig,
    assessment_target: AssessmentTarget = "unspecified",
) -> FacetAssessmentResult:
    """Assess one facet; never aggregate it into a whole-claim verdict.

    Context, qualification and unresolved inputs remain in the result without
    scoring edges. Ineligible or uncertain inputs retain specific reasons.
    No existing graph, database, source, or interpretation is modified.
    """
    if not isinstance(claim_text, str) or not claim_text.strip():
        raise ValueError("claim_text must not be blank")
    if not isinstance(facet, str) or not facet.strip():
        raise ValueError("facet must not be blank")
    if type(as_of) is not date:
        raise ValueError("as_of must be an explicit date")

    validate_target(assessment_target)
    passages = tuple(evidence)
    if len({p.evidence_id for p in passages}) != len(passages):
        raise ValueError("Duplicate evidence IDs")
    items = tuple(prepared)
    nodes = [
        GraphNode(
            "fact:facet",
            "fact",
            facet,
            {
                "statement": facet,
                "claim_text": claim_text,
                "category": "corpus-facet",
                "assessment_target": assessment_target,
            },
        )
    ]
    edges = []
    dispositions = []
    sources = {}
    origins = {}
    duplicate_origins = {}

    # Check all source/origin declarations, including non-scoring inputs.
    for item in items:
        validate_target(item.evidence_target)
        if not isinstance(item.target_basis, str):
            raise TypeError("target_basis must be a string")
        if item.evidence_target != "unspecified" and not item.target_basis.strip():
            raise ValueError("Explicit evidence target requires a target_basis")
        if type(item.independence_verified) is not bool or not isinstance(
            item.independence_basis, str
        ):
            raise ValueError("Invalid independence judgement types")
        if item.independence_verified and not item.independence_basis.strip():
            raise ValueError("Verified independence requires a basis")
        source = item.source
        source_json = source.model_dump(mode="json")
        for name in (
            "origin_id",
            "source_class",
            "approval_key",
            "judgement_basis",
            "origin_basis",
        ):
            value = getattr(item, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be explicitly supplied")
        previous = sources.setdefault(source.source_id, source_json)
        if previous != source_json:
            raise ValueError("Conflicting snapshots for one source")
        previous_origin = origins.setdefault(source.source_id, item.origin_id)
        if previous_origin != item.origin_id:
            raise ValueError("One source cannot have multiple origins in version 1")
        if source.duplicate_group:
            origin = duplicate_origins.setdefault(source.duplicate_group, item.origin_id)
            if origin != item.origin_id:
                raise ValueError("Documented duplicates must share an origin")

    for item in items:
        parent = item.source.derived_from_source_id
        if parent:
            if parent not in origins:
                raise ValueError("Derived source requires its parent's origin declaration")
            if origins[parent] != item.origin_id:
                raise ValueError("Derived sources must share their parent's origin")

    for index, item in enumerate(items, start=1):
        interpretation = validate_interpretation(
            item.interpretation, passages, claim_text=claim_text
        )
        if interpretation.facet != facet:
            raise ValueError("Interpretation belongs to a different facet")
        if {c.source_id for c in interpretation.citations} != {item.source.source_id}:
            raise ValueError("Version 1 requires citations from exactly the supplied source")

        for name in ("scope_matches", "temporal_matches", "authority_verified"):
            value = getattr(item, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{name} must be true, false or None")
        for name in ("directness", "specificity", "completeness"):
            value = getattr(item, name)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be a finite number between 0 and 1")
        if item.source_class not in config.source_class_weights:
            raise ValueError("source_class has no configured weight")
        if item.approval_key not in config.approval_weights:
            raise ValueError("approval_key has no configured weight")

        source = item.source
        reasons = []
        if interpretation.mode == "formal":
            code_match = DOCUMENT_REFERENCE.match(source.title)
            _, clauses, _ = approval_lifecycle(
                source.approval_status, code_match[0] if code_match else ""
            )
            own_approval = " ".join(
                clause["quote"] for clause in clauses if clause["scope"] == "own_document"
            )
            negative, _ = approval_signals(own_approval)
            if negative:
                reasons.append(
                    "Stored own-document approval explicitly includes non-approval; "
                    "supplied authority cannot establish an effective formal rule."
                )
            if item.approval_key in {"unapproved", "draft"}:
                reasons.append(
                    "Supplied approval status does not establish an effective formal rule."
                )
        target_reason = target_exclusion(
            assessment_target, item.evidence_target, interpretation.mode
        )
        if target_reason:
            reasons.append(target_reason)
        if interpretation.stance not in {"support", "contradict"}:
            reasons.append(f"Non-decisive interpretation: {interpretation.stance}.")
        if interpretation.mode == "unresolved":
            reasons.append("Evidence mode is unresolved.")
        for name in ("scope_matches", "temporal_matches", "authority_verified"):
            if getattr(item, name) is not True:
                reasons.append(f"{name} is false or unresolved.")

        if getattr(source, "metadata_conflicts", None):
            reasons.append("Source metadata conflicts remain unresolved.")
        if source.ingestion_status != "ingested":
            reasons.append("Source was not successfully ingested.")
        if source.effective_start_date and as_of < source.effective_start_date:
            reasons.append("Source is not yet effective.")
        if source.effective_end_date and as_of > source.effective_end_date:
            reasons.append("Source is no longer effective.")
        superseded = getattr(source, "superseded_date", None)
        if superseded and as_of >= superseded:
            reasons.append(
                "Superseded-date boundary reached; boundary inclusion is unspecified."
                if as_of == superseded
                else "Assessment date follows the documented superseded date."
            )
        if interpretation.mode == "formal" and source.lifecycle_status in {
            "draft",
            "withdrawn",
            "unknown",
        }:
            reasons.append("Source lifecycle does not establish an effective formal rule.")
        if source.lifecycle_status not in config.lifecycle_multipliers:
            reasons.append("Source lifecycle has no configured multiplier.")

        input_id = f"input:{index}"
        judgements = {
            name: getattr(item, name)
            for name in (
                "origin_id",
                "source_class",
                "approval_key",
                "scope_matches",
                "temporal_matches",
                "authority_verified",
                "directness",
                "specificity",
                "completeness",
                "judgement_basis",
                "origin_basis",
                "independence_verified",
                "independence_basis",
                "evidence_target",
                "target_basis",
            )
        }
        edge_id = None
        if not reasons:
            document_id = f"document:{index}"
            edge_id = f"edge:{index}"
            updated = getattr(source, "last_updated_date", None)
            nodes.append(
                GraphNode(
                    document_id,
                    "document",
                    source.title,
                    {
                        "source_id": source.source_id,
                        "source_class": item.source_class,
                        "approval_status": item.approval_key,
                        "status": source.lifecycle_status,
                        "duplicate_group": item.origin_id,
                        "effective_date": (
                            source.effective_start_date.isoformat()
                            if source.effective_start_date
                            else None
                        ),
                        "effective_end_date": (
                            source.effective_end_date.isoformat()
                            if source.effective_end_date
                            else None
                        ),
                        "superseded_date": superseded.isoformat() if superseded else None,
                        "last_updated": updated.isoformat() if updated else None,
                    },
                )
            )
            edges.append(
                GraphEdge(
                    edge_id,
                    document_id,
                    "fact:facet",
                    interpretation.mode.upper(),
                    {
                        # A quoted assertion, not the interpretation rationale.
                        "attests_value": "\n\n".join(
                            c.quotation for c in interpretation.citations
                        ),
                        "agrees": interpretation.stance == "support",
                        "applicable": True,
                        "scope_match": True,
                        "directness": item.directness,
                        "specificity": item.specificity,
                        "completeness": item.completeness,
                        "independence_verified": item.independence_verified,
                        "independence_basis": item.independence_basis,
                        "evidence_target": item.evidence_target,
                        "target_basis": item.target_basis,
                        "input_id": input_id,
                        "judgement_basis": item.judgement_basis,
                    },
                )
            )
        dispositions.append(
            InputDisposition(
                input_id,
                interpretation.model_copy(deep=True),
                source.model_copy(deep=True),
                judgements,
                edge_id,
                tuple(reasons),
            )
        )

    precedence_notes = ()
    if assessment_target == "formal_rule":
        edges, dispositions, precedence_notes = _apply_policy_precedence(
            nodes, edges, dispositions, as_of=as_of, config=config
        )
    graph = OrganisationalGraph(nodes, edges, version="corpus-facet-adapter-v1")
    assessment = GraphCredibilityFramework(graph, config).evaluate_fact("fact:facet", as_of=as_of)
    if precedence_notes:
        assessment = replace(
            assessment,
            related_qualifiers=(*assessment.related_qualifiers, *precedence_notes),
            rules_applied=(*assessment.rules_applied, "CORPUS_POLICY_PRECEDENCE_V1"),
            summary=assessment.summary
            + " Conflicting role/table summaries are retained as documentation inconsistencies under policy precedence.",
        )
    return FacetAssessmentResult(
        claim_text,
        facet,
        as_of,
        assessment,
        tuple(dispositions),
        (
            "This is a facet assessment, not a whole-claim verdict.",
            (
                "Legacy target unspecified; no statement/event/rule target check performed."
                if assessment_target == "unspecified"
                else "Target declarations were compared; their semantic correctness is not verified."
            ),
            (
                "Relationship, authority and quality judgements are supplied inputs, "
                "not established by citation validation."
            ),
            (
                "Authority verification is supplied externally; no person-role graph "
                "resolution is performed by this adapter."
            ),
            (
                "Version 1 uses source-level origins; distinct rows in one source "
                "are conservatively grouped."
            ),
            "Framework gaps describe admitted attestations, not exhaustive corpus coverage.",
            "Existing framework lifecycle and historical corroboration rules are unchanged.",
        ),
        assessment_target=assessment_target,
    )
