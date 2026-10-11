import { useRef, useState } from "react";
import { saveAssessmentRevision } from "./api";
import type { AssessmentSnapshot, ReviewInput } from "./AutomaticAssessment";

export function checkReviewRevision(value: AssessmentSnapshot, parent: AssessmentSnapshot) {
  const response = value.snapshot.response;
  const request = parent.snapshot.request;
  if (value.snapshot.parent_run_id !== parent.snapshot.run_id || value.snapshot.run_id === parent.snapshot.run_id ||
      response.claim_text !== request.claim_text || response.facet !== request.facet || response.as_of !== request.as_of ||
      !response.persisted || response.status !== "assessed_supplied_judgements")
    throw new Error("The returned revision does not match this assessment. Reopen saved history before continuing.");
  return value;
}

export default function AssessmentReview({record, onSaved}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void}) {
  const [inputs, setInputs] = useState<ReviewInput[]>(record.snapshot.request.inputs);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<{body: string; id: string} | null>(null);
  const keyFor = (body: unknown) => {
    const text = JSON.stringify(body);
    if (pending.current?.body !== text) pending.current = {body: text, id: crypto.randomUUID()};
    return pending.current.id;
  };
  async function review() {
    if (!record) return;
    setBusy(true); setError(null);
    const query = { assessment: { ...record.snapshot.request, inputs }, parent_run_id: record.snapshot.run_id, revision_reason: reason };
    try {
      const value = await saveAssessmentRevision({ ...query, request_id: keyFor(query) });
      checkReviewRevision(value, record); pending.current = null; onSaved(value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review could not be saved."); }
    finally { setBusy(false); }
  }
  const edit = (index: number, field: string, value: unknown) => setInputs(items => items.map((item, i) => i === index ? { ...item, [field]: value } : item));
  return <section className="ev-automatic">
      <details className="ev-card">
        <summary>Review this result</summary>
        <p>Inspect the exact citations above before changing a judgement. Revisions assess the current corpus; the previous snapshot stays unchanged. Confirm authority only with evidence of adoption rights or delegation for this scope and date. In Judgement basis, identify the supporting source, passage and applicable dates. If evidence is missing, leave authority Unresolved and explain the gap.</p>
        {inputs.map((item, index) => <fieldset key={index} disabled={busy}>
          <legend>Evidence {index + 1} · {item.citations[0]?.source_id ?? "Source unavailable"}</legend>
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
        {!inputs.length && <p className="ev-notice">There are no evidence inputs to review. Run another search with a complete claim before creating a revision.</p>}
        <label>Reason for this review <textarea value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
        <button className="ev-button ev-button-primary" disabled={busy || !reason.trim() || !inputs.length} onClick={review}>Save review as a new revision</button>
        <p className="ev-muted">Reviewer declarations remain conditional; a saved review is not independent verification.</p>
      </details>
    {error && <p role="alert">{error}</p>}
  </section>;
}
