# Graph prototype file map

The framework is organised into focused modules under `framework/`. The public API
(`from framework import ...`) is exposed by `framework/__init__.py`, which also resolves
`GRAPH_PATH` and `CONFIG_PATH`.

| Purpose | Repository location |
| --- | --- |
| Shared vocabulary (dimensions, questions, outcomes, confidence) | `framework/constants.py` |
| Schema/validation exception | `framework/errors.py` |
| Immutable data records (nodes, edges, assessments) | `framework/models.py` |
| Credibility configuration record | `framework/config.py` |
| Graph structure, validation, retrieval and visualisation | `framework/graph.py` |
| Deterministic credibility reasoning | `framework/credibility.py` |
| Graph facts-register projection and exports | `framework/register.py` |
| Credibility configuration data | `framework/data/credibility.json` |
| Synthetic demonstration graph | `framework/data/prototype_graph.json` |
| HTTP API | `decidr/api/app.py` |
| Web application | `frontend/` |
| Automated tests | `tests/test_graph_prototype.py` and `tests/test_api.py` |
| Additional dependencies | `requirements-graph.txt` |
| Local launch scripts | `setup_graph_and_run.ps1` and `setup_graph_and_run.sh` |
| Graph-specific quality checks | `.github/workflows/graph-quality.yml` |

The prototype contains no notebook, so no notebook file is included.
