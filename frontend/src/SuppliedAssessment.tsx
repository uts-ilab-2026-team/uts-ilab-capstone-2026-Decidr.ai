import { useEffect, useRef, useState, type CSSProperties } from "react";
import AssessmentGraph, { evidenceWeight } from "./AssessmentGraph";
import { Badge, DetailFrame, EvidenceRow, SourceMetadata, humanize, outcomeTone } from "./EvidenceUI";
import { assessSupplied, getCorpusEvidence } from "./api";
import {
  checkSuppliedResponse, parseSuppliedRequest,
  type Citation, type SuppliedResult,
} from "./suppliedAssessmentContract";


const button: CSSProperties = { padding: "9px 14px", border: "1px solid #e5e3df", borderRadius: 6, background: "#fff", color: "#1a1a1a", cursor: "pointer", font: "inherit" };
const small: CSSProperties = { fontSize: 12, color: "#6b7280", overflowWrap: "anywhere" };
const prose: CSSProperties = { whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.65 };

function CitationView({ citation }: { citation: Citation }) {
  const [state, setState] = useState<{ text?: string; error?: string; loading?: boolean }>({});
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function open() {
    setState({ loading: true });
    try {
      const current = await getCorpusEvidence(citation.evidence_id, citation.source_id);
      // API offsets are Python Unicode code-point indices, not JS UTF-16 indices.
      const quote = Array.from(current.evidence.text).slice(citation.start, citation.end).join("");
      if (current.evidence.evidence_id !== citation.evidence_id ||
          current.evidence.source_id !== citation.source_id ||
          current.source.source_id !== citation.source_id ||
          current.evidence.locator !== citation.locator || quote !== citation.quotation) {
        throw new Error("The current index no longer matches this citation. Reassess before using it.");
      }
      if (live.current) setState({ text: current.evidence.text });
    } catch (error) {
      if (live.current) setState({ error: error instanceof Error ? error.message : "Citation unavailable." });
    }
  }
  return <div style={{ borderTop: "1px solid #f0eee9", paddingTop: 12, marginTop: 12 }}>
    <p style={prose}>{citation.quotation}</p>
    <p style={small}>{citation.evidence_id} · {citation.locator}</p>
    <button type="button" style={button} disabled={state.loading} onClick={open}>
      {state.loading ? "Loading citation…" : "Open current citation"}
    </button>
    {state.error && <p role="alert">{state.error}</p>}
    {state.text && <details open style={{ marginTop: 12 }}>
      <summary>Current stored passage</summary><p style={prose}>{state.text}</p>
      <p style={small}>Current index lookup; matching text does not verify the supplied relationship.</p>
    </details>}
  </div>;
}

