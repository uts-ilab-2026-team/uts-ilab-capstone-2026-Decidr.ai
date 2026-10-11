"""Complete expense approval requirements; currency symbols are not currency inference."""

from decimal import Decimal
import re

from decidr.approval_propositions import NUMBER, PHRASE, UNSUPPORTED

PATTERN = re.compile(
    rf"expense claims (?:of )?(?P<prefix>over |above |at least |exactly |below |at most )?"
    rf"(?P<currency>[$£€])(?P<amount>{NUMBER})(?P<suffix> or greater| or more| or less)? "
    r"require (?P<written>written )?approval from (?P<approver>.+?) "
    r"(?P<timing>before|after) (?P<event>reimbursement is processed)"
)


def parse_expense_rule(text: str) -> dict | None:
    text = re.sub(r"^\d+[.)]\s+", "", text.casefold().strip())
    text = " ".join(text.replace("**", "").replace("`", "").rstrip(".").split())
    m = PATTERN.fullmatch(text)
    if not m or not PHRASE.fullmatch(m["approver"]) or UNSUPPORTED.search(m["approver"]):
        return None
    boundary = {
        ("over", ""): "gt",
        ("above", ""): "gt",
        ("at least", ""): "ge",
        ("exactly", ""): "eq",
        ("", ""): "eq",
        ("below", ""): "lt",
        ("at most", ""): "le",
        ("", "or greater"): "ge",
        ("", "or more"): "ge",
        ("", "or less"): "le",
    }.get(((m["prefix"] or "").strip(), (m["suffix"] or "").strip()))
    if boundary is None:
        return None
    return {
        "measure": "expense_claim_amount",
        "currency": m["currency"],
        "amount": format(Decimal(m["amount"]).normalize(), "f"),
        "boundary": boundary,
        "approver": m["approver"],
        "written": bool(m["written"]),
        "timing": m["timing"],
        "event": m["event"],
    }


def _interval(rule: dict) -> tuple:
    n, zero, maximum = Decimal(rule["amount"]), Decimal(0), Decimal("Infinity")
    return {
        "gt": (n, False, maximum, False),
        "ge": (n, True, maximum, False),
        "eq": (n, True, n, True),
        "lt": (zero, True, n, False),
        "le": (zero, True, n, True),
    }[rule["boundary"]]


def compare_expense_rules(claim: str, evidence: str) -> dict | None:
    a, b = parse_expense_rule(claim), parse_expense_rule(evidence)
    if a is None or b is None:
        return None
    low, lc, high, hc = _interval(a)
    elow, elc, ehigh, ehc = _interval(b)
    covered = (
        (low > elow or (low == elow and (not lc or elc)))
        and (high < ehigh or (high == ehigh and (not hc or ehc)))
        and not (low == high and not (lc and hc))
        and not (elow == ehigh and not (elc and ehc))
    )
    differences = [k for k in a if a[k] != b[k]]
    return {
        "claim_fields": a,
        "evidence_fields": b,
        "differences": differences,
        "equivalent": not differences,
        "claim_range_covered": covered,
        "evidence_entails_claim": covered and not (set(differences) - {"amount", "boundary"}),
        "method": "expense_approval_fields_v1",
    }


def expense_context_reason(clause: str, rule: dict) -> str | None:
    if clause == "all expense claims must include an itemised receipt":
        return "Receipt requirement retained; it does not remove the approval rule."
    lower = re.fullmatch(
        rf"expense claims of ([$£€])({NUMBER}) or less may be approved by the employee's direct manager",
        clause,
    )
    if lower and lower[1] == rule["currency"]:
        n, threshold = Decimal(lower[2]), Decimal(rule["amount"])
        if (rule["boundary"] == "gt" and n <= threshold) or (
            rule["boundary"] in {"ge", "eq"} and n < threshold
        ):
            return "The lower-amount permission does not overlap the cited approval range."
    return None
