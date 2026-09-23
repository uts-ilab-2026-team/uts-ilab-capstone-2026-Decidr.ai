"""Employee-facing Approach B over the shared SQLite evidence ledger."""

import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any

from decidr.config import PROJ_ROOT
from decidr.contracts import AssessmentResult, StructuredClaimResult
from decidr.corpus import active_source
from decidr.evidence_b import PRACTICE_TYPES, eligibility, employee_excerpt
from decidr.hybrid import HybridResult, reciprocal_rank_fusion
from decidr.models import (
    AtomicClaim,
    ClaimOutcome,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
    EvidenceTarget,
    Source,
)
from decidr.query_b import direct_answer, question_condition, threshold, threshold_comparison
from decidr.reasoning import ReasoningConfig, ReviewedEvidence, assess_claim, credibility_value
from decidr.retrieval import lexical_search
from decidr.semantic import SemanticUnavailableError, SentenceTransformerEmbedder, semantic_search


@dataclass(frozen=True, slots=True)
class InterpretationCandidate:
    claim: AtomicClaim
    score: float
    match_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParseProposal:
    claims: tuple[AtomicClaim, ...]
    ambiguities: tuple[str, ...]
    clarification: str | None
    candidates: tuple[InterpretationCandidate, ...] = ()
    interpretation_source: str = "deterministic fallback"

    @property
    def requires_clarification(self) -> bool:
        return bool(self.ambiguities)


@dataclass(frozen=True, slots=True)
class CitationValidation:
    valid: bool
    errors: tuple[str, ...]


NORMALISATIONS = {
    "approavl": "approval",
    "aproval": "approval",
    "manger": "manager",
    "managr": "manager",
    "authorised": "authorized",
    "authoried": "authorized",
    "discunt": "discount",
    "new business": "new-business",
    "closed-won": "Closed Won",
}
STOP = {
    "about",
    "before",
    "company",
    "does",
    "from",
    "greater",
    "need",
    "question",
    "that",
    "their",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "whether",
    "which",
    "with",
    "without",
    "would",
    "could",
    "should",
}


def _normalise(text: str) -> str:
    value = " ".join(text.strip().split())
    for wrong, right in NORMALISATIONS.items():
        value = re.sub(rf"\b{re.escape(wrong)}\b", right, value, flags=re.IGNORECASE)
    return value


def proposition_polarity(text: str) -> str:
    """Bounded approval modality recognition; never substitute portfolio wording."""
    lower = _normalise(text).casefold()
    if re.search(r"\bwithout\b|\b(?:approve|approving) independently\b", lower):
        return "permission_without_approval"
    if re.search(r"\b(?:does? not|don't|doesn't) (?:require|need)\b|\bno .{0,30}approval (?:is )?required\b", lower):
        return "negative"
    return "positive"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in STOP
    }


