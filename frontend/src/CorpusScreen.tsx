import { useState } from "react";
import AutomaticAssessment from "./AutomaticAssessment";
import { getCorpusEvidence, useApi, type CorpusGroup, type CorpusSource } from "./api";
import { Badge, PassageView, SourceMetadata } from "./EvidenceUI";

export default function CorpusScreen(props: { claim: string; initialAsOf?: string; onBack: () => void }) {
  return <CorpusClaimScreen key={props.claim} {...props} />;
}

// The graph engine does its own retrieval, so a claim goes straight to assessment: no separate
// corpus search and no scope question in between.
function CorpusClaimScreen({ claim, initialAsOf, onBack }: { claim: string; initialAsOf?: string; onBack: () => void }) {
  const [assessmentReady, setAssessmentReady] = useState(false);
  return <main className="ev-workspace" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "36px 48px" }}>
    <div hidden={assessmentReady}>
      <div className="ev-toolbar"><div><span className="ev-crumb">Claims / Assessment</span><h1>Checking your claim</h1></div>
        <button className="ev-button" onClick={onBack}>New claim</button></div>
      <section className="ev-card"><span className="ev-kicker">Your claim</span>
        <p className="ev-claim">{claim}</p>
      </section>
    </div>
    <AutomaticAssessment claim={claim} initialAsOf={initialAsOf} autoStart={initialAsOf !== undefined} onResultChange={setAssessmentReady} />
  </main>;
}

export function CorpusEvidenceDetail({ group, source }: { group: CorpusGroup; source?: CorpusSource }) {
  const matched = new Set(group.matched_evidence_ids);
  return <>
    <div className="ev-chips"><Badge>Retrieved candidate · Unassessed</Badge><Badge>{source?.lifecycle_status ?? "unknown"}</Badge></div>
    <p className="ev-muted">No verdict or confidence assigned to these retrieval candidates.</p>
    {group.passages.map(passage => <section className="ev-card" key={passage.evidence.evidence_id}>
      <h3>{matched.has(passage.evidence.evidence_id) ? "Retrieved passage" : "Section context"}</h3>
      <PassageView evidence={passage.evidence} />
      <p className="ev-muted ev-mono">{passage.evidence.evidence_id} · {passage.evidence.locator}</p>
      <CitationLookup evidenceId={passage.evidence.evidence_id} sourceId={passage.evidence.source_id}
        expectedText={passage.evidence.text} expectedLocator={passage.evidence.locator} />
      {passage.record_references.length > 0 && <><h3>Explicit record connections</h3>
        <ul>{passage.record_references.map((r, i) => <li key={i}>{r.record_id} — {r.relationship.replace(/_/g, " ")}</li>)}</ul>
        <p className="ev-muted">These connections identify records; they do not establish a relationship to the claim.</p></>}
    </section>)}
    <SourceMetadata source={source} />
  </>;
}

type CitationProps = { evidenceId: string; sourceId: string; expectedText: string; expectedLocator: string };
function CitationLookup(props: CitationProps) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Open current citation</summary>{open && <CitationContent {...props} />}
  </details>;
}
function CitationContent({ evidenceId, sourceId, expectedText, expectedLocator }: CitationProps) {
  const { data, error } = useApi(() => getCorpusEvidence(evidenceId, sourceId), [evidenceId, sourceId]);
  if (error) return <p role="alert">Citation unavailable: {error}</p>;
  if (!data) return <p role="status">Loading citation…</p>;
  if (data.evidence.evidence_id !== evidenceId || data.evidence.source_id !== sourceId || data.source.source_id !== sourceId)
    return <p role="alert">Citation identity mismatch. Please run the search again.</p>;
  const changed = data.evidence.text !== expectedText || data.evidence.locator !== expectedLocator;
  return <section className="ev-notice">
    {changed && <p role="alert">The stored passage has changed since this search. Run the search again before using this citation.</p>}
    <PassageView evidence={data.evidence} />
    <p className="ev-mono">{data.evidence.evidence_id} · {data.evidence.locator}</p>
    <SourceMetadata source={data.source} />
    <p className="ev-muted">This is the passage stored in the current corpus index, not a historical assessment snapshot. Its relationship to your claim remains unassessed. Text checks do not verify source metadata or supplied judgements.</p>
  </section>;
}
