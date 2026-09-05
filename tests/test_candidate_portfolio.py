import csv
from datetime import date
import json

from decidr.config import PROJ_ROOT
from decidr.database import connect, initialise_database
from decidr.candidate_portfolio import load_candidate_portfolio
from decidr.models import EvidenceTarget


CANDIDATE_PATH = PROJ_ROOT / "framework" / "candidate_claim_portfolio.csv"
DESIGN_PATH = PROJ_ROOT / "framework" / "candidate_claim_portfolio_design.csv"
STUDY_CONFIG_PATH = PROJ_ROOT / "configs" / "human_study.json"
AUDIT_PATH = (
    PROJ_ROOT
    / "data"
    / "raw"
    / "phase2_model_development"
    / "09_audit_log"
    / "system_audit_log.csv"
)


def _rows():
    with CANDIDATE_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_candidate_portfolio_has_eight_unapproved_atomic_records():
    rows = _rows()

    assert len(rows) == 8
    assert len({row["candidate_claim_id"] for row in rows}) == 8
    assert {row["portfolio_status"] for row in rows} == {
        "approved_and_frozen"
    }
    validated = load_candidate_portfolio(CANDIDATE_PATH, STUDY_CONFIG_PATH)
    assert len(validated) == 8
    assert all(item.claim.claim_text for item in validated)


def test_candidate_split_and_required_challenge_mix():
    with DESIGN_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    splits = [row["recommended_split"] for row in rows]
    characteristics = " ".join(row["challenge_characteristics"] for row in rows).casefold()

    assert splits.count("development") == 6
    assert splits.count("held_out") == 2
    assert {row["candidate_claim_id"] for row in rows if row["recommended_split"] == "held_out"} == {
        "CAND-04",
        "CAND-08",
    }
    for required in ("policy-practice divergence", "temporal change", "copied", "missing"):
        assert required in characteristics


def test_dates_types_and_unverified_fields_are_explicit():
    rows = _rows()
    allowed_types = {
        "formal_rule",
        "routine_practice",
        "system_record_assertion",
        "specific_event_assertion",
    }

    assert {row["claim_type"] for row in rows} <= allowed_types
    assert {row["assessment_cutoff_date"] for row in rows} == {"2026-07-31"}
    for row in rows:
        for field in ("applicable_start_date", "applicable_end_date", "assessment_cutoff_date"):
            if row[field]:
                assert date.fromisoformat(row[field]).isoformat() == row[field]
    partial = {row["candidate_claim_id"]: row for row in rows if row["unverified_fields"]}
    assert set(partial) == {"CAND-04", "CAND-07", "CAND-08"}
    assert {row["claim_version"] for row in rows} == {"1.2-final"}
    assert {row["ingestion_completeness"] for row in rows} == {
        "complete_with_documented_exclusions"
    }
    assert all(row["record_population_completeness"] for row in rows)
    assert all(row["claim_evidence_coverage"] for row in rows)


def test_every_candidate_has_the_required_evidence_target():
    candidates = load_candidate_portfolio(CANDIDATE_PATH, STUDY_CONFIG_PATH)
    targets = {item.claim.claim_id: item.claim.evidence_target for item in candidates}

    assert targets == {
        "CAND-01": EvidenceTarget.PRESCRIBED_RULE,
        "CAND-02": EvidenceTarget.PRESCRIBED_RULE,
        "CAND-03": EvidenceTarget.PRESCRIBED_RULE,
        "CAND-04": EvidenceTarget.ROUTINE_PRACTICE,
        "CAND-05": EvidenceTarget.PRESCRIBED_RULE,
        "CAND-06": EvidenceTarget.PRESCRIBED_RULE,
        "CAND-07": EvidenceTarget.SYSTEM_RECORD,
        "CAND-08": EvidenceTarget.SPECIFIC_EVENT,
    }


def test_quantitative_candidates_have_nonzero_populations_and_rules():
    rows = _rows()
    quantitative = {
        row["candidate_claim_id"]: row
        for row in rows
        if "more than half" in row["exact_claim_wording"].casefold()
    }

    assert set(quantitative) == {"CAND-04"}
    assert int(quantitative["CAND-04"]["eligible_case_count"]) == 5
    assert quantitative["CAND-04"]["numerator_rule"]
    assert quantitative["CAND-04"]["denominator_rule"]
    assert "outcome" not in quantitative["CAND-04"]


