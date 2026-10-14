import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { checkAutomaticResponse, type AssessmentSnapshot } from "../src/AutomaticAssessment";
import { GraphResultView, evidenceMap, explainPassage, isGraphResult, ruleText, scoreOutOf100, sourceStance, type GraphResult } from "../src/GraphAssessment";
import { SavedRows } from "../src/SavedAssessments";

const passage = { quote: "Any discount of **15% or greater** requires written approval.", stance: "support", applicable: true, material: true, score: 0.938, limitations: ["Independence is unverified."], trace: ["Source: approved_policy authority=1.00."] };
const result: GraphResult = {
  claim: "Discounts need approval", claim_text: "Discounts need approval", facet: "Discounts need approval", as_of: "2026-07-31",
  status: "assessed_automatically", overall_outcome: "Contested", confidence: "Moderate confidence", target: "formal_requirement", split_status: "validated",
  facets: [
    { facet: "c1", predicate: "require", summary: "Discounts require approval", outcome: "Supported", confidence: "Higher confidence", decisive: true,
      evidence: [{ source: "POL-01", title: "POL-01 — Discount Approval Policy", mode: "formal", source_class: "approved_policy", lifecycle_status: "current", retrieved_via: ["graph_governed"], material: true, best_score: 0.938, passages: [passage] }] },
    { facet: "c2", predicate: "is", summary: "before the deal closes", outcome: "Contested", confidence: "Moderate confidence", decisive: false,
      evidence: [{ source: "POL-02", title: "POL-02 [SUPERSEDED]", mode: "formal", source_class: "approved_policy", lifecycle_status: "superseded", retrieved_via: ["keyword"], material: false, best_score: null,
        passages: [{ ...passage, stance: "contradict", applicable: false, material: false, score: null, quote: "<script>x</script>" }] }] },
  ],
  rules_applied: ["CLAIM_COMBINER_V1_CONJUNCTIVE", "any facet Contested -> Contested"],
  retrieval: { graph_guided: true, processes_matched: ["P1 Customer discount approval"], governed_docs: ["POL-01"], counts: { graph_governed: 2, keyword: 3 }, lanes: { formal: 2, observed: 3 } },
  passages_considered: 5, findings_count: 4, notes: ["dropped a malformed finding: x"], persisted: true,
};

test("graph result shows the verdict, confidence band, parts and evidence", () => {
  const html = renderToStaticMarkup(<GraphResultView result={result} />);
  for (const text of ["Contested", 'aria-label="Confidence in this result: moderate confidence"', "Discounts require approval", "shown but not counted",
    "POL-01 — Discount Approval Policy", "Formal document", "Found by: Governing document", "Supports", "Used in assessment · weight 93/100",
    "Contradicts", "Not applied · kept for reference", "<strong>15% or greater</strong>", "P1 Customer discount approval", "dropped a malformed finding: x"])
    assert.ok(html.includes(text), text);
  assert.ok(!html.includes("<script>x</script>"));
  assert.ok(html.includes("1 part of the claim assessed against 5 passages from 2 sources."));
  assert.ok(!html.includes("ev-component-summary")); // parts are listed under Findings, not under the score
});

test("graph results are recognised and validated against the request", () => {
  const record = { snapshot: { run_id: "r1", request: {}, response: result }, snapshot_sha256: "x" } as unknown as AssessmentSnapshot;
  const request = { claim: result.claim_text, facet: result.facet, as_of: result.as_of };
  assert.ok(isGraphResult(result));
  assert.ok(!isGraphResult({ canonical_assessment: {}, claim_text: "x" }));
  assert.equal(checkAutomaticResponse(record, request), record);
  assert.throws(() => checkAutomaticResponse(record, { ...request, as_of: "2026-01-01" }), /does not match/);
});

test("combiner rules read as sentences and saved rows label graph results", () => {
  assert.equal(ruleText("any facet Contested -> Contested"), "Any part Contested → Contested");
  assert.ok(ruleText("CLAIM_COMBINER_V1_CONJUNCTIVE").startsWith("Every counted part"));
  const html = renderToStaticMarkup(<SavedRows onOpen={() => {}} items={[{ run_id: "r1", parent_run_id: null, created_at: "2026-10-13T10:00:00Z", claim_text: "Discounts need approval",
    facet: "f", as_of: "2026-07-31", overall_outcome: "Contested", formal_outcome: "Contested", observed_outcome: "Contested", record_type: "automatic_assessment",
    review_status: "not_established", snapshot_sha256: "x", outcome_basis: "graph_engine_deterministic_scoring", processing: null, confidence: null }]} />);
  for (const text of ["Automatic result · graph assessment", "Scored on the organisation graph", "Contested"]) assert.ok(html.includes(text), text);
});

