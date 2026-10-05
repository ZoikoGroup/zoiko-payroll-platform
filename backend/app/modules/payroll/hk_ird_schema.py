"""
modules/payroll/hk_ird_schema.py
--------------------------------
IRD prescribed-schema READINESS for Hong Kong (release gate G2) — engineering
scaffolding only. NO IRD schema is bundled or invented here: the official
BIR56A / IR56B / IR56E / IR56F / IR56G electronic schemas are not available
(docs/HONG_KONG_RELEASE_EVIDENCE/G2/MISSING_ARTIFACTS.md).

When the IRD supplies them, this module lets the deploy / compliance owner:

* register a schema file per form and year of assessment as a SourceArtifact
  (form_number ``HK-IRD-SCHEMA:<FORM>:<YA>``) with its SHA-256 — a changed file
  becomes a NEW artifact that supersedes the previous one (history kept);
* see which forms still have no schema (``readiness``);
* validate a rendered XML document against the registered schema (``validate``)
  — the conformance step of G2/TEST_PROCEDURE.md.

A registered schema is UNREVIEWED until a different Super Admin reviews the
artifact (the same rule as HK-GATE evidence). Nothing here transmits to the IRD.
"""

import hashlib
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll.models import SourceArtifact

FORMS = ("BIR56A", "IR56B", "IR56E", "IR56F", "IR56G")
# Engineering limit (not statutory): an annual return for a large employer is
# far below this; anything larger is refused before parsing (resource guard).
MAX_XML_BYTES = 20 * 1024 * 1024
AGENCY = "Inland Revenue Department"


def _form_number(form: str, ya: str) -> str:
    return f"HK-IRD-SCHEMA:{form}:{ya}"


def registered_schema(db: Session, form: str, ya: str) -> Optional[SourceArtifact]:
    return (db.query(SourceArtifact)
            .filter(SourceArtifact.form_number == _form_number(form, ya), SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).first())


def register_schema(db: Session, form: str, ya: str, path: str, actor_id: Optional[int] = None,
                    source_url: Optional[str] = None) -> SourceArtifact:
    form = (form or "").upper()
    if form not in FORMS:
        raise BadRequestException(f"unknown IRD form {form!r} (expected one of {', '.join(FORMS)})")
    file = Path(path)
    if not file.is_file():
        raise BadRequestException(f"schema file not found: {path}")
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    current = registered_schema(db, form, ya)
    if current is not None and current.checksum_sha256 == digest:
        return current                                   # idempotent: same file already registered
    artifact = SourceArtifact(agency=AGENCY, title=f"IRD electronic schema — {form} YA {ya} (registered, unreviewed)",
                              form_number=_form_number(form, ya), source_url=source_url, checksum_sha256=digest,
                              file_path=str(file), original_filename=file.name, created_by_id=actor_id)
    db.add(artifact)
    db.flush()
    if current is not None:
        current.superseded_by_id = artifact.id           # a changed schema supersedes; history is kept
    db.commit()
    return artifact


def _parser():
    """Hardened XML parser: no entity expansion, no network / external DTD
    access (XXE / entity-expansion safe) for schema files and documents."""
    from lxml import etree

    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def _reviewed(art: SourceArtifact) -> bool:
    """Four-eyes: reviewed by someone other than the registrant (the HK-GATE rule)."""
    return bool(art.reviewer_id) and art.reviewer_id != art.created_by_id


def readiness(db: Session, ya: str) -> list:
    out = []
    for form in FORMS:
        art = registered_schema(db, form, ya)
        out.append({"form": form, "yearOfAssessment": ya,
                    "status": "EXTERNAL SCHEMA REQUIRED" if art is None else
                    ("REGISTERED — REVIEWED" if _reviewed(art) else "REGISTERED — AWAITING REVIEW"),
                    "sha256": None if art is None else art.checksum_sha256,
                    "artifactId": None if art is None else art.id})
    return out


def validate(xml_bytes: bytes, schema_path: str) -> list:
    """Validation errors of an XML document against an XSD ([] = valid)."""
    from lxml import etree

    if len(xml_bytes or b"") > MAX_XML_BYTES:
        return [f"document exceeds the {MAX_XML_BYTES // (1024 * 1024)} MB limit — refused before parsing"]
    parser = _parser()
    schema = etree.XMLSchema(etree.parse(schema_path, parser))
    try:
        doc = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as exc:
        return [f"not well-formed XML: {exc}"]
    docinfo = doc.getroottree().docinfo
    if docinfo.internalDTD is not None or docinfo.doctype:
        # An IRD return never needs a DOCTYPE; entity declarations are refused
        # outright (XXE / entity expansion), not merely left unresolved.
        return ["a DOCTYPE / entity declaration is not accepted in an IRD submission"]
    try:
        if schema.validate(doc):
            return []
    except etree.XMLSchemaValidateError as exc:
        return [f"schema validation failed: {exc}"]
    return [f"line {e.line}: {e.message}" for e in schema.error_log]
