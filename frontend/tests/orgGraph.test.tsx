import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import OrganisationScreen, { NetworkView, NodeDetail, OrgChart, ProcessMap } from "../src/OrganisationScreen";
import { documents, edges, getNode, incoming, neighbours, nodes, nodesOfKind, processCards, roleTree, shortSourceId, type RoleNode } from "../src/orgGraph";

test("corpus graph loads with consistent nodes and edges", () => {
  assert.equal(nodes.length, 116);
  assert.equal(edges.length, 153);
  assert.equal(new Set(nodes.map(node => node.id)).size, nodes.length);
  for (const edge of edges) assert.ok(getNode(edge.source) && getNode(edge.target), edge.id);
});

test("reporting tree has one root and reaches every role exactly once", () => {
  const roots = roleTree();
  assert.equal(roots.length, 1);
  assert.equal(roots[0].role.label, "CEO / Founder");
  const seen: string[] = [];
  const walk = (node: RoleNode) => { seen.push(node.role.id); node.reports.forEach(walk); };
  roots.forEach(walk);
  assert.equal(seen.length, nodesOfKind("role").length);
  assert.equal(new Set(seen).size, seen.length);
  for (const role of nodesOfKind("role")) assert.ok(incoming(role.id, "HOLDS").length > 0, role.label);
});

test("every process has a governing document and participating roles", () => {
  const cards = processCards();
  assert.equal(cards.length, 8);
  assert.deepEqual(cards.map(card => card.process.attributes.code), ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]);
  for (const card of cards) {
    assert.ok(card.governedBy.length > 0, card.process.label);
    assert.ok(card.roles.length > 0, card.process.label);
  }
});

test("documents list drops the release prefix from source ids", () => {
  assert.equal(shortSourceId("phase1:POL-06"), "POL-06");
  assert.equal(shortSourceId("phase2:crm-deals"), "crm-deals");
  assert.equal(shortSourceId(undefined), "");
  const list = documents();
  assert.equal(list.length, 44);
  assert.ok(list.every(doc => !doc.shortId.includes(":")));
  assert.equal(list.filter(doc => doc.governs.length > 0).length, 13);
});

test("detail relations are grouped and point both ways", () => {
  const groups = neighbours("role:head-of-finance-people-ops").map(group => group.label);
  for (const label of ["Held by", "Reports to", "Direct reports", "Function", "Takes part in"]) assert.ok(groups.includes(label), label);
});

test("organisation views render the roster, processes and network without raw ids", () => {
  const chart = renderToStaticMarkup(<OrgChart selected={null} onSelect={() => {}} />);
  for (const text of ["CEO / Founder", "Renata Voss", "Head of Sales", "Diane Okafor", "Finance &amp; People Ops"]) assert.ok(chart.includes(text), text);
  assert.equal((chart.match(/class="org-box"/g) ?? []).length, 20);
  assert.ok(chart.includes("Wei Zhang") && chart.includes("org-inactive"));

  const processes = renderToStaticMarkup(<ProcessMap selected={null} onSelect={() => {}} />);
  assert.equal((processes.match(/org-process-head/g) ?? []).length, 8);
  for (const text of ["Customer discount approval", "POL-01", "Governed by", "Roles involved"]) assert.ok(processes.includes(text), text);

  for (const layout of ["web", "columns"] as const) {
    const network = renderToStaticMarkup(<NetworkView selected={null} onSelect={() => {}} initialLayout={layout} />);
    assert.ok(network.includes("Unlinked documents"), layout);
    assert.equal((network.match(/data-kind="document"/g) ?? []).length, 15, layout); // unlinked documents start hidden
    assert.equal((network.match(/data-kind="person"/g) ?? []).length, 29, layout);
    assert.ok(!network.includes("REPORTS_TO") && !network.includes("role:"), layout);
  }

  const page = renderToStaticMarkup(<OrganisationScreen />);
  for (const text of ["Organisation", "Org chart", "Processes", "Network"]) assert.ok(page.includes(text), text);
});

test("detail panel lists a document's attributes and connections", () => {
  const html = renderToStaticMarkup(<NodeDetail id="document:POL-06" onSelect={() => {}} onClose={() => {}} />);
  for (const text of ["Document", "Governs", "POL-06", "Approval status"]) assert.ok(html.includes(text), text);
  assert.equal(renderToStaticMarkup(<NodeDetail id="missing" onSelect={() => {}} onClose={() => {}} />), "");
});
