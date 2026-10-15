"""
Server-rendered pages and crawler files: content pages, the 303-rule library,
sitemap.xml, robots.txt, llms.txt, llms-full.txt, IndexNow key, icons.

PUBLIC_BASE_URL is the canonical origin (no trailing slash). All canonical links,
the sitemap and llms.txt use it, so moving to a custom domain is one env change.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app import content
from app.engine import rules as rules_mod

BASE = os.environ.get("PUBLIC_BASE_URL", "https://uaeinvoicecheck.web.app").rstrip("/")
BRAND = os.environ.get("BRAND_NAME", "UAE Invoice Check")
ASSET_V = os.environ.get("APP_VERSION", "0.2.0")
BUILD_DATE = os.environ.get("BUILD_DATE", date.today().isoformat())
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "7c1e9a4f2b8d4e6fa3c5b7d9e1f20468")
GOOGLE_VERIFY = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
# Search Console "HTML file" method: comma-separated file names such as google7b55f293e02f9a93.html
GOOGLE_VERIFY_FILES = [f.strip() for f in os.environ.get("GOOGLE_VERIFICATION_FILES", "").split(",")
                       if re.fullmatch(r"google[0-9a-f]{16}\.html", f.strip())]
BING_VERIFY = os.environ.get("BING_SITE_VERIFICATION", "")
STATIC = Path(__file__).resolve().parent / "static"
HTML_CACHE = "private, max-age=300"   # browsers cache 5 min; the CDN does not (so visits reach the server)
CRAWLER_CACHE = "no-cache"            # sitemap/robots/llms: every crawler fetch reaches the server and is logged

router = APIRouter()
e = html.escape

NAV = [("/", "Readiness check")] + [(p, d["nav"]) for p, d in content.PAGES.items() if d["nav"]] + [("/rules", "Rule library")]


def head_tags(title: str, description: str, path: str, jsonld: list | None = None, og_type: str = "website") -> str:
    url = BASE + path
    tags = [
        f'<title>{e(title)}</title>',
        f'<meta name="description" content="{e(description)}">',
        f'<link rel="canonical" href="{e(url)}">',
        '<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">',
        f'<meta property="og:site_name" content="{e(BRAND)}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{e(url)}">',
        f'<meta property="og:image" content="{BASE}/og.png">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        '<meta property="og:locale" content="en_AE">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(description)}">',
        f'<meta name="twitter:image" content="{BASE}/og.png">',
        '<link rel="icon" href="/favicon.ico" sizes="32x32">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        f'<link rel="alternate" type="text/plain" title="LLM summary" href="{BASE}/llms.txt">',
        '<meta name="theme-color" content="#10243E">',
    ]
    if GOOGLE_VERIFY:
        tags.append(f'<meta name="google-site-verification" content="{e(GOOGLE_VERIFY)}">')
    if BING_VERIFY:
        tags.append(f'<meta name="msvalidate.01" content="{e(BING_VERIFY)}">')
    for block in jsonld or []:
        tags.append('<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    return "\n".join(tags)


def site_jsonld() -> list:
    return [
        {"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": BASE + "/",
         "description": "Free UAE e-invoicing readiness check and PINT AE validator."},
        {"@context": "https://schema.org", "@type": "WebApplication", "name": BRAND, "url": BASE + "/",
         "applicationCategory": "BusinessApplication", "operatingSystem": "Web browser", "inLanguage": "en",
         "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "AED"},
         "description": "Upload an invoice export (Excel, CSV, PDF or XML) and see which UAE e-invoicing (PINT AE 1.0.2) rules it fails, in plain language.",
         "featureList": ["UAE e-invoicing readiness check from Excel/CSV/PDF", "PINT AE XML validator (UBL 2.1 + Schematron)",
                         "Peppol TIN lookup for UAE businesses", "303 PINT AE rules explained", "PDF readiness report"],
         "audience": {"@type": "BusinessAudience", "audienceType": "UAE businesses, accountants and tax agents"}},
    ]


def faq_jsonld() -> dict:
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in content.FAQ]}


def breadcrumb(items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": BASE + p} for i, (p, n) in enumerate(items)]}


def layout(title: str, description: str, path: str, h1: str, body: str, jsonld: list | None = None) -> str:
    nav = "".join(f'<a href="{p}"{" aria-current=page" if p == path else ""}>{e(n)}</a>' for p, n in NAV)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head_tags(title, description, path, jsonld, og_type="article" if path != "/" else "website")}
<link rel="stylesheet" href="/static/styles.css?v={ASSET_V}">
</head>
<body>
<header class="top"><div class="wrap row">
<a class="brand" href="/"><span class="logo">✓</span> {e(BRAND)}</a>
<nav>{nav}</nav>
</div></header>
<main class="wrap article">
<h1>{e(h1)}</h1>
{body}
<section class="card cta-inline">
<h2>Check your own invoices</h2>
<p>Upload an Excel, CSV, PDF or XML export and see which UAE e-invoicing rules your invoices fail, in plain language. Free, no sign-up, files never stored.</p>
<p><a class="btn primary" href="/">Run the free readiness check</a></p>
</section>
</main>
{footer()}
<script src="/static/t.js?v={ASSET_V}" defer></script>
</body>
</html>"""


