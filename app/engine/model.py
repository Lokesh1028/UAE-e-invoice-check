"""
Canonical invoice model: the common shape every importer (CSV/XLSX, PDF text,
XML, API JSON) produces, and the UBL generator consumes.

Rules:
 - Only data the user actually supplied goes in. Nothing is invented, except
   purely technical identifiers (UUID, specification IDs, line numbers) which
   are reported as auto-generated.
 - Money is Decimal, never float.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

VatCategory = Literal["S", "Z", "E", "O", "AE"]
DocType = Literal["invoice", "creditnote"]
EMIRATES = {"AUH", "DXB", "SHJ", "AJM", "UAQ", "RAK", "FUJ"}
EMIRATE_NAMES = {
    "abu dhabi": "AUH", "abudhabi": "AUH", "auh": "AUH",
    "dubai": "DXB", "dxb": "DXB",
    "sharjah": "SHJ", "shj": "SHJ",
    "ajman": "AJM", "ajm": "AJM",
    "umm al quwain": "UAQ", "umm al-quwain": "UAQ", "uaq": "UAQ",
    "ras al khaimah": "RAK", "ras al-khaimah": "RAK", "rak": "RAK",
    "fujairah": "FUJ", "fuj": "FUJ",
}
UNIT_SYNONYMS = {
    "pcs": "H87", "pc": "H87", "piece": "H87", "pieces": "H87", "nos": "H87", "no": "H87", "no.": "H87", "pce": "H87",
    "unit": "H87", "units": "H87", "qty": "H87", "ea": "EA", "each": "EA", "one": "C62",
    "kg": "KGM", "kgs": "KGM", "kilogram": "KGM", "g": "GRM", "gm": "GRM", "gram": "GRM", "ton": "TNE", "tonne": "TNE", "mt": "TNE",
    "l": "LTR", "ltr": "LTR", "litre": "LTR", "liter": "LTR", "ml": "MLT",
    "m": "MTR", "mtr": "MTR", "metre": "MTR", "meter": "MTR", "rm": "MTR", "sqm": "MTK", "m2": "MTK", "sq.m": "MTK", "sq m": "MTK",
    "cbm": "MTQ", "m3": "MTQ", "cm": "CMT", "km": "KMT", "ft": "FOT", "sqft": "FTK", "inch": "INH",
    "hr": "HUR", "hrs": "HUR", "hour": "HUR", "hours": "HUR", "min": "MIN", "day": "DAY", "days": "DAY",
    "week": "WEE", "weeks": "WEE", "month": "MON", "months": "MON", "mth": "MON", "year": "ANN", "yr": "ANN",
    "set": "SET", "sets": "SET", "pair": "PR", "dozen": "DZN", "dz": "DZN", "lot": "LO",
    "box": "XBX", "boxes": "XBX", "bx": "XBX", "carton": "XCT", "ctn": "XCT", "cartons": "XCT", "case": "XCS", "cs": "XCS",
    "pack": "XPK", "packet": "XPK", "pkt": "XPK", "roll": "XRO", "rolls": "XRO", "bag": "XBG", "bags": "XBG",
    "drum": "XDR", "rol": "XRO", "pkg": "XPK", "pkgs": "XPK", "mday": "E49", "mdays": "E49", "contr": "C62", "contract": "C62", "consg": "C62", "consignment": "C62", "shipment": "C62", "package": "XPK", "packages": "XPK", "pce": "H87", "ea.": "EA", "unit.": "H87", "drm": "XDR", "drums": "XDR", "nos.": "H87", "pcs.": "H87", "pkts": "XPK", "ctns": "XCT", "bdl": "XBE", "bundles": "XBE", "mtrs": "MTR", "ltrs": "LTR", "sqmt": "MTK", "sq.mt": "MTK", "sq.ft": "FTK", "cbm.": "MTQ", "tons": "TNE", "mts": "TNE", "ton.": "TNE", "no": "H87", "doz": "DZN", "pr": "PR", "pairs": "PR", "hrs.": "HUR", "mth.": "MON", "qtr": "QAN", "quarter": "QAN", "kit": "KT", "kits": "KT", "can.": "XCA", "tin": "XTN", "jar": "XJR", "pouch": "XPO", "sachet": "XSH", "sack": "XSA", "tray": "XPU", "pallets": "XPX", "crate": "XCR", "container": "XCN", "trips": "E48", "visits": "E48", "sessions": "E48", "mandays": "E49", "man days": "E49", "manhour": "HUR", "man hours": "HUR", "manhours": "HUR", "license": "C62", "licence": "C62", "user": "C62", "users": "C62", "seat": "C62", "room night": "DAY", "nights": "DAY", "pallet": "XPX", "bottle": "XBO", "can": "XCA", "bundle": "XBE", "sheet": "XST", "tube": "XTU",
    "job": "E48", "service": "E48", "svc": "E48", "ls": "LS", "lump sum": "LS", "lumpsum": "LS", "fixed": "1I",
    "kwh": "KWH", "trip": "E48", "visit": "E48", "night": "DAY", "session": "E48", "man-day": "E49", "manday": "E49",
}
PAYMENT_SYNONYMS = {
    "cash": "10", "cheque": "20", "check": "20", "bank transfer": "30", "transfer": "30", "wire": "30",
    "tt": "30", "neft": "30", "credit transfer": "30", "card": "48", "credit card": "54", "debit card": "55",
    "online": "68", "payment link": "68", "direct debit": "49", "credit": "97",
}
CREDIT_REASON_WORDS = {
    "DL8.61.1.A": ["cancel", "cancelled", "cancellation", "void"],
    "DL8.61.1.B": ["nature", "tax treatment", "treatment changed"],
    "DL8.61.1.C": ["consideration", "price", "rate", "discount agreed", "revised", "reduced", "negotiat"],
    "DL8.61.1.D": ["return", "returned", "rejected", "damaged", "short"],
    "DL8.61.1.E": ["error", "wrong", "mistake", "incorrect", "duplicate", "erroneous"],
    "VD": ["volume", "turnover discount", "rebate"],
}


def credit_reason_code(text) -> Optional[str]:
    if text is None:
        return None
    t = str(text).strip()
    if t.upper() in CREDIT_REASON_WORDS:
        return t.upper()
    tl = t.lower()
    for code, words in CREDIT_REASON_WORDS.items():
        if any(w in tl for w in words):
            return code
    return None


TWO = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


class Party(BaseModel):
    name: Optional[str] = None                 # legal / registered name
    trade_name: Optional[str] = None
    tin: Optional[str] = None                  # 10 digits, Peppol endpoint (0235)
    trn: Optional[str] = None                  # 15 chars, VAT number
    licence_no: Optional[str] = None           # legal registration identifier
    licence_type: Literal["TL", "EID", "PAS", "CD"] = "TL"
    licence_authority: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    emirate: Optional[str] = None              # AUH/DXB/SHJ/AJM/UAQ/RAK/FUJ (names are normalised)
    postal_zone: Optional[str] = None
    country: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("tin", "trn", "licence_no", mode="before")
    @classmethod
    def _strip_ids(cls, v):
        if v is None:
            return None
        s = str(v).strip().replace(" ", "").replace("-", "")
        if s.endswith(".0"):  # Excel numeric cell
            s = s[:-2]
        return s or None

    @field_validator("emirate", mode="before")
    @classmethod
    def _norm_emirate(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return EMIRATE_NAMES.get(s.lower(), s.upper())

    @field_validator("country", mode="before")
    @classmethod
    def _norm_country(cls, v):
        if v is None or str(v).strip() == "":
            return None
        s = str(v).strip()
        names = {"uae": "AE", "u.a.e": "AE", "u.a.e.": "AE", "united arab emirates": "AE", "india": "IN",
                 "saudi arabia": "SA", "ksa": "SA", "oman": "OM", "qatar": "QA", "bahrain": "BH", "kuwait": "KW",
                 "united kingdom": "GB", "uk": "GB", "usa": "US", "united states": "US"}
        return names.get(s.lower(), s.upper()[:2] if len(s) == 2 else s)


class Line(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None       # net unit price
    gross_price: Optional[Decimal] = None      # before line discount; defaults to unit_price
    discount: Optional[Decimal] = None         # line-level discount amount (absolute)
    vat_category: Optional[VatCategory] = None
    vat_rate: Optional[Decimal] = None
    line_net: Optional[Decimal] = None         # supplied by user, or computed
    vat_amount: Optional[Decimal] = None
    line_total: Optional[Decimal] = None       # net + VAT (BTAE-10)
    item_type: Optional[Literal["G", "S", "B"]] = None
    hs_code: Optional[str] = None
    sac_code: Optional[str] = None
    exemption_reason_code: Optional[str] = None
    goods_type_code: Optional[str] = None

    @field_validator("unit", mode="before")
    @classmethod
    def _norm_unit(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return UNIT_SYNONYMS.get(s.lower(), s.upper() if len(s) <= 3 else s)

    @field_validator("vat_category", mode="before")
    @classmethod
    def _norm_cat(cls, v):
        if v is None:
            return None
        s = str(v).strip().upper()
        if not s:
            return None
        aliases = {"STANDARD": "S", "STD": "S", "5%": "S", "5": "S", "ZERO": "Z", "ZERO RATED": "Z", "ZERO-RATED": "Z",
                   "0%": "Z", "EXEMPT": "E", "EXEMPTED": "E", "OUT OF SCOPE": "O", "OOS": "O", "NA": "O",
                   "REVERSE CHARGE": "AE", "RCM": "AE", "RC": "AE"}
        return aliases.get(s, s)

    @field_validator("quantity", "unit_price", "gross_price", "discount", "vat_rate", "line_net", "vat_amount", "line_total", mode="before")
    @classmethod
    def _dec(cls, v):
        return to_decimal(v)

    # derived helpers -------------------------------------------------------
    def computed_net(self) -> Optional[Decimal]:
        if self.line_net is not None:
            return self.line_net
        if self.quantity is None or self.unit_price is None:
            return None
        return q2(self.quantity * self.unit_price - (self.discount or Decimal(0)))

    def effective_rate(self) -> Optional[Decimal]:
        if self.vat_rate is not None:
            return self.vat_rate
        if self.vat_category == "S":
            return Decimal(5)
        if self.vat_category in ("Z", "AE"):
            return Decimal(0)
        return None

    def computed_vat(self) -> Optional[Decimal]:
        if self.vat_amount is not None:
            return self.vat_amount
        net = self.computed_net()
        if net is None:
            return None
        if self.vat_category in ("E", "O", "AE", "Z"):
            return Decimal("0.00")
        rate = self.effective_rate()
        if rate is None:
            return None
        return q2(net * rate / Decimal(100))

    def computed_total(self) -> Optional[Decimal]:
        if self.line_total is not None:
            return self.line_total
        net, vat = self.computed_net(), self.computed_vat()
        if net is None:
            return None
        return q2(net + (vat or Decimal(0)))


class Totals(BaseModel):
    """Totals as the user supplied them. Any that are None get computed from lines."""
    line_sum: Optional[Decimal] = None
    discount_total: Optional[Decimal] = None
    charge_total: Optional[Decimal] = None
    tax_exclusive: Optional[Decimal] = None
    vat_total: Optional[Decimal] = None
    tax_inclusive: Optional[Decimal] = None
    paid: Optional[Decimal] = None
    rounding: Optional[Decimal] = None
    payable: Optional[Decimal] = None
    vat_total_aed: Optional[Decimal] = None

    @field_validator("*", mode="before")
    @classmethod
    def _dec(cls, v):
        return to_decimal(v)


class Invoice(BaseModel):
    doc_type: DocType = "invoice"
    number: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    type_code: Optional[str] = None            # 380 invoice, 480 out of scope, 381 credit note
    transaction_type: str = "00000000"
    currency: str = "AED"
    exchange_rate: Optional[Decimal] = None
    uuid: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    seller: Party = Field(default_factory=Party)
    buyer: Party = Field(default_factory=Party)
    lines: list[Line] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    payment_means_code: Optional[str] = None
    iban: Optional[str] = None
    payment_terms: Optional[str] = None
    note: Optional[str] = None
    po_number: Optional[str] = None
    original_invoice_number: Optional[str] = None   # credit notes
    original_invoice_date: Optional[date] = None
    credit_reason_code: Optional[str] = None
    document_discount: Optional[Decimal] = None     # single document-level allowance (S, 5%)
    incoterms: Optional[str] = None
    auto_generated: list[str] = Field(default_factory=list)  # names of fields we filled in

    @field_validator("payment_means_code", mode="before")
    @classmethod
    def _norm_pay(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return PAYMENT_SYNONYMS.get(s.lower(), s)

    @field_validator("issue_date", "due_date", "original_invoice_date", mode="before")
    @classmethod
    def _date(cls, v):
        return to_date(v)

    @field_validator("exchange_rate", "document_discount", mode="before")
    @classmethod
    def _dec(cls, v):
        return to_decimal(v)

    @field_validator("currency", mode="before")
    @classmethod
    def _cur(cls, v):
        if v is None or str(v).strip() == "":
            return "AED"
        s = str(v).strip().upper()
        return {"DHS": "AED", "DH": "AED", "DIRHAM": "AED", "DIRHAMS": "AED", "AED.": "AED", "$": "USD", "US$": "USD"}.get(s, s)

    def effective_type_code(self) -> str:
        if self.type_code:
            return str(self.type_code)
        return "381" if self.doc_type == "creditnote" else "380"


# ----------------------------------------------------------------- coercion
def to_decimal(v) -> Optional[Decimal]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    if not s or s.lower() in ("na", "n/a", "nil", "-", "none"):
        return None
    s = s.replace(",", "").replace("AED", "").replace("aed", "").replace("Dhs", "").replace("%", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except Exception:
        return None


def to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    from datetime import datetime
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{8}", s):
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:  # Excel serial number
        n = float(s)
        if 20000 < n < 80000:
            from datetime import timedelta
            return date(1899, 12, 30) + timedelta(days=int(n))
    except ValueError:
        pass
    return None
