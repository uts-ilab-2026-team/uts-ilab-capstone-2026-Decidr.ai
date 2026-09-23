"""Conservative Approach B eligibility and employee presentation; no verdict authority."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any

from decidr.models import AtomicClaim, EvidenceTarget, Source
from decidr.query_b import threshold, threshold_comparison
from decidr.source_metadata import metadata_constraint

PRACTICE_TYPES = {
    "crm_records",
    "operational_record",
    "system_export",
    "interview",
    "meeting_notes",
}
FORMAL_TYPES = {"policy", "procedure", "system_record", "organisational_information"}


def clean(text: str) -> str:
    return " ".join(re.sub(r"[*`]", "", text).split())


def excerpt(text: str, limit: int = 420) -> str:
    value = clean(text)
    return value if len(value) <= limit else value[: limit - 1].rsplit(" ", 1)[0] + "…"


def rule_fields(text: str) -> dict[str, str]:
    """Extract a single explicit approval proposition, preserving its boundary."""
    sentences = re.split(r"\n|(?<=[.!?])\s+", text)
    for sentence in sentences:
        sentence = re.sub(r"^\d+\.\s*", "", clean(sentence))
        match = re.search(
            r"(.+?)\s+requires?\s+(written approval|approval)(?: from (.+?))?\s+before\s+(.+?)(?:\.|$)",
            sentence,
            re.IGNORECASE,
        )
        if match:
            recording = next(
                (
                    clean(s)
                    for s in sentences
                    if re.search(r"approval must be recorded", s, re.IGNORECASE)
                ),
                "",
            )
            recording = re.sub(r"^\d+\.\s*", "", recording)
            return {
                "subject": match[1],
                "action": match[2],
                "approver": match[3] or "",
                "timing": match[4],
                "recording": recording,
                "proposition": sentence,
            }
    return {}


@dataclass
class Eligibility:
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    historical: bool = False
    practice_violation: bool = False
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return all(self.checks.values())

    def check(self, name: str, passed: bool, reason: str) -> None:
        self.checks[name] = passed
        if not passed:
            self.reasons.append(reason)


def eligibility(
    claim: AtomicClaim, item: dict[str, Any], source: Source, sources: dict[str, Source]
) -> Eligibility:
    result = Eligibility()
    text = clean(item["text"])
    lower = text.casefold()
    metadata = item.get("metadata", {})
    record = metadata.get("structured_metadata", {}).get("record", {})
    result.fields = rule_fields(item["text"])
    practice = source.source_type in PRACTICE_TYPES
    start = claim.applicable_start_date or datetime.now(UTC).date()
    end = claim.applicable_end_date or start
    constraint, metadata_reasons = metadata_constraint(source.model_dump(mode="json"), start, end)
    result.check("source_metadata", constraint is None, "; ".join(metadata_reasons))
    valid_end = source.effective_end_date
    successor = sources.get(source.successor_source_id)
    successor_start = successor.effective_start_date if successor else None
    result.historical = bool(
        claim.applicable_start_date
        and (
            (valid_end and end <= valid_end)
            or (source.superseded_date and end < source.superseded_date)
            or (successor_start and end < successor_start)
        )
        and (not source.effective_start_date or start >= source.effective_start_date)
    )
    result.check(
        "source",
        source.source_id.startswith("phase2:") and source.ingestion_status != "excluded",
        source.exclusion_reason or "Source excluded from corpus.",
    )
    result.check(
        "lifecycle",
        source.lifecycle_status not in {"draft", "withdrawn"}
        and (source.lifecycle_status != "superseded" or result.historical),
        "Superseded source without period justification or unapproved lifecycle.",
    )
    result.check(
        "dates",
        (not source.effective_start_date or start >= source.effective_start_date)
        and (not valid_end or end <= valid_end)
        and (not successor_start or end < successor_start),
        "Source does not cover the confirmed applicability period.",
    )
    result.check(
        "target",
        (practice or source.source_type in FORMAL_TYPES)
        if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE
        else practice
        if claim.evidence_target
        in {EvidenceTarget.ROUTINE_PRACTICE, EvidenceTarget.ACTUAL_PRACTICE}
        else source.source_type
        in {"crm_records", "operational_record", "system_export", "system_record"},
        "Source type cannot establish this evidence target.",
    )
    claim_context = clean(
        " ".join(
            filter(
                None,
                [claim.claim_text, claim.object, claim.process, claim.scope, *claim.conditions],
            )
        )
    ).casefold()
    if "discount" in claim_context:
        result.check(
            "process",
            "discount" in lower or "discount_pct" in record,
            "Evidence does not establish the discount approval process.",
        )
        requested_value = threshold(claim.claim_text)
        amount = float(requested_value.value) if requested_value else None
        wants_new = "new-business" in claim_context or "new business" in claim_context
        wants_renewal = "renewal" in claim_context and not wants_new
        scope_text = clean(claim.scope or "").casefold()
        business_scope_only = bool(
            re.fullmatch(r"(?:new.business|renewal)(?: deals?)?", scope_text)
        )
        result.check(
            "organisation",
            not scope_text or business_scope_only or scope_text in lower,
            "Additional organisational scope is not established by this evidence.",
        )
        if record:
            scope = str(record.get("deal_type", "")) + " " + str(record.get("notes", ""))
            renewal = "renewal" in scope.casefold()
            result.check(
                "scope",
                not (wants_new and renewal) and not (wants_renewal and not renewal),
                "Deal business scope differs from the confirmed claim.",
            )
            if wants_new and not renewal and not record.get("deal_type"):
                result.limitations.append(
                    "CRM has no explicit deal-type field; new-business scope is inferred from deal context and may require confirmation."
                )
            try:
                value = float(record.get("discount_pct", ""))
            except (ValueError, TypeError):
                value = None
            result.check(
                "threshold",
                value is not None and amount is not None and 0 <= value <= 100 and value >= amount,
                "Missing, invalid or below-boundary discount value cannot establish threshold applicability.",
            )
            if value is None:
                result.limitations.append(
                    "Some retrieved CRM records lack discount values, so threshold applicability cannot be established."
                )
            result.check(
                "event",
                "closed won" not in claim_context
                or str(record.get("stage", "")).casefold() == "closed won",
                "Deal has not reached the claim's Closed Won outcome.",
            )
            closed = str(record.get("close_date", ""))
            # Undated current questions use the current rule period, not today's deals only.
            result.check(
                "record_dates",
                bool(closed)
                and (not claim.applicable_start_date or closed >= start.isoformat())
                and (not claim.applicable_end_date or closed <= end.isoformat()),
                "Record date is missing or outside the confirmed period.",
            )
            approval = str(record.get("approval_record", ""))
            result.practice_violation = bool(
                re.search(
                    r"recorded outside CRM|never went through|without (?:required |written )?approval|approval (?:was )?(?:not obtained|denied)",
                    approval + " " + str(record.get("notes", "")),
                    re.IGNORECASE,
                )
            )
            if approval.casefold() in {"", "none found", "unknown", "not recorded"}:
                result.limitations.append(
                    "Applicable CRM records have missing approval information; this does not prove approval never occurred."
                )
        else:
            proposition = result.fields.get("proposition", "").casefold()
            result.check(
                "directness",
                bool(result.fields),
                "No explicit approval proposition with timing was established.",
            )
            result.check(
                "scope",
                not (wants_new and "renewal" in proposition)
                and not (wants_renewal and "new-business" in proposition),
                "Rule business scope differs from the confirmed claim.",
            )
            boundary = threshold(proposition)
            requested = threshold(claim.claim_text)
            applicable = bool(
                boundary
                and requested
                and threshold_comparison(requested, boundary)["within_policy_range"]
            )
            result.check(
                "threshold",
                applicable,
                "Rule threshold boundary does not establish applicability to this claim.",
            )
            result.check(
                "event",
                "closed won" not in claim_context or "closed won" in proposition,
                "Rule does not establish the required event timing.",
            )
        # Every remaining condition must be explicitly evidenced, not inferred from search score.
        remaining = [
            c
            for c in claim.conditions
            if not re.search(r"discount|closed won|new.business|renewal", c, re.IGNORECASE)
        ]
        result.check(
            "conditions",
            all(clean(c).casefold() in lower for c in remaining),
            "Additional claim conditions are not established.",
        )
    else:
        result.check(
            "process",
            bool(claim.process and clean(claim.process).casefold() in lower),
            "Process applicability is not explicitly established.",
        )
        result.check(
            "scope",
            not claim.scope or clean(claim.scope).casefold() in lower,
            "Organisational scope is not explicitly established.",
        )
        result.check(
            "conditions",
            all(clean(c).casefold() in lower for c in claim.conditions),
            "Claim conditions are not explicitly established.",
        )
    if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE and not practice:
        result.check(
            "approval",
            source.approval_status is None
            or source.approval_status.casefold().startswith("approved"),
            "Formal source is not approved.",
        )
    return result


def employee_excerpt(item: dict[str, Any]) -> str:
    record = item.get("metadata", {}).get("structured_metadata", {}).get("record", {})
    if record:
        fields = [
            ("Deal", "deal_id"),
            ("Discount %", "discount_pct"),
            ("Stage", "stage"),
            ("Close date", "close_date"),
            ("Approval", "approval_record"),
            ("Approver", "approval_role"),
            ("Note", "notes"),
        ]
        return " · ".join(
            f"{label}: {excerpt(str(record.get(key) or 'not recorded'), 100)}"
            for label, key in fields
            if key != "notes" or record.get(key)
        )
    fields = rule_fields(item["text"])
    return excerpt(
        " ".join([fields["proposition"], fields["recording"]]) if fields else item["text"]
    )


def employee_evidence(result: Any) -> tuple[list[dict], list[dict]]:
    items = result.supporting_evidence + result.contradicting_evidence
    return items[:3], items[3:] + result.qualifying_evidence + result.contextual_evidence


def gap_summary(gaps: list[str]) -> str:
    return (
        " ".join(dict.fromkeys(gaps))
        if gaps
        else "No material coverage limitations identified in the assessed evidence."
    )


def excluded_summary(items: list[dict]) -> tuple[dict[str, int], list[dict]]:
    """Count each failed eligibility dimension; bound optional employee examples."""
    from collections import Counter

    counts = Counter()
    for item in items:
        checks = item.get("eligibility", {}).get("checks", {})
        reasons = [name for name, passed in checks.items() if not passed]
        counts.update(reasons or ["other applicability exclusion"])
    return dict(sorted(counts.items())), items[:10]
