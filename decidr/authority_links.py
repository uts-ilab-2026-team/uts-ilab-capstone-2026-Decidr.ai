"""Explicit cross-document references for inspection, never authority proofs."""

from datetime import date
import re

from decidr.retrieval_models import Evidence, Source


def _quote(passage: Evidence) -> dict:
    return {
        "evidence_id": passage.evidence_id,
        "source_id": passage.source_id,
        "locator": passage.locator,
        "quotation": passage.text,
        "start": 0,
        "end": len(passage.text),
    }


def _date_context(source: Source, as_of: date) -> dict:
    status = "unresolved"
    reasons = ["Document dates do not establish the date or authority of a described decision."]
    if source.creation_date and source.creation_date > as_of:
        status = "recorded_after_assessment"
        reasons.append("The source was recorded after the requested assessment date.")
    elif source.creation_date:
        status = "recorded_on_or_before_assessment"
    return {
        "status": status,
        "creation_date": source.creation_date.isoformat() if source.creation_date else None,
        "effective_start_date": source.effective_start_date.isoformat()
        if source.effective_start_date
        else None,
        "reasons": reasons,
    }


def explicit_authority_links(
    *,
    source: Source,
    sources: list[Source],
    passages: list[Evidence],
    as_of: date,
    limit: int = 12,
) -> dict:
    """Match a unique leading document code within the same corpus release.

    A match means only that another source explicitly mentions this document.
    The complete referring passage is retained so negation and qualifications
    are not removed. No keyword is treated as proof of sign-off.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    match = re.match(r"^([A-Z][A-Z0-9]*-\d+)(?=\s|$)", source.title)
    result = {
        "status": "unresolved",
        "links": [],
        "total_matches": 0,
        "omitted_matches": 0,
        "authority_verified": None,
        "scope_matches": None,
        "temporal_matches": None,
        "limitations": [
            "References are contextual links, not proof of adoption or independent corroboration.",
            "Decision scope, signatory authority and event dates require separate resolution.",
            "Only explicit document codes in the same release are searched; this is not exhaustive authority retrieval.",
        ],
    }
    release, separator, _ = source.source_id.partition(":")
    if not match or not separator:
        result["reason"] = "No release-scoped leading document code is available."
        return result
    code = match[1]
    pattern = re.compile(rf"(?<![\w-]){re.escape(code)}(?![\w-])")
    local_sources = {
        s.source_id: s
        for s in sources
        if s.source_id.startswith(release + ":")
        and s.ingestion_status not in {"excluded", "failed"}
    }
    owners = [
        s for s in local_sources.values() if re.match(rf"^{re.escape(code)}(?=\s|$)", s.title)
    ]
    if len(owners) != 1 or owners[0].source_id != source.source_id:
        result["reason"] = "Document code is absent or ambiguous in this release."
        return result
    matches = sorted(
        (
            p
            for p in passages
            if p.source_id != source.source_id
            and p.source_id in local_sources
            and pattern.search(p.text)
        ),
        key=lambda p: (p.source_id, p.locator, p.evidence_id),
    )
    for passage in matches[:limit]:
        referring = local_sources[passage.source_id]
        result["links"].append(
            {
                "relationship": "explicit_document_reference",
                "referenced_code": code,
                "source_id": referring.source_id,
                "source_title": referring.title,
                "source_type": referring.source_type,
                "lifecycle_status": referring.lifecycle_status,
                "metadata_conflicts": referring.metadata_conflicts,
                "citation": _quote(passage),
                "date_context": _date_context(referring, as_of),
                "adoption_status": "unresolved",
            }
        )
    result["status"] = "references_found" if matches else "unresolved"
    result["total_matches"] = len(matches)
    result["omitted_matches"] = max(0, len(matches) - limit)
    result["reason"] = "Explicit references require review for adoption, scope and authority."
    return result
