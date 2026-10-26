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


# ═══ W1-3b: termination reasons and the finiquito rule (LFT; LISR Arts. 95–96) ═══
# Further points the sources leave open (DECISIONS_PENDING), None = BLOCK:
#   D-12  MX_INDEMNITY_SALARY_BASIS — LFT Art. 89: indemnities on the daily
#         rate "y la parte proporcional de las prestaciones mencionadas en el
#         artículo 84". "POLICY_INTEGRATED" = daily salary × the labour policy's
#         integration factor (aguinaldo + vacation premium) — the same question
#         as gap C4 (the SDI source).
#   D-13  MX_SERVICE_YEARS_COUNT — "por cada año de servicios" (Arts. 50, 54,
#         162): "PROPORTIONAL" (a part year counts pro rata) or "COMPLETED"
#         (whole years only).
#   D-07b MX_SENIORITY_PREMIUM_WAGE_REFERENCE — Arts. 485–486 bound the
#         seniority-premium salary by the minimum wage and twice "el salario
#         mínimo del área geográfica de aplicación": "ZONE_MIN_WAGE" or "UMA".
MX_INDEMNITY_SALARY_BASIS = None             # D-12: "POLICY_INTEGRATED"
MX_SERVICE_YEARS_COUNT = None                # D-13: "PROPORTIONAL" | "COMPLETED"
MX_SENIORITY_PREMIUM_WAGE_REFERENCE = None   # D-07b: "ZONE_MIN_WAGE" | "UMA"
INDEMNITY_SALARY_BASES = ("POLICY_INTEGRATED",)
SERVICE_YEARS_COUNTS = ("PROPORTIONAL", "COMPLETED")

# SAT c_TipoContrato (S28 / pinned set sat_2026_08): 01 "tiempo indeterminado", 03 "tiempo determinado".
CONTRACT_INDEFINITE, CONTRACT_FIXED_TERM = "01", "03"
SENIORITY_PREMIUM_DAYS_PER_YEAR = Decimal("12")         # LFT Art. 162 I; Art. 54
INDEMNITY_DAYS_PER_YEAR = Decimal("20")                 # LFT Art. 50 I, II
THREE_MONTHS_DAYS = Decimal("90")                       # Arts. 48 / 50 III "tres meses de salario" (TL-TER-1)
ONE_MONTH_DAYS = Decimal("30")                          # Art. 54 "un mes de salario"; Art. 89 ¶3 ÷ 30
SIX_MONTHS_DAYS = Decimal("180")                        # Art. 50 I "seis meses por el primer año"
VOLUNTARY_MIN_YEARS = 15                                # Art. 162 III

_C_47 = (_S26, "Art. 47: 'Son causas de rescision de la relacion de trabajo, sin responsabilidad para el patron', "
               "PDF p. 15")
_C_48 = (_S26, "Art. 48: 'que se le indemnice con el importe de tres meses de salario, a razon del que corresponda a la "
               "fecha en que se realice el pago', PDF p. 16")
_C_49 = (_S26, "Art. 49: 'quedara eximida de la obligacion de reinstalar a la persona trabajadora, mediante el pago de "
               "las indemnizaciones que se determinan en el articulo 50', PDF p. 18")
_C_50 = (_S26, "Art. 50: 'Si la relacion de trabajo fuere por tiempo determinado menor de un ano, en una cantidad igual "
               "al importe de los salarios de la mitad del tiempo de servicios prestados'; 'seis meses por el primer ano "
               "y de veinte dias por cada uno de los anos siguientes'; 'la indemnizacion consistira en veinte dias de "
               "salario por cada uno de los anos de servicios prestados'; 'en el importe de tres meses de salario', "
               "PDF p. 19")
_C_51_52 = (_S26, "Art. 52: 'tendra derecho a que el patron lo indemnice en los terminos del articulo 50', PDF p. 20")
_C_53 = (_S26, "Art. 53: 'La terminacion de la obra o vencimiento del termino o inversion del capital', PDF p. 20")
_C_54 = (_S26, "Art. 54: 'tendra derecho a que se le pague un mes de salario y doce dias por cada ano de servicios, de "
               "conformidad con lo dispuesto en el articulo 162', PDF p. 21")
_C_162 = (_S26, "Art. 162: 'Los trabajadores de planta tienen derecho a una prima de antiguedad'; 'consistira en el "
                "importe de doce dias de salario, por cada ano de servicios'; 'se pagara a los trabajadores que se "
                "separen voluntariamente de su empleo, siempre que hayan cumplido quince anos de servicios, por lo "
                "menos'; 'a los que se separen por causa justificada y a los que sean separados de su empleo, "
                "independientemente de la justificacion o injustificacion del despido', PDF p. 52")
