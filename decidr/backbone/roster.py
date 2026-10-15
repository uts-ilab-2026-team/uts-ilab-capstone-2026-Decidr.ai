"""Backbone layer parsed from clean markdown tables: processes, roster, role descriptions."""

from __future__ import annotations

import re

from decidr.backbone.common import (
    LEFT_COMPANY_PATTERN,
    PROCESS_CODE_PATTERN,
    _GraphBuilder,
    _slug,
)

# --------------------------------------------------------------------------- #
# Backbone layer (parsed from the clean markdown tables)                       #
# --------------------------------------------------------------------------- #


def _table_rows(text: str, header_must_contain: str) -> list[list[str]]:
    """Return cell lists for a single GitHub markdown table matching the header."""
    rows: list[list[str]] = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        if not capturing:
            if stripped.startswith("|") and header_must_contain in stripped:
                capturing = True
            continue
        if not stripped.startswith("|"):
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def _add_processes(builder: _GraphBuilder, overview_text: str) -> dict[str, str]:
    """Create the 8 process nodes from the company-overview table. Returns code -> node_id."""
    process_ids: dict[str, str] = {}
    for cells in _table_rows(overview_text, "Process"):
        if len(cells) < 2:
            continue
        code_match = PROCESS_CODE_PATTERN.fullmatch(cells[0].strip())
        if not code_match:
            continue
        code = cells[0].strip()
        node_id = f"process:{code.casefold()}"
        builder.add_node(node_id, "process", f"{code} {cells[1]}", {"code": code})
        process_ids[code] = node_id
    return process_ids


def _add_roster(builder: _GraphBuilder, roster_text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse the staff roster table. Returns (person_name -> role_id, role_label -> role_id)."""
    inactive = {
        match.group("name").strip()
        for line in roster_text.splitlines()
        if (match := LEFT_COMPANY_PATTERN.match(line.strip()))
    }
    name_to_role: dict[str, str] = {}
    role_by_label: dict[str, str] = {}
    name_to_person: dict[str, str] = {}
    pending_reports: list[tuple[str, str]] = []  # (person_name, manager_name)

    for cells in _table_rows(roster_text, "Employee"):
        if len(cells) < 4:
            continue
        name, function_name, role_name, reports_to = cells[0], cells[1], cells[2], cells[3]
        start = cells[4] if len(cells) > 4 else ""
        if not name or not role_name:
            continue
        person_id = f"person:{_slug(name)}"
        role_id = f"role:{_slug(role_name)}"
        function_id = f"function:{_slug(function_name)}"
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", start)
        person_attrs = {"status": "inactive" if name in inactive else "active"}
        if date_match:
            person_attrs["start_date"] = date_match.group()
        builder.add_node(person_id, "person", name, person_attrs)
        builder.add_node(role_id, "role", role_name, {})
        builder.add_node(function_id, "function", function_name, {})
        builder.add_edge(person_id, role_id, "HOLDS")
        builder.add_edge(role_id, function_id, "SITS_IN")
        name_to_role[name] = role_id
        name_to_person[name] = person_id
        role_by_label[role_name] = role_id
        if reports_to and reports_to.casefold() != "board":
            pending_reports.append((name, reports_to))

    for name, manager in pending_reports:
        self_role = name_to_role.get(name)
        manager_role = name_to_role.get(manager)
        if self_role and manager_role and self_role != manager_role:
            builder.add_edge(self_role, manager_role, "REPORTS_TO")
        elif manager not in name_to_role:
            builder.warnings.append(f"reports-to manager not in roster: {name!r} -> {manager!r}")
    return name_to_role, role_by_label


def _resolve_role(role_name: str, role_by_label: dict[str, str]) -> str | None:
    """Match a role-description heading to a roster role (handles minor variants)."""
    if role_name in role_by_label:
        return role_by_label[role_name]
    target = _slug(role_name)
    for label, role_id in role_by_label.items():
        candidate = _slug(label)
        if candidate == target or candidate.startswith(target) or target.startswith(candidate):
            return role_id
        # "Product Managers" -> "Product Manager"; "CEO / Founder" -> "CEO"
        if candidate.rstrip("s") == target.rstrip("s"):
            return role_id
    return None


def _add_role_descriptions(
    builder: _GraphBuilder,
    roles_text: str,
    role_by_label: dict[str, str],
    process_ids: dict[str, str],
) -> None:
    """Add ACCESSES (role->system) and PARTICIPATES_IN (role->process) from role descriptions."""
    current_role_id: str | None = None
    for line in roles_text.splitlines():
        heading = re.match(r"^##\s+(?P<name>.+?)\s*[—–-]\s*.+$", line)
        if heading:
            current_role_id = _resolve_role(heading.group("name").strip(), role_by_label)
            if current_role_id is None:
                builder.warnings.append(
                    f"role-description heading unmatched: {heading.group('name')!r}"
                )
            continue
        if current_role_id is None:
            continue
        systems = re.match(r"^- \*\*Systems accessed:\*\*\s*(?P<value>.+)$", line)
        if systems:
            for raw in systems.group("value").split(","):
                name = re.sub(r"\(.*?\)", "", raw).strip().rstrip(".")
                if not name or name.casefold().startswith("all "):
                    continue
                system_id = f"system:{_slug(name)}"
                builder.add_node(system_id, "system", name, {})
                builder.add_edge(current_role_id, system_id, "ACCESSES")
            continue
        participation = re.match(r"^- \*\*Process participation:\*\*\s*(?P<value>.+)$", line)
        if participation:
            for code_num in PROCESS_CODE_PATTERN.findall(participation.group("value")):
                process_id = process_ids.get(f"P{code_num}")
                if process_id:
                    builder.add_edge(current_role_id, process_id, "PARTICIPATES_IN")
