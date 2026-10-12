import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { SuppliedResultView, SuppliedEvidenceDetail, assessmentConfidence } from "../src/SuppliedAssessment";
import { checkAutomaticResponse, type AssessmentSnapshot } from "../src/AutomaticAssessment";
import { SavedRows, savedOutcome, savedResultType } from "../src/SavedAssessments";
import AssessmentGraph, { unifiedGraph, evidenceWeight } from "../src/AssessmentGraph";
import ConnectedEvidence from "../src/ConnectedEvidence";
import type { CanonicalAssessment, SuppliedResult } from "../src/suppliedAssessmentContract";
import type { SavedAssessmentSummary } from "../src/api";

const citation = {source_id: "manual:ops", evidence_id: "passage:policy", locator: "section:1", quotation: "Customer installation must finish within nine weeks of assignment.", start: 0, end: 69};
function canonicalFixture(outcome = "Supported", score: number | null = 82): SuppliedResult {
  const component = {id: "component-one", text: "Customer installation must finish within nine weeks of assignment.", claim_quote: "installation must finish within nine weeks of assignment", entities: ["customer installation"], predicate: "must finish", polarity: "positive", quantities: [{value: 9, unit: "weeks", comparator: "within"}], scope: "customer installation", temporal: "from assignment", modality: "requirement"};
  const finding = {component_id: component.id, evidence_id: citation.evidence_id, source_id: citation.source_id, quotation: citation.quotation, relationship: outcome === "Contradicted" ? "contradicts" : "supports", reason: "The dated procedure specifies the customer scope and starting event.", scope_fit: "yes", time_fit: "yes", directness: "direct", limitations: ["Source independence remains unverified."], basis: "exact cited requirement", original_relationship: "supports", admitted: true, exclusion_reasons: [], citations: [citation]};
  const canonical: CanonicalAssessment = {schema_version: "canonical-assessment-v1", processing: {status: "assessed", code: "assessment_complete", message: "Components evaluated"}, interpreted_claim: {target: "formal_requirement", components: [component], ambiguities: []}, components: [{...component, status: "supported", outcome, findings: [finding], citations: [citation]}], overall_outcome: outcome, summary: "The requirement and its starting point were assessed from the cited procedure.", confidence: {score, method: "assessment-confidence-v1", label: "Uncalibrated assessment confidence", basis: ["Evidence coverage, directness and applicability inform this score."], components: [{component_id: component.id, score: score ?? 0, factors: {scope_fit: 1, independence: 0}, basis: ["One unverified origin group."]}], weights: {scope_fit: .1, independence: .1}, calibrated: false, meaning: "Quality of the basis for the outcome, not probability the claim is true."}, unresolved_questions: [], evidence_relations: [{component_id: component.id, evidence_id: citation.evidence_id, source_id: citation.source_id, relationship: finding.relationship, reason: finding.reason, inferential: true, citations: [citation]}], citations: [citation], diagnostics: {selected_passages: 1}, provenance: {model: "synthetic provider fixture"}};
  return {claim_text: component.text, facet: component.text, as_of: "2026-06-01", persisted: true, status: "assessed_automatically", assessment_target: "formal_rule", interpretation_basis: "canonical", target_validation: "canonical", config_version: "test", assurance: {outcome_basis: "canonical", notice: "Review pending"}, limitations: [],
    assessment: {overall_outcome: "Insufficient evidence", formal_outcome: "Insufficient evidence", observed_outcome: "Insufficient evidence", confidence: "Lower confidence", evidence: [], gaps: ["Legacy gap must not override canonical result"], summary: "Obsolete approval grammar result", rules_applied: []},
    claim_conclusion: {label: "Obsolete event label", status: "unresolved", summary: "Obsolete summary", basis: "recorded_event_comparison", notice: "Legacy"},
    inputs: [{input_id: "input-one", source: {source_id: citation.source_id, title: "Customer delivery procedure", lifecycle_status: "current"}, interpretation: {mode: "formal", stance: "unresolved", rationale: "Obsolete grammar result", citations: [citation]}, supplied_judgements: {temporal_matches: false}, admitted_to_framework: false, edge_id: null, reasons: []}], canonical_assessment: canonical,
  } as unknown as SuppliedResult;
}
function historyRow(result: SuppliedResult): SavedAssessmentSummary {
  const canonical = result.canonical_assessment!;
  return {run_id: "snapshot-1", parent_run_id: null, created_at: "2026-06-01T08:00:00Z", claim_text: result.claim_text, facet: result.facet, as_of: result.as_of, overall_outcome: canonical.overall_outcome ?? "Assessment not completed", formal_outcome: "Not applicable", observed_outcome: "Not applicable", record_type: canonical.processing.status === "failed" ? "automatic_processing_failure" : "automatic_assessment", processing: canonical.processing, confidence: canonical.confidence, claim_conclusion: result.claim_conclusion, review_status: "pending", snapshot_sha256: "test"};
}

