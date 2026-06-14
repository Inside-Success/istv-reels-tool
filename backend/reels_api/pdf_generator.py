import os
from io import BytesIO
from datetime import datetime
from html import escape as html_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    PageBreak,
    HRFlowable,
)
from reportlab.pdfgen import canvas as rl_canvas
from PIL import Image

from reels_api.transcription import fmt_time
from reels_api.transcript_snippets import verbatim_from_words

# ── Palette ────────────────────────────────────────────────────────────────────
C_BLACK  = HexColor("#000000")
C_WHITE  = HexColor("#FFFFFF")
C_DARK   = HexColor("#1a1a1a")
C_MID    = HexColor("#555555")
C_LIGHT  = HexColor("#cccccc")
C_XLIGHT = HexColor("#e8e8e8")


# ── Style sheet ────────────────────────────────────────────────────────────────

def _styles() -> dict:
    return {
        "cover_h1": ParagraphStyle(
            "cover_h1", fontName="Helvetica-Bold", fontSize=54,
            textColor=C_WHITE, alignment=TA_CENTER, leading=58, spaceAfter=4,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName="Helvetica", fontSize=12,
            textColor=C_LIGHT, alignment=TA_CENTER, letterSpacing=5,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontName="Helvetica", fontSize=9,
            textColor=C_MID, alignment=TA_CENTER,
        ),
        "section_h": ParagraphStyle(
            "section_h", fontName="Helvetica-Bold", fontSize=20,
            textColor=C_WHITE, letterSpacing=3,
        ),
        "reel_num": ParagraphStyle(
            "reel_num", fontName="Helvetica-Bold", fontSize=38, textColor=C_WHITE,
        ),
        "reel_ts": ParagraphStyle(
            "reel_ts", fontName="Helvetica", fontSize=12,
            textColor=C_LIGHT, alignment=TA_RIGHT,
        ),
        "reel_title": ParagraphStyle(
            "reel_title", fontName="Helvetica-Bold", fontSize=16,
            textColor=C_BLACK, spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label", fontName="Helvetica-Bold", fontSize=7,
            textColor=C_MID, letterSpacing=2, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=9,
            textColor=C_DARK, leading=14, spaceAfter=5,
        ),
        "quote": ParagraphStyle(
            "quote", fontName="Helvetica-Oblique", fontSize=10,
            textColor=C_BLACK, leading=16, spaceAfter=5,
            leftIndent=12, rightIndent=12,
        ),
        "ts_word": ParagraphStyle(
            "ts_word", fontName="Helvetica", fontSize=7,
            textColor=C_DARK, leading=11, spaceAfter=2,
        ),
        "km_hdr": ParagraphStyle(
            "km_hdr", fontName="Helvetica-Bold", fontSize=7,
            textColor=C_BLACK, spaceAfter=1,
        ),
        "km_q": ParagraphStyle(
            "km_q", fontName="Helvetica-Oblique", fontSize=8,
            textColor=C_DARK, leading=12, spaceAfter=5,
        ),
    }


def _ptext(value) -> str:
    """Escape text for ReportLab Paragraph's small HTML subset."""
    return html_escape(str(value or ""), quote=False).replace("\n", "<br/>")


# ── Page-numbering canvas ──────────────────────────────────────────────────────

class _PageCanvas(rl_canvas.Canvas):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                self.setFillColor(C_MID)
                self.setFont("Helvetica", 7)
                self.drawString(2 * cm, 1.1 * cm, "INSIDE SUCCESS — REEL SUGGESTIONS")
                self.drawRightString(
                    A4[0] - 2 * cm, 1.1 * cm, f"{self._pageNumber} / {total}"
                )
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)


# ── PIL image → ReportLab Image ────────────────────────────────────────────────

