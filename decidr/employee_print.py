"""Compact, escaped employee-only print document; browser UI remains unchanged."""

from html import escape

from decidr.evidence_b import employee_evidence

PRINT_CSS = """
.employee-print { display: none; }
@media print {
  @page { size: A4; margin: 14mm; }
  [data-testid="stSidebar"], [data-testid="stSidebarNav"], header, footer,
  [data-testid="stBottom"], [data-testid="stChatInput"],
  [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
  [data-testid="stMainBlockContainer"] *:not(:has(.employee-print)):not(.employee-print):not(.employee-print *) {
    display: none !important;
  }
  html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
  [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    width: 100% !important; max-width: none !important; min-height: 0 !important;
    height: auto !important; overflow: visible !important; margin: 0 !important;
    padding: 0 !important; position: static !important;
  }
  [data-testid="stMainBlockContainer"] > div,
  [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
  .employee-print { display: block !important; width: 100%; color: #111;
    font: 10pt/1.35 Arial, sans-serif; overflow-wrap: anywhere; }
  .employee-print h1 { font-size: 17pt; margin: 0 0 8pt; }
  .employee-print h2 { font-size: 12pt; margin: 10pt 0 5pt; break-after: avoid; }
  .employee-print p { margin: 5pt 0; }
  .employee-print .status { white-space: normal; overflow: visible; text-overflow: clip; }
  .employee-print article { border: 1px solid #bbb; padding: 7pt; margin: 6pt 0;
    break-inside: avoid; page-break-inside: avoid; }
  .employee-print .reference { font-size: 8pt; }
}
"""


def employee_print_html(result) -> str:
    def p(value):
        return f"<p>{escape(str(value))}</p>"

    def card(item):
        return (
            "<article>" + p(item["source_title"]) + p(item["excerpt"])
            + '<p class="reference">'
            + escape(f"{item['evidence_id']} · {item['source_id']} · {item['locator']}")
            + "</p></article>"
        )

    primary, _ = employee_evidence(result)
    content = '<section class="employee-print"><h1>Employee knowledge assistant</h1>'
    content += p(result.original_question or result.query)
    content += '<p class="status">' + escape(
        f"Verdict: {result.outcome.value} · Confidence: {result.confidence.value}"
    ) + "</p>"
    content += p(result.safe_employee_guidance) + "<h2>Evidence</h2>"
    content += "".join(card(item) for item in primary)
    content += "".join(p(gap) for gap in result.evidence_gaps)
    if result.divergence_evidence:
        content += "<h2>Observed practice</h2>"
        content += "".join(p(note) for note in result.policy_practice_divergence)
        content += "".join(card(item) for item in result.divergence_evidence[:1])
        content += p("This observation does not change the prescribed-rule verdict.")
    content += "<h2>Recommended next action</h2>" + p(result.recommended_organisational_action)
    if result.responsible_role_basis == "cited policy text":
        content += p("Responsible role identified in the cited policy: " + result.responsible_role)
    return content + "</section>"
