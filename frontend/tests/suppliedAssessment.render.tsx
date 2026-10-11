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
    "Conditional on supplied judgements.", "qualify", "Retained without a scoring edge.",
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
    as_of: "2026-06-17", assessment_target: "formal_rule", assurance: { notice: "Human review pending." },
    inputs: [], limitations: [], assessment: { overall_outcome: "Insufficient evidence",
      formal_outcome: "Insufficient evidence", observed_outcome: "Insufficient evidence",
      confidence: "Low", evidence: [], gaps: [], rules_applied: [], summary: "No admitted evidence." },
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedResultView result={result} />);
  for (const text of ["Automatic result", "Review pending", "Saved snapshot", "Original", "Insufficient evidence"])
    assert.ok(html.includes(text));
  assert.ok(!html.includes("Not saved"));
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
        citations: [], limitations: ["Not independent authentication."] }, authority_context: {}, authority_links: {} }],
  } as unknown as SuppliedResult;
  const html = renderToStaticMarkup(<SuppliedEvidenceDetail result={result} item={item} />);
  assert.ok(html.includes("Documented authority resolved"));
  assert.ok(html.includes("Dated adoption rights match."));
  assert.ok(!html.includes("Authority remains unresolved."));
});
