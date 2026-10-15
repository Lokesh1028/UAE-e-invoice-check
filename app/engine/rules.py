"""
Rule dictionary: official rule id -> plain-language explanation.

Source of truth is the official Schematron (rules_raw.json, generated from the
.sch files). rules_plain.json adds human wording, the field a user would look
for on their invoice, and how to fix it. Anything not in rules_plain.json falls
back to a cleaned-up version of the official text.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "resources" / "pint-ae"

TERMS = {
    "ibt-001": "invoice number", "ibt-002": "invoice date", "ibt-003": "invoice type code",
    "ibt-005": "invoice currency", "ibt-006": "VAT accounting currency", "ibt-007": "VAT point date",
    "ibt-009": "due date", "ibt-022": "invoice note", "ibt-023": "business process ID",
    "ibt-024": "specification ID", "ibt-025": "original invoice number",
    "ibt-027": "seller name", "ibt-029": "seller ID", "ibt-030": "seller licence / registration number",
    "ibt-031": "seller TRN", "ibt-032": "seller TIN", "ibt-034": "seller Peppol address (TIN)",
    "ibt-035": "seller address line 1", "ibt-037": "seller city", "ibt-039": "seller emirate",
    "ibt-040": "seller country", "ibt-044": "buyer name", "ibt-046": "buyer ID",
    "ibt-047": "buyer licence / registration number", "ibt-048": "buyer TRN",
    "ibt-049": "buyer Peppol address (TIN)", "ibt-050": "buyer address line 1", "ibt-052": "buyer city",
    "ibt-054": "buyer emirate", "ibt-055": "buyer country", "ibt-081": "payment method code",
    "ibt-084": "bank account / IBAN", "ibt-092": "discount amount", "ibt-099": "charge amount",
    "ibt-106": "sum of line amounts", "ibt-107": "total discounts", "ibt-108": "total charges",
    "ibt-109": "total before VAT", "ibt-110": "total VAT", "ibt-112": "total with VAT",
    "ibt-113": "paid amount", "ibt-114": "rounding amount", "ibt-115": "amount due",
    "ibt-116": "taxable amount (VAT breakdown)", "ibt-117": "VAT amount (VAT breakdown)",
    "ibt-118": "VAT category (VAT breakdown)", "ibt-119": "VAT rate (VAT breakdown)",
    "ibt-120": "VAT exemption reason", "ibt-121": "VAT exemption reason code",
    "ibt-126": "line number", "ibt-129": "quantity", "ibt-130": "unit of measure",
    "ibt-131": "line net amount", "ibt-146": "unit price", "ibt-148": "gross unit price",
    "ibt-149": "price base quantity", "ibt-151": "line VAT category", "ibt-152": "line VAT rate",
    "ibt-153": "item name", "ibt-154": "item description", "ibt-157": "item standard ID",
    "ibt-158": "HS code", "btae-02": "transaction type code", "btae-03": "credit note reason",
    "btae-04": "exchange rate", "btae-07": "invoice UUID", "btae-08": "line VAT amount",
    "btae-09": "type of goods (reverse charge)", "btae-10": "line amount payable",
    "btae-11": "buyer licence authority", "btae-12": "seller licence authority",
    "btae-13": "item type (goods/services)", "btae-15": "seller registration ID type",
    "btae-16": "buyer registration ID type", "btae-17": "service accounting code (SAC)",
    "btae-22": "Incoterms",
    "ibg-03": "original invoice reference", "ibg-05": "seller address", "ibg-08": "buyer address",
    "ibg-13": "delivery details", "ibg-14": "invoicing period", "ibg-20": "document discount",
    "ibg-21": "document charge", "ibg-23": "VAT breakdown", "ibg-25": "invoice line",
    "ibg-29": "price details", "ibg-30": "line VAT information", "ibg-31": "item details",
}


def _dejargon(msg: str) -> str:
    msg = re.sub(r"^\[[^\]]+\]\s*-?\s*", "", msg).strip()

    def rep(m: re.Match) -> str:
        key = re.sub(r"\s+", "", m.group(1).lower())
        return "(" + TERMS.get(key, m.group(1)) + ")"

    msg = re.sub(r"[\(\[]\s*((?:ibt|btae|ibg)\s*-\s*\d{2,3})\s*[\)\]]", rep, msg, flags=re.I)
    return msg


@lru_cache(maxsize=1)
def _load() -> tuple[dict, dict]:
    raw = json.loads((RES / "rules_raw.json").read_text())
    plain_path = RES / "rules_plain.json"
    plain = json.loads(plain_path.read_text()) if plain_path.exists() else {}
    return raw, plain


LAYER_LABELS = {
    "ae": "UAE-specific rule", "shared": "International PINT rule",
    "xsd": "XML structure (UBL 2.1 schema)", "precheck": "Data check",
}


def explain(rule_id: str, official_message: str = "", layer: str = "") -> dict:
    raw, plain = _load()
    base = raw.get(rule_id, {})
    official = official_message or base.get("message", "")
    p = plain.get(rule_id, {})
    layer = layer or base.get("layer", "")
    return {
        "rule_id": rule_id,
        "title": p.get("title") or _dejargon(official)[:140],
        "plain": p.get("plain") or _dejargon(official),
        "field": p.get("field", ""),
        "fix": p.get("fix", ""),
        "official": official,
        "layer": layer,
        "layer_label": LAYER_LABELS.get(layer, layer),
        "severity": (base.get("flag") or "fatal"),
    }


def all_rules() -> list[dict]:
    raw, _ = _load()
    return [explain(k) for k in sorted(raw)]
