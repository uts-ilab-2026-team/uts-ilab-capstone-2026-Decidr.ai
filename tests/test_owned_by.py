"""Tests for OWNED_BY emission (document -> owning PERSON, graph structure only).

The owner is resolved from the header to a PERSON node (owner != decision-right holder); the edge
records whether that person is still active. Documents with no resolvable named person owner get no
edge. These unit-test _add_owned_by directly with a hand-built builder.
"""

from types import SimpleNamespace

from decidr.backbone import _GraphBuilder, _add_owned_by


def _builder() -> _GraphBuilder:
    builder = _GraphBuilder()
    builder.add_node("person:harriet-doyle", "person", "Harriet Doyle", {"status": "active"})
    builder.add_node("person:wei-zhang", "person", "Wei Zhang", {"status": "inactive"})
    for code in ("POL-01", "POL-09", "PROC-07", "POL-X", "INT-02"):
        builder.add_node(f"document:{code}", "document", code, {})
    return builder


def _src(source_id: str, owner: str | None):
    return SimpleNamespace(source_id=source_id, responsible_person_or_role=owner)


def test_links_document_to_active_owner():
    builder = _builder()
    _add_owned_by(
        builder,
        [_src("phase1:POL-01", "Harriet Doyle, Head of Finance & People Ops")],
        {"phase1:POL-01": "document:POL-01"},
    )
    edge = builder.edges["owned_by:document:POL-01->person:harriet-doyle"]
    assert edge.relationship == "OWNED_BY"
    assert edge.target == "person:harriet-doyle"
    assert edge.attributes["owner_active"] is True
    assert builder.warnings == []


def test_flags_owner_who_has_left():
    builder = _builder()
    _add_owned_by(
        builder,
        [_src("phase1:POL-09", "Wei Zhang, Former Lead")],
        {"phase1:POL-09": "document:POL-09"},
    )
    edge = builder.edges["owned_by:document:POL-09->person:wei-zhang"]
    assert edge.attributes["owner_active"] is False
    assert any("no longer active" in w for w in builder.warnings)


def test_collective_owner_gets_no_edge():
    builder = _builder()
    _add_owned_by(
        builder,
        [_src("phase1:PROC-07", "Jointly maintained by Sales and Customer Success & Delivery")],
        {"phase1:PROC-07": "document:PROC-07"},
    )
    assert not any(e.relationship == "OWNED_BY" for e in builder.edges.values())


def test_named_owner_not_in_roster_gets_no_edge():
    builder = _builder()
    _add_owned_by(
        builder,
        [_src("phase1:POL-X", "Jane External, Consultant")],
        {"phase1:POL-X": "document:POL-X"},
    )
    assert not any(e.relationship == "OWNED_BY" for e in builder.edges.values())
    assert any("not in roster" in w for w in builder.warnings)


def test_missing_owner_is_skipped():
    builder = _builder()
    _add_owned_by(builder, [_src("phase1:POL-01", None)], {"phase1:POL-01": "document:POL-01"})
    assert not any(e.relationship == "OWNED_BY" for e in builder.edges.values())


def test_committed_graph_has_owned_by_edges():
    import json
    import pathlib

    graph = json.loads(
        pathlib.Path("decidr/graph/data/corpus_graph.json").read_text(encoding="utf-8")
    )
    owned = [e for e in graph["edges"] if e["relationship"] == "OWNED_BY"]
    assert len(owned) == 14
    pol01 = next(e for e in owned if e["source"] == "document:POL-01")
    assert pol01["target"] == "person:harriet-doyle"
    assert pol01["attributes"]["owner_active"] is True
