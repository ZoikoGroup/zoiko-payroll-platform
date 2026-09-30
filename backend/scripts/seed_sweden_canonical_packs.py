"""
scripts/seed_sweden_canonical_packs.py
--------------------------------------
Seeds the canonical (organization_id IS NULL) Sweden content as DRAFT —
JurisdictionPack + ContributionRate + TaxSlab scaffolds + SourceArtifact
evidence + the AGI filing calendar + the AGI individual-statement report
template — the same DB-driven shape every other country's canonical pack
uses (see seed_singapore_canonical_pack.py, the blueprint).

Source: ZP-SE-ENG-001 v1.0 (22 Sep 2026), Jur_doc/Zoiko_Payroll_Sweden_
Engineering_Implementation_Wireframe_v1.0.docx, registered as ONE
SourceArtifact (SHA-256 of the file, verified at run time when the file is
present). The official Skatteverket / Försäkringskassan / verksamt.se
references the specification cites (S1–S17) are recorded on the pack's
source_references; they were NOT retrieved by this script, so no hash is
claimed for them and no SourceArtifact pretends they were.

Unit convention: percent-type ContributionRate values are PERCENT numbers
(31.42 = 31.42%) — France's convention, which engine/countries/sweden.py
reads. Amount-type parameters use flat_amount.

What is seeded (every value is in the specification):
  SE-PAYROLL-2026 v1.0 (2026-01-01 .. 2026-12-31)
    * 7 employer-contribution components summing to 31.42% (spec §3 "store
      component rates and total"). The component split is the Skatteverket
      2026 breakdown; the specification states only the total, the 10.21%
      pension component and the 20.81% youth rate — the split MUST be
      confirmed by the Swedish statutory reviewer before activation (a
      second published split with the same total exists).
    * cohort bounds: born <= 1937 -> 0%, born 1938–1958 -> 10.21% (spec §3)
    * temporary youth reduction 20.81% up to SEK 25,000/month, row window
      2026-04-01 .. 2027-09-30 (spec §3/§6, SE-005)
    * SINK 22.5%, supplementary income 30%, SLP 24.26%
    * vacation percentage 12%, sick-pay qualifying deduction 20% (spec §7/§8)
  SE-PAYROLL-2027 v1.0 (2027-01-01 .. 2027-12-31)
    * SINK 20% (enacted, spec §3), youth reduction to 2027-09-30, and the
      rates the specification states as standing law (supplementary 30%,
      SLP 24.26%, zero cohort 1937, vacation 12%, qualifying deduction 20%).

Deliberately NOT seeded (BLOCKED — AUTHORITATIVE VALUE REQUIRED):
  * 2027 employer-contribution components and the 2027 older-cohort
    birth-year bound — the specification states 2026 values only. The 2027
    pack therefore fails the readiness check until they are entered.
  * Tax tables 29–42 and one-time-payment table VALUES (approved decision:
    structure seeded in Draft, values entered via Super Admin). Each
    (table, column) and each one-time column gets ONE inert scaffold row
    with no assessment_basis, which the engine refuses to calculate from.
    The column set 1–6 must be confirmed against Skatteverket's published
    2026 tables.
  * The large-VAT-filer AGI declaration variation (spec §10: "can have a
    later declaration date") — no date is stated.
  * TaxabilityRule earning-code rows (SE-003/SE-004 require a legal source,
    regression fixtures and dual approval per earning code; TaxabilityRule
    has no Draft state, so a row would be live on insert).
  * Any collective agreement — Sweden has no national default (spec §9).

Governance: nothing is ever set Active here. Activation goes through the
Super Admin workflow (distinct approver, linked SourceArtifact, passing SE
certification, the SE readiness gate). Re-running refuses to touch a pack
that has left Draft, and a Draft pack's rows are reconciled so an
unchanged re-run changes nothing.

Usage:
    python -m scripts.seed_sweden_canonical_packs
"""
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries.sweden import (  # noqa: E402
    SE_ONE_TIME_PAYMENT_RULE, SE_PARAMETER_KEYS, SE_TAX_TABLE_RULE,
)
from app.modules.payroll.models import (  # noqa: E402
    ContributionRate, JurisdictionPack, ReportTemplate, SourceArtifact, StatutoryFilingCalendar, TaxSlab,
)
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "SE"
CURRENCY = "SEK"
SPEC = "ZP-SE-ENG-001 v1.0 (22 Sep 2026)"
AUTHORITY = "Skatteverket; Försäkringskassan"

