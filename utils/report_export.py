"""
REPORT EXPORT
----------------
Kaam: Database mein saved incident se downloadable report banana
(PDF, Markdown, ya plain text).

Report LLM ke likhe narrative se nahi, incident ke REAL structured data
se banti hai (asli timestamp, findings, confidence). Koi cheez invent
nahi hoti - jo data system ke paas nahi hai (severity, MTTR, impact),
wo report mein hai hi nahi.
"""

import io
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
)

# ---------- THEME ----------

NAVY = colors.HexColor("#1e3a8a")
GREY = colors.HexColor("#475569")
INK = colors.HexColor("#1f2937")
RULE = colors.HexColor("#cbd5e1")

LEVEL_HEX = {"High": "#16a34a", "Medium": "#d97706", "Low": "#dc2626", "N/A": "#64748b"}

# Reports are consumed by browsers, email clients, text editors, and PDF
# readers. Normalize typography to ASCII so a UTF-8/Windows-1252 mismatch
# cannot turn characters such as an en dash into visible mojibake ("â€“").
_TEXT_REPLACEMENTS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2212": "-", "\u2192": "->", "\u2190": "<-", "\u2265": ">=", "\u2264": "<=",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u2022": "-", "\u00a0": " ", "\u202f": " ", "\u2009": " ",
    "â€“": "-", "â€”": "-", "â€‘": "-", "â€™": "'", "â€œ": '"', "â€": '"',
    "â€¢": "-", "Â": "",
}


def _clean_text(value):
    text = "" if value is None else str(value)
    for old, new in _TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def _clean_incident(incident):
    """Return report data with human-readable, encoding-safe string fields."""
    cleaned = dict(incident)
    for key in ("id", "created_at", "raw_log", "anomaly_reason", "root_cause", "suggested_fix", "final_report"):
        if key in cleaned:
            cleaned[key] = _clean_text(cleaned[key])
    cleaned["investigation_angles"] = [_clean_text(x) for x in (cleaned.get("investigation_angles") or [])]
    cleaned["investigation_findings"] = [
        {**finding, "angle": _clean_text(finding.get("angle")), "finding": _clean_text(finding.get("finding"))}
        for finding in (cleaned.get("investigation_findings") or [])
    ]
    return cleaned


# ---------- COMMON HELPERS (teeno formats yahi use karte hain) ----------

def _pct(value):
    return f"{value * 100:.0f}%" if value is not None else "N/A"


def _level(value):
    if value is None:
        return "N/A"
    if value >= 0.75:
        return "High"
    if value >= 0.5:
        return "Medium"
    return "Low"


