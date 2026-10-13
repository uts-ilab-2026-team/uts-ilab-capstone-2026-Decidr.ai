import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { saveAssessmentRevision, saveCanonicalReview } from "./api";
import { unifiedGraph } from "./AssessmentGraph";
import { Badge, MarkdownLite, RecordQuote } from "./EvidenceUI";
import type { CanonicalAssessment, CanonicalReviewFinding } from "./suppliedAssessmentContract";
import type { AssessmentSnapshot, ReviewInput } from "./AutomaticAssessment";

// The review opens as a side panel so the result stays in view. A parent can control it
// (to put the trigger in its toolbar); otherwise the component shows its own trigger.
export type ReviewPanelProps = { open?: boolean; onOpenChange?: (open: boolean) => void };

function Choice({ label, value, options, onChange }: { label: string; value: string; options: readonly (readonly [string, string])[]; onChange: (value: string) => void }) {
  return <div className="ev-choice"><span className="ev-choice-label">{label}</span>
    <div className="ev-segments" role="group" aria-label={label}>{options.map(([option, text]) =>
      <button type="button" key={option} aria-pressed={value === option} onClick={() => onChange(option)}>{text}</button>)}</div>
  </div>;
}

// One item is shown at a time; the rest stay mounted (hidden) so nothing typed is lost.
function ReviewDrawer({ panel, itemLabel, count, position, onPosition, changed, intro, footnote, reason, onReason, busy, canSave, saveLabel, onSave, error, empty, children }: {
  panel: ReviewPanelProps; itemLabel: string; count: number; position: number; onPosition: (next: number) => void; changed: number;
  intro: string; footnote: string; reason: string; onReason: (value: string) => void; busy: boolean; canSave: boolean; saveLabel: string;
  onSave: () => void; error: string | null; empty: ReactNode; children: ReactNode;
}) {
  const [own, setOwn] = useState(false);
  const controlled = panel.open !== undefined;
  const open = controlled ? !!panel.open : own;
  const setOpen = (next: boolean) => { if (controlled) panel.onOpenChange?.(next); else setOwn(next); };
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return <section className="ev-automatic">
    {!controlled && <button type="button" className="ev-card ev-review-trigger" aria-expanded={open} onClick={() => setOpen(true)}>Review this result<span className="ev-muted">Change a judgement and save it as a separate revision</span></button>}
    <aside className="ev-drawer" hidden={!open} aria-label="Review this result">
      <header className="ev-drawer-head">
        <div><h3>Review this result</h3>
          <span className="ev-muted">{count ? `${itemLabel} ${position + 1} of ${count}` : `No ${itemLabel.toLowerCase()} to review`}{changed ? ` · ${changed} changed` : ""}</span></div>
        <div className="ev-drawer-nav">
          <button type="button" className="ev-button" disabled={position <= 0} onClick={() => onPosition(position - 1)}>Previous</button>
          <button type="button" className="ev-button" disabled={position >= count - 1} onClick={() => onPosition(position + 1)}>Next</button>
          <button type="button" className="ev-button" aria-label="Close review" onClick={() => setOpen(false)}>Close</button>
        </div>
      </header>
      <div className="ev-drawer-body">
        <details className="ev-drawer-intro"><summary>How review works</summary><p>{intro}</p></details>
        {count ? children : empty}
      </div>
      <footer className="ev-drawer-foot">
        <label>Reason for this review <textarea rows={2} value={reason} disabled={busy} onChange={event => onReason(event.target.value)} /></label>
        {error && <p role="alert" style={{ color: "var(--red)" }}>{error}</p>}
        <div className="ev-drawer-actions">
          <span className="ev-muted">{footnote}</span>
          <button className="ev-button ev-button-primary" disabled={busy || !canSave} onClick={onSave}>{saveLabel}</button>
        </div>
      </footer>
    </aside>
  </section>;
}

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

