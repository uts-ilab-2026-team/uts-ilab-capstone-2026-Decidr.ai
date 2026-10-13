import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { Citation, SuppliedResult } from "./suppliedAssessmentContract";
import ConnectedEvidence from "./ConnectedEvidence";
import { Count, humanize, quotePreview } from "./EvidenceUI";

type Input = SuppliedResult["inputs"][number];
export function graphInputs(result: SuppliedResult, lane: string) {
  return result.inputs.filter(item => lane === "both" || item.interpretation.mode === lane);
}
export function evidenceWeight(result: SuppliedResult, item: Input) {
  if (result.canonical_assessment) {
    const used = result.canonical_assessment.evidence_relations.some(relation => relation.inferential && item.interpretation.citations.some(citation => citation.source_id === relation.source_id && citation.evidence_id === relation.evidence_id));
    return used ? "Used in canonical assessment" : "Context or excluded evidence";
  }
  const edge = (result.credibility_assessment ?? result.assessment).evidence.find(value => value.edge_id === item.edge_id);
  if (!item.admitted_to_framework) return "Not scored · retained for review";
  if (!edge || edge.materiality_score === null) return "Not scored";
  return `${edge.materiality_score.toFixed(2)} · ${edge.material ? "material" : "weighted down"}`;
}
export function graphLanes(result: SuppliedResult, lane: string) {
  const inputs = graphInputs(result, lane);
  return ["formal", "observed", "unresolved"].map(mode => ({
    mode, label: mode === "formal" ? "Formal evidence" : mode === "observed" ? "Observed practice" : "Lane unresolved",
    items: inputs.filter(item => item.interpretation.mode === mode),
  })).filter(group => group.items.length > 0);
}
export function passageLabel(item: Input) {
  return item.interpretation.citations[0]?.locator ?? item.input_id;
}

type Context = {relationship: string; reason: string; temporal_status?: string; details?: Record<string, unknown>; limitations: string[]};
export type GraphNode = {
  id: string; evidenceId: string; sourceId: string; title: string; recordIds: string[];
  lanes: string[]; citations: Citation[]; inputs: Input[];
  findings: {label: string; status: string; reason: string; componentId?: string}[];
  contexts: Context[]; used: boolean;
};
export type GraphEdge = {from: string; to: string; relationship: string; basis: string; inferential?: boolean};
export type GraphComponent = {id: string; text: string; outcome: string};
const laneNames: Record<string, string> = {formal: "Formal evidence", observed: "Observed practice", documented: "Documentation", unresolved: "Lane unresolved"};
const canonicalLaneNames: Record<string, string> = {formal: "Formal documents", observed: "Reported or recorded practice", documented: "Documentation", unresolved: "Source category unknown"};
const sourceTypeLanes = new Map<string, string>([
  ["policy", "formal"], ["procedure", "formal"], ["role_description", "formal"],
  ["interview", "observed"], ["internal_communication", "observed"], ["crm_records", "observed"], ["project_tasks", "observed"], ["audit_events", "observed"],
  ["meeting", "documented"], ["organisational_information", "documented"], ["technical", "documented"],
]);
const passageKey = (citation: Citation) => JSON.stringify([citation.source_id, citation.evidence_id]);
const addUnique = <T,>(items: T[], value: T) => { if (!items.some(item => JSON.stringify(item) === JSON.stringify(value))) items.push(value); };

