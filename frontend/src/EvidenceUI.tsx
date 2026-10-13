import { useEffect, useRef, type ReactNode } from "react";
import type { CorpusPassage, CorpusSource } from "./api";
import "./evidence.css";

export const humanize = (value: string) => value.replace(/_/g, " ");
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`ev-badge ev-tone-${tone}`}>{children}</span>;
}
// Outcome and component labels vary by assessment basis ("Supported", "Supported by the
// available record", "partially supported", ...), so tone is read from the leading words.
export function outcomeTone(value: string | null | undefined) {
  const text = (value ?? "").trim().toLowerCase(); // older saved rows carry no overall outcome
  if (text.startsWith("supported")) return "green";
  if (text.startsWith("contradicted")) return "red";
  if (text.startsWith("partially") || text.startsWith("contested") || text.startsWith("conflicting")) return "amber";
  return "neutral";
}
// A count shown as a pill beside its heading, so it cannot be read as stray text.
export function Count({ children }: { children: ReactNode }) {
  return <span className="ev-count">{children}</span>;
}
export function Chevron() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}
// Two equal cards so the formal and in-practice outcomes are never merged into one.
export function LaneCards({ lanes }: { lanes: { label: string; value: string; note?: string }[] }) {
  return <div className="ev-two">{lanes.map(lane => <section className="ev-card ev-lane" key={lane.label}>
    <span className="ev-kicker">{lane.label}</span>
    <div className={`ev-lane-value ev-lane-${outcomeTone(lane.value)}`}>{lane.value}</div>
    {lane.note && <p className="ev-muted">{lane.note}</p>}
  </section>)}</div>;
}
// Presentation bands for the 0-100 assessment confidence. The score itself is uncalibrated;
// these cut-offs only decide the word shown under the ring.
export function confidenceLevel(score: number): string {
  return score >= 70 ? "High" : score >= 40 ? "Medium" : "Low";
}
// A ring gauge. It takes the verdict's colour, so colour only ever means the outcome; the
// confidence itself is carried by how full the ring is, the number and the word beneath.
export function ConfidenceRing({ score, tone = "neutral", label }: { score: number; tone?: string; label?: string }) {
  const value = Math.max(0, Math.min(100, score));
  const level = label ? label.replace(/\s*confidence$/i, "") : confidenceLevel(value); // a band supplied with the score wins
  const radius = 30, circumference = 2 * Math.PI * radius;
  return <div className={`ev-ring ev-ring-${tone}`} role="img" aria-label={`Confidence in this result: ${Math.round(value)} out of 100, ${level.toLowerCase()}`}>
    <svg width="76" height="76" viewBox="4 4 76 76" aria-hidden="true">
      <circle cx="42" cy="42" r={radius} className="ev-ring-track" />
      <circle cx="42" cy="42" r={radius} className="ev-ring-value" strokeDasharray={`${(value / 100) * circumference} ${circumference}`} transform="rotate(-90 42 42)" />
      <text x="42" y="43" textAnchor="middle" dominantBaseline="middle" className="ev-ring-number">{Math.round(value)}</text>
    </svg>
    <span className="ev-ring-word">{level} confidence</span>
    <span className="ev-ring-sub">in this result</span>
  </div>;
}
// The graph engine reports confidence as one of three bands, not a number.
const CONFIDENCE_BANDS = ["lower confidence", "moderate confidence", "higher confidence"];
export function ConfidenceBand({ label, tone = "neutral" }: { label: string; tone?: string }) {
  const rank = CONFIDENCE_BANDS.indexOf(label.trim().toLowerCase());
  return <div className={`ev-band ev-band-${tone}`} role="img" aria-label={`Confidence in this result: ${label.toLowerCase()}`}>
    <div className="ev-band-steps" aria-hidden="true">{CONFIDENCE_BANDS.map((band, i) => <span key={band} className={rank >= 0 && i <= rank ? "ev-band-on" : undefined} />)}</div>
    <span className="ev-ring-word">{label}</span>
    <span className="ev-ring-sub">in this result</span>
  </div>;
}
export function ConfidenceMeter({ label, score, note }: { label: string; score: number | null; note?: string }) {
  const filled = score !== null && Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
  return <div className="ev-meter">
    <div className="ev-meter-label"><span className="ev-kicker" style={{ marginBottom: 4 }}>Confidence</span><strong>{label}</strong></div>
    {score === null ? <div className="ev-meter-spacer" /> : <div className="ev-meter-track">{filled > 0 && <div className="ev-meter-fill" style={{ width: `${filled}%` }} />}</div>}
    {note && <span className="ev-meter-note">{note}</span>}
  </div>;
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
    </span><span className="ev-row-arrow"><Chevron /></span>
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
    .slice(0, 4).map(([k, v]) => `${humanize(k)}: ${recordValue(v)}`).join(" · ") : plainText(evidence.text);
}
// A citation of a structured row is stored as its JSON text; show its leading fields instead.
export function quotePreview(text: string): string {
  if (!text.trimStart().startsWith("{")) return plainText(text);
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return text;
    return Object.entries(parsed).filter(([, v]) => v !== "" && v != null)
      .slice(0, 5).map(([k, v]) => `${humanize(k)}: ${recordValue(v)}`).join(" · ");
  } catch { return text; }
}
// Source passages are stored as Markdown. Show their bold, emphasis, code and list markers as
// formatting instead of printing the symbols; the words themselves are never changed.
function inlineMarkup(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g).filter(part => part !== "").map((part, index) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? <code key={index}>{part.slice(1, -1)}</code>
      : part.startsWith("*") && part.endsWith("*") && part.length > 2 ? <em key={index}>{part.slice(1, -1)}</em>
      : part);
}
export function MarkdownLite({ text }: { text: string }) {
  return <div className="ev-md">{text.split("\n").map((line, index) => {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) return <div key={index} className="ev-md-item">{inlineMarkup(bullet[1])}</div>;
    return line.trim() ? <div key={index}>{inlineMarkup(line)}</div> : <div key={index} className="ev-md-gap" />;
  })}</div>;
}
// One-line previews drop the markers entirely.
export const plainText = (text: string) => text.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/^\s*[-*]\s+/gm, "").replace(/\*([^*\s][^*]*)\*/g, "$1");
export const relationTone = (relationship: string) => relationship.startsWith("support") ? "green" : relationship.startsWith("contradict") ? "red" : relationship.startsWith("qualif") ? "amber" : "neutral";

// A quoted structured row shown as labelled fields, with the exact stored text kept beneath.
export function RecordQuote({ text }: { text: string }) {
  if (!text.trimStart().startsWith("{")) return null;
  let record: Record<string, unknown>;
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    record = parsed;
  } catch { return null; }
  return <>
    <dl className="ev-fields">{Object.entries(record).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{recordValue(value)}</dd></div>)}</dl>
    <details><summary>Exact stored record</summary><pre>{text}</pre></details>
  </>;
}
export const stanceTone = (stance: string) => stance === "support" ? "green" : stance === "contradict" ? "red" : "neutral";
export function PassageView({ evidence }: { evidence: Passage }) {
  const record = recordFields(evidence);
  return record ? <>
    <dl className="ev-fields">{Object.entries(record).map(([key, value]) => <div key={key}>
      <dt>{humanize(key)}</dt><dd>{recordValue(value)}</dd>
    </div>)}</dl>
    <details><summary>Exact stored record</summary><pre>{evidence.text}</pre></details>
  </> : <div className="ev-quote"><MarkdownLite text={evidence.text} /></div>;
}