SPEC_FILE = Path(__file__).resolve().parents[2] / "Jur_doc" / "Zoiko_Payroll_Sweden_Engineering_Implementation_Wireframe_v1.0.docx"
SPEC_SHA256 = "69244f3dd8838928293a2d438a01a7dc284d57a8bea27b07fde239788b9eb991"
SPEC_SIZE = 339610
SPEC_REGISTERED_AT = datetime(2026, 9, 30, 9, 0, 0, tzinfo=timezone.utc)

# The specification's own evidence register (§18) — cited, not retrieved.
EVIDENCE_REGISTER = (
    ("S1", "Skatteverket — Arbetsgivaravgifter (2026 rates, temporary youth reduction)", "https://www.skatteverket.se/arbetsgivaravgifter"),
    ("S2", "Skatteverket — Skattetabeller 2026", "https://www.skatteverket.se/foretag/arbetsgivare/arbetsgivaravgifterochskatteavdrag/skattetabeller.html"),
    ("S3", "Skatteverket — Skatteavdrag med 30 procent", "https://www.skatteverket.se/foretag/arbetsgivare/arbetsgivaravgifterochskatteavdrag/skatteavdrag/skatteavdragmed30procent.html"),
    ("S4", "Skatteverket — Engångsbelopp 2026", "https://www.skatteverket.se/foretag/arbetsgivare/arbetsgivaravgifterochskatteavdrag/skatteavdrag/engangsbelopp.html"),
    ("S5", "Skatteverket — SINK (22.5% 2026; 20% from 2027)", "https://www4.skatteverket.se/rattsligvagledning/edition/2026.6/325050.html"),
    ("S6", "Skatteverket — Särskild löneskatt på pensionskostnader (24.26%)", "https://www4.skatteverket.se/rattsligvagledning/edition/2026.6/2915.html"),
    ("S7", "Skatteverket — AGI Technical description 1.1.18.2", "https://www.skatteverket.se/foretag/arbetsgivare/lamnaarbetsgivardeklaration/tekniskbeskrivningochtesttjanst.html"),
    ("S8", "Försäkringskassan — parental leave / VAB absence data", "https://www.forsakringskassan.se/arbetsgivare/foraldraledighet/redovisa-franvarouppgifter-for-foraldraledighet-och-vab"),
    ("S10", "verksamt.se — Annual leave", "https://verksamt.se/en/employees-recruitment/leave/vacation-annual-leave"),
    ("S11", "verksamt.se — Percentage rule (12%)", "https://verksamt.se/en/employees-recruitment/leave/vacationy-pay-hourly-employees"),
    ("S13", "Försäkringskassan — Sick employee days 1-90", "https://www.forsakringskassan.se/english/for-employers/illness-and-injury/sick-employee-days-1-90"),
    ("S14", "Försäkringskassan — Sick pay and 20% qualifying deduction", "https://www.forsakringskassan.se/english/for-employers/illness-and-injury/sick-employee-days-1-90/sick-pay"),
    ("S15", "Skatteverket — employer declaration filing times", "https://www4.skatteverket.se/rattsligvagledning/edition/2026.11/325375.html"),
)

YOUTH_FROM = date(2026, 4, 1)
YOUTH_TO = date(2027, 9, 30)

# Employer-contribution components, 2026 (percent). Sum asserted = 31.42.
ER_COMPONENTS_2026 = (
    ("se_er_age_pension", "Ålderspensionsavgift (age pension)", "10.21"),
    ("se_er_survivor_pension", "Efterlevandepensionsavgift (survivor pension)", "0.60"),
    ("se_er_health_insurance", "Sjukförsäkringsavgift (health insurance)", "3.55"),
    ("se_er_parental_insurance", "Föräldraförsäkringsavgift (parental insurance)", "2.60"),
    ("se_er_work_injury", "Arbetsskadeavgift (work injury)", "0.20"),
    ("se_er_labour_market", "Arbetsmarknadsavgift (labour market)", "2.64"),
    ("se_er_general_payroll_tax", "Allmän löneavgift (general payroll tax)", "11.62"),
)
STANDARD_TOTAL = Decimal("31.42")