def footer() -> str:
    links = " · ".join(f'<a href="{p}">{e(n)}</a>' for p, n in NAV[1:])
    return f"""<footer class="wrap foot">
<p>{links} · <a href="/privacy">Privacy</a> · <a href="/llms.txt">llms.txt</a></p>
<p>Rule set: PINT AE Billing 1.0.2 (OpenPeppol / UAE Peppol Authority) · UBL 2.1 (OASIS) · Deadlines per UAE Ministry of Finance, Ministerial Decisions 243/244 of 2025 as amended · Penalties per Cabinet Decision 106 of 2025. Independent tool, not affiliated with the Ministry of Finance, the Federal Tax Authority or OpenPeppol. Not tax advice.</p>
</footer>"""


def _html(body: str) -> HTMLResponse:
    return HTMLResponse(body, headers={"Cache-Control": HTML_CACHE})


# ------------------------------------------------------------------ home page
@lru_cache(maxsize=1)
def home_html() -> str:
    raw = (STATIC / "index.html").read_text(encoding="utf-8")
    title = f"{BRAND} — Free UAE E-Invoicing Readiness Check & PINT AE Validator"
    desc = ("Free UAE e-invoicing checker: upload Excel, CSV, PDF or XML invoices and see which PINT AE rules they fail, in plain language. "
            "Deadlines 1 Jan 2027 and 1 Jul 2027. No sign-up.")
    jsonld = site_jsonld() + [faq_jsonld()]
    faq_html = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in content.FAQ)
    nav = "".join(f'<a href="{p}">{e(n)}</a>' for p, n in NAV[1:])
    out = (raw.replace("<!--HEAD-->", head_tags(title, desc, "/", jsonld))
              .replace("<!--BRAND-->", e(BRAND))
              .replace("<!--NAV-->", nav)
              .replace("<!--FAQ-->", faq_html)
              .replace("<!--FOOTER-->", footer())
              .replace("{{V}}", ASSET_V))
    return out


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
def home():
    return _html(home_html())


# ------------------------------------------------------------------ content pages
def _make_page_route(path: str, page: dict):
    def view():
        crumbs = breadcrumb([("/", BRAND), (path, page["h1"])])
        extra = [faq_jsonld()] if path == "/uae-e-invoicing-guide" else []
        art = {"@context": "https://schema.org", "@type": "Article", "headline": page["h1"], "description": page["description"],
               "dateModified": BUILD_DATE, "inLanguage": "en", "mainEntityOfPage": BASE + path,
               "publisher": {"@type": "Organization", "name": BRAND, "url": BASE + "/"}}
        return _html(layout(page["title"], page["description"], path, page["h1"], page["body"], [crumbs, art] + extra))
    return view


for _path, _page in content.PAGES.items():
    router.add_api_route(_path, _make_page_route(_path, _page), methods=["GET"], include_in_schema=False, response_class=HTMLResponse)


# ------------------------------------------------------------------ rule library
@lru_cache(maxsize=1)
def _rules() -> list[dict]:
    return rules_mod.all_rules()


def _rule_by_id() -> dict[str, dict]:
    return {r["rule_id"].lower(): r for r in _rules()}


@router.get("/rules", include_in_schema=False, response_class=HTMLResponse)
def rules_index():
    groups = {"ae": [], "shared": []}
    for r in _rules():
        groups.setdefault(r["layer"], []).append(r)
    def ul(items):
        return "<ul class='rules'>" + "".join(f'<li><a href="/rules/{e(r["rule_id"].lower())}"><code>{e(r["rule_id"])}</code></a> {e(r["title"])}</li>' for r in items) + "</ul>"
    body = (f"<p class='lede'>Every validation rule in the UAE e-invoicing specification (PINT AE Billing 1.0.2), with what it means, the field it checks and how to fix a failure. "
            f"{len(_rules())} rules: the UAE-specific layer and the shared international PINT layer.</p>"
            f"<h2>UAE-specific rules ({len(groups.get('ae', []))})</h2>{ul(groups.get('ae', []))}"
            f"<h2>Shared PINT rules ({len(groups.get('shared', []))})</h2>{ul(groups.get('shared', []))}")
    title = "PINT AE Rules Explained — All 303 UAE E-Invoicing Validation Rules and Fixes"
    desc = "Plain-language explanation of every PINT AE 1.0.2 validation rule (ibr-xxx-ae, aligned-ibrp, ibr-co, ibr-cl) used for UAE e-invoices, with the fix for each error."
    return _html(layout(title, desc, "/rules", "PINT AE rule library", body, [breadcrumb([("/", BRAND), ("/rules", "Rule library")])]))


