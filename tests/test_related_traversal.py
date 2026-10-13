"""Tests for the RELATED enhancement: parse 'Related documents:', emit edges, traverse one hop.

Covers the three touch-points:
  * ingestion parsing of the header line into Source.related_source_codes,
  * the directed single-hop traversal (decidr.assess_claim._related_codes), including that the
    RELATED-only view ignores GOVERNS out-edges,
  * a realistic assertion against the committed skeleton (POL-01 -> POL-06, the demo path).
"""

from decidr.assess_claim import _related_codes, _related_view
from decidr.backbone_assessment import load_skeleton
from decidr.ingestion import _related_source_codes
from framework.graph import OrganisationalGraph
from framework.models import GraphEdge, GraphNode


# --------------------------------------------------------------------------- #
# ingestion: header line -> codes                                             #
# --------------------------------------------------------------------------- #


def test_parse_related_line_extracts_codes():
    value = "PROC-02 (Discount Approval Process), POL-06 (Contract Renewal Discount Policy)"
    assert _related_source_codes(value, "POL-01") == ["PROC-02", "POL-06"]


def test_parse_related_none_formally_linked():
    assert _related_source_codes("None formally linked.", "POL-05") == []


def test_parse_related_drops_self_reference_and_dedupes():
    assert _related_source_codes("POL-01, POL-06, POL-06", "POL-01") == ["POL-06"]


def test_parse_related_missing_value():
    assert _related_source_codes(None, "POL-01") == []


# --------------------------------------------------------------------------- #
# traversal: directed, one hop, RELATED only                                  #
# --------------------------------------------------------------------------- #


def _doc(code: str) -> GraphNode:
    return GraphNode(f"document:{code}", "document", code, {})


def _rel(src: str, dst: str) -> GraphEdge:
    return GraphEdge(f"related:{src}->{dst}", f"document:{src}", f"document:{dst}", "RELATED", {})


def _fixture_graph() -> OrganisationalGraph:
    nodes = [_doc("POL-01"), _doc("POL-06"), _doc("PROC-02"), GraphNode("process:x", "process", "X")]
    edges = [
        _rel("POL-01", "PROC-02"),
        _rel("POL-01", "POL-06"),
        _rel("POL-06", "POL-01"),  # reciprocal, but one hop means no loop
        # a GOVERNS out-edge on POL-01 that the RELATED-only view must ignore:
        GraphEdge("governs:POL-01->x", "document:POL-01", "process:x", "GOVERNS", {}),
    ]
    return OrganisationalGraph(nodes, edges, version="test")


def test_directed_one_hop_follows_stated_links():
    graph = _fixture_graph()
    assert _related_codes(["POL-01"], graph) == ["PROC-02", "POL-06"]


def test_process_doc_declares_nothing_expands_to_nothing():
    graph = _fixture_graph()
    assert _related_codes(["PROC-02"], graph) == []


def test_governing_set_is_excluded_from_expansion():
    graph = _fixture_graph()
    # PROC-02 is already governed, so only POL-06 is the fresh related expansion.
    assert _related_codes(["POL-01", "PROC-02"], graph) == ["POL-06"]


def test_related_view_ignores_governs_edges():
    graph = _fixture_graph()
    view = _related_view(graph)
    targets = set(view.successors("document:POL-01"))
    assert targets == {"document:PROC-02", "document:POL-06"}  # process:x (GOVERNS) excluded


def test_one_hop_does_not_chain():
    # POL-01 -> POL-06 -> PROC-07 would be two hops; PROC-07 must NOT appear from POL-01.
    nodes = [_doc("POL-01"), _doc("POL-06"), _doc("PROC-07")]
    edges = [_rel("POL-01", "POL-06"), _rel("POL-06", "PROC-07")]
    graph = OrganisationalGraph(nodes, edges, version="test")
    assert _related_codes(["POL-01"], graph) == ["POL-06"]  # not PROC-07


# --------------------------------------------------------------------------- #
# realistic: the committed skeleton carries the demo path                     #
# --------------------------------------------------------------------------- #


def test_committed_skeleton_has_pol01_to_pol06():
    skeleton = load_skeleton()
    expanded = _related_codes(["POL-01"], skeleton)
    assert "POL-06" in expanded  # the demo-scripted related hop
    assert "PROC-02" in expanded
