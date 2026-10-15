"""
CSV / XLSX importer.

Handles what SMEs actually export:
 - title rows above the header, header anywhere in the first 15 rows
 - multi-sheet workbooks: an invoice register plus master sheets (customers,
   legal entities, tax codes, items). Masters are joined by code.
 - one row per line, invoice fields repeated per row (or blank on continuation rows)
 - header names in many flavours (synonym table) with an explicit mapping override

Output: list[Invoice] plus an ImportReport describing what was detected.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Optional

import openpyxl

from app.engine.model import Invoice, Line, Party, Totals, to_decimal, to_date, credit_reason_code, EMIRATES

MAX_ROWS = 20000

# canonical field -> header synonyms (lowercased, punctuation-stripped)
SYN: dict[str, list[str]] = {
    # invoice header
    "inv_number": ["inv ref", "invoice no", "invoice number", "inv no", "invoice", "bill no", "bill number", "doc no", "document no", "voucher no", "vch no", "invoice ref", "inv num", "tax invoice no", "invoice ref no", "inv ref no"],
    "doc_type": ["doc type", "document type", "bill kind", "type", "vch type", "voucher type", "transaction type", "invoice type"],
    "inv_date": ["inv date", "invoice date", "bill dated", "bill date", "date", "doc date", "document date", "voucher date", "issue date", "dated"],
    "due_date": ["due date", "payment due", "due on", "due"],
    "entity_code": ["entity", "entity code", "billing co", "billing company", "company code", "seller code", "our company", "branch", "legal entity"],
    "cust_code": ["cust code", "customer code", "partner code", "client code", "buyer code", "account code", "ledger code", "customer id", "party code"],
    "cust_name": ["customer name", "customer", "partner name", "client name", "buyer name", "party name", "bill to", "particulars", "account name", "client", "buyer", "name of customer", "sold to"],
    "cust_trn": ["customer trn", "cust trn", "buyer trn", "trn of customer", "customer vat", "buyer vat", "party trn", "client trn", "customer tax registration number", "buyer tax id"],
    "cust_tin": ["customer tin", "buyer tin", "customer peppol id", "customer e invoicing network id", "network id", "peppol id"],
    "cust_street": ["customer address", "billing address", "address", "bill to address", "customer street", "buyer address", "address line 1", "party address"],
    "cust_city": ["customer city", "city", "buyer city", "bill to city", "town"],
    "cust_emirate": ["customer emirate", "emirate", "buyer emirate", "state", "region", "bill to emirate"],
    "cust_country": ["customer country", "country", "buyer country", "bill to country", "country code"],
    "cust_licence": ["customer licence", "customer license", "customer trade licence", "buyer licence", "licence no", "license no", "trade licence no"],
    "currency": ["cur", "currency", "billing currency", "ccy", "curr", "invoice currency"],
    "fx_rate": ["fx rate", "exchange rate", "conversion to aed", "conversion rate", "rate to aed", "ex rate"],
    "po_number": ["po", "po no", "po number", "purchase order", "lpo", "lpo no", "order ref", "customer po", "po ref", "customer s order ref", "customer order ref", "order no"],
    "payment_terms": ["payment terms", "credit terms", "terms of payment"],
    "incoterms": ["delivery terms", "incoterms", "incoterm", "delivery terms icc"],
    "payment_method": ["payment method", "payment mode", "mode of payment", "paid by", "payment means"],
    "orig_invoice": ["adjusted against bill", "original invoice", "against invoice", "ref invoice", "credit against", "original inv", "preceding invoice", "invoice reference"],
    "credit_reason": ["reason for adjustment", "credit reason", "reason", "credit note reason"],
    "note": ["remarks", "narration", "notes", "note", "comment", "comments"],
    # line
    "line_no": ["line", "sl", "sl no", "s no", "sr no", "line no", "#", "sno", "item no", "seq"],
    "item_code": ["item code", "product code", "product service code", "sku", "code", "item id", "stock code", "part no"],
    "description": ["description", "what was supplied", "item description", "particulars of supply", "item", "product", "service", "item name", "goods description", "details", "narration"],
    "nature": ["nature of supply", "goods or service", "goods service", "item type", "g s", "type of supply", "supply type"],
    "qty": ["qty", "quantity", "units", "nos", "no of units", "qnty"],
    "uom": ["uom", "unit", "units", "measure", "unit of measure", "per"],
    "unit_price": ["rate", "rate charged", "rate charged after discount", "unit price", "price", "unit rate", "selling price", "net rate", "unit cost"],
    "gross_price": ["list rate", "list rate before discount", "gross price", "list price", "mrp", "rate before discount"],
    "price_per": ["rate applies per", "per qty", "price basis", "base qty"],
    "line_value": ["line value", "line value billing ccy", "amount", "net amount", "taxable value", "taxable amount", "line amount", "value", "net value", "amount before vat", "amount excl vat", "line net"],
    "tax_code": ["tax code", "vat code", "tax treatment", "vat treatment", "supply treatment", "vat category", "tax category", "tax type", "vat type", "gst code", "treatment"],
    "tax_rate": ["tax %", "vat %", "tax rate", "vat rate", "vat percent", "tax percent", "rate of tax", "applicable %", "applicable", "tax pct", "vat pct", "tax", "vat"],
    "tax_amount": ["tax amt", "tax amount", "vat amt", "vat amount", "vat on line", "vat on line billing ccy", "vat charged", "output vat", "tax value", "vat value"],
    "line_total": ["line total", "total", "gross amount", "amount incl vat", "total incl vat", "line total incl vat", "total amount", "gross"],
    "invoice_total": ["invoice total", "invoice value", "bill total", "grand total", "total invoice value", "invoice value incl vat", "amount payable", "net payable", "balance payable"],
    "hs_code": ["hs code", "hsn", "hsn code", "customs tariff heading", "tariff code", "hs", "commodity code"],
    "sac_code": ["sac", "sac code", "service code", "service category code", "service accounting code"],
    "tax_amount_aed": ["vat in local currency", "vat in local currency aed", "vat aed", "tax amount aed"],
    "discount": ["discount", "disc", "line discount", "discount amount", "less discount"],
}
# master sheets
SYN_CUST = {
    "code": ["cust code", "customer code", "partner code", "code", "client code", "id"],
    "name": ["customer name", "registered name of customer", "registered name", "name", "legal name", "party name", "company name", "name on trade licence", "name on trade license"],
    "trn": ["trn", "customer s tax registration number", "tax registration number", "vat no", "vat number", "tax registration no", "vat registration number", "vat reg no"],
    "tin": ["tin", "customer e invoicing network id", "e invoicing network id", "network id", "peppol id", "tax identification number", "federal tax identification number"],
    "licence_no": ["customer s licence cr no", "licence cr reference", "trade licence no", "trade license no", "licence no", "license no", "cr no", "registration no", "licence number"],
    "licence_authority": ["customer s registering authority", "licensing authority", "issued by", "issuing authority", "registering authority", "authority"],
    "licence_type": ["type of registration held", "registration type", "id type"],
    "street": ["billing address street", "address", "registered address", "registered office street", "street", "address line 1", "address 1", "billing address"],
    "city": ["billing address town city", "city", "town", "registered office town", "address city"],
    "emirate": ["billing address emirate", "emirate", "registered office emirate", "state", "region"],
    "country": ["billing address iso country", "country", "registered office country", "iso country", "country code"],
    "email": ["accounts payable contact", "ap contact email", "email", "contact email", "finance contact email"],
    "passport_country": ["passport issuing country"],
}
SYN_ENT = {
    "code": ["entity code", "entity ref", "entity", "code", "company code", "billing co", "ref"],
    "name": ["registered name", "name on trade licence", "legal name", "name", "company name", "entity name"],
    "trade_name": ["doing business as", "trade name", "dba", "brand"],
    "trn": ["trn", "tax registration number", "vat no", "vat number", "vat registration number"],
    "tin": ["tin", "e invoicing network id", "network id", "peppol id", "federal tax identification number", "tax identification number"],
    "licence_no": ["trade licence no", "trade license no", "licence cr reference", "licence no", "license no", "cr no", "licence number"],
    "licence_authority": ["licensing authority", "issued by", "issuing authority", "authority"],
    "street": ["registered address", "registered office street", "address", "street", "address line 1"],
    "city": ["city", "registered office town", "town"],
    "emirate": ["emirate", "registered office emirate"],
    "country": ["country", "registered office country", "country code"],
    "email": ["contact email", "finance contact email", "email"],
    "iban": ["iban", "bank account", "account no"],
}
SYN_TAX = {
    "code": ["tax code", "code", "treatment", "vat code"],
    "rate": ["rate", "rate percent", "applicable", "percent", "vat rate"],
    "category": ["code for filing", "category", "vat category", "pint code", "ubl code"],
    "description": ["description", "what it means", "name"],
    "type": ["type"],
    "reason": ["reason reference where exempt", "exemption reason", "reason code", "reason"],
}
SYN_ITEM = {
    "code": ["code", "item code", "sku", "product code"],
    "name": ["short name", "name", "item name", "description"],
    "description": ["full description of supply", "description", "long description"],
    "nature": ["goods or service", "type", "nature", "item type"],
    "unit": ["selling unit", "unit", "uom"],
    "hs_code": ["customs tariff heading", "hs code", "hsn", "tariff"],
    "sac_code": ["service category code", "sac", "sac code"],
    "tax_code": ["default vat treatment", "tax code", "vat code"],
}
SYN_SUMMARY = {
    "inv_number": ["bill no", "invoice no", "inv ref", "invoice number", "inv no"],
    "discount_total": ["less bill level discount", "bill level discount", "discount", "document discount"],
    "charge_total": ["add freight recovered", "freight", "charges", "shipping", "delivery charges"],
    "tax_exclusive": ["net invoice value before vat", "net invoice value", "taxable value", "total before vat"],
    "vat_total": ["vat charged", "vat amount", "total vat", "tax amount"],
    "vat_total_aed": ["vat charged local currency", "vat charged local currency aed", "vat in aed", "tax amount aed", "vat local currency"],
    "tax_inclusive": ["invoice value incl vat", "invoice value", "total incl vat", "gross total"],
    "paid": ["advance adjusted", "advance", "paid", "prepaid", "amount received"],
    "rounding": ["round off", "rounding", "round off +/-"],
    "payable": ["balance payable by customer", "balance payable", "amount due", "net payable", "payable"],
    "fx_rate": ["conversion to aed", "exchange rate", "fx rate"],
    "vat_treatment": ["vat treatment", "tax treatment", "tax code"],
    "tax_rate": ["applicable", "vat rate", "rate"],
}

TAX_TREATMENT_PATTERNS = [
    ("AE", r"\breverse\b|\brcm\b|\brc\b"),
    ("O", r"out\s*of\s*scope|\boos\b|not\s*subject|non[\s-]*taxable|outside\s*scope|designated\s*zone|\bdz\b|\bnone\b|no\s*tax\b"),
    ("E", r"\bexempt(?:ed)?\b|\bexm\b|\bex\b"),
    ("Z", r"\bzero\b|\bexport(?:s|ed)?\b|\bexp\b|\bzr\b|\b0\s*%"),
    ("S", r"\bstandard\b|\bstd\b|\b5\s*%|domestic\s*taxable|\bsr\b|\bos5\b"),
]


def _treatment_from_text(text: str):
    t = (text or "").lower()
    for cat, pat in TAX_TREATMENT_PATTERNS:
        if re.search(pat, t):
            return cat
    return None


def norm(h: Any) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)          # drop parentheticals like (AED)
    s = re.sub(r"[^a-z0-9%#+/ -]", " ", s)
    s = s.replace("/", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def match_headers(headers: list[str], syn: dict[str, list[str]]) -> dict[str, int]:
    """Map canonical field -> column index. Exact synonym match first, then prefix/contains."""
    nh = [norm(h) for h in headers]
    out: dict[str, int] = {}
    used: set[int] = set()
    for field_name, names in syn.items():
        for cand in names:
            for i, h in enumerate(nh):
                if i in used:
                    continue
                if h == cand:
                    out[field_name] = i
                    used.add(i)
                    break
            if field_name in out:
                break
    for field_name, names in syn.items():
        if field_name in out:
            continue
        for cand in names:
            if len(cand) < 4:
                continue
            for i, h in enumerate(nh):
                if i in used:
                    continue
                if h.startswith(cand + " ") or h.endswith(" " + cand) or (len(cand) >= 6 and cand in h):
                    out[field_name] = i
                    used.add(i)
                    break
            if field_name in out:
                break
    return out


@dataclass
class Sheet:
    name: str
    header_row: int
    headers: list[str]
    rows: list[list[Any]]
    role: str = "unknown"
    mapping: dict[str, int] = field(default_factory=dict)
    score: int = 0


@dataclass
class ImportReport:
    sheets: list[dict] = field(default_factory=list)
    invoice_sheet: Optional[str] = None
    mapping: dict[str, str] = field(default_factory=dict)        # canonical -> header text
    unmapped_headers: list[str] = field(default_factory=list)
    masters_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows_read: int = 0
    invoices_found: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


class ImportError_(ValueError):
    pass


# --------------------------------------------------------------- reading files
def _read_xlsx(data: bytes) -> list[tuple[str, list[list[Any]]]]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i >= MAX_ROWS:
                break
            rows.append(list(r))
        out.append((ws.title, rows))
    return out


def _read_csv(data: bytes) -> list[tuple[str, list[list[Any]]]]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportError_("Could not decode CSV text")
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [row for i, row in enumerate(csv.reader(io.StringIO(text), dialect)) if i < MAX_ROWS]
    return [("Sheet1", rows)]


def _find_header(rows: list[list[Any]]) -> Optional[int]:
    best, best_i = 0, None
    for i, r in enumerate(rows[:15]):
        strings = [c for c in r if isinstance(c, str) and c.strip()]
        if len(strings) < 3:
            continue
        hits = 0
        allsyn = set()
        for syn in (SYN, SYN_CUST, SYN_ENT, SYN_TAX, SYN_ITEM, SYN_SUMMARY):
            for names in syn.values():
                allsyn.update(names)
        for c in strings:
            n = norm(c)
            if n in allsyn or any(n.startswith(a + " ") for a in allsyn if len(a) > 3):
                hits += 1
        score = hits * 10 + len(strings)
        if hits >= 2 and score > best:
            best, best_i = score, i
    return best_i


def _classify(headers: list[str]) -> tuple[str, dict[str, int], int]:
    cands = []
    nh_all = " | ".join(norm(h) for h in headers)
    m_inv = match_headers(headers, SYN)
    has_line_data = ("qty" in m_inv) or ("line_value" in m_inv) or ("unit_price" in m_inv)
    if "inv_number" in m_inv and ("inv_date" in m_inv or has_line_data) and ("description" in m_inv or has_line_data):
        inv_score = sum(k in m_inv for k in ("inv_number", "inv_date", "qty", "unit_price", "line_value", "description", "cust_name", "tax_rate", "tax_code", "uom"))
        cands.append(("invoices", m_inv, inv_score + 5))
    m_sum = match_headers(headers, SYN_SUMMARY)
    if "inv_number" in m_sum and sum(k in m_sum for k in ("tax_inclusive", "vat_total", "payable", "discount_total", "tax_exclusive")) >= 2 and "qty" not in m_inv:
        cands.append(("summary", m_sum, 6 + sum(k in m_sum for k in SYN_SUMMARY)))
    m_t = match_headers(headers, SYN_TAX)
    m_i = match_headers(headers, SYN_ITEM)
    itemish = ("hs_code" in m_i) or ("sac_code" in m_i) or any(w in nh_all for w in ("tariff", "hs code", "hsn", "gtin", "barcode", "selling unit", "list rate", "sku", "product", "item code", "catalog"))
    if "code" in m_t and "rate" in m_t and "inv_date" not in m_inv and "qty" not in m_inv and not itemish and ("treatment" in nh_all or "tax code" in nh_all or "vat code" in nh_all or "filing" in nh_all or "tax" in nh_all):
        cands.append(("taxcodes", m_t, 20 + len(m_t)))
    m_e = match_headers(headers, SYN_ENT)
    m_c = match_headers(headers, SYN_CUST)
    party_words_cust = any(w in nh_all for w in ("customer", "partner", "client", "buyer", "debtor"))
    party_words_ent = any(w in nh_all for w in ("entity", "our compan", "name on trade licen", "functional currency", "books currency", "billing co", "legal entit"))
    if "inv_number" not in m_inv and "qty" not in m_inv:
        if "name" in m_c and ("trn" in m_c or "code" in m_c or "tin" in m_c) and ("street" in m_c or "city" in m_c or "country" in m_c or "emirate" in m_c):
            if party_words_cust and not (party_words_ent and not party_words_cust):
                cands.append(("customers", m_c, 10 + sum(k in m_c for k in SYN_CUST)))
        if "name" in m_e and ("trn" in m_e or "licence_no" in m_e or "tin" in m_e) and ("street" in m_e or "city" in m_e or "emirate" in m_e or "country" in m_e):
            if party_words_ent or not party_words_cust:
                cands.append(("entities", m_e, 10 + sum(k in m_e for k in SYN_ENT) + (3 if party_words_ent else 0)))
    if "code" in m_i and itemish and "inv_number" not in m_inv and "trn" not in m_c:
        cands.append(("items", m_i, 22 + len(m_i)))
    if not cands:
        return "unknown", {}, 0
    cands.sort(key=lambda c: -c[2])
    return cands[0]


def load_sheets(data: bytes, filename: str) -> list[Sheet]:
    fn = (filename or "").lower()
    if fn.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        raw = _read_xlsx(data)
    elif fn.endswith(".xls"):
        raise ImportError_("Legacy .xls is not supported. Save the file as .xlsx or .csv and upload again.")
    else:
        raw = _read_csv(data)
    sheets: list[Sheet] = []
    for name, rows in raw:
        hi = _find_header(rows)
        if hi is None:
            sheets.append(Sheet(name, -1, [], [], "unknown"))
            continue
        headers = [str(c).strip() if c is not None else "" for c in rows[hi]]
        body = [r for r in rows[hi + 1:] if any(c not in (None, "") for c in r)]
        role, mapping, score = _classify(headers)
        sheets.append(Sheet(name, hi, headers, body, role, mapping, score))
    return sheets


# --------------------------------------------------------------- building
def _cell(row: list[Any], m: dict[str, int], key: str):
    i = m.get(key)
    if i is None or i >= len(row):
        return None
    v = row[i]
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _rows_to_dicts(sheet: Sheet) -> dict[str, dict]:
    out = {}
    for r in sheet.rows:
        code = _cell(r, sheet.mapping, "code")
        if code is None:
            continue
        out[str(code).strip().upper()] = {k: _cell(r, sheet.mapping, k) for k in sheet.mapping}
    return out


def _category_from(tax_code, tax_rate, taxcodes: dict[str, dict], description=None) -> tuple[Optional[str], Optional[Decimal], Optional[str]]:
    """Return (category, rate, exemption_reason)."""
    rate = to_decimal(tax_rate)
    reason = None
    cat = None
    if tax_code is not None:
        key = str(tax_code).strip().upper()
        tc = taxcodes.get(key)
        if key in ("S", "Z", "E", "O", "AE"):
            cat = key
        if tc:
            c = (tc.get("category") or "").strip().upper()
            if c in ("S", "Z", "E", "O", "AE"):
                cat = c
            if rate is None:
                rate = to_decimal(tc.get("rate"))
            reason = tc.get("reason")
            if cat is None:
                cat = _treatment_from_text(f"{key} {tc.get('description') or ''} {tc.get('type') or ''}")
        if cat is None:
            cat = _treatment_from_text(key)
    if cat is None and rate is not None and rate > 0:
        cat = "S"
    if cat is None and description:
        cat = _treatment_from_text(str(description))
    if cat == "S" and rate is None:
        rate = Decimal(5)
    if cat in ("Z", "AE") and rate is None:
        rate = Decimal(0)
    return cat, rate, reason


def _party_from_master(rec: dict, fallback_name=None, fallback_trn=None, fallback_tin=None) -> Party:
    if rec is None:
        return Party(name=fallback_name, trn=fallback_trn, tin=fallback_tin)
    rec = dict(rec)
    if not rec.get("country") and rec.get("emirate"):
        from app.engine.model import EMIRATE_NAMES
        em = str(rec["emirate"]).strip()
        if em.upper() in EMIRATES or em.lower() in EMIRATE_NAMES:
            rec["country"] = "AE"
    tin = rec.get("tin")
    trn = rec.get("trn")
    # Some masters put the TRN into the "network id" column; only accept a 10-digit TIN.
    if tin is not None and not re.fullmatch(r"\s*1\d{9}\s*", str(tin).replace(".0", "")):
        tin = None
    lt = (rec.get("licence_type") or "").lower()
    licence_type = "TL"
    if "emirates" in lt or "eid" in lt:
        licence_type = "EID"
    elif "passport" in lt:
        licence_type = "PAS"
    elif "cabinet" in lt:
        licence_type = "CD"
    return Party(
        name=rec.get("name") or fallback_name, trade_name=rec.get("trade_name"),
        tin=tin or fallback_tin, trn=trn or fallback_trn,
        licence_no=rec.get("licence_no"), licence_type=licence_type, licence_authority=rec.get("licence_authority"),
        street=rec.get("street"), city=rec.get("city"), emirate=rec.get("emirate"), country=rec.get("country"),
        email=rec.get("email"),
    )


def build_invoices(sheets: list[Sheet], mapping_override: Optional[dict[str, str]] = None,
                   invoice_sheet: Optional[str] = None, seller_default: Optional[Party] = None) -> tuple[list[Invoice], ImportReport]:
    rep = ImportReport()
    rep.sheets = [{"name": s.name, "role": s.role, "rows": len(s.rows), "headers": s.headers[:40]} for s in sheets]
    inv_sheets = [s for s in sheets if s.role == "invoices"]
    if invoice_sheet:
        inv_sheets = [s for s in sheets if s.name == invoice_sheet] or inv_sheets
    if not inv_sheets:
        raise ImportError_("No sheet looks like an invoice register (needs at least an invoice number plus quantity, amount or description columns). "
                           "Headers found: " + "; ".join(f"{s.name}: {', '.join(h for h in s.headers[:8] if h)}" for s in sheets if s.headers))
    inv_sheets.sort(key=lambda s: -s.score)
    S = inv_sheets[0]
    rep.invoice_sheet = S.name
    m = dict(S.mapping)
    if mapping_override:
        for k, header in mapping_override.items():
            if header in S.headers:
                m[k] = S.headers.index(header)
            elif header == "":
                m.pop(k, None)
    rep.mapping = {k: S.headers[i] for k, i in m.items()}
    rep.unmapped_headers = [h for i, h in enumerate(S.headers) if h and i not in m.values()]

    def best(role):
        c = sorted((s for s in sheets if s.role == role and s.name != S.name), key=lambda s: -s.score)
        return c[0] if c else None
    customers = _rows_to_dicts(best("customers")) if best("customers") else {}
    entities = _rows_to_dicts(best("entities")) if best("entities") else {}
    taxcodes = _rows_to_dicts(best("taxcodes")) if best("taxcodes") else {}
    items = _rows_to_dicts(best("items")) if best("items") else {}
    summary_sheet = best("summary")
    summary: dict[str, dict] = {}
    if summary_sheet:
        for r in summary_sheet.rows:
            n = _cell(r, summary_sheet.mapping, "inv_number")
            if n is not None:
                summary[str(n).strip()] = {k: _cell(r, summary_sheet.mapping, k) for k in summary_sheet.mapping}
    for label, d in (("customers", customers), ("entities", entities), ("taxcodes", taxcodes), ("items", items), ("summary", summary)):
        if d:
            rep.masters_used.append(label)
    cust_by_name = {str(v.get("name") or "").strip().lower(): v for v in customers.values()}

    # group rows by invoice number (carry forward blank header cells)
    groups: dict[str, list[list[Any]]] = {}
    order: list[str] = []
    last_key = None
    carry: dict[str, Any] = {}
    for r in S.rows:
        rep.rows_read += 1
        num = _cell(r, m, "inv_number")
        if num is None:
            if last_key is None:
                continue
            num = last_key
            r = list(r)
            for k, v in carry.items():  # fill blanks on continuation rows
                i = m.get(k)
                if i is not None and i < len(r) and r[i] in (None, ""):
                    r[i] = v
        key = str(num).strip()
        if key != last_key:
            carry = {k: _cell(r, m, k) for k in ("inv_date", "due_date", "entity_code", "cust_code", "cust_name", "cust_trn", "cust_tin", "currency", "fx_rate", "doc_type", "po_number", "payment_terms", "payment_method", "orig_invoice", "credit_reason", "invoice_total", "incoterms", "note", "cust_street", "cust_city", "cust_emirate", "cust_country", "cust_licence")}
            last_key = key
            if key not in groups:
                order.append(key)
        groups.setdefault(key, []).append(r)

    invoices: list[Invoice] = []
    for key in order:
        rows = groups[key]
        first = rows[0]
        g = lambda k, row=first: _cell(row, m, k)  # noqa: E731
        doc_type_txt = str(g("doc_type") or "").lower()
        is_cn = (any(w in doc_type_txt for w in ("credit", "crn", "cr note", "c/n", "adjust", "adj", "return", "cancel")) or doc_type_txt.strip() in ("cn", "crn", "cr")) and "debit" not in doc_type_txt
        currency = g("currency") or "AED"
        ent = entities.get(str(g("entity_code") or "").strip().upper()) if entities else None
        if ent is None and len(entities) == 1:
            ent = next(iter(entities.values()))
        seller = _party_from_master(ent) if ent else (seller_default or Party())
        cust_code = str(g("cust_code") or "").strip().upper()
        crec = customers.get(cust_code) if cust_code else None
        if crec is None and g("cust_name"):
            crec = cust_by_name.get(str(g("cust_name")).strip().lower())
        buyer = _party_from_master(crec, fallback_name=g("cust_name"), fallback_trn=g("cust_trn"), fallback_tin=g("cust_tin"))
        # inline address columns (flat exports) fill whatever the master did not provide
        inline = {"street": g("cust_street"), "city": g("cust_city"), "emirate": g("cust_emirate"), "country": g("cust_country"), "licence_no": g("cust_licence")}
        if any(inline.values()):
            merged = buyer.model_dump()
            for k, val in inline.items():
                if val not in (None, "") and not merged.get(k):
                    merged[k] = val
            if not merged.get("country") and merged.get("emirate") and str(merged["emirate"]).strip().upper() in EMIRATES | set(k.upper() for k in __import__("app.engine.model", fromlist=["EMIRATE_NAMES"]).EMIRATE_NAMES):
                merged["country"] = "AE"
            buyer = Party(**merged)

        lines: list[Line] = []
        for i, r in enumerate(rows, start=1):
            rg = lambda k, row=r: _cell(row, m, k)  # noqa: E731
            code = str(rg("item_code") or "").strip().upper()
            irec = items.get(code) if code else None
            tax_code = rg("tax_code") or (irec or {}).get("tax_code")
            cat, rate, reason = _category_from(tax_code, rg("tax_rate"), taxcodes, rg("description"))
            nature = str(rg("nature") or (irec or {}).get("nature") or "").strip().lower()
            item_type = "G" if nature.startswith("g") else "S" if nature.startswith("s") else "B" if nature.startswith("b") else None
            qty = to_decimal(rg("qty"))
            price = to_decimal(rg("unit_price"))
            per = to_decimal(rg("price_per"))
            gross = to_decimal(rg("gross_price"))
            if per and per not in (0, 1):
                if price is not None:
                    price = (price / per)
                if gross is not None:
                    gross = (gross / per)
            lines.append(Line(
                id=str(rg("line_no")) if rg("line_no") is not None else str(i),
                name=(rg("description") or (irec or {}).get("name") or (irec or {}).get("description")),
                description=((irec or {}).get("description") or rg("description")),
                quantity=qty, unit=rg("uom") or (irec or {}).get("unit"),
                unit_price=price, gross_price=gross, discount=to_decimal(rg("discount")),
                vat_category=cat, vat_rate=rate, line_net=to_decimal(rg("line_value")),
                vat_amount=to_decimal(rg("tax_amount")), line_total=to_decimal(rg("line_total")),
                item_type=item_type, hs_code=(str(rg("hs_code") or (irec or {}).get("hs_code") or "") or None),
                sac_code=(str(rg("sac_code") or (irec or {}).get("sac_code") or "") or None),
                exemption_reason_code=reason if cat == "E" else None,
            ))
        totals = Totals()
        srec = summary.get(key)
        if srec:
            totals = Totals(discount_total=srec.get("discount_total"), charge_total=srec.get("charge_total"),
                            tax_exclusive=srec.get("tax_exclusive"), vat_total=srec.get("vat_total"),
                            tax_inclusive=srec.get("tax_inclusive"), paid=srec.get("paid"), rounding=srec.get("rounding"),
                            payable=srec.get("payable"), vat_total_aed=srec.get("vat_total_aed"))
        elif g("invoice_total") is not None:
            totals = Totals(payable=g("invoice_total"))
        inv = Invoice(
            doc_type="creditnote" if is_cn else "invoice",
            number=key, issue_date=g("inv_date"), due_date=g("due_date"),
            currency=currency, exchange_rate=g("fx_rate") or (srec or {}).get("fx_rate"),
            seller=seller, buyer=buyer, lines=lines, totals=totals,
            payment_means_code=g("payment_method"), payment_terms=g("payment_terms"), po_number=g("po_number"),
            original_invoice_number=g("orig_invoice") or (_ref_from_text(g("note"), key) if is_cn else None),
            credit_reason_code=(credit_reason_code(g("credit_reason")) or credit_reason_code(g("note"))) if is_cn else None,
            note=g("note"), incoterms=(str(g("incoterms")).strip().upper()[:3] if g("incoterms") else None),
            iban=(ent or {}).get("iban") if ent else None,
        )
        invoices.append(inv)
    rep.invoices_found = len(invoices)
    if not invoices:
        rep.warnings.append("No invoice rows found under the detected header.")
    return invoices, rep


def _ref_from_text(text, own_number: str):
    """Find an invoice-number-like token in free text (e.g. 'Credit against OG/01/26/4101')."""
    if not text:
        return None
    for tok in re.findall(r"[A-Z]{1,6}[/\-][A-Z0-9/\-]{3,}\d|\b[A-Z]{2,5}\d{3,}\b|\b\d{4,}\b", str(text).upper()):
        if tok != own_number.upper():
            return tok
    return None


def import_file(data: bytes, filename: str, mapping_override: Optional[dict[str, str]] = None,
                invoice_sheet: Optional[str] = None, seller_default: Optional[Party] = None) -> tuple[list[Invoice], ImportReport]:
    sheets = load_sheets(data, filename)
    return build_invoices(sheets, mapping_override, invoice_sheet, seller_default)
