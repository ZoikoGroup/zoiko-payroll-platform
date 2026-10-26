"""
engine/countries/mexico_rules.py
--------------------------------
Mexico special-payment RULE OBJECTS (completion programme W1-3), written at
transcription from the saved text — the interfaces are engine/jurisdictions/
mexico/special_pay.py and termination.py. mexico_content wires instances in;
the engine never reads this module directly.

Each rule cites the wording it rests on (`citations`: (source, ref) pairs,
every ref quoting the source — verify_mexico_sources.py `compare` finds each
quote in its file). Three points the sources leave open are switches below,
None until the owner decides (docs/mexico/DECISIONS_PENDING.md); while one is
None the case that needs it BLOCKS with its own code — never a guess:

  D-07  MX_EXEMPTION_WAGE_REFERENCE  — LISR Art. 93 XIII / XIV word their caps
        in "salario mínimo general del área geográfica"; read as the UMA (S34
        Transitorio Tercero) or as the worker's zone minimum wage (RLISR
        Art. 167: the place of work)?  "UMA" / "ZONE_MIN_WAGE"
  D-08  MX_SPECIAL_PAY_WITHHOLDING_METHOD — LISR Art. 96 lets the payer of
        aguinaldo / PTU / vacation premium withhold under RLISR Art. 174
        ("podrá optar"); the default is the monthly tariff on the month's whole
        income, which needs month-to-date ordinary income a special run does
        not carry yet.  "RLISR_174"
  D-09  MX_MONTHLY_ORDINARY_INCOME_DAYS — "último sueldo mensual ordinario"
        (LISR Arts. 95, 96) and "el ingreso ordinario … en el mes" (RLISR
        Art. 174 II) are not defined from a daily salary.  Days per month, e.g.
        "30" or "30.4"
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

_S24 = "S24/S24_DIP_LISR.pdf"
_S25 = "S25/S25_DIP_RLISR.pdf"
_S26 = "S26/S26_DIP_LFT.pdf"
_S34 = "S34/S34_DIP_CPEUM_ref226_27ene16.pdf"

# ── Decision switches (None = undecided: the dependent case BLOCKS) ─────────
MX_EXEMPTION_WAGE_REFERENCE = None         # D-07: "UMA" | "ZONE_MIN_WAGE"
MX_SPECIAL_PAY_WITHHOLDING_METHOD = None   # D-08: "RLISR_174"
MX_MONTHLY_ORDINARY_INCOME_DAYS = None     # D-09: e.g. "30.4"
WAGE_REFERENCES = ("UMA", "ZONE_MIN_WAGE")
WITHHOLDING_METHODS = ("RLISR_174",)

_ZERO, _ONE = Decimal("0"), Decimal("1")

# LISR Art. 93 XIV: days of the reference wage exempt per calendar year, per concept.
ART93_XIV_DAYS = {"AGUINALDO": Decimal("30"), "VACATION_PREMIUM": Decimal("15"), "PTU": Decimal("15")}
# LISR Art. 93 XIII: the reference wage × 90 per year of service, shared by every separation payment.
ART93_XIII_DAYS_PER_YEAR = Decimal("90")
SEPARATION_CONCEPTS = ("SEPARATION_SENIORITY_PREMIUM", "SEPARATION_PAYMENT", "SEPARATION_INDEMNITY")
# RLISR Art. 174 I: remuneration ÷ 365 × 30.4.
RLISR_174_DIVISOR, RLISR_174_MULTIPLIER = Decimal("365"), Decimal("30.4")

_C_93_XIV = (_S24, "Art. 93 XIV: 'Las gratificaciones que reciban los trabajadores de sus patrones, durante un ano "
                   "de calendario, hasta el equivalente del salario minimo general del area geografica del "
                   "trabajador elevado a 30 dias'; 'las primas vacacionales'; 'la participacion de los trabajadores "
                   "en las utilidades de las empresas, hasta por el equivalente a 15 dias de salario minimo general "
                   "del area geografica del trabajador, por cada uno de los conceptos senalados', PDF p. 123")
_C_93_XIII = (_S24, "Art. 93 XIII: 'por concepto de primas de antiguedad, retiro e indemnizaciones u otros pagos'; "
                    "'hasta por el equivalente a noventa veces el salario minimo general del area geografica del "
                    "contribuyente por cada ano de servicio'; 'mas de seis meses se considerara un ano completo' "
                    "(continuing 'Toda fraccion de' across the page break), PDF pp. 122-123")
_C_93_I = (_S24, "Art. 93 I: 'Las prestaciones distintas del salario que reciban los trabajadores del salario minimo "
                 "general para una o varias areas geograficas' (not modelled: such a worker BLOCKS), PDF p. 121")
_C_96 = (_S24, "Art. 96: 'La retencion se calculara aplicando a la totalidad de los ingresos obtenidos en un mes de "
               "calendario'; 'podran efectuar la retencion del impuesto de conformidad con los requisitos que "
               "establezca el Reglamento de esta Ley', PDF p. 130")
_C_174 = (_S25, "Art. 174: 'La remuneracion de que se trate se dividira entre 365 y el resultado se multiplicara por "
                "30.4'; 'se le adicionara el ingreso ordinario por la prestacion de un servicio personal subordinado "
                "que perciba el trabajador'; 'se disminuira con el Impuesto que corresponderia al ingreso "
                "ordinario'; 'dividiendo el Impuesto que se determine en terminos de la fraccion III de este "
                "articulo entre la cantidad que resulte conforme a la fraccion I', PDF pp. 45-46")
_C_167 = (_S25, "Art. 167: 'podran considerar el salario minimo general del area geografica que corresponda al "
                "lugar donde el trabajador preste sus servicios', PDF p. 44")
_C_S34 = (_S34, "Transitorio Tercero: 'todas las menciones al salario minimo como unidad de cuenta, indice, base, "
                "medida o referencia para determinar la cuantia de las obligaciones', PDF p. 2")


def _blocked(code: str, detail: str):
    from ..jurisdictions.mexico.errors import MXBlock

    return MXBlock(code, detail)


def _d(value, what: str) -> Decimal:
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:                                      # noqa: BLE001
        raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", f"{what} is missing or not a number")
    if not out.is_finite():
        raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", f"{what} is not a finite number")
    return out


def _date(value, what: str) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str) and value:
        return _dt.date.fromisoformat(value[:10])
    raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", f"{what} is missing")


def reference_wage(facts: dict) -> Decimal:
    """The daily wage Art. 93's caps are counted in (D-07)."""
    ref = MX_EXEMPTION_WAGE_REFERENCE
    if ref is None:
        raise _blocked("MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED",
                       "LISR Art. 93 words its exempt limits in the area minimum wage; whether that reads as the UMA "
                       "(S34) or the worker's zone minimum wage is a G1 decision (DECISIONS_PENDING D-07)")
    if ref not in WAGE_REFERENCES:
        raise _blocked("MX_RULE_UNRECOGNISED", f"exemption wage reference {ref!r} is not one of {WAGE_REFERENCES}")
    content = facts.get("content")
    if content is None:
        raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", "the in-force content is missing")
    if ref == "UMA":
        return content.amount("mx_uma_daily")
    zone = facts.get("zone")
    if zone not in ("GENERAL", "ZLFN"):
        raise _blocked("MX_MIN_WAGE_ZONE_UNRESOLVED", "the worker's minimum-wage zone is not resolved (RLISR Art. 167)")
    return content.min_wage(zone)


