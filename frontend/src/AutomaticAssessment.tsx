import { useRef, useState } from "react";
import { saveAutomatic } from "./api";
import AssessmentReview from "./AssessmentReview";
import { SuppliedResultView } from "./SuppliedAssessment";
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

export default function AutomaticAssessment({ claim, expectedFacet, onDetailChange, onResultChange }: {
  claim: string; expectedFacet?: string; onDetailChange?: (open: boolean) => void; onResultChange?: (ready: boolean) => void;
}) {
  const [asOf, setAsOf] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [record, setRecord] = useState<AssessmentSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState(false);
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
      const value = await saveAutomatic({ ...query, request_id: keyFor(query) });
      if (value.snapshot.response.claim_text !== claim || value.snapshot.response.facet !== query.facet ||
          value.snapshot.response.as_of !== asOf || value.snapshot.response.status !== "assessed_automatically" ||
          !value.snapshot.response.persisted) throw new Error("Assessment response does not match this claim.");
      setRecord(value); onResultChange?.(true); pending.current = null;
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Assessment unavailable."); }
    finally { setBusy(false); }
  }
  return <section className="ev-workspace ev-automatic">
    <section className="ev-card" hidden={detail || !!record}>
      <span className="ev-kicker">Automatic assessment</span>
      <p>Assess supported approval rules, then review the result. Unsupported comparisons remain unresolved.</p>
      <label>Assessment date <input type="date" value={asOf} disabled={busy} onChange={event => { setAsOf(event.target.value); setRecord(null); }} /></label>
      <button className="ev-button ev-button-primary" disabled={busy || !asOf} onClick={assess}>{busy ? "Assessing…" : "Assess claim and save result"}</button>
      <p className="ev-muted">Each result is saved separately. Review revisions preserve the original result and exact citations.</p>
      {error && <p role="alert">{error}</p>}
    </section>
    {record && <>
      <div className="ev-toolbar" hidden={detail}><h2>Claims / Assessment</h2><div className="ev-chips"><a className="ev-button" href={`/api/assessments/${record.snapshot.run_id}/export`}>Export saved assessment</a><button className="ev-button" onClick={() => { setRecord(null); onResultChange?.(false); }}>Run again</button></div></div>
      {record.snapshot.parent_run_id && <p role="status" hidden={detail}>Review saved as a separate revision. The original assessment is preserved.</p>}
      <SuppliedResultView key={record.snapshot.run_id} result={record.snapshot.response} onDetailChange={open => { setDetail(open); onDetailChange?.(open); }} />
      <div hidden={detail}><AssessmentReview key={record.snapshot.run_id} record={record} onSaved={setRecord} /></div>
    </>}
  </section>;
}
