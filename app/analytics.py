"""
First-party visit analytics, no cookies, no third parties.

Every visit-related event is written as ONE JSON line to stdout. On Cloud Run that
lands in Cloud Logging as jsonPayload, where scripts/visitors.py reads it back.

Events
  hit     server side: an HTML / SEO resource was requested (covers crawlers that run no JS)
  pv      browser beacon: a page was viewed (humans; sent by /static/t.js)
  leave   browser beacon: time spent on the page
  ev      browser beacon: a UI event (e.g. "file_selected")
  action  server side: a tool was used (readiness check, XML validation, lookup, report, lead)

What is recorded: IP address, user agent, referrer, Accept-Language, path, UTM params,
screen size / timezone / language from the beacon, and tool usage summaries.
What is NOT recorded: uploaded file contents or file names, form fields.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Request

RES = Path(__file__).resolve().parent / "resources"
ANALYTICS_ENABLED = os.environ.get("ANALYTICS_DISABLED", "") != "1"

# ----------------------------------------------------------------- client IP
@lru_cache(maxsize=1)
def _trusted_nets():
    data = json.loads((RES / "trusted_proxies.json").read_text())
    extra = [c.strip() for c in os.environ.get("TRUSTED_PROXY_CIDRS", "").split(",") if c.strip()]
    nets = []
    for group in data.values():
        if not isinstance(group, list):
            continue
        for cidr in group:
            try:
                nets.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass
    for cidr in extra:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass
    return nets


def _is_trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in _trusted_nets() if n.version == addr.version)


def client_ip(request: Request) -> str:
    """
    Walk X-Forwarded-For from the right and return the first address that is not a
    known proxy (Google front end, Fastly/Firebase, Cloudflare, private ranges).
    Entries to the left of that are client-supplied and can be forged, so they are ignored.
    """
    xff = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for ip in reversed(parts):
        if not _is_trusted(ip):
            return ip
    if parts:
        return parts[0]
    return request.client.host if request.client else "unknown"


# ----------------------------------------------------------------- bots
_BOTS = [
    ("Googlebot", r"googlebot|google-inspectiontool|googleother|apis-google|adsbot-google|mediapartners-google|google-site-verification|storebot-google"),
    ("Google-Extended", r"google-extended"),
    ("Bingbot", r"bingbot|bingpreview|msnbot|adidxbot"),
    ("DuckDuckBot", r"duckduckbot|duckassistbot"),
    ("YandexBot", r"yandex"),
    ("Baiduspider", r"baiduspider"),
    ("Applebot", r"applebot"),
    ("GPTBot", r"gptbot|chatgpt-user|oai-searchbot"),
    ("ClaudeBot", r"claudebot|claude-user|claude-searchbot|anthropic-ai"),
    ("PerplexityBot", r"perplexitybot|perplexity-user"),
    ("CCBot", r"ccbot"),
    ("Bytespider", r"bytespider"),
    ("Amazonbot", r"amazonbot"),
    ("Meta", r"meta-externalagent|meta-externalfetcher|facebookbot"),
    ("SEO tool", r"ahrefsbot|semrushbot|mj12bot|dotbot|rogerbot|seznambot|petalbot|dataforseo|serpstat|screaming frog"),
    ("Monitor", r"uptimerobot|pingdom|statuscake|site24x7|googlestackdriver|gcp-uptime"),
    ("Script", r"curl|wget|python-requests|python-httpx|httpx|aiohttp|go-http-client|okhttp|java/|libwww|axios|node-fetch|postmanruntime|insomnia"),
    ("Headless", r"headlesschrome|phantomjs|puppeteer|playwright|selenium"),
    ("Other bot", r"bot\b|crawler|spider|crawl|slurp|scrapy|archiver|feedfetcher"),
]
_PREVIEWS = [
    ("WhatsApp preview", r"whatsapp"),
    ("LinkedIn preview", r"linkedinbot"),
    ("Facebook preview", r"facebookexternalhit|facebookcatalog"),
    ("X/Twitter preview", r"twitterbot"),
    ("Telegram preview", r"telegrambot"),
    ("Slack preview", r"slackbot|slack-imgproxy"),
    ("Discord preview", r"discordbot"),
    ("Skype/Teams preview", r"skypeuripreview|microsoft teams|teamsbot"),
    ("Pinterest preview", r"pinterest"),
    ("Snapchat preview", r"snapchat"),
]
_BOT_RE = [(n, re.compile(p, re.I)) for n, p in _BOTS]
_PREVIEW_RE = [(n, re.compile(p, re.I)) for n, p in _PREVIEWS]


def classify_agent(ua: str) -> tuple[str, Optional[str]]:
    """Return (kind, name): kind is 'human', 'bot' or 'preview' (link-unfurl fetch)."""
    ua = ua or ""
    if not ua.strip():
        return "bot", "Empty UA"
    for name, rx in _PREVIEW_RE:
        if rx.search(ua):
            return "preview", name
    for name, rx in _BOT_RE:
        if rx.search(ua):
            return "bot", name
    if "mozilla" not in ua.lower() and "opera" not in ua.lower():
        return "bot", "Non-browser client"   # every mainstream browser UA starts with Mozilla/
    return "human", None


# ----------------------------------------------------------------- logging
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "src", "ref", "gclid", "fbclid", "li_fat_id")


def _base(request: Request) -> dict:
    ua = request.headers.get("user-agent", "")[:400]
    kind, name = classify_agent(ua)
    return {
        "ip": client_ip(request),
        "ua": ua,
        "agent_kind": kind,
        "agent_name": name,
        "lang": request.headers.get("accept-language", "")[:80],
        "host": request.headers.get("x-forwarded-host") or request.headers.get("host", ""),
        "sid": (request.headers.get("x-session-id") or "")[:40] or None,
    }


def emit(event: str, payload: dict) -> None:
    if not ANALYTICS_ENABLED:
        return
    rec = {"severity": "INFO", "message": f"visit:{event}", "event": event, "ts": round(time.time(), 3)}
    rec.update({k: v for k, v in payload.items() if v not in (None, "", [], {})})
    try:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def log_hit(request: Request, status: int) -> None:
    q = request.query_params
    payload = _base(request)
    payload.update({
        "path": request.url.path[:300],
        "status": status,
        "referer": request.headers.get("referer", "")[:400],
        "utm": {k: q.get(k)[:120] for k in UTM_KEYS if q.get(k)},
        "xff": request.headers.get("x-forwarded-for", "")[:300],
    })
    emit("hit", payload)


def log_action(request: Request, action: str, **details) -> None:
    payload = _base(request)
    payload["action"] = action
    payload["details"] = {k: v for k, v in details.items() if v is not None}
    emit("action", payload)


_ALLOWED_BEACON = {"t", "sid", "path", "ref", "title", "lang", "tz", "sw", "sh", "vw", "vh", "dpr", "utm", "name", "secs", "scroll", "touch", "conn"}


def log_beacon(request: Request, body: dict) -> None:
    t = str(body.get("t") or "pv")
    if t not in ("pv", "leave", "ev"):
        return
    payload = _base(request)
    for k in _ALLOWED_BEACON:
        if k in body and k != "t":
            v = body[k]
            if isinstance(v, str):
                v = v[:300]
            elif isinstance(v, dict):
                v = {str(a)[:30]: str(b)[:120] for a, b in list(v.items())[:12]}
            elif isinstance(v, (bool, int, float)):
                pass
            else:
                v = str(v)[:60]
            payload[k] = v
    # browser-sent sid wins over header (beacons can't set headers)
    if body.get("sid"):
        payload["sid"] = str(body["sid"])[:40]
    emit(t, payload)
