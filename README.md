# UAE e-invoice readiness check

Free, no-login web tool: upload an invoice export (XLSX/CSV, a text PDF invoice, or a PINT AE XML) and get a
plain-language list of everything that would fail the UAE e-invoicing rules.

* **Rule source of truth:** the official OpenPeppol / UAE Peppol Authority **PINT AE Billing 1.0.2** Schematron
  (shipped as pre-compiled XSLT in `app/resources/pint-ae/`) plus the OASIS **UBL 2.1** XSD. 303 rules.
* **Engine:** Python 3.12, lxml (XSD, XML building), SaxonC-HE 13 (runs the official XSLT; the rules use XPath 2
  functions so libxslt cannot run them). ~2 ms per invoice, ~120 MB RSS per worker.
* **Web:** FastAPI + uvicorn workers, vanilla HTML/JS front end, fpdf2 for the PDF report. Stateless: uploads live
  in memory only. Optional lead capture to a JSONL file and/or webhook.

## Layout

```
app/
  main.py            app factory: rate limiting, security headers, static, health
  api.py             /api/readiness, /api/inspect, /api/validate-xml, /api/lookup/{tin}, /api/report.pdf, /api/lead
  engine/
    validator.py     XSD + official Schematron (SaxonC), one instance per process
    model.py         canonical Invoice/Party/Line model + normalisers (units, emirates, dates, amounts)
    ubl.py           canonical model -> PINT AE UBL XML; prechecks for structurally missing data
    rules.py         rule id -> plain language (rules_plain.json overrides, official text fallback)
    codelists.py     UN/ECE units, UNCL4461 payment codes, ISO lists from the official .gc files
  importers/
    tabular.py       CSV/XLSX: header detection, sheet classification, master joins, mapping override
    pdfinvoice.py    best-effort text-PDF extraction
  lookup/peppol.py   SML (DNS-over-HTTPS NAPTR) + Peppol Directory lookup for 0235:<TIN>
  report/pdf.py      readiness report PDF
  static/            index.html, app.js, styles.css, sample-invoice.xml
tests/               pytest: official examples, generator round-trips, importers, API
deploy/              Fly.io (fly.toml at root), Cloud Run, Cloudflare notes
scripts/loadtest.py  burst load test
```

## Run locally

```bash
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pytest
./.venv/bin/uvicorn app.main:app --reload --port 8080     # http://127.0.0.1:8080
```

## Deploy (Fly.io, scale-to-zero)

```bash
brew install flyctl && fly auth signup        # or fly auth login
fly launch --copy-config --no-deploy          # accept the app name in fly.toml or pick one
fly volumes create data --size 1 --region fra # for the leads file (optional)
fly deploy
fly open
```

Then put Cloudflare in front (see `deploy/cloudflare.md`) for CDN caching, bot protection and a second rate limit.
Cloud Run alternative: `deploy/cloudrun.md`.

### Environment

| var | default | meaning |
|---|---|---|
| `WEB_CONCURRENCY` | 2 | uvicorn workers per container (1 per vCPU) |
| `HEAVY_CONCURRENCY` | cpu count | parallel heavy requests per worker before 503 |
| `HEAVY_TIMEOUT_S` | 60 | hard timeout per file |
| `MAX_UPLOAD_BYTES` | 8 MiB | upload cap |
| `RATE_LIMIT_PER_MIN` / `RATE_LIMIT_BURST` | 40 / 15 | per-IP token bucket on POST /api/* and lookups |
| `TRUST_PROXY` | 1 | read client IP from X-Forwarded-For / CF-Connecting-IP |
| `DATA_DIR` | ./data | leads.jsonl location |
| `LEAD_WEBHOOK_URL` | | POST each lead as JSON (Sheets/n8n/Zapier) |
| `LEADS_DISABLED` | | `1` turns the lead endpoint into a no-op |

## How a check works

1. Importer builds canonical `Invoice` objects (rows grouped by invoice number, masters joined by code).
2. `ubl.build()` writes PINT AE XML from exactly the supplied data. Structurally mandatory elements that are
   missing get a placeholder so the XSD passes, and a *precheck* finding with the official rule id is recorded.
3. `Validator` runs UBL 2.1 XSD, then the shared PINT and UAE-specific XSLT rule sets.
4. Findings are merged (prechecks win over the same official id), explained via `rules_plain.json`, aggregated
   into issues sorted by number of documents affected, and returned as JSON. The PDF is rendered from that JSON.

## Updating the rule set

Download the new `resources.zip` from https://docs.peppol.eu/poac/ae/, replace the `.xslt`/`.sch` files under
`app/resources/pint-ae/{invoice,creditnote}/`, regenerate `rules_raw.json` (see git history for the one-off
script), copy the new example files into `tests/fixtures/`, run `pytest`. Bump the version strings in `api.py`
and `index.html`.

## Not in scope (deliberately)

Transmission to an Accredited Service Provider, storage of invoices, user accounts, Arabic UI, scanned-PDF OCR.

## CI

A GitHub Actions workflow is kept at `deploy/github-ci.yml` (runs pytest and a Docker build). To enable it,
move it to `.github/workflows/ci.yml`. Pushing that path needs a token with the `workflow` scope
(`gh auth refresh -s workflow`, or a fine-grained token with Workflows: read and write).
