"""
Peppol participant lookup for UAE TINs (scheme 0235).

Verified mechanism (Oct 2026): NAPTR record named
    base32(sha256(lowercase("0235:<TIN>"))).iso6523-actorid-upis.<SML domain>
A hit means the participant is registered with an SMP (reachable on the network).

Primary transport is DNS-over-HTTPS (works from any hosting environment, many
home/office resolvers refuse NAPTR). Fallback is classic DNS via dnspython.
The Peppol Directory is queried as a secondary, optional source for the name.
Results are cached in-process for CACHE_TTL seconds.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, asdict

import httpx

SML_DOMAIN = os.environ.get("PEPPOL_SML_DOMAIN", "edelivery.tech.ec.europa.eu")
SML_TEST_DOMAIN = os.environ.get("PEPPOL_SML_TEST_DOMAIN", "acc.edelivery.tech.ec.europa.eu")
DOH_URL = os.environ.get("DOH_URL", "https://cloudflare-dns.com/dns-query")
DIRECTORY_URL = os.environ.get("PEPPOL_DIRECTORY_URL", "https://directory.peppol.eu/search/1.0/json")
CACHE_TTL = int(os.environ.get("LOOKUP_CACHE_TTL", "900"))
TIN_RE = re.compile(r"^1[0-9]{9}$")
UA = {"User-Agent": "uae-einvoice-check/1.0 (+readiness tool)"}

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


@dataclass
class LookupResult:
    tin: str
    participant_id: str
    valid_format: bool
    sml_registered: bool | None      # None = could not determine
    sml_environment: str | None      # "production" | "test"
    smp_host: str | None
    directory_listed: bool | None
    directory_name: str | None
    error: str | None = None
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def naptr_name(participant_id: str, domain: str) -> str:
    digest = hashlib.sha256(participant_id.lower().encode("utf-8")).digest()
    b32 = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    return f"{b32}.iso6523-actorid-upis.{domain}"


def _smp_from_naptr_data(data: str) -> str:
    m = re.search(r"!\^?\.\*\$?!([^!]+)!", data)
    return m.group(1) if m else "found"


def _doh_naptr(name: str, client: httpx.Client) -> str | None:
    """Returns SMP URL if the NAPTR exists, None if NXDOMAIN/NoData. Raises on transport error."""
    r = client.get(DOH_URL, params={"name": name, "type": "NAPTR"}, headers={**UA, "accept": "application/dns-json"})
    r.raise_for_status()
    d = r.json()
    if d.get("Status") == 0 and d.get("Answer"):
        for a in d["Answer"]:
            if a.get("type") == 35:
                return _smp_from_naptr_data(a.get("data", ""))
        return "found"
    if d.get("Status") in (0, 3):  # NoData / NXDOMAIN
        return None
    raise RuntimeError(f"DoH status {d.get('Status')}")


def _dns_naptr(name: str) -> str | None:
    import dns.resolver
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["1.1.1.1", "8.8.8.8"]
    resolver.lifetime = resolver.timeout = 3.0
    try:
        answers = resolver.resolve(name, "NAPTR")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return None
    for rr in answers:
        regexp = rr.regexp.decode() if isinstance(rr.regexp, bytes) else str(rr.regexp)
        return _smp_from_naptr_data(regexp)
    return "found"


def _query(name: str, client: httpx.Client) -> str | None:
    try:
        return _doh_naptr(name, client)
    except Exception:
        return _dns_naptr(name)


def lookup_tin(tin: str) -> LookupResult:
    tin = re.sub(r"[\s-]+", "", tin or "")
    pid = f"0235:{tin}"
    now = time.time()
    with _cache_lock:
        hit = _cache.get(pid)
        if hit and now - hit[0] < CACHE_TTL:
            return LookupResult(**hit[1])

    res = LookupResult(tin=tin, participant_id=pid, valid_format=bool(TIN_RE.match(tin)),
                       sml_registered=None, sml_environment=None, smp_host=None,
                       directory_listed=None, directory_name=None, checked_at=now)
    if not res.valid_format:
        res.error = "A UAE TIN is 10 digits and starts with 1."
        return res

    with httpx.Client(timeout=5.0) as client:
        try:
            host = _query(naptr_name(pid, SML_DOMAIN), client)
            if host:
                res.sml_registered, res.sml_environment, res.smp_host = True, "production", host
            else:
                host = _query(naptr_name(pid, SML_TEST_DOMAIN), client)
                if host:
                    res.sml_registered, res.sml_environment, res.smp_host = True, "test", host
                else:
                    res.sml_registered = False
        except Exception as e:
            res.error = f"Network lookup failed ({type(e).__name__}); try again."
        try:
            r = client.get(DIRECTORY_URL, params={"participant": f"iso6523-actorid-upis::{pid}"}, headers=UA)
            if r.status_code == 200:
                matches = r.json().get("matches") or []
                res.directory_listed = bool(matches)
                if matches:
                    ents = matches[0].get("entities") or []
                    if ents:
                        nm = ents[0].get("name")
                        if isinstance(nm, list):  # directory returns [{"name": "..."}]
                            nm = (nm[0].get("name") if nm and isinstance(nm[0], dict) else (nm[0] if nm else None))
                        res.directory_name = nm or None
        except Exception:
            pass  # directory is optional

    with _cache_lock:
        _cache[pid] = (now, res.to_dict())
    return res