@router.get("/rules/{rule_id}", include_in_schema=False, response_class=HTMLResponse)
def rule_page(rule_id: str):
    r = _rule_by_id().get(rule_id.lower())
    if not r:
        raise HTTPException(404, "Unknown rule")
    rid = r["rule_id"]
    sev = "Blocking (fatal)" if r["severity"] == "fatal" else "Warning"
    related = [x for x in _rules() if x["rule_id"] != rid and x.get("field") and x.get("field") == r.get("field")][:6]
    rel_html = ("<h2>Related rules</h2><ul class='rules'>" + "".join(
        f'<li><a href="/rules/{e(x["rule_id"].lower())}"><code>{e(x["rule_id"])}</code></a> {e(x["title"])}</li>' for x in related) + "</ul>") if related else ""
    body = f"""
<p class="lede">{e(r['plain'])}</p>
<table class="kv">
<tr><th>Rule ID</th><td><code>{e(rid)}</code></td></tr>
<tr><th>Layer</th><td>{e(r['layer_label'])}</td></tr>
<tr><th>Severity</th><td>{sev}</td></tr>
{f"<tr><th>Field to check</th><td>{e(r['field'])}</td></tr>" if r.get('field') else ''}
</table>
{f"<h2>How to fix it</h2><p>{e(r['fix'])}</p>" if r.get('fix') else ''}
<h2>Official rule text</h2>
<blockquote>{e(r['official'])}</blockquote>
<p class="meta">From the PINT AE Billing 1.0.2 Schematron published by OpenPeppol for the UAE Peppol Authority. If this rule fails on your invoice, an Accredited Service Provider will reject the document until it is fixed.</p>
{rel_html}
<p><a href="/rules">All rules</a></p>"""
    title = f"{rid}: {r['title']} | UAE e-invoicing (PINT AE) rule"
    if len(title) > 110:
        title = f"{rid}: {r['title'][:70].rstrip()}… | PINT AE rule"
    desc = f"{rid} explained: {r['plain']}"[:300]
    jl = [breadcrumb([("/", BRAND), ("/rules", "Rule library"), (f"/rules/{rid.lower()}", rid)]),
          {"@context": "https://schema.org", "@type": "TechArticle", "headline": f"{rid}: {r['title']}", "description": desc,
           "dateModified": BUILD_DATE, "inLanguage": "en", "mainEntityOfPage": f"{BASE}/rules/{rid.lower()}",
           "about": "UAE e-invoicing PINT AE validation rule"}]
    return _html(layout(title, desc, f"/rules/{rid.lower()}", f"{rid}: {r['title']}", body, jl))


# ------------------------------------------------------------------ crawler files
def all_urls() -> list[tuple[str, str]]:
    urls = [("/", "1.0")] + [(p, d["priority"]) for p, d in content.PAGES.items()] + [("/rules", "0.7")]
    urls += [(f"/rules/{r['rule_id'].lower()}", "0.5") for r in _rules()]
    return urls


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    items = "".join(f"<url><loc>{e(BASE + p)}</loc><lastmod>{BUILD_DATE}</lastmod><priority>{pr}</priority></url>" for p, pr in all_urls())
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return Response(xml, media_type="application/xml", headers={"Cache-Control": CRAWLER_CACHE})


AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai", "PerplexityBot",
             "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Amazonbot", "meta-externalagent", "DuckAssistBot", "cohere-ai"]


@router.get("/robots.txt", include_in_schema=False)
def robots():
    lines = ["# Search engines and AI assistants are welcome to crawl and cite this site.", "User-agent: *", "Allow: /", "Disallow: /api/", ""]
    for a in AI_AGENTS:
        lines += [f"User-agent: {a}", "Allow: /", "Disallow: /api/", ""]
    lines += [f"Sitemap: {BASE}/sitemap.xml", f"# LLM summary: {BASE}/llms.txt"]
    return PlainTextResponse("\n".join(lines) + "\n", headers={"Cache-Control": CRAWLER_CACHE})


