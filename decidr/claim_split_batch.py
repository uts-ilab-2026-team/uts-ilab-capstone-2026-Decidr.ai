"""Run the claim splitter over the benchmark claims and summarise results.

Loads unique ``claim_text`` values from the development input set, runs ``split_claim`` on each
(needs a local Ollama model), and prints per-claim status plus a summary of how many validated
vs degraded (flagged undecisive) vs errored.

    DECIDR_ASSESSMENT_PROVIDER=ollama DECIDR_ASSESSMENT_MODEL=llama3.1:8b \
        uv run python -m decidr.claim_split_batch
"""

from __future__ import annotations

from datetime import date
import glob
import json
from pathlib import Path

from decidr.claim_interpreter import ProviderError, get_provider
from decidr.claim_split import split_claim

REPO_ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 7, 31)


def unique_claims() -> list[str]:
    """Collect every unique claim_text across all evaluation/*.json sets."""
    seen: dict[str, None] = {}
    for path in sorted(glob.glob(str(REPO_ROOT / "evaluation/**/*.json"), recursive=True)):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records = data if isinstance(data, list) else [data]
        for record in records:
            if not isinstance(record, dict):
                continue
            inp = record.get("input") if isinstance(record.get("input"), dict) else record
            claim = inp.get("claim_text") if isinstance(inp, dict) else None
            if isinstance(claim, str) and claim.strip():
                seen.setdefault(claim, None)
    return list(seen)


def main() -> None:
    try:
        provider = get_provider()
    except ProviderError as error:
        print(f"no local provider available: {error}")
        return

    claims = unique_claims()
    print(f"{len(claims)} unique claims\n")
    tally = {"validated": 0, "degraded_undecisive": 0, "error": 0}

    for index, claim in enumerate(claims, start=1):
        try:
            result = split_claim(claim, AS_OF, provider)
            status = result["semantic_validation"]["status"]
            tally[status] = tally.get(status, 0) + 1
            preds = ", ".join(
                f"{c['id']}={c.get('predicate')!r}"
                + ("!" if c.get("label_status") == "undecisive" else "")
                for c in result["components"]
            )
            print(f"[{index:2}] {status:20} {claim[:70]}")
            print(f"      target={result['target']}  {preds}")
        except ProviderError as error:
            tally["error"] += 1
            print(f"[{index:2}] {'ERROR':20} {claim[:70]}")
            print(f"      {error}")

    print("\nsummary:")
    for key, count in tally.items():
        print(f"  {key:20} {count}")


if __name__ == "__main__":
    main()
