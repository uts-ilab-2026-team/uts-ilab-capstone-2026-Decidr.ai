import type { CorpusSource } from "./api";

export type Target = "unspecified" | "recorded_statement" | "underlying_event" | "formal_rule";
export type Relationship = "support" | "contradict" | "qualify" | "context" | "unresolved";
export interface Citation {
  evidence_id: string; source_id: string; locator: string;
  quotation: string; start: number; end: number;
}
export interface CanonicalFinding {
  component_id: string; evidence_id: string; source_id: string; quotation: string;
  relationship: string; reason: string; scope_fit: string; time_fit: string; directness: string;
  limitations: string[]; basis: string; original_relationship: string;
  admitted: boolean; exclusion_reasons: string[]; citations: Citation[];
  original_time_fit?: string;
  temporal_derivation?: {method: string; assessed_date: string; effective_start_date: string; reason: string; citations: Citation[]};
}
export interface CanonicalClaimComponent {
  id: string; text: string; claim_quote: string; entities: unknown[]; predicate: string;
  polarity: string; quantities: unknown[]; scope: unknown; temporal: unknown; modality: string;
}
export interface CanonicalAssessment {
  schema_version: string;
  processing: {status: "assessed" | "failed"; code: string | null; message: string};
  interpreted_claim: {target: string; components: CanonicalClaimComponent[]; ambiguities: string[]} | null;
  components: (CanonicalClaimComponent & {status: string; outcome: string; findings: CanonicalFinding[]; citations: Citation[]})[];
  overall_outcome: string | null; summary: string;
  confidence: {score: number | null; method: string; label: string; basis: string[];
    components: {component_id: string; score: number; factors: Record<string, number>; basis: string[]}[];
    weights: Record<string, number>; calibrated: boolean; meaning: string};
  unresolved_questions: string[];
  evidence_relations: {component_id: string; evidence_id: string; source_id: string; relationship: string; reason: string; inferential: boolean; citations: Citation[]}[];
  context_relations?: {from_citation: Citation; to_citation: Citation; relationship: "same_record" | "contextual_reference" | "supersedes"; reason: string; inferential: false}[];
  citations: Citation[]; diagnostics: Record<string, unknown>; provenance: Record<string, unknown>;
}
export type CanonicalReviewFinding = Pick<CanonicalFinding, "component_id" | "evidence_id" | "source_id" | "quotation" | "relationship" | "reason" | "scope_fit" | "time_fit" | "directness" | "basis" | "limitations">;
export interface SuppliedRequest {
  claim_text: string;
  facet: string;
  as_of: string;
  assessment_target?: Target;
  inputs: unknown[];
}
export interface SuppliedResult {
  canonical_assessment?: CanonicalAssessment;
  schema_version: string;
  status: string;
  interpretation_basis: string;
  claim_text: string; facet: string; as_of: string;
  assessment_target: Target;
  target_validation: string;
  persisted: boolean;
  config_version: string;
  assurance: { outcome_basis: string; notice: string; [key: string]: string };
  assessment: {
    formal_outcome: string; observed_outcome: string; overall_outcome: string;
    basis?: string;
    confidence: string; summary: string; gaps: string[]; rules_applied: string[];
    evidence: {
      edge_id: string; material: boolean; materiality_score: number | null;
      dimensions: Record<string, number>; limitations: string[]; trace: string[];
    }[];
  };
  credibility_assessment?: SuppliedResult["assessment"];
  inputs: {
    input_id: string;
    interpretation: {
      stance: Relationship; mode: string; rationale: string; citations: Citation[];
    };
    source: CorpusSource;
    supplied_judgements: Record<string, unknown>;
    edge_id: string | null; admitted_to_framework: boolean; reasons: string[];
  }[];
  limitations: string[];
  evidence_synthesis?: {comparisons?: {kind: string; summary: string; node_ids: string[]}[]; status: string; summary: string; notice: string; future_evidence_excluded: number; counts: Record<string, number>; questions: string[]; nodes: {id: string; lane: string; relationship: string; reason: string; source_title: string; source_id: string; record_id: string | null; temporal_status: string; details: Record<string, unknown>; limitations: string[]; citation: Citation}[]; edges: {from: string; to: string; relationship: string; basis: string}[]} | null;
  claim_conclusion?: {status: string; label: string; summary: string; basis: string; notice: string};
  transaction_assessment?: {status: string; record_id: string; candidate_record_ids?: string[]; notice: string; next_step: string; components: {field: string; label: string; status: string; observations: {status: string; reason: string; evidence_id: string}[]}[]; citations: Citation[]; connections: {evidence_id: string; relationship: string}[]};
  practice_assessment?: { status: string; examined_records: number; omitted_findings: number; notice: string; findings: {status: string; reason: string; record_id: string; source_title: string; amount: string; required_approver: string; recorded_approver: string; event_date: string | null; approval_date: string | null; limitations: string[]; citation: Citation}[] };
  deployment_event_findings?: { status: string; event_id: string | null; related_record: string | null; message: string; next_step: string; citation: Citation }[];
  rule_comparison?: { status: string; message: string; notice: string; matching_evidence_ids: string[] };
  proposals?: {
    authority_resolution?: { status: string; authority_verified: boolean | null; adoption_findings?: { method: string; decision: string; actor: string; version: string }[]; gaps?: { kind: string; message: string }[]; review_guidance?: string[]; checks: { name: string; passed: boolean; reason: string }[]; citations: Citation[]; limitations: string[] };
    passage_context?: { compatible: boolean; limitation: string; citation: Citation; clauses: { text: string; compatible: boolean; reason: string }[] };
    evidence_id: string;
    field_comparison: { differences: string[]; evidence_entails_claim: boolean } | null;
    authority_context: { [key: string]: unknown };
    authority_links: { [key: string]: unknown };
  }[];
}

export function parseSuppliedRequest(text: string, claim: string, expectedFacet?: string): SuppliedRequest {
  const value = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      value.claim_text !== claim || typeof value.facet !== "string" || !value.facet.trim() ||
      typeof value.as_of !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.as_of) ||
      !Array.isArray(value.inputs) || value.inputs.length < 1 || value.inputs.length > 50) {
    throw new Error("Use an assessment request with the exact displayed claim, a facet, assessment date and 1–50 supplied inputs. Reviewer-return files are a different format.");
  }
  if (expectedFacet !== undefined && value.facet !== expectedFacet) {
    throw new Error("The prepared facet must match the displayed claim and user-supplied scope. Prepare new judgements for this scope.");
  }
  return value;
}

export function checkSuppliedResponse(result: SuppliedResult, request: SuppliedRequest): SuppliedResult {
  if (result.schema_version !== "facet-assessment-response-v1" ||
      result.status !== "assessed_supplied_judgements" ||
      result.interpretation_basis !== "supplied_judgements" ||
      result.claim_text !== request.claim_text || result.facet !== request.facet ||
      result.as_of !== request.as_of ||
      result.assessment_target !== (request.assessment_target ?? "unspecified") ||
      result.assurance?.outcome_basis !== "conditional_on_supplied_judgements" ||
      result.assurance?.semantic_verification !== "not_performed" ||
      typeof result.assurance?.notice !== "string" || !result.assurance.notice.trim() ||
      !Array.isArray(result.inputs) || result.inputs.length !== request.inputs.length ||
      !result.assessment || !Array.isArray(result.assessment.evidence)) {
    throw new Error("Assessment response does not match this request or lacks the required supplied-judgement disclosure. Check the backend version.");
  }
  return result;
}
