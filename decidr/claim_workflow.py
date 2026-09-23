"""Claim-first application services over the existing SQLite ledger and reasoner.

Runtime never loads study portfolios, labels, reference relationships or verdicts.
Review packets, completion receipts and assessment snapshots are separate from study data.
"""

from dataclasses import asdict
from datetime import UTC, date, datetime
import hashlib
import json
import re
import sqlite3
from uuid import uuid4

from decidr.approach_a import to_assessment_result
from decidr.automatic_evidence import VERSION as CLASSIFIER_VERSION
from decidr.automatic_evidence import classify_evidence
from decidr.claim_graph import evidence_dispositions
from decidr.claim_intake import IntakePart, interpret_claim
from decidr.corpus import eligible_modelling_evidence
from decidr.database import record_audit, save_claim, save_credibility, save_link
from decidr.hybrid import reciprocal_rank_fusion
from decidr.models import (
    AtomicClaim,
    ClaimEvidenceLink,
    CredibilityAssessment,
    Evidence,
    EvidenceMode,
    EvidenceRelationship,
    EvidenceTarget,
    Source,
)
from decidr.reasoning import ReasoningConfig, ReviewedEvidence, assess_claim
from decidr.retrieval import SearchQuery, lexical_text_search
from decidr.semantic import SentenceTransformerEmbedder, semantic_text_search
from decidr.source_metadata import metadata_constraint

DIMENSIONS = tuple(ReasoningConfig().dimension_weights)
RISK_KINDS = (
    "stale_belief",
    "unresolved_decision_rights",
    "data_quality",
    "policy_practice_divergence",
)


