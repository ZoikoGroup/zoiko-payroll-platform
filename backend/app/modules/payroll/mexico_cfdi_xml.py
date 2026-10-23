"""
modules/payroll/mexico_cfdi_xml.py
----------------------------------
The CFDI 4.0 + Complemento de Nómina 1.2 builder (ZP-MX-ENG-001 Phase 11b,
MEXICO_PHASE_11_PLAN.md §4.5, X1 + X2). Pure: no database, no network, no
clock — everything arrives in `document_input` (mexico_cfdi_input assembles
it) and the pinned SAT schema set named there.

* Every SAT value the builder writes on its own is in a table below with the
  S4 page it comes from (`FIXED`, the code groups); a test checks each against
  the pinned SAT catalogs and that no other SAT literal appears in this module.
* Every catalog code is checked against the pinned 4.0 catalog, valid on the
  issue date — the XSD alone accepts codes the 4.0 catalog has dropped.
* The S4 filling rules are named checks (rule id + page). Totals are computed
  from the lines and must equal the committed result: a difference REFUSES
  (MX_CFDI_TOTALS_MISMATCH) — the builder never fixes a figure (MX-017).
* The document is validated against the pinned XSDs (both namespaces) before a
  byte leaves the builder. Sello / NoCertificado / Certificado are the signer's
  (X4): the builder never writes them; validation fills them on a throwaway
  copy only.
* MX-061: identifiers live only in memory here. No message carries a value —
  XSD errors are reduced to element / attribute / failed facet.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional, Tuple

from app.modules.payroll import mexico_cfdi_schema
from app.modules.payroll.engine.countries.mexico import MXBlock

# ── the values the builder writes on its own (S4: SAT payroll filling guide) ──
# key: (value, source, catalog the value must belong to or None)
FIXED = {
    "Comprobante.Version": ("4.0", "S4 p. 5", None),
    "Comprobante.Moneda": ("MXN", "S4 p. 7", "c_Moneda"),
    "Comprobante.TipoDeComprobante": ("N", "S4 p. 9", "c_TipoDeComprobante"),
    "Comprobante.Exportacion": ("01", "S4 p. 9", "c_Exportacion"),
    "Comprobante.MetodoPago": ("PUE", "S4 p. 9", "c_MetodoPago"),
    "CfdiRelacionados.TipoRelacion": ("04", "S4 p. 11", "c_TipoRelacion"),
    "Receptor.RegimenFiscalReceptor": ("605", "S4 p. 15", "c_RegimenFiscal"),
    "Receptor.UsoCFDI": ("CN01", "S4 p. 15", "c_UsoCFDI"),
    "Concepto.ClaveProdServ": ("84111505", "S4 p. 16", "c_ClaveProdServ"),
    "Concepto.Cantidad": ("1", "S4 p. 16", None),
    "Concepto.ClaveUnidad": ("ACT", "S4 p. 16", "c_ClaveUnidad"),
    "Concepto.Descripcion": ("Pago de nómina", "S4 p. 17", None),
    "Concepto.ObjetoImp": ("01", "S4 p. 17", "c_ObjetoImp"),
    "Nomina.Version": ("1.2", "S4 p. 19", None),
    "Nomina.TipoNomina.ordinary": ("O", "S4 p. 20", "c_TipoNomina"),
    "Nomina.TipoNomina.extraordinary": ("E", "S4 p. 20", "c_TipoNomina"),
    "Nomina.PeriodicidadPago.extraordinary": ("99", "S4 p. 38", "c_PeriodicidadPago"),
    # Seniority in whole weeks, never more than the time elapsed (ISO 8601 "PnW").
    "Nomina.Receptor.Antiguedad.weeks": ("P{weeks}W", "S4 p. 32", None),
}
# Code groups the guide names (each code checked against c_TipoPercepcion / c_TipoDeduccion / c_TipoOtroPago).
SEPARATION_PERCEPTIONS = ("022", "023", "025")          # S4 pp. 43–44: TotalSeparacionIndemnizacion
RETIREMENT_PERCEPTIONS = ("039", "044")                 # S4 pp. 44–45: TotalJubilacionPensionRetiro
# Perceptions that need a detail node the engine cannot fill yet (S4 pp. 47–48).
PERCEPTION_DETAIL = {"019": "HorasExtra — the days on which overtime was worked (S4 pp. 48, 51); the engine "
                            "records overtime hours per week only",
                     "014": "Incapacidades (S4 p. 48)", "039": "JubilacionPensionRetiro (S4 pp. 47–48)",
                     "044": "JubilacionPensionRetiro (S4 pp. 47–48)", "045": "AccionesOTitulos (S4 p. 48)"}
ISR_DEDUCTION = "002"                                   # S4 p. 60: TotalImpuestosRetenidos
OTHER_PAYMENT_DETAIL = {"002": "SubsidioAlEmpleo (S4 pp. 67, 70)", "004": "CompensacionSaldosAFavor (S4 p. 67)"}
# S4 p. 34: contract types 01–08 take regime 02/03/04; 09 and above take 05–99.
CONTRACT_WITH_EMPLOYMENT = ("01", "02", "03", "04", "05", "06", "07", "08")
REGIMES_WITH_EMPLOYMENT = ("02", "03", "04")
# S4 p. 25: a persona moral's RFC has 12 characters, a persona física's 13.
RFC_MORAL_LENGTH = 12

_SOURCES = {"R-TOTALS-PERCEPTIONS": "S4 p. 23", "R-TOTALS-TAXED-EXEMPT": "S4 p. 43",
            "R-TOTALS-DEDUCTIONS": "S4 pp. 24, 60", "R-CONCEPT-AMOUNTS": "S4 p. 17", "R-TOTAL": "S4 pp. 7, 19",
            "R-SOMETHING-PAID": "S4 p. 19", "R-REGISTRO-PATRONAL": "S4 p. 26", "R-CONTRACT-REGIME": "S4 p. 34",
            "R-PERIODICITY": "S4 p. 38", "R-DATES": "S4 pp. 21, 31", "R-DAYS-PAID": "S4 p. 22",
            "R-ISSUER-CURP": "S4 p. 25", "R-POSITIVE-AMOUNTS": "S4 pp. 63, 69", "R-DETAIL-NODE": "S4 pp. 47–48, 67",
            "R-SEPARATION": "S4 pp. 34–35, 47, 56–59", "R-CATALOG": "S30 / S28 catalogs (4.0)",
            "R-RECEIVER-REGIME": "S4 p. 15", "R-DECIMALS": "S30 c_Moneda"}

CFDI_PREFIX, NOMINA_PREFIX = "cfdi", "nomina12"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


def fixed(key: str) -> str:
    return FIXED[key][0]


# ── helpers ──────────────────────────────────────────────────────────────────

class _Problems:
    def __init__(self):
        self.items: List[Tuple[str, str]] = []

    def add(self, rule: str, text: str):
        self.items.append((rule, f"{text} ({_SOURCES.get(rule, rule)})"))

    def raise_if_any(self, code: str):
        if self.items:
            raise MXBlock(code, "; ".join(f"{r}: {t}" for r, t in self.items), reasons=self.items)


def _dec(value, what: str) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise MXBlock("MX_CFDI_INPUT_INVALID", f"{what} is not a number")


def _day(value, what: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise MXBlock("MX_CFDI_INPUT_INVALID", f"{what} is not a date")


class _Catalogs:
    """The pinned 4.0 catalogs, indexed: is `code` in `catalog` on `on`?"""

    _cache: dict = {}

    def __init__(self, set_id: str):
        if set_id not in self._cache:
            index = {}
            for name, data in mexico_cfdi_schema.catalogs(set_id).items():
                rows = index.setdefault(name, {})
                for code, description, valid_from, valid_to, attrs in data["entries"]:
                    rows.setdefault(code, []).append((valid_from, valid_to, description, attrs or {}))
            self._cache[set_id] = index
        self.index = self._cache[set_id]

    def entry(self, catalog: str, code: Optional[str], on: date):
        for valid_from, valid_to, description, attrs in self.index.get(catalog, {}).get(str(code or ""), []):
            if (valid_from is None or date.fromisoformat(valid_from) <= on) and \
                    (valid_to is None or on <= date.fromisoformat(valid_to)):
                return description, attrs
        return None


def money_decimals(set_id: str, on: date) -> int:
    """Decimals MXN supports — c_Moneda's 'Decimales' column (S30)."""
    found = _Catalogs(set_id).entry("c_Moneda", fixed("Comprobante.Moneda"), on)
    if not found or "Decimales" not in found[1]:
        raise MXBlock("MX_CFDI_CATALOG_CODE_INVALID", "c_Moneda has no Decimales for the currency (S30)")
    return int(found[1]["Decimales"])


