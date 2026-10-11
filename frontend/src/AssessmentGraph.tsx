import { useState, type CSSProperties } from "react";
import type { SuppliedResult } from "./suppliedAssessmentContract";
import { humanize } from "./EvidenceUI";

type Input = SuppliedResult["inputs"][number];
export function graphInputs(result: SuppliedResult, lane: string) {
  return result.inputs.filter(item => lane === "both" || item.interpretation.mode === lane);
}
export function evidenceWeight(result: SuppliedResult, item: Input) {
  const edge = result.assessment.evidence.find(value => value.edge_id === item.edge_id);
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
export default function AssessmentGraph({result, onOpen}: {result: SuppliedResult; onOpen: (id: string) => void}) {
  const [lane, setLane] = useState("both");
  const [expanded, setExpanded] = useState(true);
  const inputs = graphInputs(result, lane);
  const groups = graphLanes(result, lane);
  return <section className="ev-card ev-graph" aria-label="Evidence graph">
    <div className="ev-toolbar"><h3>Evidence graph · {inputs.length} of {result.inputs.length} inputs</h3>
      <button className="ev-button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Hide graph" : "Show graph"}</button>
    </div>
    <div hidden={!expanded}>
      <div className="ev-toolbar"><p className="ev-muted">Select a passage to inspect its exact citations and reasoning.</p>
        <div className="ev-segments" role="group" aria-label="Evidence graph lane">{[["formal", "Formal"], ["observed", "Practice"], ["both", "Both"]].map(([value, label]) =>
          <button key={value} aria-pressed={lane === value} onClick={() => setLane(value)}>{label}</button>)}</div>
      </div>
      {inputs.length ? <div className="ev-graph-tree">
        <div className="ev-graph-claim"><span className="ev-kicker">Claim being assessed</span><strong>{result.facet}</strong></div>
        <div className={`ev-graph-branches ${groups.length === 1 ? "ev-graph-single" : ""}`} style={{"--lane-count": groups.length, "--branch-start": `calc(${50 / groups.length}% - ${12 * (groups.length - 1) / groups.length}px)`} as CSSProperties}>
          {groups.map(group => <section className="ev-graph-branch" key={group.mode}>
            <h4>{group.label} · {group.items.length}</h4>
            <div className="ev-graph-nodes">{group.items.map(item => <button
              key={item.input_id} className={`ev-graph-node ${item.admitted_to_framework ? "" : "ev-graph-retained"}`}
              onClick={() => onOpen(item.input_id)} aria-label={`Inspect ${item.source.title}: ${passageLabel(item)}`}>
              <strong>{item.source.title}</strong>
              <span>{humanize(item.interpretation.mode)} · {item.interpretation.stance}</span>
              <small>{evidenceWeight(result, item)}</small>
              <span className="ev-preview">{item.interpretation.citations[0]?.quotation ?? item.interpretation.rationale}</span>
              <small className="ev-mono">{passageLabel(item)}</small>
            </button>)}</div>
          </section>)}
        </div>
      </div> : <p className="ev-muted">No assessment inputs in this lane.</p>}
      <p className="ev-muted">Connections group interpreted evidence under the claim. Dashed cards are retained without a score; they do not establish the verdict. Source ownership and actor authority are not inferred.</p>
    </div>
  </section>;
}
