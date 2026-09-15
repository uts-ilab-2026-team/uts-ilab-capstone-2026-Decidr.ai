from decidr.ingestion import ingest


def test_ingestion_ignores_windows_zone_identifier_sidecars(tmp_path):
    root = tmp_path / "phase1"
    root.mkdir()

    (root / "POL-01.md").write_text(
        "# Discount Policy\n\nDiscounts require approval.",
        encoding="utf-8",
    )
    (root / "POL-01.md:Zone.Identifier").write_text(
        "[ZoneTransfer]\nZoneId=3",
        encoding="utf-8",
    )

    result = ingest({"phase1": root})

    assert len(result.sources) == 1
    assert result.sources[0].source_id == "phase1:POL-01"
    assert all(
        "Zone.Identifier" not in source.original_file_path
        for source in result.sources
    )