for (const outcome of ["Supported", "Contradicted", "Partially supported", "Conflicting evidence", "Insufficient evidence"]) {
  test(`canonical ${outcome} stays consistent in result, component graph and saved history`, () => {
    const result = canonicalFixture(outcome), before = JSON.stringify(result);
    const html = renderToStaticMarkup(<SuppliedResultView result={result}/>);
    const rows = renderToStaticMarkup(<SavedRows items={[historyRow(result)]} onOpen={() => {}}/>);
    const graph = unifiedGraph(result);
    assert.ok(html.includes(`<h2>${outcome}</h2>`));
    assert.ok(rows.includes(outcome));
    assert.equal(savedOutcome(historyRow(result)), outcome);
    assert.equal(graph.components[0].outcome, outcome);
    assert.ok(html.includes("82/100"));
    assert.ok(rows.includes("82/100"));
    assert.ok(html.includes("Uncalibrated assessment confidence"));
    assert.ok(html.includes("not the probability that the claim is true"));
    assert.ok(!html.includes("Obsolete event label"));
    assert.ok(!html.includes("Obsolete approval grammar result"));
    assert.ok(!rows.includes("Obsolete event label"));
    assert.ok(!html.includes("Lower confidence"));
    assert.equal((html.match(/aria-label="Final claim assessment"/g) ?? []).length, 1);
    assert.equal((html.match(/aria-label="Evidence graph"/g) ?? []).length, 1);
    assert.equal(JSON.stringify(result), before);
  });
}

test("canonical graph uses only validated inference relations and preserves excluded context", () => {
  const result = canonicalFixture();
  const canonical = result.canonical_assessment!;
  const contextCitation = {...citation, source_id: "manual:archived", evidence_id: "old-passage", quotation: "Employee installation takes three weeks."};
  const context = {...canonical.components[0].findings[0], evidence_id: contextCitation.evidence_id, source_id: contextCitation.source_id, quotation: contextCitation.quotation, relationship: "context", original_relationship: "supports", admitted: false, reason: "Employee context does not address the customer requirement.", exclusion_reasons: ["Scope mismatch"], citations: [contextCitation]};
  canonical.components[0].findings.push(context);
  canonical.citations.push(contextCitation);
  canonical.evidence_relations.push({component_id: "component-one", evidence_id: contextCitation.evidence_id, source_id: contextCitation.source_id, relationship: "context", reason: context.reason, inferential: false, citations: [contextCitation]});
  const graph = unifiedGraph(result);
  assert.equal(graph.nodes.filter(node => node.used).length, 1);
  assert.equal(graph.edges.filter(edge => edge.inferential).length, 1);
  assert.equal(graph.edges[0].from, "component:component-one");
  assert.equal(graph.nodes[1].used, false);
  assert.ok(graph.nodes[1].contexts.some(context => context.limitations.includes("Scope mismatch")));
  assert.equal(evidenceWeight(result, result.inputs[0]), "Used in canonical assessment");
  const html = renderToStaticMarkup(<AssessmentGraph result={result} onOpen={() => {}} openSignal={1}/>);
  assert.ok(html.includes('aria-label="Claim components"'));
  assert.ok(html.includes("Validated relation used in assessment"));
  assert.ok(!html.includes("Employee installation takes"));
  const detail = renderToStaticMarkup(<ConnectedEvidence node={graph.nodes[1]} graph={graph} result={result} onSelect={() => {}} onOpen={() => {}} onClose={() => {}}/>);
  assert.ok(detail.includes("Scope mismatch"));
  assert.ok(detail.includes("Context connection only"));
  assert.ok(detail.includes("Employee installation takes three weeks."));
  assert.ok(detail.includes("Customer installation must finish within nine weeks of assignment."));
});