# (component_key, label, kwargs) shared by both packs — standing law per spec.
STANDING_ROWS = (
    ("se_youth_reduced", "Temporary youth reduction — reduced total rate",
     dict(employer_rate_pct="20.81", effective_from=YOUTH_FROM, effective_to=YOUTH_TO)),
    ("se_youth_monthly_threshold", "Youth reduction — monthly compensation cap (SEK)",
     dict(flat_amount="25000", effective_from=YOUTH_FROM, effective_to=YOUTH_TO)),
    ("se_supplementary_rate", "Preliminary tax — supplementary income (30%)", dict(employee_rate_pct="30")),
    ("se_slp", "Särskild löneskatt on pension costs (SLP)", dict(employer_rate_pct="24.26")),
    ("se_zero_cohort_max_birth_year", "No employer contributions: born in or before (year)", dict(flat_amount="1937")),
    ("se_vacation_percentage", "Vacation pay — percentage rule (% of qualifying pay)", dict(flat_amount="12")),
    ("se_sick_qualifying_deduction_pct", "Sick pay — qualifying deduction (% of avg weekly sick pay)",
     dict(flat_amount="20")),
)

TAX_TABLES = tuple(str(n) for n in range(29, 43))   # spec §3: tables 29–42
TAX_COLUMNS = ("1", "2", "3", "4", "5", "6")         # confirm against Skatteverket 2026


def _spec_2026():
    rows = [(k, label, dict(employer_rate_pct=v)) for k, label, v in ER_COMPONENTS_2026]
    rows += [
        ("se_older_cohort_max_birth_year", "Pension component only: born in or before (year)", dict(flat_amount="1958")),
        ("se_sink", "SINK — special income tax for non-residents", dict(employee_rate_pct="22.5")),
    ]
    rows += list(STANDING_ROWS)
    return {
        "pack_id": "SE-PAYROLL-2026", "version": "1.0", "tax_year": "2026",
        "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31), "rows": rows,
        "summary": (
            f"v1.0 — {SPEC}: employer contributions as 7 components (31.42% standard), 1937/1958 birth-year "
            "cohorts, temporary youth reduction 20.81% up to SEK 25,000/month for payments 1 Apr 2026 – 30 Sep "
            "2027, SINK 22.5%, supplementary 30%, SLP 24.26%, vacation 12%, qualifying deduction 20%. Tax tables "
            "29–42 and one-time tables are inert Draft SCAFFOLDS — values to be entered from Skatteverket. "
            "Component split pending Swedish statutory review."
        ),
    }


def _spec_2027():
    rows = [("se_sink", "SINK — special income tax for non-residents", dict(employee_rate_pct="20"))]
    rows += list(STANDING_ROWS)
    return {
        "pack_id": "SE-PAYROLL-2027", "version": "1.0", "tax_year": "2027",
        "effective_from": date(2027, 1, 1), "effective_to": date(2027, 12, 31), "rows": rows,
        "summary": (
            f"v1.0 — {SPEC}: SINK 20% from 1 Jan 2027 (enacted), youth reduction to 30 Sep 2027, standing "
            "supplementary/SLP/cohort-zero/vacation/sick parameters. BLOCKED until entered: 2027 employer-"
            "contribution components and the 2027 older-cohort birth-year bound (not stated in the spec)."
        ),
    }


def _dec(value):
    return Decimal(str(value)) if value is not None else None


def _pct_display(value):
    return f"{value.normalize():f}%" if value is not None else "—"


def _upsert_spec_artifact(db) -> int:
    if SPEC_FILE.exists():
        digest = hashlib.sha256(SPEC_FILE.read_bytes()).hexdigest()
        if digest != SPEC_SHA256:
            raise SystemExit(f"Specification file hash {digest} != registered {SPEC_SHA256} — the document changed; "
                             "register it as a NEW artifact instead of editing this one.")
    row = (db.query(SourceArtifact)
           .filter(SourceArtifact.checksum_sha256 == SPEC_SHA256, SourceArtifact.original_filename == SPEC_FILE.name)
           .first())
    if row is None:
        row = SourceArtifact(
            agency="Zoiko Group — Payroll Engineering",
            title="ZP-SE-ENG-001 Sweden Payroll Engineering Implementation and Acceptance Wireframe v1.0",
            form_number="ZP-SE-ENG-001", publication_date=date(2026, 9, 22), retrieved_at=SPEC_REGISTERED_AT,
            checksum_sha256=SPEC_SHA256, original_filename=SPEC_FILE.name, file_size_bytes=SPEC_SIZE,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_path=f"Jur_doc/{SPEC_FILE.name}",
        )
        db.add(row)
        db.flush()
    return row.id


