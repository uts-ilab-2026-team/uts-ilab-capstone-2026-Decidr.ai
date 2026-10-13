import { useEffect, useRef } from "react";
import type { SuppliedResult } from "./suppliedAssessmentContract";
import type { GraphComponent, GraphEdge, GraphNode } from "./AssessmentGraph";
import { Count, MarkdownLite, RecordQuote, humanize } from "./EvidenceUI";

type Props = {node: GraphNode; graph: {nodes: GraphNode[]; edges: GraphEdge[]; components?: GraphComponent[]}; result: SuppliedResult;
  onSelect: (id: string) => void; onOpen: (inputId: string) => void; onClose: () => void};

// The unified graph owns navigation; this panel only inspects the selected passage.
export default function ConnectedEvidence({node, graph, result, onSelect, onOpen, onClose}: Props) {
  const detail = useRef<HTMLElement>(null);
  useEffect(() => { detail.current?.scrollIntoView({block: "nearest"}); detail.current?.focus({preventScroll: true}); }, [node.id]);
  const links = graph.edges.filter(edge => edge.from === node.id || edge.to === node.id);
  return <section ref={detail} tabIndex={-1} className="ev-card" aria-label="Selected evidence passage" aria-live="polite">
    <div className="ev-toolbar"><h4>{node.title}</h4><button className="ev-button" onClick={onClose}>Close passage</button></div>
    <p>{node.used ? "This passage was used in the assessment. Each finding and any scoring limits are shown below." : "This passage is related context. It did not establish the conclusion."}</p>
    {node.findings.map((finding, i) => <p key={i}><strong>{finding.label}: {humanize(finding.status)}</strong><br/>{finding.reason}</p>)}
    {node.inputs.map(item => {
      if (result.canonical_assessment) return <p key={item.input_id}><button className="ev-button" onClick={() => onOpen(item.input_id)}>Inspect assessment reasoning and source</button></p>;
      const score = (result.credibility_assessment ?? result.assessment).evidence.find(edge => edge.edge_id === item.edge_id);
      return <div key={item.input_id}><p><strong>{humanize(item.interpretation.mode)} · {item.interpretation.stance}</strong><br/>{item.interpretation.rationale}</p>
        <p>{item.admitted_to_framework ? `Framework score: ${score?.materiality_score?.toFixed(2) ?? "not available"}` : "Not admitted to framework scoring."}</p>
        {!!item.reasons.length && <ul>{item.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
        <button className="ev-button" onClick={() => onOpen(item.input_id)}>Inspect assessment reasoning and scoring checks</button>
      </div>;
    })}
    <h4>Exact citations <Count>{node.citations.length}</Count></h4>
    {node.citations.map((citation, i) => <div key={i}><blockquote>{RecordQuote({ text: citation.quotation }) ?? <MarkdownLite text={citation.quotation} />}</blockquote>
      <p className="ev-mono">{citation.evidence_id} · {citation.source_id} · {citation.locator} · characters {citation.start}–{citation.end}</p></div>)}
    {!node.citations.length && <p>No passage quotation was saved for this input.</p>}
    {node.contexts.map((context, i) => <details key={i}><summary>{humanize(context.relationship)}{context.temporal_status ? ` · ${humanize(context.temporal_status)}` : ""}</summary>
      <p>{context.reason}</p>{context.details && Object.entries(context.details).map(([key, value]) => <p key={key}>{humanize(key)}: {typeof value === "string" ? value : JSON.stringify(value)}</p>)}
      <ul>{context.limitations.map((line, j) => <li key={j}>{line}</li>)}</ul>
    </details>)}
    {!!links.length && <><h4>Recorded connections</h4>{links.map((edge, i) => {
      const other = edge.from === node.id ? edge.to : edge.from;
      const target = graph.nodes.find(item => item.id === other);
      const component = graph.components?.find(item => item.id === other);
      return <p key={i}>{humanize(edge.relationship)} → {target ? <button className="ev-button" onClick={() => onSelect(target.id)}>{target.recordIds[0] ?? target.title}</button> : component?.text ?? "Submitted claim"}
        {edge.inferential !== undefined && <small> · {edge.inferential ? "Used for inference" : "Context connection only"}</small>}<br/><small>{edge.basis}</small></p>;
    })}</>}
  </section>;
}
