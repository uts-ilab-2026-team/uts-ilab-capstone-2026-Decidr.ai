"""Development cases specified independently of corpus scenarios and reference labels."""

from datetime import date
import hashlib

import pytest

from decidr.claim_export import claim_report_html
from decidr.claim_graph import review_graph
from decidr.claim_intake import interpret_claim
from decidr.claim_workflow import (
    DIMENSIONS,
    add_evidence,
    begin_review,
    clarify_claim,
    complete_review,
    corpus_state,
    entries,
    get_entry,
    get_run,
    initialise_workflow,
    knowledge_risks,
    promote_claim,
    reusable_match,
    review_evidence,
    review_interpretation,
    review_notes,
    search_evidence,
    sensitivity,
    submit_claim,
)
from decidr.database import (
    connect,
    initialise_database,
    save_claim,
    upsert_source,
    upsert_source_evidence,
)
from decidr.models import AtomicClaim, Evidence, Source
from decidr.retrieval import lexical_search

CLAIM = "Engineers must inspect turbines within 48 hours."
AS_OF = date(2026, 7, 20)


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    initialise_database(path)
    with connect(path) as connection:
        initialise_workflow(connection)
        seed(connection)
    return path


def seed(
    connection,
    sid="S1",
    *,
    text=CLAIM,
    release="phase2",
    source_updates=None,
    evidence_updates=None,
):
    source = Source(
        source_id=sid,
        title="Maintenance policy",
        original_file_path=f"/fixture/{sid}.md",
        source_type="policy",
        checksum=hashlib.sha256(sid.encode()).hexdigest(),
        ingestion_status="ingested",
        metadata_notes="release=" + release,
        creation_date=date(2026, 7, 20),
        effective_start_date=date(2025, 1, 1),
        lifecycle_status="current",
    )
    source = Source.model_validate({**source.model_dump(), **(source_updates or {})})
    evidence = Evidence(
        evidence_id="E-" + sid,
        source_id=sid,
        locator="section:maintenance#block:1",
        text=text,
        source_type=source.source_type,
        extraction_method="development_fixture",
        structured_metadata={"release": release},
    )
    evidence = Evidence.model_validate({**evidence.model_dump(), **(evidence_updates or {})})
    upsert_source(connection, source)
    upsert_source_evidence(connection, sid, [evidence])
    return evidence.evidence_id


def start(connection, wording=CLAIM):
    eid = submit_claim(connection, wording)[0]
    return eid, begin_review(connection, eid, "development-reviewer", AS_OF)


def judge(connection, run, eid="E-S1", **updates):
    values = {
        "relationship": "support",
        "matches": {
            key: True
            for key in ("target_match", "scope_match", "condition_match", "temporal_match")
        },
        "mode": "formal_rule",
        "dimensions": {key: 0.9 for key in DIMENSIONS},
        "justification": "Direct approved instruction for this scoped rule; independently specified development judgement.",
        "applicability_reason": "The excerpt explicitly requires this action within the claimed period.",
    }
    review_evidence(connection, run, eid, **{**values, **updates})


def finish(connection, run, **updates):
    return complete_review(
        connection,
        run,
        rationale="All candidates reviewed against the exact statement and date.",
        meaning_confirmed=True,
        **updates,
    )


def test_exact_submission_preserves_protected_meaning_without_confirmation(ledger):
    wording = "  Engineers must not inspect more than 12 turbines within 48 hours on 2026-06-02, except offshore units.  "
    intake = interpret_claim(wording)
    assert intake.original_wording == wording
    part = intake.parts[0]
    assert part.status == "awaiting_evidence_review"
    assert part.claim.subject == "Engineers"
    assert part.claim.predicate == "must not"
    assert (
        part.claim.object
        == "inspect more than 12 turbines within 48 hours on 2026-06-02, except offshore units"
    )
    assert part.claim.proposition_polarity == "negative"
    assert part.claim.applicable_start_date == date(2026, 6, 2)
    assert "except offshore units" in part.claim.scope
    for value in part.protected_values:
        assert wording[value["start"] : value["end"]] == value["text"]
    with connect(ledger) as connection:
        eid = submit_claim(connection, wording)[0]
        assert get_entry(connection, eid)["original_wording"] == wording
        assert get_entry(connection, eid)["status"] == "awaiting_evidence_review"


