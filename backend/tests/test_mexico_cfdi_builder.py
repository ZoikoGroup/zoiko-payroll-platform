"""Mexico Phase 11b — the CFDI 4.0 + Nómina 1.2 builder (MEXICO_PHASE_11_PLAN.md
§4.4–4.6). The golden vector is SAT's worked receipt in the filling guide
(S4 pp. 111–114); every other SAT value is read from the pinned set or from a
table in the builder that cites its S4 page. Identifiers in the golden vector
are SAT's own fictitious ones; everything else is SYNTHETIC."""

import ast
import copy
import socket
from datetime import date, datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest
from lxml import etree

SET = "sat_2026_08"
BACKEND = Path(__file__).resolve().parents[1]


def _X():
    from app.modules.payroll import mexico_cfdi_xml

    return mexico_cfdi_xml


# ── the golden vector: S4 pp. 111–114 ───────────────────────────────────────
# Transcribed from the printed receipt on S4 p. 114 (labels and values print in
# two columns; codes decoded with the pinned catalogs). Two values of SAT's own
# example do not satisfy SAT's own rules and are kept AS PRINTED in GOLDEN_AS_PRINTED:
#   * contract type 09 ("Modalidades de contratación donde no existe relación de
#     trabajo") with regime type 02 — S4 p. 34 requires 05–99 for contract 09+;
#   * the receiver CURP ends in "X" — tdCFDI t_CURP requires a final digit.
# GOLDEN is identical except contract type 01 and the CURP's final character.
# Not compared (not printed, or optional and not emitted by design): the issuer
# name (blank on p. 114), Banco / CuentaBancaria (optional, S4 pp. 38–39 — the
# builder never writes bank details), the issuer CURP printed near the issuer
# block (a persona moral has none, S4 p. 25), TotalOtrosPagos "0" (S4 p. 25:
# omitted when there are no other payments), Sello / certificate (X4).
GOLDEN_AS_PRINTED = {
    "setId": SET, "folio": "1", "issuedAt": "2022-01-15T00:00:00", "placeOfIssue": "06300",
    "issuer": {"rfc": "NUF150930AAA", "name": "SYNTHETIC ISSUER NAME", "regime": "601",
               "registroPatronal": "B5510768108"},
    "receiver": {"rfc": "LOAV890607PY7", "name": "VICTORIOSS LOPEZ AVILA", "curp": "LOAV890607HDFTTR1X",
                 "nss": "128925410", "fiscalPostalCode": "55853", "employeeNumber": "1", "contractType": "09",
                 "regimeType": "02", "workdayType": "01", "riskClass": "2", "payFrequency": "04", "state": "CMX",
                 "seniorityDate": "2021-02-01", "sdi": "233.00", "unionized": "No", "position": "Cajero"},
    "payroll": {"payDate": "2022-01-15", "periodStart": "2022-01-01", "periodEnd": "2022-01-15", "daysPaid": "15"},
    "perceptions": [{"satCode": "001", "key": "001", "concept": "Sueldo", "taxed": "6000.00", "exempt": "0.00"}],
    "deductions": [{"satCode": "001", "key": "001", "concept": "Seguridad social", "amount": "200.00"},
                   {"satCode": "002", "key": "002", "concept": "ISR", "amount": "591.26"},
                   {"satCode": "101", "key": "101", "concept": "ISR Retenido de ejercicio anterior",
                    "amount": "798.44"}],
}
GOLDEN = copy.deepcopy(GOLDEN_AS_PRINTED)
GOLDEN["receiver"].update(contractType="01", curp="LOAV890607HDFTTR10")
# Every value p. 114 prints for the nodes the builder writes (node -> attributes).
EXPECTED = {
    "Comprobante": {"Version": "4.0", "Fecha": "2022-01-15T00:00:00", "SubTotal": "6000.00", "Descuento": "1589.70",
                    "Moneda": "MXN", "Total": "4410.30", "TipoDeComprobante": "N", "MetodoPago": "PUE",
                    "LugarExpedicion": "06300"},
    "Emisor": {"Rfc": "NUF150930AAA", "RegimenFiscal": "601"},
    "Receptor": {"Rfc": "LOAV890607PY7", "Nombre": "VICTORIOSS LOPEZ AVILA", "DomicilioFiscalReceptor": "55853",
                 "RegimenFiscalReceptor": "605", "UsoCFDI": "CN01"},
    "Concepto": {"ClaveProdServ": "84111505", "Cantidad": "1", "ClaveUnidad": "ACT", "Descripcion": "Pago de nómina",
                 "ValorUnitario": "6000.00", "Importe": "6000.00", "Descuento": "1589.70"},
    "Nomina": {"Version": "1.2", "TipoNomina": "O", "FechaPago": "2022-01-15", "FechaInicialPago": "2022-01-01",
               "FechaFinalPago": "2022-01-15", "TotalPercepciones": "6000.00", "TotalDeducciones": "1589.70"},
    "nomina12:Emisor": {"RegistroPatronal": "B5510768108"},
    "nomina12:Receptor": {"NumSeguridadSocial": "128925410", "FechaInicioRelLaboral": "2021-02-01",
                          "Antigüedad": "P49W", "Sindicalizado": "No", "TipoJornada": "01", "TipoRegimen": "02",
                          "NumEmpleado": "1", "Puesto": "Cajero", "RiesgoPuesto": "2", "PeriodicidadPago": "04",
                          "SalarioDiarioIntegrado": "233.00", "ClaveEntFed": "CMX"},
    "Percepciones": {"TotalSueldos": "6000.00", "TotalGravado": "6000.00", "TotalExento": "0.00"},
    "Deducciones": {"TotalOtrasDeducciones": "998.44", "TotalImpuestosRetenidos": "591.26"},
}
EXPECTED_LINES = {
    "Percepcion": [("001", "001", "Sueldo", "6000.00", "0.00")],
    "Deduccion": [("001", "001", "Seguridad social", "200.00"), ("002", "002", "ISR", "591.26"),
                  ("101", "101", "ISR Retenido de ejercicio anterior", "798.44")],
}


