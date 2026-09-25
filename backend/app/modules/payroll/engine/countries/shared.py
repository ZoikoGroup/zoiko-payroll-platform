"""
modules/payroll/engine/countries/shared.py
---------------------------------------------
Genuinely cross-cutting helpers used by every country's calculator —
nothing here is specific to one jurisdiction's rules. Moved verbatim out
of engine/standard.py as part of splitting that file's per-country logic
into its own module per country (engine/countries/{india,us,uk,...}.py).
"""

import ast
import logging
import operator
from decimal import Decimal
from typing import Callable

from app.modules.payroll.engine.base import _round2

MONTHS_PER_YEAR = Decimal("12")
_logger = logging.getLogger("zoiko")


class MissingComplianceConfigurationError(Exception):
    """A federal/national-scope statutory parameter has no configured row
    (canonical or org-scoped) for a country that has opted into required-
    configuration validation (see _VALIDATION_ENABLED_COUNTRIES below).

    Plain Exception, not a FastAPI HTTPException — this module is
    deliberately framework/ORM-free (see this file's own docstring) so it
    stays import-safe from anywhere. The service/router layer is
    responsible for catching this and turning it into a proper 4xx
    response (see app.core.exceptions' handler, registered in main.py)."""
    def __init__(self, key: str, country: str, organization_id: int = None):
        self.key = key
        self.country = country
        self.organization_id = organization_id
        super().__init__(
            f"No statutory configuration found for '{key}' ({country}) — "
            f"configure it under Super Admin > Compliance before running payroll for this jurisdiction."
        )


# Per-jurisdiction rollout switch for the fail-fast behavior above — a
# plain in-code set, not a DB-backed flag, deliberately: this module has
# no DB access by design, and this is a rollout switch a developer flips
# per phase, not something an admin should toggle at runtime.
#
# Fallback Removal Fix Plan, Phase 6 rollout log:
#   IN — attempted 2026-09-03, REVERTED same day. Canonical data was
#        confirmed complete (component_key rebate_87a_mrelief/
#        surcharge_mrelief backfilled that day, linked to Active pack
#        IN-PAYROLL-FY2026-27 id=2) — but enabling it broke 35 existing
#        tests immediately, because canonical completeness does NOT imply
#        an EXISTING org's own already-synced ContributionRate rows are
#        complete: sync_org_rates_from_canonical only runs on an org's
#        FIRST use of a jurisdiction, never re-runs when canonical data
#        gains a new key later. The one real India org in the live DB
#        synced its rows before this backfill existed, so it almost
#        certainly lacks rebate_87a_mrelief/surcharge_mrelief today —
#        enabling validation would have broken its very next payroll run.
#        A real fix needs a re-sync mechanism (or a one-time backfill of
#        EVERY existing org's own rows, not just canonical) before this
#        can be safely re-attempted — not done here; flagged for a
#        separate, explicit decision.
#   US — same unresolved risk applies (never actually attempted).
#   UK — also blocked by its tax pack still being Draft (see history above
#        this rewrite) — _find_active_tax_pack only matches status=="Active".
_VALIDATION_ENABLED_COUNTRIES: set[str] = {"IE"}

# Per-country rollout switch for real YTD-accumulator-based caps (Canada
# CPP/CPP2/EI's YMPE/YAMPE/MIE, per ZP-TAX-CA-2026-001 §10/§11 — "exact
# year-to-date accumulators," not the current-period-annualized estimate
# engine/countries/canada.py uses today). Same deliberate plain-set
# convention as _VALIDATION_ENABLED_COUNTRIES above: a developer-flipped
# rollout gate, not a runtime admin toggle. service.py's _load_ca_ytd only
# queries/returns YTD data when the country is in this set; canada.py's own
# `ctx.ytd_pensionable_earnings is not None` check is the second,
# independent dormancy gate at the calculation layer — both must be true
# for YTD-based caps to actually apply.
#
# CA — enabled 2026-09-18 (production-readiness fix plan). No backfill of
#      existing PayslipItems is possible (their figures were computed with
#      the isolated-period bug, not just missing metadata), so flipping
#      this mid-tax-year for an org with existing 2026 CA payslips would
#      create a partial-year gap (prior periods' pensionable/insurable
#      earnings excluded from the room calculation for the rest of the
#      year) — confirmed with Venu that 0 real orgs have any 2026 CA
#      payslip yet, so this is the "fresh onboarding" safe case, not the
#      mid-year one. If this is ever disabled and re-enabled later, this
#      same check (0 existing 2026 CA payslips, or it's already Jan 1 of
#      a new tax year) must be re-confirmed first.
# US — Social Security wage base / FUTA wage base / Additional Medicare
#      threshold shared the identical current-period-annualized bug (see
#      engine/countries/us.py) and were designed to reuse this exact
#      mechanism. Enabled 2026-09-13 (gap-closure Plan Phase 2a): unlike
#      CA, zero real US employees existed in the live DB at enable time
#      (verified immediately before), so there is no existing-payslip
#      partial-year gap to worry about — safe to enable immediately,
#      same reasoning as UK's own enable note below. service.py's
#      _load_us_ytd/_upsert_us_ytd_accumulator are the read/write sides;
#      us.py's own `ctx.ytd_ss_wages_before is not None` (etc.) checks
#      are the second, independent calculation-layer dormancy gate.
# UK — enabled 2026-09-09 gap-closure Phase 3. This switch is the ONLY
#      gate on _load_uk_director_ytd/_upsert_uk_director_ytd_accumulator
#      (service.py) — the plumbing was built and tested 2026-09-08 but
#      left dormant. Unlike CA's caveat above, there is no existing UK
#      payslip history to create a partial-year gap: zero UK employees
#      existed in the live DB as of the 2026-09-07/09 audits, and even
#      once enabled this only produces a nonzero effect for an employee
#      with is_director=True (a field nobody has set, default False) —
#      every non-director UK payslip is completely unaffected.
# AU added (ZP-TAX-AU-2026-27-001 Payday Super Phase 2, 2026-09-16) for
# Superannuation Guarantee Maximum Contribution Base tracking — same
# "0 real employees exist for this country in the live DB at enable time"
# safety reasoning already used for US's own addition above: enabling
# changes nothing until a real AU accumulator row exists, and this same
# session is what builds the write path that would create one.
# KY added 2026-09-21 for Cayman Islands mandatory-pension CI$87,000
# annual-cap tracking (KY-008) — Cayman is a brand-new country with zero
# existing payroll history to create a partial-year gap (same "0 real
# employees exist for this country in the live DB at enable time" safety
# reasoning as AU/US's own additions above), so enabling it from day one
# (rather than shipping it dormant first) is the correct default for a
# genuinely new jurisdiction rather than an existing one gaining new
# tracked behavior.
# GY added 2026-09-22 for the PAYE statutory credit ledger (GY-010).
# UNLIKE every addition above, Guyana already has real live payroll
# history (went live 2026-09-21) — but enabling this switch is still
# provably a no-op for every existing employee: with no
# PayrollYtdAccumulator row, _load_gy_paye_credit_ytd defaults
# ytd_gy_paye_credit_before to 0 (same "no row = 0" convention as KY's
# own loader), and guyana.py's calculate() only touches `tds` when
# credit_before > 0 — so every employee is byte-for-byte unaffected
# until a real credit balance is manually entered (which, per this
# feature's own disclosed scope, no UI/API path exists to do yet).
# PR added 2026-09-23 for Puerto Rico's five independent wage-base caps/
# thresholds (SS $184,500, Additional Medicare $200,000, FUTA-equivalent
# $7,000, DTRH unemployment $7,000, SINOT $9,000 — ZP-PR-ENG-001 §13/§14).
# Puerto Rico is a brand-new country with zero existing payroll history to
# create a partial-year gap (same "0 real employees exist for this country
# in the live DB at enable time" safety reasoning as every other brand-new
# country's own addition above), so enabling it from day one is the
# correct default. Entirely independent of "US" above — service.py's
# _load_pr_ytd/_upsert_pr_ytd_accumulator use their own PR-scoped
# PayrollYtdAccumulator component keys, never the US ones.
_YTD_ACCUMULATOR_ENABLED_COUNTRIES: set[str] = {"UK", "US", "AU", "CA", "KY", "GY", "PR"}

