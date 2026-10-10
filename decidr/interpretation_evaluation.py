"""Offline scoring of interpretation outputs against separate references.

This module does not generate interpretations or validate quotations.
Reference labels must never be supplied to the interpreter.
Provisional agreement is not independently measured accuracy.
"""

import argparse
import json
from pathlib import Path

RELATIONSHIPS = {"support", "contradict", "qualify", "context"}
DECISIVE = {"support", "contradict"}
REVIEW_STATES = {"provisional", "adjudicated", "unresolved"}
OUTPUT_STATES = {"classified", "abstained", "error"}


def _index(rows, name):
    indexed = {}
    for row in rows:
        identifier = row.get("case_id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"{name}: case_id must be a nonblank string")
        if identifier in indexed:
            raise ValueError(f"{name}: duplicate case_id {identifier}")
        indexed[identifier] = row
    return indexed


def evaluate(references, predictions):
    """Score one dataset version and one method run.

    Each prediction must carry the fingerprint of its exact interpretation input.
    The runner that creates predictions is responsible for computing that hash.
    """
    refs = _index(references, "references")
    outputs = _index(predictions, "predictions")
    if not refs:
        raise ValueError("Reference set must not be empty")

    if outputs.keys() - refs.keys():
        raise ValueError("Predictions contain unknown case IDs")

    versions = {row.get("dataset_version") for row in refs.values()}
    if len(versions) != 1 or not next(iter(versions)):
        raise ValueError("References must identify one dataset version")
    dataset_version = next(iter(versions))

    runs = set()
    for identifier, row in refs.items():
        if row.get("review_status") not in REVIEW_STATES:
            raise ValueError(f"{identifier}: invalid review_status")
        expected = row.get("expected_relationship")
        if row["review_status"] == "unresolved":
            if expected is not None:
                raise ValueError(f"{identifier}: unresolved reference needs null label")
        elif expected not in RELATIONSHIPS:
            raise ValueError(f"{identifier}: invalid expected_relationship")
        fingerprint = row.get("input_sha256", "")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)
        ):
            raise ValueError(f"{identifier}: invalid input_sha256")

    for identifier, output in outputs.items():
        if output.get("dataset_version") != dataset_version:
            raise ValueError(f"{identifier}: dataset version mismatch")
        if output.get("input_sha256") != refs[identifier]["input_sha256"]:
            raise ValueError(f"{identifier}: input fingerprint mismatch")
        method = output.get("method_version")
        if not isinstance(method, str) or not method.strip():
            raise ValueError(f"{identifier}: missing method_version")
        runs.add(method)
        status = output.get("status")
        if status not in OUTPUT_STATES:
            raise ValueError(f"{identifier}: invalid output status")
        relationship = output.get("relationship")
        if status == "classified":
            if relationship not in RELATIONSHIPS:
                raise ValueError(f"{identifier}: classified output needs a relationship")
        elif relationship is not None:
            raise ValueError(f"{identifier}: nonclassified output needs null relationship")

    if len(runs) > 1:
        raise ValueError("Score each method version separately")

    cohorts = {}
    details = []
    for review_status in sorted(REVIEW_STATES):
        selected = [row for row in refs.values() if row["review_status"] == review_status]
        counts = {
            "cases": len(selected),
            "classified": 0,
            "abstained": 0,
            "errors": 0,
            "missing_outputs": 0,
            "matches": 0,
            "support_contradiction_reversals": 0,
            "false_decisive": 0,
            "missed_decisive": 0,
            "other_disagreements": 0,
        }
        for ref in selected:
            output = outputs.get(ref["case_id"])
            status = output["status"] if output else "missing"
            actual = output.get("relationship") if output else None
            expected = ref.get("expected_relationship")
            counts[
                {
                    "classified": "classified",
                    "abstained": "abstained",
                    "error": "errors",
                    "missing": "missing_outputs",
                }[status]
            ] += 1

            if review_status == "unresolved":
                category = "unscored"
            elif status != "classified":
                category = status
                if expected in DECISIVE:
                    counts["missed_decisive"] += 1
            elif actual == expected:
                category = "match"
                counts["matches"] += 1
            elif actual in DECISIVE and expected in DECISIVE:
                category = "support_contradiction_reversal"
                counts["support_contradiction_reversals"] += 1
            elif actual in DECISIVE:
                category = "false_decisive"
                counts["false_decisive"] += 1
            elif expected in DECISIVE:
                category = "missed_decisive"
                counts["missed_decisive"] += 1
            else:
                category = "other_disagreement"
                counts["other_disagreements"] += 1

            details.append(
                {
                    "case_id": ref["case_id"],
                    "review_status": review_status,
                    "expected": expected,
                    "actual": actual,
                    "output_status": status,
                    "category": category,
                }
            )

        total = counts["cases"]
        counts["coverage"] = counts["classified"] / total if total else None
        counts["matches_per_case"] = (
            counts["matches"] / total if total and review_status != "unresolved" else None
        )
        if review_status == "unresolved":
            for key in (
                "matches",
                "support_contradiction_reversals",
                "false_decisive",
                "missed_decisive",
                "other_disagreements",
            ):
                counts[key] = None
        cohorts[review_status] = counts

    return {
        "dataset_version": dataset_version,
        "method_version": next(iter(runs)) if runs else None,
        "cohorts": cohorts,
        "cases": sorted(details, key=lambda row: row["case_id"]),
        "limitations": [
            "Provisional agreement is not independent accuracy.",
            "Citation validity and interpretation correctness are separate checks.",
            "Missing outputs and processing errors are not deliberate abstentions.",
            "These results do not measure retrieval or final-verdict accuracy.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path, help="JSON array of reference records")
    parser.add_argument("predictions", type=Path, help="JSON array from one method run")
    args = parser.parse_args()
    references = json.loads(args.references.read_text(encoding="utf-8"))
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(references, predictions), indent=2))


if __name__ == "__main__":
    main()