def _parse(payload):
    return etree.fromstring(payload)


def _node(root, name):
    if ":" in name:
        prefix, local = name.split(":")
        return root.find(f".//{{{root.nsmap[prefix]}}}{local}")
    if name == "Comprobante":
        return root
    found = [e for e in root.iter() if etree.QName(e).localname == name]
    return found[0]


def test_sats_worked_receipt_as_printed_breaks_sats_own_rules():
    from app.modules.payroll.engine.countries.mexico import MXBlock

    with pytest.raises(MXBlock) as exc:
        _X().build(GOLDEN_AS_PRINTED)
    assert exc.value.reasons == [("R-CONTRACT-REGIME", "contract type 09 requires a regime type from 05 to 99 (S4 p. 34)")]
    printed_curp_only = copy.deepcopy(GOLDEN)
    printed_curp_only["receiver"]["curp"] = GOLDEN_AS_PRINTED["receiver"]["curp"]
    with pytest.raises(MXBlock) as exc:
        _X().build(printed_curp_only)
    assert exc.value.key == "MX_CFDI_XSD_INVALID" and exc.value.reasons == [
        ("MX_CFDI_XSD_INVALID", "Receptor@Curp: SCHEMAV_CVC_PATTERN_VALID")]
    assert "LOAV" not in str(exc.value)                      # the refusal never carries the value


def test_the_worked_receipt_is_rebuilt_node_by_node():
    root = _parse(_X().build(GOLDEN))
    for node, attrs in EXPECTED.items():
        el = _node(root, node)
        for attr, value in attrs.items():
            assert el.get(attr) == value, (node, attr, el.get(attr), value)
    for kind, rows in EXPECTED_LINES.items():
        found = [e for e in root.iter() if etree.QName(e).localname == kind]
        fields = (("TipoPercepcion", "Clave", "Concepto", "ImporteGravado", "ImporteExento") if kind == "Percepcion"
                  else ("TipoDeduccion", "Clave", "Concepto", "Importe"))
        assert [tuple(e.get(f) for f in fields) for e in found] == rows
    nomina = _node(root, "Nomina")
    assert D(nomina.get("NumDiasPagados")) == D("15")       # printed "15"; S4 p. 23 writes three decimals
    assert nomina.get("TotalOtrosPagos") is None and root.get("Sello") is None