class ConstrainedClaimParser:
    """Corpus-aware deterministic fallback that leaves material uncertainty visible."""

    def __init__(self, portfolio_path: Path | None = None) -> None:
        self.portfolio_path = portfolio_path or (
            PROJ_ROOT / "framework/versions/v1.2-final/candidate_claim_portfolio.csv"
        )

    def _portfolio_candidates(self, text: str) -> list[InterpretationCandidate]:
        if not self.portfolio_path.exists():
            return []
        query_tokens = _tokens(text)
        candidates = []
        with self.portfolio_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                wording = row["exact_claim_wording"]
                overlap = query_tokens & _tokens(wording)
                score = len(overlap) / max(len(query_tokens), 1)
                if score < 0.28:
                    continue
                reasons = [f"shared terminology: {', '.join(sorted(overlap))}"]
                match_threshold = threshold(text)
                if match_threshold and match_threshold == threshold(wording):
                    score += 0.25
                    reasons.append(f"same {match_threshold.value}% boundary")
                claim = AtomicClaim(
                    claim_id=f"QUERY-{row['candidate_claim_id']}",
                    subject=row["subject"],
                    predicate=row["relationship_predicate"],
                    object=row["target_object"],
                    process=row["process"] or None,
                    scope=row["organisational_scope"] or None,
                    conditions=[
                        part.strip() for part in row["conditions"].split(";") if part.strip()
                    ],
                    applicable_start_date=row["applicable_start_date"] or None,
                    applicable_end_date=row["applicable_end_date"] or None,
                    claim_type=row["claim_type"],
                    evidence_target=row["evidence_target"],
                    claim_text=wording,
                    proposition_polarity=proposition_polarity(wording),
                    atomicity_status="proposed_for_confirmation",
                    original_claim_text=text,
                )
                candidates.append(InterpretationCandidate(claim, min(score, 1.0), tuple(reasons)))
        return sorted(candidates, key=lambda item: (-item.score, item.claim.claim_id))[:3]

    def parse_proposal(self, query: str) -> ParseProposal:
        text = _normalise(query)
        if not text:
            raise ValueError("A question is required")
        lower, candidates = text.casefold(), self._portfolio_candidates(text)
        practice = any(
            word in lower for word in ("usually", "normally", "practice", "actually", "follow")
        )
        ambiguities, claims = [], []
        if "discount" in lower:
            found = re.search(r"(\d+(?:\.\d+)?)\s*%", lower)
            amount = found.group(1) if found else None
            renewal = "renewal" in lower
            new_business = "new-business" in lower
            if not amount:
                ambiguities.append("discount threshold")
            if not (renewal or new_business):
                ambiguities.append("deal scope")
            scope = "renewal deals" if renewal else "new-business deals" if new_business else None
            role = re.search(r"(?:can|may)\s+([a-z][a-z ]+?)\s+approve", lower)
            actor = role.group(1).strip().title() if role else None
            compound_practice = practice and any(
                word in lower for word in ("rule, and", "policy, and")
            )
            polarity = proposition_polarity(text)
            if re.search(r"\b(?:line|direct|my|their) manager\b", lower) and not re.search(
                r"clarification:.*(?:any authorized|any approval authority)", lower
            ):
                ambiguities.append("whether manager means your line manager or any authorised approval authority")
            if actor and amount and polarity == "permission_without_approval":
                subject, predicate = actor, "may approve without"
                target = f"manager approval for a {amount}% discount"
            else:
                subject = f"A {scope or 'customer-deal'} discount" + (
                    f" of {amount}%" if amount else ""
                )
                predicate = "does not require" if polarity == "negative" else "requires"
                target = "written approval from the authorised approver before Closed Won"
            claims.append(
                AtomicClaim(
                    claim_id="QUERY-DISCOUNT-1",
                    subject=subject,
                    predicate=predicate,
                    object=target,
                    process="renewal discount approval"
                    if renewal
                    else "new-business discount approval",
                    scope=scope,
                    conditions=[f"discount is {amount}%"] if amount else [],
                    claim_type="routine_practice"
                    if practice and not compound_practice
                    else "formal_rule",
                    evidence_target=EvidenceTarget.RECORDED_STATE
                    if any(term in lower for term in ("recorded in crm", "crm show", "crm record"))
                    else EvidenceTarget.ACTUAL_PRACTICE
                    if practice and not compound_practice
                    else EvidenceTarget.PRESCRIBED_RULE,
                    claim_text=(
                        f"{actor.capitalize()} may approve a {amount}% "
                        f"{'renewal' if renewal else 'new-business'} discount without authorised approval."
                        if actor and amount and polarity == "permission_without_approval"
                        and threshold(text).operator == "eq"
                        and re.fullmatch(r"(?:can|may) .+? approve (?:a |an )?\d+(?:\.\d+)?% (?:new-business|renewal) discount without (?:a manager|managerial approval)\??", text, re.IGNORECASE)
                        else f"A {amount}% {'renewal' if renewal else 'new-business'} discount "
                        f"{'does not require' if polarity == 'negative' else 'requires'} authorised approval."
                        if amount and not practice and threshold(text).operator == "eq"
                        and re.fullmatch(r"(?:do i|do we) need approval for (?:a |an )?\d+(?:\.\d+)?% (?:new-business|renewal) discount\??", text, re.IGNORECASE)
                        else query
                    ),
                    proposition_polarity=polarity,
                    atomicity_status="requires_clarification"
                    if ambiguities
                    else "proposed_for_confirmation",
                    original_claim_text=query,
                )
            )
            if compound_practice:
                claims.append(
                    AtomicClaim(
                        claim_id="QUERY-DISCOUNT-PRACTICE-2",
                        subject="Employees handling new-business discounts",
                        predicate="normally follow",
                        object="the prescribed discount-approval rule",
                        process="new-business discount approval",
                        scope=scope,
                        conditions=[],
                        claim_type="routine_practice",
                        evidence_target=EvidenceTarget.ROUTINE_PRACTICE,
                        claim_text="Employees handling new-business discounts normally follow the prescribed approval rule.",
                        atomicity_status="requires_clarification",
                        original_claim_text=query,
                    )
                )
                ambiguities.append(
                    "observable population and period for the routine-practice claim"
                )
        elif "emergency" in lower and any(
            word in lower for word in ("deploy", "release", "billing")
        ):
            claims.append(
                AtomicClaim(
                    claim_id="QUERY-DEPLOYMENT-1",
                    subject="The emergency billing deployment",
                    predicate="was approved before",
                    object="production release",
                    process="emergency production deployment",
                    scope="billing system",
                    conditions=["emergency change"],
                    claim_type="specific_event",
                    evidence_target=EvidenceTarget.SPECIFIC_EVENT,
                    claim_text="The emergency billing deployment was approved before production release.",
                    atomicity_status="proposed_for_confirmation",
                    original_claim_text=query,
                )
            )
        elif candidates:
            # A portfolio entry is a match reference, never a replacement interpretation.
            claims = [AtomicClaim(
                claim_id="QUERY-UNRESOLVED", subject=text, predicate="asks about",
                object=candidates[0].claim.process or "organisational process",
                claim_text=query, original_claim_text=query, claim_type="unresolved",
                conditions=[query], atomicity_status="requires_clarification",
            )]
            ambiguities.append("the proposition and explicit conditions to assess")
            if len(candidates) > 1 and (
                candidates[0].score - candidates[1].score < 0.15
                or not any(
                    term in lower
                    for term in ("discount", "expense", "deployment", "renewal", "onboarding")
                )
            ):
                ambiguities.append("which closely matched organisational proposition you mean")
        else:
            ambiguities.append("the process and action to assess")
        # Preserve unparsed qualifiers verbatim and require confirmation of their
        # structured meaning. Portfolio scope/dates cannot silently fill these in.
        qualifiers = re.search(
            r"\bdiscount\b.*?\b((?:in|on|during|if|unless|except|as of|from)\s+.+)",
            text, re.IGNORECASE,
        )
        if qualifiers and claims:
            explicit = qualifiers[1].rstrip("?.")
            claims = [item.model_copy(update={
                "claim_text": query,
                "conditions": [*item.conditions, explicit],
                "atomicity_status": "requires_clarification",
            }) for item in claims]
            ambiguities.append("the additional scope, date, role or condition: " + explicit)
        prompts = {
            "discount threshold": "What discount percentage should I assess?",
            "deal scope": "Is this for a new-business deal or a renewal?",
            "the process and action to assess": "Which organisational process and action are you asking about?",
        }
        clarification = (
            prompts.get(ambiguities[0], f"Please clarify {ambiguities[0]}.")
            if ambiguities
            else None
        )
        return ParseProposal(
            tuple(claims),
            tuple(dict.fromkeys(ambiguities)),
            clarification,
            tuple(candidates),
            "deterministic fallback",
        )

    def parse(self, query: str) -> list[AtomicClaim]:
        return list(self.parse_proposal(query).claims)


