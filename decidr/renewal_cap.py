"""Bounded renewal cap comparison, preserving the contracted-rate basis."""

from decimal import Decimal
import re

PATTERN = re.compile(
    r"(?:renewal discounts are capped at|the renewal discount cap is) "
    r"(?P<cap>(?:0|[1-9]\d*)(?:\.\d+)?)% off the account's current contracted rate"
)


def parse_renewal_cap(text: str) -> dict | None:
    text = re.sub(r"^\d+[.)]\s+", "", text.casefold().strip())
    text = " ".join(text.replace("**", "").replace("`", "").replace("’", "'").rstrip(".").split())
    match = PATTERN.fullmatch(text)
    if not match or not 0 <= Decimal(match["cap"]) <= 100:
        return None
    value = match["cap"]
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return {
        "measure": "renewal_discount_off_current_contracted_rate",
        "scope": "renewal discounts",
        "cap_percentage": value,
    }


def compare_renewal_caps(claim: str, evidence: str) -> dict | None:
    a, b = parse_renewal_cap(claim), parse_renewal_cap(evidence)
    if a is None or b is None:
        return None
    differences = [k for k in a if a[k] != b[k]]
    # A statement of the cap identifies the limit, not merely a permitted subrange.
    return {
        "claim_fields": a,
        "evidence_fields": b,
        "differences": differences,
        "equivalent": not differences,
        "claim_range_covered": not differences,
        "evidence_entails_claim": not differences,
        "method": "renewal_cap_fields_v1",
    }


def renewal_context_reason(clause: str) -> str | None:
    if clause == "no exceptions to the renewal discount cap are provided for under this policy":
        return "The explicit no-exceptions clause is retained; it does not weaken the cap."
    if (
        clause
        == "renewal discount decisions are made by the account executive responsible for the account, in consultation with customer success on relationship health"
    ):
        return "The decision and consultation requirement is retained; it does not authorise exceeding the cap."
    return None
