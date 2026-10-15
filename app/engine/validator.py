"""
Validation engine: UBL 2.1 XSD (lxml) + official PINT AE Schematron rule sets
(pre-compiled XSLT from OpenPeppol, executed with SaxonC-HE).

One Validator instance per process. Saxon objects are not shared across
processes; each uvicorn worker builds its own on first use.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lxml import etree
from saxonche import PySaxonProcessor

log = logging.getLogger("engine.validator")

RES = Path(__file__).resolve().parent.parent / "resources"
NS = {
    "ubl_inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "ubl_cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "svrl": "http://purl.oclc.org/dsdl/svrl",
}
DocType = Literal["invoice", "creditnote"]

MAX_XML_BYTES = int(os.environ.get("MAX_XML_BYTES", str(2 * 1024 * 1024)))  # 2 MiB


@dataclass
class Finding:
    rule_id: str
    severity: str            # "fatal" | "warning"
    layer: str               # "xsd" | "shared" | "ae" | "precheck"
    message: str             # official technical message
    location: str = ""       # XPath of the failing node
    test: str = ""           # the XPath test that failed

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "severity": self.severity, "layer": self.layer,
            "message": self.message, "location": self.location,
        }


@dataclass
class ValidationResult:
    doc_type: DocType | None
    well_formed: bool
    xsd_valid: bool
    findings: list[Finding] = field(default_factory=list)
    timing_ms: float = 0.0

    @property
    def fatal_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "fatal")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return self.well_formed and self.xsd_valid and self.fatal_count == 0


class ValidationInputError(ValueError):
    """Input is not usable (too large, not XML, unknown root)."""


class Validator:
    _instance: "Validator | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "Validator":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = Validator()
        return cls._instance

    def __init__(self) -> None:
        t = time.perf_counter()
        self._lock = threading.Lock()  # SaxonC calls are serialised per process
        self.proc = PySaxonProcessor(license=False)
        xp = self.proc.new_xslt30_processor()
        base = RES / "pint-ae"
        self.xslt = {
            "invoice": {
                "shared": xp.compile_stylesheet(stylesheet_file=str(base / "invoice" / "PINT-UBL-validation-preprocessed.xslt")),
                "ae": xp.compile_stylesheet(stylesheet_file=str(base / "invoice" / "PINT-jurisdiction-aligned-rules.xslt")),
            },
            "creditnote": {
                "shared": xp.compile_stylesheet(stylesheet_file=str(base / "creditnote" / "PINT-UBL-validation-preprocessed.xslt")),
                "ae": xp.compile_stylesheet(stylesheet_file=str(base / "creditnote" / "PINT-jurisdiction-aligned-rules.xslt")),
            },
        }
        self.xsd = {
            "invoice": etree.XMLSchema(etree.parse(str(RES / "ubl" / "maindoc" / "UBL-Invoice-2.1.xsd"))),
            "creditnote": etree.XMLSchema(etree.parse(str(RES / "ubl" / "maindoc" / "UBL-CreditNote-2.1.xsd"))),
        }
        # Hardened parser: no entities, no network, no huge trees.
        self._parser = etree.XMLParser(
            resolve_entities=False, no_network=True, huge_tree=False,
            remove_comments=False, remove_blank_text=False, load_dtd=False,
        )
        log.info("validator ready in %.0f ms (pid %s)", (time.perf_counter() - t) * 1000, os.getpid())

    # ------------------------------------------------------------------ public
    def validate_bytes(self, data: bytes) -> ValidationResult:
        if len(data) > MAX_XML_BYTES:
            raise ValidationInputError(f"XML larger than {MAX_XML_BYTES // 1024} KiB")
        t = time.perf_counter()
        try:
            root = etree.fromstring(data, self._parser)
        except etree.XMLSyntaxError as e:
            res = ValidationResult(doc_type=None, well_formed=False, xsd_valid=False)
            res.findings.append(Finding("xml-syntax", "fatal", "xsd", f"Not well-formed XML: {e.msg}"))
            res.timing_ms = (time.perf_counter() - t) * 1000
            return res
        doc_type = self._doc_type(root)
        if doc_type is None:
            res = ValidationResult(doc_type=None, well_formed=True, xsd_valid=False)
            res.findings.append(Finding(
                "xml-root", "fatal", "xsd",
                f"Root element is <{etree.QName(root).localname}> in namespace '{etree.QName(root).namespace}'. "
                "Expected a UBL 2.1 <Invoice> or <CreditNote>."))
            res.timing_ms = (time.perf_counter() - t) * 1000
            return res
        return self._validate_tree(etree.ElementTree(root), doc_type, t)

    def validate_tree(self, tree: etree._ElementTree, doc_type: DocType) -> ValidationResult:
        return self._validate_tree(tree, doc_type, time.perf_counter())

    # ----------------------------------------------------------------- private
    @staticmethod
    def _doc_type(root: etree._Element) -> DocType | None:
        q = etree.QName(root)
        if q.namespace == NS["ubl_inv"] and q.localname == "Invoice":
            return "invoice"
        if q.namespace == NS["ubl_cn"] and q.localname == "CreditNote":
            return "creditnote"
        return None

    def _validate_tree(self, tree: etree._ElementTree, doc_type: DocType, t0: float) -> ValidationResult:
        res = ValidationResult(doc_type=doc_type, well_formed=True, xsd_valid=True)
        schema = self.xsd[doc_type]
        if not schema.validate(tree):
            res.xsd_valid = False
            for err in schema.error_log:
                res.findings.append(Finding("xsd", "fatal", "xsd", err.message, location=f"line {err.line}"))
            # Schematron on a schema-invalid doc produces noise; still run it so the
            # user sees business errors too, but XSD errors come first.
        xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
        with self._lock:
            node = self.proc.parse_xml(xml_text=xml_bytes.decode("utf-8"))
            for layer in ("shared", "ae"):
                try:
                    svrl = self.xslt[doc_type][layer].transform_to_string(xdm_node=node)
                except Exception as e:  # XPath type errors inside the official rules on odd input
                    msg = " ".join(str(e).split())[:300]
                    log.warning("schematron layer %s crashed: %s", layer, msg)
                    res.findings.append(Finding(
                        "engine-" + layer, "fatal", layer,
                        "The official rule set could not evaluate this document completely "
                        f"(usually a missing VAT rate or amount makes a calculation impossible): {msg}"))
                    continue
                res.findings.extend(self._parse_svrl(svrl, layer))
        res.timing_ms = (time.perf_counter() - t0) * 1000
        return res

    def _parse_svrl(self, svrl_xml: str, layer: str) -> list[Finding]:
        out: list[Finding] = []
        root = etree.fromstring(svrl_xml.encode("utf-8"), self._parser)
        for fa in root.iter("{%s}failed-assert" % NS["svrl"]):
            text = fa.findtext("{%s}text" % NS["svrl"]) or ""
            text = " ".join(text.split())
            out.append(Finding(
                rule_id=fa.get("id", "unknown"),
                severity=(fa.get("flag") or "fatal").lower(),
                layer=layer,
                message=text,
                location=fa.get("location", ""),
                test=fa.get("test", ""),
            ))
        return out
