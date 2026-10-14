import { useState } from "react";
import { documents as orgDocuments } from "./orgGraph";
import { Badge, ConfidenceBand, ConfidenceRing, Count, MarkdownLite, RecordQuote, humanize, outcomeTone, relationTone } from "./EvidenceUI";

// The result of the graph engine (POST /api/assessments/automatic and /api/corpus/assess).
// A claim is split into parts ("facets"); each part is scored on the organisation graph from the
// passages the model read, and the parts are combined into one verdict.

export interface GraphPassage {
  quote: string; stance: string; applicable: boolean; material: boolean; score: number | null;
  limitations: string[]; trace: string[];
}
export interface GraphEvidence {
  source: string; title: string; mode: string; source_class: string; lifecycle_status: string;
  retrieved_via: string[]; material: boolean; best_score: number | null; passages: GraphPassage[];
}
export interface GraphFacet {
  facet: string; predicate: string; summary: string; outcome: string; confidence: string;
  confidence_score?: number; decisive: boolean; evidence: GraphEvidence[];
}
export interface GraphResult {
  claim: string; claim_text: string; facet: string; as_of: string; status: string;
  overall_outcome: string; confidence: string; confidence_score?: number; target: string | null; split_status: string;
  facets: GraphFacet[]; rules_applied: string[];
  retrieval: {
    graph_guided?: boolean; processes_matched?: string[]; governed_docs?: string[]; related_docs?: string[];
    counts?: Record<string, number>; lanes?: Record<string, number>;
  };
  passages_considered: number; findings_count: number; notes: string[];
  persisted?: boolean;
}

export function isGraphResult(value: unknown): value is GraphResult {
  const result = value as Partial<GraphResult> | null;
  return !!result && typeof result === "object" && Array.isArray(result.facets) &&
    typeof result.overall_outcome === "string" && typeof result.confidence === "string";
}

// The engine scores how strongly the evidence backs a Supported or Contradicted outcome (0-1).
// Contested and Insufficient evidence carry no score by design, and older results have none.
// The band changes at 0.45 and 0.75, so the number is rounded down: 0.749 shows as 74 beside
// "Moderate", never as 75, which would read as the start of the higher band.
export function scoreOutOf100(outcome: string, score: number | undefined): number | null {
  const scored = outcome === "Supported" || outcome === "Contradicted";
  return scored && typeof score === "number" && Number.isFinite(score) ? Math.floor(Math.max(0, Math.min(1, score)) * 100 + 1e-9) : null;
}
const STANCE: Record<string, string> = { support: "Supports", contradict: "Contradicts", qualify: "Qualifies", context: "Context only", unresolved: "Unresolved" };
const RETRIEVED_VIA: Record<string, string> = { graph_governed: "Governing document", graph_related: "Related document", keyword: "Keyword search", semantic: "Meaning search", hybrid: "Keyword + meaning search" };
// Combiner rules arrive as short machine phrases ("any facet Contested -> Contested").
export const ruleText = (rule: string) =>
  rule === "CLAIM_COMBINER_V1_CONJUNCTIVE" ? "Every counted part of the claim has to hold for the claim to be supported."
    : rule.replace(/\bfacets\b/g, "parts").replace(/\bfacet\b/g, "part").replace(/\s*->\s*/g, " → ").replace(/^./, letter => letter.toUpperCase());

const out100 = (value: number) => Math.floor(Math.max(0, Math.min(1, value)) * 100 + 1e-9);

function passageUse(passage: GraphPassage): string {
  if (!passage.applicable) return "Not applied · kept for reference";
  const weight = passage.score === null ? "" : ` · weight ${out100(passage.score)}/100`;
  return `${passage.material ? "Used in assessment" : "Weighted down"}${weight}`;
}

// ── Why a passage counts ─────────────────────────────────────────────────────
// The engine explains each passage in machine-style trace lines ("Status: current lifecycle
// multiplier=1.00; approval=1.00."). These are read into plain checks; any line not recognised
// is still shown, and the exact trace stays available underneath.

