# Phase 2 interpretation development packet

inputs.json contains claim text, one focal passage, source metadata and context.
references.json is separate and must not be passed to an interpreter.
manifest.json records corpus identity, code version and content hashes.

All relationship references start unresolved. Prior retrieval inspection did
not establish support, contradiction, qualification or context labels.

Review the focal passage against the exact claim, using supplied context.
Record a rationale and reviewer identity. Use provisional for a proposed label;
use adjudicated only after the project's adjudication process. Leave ambiguous
cases unresolved with a null expected_relationship.

Interpret prescribed rules separately from observed practice. A recorded
violation does not by itself contradict the existence of a rule. A single
completion cannot establish universal compliance. Preserve population, scope,
conditions, dates and inclusive/exclusive boundaries.

Context passages clarify the focal passage; do not silently label a different
context passage instead. If the four-label scheme cannot represent the case
adequately, retain it as unresolved and document why.

This is a selected development packet, not a representative or held-out test.
No model predictions or accuracy results are included.
