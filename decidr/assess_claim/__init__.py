"""End-to-end: natural-language claim -> whole-claim credibility verdict (Phase 3c core).

This is the single path wired together for the first time. It chains the pieces that were
each proven on their own:

    claim text
      -> claim_split.split_claim            (split into facets; 2 LLM calls, robust/degrades)
      -> retrieve passages                  (in-memory FTS index over the ingested corpus)
      -> fast_reader.evaluate_evidence_fast (ONE batched read: passages x facets -> findings)
      -> _finding_to_llm (converter)        (reader finding dict -> LlmFinding for the shim)
      -> backbone_assessment.assess_on_backbone  (score each facet on the REAL org skeleton)
      -> claim_combiner.combine             (merge facets -> one verdict; trace; undecisive excluded)

Nothing here re-scores or re-judges: the LLM only *reads* (stance + verbatim citation), the
deterministic graph engine does all the scoring. Everything degrades instead of crashing — a
read failure yields an Insufficient verdict with a note, never an exception to the caller.

`to_payload()` returns a plain JSON-safe dict: the exact shape a UI can render.

Live run (needs a local Ollama model; ~2-3 LLM calls, seconds):
    DECIDR_ASSESSMENT_PROVIDER=ollama DECIDR_ASSESSMENT_MODEL=qwen3.5:9b \
        uv run python -m decidr.assess_claim
"""

from decidr.assess_claim.assess import assess_claim
from decidr.assess_claim.cli import main
from decidr.assess_claim.confidence import (
    _confidence_band,
    _facet_confidence,
    _reconcile_confidence,
)
from decidr.assess_claim.payload import to_payload
from decidr.assess_claim.retrieval import _related_codes, _related_view
from decidr.assess_claim.types import ClaimAssessment

__all__ = [
    "ClaimAssessment",
    "_confidence_band",
    "_facet_confidence",
    "_reconcile_confidence",
    "_related_codes",
    "_related_view",
    "assess_claim",
    "main",
    "to_payload",
]