test("canonical evidence detail shows source-grounded findings rather than old grammar scoring", () => {
  const result = canonicalFixture();
  const html = renderToStaticMarkup(<SuppliedEvidenceDetail result={result} item={result.inputs[0]}/>);
  assert.ok(html.includes("The dated procedure specifies"));
  assert.ok(html.includes("Customer installation must finish within nine weeks"));
  assert.ok(!html.includes("Obsolete grammar result"));
  assert.ok(!html.includes("Quality dimensions are bounded grammar checks"));
});

test("canonical graph categories follow source metadata across claim targets without inferring support", () => {
  const result = canonicalFixture(), canonical = result.canonical_assessment!;
  result.inputs[0].source.source_type = "policy";
  const original = result.inputs[0];
  for (const [sourceType, lane] of [["interview", "observed"], ["crm_records", "observed"], ["procedure", "formal"], ["role_description", "formal"], ["meeting", "documented"], ["organisational_information", "documented"], ["technical", "documented"], ["internal_communication", "observed"], ["project_tasks", "observed"], ["audit_events", "observed"], ["unfamiliar", "unresolved"]]) {
    const input = {...original, input_id: `input-${sourceType}`, source: {...original.source, source_id: `source:${sourceType}`, source_type: sourceType, title: `Source ${sourceType}`}, interpretation: {...original.interpretation, mode: "formal" as const, citations: [{...citation, source_id: `source:${sourceType}`, evidence_id: `passage:${sourceType}`} ]}};
    result.inputs.push(input);
    assert.deepEqual(unifiedGraph(result).nodes.find(node => node.sourceId === input.source.source_id)?.lanes, [lane]);
  }
  const extraPolicyCitation = {...citation, evidence_id: "policy-header"};
  const orphanCitation = {...citation, source_id: "source:not-in-metadata"};
  canonical.citations.push(extraPolicyCitation, orphanCitation);
  const before = JSON.stringify(result), formal = unifiedGraph(result);
  assert.deepEqual(formal.nodes.find(node => node.evidenceId === "policy-header")?.lanes, ["formal"]);
  assert.deepEqual(formal.nodes.find(node => node.sourceId === orphanCitation.source_id)?.lanes, ["unresolved"]);
  assert.equal(formal.nodes.filter(node => node.used).length, 1);
  assert.equal(formal.edges.filter(edge => edge.inferential).length, 1);
  assert.equal(JSON.stringify(result), before);
  canonical.interpreted_claim!.target = "event";
  const event = unifiedGraph(result);
  assert.deepEqual(event.nodes.map(node => [node.id, node.lanes]), formal.nodes.map(node => [node.id, node.lanes]));
  assert.deepEqual(event.edges, formal.edges);
  assert.equal(canonical.overall_outcome, "Supported");
  assert.equal(canonical.confidence.score, 82);
  const html = renderToStaticMarkup(<AssessmentGraph result={result} onOpen={() => {}}/>);
  assert.ok(html.includes("Formal documents"));
  assert.ok(html.includes("Categories describe source types, not credibility or support."));
});