def test_every_fixed_value_cites_s4_and_is_a_valid_code_of_its_catalog():
    from app.modules.payroll import mexico_cfdi_xml as X

    cats = X._Catalogs(SET)
    on = date(2026, 10, 23)
    for key, (value, source, catalog) in X.FIXED.items():
        assert source.startswith("S4 p. "), key
        if catalog:
            assert cats.entry(catalog, value, on) is not None, (key, value, catalog)
    descriptions = {c: {e[0]: e[1] for e in X.mexico_cfdi_schema.catalogs(SET)[c]["entries"]}
                    for c in ("c_TipoPercepcion", "c_TipoDeduccion", "c_TipoOtroPago", "c_TipoContrato",
                              "c_TipoRegimen")}
    sep = [descriptions["c_TipoPercepcion"][c] for c in X.SEPARATION_PERCEPTIONS]
    assert sep == ["Prima por antigüedad", "Pagos por separación", "Indemnizaciones"]
    assert all("Jubilaciones" in descriptions["c_TipoPercepcion"][c] for c in X.RETIREMENT_PERCEPTIONS)
    assert descriptions["c_TipoDeduccion"][X.ISR_DEDUCTION] == "ISR"
    assert set(X.PERCEPTION_DETAIL) <= set(descriptions["c_TipoPercepcion"])
    assert descriptions["c_TipoPercepcion"][X.OVERTIME_PERCEPTION] == "Horas extra"
    assert set(X.OTHER_PAYMENT_DETAIL) <= set(descriptions["c_TipoOtroPago"])
    assert set(X.CONTRACT_WITH_EMPLOYMENT) | {"09"} <= set(descriptions["c_TipoContrato"])
    assert set(X.REGIMES_WITH_EMPLOYMENT) <= set(descriptions["c_TipoRegimen"])
    assert X.money_decimals(SET, on) == 2                   # c_Moneda MXN 'Decimales'


