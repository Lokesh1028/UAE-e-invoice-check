"""
Best-effort extraction of invoice data from a PDF invoice (text layer only).

This is deliberately conservative: it extracts the fields that can be found
with high confidence (numbers formatted like TRNs, dates, totals, VAT, buyer
and seller names near their labels, line rows in tables) and leaves the rest
empty. Missing fields then surface as findings, which is what a readiness
check should show. Scanned PDFs without a text layer are rejected with a clear
message.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal
from typing import Optional

import pdfplumber

from app.engine.model import Invoice, Line, Party, Totals, to_decimal, to_date

TRN_RE = re.compile(r"\b(1\d{12}03)\b")
TIN_RE = re.compile(r"\b(1\d{9})\b")
DATE_RE = re.compile(r"\b(\d{1,2}[-/ .](?:\d{1,2}|[A-Za-z]{3,9})[-/ .]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
AMOUNT_RE = re.compile(r"(?<![\d.])(-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|-?\d+(?:\.\d{1,2})?)(?![\d.])")
LABELS = {
    "number": [r"tax invoice\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{2,})", r"invoice\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{2,})", r"\bbill\s*(?:no|number)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{2,})", r"\binv(?:oice)?\s*(?:ref|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{2,})"],
    "date": [r"(?:invoice|bill|issue)\s*date\s*[:\-]?\s*(" + DATE_RE.pattern.strip(r"\b") + ")", r"\bdate\s*[:\-]?\s*(" + DATE_RE.pattern.strip(r"\b") + ")"],
    "due": [r"due\s*(?:date|on)\s*[:\-]?\s*(" + DATE_RE.pattern.strip(r"\b") + ")"],
    "po": [r"\b(?:po|lpo|purchase order)\s*(?:no|number|#|ref)?\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{2,})"],
    "total": [r"(?:grand\s*total|total\s*(?:amount\s*)?(?:due|payable)|amount\s*due|net\s*payable|total\s*incl(?:uding)?\.?\s*vat)\s*(?:\(?AED\)?)?\s*[:\-]?\s*(?:AED)?\s*" + AMOUNT_RE.pattern],
    "vat": [r"(?:total\s*)?(?:vat|tax)\s*(?:amount|@\s*5\s*%|5\s*%)?\s*(?:\(?AED\)?)?\s*[:\-]?\s*(?:AED)?\s*" + AMOUNT_RE.pattern],
    "subtotal": [r"(?:sub\s*total|total\s*(?:before|excl(?:uding)?\.?)\s*(?:vat|tax)|taxable\s*(?:amount|value)|net\s*(?:amount|total))\s*(?:\(?AED\)?)?\s*[:\-]?\s*(?:AED)?\s*" + AMOUNT_RE.pattern],
}


class PdfImportError(ValueError):
    pass


def _first(patterns, text, flags=re.I) -> Optional[str]:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1).strip()
    return None


def _party_block(text: str, labels: list[str]) -> dict:
    """Find the few lines following a label such as 'Bill To' and pull name/TRN/address from them."""
    out: dict = {}
    for lab in labels:
        m = re.search(lab + r"\s*[:\-]?\s*\n?(.{0,400})", text, re.I | re.S)
        if not m:
            continue
        block = m.group(1)
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()][:7]
        if not lines:
            continue
        name = lines[0]
        name = re.sub(r"\bTRN\b.*$", "", name, flags=re.I).strip(" :-")
        if len(name) > 2 and not re.match(r"^\d", name):
            out["name"] = name[:120]
        tr = TRN_RE.search(block)
        if tr:
            out["trn"] = tr.group(1)
        addr = [ln for ln in lines[1:] if not TRN_RE.search(ln) and not re.search(r"\b(trn|tel|phone|email|@)\b", ln, re.I)]
        if addr:
            out["street"] = addr[0][:120]
        for ln in lines:
            em = re.search(r"\b(abu dhabi|dubai|sharjah|ajman|umm al quwain|ras al khaimah|fujairah)\b", ln, re.I)
            if em:
                out["emirate"] = em.group(1)
                out["city"] = em.group(1).title()
                out["country"] = "AE"
                break
        break
    return out


def _table_lines(pdf) -> list[Line]:
    """Pull line rows from tables: rows that have a description, a quantity and an amount."""
    lines: list[Line] = []
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if not table or len(table) < 2:
                continue
            header = [str(c or "").strip().lower() for c in table[0]]
            def col(*names):
                for i, h in enumerate(header):
                    if any(n in h for n in names):
                        return i
                return None
            ci_desc = col("description", "item", "particular", "product", "service")
            ci_qty = col("qty", "quantity")
            ci_rate = col("rate", "unit price", "price")
            ci_amt = col("amount", "total", "value")
            ci_vat = col("vat", "tax")
            ci_unit = col("unit", "uom")
            if ci_desc is None or (ci_qty is None and ci_amt is None):
                continue
            for row in table[1:]:
                if not row or all(c in (None, "") for c in row):
                    continue
                desc = str(row[ci_desc] or "").strip() if ci_desc < len(row) else ""
                if not desc or re.search(r"\b(sub\s*total|total|vat|grand)\b", desc, re.I):
                    continue
                qty = to_decimal(row[ci_qty]) if ci_qty is not None and ci_qty < len(row) else None
                rate = to_decimal(row[ci_rate]) if ci_rate is not None and ci_rate < len(row) else None
                amt = to_decimal(row[ci_amt]) if ci_amt is not None and ci_amt < len(row) else None
                vat_txt = str(row[ci_vat] or "") if ci_vat is not None and ci_vat < len(row) else ""
                vat_rate = to_decimal(vat_txt) if "%" in vat_txt or (to_decimal(vat_txt) is not None and to_decimal(vat_txt) <= 100 and amt and to_decimal(vat_txt) < amt) else None
                unit = str(row[ci_unit] or "").strip() if ci_unit is not None and ci_unit < len(row) else None
                if qty is None and amt is None:
                    continue
                lines.append(Line(name=desc[:200], quantity=qty, unit_price=rate, unit=unit or None, line_net=amt if rate is not None or qty is None else None,
                                  vat_rate=vat_rate, vat_category=("S" if vat_rate and vat_rate > 0 else None)))
    return lines


def import_pdf(data: bytes, filename: str) -> tuple[Invoice, dict]:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:
        raise PdfImportError(f"Could not open PDF: {type(e).__name__}")
    with pdf:
        if len(pdf.pages) > 20:
            raise PdfImportError("PDF has more than 20 pages; upload a single invoice.")
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) < 40:
            raise PdfImportError("This PDF has no readable text layer (it is probably a scan or photo). Upload a PDF generated by your software, or an Excel/CSV export.")
        lines = _table_lines(pdf)

    number = _first(LABELS["number"], text)
    date = to_date(_first(LABELS["date"], text) or "")
    due = to_date(_first(LABELS["due"], text) or "")
    trns = TRN_RE.findall(text)
    seller_block = _party_block(text, [r"\bfrom\b", r"\bseller\b", r"\bsupplier\b", r"\bissued by\b"])
    buyer_block = _party_block(text, [r"\bbill(?:ed)?\s*to\b", r"\bcustomer\b", r"\bbuyer\b", r"\binvoice\s*to\b", r"\bsold\s*to\b", r"\bto\s*:\s*"])
    # first TRN in the document is almost always the seller's (letterhead)
    seller_trn = seller_block.get("trn") or (trns[0] if trns else None)
    buyer_trn = buyer_block.get("trn") or (next((t for t in trns if t != seller_trn), None))
    if "name" not in seller_block:
        first_line = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3), None)
        if first_line and not re.search(r"invoice", first_line, re.I):
            seller_block["name"] = first_line[:120]
    if "emirate" not in seller_block:
        head = "\n".join(text.splitlines()[:8])
        em = re.search(r"\b(abu dhabi|dubai|sharjah|ajman|umm al quwain|ras al khaimah|fujairah)\b", head, re.I)
        if em:
            seller_block.update({"emirate": em.group(1), "city": em.group(1).title(), "country": "AE"})
            addr_line = next((ln for ln in text.splitlines()[:8] if em.group(1).lower() in ln.lower() and not TRN_RE.search(ln)), None)
            if addr_line and "street" not in seller_block:
                seller_block["street"] = addr_line.strip()[:120]
    seller = Party(**{k: v for k, v in seller_block.items() if k in Party.model_fields}, **({"trn": seller_trn} if seller_trn and "trn" not in seller_block else {}))
    buyer = Party(**{k: v for k, v in buyer_block.items() if k in Party.model_fields}, **({"trn": buyer_trn} if buyer_trn and "trn" not in buyer_block else {}))
    totals = Totals(payable=_first(LABELS["total"], text), vat_total=_first(LABELS["vat"], text), tax_exclusive=_first(LABELS["subtotal"], text))
    pay = None
    if re.search(r"bank\s*transfer|wire|iban|neft|tt\b", text, re.I):
        pay = "30"
    elif re.search(r"\bcash\b", text, re.I):
        pay = "10"
    elif re.search(r"\bcheque|check\b", text, re.I):
        pay = "20"
    elif re.search(r"\bcard\b", text, re.I):
        pay = "48"
    iban_m = re.search(r"\b(AE\s?\d{2}(?:\s?\d{4}){5}\s?\d{3})\b", text)
    inv = Invoice(number=number, issue_date=date, due_date=due, seller=seller, buyer=buyer, lines=lines, totals=totals,
                  po_number=_first(LABELS["po"], text), payment_means_code=pay,
                  iban=re.sub(r"\s", "", iban_m.group(1)) if iban_m else None,
                  currency="AED" if re.search(r"\bAED\b|dirham", text, re.I) else "AED")
    info = {"text_chars": len(text), "lines_found": len(lines), "trns_found": trns[:4],
            "extracted": {"number": number, "date": str(date) if date else None, "seller": seller.name, "buyer": buyer.name,
                          "seller_trn": seller.trn, "buyer_trn": buyer.trn, "total": str(totals.payable) if totals.payable else None}}
    return inv, info