test("canonical graph does not borrow a source category from mismatched or conflicting input metadata", () => {
  const result = canonicalFixture();
  result.inputs[0].source.source_type = "policy";
  result.inputs.push({...result.inputs[0], input_id: "conflicting-type", source: {...result.inputs[0].source, source_type: "interview"}});
  const foreign = {...citation, source_id: "foreign-source"};
  result.inputs[0].interpretation.citations.push(foreign);
  const before = JSON.stringify(result), graph = unifiedGraph(result);
  assert.deepEqual(graph.nodes.find(node => node.sourceId === citation.source_id)?.lanes, ["unresolved"]);
  assert.deepEqual(graph.nodes.find(node => node.sourceId === foreign.source_id)?.lanes, ["unresolved"]);
  assert.equal(graph.nodes.find(node => node.sourceId === foreign.source_id)?.used, false);
  assert.equal(JSON.stringify(result), before);
});

test("document-date derivation explains its basis and preserves exact header citations in findings and source detail", () => {
  const result = canonicalFixture(), finding = result.canonical_assessment!.components[0].findings[0];
  const header = {...citation, evidence_id: "passage:header", locator: "header:effective", quotation: "Effective from: 2026-01-01", end: 26};
  finding.original_time_fit = "unknown";
  finding.temporal_derivation = {method: "formal-header-applicability-v1", assessed_date: result.as_of, effective_start_date: "2026-01-01", reason: "The saved approval and effective-date headers establish document-date applicability only, not scope, authority or actual compliance.", citations: [header]};
  finding.citations.push(header);
  const before = JSON.stringify(result);
  for (const html of [renderToStaticMarkup(<SuppliedResultView result={result}/>), renderToStaticMarkup(<SuppliedEvidenceDetail result={result} item={result.inputs[0]}/>)]) {
    assert.ok(html.includes("Date applicability established from saved document headers."));
    assert.ok(html.includes(finding.temporal_derivation.reason));
    assert.ok(html.includes("Assessed date: 2026-06-01 · Effective from: 2026-01-01 · Initial date fit: unknown"));
    assert.ok(html.includes("Effective from: 2026-01-01"));
    assert.ok(html.includes("passage:header · header:effective"));
    assert.equal((html.match(/passage:header · header:effective/g) ?? []).length, 1);
  }
  assert.equal(JSON.stringify(result), before);
});

test("zero confidence is a score; a failed attempt has no score, verdict or review status", () => {
  const result = canonicalFixture("Insufficient evidence", 0);
  assert.ok(renderToStaticMarkup(<SuppliedResultView result={result}/>).includes("0/100"));
  assert.equal(assessmentConfidence(0), "0/100");
  assert.equal(assessmentConfidence(null), "Not available");
  assert.equal(assessmentConfidence(Number.NaN), "Not available");
  const canonical = result.canonical_assessment!;
  canonical.processing = {status: "failed", code: "provider_unavailable", message: "The configured local model could not be reached."};
  canonical.overall_outcome = null;
  canonical.confidence.score = null;
  canonical.confidence.components = [];
  canonical.components = [];
  canonical.evidence_relations = [];
  canonical.citations = [];
  result.status = "processing_failed";
  const html = renderToStaticMarkup(<SuppliedResultView result={result}/>);
  const rows = renderToStaticMarkup(<SavedRows items={[historyRow(result)]} onOpen={() => {}}/>);
  assert.ok(html.includes("Assessment not completed"));
  assert.ok(html.includes("The configured local model could not be reached."));
  assert.ok(html.includes("No assessment outcome or confidence score was produced"));
  assert.ok(!html.includes("0/100"));
  assert.ok(!html.includes("Insufficient evidence"));
  assert.ok(!html.includes("Final claim assessment"));
  assert.ok(html.includes("Target: formal requirement"));
  canonical.interpreted_claim = null;
  assert.ok(renderToStaticMarkup(<SuppliedResultView result={result}/>).includes("Target: Not established"));
  assert.ok(!rows.includes("0/100"));
  assert.ok(!rows.includes("review pending"));
  assert.equal(savedResultType(historyRow(result)), "Processing incomplete · no assessment outcome");
});

