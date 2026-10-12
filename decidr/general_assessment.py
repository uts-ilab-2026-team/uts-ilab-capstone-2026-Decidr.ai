"""Snapshot-bound retrieval, semantic assessment and canonical response projection."""

from collections import defaultdict
from contextlib import closing
from itertools import zip_longest
import json
import re
import sqlite3
import time

from decidr.assessment_history import content_hash
from decidr.canonical_assessment import (
    CONFIDENCE_METHOD,
    SCHEMA_VERSION,
    WEIGHTS,
    canonical_assessment,
    processing_failure,
)
from decidr.claim_interpreter import (
    ProviderError,
    evaluate_evidence,
    evidence_input_budget,
    get_provider,
    interpret_claim,
)
from decidr.hybrid import search_corpus
from decidr.practice_assessment import assess_practice
from decidr.retrieval import find_record_references, record_identifiers
from decidr.retrieval_models import Evidence, Source
from decidr.retrieval_store import SCHEMA, replace_source_evidence, upsert_source
from decidr.transaction_claims import assess_transaction_claim

METHOD = "general-claim-assessment-v1"
TARGETS = {
    "formal_requirement": "formal_rule",
    "formal_authority": "formal_rule",
    "reported_statement": "recorded_statement",
}
MAX_PASSAGES = 36
MAX_CHARACTERS = 50000


def _retrieve(operation, *args, **kwargs):
    """Keep retrieval data errors distinct from claim or evidence uncertainty."""
    try:
        return operation(*args, **kwargs)
    except (ValueError, sqlite3.Error, OSError) as error:
        raise ProviderError(
            "retrieval_failure",
            "Evidence retrieval could not complete. Check the corpus data and index.",
        ) from error


def read_snapshot(path):
    if path is None:
        raise ProviderError("retrieval_failure", "The corpus database is not configured.")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            sources = {
                s.source_id: s
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM sources ORDER BY source_id"
                )
                if (s := Source.model_validate_json(raw))
            }
            evidence = {
                e.evidence_id: e
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM evidence ORDER BY evidence_id"
                )
                if (e := Evidence.model_validate_json(raw))
            }
    except (OSError, sqlite3.Error, ValueError) as error:
        raise ProviderError(
            "retrieval_failure",
            "The corpus snapshot could not be read. Check the corpus configuration and schema.",
        ) from error
    if not sources or not evidence:
        raise ProviderError("empty_corpus", "The corpus contains no indexed evidence to assess.")
    return sources, evidence


def snapshot_index(sources, evidence):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    groups = defaultdict(list)
    for passage in evidence.values():
        groups[passage.source_id].append(passage)
    for source in sources.values():
        upsert_source(connection, source)
        replace_source_evidence(connection, source.source_id, groups[source.source_id])
    return connection


