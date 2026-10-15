"""
Application entry point.

Run locally:   uvicorn app.main:app --reload
Production:    see Dockerfile (uvicorn with N workers behind the platform's load balancer).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import analytics
from app.api import router as api_router
from app.engine.validator import Validator
from app.site import BASE, router as site_router

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger("main")

STATIC = Path(__file__).resolve().parent / "static"
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "40"))
RATE_LIMIT_BURST = int(os.environ.get("RATE_LIMIT_BURST", "15"))
APP_VERSION = os.environ.get("APP_VERSION", "0.2.0")
# Send visitors who open the long *.run.app address to the canonical short address.
# Only enable once the CDN in front (Firebase Hosting) is confirmed to send X-Forwarded-Host,
# otherwise requests arriving through it would loop.
REDIRECT_TO_CANONICAL = os.environ.get("REDIRECT_TO_CANONICAL", "0") == "1"
CANONICAL_HOST = BASE.split("://", 1)[-1]

app = FastAPI(title="UAE Invoice Check", version=APP_VERSION, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ----------------------------------------------------------------- rate limit
class _Bucket:
    __slots__ = ("tokens", "ts")

    def __init__(self):
        self.tokens = float(RATE_LIMIT_BURST)
        self.ts = time.monotonic()


_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
_last_sweep = time.monotonic()


def _allow(ip: str) -> tuple[bool, float]:
    global _last_sweep
    now = time.monotonic()
    b = _buckets[ip]
    b.tokens = min(RATE_LIMIT_BURST, b.tokens + (now - b.ts) * (RATE_LIMIT_PER_MIN / 60.0))
    b.ts = now
    if now - _last_sweep > 300:
        _last_sweep = now
        for k in [k for k, v in _buckets.items() if now - v.ts > 600]:
            _buckets.pop(k, None)
    if b.tokens >= 1:
        b.tokens -= 1
        return True, 0
    return False, (1 - b.tokens) / (RATE_LIMIT_PER_MIN / 60.0)


def _is_page(path: str) -> bool:
    """Requests worth recording as a visit hit (HTML pages and crawler files, not assets or API)."""
    if path.startswith(("/api/", "/static/", "/health", "/readyz")):
        return False
    if path in ("/favicon.ico", "/apple-touch-icon.png", "/og.png"):
        return False
    return True


@app.middleware("http")
async def guard(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    path = request.url.path

    if REDIRECT_TO_CANONICAL and request.method == "GET" and not path.startswith(("/api/", "/health", "/readyz")):
        host = request.headers.get("host", "")
        via_cdn = any(CANONICAL_HOST in request.headers.get(h, "") for h in ("x-forwarded-host", "x-fh-requested-host"))
        kind, _ = analytics.classify_agent(request.headers.get("user-agent", ""))
        # Never redirect crawlers (canonical tags handle duplicates) and never let a CDN cache the redirect:
        # Firebase does not always mark crawler requests, and a cached self-redirect loops forever.
        if host.endswith(".run.app") and not via_cdn and kind == "human":
            target = BASE + path + (("?" + request.url.query) if request.url.query else "")
            return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})

    if (path.startswith("/api/") and request.method != "GET") or path.startswith("/api/lookup"):
        ok, wait = _allow(analytics.client_ip(request))
        if not ok:
            return JSONResponse({"detail": "Too many requests. Please wait a moment."}, status_code=429,
                                headers={"Retry-After": str(int(wait) + 1)})
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled rid=%s path=%s", rid, path)
        return JSONResponse({"detail": f"Internal error (ref {rid})."}, status_code=500)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    if request.method in ("GET", "HEAD") and _is_page(path):
        analytics.log_hit(request, response.status_code)
    if path.startswith("/api/") and request.method != "GET":
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, path, response.status_code, (time.perf_counter() - t0) * 1000)
    return response


@app.on_event("startup")
def _warm():
    Validator.get()  # compile rule sets once per worker before serving traffic


@app.get("/healthz", include_in_schema=False)
@app.get("/health", include_in_schema=False)  # Cloud Run reserves paths ending in "z" at its front end
def healthz():
    return {"ok": True, "version": APP_VERSION}


@app.get("/readyz", include_in_schema=False)
def readyz():
    return {"ok": Validator.get() is not None, "rules": "PINT AE 1.0.2"}


@app.post("/api/e", include_in_schema=False)
async def beacon(request: Request):
    """Browser beacon (page view, time on page, UI events). Body is small JSON sent as text/plain."""
    raw = await request.body()
    if len(raw) > 4096:
        return Response(status_code=413)
    try:
        body = json.loads(raw or b"{}")
        if isinstance(body, dict):
            analytics.log_beacon(request, body)
    except ValueError:
        pass
    return Response(status_code=204)


app.include_router(api_router)
app.include_router(site_router)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