// One passage may supply several findings or quotations. Its source remains part of its identity.
export function unifiedGraph(result: SuppliedResult) {
  const canonical = result.canonical_assessment;
  const sourceLanes = new Map<string, Set<string>>();
  if (canonical) for (const {source} of result.inputs) {
    const lanes = sourceLanes.get(source.source_id) ?? new Set<string>();
    lanes.add(sourceTypeLanes.get(source.source_type) ?? "unresolved");
    sourceLanes.set(source.source_id, lanes);
  }
  const nodes = new Map<string, GraphNode>();
  const aliases = new Map<string, string>([["claim", "claim"]]);
  const edges: GraphEdge[] = [];
  const add = (citation: Citation | undefined, title: string, fallback?: string) => {
    const id = citation ? passageKey(citation) : `input:${fallback}`;
    let node = nodes.get(id);
    if (!node) {
      node = {id, evidenceId: citation?.evidence_id ?? fallback ?? "", sourceId: citation?.source_id ?? "", title,
        recordIds: [], lanes: [], citations: [], inputs: [], findings: [], contexts: [], used: false};
      nodes.set(id, node);
    }
    if (citation) addUnique(node.citations, {...citation});
    return node;
  };
  const link = (node: GraphNode, relationship: string, basis: string) => addUnique(edges, {from: "claim", to: node.id, relationship, basis});
  for (const item of result.inputs) {
    for (const citation of item.interpretation.citations.length ? item.interpretation.citations : [undefined]) {
      const sourceMatches = !citation || citation.source_id === item.source.source_id;
      const node = add(citation, sourceMatches ? item.source.title : citation!.source_id, item.input_id);
      if (!sourceMatches) {
        node.contexts.push({relationship: "unresolved", reason: "Citation source does not match the assessment input source.", limitations: ["Input findings are not assigned to this passage."]});
        continue;
      }
      addUnique(node.inputs, item);
      if (!canonical) addUnique(node.lanes, laneNames[item.interpretation.mode] ? item.interpretation.mode : "unresolved");
      const excluded = item.supplied_judgements.temporal_matches === false ||
        !!(item.source.creation_date && item.source.creation_date.slice(0, 10) > result.as_of);
      if (excluded && !canonical) node.contexts.push({relationship: "excluded", reason: "Not applicable at the selected assessment date.", limitations: item.reasons});
      node.used ||= !canonical && !excluded && (item.admitted_to_framework || (!result.transaction_assessment && ["support", "contradict", "qualify"].includes(item.interpretation.stance)));
      if (!canonical) link(node, item.interpretation.stance, item.interpretation.rationale);
    }
  }
  const report = result.evidence_synthesis;
  for (const context of report?.nodes ?? []) {
    const node = add(context.citation, context.source_title);
    aliases.set(context.id, node.id);
    if (!canonical) addUnique(node.lanes, laneNames[context.lane] ? context.lane : "unresolved");
    if (context.record_id) addUnique(node.recordIds, context.record_id);
    node.contexts.push({relationship: context.relationship, reason: context.reason, temporal_status: context.temporal_status,
      details: {...context.details}, limitations: [...context.limitations]});
  }
  for (const edge of report?.edges ?? []) {
    const from = aliases.get(edge.from), to = aliases.get(edge.to);
    if (from && to) addUnique(edges, {...edge, from, to, ...(canonical ? {inferential: false} : {})});
  }
  const transaction = canonical ? undefined : result.transaction_assessment;
  for (const citation of transaction?.citations ?? []) {
    const source = result.inputs.find(item => item.source.source_id === citation.source_id)?.source;
    const node = add(citation, source?.title ?? citation.source_id);
    addUnique(node.lanes, "observed");
  }
  // An evidence-only observation is assignable only when its transaction citations identify one source.
  const transactionNode = (evidenceId: string) => {
    const matches = [...new Set((transaction?.citations ?? []).filter(c => c.evidence_id === evidenceId).map(passageKey))];
    return matches.length === 1 ? nodes.get(matches[0]) : undefined;
  };
  for (const component of transaction?.components ?? []) {
    for (const observation of component.observations) {
      const node = transactionNode(observation.evidence_id);
      if (!node) continue;
      addUnique(node.findings, {label: component.label, status: observation.status, reason: observation.reason});
      node.used = true;
      link(node, `component_${observation.status}`, `${component.label}: ${observation.reason}`);
    }
  }
  for (const connection of transaction?.connections ?? []) {
    const node = transactionNode(connection.evidence_id);
    if (node) {
      if (connection.relationship === "record_itself" && transaction?.record_id) addUnique(node.recordIds, transaction.record_id);
      link(node, connection.relationship, "Recorded transaction connection");
    }
  }
  for (const finding of canonical ? [] : result.practice_assessment?.findings ?? []) {
    const node = add(finding.citation, finding.source_title);
    addUnique(node.lanes, "observed");
    if (finding.record_id) addUnique(node.recordIds, finding.record_id);
    addUnique(node.findings, {label: "Recorded practice", status: finding.status, reason: finding.reason});
    node.contexts.push({relationship: "practice_comparison", reason: finding.reason, limitations: [...finding.limitations]});
    node.used = true;
    link(node, finding.status, finding.reason);
  }
  for (const finding of canonical ? [] : result.deployment_event_findings ?? []) {
    const node = add(finding.citation, finding.citation.source_id);
    addUnique(node.lanes, "observed");
    addUnique(node.findings, {label: "Event finding", status: finding.status, reason: finding.message});
    node.used = true;
    link(node, finding.status, finding.message);
  }
  const components: GraphComponent[] = canonical?.components.map(component => ({id: `component:${component.id}`, text: component.text, outcome: component.outcome})) ?? [];
  if (canonical) {
    for (const citation of canonical.citations) {
      const source = result.inputs.find(item => item.source.source_id === citation.source_id)?.source;
      add(citation, source?.title ?? citation.source_id);
    }
    for (const component of canonical.components) {
      for (const finding of component.findings) {
        for (const citation of finding.citations) {
          if (citation.source_id !== finding.source_id || citation.evidence_id !== finding.evidence_id) continue;
          const source = result.inputs.find(item => item.source.source_id === citation.source_id)?.source;
          const node = add(citation, source?.title ?? citation.source_id);
          addUnique(node.findings, {label: component.text, status: finding.relationship, reason: finding.reason, componentId: component.id});
          node.contexts.push({relationship: finding.admitted ? "admitted_evidence" : "context_or_excluded", reason: finding.reason,
            limitations: [...finding.exclusion_reasons, ...finding.limitations]});
        }
      }
    }
    for (const relation of canonical.evidence_relations) {
      const component = components.find(item => item.id === `component:${relation.component_id}`);
      if (!component) continue;
      for (const citation of relation.citations) {
        if (citation.source_id !== relation.source_id || citation.evidence_id !== relation.evidence_id) continue;
        const source = result.inputs.find(item => item.source.source_id === citation.source_id)?.source;
        const node = add(citation, source?.title ?? citation.source_id);
        const inferential = canonical.processing.status === "assessed" && relation.inferential;
        node.used ||= inferential;
        addUnique(edges, {from: component.id, to: node.id, relationship: relation.relationship, basis: relation.reason, inferential});
      }
    }
    for (const relation of canonical.context_relations ?? []) {
      const passages = [relation.from_citation, relation.to_citation].map(citation => {
        const source = result.inputs.find(item => item.source.source_id === citation.source_id)?.source;
        const node = add(citation, source?.title ?? citation.source_id);
        addUnique(node.contexts, {relationship: relation.relationship, reason: relation.reason, limitations: ["This exact recorded link is context only; it does not establish support or independent corroboration."]});
        return node;
      });
      addUnique(edges, {from: passages[0].id, to: passages[1].id, relationship: relation.relationship, basis: relation.reason, inferential: false});
    }
  }
  const comparisons = (report?.comparisons ?? []).map(comparison => ({...comparison,
    node_ids: [...new Set(comparison.node_ids.map(id => aliases.get(id)).filter((id): id is string => !!id))]}));
  for (const node of nodes.values()) {
    if (canonical) {
      const lanes = sourceLanes.get(node.sourceId || node.inputs[0]?.source.source_id || "");
      node.lanes = lanes?.size === 1 ? [...lanes] : ["unresolved"];
    }
    const source = result.inputs.find(item => item.source.source_id === node.sourceId)?.source;
    const excluded = !!(source?.creation_date && source.creation_date.slice(0, 10) > result.as_of) ||
      (node.inputs.length > 0 && node.inputs.every(item => item.supplied_judgements.temporal_matches === false));
    if (excluded && !canonical) node.used = false;
  }
  return {nodes: [...nodes.values()].sort((a, b) => Number(b.used) - Number(a.used)), edges, comparisons, components};
}