export interface PassageCheck { tone: "ok" | "warn" | "info"; text: string }
export interface WeightBreakdown { fit: number; status: number; authority: number; weight: number }

const sentence = (text: string) => text.trim().replace(/^./, letter => letter.toUpperCase()).replace(/\.?$/, "");
const percent = (value: number) => `${Math.round(value * 100)}%`;

export function explainPassage(passage: GraphPassage): { checks: PassageCheck[]; weight: WeightBreakdown | null } {
  const checks: PassageCheck[] = [];
  let weight: WeightBreakdown | null = null;
  for (const line of passage.trace) {
    let match;
    if ((match = line.match(/^Source: (\S+) authority=(\d+(?:\.\d+)?)\.\s*(.*)$/))) {
      const authority = Number(match[2]);
      checks.push({ tone: authority >= 0.8 ? "ok" : "info", text: `${sentence(humanize(match[1]))} · authority ${out100(authority)}/100` });
      if (match[3] && !/No person-level authority resolution was required/i.test(match[3])) checks.push({ tone: "info", text: sentence(match[3]) });
    } else if ((match = line.match(/^Status: (\S+) lifecycle multiplier=(\d+(?:\.\d+)?); approval=(\d+(?:\.\d+)?)\.?$/))) {
      const lifecycle = Number(match[2]), approval = Number(match[3]);
      checks.push({ tone: lifecycle >= 1 ? "ok" : "warn", text: `${sentence(humanize(match[1]))} version${lifecycle < 1 ? `, counted at ${percent(lifecycle)}` : ""}` });
      checks.push(approval >= 1 ? { tone: "ok", text: "Formally approved" } : { tone: "warn", text: `Approval not confirmed, counted at ${percent(approval)}` });
    } else if ((match = line.match(/^Date: (.*) value=(\d+(?:\.\d+)?)\.?$/))) {
      const value = Number(match[2]);
      checks.push(value >= 1 ? { tone: "ok", text: "In force on the assessment date" }
        : { tone: "warn", text: `${sentence(match[1])}, counted at ${percent(value)}` });
    } else if ((match = line.match(/^Materiality: weighted dimensions (\d+(?:\.\d+)?) × lifecycle (\d+(?:\.\d+)?) × authority (\d+(?:\.\d+)?) = (\d+(?:\.\d+)?)/))) {
      weight = { fit: Number(match[1]), status: Number(match[2]), authority: Number(match[3]), weight: Number(match[4]) };
    } else if ((match = line.match(/^Applicability gate failed: (.*?)\s*Evidence retained but not scored\.?$/))) {
      checks.push({ tone: "warn", text: `Not applied: ${sentence(match[1]).replace(/^./, letter => letter.toLowerCase())}` });
    } else if (!/^(Supplied independence judgement|Independence)/.test(line)) {
      checks.push({ tone: "info", text: sentence(line) });
    }
  }
  const limits = passage.limitations.map(limit => limit.trim());
  const gated = passage.trace.some(line => line.startsWith("Applicability gate failed"));
  if (limits.some(limit => /No independent source corroborates/i.test(limit)))
    checks.push({ tone: "warn", text: "Only source saying this, so it gets no extra credit for agreement" });
  else if (limits.some(limit => /Independence is unverified/i.test(limit)))
    checks.push({ tone: "warn", text: "Independence from the other sources is not verified" });
  if (limits.some(limit => /duplicate source exists/i.test(limit)))
    checks.push({ tone: "info", text: "A duplicate copy of this document exists and is counted once" });
  for (const limit of limits) {
    if (/No independent source corroborates|Independence is unverified|duplicate source exists/i.test(limit)) continue;
    if (gated && passage.trace.some(line => line.includes(limit))) continue; // already shown as "Not applied"
    checks.push({ tone: "warn", text: sentence(limit) });
  }
  return { checks, weight };
}

const CHECK_MARK: Record<PassageCheck["tone"], { glyph: string; label: string }> = {
  ok: { glyph: "✓", label: "Passed" }, warn: { glyph: "!", label: "Caveat" }, info: { glyph: "i", label: "Note" },
};

