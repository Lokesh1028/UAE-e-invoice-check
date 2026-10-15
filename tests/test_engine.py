import glob, re
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.model import Invoice, Line, Party, Totals, to_date, to_decimal
from app.engine.ubl import build, merge_findings
from app.engine.validator import Validator
from app.engine import rules

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def v():
    return Validator.get()


@pytest.mark.parametrize("path", sorted(glob.glob(str(FIX / "*" / "*.xml"))))
def test_official_examples_pass(v, path):
    r = v.validate_bytes(Path(path).read_bytes())
    assert r.well_formed and r.xsd_valid
    assert r.fatal_count == 0, [f.rule_id for f in r.findings]


def test_broken_example_is_caught(v):
    data = (FIX / "invoice" / "Standard_invoice_Mandatory_fields.xml").read_bytes()
    broken = re.sub(rb"<cac:PartyTaxScheme>.*?</cac:PartyTaxScheme>", b"", data, count=1, flags=re.S)
    broken = broken.replace(b"<cbc:CountrySubentity>DXB</cbc:CountrySubentity>", b"<cbc:CountrySubentity>Dubai</cbc:CountrySubentity>", 1)
    r = v.validate_bytes(broken)
    ids = {f.rule_id for f in r.findings}
    assert {"ibr-134-ae", "ibr-128-ae"} <= ids


def test_non_xml_and_wrong_root(v):
    assert not v.validate_bytes(b"not xml").well_formed
    r = v.validate_bytes(b"<hello/>")
    assert r.findings[0].rule_id == "xml-root"


def test_too_large_rejected(v):
    from app.engine.validator import ValidationInputError
    with pytest.raises(ValidationInputError):
        v.validate_bytes(b"<a>" + b"x" * (3 * 1024 * 1024) + b"</a>")


def _complete_invoice():
    seller = Party(name="Example Trading LLC", tin="1234567890", trn="100123456700003", licence_no="CN-1234567", licence_authority="Dubai DET", street="Al Quoz 3", city="Dubai", emirate="Dubai", country="UAE")
    buyer = Party(name="Sample Buyer LLC", tin="1987654321", trn="100987654300003", licence_no="CN-7654321", licence_authority="Dubai DET", street="SZR", city="Dubai", emirate="DXB", country="AE")
    return Invoice(number="INV-1", issue_date="2026-10-01", due_date="2026-10-31", seller=seller, buyer=buyer, payment_means_code="bank transfer", iban="AE070331234567890123456",
                   lines=[Line(name="Water", description="Case", quantity=10, unit="ctn", unit_price="36.00", vat_category="S", item_type="G", hs_code="22011000"),
                          Line(name="Delivery", quantity=1, unit="job", unit_price="50", vat_category="S", item_type="S", sac_code="996511")])


def test_generated_complete_invoice_is_valid(v):
    g = build(_complete_invoice())
    r = v.validate_bytes(g.xml)
    assert g.findings == []
    assert r.is_valid, [(f.rule_id, f.message[:80]) for f in r.findings]


def test_generated_credit_note_is_valid(v):
    inv = _complete_invoice()
    inv.doc_type = "creditnote"; inv.number = "CN-1"; inv.original_invoice_number = "INV-1"; inv.credit_reason_code = "DL8.61.1.D"
    g = build(inv)
    r = v.validate_bytes(g.xml)
    assert r.doc_type == "creditnote"
    assert r.is_valid, [(f.rule_id, f.message[:80]) for f in r.findings]


def test_foreign_currency_invoice_is_valid(v):
    inv = _complete_invoice()
    inv.currency = "USD"; inv.exchange_rate = Decimal("3.6725")
    g = build(inv)
    r = v.validate_bytes(g.xml)
    assert r.is_valid, [(f.rule_id, f.message[:80]) for f in r.findings]


def test_incomplete_invoice_reports_prechecks(v):
    inv = Invoice(number="A1", issue_date="2026-10-01", seller=Party(name="X"), buyer=Party(name="Y"), lines=[Line(name="thing", quantity=1, unit_price=100)])
    g = build(inv)
    r = v.validate_bytes(g.xml)
    allf = merge_findings(g.findings, r.findings)
    ids = [f.rule_id for f in allf]
    assert "ibr-081" in ids and "ibr-080" in ids and "ibr-145-ae" in ids
    assert ids.count("ibr-081") == 1  # deduplicated
    assert r.xsd_valid


def test_unit_and_payment_synonyms():
    assert Line(name="x", unit="pcs").unit == "H87"
    assert Line(name="x", unit="ctn").unit == "XCT"
    assert Line(name="x", unit="sqm").unit == "MTK"
    assert Invoice(payment_means_code="Bank Transfer").payment_means_code == "30"
    assert Party(emirate="Abu Dhabi").emirate == "AUH"
    assert Party(trn="100 123 4567 00003").trn == "100123456700003"


def test_date_and_decimal_parsing():
    assert str(to_date("03-Feb-26")) == "2026-02-03"
    assert str(to_date("20260212")) == "2026-02-12"
    assert str(to_date("05/03/2026")) == "2026-03-05"
    assert to_decimal("(1,200.50)") == Decimal("-1200.50")
    assert to_decimal("AED 5,000") == Decimal("5000")


def test_rules_dictionary_covers_all_ids():
    allr = rules.all_rules()
    assert len(allr) >= 300
    e = rules.explain("ibr-132-ae")
    assert "TRN" in e["title"] and e["fix"]
