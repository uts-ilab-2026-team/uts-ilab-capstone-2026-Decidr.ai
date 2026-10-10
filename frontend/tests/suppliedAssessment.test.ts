import assert from "node:assert/strict";
import test from "node:test";
import { parseSuppliedRequest, checkSuppliedResponse, type SuppliedResult } from "../src/suppliedAssessmentContract.ts";

const request = { claim_text: "Exact claim.", facet: "A facet.", as_of: "2026-06-17", inputs: [{}] };
function response() {
  return {
    schema_version: "facet-assessment-response-v1", status: "assessed_supplied_judgements",
    interpretation_basis: "supplied_judgements", ...request,
    assessment_target: "unspecified", inputs: [{}],
    assurance: {
      outcome_basis: "conditional_on_supplied_judgements",
      semantic_verification: "not_performed", notice: "Conditional.",
    },
    assessment: { evidence: [] },
  } as unknown as SuppliedResult;
}
test("exact claim binding preserves request without filling assumptions", () => {
  assert.deepEqual(parseSuppliedRequest(JSON.stringify(request), request.claim_text), request);
  assert.throws(() => parseSuppliedRequest(JSON.stringify(request), "Another claim."));
  assert.throws(() => parseSuppliedRequest(JSON.stringify(request), "Exact claim. "));
});
test("review-return files and malformed requests are rejected", () => {
  for (const input of [null, [], { packet_id: "review", cases: [] },
    { ...request, inputs: [] }, { ...request, as_of: "today" }, { ...request, facet: "" }]) {
    assert.throws(() => parseSuppliedRequest(JSON.stringify(input), request.claim_text));
  }
});
test("only matching disclosed responses are accepted", () => {
  assert.equal(checkSuppliedResponse(response(), request).claim_text, request.claim_text);
  for (const change of [
    { claim_text: "Other" }, { facet: "Other" }, { as_of: "2025-01-01" },
    { assessment_target: "formal_rule" }, { assurance: {} }, { inputs: [] },
    { status: "verified" }, { interpretation_basis: "automatic" },
  ]) {
    assert.throws(() => checkSuppliedResponse({ ...response(), ...change } as SuppliedResult, request));
  }
});
test("semantic verification claims are rejected", () => {
  const result = response();
  result.assurance.semantic_verification = "verified";
  assert.throws(() => checkSuppliedResponse(result, request));
});
