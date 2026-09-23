"""Phase 2 full-packet diagnostics. References never enter retrieval or assessment.

Run with python -m decidr.retrieval_benchmark --help. All outputs are append-only;
the source ledger is opened read-only and only evidence is copied to a scratch ledger.
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import zipfile

from decidr.approach_b import BoundedGraphExpander
from decidr.automatic_evidence import classify_evidence
from decidr.claim_intake import interpret_claim
from decidr.claim_workflow import (
    _attach_source_context,
    _reason_run,
    corpus_state,
    ensure_system_assessment,
    evidence_catalog,
    expand_evidence,
    initialise_workflow,
    submit_claim,
)
from decidr.database import connect, initialise_database, upsert_source, upsert_source_evidence
from decidr.hybrid import reciprocal_rank_fusion
from decidr.models import Evidence, Source
from decidr.retrieval import SearchQuery, lexical_search, lexical_text_search
from decidr.semantic import (
    SemanticUnavailableError,
    SentenceTransformerEmbedder,
    semantic_text_search,
)

ROOT = Path(__file__).resolve().parents[1]
RELATIONS = {"support", "contradict", "qualify", "contextual", "not_applicable"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2)


def independent(row):
    """Require declared independent human reviews; an agent label cannot self-promote."""
    reviews = row.get("reviews", [])
    return (
        row.get("status") == "independently_adjudicated"
        and len(
            {
                r["reviewer"]
                for r in reviews
                if r.get("kind") == "human" and r.get("independent") and r.get("completed_at")
            }
        )
        >= 2
        and bool(row.get("adjudicator"))
        and bool(row.get("rationale"))
    )


def validate_spec(spec, catalog):
    if spec.get("phase") != "phase2" or spec.get("purpose") != "development_only":
        raise ValueError("This runner accepts Phase 2 development only; no validation claims")
    groups, families, wordings = {}, {}, {}
    for case in spec["cases"]:
        gid, family, split = case["group_id"], case["family"], case["split"]
        if split not in {"familiar_development", "family_disjoint_development"}:
            raise ValueError("Unknown development split")
        if groups.setdefault(gid, (family, split, case["target"])) != (
            family,
            split,
            case["target"],
        ):
            raise ValueError("Underlying claim group crosses split, target or family")
        if families.setdefault(family, split) != split:
            raise ValueError("Scenario family crosses splits")
        normal = " ".join(case["wording"].casefold().split())
        if wordings.setdefault(normal, gid) != gid:
            raise ValueError("Same wording assigned to different claim groups")
    if len({c["case_id"] for c in spec["cases"]}) != len(spec["cases"]):
        raise ValueError("Duplicate case IDs")
    seen = set()
    for row in spec["judgements"]:
        key = row["group_id"], row["evidence_id"]
        if key in seen or key[0] not in groups or key[1] not in catalog:
            raise ValueError("Duplicate or out-of-scope evidence judgement")
        seen.add(key)
        record = catalog[key[1]]["evidence"]
        if row["source_id"] != record["source_id"] or row["passage_sha256"] != digest(
            record["text"]
        ):
            raise ValueError("Judgement evidence binding changed")
        if not row.get("quote") or row["quote"] not in record["text"]:
            raise ValueError("Judgement requires an exact source quotation")
        if row["relationship"] not in RELATIONS or type(row["relevant"]) is not bool:
            raise ValueError("Invalid relevance or relationship judgement")
        if row.get("decisive_counterevidence") and not (
            row["relevant"]
            and row["relationship"] == "contradict"
            and row.get("applicable") is True
        ):
            raise ValueError("Decisive counterevidence must be applicable contradiction")
        if row.get("status") != "provisional" and not independent(row):
            raise ValueError("Independent reference lacks review provenance")
    if not spec["cases"] or not spec["judgements"]:
        raise ValueError("Empty benchmark")


def set_metrics(returned, relevant, irrelevant, *, complete=False):
    """Unknowns never become irrelevant; incomplete recall is explicitly pool-relative."""
    returned, relevant, irrelevant = set(returned), set(relevant), set(irrelevant)
    if relevant & irrelevant:
        raise ValueError("Conflicting relevance judgements")
    unjudged = returned - relevant - irrelevant
    found, wrong = returned & relevant, returned & irrelevant
    precision = len(found) / len(returned) if returned and not unjudged else None
    return {
        "returned": len(returned),
        "known_relevant_found": len(found),
        "known_irrelevant_returned": len(wrong),
        "known_relevant_missed": len(relevant - returned),
        "unjudged_ids": sorted(unjudged),
        "precision": precision,
        "judged_precision": len(found) / len(found | wrong) if found | wrong else None,
        "precision_bounds": [
            len(found) / len(returned),
            (len(found) + len(unjudged)) / len(returned),
        ]
        if returned
        else None,
        "recall": len(found) / len(relevant) if complete and relevant else None,
        "known_pool_recall": len(found) / len(relevant) if relevant else None,
        "pool_complete": complete,
    }


def score_retrieval(ids, judgements, catalog, *, complete=False):
    relevant = {r["evidence_id"] for r in judgements if r["relevant"]}
    irrelevant = {r["evidence_id"] for r in judgements if not r["relevant"]}
    documents = {catalog[e]["evidence"]["source_id"] for e in ids}
    relevant_docs = {catalog[e]["evidence"]["source_id"] for e in relevant}
    # A negative passage does not make its entire document irrelevant.
    by_doc = defaultdict(set)
    for eid, record in catalog.items():
        by_doc[record["evidence"]["source_id"]].add(eid)
    irrelevant_docs = {sid for sid, eids in by_doc.items() if eids <= irrelevant}
    return {
        "passage": set_metrics(ids, relevant, irrelevant, complete=complete),
        "document": set_metrics(documents, relevant_docs, irrelevant_docs, complete=complete),
        "by_relationship": {
            relation: set_metrics(
                ids,
                {
                    r["evidence_id"]
                    for r in judgements
                    if r["relevant"] and r["relationship"] == relation
                },
                set(),
                complete=complete,
            )["known_pool_recall"]
            for relation in sorted(RELATIONS)
        },
        **{
            field: {
                "total": len(wanted := {r["evidence_id"] for r in judgements if r.get(field)}),
                "recovered": len(set(ids) & wanted),
                "missed_ids": sorted(wanted - set(ids)),
                "known_pool_recall": len(set(ids) & wanted) / len(wanted) if wanted else None,
            }
            for field in ("decisive_counterevidence", "exception")
        },
    }


def references(ids, rows, catalog, coverage):
    reviewed = [r for r in rows if independent(r)]
    complete = independent(coverage) and coverage.get("corpus_relevance_complete") is True
    if complete and {r["evidence_id"] for r in reviewed} != set(catalog):
        raise ValueError(
            "Complete corpus reference requires independent judgements for all passages"
        )
    return {
        "independent": score_retrieval(ids, reviewed, catalog, complete=complete),
        "provisional_diagnostic": score_retrieval(ids, rows, catalog),
        "warning": "Provisional pool recovery is not corpus recall or validated precision.",
    }


def bounded_context(connection, records, budget):
    """Charge every unique context passage to the same final evidence budget."""
    records = deepcopy(records)
    _attach_source_context(connection, records)
    catalog = evidence_catalog(connection)
    selected, seen = [], set()
    for record in records:
        for eid in [record["evidence_id"], *[r["evidence_id"] for r in record["source_context"]]]:
            if eid in seen or len(selected) == budget:
                continue
            seen.add(eid)
            if eid == record["evidence_id"]:
                selected.append(record)
            else:
                ev = catalog[eid]["evidence"]
                selected.append(
                    {
                        **catalog[eid],
                        "evidence_id": eid,
                        "source_id": ev["source_id"],
                        "text": ev["text"],
                        "locator": ev["locator"],
                        "retrieval_origin": "same_source_context",
                    }
                )
    _attach_source_context(connection, selected)
    for record in selected:
        record["source_context"] = [
            r for r in record["source_context"] if r["evidence_id"] in seen
        ]
    return selected


def package(results, catalog):
    return [
        {
            **(r if isinstance(r, dict) else asdict(r)),
            **catalog[r["evidence_id"] if isinstance(r, dict) else r.evidence_id],
        }
        for r in results
        if (r["evidence_id"] if isinstance(r, dict) else r.evidence_id) in catalog
    ]


def fill_budget(records, fallback, budget):
    """Keep expansion order, backfill unused slots, and deduplicate before truncating."""
    unique = {}
    for record in [*records, *fallback]:
        unique.setdefault(record["evidence_id"], record)
    return list(unique.values())[:budget]


def assess_packet(connection, claim, records, run_id, state, budget):
    """Replay the unmodified automatic classifier and complete employee reasoner."""
    run = {
        "run_id": run_id,
        "entry_id": run_id,
        "claim": claim.model_dump(mode="json"),
        "submission_original": claim.claim_text,
        "as_of": state["snapshot_date"],
        "reviewer": "system:benchmark",
        "assessment_kind": "system",
        "system_run_id": run_id,
        "packet": {
            "results": records,
            "method": run_id,
            "limit": budget,
            "semantic_status": "See retrieval run metadata",
        },
        "receipt": {
            "coverage": "Matched total exposed passage budget; incomplete corpus coverage",
            "gaps": [],
            "settlement": "Inspect unresolved cited evidence and missing pool passages.",
        },
        "source_graph": {
            r["source"]["source_id"]: r["source"] for r in evidence_catalog(connection).values()
        },
        **state,
    }
    notes = {r["evidence_id"]: classify_evidence(claim, r, run_id) for r in records}
    result = _reason_run(run, notes)
    result["review_snapshot"] = notes
    result["review_status"] = "Not yet reviewed"
    return result


def pipeline_files():
    return sorted(
        [
            *ROOT.glob("decidr/*.py"),
            *ROOT.glob("app/**/*.py"),
            *ROOT.glob("configs/*"),
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        ]
    )


def pipeline_hashes():
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in pipeline_files()
        if p.is_file()
    }


def evidence_only_copy(source_path, target):
    """Do not copy or load study claims, labels, reviews or historical model responses."""
    initialise_database(target)
    with (
        sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True) as src,
        connect(target) as dst,
    ):
        sources = [
            Source.model_validate_json(r[0])
            for r in src.execute("SELECT payload_json FROM sources ORDER BY source_id")
        ]
        if any(not s.source_id.startswith("phase2:") for s in sources):
            raise ValueError("Non-Phase-2 ledger refused before evidence/claim access")
        for source in sources:
            upsert_source(dst, source)
            evidence = [
                Evidence.model_validate_json(r[0])
                for r in src.execute(
                    "SELECT payload_json FROM evidence WHERE source_id=? ORDER BY evidence_id",
                    (source.source_id,),
                )
            ]
            upsert_source_evidence(dst, source.source_id, evidence)


def diagnose(result, rows, ids):
    if result is None:
        return {
            "interpretation": "pending",
            "retrieval": None,
            "relationship": None,
            "applicability": None,
            "final_verdict": None,
        }
    notes = result["review_snapshot"]
    excluded = {r["evidence_id"] for r in result["not_applicable_evidence"]}
    relationship, applicability = [], []
    for row in rows:
        eid = row["evidence_id"]
        if eid not in notes:
            continue
        actual = notes[eid]["link"]["relationship"]
        if actual != row["relationship"]:
            relationship.append(
                {
                    "evidence_id": eid,
                    "expected": row["relationship"],
                    "observed": actual,
                    "reference_status": row["status"],
                }
            )
        if row.get("applicable") is not None and actual is not None:
            link = notes[eid]["link"]
            observed = eid not in excluded and all(
                link[k]
                for k in ("target_match", "scope_match", "condition_match", "temporal_match")
            )
            if observed != row["applicable"]:
                applicability.append(
                    {
                        "evidence_id": eid,
                        "expected": row["applicable"],
                        "observed": observed,
                        "reference_status": row["status"],
                    }
                )
    return {
        "interpretation": "parsed; semantic correctness awaits independent review",
        "retrieval": {
            "missing_proposed_relevant": sorted(
                {r["evidence_id"] for r in rows if r["relevant"]} - set(ids)
            )
        },
        "relationship": relationship,
        "applicability": applicability,
        "final_verdict": {
            "automatic": result["outcome"],
            "correct": None,
            "reason": "No independent complete claim-level verdict reference",
        },
    }


def run(spec_path, database, output, budgets):
    if output.exists():
        raise ValueError("Use a new output directory; earlier runs are immutable")
    if not budgets or any(b < 2 or b > 50 for b in budgets):
        raise ValueError("Candidate budgets must be in 2..50")
    spec = json.loads(spec_path.read_text())
    # Check release declaration before touching the ledger.
    if spec.get("phase") != "phase2" or spec.get("purpose") != "development_only":
        raise ValueError("Phase 3 validation is not supported by this development runner")
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "benchmark.sqlite3"
        evidence_only_copy(database, scratch)
        with connect(scratch) as connection:
            initialise_workflow(connection)
            catalog = evidence_catalog(connection)
            validate_spec(spec, catalog)
            state = corpus_state(connection)
            if not state["snapshot_date"]:
                raise ValueError("An explicit source snapshot date is required")
            output.mkdir(parents=True)
            (output / "automatic").mkdir()
            frozen = pipeline_hashes()
            write_json(output / "benchmark.json", spec)
            write_json(output / "corpus.json", catalog)
            with zipfile.ZipFile(output / "pipeline.zip", "x", zipfile.ZIP_DEFLATED) as archive:
                for name in frozen:
                    archive.write(ROOT / name, name)
            manifest = {
                "phase": "phase2",
                "created_at": datetime.now(UTC).isoformat(),
                "purpose": "baseline_measurement_freeze",
                "selected_for_phase3": False,
                "phase3_accessed": False,
                "pipeline_files": frozen,
                "spec_sha256": digest(spec),
                "corpus_sha256": digest(catalog),
                **state,
                "budgets": budgets,
                "graph_seed_fraction": 0.6,
                "dependencies": {
                    d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
                },
                "reference_scope": "Partial Phase 2 pools; no automatic label promotion",
            }
            write_json(output / "freeze.json", manifest)
            adapter, semantic_status = None, None
            try:
                adapter = SentenceTransformerEmbedder()
                semantic_status = {
                    "status": "available",
                    "model": adapter.name,
                    "version": adapter.version,
                }
                from huggingface_hub import try_to_load_from_cache

                model_path = Path(try_to_load_from_cache(adapter.name, "config.json")).parent
                semantic_status.update(
                    revision=model_path.name,
                    device=str(adapter._model.device),
                    files={
                        str(p.relative_to(model_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(model_path.rglob("*"))
                        if p.is_file()
                    },
                )
            except SemanticUnavailableError as error:
                semantic_status = {"status": "unavailable", "reason": str(error)}
            write_json(output / "semantic-model.json", semantic_status)
            rows, native, pools = [], [], defaultdict(set)
            by_group = {
                g: [r for r in spec["judgements"] if r["group_id"] == g]
                for g in {c["group_id"] for c in spec["cases"]}
            }
            for case in spec["cases"]:
                print("Evaluating", case["case_id"], flush=True)
                intake = interpret_claim(case["wording"], target=case["target"])
                claim = intake.parts[0].claim if len(intake.parts) == 1 else None
                if claim:
                    claim.claim_id = case["case_id"]
                # Native path is retained separately: its attached context is not budget matched.
                entry_ids = submit_claim(connection, case["wording"], target=case["target"])
                native_runs = [ensure_system_assessment(connection, eid) for eid in entry_ids]
                native_path = "automatic/" + case["case_id"] + "-native.json.gz"
                with gzip.open(output / native_path, "xt") as handle:
                    json.dump(native_runs, handle)
                native.append(
                    {
                        "case_id": case["case_id"],
                        "snapshot": native_path,
                        "outcomes": [r["result"]["outcome"] if r else None for r in native_runs],
                        "exposed_passages": [
                            len(
                                {
                                    p["evidence_id"]
                                    for r in n["result"]["evidence_records"]
                                    for p in [r, *r.get("source_context", [])]
                                }
                            )
                            if n
                            else 0
                            for n in native_runs
                        ],
                    }
                )
                for budget in budgets:
                    started = perf_counter()
                    lexical = lexical_text_search(connection, SearchQuery(case["wording"]), budget)
                    methods = {"lexical_raw": package(lexical, catalog)}
                    if claim:
                        methods["lexical_structured"] = package(
                            lexical_search(connection, claim, budget), catalog
                        )
                    seed = max(1, int(budget * 0.6))
                    packet = {"results": package(lexical[:seed], catalog)}
                    methods["provenance_graph"] = expand_evidence(
                        connection, packet, limit=budget
                    )["results"]
                    if claim:
                        methods["approach_b_graph"] = package(
                            BoundedGraphExpander(connection).expand(claim, packet["results"])[
                                :budget
                            ],
                            catalog,
                        )
                    if adapter:
                        semantic = semantic_text_search(
                            connection, SearchQuery(case["wording"]), adapter, budget
                        )
                        methods["semantic"] = package(semantic, catalog)
                        methods["hybrid"] = package(
                            reciprocal_rank_fusion(lexical, semantic, limit=budget), catalog
                        )
                    for method, candidates in methods.items():
                        if "graph" in method:
                            candidates = fill_budget(candidates, methods["lexical_raw"], budget)
                        ranked_ids = [r["evidence_id"] for r in candidates]
                        exposed = bounded_context(connection, candidates, budget)
                        ids = [r["evidence_id"] for r in exposed]
                        assert len(set(ids)) == len(ids) <= budget
                        pool = pools[case["group_id"]]
                        pool.update(ranked_ids)
                        pool.update(ids)
                        result = (
                            assess_packet(
                                connection,
                                claim,
                                exposed,
                                case["case_id"] + "-" + method + str(budget),
                                state,
                                budget,
                            )
                            if claim
                            else None
                        )
                        snapshot = (
                            "automatic/"
                            + case["case_id"]
                            + "-"
                            + method
                            + str(budget)
                            + ".json.gz"
                        )
                        with gzip.open(output / snapshot, "xt") as handle:
                            json.dump(
                                {
                                    "intake": intake.model_dump(mode="json"),
                                    "result": result,
                                    "ranked_ids": ranked_ids,
                                    "exposed_ids": ids,
                                },
                                handle,
                            )
                        refs = by_group[case["group_id"]]
                        row = {
                            **case,
                            "method": method,
                            "budget": budget,
                            "seed_count": seed if "graph" in method else None,
                            "ranked_ids": ranked_ids,
                            "exposed_ids": ids,
                            "ranked": references(
                                ranked_ids,
                                refs,
                                catalog,
                                spec.get("coverage", {}).get(case["group_id"], {}),
                            ),
                            "exposed": references(
                                ids,
                                refs,
                                catalog,
                                spec.get("coverage", {}).get(case["group_id"], {}),
                            ),
                            "snapshot": snapshot,
                            "automatic_outcome": result["outcome"] if result else None,
                            "unclassified_count": len(result["unclassified_evidence"])
                            if result
                            else None,
                            "diagnostics": diagnose(result, refs, ids),
                        }
                        rows.append(row)
                    # Timing is descriptive, no method speed claim from cumulative elapsed time.
                    rows[-1]["whole_budget_elapsed_seconds"] = perf_counter() - started
            for row in rows:
                if "graph" not in row["method"]:
                    continue
                base = next(
                    r
                    for r in rows
                    if r["case_id"] == row["case_id"]
                    and r["budget"] == row["budget"]
                    and r["method"] == "lexical_raw"
                )
                added = set(row["exposed_ids"]) - set(base["exposed_ids"])
                lost = set(base["exposed_ids"]) - set(row["exposed_ids"])
                refs = by_group[row["group_id"]]
                relevant = {r["evidence_id"] for r in refs if r["relevant"]}
                row["graph_delta"] = {
                    "added_ids": sorted(added),
                    "displaced_ids": sorted(lost),
                    "proposed_relevant_added": sorted(added & relevant),
                    "proposed_relevant_displaced": sorted(lost & relevant),
                    "independently_unjudged_additions": sorted(
                        added - {r["evidence_id"] for r in refs if independent(r)}
                    ),
                    "verdict_changed": row["automatic_outcome"] != base["automatic_outcome"],
                    "assessment_improved": None,
                    "reason": "Verdict change is not improvement without an independent verdict reference",
                }
            write_json(
                output / "results.json",
                {
                    "semantic": semantic_status,
                    "runs": rows,
                    "native": native,
                    "phase3_readiness_established": False,
                },
            )
            # No rankings, proposed labels or model predictions in the blind packet.
            write_json(
                output / "blind-review.json",
                {
                    "phase": "phase2",
                    "corpus": "corpus.json",
                    "corpus_sha256": digest(catalog),
                    "instructions": "Review independently using the entire corpus. Add missed evidence; judge relevance separately from relationship/applicability. No response is inferred from an empty field. See docs/retrieval_benchmark_protocol.md.",
                    "groups": [
                        {
                            "group_id": gid,
                            "claims": [c for c in spec["cases"] if c["group_id"] == gid],
                            "candidate_ids": sorted(
                                ids | {r["evidence_id"] for r in by_group[gid]}, key=digest
                            ),
                            "judgements": [],
                            "corpus_relevance_complete": False,
                            "claim_verdict": None,
                            "reviewer": None,
                        }
                        for gid, ids in pools.items()
                    ],
                },
            )
            if pipeline_hashes() != frozen:
                raise RuntimeError("Pipeline changed during evaluation; this run is invalid")
            artifacts = {
                str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob("*"))
                if p.is_file()
            }
            write_json(
                output / "completion.json",
                {
                    "complete": True,
                    "pipeline_unchanged": True,
                    "artifacts": artifacts,
                    "run_count": len(rows),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
            print(
                json.dumps(
                    {
                        "runs": len(rows),
                        "native": len(native),
                        "semantic": semantic_status,
                        "automatic_outcomes": dict(Counter(r["automatic_outcome"] for r in rows)),
                    }
                )
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/evidence.sqlite3")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budgets", type=int, nargs="+", default=[10, 20, 50])
    parser.add_argument("--model-cache", type=Path, help="Existing HF_HOME cache; never downloads")
    args = parser.parse_args()
    if args.model_cache:
        os.environ["HF_HOME"] = str(args.model_cache.resolve())
        os.environ["HF_HUB_OFFLINE"] = "1"
    run(args.spec, args.database, args.output, args.budgets)


if __name__ == "__main__":
    main()
