"""Join policy version history to a structured meeting decision and sign-off."""

from datetime import date
from decimal import Decimal
import re

from decidr.approval_propositions import ApprovalRule
from decidr.authority_context import _header_citations
from decidr.retrieval_models import Evidence, Source

NUMBER = r"(?:0|[1-9]\d*)(?:\.\d+)?"
DAY = r"\d{4}-\d{2}-\d{2}"
CHANGE = re.compile(
    rf"Threshold raised from (?P<old>{NUMBER})% to (?P<new>{NUMBER})%, "
    rf"approved at leadership/finance meeting (?P<meeting>{DAY})"
)
DECISION = re.compile(
    rf"Raise the Finance approval threshold from (?P<old>{NUMBER})% to (?P<new>{NUMBER})%, "
    rf"effective (?P<effective>{DAY})\."
    rf"(?: Option \d+ \((?P<rejected>{NUMBER})%\) was discussed but not adopted "
    r"— [\w '-]+ felt it removed too much oversight\.)?"
)
SIGNOFF = re.compile(
    r"(?P<owner>[\w '-]+) \(policy owner\), with (?P<actor>[\w '-]+)'s sign-off\."
)


def structured_adoptions(
    policy: Source, rule: ApprovalRule, passages: list[Evidence], sources: dict[str, Source]
) -> dict[str, dict]:
    """Extract adoption only from a uniquely bound version/date/action/sign-off chain.

    A sign-off documents an act, not the signatory's right to adopt policy.
    Returned evidence identities allow callers to retain exact original quotations.
    """
    local = [p for p in passages if p.source_id == policy.source_id]
    code_match = re.match(r"^([A-Z][A-Z0-9]*-\d+)(?=\s|$)", policy.title)
    if not code_match or not policy.version or not policy.effective_start_date:
        return {}
    code = code_match[1]
    histories = []
    version_rows = 0
    for p in local:
        if (p.heading or "").casefold() != "version history":
            continue
        lines = [line.strip() for line in p.text.splitlines() if line.strip()]
        # Column meaning is required, not inferred from a coincidental date row.
        if not lines or [c.strip().casefold() for c in lines[0].strip("|").split("|")] != [
            "version",
            "effective",
            "change",
        ]:
            continue
        for line in lines[2:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 3 or cells[0] != policy.version:
                continue
            version_rows += 1
            change = CHANGE.fullmatch(cells[2])
            if change and cells[1] == policy.effective_start_date.isoformat():
                histories.append((change, p))
    if len(histories) != 1 or version_rows != 1:
        return {}
    change, history = histories[0]
    if Decimal(change["new"]) != Decimal(rule.percentage) or rule.boundary != "ge":
        return {}
    release = policy.source_id.partition(":")[0]
    results = {}
    for decision in passages:
        meeting = sources.get(decision.source_id)
        if (
            not meeting
            or meeting.source_type != "meeting"
            or not meeting.source_id.startswith(release + ":")
            or (decision.heading or "").casefold() != "final decision"
            or not decision.section
            or " > " not in decision.section
        ):
            continue
        parsed = DECISION.fullmatch(decision.text.strip())
        if not parsed:
            continue
        try:
            decided = date.fromisoformat(change["meeting"])
            effective = date.fromisoformat(parsed["effective"])
        except ValueError:
            continue
        if (
            meeting.creation_date != decided
            or decided > effective
            or effective != policy.effective_start_date
            or Decimal(parsed["old"]) != Decimal(change["old"])
            or Decimal(parsed["new"]) != Decimal(change["new"])
            or (parsed["rejected"] and Decimal(parsed["rejected"]) == Decimal(parsed["new"]))
        ):
            continue
        meeting_passages = [p for p in passages if p.source_id == meeting.source_id]
        dates = _header_citations(meeting, meeting_passages, "date")
        if {entry["value"] for entry, _ in dates} != {decided.isoformat()}:
            continue
        parent = decision.section.rsplit(" > ", 1)[0]
        siblings = [
            p
            for p in meeting_passages
            if p.section and " > " in p.section and p.section.rsplit(" > ", 1)[0] == parent
        ]
        owners = [p for p in siblings if (p.heading or "").casefold() == "decision owner"]
        actions = [p for p in siblings if (p.heading or "").casefold() == "actions"]
        if len(owners) != 1 or len(actions) != 1:
            continue
        signoff = SIGNOFF.fullmatch(owners[0].text.strip())
        if not signoff or any(
            re.search(r"\b(and|or|not|unless|except)\b", signoff[k], re.IGNORECASE)
            for k in ("actor", "owner")
        ):
            continue
        expected = f"- {signoff['owner']} to update and circulate {code} by {effective.isoformat()}. (Done — see {code}.)"
        action_lines = actions[0].text.splitlines()
        if sum(line.strip() == expected for line in action_lines) != 1:
            continue
        # Other actions may be present, but another reference to the policy is ambiguous.
        code_lines = [
            line
            for line in action_lines
            if re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", line)
        ]
        if len(code_lines) != 1:
            continue
        owners_in_header = _header_citations(policy, local, "document owner")
        if len({entry["value"] for entry, _ in owners_in_header}) != 1:
            continue
        if not all(
            entry["value"].startswith(signoff["owner"] + ", ") for entry, _ in owners_in_header
        ):
            continue
        # Version history binds the decision to the policy rule, not just a shared threshold.
        results[decision.evidence_id] = {
            "actor": signoff["actor"],
            "code": code,
            "version": policy.version,
            "scope": rule.deal_scope,
            "decision": decided.isoformat(),
            "effective": effective.isoformat(),
            "method": "version-history-meeting-signoff-v1",
            "evidence_ids": [
                history.evidence_id,
                decision.evidence_id,
                owners[0].evidence_id,
                actions[0].evidence_id,
                *[c.evidence_id for _, c in dates + owners_in_header],
            ],
        }
    return results