export default function AssessmentGraph({result, onOpen, openSignal = 0}: {result: SuppliedResult; onOpen: (id: string) => void; openSignal?: number}) {
  const [lane, setLane] = useState("both");
  const [componentId, setComponentId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState((!result.transaction_assessment && !result.canonical_assessment) || openSignal > 0);
  const [showContext, setShowContext] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { if (openSignal > 0) setExpanded(true); }, [openSignal]);
  const graph = useMemo(() => unifiedGraph(result), [result]);
  const labels = result.canonical_assessment ? canonicalLaneNames : laneNames;
  const nodes = graph.nodes.filter(node => (showContext || node.used) && (lane === "both" || node.lanes.includes(lane)) && (!componentId || graph.edges.some(edge => edge.from === componentId && edge.to === node.id)));
  const groups = Object.entries(labels).map(([mode, label]) => ({mode, label,
    nodes: nodes.filter(node => (lane === "both" ? node.lanes[0] ?? "unresolved" : lane) === mode)})).filter(group => group.nodes.length);
  const current = graph.nodes.find(node => node.id === selected);
  const contextCount = graph.nodes.filter(node => !node.used).length;
  return <section className="ev-card ev-graph" aria-label="Evidence graph">
    <div className="ev-toolbar"><h3>Evidence graph <Count>{nodes.length} of {graph.nodes.length} passages</Count></h3>
      <button className="ev-button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Hide graph" : "Show graph"}</button>
    </div>
    <div hidden={!expanded}>
      <p className="ev-muted">Evidence used in the assessment appears first. Select a passage to see its findings, exact citations and recorded connections.</p>
      <div className="ev-toolbar"><div className="ev-segments" role="group" aria-label="Evidence graph lane">
        {[["both", "All"], ["formal", "Formal"], ["observed", "Practice"], ["documented", "Documentation"], ...(result.canonical_assessment ? [["unresolved", "Unknown"]] : [])].map(([value, label]) =>
          <button key={value} aria-pressed={lane === value} onClick={() => setLane(value)}>{label}</button>)}
      </div>{contextCount > 0 && <button className="ev-button" aria-pressed={showContext} onClick={() => setShowContext(value => !value)}>{showContext ? "Hide" : "Include"} related context · {contextCount}</button>}</div>
      <div className={`ev-graph-layout${current ? " ev-graph-split" : ""}`}><div className="ev-graph-tree">
        <div className="ev-graph-claim"><span className="ev-kicker">Claim being assessed</span><strong>{result.facet}</strong></div>
        {!!graph.components.length && <section aria-label="Claim components" className="ev-two">{graph.components.map(component => <button key={component.id} className="ev-graph-node" aria-pressed={componentId === component.id} onClick={() => setComponentId(value => value === component.id ? null : component.id)}>
          <strong>{component.text}</strong><span>{component.outcome}</span><small>{componentId === component.id ? "Showing this component · select again to show all" : "Inspect evidence connected to this component"}</small>
        </button>)}</section>}
        {nodes.length ? <div className={`ev-graph-branches ${groups.length === 1 ? "ev-graph-single" : ""}`} style={{"--lane-count": groups.length, "--branch-start": `calc(${50 / groups.length}% - ${12 * (groups.length - 1) / groups.length}px)`} as CSSProperties}>
          {groups.map(group => <section className="ev-graph-branch" key={group.mode}><h4>{group.label} <Count>{group.nodes.length}</Count></h4>
            <div className="ev-graph-nodes">{group.nodes.map(node => <button key={node.id}
              className={`ev-graph-node ${(result.canonical_assessment ? node.used : node.inputs.some(item => item.admitted_to_framework)) ? "" : "ev-graph-retained"}${node.used ? " ev-graph-used" : ""}`}
              aria-pressed={selected === node.id} onClick={() => setSelected(node.id)} aria-label={`Inspect ${node.title}: ${node.citations[0]?.locator ?? node.evidenceId}`}>
              <strong>{node.recordIds.length ? `${node.recordIds.join(", ")} · ` : ""}{node.title}</strong>
              <span>{node.used ? "Used in assessment" : "Related context · not used in conclusion"}</span>
              {node.findings.map((finding, i) => <span key={i}>{finding.label}: {humanize(finding.status)}</span>)}
              {!node.findings.length && (result.canonical_assessment ? <span>{labels[node.lanes[0]]}</span> : node.inputs.map(item => <span key={item.input_id}>{humanize(item.interpretation.mode)} · {item.interpretation.stance}</span>))}
              <small>{result.canonical_assessment ? (node.used ? "Validated relation used in assessment" : "Context link only · not inferential") : node.inputs.some(item => item.admitted_to_framework) ? "Included in framework scoring" : "Not scored · retained for review"}</small>
              <span className="ev-preview">{quotePreview(node.citations[0]?.quotation ?? node.inputs[0]?.interpretation.rationale ?? "")}</span>
              <small className="ev-mono">{node.citations[0]?.locator ?? node.evidenceId}</small>
            </button>)}</div></section>)}
        </div> : <p className="ev-muted">No evidence used in this category.{contextCount > 0 ? " Include related context to inspect the remaining retrieved passages." : ""}</p>}
      </div>
      {current && <ConnectedEvidence node={current} graph={graph} result={result} onSelect={setSelected} onOpen={onOpen} onClose={() => setSelected(null)} />}</div>
      {!!graph.comparisons.length && <details><summary>Policy and recorded-role differences <Count>{graph.comparisons.length}</Count></summary>{graph.comparisons.map((comparison, i) => <div className="ev-callout" key={i}><p>{comparison.summary}</p>
        <div className="ev-chips">{comparison.node_ids.map(id => <button className="ev-button" key={id} onClick={() => setSelected(id)}>Inspect {graph.nodes.find(node => node.id === id)?.recordIds[0] ?? "passage"}</button>)}</div></div>)}</details>}
      <details className="ev-graph-guide"><summary>How to read this graph</summary><p className="ev-muted">{result.canonical_assessment ? "Categories describe source types, not credibility or support. Component connections labelled supports, contradicts or qualifies are used in the assessment only when their provenance and applicability checks pass. Dashed cards show context or excluded evidence. Exact record references organise evidence; they do not themselves establish support or independent corroboration." : "Connections group interpreted evidence under the claim. Dashed cards are retained without a score; their findings may still inform the component assessment. Context links do not establish support, independence or authority."}</p></details>
      {result.evidence_synthesis && <details><summary>Context search coverage and remaining questions</summary><div className="ev-coverage">
        <p>{result.evidence_synthesis.summary}</p><p className="ev-muted">{result.evidence_synthesis.future_evidence_excluded} later-dated passages or records excluded for this assessment date.</p>
        {!!result.evidence_synthesis.questions.length && <><h4>Questions still open</h4><ul className="ev-checks">{result.evidence_synthesis.questions.map(question => <li key={question}>{question}</li>)}</ul></>}
        <p className="ev-muted">{result.evidence_synthesis.notice}</p></div></details>}
    </div>
  </section>;
}
