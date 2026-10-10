import { useEffect, useState } from "react";

// ─── Types (mirror decidr/api/app.py) ─────────────────────────────────────────

export type Outcome = "Supported" | "Contradicted" | "Contested" | "Insufficient evidence";
export type Stance = "support" | "contradict" | "qualify";
export type Mode = "formal" | "observed";

export interface SourceDoc {
  id: string;
  short_id: string;
  title: string;
  type: string | null;
  status: string;
  approval_status: string;
  source_class: string;
  effective_date: string | null;
  effective_end_date: string | null;
  last_updated: string | null;
  owner: string | null;
  used_in: number;
}

export interface Actor {
  id: string;
  label: string;
  roles: string[];
}

export interface Evidence {
  edge_id: string;
  document_id: string;
  document_title: string;
  mode: Mode;
  attests_value: string;
  stance: Stance;
  source_class: string;
  lifecycle_status: string;
  applicable: boolean;
  materiality_score: number | null;
  material: boolean;
  dimensions: Record<string, number>;
  limitations: string[];
  trace: string[];
  document: SourceDoc;
  actor: Actor | null;
}

export interface Assessment {
  fact_id: string;
  label: string;
  statement: string;
  category: string;
  scope: string | null;
  as_of: string;
  formal_outcome: Outcome;
  observed_outcome: Outcome;
  overall_outcome: Outcome;
  confidence: string;
  summary: string;
  evidence: Evidence[];
  gaps: string[];
  related_qualifiers: string[];
  rules_applied: string[];
  sources_searched: number;
}

export interface ClaimRecord {
  fact_id: string;
  statement: string;
  category: string;
  status: string;
  formal_outcome: Outcome;
  observed_outcome: Outcome;
  overall_outcome: Outcome;
  confidence: string;
  documents: string[];
  gaps: string[];
}

export interface ClaimsResponse {
  as_of: string;
  summary: { claims_assessed: number; contested: number; insufficient_evidence: number; sources: number };
  claims: ClaimRecord[];
}

export interface FactMatch {
  fact_id: string;
  label: string;
  statement: string;
  similarity: number;
}

export interface CheckResponse {
  claim: string | null;
  as_of: string;
  sources_searched: number;
  matches: FactMatch[];
  assessment: Assessment | null;
}

export interface SourceAttestation {
  edge_id: string;
  fact_id: string;
  statement: string;
  mode: Mode;
  stance: Stance;
  attests_value: string;
  applicable: boolean;
  material: boolean;
  formal_outcome: Outcome;
  observed_outcome: Outcome;
  overall_outcome: Outcome;
}

export interface LineageLink {
  relationship: string;
  direction: "outgoing" | "incoming";
  node_id: string;
  short_id: string;
  label: string;
  kind: string;
  status: string | null;
  reason: string | null;
}

export interface SourceDetail extends SourceDoc {
  as_of: string;
  attestations: SourceAttestation[];
  lineage: LineageLink[];
}

// ─── Requests ─────────────────────────────────────────────────────────────────

let unauthorized: (() => void) | null = null;

/** Registers what happens when a signed-in request is rejected because the session ended. */
export const onUnauthorized = (handler: () => void) => {
  unauthorized = handler;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) unauthorized?.();
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    // FastAPI reports validation failures as a list of {msg}; everything else as a string.
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : null;
    throw new Error(message ?? `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const post = <T>(path: string, body?: unknown, method = "POST") =>
  request<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

// ─── Accounts ─────────────────────────────────────────────────────────────────

export interface User {
  id: number;
  email: string;
  name: string;
}

export const getMe = () => request<User>("/auth/me");
export const login = (email: string, password: string) => post<User>("/auth/login", { email, password });
export const signup = (name: string, email: string, password: string) => post<User>("/auth/signup", { name, email, password });
export const logout = () => post<void>("/auth/logout");
export const forgotPassword = (email: string) => post<{ detail: string }>("/auth/forgot", { email });
export const resetPassword = (token: string, password: string) => post<void>("/auth/reset", { token, password });
export const updateProfile = (name: string) => post<User>("/auth/me", { name }, "PATCH");
export const changePassword = (current_password: string, new_password: string) =>
  post<void>("/auth/password", { current_password, new_password });

// ─── Claims and sources ───────────────────────────────────────────────────────

const id = encodeURIComponent;

export const registerCsvUrl = (asOf: string) => `/api/register.csv?as_of=${asOf}`;

export const getClaims = (asOf: string) => request<ClaimsResponse>(`/claims?as_of=${asOf}`);

export const getClaim = (factId: string, asOf: string) =>
  request<Assessment>(`/claims/${id(factId)}?as_of=${asOf}`);

export const checkClaim = (claim: string, asOf: string) =>
  post<CheckResponse>("/claims/check", { claim, as_of: asOf });

export const getSources = () => request<{ sources: SourceDoc[] }>("/sources").then((r) => r.sources);

export const getSource = (documentId: string, asOf: string) =>
  request<SourceDetail>(`/sources/${id(documentId)}?as_of=${asOf}`);

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useApi<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ data: null, error: null });
    load().then(
      (data) => live && setState({ data, error: null }),
      (error: Error) => live && setState({ data: null, error: error.message }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}


/** Corpus retrieval records are separate from assessed graph evidence. */
export interface CorpusSource {
  source_id: string;
  title: string;
  source_type: string;
  original_file_path: string;
  lifecycle_status: string;
  approval_status: string | null;
  version: string | null;
  creation_date: string | null;
  last_updated_date: string | null;
  effective_start_date: string | null;
  effective_end_date: string | null;
  superseded_date: string | null;
  responsible_person_or_role: string | null;
  metadata_conflicts: Record<string, unknown>[];
}

export interface CorpusPassage {
  evidence: {
    evidence_id: string;
    source_id: string;
    locator: string;
    text: string;
    source_type: string;
    row_identifier?: string | null;
    structured_metadata?: { record?: Record<string, unknown>; [key: string]: unknown };
  };
  interpretation_status: "unassessed";
  relationship: null;
  retrieval: Record<string, unknown> | null;
  record_references: {
    evidence_id: string;
    locator: string;
    record_id: string;
    relationship: string;
  }[];
}

export interface CorpusGroup {
  position: number;
  source_id: string;
  lead_evidence_id: string;
  matched_evidence_ids: string[];
  passages: CorpusPassage[];
}

export interface CorpusSearchResponse {
  claim: string;
  status: "retrieved_unassessed";
  assessment: null;
  retrieval_method: string;
  ranked_group_limit: number;
  indexed_source_count: number;
  indexed_evidence_count: number;
  candidate_count: number;
  ranked_groups: CorpusGroup[];
  additional_linked_groups: CorpusGroup[];
  sources: CorpusSource[];
  limitations: string[];
}

export const searchCorpus = (claim: string) =>
  post<CorpusSearchResponse>("/corpus/search", { claim, limit: 8 });


export interface CorpusCitationResponse {
  evidence: CorpusPassage["evidence"];
  source: CorpusSource;
  interpretation_status: "unassessed";
  relationship: null;
  index_scope: "current";
}

export const getCorpusEvidence = (evidenceId: string, sourceId: string) =>
  request<CorpusCitationResponse>(
    `/corpus/evidence/${encodeURIComponent(evidenceId)}?source_id=${encodeURIComponent(sourceId)}`
  );


// Supplied assessments stay separate from retrieved candidates and register facts.
export const assessSupplied = (body: import("./suppliedAssessmentContract").SuppliedRequest) =>
  post<import("./suppliedAssessmentContract").SuppliedResult>("/corpus/assess-supplied", body);