def retrieve_context(
    connection, claim, interpretation, sources, evidence, *, questions=(), exclude=()
):
    """One bounded expansion over the same frozen index, never a second corpus version."""
    queries = list(
        dict.fromkeys(
            [
                claim,
                *questions[:2],
                *interpretation.get("search_queries", [])[:3],
                *(c["text"] for c in interpretation.get("components", [])[:4]),
            ]
        )
    )
    seeds, candidates, reasons, ranks = [], set(), {}, {}
    practice_target = interpretation.get("target") in {"observed_practice", "current_state"}
    group_limit = 12 if questions or practice_target else 8
    for query in queries:
        result = search_corpus(connection, query, limit=group_limit)
        candidates.update(item.evidence_id for item in result.candidates)
        for item in result.candidates:
            rank = getattr(item, "rank", len(evidence))
            ranks[item.evidence_id] = min(rank, ranks.get(item.evidence_id, rank))
        for group in (*result.ranked_groups, *result.additional_linked_groups):
            lead_id = getattr(getattr(group, "lead_result", None), "evidence_id", None)
            for passage in sorted(group.passages, key=lambda p: p.evidence_id != lead_id):
                if passage.evidence_id not in seeds:
                    seeds.append(passage.evidence_id)
                    reasons[passage.evidence_id] = "retrieved_for_claim_or_component"
    by_source = defaultdict(list)
    for passage in evidence.values():
        by_source[passage.source_id].append(passage)
    seed_groups = defaultdict(list)
    for eid in seeds:
        seed_groups[evidence[eid].source_id].append(eid)
    ordered, contextual_groups, headers = [], [], []

    def is_header(passage):
        source = sources[passage.source_id]
        quotes = [
            item["quote"]
            for item in source.header_evidence
            if item.get("quote") and item["quote"] in passage.text
        ]
        remainder = passage.text
        for quote in quotes:
            remainder = remainder.replace(quote, "")
        titles = {source.title, passage.heading}
        return bool(quotes) and all(
            not line.strip() or re.sub(r"^#{1,6}\s+", "", line.strip()) in titles
            for line in remainder.splitlines()
        )

    # A document reference points to that document, not every passage mentioning
    # its identifier. Its substantive passages may not repeat the document code.
    documents = defaultdict(list)
    for source in sources.values():
        names = {source.source_id.rsplit(":", 1)[-1], source.title.partition(" ")[0]}
        for name in names:
            if record_identifiers(name) == [name.upper()]:
                documents[name.upper()].append(source.source_id)
    original_groups = dict(seed_groups)
    seed_groups = {}
    document_references = set()

    def add_documents(references):
        for reference in sorted(references):
            for target in documents.get(reference, []):
                document_references.add(reference)
                if target in seed_groups:
                    continue
                passages = sorted(
                    (p for p in by_source[target] if not is_header(p)),
                    key=lambda p: (ranks.get(p.evidence_id, len(evidence)), p.locator),
                )
                seed_groups[target] = list(
                    dict.fromkeys(
                        [
                            *(p.evidence_id for p in passages[:group_limit]),
                            *original_groups.get(target, []),
                        ]
                    )
                )
                for passage in passages[:group_limit]:
                    reasons.setdefault(passage.evidence_id, "explicit_document_reference_context")

    header_references = set()
    for source_id, ids in original_groups.items():
        seed_groups.setdefault(source_id, ids)
        references = set(record_identifiers(claim))
        for passage in by_source[source_id]:
            if is_header(passage):
                header_references.update(record_identifiers(passage.text))
            elif passage.evidence_id in ids:
                references.update(record_identifiers(passage.text))
        add_documents(references)
    add_documents(header_references)
    if practice_target:
        seed_groups = dict(
            sorted(
                seed_groups.items(),
                key=lambda item: sources[item[0]].source_type in {"policy", "procedure"},
            )
        )

    def append(eid, reason):
        if eid not in ordered:
            ordered.append(eid)
        reasons.setdefault(eid, reason)

    # Keep scope and adjacent caveats with each seed. Header metadata already
    # travels with every passage; header text must not crowd out substantive seeds.
    for row in zip_longest(*seed_groups.values()):
        for eid in row:
            if eid is None:
                continue
            passage = evidence[eid]
            append(eid, "retrieved_for_claim_or_component")
            if is_header(passage):
                ordered.remove(eid)
                if eid not in headers:
                    headers.append(eid)
                continue
            section = [
                sibling
                for sibling in by_source[passage.source_id]
                if sibling.heading == passage.heading
                and sibling.section == passage.section
                and not sibling.row_identifier
                and not sibling.locator.startswith("csv:")
            ]
            for sibling in sorted(
                by_source[passage.source_id],
                key=lambda p: (p.section or p.heading or "", p.paragraph or 0, p.locator),
            ):
                if sibling.row_identifier or sibling.locator.startswith("csv:"):
                    continue
                if is_header(sibling):
                    if sibling.evidence_id not in headers:
                        headers.append(sibling.evidence_id)
                    continue
                conditions = re.search(
                    r"\b(?:scope|conditions?|exceptions?|applicability)\b",
                    sibling.heading or "",
                    re.IGNORECASE,
                )
                adjacent = (
                    sibling.heading == passage.heading
                    and sibling.section == passage.section
                    and (
                        len(section) <= 20
                        or (
                            sibling.paragraph is not None
                            and passage.paragraph is not None
                            and abs(sibling.paragraph - passage.paragraph) <= 1
                        )
                    )
                )
                if conditions or adjacent:
                    append(sibling.evidence_id, "same_source_context")

    for source_id in seed_groups:
        siblings = sorted(by_source[source_id], key=lambda p: (p.paragraph or 0, p.locator))
        if len(siblings) <= 20:
            contextual_groups.append(
                [
                    p.evidence_id
                    for p in siblings
                    if not p.row_identifier and not p.locator.startswith("csv:")
                ]
            )
    # Follow exact references from ranked evidence and its necessary context, not
    # references in unrelated optional sections of the same document.
    reference_ids = set()
    for eid in [*ordered, *headers]:
        reference_ids.update(record_identifiers(evidence[eid].text))
    for link in find_record_references(
        " ".join(sorted(reference_ids - document_references)), list(evidence.values())
    ):
        append(link.evidence_id, "explicit_record_reference_context")
    for eid in headers:
        append(eid, "same_source_context")
    for row in zip_longest(*contextual_groups):
        for eid in row:
            if eid is not None:
                append(eid, "same_source_context")
    selected, omitted, chars = [], [], 0
    for eid in ordered:
        if eid in exclude:
            continue
        p = evidence[eid]
        if len(selected) >= MAX_PASSAGES or chars + len(p.text) > MAX_CHARACTERS:
            omitted.append(eid)
            continue
        selected.append(eid)
        chars += len(p.text)
    payload = [
        {
            "evidence_id": eid,
            "source_id": evidence[eid].source_id,
            "locator": evidence[eid].locator,
            "text": evidence[eid].text,
            "heading": evidence[eid].heading,
            "source": sources[evidence[eid].source_id].model_dump(mode="json"),
        }
        for eid in selected
    ]
    return payload, {
        "queries": queries,
        "ranked_group_limit": group_limit,
        "candidate_count": len(candidates),
        "selected_passage_count": len(selected),
        "expanded_candidate_count": len(ordered),
        "omitted_passage_count": len(omitted),
        "passage_limit": MAX_PASSAGES,
        "character_limit": MAX_CHARACTERS,
        "selection_reasons": {eid: reasons.get(eid, "same_source_context") for eid in selected},
    }