function LegacyAssessmentReview({record, onSaved, panel}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void; panel: ReviewPanelProps}) {
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
  const original = record.snapshot.request.inputs;
  // Evidence that decided the result is reviewed first; the rest follows in its saved order.
  const order = useMemo(() => {
    const response = record.snapshot.response;
    let used = new Set<string>();
    try { if (response?.inputs) used = new Set(unifiedGraph(response).nodes.filter(node => node.used).flatMap(node => node.inputs.map(input => input.input_id))); } catch { /* order falls back to saved order */ }
    const isUsed = (index: number) => response?.inputs?.length === original.length && used.has(response.inputs[index].input_id);
    const indices = original.map((_, index) => index);
    return { indices: [...indices.filter(isUsed), ...indices.filter(index => !isUsed(index))], isUsed };
  }, [record, original]);
  const [position, setPosition] = useState(0);
  const isChanged = (index: number) => JSON.stringify(inputs[index]) !== JSON.stringify(original[index]);
  const tri = (value: boolean | null) => String(value);
  return <ReviewDrawer panel={panel} itemLabel="Evidence" count={inputs.length} position={position} onPosition={setPosition}
    changed={inputs.filter((_, index) => isChanged(index)).length} reason={reason} onReason={setReason} busy={busy}
    canSave={!!reason.trim() && !!inputs.length} saveLabel="Save review as a new revision" onSave={review} error={error}
    intro="Inspect the exact citations above before changing a judgement. Revisions assess the current corpus; the previous snapshot stays unchanged. Confirm authority only with evidence of adoption rights or delegation for this scope and date. In Judgement basis, identify the supporting source, passage and applicable dates. If evidence is missing, leave authority, scope or date unresolved."
    footnote="Reviewer declarations remain conditional; a saved review is not independent verification."
    empty={<p className="ev-notice">There are no evidence inputs to review. Run another search with a complete claim before creating a revision.</p>}>
    {inputs.map((item, index) => <fieldset key={index} className="ev-review-item" disabled={busy} hidden={order.indices[position] !== index}>
      <legend>Evidence {index + 1} · {item.citations[0]?.source_id ?? "Source unavailable"}</legend>
      <div className="ev-chips" style={{ margin: "0 0 10px" }}><Badge tone={order.isUsed(index) ? "green" : "neutral"}>{order.isUsed(index) ? "Used in the result" : "Not used in the result"}</Badge>{isChanged(index) && <Badge tone="amber">Changed</Badge>}</div>
      <p>{item.rationale}</p>
      {item.citations.map((citation, i) => <div key={i} className="ev-review-quote">
        {RecordQuote({ text: citation.quotation }) ?? <MarkdownLite text={citation.quotation} />}
        <p className="ev-mono">{citation.source_id} · {citation.evidence_id} · {citation.locator}</p>
      </div>)}
      <Choice label="Relationship" value={item.stance} onChange={value => edit(index, "stance", value)}
        options={[["support", "Support"], ["contradict", "Contradict"], ["qualify", "Qualify"], ["context", "Context"], ["unresolved", "Unresolved"]]} />
      {([["scope_matches", "Scope matches"], ["temporal_matches", "Date applies"], ["authority_verified", "Authority verified"]] as const).map(([field, label]) =>
        <Choice key={field} label={label} value={tri(item[field])} onChange={value => edit(index, field, value === "null" ? null : value === "true")}
          options={[["true", "Verified"], ["false", "Does not match"], ["null", "Unresolved"]]} />)}
      <details><summary>Scores and written basis</summary>
        <div className="ev-inline-form" style={{ margin: "12px 0" }}>{(["directness", "specificity", "completeness"] as const).map(field =>
          <label key={field}>{field} <input type="number" min="0" max="1" step="0.1" style={{ width: 96 }} value={item[field]} onChange={event => edit(index, field, Number(event.target.value))} /></label>)}</div>
        <label>Judgement basis <textarea rows={3} value={item.judgement_basis} onChange={event => edit(index, "judgement_basis", event.target.value)} /></label>
        <label>Interpretation rationale <textarea rows={3} value={item.rationale} onChange={event => edit(index, "rationale", event.target.value)} /></label>
      </details>
    </fieldset>)}
  </ReviewDrawer>;
}


export function canonicalReviewFindings(canonical: CanonicalAssessment): CanonicalReviewFinding[] {
  return canonical.components.flatMap(component => component.findings.map(finding => ({
    component_id: component.id, source_id: finding.source_id, evidence_id: finding.evidence_id,
    quotation: finding.quotation, relationship: finding.relationship, reason: finding.reason,
    scope_fit: finding.scope_fit, time_fit: finding.time_fit, directness: finding.directness,
    basis: finding.basis, limitations: [...finding.limitations],
  })));
}

