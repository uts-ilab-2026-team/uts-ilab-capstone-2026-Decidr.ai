"""Bounded comparison of complete percentage-discount approval requirements.

Two explicit grammatical forms, arbitrary approver/scope/threshold/event values.
This is field comparison, not general entailment or organisational role resolution.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal
import re


@dataclass(frozen=True, slots=True)
class ApprovalRule:
    approver: str
    deal_scope: str
    percentage: str
    boundary: str
    written: bool
    timing: str
    event: str
    measure: str = "discount_off_list_price"

    def model_dump(self) -> dict:
        return asdict(self)


NUMBER = r"(?:0|[1-9]\d*)(?:\.\d+)?"
THRESHOLD = rf"(?:(?:exactly|at least|above|below|at most) )?{NUMBER}\s*%(?: or (?:greater|more|less|fewer))?"
PATTERNS = (
    re.compile(
        rf"any discount of (?P<threshold>{THRESHOLD}) off list price on a "
        r"(?P<scope>.+?) deal requires (?P<written>written )?approval from "
        r"(?P<approver>.+?) (?P<timing>before|after) the deal is marked (?P<event>.+)"
    ),
    re.compile(
        r"(?P<approver>.+?) must (?:give|provide) (?P<written>written )?approval "
        r"(?P<timing>before|after) (?:any|every) (?P<scope>.+?) deal with a discount of "
        rf"(?P<threshold>{THRESHOLD}) off list price is marked (?P<event>.+)"
    ),
)
# Nested propositions or restrictions cannot be swallowed into a free-text field.
UNSUPPORTED = re.compile(
    r"\b(if|unless|except|provided|when|whether|not|never|without|may|might|"
    r"must|shall|requires?|before|after|said|reported|told|according|only|"
    r"some|sometimes|either|neither|or|but|although|until)\b"
)
PHRASE = re.compile(r"[\w][\w &/'()-]*")


def parse_approval_rule(text: str) -> ApprovalRule | None:
    """Return all fields or abstain; never invent omitted conditions or actors."""
    text = text.casefold().strip()
    text = re.sub(r"^\d+[.)]\s+", "", text)
    text = " ".join(text.replace("**", "").replace("`", "").rstrip(".").split())
    match = next((m for p in PATTERNS if (m := p.fullmatch(text))), None)
    if match is None:
        return None
    fields = [match[name] for name in ("approver", "scope", "event")]
    if any(not PHRASE.fullmatch(value) or UNSUPPORTED.search(value) for value in fields):
        return None
    threshold = match["threshold"]
    number_match = re.search(NUMBER, threshold)
    if number_match is None:
        return None
    percentage = Decimal(number_match[0])
    if not 0 <= percentage <= 100:
        return None
    prefix, suffix = (
        threshold[: number_match.start()].strip(),
        threshold[number_match.end() :].strip(),
    )
    operators = {
        ("", "%"): "eq",
        ("exactly", "%"): "eq",
        ("at least", "%"): "ge",
        ("", "% or greater"): "ge",
        ("", "% or more"): "ge",
        ("above", "%"): "gt",
        ("below", "%"): "lt",
        ("at most", "%"): "le",
        ("", "% or less"): "le",
        ("", "% or fewer"): "le",
    }
    boundary = operators.get((prefix, suffix))
    if boundary is None:
        return None
    return ApprovalRule(
        approver=match["approver"],
        deal_scope=match["scope"],
        percentage=format(percentage.normalize(), "f"),
        boundary=boundary,
        written=bool(match["written"]),
        timing=match["timing"],
        event=match["event"],
    )


def _range(rule: ApprovalRule) -> tuple[Decimal, bool, Decimal, bool]:
    value = Decimal(rule.percentage)
    zero, maximum = Decimal(0), Decimal(100)
    return {
        "eq": (value, True, value, True),
        "ge": (value, True, maximum, True),
        "gt": (value, False, maximum, True),
        "le": (zero, True, value, True),
        "lt": (zero, True, value, False),
    }[rule.boundary]


def _range_covers(evidence: ApprovalRule, claim: ApprovalRule) -> bool:
    low, low_closed, high, high_closed = _range(claim)
    e_low, e_low_closed, e_high, e_high_closed = _range(evidence)
    if low == high and not (low_closed and high_closed):
        return False  # Empty discount ranges cannot supply meaningful support.
    if e_low == e_high and not (e_low_closed and e_high_closed):
        return False
    lower = low > e_low or (low == e_low and (not low_closed or e_low_closed))
    upper = high < e_high or (high == e_high and (not high_closed or e_high_closed))
    return lower and upper


def compare_approval_rules(left: str, right: str) -> dict | None:
    """Expose field agreement; differences alone never establish contradiction."""
    claim, evidence = parse_approval_rule(left), parse_approval_rule(right)
    if claim is None or evidence is None:
        return None
    a, b = claim.model_dump(), evidence.model_dump()
    differences = [key for key in a if a[key] != b[key]]
    covered = _range_covers(evidence, claim)
    other_fields_match = not (set(differences) - {"percentage", "boundary"})
    return {
        "claim_fields": a,
        "evidence_fields": b,
        "differences": differences,
        "equivalent": not differences,
        "claim_range_covered": covered,
        "evidence_entails_claim": covered and other_fields_match,
        "method": "approval_fields_v2",
    }
