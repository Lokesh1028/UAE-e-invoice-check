"""
Render every crawlable page with the app itself and publish them as STATIC files on Firebase Hosting,
with a catch-all rewrite to Cloud Run for everything else (API, tools, health).

Why: with a pure Cloud Run rewrite, Googlebot requests that miss the Firebase/Fastly cache fail at the
CDN layer ("robots.txt unreachable"), while browsers and other crawlers are fine. Static files are
served by Hosting directly, before rewrites, so Googlebot gets them.

Usage:  ./.venv/bin/python scripts/firebase_deploy.py            (uses gcloud credentials)
Env:    the same PUBLIC_BASE_URL / GOOGLE_* / APP_VERSION values as the Cloud Run service.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Same values the Cloud Run service uses, so static and dynamic pages are identical.
os.environ.setdefault("PUBLIC_BASE_URL", "https://uaeinvoicecheck.web.app")
os.environ.setdefault("APP_VERSION", "0.2.6")
os.environ.setdefault("BUILD_DATE", "2026-10-15")
os.environ.setdefault("GOOGLE_SITE_VERIFICATION", "DeFElMnyjlhtqo5T0b9dYbSZO6xkwWttd2a6Syk9Hq8")
os.environ.setdefault("GOOGLE_VERIFICATION_FILES", "google7b55f293e02f9a93.html")
os.environ["ANALYTICS_DISABLED"] = "1"

import urllib.request  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import site  # noqa: E402

PROJECT = os.environ.get("GCP_PROJECT", "e-invoicing-511716")
SITE = os.environ.get("FIREBASE_SITE", "uaeinvoicecheck")
SERVICE, REGION = "uae-einvoice-check", "me-central1"
API = "https://firebasehosting.googleapis.com/v1beta1"


def gcloud_token() -> str:
    for g in ("gcloud", "/opt/homebrew/share/google-cloud-sdk/bin/gcloud"):
        try:
            return subprocess.run([g, "auth", "print-access-token"], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            continue
    sys.exit("gcloud not available")


def call(method: str, url: str, token: str, body=None, data: bytes | None = None, ctype="application/json"):
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": PROJECT, "Content-Type": ctype}
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    print(f"  {method} {url.split('/v1beta1/')[-1][:90]}", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw and r.headers.get("content-type", "").startswith("application/json") else raw
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} -> {e.code}: {e.read()[:500]!r}")


def render() -> dict[str, bytes]:
    """Map Hosting file path -> bytes, rendered by the real app."""
    c = TestClient(app)
    files: dict[str, bytes] = {}

    def grab(url: str, dest: str):
        r = c.get(url)
        if r.status_code != 200:
            sys.exit(f"render failed {url}: {r.status_code}")
        files[dest] = r.content

    for path, _prio in site.all_urls():
        dest = "/index.html" if path == "/" else f"{path}.html"
        grab(path, dest)
    for p in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/llms-full.txt", "/favicon.ico", "/og.png", "/apple-touch-icon.png",
              f"/{site.INDEXNOW_KEY}.txt"):
        grab(p, p)
    # Google verification files are NOT uploaded: cleanUrls would 301 "/googleXXXX.html" to "/googleXXXX".
    # They fall through to the Cloud Run rewrite, which serves them byte-exact.
    for f in sorted((ROOT / "app" / "static").iterdir()):
        if f.is_file() and f.name != "index.html":
            files[f"/static/{f.name}"] = f.read_bytes()
    return files


def main():
    print("rendering pages…", flush=True)
    files = render()
    print(f"rendered {len(files)} files", flush=True)
    token = gcloud_token()
    config = {
        "cleanUrls": True,
        "trailingSlashBehavior": "REMOVE",
        "headers": [
            {"glob": "**/*.html", "headers": {"Cache-Control": "public, max-age=600", "X-Content-Type-Options": "nosniff",
                                              "Referrer-Policy": "strict-origin-when-cross-origin", "X-Frame-Options": "DENY"}},
            {"glob": "/static/**", "headers": {"Cache-Control": "public, max-age=86400"}},
            {"glob": "/@(robots.txt|sitemap.xml|llms.txt|llms-full.txt)", "headers": {"Cache-Control": "public, max-age=3600"}},
        ],
        "rewrites": [{"glob": "**", "run": {"serviceId": SERVICE, "region": REGION}}],
    }
    version = call("POST", f"{API}/sites/{SITE}/versions", token, {"config": config})["name"]
    gz = {p: gzip.compress(b, mtime=0) for p, b in files.items()}
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in gz.items()}
    pop = call("POST", f"{API}/{version}:populateFiles", token, {"files": hashes})
    need = set(pop.get("uploadRequiredHashes", []))
    upload_url = pop.get("uploadUrl")
    by_hash = {h: gz[p] for p, h in hashes.items()}
    for h in need:
        call("POST", f"{upload_url}/{h}", token, data=by_hash[h], ctype="application/octet-stream")
    print(f"uploaded {len(need)} new files ({len(files) - len(need)} unchanged)")
    call("PATCH", f"{API}/{version}?update_mask=status", token, {"status": "FINALIZED"})
    rel = call("POST", f"{API}/sites/{SITE}/releases?versionName={version}", token, {})
    print("released", rel.get("name"))


if __name__ == "__main__":
    main()
