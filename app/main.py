"""
Application entry point.

Run locally:   uvicorn app.main:app --reload
Production:    see Dockerfile (uvicorn with N workers behind the platform's load balancer).
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.engine.validator import Validator

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger("main")

STATIC = Path(__file__).resolve().parent / "static"
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "40"))
RATE_LIMIT_BURST = int(os.environ.get("RATE_LIMIT_BURST", "15"))
TRUST_PROXY = os.environ.get("TRUST_PROXY", "1") == "1"
APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")

app = FastAPI(title="UAE e-invoice readiness check", version=APP_VERSION, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ----------------------------------------------------------------- rate limit
class _Bucket:
    __slots__ = ("tokens", "ts")

    def __init__(self):
        self.tokens = float(RATE_LIMIT_BURST)
        self.ts = time.monotonic()


_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
_last_sweep = time.monotonic()


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf
    return request.client.host if request.client else "unknown"


def _allow(ip: str) -> tuple[bool, float]:
    global _last_sweep
    now = time.monotonic()
    b = _buckets[ip]
    b.tokens = min(RATE_LIMIT_BURST, b.tokens + (now - b.ts) * (RATE_LIMIT_PER_MIN / 60.0))
    b.ts = now
    if now - _last_sweep > 300:  # keep the dict bounded
        _last_sweep = now
        for k in [k for k, v in _buckets.items() if now - v.ts > 600]:
            _buckets.pop(k, None)
    if b.tokens >= 1:
        b.tokens -= 1
        return True, 0
    return False, (1 - b.tokens) / (RATE_LIMIT_PER_MIN / 60.0)


@app.middleware("http")
async def guard(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    if request.url.path.startswith("/api/") and request.method != "GET" or request.url.path.startswith("/api/lookup"):
        ok, wait = _allow(_client_ip(request))
        if not ok:
            return JSONResponse({"detail": "Too many requests. Please wait a moment."}, status_code=429,
                                headers={"Retry-After": str(int(wait) + 1)})
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled rid=%s path=%s", rid, request.url.path)
        return JSONResponse({"detail": f"Internal error (ref {rid})."}, status_code=500)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    if request.url.path.startswith("/api/") and request.method != "GET":
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path, response.status_code, (time.perf_counter() - t0) * 1000)
    return response


@app.on_event("startup")
def _warm():
    Validator.get()  # compile rule sets once per worker before serving traffic


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "version": APP_VERSION}


@app.get("/readyz", include_in_schema=False)
def readyz():
    v = Validator.get()
    return {"ok": v is not None, "rules": "PINT AE 1.0.2"}


app.include_router(router)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "public, max-age=300"})


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /api/\n", media_type="text/plain")
