"""Mexico Phase 11a — loading a pinned SAT set into a CFDI schema release, the
catalog-name fix for canonical classifications, and the system-concept
mappings (maker-checker, D4). SYNTHETIC users; SAT codes come only from the
pinned set (never typed here except as values read back from it)."""

import gzip
import json
import shutil

import pytest

from tests import test_mexico_pilot as tp

SA_A, SA_B = tp.SA_A, tp.SA_B
SET_ID = "sat_2026_08"


def _C():
    from app.modules.payroll import mexico_cfdi_catalog_service

    return mexico_cfdi_catalog_service


def _svc():
    from app.modules.payroll import mexico_service

    return mexico_service


def _release(db, actor=SA_A, **over):
    data = {"cfdi_version": "4.0", "complement_version": "1.2", **over}
    return _svc().create_release(db, data, actor.id)


@pytest.fixture()
def mini_set(tmp_path, monkeypatch):
    """The real set with its catalog extract cut to a few rows per catalog
    (manifest recomputed), so most tests load in milliseconds."""
    import hashlib

    from app.modules.payroll import mexico_cfdi_schema as S

    root = tmp_path / "mx_cfdi_schemas"
    shutil.copytree(S.ROOT / SET_ID, root / SET_ID)
    folder = root / SET_ID
    data = json.loads(gzip.decompress((folder / "catalogs.json.gz").read_bytes()))
    for name, cat in data["catalogs"].items():
        cat["entries"] = cat["entries"][:3]
    raw = gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    (folder / "catalogs.json.gz").write_bytes(raw)
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    m["catalogsSha256"] = hashlib.sha256(raw).hexdigest()
    m["catalogCounts"] = {k: len(v["entries"]) for k, v in data["catalogs"].items()}
    (folder / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", root)
    S._compiled.cache_clear()
    return data["catalogs"]


def _first(catalogs, name):
    return catalogs[name]["entries"][0][0]


def test_the_full_pinned_set_loads_into_an_empty_draft_release(db):
    from app.modules.payroll import mexico_cfdi_schema as S
    from app.modules.payroll.models import TaxConfigurationAudit as A

    rel = _release(db)
    out = _C().load_pinned_set(db, rel["id"], SET_ID, SA_A.id)
    m = S.manifest(SET_ID)
    assert out["catalogCounts"] == m["catalogCounts"]
    assert out["entries"] == sum(m["catalogCounts"].values())
    assert (out["revision"], out["xsdChecksum"]) == (SET_ID, m["xsdChecksum"])
    audit = db.query(A).filter(A.entity_type == "mx_cfdi_schema_release", A.action == "load_pinned_set").one()
    assert audit.new_value["entries"] == out["entries"]
    page = _C().list_entries(db, rel["id"], catalog="c_TipoNomina")
    assert page["total"] == m["catalogCounts"]["c_TipoNomina"]
    assert {e["catalogName"] for e in page["entries"]} == {"c_TipoNomina"}
    capped = _C().list_entries(db, rel["id"], catalog="c_CodigoPostal", limit=5000)
    assert capped["limit"] == 1000 and len(capped["entries"]) == 1000 and capped["total"] > 1000


def test_loading_is_refused_unless_the_release_is_an_empty_draft_of_the_same_versions(db, mini_set):
    from app.core.exceptions import BadRequestException

    C = _C()
    other = _release(db, cfdi_version="3.3")
    with pytest.raises(BadRequestException, match="CFDI 3.3"):
        C.load_pinned_set(db, other["id"], SET_ID, SA_A.id)
    rel = _release(db)
    with pytest.raises(BadRequestException, match="cannot be used|unknown schema set"):
        C.load_pinned_set(db, rel["id"], "no_such_set", SA_A.id)
    C.load_pinned_set(db, rel["id"], SET_ID, SA_A.id)
    with pytest.raises(BadRequestException, match="already has catalog entries"):
        C.load_pinned_set(db, rel["id"], SET_ID, SA_A.id)
    _svc().transition_release(db, rel["id"], "submit", SA_A.id)
    with pytest.raises(BadRequestException, match="only into a Draft"):
        C.load_pinned_set(db, rel["id"], SET_ID, SA_A.id)


def test_a_tampered_set_is_refused_and_nothing_is_loaded(db, mini_set):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_cfdi_schema as S

    xsd = S.ROOT / SET_ID / "cfdv40.xsd"
    xsd.write_bytes(xsd.read_bytes() + b" ")
    rel = _release(db)
    with pytest.raises(BadRequestException, match="cfdv40.xsd differs"):
        _C().load_pinned_set(db, rel["id"], SET_ID, SA_A.id)
    assert _C().catalog_counts(db, rel["id"]) == {}


def test_a_canonical_classification_needs_its_code_in_its_own_node_catalog(db):
    """Before 11a any catalog matched, so a PERCEPCION row passed with a code
    SAT lists only as a deduction. The code is read from the pinned set."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_cfdi_schema as S
    from tests.test_mexico_classifications import _data

    cats = S.catalogs(SET_ID)
    perceptions = {e[0] for e in cats["c_TipoPercepcion"]["entries"]}
    deduction_only = sorted({e[0] for e in cats["c_TipoDeduccion"]["entries"]} - perceptions)[0]
    svc = _svc()
    rel = _release(db)
    svc.add_catalog_entry(db, rel["id"], {"catalog_name": "c_TipoDeduccion", "code": deduction_only,
                                          "description": "from the pinned set"}, SA_A.id)
    svc.transition_release(db, rel["id"], "submit", SA_A.id)
    svc.transition_release(db, rel["id"], "approve", SA_B.id)
    wrong = svc.create_classification(db, _data(cfdi_concept_code=deduction_only), SA_A.id)        # PERCEPCION
    with pytest.raises(BadRequestException, match="SAT concept code"):
        svc.approve_classification(db, wrong["id"], SA_B.id)
    right = svc.create_classification(db, _data(earning_code="DESC", cfdi_node_type="DEDUCCION",
                                                cfdi_concept_code=deduction_only), SA_A.id)
    assert svc.approve_classification(db, right["id"], SA_B.id)["status"] == "ACTIVE"


def test_system_concepts_are_four_eyes_cited_and_checked_against_the_release(db, mini_set):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxConfigurationAudit as A

    C = _C()
    rel = _release(db)
    deduction = _first(mini_set, "c_TipoDeduccion")
    good = {"release_id": rel["id"], "concept_key": "ISR_WITHHELD", "node_type": "DEDUCCION", "sat_code": deduction,
            "source_ref": "S28 c_TipoDeduccion (SYNTHETIC test citation)"}
    with pytest.raises(BadRequestException, match="not in c_TipoDeduccion"):
        C.propose_system_concept(db, good, SA_A.id)                         # the release is still empty
    C.load_pinned_set(db, rel["id"], SET_ID, SA_A.id)
    with pytest.raises(BadRequestException, match="conceptKey"):
        C.propose_system_concept(db, {**good, "concept_key": "BONUS"}, SA_A.id)
    with pytest.raises(BadRequestException, match="sourceRef"):
        C.propose_system_concept(db, {**good, "source_ref": "trust me"}, SA_A.id)
    with pytest.raises(BadRequestException, match="not in c_TipoOtroPago"):
        C.propose_system_concept(db, {**good, "node_type": "OTRO_PAGO", "sat_code": "ZZZ"}, SA_A.id)
    p = C.propose_system_concept(db, good, SA_A.id)
    assert p["status"] == "PROPOSED"
    with pytest.raises(BadRequestException, match="already has a proposal"):
        C.propose_system_concept(db, good, SA_B.id)
    with pytest.raises(BadRequestException, match="different Super Admin"):
        C.approve_system_concept(db, p["id"], SA_A.id)
    assert C.approved_concept(db, rel["id"], "ISR_WITHHELD") is None      # a proposal changes nothing
    assert C.approve_system_concept(db, p["id"], SA_B.id)["status"] == "APPROVED"
    assert C.approved_concept(db, rel["id"], "ISR_WITHHELD").sat_code == deduction
    q = C.propose_system_concept(db, good, SA_B.id)
    C.approve_system_concept(db, q["id"], SA_A.id)                        # a newer approval supersedes
    states = {r["id"]: r["status"] for r in C.list_system_concepts(db, rel["id"])["rows"]}
    assert states == {p["id"]: "SUPERSEDED", q["id"]: "APPROVED"}
    w = C.propose_system_concept(db, good, SA_A.id)
    assert C.withdraw_system_concept(db, w["id"], SA_A.id)["status"] == "WITHDRAWN"
    actions = {a.action for a in db.query(A).filter(A.entity_type == "mx_cfdi_system_concept")}
    assert {"propose", "approve", "supersede", "withdraw", "refused"} <= actions


def test_pinned_set_and_system_concept_routes(db, mini_set):
    from tests._mx_employer_helpers import http

    base = "/api/super-admin/compliance/mexico"
    with http(db, SA_A) as c:
        sets = c.get(f"{base}/cfdi-catalogs/pinned-sets").json()
        assert [s["setId"] for s in sets] == [SET_ID] and sets[0]["verified"] is True
        rel = c.post(f"{base}/cfdi-catalogs", json={"cfdiVersion": "4.0", "complementVersion": "1.2"}).json()
        r = c.post(f"{base}/cfdi-catalogs/{rel['id']}/load-pinned", json={"setId": SET_ID})
        assert r.status_code == 200, r.text
        page = c.get(f"{base}/cfdi-catalogs/{rel['id']}/entries", params={"catalog": "c_TipoPercepcion"}).json()
        assert page["total"] == 3 and page["counts"]["c_TipoPercepcion"] == 3
        body = {"releaseId": rel["id"], "conceptKey": "IMSS_EMPLOYEE", "nodeType": "DEDUCCION",
                "satCode": _first(mini_set, "c_TipoDeduccion"), "sourceRef": "S28 c_TipoDeduccion (SYNTHETIC)"}
        p = c.post(f"{base}/cfdi-system-concepts", json=body)
        assert p.status_code == 200, p.text
        assert c.post(f"{base}/cfdi-system-concepts/{p.json()['id']}/approve").status_code == 400
    with http(db, SA_B) as c:
        assert c.post(f"{base}/cfdi-system-concepts/{p.json()['id']}/approve").json()["status"] == "APPROVED"
        listed = c.get(f"{base}/cfdi-system-concepts", params={"releaseId": rel["id"]}).json()
        assert [r["status"] for r in listed["rows"]] == ["APPROVED"]
        assert "ISR_WITHHELD" in {k["key"] for k in listed["concepts"]}
