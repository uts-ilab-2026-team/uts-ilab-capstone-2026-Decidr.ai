import { useState } from "react";
import { REVIEW_AVAILABLE, getSavedAssessments, getSavedAssessment, useApi, type SavedAssessmentSummary } from "./api";
import AssessmentReview from "./AssessmentReview";
import { SuppliedResultView, assessmentConfidence, processingExplanation } from "./SuppliedAssessment";
import { Badge, outcomeTone } from "./EvidenceUI";
import { GraphResultView, isGraphResult } from "./GraphAssessment";

const GRAPH_BASIS = "graph_engine_deterministic_scoring";
export function savedResultType(row: {parent_run_id: string | null; record_type: string; outcome_basis?: string}) {
  if (row.record_type === "automatic_processing_failure") return "Processing incomplete · no assessment outcome";
  if (row.parent_run_id) return "Human review revision · conditional";
  if (row.record_type === "automatic_assessment") return row.outcome_basis === GRAPH_BASIS ? "Automatic result · graph assessment" : "Automatic result · review pending";
  return "Supplied assessment · review not established";
}
export function savedOutcome(row: SavedAssessmentSummary) {
  if (row.processing?.status === "failed" || row.record_type === "automatic_processing_failure") return "Assessment not completed";
  return row.processing?.status === "assessed" ? row.overall_outcome : row.claim_conclusion?.label ?? row.overall_outcome;
}
function savedBasis(row: SavedAssessmentSummary) {
  if (row.processing?.status === "failed" || row.record_type === "automatic_processing_failure") return processingExplanation(row.processing?.code ?? null);
  if (row.outcome_basis === GRAPH_BASIS) return "Scored on the organisation graph";
  if (row.claim_conclusion?.basis === "canonical_component_assessment" || row.processing?.status === "assessed") return "Evaluated claim components";
  return row.claim_conclusion ? (row.claim_conclusion.basis === "unsupported_interpretation" ? "Interpretation incomplete" : "Recorded event comparison") : `Formal: ${row.formal_outcome}; Practice: ${row.observed_outcome}`;
}
export function SavedRows({items, onOpen}: {items: SavedAssessmentSummary[]; onOpen: (id: string) => void}) {
  return <div className="ev-card ev-table" style={{padding: 0}}>
    <div className="ev-table-head"><span>Claim</span><span>Assessment</span><span>Evidence basis</span><span>As at</span></div>
    {items.map(row => <button key={row.run_id} className="ev-table-row" onClick={() => onOpen(row.run_id)}>
      <span>{row.claim_text}<small>{savedResultType(row)} · Saved {new Date(row.created_at).toLocaleString()}</small></span>
      <span><Badge tone={outcomeTone(savedOutcome(row))}>{savedOutcome(row)}</Badge>{row.processing?.status === "assessed" && row.confidence?.score !== null && row.confidence?.score !== undefined && <small>Assessment confidence: {assessmentConfidence(row.confidence.score)} · uncalibrated</small>}</span>
      <span>{savedBasis(row)}</span><span>{row.as_of}</span>
    </button>)}
  </div>;
}
export function SavedDashboard({onOpen, onCheck}: {onOpen: (id: string) => void; onCheck: () => void}) {
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("All");
  const {data, error} = useApi(() => getSavedAssessments(offset), [offset]);
  const items = data?.items ?? [];
  const rows = items.filter(row => row.claim_text.toLowerCase().includes(query.toLowerCase()) && (verdict === "All" || savedOutcome(row) === verdict));
  return <section className="ev-workspace"><h1>Dashboard</h1>
    <p className="ev-muted" style={{ marginTop: 4 }}>Every claim you check is saved here. Counts and filters apply to this page.</p>
    <div className="ev-tiles">
      {[['Saved results', items.length], ['Contested', items.filter(r => ['Contested', 'Conflicting evidence', 'Conflicting records'].includes(savedOutcome(r))).length], ['Insufficient evidence', items.filter(r => savedOutcome(r) === 'Insufficient evidence').length], ['Contradicted', items.filter(r => savedOutcome(r).startsWith('Contradicted')).length]].map(([label, n]) => <section className={`ev-tile${data && n === 0 ? " ev-tile-empty" : ""}`} key={label}><strong>{data ? n : '—'}</strong><span>{label}</span></section>)}
    </div>
    <div className="ev-filters"><h2>Saved assessments</h2>
      <input aria-label="Search saved claims on this page" placeholder="Search this page…" value={query} onChange={e => setQuery(e.target.value)} />
      <select aria-label="Saved overall outcome" value={verdict} onChange={e => setVerdict(e.target.value)}>{['All','Assessment not completed','Not assessed automatically','Supported','Partially supported','Conflicting evidence','Contested','Contradicted','Insufficient evidence','Supported by the available record','Partially supported by the available records','Contradicted by the available records','Conflicting records','Not established by the available records'].map(v => <option key={v}>{v}</option>)}</select>
    </div>
    {error ? <p role="alert">Could not load saved assessments: {error}</p> : !data ? <p role="status">Loading saved assessments…</p> : <>
      {rows.length ? <SavedRows items={rows} onOpen={onOpen} /> : <div className="ev-state">
        <strong>{items.length ? 'No matches on this page.' : 'No saved assessments on this page.'}</strong>
        {!items.length && <>Check a claim to see how it holds up against the indexed sources.<div style={{ marginTop: 16 }}><button className="ev-button ev-button-primary" onClick={onCheck}>Check a claim</button></div></>}
      </div>}
      {(offset > 0 || items.length >= 20) && <div className="ev-pager"><button className="ev-button" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0,n-20))}>Previous</button><span>Page {offset / 20 + 1}</span><button className="ev-button" disabled={items.length < 20} onClick={() => setOffset(n => n+20)}>Next</button></div>}
    </>}
  </section>;
}
export function SavedAssessmentView({runId, onBack, onOpen, onRunAgain}: {runId: string; onBack: () => void; onOpen: (id: string) => void; onRunAgain: (claim: string, asOf?: string) => void}) {
  const [detail, setDetail] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const {data, error} = useApi(() => getSavedAssessment(runId), [runId]);
  const reviewable = REVIEW_AVAILABLE && !!data && !isGraphResult(data.snapshot.response) && data.snapshot.response.canonical_assessment?.processing.status !== "failed";
  return <section className={`ev-workspace${reviewOpen && !detail ? " ev-with-drawer" : ""}`}><button className="ev-back" onClick={onBack}>← Back to saved assessments</button>
    {error ? <p role="alert">Could not load saved assessment: {error}</p> : !data ? <p role="status">Loading saved snapshot…</p> : data.snapshot.run_id !== runId ? <p role="alert">Snapshot identity mismatch.</p> : <>
      <div className="ev-toolbar" hidden={detail}><div><span className="ev-crumb">{savedResultType({...data.snapshot, outcome_basis: data.snapshot.response.assurance?.outcome_basis})} · Saved {new Date(data.snapshot.created_at).toLocaleString()}</span><h1>Saved assessment</h1></div>
        <div className="ev-chips" style={{ margin: 0 }}>{reviewable && <button className="ev-button" aria-expanded={reviewOpen} onClick={() => setReviewOpen(true)}>Review</button>}<a className="ev-button" href={`/api/assessments/${encodeURIComponent(runId)}/export`}>Export</a><button className="ev-button ev-button-primary" onClick={() => onRunAgain(data.snapshot.request.claim_text, data.snapshot.request.as_of)}>Run again</button></div></div>
      <p className="ev-muted" style={{ marginBottom: 16 }}>This is the result and evidence saved at that time. Opening it does not reassess the claim.</p>
      {data.snapshot.revision_reason && <p>Review reason: {data.snapshot.revision_reason}</p>}
      {data.snapshot.parent_run_id && <button className="ev-button" onClick={() => onOpen(data.snapshot.parent_run_id!)}>Open preceding snapshot</button>}
      {isGraphResult(data.snapshot.response) ? <GraphResultView result={data.snapshot.response} /> : <SuppliedResultView result={data.snapshot.response} onDetailChange={setDetail} />}
      {reviewable && <div hidden={detail}><AssessmentReview key={runId} record={data} open={reviewOpen} onOpenChange={setReviewOpen} onSaved={value => { setReviewOpen(false); onOpen(value.snapshot.run_id); }} /></div>}
    </>}
  </section>;
}
