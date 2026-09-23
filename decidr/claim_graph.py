"""Bounded employee graph views retain review state and intermediate source origins."""

from urllib.parse import urlencode

import networkx as nx


def evidence_dispositions(result):
    """One final disposition per candidate, shared by graph, page and export."""
    dispositions = {}
    decisive = {
        eid
        for trace in result.get("rules_applied", [])
        if trace["rule_id"].startswith("R4_")
        for eid in trace["evidence_ids"]
    }
    for key in (
        "supporting_evidence",
        "contradicting_evidence",
        "qualifying_evidence",
        "contextual_evidence",
        "divergence_evidence",
    ):
        for item in result.get(key, []):
            dispositions[item["evidence_id"]] = {
                **item,
                "disposition": "used",
                "decisive": item["evidence_id"] in decisive,
            }
    for key in ("not_applicable_evidence", "dependent_evidence_groups"):
        for item in result.get(key, []):
            dispositions[item["evidence_id"]] = {
                **item,
                "disposition": "excluded",
                "decisive": False,
            }
    for item in result.get("unclassified_evidence", []):
        dispositions[item["evidence_id"]] = {
            **item,
            "disposition": "unclassified",
            "decisive": False,
        }
    return dispositions


def review_graph(
    run: dict,
    notes: dict,
    *,
    seed: str | None = None,
    limit=100,
    conversation_id=None,
    targets=None,
    dispositions=None,
) -> nx.MultiDiGraph:
    """Bounded view of a frozen snapshot; every hidden candidate is counted."""
    from decidr.assessment_snapshot import presentation

    if not 1 <= limit <= 100:
        raise ValueError("Graph limit must be between 1 and 100")
    graph = nx.MultiDiGraph()
    result = run.get("result")
    claim = result["claim"] if result else run["claim"]
    claim_id = claim["claim_id"]
    graph.add_node(claim_id, kind="claim", label=claim["claim_text"])
    records = result["evidence_records"] if result else run["packet"]["results"]
    findings = presentation(result)["findings"] if result else []
    selected = []
    for index, item in enumerate(records, 1):
        eid, sid = item["evidence_id"], item["source_id"]
        assessed = [
            f
            for f in findings
            if f["evidence_id"] == eid
            and (targets is None or f["assessment_target"] in targets)
            and (dispositions is None or f["disposition"] in dispositions)
        ]
        if (seed and eid != seed) or (result and not assessed):
            continue
        selected.append(eid)
        needed = int(eid not in graph) + int(sid not in graph)
        if len(graph) + needed > limit:
            continue
        locator = item["locator"].split(" > ")[-1].split("#block:")[0].removeprefix("heading:")
        params = {"source": sid, "evidence": eid}
        if result:
            params["assessment"] = run["run_id"]
        if conversation_id:
            params["conversation"] = conversation_id
        graph.add_node(
            eid,
            kind="evidence",
            label=f"E{index} · {locator}",
            tooltip=item["text"],
            URL="?" + urlencode(params),
        )
        graph.add_node(
            sid,
            kind="source",
            label=item["source"]["title"],
            URL="?" + urlencode({k: v for k, v in params.items() if k != "evidence"}),
            tooltip=item["source"]["title"],
        )
        graph.add_edge(eid, sid, relationship="EXTRACTED_FROM", validation_status="ingested")
        if not result:
            note = notes.get(eid)
            assessed = [
                {
                    "relationship": note["link"]["relationship"] if note else "RETRIEVED_MATCH",
                    "disposition": "proposed",
                    "assessment_target": run["claim"].get("evidence_target")
                    or "all_relevant_evidence",
                }
            ]
        for finding in assessed:
            state, relation = finding["disposition"], finding["relationship"]
            target = finding["assessment_target"]
            note = (
                (result or {})
                .get("target_findings", {})
                .get(target, {})
                .get("review_snapshot", notes)
                .get(eid, {})
            )
            link = note.get("link", {})
            graph.add_edge(
                eid,
                claim_id,
                relationship="unclassified"
                if state == "unclassified"
                else "excluded"
                if state == "excluded"
                else relation,
                assessed_relationship=relation,
                assessment_target=target,
                disposition=state,
                finding_id=finding.get("finding_id"),
                decisive=finding.get("decisive", False),
                tooltip=finding.get("reason", ""),
                validation_status="reviewed"
                if link.get("method") == "human_review" and link.get("review_status") == "complete"
                else "unclassified"
                if state == "unclassified"
                else "system_classified"
                if link.get("method") == "automatic"
                else "proposed",
                reviewer=link.get("reviewer"),
            )
    queue = [n for n, a in graph.nodes(data=True) if a["kind"] == "source"]
    visited, hidden_origins = set(), set()
    while queue:
        sid = queue.pop(0)
        if sid in visited:
            continue
        visited.add(sid)
        source = run["source_graph"].get(sid, {})
        links = [
            (source.get("derived_from_source_id"), "DERIVED_FROM"),
            (source.get("predecessor_source_id"), "SUPERSEDES"),
        ]
        links += [
            (notes.get(r["evidence_id"], {}).get("origin_source_id"), "REVIEWED_ORIGIN")
            for r in records
            if r["source_id"] == sid
        ]
        for target, relation in links:
            if not target or target not in run["source_graph"]:
                continue
            if target not in graph and len(graph) >= limit:
                hidden_origins.add(target)
                continue
            params = {"source": target, "assessment": run["run_id"]}
            if conversation_id:
                params["conversation"] = conversation_id
            graph.add_node(
                target,
                kind="source",
                label=run["source_graph"][target]["title"],
                URL="?" + urlencode(params),
            )
            graph.add_edge(
                sid, target, relationship=relation, validation_status="explicit_metadata"
            )
            queue.append(target)
    shown = sum(a["kind"] == "evidence" for _, a in graph.nodes(data=True))
    graph.graph.update(
        evidence_shown=shown,
        evidence_total=len(records),
        evidence_filtered=len(records) - len(selected),
        evidence_omitted_by_limit=len(selected) - shown,
        provenance_omitted_by_limit=len(hidden_origins),
        nodes_shown=len(graph),
        node_limit=limit,
        findings_shown=sum("assessment_target" in a for *_, a in graph.edges(data=True)),
        findings_total=len(findings),
    )
    return graph


def source_neighbourhood(connection, evidence_id: str, *, depth=2, limit=40):
    """Inspect bounded provenance around a search match without creating a claim."""
    from decidr.graph import build_ledger_graph

    if not 1 <= depth <= 3 or not 1 <= limit <= 100:
        raise ValueError("Graph bounds: depth 1–3, nodes 1–100")
    graph = build_ledger_graph(connection)
    if evidence_id not in graph:
        raise ValueError("No eligible evidence node with this ID")
    selected = {evidence_id}
    frontier = [evidence_id]
    for _ in range(depth):
        following = []
        for node in frontier:
            for neighbour in sorted(set(graph.predecessors(node)) | set(graph.successors(node))):
                if neighbour not in selected and len(selected) < limit:
                    selected.add(neighbour)
                    following.append(neighbour)
        frontier = following
    return graph.subgraph(selected).copy()
