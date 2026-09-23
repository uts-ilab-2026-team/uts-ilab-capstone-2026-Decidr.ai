"""Workflow/presentation invariants, separate from the development semantic scorecard."""

from copy import deepcopy
from html.parser import HTMLParser

from test_onboarding_assessment import onboarding  # noqa: F401 -- shared fixture

from decidr.assessment_snapshot import presentation
from decidr.claim_export import claim_report_html
from decidr.claim_graph import review_graph
from decidr.graph import to_graphviz


def test_graph_retains_each_target_and_discloses_every_hidden_candidate(onboarding):
    result = onboarding["result"]
    view = presentation(result)
    assert len(view["findings"]) == 3 * len(result["evidence_records"])
    graph = review_graph(onboarding, result["review_snapshot"], limit=100)
    edges = {a["finding_id"]: a for *_, a in graph.edges(data=True) if a.get("finding_id")}
    assert set(edges) == {f["finding_id"] for f in view["findings"]}
    for f in view["findings"]:
        edge = edges[f["finding_id"]]
        assert (edge["assessment_target"], edge["assessed_relationship"], edge["disposition"]) == (
            f["assessment_target"],
            f["relationship"],
            f["disposition"],
        )
    small = review_graph(onboarding, result["review_snapshot"], limit=3)
    counts = small.graph
    assert (
        counts["evidence_shown"]
        + counts["evidence_filtered"]
        + counts["evidence_omitted_by_limit"]
        == counts["evidence_total"]
    )
    assert counts["evidence_omitted_by_limit"] > 0
    empty = review_graph(onboarding, result["review_snapshot"], targets=[])
    assert empty.graph["evidence_shown"] == 0
    assert empty.graph["evidence_filtered"] == len(result["evidence_records"])
    filtered = review_graph(
        onboarding, result["review_snapshot"], targets=["prescribed_rule"], dispositions=["used"]
    )
    assert all(
        a["assessment_target"] == "prescribed_rule" and a["disposition"] == "used"
        for *_, a in filtered.edges(data=True)
        if a.get("finding_id")
    )


def test_snapshot_is_the_source_for_graph_exports_and_cited_actions(onboarding):
    baseline = deepcopy(onboarding)
    view = presentation(onboarding["result"])
    assert view is onboarding["result"]["presentation"]
    ids = {f["finding_id"] for f in view["findings"]}
    for action in view["recommendations"]:
        assert action["finding_ids"] or action.get("gap_ids") or action.get("limit_ids")
        assert set(action["finding_ids"]) <= ids

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.links = [], []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.ids.append(attrs["id"])
            if tag == "a" and attrs.get("href", "").startswith("#"):
                self.links.append(attrs["href"][1:])

    html = claim_report_html(onboarding["result"])
    links = Links()
    links.feed(html)
    assert set(links.links) <= set(links.ids)
    assert len(links.ids) == len(set(links.ids))
    titles = [
        "Supporting sources",
        "Contradicting sources",
        "Exceptions/practice differences",
        "Evidence gaps",
        "Recommended next action",
        "Expandable graph",
    ]
    assert [html.index(t) for t in titles] == sorted(html.index(t) for t in titles)
    assert onboarding == baseline
    altered = deepcopy(onboarding)
    altered["packet"]["results"] = []
    assert review_graph(altered, altered["result"]["review_snapshot"]).graph[
        "evidence_total"
    ] == len(baseline["result"]["evidence_records"])
    legacy = deepcopy(onboarding["result"])
    legacy.pop("presentation")
    original = deepcopy(legacy)
    assert "Historical result" in claim_report_html(legacy)
    assert presentation(legacy)["findings"]
    assert legacy == original


def test_long_graph_labels_wrap_without_losing_meaning(onboarding):
    run = deepcopy(onboarding)
    text = (
        "A complete claim with a carefully scoped exception and a different completion event " * 4
    )
    run["result"]["claim"]["claim_text"] = text
    graph = review_graph(run, run["result"]["review_snapshot"])
    dot = to_graphviz(graph)
    assert "completion event" in dot
    assert "\\n" in dot
    assert graph.nodes[run["claim"]["claim_id"]]["label"] == text


def test_historical_title_preserves_meaning_but_history_section_qualifies(onboarding):
    from decidr.automatic_evidence import classify_evidence
    from decidr.models import AtomicClaim

    record = deepcopy(
        next(
            r
            for r in onboarding["result"]["evidence_records"]
            if r["source_id"] == "phase2:POL-03" and "Formal requirements" in r["locator"]
        )
    )
    claim = AtomicClaim.model_validate(onboarding["claim"]).model_copy(
        update={"claim_text": "Standard onboarding is completed within 6 weeks of assignment."}
    )
    record["source"]["lifecycle_status"] = "superseded"
    record["locator"] = "heading:Policy [SUPERSEDED] > Formal requirements"
    assert classify_evidence(claim, record, "development")["link"]["relationship"] == "support"
    record["locator"] = "heading:Policy > Version history"
    assert classify_evidence(claim, record, "development")["link"]["relationship"] == "qualify"