@pytest.mark.parametrize(
    "wording",
    [
        "Who approves maintenance?",
        "They must inspect turbines.",
        "Turbines maybe whatever",
        "Engineers must inspect turbines by 2026-08-01.",
        "Engineers must inspect turbines in July 2026.",
        "Engineers must inspect turbines in 2025.",
    ],
)
def test_unsupported_or_ambiguous_intake_stays_pending(wording, ledger):
    with connect(ledger) as connection:
        eid = submit_claim(connection, wording)[0]
        entry = get_entry(connection, eid)
        assert entry["status"] == "awaiting_clarification"
        assert entry["claim_id"] is None
        with pytest.raises(ValueError, match="Resolve"):
            begin_review(connection, eid, "reviewer", AS_OF)
        assert not knowledge_risks(connection)["flags"]


def test_compounds_preserve_all_components_and_do_not_split_noun_and():
    text = "Engineers must inspect turbines. Operators must close valves."
    intake = interpret_claim(text)
    assert [p.claim.subject for p in intake.parts] == ["Engineers", "Operators"]
    assert [p.text for p in intake.parts] == [
        "Engineers must inspect turbines.",
        "Operators must close valves.",
    ]
    joined = interpret_claim("Engineers must inspect turbines and operators must close valves.")
    assert len(joined.parts) == 2
    nouns = interpret_claim("The policy requires seals and valves.")
    assert len(nouns.parts) == 1 and nouns.parts[0].claim.object == "seals and valves"
    partial = interpret_claim("Engineers must inspect turbines; log findings.")
    assert len(partial.parts) == 2 and partial.parts[1].status == "awaiting_clarification"


def test_clarification_merges_target_and_retains_history(ledger):
    from decidr.conversation import create_conversation, send_message

    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, "Engineers are assigned to turbine inspections.")
        original = entries(c)[0]
        send_message(c, cid, "Actual practice")
        entry = entries(c)[-1]
        assert entry["original_wording"] == "Engineers are assigned to turbine inspections."
        assert entry["intake"]["claim"]["evidence_target"] == "actual_practice"
        assert entry["status"] == "completed_assessment"
        assert get_entry(c, original["entry_id"]) == original


def test_manual_fallback_retains_original_and_clarification(ledger):
    with connect(ledger) as c:
        eid = submit_claim(c, "Engineers inspect turbines.")[0]
        clarify_claim(c, eid, "This describes actual practice.")
        claim = AtomicClaim(
            claim_id="ignored",
            subject="Engineers",
            predicate="inspect",
            object="turbines",
            claim_text="Engineers inspect turbines.",
            claim_type="employee_entered",
            evidence_target="actual_practice",
        )
        review_interpretation(
            c,
            eid,
            claim,
            reviewer="Reviewer",
            reason="Single action; original values and added target preserved.",
        )
        entry = get_entry(c, eid)
        assert entry["original_wording"] == "Engineers inspect turbines."
        assert entry["interpretation_review"]["context"].endswith(
            "This describes actual practice."
        )
        assert entry["status"] == "awaiting_evidence_review"


def test_full_reviewed_claim_assessment_uses_real_retrieval_review_and_reasoning(ledger):
    with connect(ledger) as c:
        eid, run = start(c)
        assert [r["evidence_id"] for r in get_run(c, run)["packet"]["results"]] == ["E-S1"]
        judge(c, run)
        result = finish(c, run)
        assert result["outcome"] == "Supported"
        assert result["confidence"] == "Moderate confidence"
        assert result["supporting_evidence"][0]["source_id"] == "S1"
        assert result["claim"]["claim_text"] == CLAIM
        assert get_entry(c, eid)["status"] == "completed_assessment"
        assert c.execute("SELECT COUNT(*) FROM claim_assessments").fetchone()[0] == 0
        assert result["runtime_metadata"]["llm_used"] is False
        assert (
            result["runtime_metadata"]["corpus_fingerprint"]
            == corpus_state(c)["corpus_fingerprint"]
        )