def initialise_workflow(connection: sqlite3.Connection) -> None:
    """Add application tables without changing source, study or historical records."""
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS employee_claims (
            entry_id TEXT PRIMARY KEY, claim_id TEXT REFERENCES claims(claim_id),
            original_wording TEXT NOT NULL, kind TEXT NOT NULL,
            status TEXT NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS employee_review_runs (
            run_id TEXT PRIMARY KEY, entry_id TEXT NOT NULL REFERENCES employee_claims(entry_id),
            reviewer TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL,
            result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS employee_review_notes (
            run_id TEXT NOT NULL REFERENCES employee_review_runs(run_id),
            evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
            payload_json TEXT NOT NULL, PRIMARY KEY(run_id,evidence_id)
        );
    """)


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def corpus_state(connection: sqlite3.Connection) -> dict:
    """Fingerprint the ledger without reading any claim or research label."""
    rows = connection.execute(
        "SELECT source_id,checksum,payload_json FROM sources ORDER BY source_id"
    ).fetchall()
    raw = hashlib.sha256()
    dates = []
    for sid, checksum, payload in rows:
        raw.update(f"{sid}\0{checksum}\n".encode())
        source = json.loads(payload)
        if eligible_modelling_evidence(
            source, {}, source.get("ingestion_status", "")
        ) and source.get("creation_date"):
            dates.append(source["creation_date"])
    evidence = connection.execute(
        "SELECT evidence_id,payload_json FROM evidence ORDER BY evidence_id"
    ).fetchall()
    return {
        "corpus_fingerprint": raw.hexdigest(),
        "ledger_revision": _digest([list(r) for r in rows] + [list(r) for r in evidence]),
        "snapshot_date": max(dates) if dates else None,
        "date_basis": "Latest creation date among eligible sources; a visible snapshot convention, not proof of completeness",
    }


def evidence_catalog(connection: sqlite3.Connection) -> dict[str, dict]:
    catalog = {}
    for eid, ep, sp, status in connection.execute("""
        SELECT e.evidence_id,e.payload_json,s.payload_json,s.ingestion_status
        FROM evidence e JOIN sources s ON s.source_id=e.source_id ORDER BY e.evidence_id
    """):
        evidence, source = json.loads(ep), json.loads(sp)
        if eligible_modelling_evidence(source, evidence, status):
            catalog[eid] = {"evidence": evidence, "source": source}
    return catalog


def search_evidence(connection, text: str, *, semantic=False, embedder=None, limit=20) -> dict:
    """Search without asserting a claim; isolate all optional semantic failures."""
    if not 1 <= limit <= 50:
        raise ValueError("Search limit must be between 1 and 50")
    query = SearchQuery(text)
    lexical = lexical_text_search(connection, query, limit=limit)
    semantic_results, status = [], "Disabled; lexical retrieval only"
    if semantic:
        try:
            adapter = embedder or SentenceTransformerEmbedder()
            semantic_results = semantic_text_search(connection, query, adapter, limit=limit)
            status = f"Available locally: {adapter.name} ({adapter.version})"
        except Exception as error:  # noqa: BLE001 -- isolate optional local model failures
            status = f"Unavailable ({type(error).__name__}); lexical results retained"
    fused = reciprocal_rank_fusion(lexical, semantic_results, limit=limit)
    catalog = evidence_catalog(connection)
    results = []
    for item in fused:
        if item.evidence_id not in catalog:
            continue
        record = asdict(item)
        record.update(catalog[item.evidence_id])
        record["retrieval_origin"] = "rank_fusion"
        results.append(record)
    return {
        "results": results,
        "semantic_status": status,
        "method": "hybrid" if semantic_results else "lexical",
        "limit": limit,
        "query": text,
        "conclusions_verified": False,
    }


def expand_evidence(connection, packet: dict, *, limit=30) -> dict:
    """Bound expansion to explicit source provenance; added matches need review too."""
    packet = json.loads(json.dumps(packet))
    catalog = evidence_catalog(connection)
    source_ids = {r["source_id"] for r in packet["results"][:5]}
    neighbours = set()
    for item in catalog.values():
        source = item["source"]
        for field in ("derived_from_source_id", "predecessor_source_id", "successor_source_id"):
            target = source.get(field)
            if source["source_id"] in source_ids and target:
                neighbours.add(target)
            if target in source_ids:
                neighbours.add(source["source_id"])
    seen = {r["evidence_id"] for r in packet["results"]}
    for eid, item in catalog.items():
        if len(packet["results"]) >= limit:
            break
        ev = item["evidence"]
        if eid not in seen and ev["source_id"] in neighbours:
            packet["results"].append(
                {
                    "evidence_id": eid,
                    "source_id": ev["source_id"],
                    "locator": ev["locator"],
                    "text": ev["text"],
                    **item,
                    "retrieval_origin": "explicit_source_graph",
                    "rank": len(seen) + 1,
                }
            )
            seen.add(eid)
    packet["graph_limit"] = limit
    return packet


def entries(connection) -> list[dict]:
    # Only our explicit application register is visible. Never enumerate study claims.
    return [
        dict(
            entry_id=row[0],
            claim_id=row[1],
            original_wording=row[2],
            kind=row[3],
            status=row[4],
            **json.loads(row[5]),
        )
        for row in connection.execute("""
                SELECT entry_id,claim_id,original_wording,kind,status,payload_json
                FROM employee_claims ORDER BY created_at,rowid
            """)
    ]


def get_entry(connection, entry_id) -> dict:
    return (
        next((entry for entry in entries(connection) if entry["entry_id"] == entry_id), None)
        or _missing()
    )


def _missing():
    raise ValueError("Unknown employee claim")


def submit_claim(connection, wording: str, *, target=None, parent_run_id=None) -> list[str]:
    intake = contextual_intake(connection, wording, target=target)
    parent = get_run(connection, parent_run_id) if parent_run_id and target else None
    if parent and wording != parent["claim"]["claim_text"]:
        raise ValueError("A scope change must retain its parent assessment's interpreted claim")
    original = parent["submission_original"] if parent else wording
    ids = []
    for part in intake.parts:
        entry_id = "ENTRY-" + uuid4().hex[:16]
        if parent:
            part.provenance.update(
                meaning_basis="scope_change_from_assessment",
                parent_run_id=parent_run_id,
                prior_interpretation=parent.get("interpretation_provenance", {}),
            )
        if part.claim:
            part.claim.original_claim_text = original
            save_claim(connection, part.claim)
        payload = {
            "intake": part.model_dump(mode="json"),
            "clarifications": [],
            "submission_parts": len(intake.parts),
            "interpretation_review": None,
            "parent_run_id": parent_run_id,
        }
        connection.execute(
            "INSERT INTO employee_claims VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (
                entry_id,
                part.claim.claim_id if part.claim else None,
                original,
                "employee_entered",
                part.status,
                json.dumps(payload),
            ),
        )
        record_audit(
            connection,
            actor="employee",
            action="claim_submitted",
            entity_type="employee_claim",
            entity_id=entry_id,
            changed_fields={"original_wording": original, **payload},
        )
        ids.append(entry_id)
    return ids


def contextual_intake(connection, wording, *, target=None):
    """Resolve vocabulary from eligible sources, never import a policy answer into a claim."""
    from decidr.automatic_evidence import expense_route_claim

    intake = interpret_claim(wording, target=target)
    for part in intake.parts:
        if not expense_route_claim(part.text):
            continue
        packet = search_evidence(connection, part.text)
        context = [
            {key: r[key] for key in ("evidence_id", "source_id", "locator", "text")}
            for r in packet["results"]
            if "expense approval" in r["source"]["title"].casefold()
            or re.search(
                r"onboarding.{0,45}(travel|visit)|travel.{0,60}onboarding",
                r["text"],
                re.IGNORECASE,
            )
        ]
        part.provenance["terminology_context"] = context
        part.provenance["interpreted_claim"] = part.text.strip()
        if context:
            part.provenance["terminology_basis"] = (
                "Customer-onboarding travel refers to travel for customer onboarding visits; "
                "normal expense approval route refers to the general expense approval process. "
                "No approver, threshold, or exception has been inserted into the claim."
            )
    return intake


def clarify_claim(connection, entry_id: str, response: str, *, target=None) -> None:
    """Keep every clarification; only the explicit target question has automatic merging."""
    if not response.strip():
        raise ValueError("Enter the clarification")
    entry = get_entry(connection, entry_id)
    if entry["status"] != "awaiting_clarification":
        raise ValueError("This claim is not awaiting clarification")
    entry["clarifications"].append(response)
    old = IntakePart.model_validate(entry["intake"])
    if (
        target
        and old.clarification
        and (
            old.clarification.startswith("Is this about")
            or old.provenance.get("clarification_kind") == "evidence_target"
        )
    ):
        part = contextual_intake(connection, old.text, target=target).parts[0]
        if part.claim:
            part.claim.original_claim_text = entry["original_wording"]
            save_claim(connection, part.claim)
            connection.execute(
                "UPDATE employee_claims SET claim_id=?,status=? WHERE entry_id=?",
                (part.claim.claim_id, part.status, entry_id),
            )
        entry["intake"] = part.model_dump(mode="json")
    _update_entry(connection, entry_id, entry)
    record_audit(
        connection,
        actor="employee",
        action="claim_clarified",
        entity_type="employee_claim",
        entity_id=entry_id,
        changed_fields={"response": response, "target": target},
    )


def _update_entry(connection, entry_id, entry):
    payload = {
        key: entry.get(key)
        for key in (
            "intake",
            "clarifications",
            "submission_parts",
            "interpretation_review",
            "parent_run_id",
        )
    }
    connection.execute(
        "UPDATE employee_claims SET payload_json=? WHERE entry_id=?",
        (json.dumps(payload), entry_id),
    )


def review_interpretation(connection, entry_id, claim: AtomicClaim, *, reviewer: str, reason: str):
    """Manual fallback for unsupported grammar, with explicit retained meaning attestation."""
    entry = get_entry(connection, entry_id)
    if entry["status"] != "awaiting_clarification" or not reviewer.strip() or not reason.strip():
        raise ValueError("Pending interpretation, reviewer and justification are required")
    # Exact wording stays the assessed claim. Structured values must occur in its full context.
    context = entry["intake"]["text"] + "\n" + "\n".join(entry["clarifications"])
    if (
        claim.claim_text != entry["intake"]["text"].strip()
        or claim.evaluation_split != "development"
    ):
        raise ValueError(
            "Keep the exact submitted statement; no evaluation claims may be imported"
        )
    if any(value not in context for value in (claim.subject, claim.predicate, claim.object)):
        raise ValueError("Meaning fields must quote the original claim or its clarification")
    claim = claim.model_copy(
        update={
            "claim_id": "CF-" + uuid4().hex[:16],
            "original_claim_text": entry["original_wording"],
            "scope": context,
            "atomicity_status": "human_reviewed",
        }
    )
    save_claim(connection, claim)
    entry["intake"]["claim"] = claim.model_dump(mode="json")
    entry["intake"]["status"] = "awaiting_evidence_review"
    entry["interpretation_review"] = {"reviewer": reviewer, "reason": reason, "context": context}
    _update_entry(connection, entry_id, entry)
    connection.execute(
        "UPDATE employee_claims SET claim_id=?,status='awaiting_evidence_review' WHERE entry_id=?",
        (claim.claim_id, entry_id),
    )
    record_audit(
        connection,
        actor=reviewer,
        action="interpretation_reviewed",
        entity_type="employee_claim",
        entity_id=entry_id,
        changed_fields=entry["interpretation_review"],
    )


def reusable_match(connection, wording: str) -> dict | None:
    """Conservative exact match; no similarity, case folding or protected-value substitution."""
    interpretation = interpret_claim(wording)
    if len(interpretation.parts) != 1 or interpretation.parts[0].claim is None:
        return None
    protected_fields = (
        "subject",
        "predicate",
        "object",
        "scope",
        "conditions",
        "applicable_start_date",
        "applicable_end_date",
        "evidence_target",
        "proposition_polarity",
    )
    candidate = interpretation.parts[0].claim.model_dump(mode="json")
    for entry in entries(connection):
        stored = entry["intake"]["claim"]
        if (
            entry["kind"] == "reviewed_reusable"
            and entry["original_wording"] == wording
            and not entry["clarifications"]
            and stored
            and all(candidate[key] == stored[key] for key in protected_fields)
        ):
            return entry
    return None


def promote_claim(connection, entry_id: str, *, reviewer: str, reason: str):
    entry = get_entry(connection, entry_id)
    if entry["status"] != "completed_assessment" or not reviewer.strip() or not reason.strip():
        raise ValueError(
            "Complete assessment and a human meaning-review justification are required"
        )
    if entry["submission_parts"] != 1:
        raise ValueError("Register compound components separately before reuse")
    entry["interpretation_review"] = {"reviewer": reviewer, "reason": reason}
    _update_entry(connection, entry_id, entry)
    connection.execute(
        "UPDATE employee_claims SET kind='reviewed_reusable' WHERE entry_id=?", (entry_id,)
    )
    record_audit(
        connection,
        actor=reviewer,
        action="reusable_claim_reviewed",
        entity_type="employee_claim",
        entity_id=entry_id,
        changed_fields=entry["interpretation_review"],
    )


def begin_review(
    connection, entry_id: str, reviewer: str, as_of: date, *, semantic=False, embedder=None
) -> str:
    entry = get_entry(connection, entry_id)
    if not entry["claim_id"] or not reviewer.strip():
        raise ValueError("Resolve claim meaning and name the reviewer first")
    claim = AtomicClaim.model_validate(entry["intake"]["claim"])
    if claim.evaluation_split != "development" or claim.inclusion_status != "included":
        raise ValueError("Only runtime development claims can be assessed")
    packet = expand_evidence(
        connection,
        search_evidence(
            connection, claim.claim_text, semantic=semantic, embedder=embedder, limit=50
        ),
        limit=50,
    )
    run_id = "RUN-" + uuid4().hex[:16]
    payload = {
        "claim": claim.model_dump(mode="json"),
        "as_of": as_of.isoformat(),
        "submission_original": entry["original_wording"],
        "interpretation_provenance": entry["intake"]["provenance"],
        "parent_run_id": entry.get("parent_run_id"),
        "packet": packet,
        **corpus_state(connection),
        "receipt": None,
        "source_graph": {
            r["source"]["source_id"]: r["source"] for r in evidence_catalog(connection).values()
        },
    }
    connection.execute(
        "INSERT INTO employee_review_runs VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (run_id, entry_id, reviewer, "awaiting_evidence_review", json.dumps(payload), None),
    )
    return run_id


def get_run(connection, run_id) -> dict:
    row = connection.execute(
        "SELECT entry_id,reviewer,status,payload_json,result_json FROM employee_review_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Unknown review run")
    return dict(
        run_id=run_id,
        entry_id=row[0],
        reviewer=row[1],
        status=row[2],
        **json.loads(row[3]),
        result=json.loads(row[4]) if row[4] else None,
    )


def runs(connection, entry_id=None) -> list[dict]:
    rows = connection.execute(
        "SELECT run_id FROM employee_review_runs ORDER BY created_at,rowid"
    ).fetchall()
    return [
        run
        for row in rows
        if (run := get_run(connection, row[0]))
        and (entry_id is None or run["entry_id"] == entry_id)
    ]


def _editable_run(connection, run_id):
    run = get_run(connection, run_id)
    if run["status"] != "awaiting_evidence_review":
        raise ValueError("Completed reviews are immutable; start another review")
    if corpus_state(connection)["ledger_revision"] != run["ledger_revision"]:
        raise ValueError("Evidence ledger changed; start a new review packet")
    return run


def add_evidence(connection, run_id, evidence_id):
    run = _editable_run(connection, run_id)
    catalog = evidence_catalog(connection)
    if evidence_id not in catalog:
        raise ValueError("Evidence is not eligible Phase 2 knowledge")
    results = run["packet"]["results"]
    if any(r["evidence_id"] == evidence_id for r in results):
        return
    if len(results) >= 50:
        raise ValueError("Review packet is bounded to 50 evidence units")
    item = catalog[evidence_id]
    ev = item["evidence"]
    results.append(
        {
            **item,
            "evidence_id": evidence_id,
            "source_id": ev["source_id"],
            "locator": ev["locator"],
            "text": ev["text"],
            "retrieval_origin": "reviewer_added",
        }
    )
    _save_run_payload(connection, run)


def _save_run_payload(connection, run):
    payload = {
        k: v
        for k, v in run.items()
        if k not in {"run_id", "entry_id", "reviewer", "status", "result"}
    }
    connection.execute(
        "UPDATE employee_review_runs SET payload_json=? WHERE run_id=?",
        (json.dumps(payload), run["run_id"]),
    )


def review_evidence(
    connection,
    run_id,
    evidence_id,
    *,
    relationship: str,
    matches: dict,
    mode: str,
    dimensions: dict,
    justification: str,
    applicability_reason: str,
    proposed=False,
    gaps=None,
    settlement="",
    responsible_role="",
    role_quote="",
    risks=None,
    risk_reason="",
    origin_source_id="",
    origin_quote="",
    temporal_basis="",
    intended_value_confirmed=False,
    corroborating_evidence_ids=None,
) -> None:
    """Persist explicit reviews, never turn retrieved similarity into a relationship."""
    run = _editable_run(connection, run_id)
    record = next((r for r in run["packet"]["results"] if r["evidence_id"] == evidence_id), None)
    if record is None:
        raise ValueError("Evidence must be in the review packet")
    if set(dimensions) != set(DIMENSIONS):
        raise ValueError("Review all seven credibility dimensions")
    risks = risks or []
    if any(risk not in RISK_KINDS for risk in risks) or (risks and not risk_reason.strip()):
        raise ValueError("Risk flags require a supported category and evidence-specific rationale")
    if responsible_role and (
        not role_quote or role_quote not in record["text"] or responsible_role not in role_quote
    ):
        raise ValueError("The responsible role must be quoted from this evidence")
    if origin_source_id:
        known_sources = {
            item["source"]["source_id"] for item in evidence_catalog(connection).values()
        }
        if (
            origin_source_id not in known_sources
            or not origin_quote
            or origin_quote not in record["text"]
        ):
            raise ValueError(
                "A reviewed shared origin needs an eligible source and an exact provenance quote"
            )
    if gaps and not settlement.strip():
        raise ValueError("Explain what information would settle the recorded gaps")
    corroborating_evidence_ids = corroborating_evidence_ids or []
    packet_ids = {r["evidence_id"] for r in run["packet"]["results"]}
    if intended_value_confirmed and (
        not corroborating_evidence_ids
        or evidence_id in corroborating_evidence_ids
        or not set(corroborating_evidence_ids) <= packet_ids
    ):
        raise ValueError("Independent confirmation needs other evidence IDs in this review packet")
    link_id = f"{run_id}:{evidence_id}"
    link = ClaimEvidenceLink(
        link_id=link_id,
        claim_id=run["claim"]["claim_id"],
        evidence_id=evidence_id,
        reviewer=f"claim-first:{run_id}:{run['reviewer']}",
        relationship=relationship,
        applicability_reason=applicability_reason,
        review_status="proposed" if proposed else "complete",
        method="suggestion" if proposed else "human_review",
        **matches,
    )
    credibility = CredibilityAssessment(
        assessment_id=link_id + ":cred",
        link_id=link_id,
        evidence_mode=mode,
        reviewer_justification=justification,
        **dimensions,
    )
    notes = {
        "gaps": gaps or [],
        "settlement": settlement,
        "responsible_role": responsible_role,
        "role_quote": role_quote,
        "risks": risks,
        "risk_reason": risk_reason,
        "origin_source_id": origin_source_id,
        "origin_quote": origin_quote,
        "temporal_basis": temporal_basis,
        "intended_value_confirmed": intended_value_confirmed,
        "corroborating_evidence_ids": corroborating_evidence_ids,
        "link": link.model_dump(mode="json"),
        "credibility": credibility.model_dump(mode="json"),
    }
    save_link(connection, link)
    save_credibility(connection, credibility)
    connection.execute(
        "INSERT INTO employee_review_notes VALUES (?,?,?) ON CONFLICT(run_id,evidence_id) DO UPDATE SET payload_json=excluded.payload_json",
        (run_id, evidence_id, json.dumps(notes)),
    )


def review_notes(connection, run_id) -> dict:
    return {
        row[0]: json.loads(row[1])
        for row in connection.execute(
            "SELECT evidence_id,payload_json FROM employee_review_notes WHERE run_id=? ORDER BY evidence_id",
            (run_id,),
        )
    }


def _source_groups(records, notes, source_graph):
    sources = source_graph
    parent = {sid: sid for sid in sources}

    def root(sid):
        parent.setdefault(sid, sid)
        while parent[sid] != sid:
            sid = parent[sid]
        return sid

    def union(left, right):
        a, b = root(left), root(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for sid, source in sources.items():
        if source.get("derived_from_source_id"):
            union(sid, source["derived_from_source_id"])
        if source.get("duplicate_group"):
            union(sid, "group:" + source["duplicate_group"])
    for record in records:
        origin = notes[record["evidence_id"]].get("origin_source_id")
        if origin:
            union(record["source_id"], origin)
    return {sid: root(sid) for sid in sources}


def _evidence_groups(records, notes, source_graph):
    groups = _source_groups(records, notes, source_graph)
    result = {}
    for record in records:
        eid, sid = record["evidence_id"], record["source_id"]
        ev, source = record["evidence"], record["source"]
        group = groups[sid]
        if ev["extraction_method"].startswith("csv"):
            group += ":record:" + (ev.get("row_identifier") or record["locator"])
        elif source["source_type"] == "internal_communication":
            # Blocks in one communication share an origin; a log is only a container.
            group += ":entry:" + record["locator"].split("#block:")[0]
        result[eid] = group
    return result


def _attach_source_context(connection, records):
    """Freeze same-source scope and exceptions with their exact evidence references."""
    catalog = evidence_catalog(connection)
    for record in records:
        record["source_context"] = [
            {key: item["evidence"][key] for key in ("evidence_id", "source_id", "locator", "text")}
            for item in catalog.values()
            if item["source"]["source_id"] == record["source_id"]
            and item["source"]["source_type"] in {"policy", "procedure"}
            and (
                " > " not in item["evidence"]["locator"]
                or "Exceptions" in item["evidence"]["locator"]
            )
            and item["evidence"]["evidence_id"] != record["evidence_id"]
        ]


TARGET_TITLES = {
    "prescribed_rule": "Written rules",
    "actual_practice": "Reported practice",
    "recorded_state": "Recorded events",
}


def _reason_run(run, notes, *, removed_group=None, threshold=0.5):
    """Use the same reasoner per target; cross-target differences are not conflicts."""
    options = {"removed_group": removed_group, "threshold": threshold}
    selected = run["claim"].get("evidence_target")
    result = _reason_target(run, notes, **options)
    findings = {}
    for target, title in TARGET_TITLES.items():
        scoped_notes = {}
        for eid, note in notes.items():
            scoped = note.get("target_findings", {}).get(target)
            if scoped is None:
                scoped = json.loads(json.dumps(note))
                # A human judgement applies to its reviewed target, not every target.
                if selected and selected != target and scoped["link"]["relationship"]:
                    scoped["link"].update(relationship="contextual", target_match=True)
            scoped_notes[eid] = scoped
        scoped_run = {**run, "claim": {**run["claim"], "evidence_target": target}}
        finding = _reason_target(scoped_run, scoped_notes, **options)
        finding["title"] = title
        finding["review_snapshot"] = scoped_notes
        findings[target] = finding
    unclassified = {item["evidence_id"]: item for item in result["unclassified_evidence"]}
    for finding in findings.values():
        for item in finding["unclassified_evidence"]:
            unclassified.setdefault(item["evidence_id"], item)
    result["unclassified_evidence"] = list(unclassified.values())
    result["classification_status"] = "incomplete" if unclassified else "complete"
    if selected is None:
        # Keep provenance and the submitted claim, but derive the verdict exclusively
        # from comparisons within each target. No cross-target vote counting.
        outcomes = {f["outcome"] for f in findings.values()} - {"Insufficient evidence"}
        result["outcome"] = (
            "Contested"
            if "Contested" in outcomes
            else "Mixed findings"
            if len(outcomes) > 1
            else next(iter(outcomes), "Insufficient evidence")
        )
        result["confidence"] = "Lower confidence"
        result["explanation"] = (
            "; ".join(f"{f['title']}: {f['outcome'].lower()}" for f in findings.values()) + "."
        )
        result["rules_applied"] = [
            {**trace, "assessment_target": target}
            for target, finding in findings.items()
            for trace in finding["rules_applied"]
        ]
        used = set()
        for key in ("supporting_evidence", "contradicting_evidence", "qualifying_evidence"):
            result[key] = [
                {**item, "assessment_target": target}
                for target, finding in findings.items()
                for item in finding[key]
            ]
            used.update(item["evidence_id"] for item in result[key])
        for key in ("contextual_evidence", "not_applicable_evidence", "dependent_evidence_groups"):
            result[key] = [item for item in result[key] if item["evidence_id"] not in used]
        result["material_exclusions"] = [
            item for item in result["material_exclusions"] if item["evidence_id"] not in used
        ]
        result["risk_flags"] = [f for f in result["risk_flags"] if f["kind"] != "contested_claim"]
        result["risk_flags"].extend(
            {**flag, "assessment_target": target}
            for target, finding in findings.items()
            for flag in finding["risk_flags"]
            if flag["kind"] == "contested_claim"
        )
    rule, practice = findings["prescribed_rule"], findings["actual_practice"]
    divergence = {rule["outcome"], practice["outcome"]} == {"Supported", "Contradicted"}
    result["policy_practice_divergence"] = []
    if divergence:
        explanation = (
            "Written rules and reported practice differ for this claim within the cited scopes. "
            "A report of practice does not amend a written rule; these are different assessment "
            "targets, not a direct logical contradiction."
        )
        result["policy_practice_divergence"].append(explanation)
        result["explanation"] += " " + explanation
        result["risk_flags"].append(
            {
                "kind": "policy_practice_divergence",
                "reason": explanation,
                "evidence_ids": list(
                    dict.fromkeys(
                        i["evidence_id"]
                        for f in (rule, practice)
                        for key in ("supporting_evidence", "contradicting_evidence")
                        for i in f[key]
                    )
                ),
                "basis": "separate_target_assessments",
            }
        )
    coverage = run["receipt"].get("coverage", "Bounded evidence packet.")
    result["limitations"] = list(dict.fromkeys([coverage, *result["limitations"]]))
    if len(run["packet"]["results"]) >= run["packet"].get("limit", 50):
        result["limitations"].append(
            "The retrieval limit was reached; additional candidates may not have been retrieved or assessed."
        )
    if result["unclassified_evidence"]:
        result["confidence"] = "Lower confidence"
        result["explanation"] += (
            " Coverage is incomplete: the classifier could not assess "
            f"{len(result['unclassified_evidence'])} retrieved candidates. "
            "The verdict is provisional; unassessed evidence could change it."
        )
    result["target_findings"] = findings
    result["interpretation_provenance"] = run.get("interpretation_provenance", {})
    result["run_id"] = run["run_id"]
    result["entry_id"] = run["entry_id"]
    result["evidence_dispositions"] = evidence_dispositions(result)
    return result


def _reason_target(run, notes, *, removed_group=None, threshold=0.5):
    claim = AtomicClaim.model_validate(run["claim"])
    records = run["packet"]["results"]
    groups = _evidence_groups(records, notes, run["source_graph"])
    sources = {sid: Source.model_validate(source) for sid, source in run["source_graph"].items()}
    start = claim.applicable_start_date or date.fromisoformat(run["as_of"])
    end = claim.applicable_end_date or start
    reviewed, extra_excluded, gaps, risk_flags, settlements, roles = [], [], [], [], [], []
    unclassified, limitations = [], []
    for record in records:
        eid = record["evidence_id"]
        note = notes[eid]
        classification = note.get("classification", {})
        limitations.extend(classification.get("limitations", []))
        if (
            note["link"]["method"] == "automatic"
            and classification.get("status") == "unclassified"
        ):
            unclassified.append(
                {
                    "evidence_id": eid,
                    "source_id": record["source_id"],
                    "locator": record["locator"],
                    "relationship": None,
                    "reason": classification["reason"],
                    "failure_kind": classification.get("failure_kind", "unsupported_comparison"),
                }
            )
            continue
        link = ClaimEvidenceLink.model_validate(note["link"])
        credibility = CredibilityAssessment.model_validate(note["credibility"])
        source = sources[record["source_id"]]
        evidence = Evidence.model_validate(record["evidence"])
        group = groups[eid]
        if group == removed_group:
            extra_excluded.append(
                {**record, "exclusion_reason": f"Temporary sensitivity removal: {group}"}
            )
            continue
        temporal = link.temporal_match
        reasons = []
        constraint, metadata_reasons = metadata_constraint(
            source.model_dump(mode="json"), start, end
        )
        if constraint is not None:
            temporal = False
            reasons.extend(metadata_reasons)
        if source.creation_date and source.creation_date > date.fromisoformat(run["as_of"]):
            temporal = False
            reasons.append("Source was created after the assessment-as-of snapshot")
        if source.effective_start_date and source.effective_start_date > start:
            temporal = False
            reasons.append("Source was not yet effective at the claim date")
        expiry = source.effective_end_date
        successor = sources.get(source.successor_source_id)
        if successor and successor.effective_start_date and successor.effective_start_date <= end:
            temporal = False
            reasons.append("Explicit successor was effective at the claim date")
        if expiry and expiry < end:
            temporal = False
            reasons.append("Source effective period ended before the claim period")
        historical_ok = bool(
            (source.effective_start_date is None or source.effective_start_date <= start)
            and (
                (expiry and end <= expiry)
                or (source.superseded_date and end < source.superseded_date)
                or (
                    successor
                    and successor.effective_start_date
                    and end < successor.effective_start_date
                )
            )
        )
        if source.lifecycle_status == "superseded" and not historical_ok:
            reasons.append(
                "Superseded source lacks a verified effective interval covering the claim"
            )
        if (
            not source.effective_start_date
            and credibility.evidence_mode == EvidenceMode.FORMAL_RULE
            and link.relationship != EvidenceRelationship.CONTEXTUAL
            and not note["temporal_basis"].strip()
        ):
            temporal = False
            reasons.append("No effective date or reviewed temporal applicability basis")
        if evidence.relevant_start_date and evidence.relevant_start_date > end:
            temporal = False
            reasons.append("Evidence event occurs after the assessed period")
        if (
            evidence.relevant_end_date
            and evidence.relevant_end_date < start
            and claim.evidence_target != EvidenceTarget.PRESCRIBED_RULE
        ):
            temporal = False
            reasons.append("Evidence event falls outside the assessed period")
        mode_mismatch = (
            claim.evidence_target
            in {EvidenceTarget.ACTUAL_PRACTICE, EvidenceTarget.RECORDED_STATE}
            and credibility.evidence_mode == EvidenceMode.FORMAL_RULE
        ) or (
            claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE
            and credibility.evidence_mode == EvidenceMode.OBSERVED_PRACTICE
            and link.relationship == EvidenceRelationship.SUPPORT
        )
        if mode_mismatch:
            reasons.append("Evidence describes a different knowledge target")
        # Populated fields are evidence of recorded state only; factual corrections need review.
        record_only = source.source_type in {
            "crm_records",
            "task_records",
            "audit_logs",
            "crm",
            "crm_export",
            "task_record",
            "audit_log",
            "operational_record",
            "structured_data",
        } or evidence.extraction_method.startswith("csv")
        corroborated = note["intended_value_confirmed"] and any(
            other["evidence_id"] in note.get("corroborating_evidence_ids", [])
            and groups[other["evidence_id"]] != group
            and notes[other["evidence_id"]]["link"]["review_status"] == "complete"
            and notes[other["evidence_id"]]["link"]["target_match"]
            and notes[other["evidence_id"]]["link"]["relationship"] == link.relationship.value
            and notes[other["evidence_id"]]["credibility"]["evidence_mode"] == "observed_practice"
            for other in records
        )
        if (
            record_only
            and claim.evidence_target != EvidenceTarget.RECORDED_STATE
            and credibility.evidence_mode != EvidenceMode.FORMAL_RULE
            and not corroborated
            and link.relationship != EvidenceRelationship.CONTEXTUAL
        ):
            mode_mismatch = True
            reasons.append("Recorded value alone does not establish actual or intended state")
        item = ReviewedEvidence(
            evidence_id=eid,
            source_id=source.source_id,
            locator=evidence.locator,
            relationship=link.relationship,
            target_match=link.target_match and not mode_mismatch,
            scope_match=link.scope_match,
            condition_match=link.condition_match,
            temporal_match=temporal,
            credibility=credibility,
            duplicate_group=group,
            lifecycle_status=source.lifecycle_status,
            superseded_is_temporally_justified=historical_ok,
            policy_practice_violation="policy_practice_divergence" in note["risks"],
        )
        reviewed.append(item)
        if reasons:
            extra_excluded.append({**record, "exclusion_reason": "; ".join(reasons)})
        for gap in note["gaps"]:
            gaps.append(f"{eid}: {gap}")
        if note["settlement"]:
            settlements.append({"evidence_id": eid, "text": note["settlement"]})
        if (
            note["responsible_role"]
            and temporal
            and link.target_match
            and link.scope_match
            and link.condition_match
            and not mode_mismatch
            and (source.lifecycle_status != "superseded" or historical_ok)
        ):
            roles.append(
                {"evidence_id": eid, "role": note["responsible_role"], "quote": note["role_quote"]}
            )
        for risk in note["risks"]:
            risk_flags.append(
                {
                    "kind": risk,
                    "evidence_ids": [eid],
                    "reason": note["risk_reason"],
                    "basis": note["link"]["method"],
                }
            )
    receipt = run["receipt"]
    if receipt.get("gaps"):
        gaps.extend(receipt["gaps"])
    if not records:
        gaps.append(
            "No relevant evidence retrieved in the bounded search; this does not establish that no evidence exists in the corpus."
        )
    if receipt.get("settlement"):
        settlements.append({"evidence_id": None, "text": receipt["settlement"]})
    reasoning = assess_claim(
        reviewed,
        expected_evidence_gaps=list(dict.fromkeys(gaps)),
        evidence_target=claim.evidence_target,
        config=ReasoningConfig(materiality_threshold=threshold),
    )
    result = to_assessment_result(
        claim,
        reasoning,
        query=claim.claim_text,
        runtime_metadata={
            "workflow": "claim-first-1",
            "assessment_kind": run.get("assessment_kind", "human_review"),
            "system_run_id": run.get("system_run_id"),
            "parent_run_id": run.get("parent_run_id"),
            "ruleset_version": "deterministic_v1",
            "as_of": run["as_of"],
            "reviewer": run["reviewer"],
            "corpus_fingerprint": run["corpus_fingerprint"],
            "ledger_revision": run["ledger_revision"],
            "retrieval_method": run["packet"]["method"],
            "semantic_status": run["packet"]["semantic_status"],
            "llm_used": False,
            "review_receipt": receipt,
            "temporary_scenario": bool(removed_group or threshold != 0.5),
        },
    ).model_dump(mode="json")
    result["unclassified_evidence"] = unclassified
    result["classification_status"] = "incomplete" if unclassified else "complete"
    if unclassified:
        limitations.append(
            f"Classification could not complete for {len(unclassified)} retrieved candidates. Their relationships remain unclassified; this does not mean the evidence is absent."
        )
    for record in records:
        note = notes[record["evidence_id"]]
        if (
            note["link"]["relationship"] == "contextual"
            and not record["source"].get("effective_start_date")
            and record["source"]["source_type"] in {"policy", "procedure"}
        ):
            limitations.append(
                record["source"]["title"]
                + ": no effective date is recorded; retained as process context, not an independently effective rule."
            )
    result["limitations"] = list(dict.fromkeys(limitations))
    result["diagnostic_explanation"] = result["explanation"]
    result["explanation"] = {
        "Supported": "Applicable evidence supports the proposition within the cited scope; no material applicable contradiction was established.",
        "Contradicted": "Applicable evidence contradicts the proposition; no material applicable support was established.",
        "Contested": "Material applicable support and contradiction coexist.",
        "Insufficient evidence": "The completed comparisons do not establish a decisive verdict."
        if unclassified
        else "The assessed packet contains no decisive applicable support or contradiction.",
    }[result["outcome"]]
    if unclassified:
        result["explanation"] += (
            f" {len(unclassified)} candidates remain unclassified because the classifier could not assess them."
        )
    if (
        result["outcome"] == "Insufficient evidence"
        and records
        and not unclassified
        and not result["evidence_gaps"]
    ):
        result["evidence_gaps"] = [
            "No decisive applicable evidence was established in the assessed packet; the bounded search does not prove corpus-wide absence."
        ]
    excluded_reasons = {item["evidence_id"]: item["exclusion_reason"] for item in extra_excluded}
    for item in result["not_applicable_evidence"]:
        note = notes[item["evidence_id"]]
        item["exclusion_reason"] = (
            note["link"]["applicability_reason"]
            if note["link"]["relationship"] == "not_applicable"
            else excluded_reasons.get(item["evidence_id"], note["link"]["applicability_reason"])
        )
    if reasoning.outcome.value == "Contested":
        risk_flags.append(
            {
                "kind": "contested_claim",
                "evidence_ids": [
                    r.evidence_id
                    for r in reasoning.applicable
                    if r.relationship
                    in {EvidenceRelationship.SUPPORT, EvidenceRelationship.CONTRADICT}
                ],
                "reason": "Material applicable support and contradiction coexist",
                "basis": "deterministic_reasoner",
            }
        )
    grouped = {}
    for record in records:
        grouped.setdefault(groups[record["evidence_id"]], []).append(record["evidence_id"])
    for group, eids in grouped.items():
        if len(eids) > 1:
            risk_flags.append(
                {
                    "kind": "source_dependence",
                    "evidence_ids": eids,
                    "reason": f"These evidence units share origin group {group}; repetitions are not independent votes",
                    "basis": "provenance",
                }
            )
    if receipt.get("gaps") and records:
        risk_flags.append(
            {
                "kind": "evidence_gap",
                "evidence_ids": [r["evidence_id"] for r in records],
                "reason": "; ".join(receipt["gaps"]),
                "basis": "reviewed_packet_coverage",
            }
        )
    for eid, note in notes.items():
        if note["gaps"]:
            risk_flags.append(
                {
                    "kind": "evidence_gap",
                    "evidence_ids": [eid],
                    "reason": "; ".join(note["gaps"]),
                    "basis": note["link"]["method"],
                }
            )
    divergence_ids = {
        item.evidence_id
        for item in reasoning.applicable
        if claim.evidence_target == EvidenceTarget.PRESCRIBED_RULE
        and item.credibility.evidence_mode == EvidenceMode.OBSERVED_PRACTICE
        and item.relationship == EvidenceRelationship.CONTRADICT
    }
    result["divergence_evidence"] = [
        item for item in result["contradicting_evidence"] if item["evidence_id"] in divergence_ids
    ]
    result["contradicting_evidence"] = [
        item
        for item in result["contradicting_evidence"]
        if item["evidence_id"] not in divergence_ids
    ]
    result.update(
        claim=run["claim"],
        original_wording=run["submission_original"],
        as_of=run["as_of"],
        assessed_period={"start": start.isoformat(), "end": end.isoformat()},
        evidence_records=records,
        material_exclusions=extra_excluded,
        source_groups=grouped,
        dependence_note="Documented copies and derivations share origin groups. Separate CSV records and communications entries are not duplicates merely because they share a container. Dependence between remaining groups is unknown; no statistical independence is asserted.",
        risk_flags=risk_flags,
        settlements=settlements,
        responsible_roles=roles,
        next_step=(
            "Review the cited settlement requests."
            if settlements
            else "Retain the cited evidence and revisit if applicability or source versions change."
        ),
        responsibility_note="No responsible role documented in the reviewed evidence."
        if not roles
        else "Roles below were explicitly quoted and reviewed; ownership or tenure alone is not decision authority.",
    )
    result["evidence_dispositions"] = evidence_dispositions(result)
    return result


def complete_review(
    connection, run_id, *, rationale: str, gaps=None, settlement="", meaning_confirmed=False
) -> dict:
    run = _editable_run(connection, run_id)
    if not rationale.strip() or not meaning_confirmed:
        raise ValueError(
            "Explicit review completion and confirmation of preserved claim meaning are required"
        )
    notes = review_notes(connection, run_id)
    ids = {r["evidence_id"] for r in run["packet"]["results"]}
    if ids != set(notes) or any(
        n["link"]["review_status"] != "complete" or n["link"]["method"] != "human_review"
        for n in notes.values()
    ):
        raise ValueError(
            "Every candidate needs completed human review; proposed or absent links cannot complete assessment"
        )
    if (gaps or not ids) and not settlement.strip():
        raise ValueError("Describe what additional information would settle the gap")
    run["receipt"] = {
        "rationale": rationale,
        "gaps": gaps or [],
        "settlement": settlement,
        "meaning_confirmed": True,
        "reviewed_ids": sorted(ids),
        "notes_digest": _digest(notes),
        "reviewer": run["reviewer"],
        "coverage": "Bounded candidate packet, including reviewer additions; not an exhaustive corpus audit",
    }
    result = _reason_run(run, notes)
    if result["outcome"] in {"Contested", "Insufficient evidence"} and not result["settlements"]:
        raise ValueError("Describe what additional evidence would settle this unresolved claim")
    if result["outcome"] == "Insufficient evidence" and not result["evidence_gaps"]:
        run["receipt"]["gaps"] = [
            "Completed review found no decisive applicable evidence in this packet; this is not evidence of corpus-wide absence."
        ]
        result = _reason_run(run, notes)
    # Notes and receipt are captured in the immutable snapshot for reproducible sensitivity.
    result["review_snapshot"] = notes
    from decidr.assessment_snapshot import build_presentation

    result["presentation"] = build_presentation(result)
    result["assessed_at"] = datetime.now(UTC).isoformat()
    _save_run_payload(connection, run)
    connection.execute(
        "UPDATE employee_review_runs SET status='completed_assessment',result_json=? WHERE run_id=?",
        (json.dumps(result), run_id),
    )
    connection.execute(
        "UPDATE employee_claims SET status='completed_assessment' WHERE entry_id=?",
        (run["entry_id"],),
    )
    record_audit(
        connection,
        actor=run["reviewer"],
        action="claim_assessment_completed",
        entity_type="employee_review_run",
        entity_id=run_id,
        changed_fields={"receipt": run["receipt"], "result_digest": _digest(result)},
    )
    return result


def sensitivity(connection, run_id, *, remove_group=None, materiality_threshold=0.5) -> dict:
    """Read-only replay of the same reviewed snapshot and reasoner."""
    run = get_run(connection, run_id)
    if run["status"] != "completed_assessment":
        raise ValueError("Sensitivity requires a completed baseline")
    if materiality_threshold not in {0.4, 0.5, 0.6}:
        raise ValueError("Allowed materiality assumptions are 0.4, 0.5 and 0.6")
    if remove_group is not None and remove_group not in run["result"]["source_groups"]:
        raise ValueError("Choose an existing source group")
    alternative = _reason_run(
        run,
        run["result"]["review_snapshot"],
        removed_group=remove_group,
        threshold=materiality_threshold,
    )
    explanation = {
        "Mixed findings": "Findings differ across assessment targets; inspect each scoped finding.",
        "Supported": "Applicable material support remains without material contradiction.",
        "Contradicted": "Applicable material contradiction remains without material support.",
        "Contested": "Applicable material support and contradiction both remain.",
        "Insufficient evidence": "No decisive applicable evidence remains under this scenario.",
    }[alternative["outcome"]]
    return {
        "baseline": {k: run["result"][k] for k in ("outcome", "confidence")},
        "alternative": {k: alternative[k] for k in ("outcome", "confidence")},
        "reason": f"{explanation} Same reviewed snapshot and reasoner; removed group={remove_group or 'none'}, materiality threshold={materiality_threshold}. Confidence is qualitative, not calibrated probability.",
        "rules_applied": alternative["rules_applied"],
        "temporary": True,
    }


def knowledge_risks(connection) -> dict:
    register = entries(connection)
    all_runs = runs(connection)
    latest = {}
    for run in all_runs:
        if run["status"] == "completed_assessment":
            latest[run["entry_id"]] = run
    flags = []
    for entry_id, run in latest.items():
        for flag in run["result"]["risk_flags"]:
            if flag["evidence_ids"]:
                flags.append(
                    {
                        **flag,
                        "entry_id": entry_id,
                        "run_id": run["run_id"],
                        "claim": run["claim"]["claim_text"],
                    }
                )
    return {
        "flags": flags,
        "registered_claims": len(register),
        "assessed_claims": len(latest),
        "pending_claims": [e for e in register if e["status"] != "completed_assessment"],
        "pending_reviews": [
            r["run_id"] for r in all_runs if r["status"] != "completed_assessment"
        ],
        "coverage": "Latest completed assessment per employee claim; flags are review findings, not confirmed breaches. Bounded retrieval does not audit all transactions.",
    }


def _save_assessment_snapshot(connection, run, notes):
    """Persist a completed system or corrected snapshot, never a human approval proxy."""
    result = _reason_run(run, notes)
    result["review_snapshot"] = notes
    from decidr.assessment_snapshot import build_presentation

    result["presentation"] = build_presentation(result)
    result["assessed_at"] = datetime.now(UTC).isoformat()
    result["review_status"] = (
        "Not yet reviewed"
        if run["assessment_kind"] == "system"
        else "Human reviewed"
        if all(n["link"]["method"] == "human_review" for n in notes.values())
        else "Partially reviewed"
    )
    result["assessment_kind"] = run["assessment_kind"]
    _save_run_payload(connection, run)
    connection.execute(
        "UPDATE employee_review_runs SET status='completed_assessment',result_json=? WHERE run_id=?",
        (json.dumps(result), run["run_id"]),
    )
    connection.execute(
        "UPDATE employee_claims SET status='completed_assessment' WHERE entry_id=?",
        (run["entry_id"],),
    )
    record_audit(
        connection,
        actor=run["reviewer"],
        action="employee_" + run["assessment_kind"] + "_assessment",
        entity_type="employee_review_run",
        entity_id=run["run_id"],
        changed_fields={
            "parent_run_id": run.get("parent_run_id"),
            "system_run_id": run["system_run_id"],
            "result_digest": _digest(result),
            "changes": run.get("changes", {}),
        },
    )
    return get_run(connection, run["run_id"])


def ensure_system_assessment(connection, entry_id):
    """Resume saved pending claims and idempotently produce an immutable system verdict."""
    existing = runs(connection, entry_id)
    system = next((r for r in existing if r.get("assessment_kind") == "system"), None)
    if system:
        return system
    entry = get_entry(connection, entry_id)
    if entry["status"] == "completed_assessment":
        # Historical human-only assessments retain their actual provenance.
        return next(r for r in reversed(existing) if r["status"] == "completed_assessment")
    if entry["status"] == "awaiting_clarification":
        old = IntakePart.model_validate(entry["intake"])
        # Upgrade legacy category gates without changing completed snapshots or
        # discarding any responses. Unknown clarifications still need resolution.
        from decidr.conversation import _target

        legacy_target = (old.clarification or "").startswith("Is this about") or (
            old.provenance.get("clarification_kind") == "evidence_target"
        )
        responses = [_target(text) for text in entry["clarifications"]]
        if responses and (not legacy_target or not all(responses)):
            return None
        part = contextual_intake(
            connection, old.text, target=responses[-1] if responses else None
        ).parts[0]
        if not part.claim:
            if part.model_dump(mode="json") != entry["intake"]:
                entry["intake"] = part.model_dump(mode="json")
                _update_entry(connection, entry_id, entry)
                record_audit(
                    connection,
                    actor="system",
                    action="pending_interpretation_updated",
                    entity_type="employee_claim",
                    entity_id=entry_id,
                    changed_fields={
                        "previous_intake": old.model_dump(mode="json"),
                        "intake": entry["intake"],
                    },
                )
            return None
        part.claim.original_claim_text = entry["original_wording"]
        save_claim(connection, part.claim)
        entry["intake"] = part.model_dump(mode="json")
        _update_entry(connection, entry_id, entry)
        connection.execute(
            "UPDATE employee_claims SET claim_id=?,status=? WHERE entry_id=?",
            (part.claim.claim_id, part.status, entry_id),
        )
        record_audit(
            connection,
            actor="system",
            action="pending_interpretation_resolved",
            entity_type="employee_claim",
            entity_id=entry_id,
            changed_fields={
                "previous_intake": old.model_dump(mode="json"),
                "intake": entry["intake"],
            },
        )
    state = corpus_state(connection)
    as_of = (
        date.fromisoformat(state["snapshot_date"])
        if state["snapshot_date"]
        else datetime.now(UTC).date()
    )
    run_id = begin_review(connection, entry_id, "system:" + CLASSIFIER_VERSION, as_of)
    run = get_run(connection, run_id)
    run.update(assessment_kind="system", system_run_id=run_id)
    _attach_source_context(connection, run["packet"]["results"])
    claim = AtomicClaim.model_validate(run["claim"])
    notes = {
        r["evidence_id"]: classify_evidence(claim, r, run_id) for r in run["packet"]["results"]
    }
    run["receipt"] = {
        "classifier_version": CLASSIFIER_VERSION,
        "meaning_basis": "resolved_intake",
        "human_reviewed_ids": [],
        "notes_digest": _digest(notes),
        "gaps": [],
        "settlement": "Inspect the cited classifications and source versions; supply applicable evidence or correct a relationship if the claim remains unresolved.",
        "coverage": "Bounded lexical retrieval and explicit source provenance expansion; not a corpus-wide audit.",
        "date_basis": state["date_basis"]
        if state["snapshot_date"]
        else "Today's date; no eligible source creation date is recorded.",
    }
    return _save_assessment_snapshot(connection, run, notes)


def refresh_system_assessment(connection, baseline_run_id):
    """Append a new automatic assessment of a frozen packet, preserving every prior run."""
    baseline = get_run(connection, baseline_run_id)
    if baseline["status"] != "completed_assessment":
        raise ValueError("Complete the baseline assessment first")
    state = corpus_state(connection)
    if state["ledger_revision"] != baseline["ledger_revision"]:
        raise ValueError(
            "The source ledger changed; submit a new claim assessment to retrieve current evidence"
        )
    run = json.loads(json.dumps(baseline))
    run.pop("changes", None)
    run_id = "RUN-" + uuid4().hex[:16]
    run.update(
        run_id=run_id,
        assessment_kind="system",
        system_run_id=run_id,
        parent_run_id=baseline_run_id,
        reviewer="system:" + CLASSIFIER_VERSION,
        status="in_review",
        result=None,
    )
    _attach_source_context(connection, run["packet"]["results"])
    claim = AtomicClaim.model_validate(run["claim"])
    notes = {
        record["evidence_id"]: classify_evidence(claim, record, run_id)
        for record in run["packet"]["results"]
    }
    run["receipt"] = {
        "classifier_version": CLASSIFIER_VERSION,
        "gaps": [],
        "settlement": "Inspect unclassified passages or supply scoped evidence if the assessment remains unresolved.",
        "notes_digest": _digest(notes),
        "human_reviewed_ids": [],
        "coverage": "Reclassified frozen retrieval packet with same-source scope and exceptions; no prior assessment changed.",
    }
    connection.execute("SAVEPOINT automatic_reassessment")
    try:
        connection.execute(
            "INSERT INTO employee_review_runs(run_id,entry_id,reviewer,status,payload_json) VALUES(?,?,?,?,?)",
            (run_id, run["entry_id"], run["reviewer"], run["status"], "{}"),
        )
        result = _save_assessment_snapshot(connection, run, notes)
        connection.execute("RELEASE automatic_reassessment")
        return result
    except Exception:
        connection.execute("ROLLBACK TO automatic_reassessment")
        connection.execute("RELEASE automatic_reassessment")
        raise


def reassess_evidence(
    connection, baseline_run_id, evidence_id, *, reviewer, rationale, **judgement
):
    """One explicit human correction creates a new result on the original evidence snapshot.

    Unchanged evidence retains its actual automatic/human provenance. Only the
    changed unit is recorded in the human review ledger for this new run.
    """
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("Enter your reviewer name and explain this confirmation or correction.")
    baseline = get_run(connection, baseline_run_id)
    if baseline["status"] != "completed_assessment" or not baseline.get("system_run_id"):
        raise ValueError("Produce a system assessment before correcting evidence.")
    if corpus_state(connection)["ledger_revision"] != baseline["ledger_revision"]:
        raise ValueError(
            "The source ledger changed since this assessment. Restore its evidence snapshot before saving corrections; the original assessment remains available."
        )
    if evidence_id not in baseline["result"]["review_snapshot"]:
        raise ValueError("Choose evidence from this assessment.")
    run_id = "RUN-" + uuid4().hex[:16]
    run = {k: v for k, v in baseline.items() if k not in {"result", "status"}}
    run.update(
        run_id=run_id,
        reviewer=reviewer,
        assessment_kind="human_reassessment",
        parent_run_id=baseline_run_id,
        status="awaiting_evidence_review",
    )
    payload = {
        k: v for k, v in run.items() if k not in {"run_id", "entry_id", "reviewer", "status"}
    }
    # A failed correction must not leave a half-created run when callers handle errors.
    connection.execute("SAVEPOINT human_reassessment")
    try:
        connection.execute(
            "INSERT INTO employee_review_runs VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (run_id, run["entry_id"], reviewer, run["status"], json.dumps(payload), None),
        )
        review_evidence(connection, run_id, evidence_id, **judgement)
        notes = {**baseline["result"]["review_snapshot"], **review_notes(connection, run_id)}
        if notes[evidence_id]["link"]["method"] != "human_review":
            raise ValueError(
                "Save a completed human judgement to reassess; a proposal cannot change the verdict."
            )
        run["changes"] = {
            "evidence_id": evidence_id,
            "rationale": rationale,
            "before": baseline["result"]["review_snapshot"][evidence_id],
            "after": notes[evidence_id],
        }
        run["receipt"] = {
            **baseline["receipt"],
            "rationale": rationale,
            "human_reviewed_ids": [
                eid for eid, n in notes.items() if n["link"]["method"] == "human_review"
            ],
            "notes_digest": _digest(notes),
        }
        result = _save_assessment_snapshot(connection, run, notes)
        connection.execute("RELEASE human_reassessment")
        return result
    except Exception:
        connection.execute("ROLLBACK TO human_reassessment")
        connection.execute("RELEASE human_reassessment")
        raise
