# ruff: noqa: N999
"""Home page for the standalone graph-governed prototype."""

from framework.graph_prototype import GRAPH_PATH, OrganisationalGraph
import streamlit as st

st.set_page_config(page_title="Graph-governed credibility prototype", layout="wide")
st.title("Graph-governed Credibility Prototype")
st.info(
    "This is a new, standalone implementation. It does not import from, write to, or extend "
    "the existing relational credibility framework and facts register."
)

graph = OrganisationalGraph.load(GRAPH_PATH)
nodes = list(graph.nodes.values())
node_counts = {
    kind: sum(node.kind == kind for node in nodes)
    for kind in ("person", "role", "function", "process", "system", "document", "fact")
}

st.subheader("Architecture")
st.markdown(
    """
**Organisational backbone:** Person, Role, Function, Process and System nodes resolve names,
employment status and authority.  The backbone does not decide truth.

**Evidence engine:** Document and Fact nodes.  A Fact is a searchable topic and stores no
value.  Values live on `FORMAL` or `OBSERVED` edges as `attests_value`, with agreement,
scope and extraction metadata.

**Decision discipline:** retrieval finds the Fact; edges gather attestations; deterministic
code weighs source class, lifecycle status, date, directness, specificity, corroboration,
independence and completeness.  Formal and observed outcomes remain separate.
"""
)

columns = st.columns(len(node_counts))
for column, (kind, count) in zip(columns, node_counts.items(), strict=True):
    column.metric(kind.title(), count)
st.caption(f"Graph version: {graph.version}; {len(graph.edges)} validated relationships.")

st.subheader("End-to-end flow")
st.code(
    "Claim/query -> local vector retrieval -> Fact -> FORMAL/OBSERVED edges\n"
    "-> source/status/date weighting -> separate lane outcomes -> graph facts register"
)

st.subheader("Pages")
st.markdown(
    "- **Graph Credibility Framework** retrieves a Fact and shows the complete credibility trace.\n"
    "- **Graph Facts Register** derives exportable findings from every Fact in this graph."
)

st.subheader("Run independently")
st.code(
    ".\\.venv\\Scripts\\python.exe -m streamlit run decidr\\graph_app\\Home.py",
    language="powershell",
)