function WhyItCounts({ passage }: { passage: GraphPassage }) {
  const { checks, weight } = explainPassage(passage);
  if (!checks.length && !weight && !passage.limitations.length && !passage.trace.length) return null;
  const passed = checks.filter(check => check.tone === "ok").length, caveats = checks.filter(check => check.tone === "warn").length;
  return <details className="ev-why">
    <summary>{passage.applicable ? "Why this passage counts" : "Why this passage was not applied"}
      <span className="ev-why-tally">{passed > 0 && <span className="ev-why-ok">✓ {passed}</span>}{caveats > 0 && <span className="ev-why-warn">! {caveats}</span>}</span></summary>
    {weight && <div className="ev-why-weight" aria-label={`Weight ${out100(weight.weight)} out of 100`}>
      <strong>Weight {out100(weight.weight)}/100</strong>
      {([["Evidence fit", weight.fit], ["Status", weight.status], ["Authority", weight.authority]] as const).map(([label, value], i) => <span key={label} className="ev-why-factor">
        {i > 0 && <span className="ev-why-times" aria-hidden="true">×</span>}{label}<span className="ev-why-bar" aria-hidden="true"><i style={{ width: `${out100(value)}%` }} /></span><b>{out100(value)}</b>
      </span>)}
    </div>}
    <ul className="ev-why-list">{checks.map((check, i) => <li key={i} className={`ev-why-${check.tone}`}>
      <span className="ev-why-mark" role="img" aria-label={CHECK_MARK[check.tone].label}>{CHECK_MARK[check.tone].glyph}</span>{check.text}</li>)}</ul>
    <details className="ev-why-raw"><summary>Technical trace</summary>
      <ul>{[...passage.limitations, ...passage.trace].map((line, i) => <li key={i}>{line}</li>)}</ul>
    </details>
  </details>;
}

function PassageCard({ passage }: { passage: GraphPassage }) {
  const record = passage.quote.trimStart().startsWith("{");
  return <section className="ev-finding">
    <div className="ev-chips" style={{ margin: "0 0 8px" }}>
      <Badge tone={relationTone(passage.stance)}>{STANCE[passage.stance] ?? humanize(passage.stance)}</Badge>
      <span className="ev-muted" style={{ display: "inline" }}>{passageUse(passage)}</span>
    </div>
    <div className="ev-cite"><div className="ev-cite-quote">{record ? <RecordQuote text={passage.quote} /> : <MarkdownLite text={passage.quote} />}</div></div>
    <WhyItCounts passage={passage} />
  </section>;
}

function SourceBlock({ evidence }: { evidence: GraphEvidence }) {
  return <section className="ev-graph-source">
    <h4>{evidence.title} <span className="ev-mono ev-muted" style={{ display: "inline" }}>{evidence.source}</span></h4>
    <div className="ev-chips" style={{ margin: "4px 0 0" }}>
      <Badge>{evidence.mode === "formal" ? "Formal document" : evidence.mode === "observed" ? "Observed practice" : humanize(evidence.mode)}</Badge>
      <Badge>{humanize(evidence.source_class)}</Badge>
      <Badge tone={evidence.lifecycle_status === "current" ? "neutral" : "amber"}>{humanize(evidence.lifecycle_status)}</Badge>
      {evidence.retrieved_via.map(via => <Badge key={via}>Found by: {RETRIEVED_VIA[via] ?? humanize(via)}</Badge>)}
    </div>
    {evidence.passages.map((passage, i) => <PassageCard key={i} passage={passage} />)}
  </section>;
}

// ── Evidence map ─────────────────────────────────────────────────────────────
// The same findings drawn as a graph: claim → its parts → the sources read for each part →
// the process each source governs (from the organisation graph).

export interface MapNode { id: string; column: number; title: string; sub: string; tone: string; muted?: boolean; source?: string }
export interface MapEdge { from: string; to: string; tone: string; dashed?: boolean; label: string }

