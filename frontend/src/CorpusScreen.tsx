import { useState, type CSSProperties } from "react";
import {
  searchCorpus, getCorpusEvidence, useApi,
  type CorpusGroup, type CorpusSource,
} from "./api";

const card: CSSProperties = {
  background: "#fff", border: "1px solid #e5e3df",
  borderRadius: 8, padding: 20, marginBottom: 16,
};
const button: CSSProperties = {
  padding: "9px 14px", border: "1px solid #e5e3df",
  borderRadius: 6, background: "#fff", color: "#1a1a1a",
  cursor: "pointer", font: "inherit",
};
const small: CSSProperties = {
  fontSize: 12, color: "#6b7280", overflowWrap: "anywhere",
};

function EvidenceGroup({
  group, source,
}: { group: CorpusGroup; source?: CorpusSource }) {
  const matched = new Set(group.matched_evidence_ids);
  const fields = [
    ["Source type", source?.source_type],
    ["Lifecycle", source?.lifecycle_status],
    ["Approval status", source?.approval_status],
    ["Version", source?.version],
    ["Responsible person or role", source?.responsible_person_or_role],
    ["Created", source?.creation_date],
    ["Last updated", source?.last_updated_date],
    ["Effective from", source?.effective_start_date],
    ["Effective end", source?.effective_end_date],
    ["Superseded on", source?.superseded_date],
    ["Original file", source?.original_file_path],
  ];

  return (
    <article style={card}>
      <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>
        {group.position}. {source?.title ?? group.source_id}
      </h3>
      <div style={small}>
        {group.source_id} · {group.passages.length} passage(s) · Unassessed
      </div>
      <details style={{ marginTop: 14 }}>
        <summary style={{ cursor: "pointer" }}>Source metadata</summary>
        <p style={small}>
          Dates and status are source metadata. Applicability to this claim
          has not been assessed.
        </p>
        <dl style={{ fontSize: 13 }}>
          {fields.map(([label, value]) => (
            <div key={label} style={{ marginBottom: 8 }}>
              <dt style={{ fontWeight: 600 }}>{label}</dt>
              <dd style={{ margin: "3px 0 0", overflowWrap: "anywhere" }}>
                {value || "Not recorded"}
              </dd>
            </div>
          ))}
        </dl>
        {!!source?.metadata_conflicts?.length && (
          <div>
            <strong>Unresolved metadata conflicts</strong>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(source.metadata_conflicts, null, 2)}
            </pre>
          </div>
        )}
      </details>

      {group.passages.map((passage) => (
        <section
          key={passage.evidence.evidence_id}
          style={{ borderTop: "1px solid #f0eee9", marginTop: 18, paddingTop: 16 }}
        >
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {matched.has(passage.evidence.evidence_id)
              ? "Retrieved passage" : "Section context"}
          </div>
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.65 }}>
            {passage.evidence.text}
          </p>
          <div style={small}>
            <CitationLookup
              evidenceId={passage.evidence.evidence_id}
              sourceId={passage.evidence.source_id}
              expectedText={passage.evidence.text}
              expectedLocator={passage.evidence.locator}
            />
            {passage.evidence.locator}
          </div>
          {passage.record_references.length > 0 && (
            <div style={{ marginTop: 12, fontSize: 13 }}>
              <strong>Explicit record connections</strong>
              <ul>
                {passage.record_references.map((reference, index) => (
                  <li key={index}>
                    {reference.record_id} — {reference.relationship.replace(/_/g, " ")}
                  </li>
                ))}
              </ul>
              <p style={small}>
                These connections identify records; they do not establish a
                relationship to the claim.
              </p>
            </div>
          )}
        </section>
      ))}
    </article>
  );
}

