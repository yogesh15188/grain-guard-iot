"""Build a judge-ready PDF from the persistent telemetry and event ledger."""
from __future__ import annotations

import io
import json
import os
import threading
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MAX_TELEMETRY_ROWS = 500
MAX_EVENT_ROWS = 500
_FONT_LOCK = threading.Lock()
INK = colors.HexColor("#242820")
GREEN = colors.HexColor("#476b45")
PALE_GREEN = colors.HexColor("#eaf0e6")
PALE_GRAY = colors.HexColor("#f3f4f1")
LINE = colors.HexColor("#d8ddd4")


def _register_fonts():
    windows = os.environ.get("WINDIR", r"C:\Windows")
    candidates = (
        (os.path.join(windows, "Fonts", "arial.ttf"),
         os.path.join(windows, "Fonts", "arialbd.ttf")),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    for regular, bold in candidates:
        if os.path.isfile(regular) and os.path.isfile(bold):
            with _FONT_LOCK:
                if "GrainGuardSans" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("GrainGuardSans", regular))
                    pdfmetrics.registerFont(TTFont("GrainGuardSans-Bold", bold))
            return "GrainGuardSans", "GrainGuardSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _paragraph(text, style):
    return Paragraph(escape(str(text if text is not None else "—")).replace("\n", "<br/>"), style)


def _timestamp(value):
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return str(value)