function CanonicalAssessmentReview({record, onSaved, panel}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void; panel: ReviewPanelProps}) {
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
  const original = useMemo(() => canonicalReviewFindings(canonical), [canonical]);
  const [position, setPosition] = useState(0);
  const isChanged = (index: number) => JSON.stringify(findings[index]) !== JSON.stringify(original[index]);
  if (canonical.processing.status === "failed") return null;
  return <ReviewDrawer panel={panel} itemLabel="Finding" count={findings.length} position={position} onPosition={setPosition}
    changed={findings.filter((_, index) => isChanged(index)).length} reason={reason} onReason={setReason} busy={busy}
    canSave={!!reason.trim() && !!findings.length && !findings.some(finding => !finding.reason.trim() || !finding.basis.trim())}
    saveLabel={busy ? "Saving review…" : "Save review as a new revision"} onSave={save} error={error}
    intro="Review the component findings against their exact saved evidence. Saving recalculates the same assessment and confidence method from your judgements in a new revision. The original result, claim interpretation and cited passages stay unchanged."
    footnote="Reviewer judgements do not independently verify the sources or create authority. Existing validation and date safeguards still apply."
    empty={<p>No evidence findings are available to revise. Reassess with relevant evidence before reviewing.</p>}>
    {findings.map((finding, index) => <fieldset key={index} className="ev-review-item" disabled={busy} hidden={position !== index}>
      <legend>{canonical.components.find(component => component.id === finding.component_id)?.text ?? finding.component_id}</legend>
      {isChanged(index) && <div className="ev-chips" style={{ margin: "0 0 10px" }}><Badge tone="amber">Changed</Badge></div>}
      <div className="ev-review-quote">{RecordQuote({ text: finding.quotation }) ?? <MarkdownLite text={finding.quotation} />}<p className="ev-mono">{finding.source_id} · {finding.evidence_id}</p></div>
      <Choice label="Relationship" value={finding.relationship} onChange={value => edit(index, "relationship", value)}
        options={[["supports", "Supports"], ["contradicts", "Contradicts"], ["qualifies", "Qualifies"], ["context", "Context"], ["unresolved", "Unresolved"]]} />
      {([["scope_fit", "Scope applies"], ["time_fit", "Date applies"]] as const).map(([field, label]) =>
        <Choice key={field} label={label} value={finding[field]} onChange={value => edit(index, field, value)}
          options={[["yes", "Yes, based on the cited evidence"], ["no", "No"], ["unknown", "Not established"]]} />)}
      <Choice label="Evidence directness" value={finding.directness} onChange={value => edit(index, "directness", value)} options={[["direct", "Direct"], ["indirect", "Indirect"]]} />
      <label>Reason for this finding <textarea rows={3} value={finding.reason} onChange={event => edit(index, "reason", event.target.value)}/></label>
      <details><summary>Evidence basis and limitations</summary>
        <label style={{ marginTop: 12 }}>Evidence basis <select value={finding.basis} onChange={event => edit(index, "basis", event.target.value)}>{[
          ["direct_statement", "The source directly states this"], ["recorded_action", "The source records an action"],
          ["reported_statement", "Someone reports this"], ["independent_validation", "The cited evidence describes an independent check"],
          ["contextual", "Related context only"],
        ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Limitations, one per line <textarea rows={3} value={finding.limitations.join("\n")} onChange={event => edit(index, "limitations", event.target.value.split("\n"))}/></label>
      </details>
    </fieldset>)}
  </ReviewDrawer>;
}

export default function AssessmentReview({record, onSaved, open, onOpenChange}: {record: AssessmentSnapshot; onSaved: (value: AssessmentSnapshot) => void} & ReviewPanelProps) {
  const panel = { open, onOpenChange };
  return record.snapshot.response?.canonical_assessment ? <CanonicalAssessmentReview record={record} onSaved={onSaved} panel={panel}/> : <LegacyAssessmentReview record={record} onSaved={onSaved} panel={panel}/>;
}
