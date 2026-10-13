import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Count, humanize } from "./EvidenceUI";
import {
  KIND_LABELS, describeDocument, edges, getNode, graphVersion, isActive, isLinked, neighbourIds, neighbours, nodes,
  nodesOfKind, processCards, roleTree, shortSourceId,
  type NodeKind, type OrgNode, type RoleNode,
} from "./orgGraph";
import "./evidence.css";

type Select = (id: string) => void;

// Functions are identified by a labelled chip; the colour is a secondary cue only.
// Fixed order from the validated categorical palette, assigned by sorted function name.
const FUNCTION_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const functionColour = (func: OrgNode | undefined) => {
  const index = func ? nodesOfKind("function").findIndex(item => item.id === func.id) : -1;
  return index < 0 ? "#9ca3af" : FUNCTION_COLOURS[index % FUNCTION_COLOURS.length];
};
const statusTone = (status: string) => status === "current" || status === "approved" ? "green" : status === "draft" ? "amber" : "neutral";

function FunctionChip({ func }: { func: OrgNode | undefined }) {
  if (!func) return null;
  return <span className="org-func"><span className="org-func-dot" style={{ background: functionColour(func) }} />{func.label}</span>;
}

function Holders({ holders }: { holders: OrgNode[] }) {
  if (!holders.length) return <span className="org-holder org-vacant">No holder recorded</span>;
  return <>{holders.map(person => <span key={person.id} className={`org-holder${isActive(person) ? "" : " org-inactive"}`}>
    {person.label}{!isActive(person) && <em> · {person.attributes.status ?? "inactive"}</em>}
  </span>)}</>;
}

// ── Org chart ────────────────────────────────────────────────────────────────

function RoleBox({ node, selected, onSelect }: { node: RoleNode; selected: string | null; onSelect: Select }) {
  return <button type="button" className="org-box" aria-pressed={selected === node.role.id} onClick={() => onSelect(node.role.id)}
    style={{ borderTopColor: functionColour(node.func) }}>
    <strong>{node.role.label}</strong>
    <Holders holders={node.holders} />
    <FunctionChip func={node.func} />
  </button>;
}

function Branch({ node, selected, onSelect }: { node: RoleNode; selected: string | null; onSelect: Select }) {
  // A manager whose reports are all individual roles lists them in a column, which keeps
  // the chart narrow enough to read without scrolling sideways.
  const stacked = node.reports.length > 0 && node.reports.every(report => report.reports.length === 0);
  return <div className="org-branch">
    <RoleBox node={node} selected={selected} onSelect={onSelect} />
    {node.reports.length > 0 && (stacked
      ? <div className="org-stack">{node.reports.map(report => <RoleBox key={report.role.id} node={report} selected={selected} onSelect={onSelect} />)}</div>
      : <div className="org-children">{node.reports.map(report => <Branch key={report.role.id} node={report} selected={selected} onSelect={onSelect} />)}</div>)}
  </div>;
}

