"""Submit every sitemap URL to IndexNow (Bing, Yandex, Seznam, Naver...). Usage: python scripts/indexnow.py [base_url]"""
import json, re, sys, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://uaeinvoicecheck.web.app").rstrip("/")
UA = {"User-Agent": "uae-invoice-check-indexnow/1.0"}
sm = urllib.request.urlopen(urllib.request.Request(BASE + "/sitemap.xml", headers=UA), timeout=30).read().decode()
urls = re.findall(r"<loc>([^<]+)</loc>", sm)
import os
key = os.environ.get("INDEXNOW_KEY", "7c1e9a4f2b8d4e6fa3c5b7d9e1f20468")
assert urllib.request.urlopen(urllib.request.Request(f"{BASE}/{key}.txt", headers=UA), timeout=30).read().decode().strip() == key, "key file not served"
host = BASE.split("://", 1)[1]
body = json.dumps({"host": host, "key": key, "keyLocation": f"{BASE}/{key}.txt", "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={**UA, "Content-Type": "application/json; charset=utf-8"})
try:
    r = urllib.request.urlopen(req, timeout=30)
    print(f"IndexNow: submitted {len(urls)} URLs for {host} -> HTTP {r.status}")
except urllib.error.HTTPError as e:
    print(f"IndexNow: HTTP {e.code} {e.read()[:300]!r}")
