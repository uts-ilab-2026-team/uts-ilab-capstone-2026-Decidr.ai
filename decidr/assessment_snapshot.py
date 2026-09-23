"""Presentation data derived only from an immutable assessment, never live retrieval."""

from decidr.claim_graph import evidence_dispositions

SECTIONS = (
    ("Supporting sources", ("supporting_evidence",)),
    ("Contradicting sources", ("contradicting_evidence",)),
    (
        "Exceptions/practice differences",
        ("qualifying_evidence", "contextual_evidence", "divergence_evidence"),
    ),
)


def assessment_findings(result):
    """Retain one disposition per evidence AND target, including exclusions and failures."""
    selected = result["claim"].get("evidence_target")
    targets = result.get("target_findings") or {selected or "all_relevant_evidence": result}
    rows = []
    for target, finding in targets.items():
        notes = finding.get("review_snapshot", result.get("review_snapshot", {}))
        dispositions = evidence_dispositions(finding)
        for record in result["evidence_records"]:
            eid = record["evidence_id"]
            disposition = dispositions.get(
                eid,
                {
                    "evidence_id": eid,
                    "relationship": None,
                    "disposition": "unclassified",
                    "decisive": False,
                },
            )
            note = notes.get(eid, {})
            rows.append(
                {
                    **disposition,
                    "finding_id": target + ":" + eid,
                    "assessment_target": target,
                    "reason": disposition.get("exclusion_reason")
                    or disposition.get("reason")
                    or note.get("link", {}).get(
                        "applicability_reason", "No classification recorded in this snapshot."
                    ),
                    "comparisons": note.get("classification", {}).get("comparisons", []),
                }
            )
    return rows


def build_presentation(result):
    """Freeze sections, coverage and cited actions with the verdict that produced them."""
    findings = assessment_findings(result)
    selected = result["claim"].get("evidence_target")
    visible = [f for f in findings if not selected or f["assessment_target"] == selected]
    sections = []
    for title, keys in SECTIONS:
        relations = {
            "supporting_evidence": "support",
            "contradicting_evidence": "contradict",
            "qualifying_evidence": "qualify",
            "contextual_evidence": "contextual",
            "divergence_evidence": "divergence",
        }
        sections.append(
            {
                "title": title,
                "finding_ids": [
                    f["finding_id"]
                    for f in visible
                    if f["disposition"] == "used"
                    and f["relationship"] in {relations[k] for k in keys}
                ],
            }
        )
    if selected:
        sections[-1]["finding_ids"].extend(
            f["finding_id"]
            for f in findings
            if f["assessment_target"] != selected and f["disposition"] == "used"
        )
    failures = [f for f in visible if f["disposition"] == "unclassified"]
    excluded = [f for f in visible if f["disposition"] == "excluded"]
    used = [f for f in visible if f["disposition"] == "used"]
    actions = []
    if failures:
        actions.append(
            {
                "text": "Review these unclassified passages before relying on the provisional verdict; their meaning has not been established.",
                "finding_ids": [f["finding_id"] for f in failures],
                "basis": "classification_failure",
            }
        )
    scoped = [f for f in used if f["relationship"] in {"contradict", "qualify", "contextual"}]
    if scoped:
        actions.append(
            {
                "text": "Resolve the cited conditions, dates and practice differences for the decision at hand. Confirm formal authority from applicable approved sources where needed.",
                "finding_ids": [f["finding_id"] for f in scoped],
                "basis": "scoped_findings",
            }
        )
    if not actions and used:
        actions.append(
            {
                "text": "Use the cited finding within its stated scope and effective period; revisit it when the source changes.",
                "finding_ids": [f["finding_id"] for f in used],
                "basis": "applicable_findings",
            }
        )
    gaps = [
        {"gap_id": "gap:" + str(i), "text": gap}
        for i, gap in enumerate(result.get("evidence_gaps", []))
    ]
    if gaps:
        actions.append(
            {
                "text": "Obtain evidence addressing the recorded gaps, then create a new assessment.",
                "finding_ids": [],
                "gap_ids": [g["gap_id"] for g in gaps],
                "basis": "evidence_gap",
            }
        )
    retrieval = [
        s
        for s in result.get("limitations", [])
        if any(term in s.lower() for term in ("retrieval", "bounded", "corpus-wide"))
    ]
    if any("retrieval limit" in s.lower() for s in retrieval):
        actions.append(
            {
                "text": "Expand retrieval and assess the additional candidates in a new snapshot; the candidate limit was reached.",
                "finding_ids": [],
                "limit_ids": ["retrieval"],
                "basis": "retrieval_limit",
            }
        )
    return {
        "version": 1,
        "findings": findings,
        "sections": sections,
        "excluded": [f["finding_id"] for f in excluded],
        "failures": [f["finding_id"] for f in failures],
        "coverage": {
            "classified": len(visible) - len(failures),
            "total": len(visible),
            "unit": "evidence–target comparisons",
            "retrieved": len(result["evidence_records"]),
        },
        "gaps": gaps,
        "recommendations": actions,
        "retrieval_limits": retrieval,
    }


def presentation(result):
    """Legacy snapshots get a read-only layout adapter, never a recalculated verdict."""
    return result.get("presentation") or build_presentation(result)
