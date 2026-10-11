import { useRef, useState } from "react";
import { searchCorpus } from "./api";
import { PassageView, SourceMetadata } from "./EvidenceUI";

export default function RoleCrossCheck({asOf}: {asOf: string}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof searchCorpus>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  async function search() {
    const current = ++generation.current;
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await searchCorpus(query.trim(), null);
      if (current === generation.current) setResult(response);
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : "Role search unavailable.");
    } finally { if (current === generation.current) setBusy(false); }
  }
  const groups = result ? [...result.ranked_groups, ...result.additional_linked_groups] : [];
  return <details className="ev-card">
    <summary>Cross-check a role or person</summary>
    <p>Search the corpus for role assignments, decision rights and delegation records relevant to {asOf}.</p>
    <form onSubmit={event => {event.preventDefault(); if (query.trim()) void search();}}>
      <label>Role or person <input value={query} maxLength={500} required onChange={event => {generation.current++; setQuery(event.target.value); setResult(null); setBusy(false); setError(null);}} /></label>
      <button className="ev-button" disabled={busy || !query.trim()}>{busy ? "Searching…" : "Find role evidence"}</button>
    </form>
    <p className="ev-muted">These are search candidates, not verified role assignments. Check who held the role on the relevant date and whether their documented rights cover this decision. A title alone does not prove authority. This search does not change the saved assessment.</p>
    {error && <p role="alert">{error}</p>}
    {result && !groups.length && <p>No matching passages returned. The role remains unresolved.</p>}
    {groups.map(group => {
      const source = result?.sources.find(value => value.source_id === group.source_id);
      return <details key={group.lead_evidence_id}>
        <summary>{source?.title ?? group.source_id} · {group.passages.length} passages</summary>
        {group.passages.map(passage => <section key={passage.evidence.evidence_id}>
          <PassageView evidence={passage.evidence} />
          <p className="ev-mono">{passage.evidence.evidence_id} · {passage.evidence.locator}</p>
        </section>)}
        <SourceMetadata source={source} />
      </details>;
    })}
  </details>;
}
