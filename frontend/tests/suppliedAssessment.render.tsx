import "./suppliedAssessment.test";
import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import SuppliedAssessment, { SuppliedResultView, SuppliedEvidenceDetail } from "../src/SuppliedAssessment";
import type { SuppliedResult } from "../src/suppliedAssessmentContract";
import ScopeClarification from "../src/ScopeClarification";
import { parseSuppliedRequest } from "../src/suppliedAssessmentContract";

test("clarification uses existing cards and exposes optional scope choices", () => {
  const html = renderToStaticMarkup(<ScopeClarification onAnswer={() => {}} context={{
    status: "clarification_available", question: "Which deal type?", options: ["New-business deals", "Renewal deals", "All deal types"],
    answer: null, facet: "Original", basis: [],
  }} />);
  for (const text of ["ev-card", "Which deal type?", "All deal types", "Continue without narrowing", "Another scope or explanation"])
    assert.ok(html.includes(text));
  assert.ok(!html.includes("Conditional outcome"));
});

test("selected scope is visible and does not become a verdict", () => {
  const html = renderToStaticMarkup(<ScopeClarification onAnswer={() => {}} context={{
    status: "scope_supplied", question: null, options: [], answer: "<custom scope>", facet: "Original", basis: [],
  }} />);
  assert.ok(html.includes("&lt;custom scope&gt;"));
  assert.ok(html.includes("Change scope"));
  assert.ok(html.includes("Evidence is still unassessed"));
});

test("prepared assessment must match the confirmed scoped facet", () => {
  const body = { claim_text: "Original", facet: "Original", as_of: "2026-06-17", inputs: [{}] };
  const facet = "Original\n\nScope supplied by user: Renewal deals";
  assert.throws(() => parseSuppliedRequest(JSON.stringify(body), "Original", facet), /scope/);
  body.facet = facet;
  assert.equal(parseSuppliedRequest(JSON.stringify(body), "Original", facet).facet, facet);
});

test("result retains qualification, exclusions and conditional disclosure", () => {
  const result = {
    claim_text: "Original claim", facet: "Exact facet", as_of: "2026-06-17",
    assessment_target: "formal_rule", config_version: "test",
    assurance: { notice: "Conditional on supplied judgements." },
    assessment: {
      overall_outcome: "Supported", formal_outcome: "Supported",
      observed_outcome: "Insufficient evidence", confidence: "Moderate confidence",
      summary: "Summary", evidence: [], gaps: ["Observed gap"], rules_applied: [],
    },
    inputs: [{
      input_id: "input:1", source: { title: "Interview", source_id: "source:1" },
      interpretation: {
        stance: "qualify", mode: "observed", rationale: "Scope is unresolved.",
        citations: [{ evidence_id: "e1", source_id: "source:1", locator: "paragraph:1",
          quotation: "<script>not executed</script>", start: 0, end: 29 }],
      },
      supplied_judgements: { authority_verified: null }, edge_id: null,
      admitted_to_framework: false, reasons: ["Scope gate failed."],
    }],
    limitations: ["Supplied assumptions."],
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedResultView result={result} />) +
    renderToStaticMarkup(<SuppliedEvidenceDetail result={result} item={result.inputs[0]} />);
  for (const expected of ["Original claim", "Exact facet", "Conditional outcome",
    "Conditional on supplied judgements.", "qualify", "Not scored · retained for review",
    "Scope gate failed.", "Observed gap", "Supplied assumptions.", "e1", "paragraph:1"]) {
    assert.ok(html.includes(expected), expected);
  }
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});
test("development entry starts collapsed with no result or prefilled judgements", () => {
  const html = renderToStaticMarkup(<SuppliedAssessment claim="Exact claim" />);
  assert.ok(html.includes("<details"));
  assert.ok(!html.includes("<details open"));
  assert.ok(!html.includes("Conditional outcome:"));
  assert.ok(html.includes("Automatic interpretation is not performed."));
  assert.ok(html.includes("disabled"));
});

