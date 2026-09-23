"""Query-owned constraints and bounded question semantics, independent of candidates."""

from dataclasses import asdict, dataclass
from decimal import Decimal
import re


@dataclass(frozen=True)
class Threshold:
    value: str
    operator: str = "eq"

    def interval(self):
        value = Decimal(self.value)
        return {
            "eq": (value, True, value, True),
            "gt": (value, False, Decimal("Infinity"), False),
            "ge": (value, True, Decimal("Infinity"), False),
            "lt": (Decimal("-Infinity"), False, value, False),
            "le": (Decimal("-Infinity"), False, value, True),
        }[self.operator]


def threshold(text: str) -> Threshold | None:
    match = re.search(
        r"(?:(greater than or equal to|less than or equal to|at least|at most|greater than|less than|above|over|below|under|>=|<=|>|<)\s*)?"
        r"(\d+(?:\.\d+)?)\s*%(?:\s+(or greater|or more|or less))?",
        text.casefold(),
    )
    if not match:
        return None
    operators = {
        "greater than or equal to": "ge", "at least": "ge", ">=": "ge",
        "less than or equal to": "le", "at most": "le", "<=": "le",
        "greater than": "gt", "above": "gt", "over": "gt", ">": "gt",
        "less than": "lt", "below": "lt", "under": "lt", "<": "lt",
        "or greater": "ge", "or more": "ge", "or less": "le",
    }
    return Threshold(match[2], operators.get(match[3] or match[1], "eq"))


def threshold_comparison(user: Threshold, policy: Threshold) -> dict:
    lo, li, hi, hi_i = user.interval()
    plo, pli, phi, phi_i = policy.interval()
    contained = (lo > plo or (lo == plo and (not li or pli))) and (
        hi < phi or (hi == phi and (not hi_i or phi_i))
    )
    a, b = Decimal(user.value), Decimal(policy.value)
    return {
        "user": asdict(user), "policy": asdict(policy),
        "relationship": "below" if a < b else "meets" if a == b else "exceeds",
        "within_policy_range": contained,
    }


def question_condition(text: str) -> str:
    """What a 'yes' asserts. Unknown/negative interrogatives stay declarative."""
    lower = text.casefold().strip()
    if text.count("?") > 1 or re.search(r"\b(?:or|and|not|no|unless)\b|;", lower):
        return "declarative"
    if re.match(r"(?:can|may)\b", lower) and "approve" in lower and "without" in lower:
        return "permission_without_approval"
    if re.match(r"(?:do i|do we|does .+?)\s+(?:need|require)\b", lower):
        return "approval_required"
    return "declarative"


def direct_answer(condition: str, proposition_polarity: str, verdict: str) -> str:
    if condition == "declarative" or verdict not in {"Supported", "Contradicted"}:
        return ""
    proposition_requires = proposition_polarity == "positive"
    question_requires = condition == "approval_required"
    yes = (verdict == "Supported") == (proposition_requires == question_requires)
    return "Yes. " if yes else "No. "
