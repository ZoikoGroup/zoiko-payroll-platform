"""
modules/payroll/mexico_cfdi_schema.py
-------------------------------------
Pinned CFDI 4.0 + Complemento de Nómina 1.2 schema sets (ZP-MX-ENG-001 Phase
11a, MEXICO_PHASE_11_PLAN.md §4.1, decision D2).

A set lives in ``mx_cfdi_schemas/<set_id>/``: the SAT XSDs byte-for-byte, the
catalog extract and ``manifest.json`` (built by scripts/mx_build_cfdi_schema_set.py
from docs/mexico/sources/, S28 + S30). Before anything uses a set it is verified
against its manifest; a changed or missing file makes the whole set unusable.

Validation never touches the network: imports resolve only to files of the same
pinned set, and any other location is refused.
"""

from __future__ import annotations

import functools
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Iterator, List, Optional

ROOT = Path(__file__).resolve().parent / "mx_cfdi_schemas"
_SET_ID = re.compile(r"^[a-z0-9_]{3,40}$")
SAT_BASE = "http://www.sat.gob.mx/"
MAIN_SCHEMAS = ("cfdv40.xsd", "nomina12.xsd")


class SchemaSetError(Exception):
    """A pinned set that cannot be used (unknown, changed, incomplete)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir(set_id: str) -> Path:
    if not isinstance(set_id, str) or not _SET_ID.match(set_id):
        raise SchemaSetError(f"unknown schema set {set_id!r}")
    path = ROOT / set_id
    if not (path / "manifest.json").is_file():
        raise SchemaSetError(f"unknown schema set {set_id!r}")
    return path


def available_sets() -> List[str]:
    if not ROOT.is_dir():
        return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and _SET_ID.match(p.name)
                  and (p / "manifest.json").is_file())


def manifest(set_id: str) -> dict:
    return json.loads((_dir(set_id) / "manifest.json").read_text(encoding="utf-8"))


def problems(set_id: str) -> List[str]:
    """Every reason the set cannot be used (empty = verified)."""
    try:
        path, m = _dir(set_id), manifest(set_id)
    except (SchemaSetError, ValueError) as exc:
        return [str(exc)]
    out = []
    for name, expected in sorted((m.get("files") or {}).items()):
        f = path / name
        if not f.is_file():
            out.append(f"{name} is missing")
        elif _sha(f.read_bytes()) != expected:
            out.append(f"{name} differs from its manifest checksum")
    cat = path / "catalogs.json.gz"
    if not cat.is_file():
        out.append("catalogs.json.gz is missing")
    elif _sha(cat.read_bytes()) != m.get("catalogsSha256"):
        out.append("catalogs.json.gz differs from its manifest checksum")
    files = m.get("files") or {}
    expected = _sha("".join(f"{k}:{files[k]}\n" for k in sorted(files)).encode())
    if m.get("xsdChecksum") != expected:
        out.append("the manifest's xsdChecksum does not match its files")
    for main in MAIN_SCHEMAS:
        if main not in files:
            out.append(f"{main} is not in the set")
    return out


def verify(set_id: str) -> dict:
    found = problems(set_id)
    if found:
        raise SchemaSetError(f"schema set {set_id!r} cannot be used: " + "; ".join(found))
    return manifest(set_id)


def _resolver_for(path: Path):
    from lxml import etree

    names = set(manifest(path.name).get("files") or {})

    class PinnedResolver(etree.Resolver):
        """Maps SAT schema URLs (and the set's own files) to the pinned copies;
        refuses everything else, so validation can never fetch."""

        def resolve(self, url, pubid, context):
            name = (url or "").replace("\\", "/").rsplit("/", 1)[-1]
            local = url and not url.startswith(("http://", "https://", "ftp://", "file:"))
            if name in names and (url.startswith(SAT_BASE) or url.startswith("zoiko-pinned:")
                                  or (local and Path(url).resolve().parent == path.resolve())):
                return self.resolve_filename(str(path / name), context)
            raise SchemaSetError(f"refused a schema import outside the pinned set: {url}")

    return PinnedResolver()


@functools.lru_cache(maxsize=8)
def _compiled(set_id: str, main: str, xsd_checksum: str):
    from lxml import etree

    path = _dir(set_id)
    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    parser.resolvers.add(_resolver_for(path))
    with open(path / main, "rb") as fh:
        doc = etree.parse(fh, parser, base_url=f"zoiko-pinned:{set_id}/{main}")
    return etree.XMLSchema(doc)


def schema(set_id: str, main: str):
    """The compiled XMLSchema for one main schema of a verified set."""
    if main not in MAIN_SCHEMAS:
        raise SchemaSetError(f"{main} is not a main schema")
    m = verify(set_id)
    return _compiled(set_id, main, m["xsdChecksum"])


def schema_locations(set_id: str) -> dict:
    """{namespace: official location} of the two main schemas (Phase 11b; from
    the manifest, which read them from the XSDs and SOURCES_MANIFEST.csv)."""
    found = verify(set_id).get("schemaLocations") or {}
    if len(found) != len(MAIN_SCHEMAS):
        raise SchemaSetError(f"schema set {set_id!r} has no schema locations — rebuild it")
    return dict(found)


@functools.lru_cache(maxsize=8)
def _combined(set_id: str, xsd_checksum: str):
    from lxml import etree

    imports = "".join(f'<xs:import namespace="{ns}" schemaLocation="zoiko-pinned:{set_id}/{loc.rsplit("/", 1)[-1]}"/>'
                      for ns, loc in sorted(schema_locations(set_id).items()))
    wrapper = f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{imports}</xs:schema>'.encode()
    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    parser.resolvers.add(_resolver_for(_dir(set_id)))
    return etree.XMLSchema(etree.fromstring(wrapper, parser, base_url=f"zoiko-pinned:{set_id}/combined.xsd"))


def combined_schema(set_id: str):
    """One XMLSchema knowing both CFDI 4.0 and Nómina 1.2: the Complemento
    element of cfdv40.xsd validates its content strictly (xs:any), so a payroll
    CFDI validates only against both."""
    m = verify(set_id)
    return _combined(set_id, m["xsdChecksum"])


def catalogs(set_id: str) -> dict:
    """{catalog: {"meta": {...}, "entries": [[code, description, valid_from, valid_to, attributes], ...]}}"""
    verify(set_id)
    with gzip.open(_dir(set_id) / "catalogs.json.gz", "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))["catalogs"]


def catalog_rows(set_id: str, only: Optional[set] = None) -> Iterator[tuple]:
    """(catalog_name, code, description, valid_from, valid_to, attributes) for every entry."""
    for name, data in sorted(catalogs(set_id).items()):
        if only is not None and name not in only:
            continue
        for code, description, valid_from, valid_to, attributes in data["entries"]:
            yield name, code, description, valid_from, valid_to, attributes


def set_view(set_id: str) -> dict:
    found = problems(set_id)
    m = {} if found and not (ROOT / set_id / "manifest.json").is_file() else manifest(set_id)
    return {"setId": set_id, "verified": not found, "problems": found, "cfdiVersion": m.get("cfdiVersion"),
            "complementVersion": m.get("complementVersion"), "catalogRelease": m.get("catalogRelease"),
            "xsdChecksum": m.get("xsdChecksum"), "catalogCounts": m.get("catalogCounts") or {},
            "caseNormalised": m.get("caseNormalised") or [],
            "sources": [{"file": k, **v} for k, v in sorted((m.get("sources") or {}).items())]}
