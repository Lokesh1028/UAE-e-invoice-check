"""
HTTP API. Stateless: uploads are processed in memory and never stored.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.engine import rules as rules_mod
from app.engine.model import Invoice, Party
from app.engine.ubl import build, merge_findings
from app.engine.validator import Finding, ValidationInputError, Validator
from app.importers.pdfinvoice import PdfImportError, import_pdf
from app.importers.tabular import ImportError_, import_file, load_sheets
from app.lookup.peppol import lookup_tin
from app.report.pdf import build_report_pdf
from app.leads import store_lead

log = logging.getLogger("api")
router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
MAX_DOCS_DETAILED = int(os.environ.get("MAX_DOCS_DETAILED", "500"))
MAX_DOCS_TOTAL = int(os.environ.get("MAX_DOCS_TOTAL", "5000"))
HEAVY_CONCURRENCY = int(os.environ.get("HEAVY_CONCURRENCY", "2"))  # SaxonC serialises per process; 2 keeps a short queue
HEAVY_TIMEOUT_S = float(os.environ.get("HEAVY_TIMEOUT_S", "60"))
HEAVY_QUEUE_WAIT_S = float(os.environ.get("HEAVY_QUEUE_WAIT_S", "10"))
_heavy = asyncio.Semaphore(HEAVY_CONCURRENCY)


async def _run_heavy(fn, *args):
    """Run CPU work in the threadpool with a concurrency cap and a hard timeout."""
    try:
        await asyncio.wait_for(_heavy.acquire(), timeout=HEAVY_QUEUE_WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(503, "The service is busy right now. Please retry in a few seconds.", headers={"Retry-After": "3"})
    try:
        return await asyncio.wait_for(run_in_threadpool(fn, *args), timeout=HEAVY_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Processing took too long. Try a smaller file (fewer rows or sheets).")
    finally:
        _heavy.release()


async def _read_upload(file: UploadFile) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 256)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"File larger than {MAX_UPLOAD_BYTES // (1024*1024)} MB. Export fewer months or split the file.")
        chunks.append(chunk)
    return b"".join(chunks)


def _finding_dict(f: Finding) -> dict:
    e = rules_mod.explain(f.rule_id, f.message, f.layer)
    return {"rule_id": f.rule_id, "severity": f.severity, "layer": f.layer, "layer_label": e["layer_label"],
            "title": e["title"], "plain": e["plain"], "fix": e["fix"], "field": e["field"],
            "message": f.message, "location": f.location}


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, date):
        return o.isoformat()
    return str(o)


# ------------------------------------------------------------------ core work
def _check_documents(invoices: list[Invoice], include_xml: bool = False) -> tuple[list[dict], dict, list[dict], Optional[str]]:
    v = Validator.get()
    docs_out: list[dict] = []
    agg: dict[str, dict] = {}
    fatal_total = warn_total = ready = 0
    sample_xml = None
    for idx, inv in enumerate(invoices[:MAX_DOCS_TOTAL]):
        gen = build(inv)
        res = v.validate_bytes(gen.xml)
        allf = merge_findings(gen.findings, res.findings)
        fatal = [f for f in allf if f.severity == "fatal"]
        warns = [f for f in allf if f.severity != "fatal"]
        fatal_total += len(fatal)
        warn_total += len(warns)
        if not fatal:
            ready += 1
        seen_rules = set()
        for f in allf:
            a = agg.setdefault(f.rule_id, {"count": 0, "docs": set(), "example": None, "severity": f.severity, "layer": f.layer, "message": f.message})
            a["count"] += 1
            a["docs"].add(idx)
            if a["example"] is None:
                a["example"] = f"{inv.number or 'document ' + str(idx + 1)}: {f.message[:160]}"
            seen_rules.add(f.rule_id)
        if idx < MAX_DOCS_DETAILED:
            docs_out.append({
                "index": idx, "number": inv.number, "date": inv.issue_date.isoformat() if inv.issue_date else None,
                "doc_type": inv.doc_type, "currency": inv.currency,
                "seller": inv.seller.name, "buyer": inv.buyer.name,
                "fatal": len(fatal), "warnings": len(warns),
                "findings": [_finding_dict(f) for f in (fatal + warns)[:60]],
            })
        if include_xml and sample_xml is None:
            sample_xml = gen.xml.decode("utf-8")
    issues = []
    for rid, a in agg.items():
        e = rules_mod.explain(rid, a["message"], a["layer"])
        issues.append({**{k: e[k] for k in ("rule_id", "title", "plain", "fix", "field", "layer", "layer_label")},
                       "severity": a["severity"], "count": a["count"], "documents": len(a["docs"]), "example": a["example"]})
    issues.sort(key=lambda i: (i["severity"] != "fatal", -i["documents"], -i["count"]))
    summary = {"documents": min(len(invoices), MAX_DOCS_TOTAL), "documents_ready": ready, "fatal_total": fatal_total,
               "warning_total": warn_total, "distinct_rules": len(agg), "truncated": len(invoices) > MAX_DOCS_TOTAL}
    return docs_out, summary, issues, sample_xml


def _readiness_sync(data: bytes, filename: str, mapping: Optional[dict], sheet: Optional[str], include_xml: bool,
                    seller: Optional[dict] = None) -> dict:
    t0 = time.perf_counter()
    fn = (filename or "upload").lower()
    source: dict[str, Any] = {"filename": filename}
    if fn.endswith(".pdf") or data[:5] == b"%PDF-":
        inv, info = import_pdf(data, filename)
        invoices = [inv]
        source.update({"kind": "pdf", "pdf": info})
    elif fn.endswith(".xml") or data.lstrip()[:1] == b"<":
        v = Validator.get()
        res = v.validate_bytes(data)
        allf = res.findings
        fatal = [f for f in allf if f.severity == "fatal"]
        docs = [{"index": 0, "number": "(uploaded XML)", "date": None, "doc_type": res.doc_type, "currency": None,
                 "seller": None, "buyer": None, "fatal": len(fatal), "warnings": len(allf) - len(fatal),
                 "findings": [_finding_dict(f) for f in allf[:100]]}]
        agg = collections.Counter(f.rule_id for f in allf)
        issues = []
        for rid, n in agg.most_common():
            f = next(x for x in allf if x.rule_id == rid)
            e = rules_mod.explain(rid, f.message, f.layer)
            issues.append({**{k: e[k] for k in ("rule_id", "title", "plain", "fix", "field", "layer", "layer_label")},
                           "severity": f.severity, "count": n, "documents": 1, "example": f.message[:160]})
        return {"source": {**source, "kind": "xml", "doc_type": res.doc_type, "well_formed": res.well_formed, "xsd_valid": res.xsd_valid},
                "summary": {"documents": 1, "documents_ready": int(not fatal), "fatal_total": len(fatal), "warning_total": len(allf) - len(fatal),
                            "distinct_rules": len(agg), "processing_ms": round((time.perf_counter() - t0) * 1000)},
                "issues": issues, "documents": docs}
    else:
        seller_default = None
        if seller and any(seller.values()):
            seller_default = Party(**{k: v for k, v in seller.items() if k in Party.model_fields and v})
        invoices, rep = import_file(data, filename, mapping, sheet, seller_default)
        if seller_default is not None:
            # a profile typed in the form fills gaps in (or replaces an absent) seller from the file
            for inv in invoices:
                for k, val in seller_default.model_dump(exclude_none=True).items():
                    if getattr(inv.seller, k, None) in (None, "") and k != "licence_type":
                        setattr(inv.seller, k, val)
            source["seller_profile_used"] = True
        source.update({"kind": "xlsx" if (fn.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK") else "csv",
                       "invoice_sheet": rep.invoice_sheet, "sheets": rep.sheets, "mapping": rep.mapping,
                       "unmapped_headers": rep.unmapped_headers, "masters_used": rep.masters_used,
                       "warnings": rep.warnings, "rows_read": rep.rows_read})
    docs, summary, issues, sample_xml = _check_documents(invoices, include_xml)
    summary["processing_ms"] = round((time.perf_counter() - t0) * 1000)
    out = {"source": source, "summary": summary, "issues": issues, "documents": docs}
    if sample_xml:
        out["sample_xml"] = sample_xml
    return out


# ------------------------------------------------------------------ routes
@router.post("/readiness")
async def readiness(request: Request, file: UploadFile = File(...), mapping: Optional[str] = Form(None),
                    sheet: Optional[str] = Form(None), include_xml: bool = Form(False),
                    seller_name: Optional[str] = Form(None), seller_tin: Optional[str] = Form(None), seller_trn: Optional[str] = Form(None),
                    seller_licence_no: Optional[str] = Form(None), seller_licence_authority: Optional[str] = Form(None),
                    seller_street: Optional[str] = Form(None), seller_city: Optional[str] = Form(None), seller_emirate: Optional[str] = Form(None),
                    seller_iban: Optional[str] = Form(None)):
    seller = {"name": seller_name, "tin": seller_tin, "trn": seller_trn, "licence_no": seller_licence_no, "licence_authority": seller_licence_authority,
              "street": seller_street, "city": seller_city, "emirate": seller_emirate, "country": "AE" if (seller_emirate or seller_city) else None}
    seller = {k: (v.strip()[:200] if isinstance(v, str) else v) for k, v in seller.items()}
    data = await _read_upload(file)
    if not data:
        raise HTTPException(400, "Empty file.")
    mapping_dict = None
    if mapping:
        try:
            mapping_dict = json.loads(mapping)
            if not isinstance(mapping_dict, dict) or len(mapping_dict) > 80:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "mapping must be a JSON object of field -> column header.")
    try:
        result = await _run_heavy(_readiness_sync, data, file.filename or "upload", mapping_dict, sheet, include_xml, seller)
    except (ImportError_, PdfImportError, ValidationInputError) as e:
        raise HTTPException(422, str(e))
    except HTTPException:
        raise
    except Exception as e:  # never leak stack traces; log with a reference id
        ref = uuid.uuid4().hex[:8]
        log.exception("readiness failed ref=%s file=%s", ref, file.filename)
        raise HTTPException(500, f"We could not process this file (ref {ref}). If it is an Excel export, try saving the invoice sheet as CSV.")
    return JSONResponse(json.loads(json.dumps(result, default=_json_default)))


@router.post("/inspect")
async def inspect(file: UploadFile = File(...)):
    """Sheets, detected roles and proposed column mapping, so the UI can offer corrections before running."""
    data = await _read_upload(file)
    try:
        sheets = await _run_heavy(load_sheets, data, file.filename or "upload")
    except ImportError_ as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(422, "Could not read this file as CSV or XLSX.")
    from app.importers.tabular import SYN
    return {"fields": list(SYN.keys()),
            "sheets": [{"name": s.name, "role": s.role, "header_row": s.header_row, "rows": len(s.rows), "headers": s.headers,
                        "mapping": {k: s.headers[i] for k, i in s.mapping.items()} if s.role == "invoices" else {}} for s in sheets]}


@router.post("/validate-xml")
async def validate_xml(request: Request, file: Optional[UploadFile] = File(None)):
    if file is not None:
        data = await _read_upload(file)
    else:
        data = await request.body()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "XML too large.")
    if not data.strip():
        raise HTTPException(400, "No XML received.")
    try:
        res = await _run_heavy(Validator.get().validate_bytes, data)
    except ValidationInputError as e:
        raise HTTPException(422, str(e))
    fatal = [f for f in res.findings if f.severity == "fatal"]
    return {"doc_type": res.doc_type, "well_formed": res.well_formed, "xsd_valid": res.xsd_valid,
            "valid": res.is_valid, "fatal": len(fatal), "warnings": len(res.findings) - len(fatal),
            "timing_ms": round(res.timing_ms, 1), "rule_set": "PINT AE Billing 1.0.2 (2026-01-28) + UBL 2.1",
            "findings": [_finding_dict(f) for f in res.findings[:300]]}


@router.get("/lookup/{tin}")
async def lookup(tin: str):
    if len(tin) > 20:
        raise HTTPException(400, "TIN too long.")
    res = await run_in_threadpool(lookup_tin, tin)
    d = res.to_dict()
    if not d["valid_format"]:
        d["verdict"] = "invalid"
        d["explanation"] = "That is not a UAE TIN. A TIN is 10 digits starting with 1 (your 15-digit number is the TRN)."
    elif d["sml_registered"]:
        env = "the live" if d["sml_environment"] == "production" else "the TEST"
        d["verdict"] = "reachable" if d["sml_environment"] == "production" else "test-only"
        d["explanation"] = f"This TIN is registered on {env} e-invoicing network" + (f" via {d['smp_host']}" if d["smp_host"] and d["smp_host"] != "found" else "") + ". E-invoices addressed to it can be delivered."
    elif d["sml_registered"] is False:
        d["verdict"] = "not-found"
        d["explanation"] = "No e-invoicing registration found for this TIN yet. The business (or its provider) has not published it on the network, so an e-invoice cannot be delivered to it today."
    else:
        d["verdict"] = "unknown"
        d["explanation"] = d.get("error") or "Lookup could not be completed."
    return d


@router.post("/report.pdf")
async def report_pdf(request: Request):
    body = await request.body()
    if len(body) > 6 * 1024 * 1024:
        raise HTTPException(413, "Report too large.")
    try:
        report = json.loads(body)
        assert isinstance(report, dict) and "summary" in report
    except Exception:
        raise HTTPException(400, "Send the readiness report JSON.")
    pdf = await _run_heavy(build_report_pdf, report)
    name = "einvoice-readiness-report.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/lead")
async def lead(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body expected.")
    email = (body.get("email") or "").strip()[:200]
    whatsapp = (body.get("whatsapp") or "").strip()[:40]
    if not email and not whatsapp:
        raise HTTPException(400, "Provide an email or WhatsApp number.")
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise HTTPException(400, "That email address does not look right.")
    rec = {
        "id": uuid.uuid4().hex, "ts": time.time(), "email": email, "whatsapp": whatsapp,
        "company": (body.get("company") or "").strip()[:200], "role": (body.get("role") or "").strip()[:100],
        "summary": body.get("summary") if isinstance(body.get("summary"), dict) else {},
        "source": (body.get("source") or "")[:100], "ip": request.client.host if request.client else None,
        "ua": request.headers.get("user-agent", "")[:200],
    }
    await run_in_threadpool(store_lead, rec)
    return {"ok": True}


@router.get("/rules")
async def rules_list():
    return {"rule_set": "PINT AE Billing 1.0.2 (2026-01-28)", "count": len(rules_mod.all_rules()), "rules": rules_mod.all_rules()}


@router.get("/template.csv")
async def template_csv():
    cols = ["Invoice No", "Doc Type", "Invoice Date", "Due Date", "Customer Name", "Customer TRN", "Customer TIN", "Customer Address", "Customer City", "Customer Emirate", "Customer Country",
            "Currency", "Payment Method", "Line", "Description", "Qty", "Unit", "Unit Price", "VAT Category", "VAT %", "Line Value", "VAT Amount", "Line Total", "HS Code", "SAC Code", "PO Ref"]
    row = ["INV-2027-0001", "INV", "2027-07-01", "2027-07-31", "Example Trading LLC", "100123456700003", "1001234567", "Office 12, Al Quoz 3", "Dubai", "DXB", "AE",
           "AED", "Bank transfer", "1", "Consulting services June", "10", "HUR", "500", "S", "5", "5000", "250", "5250", "", "998311", "PO-1001"]
    import csv, io
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(cols); w.writerow(row)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="einvoice-readiness-template.csv"'})
