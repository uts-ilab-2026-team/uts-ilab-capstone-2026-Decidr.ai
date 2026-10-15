"""Deterministic numeric/threshold primitives: extraction, units and boundaries."""

from decimal import Decimal
import json
import re

_IDENTIFIERS = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-\d+[A-Za-z0-9_-]*\b")
_DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBERS = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?!\w|\.\d)")
_WORD_NUMBERS = dict(
    zip(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
        ],
        [*range(21), 30, 40, 50, 60, 70, 80, 90],
        strict=True,
    )
)


def _numbers(text: str) -> set[Decimal]:
    text = _IDENTIFIERS.sub("", _DATES.sub("", text))
    values = {Decimal(m.group().replace(",", "")) for m in _NUMBERS.finditer(text)}
    words = "|".join(_WORD_NUMBERS) + "|hundred|thousand|million"
    for match in re.finditer(
        r"\b(?:" + words + r")(?:[ -]+(?:and[ -]+)?(?:" + words + r"))*\b", text, re.IGNORECASE
    ):
        total, part = 0, 0
        for word in re.findall(r"\w+", match.group().lower()):
            if word in _WORD_NUMBERS:
                part += _WORD_NUMBERS[word]
            elif word == "hundred":
                part = max(1, part) * 100
            elif word in {"thousand", "million"}:
                total += max(1, part) * (1000 if word == "thousand" else 1_000_000)
                part = 0
        values.add(Decimal(total + part))
    return values


def _boundary(text: str, value: str) -> str | None:
    escaped = re.escape(value)
    unit = r"\s*(?:%|percent|percentage points?|dollars?)?"
    before = {
        "gte": r"(?:at least|no less than|>=|≥)",
        "lte": r"(?:at most|no more than|up to|<=|≤)",
        "gt": r"(?:above|over|greater than|more than|>)",
        "lt": r"(?:under|below|less than|<)",
    }
    for op, pattern in before.items():
        if re.search(pattern + r"\s*\$?" + escaped + r"(?![\d.])", text, re.IGNORECASE):
            return op
    if re.search(escaped + unit + r"\s+(?:or|and) (?:more|greater|above)", text, re.IGNORECASE):
        return "gte"
    if re.search(escaped + unit + r"\s+(?:or|and) (?:less|fewer|below)", text, re.IGNORECASE):
        return "lte"
    return None


_CURRENCY_UNITS = {
    "$": "unspecified",
    "dollar": "unspecified",
    "dollars": "unspecified",
    "usd": "USD",
    "us$": "USD",
    "aud": "AUD",
    "a$": "AUD",
    "au$": "AUD",
    "cad": "CAD",
    "c$": "CAD",
    "ca$": "CAD",
    "nzd": "NZD",
    "nz$": "NZD",
    "eur": "EUR",
    "€": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "jpy": "JPY",
    "chf": "CHF",
    "cny": "CNY",
    "inr": "INR",
    "sgd": "SGD",
    "hkd": "HKD",
}
_DURATION_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}


def _numeric_unit(unit: str) -> tuple[str, Decimal] | None:
    normalized = unit.strip().lower()
    if normalized in {"%", "percent", "percentage", "percentage points"}:
        return "percent", Decimal(1)
    if normalized in _CURRENCY_UNITS:
        return "currency:" + _CURRENCY_UNITS[normalized], Decimal(1)
    if normalized in _DURATION_UNITS:
        return "fixed_duration", Decimal(_DURATION_UNITS[normalized])
    if normalized in {"business day", "business days", "working day", "working days"}:
        return "business_days", Decimal(1)
    return None


def _quantity_mentions(text: str) -> list[tuple[Decimal, str, int, int]]:
    words = "|".join(_WORD_NUMBERS) + "|hundred|thousand|million"
    numeric = (
        r"(?:-?\d+(?:,\d{3})*(?:\.\d+)?|(?:"
        + words
        + r")(?:[ -]+(?:and[ -]+)?(?:"
        + words
        + r"))*)"
    )
    currencies = "|".join(
        re.escape(unit) for unit in sorted(_CURRENCY_UNITS, key=len, reverse=True)
    )
    durations = "|".join(
        re.escape(unit) for unit in sorted(_DURATION_UNITS, key=len, reverse=True)
    )
    suffixes = (
        r"business days?|working days?|percentage points|percent|%|" + currencies + "|" + durations
    )
    patterns = [
        r"(?<![\w.])(?P<value>" + numeric + r")\s*(?P<unit>" + suffixes + r")(?!\w)",
        r"(?<!\w)(?P<unit>" + currencies + r")\s*(?P<value>" + numeric + r")(?!\w|\.\d)",
    ]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            values = _numbers(match["value"])
            unit = _numeric_unit(match["unit"])
            if len(values) == 1 and unit:
                dimension, multiplier = unit
                found.append(
                    (next(iter(values)) * multiplier, dimension, match.start(), match.end())
                )
    return found


def _scalar_observations(text: str) -> list[tuple[Decimal, str]]:
    found = [(value, dimension) for value, dimension, _, _ in _quantity_mentions(text)]
    try:
        row = json.loads(text)
        if isinstance(row, dict):
            for key, value in row.items():
                if re.search(r"(?:_pct|_percent|percentage)$", key) and re.fullmatch(
                    r"-?\d+(?:\.\d+)?", str(value)
                ):
                    found.append((Decimal(str(value)), "percent"))
    except (ValueError, TypeError):
        pass
    return found


_APPROVAL_WORD = r"(?:approv\w*|authori[sz]\w*|permission|consent|sign[ -]?off)"
_THRESHOLD_ASSERTION = r"\b(?:threshold|cut[ -]?off|limit)\b[^.!?;]*\b(?:is|was|are|were|equals?|stands? at|stood at)\b"


def _normative_threshold_claim(claim: str) -> bool:
    """Recognize unqualified statements of a rule's scalar approval threshold only."""
    text = re.sub(r"[*`]", "", claim)
    if re.search(
        r"\b(?:in practice|actual(?:ly)?|observed|reported|recorded|said|says|stated|"
        r"according to|claims? that|told|asserts?|interview|email|message|configuration|configured|setting|"
        r"stored|database|dashboard|software|system|field|display(?:ed|s)?|accurate|"
        r"changed|raised|lowered|reduced|increased|adopted|introduced|approved|"
        r"authori[sz]ed|granted|signed off)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return bool(
        _quantity_mentions(text)
        and re.search(r"\b" + _APPROVAL_WORD + r"\b", text, re.IGNORECASE)
        and re.search(_THRESHOLD_ASSERTION, text, re.IGNORECASE)
    )
