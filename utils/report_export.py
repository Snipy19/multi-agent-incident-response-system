"""
REPORT EXPORT
----------------
Kaam: Database mein saved incident se downloadable report banana
(Markdown, plain text, ya PDF).

Ye report LLM ke likhe narrative se nahi, balki incident ke REAL
structured data se banti hai (asli timestamp, findings, confidence),
taaki koi invented detail (fake times, fake durations) report mein na jaaye.
"""

import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


# ---------- COMMON HELPERS ----------

def _pct(value):
    return f"{value * 100:.0f}%" if value is not None else "N/A"


def _when(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return iso or "N/A"


def _review_text(flag):
    return "Human review required" if flag else "No human review required"


def _anomaly_text(flag):
    return "Anomaly confirmed" if flag else "No anomaly detected"


def _agent_count(incident):
    angles = incident.get("investigation_angles") or []
    findings = incident.get("investigation_findings") or []
    return len(angles) if angles else len(findings)


def _md_cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


# ---------- MARKDOWN ----------

def build_markdown(incident: dict) -> str:
    findings = incident.get("investigation_findings") or []

    lines = [
        "# Incident Post-Mortem Report",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Incident ID | {incident['id']} |",
        f"| Analysed on | {_when(incident.get('created_at'))} |",
        f"| Detection | {_anomaly_text(incident.get('is_anomaly'))} |",
        f"| Agents deployed | {_agent_count(incident)} |",
        f"| Root-cause confidence | {_pct(incident.get('root_cause_confidence'))} |",
        f"| Fix confidence | {_pct(incident.get('fix_confidence'))} |",
        f"| Review status | {_review_text(incident.get('needs_human_review'))} |",
        "",
        "## Log Entry",
        "",
        "```text",
        incident.get("raw_log") or "",
        "```",
        "",
        "## Detection",
        "",
        incident.get("anomaly_reason") or "N/A",
        "",
        "## Investigation Findings",
        "",
        "| Angle | Finding | Confidence |",
        "|---|---|---|",
    ]

    for f in findings:
        lines.append(
            f"| {_md_cell(f.get('angle'))} | {_md_cell(f.get('finding'))} | {_pct(f.get('confidence'))} |"
        )

    lines += [
        "",
        "## Root Cause",
        "",
        incident.get("root_cause") or "N/A",
        "",
        f"*Confidence: {_pct(incident.get('root_cause_confidence'))}*",
        "",
        "## Recommended Fix",
        "",
        incident.get("suggested_fix") or "N/A",
        "",
        f"*Confidence: {_pct(incident.get('fix_confidence'))}*",
        "",
        "---",
        "*Generated automatically by Incident Response Console. "
        "Recommendations should be reviewed by an engineer before being applied.*",
        "",
    ]
    return "\n".join(lines)


# ---------- PLAIN TEXT ----------

def build_text(incident: dict) -> str:
    findings = incident.get("investigation_findings") or []
    bar = "=" * 72
    thin = "-" * 72

    lines = [
        "INCIDENT POST-MORTEM REPORT",
        bar,
        f"Incident ID           : {incident['id']}",
        f"Analysed on           : {_when(incident.get('created_at'))}",
        f"Detection             : {_anomaly_text(incident.get('is_anomaly'))}",
        f"Agents deployed       : {_agent_count(incident)}",
        f"Root-cause confidence : {_pct(incident.get('root_cause_confidence'))}",
        f"Fix confidence        : {_pct(incident.get('fix_confidence'))}",
        f"Review status         : {_review_text(incident.get('needs_human_review'))}",
        "",
        "LOG ENTRY",
        thin,
        incident.get("raw_log") or "",
        "",
        "DETECTION",
        thin,
        incident.get("anomaly_reason") or "N/A",
        "",
        "INVESTIGATION FINDINGS",
        thin,
    ]

    for i, f in enumerate(findings, 1):
        lines.append(f"{i}. [{f.get('angle')}] (confidence {_pct(f.get('confidence'))})")
        lines.append(f"   {f.get('finding')}")
        lines.append("")

    lines += [
        "ROOT CAUSE",
        thin,
        incident.get("root_cause") or "N/A",
        f"(confidence {_pct(incident.get('root_cause_confidence'))})",
        "",
        "RECOMMENDED FIX",
        thin,
        incident.get("suggested_fix") or "N/A",
        f"(confidence {_pct(incident.get('fix_confidence'))})",
        "",
        bar,
        "Generated automatically by Incident Response Console.",
        "Recommendations should be reviewed by an engineer before being applied.",
        "",
    ]
    return "\n".join(lines)


# ---------- PDF ----------

# ReportLab ke standard fonts sirf Latin-1 jaise characters support karte hain.
# LLM output mein kabhi kabhi special characters (non-breaking hyphen, approx sign, arrows)
# aate hain, unko safe equivalents se replace karte hain warna PDF mein black boxes dikhte hain.
_REPLACEMENTS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-",
    "\u2248": "~", "\u2192": "->", "\u2190": "<-",
    "\u2265": ">=", "\u2264": "<=",
    "\u2026": "...", "\u202f": " ", "\u2009": " ",
}


