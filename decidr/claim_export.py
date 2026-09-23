"""Standalone escaped report of the same frozen presentation used by chat and graph."""

from html import escape
import json

from decidr.assessment_snapshot import presentation


def claim_report_html(result: dict) -> str:
    def p(text):
        return "<p>" + escape(str(text)) + "</p>"

    view = presentation(result)
    findings = {f["finding_id"]: f for f in view["findings"]}
    records = {r["evidence_id"]: r for r in result["evidence_records"]}

    def citation(fid):
        f = findings[fid]
        record = records[f["evidence_id"]]
        return (
            '<a href="#'
            + escape(fid, quote=True)
            + '">'
            + escape(
                record["source"]["title"]
                + " · "
                + f["assessment_target"].replace("_", " ")
                + " · "
                + (f["relationship"] or "unclassified")
            )
            + "</a>"
        )

    def finding_html(fid):
        f = findings[fid]
        record = records[f["evidence_id"]]
        return (
            '<article id="'
            + escape(fid, quote=True)
            + '">'
            + citation(fid)
            + p(f["reason"])
            + "<blockquote>"
            + escape(record["text"])
            + '</blockquote><a href="#source-'
            + escape(record["evidence_id"], quote=True)
            + '">Source details and scope</a></article>'
        )

    content = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Decidr claim assessment</title><style>
    body{font:12pt/1.45 system-ui,sans-serif;max-width:1000px;margin:2em auto;padding:0 1em;color:#17212b}
    p,pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}h2{break-after:avoid}article{border-top:1px solid #aaa;padding:1em 0}
    a{color:#17558a}summary{cursor:pointer}blockquote{margin:1em;padding:1em;background:#f3f5f8}
    .edge{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1em;margin:1em 0;padding:.8em;border:2px solid var(--color);border-radius:.5em;overflow-wrap:anywhere}.edge>div{min-width:0}.edge-label{font-weight:600;color:var(--color)}
    @media print{@page{size:A4;margin:16mm}body{max-width:none;margin:0;padding:0}.edge,article,p,pre{height:auto;max-height:none;overflow:visible;break-inside:auto}h1{font-size:18pt}h2{font-size:14pt}.controls{display:none}}
    </style><body><h1>Decidr claim assessment</h1>"""
    content += p(result["claim"]["claim_text"])
    content += p(f"Verdict: {result['outcome']} · Confidence: {result['confidence']}") + p(
        result["explanation"]
    )
    content += p(
        (
            "Saved assessment result · frozen snapshot"
            if result.get("presentation")
            else "Historical result · saved verdict retained"
        )
        + " · "
        + result.get("run_id", "historical")
    )
    content += p(
        f"Assessment as of {result['as_of']}; relevant period: {result['assessed_period']}"
    )
    if result.get("assessed_at"):
        content += p("Created " + result["assessed_at"])
    content += p("Review status: " + result.get("review_status", "Human reviewed"))
    for finding in result.get("target_findings", {}).values():
        content += p(finding["title"] + ": " + finding["outcome"])
    for section in view["sections"]:
        content += "<h2>" + escape(section["title"]) + "</h2>"
        content += "".join(finding_html(fid) for fid in section["finding_ids"]) or p(
            "None established in this assessment."
        )
    content += "".join(p(t) for t in result.get("policy_practice_divergence", []))
    content += "<h2>Evidence gaps</h2>"
    for gap in view["gaps"]:
        content += '<p id="' + gap["gap_id"] + '">' + escape(gap["text"]) + "</p>"
    if not view["gaps"]:
        content += p(
            "No genuine evidence gap recorded. Retrieval and classification coverage are separate."
        )
    coverage = view["coverage"]
    content += p(
        f"Classification coverage: {coverage['classified']}/{coverage['total']} {coverage['unit']}; {coverage['retrieved']} retrieved candidates."
    )
    content += (
        "<details><summary>Classification failures (" + str(len(view["failures"])) + ")</summary>"
    )
    content += "".join(finding_html(fid) for fid in view["failures"]) + "</details>"
    content += (
        '<details id="retrieval"><summary>Retrieval limits</summary>'
        + "".join(p(t) for t in view["retrieval_limits"])
        + "</details>"
    )
    content += (
        "<details><summary>Material exclusions and repeated evidence</summary>"
        + "".join(finding_html(fid) for fid in view["excluded"])
        + p(result["dependence_note"])
        + "</details>"
    )
    content += "<h2>Recommended next action</h2>"
    for action in view["recommendations"]:
        content += p(action["text"])
        content += (
            "<ul>"
            + "".join("<li>" + citation(fid) + "</li>" for fid in action["finding_ids"])
            + "</ul>"
        )
        for gid in action.get("gap_ids", []):
            content += '<a href="#' + gid + '">Recorded evidence gap</a> '
        if action.get("limit_ids"):
            content += '<a href="#retrieval">Recorded retrieval limit</a>'
    content += "<details><summary>Expandable graph</summary>"
    content += p(
        "Legend: green support; red contradiction; gold qualification; blue context; grey excluded; purple unclassified. Each row retains the source → excerpt → assessment target relationship."
    )
    content += (
        '<div class="controls"><label>Target <select id="target"><option value="">All</option>'
    )
    for target in dict.fromkeys(f["assessment_target"] for f in view["findings"]):
        content += "<option>" + escape(target) + "</option>"
    content += '</select></label> <label>Disposition <select id="state"><option value="">All</option><option>used</option><option>excluded</option><option>unclassified</option></select></label></div>'
    content += (
        '<p id="counts">Shown '
        + str(len(findings))
        + "/"
        + str(len(findings))
        + " target findings; "
        + str(len(records))
        + " retrieved candidates.</p>"
    )
    colours = {
        "support": "#15803d",
        "contradict": "#b91c1c",
        "qualify": "#a16207",
        "contextual": "#2563eb",
        "excluded": "#6b7280",
        "unclassified": "#7e22ce",
    }
    for fid, f in findings.items():
        record = records[f["evidence_id"]]
        state = f["disposition"]
        colour = colours.get(state if state != "used" else f["relationship"], "#475569")
        content += (
            '<div class="edge" data-target="'
            + escape(f["assessment_target"], quote=True)
            + '" data-state="'
            + state
            + '" style="--color:'
            + colour
            + '">'
        )
        content += (
            '<div><a href="#source-'
            + escape(record["evidence_id"], quote=True)
            + '">'
            + escape(record["source"]["title"])
            + "</a><br>→ extracted excerpt</div>"
        )
        content += "<div>" + citation(fid) + "<br>" + escape(record["locator"]) + "</div>"
        content += (
            '<div class="edge-label">→ '
            + escape(
                state
                + " · "
                + (f["relationship"] or "unclassified")
                + " · "
                + f["assessment_target"].replace("_", " ")
            )
            + "<br>"
            + escape(result["claim"]["claim_text"])
            + "</div></div>"
        )
    rendered = {fid for section in view["sections"] for fid in section["finding_ids"]}
    rendered.update(view["excluded"])
    rendered.update(view["failures"])
    content += "</details><details><summary>Other assessment targets</summary>"
    content += "".join(finding_html(fid) for fid in findings if fid not in rendered)
    content += "</details><details><summary>All frozen excerpts and source inspection</summary>"
    for eid, record in records.items():
        content += (
            '<article id="source-'
            + escape(eid, quote=True)
            + '"><h3>'
            + escape(record["source"]["title"])
            + "</h3>"
        )
        content += (
            p(eid + " · " + record["locator"])
            + p(record["text"])
            + p(record["source"]["original_file_path"])
        )
        content += p(
            "Frozen source metadata: " + json.dumps(record["source"], ensure_ascii=False, indent=2)
        )
        for context in record.get("source_context", []):
            content += p(context["evidence_id"] + " · " + context["locator"]) + p(context["text"])
        content += "</article>"
    content += "</details><details><summary>Complete snapshot and limitations</summary>"
    content += (
        "".join(p(t) for t in result.get("limitations", []))
        + p(json.dumps(result, ensure_ascii=False, indent=2))
        + "</details>"
    )
    # No external scripts or live sources. Hash links reveal frozen excerpts even inside details.
    content += """<script>
    const edges=[...document.querySelectorAll('.edge')];
    function filter(){let shown=0;for(const e of edges){e.hidden=(target.value&&e.dataset.target!==target.value)||(state.value&&e.dataset.state!==state.value);e.style.display=e.hidden?'none':'';if(!e.hidden)shown++;}document.getElementById('counts').textContent=`Shown ${shown}/${edges.length} target findings; filtered ${edges.length-shown}.`;}
    const target=document.getElementById('target'),state=document.getElementById('state');target.addEventListener('change',filter);state.addEventListener('change',filter);
    function reveal(){const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(e){for(let p=e.parentElement;p;p=p.parentElement){if(p.tagName==='DETAILS')p.open=true;}e.scrollIntoView();}}
    addEventListener('hashchange',reveal);reveal();
    addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>d.open=true));
    </script></body></html>"""
    return content
