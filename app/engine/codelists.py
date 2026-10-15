"""Code sets loaded from the official genericode files."""
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET

RES = Path(__file__).resolve().parent.parent / "resources" / "pint-ae" / "codelist"
NS = "{http://docs.oasis-open.org/codelist/ns/genericode/1.0/}"


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    root = ET.parse(RES / f"{name}.gc").getroot()
    for r in root.iter(NS + "Row"):
        vals = {}
        for v in r.findall(NS + "Value"):
            sv = v.find(NS + "SimpleValue")
            vals[v.get("ColumnRef")] = (sv.text or "").strip() if sv is not None else ""
        code = vals.get("code") or vals.get("id")
        if code:
            out[code] = vals.get("name", "")
    return out


UNIT_CODES = load("UNECERec20")
PAYMENT_CODES = load("UNCL4461")
COUNTRY_CODES = load("ISO3166")
CURRENCY_CODES = load("ISO4217")