def _rl_image(pil_img: Image.Image, width_cm: float, aspect: float = 9 / 16) -> RLImage:
    buf = BytesIO()
    pil_img.convert("L").save(buf, format="PNG")
    buf.seek(0)
    w = width_cm * cm
    return RLImage(buf, width=w, height=w * aspect)


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_pdf(
    analysis: dict,
    thumbnails: list,
    transcript: dict,
    output_path: str,
    video_filename: str = "Documentary",
) -> str:
    s = _styles()
    pw = A4[0] - 4 * cm  # printable width ≈ 17 cm

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.5 * cm, bottomMargin=2 * cm,
        title="Inside Success — Reel Suggestions",
        author="Inside Success Reels Tool",
    )

    story = []
    reels = analysis.get("reels", [])
    brand = analysis.get("brand_story", {})

    # ── COVER ──────────────────────────────────────────────────────────────────
    cover_rows = [
        [Paragraph("INSIDE", s["cover_h1"])],
        [Paragraph("SUCCESS", s["cover_h1"])],
        [Spacer(1, 0.5 * cm)],
        [HRFlowable(width="65%", thickness=2, color=C_WHITE, spaceAfter=0)],
        [Spacer(1, 0.4 * cm)],
        [Paragraph("REEL SUGGESTIONS REPORT", s["cover_sub"])],
        [Spacer(1, 0.6 * cm)],
        [Paragraph(video_filename.upper(), s["cover_meta"])],
        [Paragraph(datetime.now().strftime("%B %d, %Y").upper(), s["cover_meta"])],
    ]
    cover_tbl = Table(cover_rows, colWidths=[pw])
    cover_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLACK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(cover_tbl)
    story.append(Spacer(1, 1 * cm))

    stat_s = ParagraphStyle(
        "stat", fontName="Helvetica", fontSize=13,
        textColor=C_BLACK, alignment=TA_CENTER,
    )
    stats = Table(
        [[
            Paragraph(f"<b>{len(reels)}</b><br/>REELS", stat_s),
            Paragraph(f"<b>{transcript.get('word_count', 0):,}</b><br/>WORDS", stat_s),
            Paragraph(f"<b>{fmt_time(transcript.get('duration', 0))}</b><br/>RUNTIME", stat_s),
        ]],
        colWidths=[pw / 3] * 3,
    )
    stats.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_XLIGHT),
        ("GRID",          (0, 0), (-1, -1), 1, C_WHITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(stats)
    story.append(PageBreak())

    # ── Documentary cut sheet (join in sequence) ───────────────────────────────
    story += _section_header("DOCUMENTARY — CUT & JOIN (sequence order)", s, pw)
    story += _documentary_cut_sheet_table(brand, s, pw, transcript)
    story.append(PageBreak())

    # ── REEL PAGES (nested hook + parts) ──────────────────────────────────────
    for idx, reel in enumerate(reels):
        thumb = thumbnails[idx] if idx < len(thumbnails) else None
        story += _reel_section(reel, thumb, s, pw)
        if idx < len(reels) - 1:
            story.append(PageBreak())

    story.append(PageBreak())
    story += _section_header("BRAND COPY (reference)", s, pw)
    story += _brand_reference_section(brand, s, pw)

    doc.build(story, canvasmaker=_PageCanvas)
    return output_path


def _documentary_cut_sheet_table(brand: dict, s: dict, pw: float, transcript: dict) -> list:
    out = []
    words = transcript.get("words") or []
    note = brand.get("cut_sheet_assembly_note") or ""
    if note:
        out.append(Paragraph(_ptext(note), s["body"]))
        out.append(Spacer(1, 0.3 * cm))

    cuts = brand.get("documentary_cut_sheet") or []
    if not cuts:
        out.append(Paragraph("No documentary cut sheet in this analysis.", s["body"]))
        return out

    rows = [["SEQ", "SECTION", "IN", "OUT", "s", "VERBATIM", "CUT"]]
    for row in cuts:
        try:
            a = float(row.get("start_time_seconds") or 0)
            b = float(row.get("end_time_seconds") or 0)
        except (TypeError, ValueError):
            a, b = 0.0, 0.0
        dur = max(0.0, b - a)
        vtxt = str(row.get("verbatim_transcript") or "").strip() or verbatim_from_words(words, a, b)
        rows.append([
            str(int(row.get("sequence", 0))),
            _ptext(row.get("section_title", "")),
            fmt_time(a),
            fmt_time(b),
            f"{dur:.0f}",
            _ptext(vtxt[:900]),
            _ptext(row.get("cut_instruction", "")),
        ])
    tbl = Table(
        rows,
        colWidths=[0.06 * pw, 0.16 * pw, 0.09 * pw, 0.09 * pw, 0.05 * pw, 0.30 * pw, 0.25 * pw],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_BLACK),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_XLIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.25, C_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    out.append(tbl)
    return out


def _brand_reference_section(brand: dict, s: dict, pw: float) -> list:
    elems = []
    headline = brand.get("seo_headline") or brand.get("headline")
    if headline:
        elems.append(Paragraph("SEO HEADLINE", s["label"]))
        elems.append(Paragraph(f"\"{_ptext(headline)}\"", s["quote"]))
    if brand.get("meta_description"):
        elems.append(Paragraph("META", s["label"]))
        elems.append(Paragraph(_ptext(brand["meta_description"]), s["body"]))
    for label, value in [
        ("FOUNDER", brand.get("founder_name")),
        ("COMPANY", brand.get("company_name")),
    ]:
        if value:
            elems.append(Paragraph(f"{label}: {_ptext(str(value))}", s["label"]))
    full_story = brand.get("full_story") or brand.get("core_message")
    if full_story:
        elems.append(Spacer(1, 0.25 * cm))
        elems.append(Paragraph("FULL STORY (reference)", s["label"]))
        elems.append(Paragraph(_ptext(full_story), s["body"]))
    j = brand.get("journey_arc", {})
    if j:
        journey_rows = [
            ("ORIGIN", j.get("origin") or j.get("challenge", "")),
            ("THE LEAP", j.get("leap") or j.get("turning_point", "")),
            ("STRUGGLE", j.get("struggle", "")),
            ("BREAKTHROUGH", j.get("breakthrough", "")),
            ("TODAY", j.get("today") or j.get("outcome", "")),
            ("VISION", j.get("vision", "")),
        ]
        journey_data = [
            [label, Paragraph(_ptext(value), s["body"])]
            for label, value in journey_rows
            if value
        ]
        if journey_data:
            elems.append(Spacer(1, 0.3 * cm))
            journey = Table(journey_data, colWidths=[3.2 * cm, pw - 3.2 * cm])
            journey.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (0, -1), C_DARK),
                ("BACKGROUND",    (1, 0), (1, -1), C_XLIGHT),
                ("TEXTCOLOR",     (0, 0), (0, -1), C_WHITE),
                ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("GRID",          (0, 0), (-1, -1), 0.5, C_WHITE),
            ]))
            elems.append(journey)
    return elems