def test_revised_claim_wording_avoids_unverified_scope_and_authority():
    rows = {row["candidate_claim_id"]: row for row in _rows()}

    assert "customer-deal" in rows["CAND-02"]["exact_claim_wording"]
    assert rows["CAND-03"]["evidence_target"] == "prescribed_rule"
    assert rows["CAND-03"]["exact_claim_wording"].startswith("Standard new-business")
    assert "Account Executive" not in rows["CAND-05"]["exact_claim_wording"]
    assert rows["CAND-07"]["eligible_case_count"] == "1"


def test_prescribed_rule_claims_are_organisational_propositions():
    rows = {row["candidate_claim_id"]: row for row in _rows()}

    for claim_id in ("CAND-01", "CAND-02", "CAND-03", "CAND-05", "CAND-06"):
        assert rows[claim_id]["evidence_target"] == "prescribed_rule"
        assert not rows[claim_id]["exact_claim_wording"].startswith("POL-")
        assert not rows[claim_id]["subject"].startswith("POL-")
    assert rows["CAND-01"]["relationship_predicate"] == "requires"
    assert rows["CAND-03"]["subject"] == "standard new-business onboarding"


def test_final_metadata_normalisation_preserves_atomic_rule_components():
    rows = {row["candidate_claim_id"]: row for row in _rows()}

    assert rows["CAND-01"]["subject"] == "A new-business discount of 15% or greater"
    assert rows["CAND-01"]["target_object"] == (
        "Written approval from the Head of Finance & People Ops"
    )
    assert rows["CAND-01"]["conditions"] == "Before the deal is marked Closed Won"
    assert rows["CAND-02"]["subject"] == "A customer-deal discount of 10% or greater"
    assert rows["CAND-02"]["conditions"].split("; ") == [
        "approval before Closed Won",
        "applicability from 2021-06-01 to 2025-02-28",
    ]
    assert rows["CAND-06"]["target_object"] == "Approval from the Head of Finance & People Ops"
    assert rows["CAND-06"]["conditions"] == "Before reimbursement"
    assert rows["CAND-08"]["subject"] == "Emergency billing deployment on 18 February 2026"
    assert "INC-2026-02" not in rows["CAND-08"]["subject"]
    assert "AUD-0111" not in rows["CAND-08"]["subject"]
    assert "INC-2026-02" in rows["CAND-08"]["conditions"]
    assert "AUD-0111" in rows["CAND-08"]["conditions"]


def test_held_out_escalation_denominator_uses_stable_ids_without_scoring_outcome():
    with AUDIT_PATH.open(encoding="utf-8", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))
    created = {
        row["related_record"]
        for row in audit_rows
        if row["related_record"].startswith("TICK-") and row["action"] == "Raised ticket"
    }
    escalated = {
        row["related_record"]
        for row in audit_rows
        if row["related_record"].startswith("TICK-")
        and row["action"] == "Escalated ticket to Engineering"
    }

    assert created & escalated == {
        "TICK-4102",
        "TICK-4171",
        "TICK-4288",
        "TICK-4350",
        "TICK-4510",
    }


def test_reviewer_identities_are_stored_once_in_study_configuration():
    configuration = json.loads(STUDY_CONFIG_PATH.read_text(encoding="utf-8"))
    with DESIGN_PATH.open(encoding="utf-8", newline="") as handle:
        design_fields = csv.DictReader(handle).fieldnames

    assert configuration["reviewers"] == {
        "reviewer-a": "Royston",
        "reviewer-b": "Isanka",
    }
    assert configuration["packet_generation_authorised"] is True
    assert configuration["final_evaluation_authorised"] is False
    assert configuration["held_out_access_status"] == "sealed"
    assert configuration["reasoning_ruleset_status"] == "development_unfrozen"
    assert "proposed_reviewer_1" not in design_fields
    assert "proposed_reviewer_2" not in design_fields


def test_operational_definitions_are_recorded_before_review():
    configuration = json.loads(STUDY_CONFIG_PATH.read_text(encoding="utf-8"))
    definitions = configuration["operational_definitions"]

    assert definitions["majority_threshold"] == "strictly_greater_than_50_percent"
    assert definitions["within_six_weeks"] == "no_more_than_42_calendar_days"
    assert definitions["missing_timestamp_handling"].startswith("exclude_from_denominator")
    assert configuration["ruleset_version"] == "development-unfrozen"


def test_candidates_are_not_inserted_into_claim_or_adjudication_tables(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)

    with connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM adjudications").fetchone()[0] == 0
