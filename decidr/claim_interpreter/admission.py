"""Evidence-admission exclusion rules (never invent the opposite relationship)."""

from decimal import Decimal
import re

from decidr.claim_interpreter.text_numeric import (
    _APPROVAL_WORD,
    _THRESHOLD_ASSERTION,
    _normative_threshold_claim,
    _numeric_unit,
    _quantity_mentions,
    _scalar_observations,
)
from decidr.claim_spans import exact_evidence_span


def _threshold_support_exclusion(component: dict, quotation: str) -> str | None:
    claim = component.get("claim_quote", component["text"])
    if not _normative_threshold_claim(claim):
        return None
    clause = re.search(_THRESHOLD_ASSERTION, re.sub(r"[*`]", "", claim), re.IGNORECASE)
    quantities = [
        (value, dimension)
        for value, dimension, start, _ in _quantity_mentions(re.sub(r"[*`]", "", claim))
        if start >= clause.end()
    ]
    if not quantities:
        return None
    value, dimension = quantities[0]
    if any(q["comparator"] in {"approx", "range"} for q in component.get("quantities", [])):
        return None
    observations = _scalar_observations(quotation)
    comparable = {number for number, kind in observations if kind == dimension}
    if comparable and value not in comparable:
        return (
            "The passage states different quantities for the asserted scalar approval cutoff. "
            "An overlapping trigger range does not establish equality of that cutoff. "
            "This excludes support only; it does not establish a contradiction."
        )
    if (
        not comparable
        and dimension.startswith("currency:")
        and dimension != "currency:unspecified"
    ):
        currencies = {kind for _, kind in observations if kind.startswith("currency:")}
        if currencies and "currency:unspecified" not in currencies:
            return (
                "The passage supplies only a different explicitly named currency for the scalar "
                "approval cutoff. Support requires a same-currency basis; no exchange is assumed."
            )
    return None


def _approval_event_support_exclusion(
    component: dict, quotation: str, target: str | None
) -> str | None:
    if target != "event" or not re.search(
        r"\b(?:approved|authori[sz]ed|adopted|ratified|signed[ -]?off)\b|"
        r"\b(?:gave|granted|received|completed)\b.{0,35}\bapproval\b|"
        r"\bapproval\b.{0,20}\b(?:occurred|completed|given|granted)\b",
        component.get("predicate", ""),
        re.IGNORECASE,
    ):
        return None
    text = re.sub(r"[*`]", "", quotation)
    lines = [
        re.sub(r"^(?:(?:[-+*]|\d+[.)])\s+|>\s*)+", "", line.strip())
        for line in text.splitlines()
        if line.strip()
    ]
    if lines and all(
        re.match(
            r"^(?:From|To|Cc|Bcc|Sent|Date|Timestamp|Subject|Reply-To|Message-ID|Participants)\s*:",
            line,
            re.IGNORECASE,
        )
        for line in lines
    ):
        return (
            "Communication headers establish message metadata, not a substantive completed "
            "approval event. Sender, timestamp, title and subject alone cannot supply the missing approval."
        )
    formal_pattern = (
        r"\b(?:formally|officially)\s+(?:(?:been|was|has|had|not|never)\s+)*"
        r"(?:approved|adopted|ratified|authori[sz]ed|signed[ -]?off)\b|"
        r"\b(?:gave|granted|received|completed|obtained|documented|recorded)\s+(?:(?:a|the)\s+)?"
        r"(?:formal|official)\s+(?:approval|adoption|ratification|authori[sz]ation|sign[ -]?off)\b|"
        r"\b(?:formal|official)\s+(?:approval|adoption|ratification|authori[sz]ation|sign[ -]?off)\s+"
        r"(?:(?:of|for)\s+[^.!?;\n]{1,100}?\s+)?"
        r"(?:was|is|has been|had been|occurred|took place|given|granted|recorded|confirmed)\b|"
        r"\b(?:adopted|ratified)\b|"
        r"\b(?:approved|signed[ -]?off)\b[^.!?;\n]{0,60}\bas\s+(?:the\s+)?official\s+"
        r"(?:process|policy|procedure|rule|standard|protocol)(?=\s*(?:[.,;:]|$))"
    )
    formal_claim = re.search(formal_pattern, component["text"], re.IGNORECASE)
    formal_indication = re.search(formal_pattern, text, re.IGNORECASE)
    if formal_claim and not formal_indication:
        return (
            "The passage does not establish the specifically claimed formal approval or adoption. "
            "Unspecified sign-off, informal/pilot permission and role titles do not supply that distinction."
        )
    return None


