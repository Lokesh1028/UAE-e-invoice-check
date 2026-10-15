"""
Lead storage: append-only JSONL file under DATA_DIR (works on a single VM /
persistent volume) plus an optional webhook (LEAD_WEBHOOK_URL) for Google
Sheets / n8n / Zapier. Set LEADS_DISABLED=1 to turn the endpoint into a no-op.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import httpx

log = logging.getLogger("leads")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
WEBHOOK = os.environ.get("LEAD_WEBHOOK_URL", "")
DISABLED = os.environ.get("LEADS_DISABLED", "") == "1"
_lock = threading.Lock()


def store_lead(rec: dict) -> None:
    if DISABLED:
        return
    # Always emit to the platform log too: on Cloud Run the filesystem is ephemeral, the log is not.
    # Retrieve with: gcloud logging read 'textPayload:"LEAD "' --freshness=30d --format='value(textPayload)'
    log.info("LEAD %s", json.dumps(rec, ensure_ascii=False))
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _lock, open(DATA_DIR / "leads.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        log.exception("could not write lead file")
    if WEBHOOK:
        try:
            httpx.post(WEBHOOK, json=rec, timeout=5.0)
        except Exception:
            log.warning("lead webhook failed")