class HybridGraphRetriever:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        semantic: bool = False,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.connection, self.semantic, self.embedding_model = (
            connection,
            semantic,
            embedding_model,
        )
        self.component_latency_ms = {}
        self.status = {
            "lexical": "available",
            "semantic": "disabled by configuration",
            "fusion": "available",
        }

    def retrieve(self, claim: AtomicClaim, limit: int = 20) -> list[HybridResult]:
        started = perf_counter()
        lexical = lexical_search(self.connection, claim, limit=max(limit, 30))
        self.component_latency_ms["lexical"] = (perf_counter() - started) * 1000
        semantic_results = []
        if self.semantic:
            started = perf_counter()
            try:
                embedder = SentenceTransformerEmbedder(self.embedding_model)
                semantic_results = semantic_search(
                    self.connection, claim, embedder, limit=max(limit, 30)
                )
                self.status["semantic"] = "available (configured local model used)"
            except SemanticUnavailableError as error:
                self.status["semantic"] = f"configured but unavailable: {error}"
            self.component_latency_ms["semantic"] = (perf_counter() - started) * 1000
        started = perf_counter()
        result = reciprocal_rank_fusion(lexical, semantic_results, limit=limit)
        self.component_latency_ms["fusion"] = (perf_counter() - started) * 1000
        return result


class OptionalCrossEncoderReranker:
    def __init__(self, model_name: str, enabled: bool = False) -> None:
        self.model_name, self.version, self._model = model_name, "unavailable", None
        self.status = "disabled by configuration"
        if enabled:
            try:
                from sentence_transformers import CrossEncoder, __version__

                self._model = CrossEncoder(model_name, local_files_only=True)
                self.version, self.status = __version__, "available (configured local model used)"
            except Exception:  # noqa: BLE001
                self.status = "configured but local model unavailable"

    def rerank(self, claim: AtomicClaim, results: list[HybridResult]) -> list[dict[str, Any]]:
        records = [asdict(item) for item in results]
        if self._model is None:
            return [{**item, "reranker_score": None, "reranker_rank": None} for item in records]
        scores = self._model.predict([(claim.claim_text, item.text) for item in results])
        ordered = sorted(zip(records, scores, strict=True), key=lambda pair: -float(pair[1]))
        return [
            {**item, "reranker_score": float(score), "reranker_rank": rank}
            for rank, (item, score) in enumerate(ordered, 1)
        ]


