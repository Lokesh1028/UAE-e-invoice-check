"""
Canonical Invoice -> PINT AE (UBL 2.1) XML.

Design: emit exactly what the user supplied. For structurally mandatory
elements that are missing (invoice number, date, names, line basics) we emit a
clearly marked placeholder so the XSD passes and the official business rules
can still run on the rest; each placeholder is recorded as a 'precheck'
finding with the official rule id, so the user sees it as a normal error.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from lxml import etree

from .model import Invoice, Line, Party, q2
from .codelists import UNIT_CODES, PAYMENT_CODES
from .validator import Finding

NS_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
PLACEHOLDER = "MISSING"

TAX_CATEGORY_NAMES = {"S": "Standard rate", "Z": "Zero rated", "E": "Exempt", "O": "Out of scope", "AE": "Reverse charge"}


def _cbc(parent, name, text, **attrs):
    if text is None:
        return None
    s = str(text)
    if s == "":
        return None
    el = etree.SubElement(parent, f"{{{NS_CBC}}}{name}")
    el.text = s
    for k, v in attrs.items():
        if v is not None:
            el.set(k, str(v))
    return el


def _cac(parent, name):
    return etree.SubElement(parent, f"{{{NS_CAC}}}{name}")


def _amt(parent, name, value: Optional[Decimal], cur: str):
    if value is None:
        return None
    return _cbc(parent, name, _fmt(value), currencyID=cur)


def _fmt(d: Decimal) -> str:
    d = Decimal(d)
    if d == d.to_integral():
        return str(d.quantize(Decimal(1)))
    if -d.as_tuple().exponent > 6:
        d = d.quantize(Decimal("0.000001"))
    return format(d.normalize(), "f")


class GenerationResult:
    def __init__(self, xml: bytes, findings: list[Finding], doc_type: str):
        self.xml = xml
        self.findings = findings
        self.doc_type = doc_type


def build(inv: Invoice) -> GenerationResult:
    findings: list[Finding] = []
    is_cn = inv.doc_type == "creditnote"
    ns_root = NS_CN if is_cn else NS_INV
    root_name = "CreditNote" if is_cn else "Invoice"
    cur = inv.currency or "AED"
    root = etree.Element(f"{{{ns_root}}}{root_name}", nsmap={None: ns_root, "cac": NS_CAC, "cbc": NS_CBC})

    def missing(rule_id: str, what: str, location: str = ""):
        findings.append(Finding(rule_id, "fatal", "precheck", f"{what} is missing.", location=location))

    _cbc(root, "CustomizationID", "urn:peppol:pint:billing-1@ae-1")
    _cbc(root, "ProfileID", "urn:peppol:bis:billing")
    _cbc(root, "ProfileExecutionID", inv.transaction_type or "00000000")
    if inv.number:
        _cbc(root, "ID", inv.number)
    else:
        missing("ibr-002", "Invoice number", "/Invoice/cbc:ID")
        _cbc(root, "ID", PLACEHOLDER)
    _cbc(root, "UUID", inv.uuid)
    if inv.issue_date:
        _cbc(root, "IssueDate", inv.issue_date.isoformat())
    else:
        missing("ibr-003", "Invoice issue date", "/Invoice/cbc:IssueDate")
        _cbc(root, "IssueDate", "1900-01-01")
    if not is_cn:
        _cbc(root, "DueDate", inv.due_date.isoformat() if inv.due_date else None)
    _cbc(root, "CreditNoteTypeCode" if is_cn else "InvoiceTypeCode", inv.effective_type_code())
    _cbc(root, "Note", inv.note)
    _cbc(root, "DocumentCurrencyCode", cur)
    fx = inv.exchange_rate if (cur != "AED" and inv.exchange_rate) else None
    if fx:
        _cbc(root, "TaxCurrencyCode", "AED")
    if inv.po_number:
        _cbc(_cac(root, "OrderReference"), "ID", inv.po_number)
    if is_cn or inv.original_invoice_number:
        br = _cac(root, "BillingReference")
        idr = _cac(br, "InvoiceDocumentReference")
        _cbc(idr, "ID", inv.original_invoice_number or (PLACEHOLDER if is_cn else None))
        if inv.original_invoice_date:
            _cbc(idr, "IssueDate", inv.original_invoice_date.isoformat())
        if is_cn and not inv.original_invoice_number:
            missing("ibr-055-ae", "Original invoice number on the credit note", "/CreditNote/cac:BillingReference")
    if is_cn and inv.credit_reason_code:
        adr = _cac(root, "AdditionalDocumentReference")
        _cbc(adr, "ID", "CreditReason")
        _cbc(adr, "DocumentTypeCode", inv.credit_reason_code)

    if fx:
        # BTAE-20: total including VAT expressed in AED (computed later; patched after totals are known)
        adr_aed = _cac(root, "AdditionalDocumentReference")
        _cbc(adr_aed, "ID", "AED")
        _cbc(adr_aed, "DocumentTypeCode", "aedtotal-incl-vat")
        aed_desc = _cbc(adr_aed, "DocumentDescription", "AED 0")
    else:
        aed_desc = None

    _party(root, "AccountingSupplierParty", inv.seller, True, findings)
    _party(root, "AccountingCustomerParty", inv.buyer, False, findings)

    if inv.incoterms:
        d = _cac(root, "Delivery")
        _cbc(_cac(d, "DeliveryTerms"), "ID", inv.incoterms, schemeID="Incoterms")

    type_code = inv.effective_type_code()
    deemed = len(inv.transaction_type or "") == 8 and inv.transaction_type[1] == "1"
    if inv.payment_means_code and type_code not in ("381", "81", "261") and not deemed:
        # ibr-191-ae: payment means is required on invoices and must be absent on credit notes / deemed supplies
        if inv.payment_means_code not in PAYMENT_CODES:
            findings.append(Finding("ibr-cl-16", "fatal", "precheck", f"Payment method '{inv.payment_means_code}' is not a UNCL4461 code (10 cash, 20 cheque, 30 bank transfer, 48 card, 68 online).", location="/Invoice/cac:PaymentMeans"))
        pm = _cac(root, "PaymentMeans")
        _cbc(pm, "PaymentMeansCode", inv.payment_means_code)
        if inv.iban:
            _cbc(_cac(pm, "PayeeFinancialAccount"), "ID", inv.iban)
    if inv.payment_terms:
        _cbc(_cac(root, "PaymentTerms"), "Note", inv.payment_terms)

    # document-level allowance / charge, in the invoice's dominant VAT category
    dom_cat, dom_rate = _dominant_category(inv)
    for is_charge, amount, reason in ((False, inv.document_discount or inv.totals.discount_total, "Discount"),
                                      (True, inv.totals.charge_total, "Freight / charges")):
        if amount:
            ac = _cac(root, "AllowanceCharge")
            _cbc(ac, "ChargeIndicator", "true" if is_charge else "false")
            _cbc(ac, "AllowanceChargeReason", reason)
            _amt(ac, "Amount", q2(abs(amount)), cur)
            tc = _cac(ac, "TaxCategory")
            _cbc(tc, "ID", dom_cat)
            if dom_cat not in ("E", "O"):
                _cbc(tc, "Percent", _fmt(dom_rate if dom_rate is not None else Decimal(0)))
            _cbc(_cac(tc, "TaxScheme"), "ID", "VAT")

    if inv.exchange_rate and cur != "AED":
        er = _cac(root, "TaxExchangeRate")
        _cbc(er, "SourceCurrencyCode", cur)
        _cbc(er, "TargetCurrencyCode", "AED")
        _cbc(er, "CalculationRate", _fmt(inv.exchange_rate))

    # ---- totals & VAT breakdown
    lines = inv.lines
    if not lines:
        missing("ibr-016", "Line items", "/Invoice/cac:InvoiceLine")
    line_nets = [ln.computed_net() for ln in lines]
    line_vats = [ln.computed_vat() for ln in lines]
    line_sum = inv.totals.line_sum if inv.totals.line_sum is not None else (q2(sum((n for n in line_nets if n is not None), Decimal(0))) if lines else None)
    disc = abs(inv.totals.discount_total) if inv.totals.discount_total is not None else (q2(abs(inv.document_discount)) if inv.document_discount else None)
    charge = inv.totals.charge_total
    tax_excl = inv.totals.tax_exclusive if inv.totals.tax_exclusive is not None else (
        q2(line_sum - (disc or 0) + (charge or 0)) if line_sum is not None else None)

    # VAT breakdown grouped by (category, rate)
    groups: dict[tuple[str, Optional[Decimal]], dict] = {}
    for ln, net, vat in zip(lines, line_nets, line_vats):
        if net is None:
            continue
        cat = ln.vat_category or "S"
        rate = ln.effective_rate()
        key = (cat, rate)
        g = groups.setdefault(key, {"taxable": Decimal(0), "vat": Decimal(0), "exempt_code": ln.exemption_reason_code})
        g["taxable"] += net
        g["vat"] += (vat or Decimal(0))
    adj = (inv.totals.charge_total or Decimal(0)) - abs(inv.document_discount or inv.totals.discount_total or Decimal(0))
    if adj and groups:
        key = (dom_cat, dom_rate)
        g = groups.setdefault(key, {"taxable": Decimal(0), "vat": Decimal(0), "exempt_code": None})
        g["taxable"] += q2(adj)
        if dom_cat in ("S",) and dom_rate:
            g["vat"] = q2(g["taxable"] * dom_rate / 100)
    vat_total = inv.totals.vat_total if inv.totals.vat_total is not None else (q2(sum((g["vat"] for g in groups.values()), Decimal(0))) if groups else None)
    tax_incl = inv.totals.tax_inclusive if inv.totals.tax_inclusive is not None else (q2(tax_excl + (vat_total or 0)) if tax_excl is not None else None)
    payable = inv.totals.payable if inv.totals.payable is not None else (
        q2(tax_incl - (inv.totals.paid or 0) + (inv.totals.rounding or 0)) if tax_incl is not None else None)

    tt = _cac(root, "TaxTotal")
    _amt(tt, "TaxAmount", q2(vat_total) if vat_total is not None else Decimal("0.00"), cur)
    if fx and vat_total is not None:
        aed = inv.totals.vat_total_aed if inv.totals.vat_total_aed is not None else q2(vat_total * fx)
        _amt(_cac(root, "TaxTotal"), "TaxAmount", q2(aed), "AED")
    for (cat, rate), g in groups.items():
        st = _cac(tt, "TaxSubtotal")
        _amt(st, "TaxableAmount", q2(g["taxable"]), cur)
        _amt(st, "TaxAmount", q2(g["vat"]), cur)
        tc = _cac(st, "TaxCategory")
        _cbc(tc, "ID", cat)
        if cat != "E" and cat != "O":
            _cbc(tc, "Percent", _fmt(rate) if rate is not None else "0")
        if cat == "E":
            _cbc(tc, "TaxExemptionReasonCode", g.get("exempt_code"))
        _cbc(_cac(tc, "TaxScheme"), "ID", "VAT")

    lmt = _cac(root, "LegalMonetaryTotal")
    _amt(lmt, "LineExtensionAmount", q2(line_sum) if line_sum is not None else Decimal("0.00"), cur)
    _amt(lmt, "TaxExclusiveAmount", q2(tax_excl) if tax_excl is not None else Decimal("0.00"), cur)
    _amt(lmt, "TaxInclusiveAmount", q2(tax_incl) if tax_incl is not None else Decimal("0.00"), cur)
    _amt(lmt, "AllowanceTotalAmount", q2(disc) if disc is not None else None, cur)
    _amt(lmt, "ChargeTotalAmount", q2(charge) if charge is not None else None, cur)
    _amt(lmt, "PrepaidAmount", q2(inv.totals.paid) if inv.totals.paid is not None else None, cur)
    _amt(lmt, "PayableRoundingAmount", q2(inv.totals.rounding) if inv.totals.rounding is not None else None, cur)
    _amt(lmt, "PayableAmount", q2(payable) if payable is not None else Decimal("0.00"), cur)

    if aed_desc is not None and tax_incl is not None:
        aed_desc.text = f"AED {q2(tax_incl * fx)}"

    for i, ln in enumerate(lines, start=1):
        _line(root, ln, i, cur, is_cn, findings)

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return GenerationResult(xml, findings, inv.doc_type)


def _dominant_category(inv: Invoice):
    """VAT category/rate carrying the largest net amount; default S/5."""
    best, best_amt = ("S", Decimal(5)), Decimal(-1)
    sums: dict = {}
    for ln in inv.lines:
        net = ln.computed_net()
        if net is None:
            continue
        key = (ln.vat_category or "S", ln.effective_rate())
        sums[key] = sums.get(key, Decimal(0)) + net
    for key, amt in sums.items():
        if amt > best_amt:
            best, best_amt = key, amt
    return best


def merge_findings(precheck, official):
    """Drop official findings whose rule id was already reported by a precheck (same problem, clearer text)."""
    pre_ids = {f.rule_id for f in precheck}
    return list(precheck) + [f for f in official if f.rule_id not in pre_ids]


def _party(root, tag: str, p: Party, is_seller: bool, findings: list[Finding]):
    who = "Seller" if is_seller else "Buyer"
    base = f"/Invoice/cac:{tag}"
    wrap = _cac(root, tag)
    party = _cac(wrap, "Party")
    if p.tin:
        _cbc(party, "EndpointID", p.tin, schemeID="0235")
    else:
        findings.append(Finding("ibr-081" if is_seller else "ibr-080", "fatal", "precheck",
                                f"{who} electronic address (10-digit TIN) is missing.", location=base + "/cac:Party/cbc:EndpointID"))
    if p.trade_name:
        _cbc(_cac(party, "PartyName"), "Name", p.trade_name)
    addr = _cac(party, "PostalAddress")
    _cbc(addr, "StreetName", p.street)
    _cbc(addr, "AdditionalStreetName", p.street2)
    _cbc(addr, "CityName", p.city)
    _cbc(addr, "PostalZone", p.postal_zone)
    _cbc(addr, "CountrySubentity", p.emirate)
    if p.country:
        _cbc(_cac(addr, "Country"), "IdentificationCode", p.country)
    # no country: cac:Country is optional in UBL, the official rule ibr-009 / ibr-011 reports it
    if p.trn:
        pts = _cac(party, "PartyTaxScheme")
        _cbc(pts, "CompanyID", p.trn)
        _cbc(_cac(pts, "TaxScheme"), "ID", "VAT")
    elif is_seller and p.tin:
        # not VAT registered: identify by TIN with scheme "!VAT" per ibr-178-ae
        pts = _cac(party, "PartyTaxScheme")
        _cbc(pts, "CompanyID", p.tin)
        _cbc(_cac(pts, "TaxScheme"), "ID", "!VAT")
    ple = _cac(party, "PartyLegalEntity")
    if p.name:
        _cbc(ple, "RegistrationName", p.name)
    else:
        findings.append(Finding("ibr-006" if is_seller else "ibr-007", "fatal", "precheck",
                                f"{who} legal name is missing.", location=base + "/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"))
        _cbc(ple, "RegistrationName", PLACEHOLDER)
    if p.licence_no:
        _cbc(ple, "CompanyID", p.licence_no, schemeAgencyID=p.licence_type,
             schemeAgencyName=p.licence_authority)
    if p.email or p.phone:
        c = _cac(party, "Contact")
        _cbc(c, "Telephone", p.phone)
        _cbc(c, "ElectronicMail", p.email)


def _line(root, ln: Line, idx: int, cur: str, is_cn: bool, findings: list[Finding]):
    tag = "CreditNoteLine" if is_cn else "InvoiceLine"
    qty_tag = "CreditedQuantity" if is_cn else "InvoicedQuantity"
    loc = f"/Invoice/cac:{tag}[{idx}]"
    el = _cac(root, tag)
    _cbc(el, "ID", ln.id or str(idx))
    net = ln.computed_net()
    unit = ln.unit or "H87"
    if ln.unit and ln.unit not in UNIT_CODES:
        findings.append(Finding("ibr-cl-23", "fatal", "precheck", f"Line {idx}: unit '{ln.unit}' is not a UN/ECE unit code (use e.g. H87 piece, KGM kg, MTR metre, HUR hour, XBX box, XCT carton).", location=loc))
    if ln.quantity is None:
        findings.append(Finding("ibr-022", "fatal", "precheck", f"Line {idx}: quantity is missing.", location=loc))
        _cbc(el, qty_tag, "0", unitCode=unit)
    else:
        if ln.unit is None:
            findings.append(Finding("ibr-023", "fatal", "precheck", f"Line {idx}: unit of measure is missing.", location=loc))
        _cbc(el, qty_tag, _fmt(ln.quantity), unitCode=unit)
    if net is None:
        findings.append(Finding("ibr-024", "fatal", "precheck", f"Line {idx}: line net amount could not be determined (need quantity and unit price, or a line amount).", location=loc))
        _amt(el, "LineExtensionAmount", Decimal("0.00"), cur)
    else:
        _amt(el, "LineExtensionAmount", q2(net), cur)
    item = _cac(el, "Item")
    _cbc(item, "Description", ln.description or ln.name)
    if ln.name:
        _cbc(item, "Name", ln.name)
    else:
        findings.append(Finding("ibr-025", "fatal", "precheck", f"Line {idx}: item name is missing.", location=loc))
        _cbc(item, "Name", PLACEHOLDER)
    if ln.sac_code:
        _cbc(_cac(item, "AdditionalItemIdentification"), "ID", ln.sac_code, schemeID="SAC")
    if ln.item_type or ln.hs_code or ln.goods_type_code:
        cc = _cac(item, "CommodityClassification")
        _cbc(cc, "NatureCode", ln.goods_type_code)
        _cbc(cc, "CommodityCode", ln.item_type)
        if ln.hs_code:
            _cbc(cc, "ItemClassificationCode", ln.hs_code, listID="HS", listVersionID="1.0")
    cat = ln.vat_category
    if cat is None:
        findings.append(Finding("ibr-145-ae", "fatal", "precheck", f"Line {idx}: VAT category is missing (S, Z, E, O or AE).", location=loc))
    ctc = _cac(item, "ClassifiedTaxCategory")
    _cbc(ctc, "ID", cat or "S")
    rate = ln.effective_rate()
    if (cat or "S") not in ("E", "O"):
        if rate is None:
            findings.append(Finding("ibr-152-missing", "fatal", "precheck", f"Line {idx}: VAT rate is missing.", location=loc))
            rate = Decimal(0)
        _cbc(ctc, "Percent", _fmt(rate))
    if cat == "E":
        _cbc(ctc, "TaxExemptionReasonCode", ln.exemption_reason_code)
    _cbc(_cac(ctc, "TaxScheme"), "ID", "VAT")
    price = _cac(el, "Price")
    if ln.unit_price is None:
        findings.append(Finding("ibr-026", "fatal", "precheck", f"Line {idx}: unit price is missing.", location=loc))
        _amt(price, "PriceAmount", Decimal("0"), cur)
    else:
        _amt(price, "PriceAmount", ln.unit_price, cur)
    _cbc(price, "BaseQuantity", "1", unitCode=unit)
    gross = ln.gross_price if ln.gross_price is not None else ln.unit_price
    if gross is not None:
        if ln.unit_price is not None and gross < ln.unit_price:
            gross = ln.unit_price  # a "list price" below the charged price is not a discount
        ac = _cac(price, "AllowanceCharge")
        _cbc(ac, "ChargeIndicator", "false")
        _amt(ac, "Amount", (gross - (ln.unit_price if ln.unit_price is not None else gross)), cur)
        _amt(ac, "BaseAmount", gross, cur)
    ext = _cac(el, "ItemPriceExtension")
    total = ln.computed_total()
    _amt(ext, "Amount", q2(total) if total is not None else Decimal("0.00"), cur)
    vat = ln.computed_vat()
    _amt(_cac(ext, "TaxTotal"), "TaxAmount", q2(vat) if vat is not None else Decimal("0.00"), cur)
