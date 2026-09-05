from loguru import logger
import typer

from decidr.config import DATABASE_PATH, PHASE1_DATA_DIR, PHASE2_DATA_DIR, REPORTS_DIR
from decidr.ingestion import ingest, write_exports

app = typer.Typer()


@app.command()
def main(
    phase1: str = str(PHASE1_DATA_DIR),
    phase2: str = str(PHASE2_DATA_DIR),
    database: str = str(DATABASE_PATH),
    output: str = str(REPORTS_DIR / "ingestion"),
) -> None:
    """Ingest configured releases into the evidence ledger and write registers."""
    from pathlib import Path

    releases = {"phase1": Path(phase1), "phase2": Path(phase2)}
    logger.info("Scanning configured releases without modifying raw data")
    result = ingest(releases, Path(database))
    write_exports(result, Path(output))
    logger.success(
        "Registered {} sources and {} evidence units; fingerprint={}",
        len(result.sources),
        len(result.evidence),
        result.dataset_fingerprint,
    )
    for warning in result.warnings:
        logger.warning(warning)


if __name__ == "__main__":
    app()
