"""Local, citation-grounded semantic interpretation with explicit operational failures.

The model proposes meaning and relationships; exact spans, identifiers and numeric
boundaries are checked here, followed by a separate semantic verification pass.
"""

from decidr.claim_interpreter.admission import (
    approval_boundary_exclusion,
    claim_evidence_exclusion,
)
from decidr.claim_interpreter.llm_completion import _complete
from decidr.claim_interpreter.pipeline import (
    _evidence_data,
    _validated_retry,
    interpret_claim,
)
from decidr.claim_interpreter.prompts import _EVALUATION_INSTRUCTION
from decidr.claim_interpreter.providers import (
    CITATION_METHOD,
    METHOD,
    NUMERIC_VALIDATION_LIMITATIONS,
    NUMERIC_VALIDATION_METHOD,
    VALIDATION_METHOD,
    OllamaProvider,
    Provider,
    ProviderError,
    _EvidenceMeaningError,
    get_provider,
)
from decidr.claim_interpreter.schemas import (
    ClaimCheck,
    Component,
    Evaluation,
    Interpretation,
    InterpretationVerification,
    OmittedClaimSpan,
    Quantity,
    _claim_verifier_model,
    _FindingSelection,
    _interpretation_model,
    _selection_model,
)
from decidr.claim_interpreter.text_numeric import (
    _IDENTIFIERS,
    _numeric_unit,
    _scalar_observations,
)
from decidr.claim_interpreter.validation import (
    _validate_claim_numbers,
    _validate_evidence_numbers,
)

__all__ = [
    "CITATION_METHOD",
    "METHOD",
    "NUMERIC_VALIDATION_LIMITATIONS",
    "NUMERIC_VALIDATION_METHOD",
    "VALIDATION_METHOD",
    "_EVALUATION_INSTRUCTION",
    "_IDENTIFIERS",
    "ClaimCheck",
    "Component",
    "Evaluation",
    "Interpretation",
    "InterpretationVerification",
    "OllamaProvider",
    "OmittedClaimSpan",
    "Provider",
    "ProviderError",
    "Quantity",
    "_EvidenceMeaningError",
    "_FindingSelection",
    "_claim_verifier_model",
    "_complete",
    "_evidence_data",
    "_interpretation_model",
    "_numeric_unit",
    "_scalar_observations",
    "_selection_model",
    "_validate_claim_numbers",
    "_validate_evidence_numbers",
    "_validated_retry",
    "approval_boundary_exclusion",
    "claim_evidence_exclusion",
    "get_provider",
    "interpret_claim",
]