def _check_not_minimum_wage_worker(facts: dict) -> None:
    """Art. 93 I exempts in full, for a worker on the area minimum wage, the
    benefits within the legal minimums — not modelled, so such a worker BLOCKS
    rather than being taxed under fr. XIV."""
    content, zone = facts.get("content"), facts.get("zone")
    if zone not in ("GENERAL", "ZLFN") or content is None:
        raise _blocked("MX_MIN_WAGE_ZONE_UNRESOLVED", "the worker's minimum-wage zone is not resolved")
    if _d(facts.get("daily_salary"), "the daily salary") <= content.min_wage(zone):
        raise _blocked("MX_ART93_I_NOT_MODELLED",
                       "the worker earns the area minimum wage: LISR Art. 93 I (full exemption within the legal "
                       "minimums) applies and is not modelled")


def years_of_service_art93_xiii(seniority_date, separation_date) -> int:
    """Art. 93 XIII: whole years, a fraction of more than six months counted as a full year."""
    start, end = _date(seniority_date, "the seniority date"), _date(separation_date, "the separation date")
    if end < start:
        raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", "the separation date is before the seniority date")
    years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    anniversary = _add_years(start, years)
    six_months = _add_months(anniversary, 6)
    return years + (1 if end > six_months else 0)


def _add_years(d: _dt.date, n: int) -> _dt.date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                                      # 29 Feb → 28 Feb
        return d.replace(year=d.year + n, day=28)