def _upsert_pack(db, spec, source_id):
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == spec["pack_id"], JurisdictionPack.version == spec["version"])
            .first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{spec['pack_id']} v{spec['version']} is {pack.status!r}, not Draft — refusing to rewrite "
                         "a pack that has entered review/approval. Create a new version from Super Admin instead.")
    created = pack is None
    if created:
        pack = JurisdictionPack(pack_id=spec["pack_id"], jurisdiction_country=CODE, version=spec["version"])
        db.add(pack)
    pack.jurisdiction_state = None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = spec["effective_from"]
    pack.effective_to = spec["effective_to"]
    pack.tax_year = spec["tax_year"]
    pack.currency = CURRENCY
    pack.regulatory_authority = AUTHORITY
    pack.compliance_category = "Arbetsgivaravgifter / Preliminary tax / SINK / SLP / AGI"
    pack.compliance_owner = "Super Admin — Sweden build"
    pack.source_document_id = source_id
    pack.change_summary = spec["summary"]
    pack.source_references = f"{SPEC}; " + "; ".join(f"[{i}] {t} <{u}>" for i, t, u in EVIDENCE_REGISTER)
    db.flush()
    prior = {model: [i for (i,) in db.query(model.id).filter(model.jurisdiction_pack_id == pack.id,
                                                              model.organization_id.is_(None))]
             for model in (ContributionRate, TaxSlab)}
    return pack, created, prior


_ROW_BOOKKEEPING = {"id", "created_at", "updated_at"}


def _reconcile_pack_rows(db, pack, prior) -> dict:
    """Singapore's reconcile: keep every existing row that already holds the
    canonical values (no UPDATE, same id), insert only what differs, delete
    stale rows — an unchanged re-run is a no-op."""
    db.flush()
    db.expire_all()
    changes = {}
    for model in (ContributionRate, TaxSlab):
        columns = [c.name for c in model.__table__.columns if c.name not in _ROW_BOOKKEEPING]
        old_ids = set(prior[model])
        rows = (db.query(model).filter(model.jurisdiction_pack_id == pack.id, model.organization_id.is_(None))
                .order_by(model.id).all())
        existing = {}
        for row in rows:
            if row.id in old_ids:
                existing.setdefault(tuple(getattr(row, c) for c in columns), []).append(row)
        inserted = 0
        for row in rows:
            if row.id in old_ids:
                continue
            match = existing.get(tuple(getattr(row, c) for c in columns))
            if match:
                match.pop(0)
                db.delete(row)
            else:
                inserted += 1
        deleted = 0
        for leftovers in existing.values():
            for row in leftovers:
                db.delete(row)
                deleted += 1
        changes[model.__tablename__] = {"inserted": inserted, "deleted": deleted}
    db.flush()
    return changes


def _add_rate(db, pack, sort_order, key, label, source_id, employer_rate_pct=None, employee_rate_pct=None,
              flat_amount=None, effective_from=None, effective_to=None):
    if key not in SE_PARAMETER_KEYS:
        raise SystemExit(f"{key} is not in engine SE_PARAMETER_KEYS — catalog drift")
    if len(label) > 100:
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    er, ee, flat = _dec(employer_rate_pct), _dec(employee_rate_pct), _dec(flat_amount)
    shown = str(flat) if flat is not None else None
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        component_key=key, label=label,
        employee_share=_pct_display(ee) if ee is not None else (shown or "—"),
        employer_share=_pct_display(er) if er is not None else "—",
        total=_pct_display(er if er is not None else ee) if (er is not None or ee is not None) else (shown or "—"),
        employer_rate_pct=er, employee_rate_pct=ee, flat_amount=flat,
        effective_from=effective_from, effective_to=effective_to, sort_order=sort_order,
        source_document_id=source_id,
    ))


def _add_table_scaffolds(db, pack, source_id, year) -> int:
    """ONE inert scaffold per (table, column) and per one-time column: no
    assessment_basis, no amount — engine/countries/sweden.py blocks on it,
    so a Draft scaffold can never produce a withholding figure."""
    count = 0
    for t_index, table in enumerate(TAX_TABLES):
        for c_index, column in enumerate(TAX_COLUMNS):
            db.add(TaxSlab(
                jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
                rule_type=SE_TAX_TABLE_RULE, tax_table_number=table, tax_column=column,
                min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), flat_amount=None,
                assessment_basis=None,
                rate_label=f"SE-{year}-T{table}-C{column}-DRAFT",
                tax_formula="DRAFT — enter Skatteverket monthly bands (AMOUNT or PERCENT)",
                sort_order=1000 + t_index * 10 + c_index, source_document_id=source_id,
            ))
            count += 1
    for c_index, column in enumerate(TAX_COLUMNS):
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
            rule_type=SE_ONE_TIME_PAYMENT_RULE, tax_table_number=None, tax_column=column,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), flat_amount=None,
            assessment_basis=None,
            rate_label=f"SE-{year}-OTP-C{column}-DRAFT",
            tax_formula="DRAFT — enter Skatteverket one-time bands (annual income, PERCENT)",
            sort_order=2000 + c_index, source_document_id=source_id,
        ))
        count += 1
    return count