def _text(html_str: str) -> str:
    s = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", html_str, flags=re.S)
    s = re.sub(r"<li>(.*?)</li>", r"- \1\n", s, flags=re.S)
    s = re.sub(r"</tr>", "\n", s)
    s = re.sub(r"</t[hd]>", " | ", s)
    s = re.sub(r"<a [^>]*href=\"(/[^\"]*)\"[^>]*>(.*?)</a>", lambda m: f"{m.group(2)} ({BASE}{m.group(1)})", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


@router.get("/llms.txt", include_in_schema=False)
def llms_txt():
    pages = "\n".join(f"- [{d['h1']}]({BASE}{p}): {d['description']}" for p, d in content.PAGES.items() if d["nav"])
    txt = f"""# {BRAND}

> Free, independent web tool for UAE e-invoicing readiness. Upload an invoice export (Excel/CSV/PDF) or a PINT AE XML and get every failure against the official UAE rule set (PINT AE Billing 1.0.2 + UBL 2.1, 303 rules) explained in plain language. Also: Peppol TIN lookup and a library explaining every PINT AE rule.

Key facts (reviewed {content.REVIEWED}): UAE e-invoicing covers B2B and B2G transactions regardless of VAT registration. Businesses with revenue of AED 50 million or more appoint an Accredited Service Provider (ASP) by 30 October 2026 and go live 1 January 2027; businesses below AED 50 million appoint an ASP by 31 March 2027 and go live 1 July 2027; government entities go live 1 October 2027. Penalties (Cabinet Decision 106 of 2025): AED 5,000 per month for late implementation or ASP appointment, AED 100 per e-invoice not issued on time. Format: PINT AE (UBL 2.1 XML), exchanged on the Peppol five-corner model; participant ID scheme 0235 + 10-digit TIN.

## Tools
- [Readiness check]({BASE}/): upload Excel, CSV, PDF or XML invoices; returns a plain-language list of PINT AE rule failures and a PDF report. Free, no sign-up, files not stored.
- [PINT AE XML validator]({BASE}/pint-ae-validator): UBL 2.1 XSD + shared PINT + UAE-specific Schematron.
- [Peppol TIN lookup]({BASE}/peppol-tin-lookup): is a UAE business reachable on the e-invoicing network?

## Guides
{pages}

## Reference
- [PINT AE rule library]({BASE}/rules): all {len(_rules())} rules with plain explanations and fixes, one page per rule (e.g. {BASE}/rules/ibr-132-ae).
- [Full text for LLMs]({BASE}/llms-full.txt)
- [HTTP API (OpenAPI)]({BASE}/api/docs)

## Optional
- [Privacy]({BASE}/privacy): uploaded files are processed in memory and never stored.
"""
    return PlainTextResponse(txt, headers={"Cache-Control": CRAWLER_CACHE})


@router.get("/llms-full.txt", include_in_schema=False)
def llms_full():
    parts = [f"# {BRAND} — full reference (reviewed {content.REVIEWED})\n"]
    parts.append("## Frequently asked questions\n" + "\n\n".join(f"Q: {q}\nA: {a}" for q, a in content.FAQ))
    for p, d in content.PAGES.items():
        if not d["nav"]:
            continue
        parts.append(f"\n\n# {d['h1']}\nURL: {BASE}{p}\n\n{_text(d['body'])}")
    parts.append("\n\n# PINT AE rules (id — title — explanation — fix)\n")
    for r in _rules():
        parts.append(f"- {r['rule_id']} — {r['title']} — {r['plain']}" + (f" Fix: {r['fix']}" if r.get("fix") else ""))
    return PlainTextResponse("\n".join(parts) + "\n", headers={"Cache-Control": CRAWLER_CACHE})


@router.get(f"/{INDEXNOW_KEY}.txt", include_in_schema=False)
def indexnow_key():
    return PlainTextResponse(INDEXNOW_KEY)


def _static_file(name: str, media: str, max_age: int = 86400) -> Response:
    p = STATIC / name
    if not p.exists():
        raise HTTPException(404)
    return Response(p.read_bytes(), media_type=media, headers={"Cache-Control": f"public, max-age={max_age}"})


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return _static_file("favicon.ico", "image/x-icon")


@router.get("/apple-touch-icon.png", include_in_schema=False)
def apple_icon():
    return _static_file("apple-touch-icon.png", "image/png")


@router.get("/og.png", include_in_schema=False)
def og_image():
    return _static_file("og.png", "image/png")


def _verification_file_route(name: str):
    def view():
        # Google compares the body byte-for-byte: "google-site-verification: <file name>"
        return Response(f"google-site-verification: {name}", media_type="text/html", headers={"Cache-Control": "no-cache"})
    return view


for _name in GOOGLE_VERIFY_FILES:
    router.add_api_route(f"/{_name}", _verification_file_route(_name), methods=["GET", "HEAD"], include_in_schema=False)