// What one source says about one part: the strongest stance among its applicable passages.
export function sourceStance(evidence: GraphEvidence[]): { label: string; tone: string; applied: boolean } {
  const stances = new Set(evidence.flatMap(item => item.passages.filter(passage => passage.applicable).map(passage => passage.stance)));
  if (stances.size === 0) return { label: "Not applied", tone: "neutral", applied: false };
  const stance = ["contradict", "support", "qualify"].find(value => stances.has(value)) ?? [...stances][0];
  return { label: STANCE[stance] ?? humanize(stance), tone: relationTone(stance), applied: true };
}

export function evidenceMap(result: GraphResult): { nodes: MapNode[]; edges: MapEdge[] } {
  const known = new Map(orgDocuments().map(document => [document.shortId, document]));
  const nodes: MapNode[] = [{ id: "claim", column: 0, title: result.claim_text, sub: result.overall_outcome, tone: outcomeTone(result.overall_outcome) }];
  const edges: MapEdge[] = [];
  const has = (id: string) => nodes.some(node => node.id === id);
  for (const facet of result.facets) {
    const part = `part:${facet.facet}`;
    nodes.push({ id: part, column: 1, title: facet.summary || facet.facet, sub: facet.decisive ? facet.outcome : `${facet.outcome} · not counted`, tone: outcomeTone(facet.outcome), muted: !facet.decisive });
    edges.push({ from: "claim", to: part, tone: outcomeTone(facet.outcome), dashed: !facet.decisive, label: facet.outcome });
    for (const code of new Set(facet.evidence.map(item => item.source))) {
      const items = facet.evidence.filter(item => item.source === code);
      const source = `source:${code}`;
      if (!has(source)) {
        nodes.push({ id: source, column: 2, title: items[0].title, sub: `${code} · ${humanize(items[0].lifecycle_status)}`, tone: "neutral", muted: items[0].lifecycle_status !== "current", source: code });
        for (const process of known.get(code)?.governs ?? []) {
          const id = `process:${process.id}`;
          if (!has(id)) nodes.push({ id, column: 3, title: process.label, sub: process.attributes.code ? `Process ${process.attributes.code}` : "Process", tone: "neutral" });
          edges.push({ from: source, to: id, tone: "neutral", label: "Governs" });
        }
      }
      const stance = sourceStance(items);
      edges.push({ from: part, to: source, tone: stance.tone, dashed: !stance.applied, label: stance.label });
    }
  }
  return { nodes, edges };
}

const MAP_COLUMNS = ["Claim", "Parts of the claim", "Sources read", "Process governed"];
const NODE_W = 232, NODE_H = 68, ROW_GAP = 14, COLUMN_STEP = 269, HEAD = 26;