test("automatic API response validation preserves claim binding and separates success from processing failure", () => {
  const result = canonicalFixture(), request = {claim: result.claim_text, facet: result.facet, as_of: result.as_of};
  const snapshot = {snapshot: {run_id: "saved", response: result}} as AssessmentSnapshot;
  assert.equal(checkAutomaticResponse(snapshot, request), snapshot);
  result.canonical_assessment!.confidence.score = 0;
  assert.equal(checkAutomaticResponse(snapshot, request), snapshot);
  assert.throws(() => checkAutomaticResponse(snapshot, {...request, claim: "Another claim"}), /does not match/);
  for (const value of [null, Number.NaN, -1, 101]) {
    result.canonical_assessment!.confidence.score = value;
    assert.throws(() => checkAutomaticResponse(snapshot, request), /processing state/);
  }
  result.canonical_assessment!.processing.status = "failed";
  result.canonical_assessment!.confidence.score = null;
  result.canonical_assessment!.overall_outcome = null;
  result.status = "processing_failed";
  assert.equal(checkAutomaticResponse(snapshot, request), snapshot);
  result.canonical_assessment!.confidence.score = 0;
  assert.throws(() => checkAutomaticResponse(snapshot, request), /processing state/);
});

test("processing failures keep raw validation errors collapsed without changing the saved response", () => {
  const result = canonicalFixture(), canonical = result.canonical_assessment!;
  result.status = "processing_failed";
  canonical.processing = {status: "failed", code: "invalid_model_output", message: "Raw validator diagnostics. ".repeat(60)};
  canonical.overall_outcome = null;
  canonical.confidence.score = null;
  canonical.components = [];
  canonical.evidence_relations = [];
  const before = JSON.stringify(result);
  const html = renderToStaticMarkup(<SuppliedResultView result={result}/>);
  const alert = html.match(/<section role="alert" aria-label="Assessment processing failure">([\s\S]*?)<\/section>/)?.[1] ?? "";
  assert.ok(alert.includes("The automatic interpretation did not pass validation, so no assessment was issued."));
  const technical = alert.match(/<details><summary>Technical details<\/summary>([\s\S]*?)<\/details>/);
  assert.ok(technical?.[1].includes(canonical.processing.message));
  assert.ok(!alert.replace(technical![0], "").includes("Raw validator diagnostics"));
  assert.ok(!html.includes('aria-label="Assessment confidence"'));
  assert.ok(!html.includes('aria-label="Final claim assessment"'));
  const rows = renderToStaticMarkup(<SavedRows items={[historyRow(result)]} onOpen={() => {}}/>);
  assert.ok(rows.includes("The automatic interpretation did not pass validation, so no assessment was issued."));
  assert.ok(!rows.includes("Raw validator diagnostics"));
  assert.equal(JSON.stringify(result), before);
});