class BoundedGraphExpander:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def expand(
        self, claim: AtomicClaim, results: list[Any], depth: int = 1
    ) -> list[dict[str, Any]]:
        if depth != 1:
            raise ValueError("Experimental graph expansion is bounded to depth 1")
        packaged = []
        packaged_ids: set[str] = set()
        for item in results:
            record = item if isinstance(item, dict) else asdict(item)
            if not active_source(record["source_id"]) or record["evidence_id"] in packaged_ids:
                continue
            packaged.append(
                {**record, "graph_expansion_reason": None, "final_retrieval_source": "hybrid"}
            )
            packaged_ids.add(record["evidence_id"])
        seen, seeds = (
            {item["evidence_id"] for item in packaged},
            {item["source_id"] for item in packaged},
        )
        rows = self.connection.execute(
            "SELECT source_id,payload_json FROM sources WHERE source_id LIKE 'phase2:%'"
        ).fetchall()
        sources = {row[0]: json.loads(row[1]) for row in rows}
        for source_id in sorted(seeds):
            source = sources.get(source_id, {})
            related = {
                source.get(key)
                for key in (
                    "predecessor_source_id",
                    "successor_source_id",
                    "derived_from_source_id",
                )
                if source.get(key)
            }
            group = source.get("duplicate_group")
            if group:
                related.update(
                    key for key, value in sources.items() if value.get("duplicate_group") == group
                )
            for related_id in sorted(related - seeds):
                if not active_source(related_id):
                    continue
                evidence_rows = self.connection.execute(
                    "SELECT evidence_id,source_id,locator,text_content FROM evidence WHERE source_id=? ORDER BY evidence_id",
                    (related_id,),
                ).fetchall()
                for row in evidence_rows:
                    if row[0] in seen:
                        continue
                    packaged.append(
                        {
                            "evidence_id": row[0],
                            "source_id": row[1],
                            "locator": row[2],
                            "text": row[3],
                            "rank": len(packaged) + 1,
                            "combined_score": 0.0,
                            "lexical_rank": None,
                            "semantic_rank": None,
                            "reranker_score": None,
                            "reranker_rank": None,
                            "graph_expansion_reason": f"explicit provenance link from {source_id}",
                            "final_retrieval_source": "graph_expansion",
                        }
                    )
                    seen.add(row[0])
        return packaged


class StrictCitationValidator:
    def validate(
        self, explanation: str, package: list[dict[str, Any]], outcome: ClaimOutcome
    ) -> CitationValidation:
        available = {item["evidence_id"] for item in package}
        cited = set(re.findall(r"\[([^\]]+)\]", explanation))
        errors = [
            f"Unknown or out-of-package citation: {item}" for item in sorted(cited - available)
        ]
        if outcome.value not in explanation:
            errors.append("Explanation outcome does not match deterministic outcome")
        errors.extend(
            f"Missing locator for {item['evidence_id']}"
            for item in package
            if not item.get("locator")
        )
        return CitationValidation(not errors, tuple(errors))


def _sources(connection: sqlite3.Connection) -> dict[str, Source]:
    return {
        row[0]: Source.model_validate_json(row[1])
        for row in connection.execute(
            "SELECT source_id,payload_json FROM sources WHERE source_id LIKE 'phase2:%'"
        )
    }


def _relationship(claim: AtomicClaim, text: str, source: Source) -> EvidenceRelationship:
    # Eligibility has already established process, scope, boundary, dates and authority.
    # An explicit applicable rule is decisive regardless of employee vocabulary overlap.
    from decidr.evidence_b import rule_fields

    if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE and rule_fields(text):
        return (
            EvidenceRelationship.CONTRADICT
            if (proposition_polarity(claim.claim_text) != "positive")
            != (proposition_polarity(rule_fields(text)["proposition"]) != "positive")
            else EvidenceRelationship.SUPPORT
        )
    overlap = len(_tokens(claim.claim_text) & _tokens(text)) / max(
        len(_tokens(claim.claim_text)), 1
    )
    if overlap < 0.22:
        return EvidenceRelationship.CONTEXTUAL
    practice = source.source_type in {
        "interview",
        "operational_record",
        "system_export",
        "meeting_notes",
    }
    if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE and practice:
        return EvidenceRelationship.QUALIFY
    evidence_lower = text.casefold()
    claim_lower = claim.claim_text.casefold()
    evidence_requires = bool(
        re.search(r"\b(require[sd]?|must|needs?)\b.{0,80}\bapprov", evidence_lower)
    )
    evidence_without = bool(
        re.search(
            r"\b(?:may|can|could|was|were)\b.{0,80}\bwithout\b.{0,50}\bapprov",
            evidence_lower,
        )
        or re.search(r"\bdoes not require\b.{0,50}\bapprov", evidence_lower)
    )
    claim_without = "without" in claim_lower or "does not require" in claim_lower
    if overlap >= 0.38:
        if evidence_requires or evidence_without:
            return (
                EvidenceRelationship.CONTRADICT
                if evidence_requires == claim_without
                else EvidenceRelationship.SUPPORT
            )
        return EvidenceRelationship.QUALIFY
    return EvidenceRelationship.QUALIFY


