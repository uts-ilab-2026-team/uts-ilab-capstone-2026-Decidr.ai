"""Citation-backed field comparisons for explicitly identified approval events.

These describe what linked records establish, separately from source credibility.
No policy adoption right, event time or foreign-key connection is inferred.
"""

from decimal import Decimal
import re

_ID = r"[A-Za-z][A-Za-z0-9]*(?:-[0-9]+)+"
_PERSON = r"[A-Za-zÀ-ž][A-Za-zÀ-ž'’-]*(?: [A-Za-zÀ-ž][A-Za-zÀ-ž'’-]*){0,4}?"
_ACTION = rf"(?P<approver>{_PERSON}) (?:approved|authorised|authorized) (?:a |the )?(?P<percentage>\d+(?:\.\d+)?)\s*(?:%|percent|per cent) discount"


def parse_transaction_claim(text):
    text = " ".join(text.strip().rstrip(".").split())
    if re.search(
        r"\b(?:in principle|subject to|if|unless|allegedly|possibly)\b", text, re.IGNORECASE
    ):
        return None
    timing = re.search(
        r" before (?:(?:the )?contract (?:was |is )?signed|signing)$", text, re.IGNORECASE
    )
    if timing:
        text = text[: timing.start()]
    channel = None
    record_id = ""
    # Extract only complete syntactic modifiers; leftover assertions must still
    # match the whole approval sentence, so compound/unsupported claims abstain.
    prefix = re.match(rf"(?:For |On )?({_ID})[,:]? ", text, re.IGNORECASE)
    if prefix:
        record_id, text = prefix[1].upper(), text[prefix.end() :]
    for _ in range(2):
        record = re.search(rf" (?:for|on) ({_ID})$", text, re.IGNORECASE)
        channel_match = re.search(
            r" (?:on|via|in|over) ([A-Za-z][A-Za-z0-9_-]*)$", text, re.IGNORECASE
        )
        if record:
            if record_id:
                return None
            record_id, text = record[1].upper(), text[: record.start()]
        elif channel_match:
            if channel:
                return None
            channel, text = channel_match[1], text[: channel_match.start()]
        else:
            break
    passive = rf"(?:the |a )?(?P<percentage>\d+(?:\.\d+)?)\s*(?:%|percent|per cent) discount(?: for (?P<record_id>{_ID}))? (?:was |is )?(?:approved|authorised|authorized) by (?P<approver>{_PERSON})"
    for pattern in (_ACTION, passive):
        match = re.fullmatch(pattern, text, re.IGNORECASE)
        if not match or Decimal(match["percentage"]) > 100:
            continue
        if re.search(
            r"\b(not|never|if|unless|possibly|allegedly|before|after|signing)\b",
            match["approver"],
            re.IGNORECASE,
        ):
            continue
        embedded_id = match.groupdict().get("record_id")
        if record_id and embedded_id:
            return None
        return {
            "record_id": record_id or (embedded_id or "").upper(),
            "approver": match["approver"],
            "percentage": match["percentage"],
            "before_signing": bool(timing),
            **({"channel": channel} if channel else {}),
        }
    return None
