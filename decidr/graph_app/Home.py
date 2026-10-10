# ruff: noqa: N999
"""Home page for the locally integrated credibility prototype."""

import streamlit as st

from decidr.corpus_assessment import AssessmentStore
from framework.graph_prototype import GRAPH_PATH, OrganisationalGraph

st.set_page_config(page_title="Graph-governed credibility prototype", layout="wide")
st.title("Decidr Graph and Structured Retrieval Prototype")
st.info(
    "The graph credibility framework is connected to Saif's structured retrieval engine. "
    "Retrieval remains separate from interpretation, credibility scoring and final human review."
)

graph = OrganisationalGraph.load(GRAPH_PATH)
corpus = AssessmentStore()
corpus_counts = corpus.counts()
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

**Corpus integration:** Saif's FTS5/BM25 retrieval, optional local semantic retrieval, reciprocal
rank fusion, temporal handling and provenance controls propose candidate evidence. The framework
then performs numeric and authority comparison, interpretation and graph scoring. Automated
candidates remain separate from final human-reviewed findings.
"""
)

columns = st.columns(len(node_counts))
for column, (kind, count) in zip(columns, node_counts.items(), strict=True):
    column.metric(kind.title(), count)
st.caption(f"Graph version: {graph.version}; {len(graph.edges)} validated relationships.")

corpus_columns = st.columns(4)
corpus_columns[0].metric("Corpus sources", corpus_counts["sources"])
corpus_columns[1].metric("Corpus evidence", corpus_counts["evidence"])
corpus_columns[2].metric("Saved assessments", corpus_counts["assessments"])
corpus_columns[3].metric("Human reviews", corpus_counts["reviews"])

st.subheader("End-to-end flow")
st.code(
    "Exact claim -> Saif FTS5/BM25 + optional semantic RRF retrieval -> interpretation\n"
    "-> numeric/authority comparison -> FORMAL/OBSERVED graph edges -> credibility scoring\n"
    "-> automated candidate -> two independent reviews / adjudication -> final register finding"
)

st.subheader("Pages")
st.markdown(
    "- **Graph Credibility Framework** retrieves a Fact and shows the complete credibility trace.\n"
    "- **Graph Facts Register** derives exportable findings from every prebuilt Fact.\n"
    "- **End-to-End Claim Assessment** uses Saif's engine, then applies framework checks.\n"
    "- **Corpus Facts Register** keeps automated candidates separate from human-reviewed findings."
)

st.subheader("Run independently")
st.code(
    ".\\.venv\\Scripts\\python.exe -m streamlit run decidr\\graph_app\\Home.py",
    language="powershell",
)