_C_485 = (_S26, "Arts. 485-486: 'no podra ser inferior al salario minimo'; 'excede del doble del salario minimo del "
                "area geografica de aplicacion a que corresponda el lugar de prestacion del trabajo, se considerara "
                "esa cantidad como salario maximo', PDF p. 142")
_C_89 = (_S26, "Art. 89: 'se tomara como base el salario correspondiente al dia en que nazca el derecho a la "
               "indemnizacion, incluyendo en el la cuota diaria y la parte proporcional de las prestaciones mencionadas "
               "en el articulo 84', PDF p. 25")
_C_79 = (_S26, "Art. 79: 'Si la relacion de trabajo termina antes de que se cumpla el ano de servicios, el trabajador "
               "tendra derecho a una remuneracion proporcionada al tiempo de servicios prestados', PDF p. 24")
_C_76 = (_S26, "Art. 76: 'disfrutaran de un periodo anual de vacaciones pagadas', PDF p. 24")
_C_96_SEP = (_S24, "Art. 96: 'una tasa que se calculara dividiendo el impuesto correspondiente al ultimo sueldo mensual "
                   "ordinario, entre dicho sueldo'; 'Cuando los pagos por estos conceptos sean inferiores al ultimo "
                   "sueldo mensual ordinario, la retencion se calculara aplicandoles la tarifa establecida en este "
                   "articulo', PDF p. 131")
_C_172 = (_S25, "Art. 172: 'disminuida por la cantidad que resulte de aplicar lo dispuesto en el articulo 93, fraccion "
                "XIII de la Ley', PDF p. 45")


def _whole_years(start: _dt.date, end: _dt.date) -> int:
    return end.year - start.year - ((end.month, end.day) < (start.month, start.day))


def service_years(seniority_date, termination_date) -> Decimal:
    """Years of service under D-13: whole years, plus the part year pro rata
    (days since the last anniversary ÷ days to the next one) when PROPORTIONAL."""
    mode = MX_SERVICE_YEARS_COUNT
    if mode is None:
        raise _blocked("MX_SERVICE_YEARS_COUNT_UNDECIDED",
                       "whether 'por cada año de servicios' (LFT Arts. 50, 54, 162) counts a part year is a decision "
                       "(DECISIONS_PENDING D-13)")
    if mode not in SERVICE_YEARS_COUNTS:
        raise _blocked("MX_RULE_UNRECOGNISED", f"service-years count {mode!r} is not one of {SERVICE_YEARS_COUNTS}")
    start, end = _date(seniority_date, "the seniority date"), _date(termination_date, "the termination date")
    if end < start:
        raise _blocked("MX_TERMINATION_FACT_MISSING", "the termination date is before the seniority date")
    whole = _whole_years(start, end)
    if mode == "COMPLETED":
        return Decimal(whole)
    last, nxt = _add_years(start, whole), _add_years(start, whole + 1)
    return Decimal(whole) + Decimal((end - last).days) / Decimal((nxt - last).days)


def indemnity_daily_salary(facts: dict) -> Decimal:
    """LFT Art. 89 (D-12): the daily salary indemnities are counted in."""
    basis = MX_INDEMNITY_SALARY_BASIS
    if basis is None:
        raise _blocked("MX_INDEMNITY_SALARY_UNDECIDED",
                       "LFT Art. 89 counts indemnities on the daily rate plus the proportional Art. 84 benefits; how "
                       "that integrated salary is built is a decision (DECISIONS_PENDING D-12, gap C4)")
    if basis not in INDEMNITY_SALARY_BASES:
        raise _blocked("MX_RULE_UNRECOGNISED", f"indemnity salary basis {basis!r} is not one of {INDEMNITY_SALARY_BASES}")
    from ..jurisdictions.mexico import sbc

    policy = facts.get("labor_policy")
    if not policy:
        raise _blocked("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force on the termination date")
    year = sbc.service_year(_date(facts.get("seniority_date"), "the seniority date"),
                            _date(facts.get("termination_date"), "the termination date"))
    return _d(facts.get("daily_salary"), "the daily salary") * sbc.integration_factor(policy, year)["factor"]


