"""Fixed-output metadata replay and boundary integration regression checks."""

from copy import deepcopy
from datetime import date
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/metadata-correction-development-v1"


def test_replay_preserves_outputs_and_labels(tmp_path):
    subprocess.run(
        [sys.executable, str(REPORT / "replay.py"), "--output", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    read = lambda name: json.loads((tmp_path / name).read_text())
    all_cases = read("comparisons.json")["summaries"]["all"]
    assert all_cases["applicability_matches_before"] == 56
    assert all_cases["metadata_only_frozen_gate_matches"] == 61
    assert all_cases["applicability_matches_after"] == 62
    assert all_cases["methods"]["direct_model"]["verdict_matches_after"] == 55
    assert read("preservation-check.json")["changed"] == []
    assert read("manifest.json")["model_calls"] == 0
    assert [c["status"] for c in read("boundary-checks.json")] == ["yes", "unknown", "no"]
    original = json.loads(
        (ROOT / "reports/structured-extraction-development/matrix.json").read_text()
    )
    corrected = read("matrix.json")
    for old, new in zip(original["cases"], corrected["cases"], strict=True):
        restored = deepcopy(new)
        restored["record"]["source"] = old["record"]["source"]
        assert restored == old
    packet = read("reviewer-packet.json")["cases"]
    assert sum(len(c["metadata_annotation_amendments"]) for c in packet) == 7
    assert len(packet) == 62
    from html.parser import HTMLParser

    class Packet(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = set()

        def handle_starttag(self, tag, attrs):
            if "id" in dict(attrs):
                self.ids.add(dict(attrs)["id"])

    html = Packet()
    html.feed((tmp_path / "reviewer-packet.html").read_text())
    assert html.ids == {c["case_key"] for c in packet}


def test_unknown_supersession_boundary_reaches_all_reasoning_paths():
    from decidr.approach_a import _period_justifies_superseded_source
    from decidr.automatic_evidence import classify_evidence, clean
    from decidr.claim_workflow import _reason_target
    from decidr.evidence_b import eligibility
    from decidr.ingestion import ingest
    from decidr.models import AtomicClaim

    sources = {
        s.source_id: s
        for s in ingest({"phase2": ROOT / "data/raw/phase2_model_development"}).sources
    }
    snapshot = json.loads(
        (ROOT / "reports/assessment-quality-development/discount.json").read_text()
    )
    matrix = json.loads(
        (ROOT / "reports/structured-extraction-development/matrix.json").read_text()
    )
    record = deepcopy(next(r["record"] for r in matrix["cases"] if r["case_key"] == "frozen-45"))
    item = sources[record["source_id"]]
    record["source"] = item.model_dump(mode="json")
    claim_text = clean(record["text"].splitlines()[0])
    at = date(2025, 2, 28)
    claim = AtomicClaim(
        claim_id="boundary-check",
        subject="Literal proposition",
        predicate="states",
        object=claim_text,
        claim_text=claim_text,
        claim_type="development",
        evidence_target="prescribed_rule",
        applicable_start_date=at,
        applicable_end_date=at,
    )
    assert not _period_justifies_superseded_source(claim, item)
    assert not eligibility(claim, record, item, sources).checks["source_metadata"]
    metadata = snapshot["runtime_metadata"]
    run = {
        **metadata,
        "claim": claim.model_dump(mode="json"),
        "submission_original": claim_text,
        "source_graph": {sid: s.model_dump(mode="json") for sid, s in sources.items()},
        "receipt": metadata["review_receipt"],
        "packet": {"results": [record], "method": "lexical", "semantic_status": "disabled"},
    }
    note = classify_evidence(claim, record, "boundary-check")
    assert note["link"]["relationship"] == "support"
    result = _reason_target(run, {record["evidence_id"]: note})
    assert result["outcome"] == "Insufficient evidence"
    assert any(
        "boundary inclusion is unspecified" in e["exclusion_reason"]
        for e in result["material_exclusions"]
    )
