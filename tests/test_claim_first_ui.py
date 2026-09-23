"""Streamlit interactions backed by actual development-ledger services."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_claim_first import CLAIM, finish, judge, seed, start

from decidr.claim_workflow import entries, initialise_workflow, runs, submit_claim
from decidr.database import connect, initialise_database


@pytest.fixture
def ui_ledger(tmp_path):
    database = tmp_path / "ui.sqlite3"
    initialise_database(database)
    with connect(database) as c:
        initialise_workflow(c)
        seed(c)
    return database


def harness(page_name, database):
    from pathlib import Path

    import app.employee as ui

    ui.DATABASE_PATH = Path(database)
    getattr(ui, page_name)()


def page(name, database):
    return AppTest.from_function(harness, args=(name, str(database))).run()


def widget(group, label):
    return next(item for item in group if item.label == label)


def test_home_navigation_and_one_click_submission(ui_ledger, monkeypatch):
    import app.employee

    import decidr.config

    monkeypatch.setattr(decidr.config, "DATABASE_PATH", ui_ledger)
    monkeypatch.setattr(app.employee, "DATABASE_PATH", ui_ledger)
    app = AppTest.from_file(str(Path("app/Home.py").resolve())).run()
    assert not app.exception
    assert app.title[0].value == "Assess a Claim"
    app.chat_input[0].set_value(CLAIM).run()
    assert not app.exception
    assert not any("Confirm" in b.label for b in app.button)
    assert widget(app.metric, "Verdict").value == "Supported"
    with connect(ui_ledger) as c:
        registered = entries(c)
        assert registered[0]["original_wording"] == CLAIM
        assert registered[0]["status"] == "completed_assessment"
        assert runs(c)[0]["result"]["review_status"] == "Not yet reviewed"
        assert not c.execute("SELECT * FROM employee_review_notes").fetchall()


def test_ui_clarification_retains_original(ui_ledger):
    app = page("assess_page", ui_ledger)
    app.chat_input[0].set_value("Engineers are assigned to turbine inspections.").run()
    app.chat_input[0].set_value("Actual practice").run()
    assert not app.exception
    assert widget(app.metric, "Verdict").value == "Insufficient"
    with connect(ui_ledger) as c:
        entry = entries(c)[-1]
        assert len(entries(c)) == 2
        assert entries(c)[0]["intake"]["claim"]["evidence_target"] is None
        assert entry["original_wording"] == "Engineers are assigned to turbine inspections."
        assert entry["status"] == "completed_assessment"
        assert entry["intake"]["claim"]["evidence_target"] == "actual_practice"


@pytest.mark.parametrize("reopen", [False, True])
def test_threshold_automatic_verdict_then_traceable_correction(ui_ledger, monkeypatch, reopen):
    import json

    import app.employee

    import decidr.config

    wording = "The current threshold for new-business discount approval is 15%"
    with connect(ui_ledger) as c:
        seed(c, text=wording, source_updates={"title": "Discount approval policy"})
        seed(
            c,
            "S2",
            text=wording.replace("15%", "20%"),
            source_updates={"title": "Conflicting discount approval policy"},
        )
        if reopen:
            # Exact shape of a saved claim from the old parser, before target selection.
            eid = submit_claim(c, wording)[0]
            payload = entries(c)[0]
            payload["intake"].update(
                status="awaiting_clarification",
                claim=None,
                clarification="Is this about a prescribed rule, what happens in practice, or what a record says?",
            )
            c.execute(
                "UPDATE employee_claims SET status='awaiting_clarification',claim_id=NULL,payload_json=? WHERE entry_id=?",
                (
                    json.dumps(
                        {
                            k: payload[k]
                            for k in (
                                "intake",
                                "clarifications",
                                "submission_parts",
                                "interpretation_review",
                            )
                        }
                    ),
                    eid,
                ),
            )
    monkeypatch.setattr(decidr.config, "DATABASE_PATH", ui_ledger)
    monkeypatch.setattr(app.employee, "DATABASE_PATH", ui_ledger)
    if reopen:
        app = page("register_page", ui_ledger)
    else:
        app = AppTest.from_file(str(Path("app/Home.py").resolve())).run()
        app.chat_input[0].set_value(wording).run()
        widget(app.button, "Optional human review").click().run()
    assert not app.exception and not app.error
    assert widget(app.metric, "Verdict").value == "Contested"
    assert not any(s.label == "Meaning of the claim" for s in app.selectbox)
    assert any("Not yet reviewed" in c.value for c in app.caption)
    with connect(ui_ledger) as c:
        assert len(entries(c)) == 1 and len(runs(c)) == 1
        original = runs(c)[0]
        assert entries(c)[0]["original_wording"] == wording
        assert entries(c)[0]["status"] == "completed_assessment"
        assert entries(c)[0]["clarifications"] == []
        assert not c.execute("SELECT * FROM employee_review_notes").fetchall()
        assert not c.execute("SELECT * FROM claim_evidence_links").fetchall()
        assert original["result"]["supporting_evidence"][0]["evidence_id"] == "E-S1"
        assert original["result"]["contradicting_evidence"][0]["evidence_id"] == "E-S2"
        assert all(
            n["link"]["method"] == "automatic" and n["link"]["review_status"] == "not_reviewed"
            for n in original["result"]["review_snapshot"].values()
        )
    assert any(m.value == original["result"]["explanation"] for m in app.markdown)
    assert all(
        any("source=" + sid in b.proto.url for b in app.get("link_button")) for sid in ("S1", "S2")
    )
    widget(app.selectbox, "Evidence to correct").select("E-S2").run()
    widget(app.text_input, "Reviewer name").set_value("Synthetic fixture reviewer")
    widget(app.selectbox, "Evidence relationship").select("not_applicable")
    widget(app.checkbox, "Scope matches").uncheck()
    widget(app.text_area, "Reason for confirming or correcting this evidence").set_value(
        "Synthetic review: the second source's scope was incorrectly classified."
    )
    widget(app.button, "Save human review and reassess").click().run()
    assert "confirm the checkbox" in app.error[0].value
    widget(app.checkbox, "I inspected this excerpt and its applicability to the claim").check()
    widget(app.button, "Save human review and reassess").click().run()
    assert not app.exception and not app.error
    assert [m.value for m in app.metric if m.label == "Verdict"][-1] == "Supported"
    with connect(ui_ledger) as c:
        saved = runs(c)
        assert len(saved) == 2 and saved[0] == original
        assert saved[1]["parent_run_id"] == saved[1]["system_run_id"] == original["run_id"]
        assert saved[1]["result"]["review_status"] == "Partially reviewed"
        assert saved[1]["changes"]["before"]["link"]["relationship"] == "contradict"
        assert saved[1]["changes"]["after"]["link"]["relationship"] == "not_applicable"
        assert len(c.execute("SELECT * FROM employee_review_notes").fetchall()) == 1
    if reopen:
        widget(app.selectbox, "Assessment history").select(original["run_id"]).run()
    assert widget(app.metric, "Verdict").value == "Contested"
    source = AppTest.from_file(str(Path("app/Home.py").resolve()))
    source.query_params["source"] = "S1"
    source.run()
    assert not source.exception
    assert source.title[0].value == "Discount approval policy"
    assert any(item.value == wording for item in source.text)
    widget(source.button, "Return to claim assessment").click().run()
    assert source.title[0].value == "Assess a Claim"
    reopened = page("register_page", ui_ledger)
    assert not reopened.exception
    assert widget(reopened.metric, "Verdict").value == "Supported"


def test_free_text_clarification_preserves_explicit_restatement(ui_ledger):
    app = page("assess_page", ui_ledger)
    app.chat_input[0].set_value("They must inspect turbines.").run()
    assert any("Who or what" in item.value for item in app.markdown)
    app.chat_input[0].set_value("Engineers must inspect turbines.").run()
    assert not app.exception and not app.error
    with connect(ui_ledger) as c:
        entry = entries(c)[0]
        assert entry["status"] == "completed_assessment"
        assert entry["original_wording"] == "They must inspect turbines."
        assert entry["intake"]["claim"]["claim_text"] == "Engineers must inspect turbines."
        assert entry["clarifications"] == ["Engineers must inspect turbines."]


def test_reviewer_page_starts_with_system_result_and_confirms_afterwards(ui_ledger):
    with connect(ui_ledger) as c:
        submit_claim(c, CLAIM)
    app = page("review_page", ui_ledger)
    assert not app.exception
    assert widget(app.metric, "Verdict").value == "Supported"
    widget(app.text_input, "Reviewer name").set_value("UI development reviewer")
    widget(app.text_area, "Reason for confirming or correcting this evidence").set_value(
        "The approved instruction explicitly states the scoped deadline."
    )
    widget(app.checkbox, "I inspected this excerpt and its applicability to the claim").check()
    widget(app.button, "Save human review and reassess").click().run()
    assert not app.exception and not app.error
    assert widget(app.metric, "Verdict").value == "Supported"
    with connect(ui_ledger) as c:
        assert runs(c)[1]["result"]["review_status"] == "Human reviewed"
        before = runs(c)[1]["result"]
    widget(app.selectbox, "Remove one source origin group").select("S1")
    widget(app.button, "Compare scenario").click().run()
    assert not app.exception
    assert widget(app.metric, "Verdict").value == "Supported"
    with connect(ui_ledger) as c:
        assert runs(c)[1]["result"] == before


def test_no_evidence_submission_and_missing_source_are_actionable(ui_ledger, monkeypatch):
    from app import employee as employee_ui

    import decidr.config

    app = page("assess_page", ui_ledger)
    app.chat_input[0].set_value("Xylophonic widgets shall oscillate extraterrestrially.").run()
    assert not app.exception and not app.error
    assert widget(app.metric, "Verdict").value == "Insufficient"
    assert any("No evidence was retrieved" in item.value for item in app.info)
    with connect(ui_ledger) as c:
        assert runs(c)[0]["result"]["review_status"] == "Not yet reviewed"
        assert not c.execute("SELECT * FROM employee_review_notes").fetchall()
    monkeypatch.setattr(decidr.config, "DATABASE_PATH", ui_ledger)
    monkeypatch.setattr(employee_ui, "DATABASE_PATH", ui_ledger)
    source = AppTest.from_file(str(Path("app/Home.py").resolve()))
    source.query_params["source"] = "missing-source"
    source.run()
    assert not source.exception
    assert "Use Evidence Explorer" in source.error[0].value


@pytest.mark.parametrize("name", ["register_page", "risks_page", "explorer_page"])
def test_employee_areas_render_completed_development_assessment(ui_ledger, name):
    with connect(ui_ledger) as c:
        _, run = start(c)
        judge(
            c,
            run,
            risks=["unresolved_decision_rights"],
            risk_reason="The excerpt gives no escalation decision holder.",
            gaps=["Decision rights missing in this excerpt."],
            settlement="Obtain an approved delegation record.",
        )
        finish(c, run)
    app = page(name, ui_ledger)
    assert not app.exception
    if name == "explorer_page":
        widget(app.text_input, "Search source evidence").set_value("inspect turbines")
        widget(app.button, "Search evidence").click().run()
        assert not app.exception
        assert any("Maintenance policy" in item.label for item in app.expander)
    if name == "risks_page":
        widget(app.button, "Inspect linked claim").click().run()
        assert not app.exception
        assert widget(app.metric, "Verdict").value == "Supported"
