import { useRef, useState } from "react";
import { saveAssessmentRevision, saveCanonicalReview } from "./api";
import type { CanonicalAssessment, CanonicalReviewFinding } from "./suppliedAssessmentContract";
import type { AssessmentSnapshot, ReviewInput } from "./AutomaticAssessment";

function stableFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableFields);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, stableFields(entry)]));
  return value;
}
export function checkReviewRevision(value: AssessmentSnapshot, parent: AssessmentSnapshot) {
  const response = value.snapshot.response;
  const request = parent.snapshot.request;
  if (value.snapshot.parent_run_id !== parent.snapshot.run_id || value.snapshot.run_id === parent.snapshot.run_id ||
      response.claim_text !== request.claim_text || response.facet !== request.facet || response.as_of !== request.as_of ||
      !response.persisted || response.status !== "assessed_supplied_judgements")
    throw new Error("The returned revision does not match this assessment. Reopen saved history before continuing.");
  const canonicalParent = parent.snapshot.response?.canonical_assessment;
  if (canonicalParent) {
    const canonical = response.canonical_assessment;
    const citationKey = (finding: {component_id: string; evidence_id: string; source_id: string; quotation: string}) => JSON.stringify([finding.component_id, finding.source_id, finding.evidence_id, finding.quotation]);
    const allowed = [...new Set(canonicalParent.components.flatMap(component => component.findings.map(citationKey)))].sort();
    if (!canonical || canonical.processing.status !== "assessed" || !canonical.overall_outcome ||
        canonical.confidence.score === null || !Number.isFinite(canonical.confidence.score) || canonical.confidence.score < 0 || canonical.confidence.score > 100 ||
        JSON.stringify(stableFields(canonical.interpreted_claim)) !== JSON.stringify(stableFields(canonicalParent.interpreted_claim)) ||
        JSON.stringify(canonical.components.map(component => [component.id, component.text])) !== JSON.stringify(canonicalParent.components.map(component => [component.id, component.text])) ||
        JSON.stringify([...new Set(canonical.components.flatMap(component => component.findings.map(citationKey)))].sort()) !== JSON.stringify(allowed)) {
      throw new Error("The returned revision does not match the frozen claim components and evidence.");
    }
  }
  return value;
}

function LegacyAssessmentReview({record, onSaved}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void}) {
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


export function canonicalReviewFindings(canonical: CanonicalAssessment): CanonicalReviewFinding[] {
  return canonical.components.flatMap(component => component.findings.map(finding => ({
    component_id: component.id, source_id: finding.source_id, evidence_id: finding.evidence_id,
    quotation: finding.quotation, relationship: finding.relationship, reason: finding.reason,
    scope_fit: finding.scope_fit, time_fit: finding.time_fit, directness: finding.directness,
    basis: finding.basis, limitations: [...finding.limitations],
  })));
}

function CanonicalAssessmentReview({record, onSaved}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void}) {
  const canonical = record.snapshot.response.canonical_assessment!;
  const [findings, setFindings] = useState(() => canonicalReviewFindings(canonical));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<{body: string; id: string} | null>(null);
  const edit = (index: number, field: "relationship" | "reason" | "scope_fit" | "time_fit" | "directness" | "basis" | "limitations", value: string | string[]) =>
    setFindings(items => items.map((item, i) => i === index ? {...item, [field]: value} : item));
  async function save() {
    const query = {revision_reason: reason, findings: findings.map(finding => ({...finding, limitations: finding.limitations.map(line => line.trim()).filter(Boolean)}))};
    const body = JSON.stringify(query);
    if (pending.current?.body !== body) pending.current = {body, id: crypto.randomUUID()};
    setBusy(true); setError(null);
    try {
      const revised = await saveCanonicalReview(record.snapshot.run_id, {...query, request_id: pending.current.id});
      checkReviewRevision(revised, record); pending.current = null; onSaved(revised);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review could not be saved."); }
    finally { setBusy(false); }
  }
  if (canonical.processing.status === "failed") return null;
  return <section className="ev-automatic"><details className="ev-card"><summary>Review this result</summary>
    <p>Review the component findings against their exact saved evidence. Saving recalculates the same assessment and confidence method from your judgements in a new revision. The original result, claim interpretation and cited passages stay unchanged.</p>
    {findings.map((finding, index) => <fieldset key={index} disabled={busy}><legend>{canonical.components.find(component => component.id === finding.component_id)?.text ?? finding.component_id}</legend>
      <p className="ev-quote">{finding.quotation}</p><p className="ev-mono">{finding.source_id} · {finding.evidence_id}</p>
      <label>Relationship <select value={finding.relationship} onChange={event => edit(index, "relationship", event.target.value)}>{["supports", "contradicts", "qualifies", "context", "unresolved"].map(value => <option key={value}>{value}</option>)}</select></label>
      {([["scope_fit", "Scope applies"], ["time_fit", "Date applies"]] as const).map(([field, label]) => <label key={field}>{label} <select value={finding[field]} onChange={event => edit(index, field, event.target.value)}><option value="yes">Yes, based on the cited evidence</option><option value="no">No</option><option value="unknown">Not established</option></select></label>)}
      <label>Evidence directness <select value={finding.directness} onChange={event => edit(index, "directness", event.target.value)}><option value="direct">Direct</option><option value="indirect">Indirect</option></select></label>
      <label>Reason for this finding <textarea value={finding.reason} onChange={event => edit(index, "reason", event.target.value)}/></label>
      <label>Evidence basis <select value={finding.basis} onChange={event => edit(index, "basis", event.target.value)}>{[
        ["direct_statement", "The source directly states this"], ["recorded_action", "The source records an action"],
        ["reported_statement", "Someone reports this"], ["independent_validation", "The cited evidence describes an independent check"],
        ["contextual", "Related context only"],
      ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Limitations, one per line <textarea value={finding.limitations.join("\n")} onChange={event => edit(index, "limitations", event.target.value.split("\n"))}/></label>
    </fieldset>)}
    {!findings.length && <p>No evidence findings are available to revise. Reassess with relevant evidence before reviewing.</p>}
    <label>Reason for this review <textarea value={reason} disabled={busy} onChange={event => setReason(event.target.value)}/></label>
    <button className="ev-button ev-button-primary" disabled={busy || !reason.trim() || !findings.length || findings.some(finding => !finding.reason.trim() || !finding.basis.trim())} onClick={save}>{busy ? "Saving review…" : "Save review as a new revision"}</button>
    <p className="ev-muted">Reviewer judgements do not independently verify the sources or create authority. Existing validation and date safeguards still apply.</p>
  </details>{error && <p role="alert">{error}</p>}</section>;
}

export default function AssessmentReview({record, onSaved}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void}) {
  return record.snapshot.response?.canonical_assessment ? <CanonicalAssessmentReview record={record} onSaved={onSaved}/> : <LegacyAssessmentReview record={record} onSaved={onSaved}/>;
}
