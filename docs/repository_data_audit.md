# Repository and data audit

Date: 2026-09-03

## Repository state

The repository is a 40 KB Python scaffold containing `decidr/config.py`, a placeholder
dataset command, one deliberately failing test, and empty documentation/framework
directories. No application, database, schemas, retrieval, reasoning, evaluation, or
real ingestion implementation existed at audit time. The directory is not a Git working
tree, so branch and commit status cannot be determined. Existing files are preserved.

The established local standard is Python 3.11, `uv`, Ruff, pytest, type hints, and paths
centralised in configuration. The host default is Python 3.14.7 and `uv 0.12.4`; project
commands must therefore let `uv` provision Python 3.11.

## Supplied corpus

The releases are outside the repository and must remain read-only:

- `../Decidr Capstone Project/04 Data/01 Raw/phase1_framework_development`: 23 files,
  45,637 bytes.
- `../Decidr Capstone Project/04 Data/01 Raw/phase2_model_development`: 45 files,
  177,964 bytes.

Actual formats are Markdown (64 files across both releases) and CSV (4 files). Phase 1
contains overview material, seven policies, seven processes, three interviews, and four
sample labelled claims. Phase 2 contains the expanded corpus: overview material, current
and superseded sources, seven policies, seven processes, ten interviews, ten meetings,
communications, 75 CRM deals, 150 project tasks, and 200 audit events.

Twenty of 22 paths common to both releases are byte-identical. Release duplication is
therefore a provenance/version fact, not independent corroboration. Two common paths
differ and require explicit version comparison during ingestion. Phase 2 includes a
superseded organisation chart and discount policy. The sample claims are illustrative
reference labels, not hidden ground truth.

No PDF, DOCX, JSON, existing claim map beyond the four-row sample, source register,
manually reviewed claim-evidence links, or adjudicated two-reviewer assessments occur in
the supplied releases. Nearby proposal/methodology documents exist outside the corpus but
are not treated as organisational evidence.

## Buildable now and genuine gaps

The full local pipeline can be built for Markdown and CSV, including stable heading,
paragraph, and row locators; checksums; release-aware duplicate detection; source and
evidence ledgers; lexical retrieval; review workflows; deterministic reasoning; graph
provenance; evaluation scaffolding; and challenge fixtures.

Research performance results cannot be reported until humans create independent reviews
and adjudicated references. A second reviewer must never be simulated. PDF/DOCX/JSON
adapters should be implemented only as tested optional adapters or when those formats
enter the configured corpus. Semantic retrieval depends on a locally available embedding
model; it must degrade explicitly to unavailable rather than download silently.

## Data handling decision

Configuration will point at external release directories. Raw files will not be copied,
rewritten, or committed. The application database, extracted units, caches, annotations,
and reports belong under ignored local data/report paths. Every source, including an
excluded technical file, must receive a checksum and registration outcome.
