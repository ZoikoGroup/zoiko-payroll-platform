"""
scripts/mx_build_cfdi_schema_set.py
-----------------------------------
Builds a pinned CFDI 4.0 + Complemento de Nómina 1.2 schema set (ZP-MX-ENG-001
Phase 11a, MEXICO_PHASE_11_PLAN.md §4.1, decision D2) from the SAT sources saved
in docs/mexico/sources/ (S28, S30 — SOURCES_MANIFEST.csv):

  app/modules/payroll/mx_cfdi_schemas/<set_id>/
    cfdv40.xsd nomina12.xsd tdCFDI.xsd catCFDI.xsd catNomina.xsd   byte-identical copies
    catalogs.json.gz                                               the catalogs the builder uses
    manifest.json                                                  hashes, sources, counts

Nothing is typed by hand: every catalog row comes from the SAT workbooks, every
code is spelled as SAT's own XSD enumeration spells it, and a workbook code the
XSD does not contain stops the build. Each source file must match the SHA-256
recorded in SOURCES_MANIFEST.csv. Deterministic (re-running gives identical bytes).

Development tool only (reads .xls): needs `pip install xlrd==2.0.1`.

    python -m scripts.mx_build_cfdi_schema_set --set-id sat_2026_08
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SOURCES = BACKEND.parent / "docs" / "mexico" / "sources"
OUT_ROOT = BACKEND / "app" / "modules" / "payroll" / "mx_cfdi_schemas"
XS = "{http://www.w3.org/2001/XMLSchema}"

# Pinned file name -> its source file in docs/mexico/sources/.
XSD_FILES = {
    "cfdv40.xsd": "S30_SAT_cfdv40.xsd",
    "tdCFDI.xsd": "S30_SAT_tdCFDI.xsd",
    "catCFDI.xsd": "S30_SAT_catCFDI.xsd",
    "nomina12.xsd": "S28_SAT_nomina12.xsd",
    "catNomina.xsd": "S28_SAT_catNomina.xsd",
}
WORKBOOKS = {"S30_SAT_catCFDI.xls": "catCFDI.xsd", "S28_SAT_catNomina.xls": "catNomina.xsd"}

# The catalogs a payroll CFDI uses (the comprobante envelope, issuer, receiver
# and the nómina complement). Customs, colonia, localidad and tax-rate
# catalogs are not extracted: a payroll receipt carries none of them.
NOMINA_CATALOGS = ("c_Banco", "c_OrigenRecurso", "c_PeriodicidadPago", "c_TipoContrato", "c_TipoDeduccion",
                   "c_TipoHoras", "c_TipoIncapacidad", "c_TipoJornada", "c_TipoNomina", "c_TipoOtroPago",
                   "c_TipoPercepcion", "c_TipoRegimen", "c_RiesgoPuesto")
CFDI_CATALOGS = ("c_FormaPago", "c_Moneda", "c_TipoDeComprobante", "c_Exportacion", "c_MetodoPago", "c_Periodicidad",
                 "c_Meses", "c_TipoRelacion", "c_RegimenFiscal", "c_Pais", "c_UsoCFDI", "c_ClaveProdServ",
                 "c_ClaveUnidad", "c_ObjetoImp", "c_Estado", "c_CodigoPostal")
DESCRIPTION_HEADERS = ("descripción", "nombre", "nombre del estado")
DESCRIPTION_MAX = 500          # PayrollMxCfdiCatalogEntry.description


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_hashes() -> dict:
    with (SOURCES / "SOURCES_MANIFEST.csv").open(newline="", encoding="utf-8") as fh:
        return {r["file"]: r for r in csv.DictReader(fh)}


def verified_source(name: str, recorded: dict) -> bytes:
    row = recorded.get(name)
    if row is None:
        raise SystemExit(f"{name} is not in SOURCES_MANIFEST.csv")
    data = (SOURCES / name).read_bytes()
    if sha256(data) != row["sha256"]:
        raise SystemExit(f"{name}: SHA-256 differs from SOURCES_MANIFEST.csv — refusing to build")
    return data


def enumerations(xsd: bytes) -> dict:
    from lxml import etree

    tree = etree.parse(io.BytesIO(xsd))
    out = {}
    for st in tree.iter(XS + "simpleType"):
        values = [e.get("value") for e in st.iter(XS + "enumeration")]
        if values and st.get("name"):
            out[st.get("name")] = values
    return out


def _target_namespace(path: Path) -> str:
    from lxml import etree

    return etree.parse(str(path)).getroot().get("targetNamespace")


def _cell(value):
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value.strip() if isinstance(value, str) else value


def _iso(book, value):
    import xlrd

    if value in ("", None):
        return None
    return xlrd.xldate.xldate_as_datetime(float(value), book.datemode).date().isoformat()


NORMALISED = []               # (catalog, workbook spelling, XSD spelling) — recorded in the manifest
DUPLICATE_HEADERS = []        # (sheet, header, occurrence) — a header SAT repeats; recorded in the manifest


def _canonical(code, enum: list, catalog: str):
    """SAT's own spelling of a workbook code (the XSD enumeration value). A
    code differing only in letter case from exactly one XSD value takes the
    XSD spelling (the XSD is what validation enforces) and is recorded."""
    if enum is None:
        return str(code)
    text = str(code)
    if text in enum:
        return text
    if isinstance(code, int):
        matches = [v for v in enum if v.isdigit() and int(v) == code]
        if len(matches) == 1:
            return matches[0]
    folded = [v for v in enum if v.casefold() == text.casefold()]
    if len(folded) == 1:
        NORMALISED.append([catalog, text, folded[0]])
        return folded[0]
    raise SystemExit(f"{catalog}: workbook code {code!r} is not in the XSD enumeration — refusing to build")


def _header_index(sheet, catalog: str) -> int:
    for i in range(min(12, sheet.nrows)):
        if str(sheet.cell_value(i, 0)).strip().lower() == catalog.lower():
            return i
    raise SystemExit(f"{catalog}: header row not found in sheet {sheet.name}")


def _meta_value(book, label: str, value):
    """Catalog header values as SAT shows them: dates as ISO dates, version
    numbers as written ("4.0", not 4)."""
    if isinstance(value, float):
        if "fecha" in label.lower():
            return _iso(book, value) if value > 0 else None
        return str(value)
    return value.strip() if isinstance(value, str) else value


def _version_meta(book, sheet, header: int) -> dict:
    for i in range(header):
        labels = [" ".join(str(v).split()) for v in sheet.row_values(i)]
        if any(lbl.lower().startswith("versión") for lbl in labels) and i + 1 < header:
            values = sheet.row_values(i + 1)
            return {lbl: _meta_value(book, lbl, values[j]) for j, lbl in enumerate(labels)
                    if lbl and j < len(values) and values[j] not in ("", None)}
    return {}


def _columns(sheet, header: int) -> tuple:
    """Column names; a second header row (col 0 empty) qualifies the columns under it."""
    top = [str(v).strip() for v in sheet.row_values(header)]
    sub = [str(v).strip() for v in sheet.row_values(header + 1)] if header + 1 < sheet.nrows else []
    has_sub = bool(sub) and not sub[0] and any(sub)
    names, last, seen = [], "", {}
    for j in range(max(len(top), len(sub))):
        t = top[j] if j < len(top) else ""
        last = t or last
        s = sub[j] if has_sub and j < len(sub) else ""
        name = f"{last}/{s}" if s else t
        if name:
            # A header SAT repeats keeps every column: the repeat gets a
            # positional suffix ("#2") instead of overwriting the first.
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                DUPLICATE_HEADERS.append([sheet.name, name, seen[name]])
                name = f"{name} #{seen[name]}"
        names.append(name)
    return names, (header + 2 if has_sub else header + 1)


def read_catalog(book, sheet_names: list, catalog: str, enum) -> dict:
    entries, meta = [], {}
    for sheet_name in sheet_names:
        sheet = book.sheet_by_name(sheet_name)
        header = _header_index(sheet, catalog)
        meta = meta or _version_meta(book, sheet, header)
        names, first = _columns(sheet, header)
        lowered = [n.lower() for n in names]
        start = next((j for j, n in enumerate(lowered) if "inicio" in n and "vigencia" in n), None)
        end = next((j for j, n in enumerate(lowered) if "fin" in n and "vigencia" in n), None)
        desc = next((j for j, n in enumerate(lowered) if n in DESCRIPTION_HEADERS), None)
        for i in range(first, sheet.nrows):
            row = sheet.row_values(i)
            raw = _cell(row[0])
            if raw in ("", None):
                continue
            if isinstance(raw, str) and raw.startswith("Continúa en "):    # a split sheet's continuation note
                continue
            code = _canonical(raw, enum, catalog)
            attrs = {}
            for j, name in enumerate(names):
                if j in (0, start, end, desc) or not name or j >= len(row):
                    continue
                value = _cell(row[j])
                if value not in ("", None):
                    attrs[name] = value
            if desc is not None and str(row[desc]).strip():
                description = str(row[desc]).strip()
            else:                                   # c_CodigoPostal has no description column
                description = " · ".join(f"{k} {v}" for k, v in attrs.items() if k.startswith("c_")) or code
            if len(description) > DESCRIPTION_MAX:
                raise SystemExit(f"{catalog} {code}: description longer than {DESCRIPTION_MAX}")
            entries.append([code, description, _iso(book, row[start]) if start is not None else None,
                            _iso(book, row[end]) if end is not None else None, attrs or None])
    entries.sort(key=lambda e: (e[0], e[2] or ""))
    return {"meta": meta, "entries": entries}


def build(set_id: str, catalog_release: str) -> Path:
    import xlrd

    recorded = source_hashes()
    out = OUT_ROOT / set_id
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():                      # empty it (the folder itself may be open in a shell)
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    files, enums = {}, {}
    for pinned, source in XSD_FILES.items():
        data = verified_source(source, recorded)
        (out / pinned).write_bytes(data)
        files[pinned] = sha256(data)
        enums[pinned] = enumerations(data)
    catalogs = {}
    for workbook, xsd in WORKBOOKS.items():
        data = verified_source(workbook, recorded)
        book = xlrd.open_workbook(file_contents=data, on_demand=True)
        wanted = NOMINA_CATALOGS if xsd == "catNomina.xsd" else CFDI_CATALOGS
        for catalog in wanted:
            sheets = [s for s in book.sheet_names() if s == catalog or s.startswith(catalog + "_Parte_")]
            if not sheets:
                raise SystemExit(f"{workbook}: no sheet for {catalog}")
            catalogs[catalog] = read_catalog(book, sheets, catalog, enums[xsd].get(catalog))
        book.release_resources()
    payload = json.dumps({"setId": set_id, "catalogs": catalogs}, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(payload)
    (out / "catalogs.json.gz").write_bytes(buf.getvalue())
    manifest = {
        "setId": set_id, "cfdiVersion": "4.0", "complementVersion": "1.2", "catalogRelease": catalog_release,
        "files": files, "catalogsSha256": sha256(buf.getvalue()),
        "xsdChecksum": sha256("".join(f"{k}:{files[k]}\n" for k in sorted(files)).encode()),
        "catalogCounts": {k: len(v["entries"]) for k, v in sorted(catalogs.items())},
        "sources": {name: {"code": recorded[name]["code"], "sha256": recorded[name]["sha256"],
                           "status": recorded[name]["status"]}
                    for name in sorted(list(XSD_FILES.values()) + list(WORKBOOKS))},
        "generator": "scripts/mx_build_cfdi_schema_set.py",
        # Phase 11b: xsi:schemaLocation pairs — the namespace read from each main
        # schema, the location from its official URL in SOURCES_MANIFEST.csv.
        "schemaLocations": {_target_namespace(out / main): recorded[XSD_FILES[main]]["url"]
                            for main in ("cfdv40.xsd", "nomina12.xsd")},
        "caseNormalised": sorted(NORMALISED),
        "duplicateHeaders": sorted(DUPLICATE_HEADERS),
    }
    # The two versions are read from the schemas themselves, never assumed.
    import re

    cfdi = re.search(rb'name="Version"[^>]*fixed="([^"]+)"', (out / "cfdv40.xsd").read_bytes())
    nomina = re.search(rb'name="Version"[^>]*fixed="([^"]+)"', (out / "nomina12.xsd").read_bytes())
    if not cfdi or not nomina or (cfdi.group(1), nomina.group(1)) != (b"4.0", b"1.2"):
        raise SystemExit("cfdv40.xsd / nomina12.xsd do not declare Version 4.0 / 1.2")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--catalog-release", required=True,
                        help="the workbook revisions, e.g. 'catCFDI_V_4_20260731 + catNomina (2022-08)'")
    args = parser.parse_args(argv)
    out = build(args.set_id, args.catalog_release)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, count in manifest["catalogCounts"].items():
        print(f"{name:22} {count}")
    print("xsdChecksum", manifest["xsdChecksum"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
