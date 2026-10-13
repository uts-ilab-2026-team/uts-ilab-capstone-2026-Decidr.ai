import corpusGraph from "./data/corpus_graph.json";

// The organisation backbone built from the corpus: people, roles, functions, processes,
// systems and documents, and how they relate. It holds no facts or evidence, so it
// describes structure only. The file is a bundled snapshot of corpus_graph.json.

export type NodeKind = "document" | "person" | "role" | "function" | "process" | "system";
export type Relationship = "HOLDS" | "REPORTS_TO" | "SITS_IN" | "PARTICIPATES_IN" | "ACCESSES" | "GOVERNS" | "SUPERSEDED_BY" | "RELATED" | "OWNED_BY";

export interface OrgNode {
  id: string;
  kind: NodeKind;
  label: string;
  attributes: Record<string, string | undefined>;
}
export interface OrgEdge {
  id: string;
  source: string;
  target: string;
  relationship: Relationship;
}

const raw = corpusGraph as unknown as { graph_version: string; nodes: OrgNode[]; edges: OrgEdge[] };

export const graphVersion = raw.graph_version;
export const nodes: OrgNode[] = raw.nodes.map(node => ({ ...node, label: node.label.trim() }));
export const edges: OrgEdge[] = raw.edges;

const byId = new Map(nodes.map(node => [node.id, node]));
const byLabel = (a: OrgNode, b: OrgNode) => a.label.localeCompare(b.label);

export const getNode = (id: string): OrgNode | undefined => byId.get(id);
export const nodesOfKind = (kind: NodeKind): OrgNode[] => nodes.filter(node => node.kind === kind).sort(byLabel);

/** Nodes this node points to through the relationship. */
export function outgoing(id: string, relationship: Relationship): OrgNode[] {
  return edges.filter(edge => edge.source === id && edge.relationship === relationship)
    .map(edge => byId.get(edge.target)).filter((node): node is OrgNode => !!node).sort(byLabel);
}
/** Nodes that point to this node through the relationship. */
export function incoming(id: string, relationship: Relationship): OrgNode[] {
  return edges.filter(edge => edge.target === id && edge.relationship === relationship)
    .map(edge => byId.get(edge.source)).filter((node): node is OrgNode => !!node).sort(byLabel);
}

/** Source ids carry a release prefix ("phase1:POL-06"); the rest identifies the document. */
export const shortSourceId = (sourceId: string | undefined): string => (sourceId ?? "").replace(/^[^:]*:/, "");

export const isActive = (person: OrgNode): boolean => person.attributes.status === "active";

// ── Reporting tree ───────────────────────────────────────────────────────────

export interface RoleNode {
  role: OrgNode;
  holders: OrgNode[];
  func: OrgNode | undefined;
  reports: RoleNode[];
}

function buildRole(role: OrgNode, seen: Set<string>): RoleNode {
  seen.add(role.id);
  return {
    role,
    holders: incoming(role.id, "HOLDS"),
    func: outgoing(role.id, "SITS_IN")[0],
    reports: incoming(role.id, "REPORTS_TO").filter(child => !seen.has(child.id)).map(child => buildRole(child, seen)),
  };
}

/** Roles nested by REPORTS_TO, starting from every role that reports to no one. */
export function roleTree(): RoleNode[] {
  const seen = new Set<string>();
  return nodesOfKind("role").filter(role => outgoing(role.id, "REPORTS_TO").length === 0).map(role => buildRole(role, seen));
}

// ── Processes ────────────────────────────────────────────────────────────────

export interface ProcessCard {
  process: OrgNode;
  governedBy: OrgNode[];
  roles: { role: OrgNode; holders: OrgNode[] }[];
  systems: OrgNode[];
}

/** Each process with the documents that govern it, the roles involved and their systems. */
export function processCards(): ProcessCard[] {
  return nodesOfKind("process").map(process => {
    const roles = incoming(process.id, "PARTICIPATES_IN");
    const systems = new Map<string, OrgNode>();
    for (const role of roles) for (const system of outgoing(role.id, "ACCESSES")) systems.set(system.id, system);
    return {
      process,
      governedBy: incoming(process.id, "GOVERNS"),
      roles: roles.map(role => ({ role, holders: incoming(role.id, "HOLDS") })),
      systems: [...systems.values()].sort(byLabel),
    };
  }).sort((a, b) => (a.process.attributes.code ?? "").localeCompare(b.process.attributes.code ?? "", undefined, { numeric: true }));
}

// ── Documents (the Sources list) ─────────────────────────────────────────────

export interface OrgDocument {
  node: OrgNode;
  shortId: string;
  sourceClass: string;
  status: string;
  approval: string;
  date: string | undefined;
  governs: OrgNode[];
  supersededBy: OrgNode[];
  supersedes: OrgNode[];
}

export function describeDocument(node: OrgNode): OrgDocument {
  return {
    node,
    shortId: shortSourceId(node.attributes.source_id) || node.id.replace(/^document:/, ""),
    sourceClass: node.attributes.source_class ?? "unknown",
    status: node.attributes.status ?? "unknown",
    approval: node.attributes.approval_status ?? "unknown",
    date: node.attributes.last_updated ?? node.attributes.effective_date,
    governs: outgoing(node.id, "GOVERNS"),
    supersededBy: outgoing(node.id, "SUPERSEDED_BY"),
    supersedes: incoming(node.id, "SUPERSEDED_BY"),
  };
}

export const documents = (): OrgDocument[] => nodesOfKind("document").map(describeDocument).sort((a, b) => a.shortId.localeCompare(b.shortId, undefined, { numeric: true }));

// ── Relations of one node, for the detail panel ──────────────────────────────

const RELATION_LABELS: Record<Relationship, { out: string; in: string }> = {
  HOLDS: { out: "Holds role", in: "Held by" },
  REPORTS_TO: { out: "Reports to", in: "Direct reports" },
  SITS_IN: { out: "Function", in: "Roles in this function" },
  PARTICIPATES_IN: { out: "Takes part in", in: "Roles involved" },
  ACCESSES: { out: "Has access to", in: "Accessed by" },
  GOVERNS: { out: "Governs", in: "Governed by" },
  SUPERSEDED_BY: { out: "Superseded by", in: "Supersedes" },
  RELATED: { out: "Related documents", in: "Named as related by" },
  OWNED_BY: { out: "Document owner", in: "Owns documents" },
};

export interface RelationGroup {
  label: string;
  nodes: OrgNode[];
}

export function neighbours(id: string): RelationGroup[] {
  const groups: RelationGroup[] = [];
  for (const relationship of Object.keys(RELATION_LABELS) as Relationship[]) {
    const out = outgoing(id, relationship);
    if (out.length) groups.push({ label: RELATION_LABELS[relationship].out, nodes: out });
    const inn = incoming(id, relationship);
    if (inn.length) groups.push({ label: RELATION_LABELS[relationship].in, nodes: inn });
  }
  return groups;
}

export const neighbourIds = (id: string): Set<string> =>
  new Set(edges.flatMap(edge => edge.source === id ? [edge.target] : edge.target === id ? [edge.source] : []));

export const isLinked = (id: string): boolean => edges.some(edge => edge.source === id || edge.target === id);

export const KIND_LABELS: Record<NodeKind, { one: string; many: string }> = {
  person: { one: "Person", many: "People" },
  role: { one: "Role", many: "Roles" },
  function: { one: "Function", many: "Functions" },
  process: { one: "Process", many: "Processes" },
  system: { one: "System", many: "Systems" },
  document: { one: "Document", many: "Documents" },
};