def seniority_premium_daily_salary(facts: dict) -> Decimal:
    """LFT Art. 162 II → Arts. 485–486: the daily salary, no lower than the
    zone minimum wage, no higher than twice the reference wage (D-07b)."""
    ref = MX_SENIORITY_PREMIUM_WAGE_REFERENCE
    if ref is None:
        raise _blocked("MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED",
                       "LFT Art. 486 caps the seniority-premium salary at twice the area minimum wage; whether that "
                       "reads as the zone minimum wage or the UMA is a decision (DECISIONS_PENDING D-07)")
    if ref not in WAGE_REFERENCES:
        raise _blocked("MX_RULE_UNRECOGNISED", f"seniority-premium wage reference {ref!r} is not one of {WAGE_REFERENCES}")
    content, zone = facts.get("content"), facts.get("zone")
    if content is None or zone not in ("GENERAL", "ZLFN"):
        raise _blocked("MX_MIN_WAGE_ZONE_UNRESOLVED", "the worker's minimum-wage zone is not resolved")
    floor = content.min_wage(zone)
    cap = Decimal("2") * (content.amount("mx_uma_daily") if ref == "UMA" else floor)
    return min(max(_d(facts.get("daily_salary"), "the daily salary"), floor), cap)


def _contract(facts: dict) -> str:
    code = str(facts.get("contract_type_code") or "").strip()
    if code not in (CONTRACT_INDEFINITE, CONTRACT_FIXED_TERM):
        raise _blocked("MX_TERMINATION_CONTRACT_UNSUPPORTED",
                       f"contract type {code or '(none)'}: only 01 (tiempo indeterminado) and 03 (tiempo determinado) "
                       f"have a transcribed LFT Art. 50 indemnity")
    return code


def _seniority_premium(facts: dict):
    """Art. 162 I: 12 days of the Art. 485–486 salary per year of service, for
    a worker 'de planta' — read as an indefinite contract (TL-TER-1)."""
    if _contract(facts) != CONTRACT_INDEFINITE:
        return None
    years = service_years(facts.get("seniority_date"), facts.get("termination_date"))
    return {"code": "SENIORITY_PREMIUM", "label": "Prima de antigüedad (LFT Art. 162)",
            "kind": "SEPARATION_SENIORITY_PREMIUM",
            "amount": SENIORITY_PREMIUM_DAYS_PER_YEAR * years * seniority_premium_daily_salary(facts)}


def _art50_indemnity(facts: dict) -> list:
    """Art. 50 I (fixed term) or II (indefinite), plus III (three months)."""
    daily = indemnity_daily_salary(facts)
    if _contract(facts) == CONTRACT_INDEFINITE:
        years = service_years(facts.get("seniority_date"), facts.get("termination_date"))
        by_years = INDEMNITY_DAYS_PER_YEAR * years * daily                                      # fr. II
    else:
        start = _date(facts.get("seniority_date"), "the seniority date")
        end = _date(facts.get("termination_date"), "the termination date")
        if _add_years(start, 1) > end:                                                         # fr. I, under a year
            by_years = Decimal((end - start).days + 1) / 2 * daily
        else:                                                                                  # fr. I, over a year
            later = service_years(_add_years(start, 1), end)
            by_years = (SIX_MONTHS_DAYS + INDEMNITY_DAYS_PER_YEAR * later) * daily
    return [{"code": "INDEMNITY_ART50_YEARS", "label": "Indemnización por años de servicio (LFT Art. 50 I-II)",
             "kind": "SEPARATION_INDEMNITY", "amount": by_years},
            {"code": "INDEMNITY_3_MONTHS", "label": "Indemnización de tres meses (LFT Art. 50 III)",
             "kind": "SEPARATION_INDEMNITY", "amount": THREE_MONTHS_DAYS * daily}]


def _three_months(facts: dict) -> dict:
    return {"code": "INDEMNITY_3_MONTHS", "label": "Indemnización de tres meses (LFT Art. 48)",
            "kind": "SEPARATION_INDEMNITY", "amount": THREE_MONTHS_DAYS * indemnity_daily_salary(facts)}


def _one_month(facts: dict) -> dict:
    return {"code": "ONE_MONTH_ART54", "label": "Un mes de salario (LFT Art. 54)", "kind": "SEPARATION_PAYMENT",
            "amount": ONE_MONTH_DAYS * indemnity_daily_salary(facts)}


def _voluntary(facts: dict) -> list:
    start = _date(facts.get("seniority_date"), "the seniority date")
    end = _date(facts.get("termination_date"), "the termination date")
    return [_seniority_premium(facts)] if _whole_years(start, end) >= VOLUNTARY_MIN_YEARS else []


class LftTerminationReason:
    def __init__(self, code: str, label: str, citations: tuple, components):
        self.code, self.label, self.citations = code, label, citations
        self.source, self.source_ref = citations[0]
        self._components = components

    def separation_components(self, facts) -> list:
        return [c for c in self._components(facts) if c]


