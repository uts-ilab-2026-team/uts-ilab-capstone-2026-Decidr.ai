"""Resolve explicit, dated policy-adoption rights without inferring them from titles."""

from datetime import date
import re

from decidr.approval_propositions import parse_approval_rule
from decidr.authority_context import _header_citations, authority_context
from decidr.expense_approval import parse_expense_rule
from decidr.interpretation_models import InterpretationCitation
from decidr.policy_adoption import structured_adoptions
from decidr.retrieval_models import Evidence, Source

NAME = r"[\w]+(?:[ '-][\w]+)*"
CODE = r"[A-Z][A-Z0-9]*-\d+"
VERSION = r"[0-9]+(?:\.[0-9]+)*"
SCOPE = r"[\w]+(?:[ -][\w]+)*"
DAY = r"\d{4}-\d{2}-\d{2}"
ADOPTION = re.compile(
    rf"On (?P<decision>{DAY}), (?P<actor>{NAME}) adopted (?P<code>{CODE}) "
    rf"version (?P<version>{VERSION}) for (?P<scope>{SCOPE}) deals, effective (?P<effective>{DAY})\."
)
RIGHT = re.compile(
    rf"(?P<actor>{NAME}) has authority to adopt (?P<code>{CODE}) "
    rf"version (?P<version>{VERSION}) for (?P<scope>{SCOPE}) deals "
    rf"from (?P<start>{DAY}) through (?P<end>{DAY})\."
)


def _quote(passage: Evidence) -> dict:
    return InterpretationCitation(
        evidence_id=passage.evidence_id,
        source_id=passage.source_id,
        locator=passage.locator,
        quotation=passage.text,
        start=0,
        end=len(passage.text),
    ).model_dump(mode="json")


def _eligible(source: Source, when: date) -> bool:
    return bool(
        source.ingestion_status == "ingested"
        and not source.metadata_conflicts
        and source.lifecycle_status == "current"
        and not source.derived_from_source_id
        and source.creation_date
        and source.creation_date <= when
        and (not source.effective_start_date or source.effective_start_date <= when)
        and (not source.effective_end_date or when <= source.effective_end_date)
        and (not source.superseded_date or when < source.superseded_date)
    )


