import { useEffect, useRef, useState } from "react";
import { REVIEW_AVAILABLE, saveAutomatic } from "./api";
import AssessmentReview from "./AssessmentReview";
import { SuppliedResultView } from "./SuppliedAssessment";
import { GraphResultView, isGraphResult } from "./GraphAssessment";
import type { Citation, SuppliedRequest, SuppliedResult } from "./suppliedAssessmentContract";

export interface ReviewInput {
  stance: string; rationale: string; judgement_basis: string; citations: Citation[];
  scope_matches: boolean | null; temporal_matches: boolean | null; authority_verified: boolean | null;
  directness: number; specificity: number; completeness: number;
  [key: string]: unknown;
}
export interface AssessmentSnapshot {
  snapshot: { run_id: string; parent_run_id?: string | null; request: SuppliedRequest & { inputs: ReviewInput[] }; response: SuppliedResult };
  snapshot_sha256: string;
}

export function checkAutomaticResponse(value: AssessmentSnapshot, request: {claim: string; facet: string; as_of: string}) {
  const result = value.snapshot.response;
  if (isGraphResult(result)) {
    // Graph-engine results carry no canonical assessment; the verdict is on the response itself.
    if (result.claim_text !== request.claim || result.facet !== request.facet || result.as_of !== request.as_of ||
        !result.persisted || result.status !== "assessed_automatically" || !result.overall_outcome)
      throw new Error("Assessment response does not match this claim or its processing state.");
    return value;
  }
  const canonical = result.canonical_assessment;
  const failed = canonical?.processing.status === "failed";
  if (result.claim_text !== request.claim || result.facet !== request.facet || result.as_of !== request.as_of ||
      !result.persisted || (failed ? result.status !== "processing_failed" || canonical.overall_outcome !== null || canonical.confidence.score !== null
        : result.status !== "assessed_automatically") ||
      (canonical && !failed && (canonical.processing.status !== "assessed" || !canonical.overall_outcome ||
        typeof canonical.confidence.score !== "number" || !Number.isFinite(canonical.confidence.score) || canonical.confidence.score < 0 || canonical.confidence.score > 100))) {
    throw new Error("Assessment response does not match this claim or its processing state.");
  }
  return value;
}

// With autoStart the assessment runs as soon as `ready` is true (date already chosen on the
// claim form, no scope question waiting), so the user reaches a result in one step. The form
// below is then only used for "Run again" or after a failure.
export default function AutomaticAssessment({ claim, initialAsOf, expectedFacet, autoStart = false, ready = true, onDetailChange, onResultChange, onNewClaim }: {
  claim: string; initialAsOf?: string; expectedFacet?: string; autoStart?: boolean; ready?: boolean;
  onDetailChange?: (open: boolean) => void; onResultChange?: (ready: boolean) => void; onNewClaim?: () => void;
}) {
  const [asOf, setAsOf] = useState(() => initialAsOf ?? new Date().toLocaleDateString("en-CA"));
  const [record, setRecord] = useState<AssessmentSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState(false);
  const [showForm, setShowForm] = useState(!autoStart);
  const [reviewOpen, setReviewOpen] = useState(false);
  const started = useRef(false);
  // Retries of the same command keep their key after a transport failure.
  const pending = useRef<{ body: string; id: string } | null>(null);
  const keyFor = (body: unknown) => {
    const text = JSON.stringify(body);
    if (pending.current?.body !== text) pending.current = { body: text, id: crypto.randomUUID() };
    return pending.current.id;
  };
  async function assess() {
    setBusy(true); setError(null);
    const query = { claim, facet: expectedFacet ?? claim, as_of: asOf };
    try {
      const value = checkAutomaticResponse(await saveAutomatic({ ...query, request_id: keyFor(query) }), query);
      setRecord(value); onResultChange?.(true); pending.current = null;
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Assessment unavailable."); setShowForm(true); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!autoStart || !ready || started.current) return;
    started.current = true; // once per mount, including under StrictMode's double effect
    void assess();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, ready]);
  const graph = !!record && isGraphResult(record.snapshot.response);
  // Review revisions were retired with the legacy scorers, so graph results are read-only.
  const reviewable = REVIEW_AVAILABLE && !!record && !graph && record.snapshot.response.canonical_assessment?.processing.status !== "failed";
  return <section className={`ev-workspace ev-automatic${reviewOpen && !detail ? " ev-with-drawer" : ""}`}>
    {!showForm && !record && busy && <div className="ev-state" role="status"><strong>Assessing your claim…</strong>Interpreting your claim and checking the evidence. Keep this page open.</div>}
    <section className="ev-card" hidden={detail || !!record || !showForm}>
      <span className="ev-kicker">Automatic assessment</span>
      <p>Assess your claim against the available evidence, then read each finding and the passages behind it.</p>
      <div className="ev-inline-form">
        <label>Assessment date <input type="date" value={asOf} disabled={busy} onChange={event => { setAsOf(event.target.value); setRecord(null); }} /></label>
        <button className="ev-button ev-button-primary" disabled={busy || !asOf} onClick={assess}>{busy ? "Assessing…" : "Assess claim and save result"}</button>
      </div>
      {busy && <p role="status">Interpreting your claim and checking the evidence. Keep this page open.</p>}
      {error && <p role="alert" style={{ color: "var(--red)" }}>{error}</p>}
      <details className="ev-notes"><summary>Notes and limits</summary>
        <p className="ev-muted">Each result is saved separately with the passages it was based on.</p>
      </details>
    </section>
    {record && <>
      <div className="ev-toolbar" hidden={detail}><div><span className="ev-crumb">Claims / Assessment</span><h1>Assessment result</h1></div><div className="ev-chips" style={{ margin: 0 }}>{reviewable && <button className="ev-button" aria-expanded={reviewOpen} onClick={() => setReviewOpen(true)}>Review</button>}{onNewClaim && <button className="ev-button" onClick={onNewClaim}>New claim</button>}<a className="ev-button" href={`/api/assessments/${record.snapshot.run_id}/export`}>Export</a><button className="ev-button ev-button-primary" onClick={() => { setRecord(null); setShowForm(true); onResultChange?.(false); }}>Run again</button></div></div>
      {record.snapshot.parent_run_id && <p role="status" hidden={detail}>Review saved as a separate revision. The original assessment is preserved.</p>}
      {isGraphResult(record.snapshot.response) ? <GraphResultView key={record.snapshot.run_id} result={record.snapshot.response} />
        : <SuppliedResultView key={record.snapshot.run_id} result={record.snapshot.response} onDetailChange={open => { setDetail(open); onDetailChange?.(open); }} />}
      {reviewable && <div hidden={detail}><AssessmentReview key={record.snapshot.run_id} record={record} open={reviewOpen} onOpenChange={setReviewOpen} onSaved={value => { setRecord(value); setReviewOpen(false); }} /></div>}
    </>}
  </section>;
}
