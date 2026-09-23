"""Independent development fixtures for automatic inference and later human changes."""

from datetime import date

import pytest
from test_claim_first import (
    CLAIM,
    judge,
    seed,
)
from test_claim_first import (
    ledger as ledger,  # noqa: PLC0414 -- register the shared pytest fixture
)

from decidr.claim_workflow import (
    DIMENSIONS,
    ensure_system_assessment,
    entries,
    get_run,
    reassess_evidence,
    review_notes,
    runs,
    submit_claim,
)
from decidr.database import connect

THRESHOLD = "The current threshold for new-business discount approval is 15%"


@pytest.mark.parametrize(
    "claim,text,updates,outcome",
    [
        (CLAIM, CLAIM, {}, "Supported"),
        (CLAIM, CLAIM.replace("must", "must not"), {}, "Contradicted"),
        (CLAIM, CLAIM.replace("48", "24"), {}, "Insufficient evidence"),
        (THRESHOLD, THRESHOLD.replace("15%", "20%"), {}, "Contradicted"),
        (THRESHOLD, THRESHOLD.replace("15%", "15.0%"), {}, "Supported"),
        (THRESHOLD, THRESHOLD.replace("new-business", "renewal"), {}, "Insufficient evidence"),
        (THRESHOLD, "Possibly " + THRESHOLD, {}, "Insufficient evidence"),
        (THRESHOLD, THRESHOLD + ". Except for regional accounts.", {}, "Insufficient evidence"),
        (THRESHOLD, THRESHOLD, {"source_type": "interview"}, "Supported"),
        (THRESHOLD, THRESHOLD, {"lifecycle_status": "draft"}, "Insufficient evidence"),
        (
            THRESHOLD,
            THRESHOLD,
            {"effective_start_date": date(2027, 1, 1)},
            "Insufficient evidence",
        ),
        (THRESHOLD, THRESHOLD, {"effective_start_date": None}, "Insufficient evidence"),
        (
            THRESHOLD,
            "Discount approval and the current new-business threshold were discussed: 15% and 20%.",
            {},
            "Insufficient evidence",
        ),
        (
            THRESHOLD,
            "Any discount of 15% or greater off list price on a new-business deal requires written approval from the Finance Director before completion.",
            {},
            "Supported",
        ),
        (
            THRESHOLD,
            "Any discount of 20% or greater off list price on a new-business deal requires written approval from the Finance Director before completion.",
            {},
            "Contradicted",
        ),
        (
            THRESHOLD,
            "Any discount of 15% or greater off list price on a renewal deal requires written approval from the Finance Director before completion.",
            {},
            "Insufficient evidence",
        ),
    ],
)
def test_grounded_classification_and_applicability(ledger, claim, text, updates, outcome):
    with connect(ledger) as c:
        seed(c, text=text, source_updates=updates)
        entry_id = submit_claim(c, claim)[0]
        run = ensure_system_assessment(c, entry_id)
        assert run["result"]["outcome"] == outcome
        assert run["result"]["review_status"] == "Not yet reviewed"
        assert ensure_system_assessment(c, entry_id) == run
        assert len(runs(c)) == 1
        assert not review_notes(c, run["run_id"])
        assert c.execute("SELECT count(*) FROM claim_evidence_links").fetchone()[0] == 0
        for record in run["result"]["evidence_records"]:
            note = run["result"]["review_snapshot"][record["evidence_id"]]
            assert note["link"]["method"] == "automatic"
            assert note["link"]["review_status"] == "not_reviewed"
            for comparison in note["classification"]["comparisons"]:
                assert comparison["span"] in record["text"]
        if outcome == "Insufficient evidence":
            assert run["result"]["settlements"]
            if run["result"]["unclassified_evidence"]:
                assert not run["result"]["evidence_gaps"]
                assert run["result"]["classification_status"] == "incomplete"
                assert "could not assess" in run["result"]["explanation"]
            else:
                assert run["result"]["evidence_gaps"]


def test_conflict_then_human_correction_preserves_both_snapshots(ledger):
    with connect(ledger) as c:
        seed(c, text=THRESHOLD)
        seed(c, "S2", text=THRESHOLD.replace("15%", "20%"))
        eid = submit_claim(c, THRESHOLD)[0]
        system = ensure_system_assessment(c, eid)
        assert system["result"]["outcome"] == "Contested"
        judgement = {
            "reviewer": "fixture-reviewer",
            "rationale": "Second source does not cover the claim scope.",
            "relationship": "not_applicable",
            "matches": {
                "target_match": True,
                "scope_match": False,
                "condition_match": True,
                "temporal_match": True,
            },
            "mode": "formal_rule",
            "dimensions": {name: 0.8 for name in DIMENSIONS},
            "justification": "Scope corrected from source.",
            "applicability_reason": "Source applies to a different scope.",
        }
        with pytest.raises(ValueError, match="proposal"):
            reassess_evidence(c, system["run_id"], "E-S2", proposed=True, **judgement)
        assert len(runs(c)) == 1
        corrected = reassess_evidence(c, system["run_id"], "E-S2", **judgement)
        assert corrected["result"]["outcome"] == "Supported"
        assert corrected["result"]["review_status"] == "Partially reviewed"
        assert get_run(c, system["run_id"]) == system
        assert corrected["parent_run_id"] == corrected["system_run_id"] == system["run_id"]
        assert corrected["changes"]["before"]["link"]["method"] == "automatic"
        assert corrected["changes"]["after"]["link"]["method"] == "human_review"
        judgement.update(relationship="support", matches={k: True for k in judgement["matches"]})
        confirmed = reassess_evidence(c, corrected["run_id"], "E-S1", **judgement)
        assert confirmed["result"]["review_status"] == "Human reviewed"
        assert get_run(c, corrected["run_id"]) == corrected
        assert confirmed["parent_run_id"] == corrected["run_id"]
        assert confirmed["system_run_id"] == system["run_id"]
        assert len(review_notes(c, confirmed["run_id"])) == 1
        assert ensure_system_assessment(c, eid) == system
        # Existing completed-run mutability guard still holds.
        with pytest.raises(ValueError, match="immutable"):
            judge(c, system["run_id"])


def test_empty_retrieval_is_an_assessment_not_a_review_blocker(ledger):
    with connect(ledger) as c:
        eid = submit_claim(c, "Xylophonic widgets shall oscillate extraterrestrially.")[0]
        run = ensure_system_assessment(c, eid)
        assert run["packet"]["results"] == []
        assert run["result"]["outcome"] == "Insufficient evidence"
        assert run["result"]["review_status"] == "Not yet reviewed"
        assert entries(c)[0]["status"] == "completed_assessment"


def test_unresolved_reference_still_requires_clarification(ledger):
    with connect(ledger) as c:
        eid = submit_claim(c, "They must inspect turbines.")[0]
        assert ensure_system_assessment(c, eid) is None
        assert entries(c)[0]["status"] == "awaiting_clarification"
        assert not runs(c)