# ── Section builders ───────────────────────────────────────────────────────────

def _section_header(title: str, s: dict, pw: float) -> list:
    hdr = Table([[Paragraph(title, s["section_h"])]], colWidths=[pw])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLACK),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
    ]))
    return [hdr, Spacer(1, 0.4 * cm)]


def _moment_row(m: dict, s: dict, pw: float) -> Table:
    ts = fmt_time(m.get("timestamp_seconds", 0))
    moment = m.get("moment_type") or m.get("moment") or "MOMENT"
    right = [Paragraph(_ptext(moment), s["body"])]
    significance = m.get("narrative_significance") or m.get("significance")
    if significance:
        right.append(Paragraph(
            _ptext(significance),
            ParagraphStyle("sig", fontName="Helvetica", fontSize=8,
                           textColor=C_MID, leading=12),
        ))
    if m.get("quote"):
        right.append(Paragraph(f"\"{_ptext(m['quote'])}\"", s["quote"]))
    t = Table(
        [[[ Paragraph(f"[{ts}]", s["label"]) ], right]],
        colWidths=[1.8 * cm, pw - 1.8 * cm],
    )
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.4, C_XLIGHT),
    ]))
    return t


def _reel_section(reel: dict, thumb, s: dict, pw: float) -> list:
    """Header + nested cut table (full reel → hook line window → other parts) + short transcript preview."""
    elems = []
    rs = float(reel.get("start_time_seconds") or 0)
    re_ = float(reel.get("end_time_seconds") or 0)
    hs = float(reel.get("hook_line_start_seconds", rs))
    he = float(reel.get("hook_line_end_seconds", min(rs + 5.0, re_)))

    bar = Table(
        [[
            Paragraph(f"REEL {reel.get('id', '')}", s["reel_num"]),
            Paragraph(
                f"{fmt_time(rs)} — {fmt_time(re_)}"
                f"<font size='10'> ({reel.get('duration_seconds', max(0, re_ - rs)):.0f}s)</font>",
                s["reel_ts"],
            ),
        ]],
        colWidths=[pw * 0.55, pw * 0.45],
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLACK),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",   (0, 0), (0, 0),   12),
        ("RIGHTPADDING",  (1, 0), (1, 0),   12),
    ]))
    elems.append(bar)
    elems.append(Spacer(1, 0.25 * cm))
    elems.append(Paragraph(_ptext((reel.get("title") or "").upper()), s["reel_title"]))
    if reel.get("assembly_note"):
        elems.append(Paragraph(_ptext(reel["assembly_note"]), s["body"]))
    elems.append(Spacer(1, 0.2 * cm))

    if thumb:
        elems.append(_rl_image(thumb, width_cm=9))
        elems.append(Spacer(1, 0.25 * cm))

    hook = reel.get("hook_line") or reel.get("hook") or ""
    elems.append(Paragraph("HOOK LINE (verbatim)", s["label"]))
    elems.append(
        Paragraph(
            f"{fmt_time(hs)} — {fmt_time(he)}  |  \"{_ptext(hook)}\"",
            s["quote"],
        )
    )
    elems.append(Spacer(1, 0.25 * cm))

    rows = [["LEVEL", "PART", "IN", "OUT", "s", "NOTE"]]
    dur_full = max(0.0, re_ - rs)
    rows.append([
        "REEL",
        "Full master take",
        fmt_time(rs),
        fmt_time(re_),
        f"{dur_full:.0f}",
        _ptext(" | ".join(x for x in [str(reel.get("hook_type", "") or ""), str(reel.get("why_this_hooks", "") or "")] if x)),
    ])
    rows.append([
        "HOOK",
        "Opening hook line",
        fmt_time(hs),
        fmt_time(he),
        f"{max(0.0, he - hs):.0f}",
        _ptext(hook[:280]),
    ])
    for part in reel.get("editor_cut_sheet") or []:
        label_up = str(part.get("label", "") or "").upper()
        if "OPENING HOOK" in label_up or "HOOK LINE" in label_up:
            continue
        try:
            a = float(part.get("start_time_seconds") or 0)
            b = float(part.get("end_time_seconds") or 0)
        except (TypeError, ValueError):
            a, b = 0.0, 0.0
        rows.append([
            "PART",
            _ptext(part.get("label", "")),
            fmt_time(a),
            fmt_time(b),
            f"{max(0.0, b - a):.0f}",
            _ptext(part.get("note", "")),
        ])

    cut_tbl = Table(
        rows,
        colWidths=[0.09 * pw, 0.24 * pw, 0.11 * pw, 0.11 * pw, 0.06 * pw, 0.39 * pw],
    )
    cut_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_DARK),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_XLIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.25, C_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(cut_tbl)
    elems.append(Spacer(1, 0.3 * cm))

    elems.append(Paragraph("TRANSCRIPT PREVIEW (optional)", s["label"]))
    words = reel.get("timestamped_words", [])
    chunk_size = 14
    if words:
        for i in range(0, min(len(words), chunk_size * 5), chunk_size):
            group = words[i: i + chunk_size]
            ts = group[0]["ts"]
            text = " ".join(w["word"] for w in group)
            elems.append(Paragraph(
                f'<font color="#999999">[{ts}]</font>  {_ptext(text)}', s["ts_word"]
            ))
    else:
        elems.append(Paragraph(_ptext(reel.get("transcript_excerpt", "—")), s["body"]))

    return elems