def _credibility(
    item: dict[str, Any], source: Source, relationship: EvidenceRelationship
) -> CredibilityAssessment:
    formal = source.source_type in {
        "policy",
        "procedure",
        "system_record",
        "organisational_information",
    }
    mode = (
        EvidenceMode.OBSERVED_PRACTICE
        if source.source_type in {"interview", "operational_record", "system_export"}
        else EvidenceMode.FORMAL_RULE
        if formal
        else EvidenceMode.OTHER
    )
    decisive = relationship in {EvidenceRelationship.SUPPORT, EvidenceRelationship.CONTRADICT}
    return CredibilityAssessment(
        assessment_id=f"test:approach-b:{item['evidence_id']}",
        link_id=f"test:approach-b-link:{item['evidence_id']}",
        relevance=0.9 if decisive else 0.55,
        institutional_authority=0.9 if formal else 0.55,
        directness=0.85 if decisive else 0.5,
        temporal_validity=0.2 if source.lifecycle_status == "superseded" else 0.85,
        independence=0.4 if source.duplicate_group or source.derived_from_source_id else 0.85,
        completeness=0.7,
        organisational_applicability=0.9,
        evidence_mode=mode,
        limitations=["Deterministic Approach B mapping; not a human adjudication."],
        reviewer_justification="Deterministic source-type, applicability, polarity and overlap mapping.",
    )


def _portable(path: str) -> str:
    normal = path.replace("\\", "/")
    for marker in ("phase1_framework_development", "phase2_model_development", "data/raw/"):
        if marker in normal:
            return normal[normal.index(marker) :]
    return Path(normal).name


def _evidence_record(
    item: dict[str, Any],
    source: Source,
    relation: EvidenceRelationship,
    reviewed: ReviewedEvidence,
    reason: str,
) -> dict[str, Any]:
    return {
        "evidence_id": item["evidence_id"],
        "source_id": item["source_id"],
        "source_title": source.title,
        "source_path": _portable(source.original_file_path),
        "locator": item["locator"],
        "excerpt": employee_excerpt(item),
        "eligibility": item["eligibility"],
        "practice_status": item.get("practice_status"),
        "validated_rule": item.get("validated_rule", {}),
        "source_type": source.source_type,
        "creation_date": source.creation_date.isoformat() if source.creation_date else None,
        "effective_start_date": source.effective_start_date.isoformat()
        if source.effective_start_date
        else None,
        "effective_end_date": source.effective_end_date.isoformat()
        if source.effective_end_date
        else None,
        "lifecycle_status": source.lifecycle_status,
        "relationship": relation.value,
        "duplicate_group": source.duplicate_group,
        "derived_from_source_id": source.derived_from_source_id,
        "independent": not bool(source.duplicate_group or source.derived_from_source_id),
        "assessment_influence": reason,
        "credibility_value": round(credibility_value(reviewed.credibility, ReasoningConfig()), 3),
        "retrieval_source": item.get("final_retrieval_source"),
        "graph_expansion_reason": item.get("graph_expansion_reason"),
    }


def _guidance(outcome: ClaimOutcome, owner: str | None) -> tuple[str, str]:
    owner = owner or "the responsible process owner"
    if outcome == ClaimOutcome.SUPPORTED:
        return (
            "You can rely on the confirmed procedure for this scoped question; follow the cited authoritative source.",
            f"Follow the verified procedure and retain the cited record. Contact {owner} if circumstances differ.",
        )
    if outcome == ClaimOutcome.CONTRADICTED:
        return (
            "Do not rely on the assumption in the question; applicable evidence points the other way.",
            f"Correct the misunderstanding using the current source and ask {owner} to retire misleading guidance.",
        )
    if outcome == ClaimOutcome.CONTESTED:
        return (
            "The sources conflict. Take the safer documented path until the authorised owner resolves it.",
            f"Refer both sides to {owner}; do not decide what policy ought to be from the conflict.",
        )
    return (
        "The corpus does not establish a safe answer. Missing evidence is not a contradiction.",
        f"Ask {owner} for the missing authoritative record or clarification before acting.",
    )