def _add_months(d: _dt.date, n: int) -> _dt.date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise ValueError(d)


def monthly_ordinary_income(facts: dict) -> Decimal:
    """D-09: the monthly ordinary income derived from the daily salary."""
    days = MX_MONTHLY_ORDINARY_INCOME_DAYS
    if days is None:
        raise _blocked("MX_MONTHLY_ORDINARY_INCOME_UNDECIDED",
                       "how the monthly ordinary salary (LISR Arts. 95, 96; RLISR Art. 174 II) is derived from the "
                       "daily salary is a G1 decision (DECISIONS_PENDING D-09)")
    return _d(facts.get("daily_salary"), "the daily salary") * Decimal(str(days))


def monthly_isr(base: Decimal, facts: dict) -> Decimal:
    """The Art. 96 monthly tariff (S2 B.V) on `base`, full precision."""
    from ..jurisdictions.mexico import isr

    content = facts.get("content")
    if content is None:
        raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", "the in-force content is missing")
    return isr.withholding(base, content.isr_tariff("MONTHLY"))["isr"]


class Art93SpecialPayRule:
    """LISR Art. 93 exempt part of one special concept, and its withholding.

    XIV concepts (aguinaldo, vacation premium, PTU): exempt up to N days of the
    reference wage per calendar year, less what earlier payments of the same
    concept in that year already used (facts["year_to_date_exempt"]).
    XIII concepts (the three separation kinds): exempt up to 90 days of the
    reference wage per year of service, shared by every separation payment of
    the separation (facts["separation_total"]), allocated pro rata.
    VACATION_PAYOUT: no Art. 93 exemption names it — fully taxable."""

    def __init__(self, concept: str, citations: tuple, *, combine_with_ordinary: bool):
        self.concept = concept
        self.citations = citations
        self.source, self.source_ref = citations[0]
        self.combine_with_ordinary = combine_with_ordinary

    def exempt(self, concept, amount, facts) -> Decimal:
        amount = _d(amount, f"the {concept} amount")
        if amount <= 0:
            return _ZERO
        if concept == "VACATION_PAYOUT":
            return _ZERO
        _check_not_minimum_wage_worker(facts)
        wage = reference_wage(facts)
        if concept in ART93_XIV_DAYS:
            cap = ART93_XIV_DAYS[concept] * wage
            ytd = facts.get("year_to_date_exempt")
            if ytd is None:
                raise _blocked("MX_YEAR_TO_DATE_EXEMPT_MISSING",
                               "the calendar year's exempt amounts already used are not supplied (Art. 93 XIV)")
            used = _d(ytd.get(concept, _ZERO), f"the {concept} exempt amount already used")
            return min(amount, max(cap - used, _ZERO))
        if concept in SEPARATION_CONCEPTS:
            years = years_of_service_art93_xiii(facts.get("seniority_date"), facts.get("separation_date"))
            cap = ART93_XIII_DAYS_PER_YEAR * wage * years
            total = _d(facts.get("separation_total"), "the separation total")
            if total <= 0 or amount > total:
                raise _blocked("MX_SPECIAL_PAY_FACT_MISSING", "the separation total does not include this payment")
            return min(amount, cap * amount / total) if total > cap else amount
        raise _blocked("MX_SPECIAL_PAY_RULE_MISSING", f"no Art. 93 rule for {concept}")

    def standalone_isr(self, taxable, facts) -> Decimal:
        """RLISR Art. 174 (D-08): a special payment withheld in its own run."""
        method = MX_SPECIAL_PAY_WITHHOLDING_METHOD
        if method is None:
            raise _blocked("MX_SPECIAL_PAY_METHOD_UNDECIDED",
                           "which withholding method applies to a special payment paid in its own run (LISR Art. 96 "
                           "monthly tariff, or the RLISR Art. 174 option) is a decision (DECISIONS_PENDING D-08)")
        if method not in WITHHOLDING_METHODS:
            raise _blocked("MX_RULE_UNRECOGNISED", f"withholding method {method!r} is not one of {WITHHOLDING_METHODS}")
        if self.concept not in ("AGUINALDO", "PTU", "VACATION_PREMIUM"):
            raise _blocked("MX_SPECIAL_PAY_METHOD_UNSUPPORTED",
                           f"RLISR Art. 174 covers the annual bonus, PTU and the Sunday and vacation premiums, not "
                           f"{self.concept}")
        taxable = _d(taxable, "the taxable amount")
        if taxable <= 0:
            return _ZERO
        monthly = taxable / RLISR_174_DIVISOR * RLISR_174_MULTIPLIER            # fr. I
        ordinary = monthly_ordinary_income(facts)                               # fr. II
        difference = monthly_isr(ordinary + monthly, facts) - monthly_isr(ordinary, facts)   # fr. III
        rate = difference / monthly                                             # fr. V
        return taxable * rate                                                   # fr. IV