TERMINATION_REASONS = {r.code: r for r in (
    LftTerminationReason("LFT_47_RESCISSION_BY_EMPLOYER", "Rescisión por el patrón con causa (LFT Art. 47)",
                         (_C_47, _C_162, _C_485), lambda f: [_seniority_premium(f)]),
    LftTerminationReason("LFT_48_DISMISSAL_INDEMNIFIED", "Despido indemnizado con tres meses (LFT Art. 48)",
                         (_C_48, _C_89, _C_162, _C_485), lambda f: [_three_months(f), _seniority_premium(f)]),
    LftTerminationReason("LFT_49_NO_REINSTATEMENT", "Patrón eximido de reinstalar (LFT Arts. 49-50)",
                         (_C_49, _C_50, _C_89, _C_162, _C_485), lambda f: _art50_indemnity(f) + [_seniority_premium(f)]),
    LftTerminationReason("LFT_51_RESCISSION_BY_WORKER", "Rescisión por el trabajador (LFT Arts. 51-52)",
                         (_C_51_52, _C_50, _C_89, _C_162, _C_485),
                         lambda f: _art50_indemnity(f) + [_seniority_premium(f)]),
    LftTerminationReason("LFT_53_III_END_OF_TERM", "Terminación de la obra o vencimiento del término (LFT Art. 53 III)",
                         (_C_53,), lambda f: []),
    LftTerminationReason("LFT_54_INCAPACITY", "Incapacidad por riesgo no profesional (LFT Arts. 53 IV, 54)",
                         (_C_54, _C_89, _C_162, _C_485), lambda f: [_one_month(f), _seniority_premium(f)]),
    LftTerminationReason("LFT_162_VOLUNTARY_SEPARATION", "Separación voluntaria (LFT Art. 162 III)",
                         (_C_162, _C_485), _voluntary),
)}


class FiniquitoRule:
    """Vacation owed at termination (LFT Arts. 76, 79) and the finiquito's
    withholding (LISR Arts. 95–96, RLISR Arts. 172, 174)."""

    citations = (_C_79, _C_76, _C_96_SEP, _C_172, _C_174)
    source, source_ref = citations[0]

    def vacation_days_owed(self, years, termination_date) -> dict:
        """Each completed service year: its days not yet taken or paid out
        (TL-TER-2); the year the termination falls in: its days in proportion
        to the time served in it (Art. 79 ¶2)."""
        out = {}
        for y in years:
            balance = (_d(y.get("opening") or 0, "opening days") - _d(y.get("taken") or 0, "taken days")
                       - _d(y.get("paid_out") or 0, "paid-out days"))
            earned = _d(y.get("policy_days"), "policy vacation days")
            if not y.get("complete"):
                start, end = _date(y.get("start"), "the service-year start"), _date(y.get("end"), "its end")
                earned = earned * Decimal((end - start).days + 1) / Decimal((_add_years(start, 1) - start).days)
            out[int(y["service_year"])] = max(earned + balance, _ZERO)
        return out

    def isr(self, taxable_by_concept, facts) -> Decimal:
        """Separation (LISR Art. 96 ¶7): the rate of the last monthly ordinary
        salary on the separation's taxable total, or the tariff when the total
        is below that salary. Aguinaldo / vacation premium: their special-pay
        rule (D-08). Vacation paid out is ordinary income of the month, which
        a finiquito run cannot see yet (gap A17): it BLOCKS."""
        if _d(taxable_by_concept.get("VACATION_PAYOUT", _ZERO), "VACATION_PAYOUT") > 0:
            raise _blocked("MX_FINIQUITO_ORDINARY_INCOME_UNSUPPORTED",
                           "vacation paid out at termination is ordinary income of the month (LISR Art. 96); a "
                           "finiquito run carries no month-to-date income yet (gap A17)")
        total = _ZERO
        separation = sum((_d(v, k) for k, v in taxable_by_concept.items() if k in SEPARATION_CONCEPTS), _ZERO)
        if separation > 0:
            monthly = monthly_ordinary_income(facts)
            if separation < monthly:
                total += monthly_isr(separation, facts)
            else:
                total += separation * (monthly_isr(monthly, facts) / monthly)
        for concept in ("AGUINALDO", "VACATION_PREMIUM"):
            taxable = _d(taxable_by_concept.get(concept, _ZERO), concept)
            if taxable > 0:
                total += SPECIAL_PAY_RULES[concept].standalone_isr(taxable, facts)
        return total


FINIQUITO_RULE = FiniquitoRule()