# ── the builder ──────────────────────────────────────────────────────────────

def build(doc: dict) -> bytes:
    """document_input -> UTF-8 XML (unsigned), or an MXBlock naming every problem."""
    set_id = doc.get("setId")
    try:
        mexico_cfdi_schema.verify(set_id)
    except mexico_cfdi_schema.SchemaSetError as exc:
        raise MXBlock("MX_CFDI_SCHEMA_SET_UNUSABLE", str(exc))
    issued = datetime.fromisoformat(str(doc["issuedAt"]))
    on = issued.date()
    cats = _Catalogs(set_id)
    places = money_decimals(set_id, on)
    quantum = Decimal(1).scaleb(-places)
    p = _Problems()

    def money(value, what) -> Decimal:
        amount = _dec(value, what)
        if amount != amount.quantize(quantum):
            p.add("R-DECIMALS", f"{what} has more than {places} decimals")
        return amount.quantize(quantum, ROUND_HALF_UP)

    def fmt(amount: Decimal) -> str:
        return f"{amount.quantize(quantum, ROUND_HALF_UP):.{places}f}"

    def code_in(catalog: str, code, what: str):
        if cats.entry(catalog, code, on) is None:
            p.add("R-CATALOG", f"{what} is not a {catalog} code valid on {on.isoformat()}")

    issuer, receiver, payroll = doc["issuer"], doc["receiver"], doc["payroll"]
    pay_date, start, end = (_day(payroll[k], k) for k in ("payDate", "periodStart", "periodEnd"))
    extraordinary = bool(payroll.get("extraordinary"))
    days_paid = _dec(payroll.get("daysPaid"), "daysPaid")

    # Fixed values must themselves be valid catalog codes on the issue date.
    for key, (value, _source, catalog) in FIXED.items():
        if catalog:
            code_in(catalog, value, key)

    # Lines.
    perceptions, deductions, others = [], [], []
    for line in doc.get("perceptions") or []:
        code = line["satCode"]
        code_in("c_TipoPercepcion", code, f"perception {line.get('key')}")
        if code in PERCEPTION_DETAIL:
            p.add("R-DETAIL-NODE", f"perception {code} needs {PERCEPTION_DETAIL[code]}")
        if code in SEPARATION_PERCEPTIONS:
            p.add("R-SEPARATION", "a separation perception needs TipoRegimen 13 and the SeparacionIndemnizacion node "
                                  "(last ordinary monthly salary, accumulable / non-accumulable income — not provided by "
                                  "the engine yet); the guide's contract-type rule (p. 34) and separation rule (p. 35) "
                                  "must also be reconciled against PAC validation — separation receipts are not built")
        taxed, exempt = money(line.get("taxed", 0), f"{code} taxed"), money(line.get("exempt", 0), f"{code} exempt")
        if taxed < 0 or exempt < 0 or taxed + exempt <= 0:
            p.add("R-POSITIVE-AMOUNTS", f"perception {code} must be positive")
        perceptions.append((code, line, taxed, exempt))
    for line in doc.get("deductions") or []:
        code_in("c_TipoDeduccion", line["satCode"], f"deduction {line.get('key')}")
        amount = money(line.get("amount"), f"{line['satCode']} amount")
        if amount <= 0:
            p.add("R-POSITIVE-AMOUNTS", f"deduction {line['satCode']} must be greater than zero")
        deductions.append((line["satCode"], line, amount))
    for line in doc.get("otherPayments") or []:
        code = line["satCode"]
        code_in("c_TipoOtroPago", code, f"other payment {line.get('key')}")
        if code in OTHER_PAYMENT_DETAIL:
            p.add("R-DETAIL-NODE", f"other payment {code} needs {OTHER_PAYMENT_DETAIL[code]}")
        amount = money(line.get("amount"), f"{code} amount")
        if amount <= 0:
            p.add("R-POSITIVE-AMOUNTS", f"other payment {code} must be greater than zero")
        others.append((code, line, amount))

    # Totals (S4 pp. 23–25, 43–46, 60).
    sueldos = sum((t + e for c, _, t, e in perceptions
                   if c not in SEPARATION_PERCEPTIONS + RETIREMENT_PERCEPTIONS), Decimal(0))
    separation = sum((t + e for c, _, t, e in perceptions if c in SEPARATION_PERCEPTIONS), Decimal(0))
    retirement = sum((t + e for c, _, t, e in perceptions if c in RETIREMENT_PERCEPTIONS), Decimal(0))
    taxed_total = sum((t for _, _, t, _ in perceptions), Decimal(0))
    exempt_total = sum((e for _, _, _, e in perceptions), Decimal(0))
    total_perceptions = sueldos + separation + retirement
    isr = sum((a for c, _, a in deductions if c == ISR_DEDUCTION), Decimal(0))
    other_deductions = sum((a for c, _, a in deductions if c != ISR_DEDUCTION), Decimal(0))
    total_deductions = isr + other_deductions
    total_others = sum((a for _, _, a in others), Decimal(0))
    subtotal = total_perceptions + total_others
    total = subtotal - total_deductions
    if total_perceptions != taxed_total + exempt_total:
        p.add("R-TOTALS-TAXED-EXEMPT", "perceptions do not equal taxed plus exempt")
    if not perceptions and not others:
        p.add("R-SOMETHING-PAID", "the receipt has no perception and no other payment")
    if total < 0:
        p.add("R-TOTAL", "the receipt total is negative")
    expected = doc.get("expectedTotals") or {}
    for key, value in (("perceptions", total_perceptions), ("deductions", total_deductions),
                       ("otherPayments", total_others)):
        if key in expected and money(expected[key], f"expected {key}") != value:
            raise MXBlock("MX_CFDI_TOTALS_MISMATCH",
                          f"the receipt's {key} ({fmt(value)}) differ from the committed result "
                          f"({fmt(_dec(expected[key], key))}) — the builder never adjusts a figure (MX-017)")

    # Receiver / contract rules.
    contract, regime = receiver.get("contractType"), receiver.get("regimeType")
    for catalog, value, what in (("c_TipoContrato", contract, "TipoContrato"), ("c_TipoRegimen", regime, "TipoRegimen"),
                                 ("c_PeriodicidadPago", receiver.get("payFrequency"), "PeriodicidadPago"),
                                 ("c_Estado", receiver.get("state"), "ClaveEntFed"),
                                 ("c_RegimenFiscal", issuer.get("regime"), "issuer RegimenFiscal"),
                                 ("c_CodigoPostal", doc.get("placeOfIssue"), "LugarExpedicion"),
                                 ("c_CodigoPostal", receiver.get("fiscalPostalCode"), "DomicilioFiscalReceptor")):
        code_in(catalog, value, what)
    if receiver.get("workdayType"):
        code_in("c_TipoJornada", receiver["workdayType"], "TipoJornada")
    if receiver.get("riskClass"):
        code_in("c_RiesgoPuesto", receiver["riskClass"], "RiesgoPuesto")
    if receiver.get("fiscalRegime") and receiver["fiscalRegime"] != fixed("Receptor.RegimenFiscalReceptor"):
        p.add("R-RECEIVER-REGIME", "the employee's receiver fiscal regime is not the one the guide requires")
    if contract in CONTRACT_WITH_EMPLOYMENT:
        if regime not in REGIMES_WITH_EMPLOYMENT:
            p.add("R-CONTRACT-REGIME", f"contract type {contract} requires regime type 02, 03 or 04")
        if not issuer.get("registroPatronal"):
            p.add("R-REGISTRO-PATRONAL", f"contract type {contract} requires the employer registration")
    elif contract and regime in REGIMES_WITH_EMPLOYMENT:
        p.add("R-CONTRACT-REGIME", f"contract type {contract} requires a regime type from 05 to 99")
    if issuer.get("registroPatronal"):
        for field in ("nss", "seniorityDate", "riskClass", "sdi"):
            if not receiver.get(field):
                p.add("R-REGISTRO-PATRONAL", f"with an employer registration the receiver's {field} is required")
    frequency = receiver.get("payFrequency")
    if extraordinary and frequency != fixed("Nomina.PeriodicidadPago.extraordinary"):
        frequency = fixed("Nomina.PeriodicidadPago.extraordinary")          # S4 p. 38: extraordinary -> 99
    elif not extraordinary and frequency == fixed("Nomina.PeriodicidadPago.extraordinary"):
        p.add("R-PERIODICITY", "an ordinary payroll cannot use periodicity 99")
    if start > end:
        p.add("R-DATES", "the period starts after it ends")
    seniority = _day(receiver["seniorityDate"], "seniorityDate") if receiver.get("seniorityDate") else None
    if seniority and seniority > end:
        p.add("R-DATES", "the employment start is after the period end")
    if days_paid <= 0:
        p.add("R-DAYS-PAID", "days paid must be greater than zero")
    moral = len(issuer.get("rfc") or "") == RFC_MORAL_LENGTH
    if not moral and not issuer.get("curp"):
        p.add("R-ISSUER-CURP", "a persona física employer needs its CURP")
    p.raise_if_any("MX_CFDI_RULE_FAILED")

    # ── serialise ────────────────────────────────────────────────────────────
    from lxml import etree

    locations = mexico_cfdi_schema.schema_locations(set_id)
    cfdi_ns = next(ns for ns, loc in locations.items() if loc.endswith("/cfdv40.xsd"))
    nomina_ns = next(ns for ns, loc in locations.items() if loc.endswith("/nomina12.xsd"))
    C = lambda tag: f"{{{cfdi_ns}}}{tag}"            # noqa: E731
    N = lambda tag: f"{{{nomina_ns}}}{tag}"          # noqa: E731
    nsmap = {CFDI_PREFIX: cfdi_ns, NOMINA_PREFIX: nomina_ns, "xsi": XSI}

    def attrs(el, pairs):
        for k, v in pairs:
            if v is not None and v != "":
                el.set(k, str(v))
        return el

    root = etree.Element(C("Comprobante"), nsmap=nsmap)
    root.set(f"{{{XSI}}}schemaLocation", " ".join(f"{ns} {loc}" for ns, loc in
                                                     ((cfdi_ns, locations[cfdi_ns]), (nomina_ns, locations[nomina_ns]))))
    attrs(root, [("Version", fixed("Comprobante.Version")), ("Serie", doc.get("serie")), ("Folio", doc.get("folio")),
                 ("Fecha", issued.strftime("%Y-%m-%dT%H:%M:%S")), ("SubTotal", fmt(subtotal)),
                 ("Descuento", fmt(total_deductions) if deductions else None),
                 ("Moneda", fixed("Comprobante.Moneda")), ("Total", fmt(total)),
                 ("TipoDeComprobante", fixed("Comprobante.TipoDeComprobante")),
                 ("Exportacion", fixed("Comprobante.Exportacion")), ("MetodoPago", fixed("Comprobante.MetodoPago")),
                 ("LugarExpedicion", doc["placeOfIssue"])])
    if doc.get("replacesUuid"):
        rel = attrs(etree.SubElement(root, C("CfdiRelacionados")),
                    [("TipoRelacion", fixed("CfdiRelacionados.TipoRelacion"))])
        attrs(etree.SubElement(rel, C("CfdiRelacionado")), [("UUID", doc["replacesUuid"])])
    attrs(etree.SubElement(root, C("Emisor")), [("Rfc", issuer["rfc"]), ("Nombre", issuer["name"]),
                                                ("RegimenFiscal", issuer["regime"])])
    attrs(etree.SubElement(root, C("Receptor")),
          [("Rfc", receiver["rfc"]), ("Nombre", receiver["name"]),
           ("DomicilioFiscalReceptor", receiver["fiscalPostalCode"]),
           ("RegimenFiscalReceptor", fixed("Receptor.RegimenFiscalReceptor")), ("UsoCFDI", fixed("Receptor.UsoCFDI"))])
    concepts = etree.SubElement(root, C("Conceptos"))
    attrs(etree.SubElement(concepts, C("Concepto")),
          [("ClaveProdServ", fixed("Concepto.ClaveProdServ")), ("Cantidad", fixed("Concepto.Cantidad")),
           ("ClaveUnidad", fixed("Concepto.ClaveUnidad")), ("Descripcion", fixed("Concepto.Descripcion")),
           ("ValorUnitario", fmt(subtotal)), ("Importe", fmt(subtotal)),
           ("Descuento", fmt(total_deductions) if deductions else None),
           ("ObjetoImp", fixed("Concepto.ObjetoImp"))])
    complemento = etree.SubElement(root, C("Complemento"))
    nomina = attrs(etree.SubElement(complemento, N("Nomina")),
                   [("Version", fixed("Nomina.Version")),
                    ("TipoNomina", fixed("Nomina.TipoNomina.extraordinary" if extraordinary
                                         else "Nomina.TipoNomina.ordinary")),
                    ("FechaPago", pay_date.isoformat()), ("FechaInicialPago", start.isoformat()),
                    ("FechaFinalPago", end.isoformat()), ("NumDiasPagados", f"{days_paid.quantize(Decimal('0.001'))}"),
                    ("TotalPercepciones", fmt(total_perceptions) if perceptions else None),
                    ("TotalDeducciones", fmt(total_deductions) if deductions else None),
                    ("TotalOtrosPagos", fmt(total_others) if others else None)])
    if issuer.get("registroPatronal") or (not moral and issuer.get("curp")):
        attrs(etree.SubElement(nomina, N("Emisor")),
              [("Curp", None if moral else issuer.get("curp")), ("RegistroPatronal", issuer.get("registroPatronal"))])
    weeks = (end - seniority).days // 7 if (seniority and issuer.get("registroPatronal")) else None   # S4 pp. 31–32
    attrs(etree.SubElement(nomina, N("Receptor")),
          [("Curp", receiver["curp"]), ("NumSeguridadSocial", receiver.get("nss") if issuer.get("registroPatronal") else None),
           ("FechaInicioRelLaboral", seniority.isoformat() if weeks is not None else None),
           ("Antigüedad", fixed("Nomina.Receptor.Antiguedad.weeks").format(weeks=weeks) if weeks is not None
            else None),
           ("TipoContrato", contract), ("Sindicalizado", receiver.get("unionized")),
           ("TipoJornada", receiver.get("workdayType")), ("TipoRegimen", regime),
           ("NumEmpleado", receiver["employeeNumber"]), ("Puesto", receiver.get("position")),
           ("RiesgoPuesto", receiver.get("riskClass") if issuer.get("registroPatronal") else None),
           ("PeriodicidadPago", frequency),
           ("SalarioDiarioIntegrado", fmt(_dec(receiver["sdi"], "sdi")) if issuer.get("registroPatronal") else None),
           ("ClaveEntFed", receiver["state"])])
    if perceptions:
        pe = attrs(etree.SubElement(nomina, N("Percepciones")),
                   [("TotalSueldos", fmt(sueldos) if sueldos else None),
                    ("TotalSeparacionIndemnizacion", fmt(separation) if separation else None),
                    ("TotalJubilacionPensionRetiro", fmt(retirement) if retirement else None),
                    ("TotalGravado", fmt(taxed_total)), ("TotalExento", fmt(exempt_total))])
        for code, line, taxed, exempt in perceptions:
            attrs(etree.SubElement(pe, N("Percepcion")),
                  [("TipoPercepcion", code), ("Clave", line["key"]), ("Concepto", line["concept"]),
                   ("ImporteGravado", fmt(taxed)), ("ImporteExento", fmt(exempt))])
    if deductions:
        de = attrs(etree.SubElement(nomina, N("Deducciones")),
                   [("TotalOtrasDeducciones", fmt(other_deductions) if other_deductions else None),
                    ("TotalImpuestosRetenidos", fmt(isr) if isr else None)])
        for code, line, amount in deductions:
            attrs(etree.SubElement(de, N("Deduccion")),
                  [("TipoDeduccion", code), ("Clave", line["key"]), ("Concepto", line["concept"]),
                   ("Importe", fmt(amount))])
    if others:
        op = etree.SubElement(nomina, N("OtrosPagos"))
        for code, line, amount in others:
            attrs(etree.SubElement(op, N("OtroPago")),
                  [("TipoOtroPago", code), ("Clave", line["key"]), ("Concepto", line["concept"]),
                   ("Importe", fmt(amount))])
    payload = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    validate(payload, set_id)
    return payload