import AssessmentReview, { canonicalReviewFindings, checkReviewRevision } from "../src/AssessmentReview";
test("canonical human review preserves frozen evidence and reuses canonical findings instead of old score inputs", () => {
  const result = canonicalFixture(), canonical = result.canonical_assessment!, before = JSON.stringify(result);
  const record = {snapshot: {run_id: "parent-run", request: {claim_text: result.claim_text, facet: result.facet, as_of: result.as_of, inputs: []}, response: result}} as unknown as AssessmentSnapshot;
  const findings = canonicalReviewFindings(canonical);
  assert.equal(findings.length, 1);
  assert.equal(findings[0].quotation, citation.quotation);
  assert.equal(findings[0].component_id, "component-one");
  assert.ok(!("admitted" in findings[0]));
  assert.ok(!("authority_verified" in findings[0]));
  assert.ok(!("semantic_validation" in findings[0]));
  findings[0].relationship = "qualifies";
  findings[0].limitations.push("Reviewer identified a scope limit.");
  assert.equal(JSON.stringify(result), before);
  const html = renderToStaticMarkup(<AssessmentReview record={record} onSaved={() => {}}/>);
  assert.ok(html.includes("Customer installation must finish within nine weeks"));
  assert.ok(html.includes("original result, claim interpretation and cited passages stay unchanged"));
  assert.ok(html.includes("Existing validation and date safeguards still apply"));
  assert.ok(!html.includes('type="number"'));
  assert.ok(!html.includes("authority_verified"));
  assert.ok(html.includes("Save review as a new revision"));
});

test("canonical review response rejects changed evidence or interpretation and labels human review accurately", () => {
  const result = canonicalFixture();
  const record = {snapshot: {run_id: "parent-run", request: {claim_text: result.claim_text, facet: result.facet, as_of: result.as_of, inputs: []}, response: result}} as unknown as AssessmentSnapshot;
  const child = structuredClone(record);
  child.snapshot.run_id = "child-run";
  child.snapshot.parent_run_id = "parent-run";
  child.snapshot.response.status = "assessed_supplied_judgements";
  assert.equal(checkReviewRevision(child, record), child);
  const html = renderToStaticMarkup(<SuppliedResultView result={child.snapshot.response}/>);
  assert.ok(html.includes("Human review revision · Conditional"));
  assert.ok(!html.includes("Automatic result · Review pending"));
  assert.ok(!html.includes("Human review is pending"));
  for (const corrupt of [
    (value: AssessmentSnapshot) => { value.snapshot.response.canonical_assessment!.components[0].findings[0].quotation = "Invented passage"; },
    (value: AssessmentSnapshot) => { value.snapshot.response.canonical_assessment!.components[0].findings = []; },
    (value: AssessmentSnapshot) => { value.snapshot.response.canonical_assessment!.interpreted_claim!.components[0].text = "Different claim"; },
    (value: AssessmentSnapshot) => { value.snapshot.response.canonical_assessment!.processing.status = "failed"; },
  ]) {
    const invalid = structuredClone(child); corrupt(invalid);
    assert.throws(() => checkReviewRevision(invalid, record), /does not match/);
  }
});

test("exact record and version context links remain inspectable without changing inference or confidence", () => {
  const result = canonicalFixture(), canonical = result.canonical_assessment!;
  const other = {...citation, source_id: "manual:old", evidence_id: "older-passage", quotation: "Previous requirement for the same service."};
  canonical.context_relations = [{from_citation: citation, to_citation: other, relationship: "supersedes", reason: "The stored source metadata identifies the previous version.", inferential: false}, {from_citation: other, to_citation: citation, relationship: "contextual_reference", reason: "An explicit reference links the records.", inferential: false}];
  const before = JSON.stringify(result), graph = unifiedGraph(result);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.nodes.filter(node => node.used).length, 1);
  assert.equal(graph.edges.filter(edge => edge.inferential).length, 1);
  assert.equal(graph.edges.filter(edge => edge.relationship === "supersedes" && !edge.inferential).length, 1);
  const node = graph.nodes.find(node => node.evidenceId === "older-passage")!;
  assert.deepEqual(node.citations, [other]);
  const html = renderToStaticMarkup(<ConnectedEvidence node={node} graph={graph} result={result} onOpen={() => {}} onSelect={() => {}} onClose={() => {}}/>);
  assert.ok(html.includes("Context connection only"));
  assert.ok(html.includes("stored source metadata identifies the previous version"));
  assert.equal(JSON.stringify(result), before);
});
