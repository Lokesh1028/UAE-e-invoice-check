"""
Visitor report from Cloud Logging (first-party analytics written by app/analytics.py).

Usage:
  python scripts/visitors.py                 # last 7 days
  python scripts/visitors.py --days 3 --exclude-me
  python scripts/visitors.py --days 30 --out ~/Desktop/uae-prospects/visitors

Prints a summary and writes three CSVs: sessions (one row per human visit), bots, and raw events.
IP -> country / network uses the free DB-IP Lite databases (CC BY 4.0, https://db-ip.com),
downloaded once into ~/.cache/uae-invoice-check.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.analytics import classify_agent  # noqa: E402  (re-classify old events with current rules)

MACHINE_FILES = re.compile(r"^/(robots\.txt|sitemap\.xml|llms(-full)?\.txt|[0-9a-f]{32}\.txt|favicon\.ico|og\.png|apple-touch-icon\.png)$")
PROJECT = os.environ.get("GCP_PROJECT", "e-invoicing-511716")
SERVICE = os.environ.get("RUN_SERVICE", "uae-einvoice-check")
CACHE = Path.home() / ".cache" / "uae-invoice-check"
DUBAI = timezone(timedelta(hours=4))
IST = timezone(timedelta(hours=5, minutes=30))


# ------------------------------------------------------------------ data access
def gcloud() -> str:
    for c in (shutil.which("gcloud"), "/opt/homebrew/share/google-cloud-sdk/bin/gcloud", "/usr/local/bin/gcloud"):
        if c and Path(c).exists():
            return c
    sys.exit("gcloud not found. Install the Google Cloud SDK and run `gcloud auth login`.")


def fetch_events(days: int) -> list[dict]:
    flt = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{SERVICE}" '
           f'AND jsonPayload.event:*')
    cmd = [gcloud(), "logging", "read", flt, f"--freshness={days}d", "--limit=100000", "--format=json", f"--project={PROJECT}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("gcloud logging read failed:\n" + out.stderr[-2000:])
    rows = json.loads(out.stdout or "[]")
    events = []
    for r in rows:
        p = r.get("jsonPayload") or {}
        if not p.get("event"):
            continue
        p["_revision"] = (r.get("resource") or {}).get("labels", {}).get("revision_name")
        events.append(p)
    events.extend(fetch_hosting_hits(days))
    if any(e.get("_src") == "hosting" for e in events):
        # Firebase Hosting logs every request (static pages included); the app's own "hit" events would double count
        events = [e for e in events if not (e.get("event") == "hit" and e.get("_src") != "hosting")]
    events.sort(key=lambda e: e.get("ts", 0))
    return events


def fetch_hosting_hits(days: int) -> list[dict]:
    """Page requests as logged by Firebase Hosting (cloudLoggingEnabled on the site)."""
    flt = 'resource.type="firebase_domain"'
    cmd = [gcloud(), "logging", "read", flt, f"--freshness={days}d", "--limit=100000", "--format=json", f"--project={PROJECT}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    hits = []
    for r in json.loads(out.stdout or "[]"):
        h = r.get("httpRequest") or {}
        url = h.get("requestUrl", "")
        path = re.sub(r"^https?://[^/]+", "", url).split("?")[0] or "/"
        if path.startswith(("/api/", "/static/", "/health")) or path in ("/favicon.ico", "/apple-touch-icon.png"):
            continue
        q = url.split("?", 1)[1] if "?" in url else ""
        utm = dict(kv.split("=", 1) for kv in q.split("&") if "=" in kv and kv.split("=", 1)[0] in
                   ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "src", "ref"))
        ts = r.get("timestamp", "")
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        hits.append({"event": "hit", "_src": "hosting", "ts": t, "path": path, "status": h.get("status"),
                     "ua": h.get("userAgent", ""), "ip": h.get("remoteIp", ""), "referer": h.get("referer", ""), "utm": utm})
    return hits


# ------------------------------------------------------------------ IP enrichment
def _dbip(kind: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    have = sorted(CACHE.glob(f"dbip-{kind}-lite-*.csv.gz"))
    if have:
        return have[-1]
    for back in range(0, 3):
        d = (date.today().replace(day=1) - timedelta(days=28 * back))
        name = f"dbip-{kind}-lite-{d:%Y-%m}.csv.gz"
        try:
            urllib.request.urlretrieve(f"https://download.db-ip.com/free/{name}", CACHE / name)
            return CACHE / name
        except Exception:
            continue
    raise RuntimeError(f"could not download DB-IP {kind} database")


def enrich(ips: set[str]) -> dict[str, dict]:
    """Stream each DB-IP file once and resolve only the IPs we need."""
    targets = {}
    for ip in ips:
        try:
            targets[ip] = ipaddress.ip_address(ip)
        except ValueError:
            pass
    out = {ip: {"country": "", "asn": "", "org": ""} for ip in targets}
    if not targets:
        return out
    by_ver = {4: sorted((int(a), ip) for ip, a in targets.items() if a.version == 4),
              6: sorted((int(a), ip) for ip, a in targets.items() if a.version == 6)}
    keys = {v: [k for k, _ in lst] for v, lst in by_ver.items()}
    for kind in ("country", "asn"):
        try:
            path = _dbip(kind)
        except RuntimeError as e:
            print("  (geo lookup skipped:", e, ")")
            continue
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                try:
                    a, b = ipaddress.ip_address(row[0]), ipaddress.ip_address(row[1])
                except ValueError:
                    continue
                ks = keys[a.version]
                if not ks:
                    continue
                lo, hi = int(a), int(b)
                i = bisect.bisect_left(ks, lo)
                while i < len(ks) and ks[i] <= hi:
                    ip = by_ver[a.version][i][1]
                    if kind == "country":
                        out[ip]["country"] = row[2]
                    else:
                        out[ip]["asn"], out[ip]["org"] = row[2], row[3]
                    i += 1
    return out


# ------------------------------------------------------------------ UA parsing
def parse_ua(ua: str) -> dict:
    ua = ua or ""
    dev = "tablet" if re.search(r"ipad|tablet", ua, re.I) else "mobile" if re.search(r"mobi|android|iphone", ua, re.I) else "desktop"
    os_ = ("iOS" if re.search(r"iphone|ipad|ipod", ua, re.I) else "Android" if "Android" in ua else
           "Windows" if "Windows" in ua else "macOS" if "Mac OS X" in ua else "Linux" if "Linux" in ua else "ChromeOS" if "CrOS" in ua else "other")
    br = ("WhatsApp in-app" if "WhatsApp" in ua else "LinkedIn in-app" if "LinkedInApp" in ua else
          "Instagram in-app" if "Instagram" in ua else "Facebook in-app" if re.search(r"FBAN|FBAV", ua) else
          "Edge" if "Edg/" in ua else "Opera" if re.search(r"OPR/|Opera", ua) else "Samsung" if "SamsungBrowser" in ua else
          "Chrome" if re.search(r"Chrome/|CriOS", ua) else "Firefox" if re.search(r"Firefox|FxiOS", ua) else
          "Safari" if "Safari" in ua else "other")
    return {"device": dev, "os": os_, "browser": br}


def referrer_source(ref: str, utm: dict | None) -> str:
    utm = utm or {}
    if utm.get("utm_source") or utm.get("src"):
        return (utm.get("utm_source") or utm.get("src")).lower()
    if not ref:
        return "direct / unknown"
    host = re.sub(r"^https?://", "", ref).split("/")[0].lower()
    for k, v in (("google.", "google"), ("bing.", "bing"), ("duckduckgo", "duckduckgo"), ("yahoo.", "yahoo"),
                 ("chatgpt", "chatgpt"), ("openai", "chatgpt"), ("perplexity", "perplexity"), ("claude.ai", "claude"),
                 ("gemini.google", "gemini"), ("linkedin", "linkedin"), ("lnkd.in", "linkedin"), ("whatsapp", "whatsapp"),
                 ("facebook", "facebook"), ("t.co", "x/twitter"), ("twitter", "x/twitter"), ("x.com", "x/twitter"),
                 ("reddit", "reddit"), ("youtube", "youtube"), ("github", "github")):
        if k in host:
            return v
    return host


def fmt_t(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%d %b %H:%M")


# ------------------------------------------------------------------ report
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "uae-prospects" / "visitors"))
    ap.add_argument("--exclude-ip", action="append", default=[], help="IP to ignore (repeatable)")
    ap.add_argument("--exclude-me", action="store_true", help="ignore this computer's current public IP")
    args = ap.parse_args()

    excluded = set(args.exclude_ip)
    if args.exclude_me:
        try:
            excluded.add(urllib.request.urlopen("https://api.ipify.org", timeout=8).read().decode().strip())
        except Exception:
            print("(could not determine your public IP; --exclude-me ignored)")

    print(f"Reading visit logs for the last {args.days} day(s) from project {PROJECT} …")
    events = [e for e in fetch_events(args.days) if e.get("ip") not in excluded]
    for e in events:
        e["agent_kind"], e["agent_name"] = classify_agent(e.get("ua", ""))
        if e["agent_kind"] == "human" and e.get("event") == "hit" and MACHINE_FILES.match(e.get("path") or ""):
            e["agent_kind"], e["agent_name"] = "bot", "Machine file fetch"
    if not events:
        print("No visit events yet.")
        return
    geo = enrich({e["ip"] for e in events if e.get("ip")})

    humans = [e for e in events if e.get("agent_kind") == "human"]
    bots = [e for e in events if e.get("agent_kind") == "bot"]
    previews = [e for e in events if e.get("agent_kind") == "preview"]

    # sessions: browser beacons (pv/leave/ev) and actions carry sid; human hits without any beacon form their own group
    sessions: dict[str, dict] = {}
    beacon_sids = {e.get("sid") for e in humans if e["event"] in ("pv", "leave", "ev") and e.get("sid")}
    # browsers that ran the beacon: their server-side page hits duplicate the beacon page views, so skip them
    beacon_clients = {(e.get("ip"), e.get("ua")) for e in humans if e["event"] in ("pv", "leave", "ev")}
    for e in humans:
        if e["event"] == "hit" and (e.get("ip"), e.get("ua")) in beacon_clients:
            continue
        key = e.get("sid") if e.get("sid") in beacon_sids else f"nojs:{e.get('ip')}:{hash(e.get('ua'))}"
        s = sessions.setdefault(key, {"first": e["ts"], "last": e["ts"], "ip": e.get("ip"), "ua": e.get("ua", ""), "pages": [],
                                      "secs": 0, "scroll": 0, "actions": [], "ref": "", "utm": {}, "lang": e.get("lang", ""),
                                      "tz": "", "screen": "", "landing": "", "js": key in beacon_sids})
        s["last"] = max(s["last"], e["ts"])
        if e["event"] == "pv":
            s["pages"].append(e.get("path") or "?")
            if not s["landing"]:
                s["landing"] = e.get("path") or "?"
                s["ref"] = e.get("ref", "")
                s["utm"] = e.get("utm") or {}
            s["tz"] = e.get("tz") or s["tz"]
            if e.get("sw"):
                s["screen"] = f"{e.get('sw')}x{e.get('sh')}"
            s["lang"] = e.get("lang") or s["lang"]
        elif e["event"] == "hit" and not s["js"]:
            s["pages"].append(e.get("path", ""))
            if not s["landing"]:
                s["landing"], s["ref"], s["utm"] = e.get("path", ""), e.get("referer", ""), e.get("utm") or {}
        elif e["event"] == "leave":
            s["secs"] += int(e.get("secs") or 0)
            s["scroll"] = max(s["scroll"], int(e.get("scroll") or 0))
        elif e["event"] == "action":
            d = e.get("details") or {}
            label = e.get("action")
            if label == "readiness":
                label = f"readiness({d.get('ext')}, {d.get('docs', '?')} docs, {d.get('ready', '?')} ready)" if d.get("ok") else f"readiness FAILED({d.get('ext')})"
            s["actions"].append(label)
        elif e["event"] == "ev":
            s["actions"].append("ui:" + str(e.get("name")))

    # attach actions that arrived without a matching beacon session (e.g. API used directly)
    rows = []
    for key, s in sorted(sessions.items(), key=lambda kv: kv[1]["first"]):
        if not s["pages"] and not s["actions"]:
            continue
        g = geo.get(s["ip"], {})
        u = parse_ua(s["ua"])
        rows.append({
            "first_seen_dubai": fmt_t(s["first"], DUBAI), "first_seen_ist": fmt_t(s["first"], IST),
            "ip": s["ip"], "country": g.get("country", ""), "network": g.get("org", ""), "asn": g.get("asn", ""),
            "device": u["device"], "os": u["os"], "browser": u["browser"], "language": s["lang"][:20], "timezone": s["tz"],
            "screen": s["screen"], "source": referrer_source(s["ref"], s["utm"]), "referrer": s["ref"],
            "utm": json.dumps(s["utm"]) if s["utm"] else "", "landing_page": s["landing"], "pages": len(s["pages"]),
            "page_list": " > ".join(s["pages"][:12]), "seconds_on_site": s["secs"], "max_scroll_pct": s["scroll"],
            "actions": "; ".join(s["actions"]), "ran_js": s["js"], "user_agent": s["ua"],
        })

    visitors = {(r["ip"], r["user_agent"]) for r in rows}
    tool_users = [r for r in rows if "readiness" in r["actions"] or "validate_xml" in r["actions"] or "lookup" in r["actions"]]
    print()
    print("=" * 78)
    print(f"HUMAN VISITS  last {args.days} day(s)   (excluded IPs: {', '.join(sorted(excluded)) or 'none'})")
    print("=" * 78)
    print(f"  visits (sessions):        {len(rows)}")
    print(f"  unique visitors (IP+UA):  {len(visitors)}")
    print(f"  unique IPs:               {len({r['ip'] for r in rows})}")
    print(f"  used a tool:              {len(tool_users)}")
    print(f"  readiness checks run:     {sum(r['actions'].count('readiness(') for r in rows)}")
    print(f"  leads submitted:          {sum(r['actions'].count('lead') for r in rows)}")
    by_day = Counter(datetime.fromtimestamp(sessions[k]['first'], DUBAI).strftime('%a %d %b') for k in sessions if sessions[k]['pages'] or sessions[k]['actions'])
    print("\n  Visits per day (Dubai time):")
    for d_, n in sorted(by_day.items(), key=lambda x: datetime.strptime(x[0] + " 2026", "%a %d %b %Y")):
        print(f"    {d_}: {n}")
    for title, key in (("Country", "country"), ("Source", "source"), ("Landing page", "landing_page"), ("Device", "device"),
                       ("Browser", "browser"), ("Network (ISP / company)", "network")):
        c = Counter(r[key] or "unknown" for r in rows)
        print(f"\n  {title}:")
        for k, n in c.most_common(10):
            print(f"    {n:4d}  {k}")
    print("\n  Each visit:")
    for r in rows[-40:]:
        print(f"    {r['first_seen_dubai']} GST | {r['country'] or '??'} | {r['network'][:28]:28s} | {r['device']:7s} {r['browser'][:14]:14s} | "
              f"{r['source'][:18]:18s} | {r['pages']}p {r['seconds_on_site']}s | {r['actions'][:60]}")

    print()
    print("=" * 78)
    print("CRAWLERS AND LINK PREVIEWS")
    print("=" * 78)
    bc = Counter(e.get("agent_name") for e in bots)
    for name, n in bc.most_common():
        paths = Counter(e.get("path") for e in bots if e.get("agent_name") == name)
        print(f"  {n:4d}  {name:18s} e.g. {', '.join(str(p) for p, _ in paths.most_common(3))}")
    pc = Counter(e.get("agent_name") for e in previews)
    for name, n in pc.most_common():
        print(f"  {n:4d}  {name}  (someone pasted the link into {name.replace(' preview', '')})")
    if not bc and not pc:
        print("  none yet")

    out = Path(os.path.expanduser(args.out))
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(DUBAI).strftime("%Y-%m-%d_%H%M")
    if rows:
        with open(out / f"sessions_{stamp}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with open(out / f"bots_{stamp}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time_dubai", "kind", "name", "path", "ip", "country", "network", "user_agent"])
        for e in bots + previews:
            g = geo.get(e.get("ip"), {})
            w.writerow([fmt_t(e["ts"], DUBAI), e.get("agent_kind"), e.get("agent_name"), e.get("path"), e.get("ip"), g.get("country"), g.get("org"), e.get("ua")])
    with open(out / f"events_{stamp}.jsonl", "w", encoding="utf-8") as fh:
        for e in events:
            g = geo.get(e.get("ip"), {})
            fh.write(json.dumps({**e, "geo_country": g.get("country"), "geo_network": g.get("org")}, ensure_ascii=False) + "\n")
    print(f"\nFiles written to {out}/ (sessions_*.csv, bots_*.csv, events_*.jsonl)")
    print("IP geolocation by DB-IP Lite (https://db-ip.com), CC BY 4.0.")


if __name__ == "__main__":
    main()