def approval_boundary_exclusion(component: dict, finding: dict, target: str | None) -> str | None:
    if finding.get("relationship") != "supports":
        return None
    if target not in {"formal_requirement", "formal_authority"}:
        return
    if target != "formal_authority" and not re.search(
        r"\b(?:approv\w*|authorit\w*|authori[sz]\w*|permission|consent|sign.off)\b",
        component["predicate"] + " " + component["text"],
        re.IGNORECASE,
    ):
        return
    text = re.sub(r"[*`]", "", finding["quotation"])
    mentions = _quantity_mentions(text)
    for quantity in component["quantities"]:
        if quantity["comparator"] not in {"gte", "lte"}:
            continue
        unit = _numeric_unit(quantity["unit"])
        if not unit or not (unit[0] == "percent" or unit[0].startswith("currency:")):
            continue
        dimension, multiplier = unit
        value = Decimal(quantity["value"]) * multiplier
        matching = [mention for mention in mentions if mention[1] == dimension]
        if not matching or {mention[0] for mention in matching} != {value}:
            continue
        boundaries = set()
        for _, _, start, end in matching:
            before, after = text[:start], text[end:]
            for comparator, pattern in {
                "gte": r"(?:at least|no less than|>=|≥)\s*$",
                "lte": r"(?:at most|no more than|up to|<=|≤)\s*$",
                "gt": r"(?:\babove|\bover|greater than|more than|(?<![<>=])>)\s*$",
                "lt": r"(?:\bunder|\bbelow|less than|(?<![<>=])<)\s*$",
            }.items():
                if re.search(pattern, before, re.IGNORECASE):
                    boundaries.add(comparator)
            if re.match(r"\s+(?:or|and) (?:more|greater|above)\b", after, re.IGNORECASE):
                boundaries.add("gte")
            if re.match(r"\s+(?:or|and) (?:less|fewer|below)\b", after, re.IGNORECASE):
                boundaries.add("lte")
        inclusive = quantity["comparator"]
        if {"gte": "gt", "lte": "lt"}[inclusive] in boundaries and inclusive not in boundaries:
            return (
                "Finding for component "
                + component["id"]
                + " and passage "
                + finding["evidence_id"]
                + " uses an exclusive approval/authority trigger to support an inclusive claim at "
                + quantity["value"]
                + " "
                + quantity["unit"]
                + "; that boundary is not covered."
            )


def _uncertainty_only(quote: str) -> bool:
    uncertainty = r"\b(?:no idea|(?:do|does|did) not know|don['’]t know|doesn['’]t know|didn['’]t know|not sure|uncertain|unclear|cannot confirm|can['’]t confirm|unable to confirm)\b"
    if not re.search(uncertainty, quote, re.IGNORECASE):
        return False
    if not re.match(
        r"^[\s*\"'“‘]*(?:whether\b|(?:(?:I|we|he|she|they|it)\s+"
        r"(?:(?:have|has|am|are|is|was|were)\s+)?)?" + uncertainty + r")",
        quote,
        re.IGNORECASE,
    ):
        return False
    if re.search(uncertainty + r"\s+(?:why|how)\b", quote, re.IGNORECASE):
        return False
    # The exact grounding may contain a separate actual observation as well as uncertainty.
    clauses = [
        part.strip()
        for part in re.split(r"[.;!?]|\bbut\b|\bhowever\b", quote, flags=re.IGNORECASE)
        if part.strip()
    ]
    return not any(
        not re.search(uncertainty + r"|\b(?:assum\w*|presum\w*|guess\w*)\b", clause, re.IGNORECASE)
        for clause in clauses
    )


