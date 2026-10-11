import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import AssessmentGraph, { unifiedGraph } from "../src/AssessmentGraph";
import ConnectedEvidence from "../src/ConnectedEvidence";
import type { SuppliedResult } from "../src/suppliedAssessmentContract";

const citation = {evidence_id: "passage-42", source_id: "source-ledger", locator: "row:42", quotation: "<original ledger record>", start: 0, end: 24};
function graphFixture() {
  return {claim_text: "An unfamiliar transaction claim", facet: "An unfamiliar transaction claim", as_of: "2026-04-01",
    assessment: {evidence: []}, inputs: [{input_id: "input-42", source: {source_id: citation.source_id, title: "Ledger", creation_date: "2026-03-01"},
      interpretation: {mode: "observed", stance: "qualify", rationale: "Timing remains unknown", citations: [citation]},
      admitted_to_framework: false, edge_id: null, supplied_judgements: {temporal_matches: true}, reasons: ["Independence unresolved"]}],
    transaction_assessment: {components: [{field: "approval", label: "Named approval", status: "supported", observations: [{status: "supported", evidence_id: citation.evidence_id, reason: "Record reports approval."}]}],
      citations: [citation], connections: [{evidence_id: citation.evidence_id, relationship: "record_itself"}]},
    evidence_synthesis: {summary: "Connected records", notice: "Context is not proof.", future_evidence_excluded: 0, questions: [], comparisons: [],
      nodes: [{id: "context-ledger", citation, source_id: citation.source_id, source_title: "Ledger", record_id: "CASE-842", lane: "documented", relationship: "record_documentation", reason: "Record metadata", temporal_status: "current", details: {}, limitations: []},
        {id: "context-role", citation: {...citation, evidence_id: "role-passage", source_id: "source-role", quotation: "<recorded role>"}, source_id: "source-role", source_title: "Role record", record_id: null, lane: "formal", relationship: "role_context", reason: "Role, not adoption rights", temporal_status: "date_not_established", details: {}, limitations: ["Authority unresolved"]}],
      edges: [{from: "claim", to: "context-ledger", relationship: "exact_record_reference", basis: "Record identifier"}, {from: "context-ledger", to: "context-role", relationship: "recorded_person_role", basis: "Exact recorded person"}]},
  } as unknown as SuppliedResult;
}

test("unified graph merges passage evidence and keeps exact citations, findings and explicit edges", () => {
  const result = graphFixture(), before = JSON.stringify(result);
  const graph = unifiedGraph(result);
  assert.equal(graph.nodes.length, 2);
  const used = graph.nodes.filter(node => node.used);
  assert.equal(used.length, 1);
  assert.deepEqual(used[0].citations, [citation]);
  assert.equal(used[0].inputs.length, 1);
  assert.equal(used[0].findings[0].status, "supported");
  assert.equal(graph.nodes[1].used, false);
  assert.ok(graph.edges.some(edge => edge.relationship === "recorded_person_role" && edge.from === used[0].id && edge.to === graph.nodes[1].id));
  assert.equal(JSON.stringify(result), before);
});

test("unified graph does not join an evidence identifier across different sources", () => {
  const result = graphFixture();
  result.evidence_synthesis!.nodes[1].citation.evidence_id = citation.evidence_id;
  const graph = unifiedGraph(result);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.nodes.find(node => node.sourceId === "source-role")!.findings.length, 0);
  result.transaction_assessment!.citations.push({...citation, source_id: "source-role"});
  assert.equal(unifiedGraph(result).nodes.filter(node => node.used).length, 0);
});

test("unified graph retains separate exact quotation spans from one passage", () => {
  const result = graphFixture();
  const excerpt = {...citation, start: 1, end: 9, quotation: "original"};
  result.evidence_synthesis!.nodes[0].citation = excerpt;
  const node = unifiedGraph(result).nodes[0];
  assert.equal(node.citations.length, 2);
  assert.deepEqual(node.citations[1], excerpt);
});

test("unified graph puts unscored input-only context and future inputs outside the conclusion", () => {
  const result = graphFixture();
  result.transaction_assessment!.components = [];
  result.inputs[0].supplied_judgements.temporal_matches = false;
  result.inputs[0].admitted_to_framework = true;
  const graph = unifiedGraph(result);
  assert.equal(graph.nodes.filter(node => node.used).length, 0);
  assert.ok(graph.nodes[0].contexts.some(context => context.relationship === "excluded"));
  const future = graphFixture();
  future.inputs[0].source.creation_date = "2026-05-01";
  assert.equal(unifiedGraph(future).nodes.filter(node => node.used).length, 0);
});

test("unified graph renders one root and filter set, with related context hidden by default", () => {
  const result = graphFixture();
  const html = renderToStaticMarkup(<AssessmentGraph result={result} onOpen={() => {}} openSignal={1}/>);
  assert.equal((html.match(/Claim being assessed/g) ?? []).length, 1);
  assert.equal((html.match(/aria-label="Evidence graph lane"/g) ?? []).length, 1);
  assert.ok(html.includes("Include related context · 1"));
  assert.ok(html.includes("Named approval: supported"));
  assert.ok(html.includes("&lt;original ledger record&gt;"));
  assert.ok(!html.includes("Credibility scoring inputs"));
  assert.ok(!html.includes("Role record"));
  assert.ok(!html.includes('<div hidden="">'));
  const graph = unifiedGraph(result);
  const detail = renderToStaticMarkup(<ConnectedEvidence node={graph.nodes[0]} graph={graph} result={result} onOpen={() => {}} onSelect={() => {}} onClose={() => {}}/>);
  for (const expected of ["Not admitted to framework scoring", "Record reports approval.", "row:42", "Role record", "Exact recorded person", "Independence unresolved"]) assert.ok(detail.includes(expected), expected);
});
