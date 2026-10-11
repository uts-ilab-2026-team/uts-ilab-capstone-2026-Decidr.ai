import { useRef, useState } from "react";
import { saveAutomatic, saveAssessmentRevision } from "./api";
import { SuppliedResultView } from "./SuppliedAssessment";
import type { Citation, SuppliedRequest, SuppliedResult } from "./suppliedAssessmentContract";

export interface ReviewInput {
  stance: string; rationale: string; judgement_basis: string; citations: Citation[];
  scope_matches: boolean | null; temporal_matches: boolean | null; authority_verified: boolean | null;
  directness: number; specificity: number; completeness: number;
  [key: string]: unknown;
}
export interface AssessmentSnapshot {
  snapshot: { run_id: string; request: SuppliedRequest & { inputs: ReviewInput[] }; response: SuppliedResult };
  snapshot_sha256: string;
}

export default function AutomaticAssessment({ claim, expectedFacet, onDetailChange }: {
  claim: string; expectedFacet?: string; onDetailChange?: (open: boolean) => void;
}) {
  const [asOf, setAsOf] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [record, setRecord] = useState<AssessmentSnapshot | null>(null);
  const [inputs, setInputs] = useState<ReviewInput[]>([]);
  const [reason, setReason] = useState("");
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
      setRecord(value); setInputs(value.snapshot.request.inputs); setReason(""); pending.current = null;
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Assessment unavailable."); }
    finally { setBusy(false); }
  }
  async function review() {
    if (!record) return;
    setBusy(true); setError(null);
    const query = { assessment: { ...record.snapshot.request, inputs }, parent_run_id: record.snapshot.run_id, revision_reason: reason };
    try {
      const value = await saveAssessmentRevision({ ...query, request_id: keyFor(query) });
      setRecord(value); setInputs(value.snapshot.request.inputs); setReason(""); pending.current = null;
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review could not be saved."); }
    finally { setBusy(false); }
  }
  const edit = (index: number, field: string, value: unknown) => setInputs(items => items.map((item, i) => i === index ? { ...item, [field]: value } : item));
  return <section className="ev-workspace ev-automatic">
    <section className="ev-card" hidden={detail}>
      <span className="ev-kicker">Automatic assessment</span>
      <p>Assess supported approval rules, then review the result. Unsupported comparisons remain unresolved.</p>
      <label>Assessment date <input type="date" value={asOf} disabled={busy} onChange={event => { setAsOf(event.target.value); setRecord(null); }} /></label>
      <button className="ev-button ev-button-primary" disabled={busy || !asOf} onClick={assess}>{busy ? "Assessing…" : "Assess claim and save result"}</button>
      <p className="ev-muted">Each result is saved separately. Review revisions preserve the original result and exact citations.</p>
      {error && <p role="alert">{error}</p>}
    </section>
    {record && <>
      <p hidden={detail}><a href={`/api/assessments/${record.snapshot.run_id}/export`}>Download this saved assessment</a></p>
      <SuppliedResultView key={record.snapshot.run_id} result={record.snapshot.response} onDetailChange={open => { setDetail(open); onDetailChange?.(open); }} />
      <details className="ev-card" hidden={detail}>
        <summary>Review this result</summary>
        <p>Inspect the exact citations above before changing a judgement. Revisions assess the current corpus; the previous snapshot stays unchanged. Confirm authority only with evidence of adoption rights or delegation for this scope and date. In Judgement basis, identify the supporting source, passage and applicable dates. If evidence is missing, leave authority Unresolved and explain the gap.</p>
        {inputs.map((item, index) => <fieldset key={index} disabled={busy}>
          <legend>Evidence {index + 1}</legend>
          <p>{item.rationale}</p>
          <p className="ev-muted">Inspect evidence {index + 1} using its citation identifiers below.</p>
          {item.citations.map((citation, i) => <div key={i}>
            <p className="ev-quote">{citation.quotation}</p>
            <p className="ev-mono">{citation.source_id} · {citation.evidence_id} · {citation.locator}</p>
          </div>)}
          <label>Relationship <select value={item.stance} onChange={event => edit(index, "stance", event.target.value)}>
            {["support", "contradict", "qualify", "context", "unresolved"].map(value => <option key={value}>{value}</option>)}
          </select></label>
          {(["scope_matches", "temporal_matches", "authority_verified"] as const).map(field => <label key={field}>{field.replace(/_/g, " ")} <select value={String(item[field])} onChange={event => edit(index, field, event.target.value === "null" ? null : event.target.value === "true")}>
            <option value="null">Unresolved</option><option value="true">Verified</option><option value="false">Does not match</option>
          </select></label>)}
          {(["directness", "specificity", "completeness"] as const).map(field => <label key={field}>{field} <input type="number" min="0" max="1" step="0.1" value={item[field]} onChange={event => edit(index, field, Number(event.target.value))} /></label>)}
          <label>Judgement basis <textarea value={item.judgement_basis} onChange={event => edit(index, "judgement_basis", event.target.value)} /></label>
          <label>Interpretation rationale <textarea value={item.rationale} onChange={event => edit(index, "rationale", event.target.value)} /></label>
        </fieldset>)}
        <label>Reason for this review <textarea value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
        <button className="ev-button ev-button-primary" disabled={busy || !reason.trim() || !inputs.length} onClick={review}>Save review as a new revision</button>
        <p className="ev-muted">Reviewer declarations remain conditional; a saved review is not independent verification.</p>
      </details>
    </>}
  </section>;
}
