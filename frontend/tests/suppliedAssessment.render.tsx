import "./suppliedAssessment.test";
import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import SuppliedAssessment, { SuppliedResultView, SuppliedEvidenceDetail } from "../src/SuppliedAssessment";
import type { SuppliedResult } from "../src/suppliedAssessmentContract";

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