export default function CorpusScreen({
  claim, onBack,
}: { claim: string; onBack: () => void }) {
  const [attempt, setAttempt] = useState(0);
  const { data, error } = useApi(() => searchCorpus(claim), [claim, attempt]);
  const sources = new Map(data?.sources.map((source) => [source.source_id, source]) ?? []);

  return (
    <main style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "36px 48px", color: "#1a1a1a" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Corpus evidence</h1>
        <button style={button} onClick={onBack}>New search</button>
      </div>

      <section style={card}>
        <h2 style={{ fontSize: 14, marginTop: 0 }}>Your submitted claim</h2>
        <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 }}>{claim}</p>
        <strong>Unassessed — no verdict or confidence assigned</strong>
        <p style={{ lineHeight: 1.6, marginBottom: 0 }}>
          These passages are candidates for review. Retrieval does not establish
          support, contradiction, credibility or temporal applicability.
        </p>
      </section>

      {!data && !error && <p role="status">Searching the corpus…</p>}
      {error && (
        <section style={card} role="alert">
          <h2 style={{ fontSize: 16 }}>Corpus search unavailable</h2>
          <p>{error}</p>
          <button style={button} onClick={() => setAttempt((value) => value + 1)}>Retry</button>
        </section>
      )}

      {data && (
        <>
          <p style={{ color: "#6b7280", lineHeight: 1.6 }}>
            Index: {data.indexed_source_count} sources and {data.indexed_evidence_count} evidence units.
            {" "}{data.ranked_groups.length} ranked groups shown;
            {" "}{data.additional_linked_groups.length} additional linked groups.
          </p>
          {data.ranked_groups.length === 0 && data.additional_linked_groups.length === 0 && (
            <section style={card}>
              <h2 style={{ fontSize: 16 }}>No passages returned</h2>
              <p>This search returned no candidates. It does not establish that the claim is false or that evidence is absent from the corpus.</p>
            </section>
          )}
          {data.ranked_groups.length > 0 && <h2 style={{ fontSize: 17 }}>Ranked evidence groups</h2>}
          {data.ranked_groups.map((group) => (
            <EvidenceGroup key={group.lead_evidence_id} group={group} source={sources.get(group.source_id)} />
          ))}
          {data.additional_linked_groups.length > 0 && (
            <>
              <h2 style={{ fontSize: 17 }}>Additional linked evidence</h2>
              <p>Explicit record connections retained outside the ranked-group limit.</p>
              {data.additional_linked_groups.map((group) => (
                <EvidenceGroup key={group.lead_evidence_id} group={group} source={sources.get(group.source_id)} />
              ))}
            </>
          )}
          <details style={card}>
            <summary style={{ cursor: "pointer" }}>Search limits and interpretation status</summary>
            <ul style={{ lineHeight: 1.7 }}>
              {data.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
          </details>
        </>
      )}
    </main>
  );
}


type CitationProps = {
  evidenceId: string;
  sourceId: string;
  expectedText: string;
  expectedLocator: string;
};

function CitationLookup(props: CitationProps) {
  const [open, setOpen] = useState(false);
  return (
    <details
      style={{ margin: "10px 0" }}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary style={{ cursor: "pointer", color: "#b7470b", textDecoration: "underline" }}>
        Open citation: {props.evidenceId}
      </summary>
      {open && <CitationContent {...props} />}
    </details>
  );
}

function CitationContent({
  evidenceId, sourceId, expectedText, expectedLocator,
}: CitationProps) {
  const { data, error } = useApi(
    () => getCorpusEvidence(evidenceId, sourceId),
    [evidenceId, sourceId],
  );

  if (error) return <p role="alert">Citation unavailable: {error}</p>;
  if (!data) return <p role="status">Loading citation…</p>;
  if (
    data.evidence.evidence_id !== evidenceId ||
    data.evidence.source_id !== sourceId ||
    data.source.source_id !== sourceId
  ) {
    return <p role="alert">Citation identity mismatch. Please run the search again.</p>;
  }

  const changed = data.evidence.text !== expectedText ||
    data.evidence.locator !== expectedLocator;

  return (
    <section style={{
      marginTop: 12, padding: 16, background: "#f5f4f2",
      border: "1px solid #e5e3df", borderRadius: 6,
      color: "#1a1a1a", fontSize: 13,
    }}>
      <h4 style={{ margin: "0 0 10px", fontSize: 14 }}>{data.source.title}</h4>
      {changed && (
        <p role="alert">
          The stored passage has changed since this search.
          Run the search again before using this citation.
        </p>
      )}
      <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.65 }}>
        {data.evidence.text}
      </p>
      <dl style={{ lineHeight: 1.6, overflowWrap: "anywhere" }}>
        <dt>Evidence ID</dt><dd>{data.evidence.evidence_id}</dd>
        <dt>Source ID</dt><dd>{data.source.source_id}</dd>
        <dt>Locator</dt><dd>{data.evidence.locator}</dd>
        <dt>Source type</dt><dd>{data.source.source_type}</dd>
        <dt>Lifecycle</dt><dd>{data.source.lifecycle_status}</dd>
        <dt>Approval status</dt><dd>{data.source.approval_status || "Not recorded"}</dd>
        <dt>Effective from</dt><dd>{data.source.effective_start_date || "Not recorded"}</dd>
        <dt>Effective end</dt><dd>{data.source.effective_end_date || "Not recorded"}</dd>
        <dt>Superseded on</dt><dd>{data.source.superseded_date || "Not recorded"}</dd>
        <dt>Original file location</dt><dd>{data.source.original_file_path}</dd>
      </dl>
      <p>
        This is the passage stored in the current corpus index.
        It is not a historical assessment snapshot. Its relationship to your
        claim remains unassessed.
      </p>
    </section>
  );
}
