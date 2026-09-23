"""Source-grounded regression checks; runtime never loads expected outcomes."""

from copy import deepcopy
from pathlib import Path

import pytest

from decidr.automatic_evidence import classify_evidence
from decidr.claim_export import claim_report_html
from decidr.claim_graph import evidence_dispositions, review_graph
from decidr.claim_intake import interpret_claim
from decidr.claim_workflow import (
    _evidence_groups,
    ensure_system_assessment,
    get_run,
    initialise_workflow,
    refresh_system_assessment,
    submit_claim,
)
from decidr.database import connect
from decidr.graph import to_graphviz
from decidr.ingestion import ingest

CLAIM = "Standard customer onboarding must be completed within six weeks."


@pytest.fixture(scope="module")
def onboarding(tmp_path_factory):
    path = tmp_path_factory.mktemp("onboarding") / "evidence.sqlite3"
    ingest({"phase2": Path("data/raw/phase2_model_development")}, path)
    with connect(path) as connection:
        initialise_workflow(connection)
        entry = submit_claim(connection, CLAIM)[0]
        return ensure_system_assessment(connection, entry)


def test_actual_passages_and_shared_dispositions(onboarding):
    result = onboarding["result"]
    assert len(result["evidence_records"]) == 50
    assert any("retrieval limit" in note for note in result["limitations"])
    policy = next(
        r
        for r in result["evidence_records"]
        if r["source_id"] == "phase2:POL-03" and "Formal requirements" in r["locator"]
    )
    assert (
        "2. Standard onboarding is completed within **6 weeks** of assignment." in policy["text"]
    )
    assert any("All new-business customer accounts" in c["text"] for c in policy["source_context"])
    assert any("unusual technical complexity" in c["text"] for c in policy["source_context"])
    assert result["outcome"] == "Supported"
    assert [r["evidence_id"] for r in result["supporting_evidence"]] == [policy["evidence_id"]]
    assert len(result["contextual_evidence"]) >= 9
    assert len(result["not_applicable_evidence"]) >= 10
    assert result["unclassified_evidence"]
    assert result["classification_status"] == "incomplete"
    assert not result["dependent_evidence_groups"]
    assert not result["evidence_gaps"]
    dispositions = evidence_dispositions(result)
    assert dispositions == result["evidence_dispositions"]
    assert len(dispositions) == 50
    graph = review_graph(onboarding, result["review_snapshot"], limit=100)
    for eid, d in dispositions.items():
        edge = graph[eid][result["claim"]["claim_id"]][0]
        assert edge["disposition"] == d["disposition"]
        assert edge["assessed_relationship"] == d["relationship"]
        assert edge["decisive"] == d["decisive"]
        assert graph.nodes[eid]["URL"].startswith("?source=")
        assert len(graph.nodes[eid]["label"]) < 50
    dot = to_graphviz(graph)
    assert 'Supports\\nprescribed rule' in dot and 'Excluded\\nprescribed rule' in dot
    assert "#15803d" in dot and "#6b7280" in dot
    html = claim_report_html(result)
    assert "Material exclusions and repeated evidence" in html
    assert "Source details and scope" in html
    for record in result["evidence_records"]:
        assert record["evidence_id"] in html
    for d in result["not_applicable_evidence"]:
        assert (
            "different population" in d["exclusion_reason"]
            or "contract renewal" in d["exclusion_reason"]
            or "Data handling" in d["exclusion_reason"]
        )
    assert "no effective date" in " ".join(result["limitations"])
    intake = interpret_claim(CLAIM).parts[0]
    assert intake.claim.subject == "Standard customer onboarding"
    assert intake.claim.predicate == "must"
    assert intake.claim.object == "be completed within six weeks"
    assert intake.claim.evidence_target == "prescribed_rule"
    duration = next(value for value in intake.protected_values if value["text"] == "six weeks")
    assert CLAIM[duration["start"] : duration["end"]] == "six weeks"