export function OrgChart({ selected, onSelect }: { selected: string | null; onSelect: Select }) {
  const roots = useMemo(roleTree, []);
  const chart = useRef<HTMLElement>(null);
  // With the detail panel open the chart is narrower than the tree; keep the chosen role in view.
  useEffect(() => {
    chart.current?.querySelector('.org-box[aria-pressed="true"]')?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [selected]);
  return <section ref={chart} className="org-chart" aria-label="Organisation chart">
    <div className="org-legend">{nodesOfKind("function").map(func => <FunctionChip key={func.id} func={func} />)}</div>
    <div className="org-tree">{roots.map(root => <Branch key={root.role.id} node={root} selected={selected} onSelect={onSelect} />)}</div>
  </section>;
}

// ── Process map ──────────────────────────────────────────────────────────────

export function ProcessMap({ selected, onSelect }: { selected: string | null; onSelect: Select }) {
  const cards = useMemo(processCards, []);
  return <section className="org-processes" aria-label="Processes">
    {cards.map(card => <article key={card.process.id} className={`ev-card org-process${selected === card.process.id ? " org-selected" : ""}`}>
      <button type="button" className="org-process-head" onClick={() => onSelect(card.process.id)}>
        <Count>{card.process.attributes.code ?? "Process"}</Count>
        <strong>{card.process.label.replace(/^P\d+\s+/, "")}</strong>
      </button>
      <h4>Governed by</h4>
      {card.governedBy.length ? card.governedBy.map(doc => <button type="button" key={doc.id} className="org-row" onClick={() => onSelect(doc.id)}>
        <span className="ev-mono">{describeDocument(doc).shortId}</span>
        <span className="org-row-text">{doc.label.replace(/^[A-Z]+-\d+\s*—\s*/, "")}</span>
        <Badge tone={statusTone(doc.attributes.status ?? "")}>{doc.attributes.status ?? "unknown"}</Badge>
      </button>) : <p className="ev-muted">No governing document recorded.</p>}
      <h4>Roles involved <Count>{card.roles.length}</Count></h4>
      {card.roles.map(({ role, holders }) => <button type="button" key={role.id} className="org-row" onClick={() => onSelect(role.id)}>
        <span className="org-row-text">{role.label}</span>
        <span className="ev-muted" style={{ display: "inline" }}>{holders.map(person => person.label).join(", ") || "no holder recorded"}</span>
      </button>)}
      <h4>Systems these roles use</h4>
      <div className="ev-chips" style={{ marginTop: 6 }}>{card.systems.length
        ? card.systems.map(system => <button type="button" key={system.id} className="org-chip" onClick={() => onSelect(system.id)}>{system.label}</button>)
        : <span className="ev-muted">None recorded.</span>}</div>
    </article>)}
  </section>;
}

// ── Network ──────────────────────────────────────────────────────────────────
// Two layouts of the same graph. "Web" spreads nodes by their connections so teams
// cluster; "Columns" lines them up by type for tracing. Both are computed without
// randomness, so the same graph always draws the same way.

type NetLayout = "web" | "columns";
const NET_WIDTH = 1040;

// Node types are identified by a labelled legend and by each node's own label; the
// colour is a secondary cue. Fixed order from the validated categorical palette.
const KIND_COLOURS: Record<NodeKind, string> = {
  person: "#2a78d6", role: "#eb6834", function: "#1baf7a", process: "#e87ba4", system: "#4a3aa7", document: "#8a8780",
};
const KIND_ORDER: NodeKind[] = ["person", "role", "function", "process", "system", "document"];

function visibleNodes(kinds: Set<NodeKind>, showUnlinked: boolean): OrgNode[] {
  return nodes.filter(node => kinds.has(node.kind) && (node.kind !== "document" || showUnlinked || isLinked(node.id)));
}

// ── Web layout: a force-directed placement run to rest once ──────────────────

const WEB_HEIGHT = 720, WEB_PAD = 46;

interface Point { x: number; y: number }

function webLayout(shown: OrgNode[], links: { source: string; target: string }[]) {
  const linked = shown.filter(node => links.some(link => link.source === node.id || link.target === node.id));
  const loose = shown.filter(node => !linked.includes(node));
  const at = new Map<string, Point>();
  const cx = NET_WIDTH / 2, cy = WEB_HEIGHT / 2;
  // Start on a spiral so the result is repeatable.
  linked.forEach((node, index) => {
    const angle = index * 2.399963, radius = 18 * Math.sqrt(index + 1);
    at.set(node.id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
  });
  const ideal = 0.92 * Math.sqrt(((NET_WIDTH - 2 * WEB_PAD) * (WEB_HEIGHT - 2 * WEB_PAD)) / Math.max(linked.length, 1));
  const pairs = links.filter(link => at.has(link.source) && at.has(link.target));
  for (let step = 0; step < 420; step++) {
    const heat = 34 * (1 - step / 420) + 0.6;
    const move = new Map<string, Point>(linked.map(node => [node.id, { x: 0, y: 0 }]));
    for (let i = 0; i < linked.length; i++) {
      const a = at.get(linked[i].id)!;
      for (let j = i + 1; j < linked.length; j++) {
        const b = at.get(linked[j].id)!;
        let dx = a.x - b.x, dy = a.y - b.y;
        // Labels are wider than they are tall, so push apart more strongly side to side.
        const distance = Math.max(Math.hypot(dx * 0.82, dy * 1.25), 0.01);
        const force = (ideal * ideal) / distance;
        dx = (dx / distance) * force; dy = (dy / distance) * force;
        const ma = move.get(linked[i].id)!, mb = move.get(linked[j].id)!;
        ma.x += dx; ma.y += dy; mb.x -= dx; mb.y -= dy;
      }
    }
    for (const link of pairs) {
      const a = at.get(link.source)!, b = at.get(link.target)!;
      const dx = a.x - b.x, dy = a.y - b.y, distance = Math.max(Math.hypot(dx, dy), 0.01);
      const force = (distance * distance) / ideal;
      const ma = move.get(link.source)!, mb = move.get(link.target)!;
      ma.x -= (dx / distance) * force; ma.y -= (dy / distance) * force;
      mb.x += (dx / distance) * force; mb.y += (dy / distance) * force;
    }
    for (const node of linked) {
      const p = at.get(node.id)!, m = move.get(node.id)!;
      m.x += (cx - p.x) * 0.045; m.y += (cy - p.y) * 0.075; // gentle pull to the middle
      const length = Math.max(Math.hypot(m.x, m.y), 0.01), limited = Math.min(length, heat);
      p.x += (m.x / length) * limited; p.y += (m.y / length) * limited;
    }
  }
  // Nodes were free to spread; now scale the result to fill the canvas, so nothing piles
  // up against an edge.
  const fit = () => {
    const xs = linked.map(node => at.get(node.id)!.x), ys = linked.map(node => at.get(node.id)!.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const left = WEB_PAD + 44, right = NET_WIDTH - WEB_PAD - 44, top = WEB_PAD - 14, bottom = WEB_HEIGHT - WEB_PAD - 8;
    for (const node of linked) {
      const p = at.get(node.id)!;
      p.x = left + ((p.x - minX) / Math.max(maxX - minX, 1)) * (right - left);
      p.y = top + ((p.y - minY) / Math.max(maxY - minY, 1)) * (bottom - top);
    }
  };
  if (linked.length) fit();
  // Each node needs room for its mark and its label; nudge apart any that still collide.
  const box = (node: OrgNode) => {
    const p = at.get(node.id)!, width = Math.max(18, nodeText(node).length * 5.5 + 10);
    return node.kind === "document"
      ? { cx: p.x, cy: p.y, w: width + 8, h: 22 }
      : { cx: p.x, cy: p.y + 8, w: width, h: 34 };
  };
  for (let pass = 0; pass < 140; pass++) {
    let collided = false;
    for (let i = 0; i < linked.length; i++) {
      for (let j = i + 1; j < linked.length; j++) {
        const a = box(linked[i]), b = box(linked[j]);
        const overlapX = (a.w + b.w) / 2 + 3 - Math.abs(a.cx - b.cx), overlapY = (a.h + b.h) / 2 + 2 - Math.abs(a.cy - b.cy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        collided = true;
        const pa = at.get(linked[i].id)!, pb = at.get(linked[j].id)!;
        if (overlapY < overlapX) { const shift = overlapY / 2 * (a.cy <= b.cy ? -1 : 1); pa.y += shift; pb.y -= shift; }
        else { const shift = overlapX / 2 * (a.cx <= b.cx ? -1 : 1); pa.x += shift; pb.x -= shift; }
      }
    }
    for (const node of linked) {
      const p = at.get(node.id)!, half = box(node).w / 2;
      p.x = Math.min(NET_WIDTH - half - 6, Math.max(half + 6, p.x));
      p.y = Math.min(WEB_HEIGHT - 30, Math.max(18, p.y));
    }
    if (!collided) break;
  }
  // Items with no connections sit in a tidy block underneath instead of floating loose.
  const perRow = 7, cell = NET_WIDTH / perRow;
  loose.sort((a, b) => a.label.localeCompare(b.label)).forEach((node, index) =>
    at.set(node.id, { x: cell * (index % perRow) + cell / 2, y: WEB_HEIGHT + 44 + Math.floor(index / perRow) * 40 }));
  const height = loose.length ? WEB_HEIGHT + 44 + Math.ceil(loose.length / perRow) * 40 : WEB_HEIGHT;
  return { at, height, looseTop: loose.length ? WEB_HEIGHT + 6 : null, looseCount: loose.length };
}

const nodeText = (node: OrgNode) => node.kind === "document" ? describeDocument(node).shortId : node.label;

function WebCanvas({ shown, links, selected, onSelect }: { shown: OrgNode[]; links: { id: string; source: string; target: string }[]; selected: string | null; onSelect: Select }) {
  const base = useMemo(() => webLayout(shown, links), [shown, links]);
  const [moved, setMoved] = useState<Record<string, Point>>({});
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const [hover, setHover] = useState<string | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: string | null; startX: number; startY: number; origin: Point; moved: boolean } | null>(null);
  const position = (id: string): Point => moved[id] ?? base.at.get(id) ?? { x: 0, y: 0 };
  const focus = hover ?? selected;
  const near = useMemo(() => focus ? neighbourIds(focus) : null, [focus]);
  const lit = (id: string) => !focus || id === focus || !!near?.has(id);
  // Screen pixels to graph units, allowing for the current zoom.
  const unit = () => (NET_WIDTH / (svg.current?.clientWidth || NET_WIDTH)) / view.scale;

  const begin = (event: React.PointerEvent, id: string | null) => {
    event.stopPropagation();
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
    drag.current = { id, startX: event.clientX, startY: event.clientY, origin: id ? position(id) : { x: view.x, y: view.y }, moved: false };
  };
  const during = (event: React.PointerEvent) => {
    const state = drag.current;
    if (!state) return;
    const dx = (event.clientX - state.startX) * unit(), dy = (event.clientY - state.startY) * unit();
    if (Math.abs(dx) + Math.abs(dy) > 3) state.moved = true;
    if (!state.moved) return;
    if (state.id) setMoved(current => ({ ...current, [state.id!]: { x: state.origin.x + dx, y: state.origin.y + dy } }));
    else setView(current => ({ ...current, x: state.origin.x + dx * current.scale, y: state.origin.y + dy * current.scale }));
  };
  const finish = (id: string | null) => {
    const state = drag.current;
    drag.current = null;
    if (id && state && !state.moved) onSelect(id);
  };
  const zoom = (factor: number) => setView(current => {
    const scale = Math.min(2.6, Math.max(0.6, current.scale * factor));
    const cx = NET_WIDTH / 2, cy = base.height / 2; // keep the centre of the view fixed
    return { scale, x: cx - ((cx - current.x) / current.scale) * scale, y: cy - ((cy - current.y) / current.scale) * scale };
  });

  return <div className="org-web">
    <div className="org-web-tools">
      <button type="button" className="org-chip" aria-label="Zoom in" onClick={() => zoom(1.25)}>+</button>
      <button type="button" className="org-chip" aria-label="Zoom out" onClick={() => zoom(0.8)}>−</button>
      <button type="button" className="org-chip" onClick={() => { setView({ x: 0, y: 0, scale: 1 }); setMoved({}); }}>Reset</button>
    </div>
    <svg ref={svg} viewBox={`0 0 ${NET_WIDTH} ${base.height}`} className="org-web-svg" role="group" aria-label="Network of people, roles, processes, systems and documents"
      onPointerDown={event => begin(event, null)} onPointerMove={during} onPointerUp={() => finish(null)}
      onWheel={event => zoom(event.deltaY < 0 ? 1.1 : 0.9)}>
      <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
        {base.looseTop !== null && <>
          <line x1={0} x2={NET_WIDTH} y1={base.looseTop} y2={base.looseTop} className="org-web-rule" />
          <text x={0} y={base.looseTop + 16} className="org-web-note">No recorded connections · {base.looseCount}</text>
        </>}
        {links.filter(link => base.at.has(link.source) && base.at.has(link.target)).map(link => {
          const a = position(link.source), b = position(link.target);
          const active = !!focus && (link.source === focus || link.target === focus);
          return <line key={link.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`org-edge${active ? " org-edge-active" : ""}${focus && !active ? " org-edge-dim" : ""}`} />;
        })}
        {shown.filter(node => base.at.has(node.id)).map(node => {
          const p = position(node.id), text = nodeText(node), isDocument = node.kind === "document";
          const width = Math.max(40, text.length * 5.6 + 14);
          return <g key={node.id} data-kind={node.kind} transform={`translate(${p.x} ${p.y})`}
            className={`org-web-node${lit(node.id) ? "" : " org-web-dim"}${selected === node.id ? " org-web-selected" : ""}${node.kind === "person" && !isActive(node) ? " org-web-inactive" : ""}`}
            onPointerDown={event => begin(event, node.id)} onPointerMove={during} onPointerUp={() => finish(node.id)}
            onMouseEnter={() => setHover(node.id)} onMouseLeave={() => setHover(null)}>
            <title>{`${KIND_LABELS[node.kind].one}: ${node.label}`}</title>
            {isDocument
              ? <rect x={-width / 2} y={-9} width={width} height={18} rx={4} className="org-web-doc" />
              : <circle r={node.kind === "role" || node.kind === "process" ? 7.5 : 6} fill={KIND_COLOURS[node.kind]} className="org-web-dot" />}
            <text y={isDocument ? 3.5 : 19} textAnchor="middle" className={isDocument ? "org-web-doc-text" : "org-web-label"}>{text}</text>
          </g>;
        })}
      </g>
    </svg>
  </div>;
}

// ── Columns layout: people, roles, then functions/processes/systems, then documents ──

const COLUMNS: { kinds: NodeKind[]; x: number; width: number }[] = [
  { kinds: ["person"], x: 0, width: 160 },
  { kinds: ["role"], x: 232, width: 232 },
  { kinds: ["function", "process", "system"], x: 536, width: 240 },
  { kinds: ["document"], x: 848, width: 192 },
];
const ROW = 26, BOX = 22, GROUP_GAP = 34, TOP = 30;

function columnsLayout(shown: OrgNode[]) {
  const roleOrder: string[] = [];
  const walk = (node: RoleNode) => { roleOrder.push(node.role.id); node.reports.forEach(walk); };
  roleTree().forEach(walk);
  const holderRank = (person: OrgNode) => {
    const role = edges.find(edge => edge.relationship === "HOLDS" && edge.source === person.id)?.target;
    return role ? roleOrder.indexOf(role) : roleOrder.length;
  };
  const of = (kind: NodeKind) => shown.filter(node => node.kind === kind);
  const byLabel = (a: OrgNode, b: OrgNode) => a.label.localeCompare(b.label);
  const ordered: Record<NodeKind, OrgNode[]> = {
    person: of("person").sort((a, b) => holderRank(a) - holderRank(b) || byLabel(a, b)),
    role: of("role").sort((a, b) => roleOrder.indexOf(a.id) - roleOrder.indexOf(b.id)),
    function: of("function").sort(byLabel),
    process: of("process").sort((a, b) => (a.attributes.code ?? "").localeCompare(b.attributes.code ?? "", undefined, { numeric: true })),
    system: of("system").sort(byLabel),
    document: of("document").sort((a, b) => Number(isLinked(b.id)) - Number(isLinked(a.id)) || nodeText(a).localeCompare(nodeText(b), undefined, { numeric: true })),
  };
  const position = new Map<string, { x: number; y: number; width: number; column: number }>();
  const headings: { label: string; x: number; y: number }[] = [];
  let height = 0;
  COLUMNS.forEach((column, index) => {
    let y = TOP;
    for (const kind of column.kinds) {
      if (!ordered[kind].length) continue;
      headings.push({ label: `${KIND_LABELS[kind].many} · ${ordered[kind].length}`, x: column.x, y: y - 20 });
      for (const node of ordered[kind]) { position.set(node.id, { x: column.x, y, width: column.width, column: index }); y += ROW; }
      y += GROUP_GAP;
    }
    height = Math.max(height, y - GROUP_GAP + 10);
  });
  return { ordered, position, headings, height };
}

function ColumnsCanvas({ shown, links, selected, onSelect }: { shown: OrgNode[]; links: { id: string; source: string; target: string }[]; selected: string | null; onSelect: Select }) {
  const layout = useMemo(() => columnsLayout(shown), [shown]);
  const [hover, setHover] = useState<string | null>(null);
  const focus = hover ?? selected;
  const near = useMemo(() => focus ? neighbourIds(focus) : null, [focus]);
  const lit = (id: string) => !focus || id === focus || !!near?.has(id);
  const path = (from: string, to: string) => {
    const a = layout.position.get(from)!, b = layout.position.get(to)!;
    const ay = a.y + BOX / 2, by = b.y + BOX / 2;
    if (a.column === b.column) { // same column: a shallow arc on the right-hand side
      const x = a.x + a.width, bulge = 22 + Math.min(40, Math.abs(by - ay) / 6);
      return `M${x},${ay} C${x + bulge},${ay} ${x + bulge},${by} ${x},${by}`;
    }
    const leftToRight = a.column < b.column;
    const x1 = leftToRight ? a.x + a.width : a.x, x2 = leftToRight ? b.x : b.x + b.width, mid = (x1 + x2) / 2;
    return `M${x1},${ay} C${mid},${ay} ${mid},${by} ${x2},${by}`;
  };
  return <div className="org-network-scroll">
    <div className="org-network-canvas" style={{ width: NET_WIDTH, height: layout.height }}>
      <svg width={NET_WIDTH} height={layout.height} aria-hidden="true">
        {links.filter(link => layout.position.has(link.source) && layout.position.has(link.target)).map(link => {
          const active = !!focus && (link.source === focus || link.target === focus);
          return <path key={link.id} d={path(link.source, link.target)} className={`org-edge${active ? " org-edge-active" : ""}${focus && !active ? " org-edge-dim" : ""}`} />;
        })}
      </svg>
      {layout.headings.map(heading => <span key={`${heading.label}:${heading.x}:${heading.y}`} className="org-network-heading" style={{ left: heading.x, top: heading.y }}>{heading.label}</span>)}
      {KIND_ORDER.flatMap(kind => layout.ordered[kind]).map(node => {
        const at = layout.position.get(node.id)!;
        return <button type="button" key={node.id} title={node.label} aria-pressed={selected === node.id} data-kind={node.kind}
          className={`org-node org-node-${node.kind}${lit(node.id) ? "" : " org-node-dim"}${node.kind === "person" && !isActive(node) ? " org-inactive" : ""}`}
          style={{ left: at.x, top: at.y, width: at.width, height: BOX }}
          onMouseEnter={() => setHover(node.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(node.id)} onBlur={() => setHover(null)}
          onClick={() => onSelect(node.id)}>{nodeText(node)}</button>;
      })}
    </div>
  </div>;
}

export function NetworkView({ selected, onSelect, initialLayout = "web" }: { selected: string | null; onSelect: Select; initialLayout?: NetLayout }) {
  const [layout, setLayout] = useState<NetLayout>(initialLayout);
  const [kinds, setKinds] = useState<Set<NodeKind>>(() => new Set(KIND_ORDER));
  // Reporting lines give the web its shape; in columns they are arcs that add clutter.
  const [reporting, setReporting] = useState(initialLayout === "web");
  const [unlinked, setUnlinked] = useState(false);
  const unlinkedCount = useMemo(() => nodesOfKind("document").filter(doc => !isLinked(doc.id)).length, []);
  const shown = useMemo(() => visibleNodes(kinds, unlinked), [kinds, unlinked]);
  const links = useMemo(() => {
    const ids = new Set(shown.map(node => node.id));
    return edges.filter(edge => (reporting || edge.relationship !== "REPORTS_TO") && ids.has(edge.source) && ids.has(edge.target));
  }, [shown, reporting]);
  const toggleKind = (kind: NodeKind) => setKinds(current => { const next = new Set(current); if (next.has(kind)) next.delete(kind); else next.add(kind); return next; });
  const choose = (next: NetLayout) => { setLayout(next); setReporting(next === "web"); };

  return <section className="org-network" aria-label="Organisation network">
    <div className="org-network-controls">
      <div className="ev-chips" style={{ margin: 0 }}>{KIND_ORDER.map(kind =>
        <button type="button" key={kind} className="org-chip org-kind" aria-pressed={kinds.has(kind)} onClick={() => toggleKind(kind)}>
          <span className={kind === "document" ? "org-kind-box" : "org-kind-dot"} style={{ background: KIND_COLOURS[kind] }} />{KIND_LABELS[kind].many}
        </button>)}</div>
      <div className="ev-chips" style={{ margin: 0 }}>
        <button type="button" className="org-chip" aria-pressed={reporting} onClick={() => setReporting(value => !value)}>Reporting lines</button>
        <button type="button" className="org-chip" aria-pressed={unlinked} onClick={() => setUnlinked(value => !value)}>Unlinked documents <Count>{unlinkedCount}</Count></button>
        <div className="ev-segments" role="group" aria-label="Network layout">
          <button type="button" aria-pressed={layout === "web"} onClick={() => choose("web")}>Web</button>
          <button type="button" aria-pressed={layout === "columns"} onClick={() => choose("columns")}>Columns</button>
        </div>
      </div>
    </div>
    <p className="ev-muted" style={{ margin: "10px 0 14px" }}>{layout === "web"
      ? "Point at an item to trace its connections. Drag an item to move it, drag the background to pan, and scroll to zoom."
      : "Point at or select an item to trace its connections. Reporting lines are off here by default; the org chart shows them."}</p>
    {layout === "web"
      ? <WebCanvas shown={shown} links={links} selected={selected} onSelect={onSelect} />
      : <ColumnsCanvas shown={shown} links={links} selected={selected} onSelect={onSelect} />}
  </section>;
}

// ── Detail panel ─────────────────────────────────────────────────────────────

export function NodeDetail({ id, onSelect, onClose }: { id: string; onSelect: Select; onClose: () => void }) {
  const node = getNode(id);
  if (!node) return null;
  const groups = neighbours(id);
  const attributes = Object.entries(node.attributes).filter(([key, value]) => value && key !== "duplicate_group");
  return <aside className="ev-card org-detail" aria-label="Selected item">
    <div className="ev-toolbar" style={{ alignItems: "flex-start", marginBottom: 10 }}>
      <div><span className="ev-kicker" style={{ marginBottom: 4 }}>{KIND_LABELS[node.kind].one}</span><h3 style={{ margin: 0 }}>{node.label}</h3></div>
      <button type="button" className="ev-button org-close" onClick={onClose}>Close</button>
    </div>
    {attributes.length > 0 && <dl className="ev-fields org-detail-fields">{attributes.map(([key, value]) => <div key={key}>
      <dt>{humanize(key).replace(/^./, letter => letter.toUpperCase())}</dt>
      <dd>{key === "source_id" ? shortSourceId(value) : humanize(value ?? "")}</dd>
    </div>)}</dl>}
    {groups.length === 0 && <p className="ev-muted">No recorded connections for this item.</p>}
    {groups.map(group => <div key={group.label}>
      <h4>{group.label} <Count>{group.nodes.length}</Count></h4>
      {group.nodes.map(item => <button type="button" key={item.id} className="org-row" onClick={() => onSelect(item.id)}>
        <span className="org-row-text">{item.label}</span>
        <span className="ev-muted" style={{ display: "inline" }}>{KIND_LABELS[item.kind].one}</span>
      </button>)}
    </div>)}
  </aside>;
}

// ── Page ─────────────────────────────────────────────────────────────────────

type View = "chart" | "processes" | "network";
const VIEWS: [View, string][] = [["chart", "Org chart"], ["processes", "Processes"], ["network", "Network"]];

export default function OrganisationScreen() {
  const [view, setView] = useState<View>("chart");
  const [selected, setSelected] = useState<string | null>(null);
  const counts = (Object.keys(KIND_LABELS) as NodeKind[]).map(kind => [KIND_LABELS[kind].many, nodes.filter(node => node.kind === kind).length] as const);
  return <main className="ev-workspace" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "36px 48px" }}>
    <div className="ev-toolbar">
      <div><h1>Organisation</h1>
        <p className="ev-muted" style={{ marginTop: 4 }}>How the organisation is structured according to the corpus: who holds which role, which processes they take part in, and which documents govern them.</p></div>
      <div className="ev-segments" role="group" aria-label="Organisation view">
        {VIEWS.map(([value, label]) => <button type="button" key={value} aria-pressed={view === value} onClick={() => setView(value)}>{label}</button>)}
      </div>
    </div>
    <div className="org-counts">{counts.map(([label, count]) => <span key={label}>{label} <Count>{count}</Count></span>)}
      <span className="ev-muted" style={{ display: "inline", marginLeft: "auto" }}>Graph {graphVersion}</span></div>
    <div className={`org-layout${selected ? " org-split" : ""}`}>
      <div className="org-main">
        {view === "chart" && <OrgChart selected={selected} onSelect={setSelected} />}
        {view === "processes" && <ProcessMap selected={selected} onSelect={setSelected} />}
        {view === "network" && <NetworkView selected={selected} onSelect={setSelected} />}
      </div>
      {selected && <NodeDetail id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </div>
  </main>;
}
