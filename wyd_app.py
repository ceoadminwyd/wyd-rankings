"""
WYD Super Saturday Rankings Generator
Upload the WYD Hierarchy PDF → auto-extract → compute Top 5 → download medals PDF
"""

import sys, io, re
sys.stdout.reconfigure(encoding="utf-8")

import streamlit as st
import fitz
import pandas as pd

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Colors ────────────────────────────────────────────────────────────────────
PAGE_BG  = colors.HexColor("#060608")
PANEL    = colors.HexColor("#0E0E16")
PANEL2   = colors.HexColor("#12121C")
CHARCOAL = colors.HexColor("#1A1A24")
GOLD     = colors.HexColor("#D4AF37")
GOLD_D   = colors.HexColor("#967A20")
GOLD_LT  = colors.HexColor("#F0D060")
SILVER   = colors.HexColor("#B0B0C0")
BRONZE   = colors.HexColor("#CD7F32")
CREAM    = colors.HexColor("#F5F0E8")
MUTED    = colors.HexColor("#888899")
WHITE    = colors.white

# ── Parser ────────────────────────────────────────────────────────────────────
# The WYD Hierarchy PDF stores each entry as 5 consecutive lines:
#   Line 1: Agent name
#   Line 2: Rank number (1, 2, 3…)
#   Line 3: REP ID (5 alphanumeric chars, e.g. PCD8Y)
#   Line 4: Title code (REP, SRP, DIS, DIV, REG, SRL, RVP, SVP)
#   Line 5: "value  upline_name"

TITLE_CODES = {"REP", "SRP", "DIS", "DIV", "REG", "SRL", "RVP", "SVP"}
REPID_RE    = re.compile(r"^[A-Z0-9]{4,6}$")
RANK_RE     = re.compile(r"^\d{1,3}$")
VALUE_RE    = re.compile(r"^([\d,\.]+)\s+(.+)$")

# Section header fragments → internal key
SECTION_MAP = [
    ("Personal Submitted Recruits",  "ps_rec"),
    ("Personal Submitted Premium",   "ps_pre"),
    ("Personal New REPs",            "ps_nr"),
    ("Personal New Rep",             "ps_nr"),
    ("Personal Securities",          "ps_sec"),
    ("Base Submitted Recruits",      "bs_rec"),
    ("Base Submitted Premium",       "bs_pre"),
    ("Personal Cash",                "ps_cash"),
    ("Base New Builders Premium",    "bs_nbp"),
]

# Level header fragments → level label
LEVEL_MAP = [
    (["REPs/SRPs", "REP/SRP", "REP / SRP"],              "REP/SRP"),
    (["DISs & SRPs", "DIS & SRP", "DISs -", "DISs–"],    "DIS"),
    (["DIVs", "DIV -", "DIVs -"],                         "DIV"),
    (["REGs/SRLs", "REG/SRL", "REGs -"],                  "REG/SRL"),
    (["SVPs & RVPs", "SVP & RVP", "SVPs", "RVPs"],        "RVP+"),
    (["All REPs", "All -"],                                "ALL"),
]

SKIP_EXACT = {
    "Rank", "REP Id", "Title", "Name", "Amount Upline",
    "WYD Hierarchy SS", "Page",
}
SKIP_STARTS = (
    "Prepared for:", "February 2026", "March 2026", "January 2026",
    "April 2026", "May 2026", "June 2026", "July 2026",
    "August 2026", "September 2026", "October 2026", "November 2026",
    "December 2026", "Page ",
)
SKIP_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def is_skip(line: str) -> bool:
    if not line:
        return True
    if line in SKIP_EXACT:
        return True
    if line.startswith(SKIP_STARTS):
        return True
    if SKIP_RE.match(line):
        return True
    return False


def detect_section(line: str):
    for phrase, key in SECTION_MAP:
        if phrase.lower() in line.lower():
            return key
    return None


