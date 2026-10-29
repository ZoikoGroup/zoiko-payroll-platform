"""Mexico Phase 11a — the pinned SAT schema set (MEXICO_PHASE_11_PLAN.md §4.1,
D2): the files match their manifest, the CFDI 4.0 and Nómina 1.2 schemas
compile with no network, an import outside the set is refused, a changed file
makes the set unusable, and every extracted catalog code is one SAT's own XSD
accepts. Nothing here types a SAT value: expectations come from the files."""

import csv
import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

SET_ID = "sat_2026_08"
BACKEND = Path(__file__).resolve().parents[1]
SOURCES = BACKEND.parent / "docs" / "mexico" / "sources"
XS = "{http://www.w3.org/2001/XMLSchema}"


def _S():
    from app.modules.payroll import mexico_cfdi_schema

    return mexico_cfdi_schema


def _enums(xsd: Path) -> dict:
    from lxml import etree

    out = {}
    for st in etree.parse(str(xsd)).iter(XS + "simpleType"):
        values = {e.get("value") for e in st.iter(XS + "enumeration")}
        if values and st.get("name"):
            out[st.get("name")] = values
    return out


def test_the_pinned_set_verifies_and_both_schemas_compile_offline():
    S = _S()
    assert SET_ID in S.available_sets()
    assert S.problems(SET_ID) == []
    m = S.verify(SET_ID)
    assert (m["cfdiVersion"], m["complementVersion"]) == ("4.0", "1.2")
    for main in S.MAIN_SCHEMAS:
        assert S.schema(SET_ID, main) is not None


def test_the_xsd_files_are_stored_byte_for_byte():
    """git must not touch line endings (mx_cfdi_schemas/.gitattributes: -text)."""
    root = BACKEND / "app" / "modules" / "payroll" / "mx_cfdi_schemas"
    assert "* -text" in (root / ".gitattributes").read_text(encoding="utf-8")
    m = _S().manifest(SET_ID)
    for name, sha in m["files"].items():
        assert hashlib.sha256((root / SET_ID / name).read_bytes()).hexdigest() == sha, name


def test_the_manifest_names_the_saved_sources_by_their_recorded_hashes():
    with (SOURCES / "SOURCES_MANIFEST.csv").open(newline="", encoding="utf-8") as fh:
        recorded = {r["file"]: r for r in csv.DictReader(fh)}
    for name, source in _S().manifest(SET_ID)["sources"].items():
        assert recorded[name]["sha256"] == source["sha256"], name
        assert recorded[name]["code"] in ("S28", "S30")


def test_every_extracted_code_is_accepted_by_the_sat_xsd_of_its_catalog():
    S = _S()
    folder = S.ROOT / SET_ID
    enums = {**_enums(folder / "catCFDI.xsd"), **_enums(folder / "catNomina.xsd")}
    catalogs = S.catalogs(SET_ID)
    assert {k: len(v["entries"]) for k, v in catalogs.items()} == S.manifest(SET_ID)["catalogCounts"]
    checked = 0
    for name, data in catalogs.items():
        if name not in enums:
            continue
        codes = {e[0] for e in data["entries"]}
        assert codes <= enums[name], (name, sorted(codes - enums[name])[:5])
        checked += 1
    assert checked >= 25
    # the Nómina 1.2 workbook and catNomina.xsd list exactly the same codes
    for name in ("c_TipoPercepcion", "c_TipoDeduccion", "c_TipoOtroPago", "c_TipoNomina", "c_PeriodicidadPago"):
        assert {e[0] for e in catalogs[name]["entries"]} == enums[name], name


def test_validation_never_fetches_an_import_outside_the_pinned_set(tmp_path, monkeypatch):
    from lxml import etree

    S = _S()
    resolver = S._resolver_for(S.ROOT / SET_ID)
    parser = etree.XMLParser(no_network=True)
    parser.resolvers.add(resolver)
    evil = (b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            b'<xs:import namespace="urn:x" schemaLocation="https://example.com/evil.xsd"/></xs:schema>')
    with pytest.raises(Exception):
        etree.XMLSchema(etree.parse(io.BytesIO(evil), parser, base_url="zoiko-pinned:sat_2026_08/x.xsd"))


def _copy_set(tmp_path, monkeypatch):
    S = _S()
    root = tmp_path / "mx_cfdi_schemas"
    shutil.copytree(S.ROOT / SET_ID, root / SET_ID)
    monkeypatch.setattr(S, "ROOT", root)
    S._compiled.cache_clear()
    return S, root / SET_ID


def test_a_changed_file_makes_the_set_unusable(tmp_path, monkeypatch):
    S, folder = _copy_set(tmp_path, monkeypatch)
    xsd = folder / "nomina12.xsd"
    xsd.write_bytes(xsd.read_bytes().replace(b"\r\n", b"\n"))             # what a line-ending rewrite would do
    assert S.problems(SET_ID) == ["nomina12.xsd differs from its manifest checksum"]
    with pytest.raises(S.SchemaSetError, match="cannot be used"):
        S.schema(SET_ID, "nomina12.xsd")
    with pytest.raises(S.SchemaSetError):
        S.catalogs(SET_ID)


def test_a_changed_catalog_extract_or_manifest_is_detected(tmp_path, monkeypatch):
    S, folder = _copy_set(tmp_path, monkeypatch)
    data = json.loads(gzip.decompress((folder / "catalogs.json.gz").read_bytes()))
    data["catalogs"]["c_TipoNomina"]["entries"].append(["X", "SYNTHETIC", None, None, None])
    (folder / "catalogs.json.gz").write_bytes(gzip.compress(json.dumps(data).encode()))
    assert "catalogs.json.gz differs from its manifest checksum" in S.problems(SET_ID)
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    m["xsdChecksum"] = "0" * 64
    (folder / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert "the manifest's xsdChecksum does not match its files" in S.problems(SET_ID)


def test_unknown_or_malformed_set_ids_are_refused():
    S = _S()
    for bad in ("../sat_2026_08", "nope", "", "SAT", None):
        assert S.problems(bad)
        with pytest.raises(S.SchemaSetError):
            S.verify(bad)


def test_the_generator_rebuilds_the_identical_set_from_the_saved_sources(tmp_path, monkeypatch):
    """Only where the (gitignored) source files and xlrd are present locally."""
    pytest.importorskip("xlrd")
    m = _S().manifest(SET_ID)
    if not all((SOURCES / name).is_file() for name in m["sources"]):
        pytest.skip("SAT source files are not present (docs/mexico/sources is not in git)")
    from scripts import mx_build_cfdi_schema_set as gen

    monkeypatch.setattr(gen, "OUT_ROOT", tmp_path)
    out = gen.build(SET_ID, m["catalogRelease"])
    original = _S().ROOT / SET_ID
    for f in sorted(original.iterdir()):
        assert (out / f.name).read_bytes() == f.read_bytes(), f.name