function EvidenceMap({ result }: { result: GraphResult }) {
  const { nodes, edges } = evidenceMap(result);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const columns = MAP_COLUMNS.map((_, column) => nodes.filter(node => node.column === column));
  const height = Math.max(...columns.map(column => column.length)) * (NODE_H + ROW_GAP) - ROW_GAP;
  const place = new Map<string, { x: number; y: number }>();
  columns.forEach((column, index) => {
    const top = (height - (column.length * (NODE_H + ROW_GAP) - ROW_GAP)) / 2;
    column.forEach((node, row) => place.set(node.id, { x: index * COLUMN_STEP, y: HEAD + top + row * (NODE_H + ROW_GAP) }));
  });
  const focus = hovered ?? (selected ? `source:${selected}` : null);
  const linked = new Set(focus ? [focus, ...edges.flatMap(edge => edge.from === focus ? [edge.to] : edge.to === focus ? [edge.from] : [])] : []);
  const faded = (id: string) => !!focus && !linked.has(id);
  const chosen = selected ? result.facets.map(facet => ({ facet, evidence: facet.evidence.filter(item => item.source === selected) })).filter(group => group.evidence.length > 0) : [];
  return <section className="ev-card" aria-label="Evidence map"><h3>Evidence map</h3>
    <p className="ev-muted">How the verdict traces back to the documents. Select a source to read the passages taken from it.</p>
    <div className="ev-map-legend" aria-hidden="true">{[["green", "Supports"], ["red", "Contradicts"], ["amber", "Qualifies"], ["neutral", "Context, or governs a process"], ["off", "Read but not applied"]].map(([tone, label]) =>
      <span key={label}><i className={`ev-map-key ev-map-${tone}`} />{label}</span>)}</div>
    <div className="ev-map"><div className="ev-map-canvas" style={{ width: COLUMN_STEP * 3 + NODE_W, height: HEAD + height }}>
      {MAP_COLUMNS.map((label, column) => columns[column].length > 0 && <span key={label} className="ev-map-head" style={{ left: column * COLUMN_STEP }}>{label}</span>)}
      <svg width={COLUMN_STEP * 3 + NODE_W} height={HEAD + height} aria-hidden="true">{edges.map((edge, i) => {
        const from = place.get(edge.from)!, to = place.get(edge.to)!;
        const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2, x2 = to.x, y2 = to.y + NODE_H / 2, bend = (x2 - x1) / 2;
        return <path key={i} d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`}
          className={`ev-map-edge ev-map-${edge.dashed ? "off" : edge.tone}${focus && !(linked.has(edge.from) && linked.has(edge.to) && (edge.from === focus || edge.to === focus)) ? " ev-map-faded" : ""}`} />;
      })}</svg>
      {nodes.map(node => {
        const position = place.get(node.id)!;
        const className = `ev-map-node ev-map-node-${node.tone}${node.muted ? " ev-map-muted" : ""}${faded(node.id) ? " ev-map-faded" : ""}${node.source && node.source === selected ? " ev-map-selected" : ""}`;
        const style = { left: position.x, top: position.y, width: NODE_W, height: NODE_H };
        const inner = <><span className="ev-map-title">{node.title}</span><span className="ev-map-sub">{node.sub}</span></>;
        const hover = { onMouseEnter: () => setHovered(node.id), onMouseLeave: () => setHovered(null) };
        return node.source
          ? <button type="button" key={node.id} className={className} style={style} aria-pressed={node.source === selected} title={node.title} onClick={() => setSelected(node.source === selected ? null : node.source!)} {...hover}>{inner}</button>
          : <div key={node.id} className={className} style={style} title={node.title} {...hover}>{inner}</div>;
      })}
    </div></div>
    {chosen.length > 0 && <section className="ev-map-detail" aria-label="Passages from the selected source">
      {chosen.map(({ facet, evidence }) => <div key={facet.facet}>
        <p className="ev-kicker" style={{ margin: "14px 0 0" }}>For: {facet.summary || facet.facet}</p>
        {evidence.map(item => <SourceBlock key={`${item.source}:${item.mode}`} evidence={item} />)}
      </div>)}
    </section>}
  </section>;
}

export function GraphResultView({ result }: { result: GraphResult }) {
  const counted = result.facets.filter(facet => facet.decisive);
  const sources = new Set(result.facets.flatMap(facet => facet.evidence.map(evidence => evidence.source)));
  const retrieval = result.retrieval ?? {};
  const score = scoreOutOf100(result.overall_outcome, result.confidence_score);
  return <section className="ev-workspace" aria-label="Assessment result">
    <article className="ev-card"><span className="ev-kicker">Automatic result · Graph assessment</span>
      <p className="ev-claim">{result.claim_text}</p>
      {result.facet !== result.claim_text && <p className="ev-muted">Scope supplied: {result.facet}</p>}
      <div className="ev-chips">{result.target && <Badge>Target: {humanize(result.target)}</Badge>}<Badge>As of: {result.as_of}</Badge><Badge>{result.persisted ? "Saved snapshot" : "Not saved"}</Badge></div>
    </article>
    <section className="ev-card" aria-label="Credibility assessment"><h3>Assessment</h3>
      <section className={`ev-verdict-panel ev-verdict-${outcomeTone(result.overall_outcome)}`} aria-label="Final claim assessment">
        <div className="ev-verdict-body"><h2>{result.overall_outcome}</h2>
          <p>{result.facets.length === 0 ? "The claim could not be broken into parts to assess."
            : `${counted.length} ${counted.length === 1 ? "part" : "parts"} of the claim assessed against ${result.passages_considered} ${result.passages_considered === 1 ? "passage" : "passages"} from ${sources.size} ${sources.size === 1 ? "source" : "sources"}.`}</p></div>
        {score === null ? <ConfidenceBand label={result.confidence} tone={outcomeTone(result.overall_outcome)} />
          : <ConfidenceRing score={score} label={result.confidence} tone={outcomeTone(result.overall_outcome)} />}
      </section>
      <p className="ev-muted">{score === null
        ? (result.overall_outcome === "Supported" || result.overall_outcome === "Contradicted" ? "Confidence is a band from the scoring rules, not a probability that the claim is true. The claim takes the lowest band among its counted parts."
          : "No score is given for this outcome, because the evidence does not point confidently in one direction. The band comes from the scoring rules and is not a probability that the claim is true.")
        : "The score is how strongly the evidence backs this outcome, out of 100. It is not a probability that the claim is true."}</p>
      {result.notes.length > 0 && <div className="ev-notice" role="status"><strong>Processing notes</strong><ul>{result.notes.map((note, i) => <li key={i}>{note}</li>)}</ul></div>}
    </section>
    {result.facets.some(facet => facet.evidence.length > 0) && <EvidenceMap result={result} />}
    {result.facets.length > 0 && <section className="ev-card"><h3>Findings and evidence</h3>
      {result.facets.map(facet => <details key={facet.facet} className="ev-finding-group">
        <summary>{facet.summary || facet.facet} <Badge tone={outcomeTone(facet.outcome)}>{facet.outcome}</Badge> <Count>{facet.evidence.reduce((n, evidence) => n + evidence.passages.length, 0)}</Count></summary>
        <p className="ev-muted">{facet.confidence}{facet.decisive ? "" : " · flagged as an uncertain split, so it is shown but not counted"}</p>
        {facet.evidence.length ? facet.evidence.map(evidence => <SourceBlock key={`${evidence.source}:${evidence.mode}`} evidence={evidence} />)
          : <p>No passage that was read addresses this part of the claim.</p>}
      </details>)}
    </section>}
    <details className="ev-card"><summary>How this was decided</summary>
      <ul>{result.rules_applied.map((rule, i) => <li key={i}>{ruleText(rule)}</li>)}</ul>
      <dl className="ev-fields">
        <div><dt>Claim split</dt><dd>{humanize(result.split_status)}</dd></div>
        <div><dt>Passages read</dt><dd>{result.passages_considered}</dd></div>
        <div><dt>Findings</dt><dd>{result.findings_count}</dd></div>
        <div><dt>Processes matched</dt><dd>{retrieval.processes_matched?.length ? retrieval.processes_matched.join(", ") : "None"}</dd></div>
        <div><dt>Governing documents</dt><dd>{retrieval.governed_docs?.length ? retrieval.governed_docs.join(", ") : "None"}</dd></div>
        {!!retrieval.related_docs?.length && <div><dt>Related documents followed</dt><dd>{retrieval.related_docs.join(", ")}</dd></div>}
        {retrieval.counts && <div><dt>Found by</dt><dd>{Object.entries(retrieval.counts).map(([via, n]) => `${RETRIEVED_VIA[via] ?? humanize(via)}: ${n}`).join(" · ")}</dd></div>}
        {retrieval.lanes && <div><dt>Passages by lane</dt><dd>{Object.entries(retrieval.lanes).map(([lane, n]) => `${humanize(lane)}: ${n}`).join(" · ")}</dd></div>}
      </dl>
      <p className="ev-muted">The model only reads passages and marks what each one says about the claim. The verdict and confidence come from fixed scoring rules on the organisation graph.</p>
    </details>
  </section>;
}