def run_approach_b(
    connection: sqlite3.Connection,
    query: str,
    claim: AtomicClaim,
    config: dict[str, Any],
    corpus_fingerprint: str,
    *,
    ambiguities: list[str] | None = None,
    interpretation_method: str = "deterministic fallback",
) -> AssessmentResult:
    """Assess an explicitly confirmed claim without writing any database table."""
    if claim.atomicity_status not in {"user_confirmed", "confirmed"}:
        raise ValueError("Assessment requires an explicitly confirmed atomic claim")
    started = perf_counter()
    retriever = HybridGraphRetriever(
        connection,
        semantic=bool(config.get("semantic_enabled", False)),
        embedding_model=config["embedding_model"],
    )
    fused = retriever.retrieve(claim, limit=100)
    reranker = OptionalCrossEncoderReranker(
        config["cross_encoder_model"], bool(config.get("reranker_enabled", False))
    )
    expanded = [
        item
        for item in BoundedGraphExpander(connection).expand(claim, reranker.rerank(claim, fused))
        if active_source(item["source_id"])
    ]
    sources, reviewed, relations = _sources(connection), [], {}
    decisions, gaps = {}, []
    for item in expanded:
        row = connection.execute(
            "SELECT payload_json FROM evidence WHERE evidence_id=?", (item["evidence_id"],)
        ).fetchone()
        item["metadata"] = json.loads(row[0]) if row else {}
        source = sources[item["source_id"]]
        decision = eligibility(claim, item, source, sources)
        decisions[item["evidence_id"]] = decision
        item["validated_rule"] = decision.fields
        item["eligibility"] = {
            "checks": decision.checks,
            "reasons": decision.reasons,
            "limitations": decision.limitations,
        }
        practice = source.source_type in PRACTICE_TYPES
        relation = EvidenceRelationship.NOT_APPLICABLE
        if decision.eligible:
            if practice and claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE:
                relation = EvidenceRelationship.QUALIFY
                item["practice_status"] = (
                    "divergence" if decision.practice_violation else "coverage_or_observation"
                )
            else:
                relation = _relationship(claim, item["text"], source)

        relations[item["evidence_id"]] = relation
    # Operational dates must also fall within the decisive rule's effective period.
    rule_starts = [
        sources[item["source_id"]].effective_start_date
        for item in expanded
        if decisions[item["evidence_id"]].eligible
        and item["validated_rule"]
        and sources[item["source_id"]].source_type == "policy"
    ]
    rule_start = max((value for value in rule_starts if value), default=None)
    if rule_start:
        for item in expanded:
            record = item["metadata"].get("structured_metadata", {}).get("record", {})
            if record and str(record.get("close_date", "")) < rule_start.isoformat():
                decisions[item["evidence_id"]].check(
                    "rule_period", False, "Operational record predates the applicable rule."
                )
                relations[item["evidence_id"]] = EvidenceRelationship.NOT_APPLICABLE

    # Rank eligibility and evidence qualities before retrieval score. Equivalent releases
    # use the configured release, then stable source/evidence identifiers as tie breakers.
    def rank(item):
        source = sources[item["source_id"]]
        decision = decisions[item["evidence_id"]]
        return (
            not decision.eligible,
            not bool(decision.fields or decision.practice_violation),
            not decision.checks.get("dates", False),
            source.lifecycle_status != "current" and not decision.historical,
            source.source_type != "policy"
            if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE
            else source.source_type not in PRACTICE_TYPES,
            bool(source.derived_from_source_id),
            not source.source_id.startswith(
                config.get("preferred_corpus_release", "phase2") + ":"
            ),
            -float(item.get("combined_score", 0)),
            source.source_id,
            item["evidence_id"],
        )

    expanded.sort(key=rank)
    canonical = {}
    for item in expanded:
        source = sources[item["source_id"]]
        decision = decisions[item["evidence_id"]]
        group = source.duplicate_group or source.derived_from_source_id
        if decision.eligible and group:
            if group in canonical:
                decision.check(
                    "independence",
                    False,
                    f"Dependent duplicate of {canonical[group]}; equivalent duplicate copy omitted.",
                )
                relations[item["evidence_id"]] = EvidenceRelationship.NOT_APPLICABLE
            else:
                canonical[group] = item["evidence_id"]
        if decision.eligible and claim.evidence_target != EvidenceTarget.PRESCRIBED_RULE:
            gaps.extend(decision.limitations)
        relation = relations[item["evidence_id"]]
        credibility = _credibility(item, source, relation)
        if source.source_type in PRACTICE_TYPES:
            credibility = credibility.model_copy(
                update={"evidence_mode": EvidenceMode.OBSERVED_PRACTICE}
            )
        if decision.historical:
            credibility = credibility.model_copy(update={"temporal_validity": 0.85})
        reviewed.append(
            ReviewedEvidence(
                evidence_id=item["evidence_id"],
                source_id=item["source_id"],
                locator=item["locator"],
                relationship=relation,
                target_match=decision.eligible,
                scope_match=decision.checks.get("scope", True),
                condition_match=decision.checks.get("conditions", True),
                temporal_match=decision.checks["dates"],
                credibility=credibility,
                duplicate_group=group,
                lifecycle_status=source.lifecycle_status,
                superseded_is_temporally_justified=decision.historical,
                policy_practice_violation=decision.eligible and decision.practice_violation,
            )
        )
    if not any(
        item.relationship in {EvidenceRelationship.SUPPORT, EvidenceRelationship.CONTRADICT}
        for item in reviewed
    ):
        gaps.append("No sufficiently direct, applicable organisational evidence was retrieved.")
    reasoning = assess_claim(
        reviewed, list(dict.fromkeys(gaps)), evidence_target=claim.evidence_target
    )
    applicable_ids = {item.evidence_id for item in reasoning.applicable}
    excluded = {item.evidence_id: reason for item, reason in reasoning.excluded}
    by_id = {item.evidence_id: item for item in reviewed}
    buckets = {
        key: [] for key in ("support", "contradict", "qualify", "contextual", "not_applicable")
    }
    for item in expanded:
        identifier = item["evidence_id"]
        relation = relations[identifier]
        decision = decisions[identifier]
        reason = (
            "; ".join(decision.reasons)
            or excluded.get(identifier)
            or "Eligible for the confirmed claim."
        )
        if identifier in excluded:
            relation = EvidenceRelationship.NOT_APPLICABLE
        buckets[relation.value].append(
            _evidence_record(item, sources[item["source_id"]], relation, by_id[identifier], reason)
        )
    citations = [
        {key: item[key] for key in ("evidence_id", "source_id", "source_title", "locator")}
        for group in buckets.values()
        for item in group
        if item["evidence_id"] in applicable_ids
    ]
    explanation = f"Deterministic verdict: {reasoning.outcome.value}. " + (
        " ".join(f"[{item['evidence_id']}]" for item in citations[:6]) or "No decisive citations."
    )
    validation = StrictCitationValidator().validate(explanation, expanded, reasoning.outcome)
    if not validation.valid:
        raise ValueError("Invalid citation package: " + "; ".join(validation.errors))
    owner = next(
        (
            sources[item.source_id].responsible_person_or_role
            for item in reasoning.applicable
            if sources[item.source_id].responsible_person_or_role
        ),
        None,
    )
    guidance, action = _guidance(reasoning.outcome, owner)
    requested = threshold(query)
    confirmed_threshold = threshold(claim.claim_text)
    condition = question_condition(_normalise(query))
    comparisons = {}
    owner_basis = "source metadata" if owner else None
    fields = next(
        (item["validated_rule"] for item in buckets["support"] + buckets["contradict"]
         if item["validated_rule"]), {}
    )
    comparison_fields = fields or next(
        (item["validated_rule"] for item in buckets["not_applicable"]
         if item["source_type"] == "policy" and item["validated_rule"]
         and all(passed for key, passed in item["eligibility"]["checks"].items()
                 if key != "threshold")), {}
    )
    if requested and comparison_fields:
        policy_boundary = threshold(comparison_fields["proposition"])
        if policy_boundary:
            comparisons = threshold_comparison(requested, policy_boundary)
    if (fields and claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE
            and reasoning.outcome in {ClaimOutcome.SUPPORTED, ClaimOutcome.CONTRADICTED}):
        policy_threshold = threshold(fields["proposition"])
        if requested and policy_threshold:
            comparisons = threshold_comparison(requested, policy_threshold)
        # Only map a bounded question when the confirmed constraints still match it.
        prefix = direct_answer(condition, proposition_polarity(claim.claim_text), reasoning.outcome.value)
        if requested != confirmed_threshold:
            prefix = ""
        if requested and requested.operator == "eq" and claim.scope in {"new-business deals", "renewal deals"}:
            subject = f"A {requested.value}% {claim.scope.removesuffix(' deals')} discount"
        else:
            subject = claim.subject
        comparison_wording = ""
        if comparisons.get("within_policy_range") and policy_threshold.operator == "ge":
            comparison_wording = (
                f" is at or above the {policy_threshold.value}% policy threshold and therefore"
            )
        timing = (
            "the opportunity is marked Closed Won"
            if "closed won" in fields["timing"].casefold() else fields["timing"]
        )
        recording = (
            "The approval must also be recorded in CRM."
            if "crm" in fields["recording"].casefold() else fields["recording"]
        )
        guidance = (
            f"{prefix}{subject}{comparison_wording} requires {fields['action']}"
            + (f" from {fields['approver']}" if fields["approver"] else "")
            + f" before {timing}." + (" " + recording if recording else "")
        )
        owner = fields["approver"] or owner
        if fields["approver"]:
            owner_basis = "cited policy text"
        action = (
            "Obtain " + fields["action"]
            + (" from " + fields["approver"] if fields["approver"] else "")
            + " before " + timing + "." + (" " + recording if recording else "")
        )
    practice_evidence = [
        item for item in buckets["qualify"]
        if item.get("practice_status") == "divergence"
        and item["source_id"].startswith("phase2:")
        and all(item["eligibility"]["checks"].values())
    ] if fields and claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE else []
    divergence = (
        ["The approved rule is clear, but operational records indicate that practice may differ."]
        if practice_evidence else []
    )
    candidates = ConstrainedClaimParser()._portfolio_candidates(_normalise(query))
    dependency = [
        item["assessment_influence"]
        for item in buckets["not_applicable"]
        if "duplicate" in item["assessment_influence"].lower()
    ]
    temporal = [
        item["assessment_influence"]
        for item in buckets["not_applicable"]
        if "period" in item["assessment_influence"].lower()
    ]
    statuses = {
        **retriever.status,
        "reranker": reranker.status,
        "graph": "available (explicit depth-1 metadata expansion)",
        "llm": (
            "disabled by configuration"
            if not config.get("llm_enabled")
            else "configured adapter unavailable; deterministic wording used"
        ),
    }
    return AssessmentResult(
        approach_id=config["approach_id"],
        query=query,
        original_question=query,
        confirmed_atomic_claim=claim.claim_text,
        interpretation_method=interpretation_method,
        ambiguities=ambiguities or [],
        structured_claim=StructuredClaimResult(
            claim_text=claim.claim_text,
            proposition_polarity=proposition_polarity(claim.claim_text),
            subject=claim.subject,
            predicate=claim.predicate,
            target_object=claim.object,
            process=claim.process,
            scope=claim.scope,
            conditions=claim.conditions,
            applicable_period={
                "start": claim.applicable_start_date.isoformat()
                if claim.applicable_start_date
                else None,
                "end": claim.applicable_end_date.isoformat()
                if claim.applicable_end_date
                else None,
            },
            evidence_target=claim.evidence_target.value
            if claim.evidence_target
            else "unspecified",
        ),
        outcome=reasoning.outcome,
        confidence=reasoning.confidence,
        safe_employee_guidance=guidance,
        supporting_evidence=buckets["support"],
        contradicting_evidence=buckets["contradict"],
        qualifying_evidence=buckets["qualify"],
        contextual_evidence=buckets["contextual"],
        not_applicable_evidence=buckets["not_applicable"],
        evidence_gaps=list(reasoning.gaps),
        dependent_evidence_groups=[{"note": note} for note in dependency],
        policy_practice_divergence=divergence,
        temporal_applicability_notes=temporal,
        dependency_duplication_notes=dependency,
        recommended_organisational_action=action,
        responsible_role=owner,
        responsible_role_basis=owner_basis,
        query_conditions={
            "original_text": query,
            "user_threshold": asdict(requested) if requested else None,
            "confirmed_threshold": asdict(confirmed_threshold) if confirmed_threshold else None,
            "scope": claim.scope, "conditions": claim.conditions,
            "start": str(claim.applicable_start_date) if claim.applicable_start_date else None,
            "end": str(claim.applicable_end_date) if claim.applicable_end_date else None,
        },
        threshold_reasoning=comparisons,
        direct_answer_condition=condition,
        matched_candidate_claim=candidates[0].claim.model_dump(mode="json") if candidates else None,
        divergence_evidence=practice_evidence,
        retrieval_component_status=statuses,
        rules_applied=list(reasoning.traces),
        explanation=explanation,
        citations=citations,
        assessment_provenance={
            "corpus_fingerprint": corpus_fingerprint,
            "configuration_version": config["configuration_version"],
            "ruleset_version": "development-unfrozen",
            "canonicalisation": "Eligibility, directness, dates, lifecycle, authority, independence, preferred release, retrieval score, stable IDs.",
            "preferred_corpus_release": config.get("preferred_corpus_release", "phase2"),
            "evidence_links": [
                {
                    "evidence_id": item["evidence_id"],
                    "source_id": item["source_id"],
                    "graph_expansion_reason": item.get("graph_expansion_reason"),
                    "eligibility": item["eligibility"],
                }
                for item in expanded
            ],
        },
        runtime_metadata={
            "active_modelling_release": "phase2",
            "component_status": statuses,
            "latency_ms": {
                **retriever.component_latency_ms,
                "total": (perf_counter() - started) * 1000,
            },
            "corpus_fingerprint": corpus_fingerprint,
            "configuration_version": config["configuration_version"],
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def load_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