# Per-country rollout switch for the ORG-LEVEL aggregate-remuneration
# accumulator (ZP-TAX-CA-2026-001 §13/§15's Ontario/BC EHT, Manitoba HE
# Levy, NL HAPSET, Quebec HSF — all banded on an org's total annual
# payroll across every employee, not any single employee's own pay).
# Same deliberate plain-set convention as _YTD_ACCUMULATOR_ENABLED_
# COUNTRIES above. service.py's _load_ca_org_levy_ytd/
# _upsert_ca_org_levy_ytd only read/write when the country is in this
# set — currently empty, and unreachable from any live calculation path
# regardless, since no employer levy calculation exists yet to call them
# (this accumulator is built and tested standalone first — see
# OrganizationYtdAccumulator's own docstring).
# UK — enabled 2026-09-09 gap-closure Phase 3, alongside
#      _YTD_ACCUMULATOR_ENABLED_COUNTRIES above. Once on, every UK
#      payslip starts accumulating the org's pay-bill/employer-NI
#      totals (harmless bookkeeping — `calculate_apprenticeship_levy_
#      period_amount`/`calculate_employment_allowance_net_liability`
#      themselves still fail closed to 0/not-eligible until
#      appr_levy_rate/appr_levy_allowance/empl_allowance_cap are
#      actually configured for the org), so this is safe to enable
#      before any org has configured those rates.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1 completion). Found this
#      same day: service.py's _ca_org_levy_read_inputs/_load_ca_org_levy_
#      ytd gate ALL FIVE org-banded levies (Ontario EHT, BC EHT, Manitoba
#      HE Levy, NL HAPSET, Quebec HSF) on this switch, not just the
#      associated-group sharing feature that documented needing it — so
#      despite Phase 2's rate data and Phases 6/7's mechanisms all being
#      built, every one of these levies had silently stayed $0 for any
#      employee this whole time. 0 CA employees exist on the live DB as
#      of this date, so flipping this changes no already-generated
#      payslip; it takes effect once a real ON/BC/MB/NL/QC employee's
#      payslip is generated.
# AU added (ZP-TAX-AU-2026-27-001 §14-18, Phase 4, 2026-09-16) for
# state/territory employer payroll tax's org-level aggregate-wages
# tracking — same "0 real AU employees exist, safe to enable now" reasoning
# as every other addition above.
# JM added 2026-09-22 for HEART's employer-wide monthly aggregation
# (JM-008). UNLIKE every addition above, this is NOT provably inert:
# Jamaica already has real live payroll history (went live 2026-09-21),
# and enabling this switch is the DELIBERATE fix for a disclosed Phase 1
# gap — HEART was previously evaluated against each employee's own gross
# independently rather than the employer's combined monthly total, which
# both under- and over-charges relative to JM-008's actual rule (an
# employer whose combined payroll crosses JMD 14,444 only because of
# several employees together, none individually over it, previously paid
# nothing at all). Enabling this switch is a real, intended behavior
# change for every Jamaica employer's NEXT payroll run, not a no-op —
# see jamaica.py's own module docstring for the corrected calculation.
_ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES: set[str] = {"UK", "CA", "AU", "JM"}

