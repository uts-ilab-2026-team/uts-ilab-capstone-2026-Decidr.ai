# Graph prototype file map

The standalone ZIP has been mapped into the existing repository categories as follows:

| Purpose | Repository location |
| --- | --- |
| Graph validation, retrieval and credibility rules | `framework/graph_prototype/core.py` |
| Graph facts-register projection and exports | `framework/graph_prototype/register.py` |
| Credibility configuration | `framework/graph_prototype/config/credibility.json` |
| Synthetic demonstration graph | `framework/graph_prototype/data/prototype_graph.json` |
| Streamlit application | `decidr/graph_app/Home.py` and `decidr/graph_app/pages/` |
| Automated tests | `tests/test_graph_prototype.py` |
| Additional dependencies | `requirements-graph.txt` |
| Local launch scripts | `setup_graph_and_run.ps1` and `setup_graph_and_run.sh` |
| Graph-specific quality checks | `.github/workflows/graph-quality.yml` |

The supplied prototype contains no notebook, so no notebook file has been added. Existing
repository files and the original ZIP remain unchanged.