test("evidence map links the claim to parts, sources and the governed process", () => {
  const { nodes, edges } = evidenceMap(result);
  assert.deepEqual(nodes.map(node => node.column), [0, 1, 2, 3, 1, 2]);
  const edge = (from: string, to: string) => edges.find(item => item.from === from && item.to === to);
  assert.equal(edge("part:c1", "source:POL-01")?.label, "Supports");
  assert.equal(edge("part:c2", "source:POL-02")?.label, "Not applied");
  assert.equal(edge("part:c2", "source:POL-02")?.dashed, true);
  assert.equal(edge("claim", "part:c2")?.dashed, true);
  assert.ok(edges.some(item => item.from === "source:POL-01" && item.to.startsWith("process:") && item.label === "Governs"));
  assert.equal(sourceStance([{ ...result.facets[0].evidence[0], passages: [passage, { ...passage, stance: "contradict" }] }]).label, "Contradicts");
  const html = renderToStaticMarkup(<GraphResultView result={result} />);
  for (const text of ['aria-label="Evidence map"', "Sources read", "Process governed", 'aria-pressed="false"']) assert.ok(html.includes(text), text);
});

test("a supported or contradicted result shows the score ring; other outcomes keep the band", () => {
  assert.equal(scoreOutOf100("Supported", 0.938), 93);
  assert.equal(scoreOutOf100("Supported", 0.749), 74);
  assert.equal(scoreOutOf100("Supported", 0.75), 75);
  assert.equal(scoreOutOf100("Contested", 0), null);
  assert.equal(scoreOutOf100("Supported", undefined), null);
  const scored = { ...result, overall_outcome: "Supported", confidence_score: 0.948, facets: result.facets.map(facet => ({ ...facet, outcome: "Supported", confidence_score: 0.948 })) };
  const html = renderToStaticMarkup(<GraphResultView result={scored} />);
  for (const text of ['aria-label="Confidence in this result: 94 out of 100, moderate"', "Moderate confidence", "out of 100"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("ev-band") && !html.includes("94/100")); // one score only, in the ring
  const unscored = renderToStaticMarkup(<GraphResultView result={{ ...result, confidence_score: 0 }} />);
  assert.ok(unscored.includes("ev-band") && !unscored.includes("ev-ring-number") && unscored.includes("No score is given for this outcome"));
});

test("scoring trace reads as plain checks with the weight broken down", () => {
  const { checks, weight } = explainPassage({ ...passage,
    limitations: ["Independence is unverified; no additive corroboration credit.", "A duplicate source exists and is not counted as independent.", "No independent source corroborates this stance in the same lane."],
    trace: ["Source: approved_policy authority=1.00. No person-level authority resolution was required.", "Status: current lifecycle multiplier=1.00; approval=0.50.",
      "Date: no effective or updated date was available value=0.65.", "Supplied independence judgement: False; basis=''; origin group established=False.",
      "Materiality: weighted dimensions 0.938 × lifecycle 1.00 × authority 1.00 = 0.938.", "Something new from the engine."] });
  assert.deepEqual(weight, { fit: 0.938, status: 1, authority: 1, weight: 0.938 });
  assert.deepEqual(checks.map(check => `${check.tone}: ${check.text}`), [
    "ok: Approved policy · authority 100/100", "ok: Current version", "warn: Approval not confirmed, counted at 50%",
    "warn: No effective or updated date was available, counted at 65%", "info: Something new from the engine",
    "warn: Only source saying this, so it gets no extra credit for agreement", "info: A duplicate copy of this document exists and is counted once"]);
  const gated = explainPassage({ ...passage, applicable: false, limitations: ["Assessment date follows the documented superseded date."],
    trace: ["Applicability gate failed: Assessment date follows the documented superseded date. Evidence retained but not scored."] });
  assert.deepEqual(gated.checks, [{ tone: "warn", text: "Not applied: assessment date follows the documented superseded date" }]);
  const html = renderToStaticMarkup(<GraphResultView result={result} />);
  for (const text of ["Why this passage counts", "Why this passage was not applied", "Technical trace"]) assert.ok(html.includes(text), text);
});