# Per-country rollout switch for the CRA-correct CREDIT method of
# applying "amounts" (federal BPAF, provincial BPA, Quebec BPA — and any
# future TD1-declared claim amount) to income tax. ZP-TAX-CA-2026-001 §7:
# "T3 = (R × A) − K", where K bakes in `lowest_rate × the claim amount` —
# i.e. CRA treats these as NON-REFUNDABLE CREDITS converted at the
# lowest bracket rate and subtracted from tax payable, not as a
# deduction from taxable income applied before bracket-summing.
#
# engine/countries/canada.py's existing method (still the default while
# this set is empty) computes `bracket_sum(annual_gross − bpa)` instead —
# mathematically identical to the credit method ONLY when income stays
# within the lowest bracket; once income crosses into a higher bracket,
# the deduction method effectively shields the claim amount at whatever
# bracket the TOP of income falls in rather than the fixed lowest rate,
# understating tax for every such employee (found during the
# ZP-TAX-CA-2026-001 gap-closure Phase 6 review, not introduced by it —
# this switch exists so the correct method can be verified and rolled
# out deliberately rather than silently changing every existing
# Canadian payslip's federal/provincial/Quebec tax the moment it ships).
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead).
#      A read-only DB check the same day confirmed 0 CA employees and 0
#      CA payroll runs exist on the live DB, so flipping this changes no
#      already-generated payslip; it takes effect for the first real CA
#      employee/run going forward.
_CA_CREDIT_METHOD_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for Manitoba's and Yukon's own DYNAMIC
# income-tapered Basic Personal Amount formulas (§8's "Dynamic basic
# amounts" note), replacing the generic flat "provincial_bpa" row every
# other non-Quebec province reads. Same deliberate dormancy reasoning as
# _CA_CREDIT_METHOD_ENABLED_COUNTRIES above: an org that has ALREADY
# configured a flat provincial_bpa row for MB or YT (e.g. from earlier
# statutory data entry) would see its provincial tax silently change the
# moment this ships, if it weren't gated — this switch exists so that
# never happens without a deliberate decision.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead;
#      0 CA employees/runs exist on the live DB as of that date).
_CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for CPP/QPP's mandatory age-18/age-70
# contribution window (§10's "Age 18"/"Age 70" controls). No
# PayrollEmployee has ever had a date_of_birth column before this, so
# ctx.date_of_birth is None for every existing employee regardless of
# this switch — but once that column is populated, this switch also
# gates whether it's actually CONSUMED, so an org can backfill dates of
# birth without any CPP/QPP behavior changing until it deliberately
# flips this. See canada.py's _is_age_gated_cpp_stopped for the
# disclosed calendar-age-comparison simplification (the source document
# names the controls but doesn't spell out CRA's exact month-boundary
# administrative rule).
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead).
#      Still a no-op today: 0 CA employees exist, and no date_of_birth
#      backfill has been run for any country, so ctx.date_of_birth stays
#      None regardless. Takes effect only once a CA employee's DOB is set.
_CA_AGE_GATED_CPP_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for CPP/QPP first-layer BASE (4.95%) vs.
# FIRST-ADDITIONAL (1.00%) traceability (AC-11: "CPP first-layer base
# and first additional components are separately traceable while
# respecting the combined statutory deduction"). Deliberately PURELY
# INFORMATIONAL: the combined "cpp"/"qpp" ContributionRate row remains
# the sole source of truth for the actual social_security/
# employer_social_security deduction, unconditionally, regardless of
# this switch — canada.py only uses "cpp_base"/"cpp_first_additional"
# (or "qpp_base"/"qpp_first_additional" for Quebec) rows to PROPORTION
# that already-computed amount into two breakdown fields, never to
# recompute it independently. This means flipping this switch can never
# make CPP itself disappear or change, even if those two new rows are
# never configured or are configured inconsistently with the combined
# row — the breakdown just stays $0/$0 until they exist.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead).
#      Purely informational per this switch's own docstring above — cannot
#      change any actual withheld amount regardless of employee count.
_CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for the federal K2/K3 credits — CRA's
# per-pay-period credit for CPP/QPP and EI/QPIP premiums ACTUALLY
# WITHHELD that period, converted at the lowest bracket rate (§7:
# "T3 = (R×A) − K − K1 − K2 − K3 − K4"). Only meaningful within
# _CA_CREDIT_METHOD_ENABLED_COUNTRIES's R×A formula (never applied under
# the legacy deduction-based path) — but kept as its OWN separate switch
# because it is a genuinely NEW credit that has never existed in this
# engine at all, unlike the BPA-as-credit fix that switch gates (a
# correction of an existing calculation). Every employee who has any
# CPP/QPP or EI/QPIP withheld will see LOWER federal tax once this is
# enabled — a materially different kind of change an org should be able
# to decide on independently of the BPA correctness fix. This is also
# what correctly handles a mid-year province transfer (§10's "Province
# transfer" control) without any special-case code: the credit is based
# on whatever was actually withheld this period, regardless of plan.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead,
#      alongside _CA_CREDIT_METHOD_ENABLED_COUNTRIES above, whose R×A
#      formula this only has any effect within). 0 CA employees/runs exist
#      on the live DB as of that date.
_CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for the EI/QPIP employer 1.4x-default
# premium mechanism (§11: "Default employer EI is 1.4 × employee
# premium... a valid reduced employer rate is an employer-specific
# authorization and must be stored as an effective-dated tenant overlay
# with source evidence; do not replace the statutory default globally").
# While OFF, the employer rate is read from whatever employer_rate_pct
# is independently configured on the SAME "ei"/"qpip" ContributionRate
# row as the employee rate (today's behavior) — an org that has already
# entered its own employer_rate_pct there must not see it silently
# replaced the moment this ships. Once ON, the employer rate instead
# DEFAULTS to exactly 1.4x the (dynamically resolved) employee rate,
# unless a reduced-rate EmployerTaxProfile authorization exists
# (component_code "EI_REDUCED", looked up at the country level since EI
# is federal, not provincial — see service.py's _resolve_employee_calc_
# inputs/add_payslip_item).
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead;
#      0 CA employees/runs exist on the live DB as of that date).
_CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for the labour-sponsored funds tax credit
# (LCF, §6: "Labour-sponsored fund credit rate / max: 15% / $750 — use
# LCF formula rules and cap; not a generic deduction"). A genuinely NEW
# federal credit — this engine never computed it at all before. While
# OFF, ctx.lsvcc_investment_amount is ignored entirely even if an org
# has entered employee LSVCC declarations, so backfilling that data
# ahead of time changes nothing until this is deliberately flipped.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead).
#      Still a no-op today: 0 CA employees exist and no
#      lsvcc_investment_amount data entry path exists yet.
_CA_LSVCC_CREDIT_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for the beyond-province/outside-Canada
# federal surtax (§6: "Beyond-province/outside-Canada surtax factor: 48%
# of T3 — special federal formula only; never display as a standard
# marginal bracket"). Applies when an employee's work_state is literally
# "XP" (ZP-TAX-CA-2026-001 §3's CA-XP jurisdiction code — "in Canada
# beyond limits of a province/territory"); this is a manually-assignable
# work_state value today (nothing currently auto-detects it — the
# establishment-record-based POE inference for CA-XP is Phase 9's
# unimplemented scope, tracked separately, see service.py's
# _resolve_ca_poe_with_source comment), so gating this behind its own
# switch matters even though no employee could have "XP" configured
# through any AUTOMATED path yet — an org could always have typed it in
# directly.
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead).
#      A read-only DB check the same day confirmed 0 CA employees exist
#      at all (let alone one with work_state == "XP"), so this is a no-op
#      today; takes effect only for a future employee explicitly assigned
#      to CA-XP.
_CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for BC's "basic tax reduction" (§9's
# mid-year override table: annual $690 / H1 $575 / H2 $805). Genuinely
# NEW — this engine never computed it at all before, and it comes with
# a DISCLOSED, deliberate simplification: the real reduction phases out
# with income, but the source document gives only the dollar amount,
# never the phase-out formula, so this applies the full amount to every
# BC taxpayer regardless of income (see canada.py's
# _calculate_provincial_tax_ca for the exact comment and the separate,
# pre-existing H1/H2-resolution gap this also surfaced).
#
# CA — enabled 2026-09-11 (gap-closure Phase 1, Venu's explicit go-ahead;
#      0 CA employees/runs exist on the live DB as of that date).
_CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for Canada's Taxability Matrix (ZP-TAX-CA-
# 2026-001 §17/AC-17, gap-closure Phase 5, 2026-09-11) — per-program
# (federal tax/provincial tax/CPP/EI) earning-component classification via
# TaxabilityRule, replacing today's single ctx.gross figure feeding all
# four. While OFF, every program keeps using ctx.gross exactly as today,
# regardless of any TaxabilityRule rows an admin has entered — same
# "mechanism can exist and be configured without changing live output
# until deliberately enabled" contract every other switch in this file
# uses. Even once ON, a fully unconfigured org sees IDENTICAL numbers
# (canada.py's _resolve_ca_taxability defaults every component to
# included) — this only changes a payslip once an admin has entered an
# actual override row AND enabled this switch.
#
# CA — enabled 2026-09-11 (gap-closure completion, Venu's explicit go-
#      ahead). Even now, a fully unconfigured org sees IDENTICAL numbers
#      (canada.py's _resolve_ca_taxability defaults every component to
#      included) — this only changes a payslip once an admin has entered
#      an actual TaxabilityRule override row, which none has today.
_CA_TAXABILITY_MATRIX_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for the US Taxability Matrix (ZP-TAX-US-2026-
# 001 §9.1, gap-closure Phase 7) — per-program (federal income tax/Social
# Security/Medicare/FUTA/state income tax) earning-component
# classification via TaxabilityRule, same mechanism/contract as CA's
# switch immediately above: OFF changes nothing; ON with zero configured
# TaxabilityRule rows (every org today) ALSO changes nothing (us.py's
# _resolve_us_taxability defaults every component to included, matching
# today's single-ctx.gross behavior for every wage base) — this only
# affects a real payslip once an admin enters an actual override row,
# which none has today.
#
# US — enabled 2026-09-12 (gap-closure Phase 7, Venu's explicit go-ahead;
#      same "enable now, zero live effect until configured" reasoning CA
#      used for its own switch above).
_US_TAXABILITY_MATRIX_ENABLED_COUNTRIES: set[str] = {"US"}

# Per-country rollout switch for Australia's PAYG-withholding/SG-qualifying-
# earnings taxability matrix (ZP-TAX-AU-2026-27-001 §11, Payday Super
# Phase 2, 2026-09-16) — identical "OFF changes nothing; ON with zero
# configured TaxabilityRule rows ALSO changes nothing (australia.py's
# _resolve_au_taxability defaults every component to included, matching
# today's single-ctx.gross behavior)" safety reasoning as CA/US above.
# AU — enabled as part of this same build (no real AU employees exist in
#      the live DB, and no AU TaxabilityRule row exists yet either) —
#      same "enable now, zero live effect until configured" pattern.
_AU_TAXABILITY_MATRIX_ENABLED_COUNTRIES: set[str] = {"AU"}

# Per-country rollout switch for Canada's associated-employer-group
# exemption sharing (ZP-TAX-CA-2026-001 §15, gap-closure Phase 6,
# 2026-09-11) — Ontario EHT / BC EHT / Manitoba HE Levy / NL HAPSET's
# "associated employers share exemption." Reuses Organization.
# connected_group_code (the same field UK's Apprenticeship Levy/
# Employment Allowance sharing already uses — genuinely country-agnostic
# despite its name) and the existing _ORG_LEVY_ACCUMULATOR_ENABLED_
# COUNTRIES accumulator, layered with two additive changes gated
# TOGETHER behind this one switch: (1) the org-level YTD "before" figure
# sums across every org sharing this org's connected_group_code instead
# of reading this org alone, and (2) each levy's exemption threshold is
# scaled by this org's own elected allocation share (EmployerTaxProfile,
# component_code "<LEVY>_EXEMPTION_ALLOCATION_PCT" — see service.py's
# _ca_levy_exemption_allocation_pct) instead of assuming it gets the
# full exemption. While OFF, or for any org with no connected_group_code
# set (every org today — no admin UI sets it yet), both changes are
# complete no-ops: a "group of one" sums to exactly this org's own
# total, and an unconfigured allocation defaults to 100%.
#
# CA — enabled 2026-09-11 (gap-closure completion, Venu's explicit go-
# ahead), alongside _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES above now
# also including "CA" (required for either change here to have any
# effect at all). No org has Organization.connected_group_code set today
# ("every org today" per this comment's own original text), so an org
# sums across a "group of one" -- unchanged from reading its own total
# alone -- until an admin actually groups two orgs together.
#
# AU — widened 2026-09-17 (§AU-D07: "State payroll-tax rate/threshold
# entitlement may depend on Australian wages and group status, not only
# wages in the state") to close the cross-employer group/interstate
# wage aggregation gap engine/countries/australia.py's own module
# docstring previously disclosed as NOT wired. Reuses this SAME switch
# (rather than a new near-duplicate one) since the underlying mechanism
# — service.py's _connected_group_member_ids/_sum_org_ytd_component_
# across_orgs — is exactly the country-agnostic thing this constant's
# own docstring above already describes; only
# _au_org_payroll_tax_read_inputs's own dispatch (service.py) decides
# which AU components apply it (all 8 states, since §AU-D07 applies to
# entitlement generally, unlike CA where only 4 of 5 levies qualify).
# Same "group of one, unchanged" dormancy for every org today.
_CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES: set[str] = {"CA", "AU"}

# Per-country rollout switch for Quebec's temporary HSF sector exemption
# (ZP-TAX-CA-2026-001 §15, gap-closure Phase 7, 2026-09-11) — "Eligibility
# for qualifying agriculture/forestry/fishing businesses is a separately
# effective-dated employer eligibility rule, never a default rate
# change." Implemented as an effective-dated EmployerTaxProfile row
# (component_code "QC_HSF_TEMP_SECTOR_EXEMPTION") that, while active,
# reclassifies the employer as "PRIMARY_MANUFACTURING" for HSF rate
# purposes for that window — reusing the ALREADY-configured, ALREADY-
# sourced primary/manufacturing HSF rate rather than inventing a new
# "exemption rate" the document never actually gives a number for. No
# row configured (every org today) means no reclassification — unchanged.
#
# CA — enabled 2026-09-11 (gap-closure completion, Venu's explicit go-
#      ahead). No row configured for any org today, so this stays a
#      no-op until an admin actually enters the effective-dated
#      EmployerTaxProfile eligibility row.
_CA_QC_HSF_TEMP_SECTOR_EXEMPTION_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for CRA's Option 2 (cumulative averaging)
# income tax withholding method (ZP-TAX-CA-2026-001 §7/AC — gap-closure
# Phase 9, 2026-09-11) — a genuinely DIFFERENT federal/provincial income
# tax calculation methodology from this engine's only-ever-implemented
# Option 1 (flat period x periods-per-year annualization), not a
# correction of it. Gates service.py's _load_ca_option2_ytd, which is
# what actually populates canada.py's ctx.option2_* fields — while OFF
# (default), that reader always returns {}, every ctx.option2_* field
# stays None, and canada.py's calculate() takes its EXACT existing
# Option 1 branch, byte-for-byte unchanged, for every employee/org. This
# is an employer-level METHOD CHOICE (CRA requires consistent use, not a
# per-payslip toggle) — enabling it is a real, deliberate decision by
# Venu, not a small correctness fix, so it gets the same "confirm before
# deploying past dev/test" caution as every other switch in this file,
# more so given it changes HOW tax is computed, not just a rate/threshold
# within the existing method.
#
# CA — enabled 2026-09-11 (gap-closure completion, Venu's explicit go-
#      ahead as a full employer-level method choice, not a correctness
#      fix — 0 CA employees exist on the live DB, so this takes effect
#      as the default method for the first real CA employee onward, not
#      retroactively against anything already generated).
_CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES: set[str] = {"CA"}

# Per-country rollout switch for India's statutory EPF wage ceiling
# (ZP-TAX-IN-2026-27-001 §9.1: "Current mandatory wage ceiling INR
# 15,000"). While OFF, EPF is computed on the employee's full, uncapped
# Basic — today's exact existing behavior for every org, unchanged. Once
# ON, the contribution base becomes min(basic, ceiling) instead — a real
# correctness fix (EPF is currently over-withheld for any employee with
# Basic above ₹15,000), but still a genuine payroll-affecting change to
# every such employee's next payslip, so it ships dormant like every
# other fix in this file rather than silently changing live withholding.
#
# IN — enabled 2026-09-10 (gap-analysis follow-up against
#      ZP-TAX-IN-2026-27-001). resolve_jurisdiction_parameter's own
#      fallback means an org with no "pf_wage_ceiling" row configured
#      still gets the correct statutory ₹15,000 default rather than an
#      error — so this is safe to enable even before any org has entered
#      the ceiling explicitly. This DOES change real withheld PF for any
#      live employee whose Basic already exceeds ₹15,000 (uncapped ->
#      capped) — verify there is no such live employee, or that the
#      change is wanted, before deploying past a dev/test environment.
_IN_PF_WAGE_CEILING_ENABLED_COUNTRIES: set[str] = {"IN"}

# Per-country rollout switch for India's Labour Code "code_wages" object
# (ZP-TAX-IN-2026-27-001 §8: the 50%-allowance-cap add-back that becomes
# the wage base fed into EPF/EPS/EDLI, replacing plain Basic). While OFF,
# those schemes keep computing on ctx.basic directly — today's exact
# existing behavior, unchanged. Once ON, PF/EPS/EDLI's wage base becomes
# _calculate_code_wages(ctx)'s statutory_wages instead, which is always
# >= basic — a real payroll-affecting increase for any employee whose
# non-basic components exceed 50% of gross, so this ships dormant.
#
# Phase B (2026-09-10, gap-closure follow-up): the DISCLOSED SIMPLIFICATION
# that used to live here (basic-as-proxy for core_included_wages,
# gross-minus-basic as a blind stand-in for excluded_total, because ctx
# only carried scalar gross/basic) is resolved — india.py's
# _calculate_code_wages now classifies each of the employee's own named
# components (basic/hra/special_allowance/overtime/
# additional_compensation/named_allowances) independently via
# ctx.code_wages_rules (service.py's get_code_wages_classification,
# backed by TaxabilityRule with tax_component="code_wages" — the
# previously-orphaned model, now wired in). The DEFAULT classification
# when no TaxabilityRule row is configured (basic=included, every other
# component excluded) reproduces the exact pre-Phase-B arithmetic, so
# enabling this is a pure no-op for any org that hasn't entered an
# override yet — genuinely safe to enable now on that basis alone.
#
# IN — enabled 2026-09-10, same gap-analysis follow-up as the PF-ceiling/
#      age-bands switches above. Still a REAL payroll-number change for
#      any live employee whose non-basic components (HRA/allowances/
#      overtime/additional pay) exceed 50% of gross — same "confirm
#      before deploying past dev/test" caution as those two switches;
#      not yet independently verified against live data.
_IN_CODE_WAGES_ENABLED_COUNTRIES: set[str] = {"IN"}

# India Old Regime senior/super-senior age-based basic-exemption bands
# (ZP-TAX-IN-2026-27-001 §4.1) — a real, correctness-affecting change for
# any Old-regime employee who's actually a senior/super-senior resident
# (they'd currently be taxed on the non-senior bands, which start taxing
# ₹50,000/₹250,000 sooner than they should). Ships dormant like every
# other correctness fix in this file: computing an employee's age
# category at all (india.py's _resolve_old_regime_age_category) is a
# no-op while this set is empty, regardless of whether
# date_of_birth/tax_residency_status are populated.
#
# IN — enabled 2026-09-10 (gap-analysis follow-up against
#      ZP-TAX-IN-2026-27-001). Safe even for an org with no
#      SENIOR/SUPER_SENIOR-tagged Old-regime TaxSlab rows configured:
#      _calculate_annual_tax's own filing_status-tagged-fallback logic
#      (shared.py, "filing_status_tagged") falls back to the untagged
#      ordinary bands whenever no row matches the resolved age category,
#      so an employee just starts computing their own age category as a
#      no-op until real senior/super-senior slabs exist for their
#      jurisdiction pack. Per gap_closure_plan_and_india_phase1 memory,
#      real senior/super-senior slab data was already entered against
#      the live IN pack (id 77) on 2026-09-09 — meaning this DOES change
#      real withheld tax for any live Old-regime resident employee aged
#      60+ the next time this deploys; confirm that's wanted (or that no
#      such live employee exists yet) before deploying past dev/test.
_IN_OLD_REGIME_AGE_BANDS_ENABLED_COUNTRIES: set[str] = {"IN"}

# Per-country rollout switch for removing the UK engine's independent
# Personal Allowance taper (ZP-TAX-UK-2026-27-001 §5.1 PAYE implementation
# rule: "Zoiko Payroll must not independently recompute an employee's
# tapered Personal Allowance from payroll earnings. HMRC supplies the tax
# code that operationalizes allowances..."). While OFF, uk.py keeps
# re-tapering the allowance above the £100k threshold from payroll-
# observed income — the OLD, superseded behavior, kept reachable only by
# explicitly discarding "UK" from this set (e.g. a test proving the old
# path still works if manually reverted). Once ON, the allowance is used
# exactly as parsed from the tax code, with no independent recompute at
# all.
#
# UK — enabled 2026-09-07 (Phase 1 of the phased rollout; zero live UK
# employees existed in the database at enable time, so this had no
# immediate real-payslip effect — see uk_2026_27_gap_closure memory).
_UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES: set[str] = {"UK"}

# Per-country rollout switch for capping a K-code employee's PAYE
# deduction at 50% of THIS PERIOD'S pre-tax pay (ZP-TAX-UK-2026-27-001
# §6.2: "tax deduction cannot exceed 50% of pre-tax pay/pension for the
# pay period"). Applied to the PERIOD figure (ctx.gross), not the annual
# one — the whole point of this cap is protecting a single low/irregular
# pay period from a K-code's added notional income, which an annual-level
# cap would only catch under perfectly uniform pay all year. While OFF
# (reachable only by explicitly discarding "UK"), a K-code's tax is
# uncapped — the old, superseded behavior.
#
# UK — enabled 2026-09-07 (Phase 2 of the phased rollout; zero live UK
# employees existed in the database at enable time).
_UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES: set[str] = {"UK"}

# Per-country rollout switch for National Insurance category-banded rates
# (ZP-TAX-UK-2026-27-001 §8.3/§9.1 — all 16 category letters, each with
# its own employee/employer rate bands). uk.py's _resolve_ni_bands/
# _calculate_ni_from_bands mechanism already exists (same shape as
# India's Telangana PT_FLAT bands) — this switch gates it specifically
# because ni_category is ALREADY a live, employee-configurable field.
# While OFF (reachable only by explicitly discarding "UK"), every
# category computes via the flat Category-A-shaped fallback regardless
# of what's actually declared — the old, superseded behavior.
#
# UK — enabled 2026-09-07 (Phase 3 of the phased rollout). The canonical
# ni_secondary_thresh row was reconciled to the real £5,000 (was wrongly
# £9,100) and a set of incomplete, orphaned pre-existing NI_BAND rows for
# categories A/B was found and deleted BEFORE enabling this — see
# uk_2026_27_gap_closure memory. Zero live UK employees existed in the
# database at enable time.
_UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES: set[str] = {"UK"}

# Per-country rollout switch for computing the flat-fallback NI path
# directly against THIS PERIOD'S gross and a real Weekly/Monthly
# threshold, instead of annualizing gross then dividing the result back
# down (ZP-TAX-UK-2026-27-001 §8.1: "For ordinary employees, Class 1 NIC
# is based on the earnings period rather than cumulative annual
# earnings... must not cause ordinary payroll to annualize NIC"). The
# annualize-then-divide model is only numerically equivalent to true
# period-based NI under perfectly uniform pay across the year — wrong for
# irregular/bonus periods. Scoped to Weekly and Monthly only (the two
# frequencies the document publishes real, independently-rounded
# threshold figures for — its weekly threshold doesn't even multiply out
# to its own annual figure, confirming these aren't safely derivable from
# each other); Fortnightly/FourWeekly/anything else keeps today's
# annualize-then-divide fallback. While OFF, every frequency uses today's
# exact existing behavior.
#
# UK — enabled 2026-09-07 (Phase 4 of the phased rollout; zero live UK
# employees existed in the database at enable time). While OFF
# (reachable only by explicitly discarding "UK"), every frequency uses
# the old, annualize-then-divide behavior.
_UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES: set[str] = {"UK"}

# Per-country rollout switch for rounding Student Loan/Postgraduate Loan
# deductions DOWN to the nearest whole pound (ZP-TAX-UK-2026-27-001
# §10.2: "Round the deduction down to the nearest whole pound as required
# by HMRC loan tables/manual method"). While OFF (reachable only by
# explicitly discarding "UK"), uk.py rounds to the nearest penny
# (_round2) — the old, superseded behavior.
#
# UK — enabled 2026-09-07 (Phase 5 of the phased rollout; zero live UK
# employees existed in the database at enable time).
_UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES: set[str] = {"UK"}

# Per-country rollout switch for deriving ni_category from real relief-
# eligibility facts (PayrollNiReliefFact) instead of trusting whatever
# letter an admin manually set on the employee record (ZP-TAX-UK-2026-27-
# 001 §9.1/§9.3 gap-closure Part 2, 2026-09-09 — "Relief eligibility is
# not a rate toggle"). While OFF (the default — genuinely new, unlike
# most other UK switches in this file, which started dormant only briefly
# before being enabled the same week they shipped), uk.py's
# derive_ni_category() is never called at all; the employee's own
# ni_category is used exactly as today, even for an employee who already
# has a relief fact recorded. Left off pending a deliberate enable
# decision, since this is a genuinely new-build feature (Part 2 of a
# fresh 11-part roadmap), not a correction to something already shipped.
_UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES: set[str] = {"UK"}
# UK — enabled 2026-09-10 (deliberate enable decision, gap-analysis
# follow-up). Zero live UK organizations existed in the database at
# enable time. Still a practical no-op for every employee today: there
# is no UI anywhere to record a PayrollNiReliefFact, so derive_ni_category()
# has no facts to act on and returns None (use the manual ni_category)
# for everyone until that UI is built.

# Per-country rollout switch for computing a real Automatic Enrolment
# assessment (ELIGIBLE_JOBHOLDER/NON_ELIGIBLE_JOBHOLDER/ENTITLED_WORKER
# from age + qualifying earnings) instead of leaving it as the plain
# manual yes/no field it's always been (ZP-TAX-UK-2026-27-001 §13 gap-
# closure Part 3, 2026-09-09). While OFF (the default — genuinely new,
# same as Part 2's switch above), uk.py's assess_auto_enrolment() is
# never called; PayslipItem.auto_enrolment_status stays NULL for every
# payslip exactly as today. Purely informational/output-only even once
# enabled — never changes employee_pension/employer_pension's own
# calculation (see uk.py's own comment on assess_auto_enrolment).
_UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES: set[str] = {"UK"}
# UK — enabled 2026-09-10, immediately after adding a generic Date of
# Birth field to the employee form (EmployeeForm.jsx) — this switch was
# gated on ctx.date_of_birth, which had no UI anywhere to set it until
# now. Zero live UK organizations existed in the database at enable time.
# Still purely informational/output-only even now enabled — never
# changes employee_pension/employer_pension.

# Per-country rollout switch for automatically computing and freezing a
# Statutory Family Pay total (SMP/SPP/SAP/SHPP/SPBP/SNCP) the moment a
# matching statutory leave request (leave_type in maternity/paternity/
# adoption/sharedParental/bereavement/neonatal) is approved
# (ZP-TAX-UK-2026-27-001 §11 gap-closure Part 7A, 2026-09-09). While OFF
# (the default), approving one of these leave types behaves exactly as
# any other leave type always has — no statutory_pay_* column is ever
# populated. Purely additive on approval; never touches any existing
# leave-balance/attendance-sync logic.
_UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES: set[str] = {"UK"}
# UK — enabled 2026-09-10 (deliberate enable decision, gap-analysis
# follow-up). Zero live UK organizations existed in the database at
# enable time, so no in-flight leave request could be affected by this
# flip. From this point on, approving a maternity/paternity/adoption/
# sharedParental/bereavement/neonatal leave request for a real UK
# employee will automatically compute and add a statutory-pay amount
# into that pay period's gross — see tests/test_uk_statutory_leave_
# wiring.py for the already-proven enabled-path behavior.

# Per-STATE (not per-country, unlike every switch above — the US isn't one
# jurisdiction) rollout switch for a state's real income-tax withholding
# (ZP-TAX-US-2026-001 §4). While a state is absent from this set, us.py
# ignores any TaxSlab rows configured for it and state_income_tax computes
# as 0 for that state — the same silent-zero behavior every US state has
# had until explicitly added here, so this is additive per-state, never a
# retroactive change to a state not yet in the set. Add a state only once
# its real TaxSlab/allowance data has been seeded AND (per this codebase's
# standing convention) either zero employees exist with that work_state
# yet, or an explicit go-ahead has been given to change a real number for
# employees who do.
#
# CO/KY — enabled 2026-09-07 (build-out per ZP-TAX-US-2026-001): zero live
# US employees existed in the database at enable time, so this was purely
# additive with no real-payslip effect.
#
# AZ/IL/MA/MI/PA — enabled 2026-09-11 (incremental flat-rate build-out per
# ZP-TAX-US-2026-001 §4 Matrix): zero live US organizations were in the
# database at enable time, and the document gives each a complete literal
# flat withholding percentage (AZ 2.0% no-A-4 default, IL 4.95%, MA 5.0%,
# MI 4.25%, PA 3.07%) with no state standard deduction, so seeding a single
# FLAT_RATE TaxSlab and enabling each here is fully determined by the
# document with no invented numbers.
#
# CA/DC/DE/GA/HI/IA — enabled 2026-09-12 (gap-closure Level 2, genuine
# primary-source batch — real government citations, not the earlier
# untrustworthy tracking sheet). Zero live US employees existed with any
# of these six as work_state at enable time (verified immediately before
# enabling). GA's rate here (4.99%) CORRECTS this same session's own
# earlier provisional 5.19% entry — see
# hardcoded_defaults._US_STATE_TAX_RATES_PROVISIONAL's comment on exactly
# how that was caught before it ever reached a real payslip. See
# hardcoded_defaults._US_STATE_GRADUATED_TAX_RATES's own module comment
# for the documented simplifications shared by CA/DC/DE/HI (no per-
# employee allowance/dependent-count field exists anywhere in this engine
# yet, so every count-dependent credit/allowance in the source batch is
# omitted — always in the over-withholding, never under-withholding,
# direction).
#
# AL — enabled 2026-09-12, same session, same batch. Complete literal
# bracket table; only Alabama's own separate graduated standard
# deduction/dependent exemption/federal-tax-liability deduction are
# unmodeled (again strictly over-withholding-direction gaps — see
# _US_STATE_GRADUATED_TAX_RATES["AL"]'s own comment). Zero live US
# employees existed with work_state="AL" at enable time.
#
# AR/MN — enabled 2026-09-12, same session, a follow-up batch resolving
# each state's previously-named gap (AR's exact bracket thresholds; MN's
# withholding-formula clarification — no phase-out exists at the
# withholding level at all). See _US_STATE_GRADUATED_TAX_RATES["AR"]/
# ["MN"]'s own comments for the documented simplifications each still
# carries. Zero live US employees existed with either as work_state at
# enable time.
#
# CT — enabled 2026-09-12, same session, a fully-resolved batch (all 5
# tables A-E given literally, not the earlier prose-pattern summaries).
# Genuinely different architecture from every other state here — see
# engine/countries/us.py's _calculate_ct_annual_tax and
# hardcoded_defaults._US_CT_WITHHOLDING_TABLES's own comments. Verified
# against the source batch's own worked example (Code A, $60,000
# annualized -> $2,650.00/year) before enabling — matched exactly. Zero
# live US employees existed with work_state="CT" at enable time. An
# employee with work_state="CT" but no ct_withholding_code on file
# resolves to $0, same as every other missing-election case.
# MS/MT/NE/NJ/NM/ND/NC/OK/RI/SC/UT — enabled 2026-09-13, gap-closure
# Level 2 Batches 4/5, genuine primary-source data across 11 states in
# one pass. Two required real engine work, not just data: New Jersey's
# NJ-W4 Rate Table (models.PayrollEmployee.nj_rate_table, a new field —
# an employee with none on file resolves to $0) and North Dakota's Form
# W-4 vintage-dependent bracket selection (the first real consumer of
# models.PayrollEmployee.w4_form_vintage, previously collected but never
# read anywhere in this engine). See hardcoded_defaults.
# _US_STATE_GRADUATED_TAX_RATES's own per-state comments for every
# documented simplification (MS/MT/NE/NM/ND/NJ/OK/RI/SC/UT all share the
# same "no per-employee allowance/dependent-count field exists" gap
# class already used throughout this build-out, always over- never
# under-withholding). Zero live US employees existed with any of these
# eleven as work_state at enable time (verified immediately before
# enabling).
#
# VT/VA/WI/WV — added 2026-09-13 (Batch 6, ZP-TAX-US-2026-001 primary-source
# data): completes "Group A" (every single-layer-only state on the user's
# tracking list) plus West Virginia. VT/VA/WV use the generic graduated
# TaxSlab bracket path (same documented allowance/exemption-count gap as
# the states above); WI does not use TaxSlab rows at all — it is a bespoke
# continuous-deduction calculation (_calculate_wi_annual_tax in us.py)
# reading _US_WI_WITHHOLDING_PARAMS directly, verified against both of the
# source's own worked examples. WV's One-Earner/Two-Earner table choice
# isn't tracked per-employee, so MFJ defaults to the Two-Earner table (the
# source's own deliberately-higher, safer-direction table). Zero live US
# employees existed with any of these four as work_state at enable time
# (verified immediately before enabling).
#
# MO/OH/NY — added 2026-09-13 (Batch 7 "Group B", ZP-TAX-US-2026-001
# primary-source data): completes every jurisdiction on the user's
# original consolidated list. MO uses the generic graduated bracket path
# (one bracket table for every filing status; the MFJ standard deduction
# defaults to the smaller "spouse works" amount absent a dedicated
# checkbox field — same documented-gap convention as WV above). OH's
# table is filing-status-agnostic (only the August 1, 2026-onward table
# is seeded, per the same "current rate only" precedent already used for
# Utah) — its own local municipal/school-district layer is deliberately
# NOT built (ODT's own guidance says to query "The Finder" per address
# rather than maintain a static table — a live lookup-tool integration,
# not data this engine's dormant/live switch pattern applies to). NY uses
# the generic bracket path for its ordinary table plus a bespoke Method
# III override in us.py for wages above $1,077,550; NY's HOH/MFS
# brackets conservatively fall back to its Single table (no HOH/MFS
# table was given); NYC's own resident tax is NOT implemented (the
# source batch didn't give complete bracket breakpoints, only 4 rates and
# one threshold) but Yonkers (both directions) is fully implemented. PA's
# own Act 32 EIT/LST local layer is likewise NOT built — the source
# itself confirms it's a genuine PSD-code registry-scale problem (560+
# collectors) requiring a real DCED/munstats.pa.gov file import via the
# existing LocalityDataset mechanism, not hand-typed data. Zero live US
# employees existed with MO/OH/NY as work_state at enable time (verified
# immediately before enabling).
_US_STATE_TAX_ENABLED_STATES: set[str] = {
    "CO", "KY", "AZ", "IL", "MA", "MI", "PA", "CA", "DC", "DE", "GA", "HI", "IA", "AL", "AR", "MN", "CT",
    "MS", "MT", "NE", "NJ", "NM", "ND", "NC", "OK", "RI", "SC", "UT", "VT", "VA", "WI", "WV",
    "MO", "OH", "NY",
    # Production-Readiness Plan Phase 4, 2026-09-15 — real statutory data
    # independently verified against each state's own primary source (see
    # _US_OR_WITHHOLDING_PARAMS/_US_ME_WITHHOLDING_PARAMS's own docstrings
    # for OR/ME's bespoke logic; MD/LA's real bracket data is entered as
    # ordinary canonical TaxSlab/ContributionRate rows, no bespoke code
    # needed).
    "OR", "ME", "MD", "LA",
    # Kansas — added 2026-09-16 once KW-100 (Rev. 10-24) was actually
    # obtained and independently verified (every published per-pay-period
    # bracket row checked arithmetically consistent; see
    # _US_KS_WITHHOLDING_PARAMS's own docstring). Not enabled earlier this
    # session because KDOR's site was unreachable and no real figures had
    # been confirmed yet.
    "KS",
}

# Per-state rollout switch for a state's own statutory payroll programs
# (SDI/PFML/Paid Leave/TDI/etc., ZP-TAX-US-2026-001 §5) beyond plain income
# tax withholding. While a state is absent from this set, us.py ignores any
# state-scoped program rows configured for it. Same additive-per-state
# reasoning as _US_STATE_TAX_ENABLED_STATES above — these are independent
# switches because a state can have real income-tax data ready before its
# special-program data is, or vice versa (California, for example, has no
# state income tax withholding table in this build but does have SDI).
#
# CA/CT/DC/NY/RI/WA/NJ — enabled 2026-09-07 (build-out per
# ZP-TAX-US-2026-001 §5): zero live US employees existed in the database
# at enable time, so this was purely additive with no real-payslip effect.
# CO/DE/ME added the same day (Phase 3C, headcount-conditional programs —
# see hardcoded_defaults.py's _US_STATE_HEADCOUNT_PROGRAMS/_US_DE_PAID_LEAVE),
# same zero-live-employees reasoning. Massachusetts added 2026-09-11 with
# the flat-state build-out — the document's MA PFML split (EE 0.44% / ER
# 0.44% at 25+ covered) is complete. Minnesota/Oregon are deliberately NOT
# added — the source document doesn't give a complete numeric threshold
# and/or employee/employer split for those two. Vermont added 2026-09-13
# (Batch 6) for its Child Care Contribution (employer-only 0.44%, no wage
# cap) — zero live US employees existed with VT as work_state at enable
# time.
_US_STATE_PROGRAM_ENABLED_STATES: set[str] = {"CA", "CT", "DC", "NY", "RI", "WA", "NJ", "CO", "DE", "ME", "MA", "VT"}

# ── Pay frequency (generic — any country's calculator may use this) ────────
# PayrollContext.pay_frequency defaults to "Monthly", so
# PERIODS_PER_YEAR["Monthly"] == MONTHS_PER_YEAR by construction — every
# existing calculation (which never set pay_frequency) is completely
# unaffected. Only engine/countries/uk.py currently varies its own
# annualization by this.
PERIODS_PER_YEAR = {
    "Weekly": Decimal("52"),
    "Fortnightly": Decimal("26"),
    "FourWeekly": Decimal("13"),
    "Monthly": MONTHS_PER_YEAR,
    # Added for Canada's Option 2 cumulative averaging (gap-closure Phase
    # 9, 2026-09-11) — the frontend's own pay-schedule field
    # (RunDetailPage.jsx) offers "Bi-Weekly"/"Semi-Monthly" literally,
    # neither of which matched any existing key here (both would have
    # silently fallen back to Monthly/12 via this function's own
    # default). Both spellings kept (with/without the hyphen) since nothing
    # in this codebase normalizes the string before it reaches here.
    # Semi-Monthly (24/year, twice a month) is genuinely distinct from
    # Bi-Weekly (26/year, every two weeks) — never conflate the two.
    "BiWeekly": Decimal("26"),
    "Bi-Weekly": Decimal("26"),
    "SemiMonthly": Decimal("24"),
    "Semi-Monthly": Decimal("24"),
}


def resolve_periods_per_year(pay_frequency: str | None) -> Decimal:
    return PERIODS_PER_YEAR.get(pay_frequency or "Monthly", PERIODS_PER_YEAR["Monthly"])


def resolve_period_threshold(annual_threshold: Decimal, pay_frequency: str | None) -> Decimal:
    """An annual statutory threshold (e.g. the NI Primary Threshold),
    converted to the equivalent per-period figure for this pay frequency —
    the reusable piece of "annualize, calculate, de-annualize" that every
    country calculator already does inline, factored out so it isn't
    duplicated once frequency-awareness spreads beyond UK."""
    return annual_threshold / resolve_periods_per_year(pay_frequency)


def resolve_direct_period_threshold(
    period_thresholds_by_frequency: dict,
    annual_threshold: Decimal,
    pay_frequency: str | None,
    rate_map: dict | None = None,
    param_keys_by_frequency: dict | None = None,
    country: str | None = None,
) -> Decimal:
    """For a statutory threshold whose authority publishes REAL, genuinely
    independent per-period figures (e.g. UK NI's own Weekly/Monthly
    thresholds — HMRC rounds each period's table separately, so the
    weekly figure doesn't multiply out to the annual one) — looks up the
    real published figure for `pay_frequency` when present in
    `period_thresholds_by_frequency`, falling back to
    resolve_period_threshold's derived annual/periods_per_year figure for
    any frequency the authority hasn't published a direct table for
    (today's exact existing behavior for those).

    2026-09-09 gap-closure Phase 1: these per-frequency figures used to
    have NO database override path at all — a Super Admin could edit
    every other UK figure except this one. `rate_map`/
    `param_keys_by_frequency`/`country` are optional so every other
    caller (none exist outside uk.py today, but this is a shared/
    country-agnostic helper) keeps working with zero behavior change if
    it doesn't pass them; when a caller does, a configured row for this
    frequency's key overrides the hardcoded figure exactly like every
    other UK parameter already does via resolve_jurisdiction_parameter."""
    frequency = pay_frequency or "Monthly"
    if frequency in period_thresholds_by_frequency:
        default = period_thresholds_by_frequency[frequency]
        param_key = (param_keys_by_frequency or {}).get(frequency)
        if rate_map is not None and param_key:
            return resolve_jurisdiction_parameter(rate_map, param_key, default, country=country)
        return default
    return resolve_period_threshold(annual_threshold, pay_frequency)


# ── Government-mandated scalar parameters (Global Payroll Tax Engine) ──────
# A rate_map row (ContributionRate, org-scoped, synced from the Super-
# Admin-owned canonical row of the same component_key) overrides the
# hardcoded per-country default passed in as `default` — Super Admin
# editing e.g. the US Social Security wage base actually reaches the
# calculator. A jurisdiction/org with no such row behaves exactly as if
# this mechanism didn't exist — additive, never a behavior change.

def _param_amount(rate_map: dict, key: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None and row.flat_amount is not None:
        return row.flat_amount
    return default


def _param_pct(rate_map: dict, key: str, side: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None:
        value = row.employee_rate_pct if side == "employee" else row.employer_rate_pct
        if value is not None:
            return value
    return default


def _param_text(rate_map: dict, key: str, default: str) -> str:
    """Same convention as _param_amount/_param_pct, for a non-numeric
    configuration value (ContributionRate.text_value) — e.g. UK's pension
    calculation basis. A configured row overrides the hardcoded default;
    no row means unaffected/as-before."""
    row = rate_map.get(key)
    if row is not None and getattr(row, "text_value", None):
        return row.text_value
    return default


def is_parameter_configured(rate_map: dict, key: str, side: str = None) -> bool:
    """Whether `key` resolves from a real configured row rather than
    falling back to a hardcoded default — the same check
    resolve_jurisdiction_parameter already does internally to decide
    whether to log a warning, exposed here so a caller can build a
    fallback-parameter list (Section 16 traceability) WITHOUT changing
    resolve_jurisdiction_parameter's own return shape, which every
    existing call site across every country relies on staying a plain
    scalar."""
    row = rate_map.get(key)
    if row is None:
        return False
    if side is not None:
        return getattr(row, f"{side}_rate_pct", None) is not None
    return row.flat_amount is not None


def resolve_jurisdiction_parameter(
    rate_map: dict,
    key: str,
    default,
    side: str = None,
    country: str = None,
    organization_id: int = None,
):
    """The one central resolver for a named scalar parameter (a wage
    ceiling, standard deduction, rebate cap, threshold, allowance, ...)
    consumed via rate_map — every country calculator in
    engine/countries/*.py calls this instead of calling `_param_amount`/
    `_param_pct` directly.

    It is a thin wrapper, not a re-implementation: the actual "does a
    configured row override the hardcoded constant" logic stays exactly
    where it already was (and was already correct) — `_param_amount`
    for a flat-amount parameter (side=None), `_param_pct` for a
    percentage parameter (side="employee"|"employer"). This function's
    only addition is provenance: it logs a warning, naming the missing
    key/country/org, whenever no configured row exists and the
    hardcoded engine default had to be used — so a compliance gap is
    visible in logs rather than silently invisible, without changing
    what value gets returned.

    Lives here (not in engine/tax_resolver.py, despite the name overlap)
    deliberately: this module has zero dependency on the ORM/database
    layer, which is what lets engine/countries/*.py stay import-safe
    from anywhere. tax_resolver.py imports payroll.models directly —
    routing this function through there would pull the ORM into the
    engine package's module-load chain and reintroduce exactly the kind
    of import coupling this module's isolation already avoids.

    Same call shape as the functions it wraps (`rate_map, key, default`
    for an amount; add `side=` for a percentage), so swapping a call
    site is a rename, not a restructure — no calculation changes as a
    result of adopting this resolver by itself."""
    if side is not None:
        value = _param_pct(rate_map, key, side, default)
        row = rate_map.get(key)
        configured = row is not None and getattr(row, f"{side}_rate_pct", None) is not None
    else:
        value = _param_amount(rate_map, key, default)
        row = rate_map.get(key)
        configured = row is not None and row.flat_amount is not None

    if not configured:
        if country in _VALIDATION_ENABLED_COUNTRIES:
            raise MissingComplianceConfigurationError(key, country, organization_id)
        _logger.warning(
            "[jurisdiction-param-fallback] key=%s country=%s organization_id=%s "
            "no configured row found — using hardcoded default %s",
            key, country, organization_id, default,
        )
    return value


# ── Formula-based tax rules (rule_type="FORMULA") ──────────────────────────
# Not every jurisdiction's income tax is a clean bracket table — Germany's
# real Lohnsteuer is a continuous formula, not flat bands. TABLE_LOOKUP/
# MARGINAL_RATE slabs (every jurisdiction's current data) keep using the
# bracket loop below unchanged; a slab row that opts into rule_type=FORMULA
# is evaluated here instead. Deliberately NOT `eval()` — a restricted AST
# walk that only allows arithmetic on a fixed `income` variable, so a
# formula_expression can never execute arbitrary code.

_SAFE_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_safe_node(node, variables: dict) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_safe_node(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        raise ValueError(f"Unknown variable in tax formula: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.left, variables), _eval_safe_node(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.operand, variables))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("min", "max"):
        args = [_eval_safe_node(a, variables) for a in node.args]
        return (min if node.func.id == "min" else max)(*args)
    raise ValueError(f"Disallowed expression in tax formula: {ast.dump(node)}")


def evaluate_tax_formula(expression: str, income: Decimal) -> Decimal:
    """Evaluate a stored formula_expression against a taxable `income`.
    Only arithmetic (+ - * / **), parentheses, min()/max(), and the
    `income` variable are permitted."""
    tree = ast.parse(expression, mode="eval")
    result = _eval_safe_node(tree, {"income": income})
    return max(Decimal("0"), Decimal(result))


# ── Generic bracket calculator ──────────────────────────────────────────

def _calculate_annual_tax(annual_income: Decimal, slabs, filing_status: str | None = None) -> Decimal:
    """Progressive slab-based tax on annual income.

    If any slab row opts into rule_type="FORMULA", that row's
    formula_expression is evaluated directly against annual_income instead
    of the bracket-sum loop — one formula row replaces the whole table for
    that jurisdiction (matches how Germany's real Lohnsteuer works: one
    continuous function, not a set of bands).

    `filing_status` (US-specific; NULL for every other jurisdiction and for
    US callers who don't pass one): if AT LEAST ONE slab in the list
    carries a non-NULL `filing_status` (i.e. Super Admin has configured
    filing-status-specific brackets — e.g. separate Single/MFJ/HoH tables),
    only rows matching this employee's filing_status are used, falling
    back to filing-status-agnostic rows if none match. If NO slab carries a
    filing_status at all (every jurisdiction today, and any US org that
    hasn't configured per-filing-status brackets yet), this is a complete
    no-op — bracket_slabs is built exactly as before this parameter
    existed."""
    formula_row = next((s for s in slabs if getattr(s, "rule_type", None) == "FORMULA" and s.formula_expression), None)
    if formula_row is not None:
        return evaluate_tax_formula(formula_row.formula_expression, annual_income)

    # SURCHARGE rows are a tax-on-tax overlay (surcharge % applied to the
    # tax amount above an income threshold — India's high-earner surcharge),
    # not an ordinary income bracket — they're consumed separately (see
    # india.py's _apply_surcharge) and must be excluded here or they'd be
    # double-counted as if they were plain marginal brackets. PT_FLAT rows
    # (India's state-level Professional Tax, resolved additively elsewhere
    # via get_state_scoped_config) are excluded for the same reason — if one
    # ever ends up in this list by mistake (see tax_resolver.py's
    # _pack_has_income_tax_slabs guard, the primary fix), it must not be
    # silently summed as a 0%-rate income bracket. ON_EHT_BAND rows
    # (Ontario Employer Health Tax's rate table — ONE flat rate for the
    # whole org-aggregate remuneration total, not a marginal bracket sum)
    # are excluded for the identical reason — see
    # engine/countries/canada.py's _on_eht_rate_for_total, which reads
    # them directly instead.
    # NI_BAND/NI_BAND_WEEKLY/NI_BAND_MONTHLY (UK National Insurance category
    # bands) excluded for the identical reason, as a second layer of defense
    # — engine/countries/uk.py's own income_slabs/state_income_slabs filter
    # is supposed to strip these before calling here, but a 2026-09-10 live
    # bug (that filter missed the two per-frequency variants) proved a
    # caller CAN forget, and this function is the one place that would
    # otherwise silently sum them in as bogus income-tax brackets.
    # CA_RETIRING_ALLOWANCE_BAND (Canada's retiring-allowance/severance
    # lump-sum withholding rate table, ZP-TAX-CA-2026-001 §19) is the same
    # "ONE flat rate for the whole amount, not a marginal bracket sum"
    # shape as ON_EHT_BAND — see engine/countries/canada.py's
    # _retiring_allowance_rate_for_amount, which reads these rows directly.
    # AU_PAYG_COEFFICIENT/AU_STSL_COEFFICIENT (ZP-TAX-AU-2026-27-001 §5/§8)
    # are band-selected-by-PERIOD-weekly-x rows evaluated via y=a·x−b, not
    # annual-income marginal brackets at all — see
    # engine/countries/australia.py's _resolve_au_coefficient_band, which
    # reads these rows directly. AU's own annual bracket table (§4) is
    # reference/validation data only (AU-D02) and is stored as ordinary
    # MARGINAL_RATE rows, unaffected by this exclusion.
    # TT_NIS_CLASS (ZP-TT-ENG-001 §5): Trinidad and Tobago's NIS is a
    # fixed 16-earnings-class table — a flat weekly dollar amount per
    # band, not a percentage — the same "band lookup, not a marginal-
    # bracket sum" shape as ON_EHT_BAND/NI_BAND above, excluded here for
    # the identical reason. min_amount/max_amount hold the weekly
    # earnings-class band boundaries (exactly like every other bracket
    # row); flat_amount holds the fixed weekly EMPLOYEE contribution for
    # that class, and adjustment_amount (repurposed as a plain dollar
    # figure, not a percentage — the same generic-column-reuse
    # convention PT_FLAT/AU_PAYG_COEFFICIENT already establish; NOT
    # employer_rate_pct, whose Numeric(6,4) column overflows on a
    # class-XVI-sized $339.00 employer figure — found live against
    # production Postgres, 2026-09-21, same bug class this project has
    # hit before on UK/CA/US builds, never caught by SQLite-backed tests)
    # holds the fixed weekly EMPLOYER contribution. See
    # engine/countries/trinidad_and_tobago.py's _resolve_tt_nis_class,
    # which reads these rows directly instead of this bracket-sum loop.
    bracket_slabs = [
        s for s in slabs
        if getattr(s, "rule_type", None) not in (
            "SURCHARGE", "PT_FLAT", "ON_EHT_BAND", "NI_BAND", "NI_BAND_WEEKLY", "NI_BAND_MONTHLY",
            "CA_RETIRING_ALLOWANCE_BAND", "AU_PAYG_COEFFICIENT", "AU_STSL_COEFFICIENT", "TT_NIS_CLASS",
        )
    ]

    filing_status_tagged = [s for s in bracket_slabs if getattr(s, "filing_status", None) is not None]
    if filing_status_tagged:
        matching = [s for s in filing_status_tagged if s.filing_status == filing_status]
        bracket_slabs = matching if matching else [s for s in bracket_slabs if getattr(s, "filing_status", None) is None]

    if slabs and not bracket_slabs:
        _logger.warning(
            "[income-tax-slabs-unusable] %d configured slab row(s) contained no usable "
            "income-tax bracket (MARGINAL_RATE/FORMULA/TABLE_LOOKUP/FIXED_PLUS_MARGINAL) — "
            "income tax will compute as 0 for every income.",
            len(slabs),
        )

    tax = Decimal("0")
    for slab in sorted(bracket_slabs, key=lambda s: s.min_amount):
        lower = slab.min_amount
        upper = slab.max_amount if slab.max_amount is not None else annual_income
        if annual_income <= lower:
            continue
        taxable_in_band = min(annual_income, upper) - lower
        if taxable_in_band > 0:
            tax += taxable_in_band * (slab.rate_pct / Decimal("100"))
    return tax


def telescope_period_amount(
    gross: Decimal, ytd_before: Decimal, annual_amount_fn: Callable[[Decimal], Decimal],
) -> Decimal:
    """Generic ``annual(after) − annual(before)`` telescoping wrapper for
    an org-level cumulative-remuneration levy, computed as this period's
    incremental slice of the annual amount rather than recomputed from
    scratch each period — so the per-period charges always sum to the
    correct annual total regardless of how many pay periods occur or
    when a rate-band/exemption/threshold boundary is crossed mid-year.

    This is purely the mechanical telescoping shape (identical across
    Canada's Ontario EHT / BC-MB-NL notch levies / Quebec HSF and the
    UK's Apprenticeship Levy — each cross-references the others in their
    own comments as the same reasoning). The actual statutory formula for
    "annual amount at this cumulative total" is jurisdiction-specific and
    stays entirely in the caller's own ``annual_amount_fn`` closure —
    this helper knows nothing about rates, bands, or thresholds.
    """
    ytd_after = ytd_before + gross
    return _round2(annual_amount_fn(ytd_after) - annual_amount_fn(ytd_before))