def test_no_sat_literal_outside_the_cited_tables():
    """Every code-shaped string in the builder and the input assembly sits in
    one of the tables that cite S4 (or is not a SAT value at all)."""
    tables = {"FIXED", "SEPARATION_PERCEPTIONS", "RETIREMENT_PERCEPTIONS", "PERCEPTION_DETAIL", "ISR_DEDUCTION",
              "OTHER_PAYMENT_DETAIL", "CONTRACT_WITH_EMPLOYMENT", "REGIMES_WITH_EMPLOYMENT", "_SOURCES",
              "OVERTIME_PERCEPTION", "OVERTIME_TYPE_DOUBLE"}
    code_like = __import__("re").compile(r"^(\d{2,8}|[A-Z]{1,4}\d{0,2}|CN01|PUE|MXN|ACT)$")
    allowed = {"MX", "O", "E", "N", "I", "Sí", "No", "X", "ISR", "IMSS", "MEX", "PTU", "SAT", "CSD", "UUID", "RFC",
               "CURP", "NSS", "SDI", "SBC", "DB", "PAC"}
    offenders = []
    for name in ("mexico_cfdi_xml.py", "mexico_cfdi_input.py"):
        tree = ast.parse((BACKEND / "app" / "modules" / "payroll" / name).read_text(encoding="utf-8"))
        inside = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in tables for t in node.targets):
                inside |= {id(n) for n in ast.walk(node.value)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and code_like.match(node.value) \
                    and node.value not in allowed and id(node) not in inside:
                offenders.append((name, node.lineno, node.value))
    assert not offenders, offenders


def _refusal(doc):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    with pytest.raises(MXBlock) as exc:
        _X().build(doc)
    return exc.value


def _golden(**changes):
    doc = copy.deepcopy(GOLDEN)
    for path, value in changes.items():
        target = doc
        *parents, leaf = path.split("__")
        for p in parents:
            target = target[p]
        target[leaf] = value
    return doc


@pytest.mark.parametrize("changes, rule", [
    ({"payroll__daysPaid": "0"}, "R-DAYS-PAID"),
    ({"payroll__periodStart": "2022-01-16"}, "R-DATES"),
    ({"receiver__payFrequency": "99"}, "R-PERIODICITY"),
    ({"issuer__rfc": "LOAV890607PY7"}, "R-ISSUER-CURP"),                   # a persona física employer, no CURP
    ({"receiver__contractType": "01", "issuer__registroPatronal": None}, "R-REGISTRO-PATRONAL"),
    ({"receiver__nss": None}, "R-REGISTRO-PATRONAL"),
    ({"receiver__fiscalRegime": "601"}, "R-RECEIVER-REGIME"),
    ({"receiver__state": "CDMX"}, "R-CATALOG"),                            # not a c_Estado code
    ({"placeOfIssue": "00000"}, "R-CATALOG"),
])
def test_each_s4_rule_refuses_with_its_page(changes, rule):
    exc = _refusal(_golden(**changes))
    assert exc.key == "MX_CFDI_RULE_FAILED" and rule in {r for r, _ in exc.reasons}, exc.reasons
    assert all("(S" in text for _, text in exc.reasons)                    # every reason cites its source


def test_amount_rules_totals_and_decimals():
    exc = _refusal(_golden(**{"deductions": [{"satCode": "002", "key": "002", "concept": "ISR", "amount": "0"}]}))
    assert "R-POSITIVE-AMOUNTS" in {r for r, _ in exc.reasons}
    exc = _refusal(_golden(**{"perceptions": [{"satCode": "001", "key": "001", "concept": "x", "taxed": "6000.001",
                                               "exempt": "0"}]}))
    assert "R-DECIMALS" in {r for r, _ in exc.reasons}
    doc = _golden()
    doc["expectedTotals"] = {"perceptions": "6000.00", "deductions": "1589.71"}           # one centavo off
    exc = _refusal(doc)
    assert exc.key == "MX_CFDI_TOTALS_MISMATCH" and "never adjusts" in str(exc)
    doc["expectedTotals"] = {"perceptions": "6000.00", "deductions": "1589.70", "otherPayments": "0"}
    assert _parse(_X().build(doc)).get("Total") == "4410.30"


@pytest.mark.parametrize("line, rule", [
    ({"satCode": "019", "key": "OT", "concept": "Horas extra", "taxed": "100.00", "exempt": "0"}, "R-DETAIL-NODE"),
    ({"satCode": "022", "key": "SEP", "concept": "Prima", "taxed": "100.00", "exempt": "0"}, "R-SEPARATION"),
    ({"satCode": "999", "key": "BAD", "concept": "x", "taxed": "100.00", "exempt": "0"}, "R-CATALOG"),
])
def test_perceptions_the_builder_cannot_express_yet_are_refused(line, rule):
    doc = _golden()
    doc["perceptions"] = doc["perceptions"] + [line]
    assert rule in {r for r, _ in _refusal(doc).reasons}


def test_subsidy_needs_its_node_and_is_refused():
    doc = _golden()
    doc["otherPayments"] = [{"satCode": "002", "key": "002", "concept": "Subsidio", "amount": "10.00"}]
    assert "R-DETAIL-NODE" in {r for r, _ in _refusal(doc).reasons}


def test_extraordinary_payroll_and_substitution():
    doc = _golden(**{"payroll__extraordinary": True}, replacesUuid="5FB2822E-396D-4725-8521-CDC4BDD20CCF")
    root = _parse(_X().build(doc))
    assert _node(root, "Nomina").get("TipoNomina") == "E"
    assert _node(root, "nomina12:Receptor").get("PeriodicidadPago") == "99"      # S4 p. 38
    rel = _node(root, "CfdiRelacionados")
    assert rel.get("TipoRelacion") == "04" and _node(root, "CfdiRelacionado").get("UUID").startswith("5FB2822E")


def test_a_code_outside_its_catalog_window_is_refused(monkeypatch):
    X = _X()
    index = copy.deepcopy(X._Catalogs(SET).index)
    index["c_TipoPercepcion"]["001"] = [("2016-11-01", "2021-12-31", "SYNTHETIC ended", {})]
    monkeypatch.setitem(X._Catalogs._cache, SET, index)
    assert "R-CATALOG" in {r for r, _ in _refusal(_golden()).reasons}


def test_validation_never_uses_the_network(monkeypatch):
    from app.modules.payroll import mexico_cfdi_schema

    mexico_cfdi_schema._compiled.cache_clear()
    mexico_cfdi_schema._combined.cache_clear()

    def no_network(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert _parse(_X().build(GOLDEN)).get("Total") == "4410.30"


# ── assembly + generation (database) ────────────────────────────────────────

GOOD_IDS = {"rfc": "LOAV890607PY7", "curp": "LOAV890607HDFTTR10", "nss": "12345678901"}
BAD_CURP = "AAAA000000HZZZZZ0Q"          # fails t_CURP and escapes the generic CURP redaction pattern
SOURCE_COPIES = {("payroll_employees", "compliance_fields"), ("payslip_items", "compliance_fields")}


def _ready_world(db, monkeypatch, tmp_path, code, ids=GOOD_IDS, sdi=True, mappings=True):
    from app.modules.payroll import mexico_cfdi_builder as B
    from app.modules.payroll import mexico_cfdi_catalog_service as CS
    from app.modules.payroll import mexico_cfdi_input as I
    from app.modules.payroll import mexico_cfdi_schema as S
    from app.modules.payroll import mexico_employee_service, mexico_service
    from app.modules.payroll.models import PayrollEmployee, PayrollMxEarningClassification as C
    from tests import _mx_cfdi_helpers as ch
    from tests import _mx_run_helpers as rh
    from tests import test_mexico_pilot as tp

    cats = S.catalogs(SET)
    first = lambda name, start="": next(e[0] for e in cats[name]["entries"] if e[1].startswith(start))  # noqa: E731
    w = rh.world(db, monkeypatch, code=code)
    cls = db.query(C).filter(C.earning_code == "MX_SALARY", C.organization_id.is_(None)).one()
    cls.cfdi_concept_code = first("c_TipoPercepcion", "Sueldos, Salarios")
    emp = db.get(PayrollEmployee, w.employee.id)
    emp.compliance_fields = {**(emp.compliance_fields or {}), **ids}
    prof = mexico_employee_service._profile_on(db, emp.id, w.run.pay_date)
    prof.mx_fiscal_postal_code = "06600"
    prof.mx_contract_type_code = first("c_TipoContrato", "Contrato de trabajo por tiempo indeterminado")
    prof.mx_regime_type_code = first("c_TipoRegimen", "Sueldos")
    prof.mx_workday_type_code = first("c_TipoJornada", "Diurna")
    prof.mx_job_risk_code = first("c_RiesgoPuesto", "Clase I")
    prof.mx_work_state = prof.mx_work_state or "CDMX"
    db.commit()
    rh.generate(db, w)
    rh.advance(db, w)
    rh.advance(db, w)
    db.refresh(w.run)
    ch.patch_seams(monkeypatch, tmp_path)
    monkeypatch.setattr(B, "_BUILDER", B.SatBuilder())
    rel = mexico_service.create_release(db, {"cfdi_version": "4.0", "complement_version": "1.2"}, tp.SA_A.id)
    CS.load_pinned_set(db, rel["id"], SET, tp.SA_A.id)
    release = db.get(__import__("app.modules.payroll.models", fromlist=["x"]).PayrollMxCfdiSchemaRelease, rel["id"])
    release.status = "Active"                       # activation needs PAC validation (D3) — SYNTHETIC here
    db.commit()
    if mappings:
        for key, catalog, node, start in (("ISR_WITHHELD", "c_TipoDeduccion", "DEDUCCION", "ISR"),
                                          ("IMSS_EMPLOYEE", "c_TipoDeduccion", "DEDUCCION", "Seguridad social")):
            code_ = next(e[0] for e in cats[catalog]["entries"] if e[1] == start)
            p = CS.propose_system_concept(db, {"release_id": rel["id"], "concept_key": key, "node_type": node,
                                               "sat_code": code_, "source_ref": "S28 SYNTHETIC test mapping"},
                                          tp.SA_A.id)
            CS.approve_system_concept(db, p["id"], tp.SA_B.id)
    if sdi:
        monkeypatch.setattr(I, "SDI_SOURCE", lambda result, prof: str(prof.mx_daily_salary))   # SYNTHETIC
    ch.employer_ready(db, w)
    return w


def test_a_committed_payslip_becomes_a_valid_receipt(db, monkeypatch, tmp_path):
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll.models import PayrollMxCfdiDocument

    w = _ready_world(db, monkeypatch, tmp_path, "MXB11A")
    item = __import__("tests._mx_run_helpers", fromlist=["x"]).mx_items(db, w.run)[0]
    result = item.mx_calculation_snapshot["result"]
    S.generate(db, w.run, w.users[0].id)
    doc = db.query(PayrollMxCfdiDocument).filter(PayrollMxCfdiDocument.payroll_run_id == w.run.id).one()
    stored = object_storage.read_bytes(doc.xml_storage_ref) if hasattr(object_storage, "read_bytes") \
        else Path(object_storage.local_path(doc.xml_storage_ref)).read_bytes()
    root = _parse(stored.split(b"<!--SYNTHETIC-SELLO")[0])
    _X().validate(etree.tostring(root, xml_declaration=True, encoding="UTF-8"), SET)
    assert _node(root, "Comprobante").get("Folio") == doc.folio
    assert D(_node(root, "Nomina").get("TotalPercepciones")) == D(result["gross"])
    assert D(_node(root, "Nomina").get("TotalDeducciones")) == D(result["isr_withheld"]) + D(result["employee_total"])
    assert _node(root, "nomina12:Receptor").get("ClaveEntFed") == "CMX"               # CDMX -> c_Estado by name
    assert _node(root, "Comprobante").get("Fecha").startswith(w.run.pay_date.isoformat()[:4])


def test_unmapped_amounts_and_missing_sources_refuse_by_name(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_service as S

    w = _ready_world(db, monkeypatch, tmp_path, "MXB11B", mappings=False)
    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_CONCEPT_UNMAPPED" and "ISR_WITHHELD" in str(exc.value)
    db.rollback()
    w = _ready_world(db, monkeypatch, tmp_path, "MXB11C", sdi=False)
    monkeypatch.setattr(__import__("app.modules.payroll.mexico_cfdi_input", fromlist=["x"]), "SDI_SOURCE", None)
    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_INPUT_MISSING" and "G1 decision" in str(exc.value)


# 2026: the 2nd Sunday of March is the 8th, the 1st Sunday of November the 1st.
@pytest.mark.parametrize("postal, utc, local", [
    # Tiempo del Noroeste (BCN 21000): winter -8, summer -7 — S30 "Marzo / Segundo domingo / 02:00", "Noviembre / Primer domingo / 02:00"
    ("21000", datetime(2026, 3, 8, 9, 59, 59), datetime(2026, 3, 8, 1, 59, 59)),     # last second of winter time
    ("21000", datetime(2026, 3, 8, 10, 0, 0), datetime(2026, 3, 8, 3, 0, 0)),        # 02:00 standard -> 03:00 summer
    ("21000", datetime(2026, 11, 1, 8, 59, 59), datetime(2026, 11, 1, 1, 59, 59)),   # last second of summer time
    ("21000", datetime(2026, 11, 1, 9, 0, 0), datetime(2026, 11, 1, 1, 0, 0)),       # 02:00 summer -> 01:00 winter
    # Tiempo del Centro en Frontera (COA 26000): winter -6, summer -5
    ("26000", datetime(2026, 3, 8, 7, 59, 59), datetime(2026, 3, 8, 1, 59, 59)),
    ("26000", datetime(2026, 3, 8, 8, 0, 0), datetime(2026, 3, 8, 3, 0, 0)),
    ("26000", datetime(2026, 11, 1, 6, 59, 59), datetime(2026, 11, 1, 1, 59, 59)),
    ("26000", datetime(2026, 11, 1, 7, 0, 0), datetime(2026, 11, 1, 1, 0, 0)),
    ("26000", datetime(2026, 7, 1, 12, 0, 0), datetime(2026, 7, 1, 7, 0, 0)),        # mid-summer
    ("26000", datetime(2026, 1, 15, 12, 0, 0), datetime(2026, 1, 15, 6, 0, 0)),      # mid-winter
    # Tiempo del Centro (CMX 06600): -6 all year
    ("06600", datetime(2026, 7, 1, 12, 0, 0), datetime(2026, 7, 1, 6, 0, 0)),
])
def test_fecha_follows_the_postal_codes_own_daylight_saving_rule(postal, utc, local):
    from app.modules.payroll import mexico_cfdi_input as I

    assert I.local_issue_time(SET, postal, utc.replace(tzinfo=timezone.utc)) == local


def test_the_catalog_carries_the_rule_and_an_inconsistent_row_is_refused():
    """S30's header repeats 'Día_Inicio_Horario_…' for the hour column; the set
    keeps it as '… #2' (manifest duplicateHeaders). The CHH 'Centro en Frontera'
    rows give summer -7 / winter -6 — summer behind winter — and are refused."""
    from app.modules.payroll import mexico_cfdi_input as I
    from app.modules.payroll import mexico_cfdi_schema as S
    from app.modules.payroll.engine.countries.mexico import MXBlock

    tz = "Referencias del Huso Horario/"
    rows = {e[0]: e[4] for e in S.catalogs(SET)["c_CodigoPostal"]["entries"]}
    assert rows["21000"][tz + "Día_Inicio_Horario_Verano"] == "Segundo domingo"
    assert rows["21000"][tz + "Día_Inicio_Horario_Verano #2"] == "02:00"
    assert ["c_CodigoPostal_Parte_1", tz + "Día_Inicio_Horario_Verano", 2] in S.manifest(SET)["duplicateHeaders"]
    inconsistent = [code for code, a in rows.items() if a.get(tz + "Mes_Inicio_Horario_Verano")
                    and a[tz + "Diferencia_Horaria_Verano"] != a[tz + "Diferencia_Horaria_Invierno"] + 1]
    assert len(inconsistent) == 830 and {rows[c]["c_Estado"] for c in inconsistent} == {"CHH"}
    with pytest.raises(MXBlock) as exc:
        I.local_issue_time(SET, inconsistent[0], datetime(2026, 7, 1, 12, tzinfo=timezone.utc))
    assert exc.value.key == "MX_CFDI_TIMEZONE_RULE_INVALID"


def test_an_invalid_curp_appears_nowhere(db, monkeypatch, tmp_path, caplog, capsys):
    """MX-061 / condition 5: the bad CURP is refused, and the CFDI path puts it
    in no table, CFDI event, audit row, log line or API response.

    Two columns already held it BEFORE any CFDI step, and are excluded as its
    sources: the employee's compliance_fields (where it was entered) and the
    payslip's compliance_fields — a platform-wide snapshot of every country's
    identifiers taken when the run is generated (models.PayslipItem; plaintext
    at rest is the open decision Q9 / HK D-4, reported to ZP-PRIV)."""
    import logging

    import sqlalchemy as sa

    from tests._mx_employer_helpers import http

    caplog.set_level(logging.DEBUG)
    w = _ready_world(db, monkeypatch, tmp_path, "MXB11D", ids={**GOOD_IDS, "curp": BAD_CURP})
    with http(db, w.users[0]) as c:
        r = c.post(f"/api/payroll/mexico/runs/{w.run.id}/cfdi/generate")
        page = c.get(f"/api/payroll/mexico/runs/{w.run.id}/cfdi")
    assert r.status_code == 400 and "Curp" in r.text and "SCHEMAV_CVC_PATTERN_VALID" in r.text
    needles = (BAD_CURP, BAD_CURP[4:16])
    for text in (r.text, page.text, caplog.text, "".join(capsys.readouterr())):
        assert not any(n in text for n in needles)
    db.rollback()
    found = []
    for table in sa.inspect(db.bind).get_table_names():
        cols = [c["name"] for c in sa.inspect(db.bind).get_columns(table)]
        for row in db.execute(sa.text(f'SELECT * FROM "{table}"')).mappings():
            for col in cols:
                if (table, col) in SOURCE_COPIES:
                    continue
                value = row[col]
                if value is not None and any(n in str(value) for n in needles):
                    found.append((table, col))
    assert found == []
