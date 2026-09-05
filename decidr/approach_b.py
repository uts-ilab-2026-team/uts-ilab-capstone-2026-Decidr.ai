"""Approach B experimental pipeline over the shared relational evidence ledger."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any

from decidr.contracts import AssessmentResult, StructuredClaimResult
from decidr.hybrid import HybridResult, reciprocal_rank_fusion
from decidr.models import AtomicClaim, ClaimOutcome, ConfidenceLevel, EvidenceTarget
from decidr.retrieval import lexical_search
from decidr.semantic import SemanticUnavailableError, SentenceTransformerEmbedder, semantic_search


@dataclass(frozen=True, slots=True)
class ParseProposal:
    claims: tuple[AtomicClaim, ...]
    ambiguities: tuple[str, ...]
    clarification: str | None


@dataclass(frozen=True, slots=True)
class RelationshipSuggestion:
    evidence_id: str
    suggested_relationship: str
    confidence: float
    justification: str
    supporting_text_span: str
    target_match: bool
    scope_match: bool
    condition_match: bool
    period_match: bool
    evidence_target_compatible: bool
    model_name: str
    model_version: str
    validation_status: str = "Model suggestion — not human validated"


@dataclass(frozen=True, slots=True)
class CitationValidation:
    valid: bool
    errors: tuple[str, ...]


class ConstrainedClaimParser:
    """Conservative parser that splits rule/practice questions and flags missing dimensions."""

    def parse_proposal(self, query: str) -> ParseProposal:
        text = query.strip()
        if not text:
            raise ValueError("A question is required")
        lower = text.casefold()
        is_discount = "discount" in lower
        asks_rule = any(term in lower for term in ("rule", "require", "must", "approval"))
        asks_practice = any(term in lower for term in ("follow", "usually", "normally", "practice"))
        claims: list[AtomicClaim] = []
        ambiguities: list[str] = []
        if is_discount and asks_rule:
            threshold = re.search(r"(\d+)\s*%", text)
            amount = threshold.group(1) if threshold else None
            if amount is None:
                ambiguities.append("discount threshold")
            scope = "new-business deals" if "new-business" in lower else None
            if scope is None:
                ambiguities.append("deal scope")
            claim_text = (
                f"A new-business discount of {amount}% or greater requires written approval "
                "from the Head of Finance & People Ops before the deal is marked Closed Won."
                if amount and scope
                else text.rstrip("?") + "."
            )
            claims.append(
                AtomicClaim(
                    claim_id="QUERY-RULE-1",
                    subject=f"a {scope or 'customer-deal'} discount" + (f" of {amount}% or greater" if amount else ""),
                    predicate="requires",
                    object="written approval before Closed Won",
                    process="new-business discount approval",
                    scope=scope,
                    conditions=[f"threshold {amount}% or greater"] if amount else [],
                    claim_type="formal_rule",
                    evidence_target=EvidenceTarget.PRESCRIBED_RULE,
                    claim_text=claim_text,
                    atomicity_status="proposed_for_confirmation",
                )
            )
        if asks_practice:
            claims.append(
                AtomicClaim(
                    claim_id="QUERY-PRACTICE-1",
                    subject="employees handling the specified process",
                    predicate="normally follow",
                    object="the prescribed rule",
                    process="new-business discount approval" if is_discount else None,
                    scope=None,
                    conditions=[],
                    claim_type="routine_practice",
                    evidence_target=EvidenceTarget.ROUTINE_PRACTICE,
                    claim_text="Employees normally follow the specified prescribed rule.",
                    atomicity_status="proposed_for_confirmation",
                )
            )
            ambiguities.append("observable population and period for the routine-practice claim")
        if not claims:
            ambiguities.extend(("subject", "relationship", "evidence target"))
            claims.append(
                AtomicClaim(
                    claim_id="QUERY-1", subject=text, predicate="requires clarification",
                    object="unspecified proposition", claim_type="ambiguous",
                    claim_text=text, atomicity_status="requires_clarification",
                )
            )
        clarification = (
            "Please specify " + ", ".join(dict.fromkeys(ambiguities)) + "."
            if ambiguities else None
        )
        return ParseProposal(tuple(claims), tuple(dict.fromkeys(ambiguities)), clarification)

    def parse(self, query: str) -> list[AtomicClaim]:
        return list(self.parse_proposal(query).claims)


class HybridGraphRetriever:
    def __init__(self, connection: sqlite3.Connection, semantic: bool = True) -> None:
        self.connection = connection
        self.semantic = semantic
        self.component_latency_ms: dict[str, float] = {}
        self.semantic_status = "not_requested"

    def retrieve(self, claim: AtomicClaim, limit: int = 20) -> list[HybridResult]:
        start = perf_counter()
        lexical = lexical_search(self.connection, claim, limit=max(limit, 30))
        self.component_latency_ms["lexical"] = (perf_counter() - start) * 1000
        semantic = []
        if self.semantic:
            start = perf_counter()
            try:
                semantic = semantic_search(
                    self.connection, claim, SentenceTransformerEmbedder(), limit=max(limit, 30)
                )
                self.semantic_status = "available"
            except SemanticUnavailableError as error:
                self.semantic_status = str(error)
            self.component_latency_ms["semantic"] = (perf_counter() - start) * 1000
        start = perf_counter()
        fused = reciprocal_rank_fusion(lexical, semantic, limit=limit)
        self.component_latency_ms["fusion"] = (perf_counter() - start) * 1000
        return fused


class OptionalCrossEncoderReranker:
    """Local-only cross-encoder adapter; returns input unchanged when unavailable."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.version = "unavailable"
        self._model = None
        try:
            from sentence_transformers import CrossEncoder, __version__
            self._model = CrossEncoder(model_name, local_files_only=True)
            self.version = __version__
        except Exception:  # noqa: BLE001 - optional local model may be unavailable
            self._model = None

    def rerank(self, claim: AtomicClaim, results: list[HybridResult]) -> list[dict[str, Any]]:
        records = [asdict(item) for item in results]
        if self._model is None:
            return [{**item, "reranker_score": None, "reranker_rank": None} for item in records]
        scores = self._model.predict([(claim.claim_text, item.text) for item in results])
        ordered = sorted(zip(records, scores, strict=True), key=lambda pair: -float(pair[1]))
        return [
            {**item, "reranker_score": float(score), "reranker_rank": rank}
            for rank, (item, score) in enumerate(ordered, start=1)
        ]