def claim_evidence_exclusion(component: dict, finding: dict, target: str | None) -> str | None:
    """Shared admission checks; an exclusion never invents the opposite relationship."""
    if finding.get("relationship") == "supports":
        support = _threshold_support_exclusion(
            component, finding["quotation"]
        ) or _approval_event_support_exclusion(component, finding["quotation"], target)
        if support:
            return support
    boundary = approval_boundary_exclusion(component, finding, target)
    if boundary:
        return boundary
    if finding.get("relationship") not in {"supports", "contradicts", "qualifies"}:
        return None
    text = re.sub(r"[*`]", "", finding["quotation"])
    grounding = finding.get("semantic_validation", {}).get("grounding_quote")
    if not grounding or exact_evidence_span(finding["quotation"], grounding) is None:
        grounding = finding["quotation"]
    if (
        finding["relationship"] == "contradicts"
        and target in {"event", "observed_practice", "current_state", "historical_state"}
        and not re.search(
            r"\b(?:know\w*|aware\w*|certain\w*|uncertain\w*|unclear|recall\w*|remember\w*)\b",
            component["text"],
            re.IGNORECASE,
        )
        and _uncertainty_only(grounding)
    ):
        return (
            "The cited grounding expresses uncertainty, not a contrary observation. Lack of "
            "knowledge does not establish that the claimed event or practice failed to occur."
        )
    approval = r"\b" + _APPROVAL_WORD + r"\b"
    normative = re.search(approval, text, re.IGNORECASE) and re.search(
        r"\b(?:needs?|requires?|required|must|shall|mandatory|threshold)\b",
        text,
        re.IGNORECASE,
    )
    action_pattern = (
        r"\b(?:was|were|is|are|has been|have been|had been|got)\s+"
        r"(?:(?:not|never|already|formally|informally|actually)\s+)*"
        r"(?:approved|authori[sz]ed|signed[ -]?off|recorded|granted|denied)\b|"
        r"\b(?:receiv(?:e[ds]?|ing)|obtain(?:s|ed|ing)?|gave|give[sn]?|withheld)\b"
        r"[^.!?;\n]{0,60}" + approval + r"|"
        r"\b(?:I|we|they|he|she)\s+(?:did not |never |actually )?"
        r"(?:approve[ds]?|authori[sz]e[ds]?|sign(?:ed)?[ -]?off)\b|"
        r"\b(?:approves|authori[sz]es|signs[ -]?off)\b|"
        r"\b(?:carried (?:it |this |that )?out|implemented|completed|followed|happened|took place)\b|"
        r"\b(?:approved|authori[sz]ed|signed[ -]?off)\s+(?:by|the|a|an|this|that)\b"
    )
    performed = any(
        not re.search(
            r"(?:\b(?:must|shall|should|may|can|to)\s+(?:not\s+)?be\s+|\bto\s+)$",
            text[: match.start()],
            re.IGNORECASE,
        )
        for match in re.finditer(action_pattern, text, re.IGNORECASE)
    )
    practice_context = re.search(
        r"\b(?:in practice|actually|usually|often|sometimes|not always|despite|"
        r"bypass\w*|ignor\w*|follow\w*|compl(?:y|ies|ied|iance)|noncompliance|exceptions?)\b",
        text,
        re.IGNORECASE,
    )
    instruction = re.search(
        r"\b(?:agreed|decided)\s*(?::|to\b)|\b(?:agreement|decision|instruction)\s+"
        r"(?:was|is)\s+to\b|\b(?:instructed|directed)\b[^.!?;\n]{0,50}\bto\b",
        text,
        re.IGNORECASE,
    )
    execution_context = re.search(
        r"\b(?:in practice|actually|usually|often|sometimes|not always|we did|they did|I did)\b",
        text,
        re.IGNORECASE,
    )
    if target == "observed_practice" and instruction and not performed and not execution_context:
        return (
            "The passage records an agreed instruction or intended procedure, not evidence that "
            "it was carried out. Relative timing in an instruction does not establish an actual event's timing."
        )
    if target == "observed_practice" and normative and not performed and not practice_context:
        return (
            "The cited passage states an approval requirement, not a performed approval or observed "
            "compliance. Its trigger range cannot establish or contradict actual behavior."
        )
    claim_text = component.get("claim_quote", component["text"])
    if (
        finding["relationship"] != "contradicts"
        or not re.search(approval, claim_text, re.IGNORECASE)
        or not _normative_threshold_claim(claim_text)
    ):
        return None
    dimensions = {
        unit[0]
        for quantity in component.get("quantities", [])
        if (unit := _numeric_unit(quantity["unit"])) is not None
    }
    if not dimensions or any(kind in dimensions for _, kind in _scalar_observations(text)):
        return None
    removal = re.search(
        approval
        + r"[^.!?;\n]{0,80}\b(?:not|no longer|never)\s+(?:be\s+)?(?:required|necessary|mandatory)\b|"
        r"\b(?:do|does|did)\s+not\s+(?:require|need)\b[^.!?;\n]{0,80}" + approval + r"|"
        r"\bno\s+(?:\w+[ -]){0,5}"
        + approval
        + r"[^.!?;\n]{0,80}\b(?:required|necessary|mandatory)\b|"
        r"\b(?:may|can|permitted to|allowed to)\b[^.!?;\n]{0,80}\bwithout\b[^.!?;\n]{0,60}"
        + approval
        + r"|"
        r"\b(?:requirement|threshold|cut[ -]?off)\b[^.!?;\n]{0,80}"
        r"\b(?:abolished|removed|withdrawn|revoked|repealed|eliminated)\b",
        text,
        re.IGNORECASE,
    )
    if removal:
        return None
    return (
        "The cited passage provides neither a comparable threshold quantity nor an explicit "
        "removal of the claimed approval requirement. A role or document mismatch alone does "
        "not contradict this quantitative rule."
    )