# ── validation (X2) ──────────────────────────────────────────────────────────

_ATTRIBUTE = re.compile(r"attribute '([A-Za-zÀ-ÿ]+)'")
_ELEMENT = re.compile(r"Element '(?:\{[^}]*\})?([A-Za-z]+)'")


def _safe(error) -> str:
    """An XSD error as element / attribute / failed check — never a value (MX-061)."""
    element = _ELEMENT.search(error.message or "")
    attribute = _ATTRIBUTE.search(error.message or "")
    where = (element.group(1) if element else (error.path or "?").rsplit("/", 1)[-1].split(":")[-1])
    if attribute:
        where += f"@{attribute.group(1)}"
    return f"{where}: {error.type_name}"


def validate(payload: bytes, set_id: str) -> None:
    """Validate against the pinned CFDI 4.0 + Nómina 1.2 schemas. The signer's
    three attributes are filled on a throwaway copy (the builder never writes
    them); the result names only element / attribute / failed check."""
    from lxml import etree

    copy = etree.fromstring(payload, etree.XMLParser(no_network=True, resolve_entities=False))
    for name, value in (("Sello", " "), ("NoCertificado", "0" * 20), ("Certificado", " ")):
        if copy.get(name) is None:
            copy.set(name, value)
    schema = mexico_cfdi_schema.combined_schema(set_id)
    if not schema.validate(copy):
        found = sorted({_safe(e) for e in schema.error_log})
        raise MXBlock("MX_CFDI_XSD_INVALID", "the document does not validate against the pinned SAT schemas: "
                      + "; ".join(found), reasons=[("MX_CFDI_XSD_INVALID", f) for f in found])