class BoundedGraphExpander:
    """Add evidence from explicit source lineage/process links with recorded reasons."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def expand(self, claim: AtomicClaim, results: list[HybridResult], depth: int = 1) -> list[dict[str, Any]]:
        if depth != 1:
            raise ValueError("Experimental graph expansion is bounded to depth 1")
        packaged = [
            {
                **(item if isinstance(item, dict) else asdict(item)),
                "graph_expansion_reason": None,
                "final_retrieval_source": "hybrid",
            }
            for item in results
        ]
        seen = {item["evidence_id"] for item in packaged}
        source_ids = {item["source_id"] for item in packaged}
        for source_id in sorted(source_ids):
            row = self.connection.execute(
                "SELECT payload_json FROM sources WHERE source_id=?", (source_id,)
            ).fetchone()
            if row is None:
                continue
            source = json.loads(row[0])
            related = {
                value for value in (
                    source.get("predecessor_source_id"), source.get("successor_source_id"),
                    source.get("derived_from_source_id"),
                ) if value
            }
            if source.get("duplicate_group"):
                peers = self.connection.execute("SELECT source_id,payload_json FROM sources").fetchall()
                related.update(
                    peer[0] for peer in peers
                    if json.loads(peer[1]).get("duplicate_group") == source["duplicate_group"]
                )
            for related_id in sorted(related - source_ids):
                evidence_rows = self.connection.execute(
                    "SELECT evidence_id,source_id,locator,text_content FROM evidence WHERE source_id=? ORDER BY evidence_id LIMIT 2",
                    (related_id,),
                ).fetchall()
                for evidence in evidence_rows:
                    if evidence[0] in seen:
                        continue
                    packaged.append({
                        "evidence_id": evidence[0], "source_id": evidence[1],
                        "locator": evidence[2], "text": evidence[3], "rank": len(packaged) + 1,
                        "combined_score": 0.0, "lexical_rank": None, "semantic_rank": None,
                        "graph_expansion_reason": f"explicit provenance link from {source_id}",
                        "final_retrieval_source": "graph_expansion",
                    })
                    seen.add(evidence[0])
        return packaged


class ConservativeRelationshipSuggester:
    model_name = "deterministic-local-heuristic"
    model_version = "0.1"

    def suggest(self, claim: AtomicClaim, evidence: list[dict[str, Any]]) -> list[RelationshipSuggestion]:
        tokens = {token for token in re.findall(r"[a-z0-9]+", claim.claim_text.casefold()) if len(token) > 3}
        suggestions = []
        for item in evidence:
            evidence_tokens = set(re.findall(r"[a-z0-9]+", item["text"].casefold()))
            overlap = len(tokens & evidence_tokens) / max(len(tokens), 1)
            relationship = "contextual" if overlap < 0.25 else "qualifying"
            suggestions.append(RelationshipSuggestion(
                evidence_id=item["evidence_id"], suggested_relationship=relationship,
                confidence=round(min(0.8, 0.3 + overlap), 3),
                justification="Lexical overlap only; substantive relationship requires human validation.",
                supporting_text_span=item["text"][:240], target_match=overlap >= 0.15,
                scope_match=bool(claim.scope), condition_match=bool(claim.conditions),
                period_match=True, evidence_target_compatible=True,
                model_name=self.model_name, model_version=self.model_version,
            ))
        return suggestions


class StrictCitationValidator:
    def validate(
        self, explanation: str, package: list[dict[str, Any]], outcome: ClaimOutcome
    ) -> CitationValidation:
        available = {item["evidence_id"]: item for item in package}
        cited = set(re.findall(r"\[([^\]]+)\]", explanation))
        errors = [f"Unknown or out-of-package citation: {identifier}" for identifier in cited - available.keys()]
        if outcome.value not in explanation:
            errors.append("Explanation outcome does not match deterministic outcome")
        for item in package:
            if not item.get("locator"):
                errors.append(f"Missing locator for {item['evidence_id']}")
        return CitationValidation(not errors, tuple(errors))


def run_approach_b(
    connection: sqlite3.Connection,
    query: str,
    claim: AtomicClaim,
    config: dict[str, Any],
    corpus_fingerprint: str,
) -> AssessmentResult:
    """Run offline-capable exploratory retrieval; official outcome never uses suggestions."""
    started = perf_counter()
    retriever = HybridGraphRetriever(connection)
    fused = retriever.retrieve(claim)
    reranker = OptionalCrossEncoderReranker(config["cross_encoder_model"])
    reranked = reranker.rerank(claim, fused)
    expanded = BoundedGraphExpander(connection).expand(claim, reranked)
    suggestions = ConservativeRelationshipSuggester().suggest(claim, expanded)
    outcome = ClaimOutcome.INSUFFICIENT
    confidence = ConfidenceLevel.LOWER
    citations = [
        {"evidence_id": item["evidence_id"], "source_id": item["source_id"], "locator": item["locator"]}
        for item in expanded[:5]
    ]
    cited_text = ", ".join(f"[{item['evidence_id']}]" for item in expanded[:5])
    explanation = (
        f"The deterministic outcome is {outcome.value}. Retrieved passages {cited_text} are "
        "candidate evidence only; their relationships are model suggestions and have not been "
        "human validated. The available evidence is insufficient to provide a traceable answer."
    )
    validation = StrictCitationValidator().validate(explanation, expanded, outcome)
    if not validation.valid:
        explanation = "The available evidence is insufficient to provide a traceable answer."
        citations = []
    by_relationship: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("supporting", "contradicting", "qualifying", "contextual", "not_applicable")
    }
    for suggestion in suggestions:
        key = suggestion.suggested_relationship
        key = {"qualifying": "qualifying", "contextual": "contextual"}.get(key, "not_applicable")
        by_relationship[key].append(asdict(suggestion))
    return AssessmentResult(
        approach_id=config["approach_id"], query=query,
        structured_claim=StructuredClaimResult(
            subject=claim.subject, predicate=claim.predicate, target_object=claim.object,
            scope=claim.scope, conditions=claim.conditions,
            applicable_period={
                "start": claim.applicable_start_date.isoformat() if claim.applicable_start_date else None,
                "end": claim.applicable_end_date.isoformat() if claim.applicable_end_date else None,
            }, evidence_target=claim.evidence_target.value if claim.evidence_target else "unspecified",
        ),
        outcome=outcome, confidence=confidence,
        supporting_evidence=by_relationship["supporting"],
        contradicting_evidence=by_relationship["contradicting"],
        qualifying_evidence=by_relationship["qualifying"],
        contextual_evidence=by_relationship["contextual"],
        not_applicable_evidence=by_relationship["not_applicable"],
        evidence_gaps=["No human-validated relationships are available for this exploratory query."],
        rules_applied=[{"rule_id": "B1_MODEL_SUGGESTIONS_NOT_REFERENCE_DATA"}, {"rule_id": "R4_NO_DECISIVE_APPLICABLE_EVIDENCE"}],
        explanation=explanation, citations=citations,
        runtime_metadata={
            "configuration_version": config["configuration_version"],
            "corpus_fingerprint": corpus_fingerprint, "claim_version": claim.portfolio_version,
            "embedding_model": config["embedding_model"], "semantic_status": retriever.semantic_status,
            "reranker_model": config["cross_encoder_model"],
            "reranker_status": "available" if reranker._model is not None else "optional_not_available",
            "latency_ms": {**retriever.component_latency_ms, "total": (perf_counter()-started)*1000},
            "random_seed": config["random_seed"], "prompt_template_version": config["prompt_template_version"],
            "ruleset_version": "development-unfrozen", "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def load_profile(path: Path) -> dict[str, Any]:
    """Profiles use JSON syntax, which is valid YAML and needs no extra runtime dependency."""
    return json.loads(path.read_text(encoding="utf-8"))