def fit_model_budget(interpretation, claim, passages, as_of, provider, *, retained=()):
    """Keep whole priority-ordered passages under the actual model envelope budget."""
    selected = list(retained)
    budget = evidence_input_budget(interpretation, claim, selected, as_of, provider)
    if budget is None:
        return [*selected, *passages], None
    omitted = []
    for passage in passages:
        trial = evidence_input_budget(interpretation, claim, [*selected, passage], as_of, provider)
        if trial["fits"]:
            selected.append(passage)
            budget = trial
        else:
            omitted.append(passage["evidence_id"])
    return selected, {
        **budget,
        "candidate_passage_count": len(retained) + len(passages),
        "selected_passage_count": len(selected),
        "omitted_passage_count": len(omitted),
        "omitted_evidence_ids": omitted,
        "selection_method": "whole-passages-in-retrieval-priority-order-v1",
        "notice": "Passages omitted for the model input budget remain in the frozen corpus. Their contents were not evaluated; they may alter the assessment. No passage or source metadata was truncated.",
    }


def context_connections(selected, sources):
    """Exact references organise selected evidence; none establish a component."""
    edges = []

    def citation(passage):
        return {key: passage[key] for key in ("evidence_id", "source_id", "locator")} | {
            "quotation": passage["text"],
            "start": 0,
            "end": len(passage["text"]),
        }

    def affirmative_supersession(text):
        return any(
            re.search(r"\bsupersedes\b", clause, re.IGNORECASE)
            and not re.search(
                r"\b(not|never|no|may|might|could|proposed|draft|pending|will|would|should|if|unless)\b",
                clause,
                re.IGNORECASE,
            )
            for clause in re.split(r"[.;\n]", text)
        )

    for index, left in enumerate(selected):
        identifiers = set(record_identifiers(left["text"]))
        for right in selected[index + 1 :]:
            shared = identifiers.intersection(record_identifiers(right["text"]))
            if not shared or left["source_id"] == right["source_id"]:
                continue
            origin, destination = left, right
            relationship = "contextual_reference"
            reason = (
                "Both passages explicitly reference "
                + ", ".join(sorted(shared))
                + ". This reference is context only, not corroboration."
            )
            left_source, right_source = sources[left["source_id"]], sources[right["source_id"]]
            if left_source.predecessor_source_id == right[
                "source_id"
            ] and affirmative_supersession(left["text"]):
                relationship = "supersedes"
                reason = "Source version metadata and the quoted passage identify a predecessor. This link does not by itself establish the claim."
            elif right_source.predecessor_source_id == left[
                "source_id"
            ] and affirmative_supersession(right["text"]):
                origin, destination = right, left
                relationship = "supersedes"
                reason = "Source version metadata and the quoted passage identify a predecessor. This link does not by itself establish the claim."
            else:
                rows = []
                for passage in (left, right):
                    try:
                        row = json.loads(passage["text"])
                    except ValueError:
                        row = None
                    rows.append(row if isinstance(row, dict) else {})
                row_ids = [
                    {
                        str(value).upper()
                        for key, value in row.items()
                        if key in {"deal_id", "record_id", "related_record", "task_id"}
                    }
                    for row in rows
                ]
                if shared.intersection(*row_ids):
                    relationship = "same_record"
                    reason = "Both structured records explicitly identify the same record. The link is contextual and does not prove either record's assertions."
            edges.append(
                {
                    "from_citation": citation(origin),
                    "to_citation": citation(destination),
                    "relationship": relationship,
                    "reason": reason,
                    "inferential": False,
                }
            )
    return edges


