import json
import re

from fastapi.testclient import TestClient

from app.main import app
from app import analytics

client = TestClient(app)


def test_home_has_seo_tags():
    r = client.get("/")
    assert r.status_code == 200
    h = r.text
    assert "<title>UAE Invoice Check" in h and 'rel="canonical"' in h and 'property="og:image"' in h
    assert '"@type": "FAQPage"' in h and '"@type": "WebApplication"' in h
    assert "<!--" not in h.split("<body>")[0].replace("<!--HEAD-->", "X")  # no leftover placeholders in head
    assert "/static/t.js" in h
    assert r.headers["cache-control"].startswith("private")


def test_content_pages_and_rules():
    for p in ("/uae-e-invoicing-guide", "/uae-e-invoicing-deadlines-penalties", "/uae-tin-vs-trn", "/pint-ae-validator", "/peppol-tin-lookup", "/privacy", "/rules"):
        r = client.get(p)
        assert r.status_code == 200, p
        assert "<h1>" in r.text and 'rel="canonical"' in r.text
    r = client.get("/rules/ibr-132-ae")
    assert r.status_code == 200 and "TRN" in r.text and "BreadcrumbList" in r.text
    assert client.get("/rules/IBR-132-AE").status_code == 200
    assert client.get("/rules/not-a-rule").status_code == 404


def test_crawler_files():
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and sm.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", sm.text)
    assert len(locs) > 300 and any(l.endswith("/rules/ibr-132-ae") for l in locs)
    rb = client.get("/robots.txt").text
    assert "Sitemap:" in rb and "GPTBot" in rb and "Disallow: /api/" in rb
    lt = client.get("/llms.txt").text
    assert lt.startswith("# UAE Invoice Check") and "## Tools" in lt
    full = client.get("/llms-full.txt").text
    assert "ibr-132-ae" in full and "31 March 2027" in full
    assert client.get("/7c1e9a4f2b8d4e6fa3c5b7d9e1f20468.txt").text == "7c1e9a4f2b8d4e6fa3c5b7d9e1f20468"
    for p in ("/favicon.ico", "/og.png", "/apple-touch-icon.png"):
        assert client.get(p).status_code == 200


def test_client_ip_walks_past_proxies():
    class R:
        def __init__(self, xff):
            self.headers = {"x-forwarded-for": xff}
            self.client = None
    assert analytics.client_ip(R("1.2.3.4")) == "1.2.3.4"
    assert analytics.client_ip(R("6.6.6.6, 1.2.3.4")) == "1.2.3.4"                 # forged left entry ignored
    assert analytics.client_ip(R("6.6.6.6, 1.2.3.4, 35.191.1.1")) == "1.2.3.4"      # Google front end skipped
    assert analytics.client_ip(R("1.2.3.4, 104.16.0.1")) == "1.2.3.4"               # Cloudflare skipped
    assert analytics.client_ip(R("1.2.3.4, 151.101.1.1")) == "1.2.3.4"              # Fastly skipped
    assert analytics.client_ip(R("49.43.226.58,66.249.82.98")) == "49.43.226.58"     # Firebase Hosting egress (Google)
    assert analytics.client_ip(R("6.6.6.6, 34.120.0.1")) == "34.120.0.1"            # GCP customer IP is NOT trusted


def test_agent_classification():
    assert analytics.classify_agent("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)") == ("bot", "Googlebot")
    assert analytics.classify_agent("WhatsApp/2.23.20.0") == ("preview", "WhatsApp preview")
    assert analytics.classify_agent("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2)")[1] == "GPTBot"
    assert analytics.classify_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36")[0] == "human"


def test_beacon_and_hit_logging(capsys):
    r = client.post("/api/e", content=json.dumps({"t": "pv", "sid": "abc", "ref": "https://www.google.com/", "sw": 1440, "sh": 900, "tz": "Asia/Dubai", "utm": {"src": "wa"}}),
                    headers={"Content-Type": "text/plain", "User-Agent": "Mozilla/5.0 (iPhone) Safari"})
    assert r.status_code == 204
    client.get("/uae-tin-vs-trn?src=linkedin", headers={"User-Agent": "Mozilla/5.0 Chrome/141", "Referer": "https://www.linkedin.com/"})
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    pv = next(o for o in out if o["event"] == "pv")
    assert pv["sid"] == "abc" and pv["sw"] == 1440 and pv["utm"] == {"src": "wa"}
    hit = next(o for o in out if o["event"] == "hit" and o["path"] == "/uae-tin-vs-trn")
    assert hit["utm"] == {"src": "linkedin"} and "linkedin" in hit["referer"]
    assert client.post("/api/e", content=b"x" * 5000).status_code == 413


def test_google_verification_file(monkeypatch):
    import importlib, app.site as site
    monkeypatch.setenv("GOOGLE_VERIFICATION_FILES", "google7b55f293e02f9a93.html, bad-name.html")
    importlib.reload(site)
    assert site.GOOGLE_VERIFY_FILES == ["google7b55f293e02f9a93.html"]
    from fastapi import FastAPI
    a = FastAPI(); a.include_router(site.router)
    r = TestClient(a).get("/google7b55f293e02f9a93.html")
    assert r.status_code == 200 and r.text == "google-site-verification: google7b55f293e02f9a93.html"
    monkeypatch.delenv("GOOGLE_VERIFICATION_FILES")
    importlib.reload(site)
