from pathlib import Path

from decidr.config import PROCESSED_DATA_DIR, PROJ_ROOT, RAW_DATA_DIR


def test_dataset_directories_are_anchored_to_project_root() -> None:
    """Keep the default data locations inside the checked-out repository."""
    assert PROJ_ROOT == Path(__file__).resolve().parents[1]
    assert RAW_DATA_DIR == PROJ_ROOT / "data" / "raw"
    assert PROCESSED_DATA_DIR == PROJ_ROOT / "data" / "processed"