def test_proposals_missing_reviews_and_empty_relationship_sets_do_not_complete(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        with pytest.raises(ValueError, match="Every candidate"):
            finish(c, run)
        judge(c, run, proposed=True)
        graph = review_graph(get_run(c, run), review_notes(c, run))
        assert any(a["validation_status"] == "proposed" for *_, a in graph.edges(data=True))
        with pytest.raises(ValueError, match="Every candidate"):
            finish(c, run)
        judge(c, run)
        finish(c, run)
        with pytest.raises(ValueError, match="immutable"):
            judge(c, run)


def test_novel_topic_does_not_invent_answer_and_empty_review_requires_receipt(ledger):
    with connect(ledger) as c:
        _, run = start(c, "Xylophonic widgets shall oscillate extraterrestrially.")
        assert get_run(c, run)["packet"]["results"] == []
        with pytest.raises(ValueError, match="additional information"):
            finish(c, run)
        result = finish(
            c,
            run,
            settlement="Obtain the applicable widget operating rule and its effective date.",
        )
        assert result["outcome"] == "Insufficient evidence"
        assert "No relevant evidence retrieved" in result["evidence_gaps"][0]
        assert result["responsible_roles"] == []
        assert result["supporting_evidence"] == []


def test_metadata_eligibility_rejects_archived_and_misnamed_sources(ledger):
    with connect(ledger) as c:
        seed(c, "phase2:ARCHIVE", release="phase1")
        seed(c, "FAILED", source_updates={"ingestion_status": "failed"})
        seed(
            c,
            "EXCLUDED",
            source_updates={"ingestion_status": "excluded", "exclusion_reason": "annotation"},
        )
        seed(
            c,
            "CONFLICT",
            release="phase1",
            evidence_updates={"structured_metadata": {"release": "phase2"}},
        )
        packet = search_evidence(c, "inspect turbines")
        assert [r["source_id"] for r in packet["results"]] == ["S1"]
        claim = interpret_claim(CLAIM).parts[0].claim
        assert [r.source_id for r in lexical_search(c, claim)] == ["S1"]


def test_optional_semantic_failure_preserves_lexical_results(ledger):
    class Broken:
        name = "broken-local"
        version = "fixture"

        def encode(self, texts):
            raise RuntimeError("local model failed")

    with connect(ledger) as c:
        before = len(entries(c))
        packet = search_evidence(c, "inspect turbines", semantic=True, embedder=Broken())
        assert packet["method"] == "lexical" and "RuntimeError" in packet["semantic_status"]
        assert packet["results"][0]["evidence_id"] == "E-S1"
        assert len(entries(c)) == before


def test_shared_origins_keep_chain_but_count_once(ledger):
    with connect(ledger) as c:
        seed(c, "S2", source_updates={"derived_from_source_id": "S1"})
        seed(c, "S3", source_updates={"derived_from_source_id": "S2"})
        _, run = start(c)
        for sid in ("S1", "S2", "S3"):
            judge(c, run, "E-" + sid)
        result = finish(c, run)
        assert result["outcome"] == "Supported" and result["confidence"] == "Moderate confidence"
        assert len(result["source_groups"]) == 1
        assert len(result["dependent_evidence_groups"]) == 2
        graph = review_graph(get_run(c, run), review_notes(c, run))
        assert graph.has_edge("S3", "S2") and graph.has_edge("S2", "S1")
        assert "unknown" in result["dependence_note"]


def test_same_origin_conflict_is_not_discarded(ledger):
    with connect(ledger) as c:
        seed(
            c,
            "S2",
            text="Engineers must not inspect turbines within 48 hours.",
            source_updates={"derived_from_source_id": "S1"},
        )
        _, run = start(c)
        judge(c, run)
        judge(c, run, "E-S2", relationship="contradict")
        result = finish(
            c,
            run,
            settlement="Obtain the approved wording resolving this internally inconsistent origin.",
        )
        assert result["outcome"] == "Contested"
        assert result["confidence"] != "Higher confidence"


def test_policy_and_practice_are_distinct(ledger):
    with connect(ledger) as c:
        seed(
            c,
            "MEETING",
            text="In practice engineers inspect turbines after 96 hours.",
            source_updates={"source_type": "meeting"},
        )
        _, run = start(c)
        judge(c, run)
        judge(
            c,
            run,
            "E-MEETING",
            relationship="contradict",
            mode="observed_practice",
            risks=["policy_practice_divergence"],
            risk_reason="Observed 96 hours differs from the prescribed 48 hours.",
        )
        result = finish(c, run)
        assert result["outcome"] == "Supported"
        assert any(t["details"].get("divergence_visible") for t in result["rules_applied"])
        assert any(f["kind"] == "policy_practice_divergence" for f in result["risk_flags"])


@pytest.mark.parametrize(
    "date_text,expected", [("2024-06-01", "Supported"), ("2026-06-01", "Insufficient evidence")]
)
def test_explicit_supersession_applies_rule_at_event_date(ledger, date_text, expected):
    with connect(ledger) as c:
        seed(
            c,
            source_updates={
                "effective_start_date": date(2020, 1, 1),
                "lifecycle_status": "superseded",
                "successor_source_id": "S2",
            },
        )
        # Successor need not match the search; source graph still establishes its dates.
        seed(
            c,
            "S2",
            text="Replacement instruction.",
            source_updates={
                "effective_start_date": date(2025, 1, 1),
                "predecessor_source_id": "S1",
            },
        )
        _, run = start(c, CLAIM.rstrip(".") + " on " + date_text + ".")
        for record in get_run(c, run)["packet"]["results"]:
            if record["evidence_id"] == "E-S1":
                judge(c, run)
            else:
                judge(c, run, record["evidence_id"], relationship="contextual")
        result = finish(c, run, settlement="Retrieve and review the applicable replacement rule.")
        assert result["outcome"] == expected
        if expected == "Insufficient evidence":
            assert any("successor" in x["exclusion_reason"] for x in result["material_exclusions"])


def test_old_but_effective_source_not_invalid_merely_due_to_age(ledger):
    with connect(ledger) as c:
        seed(
            c,
            source_updates={
                "creation_date": date(2010, 1, 1),
                "effective_start_date": date(2010, 1, 1),
            },
        )
        _, run = start(c)
        judge(c, run)
        assert finish(c, run)["outcome"] == "Supported"


def test_unknown_effective_dates_require_reviewed_basis(ledger):
    with connect(ledger) as c:
        seed(c, source_updates={"effective_start_date": None})
        _, run = start(c)
        judge(c, run)
        result = finish(
            c, run, settlement="Obtain effective-date confirmation for the instruction."
        )
        assert result["outcome"] == "Insufficient evidence"
        assert any(
            "No effective date" in item["exclusion_reason"]
            for item in result["material_exclusions"]
        )


@pytest.mark.parametrize(
    "wording,expected",
    [
        ("The register records turbine inspections within 48 hours.", "Supported"),
        (
            "In practice, turbine inspections are completed within 48 hours.",
            "Insufficient evidence",
        ),
    ],
)
def test_populated_noisy_records_do_not_establish_actual_or_intended_values(
    ledger, wording, expected
):
    with connect(ledger) as c:
        seed(
            c,
            source_updates={"source_type": "crm_records"},
            text="Turbine inspections: elapsed_hours=48; correction note: may be 96, unverified.",
            evidence_updates={"extraction_method": "csv_dict_row_v1"},
        )
        _, run = start(c, wording)
        judge(
            c,
            run,
            mode="observed_practice",
            risks=["data_quality"],
            risk_reason="Correction is explicitly uncertain.",
            gaps=["The intended duration is not independently corroborated."],
            settlement="Obtain dated inspection logs and confirm the correction.",
        )
        result = finish(c, run)
        assert result["outcome"] == expected
        assert result["risk_flags"][0]["evidence_ids"] == ["E-S1"]


def test_missing_approval_is_gap_not_contradiction(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        judge(
            c,
            run,
            relationship="qualify",
            gaps=["No approval record was retrieved."],
            settlement="Locate the approval record or ask the documented decision holder to verify it.",
        )
        result = finish(c, run)
        assert result["outcome"] == "Insufficient evidence"
        assert not result["contradicting_evidence"]
        assert result["evidence_gaps"]


def test_dashboard_flags_link_real_claim_and_reviewed_evidence(ledger):
    with connect(ledger) as c:
        eid, run = start(c)
        assert knowledge_risks(c)["assessed_claims"] == 0
        judge(
            c,
            run,
            risks=["unresolved_decision_rights"],
            risk_reason="This excerpt names no escalation decision holder.",
            gaps=["Escalation decision rights are undocumented here."],
            settlement="Obtain an approved delegation record.",
        )
        finish(c, run)
        dashboard = knowledge_risks(c)
        assert dashboard["registered_claims"] == dashboard["assessed_claims"] == 1
        assert all(
            f["entry_id"] == eid and f["run_id"] == run and f["evidence_ids"] == ["E-S1"]
            for f in dashboard["flags"]
        )


def test_sensitivity_same_reasoner_preserves_baseline_and_reviews(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        judge(c, run)
        result = finish(c, run)
        before = list(c.iterdump())
        scenario = sensitivity(c, run, remove_group=next(iter(result["source_groups"])))
        assert scenario["baseline"]["outcome"] == "Supported"
        assert scenario["alternative"]["outcome"] == "Insufficient evidence"
        assert list(c.iterdump()) == before
        with pytest.raises(ValueError, match="Allowed"):
            sensitivity(c, run, materiality_threshold=0.99)


def test_completed_snapshot_survives_corpus_change_but_pending_packet_invalidates(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        judge(c, run)
        finish(c, run)
        _, pending = start(c)
        seed(c, "ADDITIONAL")
        assert sensitivity(c, run)["baseline"]["outcome"] == "Supported"
        with pytest.raises(ValueError, match="ledger changed"):
            judge(c, pending)


def test_reviewed_reuse_requires_exact_meaning_and_cannot_see_heldout_claims(ledger):
    with connect(ledger) as c:
        heldout = AtomicClaim(
            claim_id="SEALED",
            subject="Engineers",
            predicate="must",
            object="inspect turbines",
            claim_text=CLAIM,
            claim_type="evaluation",
            evaluation_split="held_out",
        )
        save_claim(c, heldout)
        assert not entries(c) and reusable_match(c, CLAIM) is None
        eid, run = start(c)
        judge(c, run)
        finish(c, run)
        promote_claim(
            c,
            eid,
            reviewer="reviewer",
            reason="Reviewed complete meaning as reusable in the stated scope.",
        )
        assert reusable_match(c, CLAIM)["entry_id"] == eid
        assert reusable_match(c, CLAIM.replace("48", "72")) is None
        assert reusable_match(c, CLAIM.replace("must", "must not")) is None
        assert (
            c.execute("SELECT evaluation_split FROM claims WHERE claim_id='SEALED'").fetchone()[0]
            == "held_out"
        )


def test_responsible_role_requires_exact_evidence_quote_and_cannot_be_guessed(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        with pytest.raises(ValueError, match="quoted"):
            judge(
                c,
                run,
                responsible_role="Chief Executive",
                role_quote="The Chief Executive is responsible.",
            )
        judge(c, run)
        assert "No responsible role documented" in finish(c, run)["responsibility_note"]


def test_long_print_export_is_complete_escaped_and_has_no_fixed_height(ledger):
    text = (
        CLAIM
        + "\n"
        + ('<script>alert("untrusted")</script> complete evidence ' * 900)
        + " END-OF-EXCERPT"
    )
    with connect(ledger) as c:
        seed(c, text=text)
        _, run = start(c)
        judge(c, run)
        result = finish(c, run)
    html = claim_report_html(result)
    assert "END-OF-EXCERPT" in html and "&lt;script&gt;" in html
    assert '<script>alert("untrusted")</script>' not in html
    assert html.count("<script>") == 1  # Static report filter; evidence remains escaped.
    assert "max-height:none" in html and "break-inside:auto" in html
    assert CLAIM in html and "Moderate confidence" in html
    assert len(html) > len(text)


def test_graph_limits_and_added_evidence_are_not_automatic_support(ledger):
    with connect(ledger) as c:
        seed(c, "OTHER", text="Unrelated archive entries.")
        _, run = start(c)
        add_evidence(c, run, "E-OTHER")
        with pytest.raises(ValueError, match="Every candidate"):
            finish(c, run)
        graph = review_graph(get_run(c, run), {}, limit=3)
        assert len(graph) <= 3
        assert all(
            a["relationship"] not in {"support", "contradict"} for *_, a in graph.edges(data=True)
        )


@pytest.mark.parametrize(
    "text",
    [
        "Engineers must inspect.",
        "If engineers must inspect turbines.",
        "The register records 2025-06-01 as the scheduled date.",
    ],
)
def test_incomplete_grammar_and_record_date_values_are_not_silently_accepted(text):
    part = interpret_claim(text).parts[0]
    assert part.status == "awaiting_clarification" and part.claim is None


def test_without_condition_does_not_invert_the_main_proposition():
    part = interpret_claim(
        "Engineers must inspect turbines without shutting down the site."
    ).parts[0]
    assert part.claim.proposition_polarity == "positive"
    assert part.claim.conditions == ["without shutting down the site."]


def test_uningested_source_not_eligible(ledger):
    with connect(ledger) as c:
        seed(c, "REGISTERED", source_updates={"ingestion_status": "registered"})
        assert [r["source_id"] for r in search_evidence(c, "inspect turbines")["results"]] == [
            "S1"
        ]


def test_confirmation_of_actual_values_requires_independent_evidence_references(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        with pytest.raises(ValueError, match="other evidence IDs"):
            judge(c, run, intended_value_confirmed=True)


def test_snapshot_date_excludes_sources_created_later(ledger):
    with connect(ledger) as c:
        seed(c, source_updates={"creation_date": date(2026, 8, 1)})
        _, run = start(c)
        judge(c, run)
        result = finish(
            c, run, settlement="Obtain evidence available at the chosen snapshot date."
        )
        assert result["outcome"] == "Insufficient evidence"
        assert any("created after" in e["exclusion_reason"] for e in result["material_exclusions"])


def test_clarified_meaning_is_not_silently_reused_for_same_ambiguous_words(ledger):
    with connect(ledger) as c:
        text = "Turbine inspections are completed within 48 hours."
        eid = submit_claim(c, text, target="actual_practice")[0]
        run = begin_review(c, eid, "reviewer", AS_OF)
        judge(c, run, mode="observed_practice")
        finish(c, run)
        promote_claim(
            c, eid, reviewer="reviewer", reason="Original and clarified target reviewed."
        )
        assert reusable_match(c, text) is None


def test_allowed_credibility_sensitivity_changes_outcome_without_rewriting(ledger):
    with connect(ledger) as c:
        _, run = start(c)
        judge(c, run, dimensions={key: 0.55 for key in DIMENSIONS})
        finish(c, run)
        alternative = sensitivity(c, run, materiality_threshold=0.6)
        assert alternative["baseline"]["outcome"] == "Supported"
        assert alternative["alternative"]["outcome"] == "Insufficient evidence"
        assert "No decisive applicable evidence remains" in alternative["reason"]
        assert get_run(c, run)["result"]["outcome"] == "Supported"


def test_explorer_graph_uses_metadata_and_never_adds_ineligible_source_nodes(ledger):
    from decidr.claim_graph import source_neighbourhood

    with connect(ledger) as c:
        seed(c, "phase2:FAKE", release="phase1")
        graph = source_neighbourhood(c, "E-S1")
        assert "S1" in graph and "E-S1" in graph
        assert "phase2:FAKE" not in graph
        assert not entries(c)


def test_lowercase_second_sentence_is_a_separate_assessable_statement():
    intake = interpret_claim("Engineers must inspect turbines. operators must close valves.")
    assert len(intake.parts) == 2
    assert [p.claim.subject for p in intake.parts] == ["Engineers", "operators"]


def test_successful_local_semantics_reports_actual_hybrid_execution(ledger):
    class LocalEmbedder:
        name = "development-local"
        version = "1"

        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    with connect(ledger) as c:
        packet = search_evidence(c, "inspect turbines", semantic=True, embedder=LocalEmbedder())
        assert packet["method"] == "hybrid"
        assert "Available locally" in packet["semantic_status"]
        assert packet["results"][0]["lexical_rank"] == packet["results"][0]["semantic_rank"] == 1