def resolve_authority(
    *,
    source: Source,
    focal: Evidence,
    citation: InterpretationCitation,
    sources: dict[str, Source],
    passages: list[Evidence],
    as_of: date,
) -> dict:
    """Require separate complete adoption and person-specific rights statements.

    These are documentary checks, not authentication or independent corroboration.
    Unsupported relevant records veto resolution rather than being cherry-picked away.
    """
    result = {
        "method": "explicit-policy-adoption-v1",
        "status": "unresolved",
        "authority_verified": None,
        "checks": [],
        "citations": [],
        "limitations": [
            "Only explicit person-specific adoption rights are resolved; titles and operational approval rights are insufficient.",
            "Documentary consistency does not authenticate records or establish independent corroboration.",
            "Unrecognised relevant decisions or rights require human review; delegation chains and implicit scope are unsupported.",
        ],
    }

    def check(name, passed, reason):
        result["checks"].append({"name": name, "passed": bool(passed), "reason": reason})

    if parse_expense_rule(citation.quotation):
        check(
            "expense_adoption_rights",
            False,
            "Expense rule wording is supported, but automatic expense-policy adoption and rights resolution is not yet supported.",
        )
        result["gaps"] = [
            {
                "kind": "interpretation_limit",
                "message": "Review dated adoption and policy-making rights for this expense policy; matching operational approval wording does not establish them.",
            }
        ]
        return result
    code_match = re.match(rf"^({CODE})(?=\s|$)", source.title)
    rule = parse_approval_rule(citation.quotation)
    release, separator, _ = source.source_id.partition(":")
    if not code_match or not separator or not rule or not source.version:
        check(
            "policy_identity",
            False,
            "A supported rule, release-scoped policy code and explicit version are required.",
        )
        return result
    code = code_match[1]
    local_sources = {k: v for k, v in sources.items() if k.startswith(release + ":")}
    owners = [
        s for s in local_sources.values() if re.match(rf"^{re.escape(code)}(?=\s|$)", s.title)
    ]
    context = authority_context(
        source=source,
        focal=focal,
        citation=citation,
        passages=passages,
        facet=citation.quotation,
        as_of=as_of.isoformat(),
    )
    local = [p for p in passages if p.source_id == source.source_id]
    version_rows = _header_citations(source, local, "version")
    date_rows = _header_citations(source, local, "effective date")
    policy_ok = (
        len(owners) == 1
        and source.source_type == "policy"
        and not source.metadata_conflicts
        and source.ingestion_status == "ingested"
        and source.lifecycle_status == "current"
        and not source.derived_from_source_id
        and source.effective_start_date
        and source.effective_start_date <= as_of
        and (not source.creation_date or source.creation_date <= as_of)
        and (not source.effective_end_date or as_of <= source.effective_end_date)
        and (not source.superseded_date or as_of < source.superseded_date)
        and context["document_approval"]["status"] == "documented_assertion"
        and context["document_approval"]["value"] == "current"
        and {e["value"] for e, _ in version_rows} == {source.version}
        and {e["value"] for e, _ in date_rows} == {source.effective_start_date.isoformat()}
    )
    check(
        "policy_version_and_dates",
        policy_ok,
        "Require a unique current policy with exact version, approval and effective-date header evidence.",
    )
    result["citations"].extend(context["document_approval"]["citations"])
    result["citations"].extend(c.model_dump(mode="json") for _, c in version_rows + date_rows)
    relevant = []
    for p in passages:
        s = local_sources.get(p.source_id)
        if (
            s
            and s.source_id != source.source_id
            and re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", p.text)
        ):
            relevant.append(p)
    # A meeting action can identify the policy while its decision lives in a
    # sibling section. Keep that context visible; proximity is not adoption proof.
    parents = {
        (p.source_id, p.section.rsplit(" > ", 1)[0])
        for p in relevant
        if p.section and " > " in p.section and local_sources[p.source_id].source_type == "meeting"
    }
    known = {p.evidence_id for p in relevant}
    for p in passages:
        if (
            p.evidence_id not in known
            and p.section
            and " > " in p.section
            and (p.source_id, p.section.rsplit(" > ", 1)[0]) in parents
            and (p.heading or "").casefold()
            in {
                "final decision",
                "decision owner",
                "conditions or exceptions",
                "unresolved matters",
            }
        ):
            relevant.append(p)
    result["citations"].extend(_quote(p) for p in relevant)
    structured = structured_adoptions(source, rule, passages, sources)
    result["adoption_findings"] = list(structured.values())
    extra_ids = {eid for finding in structured.values() for eid in finding["evidence_ids"]}
    quoted = {c["evidence_id"] for c in result["citations"]}
    result["citations"].extend(_quote(p) for p in passages if p.evidence_id in extra_ids - quoted)
    adoptions, rights, blockers = [], [], []
    for p in relevant:
        s = local_sources[p.source_id]
        if (p.heading or "").casefold() not in {
            "final decision",
            "decision rights",
            "policy adoption",
            "revocations",
            "exceptions",
            "conditions or exceptions",
            "unresolved matters",
        }:
            if re.search(
                r"\b(not|never|revoked|withdrawn|unless|conditional|except|suspended)\b",
                p.text,
                re.IGNORECASE,
            ):
                blockers.append(p.evidence_id)
            continue
        if (p.heading or "").casefold() in {
            "conditions or exceptions",
            "unresolved matters",
            "exceptions",
        } and p.text.strip().casefold() in {
            "none.",
            "none discussed or agreed.",
            "none recorded at the time.",
        }:
            continue
        adoption = ADOPTION.fullmatch(p.text.strip())
        right = RIGHT.fullmatch(p.text.strip())
        try:
            if (adoption or p.evidence_id in structured) and s.source_type == "meeting":
                values = adoption.groupdict() if adoption else structured[p.evidence_id]
                decision, effective = (
                    date.fromisoformat(values["decision"]),
                    date.fromisoformat(values["effective"]),
                )
                if (
                    not re.search(
                        r"\b(and|or|not|unless|except)\b", values["actor"], re.IGNORECASE
                    )
                    and values["code"] == code
                    and values["version"] == source.version
                    and values["scope"].casefold() == rule.deal_scope
                    and effective == source.effective_start_date
                    and decision <= effective <= as_of
                    and _eligible(s, as_of)
                    and decision <= s.creation_date
                ):
                    adoptions.append((values, p, s, decision))
                else:
                    blockers.append(p.evidence_id)
            elif right and s.source_type in {"organisational_information", "role_description"}:
                values = right.groupdict()
                start, end = date.fromisoformat(values["start"]), date.fromisoformat(values["end"])
                if (
                    not re.search(
                        r"\b(and|or|not|unless|except)\b", values["actor"], re.IGNORECASE
                    )
                    and values["code"] == code
                    and values["version"] == source.version
                    and values["scope"].casefold() == rule.deal_scope
                    and start <= end
                ):
                    rights.append((values, p, s, start, end))
                else:
                    blockers.append(p.evidence_id)
            else:
                blockers.append(p.evidence_id)
        except ValueError:
            blockers.append(p.evidence_id)
    # Inspect conditions belonging to the same decision section, including clauses
    # that do not repeat the policy code.
    records = [(p, s) for _, p, s, _ in adoptions] + [(p, s) for _, p, s, _, _ in rights]
    for adoption_passage, adoption_source in records:
        parent = (adoption_passage.section or "").rsplit(" > ", 1)[0]
        for p in passages:
            if p.source_id != adoption_source.source_id or (p.heading or "").casefold() not in {
                "conditions or exceptions",
                "unresolved matters",
                "exceptions",
                "revocations",
            }:
                continue
            if parent and (p.section or "").rsplit(" > ", 1)[0] != parent:
                continue
            result["citations"].append(_quote(p))
            if p.text.strip().casefold() not in {
                "none.",
                "none discussed or agreed.",
                "none recorded at the time.",
            }:
                blockers.append(p.evidence_id)
    check(
        "adoption",
        len(adoptions) == 1,
        "Require one dated adoption linked to the policy version and scope, directly or through matching version history, completed actions and sign-off.",
    )
    chains = []
    for a, ap, adoption_source, decision in adoptions:
        for r, rp, rights_source, start, end in rights:
            identities = (source, adoption_source, rights_source)
            independent_records = (
                len({s.source_id for s in identities}) == 3
                and len({s.checksum for s in identities}) == 3
                and len([s.duplicate_group for s in identities if s.duplicate_group])
                == len({s.duplicate_group for s in identities if s.duplicate_group})
            )
            if (
                a["actor"] == r["actor"]
                and start <= decision <= end
                and _eligible(rights_source, decision)
                and independent_records
            ):
                chains.append((ap.evidence_id, rp.evidence_id))
    check(
        "adoption_rights",
        len(chains) == 1,
        "Require dated adoption rights for the named decision-maker, not merely authority to approve individual transactions. Known copies and derived records cannot establish the chain.",
    )
    check(
        "conflicts",
        not blockers,
        "All relevant decision/right passages must be supported and consistent; unresolved records block verification.",
    )
    result["blocking_evidence_ids"] = list(dict.fromkeys(blockers))
    result["gaps"] = []
    if not adoptions:
        result["gaps"].append(
            {
                "kind": "interpretation_limit" if relevant else "evidence_gap",
                "message": "No dated adoption could be connected to this policy version and scope using the supported document structures.",
            }
        )
    if not rights:
        result["gaps"].append(
            {
                "kind": "evidence_gap",
                "message": "No supported explicit, dated policy-adoption right was found. Transaction approval rights and titles do not establish this right; unrecognised wording may still require review.",
            }
        )
    elif not chains:
        result["gaps"].append(
            {
                "kind": "chain_mismatch",
                "message": "The available rights do not form a valid dated chain to the adoption decision.",
            }
        )
    if blockers:
        result["gaps"].append(
            {
                "kind": "unresolved_context",
                "message": "Other relevant records contain unrecognised or potentially conflicting context; they are retained for review, not treated as proven contradictions.",
            }
        )
    if all(c["passed"] for c in result["checks"]):
        result.update(status="documented_authority_resolved", authority_verified=True)
    else:
        result["review_guidance"] = []
        quoted = {c["evidence_id"] for c in result["citations"]}
        for adoption, _, _, decision in adoptions:
            result["review_guidance"].append(
                f"Verify whether {adoption['actor']} held authority to adopt {code} "
                f"version {source.version} for {rule.deal_scope} deals on {decision.isoformat()}. "
                "Locate a dated grant or delegation covering that decision, including its scope, "
                "effective period and any conditions or revocations. A sign-off records the act; "
                "it does not by itself establish the right to perform it."
            )
            # Role records aid review only; heading matches never establish rights.
            for p in passages:
                role_source = local_sources.get(p.source_id)
                heading = (p.heading or "").strip()
                if (
                    role_source
                    and role_source.source_type
                    in {"organisational_information", "role_description"}
                    and heading.endswith(" — " + adoption["actor"])
                ):
                    if p.evidence_id not in quoted:
                        result["citations"].append(_quote(p))
                        quoted.add(p.evidence_id)
                    result["review_guidance"].append(
                        f"Role context: {p.evidence_id} ({role_source.source_id}). "
                        "Retained for review only; role titles and general delegation do not "
                        "establish policy-adoption rights. "
                        + (
                            "The source has no recorded creation date, so its availability at the decision date is not established."
                            if not role_source.creation_date
                            else "Check the record's applicability at the decision date."
                        )
                    )
        if result["review_guidance"]:
            result["review_guidance"].append(
                "In Review this result, record the supporting source and passage identifiers, "
                "applicable dates and reasoning in Judgement basis, then explain the change in "
                "Reason for this review. If the evidence does not establish authority, leave it "
                "Unresolved. Saving a review creates a separate revision; the automatic result is preserved."
            )
    return result