import { PassageView, recordFields } from "../src/EvidenceUI";
import type { CorpusPassage } from "../src/api";
test("structured record presentation retains zero, false, and literal markup", () => {
  const evidence = { evidence_id: "e", source_id: "s", locator: "csv:row:2;id:1", source_type: "audit_events",
    text: '{"amount":0,"approved":false,"notes":"<script>literal</script>"}',
  } as CorpusPassage["evidence"];
  assert.deepEqual(recordFields(evidence), { amount: 0, approved: false, notes: "<script>literal</script>" });
  const html = renderToStaticMarkup(<PassageView evidence={evidence} />);
  assert.ok(html.includes(">0<"));
  assert.ok(html.includes(">false<"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("Exact stored record"));
  assert.equal(recordFields({ ...evidence, locator: "heading:Policy#block:001" }), null);
});

import AutomaticAssessment from "../src/AutomaticAssessment";
test("automatic entry uses existing cards, explicit date and no prepared JSON", () => {
  const html = renderToStaticMarkup(<AutomaticAssessment claim="Approval rule" />);
  assert.ok(html.includes("ev-card"));
  assert.ok(html.includes('type="date"'));
  assert.ok(html.includes("Assess claim and save result"));
  assert.ok(!html.includes("Prepared assessment request"));
  assert.ok(!html.includes("Review this result"));
});

test("automatic saved result is clearly distinguished from supplied judgements", () => {
  const result = {
    status: "assessed_automatically", persisted: true, claim_text: "Original", facet: "Facet",
    deployment_event_findings: [{status: "unresolved", event_id: "AUD-X", related_record: "INC-X", message: "Missing record is not proof of no approval.", next_step: "Check linked approval timing.", citation: {evidence_id: "e", source_id: "s", locator: "row:1", quotation: "<audit note>", start: 0, end: 12}}],
    as_of: "2026-06-17", assessment_target: "formal_rule", assurance: { notice: "Human review pending." },
    inputs: [], limitations: [], assessment: { overall_outcome: "Insufficient evidence",
      formal_outcome: "Insufficient evidence", observed_outcome: "Insufficient evidence",
      confidence: "Low", evidence: [], gaps: [], rules_applied: [], summary: "No admitted evidence." },
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedResultView result={result} />);
  for (const text of ["Automatic result", "Review pending", "Saved snapshot", "Original", "Insufficient evidence"])
    assert.ok(html.includes(text));
  assert.ok(!html.includes("Not saved"));
  assert.ok(html.includes("Deployment sign-off evidence"));
  assert.ok(html.includes("Missing record is not proof of no approval."));
  assert.ok(html.includes("Check linked approval timing."));
  assert.ok(html.includes("&lt;audit note&gt;"));
});

test("wording match is shown separately from the credibility outcome", () => {
  const result = {
    status: "assessed_automatically", persisted: true, claim_text: "Original", facet: "Facet",
    as_of: "2026-06-17", assessment_target: "formal_rule", assurance: { notice: "Human review pending." },
    rule_comparison: { message: "Rule wording matches; authority unresolved", notice: "Not a verified verdict." },
    inputs: [], limitations: [], assessment: { overall_outcome: "Insufficient evidence",
      formal_outcome: "Insufficient evidence", observed_outcome: "Insufficient evidence",
      confidence: "Low", evidence: [], gaps: [], rules_applied: [], summary: "Authority unresolved." },
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedResultView result={result} />);
  assert.ok(html.includes("Rule wording matches; authority unresolved"));
  assert.ok(html.includes("Conditional outcome: Insufficient evidence"));
  assert.ok(html.includes("Not a verified verdict."));
});

test("documented authority checks distinguish resolved evidence from missing proof", () => {
  const item = {
    input_id: "one", source: { title: "Policy", source_id: "p" },
    interpretation: { stance: "support", mode: "formal", rationale: "Matched rule", citations: [] },
    supplied_judgements: {}, admitted_to_framework: false, edge_id: null, reasons: [],
  } as unknown as SuppliedResult["inputs"][number];
  item.interpretation.citations = [{ evidence_id: "rule", source_id: "p", locator: "rule", quotation: "Rule", start: 0, end: 4 }];
  const result = { status: "assessed_automatically", inputs: [item], assessment: { evidence: [] },
    proposals: [{ evidence_id: "rule", field_comparison: null,
      authority_resolution: { authority_verified: true, checks: [{ name: "rights", passed: true, reason: "Dated adoption rights match." }],
        adoption_findings: [{method: "version-history-meeting-signoff-v1", decision: "2025-02-24", actor: "Alex Smith", version: "3.0"}],
        gaps: [{kind: "evidence_gap", message: "Dated adoption rights need review."}],
        review_guidance: ["Verify dated rights for Alex Smith; keep <missing> unresolved."],
        citations: [], limitations: ["Not independent authentication."] }, authority_context: {}, authority_links: {} }],
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedEvidenceDetail result={result} item={item} />);
  assert.ok(html.includes("Documented authority resolved"));
  assert.ok(html.includes("Documented adoption: version"));
  assert.ok(html.includes("Alex Smith"));
  assert.ok(html.includes("Dated adoption rights need review."));
  assert.ok(html.includes("What to verify next"));
  assert.ok(html.includes("Verify dated rights for Alex Smith; keep &lt;missing&gt; unresolved."));
  assert.ok(html.includes("Dated adoption rights match."));
  assert.ok(!html.includes("Authority remains unresolved."));
});


import { savedResultType, SavedRows } from "../src/SavedAssessments";
import type { SavedAssessmentSummary } from "../src/api";
test("saved dashboard preserves snapshot verdicts, dates and result origins", () => {
  const original = { run_id: "original", parent_run_id: null, record_type: "automatic_assessment",
    claim_text: "Original <claim>", as_of: "2025-03-01", created_at: "2026-10-11T00:00:00Z",
    formal_outcome: "Insufficient evidence", observed_outcome: "Insufficient evidence" } as SavedAssessmentSummary;
  const revision = {...original, run_id: "revision", parent_run_id: "original", record_type: "conditional_supplied_assessment", formal_outcome: "Supported", as_of: "2025-04-01"};
  const html = renderToStaticMarkup(<SavedRows items={[revision, original]} onOpen={() => {}} />);
  for (const text of ["Automatic result", "Human review revision", "conditional", "Supported", "Insufficient evidence", "2025-03-01", "2025-04-01", "Original &lt;claim&gt;"]) assert.ok(html.includes(text), text);
  assert.equal(savedResultType({...original, record_type: "conditional_supplied_assessment"}), "Supplied assessment · review not established");
  assert.ok(!html.includes("<claim>"));
});

import AssessmentGraph, { graphInputs, evidenceWeight } from "../src/AssessmentGraph";
import AssessmentReview from "../src/AssessmentReview";
import type { AssessmentSnapshot } from "../src/AutomaticAssessment";
const graphResult = {
  claim_text: "Purchases above €720 require regional approval.", facet: "Purchases above €720 require regional approval.",
  status: "assessed_automatically", assessment: { evidence: [{edge_id: "edge-zero", material: false, materiality_score: 0, dimensions: {}, trace: [], limitations: []}] },
  inputs: [
    {input_id: "regional-rule", source: {source_id: "policy:custom", title: "Regional purchasing policy <v7>", successor_source_id: "policy:v8"}, interpretation: {mode: "formal", stance: "support", citations: [], rationale: "Rule text matches."}, admitted_to_framework: false, edge_id: null, supplied_judgements: {}, reasons: ["Authority unresolved"]},
    {input_id: "record", source: {source_id: "ledger:custom", title: "Purchasing ledger"}, interpretation: {mode: "observed", stance: "contradict", citations: [], rationale: "A recorded exception."}, admitted_to_framework: true, edge_id: "edge-zero", supplied_judgements: {}, reasons: []},
  ],
} as unknown as SuppliedResult;
test("graph uses arbitrary snapshot evidence, preserves zero and filters lanes without changing outcomes", () => {
  const before = JSON.stringify(graphResult);
  assert.deepEqual(graphInputs(graphResult, "formal").map(i => i.input_id), ["regional-rule"]);
  assert.deepEqual(graphInputs(graphResult, "observed").map(i => i.input_id), ["record"]);
  assert.equal(graphInputs(graphResult, "both").length, 2);
  assert.equal(evidenceWeight(graphResult, graphResult.inputs[1]), "0.00 · weighted down");
  assert.equal(evidenceWeight(graphResult, graphResult.inputs[0]), "Not scored · retained for review");
  const html = renderToStaticMarkup(<AssessmentGraph result={graphResult} onOpen={() => {}} />);
  for (const value of ["Purchases above €720", "Regional purchasing policy &lt;v7&gt;", "Purchasing ledger", "support", "contradict", "aria-pressed", "retained without a score"]) assert.ok(html.includes(value), value);
  assert.ok(!html.includes("POL-01"));
  assert.ok(!html.includes("15%"));
  assert.equal(JSON.stringify(graphResult), before);
});
test("source detail keeps recorded lineage separate from authority and missing scores", () => {
  const html = renderToStaticMarkup(<SuppliedEvidenceDetail result={graphResult} item={graphResult.inputs[0]} />);
  for (const text of ["policy:v8", "Superseded by", "Authority unresolved", "Not scored", "Recorded links do not establish independent corroboration"]) assert.ok(html.includes(text), text);
});
test("review can reopen saved inputs without JSON and keeps citations unchanged", () => {
  const record = {snapshot: {run_id: "saved", request: {inputs: [{stance: "unresolved", rationale: "Needs evidence", judgement_basis: "Unknown", citations: [{quotation: "<exact quote>", evidence_id: "passage:77", source_id: "source:77", locator: "section:4", start: 0, end: 13}], scope_matches: null, temporal_matches: false, authority_verified: null, directness: 0, specificity: 1, completeness: 0.5}]}}} as AssessmentSnapshot;
  const before = JSON.stringify(record);
  const html = renderToStaticMarkup(<AssessmentReview record={record} onSaved={() => {}} />);
  for (const text of ["Review this result", "&lt;exact quote&gt;", "passage:77", "source:77", "Reason for this review", "Save review as a new revision", "previous snapshot stays unchanged"]) assert.ok(html.includes(text), text);
  assert.ok(html.includes('disabled=""'));
  assert.ok(!html.includes("Prepared assessment request"));
  assert.equal(JSON.stringify(record), before);
});

import { graphLanes } from "../src/AssessmentGraph";
import { explainEvidenceGap } from "../src/SuppliedAssessment";
test("graph has no empty lane columns and retains unclassified passages", () => {
  assert.equal(graphLanes(graphResult, "formal").length, 1);
  assert.equal(graphLanes(graphResult, "observed").length, 1);
  const unclassified = {...graphResult, inputs: [{...graphResult.inputs[0], interpretation: {...graphResult.inputs[0].interpretation, mode: "unresolved"}}]};
  assert.equal(graphLanes(unclassified, "both")[0].label, "Lane unresolved");
  assert.equal(graphLanes(unclassified, "observed").length, 0);
  const html = renderToStaticMarkup(<AssessmentGraph result={unclassified} onOpen={() => {}} />);
  assert.ok(html.includes("ev-graph-single"));
  assert.ok(html.includes("regional-rule"));
  assert.ok(html.includes("Lane unresolved"));
});
test("gap explanation distinguishes rejected evidence from no retrieved evidence", () => {
  const gap = "No Document or structured row attests to this Fact.";
  assert.ok(explainEvidenceGap(gap, graphResult).startsWith("Evidence was examined"));
  assert.ok(explainEvidenceGap(gap, {...graphResult, inputs: []}).startsWith("No evidence was available to score"));
  assert.equal(explainEvidenceGap("A separate specific gap", graphResult), "A separate specific gap");
  assert.ok(explainEvidenceGap("No material formal attestation resolves the asserted value.", graphResult).includes("after the assessment checks"));
});

import { checkReviewRevision } from "../src/AssessmentReview";
test("review response must be a new saved revision of the same claim and date", () => {
  const parent = {snapshot: {run_id: "parent", request: {claim_text: "Original", facet: "Scoped", as_of: "2026-10-11"}}} as AssessmentSnapshot;
  const child = {snapshot: {run_id: "child", parent_run_id: "parent", response: {claim_text: "Original", facet: "Scoped", as_of: "2026-10-11", persisted: true, status: "assessed_supplied_judgements"}}} as AssessmentSnapshot;
  assert.equal(checkReviewRevision(child, parent), child);
  for (const changed of [
    {...child, snapshot: {...child.snapshot, parent_run_id: "someone-else"}},
    {...child, snapshot: {...child.snapshot, run_id: "parent"}},
    {...child, snapshot: {...child.snapshot, response: {...child.snapshot.response, as_of: "2026-10-10"}}},
    {...child, snapshot: {...child.snapshot, response: {...child.snapshot.response, persisted: false}}},
  ]) assert.throws(() => checkReviewRevision(changed, parent), /does not match/);
});
