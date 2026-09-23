"""Reproducible evaluation exports guarded by available human references."""

import json
from pathlib import Path

from loguru import logger
import typer

from decidr.challenges import challenge_export
from decidr.config import DATABASE_PATH, PROJ_ROOT, REPORTS_DIR
from decidr.corpus import freeze_compatibility
from decidr.database import connect
from decidr.evaluation import outcome_metrics, serialise_evaluation
from decidr.models import Adjudication, ClaimAssessment, ClaimOutcome

app = typer.Typer()


def build_evaluation(database_path: Path) -> dict[str, object]:
    """Build only evaluations justified by records currently in the ledger."""
    configuration = json.loads((PROJ_ROOT / "configs/human_study.json").read_text())
    compatible, note = freeze_compatibility(database_path, configuration, PROJ_ROOT)
    if (
        not compatible
        or not configuration.get("final_evaluation_authorised")
        or configuration.get("held_out_access_status") != "unlocked"
        or configuration.get("reasoning_ruleset_status") != "approved_and_frozen"
    ):
        raise ValueError("Formal evaluation blocked: " + note)
    with connect(database_path) as connection:
        adjudication_rows = connection.execute(
            """SELECT payload_json FROM adjudications
               WHERE reviewer_a NOT LIKE 'test:%' AND reviewer_b NOT LIKE 'test:%'
               ORDER BY created_at, adjudication_id"""
        ).fetchall()
        automated_rows = connection.execute(
            """
            SELECT payload_json FROM claim_assessments
            WHERE reviewer LIKE 'automated:%' AND reviewer NOT LIKE 'test:%'
              AND review_status='complete'
            ORDER BY assessment_id
            """
        ).fetchall()
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        evidence_count = connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        embedding_count = connection.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
        graph_review_count = connection.execute(
            "SELECT COUNT(*) FROM claim_evidence_links"
        ).fetchone()[0]
    adjudications = [Adjudication.model_validate_json(row[0]) for row in adjudication_rows]
    automated_items = [ClaimAssessment.model_validate_json(row[0]) for row in automated_rows]
    references = {
        item.claim_id: item.final_outcome
        for item in adjudications
        if not item.preserve_disagreement and item.final_outcome is not None
    }
    automated: dict[str, ClaimOutcome] = {}
    for item in automated_items:
        automated[item.claim_id] = item.outcome
    outcomes = outcome_metrics(references, automated)
    limitation = None
    if not references:
        limitation = "No resolved two-reviewer adjudicated references exist; outcome performance is not calculated."
    elif outcomes.evaluated_claims < 6:
        limitation = "The evaluated purposive sample is too small for statistical generalisation."
    return {
        "research_results": {
            "adjudicated_reference_count": len(references),
            "automated_assessment_count": len(automated),
            "outcome_evaluation": serialise_evaluation(outcomes),
            "limitation": limitation,
        },
        "challenge_results": challenge_export(),
        "challenge_results_are_research_performance": False,
        "component_comparison": [
            {
                "component": "lexical retrieval",
                "status": "implemented" if evidence_count else "awaiting corpus",
                "baseline_limitation_addressed": "exact-term and identifier discovery",
                "observed_benefit": None,
                "observed_errors": None,
                "recommendation": "retain as interpretable baseline; performance awaits adjudicated pools",
            },
            {
                "component": "semantic retrieval",
                "status": "locally exercised"
                if embedding_count
                else "optional model unavailable/not run",
                "baseline_limitation_addressed": "paraphrase retrieval",
                "observed_benefit": None,
                "observed_errors": None,
                "recommendation": "no retention claim until evaluated on the same adjudicated pools",
            },
            {
                "component": "hybrid retrieval",
                "status": "implemented; corpus comparison pending",
                "baseline_limitation_addressed": "combine lexical precision and semantic recall",
                "observed_benefit": None,
                "observed_errors": None,
                "recommendation": "no retention claim until semantic retrieval and pooled evaluation run",
            },
            {
                "component": "graph-enhanced handling",
                "status": "implemented"
                if graph_review_count
                else "implemented; no reviewed links",
                "baseline_limitation_addressed": "provenance, version, and dependence inspection",
                "observed_benefit": None,
                "observed_errors": None,
                "recommendation": "retain for inspection; measured benefit awaits reviewer use",
            },
        ],
        "corpus_state": {"sources": source_count, "evidence_units": evidence_count},
        "error_taxonomy": [
            "claim_ambiguity",
            "retrieval_failure",
            "applicability_error",
            "relationship_misclassification",
            "provenance_loss",
            "temporal_error",
            "dependence_error",
            "inappropriate_reasoning",
            "unfaithful_explanation",
            "data_extraction_failure",
            "reference_review_disagreement",
        ],
    }


def write_evaluation(report: dict[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation_results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    challenges = report["challenge_results"]
    (output_dir / "challenge_results.json").write_text(
        json.dumps(challenges, indent=2), encoding="utf-8"
    )
    research = report["research_results"]
    lines = [
        "# Evaluation report",
        "",
        "## Research evaluation",
        "",
        f"- Adjudicated references: {research['adjudicated_reference_count']}",
        f"- Automated assessments: {research['automated_assessment_count']}",
        f"- Limitation: {research['limitation'] or 'See per-claim results and small-sample caveat.'}",
        "",
        "## Synthetic behavioral challenges",
        "",
        "These are software-behavior checks, not research performance results.",
        "",
    ]
    lines.extend(
        f"- {item['challenge_id']} {item['name']}: {'PASS' if item['passed'] else 'FAIL'} — {item['observed']}"
        for item in challenges
    )
    (output_dir / "evaluation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    database: str = str(DATABASE_PATH), output: str = str(REPORTS_DIR / "evaluation")
) -> None:
    """Run guarded evaluation and export machine/human-readable reports."""
    report = build_evaluation(Path(database))
    write_evaluation(report, Path(output))
    logger.success(
        "Evaluation exported: {} adjudicated references; {} synthetic challenges",
        report["research_results"]["adjudicated_reference_count"],
        len(report["challenge_results"]),
    )


if __name__ == "__main__":
    app()