def _when(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return iso or "N/A"


def _now():
    return datetime.now().strftime("%d %b %Y, %I:%M %p")


def _angles(incident):
    angles = incident.get("investigation_angles") or []
    if angles:
        return list(angles)
    findings = incident.get("investigation_findings") or []
    return [f.get("angle") for f in findings if f.get("angle")]


def _agent_count(incident):
    return len(_angles(incident))


def _anomaly_text(flag):
    return "Anomaly confirmed" if flag else "No anomaly detected"


def _review_text(flag):
    return "Human review required" if flag else "No human review required"


def _review_short(flag):
    return "Required" if flag else "Not flagged"


def _executive_summary(incident):
    """Real data se templated summary - koi invented detail nahi"""
    if not incident.get("is_anomaly"):
        return ("Automated analysis of the submitted log did not detect an anomaly. "
                "No further investigation was performed.")

    n = _agent_count(incident)
    rc = incident.get("root_cause_confidence")
    fc = incident.get("fix_confidence")

    parts = ["Automated analysis of the submitted log confirmed an anomaly."]
    if n:
        word = "agent" if n == 1 else "agents"
        parts.append(f"{n} investigation {word} examined the incident in parallel "
                     f"({', '.join(_angles(incident))}).")
    parts.append(f"The root cause was identified with {_pct(rc)} confidence ({_level(rc).lower()}) "
                 f"and a remediation plan was proposed with {_pct(fc)} confidence ({_level(fc).lower()}).")
    if incident.get("needs_human_review"):
        parts.append("The analysis was flagged for human review before any action is taken.")
    else:
        parts.append("No escalation was flagged, but recommendations should still be reviewed "
                     "by an engineer before being applied.")
    return " ".join(parts)


def _methodology(incident):
    n = _agent_count(incident)
    plural = "s" if n != 1 else ""
    pipeline = (
        "This report was produced by an automated multi-agent pipeline. A detection agent screens the log entry, "
        f"an orchestrator selects the investigation angles, {n} specialist agent{plural} investigate in parallel "
        "(each also consulting a reference knowledge base of historical log patterns), an aggregator reconciles "
        "their findings into a single root cause, and a remediation agent proposes a fix."
    )
    limits = [
        "Confidence scores are self-reported by the language model. They are estimates, not calibrated statistical probabilities.",
        "The analysis is based only on the submitted log text. Live systems, metrics and configuration were not inspected.",
        "Recommended actions have not been applied or validated in any environment and should be reviewed by an engineer before use.",
    ]
    return pipeline, limits


_ABBREV_END = re.compile(r"(?:e\.g|i\.e|etc|vs|approx|incl)\.$", re.IGNORECASE)


def _split_actions(text):
    """Fix ke text ko numbered steps mein todta hai (sirf sentence/semicolon boundaries pe)"""
    text = (text or "").strip()
    if not text:
        return []

    raw = re.split(r"(?<=\.)\s+(?=[A-Z])", text)
    merged = []
    for piece in raw:
        if merged and _ABBREV_END.search(merged[-1]):
            merged[-1] = merged[-1] + " " + piece
        else:
            merged.append(piece)

    actions = []
    for piece in merged:
        for sub in re.split(r";\s+", piece):
            sub = sub.strip()
            if sub:
                actions.append(sub if sub.endswith((".", "!", "?")) else sub + ".")
    return actions


def _md_cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


# ---------- MARKDOWN ----------

def build_markdown(incident: dict) -> str:
    incident = _clean_incident(incident)
    findings = incident.get("investigation_findings") or []
    actions = _split_actions(incident.get("suggested_fix"))
    pipeline, limits = _methodology(incident)
    rc, fc = incident.get("root_cause_confidence"), incident.get("fix_confidence")

    L = [
        "# Incident Post-Mortem Report",
        "",
        f"**Incident:** `{incident['id']}`  ",
        f"**Analysed:** {_when(incident.get('created_at'))}  ",
        f"**Report generated:** {_now()}",
        "",
        "## 1. Executive Summary",
        "",
        _executive_summary(incident),
        "",
        "| Agents deployed | Root-cause confidence | Fix confidence | Review status |",
        "|---|---|---|---|",
        f"| {_agent_count(incident)} | {_pct(rc)} ({_level(rc)}) | {_pct(fc)} ({_level(fc)}) | "
        f"{_review_short(incident.get('needs_human_review'))} |",
        "",
        "## 2. Incident Details",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Detection | {_anomaly_text(incident.get('is_anomaly'))} |",
        f"| Detection rationale | {_md_cell(incident.get('anomaly_reason') or 'N/A')} |",
        "",
        "**Log entry**",
        "",
        "```text",
        incident.get("raw_log") or "",
        "```",
        "",
        "## 3. Investigation Findings",
        "",
        "| Angle | Finding | Confidence |",
        "|---|---|---|",
    ]
    for f in findings:
        L.append(f"| {_md_cell(f.get('angle'))} | {_md_cell(f.get('finding'))} | {_pct(f.get('confidence'))} |")

    L += ["", "## 4. Root Cause Analysis", "", incident.get("root_cause") or "N/A", "",
          f"*Confidence: {_pct(rc)} ({_level(rc)})*", "",
          "## 5. Recommended Remediation", ""]

    if len(actions) > 1:
        L += [f"{i}. {a}" for i, a in enumerate(actions, 1)]
    else:
        L.append(incident.get("suggested_fix") or "N/A")

    L += ["", f"*Confidence: {_pct(fc)} ({_level(fc)})*", "",
          f"> **Review status:** {_review_text(incident.get('needs_human_review'))}.", "",
          "## 6. Methodology & Limitations", "", pipeline, ""]
    L += [f"- {x}" for x in limits]
    L += ["", "---",
          f"*Generated automatically by Incident Response Console on {_now()}.*", ""]
    return "\n".join(L)


# ---------- PLAIN TEXT ----------

def build_text(incident: dict) -> str:
    incident = _clean_incident(incident)
    findings = incident.get("investigation_findings") or []
    actions = _split_actions(incident.get("suggested_fix"))
    pipeline, limits = _methodology(incident)
    rc, fc = incident.get("root_cause_confidence"), incident.get("fix_confidence")
    bar, thin = "=" * 72, "-" * 72

    L = [
        "INCIDENT POST-MORTEM REPORT", bar,
        f"Incident ID           : {incident['id']}",
        f"Analysed on           : {_when(incident.get('created_at'))}",
        f"Report generated      : {_now()}",
        f"Agents deployed       : {_agent_count(incident)}",
        f"Root-cause confidence : {_pct(rc)} ({_level(rc)})",
        f"Fix confidence        : {_pct(fc)} ({_level(fc)})",
        f"Review status         : {_review_text(incident.get('needs_human_review'))}",
        "",
        "1. EXECUTIVE SUMMARY", thin, _executive_summary(incident), "",
        "2. INCIDENT DETAILS", thin,
        f"Detection: {_anomaly_text(incident.get('is_anomaly'))}",
        f"Rationale: {incident.get('anomaly_reason') or 'N/A'}",
        "", "Log entry:", incident.get("raw_log") or "", "",
        "3. INVESTIGATION FINDINGS", thin,
    ]
    for i, f in enumerate(findings, 1):
        L.append(f"{i}. [{f.get('angle')}] (confidence {_pct(f.get('confidence'))})")
        L.append(f"   {f.get('finding')}")
        L.append("")

    L += ["4. ROOT CAUSE ANALYSIS", thin, incident.get("root_cause") or "N/A",
          f"(confidence {_pct(rc)})", "",
          "5. RECOMMENDED REMEDIATION", thin]
    if len(actions) > 1:
        L += [f"{i}. {a}" for i, a in enumerate(actions, 1)]
    else:
        L.append(incident.get("suggested_fix") or "N/A")
    L += [f"(confidence {_pct(fc)})", "",
          "6. METHODOLOGY & LIMITATIONS", thin, pipeline, ""]
    L += [f"- {x}" for x in limits]
    L += ["", bar, f"Generated automatically by Incident Response Console on {_now()}.", ""]
    return "\n".join(L)


# ---------- PDF ----------

# ReportLab ke standard fonts Latin-1 jaise characters support karte hain.
# LLM output mein kabhi kabhi special characters aate hain, unko safe
# equivalents se replace karte hain warna PDF mein black boxes dikhte hain.
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


def _soft_wrap(text, n=70):
    """Bahut lambe bina-space wale tokens ko wrap karne ke liye (sirf PDF display)"""
    return re.sub(r"(\S{%d})(?=\S)" % n, r"\1 ", text)


class ConfidenceBar(Flowable):
    """Chhota color-coded horizontal bar, percentage ke saath"""

    def __init__(self, value, width=3.6 * cm, height=0.38 * cm):
        super().__init__()
        self.value = value
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        if self.value is None:
            c.setFillColor(colors.HexColor(LEVEL_HEX["N/A"]))
            c.setFont("Helvetica", 8.5)
            c.drawString(0, 0.06 * cm, "N/A")
            return

        v = max(0.0, min(1.0, float(self.value)))
        bar_w = self.width - 1.0 * cm
        r = self.height / 2

        c.setFillColor(colors.HexColor("#e2e8f0"))
        c.roundRect(0, 0, bar_w, self.height, r, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(LEVEL_HEX[_level(v)]))
        c.roundRect(0, 0, max(bar_w * v, self.height), self.height, r, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(bar_w + 0.15 * cm, 0.06 * cm, f"{v * 100:.0f}%")


def _make_canvas(short_id):
    """Har page pe header/footer aur 'Page X of Y' ke liye custom canvas"""

    class _NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_states = []

        def showPage(self):
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                self._draw_chrome(total)
                super().showPage()
            super().save()

        def _draw_chrome(self, total):
            width, height = A4
            self.saveState()

            if self._pageNumber > 1:
                self.setFont("Helvetica-Bold", 8.5)
                self.setFillColor(NAVY)
                self.drawString(2 * cm, height - 1.2 * cm, "Incident Response Console")
                self.setFont("Helvetica", 8.5)
                self.setFillColor(GREY)
                self.drawRightString(width - 2 * cm, height - 1.2 * cm,
                                     f"Incident Post-Mortem Report  |  {short_id}")
                self.setStrokeColor(RULE)
                self.setLineWidth(0.5)
                self.line(2 * cm, height - 1.4 * cm, width - 2 * cm, height - 1.4 * cm)

            self.setStrokeColor(RULE)
            self.setLineWidth(0.5)
            self.line(2 * cm, 1.7 * cm, width - 2 * cm, 1.7 * cm)
            self.setFont("Helvetica", 8)
            self.setFillColor(GREY)
            self.drawString(2 * cm, 1.15 * cm, "Automated analysis - review recommendations before acting")
            self.drawRightString(width - 2 * cm, 1.15 * cm, f"Page {self._pageNumber} of {total}")
            self.restoreState()

    return _NumberedCanvas


def _section(title, style):
    """Section heading (neeche line ke saath). keepWithNext se heading akeli page ke end pe nahi rehti"""
    t = Table([[Paragraph(_p(title), style)]], colWidths=[17 * cm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    t.keepWithNext = 1
    gap = Spacer(1, 6)
    gap.keepWithNext = 1
    return [Spacer(1, 14), t, gap]


def _callout(text, bg, border, fg, base_style):
    style = ParagraphStyle("Callout", parent=base_style, textColor=colors.HexColor(fg), fontSize=9.5, leading=13.5)
    t = Table([[Paragraph(_p(text), style)]], colWidths=[17 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def _conf_row(value, note_style):
    t = Table([[Paragraph("Confidence", note_style), ConfidenceBar(value, width=5 * cm)]],
              colWidths=[2.4 * cm, 5.2 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def build_pdf(incident: dict) -> bytes:
    incident = _clean_incident(incident)
    buffer = io.BytesIO()
    short_id = str(incident["id"])[:8]

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2.3 * cm,
        title="Incident Post-Mortem Report", author="Incident Response Console",
        subject=f"Incident {incident['id']}"
    )

    base = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica",
                          fontSize=10, leading=15, textColor=INK)
    note = ParagraphStyle("Note", parent=body, fontSize=9, leading=12, textColor=GREY)
    heading = ParagraphStyle("Heading", parent=body, fontName="Helvetica-Bold",
                             fontSize=12.5, leading=16, textColor=NAVY)
    mono = ParagraphStyle("Mono", parent=body, fontName="Courier", fontSize=8.6, leading=11.5)
    cell = ParagraphStyle("Cell", parent=body, fontSize=9, leading=12.5)
    cell_bold = ParagraphStyle("CellBold", parent=cell, fontName="Helvetica-Bold")
    cell_head = ParagraphStyle("CellHead", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    kicker = ParagraphStyle("Kicker", parent=body, fontName="Helvetica-Bold", fontSize=8.5,
                            leading=11, textColor=colors.HexColor("#93c5fd"), spaceAfter=4)
    b_title = ParagraphStyle("BTitle", parent=body, fontName="Helvetica-Bold", fontSize=22,
                             leading=27, textColor=colors.white, spaceAfter=4)
    b_meta = ParagraphStyle("BMeta", parent=body, fontSize=9, leading=13, textColor=RULE)
    t_label = ParagraphStyle("TLabel", parent=body, fontName="Helvetica-Bold", fontSize=7.5,
                             leading=10, textColor=GREY)
    t_value = ParagraphStyle("TValue", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=25)
    t_sub = ParagraphStyle("TSub", parent=body, fontSize=8.5, leading=11, textColor=GREY)
    num_style = ParagraphStyle("Num", parent=body, fontName="Helvetica-Bold", fontSize=11, textColor=NAVY)
    bullet = ParagraphStyle("Bullet", parent=body, fontSize=9.5, leading=14, leftIndent=12, bulletIndent=0)

    findings = incident.get("investigation_findings") or []
    actions = _split_actions(incident.get("suggested_fix"))
    pipeline, limits = _methodology(incident)
    rc, fc = incident.get("root_cause_confidence"), incident.get("fix_confidence")
    needs_review = bool(incident.get("needs_human_review"))
    story = []

    # ---- Banner ----
    banner = Table([[[
        Paragraph("INCIDENT POST-MORTEM REPORT", kicker),
        Paragraph("Root-Cause Analysis &amp; Remediation Plan", b_title),
        Paragraph(f"Incident {_p(incident['id'])} &nbsp;|&nbsp; Analysed {_p(_when(incident.get('created_at')))}", b_meta),
    ]]], colWidths=[17 * cm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(banner)

    # ---- 1. Executive summary + KPI tiles ----
    story += _section("1. Executive Summary", heading)
    story.append(Paragraph(_p(_executive_summary(incident)), body))
    story.append(Spacer(1, 10))

    def tile(label, value, sub, hex_color):
        return [
            Paragraph(_p(label), t_label),
            Paragraph(f'<font color="{hex_color}">{_p(value)}</font>', t_value),
            Paragraph(_p(sub), t_sub),
        ]

    n = _agent_count(incident)
    tiles = Table([[
        tile("AGENTS DEPLOYED", str(n), "parallel investigators", "#1e3a8a"),
        tile("ROOT-CAUSE CONFIDENCE", _pct(rc), f"{_level(rc)} confidence", LEVEL_HEX[_level(rc)]),
        tile("FIX CONFIDENCE", _pct(fc), f"{_level(fc)} confidence", LEVEL_HEX[_level(fc)]),
        tile("REVIEW STATUS", _review_short(needs_review),
             "human review" if needs_review else "no escalation",
             "#d97706" if needs_review else "#16a34a"),
    ]], colWidths=[4.25 * cm] * 4)
    tiles.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, NAVY),
        ("LINEAFTER", (0, 0), (2, 0), 6, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(tiles)

    # ---- 2. Incident details ----
    story += _section("2. Incident Details", heading)
    meta_rows = [
        ("Incident ID", str(incident["id"])),
        ("Analysed on", _when(incident.get("created_at"))),
        ("Report generated", _now()),
        ("Detection", _anomaly_text(incident.get("is_anomaly"))),
        ("Detection rationale", incident.get("anomaly_reason") or "N/A"),
    ]
    meta_table = Table(
        [[Paragraph(_p(k), cell_bold), Paragraph(_p(v), cell)] for k, v in meta_rows],
        colWidths=[4.2 * cm, 12.8 * cm]
    )
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)

    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Log entry</b>", note))
    story.append(Spacer(1, 3))
    raw_log = str(incident.get("raw_log") or "")
    if len(raw_log) > 6000:
        raw_log = raw_log[:6000] + "\n[... truncated for PDF ...]"
    log_box = Table([[Paragraph(_p(_soft_wrap(raw_log)), mono)]], colWidths=[17 * cm])
    log_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(log_box)

    # ---- 3. Investigation findings ----
    story += _section("3. Investigation Findings", heading)
    rows = [[Paragraph("Angle", cell_head), Paragraph("Finding", cell_head), Paragraph("Confidence", cell_head)]]
    for f in findings:
        rows.append([
            Paragraph(_p(f.get("angle")), cell_bold),
            Paragraph(_p(f.get("finding")), cell),
            ConfidenceBar(f.get("confidence")),
        ])
    findings_table = Table(rows, colWidths=[3.4 * cm, 9.6 * cm, 4.0 * cm], repeatRows=1)
    findings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(findings_table)

    # ---- 4. Root cause ----
    story += _section("4. Root Cause Analysis", heading)
    story.append(Paragraph(_p(incident.get("root_cause") or "N/A"), body))
    story.append(Spacer(1, 6))
    story.append(_conf_row(rc, note))

    # ---- 5. Remediation ----
    story += _section("5. Recommended Remediation", heading)
    if len(actions) > 1:
        step_rows = [[Paragraph(str(i), num_style), Paragraph(_p(a), body)] for i, a in enumerate(actions, 1)]
        steps = Table(step_rows, colWidths=[0.9 * cm, 16.1 * cm])
        steps.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(steps)
    else:
        story.append(Paragraph(_p(incident.get("suggested_fix") or "N/A"), body))
    story.append(Spacer(1, 6))
    story.append(_conf_row(fc, note))
    story.append(Spacer(1, 10))

    if needs_review:
        story.append(_callout(
            "Flagged for human review. An engineer should validate this diagnosis before any change is made.",
            "#fffbeb", "#f59e0b", "#92400e", body))
    else:
        story.append(_callout(
            "No escalation flagged: confidence scores were above the automatic review threshold. "
            "As with any automated analysis, an engineer should still review the recommendations before applying them.",
            "#f0fdf4", "#22c55e", "#166534", body))

    # ---- 6. Methodology & limitations ----
    story += _section("6. Methodology & Limitations", heading)
    story.append(Paragraph(_p(pipeline), body))
    story.append(Spacer(1, 6))
    for item in limits:
        story.append(Paragraph(_p(item), bullet, bulletText="\u2022"))

    story.append(Spacer(1, 16))
    story.append(Paragraph(f"Generated automatically by Incident Response Console on {_p(_now())}.", note))

    doc.build(story, canvasmaker=_make_canvas(short_id))
    return buffer.getvalue()
