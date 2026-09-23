"""Filtered, claim-centred provenance graph."""

import streamlit as st

from decidr.config import DATABASE_PATH
from decidr.database import connect
from decidr.graph import build_claim_graph, to_graphviz


st.title("Evidence Graph")
st.caption("This derived graph supports provenance inspection; it never decides credibility.")
with connect(DATABASE_PATH) as connection:
    claims = [row[0] for row in connection.execute("SELECT claim_id FROM claims ORDER BY claim_id")]
if not claims:
    st.info("Create and review a claim first.")
    st.stop()
claim_id = st.selectbox("Claim", claims)
with connect(DATABASE_PATH) as connection:
    graph = build_claim_graph(connection, claim_id)
st.graphviz_chart(to_graphviz(graph), width="stretch")
st.write(f"{graph.number_of_nodes()} nodes · {graph.number_of_edges()} relationships")
st.dataframe(
    [
        {
            "from": source,
            "relationship": attributes.get("relationship"),
            "to": target,
            "reviewer": attributes.get("reviewer"),
        }
        for source, target, attributes in graph.edges(data=True)
    ],
    width="stretch",
)
