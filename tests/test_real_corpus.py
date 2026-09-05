from collections.abc import Iterable
from pathlib import Path

import pytest

from decidr.config import PHASE1_DATA_DIR, PHASE2_DATA_DIR
from decidr.ingestion import ingest


@pytest.mark.skipif(
    not PHASE1_DATA_DIR.is_dir() or not PHASE2_DATA_DIR.is_dir(),
    reason="Northfield releases are not installed on this machine",
)
def test_real_corpus_read_only_smoke_test():
    roots = {"phase1": PHASE1_DATA_DIR, "phase2": PHASE2_DATA_DIR}
    before = _file_state(roots.values())

    result = ingest(roots)

    assert len(result.sources) == 68
    assert len(result.evidence) > 425
    assert result.warnings == []
    assert sum(source.duplicate_group is not None for source in result.sources) >= 40
    assert _file_state(roots.values()) == before


def _file_state(roots: Iterable[Path]) -> dict[str, tuple[int, int]]:
    state = {}
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                state[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return state
