import { useState } from "react";
import { getSavedAssessments, getSavedAssessment, useApi, type SavedAssessmentSummary } from "./api";
import { SuppliedResultView } from "./SuppliedAssessment";
import { Badge, outcomeTone } from "./EvidenceUI";

export function savedResultType(row: {parent_run_id: string | null; record_type: string}) {
  if (row.parent_run_id) return "Human review revision · conditional";
  return row.record_type === "automatic_assessment" ? "Automatic result · review pending" : "Supplied assessment · review not established";
}
const grid = {display: "grid", gridTemplateColumns: "minmax(0,1fr) 170px 160px 110px", padding: "14px 20px"};
export function SavedRows({items, onOpen}: {items: SavedAssessmentSummary[]; onOpen: (id: string) => void}) {
  return <div className="ev-card" style={{padding: 0, overflow: "hidden"}}>
    <div style={{...grid, color: "#6b7280"}}><span>Claim / saved result</span><span>Formal verdict</span><span>In practice</span><span>As at</span></div>
    {items.map(row => <button key={row.run_id} onClick={() => onOpen(row.run_id)} style={{...grid, alignItems: "center", width: "100%", textAlign: "left", border: 0, borderTop: "1px solid #e5e3df", background: "white", color: "#1a1a1a", font: "inherit", cursor: "pointer"}}>
      <span style={{paddingRight: 20}}>{row.claim_text}<small style={{display: "block", color: "#6b7280", marginTop: 6}}>{savedResultType(row)} · Saved {new Date(row.created_at).toLocaleString()}</small></span>
      <span><Badge tone={outcomeTone(row.formal_outcome)}>{row.formal_outcome}</Badge></span>
      <span><Badge tone={outcomeTone(row.observed_outcome)}>{row.observed_outcome}</Badge></span><span>{row.as_of}</span>
    </button>)}
  </div>;
}
export function SavedDashboard({onOpen, onRegister, onCheck}: {onOpen: (id: string) => void; onRegister: () => void; onCheck: () => void}) {
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("All");
  const {data, error} = useApi(() => getSavedAssessments(offset), [offset]);
  const items = data?.items ?? [];
  const rows = items.filter(row => row.claim_text.toLowerCase().includes(query.toLowerCase()) && (verdict === "All" || row.overall_outcome === verdict));
  return <section className="ev-workspace"><h1>Dashboard</h1>
    <p className="ev-muted">Your saved assessments. Each revision is a separate snapshot; counts and filters apply to this page.</p>
    <div style={{display: "flex", gap: 12}}>
      {[['Contested', items.filter(r => r.overall_outcome === 'Contested').length], ['Insufficient evidence', items.filter(r => r.overall_outcome === 'Insufficient evidence').length], ['Saved results', items.length], ['Review revisions', items.filter(r => r.parent_run_id).length]].map(([label,n]) => <section className="ev-card" key={label} style={{flex: 1}}><strong style={{fontSize: 40}}>{data ? n : '—'}</strong><p className="ev-muted">{label}</p></section>)}
    </div>
    <div style={{display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap"}}><h2 style={{flex: 1}}>Saved assessment history</h2>
      <input aria-label="Search saved claims on this page" placeholder="Search this page…" value={query} onChange={e => setQuery(e.target.value)} />
      <select aria-label="Saved overall outcome" value={verdict} onChange={e => setVerdict(e.target.value)}>{['All','Supported','Contested','Contradicted','Insufficient evidence'].map(v => <option key={v}>{v}</option>)}</select>
      <button className="ev-button" onClick={onRegister}>Register results (recalculated)</button>
    </div>
    {error ? <p role="alert">Could not load saved assessments: {error}</p> : !data ? <p role="status">Loading saved assessments…</p> : <>
      {rows.length ? <SavedRows items={rows} onOpen={onOpen} /> : <p>{items.length ? 'No matches on this page.' : 'No saved assessments on this page.'}</p>}
      <div style={{display: "flex", gap: 12}}><button className="ev-button" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0,n-20))}>Previous</button><span>Page {offset / 20 + 1}</span><button className="ev-button" disabled={items.length < 20} onClick={() => setOffset(n => n+20)}>Next</button><button className="ev-button" onClick={onCheck}>Check a claim</button></div>
    </>}
  </section>;
}
export function SavedAssessmentView({runId, onBack, onOpen}: {runId: string; onBack: () => void; onOpen: (id: string) => void}) {
  const {data, error} = useApi(() => getSavedAssessment(runId), [runId]);
  return <section className="ev-workspace"><button className="ev-button" onClick={onBack}>Back to saved assessments</button>
    {error ? <p role="alert">Could not load saved assessment: {error}</p> : !data ? <p role="status">Loading saved snapshot…</p> : data.snapshot.run_id !== runId ? <p role="alert">Snapshot identity mismatch.</p> : <>
      <p>{savedResultType(data.snapshot)} · Saved {new Date(data.snapshot.created_at).toLocaleString()}</p>
      <p className="ev-muted">This is the result and evidence saved at that time. Opening it does not reassess the claim.</p>
      {data.snapshot.revision_reason && <p>Review reason: {data.snapshot.revision_reason}</p>}
      {data.snapshot.parent_run_id && <button className="ev-button" onClick={() => onOpen(data.snapshot.parent_run_id!)}>Open preceding snapshot</button>}
      <a href={`/api/assessments/${encodeURIComponent(runId)}/export`}>Download saved assessment</a>
      <SuppliedResultView result={data.snapshot.response} />
    </>}
  </section>;
}
