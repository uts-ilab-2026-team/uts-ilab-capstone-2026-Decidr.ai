import { useState } from "react";
import { getSavedAssessments, getSavedAssessment, useApi, type SavedAssessmentSummary } from "./api";
import AssessmentReview from "./AssessmentReview";
import { SuppliedResultView, assessmentConfidence, processingExplanation } from "./SuppliedAssessment";
import { Badge, outcomeTone } from "./EvidenceUI";

export function savedResultType(row: {parent_run_id: string | null; record_type: string}) {
  if (row.record_type === "automatic_processing_failure") return "Processing incomplete · no assessment outcome";
  if (row.parent_run_id) return "Human review revision · conditional";
  return row.record_type === "automatic_assessment" ? "Automatic result · review pending" : "Supplied assessment · review not established";
}
export function savedOutcome(row: SavedAssessmentSummary) {
  if (row.processing?.status === "failed" || row.record_type === "automatic_processing_failure") return "Assessment not completed";
  return row.processing?.status === "assessed" ? row.overall_outcome : row.claim_conclusion?.label ?? row.overall_outcome;
}
function savedBasis(row: SavedAssessmentSummary) {
  if (row.processing?.status === "failed" || row.record_type === "automatic_processing_failure") return processingExplanation(row.processing?.code ?? null);
  if (row.claim_conclusion?.basis === "canonical_component_assessment" || row.processing?.status === "assessed") return "Evaluated claim components";
  return row.claim_conclusion ? (row.claim_conclusion.basis === "unsupported_interpretation" ? "Interpretation incomplete" : "Recorded event comparison") : `Formal: ${row.formal_outcome}; Practice: ${row.observed_outcome}`;
}
const grid = {display: "grid", gridTemplateColumns: "minmax(0,1fr) 170px 160px 110px", padding: "14px 20px"};
export function SavedRows({items, onOpen}: {items: SavedAssessmentSummary[]; onOpen: (id: string) => void}) {
  return <div className="ev-card" style={{padding: 0, overflow: "hidden"}}>
    <div style={{...grid, color: "#6b7280"}}><span>Claim / saved result</span><span>Claim assessment</span><span>Evidence basis</span><span>As at</span></div>
    {items.map(row => <button key={row.run_id} onClick={() => onOpen(row.run_id)} style={{...grid, alignItems: "center", width: "100%", textAlign: "left", border: 0, borderTop: "1px solid #e5e3df", background: "white", color: "#1a1a1a", font: "inherit", cursor: "pointer"}}>
      <span style={{paddingRight: 20}}>{row.claim_text}<small style={{display: "block", color: "#6b7280", marginTop: 6}}>{savedResultType(row)} · Saved {new Date(row.created_at).toLocaleString()}</small></span>
      <span><Badge tone={outcomeTone(savedOutcome(row))}>{savedOutcome(row)}</Badge>{row.processing?.status === "assessed" && row.confidence?.score !== null && row.confidence?.score !== undefined && <small style={{display: "block"}}>Assessment confidence: {assessmentConfidence(row.confidence.score)} · uncalibrated</small>}</span>
      <span>{savedBasis(row)}</span><span>{row.as_of}</span>
    </button>)}
  </div>;
}
export function SavedDashboard({onOpen, onRegister, onCheck}: {onOpen: (id: string) => void; onRegister: () => void; onCheck: () => void}) {
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("All");
  const {data, error} = useApi(() => getSavedAssessments(offset), [offset]);
  const items = data?.items ?? [];
  const rows = items.filter(row => row.claim_text.toLowerCase().includes(query.toLowerCase()) && (verdict === "All" || savedOutcome(row) === verdict));
  return <section className="ev-workspace"><h1>Dashboard</h1>
    <p className="ev-muted">Your saved assessments. Each revision is a separate snapshot; counts and filters apply to this page.</p>
    <div style={{display: "flex", gap: 12}}>
      {[['Conflicting evidence', items.filter(r => ['Contested', 'Conflicting evidence', 'Conflicting records'].includes(savedOutcome(r))).length], ['Insufficient evidence', items.filter(r => savedOutcome(r) === 'Insufficient evidence').length], ['Saved results', items.length], ['Review revisions', items.filter(r => r.parent_run_id).length]].map(([label,n]) => <section className="ev-card" key={label} style={{flex: 1}}><strong style={{fontSize: 40}}>{data ? n : '—'}</strong><p className="ev-muted">{label}</p></section>)}
    </div>
    <div style={{display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap"}}><h2 style={{flex: 1}}>Saved assessment history</h2>
      <input aria-label="Search saved claims on this page" placeholder="Search this page…" value={query} onChange={e => setQuery(e.target.value)} />
      <select aria-label="Saved overall outcome" value={verdict} onChange={e => setVerdict(e.target.value)}>{['All','Assessment not completed','Not assessed automatically','Supported','Partially supported','Conflicting evidence','Contested','Contradicted','Insufficient evidence','Supported by the available record','Partially supported by the available records','Contradicted by the available records','Conflicting records','Not established by the available records'].map(v => <option key={v}>{v}</option>)}</select>
      <button className="ev-button" onClick={onRegister}>Register results (recalculated)</button>
    </div>
    {error ? <p role="alert">Could not load saved assessments: {error}</p> : !data ? <p role="status">Loading saved assessments…</p> : <>
      {rows.length ? <SavedRows items={rows} onOpen={onOpen} /> : <p>{items.length ? 'No matches on this page.' : 'No saved assessments on this page.'}</p>}
      <div style={{display: "flex", gap: 12}}><button className="ev-button" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0,n-20))}>Previous</button><span>Page {offset / 20 + 1}</span><button className="ev-button" disabled={items.length < 20} onClick={() => setOffset(n => n+20)}>Next</button><button className="ev-button" onClick={onCheck}>Check a claim</button></div>
    </>}
  </section>;
}
export function SavedAssessmentView({runId, onBack, onOpen, onRunAgain}: {runId: string; onBack: () => void; onOpen: (id: string) => void; onRunAgain: (claim: string, asOf?: string) => void}) {
  const [detail, setDetail] = useState(false);
  const {data, error} = useApi(() => getSavedAssessment(runId), [runId]);
  return <section className="ev-workspace"><button className="ev-button" onClick={onBack}>Back to saved assessments</button>
    {error ? <p role="alert">Could not load saved assessment: {error}</p> : !data ? <p role="status">Loading saved snapshot…</p> : data.snapshot.run_id !== runId ? <p role="alert">Snapshot identity mismatch.</p> : <>
      <p>{savedResultType(data.snapshot)} · Saved {new Date(data.snapshot.created_at).toLocaleString()}</p>
      <p className="ev-muted">This is the result and evidence saved at that time. Opening it does not reassess the claim.</p>
      {data.snapshot.revision_reason && <p>Review reason: {data.snapshot.revision_reason}</p>}
      {data.snapshot.parent_run_id && <button className="ev-button" onClick={() => onOpen(data.snapshot.parent_run_id!)}>Open preceding snapshot</button>}
      <div className="ev-toolbar" hidden={detail}><a className="ev-button" href={`/api/assessments/${encodeURIComponent(runId)}/export`}>Export saved assessment</a><button className="ev-button" onClick={() => onRunAgain(data.snapshot.request.claim_text, data.snapshot.request.as_of)}>Run again</button></div>
      <SuppliedResultView result={data.snapshot.response} onDetailChange={setDetail} />
      {data.snapshot.response.canonical_assessment?.processing.status !== "failed" && <div hidden={detail}><AssessmentReview key={runId} record={data} onSaved={value => onOpen(value.snapshot.run_id)} /></div>}
    </>}
  </section>;
}
