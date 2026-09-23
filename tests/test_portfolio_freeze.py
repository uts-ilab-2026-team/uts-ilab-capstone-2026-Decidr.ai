import hashlib
import json

from decidr.config import PROJ_ROOT


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_manifest_checksums_and_states_are_complete():
    manifest = json.loads(
        (PROJ_ROOT / "framework" / "portfolio_freeze_manifest_v1.1-final.json").read_text()
    )

    assert manifest["portfolio_status"] == "approved_and_frozen"
    assert manifest["held_out_access_status"] == "sealed"
    assert manifest["claim_file_sha256"] == _sha256(PROJ_ROOT / manifest["claim_file"])
    assert manifest["design_file_sha256"] == _sha256(PROJ_ROOT / manifest["design_file"])
    assert manifest["study_configuration_sha256"] == _sha256(
        PROJ_ROOT / manifest["study_configuration_file"]
    )


def test_v12_freeze_manifest_checksums_and_states_are_complete():
    manifest = json.loads(
        (PROJ_ROOT / "framework" / "portfolio_freeze_manifest_v1.2-final.json").read_text()
    )

    assert manifest["portfolio_version"] == "1.2-final"
    assert manifest["portfolio_status"] == "approved_and_frozen"
    assert manifest["approver"] == "Royston"
    assert manifest["held_out_access_status"] == "sealed"
    assert manifest["claim_file_sha256"] == _sha256(PROJ_ROOT / manifest["claim_file"])
    assert manifest["design_file_sha256"] == _sha256(PROJ_ROOT / manifest["design_file"])
    assert manifest["study_configuration_sha256"] == _sha256(
        PROJ_ROOT / manifest["study_configuration_file"]
    )


def test_ingestion_audit_reports_every_registered_source():
    register = json.loads(
        (PROJ_ROOT / "reports" / "ingestion" / "source_register.json").read_text()
    )
    statuses = [source["ingestion_status"] for source in register]

    assert len(register) == 45
    assert statuses.count("ingested") == 44
    assert statuses.count("excluded") == 1
    assert {source["source_id"] for source in register if source["ingestion_status"] == "excluded"} == {
        "phase2:readme",
    }
