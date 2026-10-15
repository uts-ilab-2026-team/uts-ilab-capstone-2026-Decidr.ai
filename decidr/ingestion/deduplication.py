"""Post-scan duplicate, supersession, and near-duplicate linking across sources."""

from collections import defaultdict
from pathlib import Path
import re

from decidr.constants import SOURCE_CODE_PATTERN
from decidr.retrieval_models import Source


def _apply_duplicate_and_version_links(sources: list[Source]) -> None:
    by_checksum: dict[str, list[Source]] = defaultdict(list)
    by_code: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        by_checksum[source.checksum].append(source)
        by_code[source.source_id.split(":", 1)[1]].append(source)
    for checksum, matches in by_checksum.items():
        if len(matches) > 1:
            group = f"sha256:{checksum}"
            for source in matches:
                source.duplicate_group = group
    for source in sources:
        declared = re.search(r"declared_supersedes=([^;]+)", source.metadata_notes or "")
        if not declared:
            continue
        predecessor_code = SOURCE_CODE_PATTERN.search(declared.group(1))
        if not predecessor_code:
            continue
        candidates = by_code.get(predecessor_code.group(), [])
        same_release = [
            item
            for item in candidates
            if item.source_id.split(":", 1)[0] == source.source_id.split(":", 1)[0]
        ]
        if same_release:
            predecessor = same_release[0]
            source.predecessor_source_id = predecessor.source_id
            predecessor.successor_source_id = source.source_id


def _normalised_shingles(path: Path, width: int = 5) -> set[tuple[str, ...]]:
    text = path.read_text(encoding="utf-8-sig").casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    return {tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def _apply_near_duplicate_signals(
    sources: list[Source], source_paths: dict[str, Path], threshold: float = 0.92
) -> None:
    """Flag highly similar documents for review without asserting dependence."""
    candidates = [
        source
        for source in sources
        if source.ingestion_status != "excluded"
        and source_paths[source.source_id].suffix.casefold() == ".md"
    ]
    shingles = {
        source.source_id: _normalised_shingles(source_paths[source.source_id])
        for source in candidates
    }
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if left.checksum == right.checksum or left.source_type != right.source_type:
                continue
            left_set = shingles[left.source_id]
            right_set = shingles[right.source_id]
            if not left_set or not right_set:
                continue
            similarity = len(left_set & right_set) / len(left_set | right_set)
            if similarity >= threshold:
                for source, other in ((left, right), (right, left)):
                    signal = f"near_duplicate_candidate={other.source_id}:{similarity:.3f}"
                    source.metadata_notes = f"{source.metadata_notes}; {signal}"
