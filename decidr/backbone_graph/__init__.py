"""Build the persistent organisational backbone (the skeleton) from the corpus.

Produces a validated :class:`decidr.graph.graph.OrganisationalGraph` containing
everything EXCEPT Fact nodes and FORMAL/OBSERVED attestation edges:

* ``document`` nodes + ``SUPERSEDED_BY`` / ``RELATED`` — reused directly from
  ``decidr.ingestion`` (no re-parsing of document metadata).
* ``person`` / ``role`` / ``function`` / ``process`` / ``system`` nodes and the
  backbone edges ``HOLDS`` / ``SITS_IN`` / ``REPORTS_TO`` / ``PARTICIPATES_IN`` /
  ``ACCESSES`` / ``GOVERNS`` — parsed deterministically from the clean markdown
  tables in ``data/00_overview/``.

Design note: this module builds the backbone (it imports ``decidr.ingestion``),
whereas ``decidr.graph`` only ever *loads* the graph. The
in-memory :class:`OrganisationalGraph` is the spine; the JSON dump is an
optional, inspectable snapshot (for review + demo).

Decision rights / "who approves what" are deliberately NOT encoded here — they
are per-claim evidence (the FORMAL/OBSERVED overlay), not structural identity.
"""

from decidr.backbone_graph.builder import OUTPUT_PATH, build_corpus_graph, dump_json
from decidr.backbone_graph.common import (
    SOURCE_CLASS_BY_TYPE,
    _approval_key,
    _GraphBuilder,
    _slug,
)
from decidr.backbone_graph.structure import _add_owned_by

__all__ = [
    "OUTPUT_PATH",
    "SOURCE_CLASS_BY_TYPE",
    "_GraphBuilder",
    "_add_owned_by",
    "_approval_key",
    "_slug",
    "build_corpus_graph",
    "dump_json",
]