def _pdf_safe(text) -> str:
    text = "" if text is None else str(text)
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("cp1252", "replace").decode("cp1252")


def _p(text) -> str:
    """Paragraph ke liye text: safe characters + XML escape + line breaks"""
    return escape(_pdf_safe(text)).replace("\n", "<br/>")


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(2 * cm, 1.2 * cm, "Incident Response Console - automated analysis, review before acting")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(incident: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title="Incident Post-Mortem Report", author="Incident Response Console"
    )

    base = getSampleStyleSheet()
    navy = colors.HexColor("#1e3a8a")
    grey = colors.HexColor("#475569")
    ink = colors.HexColor("#1f2937")

    title_style = ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
                                 fontSize=20, textColor=navy, alignment=0, spaceAfter=4)
    sub_style = ParagraphStyle("ReportSub", parent=base["Normal"], fontSize=9.5,
                               textColor=grey, spaceAfter=14)
    heading = ParagraphStyle("ReportHeading", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12.5, textColor=navy, spaceBefore=16, spaceAfter=6)
    body = ParagraphStyle("ReportBody", parent=base["BodyText"], fontSize=10, leading=14.5, textColor=ink)
    note = ParagraphStyle("ReportNote", parent=body, fontSize=9, textColor=grey, spaceBefore=4)
    mono = ParagraphStyle("ReportMono", parent=body, fontName="Courier", fontSize=8.8, leading=12,
                          backColor=colors.HexColor("#f1f5f9"), borderPadding=8)
    cell = ParagraphStyle("ReportCell", parent=body, fontSize=9, leading=12.5)
    cell_bold = ParagraphStyle("ReportCellBold", parent=cell, fontName="Helvetica-Bold")
    cell_head = ParagraphStyle("ReportCellHead", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    findings = incident.get("investigation_findings") or []
    story = []

    story.append(Paragraph("Incident Post-Mortem Report", title_style))
    story.append(Paragraph(f"Automated multi-agent analysis &middot; Incident {_p(incident['id'])}", sub_style))

    # Summary table
    meta_rows = [
        ("Analysed on", _when(incident.get("created_at"))),
        ("Detection", _anomaly_text(incident.get("is_anomaly"))),
        ("Agents deployed", str(_agent_count(incident))),
        ("Root-cause confidence", _pct(incident.get("root_cause_confidence"))),
        ("Fix confidence", _pct(incident.get("fix_confidence"))),
        ("Review status", _review_text(incident.get("needs_human_review"))),
    ]
    meta_table = Table(
        [[Paragraph(_p(k), cell_bold), Paragraph(_p(v), cell)] for k, v in meta_rows],
        colWidths=[5 * cm, 12 * cm]
    )
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)

    story.append(Paragraph("Log Entry", heading))
    story.append(Paragraph(_p(incident.get("raw_log")), mono))

    story.append(Paragraph("Detection", heading))
    story.append(Paragraph(_p(incident.get("anomaly_reason") or "N/A"), body))

    story.append(Paragraph("Investigation Findings", heading))
    rows = [[Paragraph("Angle", cell_head), Paragraph("Finding", cell_head), Paragraph("Confidence", cell_head)]]
    for f in findings:
        rows.append([
            Paragraph(_p(f.get("angle")), cell_bold),
            Paragraph(_p(f.get("finding")), cell),
            Paragraph(_p(_pct(f.get("confidence"))), cell),
        ])
    findings_table = Table(rows, colWidths=[3.5 * cm, 11.3 * cm, 2.2 * cm], repeatRows=1)
    findings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(findings_table)

    story.append(Paragraph("Root Cause", heading))
    story.append(Paragraph(_p(incident.get("root_cause") or "N/A"), body))
    story.append(Paragraph(f"Confidence: {_p(_pct(incident.get('root_cause_confidence')))}", note))

    story.append(Paragraph("Recommended Fix", heading))
    story.append(Paragraph(_p(incident.get("suggested_fix") or "N/A"), body))
    story.append(Paragraph(f"Confidence: {_p(_pct(incident.get('fix_confidence')))}", note))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Generated automatically by Incident Response Console. "
        "Recommendations should be reviewed by an engineer before being applied.", note))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()