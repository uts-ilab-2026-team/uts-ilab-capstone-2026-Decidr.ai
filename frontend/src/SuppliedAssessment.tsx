import { useEffect, useRef, useState, type CSSProperties } from "react";
import RoleCrossCheck from "./RoleCrossCheck";
import AssessmentGraph, { evidenceWeight, unifiedGraph } from "./AssessmentGraph";
import { Badge, DetailFrame, EvidenceRow, SourceMetadata, humanize, outcomeTone } from "./EvidenceUI";
import { assessSupplied, getCorpusEvidence } from "./api";
import {
  checkSuppliedResponse, parseSuppliedRequest,
  type Citation, type SuppliedResult, type CanonicalAssessment, type CanonicalFinding,
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
function TemporalDerivation({finding}: {finding: CanonicalFinding}) {
  const basis = finding.temporal_derivation;
  if (!basis) return null;
  return <section aria-label="Document date applicability"><p><strong>Date applicability established from saved document headers.</strong></p>
    <p>{basis.reason}</p><p className="ev-muted">Assessed date: {basis.assessed_date} · Effective from: {basis.effective_start_date}{finding.original_time_fit ? ` · Initial date fit: ${humanize(finding.original_time_fit)}` : ""}</p>
  </section>;
}

function CanonicalEvidenceDetail({result, item}: {result: SuppliedResult; item: Input}) {
  const canonical = result.canonical_assessment!;
  const findings = canonical.components.flatMap(component => component.findings
    .filter(finding => item.interpretation.citations.some(citation => citation.source_id === finding.source_id && citation.evidence_id === finding.evidence_id))
    .map(finding => ({component, finding})));
  const citations = [...new Map([...item.interpretation.citations, ...findings.flatMap(({finding}) => finding.citations)]
    .map(citation => [JSON.stringify([citation.source_id, citation.evidence_id, citation.start, citation.end, citation.quotation]), citation])).values()];
  return <>
    <section className="ev-card"><h3>Evidence interpretation</h3>
      {findings.length ? findings.map(({component, finding}, i) => <section key={i}><h4>{component.text}</h4>
        <p><strong>{humanize(finding.relationship)}</strong> · {finding.admitted ? "Used in assessment" : "Retained as context or excluded"}</p>
        <p>{finding.reason}</p><ul>{[...finding.exclusion_reasons, ...finding.limitations].map((reason, j) => <li key={j}>{reason}</li>)}</ul>
        <p className="ev-muted">Scope fit: {humanize(finding.scope_fit)} · Date fit: {humanize(finding.time_fit)} · Directness: {humanize(String(finding.directness))}</p>
        <TemporalDerivation finding={finding}/>
      </section>) : <p>This retrieved passage was not used to establish a component of the claim.</p>}
    </section>
    <section className="ev-card"><h3>Exact citations</h3>{citations.map((citation, i) => <CitationView key={i} citation={citation}/>)}</section>
    <section className="ev-card"><h3>Source limits and recorded links</h3><p>Recorded ownership, identifiers and references do not by themselves establish authority or independent corroboration.</p>
      {!!item.reasons.length && <ul>{item.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
      {[['Previous version', item.source.predecessor_source_id], ['Superseded by', item.source.successor_source_id], ['Derived from', item.source.derived_from_source_id], ['Duplicate group', item.source.duplicate_group]].filter(([, id]) => id).map(([label, id]) => <p key={label}>{label}: {id}</p>)}
    </section>
    <SourceMetadata source={item.source}/>
  </>;
}
export function SuppliedEvidenceDetail({ result, item }: { result: SuppliedResult; item: Input }) {
  if (result.canonical_assessment) return <CanonicalEvidenceDetail result={result} item={item}/>;
  const edge = (result.credibility_assessment ?? result.assessment).evidence.find(value => value.edge_id === item.edge_id);
  const automatic = result.status === "assessed_automatically";
  const componentFindings = result.transaction_assessment?.components.flatMap(component =>
    component.observations.filter(observation => item.interpretation.citations.some(citation => citation.evidence_id === observation.evidence_id))
      .map(observation => ({label: component.label, ...observation}))) ?? [];
  const proposal = result.proposals?.find(value => item.interpretation.citations.some(citation => citation.evidence_id === value.evidence_id));
  return <>
    <div className="ev-chips"><Badge>{item.source.lifecycle_status ?? "unknown"}</Badge><span className="ev-muted">{item.source.source_id}</span></div>
    <dl className="ev-card ev-summary-fields">
      {[["Lane", humanize(item.interpretation.mode)], ["Relationship", item.interpretation.stance],
        ["Source class", humanize(String(item.supplied_judgements.source_class ?? item.source.source_type ?? "Unknown"))],
        ["Effective from", item.source.effective_start_date ?? "Not recorded"], ["Materiality", evidenceWeight(result, item)]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
    </dl>
    <section className="ev-card"><h3>{automatic ? "Automatic interpretation" : "Supplied interpretation"}</h3><p className="ev-quote">{item.interpretation.rationale}</p>
      {!!componentFindings.length && <><h4>Used in the claim assessment</h4>{componentFindings.map((finding, i) => <p key={i}><strong>{finding.label}: {humanize(finding.status)}</strong><br/>{finding.reason}</p>)}</>}
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
        </> : <p className="ev-muted">{componentFindings.length ? "This passage contributes to the component findings above. It has no framework score because the source verification checks remain unresolved." : "Not scored. Retained for review; the reasons above explain why it was not admitted to framework scoring."}</p>}
      </section>
      <section className="ev-card"><h3>Derivation and limitations</h3>
        {edge ? <ul>{[...edge.trace, ...edge.limitations].map((line, i) => <li key={i}>{line}</li>)}</ul>
          : <p className="ev-muted">No framework scoring trace for this input. See the reasons above.</p>}
      </section>
    </div>
    {proposal && result.assessment_target === "formal_rule" && <section className="ev-card"><h3>Approval-rule comparison and authority</h3>
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
    <RoleCrossCheck asOf={result.as_of} />
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

function LegacySuppliedResultView({ result, onDetailChange }: { result: SuppliedResult; onDetailChange?: (open: boolean) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const origin = useRef<HTMLElement | null>(null);
  const graphSection = useRef<HTMLDivElement>(null);
  const item = result.inputs.find(input => input.input_id === selected);
  const transaction = result.transaction_assessment;
  const conclusion = result.claim_conclusion ?? (transaction ? {
    label: ({supported_by_records:"Supported by the available record",partially_supported:"Partially supported by the available records",contradicted_by_records:"Contradicted by the available records",conflicting_records:"Conflicting records",unresolved:"Not established by the available records"} as Record<string,string>)[transaction.status] ?? "Not established by the available records",
    summary: transaction.components.map(c => `${c.label}: ${humanize(c.status)}.`).join(" "),
    notice: "This assesses what the linked records say, not independently verified truth or policy compliance. Human review is pending.",
  } : null);
  const assessment = !conclusion || result.assessment.basis ? result.assessment : {
    ...result.assessment, overall_outcome: conclusion.label, observed_outcome: conclusion.label,
    formal_outcome: "Not assessed for this event claim", confidence: "Not independently verified",
    summary: conclusion.summary, gaps: transaction?.components.filter(c => c.status !== "supported").map(c => c.label) ?? [],
  };
  const credibility = result.credibility_assessment ?? (conclusion ? result.assessment : null);
  const usedInputIds = new Set(unifiedGraph(result).nodes.filter(node => node.used).flatMap(node => node.inputs.map(input => input.input_id)));
  const usedInputs = result.inputs.filter(input => usedInputIds.has(input.input_id));
  const otherInputs = result.inputs.filter(input => !usedInputIds.has(input.input_id));
  const sources = new Set(usedInputs.map(input => input.source.source_id)).size;
  const [graphOpenSignal, setGraphOpenSignal] = useState(0);
  const verificationChecks = [
    ["Source authority", "authority_verified"], ["Date applicability", "temporal_matches"], ["Independent corroboration", "independence_verified"],
  ].map(([label, key]) => ({label, status: usedInputs.length && usedInputs.every(input => input.supplied_judgements[key] === true) ? "Recorded check passed" : "Not established"}));
  const open = (id: string) => { origin.current = document.activeElement as HTMLElement; setSelected(id); onDetailChange?.(true); };
  const back = () => { setSelected(null); onDetailChange?.(false); requestAnimationFrame(() => origin.current?.focus()); };
  return <section className="ev-workspace" aria-label="Assessment result">
    <div hidden={!!item}>
      <article className="ev-card">
        <span className="ev-kicker">Facet assessment · {result.status === "assessed_automatically" ? "Automatic result · Review pending" : "Supplied judgements"}</span>
        <p className="ev-claim">{result.claim_text}</p>
        {result.claim_text !== result.facet && <p className="ev-muted">Scope being assessed: {result.facet}</p>}
        <div className="ev-chips"><Badge>Target: {humanize(result.assessment_target)}</Badge><Badge>As of: {result.as_of}</Badge><Badge>{result.persisted ? "Saved snapshot" : "Not saved"}</Badge></div>
      </article>
      <section className="ev-card" aria-label="Credibility framework checks">
        <h3>Credibility framework checks</h3>
        {result.status === "assessed_automatically" && result.rule_comparison && <section className="ev-notice">
          <strong>{result.rule_comparison.message}</strong><p>{result.rule_comparison.notice}</p>
        </section>}
        {conclusion && <section className="ev-notice" aria-label="Final claim assessment"><h2>{result.assessment.basis ? result.assessment.overall_outcome : conclusion.label}</h2><p>{result.assessment.basis ? result.assessment.summary : conclusion.summary}</p><p className="ev-muted">{conclusion.notice}</p></section>}
        {!conclusion && <><p><strong>Conditional outcome: {assessment.overall_outcome}</strong></p><p className="ev-muted">{result.assurance.notice}</p></>}
        {transaction && <dl className="ev-component-summary">{transaction.components.map(component => <div key={component.field}><dt>{component.label}</dt><dd><Badge>{humanize(component.status)}</Badge></dd></div>)}</dl>}
        {result.transaction_assessment && <details><summary>Why this assessment · exact supporting records</summary><section className="ev-notice">
          <strong>{result.transaction_assessment.record_id} · {humanize(result.transaction_assessment.status)}</strong>
          <p>{result.transaction_assessment.notice}</p>
          {result.transaction_assessment.components.map(component => <div key={component.field}>
            <p><strong>{component.label}: {humanize(component.status)}</strong></p>
            {component.observations.length ? component.observations.map((observation, i) => <p key={i}>{observation.reason}</p>) : <p>No matching linked record establishes this part of the claim.</p>}
          </div>)}
          {!!result.transaction_assessment.candidate_record_ids?.length && <p>Matching record identifiers: {result.transaction_assessment.candidate_record_ids.join(", ")}</p>}
          <p>{result.transaction_assessment.next_step}</p>
          <details><summary>Linked records and exact citations</summary>
            {result.transaction_assessment.citations.map(citation => <div key={citation.evidence_id}><p>{humanize(result.transaction_assessment!.connections.find(link => link.evidence_id === citation.evidence_id)?.relationship ?? "linked record")}</p><CitationView citation={citation} /></div>)}
          </details>
        </section></details>}
        {!conclusion && <div className="ev-two">
          {[{ label: "Formally", value: assessment.formal_outcome }, { label: "In practice", value: assessment.observed_outcome }].map(lane =>
            <section className="ev-card" key={lane.label}><span className="ev-kicker">{lane.label}</span><Badge tone={outcomeTone(lane.value)}>{lane.value}</Badge><p className="ev-muted">Conditional on the inputs admitted to this assessment.</p></section>)}
        </div>}
        <section aria-label="Verification limits">
          <h4>{conclusion ? "Verification limits" : "Conditional confidence"}</h4>
          <strong>{assessment.confidence}</strong>
          {conclusion && <><p className="ev-muted">The result above describes the cited records. Verification of those records remains qualified by these checks.</p><ul>{verificationChecks.map(check => <li key={check.label}>{check.label}: {check.status}</li>)}</ul></>}
          <p className="ev-muted">{usedInputs.length} inputs used in this comparison · {sources} unique sources · {result.inputs.length} inputs examined</p>
          <p className="ev-muted">{result.status === "assessed_automatically" ? "Human review is pending." : "Human review is not established by this request."} {result.persisted ? "Saved results and their exact citations are preserved." : "This result has not been saved."}</p>
        </section>
        <button className="ev-button" onClick={() => { setGraphOpenSignal(value => value + 1); graphSection.current?.scrollIntoView({block: "start"}); graphSection.current?.focus({preventScroll: true}); }}>View evidence graph</button>
      </section>
      {result.practice_assessment && <section className="ev-card"><h3>Recorded practice compared with the requirement</h3>
        <p>{result.practice_assessment.notice}</p>
        <p className="ev-muted">{result.practice_assessment.examined_records} operational records examined · {result.practice_assessment.findings.length} findings shown · {result.practice_assessment.omitted_findings} additional findings omitted</p>
        {!result.practice_assessment.findings.length && <p>{result.practice_assessment.status === "unsupported_rule" ? "The claim is outside the supported operational comparison forms." : "No records with enough matching amount, currency and scope information were found for comparison."}</p>}
        {result.practice_assessment.findings.map(finding => <details key={finding.citation.evidence_id}>
          <summary>{finding.record_id} · {humanize(finding.status)}</summary>
          <p>{finding.reason}</p>
          <p className="ev-muted">{finding.source_title} · Recorded amount: {finding.amount} · Event date: {finding.event_date ?? "Not established"} · Approval date: {finding.approval_date ?? "Not established"}</p>
          <ul>{finding.limitations.map((line, i) => <li key={i}>{line}</li>)}</ul>
          <CitationView citation={finding.citation} />
        </details>)}
      </section>}
      <h3>Evidence used in this assessment</h3>
      <p className="ev-muted">{transaction ? "These passages are cited by the component findings above. Source verification is shown separately." : "These passages contribute to an interpreted finding or framework score. Open a passage to inspect its role and verification limits."}</p>
      {!usedInputs.length && <p>No passage establishes a component of this claim.</p>}
      <div className="ev-list">{usedInputs.map(input => <EvidenceRow key={input.input_id} title={input.source.title}
        subtitle={`${transaction ? "Used in component comparison" : humanize(input.interpretation.mode)} · ${evidenceWeight(result, input)}`}
        preview={input.interpretation.citations[0]?.quotation ?? input.interpretation.rationale}
        badges={<><Badge>{input.interpretation.stance}</Badge><Badge>{input.source.lifecycle_status ?? "unknown"}</Badge></>} onOpen={() => open(input.input_id)} />)}</div>
      {!!otherInputs.length && <details className="ev-card"><summary>Other retrieved passages · {otherInputs.length}</summary>
        <p className="ev-muted">These passages were not used in the findings above. Their retrieval does not make them supporting or contradictory evidence.</p>
        <div className="ev-list">{otherInputs.map(input => <EvidenceRow key={input.input_id} title={input.source.title} subtitle="Retained for review" preview={input.interpretation.citations[0]?.quotation ?? input.interpretation.rationale} badges={<Badge>Not used for this claim</Badge>} onOpen={() => open(input.input_id)} />)}</div>
      </details>}
      {result.deployment_event_findings?.map((finding, i) => <section className="ev-card" key={i}><h3>Deployment sign-off evidence · unresolved</h3><p>{finding.event_id} · {finding.related_record}</p><p>{finding.message}</p><p>{finding.next_step}</p><CitationView citation={finding.citation} /></section>)}
      <div ref={graphSection} className="ev-jump" tabIndex={-1}><AssessmentGraph result={result} onOpen={open} openSignal={graphOpenSignal} /></div>
      {assessment.gaps.length > 0 && <details className="ev-card"><summary>{conclusion ? "What remains unresolved" : "Unresolved credibility checks"}</summary>
        <p className="ev-muted">These gaps explain the saved result above.</p>
        <ul>{assessment.gaps.map((gap, i) => <li key={i}>{explainEvidenceGap(gap, result)}</li>)}</ul>
      </details>}
      <details className="ev-card"><summary>Assessment explanation, limits and rules</summary>
        <p>{assessment.summary}</p><ul>{result.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul>
        <details><summary>Technical assurance and rules</summary>
          <pre>{JSON.stringify({ assurance: result.assurance, target_validation: result.target_validation, config_version: result.config_version, rules: assessment.rules_applied, original_gap_messages: assessment.gaps, evidence_admission_record: credibility }, null, 2)}</pre>
        </details>
      </details>
    </div>
    {item && <DetailFrame title={item.source.title} onBack={back}><SuppliedEvidenceDetail result={result} item={item} /></DetailFrame>}
  </section>;
}

export function assessmentConfidence(score: number | null): string {
  return typeof score === "number" && Number.isFinite(score) && score >= 0 && score <= 100
    ? `${Math.round(score * 10) / 10}/100` : "Not available";
}

export function processingExplanation(code: string | null): string {
  switch (code) {
    case "provider_unavailable": return "The local assessment service is unavailable. Check that the configured local model is running, then try again.";
    case "provider_failure": return "The local assessment service could not finish the request. Try the assessment again.";
    case "invalid_model_output": return "The automatic interpretation did not pass validation, so no assessment was issued.";
    case "interpretation_failure": return "The system could not reliably interpret the claim and its evidence. Try the assessment again or clarify the wording.";
    default: return "The assessment could not be completed because of a processing problem.";
  }
}

function CanonicalResultView({result, canonical, onDetailChange}: {result: SuppliedResult; canonical: CanonicalAssessment; onDetailChange?: (open: boolean) => void}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [graphOpenSignal, setGraphOpenSignal] = useState(0);
  const graphSection = useRef<HTMLDivElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const item = result.inputs.find(input => input.input_id === selected);
  const failed = canonical.processing.status === "failed";
  const reviewed = result.status === "assessed_supplied_judgements";
  const interpretedTarget = typeof canonical.interpreted_claim?.target === "string" ? canonical.interpreted_claim.target : null;
  const used = new Set(canonical.evidence_relations.filter(relation => relation.inferential).map(relation => JSON.stringify([relation.source_id, relation.evidence_id])));
  const sources = new Set(canonical.evidence_relations.filter(relation => relation.inferential).map(relation => relation.source_id));
  const open = (id: string) => { origin.current = document.activeElement as HTMLElement; setSelected(id); onDetailChange?.(true); };
  const back = () => { setSelected(null); onDetailChange?.(false); requestAnimationFrame(() => origin.current?.focus()); };
  return <section className="ev-workspace" aria-label="Assessment result">
    <div hidden={!!item}>
      <article className="ev-card"><span className="ev-kicker">{failed ? "Assessment attempt · Processing incomplete" : reviewed ? "Human review revision · Conditional" : "Automatic result · Review pending"}</span>
        <p className="ev-claim">{result.claim_text}</p>
        {result.facet !== result.claim_text && <p className="ev-muted">Scope being assessed: {result.facet}</p>}
        <div className="ev-chips"><Badge>Target: {humanize(interpretedTarget ?? (failed ? "Not established" : result.assessment_target))}</Badge><Badge>As of: {result.as_of}</Badge><Badge>{result.persisted ? "Saved snapshot" : "Not saved"}</Badge></div>
      </article>
      <section className="ev-card" aria-label="Credibility framework checks"><h3>Credibility framework checks</h3>
        {failed ? <section role="alert" aria-label="Assessment processing failure"><h2>Assessment not completed</h2><p>{processingExplanation(canonical.processing.code)}</p>
          <p className="ev-muted">No assessment outcome or confidence score was produced. This is a processing problem, not a finding that the evidence is insufficient.</p>
          <details><summary>Technical details</summary>{canonical.processing.code && <p>Reason: {canonical.processing.code}</p>}<p>{canonical.processing.message}</p></details>
        </section> : <>
          <section className="ev-notice" aria-label="Final claim assessment"><h2>{canonical.overall_outcome}</h2><p>{canonical.summary}</p></section>
          <dl className="ev-component-summary">{canonical.components.map(component => <div key={component.id}><dt>{component.text}</dt><dd><Badge tone={outcomeTone(component.outcome)}>{component.outcome}</Badge></dd></div>)}</dl>
          <section aria-label="Assessment confidence"><h4>Assessment confidence</h4><strong>{assessmentConfidence(canonical.confidence.score)}</strong>
            <p>{canonical.confidence.label}</p><p className="ev-muted">Uncalibrated assessment confidence: confidence in this assessment outcome, not the probability that the claim is true. A contradicted claim can have high assessment confidence.</p>
            <details><summary>How confidence was calculated</summary><p>{canonical.confidence.meaning}</p><p>Method: {canonical.confidence.method}</p>
              <ul>{canonical.confidence.basis.map((basis, i) => <li key={i}>{basis}</li>)}</ul>
              <dl>{Object.entries(canonical.confidence.weights).map(([factor, weight]) => <div key={factor}><dt>{humanize(factor)} weight</dt><dd>{Math.round(weight * 100)}%</dd></div>)}</dl>
              {canonical.confidence.components.map(component => <section key={component.component_id}><h4>{canonical.components.find(item => item.id === component.component_id)?.text ?? component.component_id}: {assessmentConfidence(component.score)}</h4>
                <dl>{Object.entries(component.factors).map(([factor, value]) => <div key={factor}><dt>{humanize(factor)}</dt><dd>{Number.isFinite(value) ? value : "Not available"}</dd></div>)}</dl>
                <ul>{component.basis.map((basis, i) => <li key={i}>{basis}</li>)}</ul>
              </section>)}
              <p className="ev-muted">This method has not been statistically calibrated against held-out claims.</p>
            </details>
          </section>
          <p className="ev-muted">{used.size} passages used in assessment · {sources.size} unique sources. Repeated passages and links are not independent corroboration.</p>
          <p className="ev-muted">{reviewed ? "This revision uses reviewer judgements; it does not independently verify the sources." : "Human review is pending."} {result.persisted ? "The saved result and exact citations are preserved." : "This result has not been saved."}</p>
        </>}
        <button className="ev-button" onClick={() => { setGraphOpenSignal(value => value + 1); graphSection.current?.scrollIntoView({block: "start"}); graphSection.current?.focus({preventScroll: true}); }}>{failed ? "Inspect retrieved context" : "View evidence graph"}</button>
      </section>
      {!!canonical.unresolved_questions.length && <section className="ev-card"><h3>{failed ? "What is needed to continue" : "What remains unresolved"}</h3><ul>{canonical.unresolved_questions.map((question, i) => <li key={i}>{question}</li>)}</ul></section>}
      {!failed && <section className="ev-card"><h3>Findings and exact evidence</h3>
        {canonical.components.map(component => <details key={component.id}><summary>{component.text} · {component.outcome}</summary>
          {component.findings.length ? component.findings.map((finding, i) => <section key={i}>
            <p><strong>{humanize(finding.relationship)}</strong> · {finding.admitted ? "Used in assessment" : "Context or excluded evidence"}</p><p>{finding.reason}</p>
            {!!finding.exclusion_reasons.length && <ul>{finding.exclusion_reasons.map((reason, j) => <li key={j}>{reason}</li>)}</ul>}
            {!!finding.limitations.length && <ul>{finding.limitations.map((limit, j) => <li key={j}>{limit}</li>)}</ul>}
            <TemporalDerivation finding={finding}/>
            {finding.citations.map((citation, j) => <CitationView key={j} citation={citation} />)}
          </section>) : <p>No validated evidence resolves this component.</p>}
        </details>)}
      </section>}
      <div ref={graphSection} className="ev-jump" tabIndex={-1}><AssessmentGraph result={result} onOpen={open} openSignal={graphOpenSignal}/></div>
      <details className="ev-card"><summary>Interpreted claim and assessment record</summary>
        {!failed && canonical.interpreted_claim && <><p>Assessment target: {humanize(canonical.interpreted_claim.target)}</p>
          {!!canonical.interpreted_claim.ambiguities.length && <ul>{canonical.interpreted_claim.ambiguities.map((ambiguity, i) => <li key={i}>{ambiguity}</li>)}</ul>}
          {canonical.interpreted_claim.components.map(component => <div key={component.id}><h4>{component.text}</h4><p>Original claim wording: {component.claim_quote}</p>
            <dl>{Object.entries({entities: component.entities, predicate: component.predicate, polarity: component.polarity, quantities: component.quantities, scope: component.scope, temporal: component.temporal, modality: component.modality}).map(([field, value]) => <div key={field}><dt>{humanize(field)}</dt><dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd></div>)}</dl>
          </div>)}
        </>}
        <details><summary>Processing diagnostics and provenance</summary><pre>{JSON.stringify({processing: canonical.processing, diagnostics: canonical.diagnostics, provenance: canonical.provenance}, null, 2)}</pre></details>
      </details>
    </div>
    {item && <DetailFrame title={item.source.title} onBack={back}><SuppliedEvidenceDetail result={result} item={item}/></DetailFrame>}
  </section>;
}

export function SuppliedResultView({result, onDetailChange}: {result: SuppliedResult; onDetailChange?: (open: boolean) => void}) {
  return result.canonical_assessment
    ? <CanonicalResultView result={result} canonical={result.canonical_assessment} onDetailChange={onDetailChange}/>
    : <LegacySuppliedResultView result={result} onDetailChange={onDetailChange}/>;
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