def _page_footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(14 * mm, 13 * mm, landscape(A4)[0] - 14 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#596255"))
    canvas.drawString(14 * mm, 8 * mm, "GrainGuard | Local sensor audit export")
    canvas.drawRightString(
        landscape(A4)[0] - 14 * mm, 8 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_audit_pdf(snapshot: dict, facility: dict) -> io.BytesIO:
    """Render current decision, latest readings, ledger events and acknowledgments."""
    regular, bold = _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="GGTitle", parent=styles["Title"], fontName=bold, fontSize=20,
        leading=24, textColor=INK, alignment=TA_CENTER, spaceAfter=5))
    styles.add(ParagraphStyle(
        name="GGSubtitle", parent=styles["Normal"], fontName=regular, fontSize=9,
        leading=12, textColor=colors.HexColor("#5c6658"), alignment=TA_CENTER))
    styles.add(ParagraphStyle(
        name="GGHeading", parent=styles["Heading2"], fontName=bold, fontSize=12,
        leading=15, textColor=GREEN, spaceBefore=9, spaceAfter=5))
    styles.add(ParagraphStyle(
        name="GGBody", parent=styles["BodyText"], fontName=regular, fontSize=8,
        leading=11, textColor=INK, spaceAfter=3))
    styles.add(ParagraphStyle(
        name="GGSmall", parent=styles["BodyText"], fontName=regular, fontSize=6.5,
        leading=8, textColor=INK, wordWrap="CJK"))
    styles.add(ParagraphStyle(
        name="GGSmallBold", parent=styles["BodyText"], fontName=bold, fontSize=6.5,
        leading=8, textColor=INK, wordWrap="CJK"))

    buffer = io.BytesIO()
    page_size = landscape(A4)
    document = SimpleDocTemplate(
        buffer, pagesize=page_size, rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=13 * mm, bottomMargin=19 * mm,
        title="GrainGuard Sensor Audit Trail",
        author="GrainGuard",
        subject="Telemetry decisions, alerts and append-only ledger integrity",
    )
    story = [
        Paragraph("GrainGuard Sensor Audit Trail", styles["GGTitle"]),
        Paragraph(
            f"Generated {_timestamp(datetime.now().astimezone().isoformat())} "
            "| Report data is read from the local SQLite ledger.",
            styles["GGSubtitle"]),
        Spacer(1, 7 * mm),
        Paragraph("Facility and report coverage", styles["GGHeading"]),
    ]

    telemetry = snapshot.get("telemetry", [])
    events = snapshot.get("events", [])
    acknowledgments = snapshot.get("acknowledgments", [])
    latest = telemetry[-1] if telemetry else None
    totals = [
        ["Facility", facility.get("name", "GrainGuard Facility"),
         "Commodity", facility.get("commodity") or "—"],
        ["Bin / location", facility.get("bin") or "—",
         "Generated at", _timestamp(datetime.now().astimezone().isoformat())],
        ["Telemetry records", str(snapshot.get("telemetry_total", len(telemetry))),
         "Included in report", f"Latest {len(telemetry)}"],
        ["Ledger events", str(snapshot.get("event_total", len(events))),
         "Acknowledgments", str(snapshot.get("acknowledgment_total", len(acknowledgments)))],
    ]
    summary = Table(totals, colWidths=[31 * mm, 66 * mm, 34 * mm, 95 * mm])
    summary.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), regular),
        ("FONTNAME", (0, 0), (0, -1), bold),
        ("FONTNAME", (2, 0), (2, -1), bold),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (0, -1), PALE_GREEN),
        ("BACKGROUND", (2, 0), (2, -1), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary)

    chain = snapshot.get("chain") or {}
    chain_state = "INTACT" if all(
        chain.get(table) is True
        for table in ("telemetry", "events", "acknowledgments")
    ) else f"BROKEN — {chain.get('detail') or 'integrity check failed'}"
    story.extend([
        Paragraph("Ledger integrity", styles["GGHeading"]),
        _paragraph(
            f"Telemetry: {'INTACT' if chain.get('telemetry') else 'BROKEN'} | "
            f"Events: {'INTACT' if chain.get('events') else 'BROKEN'} | "
            f"Acknowledgments: {'INTACT' if chain.get('acknowledgments') else 'BROKEN'} "
            f"| Overall: {chain_state}",
            styles["GGBody"]),
    ])

    story.append(Paragraph("Latest engine decision and causes", styles["GGHeading"]))
    if latest:
        try:
            result = json.loads(latest.get("result_json") or "{}")
        except (TypeError, ValueError):
            result = {}
        facts = result.get("facts") or {}
        decision = [
            ["Sample time", _timestamp(latest.get("ts")),
             "Source", latest.get("source") or "—"],
            ["State / risk", f"{latest.get('state') or '—'} / {latest.get('risk') or '—'}",
             "Rule", latest.get("rule") or "No rule recorded"],
            ["Temperature", f"{latest.get('temp') if latest.get('temp') is not None else '—'} °C",
             "Relative humidity", f"{latest.get('rh') if latest.get('rh') is not None else '—'} %"],
            ["Fork / proximity", latest.get("fork_raw"),
             "Light sensor", latest.get("ldr_raw")],
            ["Distance", latest.get("distance_cm"),
             "EMC estimate", facts.get("emc_estimate")],
        ]
        decision_table = Table(decision, colWidths=[34 * mm, 76 * mm, 38 * mm, 78 * mm])
        decision_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), regular),
            ("FONTNAME", (0, 0), (0, -1), bold),
            ("FONTNAME", (2, 0), (2, -1), bold),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("BACKGROUND", (0, 0), (0, -1), PALE_GRAY),
            ("BACKGROUND", (2, 0), (2, -1), PALE_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(decision_table)
        story.append(_paragraph(
            "Engine evidence: " + ("; ".join(result.get("evidence") or [])
                                  or "No threshold evidence recorded."),
            styles["GGBody"]))
    else:
        story.append(_paragraph("No telemetry has been recorded yet.", styles["GGBody"]))

    story.append(Paragraph(
        f"Recent telemetry ({len(telemetry)} of "
        f"{snapshot.get('telemetry_total', len(telemetry))} records)",
        styles["GGHeading"]))
    data = [[
        "ID", "Timestamp", "Source", "Temp °C", "RH %", "Fork", "Light",
        "Distance cm", "Engine state / risk",
    ]]
    for row in telemetry:
        state = row.get("state") or "—"
        risk = row.get("risk") or "—"
        data.append([
            str(row.get("id", "")),
            _paragraph(_timestamp(row.get("ts")), styles["GGSmall"]),
            _paragraph(row.get("source"), styles["GGSmall"]),
            str(row.get("temp") if row.get("temp") is not None else "—"),
            str(row.get("rh") if row.get("rh") is not None else "—"),
            str(row.get("fork_raw") if row.get("fork_raw") is not None else "—"),
            str(row.get("ldr_raw") if row.get("ldr_raw") is not None else "—"),
            str(row.get("distance_cm") if row.get("distance_cm") is not None else "—"),
            _paragraph(f"{state} / {risk}<br/>{row.get('rule') or ''}",
                       styles["GGSmall"]),
        ])
    telemetry_table = LongTable(
        data, repeatRows=1,
        colWidths=[10 * mm, 34 * mm, 17 * mm, 16 * mm, 15 * mm,
                   15 * mm, 15 * mm, 20 * mm, 84 * mm],
        splitByRow=1,
    )
    telemetry_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), regular),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
    ]))
    story.append(telemetry_table)

    story.append(Paragraph(
        f"Event and alert trail ({len(events)} of "
        f"{snapshot.get('event_total', len(events))} events)",
        styles["GGHeading"]))
    event_data = [["ID", "Timestamp", "Kind", "State / risk", "Decision / evidence"]]
    for event in events:
        try:
            detail = json.loads(event.get("detail_json") or "{}")
        except (TypeError, ValueError):
            detail = {}
        alert = detail.get("alert") or {}
        explanation = (
            f"{event.get('rule') or ''} {alert.get('title') or ''} "
            f"{alert.get('evidence') or ''} {detail.get('note') or ''}"
        ).strip()
        if not explanation:
            explanation = str(detail.get("evidence") or detail.get("seconds") or "")
        event_data.append([
            str(event.get("id", "")),
            _paragraph(_timestamp(event.get("ts")), styles["GGSmall"]),
            _paragraph(event.get("kind"), styles["GGSmall"]),
            _paragraph(f"{event.get('state') or '—'} / {event.get('risk') or '—'}",
                       styles["GGSmall"]),
            _paragraph(explanation or "—", styles["GGSmall"]),
        ])
    event_table = LongTable(
        event_data, repeatRows=1,
        colWidths=[12 * mm, 36 * mm, 34 * mm, 45 * mm, 119 * mm],
        splitByRow=1,
    )
    event_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), regular),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("BACKGROUND", (0, 0), (-1, 0), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
    ]))
    story.append(event_table)

    alert_events = []
    for event in events:
        if event.get("kind") != "ALERT":
            continue
        try:
            detail = json.loads(event.get("detail_json") or "{}")
        except (TypeError, ValueError):
            detail = {}
        alert = detail.get("alert") or {}
        alert_events.append((event, alert))
    story.append(Paragraph(
        f"Recorded alert causes and recommended checks ({len(alert_events)} included)",
        styles["GGHeading"]))
    if alert_events:
        for event, alert in alert_events:
            story.append(_paragraph(
                f"{_timestamp(event.get('ts'))} | "
                f"{alert.get('severity', '').upper()} — {alert.get('title', '')}. "
                f"Evidence: {alert.get('evidence', '—')}. "
                f"Consistent with: {alert.get('consistency', '—')}. "
                f"Recommended checks: {'; '.join(alert.get('actions') or []) or '—'}",
                styles["GGBody"]))
    else:
        story.append(_paragraph(
            "No alert-raise events are present in the included event window.",
            styles["GGBody"]))

    story.append(Paragraph("Operator acknowledgments", styles["GGHeading"]))
    ack_data = [["ID", "Timestamp", "Operator", "Event ID", "Verified", "Note"]]
    for ack in acknowledgments:
        ack_data.append([
            str(ack.get("id", "")),
            _paragraph(_timestamp(ack.get("ts")), styles["GGSmall"]),
            _paragraph(ack.get("operator"), styles["GGSmall"]),
            str(ack.get("event_id") or "—"),
            "YES" if ack.get("verified") else "NO",
            _paragraph(ack.get("note") or "—", styles["GGSmall"]),
        ])
    ack_table = LongTable(
        ack_data, repeatRows=1,
        colWidths=[12 * mm, 38 * mm, 43 * mm, 22 * mm, 20 * mm, 111 * mm],
        splitByRow=1,
    )
    ack_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), regular),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("BACKGROUND", (0, 0), (-1, 0), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(ack_table)

    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    buffer.seek(0)
    return buffer
