import { useEffect, useRef, type ReactNode } from "react";
import type { CorpusPassage, CorpusSource } from "./api";
import "./evidence.css";

export const humanize = (value: string) => value.replace(/_/g, " ");
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`ev-badge ev-tone-${tone}`}>{children}</span>;
}
export function outcomeTone(value: string) {
  return value === "Supported" ? "green" : value === "Contradicted" ? "red" : value === "Contested" ? "amber" : "neutral";
}
export function EvidenceRow({ title, subtitle, preview, badges, onOpen }: {
  title: string; subtitle: string; preview: string; badges?: ReactNode; onOpen: () => void;
}) {
  return <button type="button" className="ev-row" onClick={onOpen}>
    <span className="ev-row-icon" aria-hidden="true">↗</span>
    <span className="ev-row-body"><span className="ev-row-title">{title}</span>
      <span className="ev-row-badges">{badges}</span>
      <span className="ev-muted">{subtitle}</span>
      <span className="ev-preview">{preview}</span>
    </span><span className="ev-row-arrow" aria-hidden="true">›</span>
  </button>;
}
export function DetailFrame({ title, onBack, children }: { title: string; onBack: () => void; children: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section className="ev-detail">
    <button type="button" className="ev-back" onClick={onBack}>← Back to results</button>
    <h2 tabIndex={-1} ref={heading}>{title}</h2>{children}
  </section>;
}
export function SourceMetadata({ source }: { source?: CorpusSource }) {
  if (!source) return <p className="ev-muted">Source metadata is unavailable.</p>;
  const fields = [
    ["Source ID", source.source_id], ["Source type", source.source_type],
    ["Lifecycle", source.lifecycle_status], ["Approval status", source.approval_status],
    ["Version", source.version], ["Responsible person or role", source.responsible_person_or_role],
    ["Created", source.creation_date], ["Last updated", source.last_updated_date],
    ["Effective from", source.effective_start_date], ["Effective end", source.effective_end_date],
    ["Superseded on", source.superseded_date],
  ];
  return <section className="ev-card">
    <h3>Source metadata</h3>
    <p className="ev-muted">Source dates and status do not establish applicability to the claim.</p>
    <dl className="ev-fields">{fields.map(([label, value]) => <div key={label}>
      <dt>{label}</dt><dd>{value || "Not recorded"}</dd>
    </div>)}</dl>
    {!!source.metadata_conflicts?.length && <div className="ev-notice" role="alert">
      <strong>Unresolved metadata conflicts</strong><pre>{JSON.stringify(source.metadata_conflicts, null, 2)}</pre>
    </div>}
    <details><summary>Original file location</summary><p className="ev-mono">{source.original_file_path}</p></details>
  </section>;
}
type Passage = CorpusPassage["evidence"];
export function recordFields(evidence: Passage): Record<string, unknown> | null {
  // Only format explicit structured records; never infer a relationship or rewrite evidence.
  const record = evidence.structured_metadata?.record;
  if (record && typeof record === "object" && !Array.isArray(record)) return record;
  if (!evidence.locator.startsWith("csv:")) return null;
  try {
    const parsed = JSON.parse(evidence.text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}
export function recordValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
export function passagePreview(evidence: Passage): string {
  const record = recordFields(evidence);
  return record ? Object.entries(record).filter(([, v]) => v !== "" && v != null)
    .slice(0, 4).map(([k, v]) => `${humanize(k)}: ${recordValue(v)}`).join(" · ") : evidence.text;
}
export function PassageView({ evidence }: { evidence: Passage }) {
  const record = recordFields(evidence);
  return record ? <>
    <dl className="ev-fields">{Object.entries(record).map(([key, value]) => <div key={key}>
      <dt>{humanize(key)}</dt><dd>{recordValue(value)}</dd>
    </div>)}</dl>
    <details><summary>Exact stored record</summary><pre>{evidence.text}</pre></details>
  </> : <p className="ev-quote">{evidence.text}</p>;
}