def agi_due_dates(year: int):
    """(payment month, declaration due date) for payment months of `year`,
    standard variation: 12th of the following month, 17th when that month
    is January or August (spec §10 [S15]), rolled to the next weekday that
    is not a Swedish public holiday — the ADJUSTED date is stored as
    content, never computed at payroll time (spec §27)."""
    holidays = _swedish_holidays(year) | _swedish_holidays(year + 1)
    out = []
    for month in range(1, 13):
        due_year, due_month = (year, month + 1) if month < 12 else (year + 1, 1)
        due = date(due_year, due_month, 17 if due_month in (1, 8) else 12)
        while due.weekday() >= 5 or due in holidays:
            due += timedelta(days=1)
        out.append((month, due))
    return out


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _swedish_holidays(year: int) -> set:
    easter = _easter(year)
    midsummer = next(date(year, 6, d) for d in range(20, 27) if date(year, 6, d).weekday() == 5)
    all_saints = next(date(year, m, d) for m, d in ((10, 31), (11, 1), (11, 2), (11, 3), (11, 4), (11, 5), (11, 6))
                      if date(year, m, d).weekday() == 5)
    return {
        date(year, 1, 1), date(year, 1, 6), easter - timedelta(days=2), easter + timedelta(days=1),
        date(year, 5, 1), easter + timedelta(days=39), date(year, 6, 6), midsummer - timedelta(days=1),
        midsummer, all_saints, date(year, 12, 24), date(year, 12, 25), date(year, 12, 26), date(year, 12, 31),
    }


def _upsert_agi_calendar(db, source_id, year=2026) -> int:
    count = 0
    for month, due in agi_due_dates(year):
        period_key = f"{year}-{month:02d}"
        row = (db.query(StatutoryFilingCalendar)
               .filter(StatutoryFilingCalendar.jurisdiction_country == CODE,
                       StatutoryFilingCalendar.report_type == "AGI",
                       StatutoryFilingCalendar.reporting_year == str(year),
                       StatutoryFilingCalendar.period_key == period_key,
                       StatutoryFilingCalendar.variation == "STANDARD")
               .first())
        if row is not None and row.status != "Draft":
            continue   # never rewrite a reviewed/approved calendar row
        if row is None:
            row = StatutoryFilingCalendar(jurisdiction_country=CODE, report_type="AGI", reporting_year=str(year),
                                          period_key=period_key, variation="STANDARD")
            db.add(row)
        row.period_label = f"AGI — payments made {date(year, month, 1):%B %Y}"
        row.due_date = due
        row.payment_due_date = due   # standard variation: declaration and payment share the due date
        row.status = "Draft"
        row.source_document_id = source_id
        count += 1
    db.flush()
    return count


AGI_TEMPLATE_KEY = "SE-AGI-INDIVIDUAL"