class Lft87AguinaldoRule:
    """LFT Art. 87: payable before 20 December; a worker who has not completed
    the year of service gets the part proportional to the time worked."""

    citations = ((_S26, "Art. 87: 'aguinaldo anual que debera pagarse antes del dia veinte de diciembre'; 'tendran "
                        "derecho a que se les pague la parte proporcional del mismo, conforme al tiempo que hubieren "
                        "trabajado', PDF p. 25"),)
    source, source_ref = citations[0]

    def fraction(self, year, employed_from, employed_to) -> Decimal:
        """Days employed within the calendar year ÷ days in that year (both ends counted)."""
        first, last = _dt.date(year, 1, 1), _dt.date(year, 12, 31)
        start = max(_date(employed_from, "the start of employment"), first)
        end = min(_date(employed_to, "the end of employment") if employed_to else last, last)
        if end < start:
            return _ZERO
        return Decimal((end - start).days + 1) / Decimal((last - first).days + 1)

    def payable_by(self, year) -> _dt.date:
        return _dt.date(year, 12, 19)                         # "antes del día veinte de diciembre"


_XIV = (_C_93_XIV, _C_93_I, _C_96, _C_174, _C_167, _C_S34)
_XIII = (_C_93_XIII, _C_93_I, _C_96, _C_167, _C_S34)
SPECIAL_PAY_RULES = {
    "AGUINALDO": Art93SpecialPayRule("AGUINALDO", _XIV, combine_with_ordinary=True),
    "VACATION_PREMIUM": Art93SpecialPayRule("VACATION_PREMIUM", _XIV, combine_with_ordinary=True),
    "PTU": Art93SpecialPayRule("PTU", _XIV, combine_with_ordinary=True),
    "VACATION_PAYOUT": Art93SpecialPayRule("VACATION_PAYOUT", (_C_96,), combine_with_ordinary=True),
    **{k: Art93SpecialPayRule(k, _XIII, combine_with_ordinary=False) for k in SEPARATION_CONCEPTS},
}
AGUINALDO_RULE = Lft87AguinaldoRule()
