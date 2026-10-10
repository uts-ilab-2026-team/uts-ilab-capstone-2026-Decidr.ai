import { useRef, useState } from "react";
import SuppliedAssessment from "./SuppliedAssessment";
import { searchCorpus, getCorpusEvidence, useApi, type CorpusGroup, type CorpusSource } from "./api";
import { Badge, DetailFrame, EvidenceRow, PassageView, SourceMetadata, passagePreview } from "./EvidenceUI";

export default function CorpusScreen({ claim, onBack }: { claim: string; onBack: () => void }) {
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<CorpusGroup | null>(null);
  const [assessmentDetail, setAssessmentDetail] = useState(false);
  const origin = useRef<HTMLElement | null>(null);
  const { data, error } = useApi(() => searchCorpus(claim), [claim, attempt]);
  const sources = new Map(data?.sources.map((source) => [source.source_id, source]) ?? []);
  const open = (group: CorpusGroup) => { origin.current = document.activeElement as HTMLElement; setSelected(group); };
  const back = () => { setSelected(null); requestAnimationFrame(() => origin.current?.focus()); };
  const rows = (groups: CorpusGroup[]) => <div className="ev-list">{groups.map(group => {
    const source = sources.get(group.source_id);
    const lead = group.passages.find(p => p.evidence.evidence_id === group.lead_evidence_id) ?? group.passages[0];
    return <EvidenceRow key={group.lead_evidence_id}
      title={`${group.position}. ${source?.title ?? group.source_id}${lead?.evidence.row_identifier ? ` · ${lead.evidence.row_identifier}` : ""}`}
      subtitle={`${group.passages.length} passage(s) · ${group.source_id}`}
      preview={lead ? passagePreview(lead.evidence) : "No passage text available"}
      badges={<><Badge>{source?.lifecycle_status ?? "unknown"}</Badge><Badge>Unassessed</Badge></>}
      onOpen={() => open(group)} />;
  })}</div>;
  return <main className="ev-workspace" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "36px 48px" }}>
    <div hidden={!!selected || assessmentDetail}>
      <div className="ev-toolbar"><div><span className="ev-kicker">Claims / Corpus evidence</span><h1>Evidence for your claim</h1></div>
        <button className="ev-button" onClick={onBack}>New search</button></div>
      <section className="ev-card"><span className="ev-kicker">Your submitted claim</span>
        <p className="ev-claim">{claim}</p><Badge>Retrieval candidates · Unassessed</Badge>
        <p className="ev-muted">Retrieval does not establish support, contradiction, credibility or temporal applicability.</p>
      </section>
    </div>
    <div hidden={!!selected}><SuppliedAssessment key={claim} claim={claim} onDetailChange={setAssessmentDetail} /></div>
    <div hidden={!!selected || assessmentDetail}>
      {!data && !error && <p role="status">Searching the corpus…</p>}
      {error && <section className="ev-card" role="alert"><h2>Corpus search unavailable</h2><p>{error}</p>
        <button className="ev-button" onClick={() => setAttempt(v => v + 1)}>Retry</button></section>}
      {data && <>
        <div className="ev-toolbar"><h2 style={{ margin: 0 }}>Retrieved evidence</h2><span className="ev-muted">
          {data.indexed_source_count} indexed sources · {data.indexed_evidence_count} evidence units
        </span></div>
        <p className="ev-muted">{data.ranked_groups.length} ranked groups · {data.additional_linked_groups.length} additional linked groups. Open a row to inspect its passages and source.</p>
        {data.ranked_groups.length === 0 && data.additional_linked_groups.length === 0 && <section className="ev-card">
          <h3>No passages returned</h3><p>This search returned no candidates. It does not establish that the claim is false or that evidence is absent from the corpus.</p>
        </section>}
        {data.ranked_groups.length > 0 && rows(data.ranked_groups)}
        {data.additional_linked_groups.length > 0 && <><h3>Additional linked evidence</h3>
          <p className="ev-muted">Explicit record connections retained outside the ranked-group limit.</p>{rows(data.additional_linked_groups)}</>}
        <details className="ev-card"><summary>Search limits and interpretation status</summary>
          <ul>{data.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
        </details>
      </>}
    </div>
    {selected && <DetailFrame title={sources.get(selected.source_id)?.title ?? selected.source_id} onBack={back}>
      <CorpusEvidenceDetail group={selected} source={sources.get(selected.source_id)} />
    </DetailFrame>}
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
