import type { CorpusSource, Outcome } from "./api";

export type Target = "unspecified" | "recorded_statement" | "underlying_event" | "formal_rule";
export type Relationship = "support" | "contradict" | "qualify" | "context" | "unresolved";
export interface Citation {
  evidence_id: string; source_id: string; locator: string;
  quotation: string; start: number; end: number;
}
export interface SuppliedRequest {
  claim_text: string;
  facet: string;
  as_of: string;
  assessment_target?: Target;
  inputs: unknown[];
}
export interface SuppliedResult {
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
    formal_outcome: Outcome; observed_outcome: Outcome; overall_outcome: Outcome;
    confidence: string; summary: string; gaps: string[]; rules_applied: string[];
    evidence: {
      edge_id: string; material: boolean; materiality_score: number | null;
      dimensions: Record<string, number>; limitations: string[]; trace: string[];
    }[];
  };
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
  rule_comparison?: { status: string; message: string; notice: string; matching_evidence_ids: string[] };
  proposals?: {
    authority_resolution?: { status: string; authority_verified: boolean | null; checks: { name: string; passed: boolean; reason: string }[]; citations: Citation[]; limitations: string[] };
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
