# Decision 0001: ingest client releases in place

Date: 2026-09-03

Status: accepted

The Phase 1 and Phase 2 Northfield releases remain outside version control and are read
in place through configurable paths. The ledger and exports are reproducible derived
artifacts and are ignored by Git.

This avoids duplicating raw evidence, preserves release boundaries, and lets checksums
detect identical content across releases. Source identity combines release and document
code because the same document can legitimately occur in both releases. Exact checksum
groups prevent cross-release copies from becoming independent corroboration. Near-copy
similarity is only a reviewer signal; dependence is not asserted automatically.

Markdown evidence uses its heading path plus an ordinal block locator. CSV evidence uses
the physical row number and first-column record identifier. These locators are designed
for reconstruction within a fingerprinted release; a changed release receives a changed
dataset fingerprint.