def project_response(request, canonical, selected, sources):
    """Legacy fields are projections of the canonical result, never a second verdict."""
    canonical["context_relations"] = context_connections(selected, sources)
    target = TARGETS.get(
        (canonical.get("interpreted_claim") or {}).get("target"), "underlying_event"
    )
    failed = canonical["processing"]["status"] != "assessed"
    outcome = canonical["overall_outcome"] if not failed else "Assessment not completed"
    components = canonical.get("components", [])
    inputs, packet_inputs, scored = [], [], []
    findings = [finding for component in components for finding in component.get("findings", [])]
    for index, passage in enumerate(selected):
        relevant = [f for f in findings if f.get("evidence_id") == passage["evidence_id"]]
        active = [
            f
            for f in relevant
            if f.get("relationship") in {"supports", "contradicts", "qualifies"}
        ]
        kinds = {f.get("relationship") for f in active}
        stance = (
            "qualify"
            if len(kinds) > 1
            else {"supports": "support", "contradicts": "contradict", "qualifies": "qualify"}.get(
                next(iter(kinds), ""), "context"
            )
        )
        citations = [c for f in relevant for c in f.get("citations", [])]
        if not citations:
            citations = [
                {
                    "evidence_id": passage["evidence_id"],
                    "source_id": passage["source_id"],
                    "locator": passage["locator"],
                    "start": 0,
                    "end": len(passage["text"]),
                    "quotation": passage["text"],
                }
            ]
        reasons = [
            reason
            for f in relevant
            for reason in f.get("exclusion_reasons", f.get("limitations", []))
        ]
        rationale = (
            " ".join(dict.fromkeys(f.get("reason", "") for f in relevant))
            or "Retrieved as context; no validated material relationship to a component was established."
        )
        edge_id = f"canonical:{index}" if active and not failed else None
        suggested = {
            "stance": stance,
            "mode": "formal" if target == "formal_rule" else "observed",
            "rationale": rationale,
            "citations": citations,
            "origin_id": passage["source_id"],
            "source_class": "unknown",
            "approval_key": "unknown",
            "scope_matches": None,
            "temporal_matches": None,
            "authority_verified": None,
            "directness": None,
            "specificity": None,
            "completeness": None,
            "judgement_basis": "See validated canonical component findings and disclosed confidence factors.",
            "origin_basis": "Recorded source identity; independent origin is not assumed.",
            "independence_verified": False,
            "independence_basis": "Not independently verified.",
            "evidence_target": target,
            "target_basis": "Validated structured claim interpretation.",
        }
        packet_inputs.append(suggested)
        inputs.append(
            {
                "input_id": f"canonical-{index}",
                "interpretation": {
                    key: suggested[key] for key in ("stance", "mode", "rationale", "citations")
                },
                "source": sources[passage["source_id"]].model_dump(mode="json"),
                "supplied_judgements": suggested,
                "edge_id": edge_id,
                "admitted_to_framework": edge_id is not None,
                "reasons": reasons,
            }
        )
        if edge_id:
            scored.append(
                {
                    "edge_id": edge_id,
                    "material": True,
                    "materiality_score": None,
                    "dimensions": {},
                    "limitations": reasons,
                    "trace": [
                        "Admitted to canonical component assessment. Confidence factors are disclosed at component level; no legacy graph score was fabricated."
                    ],
                }
            )
    confidence = canonical["confidence"]
    confidence_label = confidence.get("label", "Uncalibrated assessment confidence")
    if confidence.get("score") is not None:
        confidence_label = f"{confidence['score']}/100 · {confidence_label}"
    primary = {
        "basis": "canonical_component_assessment",
        "overall_outcome": outcome,
        "formal_outcome": outcome if target == "formal_rule" else "Not the assessed target",
        "observed_outcome": outcome if target != "formal_rule" else "Not the assessed target",
        "summary": canonical["summary"],
        "confidence": confidence_label,
        "components": components,
        "evidence": scored,
        "gaps": canonical["unresolved_questions"],
        "rules_applied": [METHOD],
    }
    response = {
        "schema_version": "facet-assessment-response-v1",
        "status": "processing_failed" if failed else "assessed_automatically",
        "claim_text": request.claim,
        "facet": request.facet or request.claim,
        "as_of": request.as_of.isoformat(),
        "assessment_target": target,
        "assessment_scope": "claim_components",
        "target_validation": "structured_claim_semantic_validation",
        "interpretation_basis": "local_model_with_server_validation",
        "persisted": False,
        "index_scope": "snapshot",
        "config_version": METHOD,
        "canonical_assessment": canonical,
        "assessment": primary,
        "inputs": inputs,
        "assurance": {
            "outcome_basis": "canonical_component_assessment",
            "human_review": "not_applicable" if failed else "pending",
            "notice": "Citation-grounded assessment of the available records. Semantic validation uses the same local model and is not independent verification; human review remains available.",
        },
        "limitations": [
            "Uncalibrated assessment confidence is not the probability that the claim is true.",
            "Retrieval is bounded; unselected evidence may alter the result.",
        ],
    }
    if not failed:
        response["claim_conclusion"] = {
            "status": outcome.lower().replace(" ", "_"),
            "label": outcome,
            "summary": canonical["summary"],
            "basis": "canonical_component_assessment",
            "notice": response["assurance"]["notice"],
        }
    return response, {
        "claim_text": request.claim,
        "facet": request.facet or request.claim,
        "as_of": request.as_of.isoformat(),
        "assessment_target": target,
        "inputs": packet_inputs,
    }