@pytest.mark.parametrize(
    "wording,relationship",
    [
        (CLAIM, "support"),
        ("Standard customer onboarding shall be finished within 6 weeks.", "support"),
        ("Standard customer onboarding must be completed in no more than 42 days.", "support"),
        ("Standard customer onboarding must not be completed within six weeks.", "contradict"),
        ("Standard customer onboarding must be completed within five weeks.", "qualify"),
        (
            "Standard customer onboarding must be completed within six weeks of contract signature.",
            "qualify",
        ),
        ("All customer onboarding must be completed within six weeks.", "qualify"),
        (
            "Standard customer onboarding must be completed within six weeks of assignment.",
            "support",
        ),
    ],
)
def test_paraphrases_preserve_duration_scope_and_clock(onboarding, wording, relationship):
    claim = interpret_claim(wording).parts[0].claim
    assert claim and claim.claim_text == wording
    record = next(
        r
        for r in onboarding["packet"]["results"]
        if r["source_id"] == "phase2:POL-03" and "Formal requirements" in r["locator"]
    )
    note = classify_evidence(claim, record, "test")
    assert note["link"]["relationship"] == relationship
    assert all(c["span"] in record["text"] for c in note["classification"]["comparisons"])
    # Same words in testimony do not prescribe a rule.
    testimony = deepcopy(record)
    testimony["source"]["source_type"] = "interview"
    assert classify_evidence(claim, testimony, "test")["link"]["relationship"] not in {
        "support",
        "contradict",
    }


def test_unclassified_is_not_absence_and_refresh_preserves_history(tmp_path):
    from test_claim_first import seed
    from decidr.database import initialise_database

    path = tmp_path / "ledger.sqlite3"
    initialise_database(path)
    with connect(path) as c:
        initialise_workflow(c)
        seed(c, text="Engineers must inspect turbines with techniques beyond this grammar.")
        entry = submit_claim(c, "Engineers must inspect turbines within 48 hours.")[0]
        baseline = ensure_system_assessment(c, entry)
        result = baseline["result"]
        assert result["outcome"] == "Insufficient evidence"
        assert result["classification_status"] == "incomplete"
        assert len(result["unclassified_evidence"]) == 1
        assert result["review_snapshot"]["E-S1"]["link"]["relationship"] is None
        assert not result["evidence_gaps"] and not result["not_applicable_evidence"]
        edge = review_graph(baseline, result["review_snapshot"])["E-S1"][
            baseline["claim"]["claim_id"]
        ][0]
        assert edge["relationship"] == "unclassified"
        refreshed = refresh_system_assessment(c, baseline["run_id"])
        assert refreshed["parent_run_id"] == baseline["run_id"]
        assert get_run(c, baseline["run_id"]) == baseline
        assert refreshed["result"]["review_status"] == "Not yet reviewed"
        assert not c.execute("SELECT * FROM employee_review_notes").fetchall()
        missing = ensure_system_assessment(
            c, submit_claim(c, "Xylophonic widgets shall oscillate extraterrestrially.")[0]
        )["result"]
        assert missing["evidence_gaps"] and not missing["unclassified_evidence"]


def test_containers_do_not_duplicate_distinct_records(onboarding):
    records = deepcopy(onboarding["packet"]["results"])
    notes = onboarding["result"]["review_snapshot"]
    groups = _evidence_groups(records, notes, onboarding["source_graph"])
    tasks = [r for r in records if r["source_id"] == "phase2:project-tasks"]
    assert len({groups[r["evidence_id"]] for r in tasks}) == len(tasks)
    first = next(r for r in records if r["source_id"] == "phase2:communications-log")
    second = deepcopy(first)
    second.update(
        evidence_id="different-message", locator=first["locator"].replace("COMMS-13", "COMMS-99")
    )
    groups = _evidence_groups(
        [first, second],
        {
            first["evidence_id"]: notes[first["evidence_id"]],
            second["evidence_id"]: notes[first["evidence_id"]],
        },
        onboarding["source_graph"],
    )
    assert groups[first["evidence_id"]] != groups[second["evidence_id"]]


def test_result_page_shows_verdict_excerpts_and_bounded_diagnostics(onboarding):
    from streamlit.testing.v1 import AppTest

    def render(run):
        from app.employee import result_view

        result_view(run)

    app = AppTest.from_function(render, args=(onboarding,)).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == "Verdict").value == "Supported"
    assert any(
        "Standard onboarding is completed within **6 weeks** of assignment." in t.value
        for t in app.text
    )
    assert any(e.label == "Material exclusions and repeated evidence" for e in app.expander)
    assert any(e.label == "Graph and assessment audit" for e in app.expander)
    assert not any("bounded classifier" in m.value for m in app.markdown)
    assert not any("R1_APPLICABILITY" in m.value for m in app.markdown)
