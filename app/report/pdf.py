"""
Readiness report PDF (fpdf2, no system dependencies).
Input: the JSON-serialisable report dict produced by the API (see app/api.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fpdf import FPDF

NAVY = (16, 36, 62)
AMBER = (154, 100, 32)
GREY = (90, 98, 110)
LIGHT = (246, 244, 238)
RED = (160, 40, 40)
GREEN = (31, 107, 94)


def _txt(s: str) -> str:
    """Core fonts are Latin-1 only; replace what cannot be encoded."""
    return (s or "").encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    def __init__(self, title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.title_text = title
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 16, 16)

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*NAVY)
        self.cell(0, 6, _txt(self.title_text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*NAVY)
        self.line(16, 22, 194, 22)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, _txt(f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')} · PINT AE 1.0.2 rules · Not tax advice · Page {self.page_no()}"), align="C")


def build_report_pdf(report: dict, brand: str = "UAE e-invoice readiness check") -> bytes:
    pdf = _PDF(brand)
    pdf.add_page()
    summ = report.get("summary", {})
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 12, _txt("E-invoicing readiness report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GREY)
    src = report.get("source", {})
    pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_txt(f"File: {src.get('filename', '-')}   ·   Sheet: {src.get('invoice_sheet') or '-'}   ·   Documents checked: {summ.get('documents', 0)}"))
    pdf.ln(3)

    # score band
    ready = summ.get("documents_ready", 0)
    docs = summ.get("documents", 0) or 1
    pct = round(100 * ready / docs)
    pdf.set_fill_color(*LIGHT)
    pdf.set_draw_color(220, 215, 205)
    y0 = pdf.get_y()
    pdf.rect(16, y0, 178, 26, style="DF")
    pdf.set_xy(20, y0 + 4)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*(GREEN if pct == 100 else AMBER if pct >= 50 else RED))
    pdf.cell(40, 10, f"{pct}%", new_x="RIGHT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*NAVY)
    pdf.set_xy(60, y0 + 4)
    pdf.multi_cell(130, 5, new_x="LMARGIN", new_y="NEXT", text=_txt(
        f"{ready} of {docs} documents would pass the official UAE PINT AE rules as-is.\n"
        f"{summ.get('fatal_total', 0)} blocking errors across {summ.get('distinct_rules', 0)} distinct rules. "
        f"Top issues are listed below; fixing the first three usually clears most documents."))
    pdf.set_y(y0 + 30)

    # top issues
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, _txt("What to fix, in order of impact"), new_x="LMARGIN", new_y="NEXT")
    for i, issue in enumerate(report.get("issues", [])[:12], start=1):
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.set_text_color(*NAVY)
        pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text=_txt(f"{i}. {issue.get('title')}  ({issue.get('count')} occurrence{'s' if issue.get('count', 0) != 1 else ''}, {issue.get('documents')} document{'s' if issue.get('documents', 0) != 1 else ''})"))
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*GREY)
        pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_txt(issue.get("plain", "")))
        if issue.get("fix"):
            pdf.set_text_color(*GREEN)
            pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_txt("Fix: " + issue["fix"]))
        if issue.get("example"):
            pdf.set_text_color(*GREY)
            pdf.set_font("Helvetica", "I", 8.5)
            pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_txt("Example: " + issue["example"]))
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 4, _txt(f"Rule {issue.get('rule_id')} · {issue.get('layer_label', '')} · field: {issue.get('field') or '-'}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # per document table
    docs_list = report.get("documents", [])
    if docs_list:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 8, _txt("Document by document"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(255, 255, 255)
        widths = (44, 20, 40, 14, 60)
        for w, h in zip(widths, ("Number", "Date", "Customer", "Errors", "First problem")):
            pdf.cell(w, 6, _txt(h), border=0, fill=True)
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 8.5)
        for n, d in enumerate(docs_list[:300]):
            pdf.set_fill_color(*(LIGHT if n % 2 else (255, 255, 255)))
            pdf.set_text_color(*(GREEN if d.get("fatal", 0) == 0 else NAVY))
            first = (d.get("findings") or [{}])[0].get("title", "") if d.get("fatal", 0) else "Ready"
            cells = (str(d.get("number", ""))[:26], str(d.get("date") or "")[:10], str(d.get("buyer") or "")[:24], str(d.get("fatal", 0)), first[:40])
            for w, c in zip(widths, cells):
                pdf.cell(w, 5.5, _txt(c), fill=True)
            pdf.ln(5.5)

    # what the tool generated / assumptions
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, _txt("How this check works"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_txt(
        "Each document was converted to the UAE e-invoice format (PINT AE, UBL 2.1) using only the data in your file, "
        "then checked against the UBL 2.1 schema and the Ministry of Finance / OpenPeppol PINT AE 1.0.2 rule sets "
        "(international and UAE-specific layers). Technical identifiers that your software will generate (UUID, "
        "specification and profile IDs, line numbers) were filled in automatically. Nothing else was assumed. "
        "A document marked Ready passes every rule in this version of the rule set; the Ministry may publish updates."))
    return bytes(pdf.output())