def detect_level(line: str):
    u = re.sub(r'\s+', ' ', line).upper()
    for keywords, label in LEVEL_MAP:
        for kw in keywords:
            if kw.upper() in u:
                return label
    return None


def parse_pdf(pdf_bytes: bytes) -> dict:
    """Returns {section_key: {level_label: [(rank, name, upline, raw_value), ...]}}"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    lines = []
    for page in doc:
        for ln in page.get_text().splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)

    data = {}
    cur_sec = None
    cur_lvl = "ALL"
    i = 0

    while i < len(lines):
        line = lines[i]

        sec = detect_section(line)
        if sec:
            cur_sec = sec
            cur_lvl = "ALL"
            data.setdefault(cur_sec, {})
            i += 1
            continue

        lvl = detect_level(line)
        if lvl and cur_sec:
            cur_lvl = lvl
            data[cur_sec].setdefault(cur_lvl, [])
            i += 1
            continue

        if is_skip(line):
            i += 1
            continue

        if cur_sec is None:
            i += 1
            continue

        if i + 4 < len(lines):
            name_l  = lines[i]
            rank_l  = lines[i + 1]
            repid_l = lines[i + 2]
            title_l = lines[i + 3]
            val_l   = lines[i + 4]

            if (RANK_RE.match(rank_l) and
                    REPID_RE.match(repid_l) and
                    title_l in TITLE_CODES and
                    not detect_section(name_l) and
                    not detect_level(name_l)):
                vm = VALUE_RE.match(val_l)
                if vm:
                    raw_value = vm.group(1)
                    upline    = vm.group(2).strip()
                    upline = re.sub(r'\s+(A\.?N\.?D\.?|Rb?\s+An[d]?|Mfg|Eb|BC|And?)\s*$',
                                    '', upline, flags=re.IGNORECASE).strip()
                    clean_name = name_l.replace(" W Y D", " WYD").strip()
                    entry = (int(rank_l), clean_name, upline, raw_value, title_l)
                    data[cur_sec].setdefault(cur_lvl, []).append(entry)
                    i += 5
                    continue

        i += 1

    return data


# ── Rankings ──────────────────────────────────────────────────────────────────
def parse_val(v: str) -> float:
    return float(re.sub(r"[^\d\.]", "", v) or 0)


def top5(entries: list, tb_entries: list = None) -> list:
    if not entries:
        return []
    seen = {}
    for e in entries:
        name = e[1].upper()
        if name not in seen or parse_val(e[3]) > parse_val(seen[name][3]):
            seen[name] = e
    unique = sorted(seen.values(), key=lambda e: parse_val(e[3]), reverse=True)

    tb_map = {}
    if tb_entries:
        for t in tb_entries:
            tb_map[t[1].upper()] = parse_val(t[3])

    result = []
    i = 0
    display_rank = 1
    while i < len(unique) and display_rank <= 5:
        e   = unique[i]
        val = parse_val(e[3])
        j = i + 1
        while j < len(unique) and parse_val(unique[j][3]) == val:
            j += 1
        tied = unique[i:j]

        if len(tied) == 1:
            result.append((display_rank, e[1], e[2], e[3], ""))
            display_rank += 1
        else:
            if tb_map:
                tied_s = sorted(tied, key=lambda t: tb_map.get(t[1].upper(), 0), reverse=True)
                rank_offset = 0
                k = 0
                while k < len(tied_s) and display_rank + rank_offset <= 5:
                    t   = tied_s[k]
                    tbv = tb_map.get(t[1].upper(), 0)
                    if tbv > 0:
                        note = f"Tiebreaker: ${tbv:,.0f} personal premium"
                    else:
                        note = "Tied — no premium data to break tie; confirm with leadership"
                    result.append((display_rank + rank_offset, t[1], t[2], t[3], note))
                    rank_offset += 1
                    k += 1
                display_rank += rank_offset
            else:
                for t in tied:
                    if display_rank > 5:
                        break
                    result.append((display_rank, t[1], t[2], t[3], "Tied — confirm order with leadership"))
                display_rank += len(tied)
        i = j

    return result[:5]


SPLIT_SECS   = {"ps_nr", "ps_sec", "ps_cash"}
BELOW_LEVELS = {"REP/SRP", "DIS", "DIV", "REG/SRL", "ALL"}
ABOVE_LEVELS = {"RVP+"}


def compute_rankings(data: dict, include: dict,
                     cash_months: int = 3,
                     cash_below_avg: int = 4000,
                     cash_rvp_avg: int = 8000) -> dict:
    above_titles = {"RVP", "SVP"}
    rankings = {}
    for sec_key, levels in data.items():
        if not include.get(sec_key, True):
            continue
        rankings[sec_key] = {}

        pre_key  = sec_key.replace("_rec", "_pre").replace("_nr", "_pre")
        pre_data = data.get(pre_key, {})

        all_entries = [e for lvl_e in levels.values() for e in lvl_e]
        all_pre     = [e for lvl_e in pre_data.values() for e in lvl_e]
        if all_entries:
            rankings[sec_key]["Overall Top 5"] = top5(all_entries, all_pre or None)

        for lvl, entries in levels.items():
            pre_lvl = pre_data.get(lvl, [])
            result  = top5(entries, pre_lvl or None)
            if result:
                rankings[sec_key][lvl] = result

        # For sections that split Below/Above RVP, split by title code
        if sec_key in SPLIT_SECS:
            all_e     = [e for lvl_e in levels.values() for e in lvl_e]
            below_raw = [e for e in all_e if not (len(e) >= 5 and e[4] in above_titles)]
            above_raw = [e for e in all_e if len(e) >= 5 and e[4] in above_titles]

            # Apply minimum income filter for Personal Cash
            if sec_key == "ps_cash":
                min_below = cash_months * cash_below_avg
                min_above = cash_months * cash_rvp_avg
                below_raw = [e for e in below_raw if parse_val(e[3]) >= min_below]
                above_raw = [e for e in above_raw if parse_val(e[3]) >= min_above]

            if below_raw:
                rankings[sec_key]["Below RVP"] = top5(below_raw)
            if above_raw:
                rankings[sec_key]["Above RVP"] = top5(above_raw)

    return rankings


def compute_top_gun(data: dict) -> dict:
    """Best personal performer per category, split Below RVP / RVP & Above."""
    below_levels = {"REP/SRP", "DIS", "DIV", "REG/SRL", "ALL"}
    above_levels = {"RVP+"}

    def best(sec_key, level_set):
        entries = []
        for lvl, lvl_entries in data.get(sec_key, {}).items():
            if lvl in level_set or (level_set == below_levels and lvl not in above_levels):
                entries.extend(lvl_entries)
        t5 = top5(entries)
        return t5[0] if t5 else None

    cats = {
        "Recruits": "ps_rec",
        "Premium":  "ps_pre",
        "New REPs": "ps_nr",
    }
    result = {"Below RVP": {}, "RVP & Above": {}}
    for cat, sec_key in cats.items():
        b = best(sec_key, below_levels)
        a = best(sec_key, above_levels)
        if b:
            result["Below RVP"][cat]   = (b[1], b[3])
        if a:
            result["RVP & Above"][cat] = (a[1], a[3])
    return result


# ── PDF Generation ────────────────────────────────────────────────────────────
SECTION_LABELS = {
    "ps_rec":  "Personal Submitted Recruits",
    "ps_pre":  "Personal Submitted Premium",
    "ps_nr":   "Personal New REPs",
    "ps_sec":  "Personal Securities Total Volume",
    "bs_rec":  "Base Submitted Recruits",
    "bs_pre":  "Base Submitted Premium",
    "ps_cash": "Personal Cash",
    "bs_nbp":  "Base New Builders Premium",
}
DOLLAR_SECS = {"ps_pre", "ps_sec", "bs_pre", "ps_cash", "bs_nbp"}
COL_LABELS  = {
    "ps_rec":  "RECRUITS",
    "ps_pre":  "PREMIUM",
    "ps_nr":   "NEW REPs",
    "ps_sec":  "VOLUME",
    "bs_rec":  "RECRUITS",
    "bs_pre":  "PREMIUM",
    "ps_cash": "AMOUNT",
    "bs_nbp":  "AMOUNT",
}
LEVEL_LABELS = {
    "REP/SRP":       "REP & Senior REP",
    "DIS":           "Districts (DIS)",
    "DIV":           "Divisions (DIV)",
    "REG/SRL":       "Regionals / SRLs (REG)",
    "RVP+":          "RVP & Above (SVP / RVP)",
    "ALL":           "All Levels",
    "Overall Top 5": "Overall Top 5",
    "Below RVP":     "Below RVP (REP / DIS / DIV / REG / SRL)",
    "Above RVP":     "RVP & Above (SVP / RVP)",
}


def fmt_value(v: str, sec_key: str) -> str:
    try:
        n = float(re.sub(r"[^\d\.]", "", v))
    except ValueError:
        return v
    if sec_key in DOLLAR_SECS:
        return f"${n:,.2f}"
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"


def fmt_entries(entries: list, sec_key: str) -> list:
    result = []
    for e in entries:
        fv   = fmt_value(e[3], sec_key)
        note = e[4] if len(e) > 4 else ""
        result.append((e[0], e[1], e[2], fv, note))
    return result


def fmt_tg_result(raw_val: str, sec_key: str) -> str:
    try:
        n = float(re.sub(r"[^\d\.]", "", raw_val))
    except ValueError:
        return raw_val
    if sec_key in ("ps_rec", "bs_rec"):
        return f"{int(n)} recruits"
    if sec_key in DOLLAR_SECS:
        return f"${n:,.0f}"
    if sec_key == "ps_nr":
        return f"{n:.1f} REPs"
    return raw_val


# ── Styles ────────────────────────────────────────────────────────────────────
def _sty(fontSize=10, fontName="Helvetica", textColor=None, alignment=TA_LEFT,
         spaceBefore=0, spaceAfter=0, leading=None, bold=False):
    if textColor is None:
        textColor = CREAM
    fn = (fontName + "-Bold") if (bold and "Bold" not in fontName) else fontName
    kw = dict(fontSize=fontSize, fontName=fn, textColor=textColor,
               alignment=alignment, spaceBefore=spaceBefore,
               spaceAfter=spaceAfter, wordWrap="CJK")
    if leading:
        kw["leading"] = leading
    return ParagraphStyle("_", **kw)


COVER_TITLE = _sty(22, bold=True,  textColor=GOLD,  alignment=TA_CENTER, spaceAfter=4)
COVER_SUB   = _sty(11,             textColor=CREAM, alignment=TA_CENTER, spaceAfter=2)
COVER_DATE  = _sty(9,              textColor=MUTED, alignment=TA_CENTER, spaceAfter=10)
COVER_NOTE  = _sty(8,  fontName="Helvetica-Oblique", textColor=MUTED, spaceAfter=6)
CAT_H       = _sty(16, bold=True,  textColor=WHITE, spaceBefore=14, spaceAfter=3)
SUBCAT_H    = _sty(11, fontName="Helvetica-Oblique", textColor=GOLD, spaceBefore=8, spaceAfter=3)
TIE_NOTE_S  = _sty(8,  fontName="Helvetica-Oblique", textColor=MUTED, spaceAfter=4)


# ── Page canvas (portrait) ────────────────────────────────────────────────────
def page_bg(canvas, doc):
    W, H = letter
    canvas.saveState()
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, H - 0.16*inch, W, 0.16*inch, fill=1, stroke=0)
    canvas.rect(0, 0, W, 0.16*inch, fill=1, stroke=0)
    canvas.setFillColor(GOLD_D)
    canvas.rect(0, H - 0.22*inch, W, 0.04*inch, fill=1, stroke=0)
    canvas.rect(0, 0.16*inch, W, 0.04*inch, fill=1, stroke=0)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(W / 2, 0.20*inch,
                             f"WYD Super Saturday Rankings  ·  Page {doc.page}")
    canvas.restoreState()


# ── Table helpers ─────────────────────────────────────────────────────────────
COL_W     = [0.38*inch, 2.85*inch, 2.05*inch, 1.35*inch]
RANK_FILL = {1: GOLD, 2: SILVER, 3: BRONZE}
RANK_TC   = {1: PAGE_BG, 2: PAGE_BG, 3: WHITE}


def _p(text, fs=9, fn="Helvetica", color=None, align=TA_LEFT, leading=None):
    if color is None:
        color = CREAM
    kw = dict(fontSize=fs, fontName=fn, textColor=color, alignment=align, wordWrap="CJK")
    if leading:
        kw["leading"] = leading
    return Paragraph(text, ParagraphStyle("_", **kw))


def lb_table(entries: list, col_label: str = "AMOUNT") -> Table:
    header = [
        _p("<b>#</b>",           9, "Helvetica-Bold", GOLD, TA_CENTER),
        _p("<b>NAME</b>",        9, "Helvetica-Bold", GOLD),
        _p("<b>UPLINE</b>",      9, "Helvetica-Bold", GOLD),
        _p(f"<b>{col_label}</b>",9, "Helvetica-Bold", GOLD, TA_RIGHT),
    ]
    rows = [header]
    cmds = [
        ("BACKGROUND",    (0,0), (-1,0), CHARCOAL),
        ("LINEBELOW",     (0,0), (-1,0), 1.2, GOLD),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#222232")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [PANEL, PANEL2]),
    ]
    for i, entry in enumerate(entries):
        rank   = entry[0]
        name   = entry[1]
        upline = entry[2]
        value  = entry[3]
        note   = entry[4] if len(entry) > 4 else ""
        ri     = i + 1

        nc = GOLD if rank == 1 else (SILVER if rank == 2 else CREAM)
        vc = GOLD if rank == 1 else (SILVER if rank == 2 else CREAM)

        name_text = f"<b>{name}</b>"
        if note:
            name_text += f'<br/><font size="7" color="#888899">{note}</font>'

        rows.append([
            _p(f"<b>{rank}</b>",  11, "Helvetica-Bold", RANK_TC.get(rank, WHITE), TA_CENTER),
            _p(name_text,          9, "Helvetica-Bold", nc, leading=13),
            _p(upline,             8, "Helvetica-Oblique", MUTED, leading=11),
            _p(f"<b>{value}</b>",  9, "Helvetica-Bold", vc, TA_RIGHT),
        ])
        if rank in RANK_FILL:
            cmds.append(("BACKGROUND", (0,ri), (0,ri), RANK_FILL[rank]))
        if rank == 1:
            cmds.append(("BACKGROUND", (1,ri), (-1,ri), colors.HexColor("#1A1A08")))

    return Table(rows, colWidths=COL_W, repeatRows=1, style=TableStyle(cmds))


def tg_table(rows_data: list) -> Table:
    hdr = [
        _p("<b>CATEGORY</b>", 9, "Helvetica-Bold", GOLD),
        _p("<b>WINNER</b>",   9, "Helvetica-Bold", GOLD),
        _p("<b>RESULT</b>",   9, "Helvetica-Bold", GOLD, TA_RIGHT),
    ]
    rows = [hdr]
    cmds = [
        ("BACKGROUND",    (0,0), (-1,0), CHARCOAL),
        ("LINEBELOW",     (0,0), (-1,0), 1.2, GOLD),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [PANEL, PANEL2]),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#222232")),
        ("BACKGROUND",    (0,1), (0,-1), colors.HexColor("#1A1800")),
    ]
    for cat, winner, result in rows_data:
        rows.append([
            _p(f"<b>{cat}</b>",    9, "Helvetica-Bold", GOLD_LT),
            _p(f"<b>{winner}</b>", 9, "Helvetica-Bold", WHITE),
            _p(f"<b>{result}</b>", 9, "Helvetica-Bold", GOLD, TA_RIGHT),
        ])
    return Table(rows, colWidths=[1.8*inch, 3.4*inch, 1.43*inch],
                 style=TableStyle(cmds))


def _rule(color=GOLD_D, thick=0.5):
    return HRFlowable(width="100%", thickness=thick, color=color, spaceAfter=4, spaceBefore=2)


def _gold_rule():
    return HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6, spaceBefore=10)


def subcat_block(title: str, entries: list, col_label: str, note: str = ""):
    items = [Paragraph(title, SUBCAT_H), _rule(), lb_table(entries, col_label)]
    if note:
        items.append(Paragraph(note, TIE_NOTE_S))
    items.append(Spacer(1, 6))
    return KeepTogether(items)


def cat_header(title: str):
    return KeepTogether([
        _gold_rule(),
        Paragraph(title.upper(), CAT_H),
        _rule(GOLD, 1.0),
        Spacer(1, 2),
    ])


def _tie_note(entries: list) -> str:
    """Return a footnote string if any entry has a tiebreaker/tied note."""
    has_tb   = any(len(e) > 4 and e[4] and "Tiebreaker" in e[4] for e in entries)
    has_tied = any(len(e) > 4 and e[4] and "Tied" in e[4] for e in entries)
    if has_tb:
        return ("* Tiebreaker applied: tied entries ranked by Personal Submitted Premium. "
                "Higher premium wins.")
    if has_tied:
        return ("* Tied entries shown above. No premium data available to break tie — "
                "confirm final order with leadership.")
    return ""


def generate_pdf(rankings: dict, top_gun: dict, period: str,
                 cash_months: int = 3,
                 cash_below_avg: int = 4000,
                 cash_rvp_avg: int = 8000) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.48*inch, rightMargin=0.48*inch,
                            topMargin=0.5*inch,   bottomMargin=0.42*inch)

    story = [
        Spacer(1, 0.25*inch),
        Paragraph("WYD SUPER SATURDAY", COVER_TITLE),
        Paragraph("Official Competition Rankings", COVER_SUB),
        Paragraph(period, COVER_DATE),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=5, spaceBefore=0),
        Paragraph(
            "Rankings are based on personal results only. "
            "Tiebreaker rule: higher Personal Submitted Premium wins. "
            "Where no tiebreaker can be established from available data, "
            "a note is provided and leadership confirmation is recommended.",
            COVER_NOTE),
        Spacer(1, 4),
    ]

    order = ["ps_rec", "ps_pre", "ps_nr", "ps_sec", "bs_rec", "bs_pre", "ps_cash", "bs_nbp"]
    for i, sec_key in enumerate(order):
        sec_r = rankings.get(sec_key)
        if not sec_r:
            continue
        num   = i + 1
        label = SECTION_LABELS.get(sec_key, sec_key)
        col   = COL_LABELS.get(sec_key, "VALUE")

        story.append(PageBreak())
        story.append(cat_header(f"{num}. {label}"))

        if sec_key in SPLIT_SECS:
            below_e = sec_r.get("Below RVP", [])
            above_e = sec_r.get("Above RVP", [])

            if below_e:
                fe = fmt_entries(below_e, sec_key)
                note = _tie_note(fe)
                if sec_key == "ps_cash":
                    min_b = cash_months * cash_below_avg
                    note = (f"* Minimum qualifying income: ${min_b:,} "
                            f"(${cash_below_avg:,}/month avg × {cash_months} months).  ") + note
                story.append(subcat_block(
                    "Below RVP (REP / DIS / DIV / REG / SRL)", fe, col, note.strip()))
            if above_e:
                fe = fmt_entries(above_e, sec_key)
                note = _tie_note(fe)
                if sec_key == "ps_cash":
                    min_a = cash_months * cash_rvp_avg
                    note = (f"* Minimum qualifying income: ${min_a:,} "
                            f"(${cash_rvp_avg:,}/month avg × {cash_months} months).  ") + note
                story.append(subcat_block(
                    "RVP & Above (SVP / RVP)", fe, col, note.strip()))
            if not below_e and not above_e:
                overall = sec_r.get("Overall Top 5", [])
                if overall:
                    fe = fmt_entries(overall, sec_key)
                    story.append(subcat_block("All Levels", fe, col, _tie_note(fe)))
        else:
            lvl_order = ["REP/SRP", "DIS", "DIV", "REG/SRL", "RVP+", "ALL"]
            for lvl in lvl_order:
                entries = sec_r.get(lvl)
                if not entries:
                    continue
                disp = LEVEL_LABELS.get(lvl, lvl)
                fe   = fmt_entries(entries, sec_key)
                story.append(subcat_block(disp, fe, col, _tie_note(fe)))

    # Top Gun
    if any(tg_data for tg_data in top_gun.values()):
        story.append(PageBreak())
        story.append(cat_header(f"{len(order) + 1}. Top Gun"))
        story.append(Paragraph(
            "Best personal result per category. "
            "Below RVP covers REP / DIS / DIV / REG / SRL titles. "
            "RVP & Above covers SVP and RVP titles.",
            COVER_NOTE))

        tg_cat_keys = {"Recruits": "ps_rec", "Premium": "ps_pre", "New REPs": "ps_nr"}
        tg_display  = {"Recruits": "Recruiting", "Premium": "Premium", "New REPs": "New Licenses"}

        for group, tg_data in top_gun.items():
            if not tg_data:
                continue
            rows_data = []
            for cat, (winner, raw_val) in tg_data.items():
                sec_k  = tg_cat_keys.get(cat, "ps_rec")
                result = fmt_tg_result(raw_val, sec_k)
                rows_data.append((tg_display.get(cat, cat), winner.upper(), result))
            story.append(KeepTogether([
                Paragraph(group, SUBCAT_H),
                _rule(),
                tg_table(rows_data),
                Spacer(1, 10),
            ]))

    story.append(Spacer(1, 0.2*inch))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=5))
    story.append(Paragraph(
        f"WYD SUPER SATURDAY  ·  {period}  ·  Data: WYD Hierarchy SS",
        _sty(7, textColor=MUTED, alignment=TA_CENTER)))

    doc.build(story, onFirstPage=page_bg, onLaterPages=page_bg)
    buf.seek(0)
    return buf.read()


# ── Streamlit UI ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="WYD Rankings", page_icon="⚽", layout="wide")

st.markdown("""
<style>
h1 { color: #D4AF37 !important; }
h2, h3 { color: #C0C0C8 !important; }
.stButton > button {
    background: #D4AF37; color: #000; font-weight: bold;
    border-radius: 6px; padding: 0.5em 1.5em; border: none;
}
.stButton > button:hover { background: #F0D060; }
</style>
""", unsafe_allow_html=True)

st.title("WYD Super Saturday Rankings Generator")
st.caption("Upload the WYD Hierarchy PDF → extracts numbers → computes Top 5 per category & subcategory → download medals PDF")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    period = st.text_input("Competition Period", "Feb–April 2026")
    st.markdown("---")
    st.markdown("**Sections:**")
    include = {
        "ps_rec":  st.checkbox("Personal Submitted Recruits", True),
        "ps_pre":  st.checkbox("Personal Submitted Premium",  True),
        "ps_nr":   st.checkbox("Personal New REPs",           True),
        "ps_sec":  st.checkbox("Personal Securities",         True),
        "bs_rec":  st.checkbox("Base Submitted Recruits",     True),
        "bs_pre":  st.checkbox("Base Submitted Premium",      True),
        "ps_cash": st.checkbox("Personal Cash",               True),
        "bs_nbp":  st.checkbox("Base New Builders Premium",   True),
    }
    st.markdown("---")
    st.markdown("**Personal Cash Thresholds:**")
    cash_months    = st.number_input("Contest duration (months)", min_value=1, max_value=12, value=3, step=1)
    cash_below_avg = st.number_input("Below RVP monthly avg ($)", min_value=0, value=4000, step=500)
    cash_rvp_avg   = st.number_input("RVP+ monthly avg ($)",      min_value=0, value=8000, step=500)
    st.caption(f"Below RVP min: **${cash_months * cash_below_avg:,}** · RVP+ min: **${cash_months * cash_rvp_avg:,}**")
    st.markdown("---")
    st.info("**Tiebreaker:** Recruiting ties are broken by Personal Submitted Premium.")

# ── Upload ────────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload WYD Hierarchy PDF", type=["pdf"])
if not uploaded:
    st.info("Upload your WYD Hierarchy SS PDF to get started.")
    st.stop()

# ── Parse ─────────────────────────────────────────────────────────────────────
with st.spinner("Reading PDF..."):
    raw_bytes = uploaded.read()
    parsed    = parse_pdf(raw_bytes)
    filtered  = {k: v for k, v in parsed.items() if include.get(k, True)}
    rankings  = compute_rankings(filtered, include, cash_months, cash_below_avg, cash_rvp_avg)
    top_gun   = compute_top_gun(filtered)

total = sum(len(e) for lv in parsed.values() for e in lv.values())
c1, c2, c3 = st.columns(3)
c1.metric("Sections Found",    len(parsed))
c2.metric("Levels Found",      sum(len(lv) for lv in parsed.values()))
c3.metric("Entries Extracted", total)

if total == 0:
    st.error("No entries detected. Check the Raw Text tab — the PDF format may differ from expected.")
else:
    st.success(f"Parsed successfully! Go to the **Rankings tab** below to see results, then click **Generate & Download PDF**.")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_rank, tab_tg, tab_raw = st.tabs(["Rankings", "Top Gun", "Raw Text"])

with tab_rank:
    order = ["ps_rec", "ps_pre", "ps_nr", "ps_sec", "bs_rec", "bs_pre", "ps_cash", "bs_nbp"]
    for sec_key in order:
        sec_r = rankings.get(sec_key)
        if not sec_r:
            continue
        label = SECTION_LABELS.get(sec_key, sec_key)
        st.subheader(label)
        disp_order = ["Below RVP", "Above RVP",
                      "REP/SRP", "DIS", "DIV", "REG/SRL", "RVP+", "ALL"]
        for lvl in disp_order:
            entries = sec_r.get(lvl)
            if not entries:
                continue
            disp = LEVEL_LABELS.get(lvl, lvl)
            st.markdown(f"**{disp}**")
            rows = []
            for e in entries:
                rows.append({
                    "Rank":   e[0],
                    "Name":   e[1],
                    "Upline": e[2],
                    "Value":  fmt_value(e[3], sec_key),
                    "Note":   e[4] if len(e) > 4 and e[4] else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("---")

    st.subheader("Download Medals PDF")
    if st.button("Generate & Download PDF"):
        with st.spinner("Building PDF..."):
            pdf_bytes = generate_pdf(rankings, top_gun, period, cash_months, cash_below_avg, cash_rvp_avg)
        fname = f"WYD_Rankings_{period.replace(' ','_').replace('–','-')}.pdf"
        st.download_button("Download PDF", pdf_bytes, fname, "application/pdf")

with tab_tg:
    st.subheader("Top Gun — Best Personal Performer")
    for group, tg_data in top_gun.items():
        if not tg_data:
            continue
        st.markdown(f"### {group}")
        rows = [{"Category": cat, "Winner": w, "Result": v} for cat, (w, v) in tg_data.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tab_raw:
    st.caption("Full extracted text — useful for debugging if entries are missing.")
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    raw_text = "\n".join(page.get_text() for page in doc)
    st.text_area("Raw Text", raw_text, height=450, label_visibility="collapsed")