type Input = SuppliedResult["inputs"][number];
export function SuppliedEvidenceDetail({ result, item }: { result: SuppliedResult; item: Input }) {
  const edge = result.assessment.evidence.find(value => value.edge_id === item.edge_id);
  const automatic = result.status === "assessed_automatically";
  const proposal = result.proposals?.find(value => item.interpretation.citations.some(citation => citation.evidence_id === value.evidence_id));
  return <>
    <div className="ev-chips"><Badge>{item.source.lifecycle_status ?? "unknown"}</Badge><span className="ev-muted">{item.source.source_id}</span></div>
    <dl className="ev-card ev-summary-fields">
      {[["Lane", humanize(item.interpretation.mode)], ["Relationship", item.interpretation.stance],
        ["Source class", humanize(String(item.supplied_judgements.source_class ?? item.source.source_type ?? "Unknown"))],
        ["Effective from", item.source.effective_start_date ?? "Not recorded"], ["Materiality", evidenceWeight(result, item)]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
    </dl>
    <section className="ev-card"><h3>{automatic ? "Automatic interpretation" : "Supplied interpretation"}</h3><p className="ev-quote">{item.interpretation.rationale}</p>
      {!!item.reasons.length && <ul>{item.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
    </section>
    <section className="ev-card"><h3>Exact citations ({item.interpretation.citations.length})</h3>
      {item.interpretation.citations.map((citation, i) => <CitationView key={i} citation={citation} />)}
    </section>
    <div className="ev-two">
      <section className="ev-card"><h3>Credibility dimensions</h3>
        <p className="ev-muted">{automatic ? "Calculated from automatic judgements; these are not verified probabilities." : "Calculated from supplied judgements; these are not verified probabilities."}</p>
        {edge ? <>
          <p>Materiality: {edge.materiality_score === null ? "Not scored" : edge.materiality_score.toFixed(3)}</p>
          {Object.entries(edge.dimensions).map(([name, value]) => <div className="ev-dimension" key={name}><span>{humanize(name)}</span><span>{value.toFixed(2)}</span></div>)}
        </> : <p className="ev-muted">Not scored. Retained for review; the reasons above explain why it cannot contribute to the verdict.</p>}
      </section>
      <section className="ev-card"><h3>Derivation and limitations</h3>
        {edge ? <ul>{[...edge.trace, ...edge.limitations].map((line, i) => <li key={i}>{line}</li>)}</ul>
          : <p className="ev-muted">No framework scoring trace for this input. See the reasons above.</p>}
      </section>
    </div>
    {proposal && <section className="ev-card"><h3>Approval-rule comparison and authority</h3>
      <p>{proposal.field_comparison?.evidence_entails_claim ? "The extracted rule covers the claimed approval range." : "No supported field comparison establishes this claim."}</p>
      {!!proposal.field_comparison?.differences.length && <p>Different fields: {proposal.field_comparison.differences.join(", ")}</p>}
      {proposal.passage_context && <details><summary>Surrounding policy conditions</summary>
        <p className="ev-quote">{proposal.passage_context.citation.quotation}</p>
        <p className="ev-mono">{proposal.passage_context.citation.evidence_id} · {proposal.passage_context.citation.locator}</p>
        <ul>{proposal.passage_context.clauses.map((clause, index) => <li key={index}>{clause.reason}</li>)}</ul>
        <p>{proposal.passage_context.limitation}</p>
      </details>}
      <p>{proposal.authority_resolution?.authority_verified
        ? "Documented authority resolved from dated adoption and person-specific decision rights. This is not independent authentication."
        : "Authority remains unresolved. Document ownership, approval labels and transaction approval rights do not establish policy adoption rights."}</p>
      {proposal.authority_resolution && <details><summary>Authority checks and citations</summary>
        {proposal.authority_resolution.adoption_findings?.map((finding, i) => <p key={i}>Documented adoption: version {finding.version}, decision dated {finding.decision}, sign-off by {finding.actor}. Adoption rights are checked separately.</p>)}
        {proposal.authority_resolution.gaps?.map((gap, i) => <p key={i}>{gap.message}</p>)}
        {Boolean(proposal.authority_resolution.review_guidance?.length) && <section><h4>What to verify next</h4><ul>{proposal.authority_resolution.review_guidance?.map((step, i) => <li key={i}>{step}</li>)}</ul></section>}
        <ul>{proposal.authority_resolution.checks.map(check => <li key={check.name}>
          <strong>{check.passed ? "Passed" : "Unresolved"}: </strong>{check.reason}
        </li>)}</ul>
        {proposal.authority_resolution.citations.map((citation, i) => <CitationView key={i} citation={citation} />)}
        <ul>{proposal.authority_resolution.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul>
      </details>}
      <details><summary>Authority context and exact supporting quotations</summary>
        <pre>{JSON.stringify({ context: proposal.authority_context, references: proposal.authority_links }, null, 2)}</pre>
      </details>
    </section>}
    <div className="ev-two">
      <section className="ev-card"><h3>Claim assessed against this source</h3><p>{result.claim_text}</p><p className="ev-muted">{humanize(item.interpretation.mode)} · {item.interpretation.stance} · {evidenceWeight(result, item)}</p></section>
      <section className="ev-card"><h3>Lineage</h3>
        {[["Previous version", item.source.predecessor_source_id], ["Superseded by", item.source.successor_source_id], ["Derived from", item.source.derived_from_source_id], ["Duplicate group", item.source.duplicate_group]].filter(([, id]) => id).map(([label, id]) => <p key={label}>{label}: <span className="ev-mono">{id}</span></p>)}
        {!item.source.predecessor_source_id && !item.source.successor_source_id && !item.source.derived_from_source_id && !item.source.duplicate_group && <p className="ev-muted">No lineage recorded in this assessment snapshot.</p>}
        <p className="ev-muted">Recorded links do not establish independent corroboration.</p>
      </section>
    </div>
    <SourceMetadata source={item.source} />
    <details className="ev-card"><summary>Technical details: supplied judgements and scoring</summary>
      <p className="ev-muted">{automatic ? "Authority is subject to the cited checks above; independence remains unverified. Quality dimensions are bounded grammar checks." : "Authority and independence flags are caller declarations. Quality scores are supplied assumptions."}</p>
      <pre>{JSON.stringify({ source: item.source, supplied_judgements: item.supplied_judgements, scoring: edge ?? null }, null, 2)}</pre>
    </details>
  </>;
}

export function explainEvidenceGap(gap: string, result: SuppliedResult): string {
  if (gap === "No Document or structured row attests to this Fact.") {
    return result.inputs.length
      ? "Evidence was examined, but none passed all checks required to contribute to the verdict. Inspect the source details for the specific reasons."
      : "No evidence was available to score in this assessment. This does not establish that the claim is false.";
  }
  if (gap === "No material formal attestation resolves the asserted value.")
    return "No formal evidence with sufficient weight establishes the claim after the assessment checks.";
  if (gap === "No material observed attestation resolves the asserted value.")
    return "No evidence of actual practice with sufficient weight establishes the claim after the assessment checks.";
  return gap;
}

export function SuppliedResultView({ result, onDetailChange }: { result: SuppliedResult; onDetailChange?: (open: boolean) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const origin = useRef<HTMLElement | null>(null);
  const graphSection = useRef<HTMLDivElement>(null);
  const item = result.inputs.find(input => input.input_id === selected);
  const sources = new Set(result.inputs.map(input => input.source.source_id)).size;
  const assessment = result.assessment;
  const open = (id: string) => { origin.current = document.activeElement as HTMLElement; setSelected(id); onDetailChange?.(true); };
  const back = () => { setSelected(null); onDetailChange?.(false); requestAnimationFrame(() => origin.current?.focus()); };
  return <section className="ev-workspace" aria-label="Assessment result">
    <div hidden={!!item}>
      <article className="ev-card">
        <span className="ev-kicker">Facet assessment · {result.status === "assessed_automatically" ? "Automatic result · Review pending" : "Supplied judgements"}</span>
        <p className="ev-claim">{result.claim_text}</p>
        {result.claim_text !== result.facet && <p className="ev-muted">Scope being assessed: {result.facet}</p>}
        <div className="ev-chips"><Badge>Target: {humanize(result.assessment_target)}</Badge><Badge>As of: {result.as_of}</Badge><Badge>{result.persisted ? "Saved snapshot" : "Not saved"}</Badge></div>
        {result.status === "assessed_automatically" && result.rule_comparison && <section className="ev-notice">
          <strong>{result.rule_comparison.message}</strong><p>{result.rule_comparison.notice}</p>
        </section>}
        <p><strong>Conditional outcome: {assessment.overall_outcome}</strong></p>
        <p className="ev-muted">{result.assurance.notice}</p>
        <button className="ev-button" onClick={() => { graphSection.current?.scrollIntoView({block: "start"}); graphSection.current?.focus({preventScroll: true}); }}>View evidence graph</button>
      </article>
      <div className="ev-two">
        {[{ label: "Formally", value: assessment.formal_outcome }, { label: "In practice", value: assessment.observed_outcome }].map(lane =>
          <section className="ev-card" key={lane.label}><span className="ev-kicker">{lane.label}</span>
            <Badge tone={outcomeTone(lane.value)}>{lane.value}</Badge>
            <p className="ev-muted">Conditional on the inputs admitted to this assessment.</p>
          </section>)}
      </div>
      <section className="ev-card"><div className="ev-toolbar" style={{ marginBottom: 0 }}><div>
        <span className="ev-kicker">Conditional confidence</span><strong>{assessment.confidence}</strong>
      </div><span className="ev-muted">{result.inputs.length} assessment inputs · {sources} unique sources</span></div>
        <p className="ev-muted">Human review is not established by this request. This assesses the stated facet, not every assertion in the claim. {result.persisted ? "Result is saved as an immutable snapshot." : "Result is not saved."}</p>
      </section>
      <h3>Evidence used in this assessment</h3>
      <p className="ev-muted">Includes retained context and excluded inputs. Other retrieved candidates have not been assessed.</p>
      <div className="ev-list">{result.inputs.map(input => {
        return <EvidenceRow key={input.input_id} title={input.source.title}
          subtitle={`${humanize(input.interpretation.mode)} · ${evidenceWeight(result, input)}`}
          preview={input.interpretation.citations[0]?.quotation ?? input.interpretation.rationale}
          badges={<><Badge>{input.interpretation.stance}</Badge><Badge>{input.source.lifecycle_status ?? "unknown"}</Badge></>} onOpen={() => open(input.input_id)} />;
      })}</div>
      {result.deployment_event_findings?.map((finding, i) => <section className="ev-card" key={i}><h3>Deployment sign-off evidence · unresolved</h3><p>{finding.event_id} · {finding.related_record}</p><p>{finding.message}</p><p>{finding.next_step}</p><CitationView citation={finding.citation} /></section>)}
      <div ref={graphSection} className="ev-jump" tabIndex={-1}><AssessmentGraph result={result} onOpen={open} /></div>
      {assessment.gaps.length > 0 && <section className="ev-card"><h3>Evidence gaps</h3>
        <p className="ev-muted">Gaps refer to admitted evidence, not an exhaustive corpus search.</p>
        <ul>{assessment.gaps.map((gap, i) => <li key={i}>{explainEvidenceGap(gap, result)}</li>)}</ul>
      </section>}
      <details className="ev-card"><summary>Assessment explanation, limits and rules</summary>
        <p>{assessment.summary}</p><ul>{result.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul>
        <details><summary>Technical assurance and rules</summary>
          <pre>{JSON.stringify({ assurance: result.assurance, target_validation: result.target_validation, config_version: result.config_version, rules: assessment.rules_applied, original_gap_messages: assessment.gaps }, null, 2)}</pre>
        </details>
      </details>
    </div>
    {item && <DetailFrame title={item.source.title} onBack={back}><SuppliedEvidenceDetail result={result} item={item} /></DetailFrame>}
  </section>;
}

export default function SuppliedAssessment({ claim, expectedFacet, onDetailChange }: { claim: string; expectedFacet?: string; onDetailChange?: (open: boolean) => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<SuppliedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(false);
  const editor = useRef<HTMLDetailsElement>(null);
  const generation = useRef(0);
  const detailChange = (open: boolean) => { setDetail(open); onDetailChange?.(open); };
  useEffect(() => () => { generation.current += 1; }, []);
  async function submit() {
    const current = ++generation.current;
    setResult(null); setError(null); setBusy(true); detailChange(false);
    try {
      const request = parseSuppliedRequest(text, claim, expectedFacet);
      const response = checkSuppliedResponse(await assessSupplied(request), request);
      if (current === generation.current) {
        setResult(response);
        if (editor.current) editor.current.open = false;
      }
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : "Assessment unavailable.");
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  return <section className="ev-workspace">
    <details ref={editor} className="ev-card" hidden={detail}>
      <summary>{result ? "Edit supplied assessment inputs" : "Assess prepared judgements"} <span className="ev-muted" style={{ display: "inline" }}>· Development input</span></summary>
      <p>Use prepared judgements to assess a facet of this exact claim. Retrieved candidates remain unassessed. Automatic interpretation is not performed.</p>
      {expectedFacet && <p className="ev-quote">Required scoped facet: {expectedFacet}</p>}
      <label>Prepared assessment request (JSON)
        <textarea value={text} disabled={busy} rows={6}
          onChange={event => { generation.current += 1; setText(event.target.value); setResult(null); setError(null); detailChange(false); }} />
      </label>
      <p className="ev-muted">Use the supplied-assessment API request format, not the teammate review-return JSON. No scores or relationships are filled in automatically.</p>
      <button type="button" className="ev-button ev-button-primary" disabled={busy || !text.trim()} onClick={submit}>
        {busy ? "Assessing…" : "Assess supplied judgements"}
      </button>
      {error && <p role="alert">{error}</p>}
    </details>
    {result && <SuppliedResultView result={result} onDetailChange={detailChange} />}
  </section>;
}