def build_general_bundle(request, path):
    started = time.monotonic()
    sources, evidence, selected = {}, {}, []
    provider = None
    interpretation = None
    diagnostics = {"method": METHOD, "stages": [], "retrieval_rounds": []}
    provenance = {
        "assessment_method": METHOD,
        "evidence_scope": "bounded_selection_from_frozen_corpus",
    }
    try:
        sources, evidence = read_snapshot(path)
        provenance["corpus_index_sha256"] = content_hash(
            {
                "sources": [s.model_dump(mode="json") for s in sources.values()],
                "evidence": [e.model_dump(mode="json") for e in evidence.values()],
            }
        )
        provider = get_provider()
        provenance["provider"] = provider.provenance()
        interpretation = interpret_claim(request.facet or request.claim, request.as_of, provider)
        diagnostics["stages"].append("claim_interpretation_validated")
        interpretation["original_claim"] = request.claim
        interpretation["assessed_facet"] = request.facet or request.claim
        interpretation["requested_target"] = request.assessment_target
        inferred_target = TARGETS.get(interpretation["target"], "underlying_event")
        if (
            request.assessment_target != "unspecified"
            and request.assessment_target != inferred_target
        ):
            raise ProviderError(
                "interpretation_failure",
                "The selected assessment target conflicts with the interpreted claim. Review the selected scope and target.",
            )
        interpretation["deterministic_findings"] = {
            "transaction": assess_transaction_claim(
                request.claim, list(evidence.values()), sources, request.as_of
            ),
            "practice": assess_practice(
                request.facet or request.claim, list(evidence.values()), sources, request.as_of
            ),
        }
        with closing(_retrieve(snapshot_index, sources, evidence)) as index:
            selected, retrieval = _retrieve(
                retrieve_context,
                index,
                request.facet or request.claim,
                interpretation,
                sources,
                evidence,
            )
            diagnostics["retrieval_rounds"].append(retrieval)
            selected, budget = fit_model_budget(
                interpretation, request.facet or request.claim, selected, request.as_of, provider
            )
            if budget is not None:
                retrieval["model_input_budget"] = budget
                if not budget["fits"] or not selected:
                    raise ProviderError(
                        "unsupported_capability",
                        "No complete evidence passage fits the local model input budget with its claim, metadata and verification reserves.",
                    )
            evaluated = evaluate_evidence(
                interpretation, request.facet or request.claim, selected, request.as_of, provider
            )
            admitted = canonical_assessment(
                interpretation, evaluated, evidence, sources, request.as_of
            )
            missing = [
                c["text"]
                for c in admitted["components"]
                if c["status"] == "insufficient" or not any(f["admitted"] for f in c["findings"])
            ]
            if missing:
                additions, retrieval = _retrieve(
                    retrieve_context,
                    index,
                    request.facet or request.claim,
                    interpretation,
                    sources,
                    evidence,
                    questions=missing,
                    exclude={p["evidence_id"] for p in selected},
                )
                room = MAX_PASSAGES - len(selected)
                characters = sum(len(p["text"]) for p in selected)
                bounded = []
                for passage in additions:
                    if len(bounded) < room and characters + len(passage["text"]) <= MAX_CHARACTERS:
                        bounded.append(passage)
                        characters += len(passage["text"])
                retrieval["remaining_budget_omissions"] = len(additions) - len(bounded)
                combined, budget = fit_model_budget(
                    interpretation,
                    request.facet or request.claim,
                    bounded,
                    request.as_of,
                    provider,
                    retained=selected,
                )
                if budget is not None:
                    retrieval["model_input_budget"] = budget
                additions = combined[len(selected) :]
                retrieval["added_passage_count"] = len(additions)
                diagnostics["retrieval_rounds"].append(retrieval)
                if additions:
                    selected.extend(additions)
                    evaluated = evaluate_evidence(
                        interpretation,
                        request.facet or request.claim,
                        selected,
                        request.as_of,
                        provider,
                    )
        diagnostics["stages"].append("evidence_relations_semantically_validated")
        diagnostics["selected_passage_count"] = len(selected)
        canonical = canonical_assessment(
            interpretation,
            evaluated,
            evidence,
            sources,
            request.as_of,
            diagnostics=diagnostics,
            provenance=provenance,
        )
    except ProviderError as error:
        canonical = processing_failure(
            error.code,
            error.message,
            diagnostics=diagnostics,
            provenance=provenance,
            interpretation=interpretation,
        )
    except (sqlite3.Error, OSError):
        canonical = processing_failure(
            "retrieval_failure",
            "Evidence retrieval could not complete. No assessment was produced.",
            diagnostics=diagnostics,
            provenance=provenance,
            interpretation=interpretation,
        )
    if provider is not None:
        provenance["provider"] = provider.provenance()
        canonical["provenance"].update(provenance)
    canonical["diagnostics"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
    response, packet = project_response(request, canonical, selected, sources)
    return {
        "response": response,
        "request": packet,
        "sources": [s.model_dump(mode="json") for s in sources.values()],
        "evidence": [e.model_dump(mode="json") for e in evidence.values()],
        "configuration": {
            "assessment_method": METHOD,
            "canonical_schema_version": SCHEMA_VERSION,
            "confidence_method": CONFIDENCE_METHOD,
            "confidence_weights": dict(WEIGHTS),
        },
        "interpretation": interpretation,
        "provenance": provenance,
    }
