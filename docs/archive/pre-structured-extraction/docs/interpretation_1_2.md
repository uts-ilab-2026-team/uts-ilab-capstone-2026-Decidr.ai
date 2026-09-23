# Experimental interpretation-1.2

QueryFrame and post-retrieval AtomicClaim remain separate. The development model is
llama3.1:8b through YAML/environment configuration; the employee UI remains unpromoted.
The evidence-binding interface, Phase 2 restrictions, retrieval, graph, eligibility,
credibility and deterministic verdict/confidence calculation are unchanged.

## Acceptance and representation

Critical failures include wrong intent/target/requested field, invented information,
changed quantities/dates/modality/negation, incomplete business actions, omitted questions,
unnecessary clarification of requested answers and unresolved material ambiguity. Unsafe,
untraceable normalised content and prohibited schema fields also block acceptance.

Recoverable representation differences include casing, punctuation/Unicode, inflection,
harmless terminology normalisation, aligned source spans and optional null representation.
They are corrected locally and do not consume an LLM repair. A redundant null process
label is not itself loss of meaning if the complete action/object retains the process.
Temporal operators can be preserved across temporal_scope and conditions; the operator
must still survive. These decisions do not allow dropping explicit business information.

Each grounded field has a SourceSpan record with normalised_value, source_span,
source_start, source_end (exclusive), alignment_method and alignment_score. The existing
text field remains an exact source-span alias for compatibility. Values need not be
verbatim; source spans and offsets always refer to employee wording or a cited bounded
conversation entry. Ontology labels are checked semantically, not treated as literal words.

The generic aligner tries exact and case-insensitive matches, then Unicode/punctuation,
inflection and token alignment within bounded windows. Every content token must align;
no business synonym table is used. General morphological endings and conservative lexical
similarity handle normalisation. The configurable minimum score is 0.85 (configuration
range 0.8–1.0). Protected numbers and temporal operators cannot be substituted; numerical
sequence order is checked so date components cannot be reversed. Global semantic checks
also enforce explicit actor/action/object/constraint retention and modality/negation.
Temporary lexical caches are cleared after each validation.

Every automatic span/null correction is recorded in session technical provenance. This
includes reconstructed missing spans and corrected offsets. No hidden reasoning, formal
review records or corpus content is stored by this layer. Alignment is lexical evidence
of traceability, not a guarantee of arbitrary semantic equivalence; employee confirmation
and development acceptance review remain necessary.

Auxiliary verbs are allowed only with a complete semantic predicate/object combination.
A generic meta-verb cannot replace an explicitly supplied business action. The prompt
uses unrelated library/laboratory/telescope and CRM-field schema examples, with no corpus
answers. Policy timing obligations remain prescribed rules even when they mention recording.

## Compound questions and repair

Potential compound interrogatives use a focused deterministic decomposition stage. It
returns verbatim question fragments with exact offsets before detailed interpretation;
there is no extra LLM call just to split text. Each fragment is interpreted separately
with the original question in bounded context. The assembled frames retain the original
question and corrected original/context offsets and are separately confirmable.

Simple questions skip decomposition. A compound question shares one LLM repair budget
across all fragments. Repairs contain only critical validation errors and the previous
structured response. A still-invalid result uses deterministic fallback and requires
employee confirmation. There is no automatic cascade to another LLM.

Existing clarification merging and repeat suppression remain. Requested unknown answers
are never themselves missing inputs; unresolved pronouns require usable context or clarification.

## Development verification

The saved 1.1 llama3.1 outputs were re-scored without Ollama calls. Four previously
rejected cases (eight saved initial/repair responses) became accepted; the previously
accepted ambiguity case remained accepted. Three recoveries use span alignment alone;
the dated-policy recovery also removes the redundant-process-field requirement and
recognises the preserved date operator in conditions. Seven cases retain critical errors.

The live subset contains those seven cases plus the ambiguity and final onboarding
checks (nine cases total, llama3.1 only). The other three cases are carried forward from
offline re-scoring. This mixed-origin 12-case result is an incremental development check,
not a new full live run and not a formal/held-out evaluation. All labels, raw outputs and
per-case scoring stay outside the repository under /tmp.

- Ruff: passed.
- Mocked tests: 222 passed.
- Dataset: 45 sources, 812 evidence units.
- Fingerprint: 766ca57488795f6e0d7e587f1bb1db36356112b9938c9e53efbed34510ba116e.

The frozen incremental result is 8/12 critical-semantic acceptance before and after
repair, with 197/208 (94.71%) meaning-focused field accuracy. All accepted extracted
values have exact source traceability. Percentages (2/2), dates (2/2), explicit modality
(6/6) and the explicit exclusion (1/1) survive unchanged. Nine live cases produced five
accepted results and four fallbacks; median whole-question latency was 10745.15 ms and
maximum 17176.80 ms. The onboarding smoke was accepted without repair/fallback in
9147.71 ms. Its auxiliary has is accompanied by the complete semantic authority-to-approve
object, as permitted by the combined-action rule.

The compound splitter returns two correct verbatim fragments, but the timing interpretation
still uses must as the action and as a temporal value. The genuine-ambiguity case succeeds.
Other remaining failures concern unnecessary threshold clarification, an incomplete
procedure business action, and a prescribed procedure misclassified as actual practice.

The promotion gate fails (8/12 is below 9/12 and compound interpretation fails). The UI
remains unpromoted. The evidence-binding interface remains pending/unchanged; no new
accepted representation has been promoted into an automatic evidence-to-answer flow.
No runtime code was changed after the live subset began. Full responses and per-field
review are in /tmp/decidr-interpreter-model-comparison-1.2.json and its companion .md report.
