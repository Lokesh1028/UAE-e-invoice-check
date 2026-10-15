import io, json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
PRIV = Path(__file__).parent / "private_data"

CSV = """Invoice No,Doc Type,Invoice Date,Due Date,Customer Name,Customer TRN,Customer TIN,Customer Address,Customer City,Customer Emirate,Customer Country,Currency,Payment Method,Line,Description,Qty,Unit,Unit Price,VAT Category,VAT %,Line Value,VAT Amount,Line Total
INV-1,INV,2027-07-01,2027-07-31,Example Trading LLC,100123456700003,1001234567,Office 12,Dubai,DXB,AE,AED,Bank transfer,1,Consulting,10,HUR,500,S,5,5000,250,5250
INV-1,,,,,,,,,,,,,2,Travel,1,job,300,S,5,300,15,315
INV-2,INV,01/07/2027,,Another Co,,,,Sharjah,SHJ,AE,AED,,1,Widgets,5,pcs,20,S,5,100,5,105
"""


def test_csv_readiness_end_to_end():
    r = client.post("/api/readiness", files={"file": ("sales.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["documents"] == 2
    assert d["source"]["mapping"]["inv_number"] == "Invoice No"
    ids = {i["rule_id"] for i in d["issues"]}
    # INV-2 has no TIN, no due date, no payment method
    assert "ibr-080" in ids and "ibr-127-ae" in ids
    titles = [i["title"] for i in d["issues"]]
    assert all(t for t in titles)


def test_mapping_override_and_inspect():
    r = client.post("/api/inspect", files={"file": ("sales.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200
    inv = [s for s in r.json()["sheets"] if s["role"] == "invoices"][0]
    assert inv["mapping"]["qty"] == "Qty"
    r = client.post("/api/readiness", files={"file": ("sales.csv", CSV.encode(), "text/csv")}, data={"mapping": json.dumps({"qty": ""})})
    assert r.status_code == 200
    assert any(i["rule_id"] == "ibr-022" for i in r.json()["issues"])


def test_bad_inputs():
    assert client.post("/api/readiness", files={"file": ("x.csv", b"", "text/csv")}).status_code == 400
    r = client.post("/api/readiness", files={"file": ("x.csv", b"a,b,c\n1,2,3\n", "text/csv")})
    assert r.status_code == 422
    r = client.post("/api/readiness", files={"file": ("x.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    assert r.status_code == 422
    r = client.post("/api/readiness", files={"file": ("x.csv", b"x" * (9 * 1024 * 1024), "text/csv")})
    assert r.status_code == 413


def test_xml_validate_and_report_pdf():
    xml = (Path(__file__).parent / "fixtures" / "invoice" / "Standard_tax_invoice.xml").read_bytes()
    r = client.post("/api/validate-xml", content=xml, headers={"Content-Type": "application/xml"})
    assert r.status_code == 200 and r.json()["valid"] is True
    r = client.post("/api/readiness", files={"file": ("inv.xml", xml, "application/xml")})
    assert r.status_code == 200 and r.json()["summary"]["documents_ready"] == 1
    rep = r.json()
    r = client.post("/api/report.pdf", json=rep)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_lookup_validation():
    r = client.get("/api/lookup/12")
    assert r.status_code == 200 and r.json()["verdict"] == "invalid"


def test_health_and_static():
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/").status_code == 200
    assert client.get("/api/template.csv").status_code == 200
    assert client.get("/api/rules").json()["count"] >= 300


@pytest.mark.skipif(not PRIV.exists() or not list(PRIV.glob("*.xlsx")), reason="private client workbooks not present")
@pytest.mark.parametrize("path", sorted(PRIV.glob("*.xlsx")))
def test_private_workbooks(path):
    r = client.post("/api/readiness", files={"file": (path.name, path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["documents"] >= 30
    assert "entities" in d["source"]["masters_used"] and "customers" in d["source"]["masters_used"]
    assert d["issues"][0]["title"]


def test_rate_limit_ignores_forged_forwarded_for():
    from app import main as m
    m._buckets.clear()
    codes = []
    for i in range(40):
        r = client.get("/api/lookup/12", headers={"X-Forwarded-For": f"10.0.{i}.1, 203.0.113.7"})
        codes.append(r.status_code)
    assert 429 in codes  # all requests come from 203.0.113.7 regardless of the forged first entry
    assert client.get("/health").json()["ok"] is True