def _seed_agi_template(db, source_id):
    """The AGI individual-statement DATA extract (spec §10) — Draft, via the
    same validated service calls Super Admin's UI uses. XML generation /
    schema v1.1 / Technical Description 1.1.18.2 validation is the approved
    follow-up phase; this template never claims a filing channel (SE-008)."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import (
        ReportTemplateComponentUpsert, ReportTemplateFieldUpsert, ReportTemplateUpsert,
    )

    existing = (db.query(ReportTemplate)
                .filter(ReportTemplate.template_key == AGI_TEMPLATE_KEY, ReportTemplate.version == "1.0").first())
    if existing is not None and existing.status != "Draft":
        return existing
    template = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=AGI_TEMPLATE_KEY, name="Arbetsgivardeklaration — individual statement (AGI data extract)",
        reportType="AGI", jurisdictionCountry=CODE, reportingYear="2026", documentScope="PER_EMPLOYEE",
        changeSummary="Seeded via scripts/seed_sweden_canonical_packs.py",
        description="Per-payee AGI figures from the frozen Sweden calculation snapshot. Data extract only — XML "
                    "generation and Skatteverket schema validation are a separate, gated phase (SE-008).",
        regulatoryAuthority="Skatteverket", effectiveFrom=date(2026, 1, 1),
        sourceReferences=f"{SPEC} §10; Technical description 1.1.18.2 [S7]",
    ), actor_id=None)
    components = (
        ("payee", "Payee", (
            ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
        )),
        ("remuneration", "Remuneration", (
            ("gross_pay", "Cash remuneration (gross)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ("employer_contribution_base", "Employer-contribution base", "currency", "PAYSLIP_ITEM_JSON",
             "se_calculation_snapshot.employer_contribution.base", None),
        )),
        ("tax", "Deducted tax", (
            ("preliminary_tax", "Preliminary tax deducted", "currency", "PAYSLIP_ITEM_JSON",
             "se_calculation_snapshot.withholding.amount", None),
            ("tax_strategy", "Withholding strategy", "text", "PAYSLIP_ITEM_JSON",
             "se_calculation_snapshot.withholding.strategy", None),
        )),
        ("employer", "Employer contributions", (
            ("employer_contribution", "Employer contributions", "currency", "PAYSLIP_ITEM_JSON",
             "se_calculation_snapshot.employer_contribution.amount", None),
            ("employer_cohort", "Contribution cohort", "text", "PAYSLIP_ITEM_JSON",
             "se_calculation_snapshot.employer_contribution.cohort", None),
        )),
    )
    for sort_order, (component_key, label, fields) in enumerate(components):
        component = service.upsert_report_component(
            db, template.id, ReportTemplateComponentUpsert(componentKey=component_key, label=label, sortOrder=sort_order),
            actor_id=None)
        for field_sort, (field_key, field_label, field_type, kind, column, aggregation) in enumerate(fields):
            service.upsert_report_field(db, component.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_label, fieldType=field_type, dataSourceKind=kind,
                sourceColumn=column, aggregation=aggregation, sortOrder=field_sort), actor_id=None)
    template.source_document_id = source_id
    db.flush()
    return template


def _ensure_service_registry_row(db) -> str:
    """Sweden's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed (same rule as Singapore)."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_sweden_pack(db, spec, source_id) -> tuple:
    from app.modules.payroll.service import record_tax_audit

    if spec["tax_year"] == "2026":
        total = sum((Decimal(v) for _k, _l, v in ER_COMPONENTS_2026), Decimal("0"))
        if total != STANDARD_TOTAL:
            raise SystemExit(f"2026 employer components sum to {total}, not {STANDARD_TOTAL}")
    pack, created, prior = _upsert_pack(db, spec, source_id)
    for sort_order, (key, label, kwargs) in enumerate(spec["rows"], start=1):
        _add_rate(db, pack, sort_order, key, label, source_id, **kwargs)
    scaffolds = _add_table_scaffolds(db, pack, source_id, spec["tax_year"])
    changes = _reconcile_pack_rows(db, pack, prior)
    record_tax_audit(
        db, actor_id=None, action="create" if created else "update", entity_type="jurisdiction_pack",
        entity_id=pack.id, jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None,
        new_value={"status": pack.status, "contributionRates": str(len(spec["rows"])),
                   "taxTableScaffolds": str(scaffolds), "rowChanges": changes},
        reason=f"Canonical Sweden pack {spec['pack_id']} v{spec['version']} seeded from {SPEC} "
               "(scripts/seed_sweden_canonical_packs.py) — Draft.",
        auto_commit=False,
    )
    return pack, changes


def seed_sweden(db) -> dict:
    source_id = _upsert_spec_artifact(db)
    pack26, changes26 = seed_sweden_pack(db, _spec_2026(), source_id)
    pack27, changes27 = seed_sweden_pack(db, _spec_2027(), source_id)
    calendar = _upsert_agi_calendar(db, source_id)
    template = _seed_agi_template(db, source_id)
    availability = _ensure_service_registry_row(db)
    db.flush()
    return {"source_id": source_id, "packs": [pack26, pack27], "changes": [changes26, changes27],
            "calendar_rows": calendar, "agi_template_id": template.id, "availability": availability}


def main() -> None:
    assert_local_database("seed_sweden_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_sweden(db)
        db.commit()
        for pack, changes in zip(out["packs"], out["changes"]):
            print(f"Seeded {pack.pack_id} v{pack.version} (id={pack.id}) as Draft — {changes}")
        print(f"AGI calendar rows: {out['calendar_rows']}; AGI template id={out['agi_template_id']}; "
              f"service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
