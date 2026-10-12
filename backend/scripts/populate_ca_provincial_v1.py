"""
scripts/populate_ca_provincial_v1.py
--------------------------------------
Canada provincial/territorial + Quebec canonical seed data
(ZP-TAX-CA-2026-001), restoring the provincial data that was previously
entered live (via the throwaway Super Admin account + maker-checker
approval) but was found missing after a database reconnection.

Deliberately a SEPARATE script from populate_canonical_tax_v1.py: that
script only ever seeds the country-level (jurisdiction_state IS NULL)
pack. Federal-level CPP/EI/BPAF/CEA/etc. figures are already correctly
seeded there and are NOT touched here.

Seeds, per jurisdiction:
  - 12 non-Quebec provinces/territories: income tax brackets (§8) +
    provincial_bpa (or Manitoba's dynamic BPA / Yukon's federal-BPAF-
    mirror, which needs no row).
  - BC: basic tax reduction (§9) + BC EHT (ordinary + charity/nonprofit, §15).
  - Manitoba: HE Levy (§15).
  - Newfoundland & Labrador: HAPSET (§15).
  - Ontario: EHT exemption + 9 rate bands (§16).
  - Northwest Territories / Nunavut: 2% employee territorial payroll tax (§14).
  - Quebec: its own bracket table (§12) + BPA/worker deduction/labour
    standards cap/QPP/QPIP/HSF parameters (§12/§13).

NOTE: every dormant _CA_*_ENABLED_COUNTRIES switch in shared.py (credit
method, dynamic provincial BPA, BC tax reduction, age-gated CPP, CPP
component split, CPP/EI federal credit, EI employer multiplier, LSVCC
credit, beyond-province surtax) is currently OFF. This script only seeds
DATA — it does not enable any switch. Some of this data (BC's reduction,
Manitoba/Yukon's dynamic BPA) has no calculation effect until its
corresponding switch is enabled.

Idempotent: safe to re-run (updates existing rows by
(jurisdiction_state, component_key) / (jurisdiction_state, sort_order)
rather than duplicating).

Usage:
    python -m scripts.populate_ca_provincial_v1
"""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack, SourceArtifact
from app.modules.payroll.service import record_tax_audit
from datetime import date

from app.modules.payroll.hardcoded_defaults import (
    _CA_PROVINCIAL_BRACKETS, _CA_PROVINCIAL_BPA, _CA_MB_DYNAMIC_BPA,
    _CA_H1_H2_PROVINCES, _CA_ON_EHT_EXEMPTION, _CA_ON_EHT_BANDS,
    _CA_EMPLOYER_LEVIES, _CA_TERRITORIAL_PAYROLL_TAX, _CA_QUEBEC_BRACKETS, _CA_QUEBEC_PARAMS,
)

COUNTRY = "CA"
TAX_YEAR = "2026"
CURRENCY = "CAD"
SOURCE_TITLE = "ZP-TAX-CA-2026-001 v1.0 — Canada 2026 Statutory Configuration Pack"
SOURCE_AGENCY = "CRA T4127 (122nd/123rd Ed.) / Revenu Québec TP-1015.F-V / provincial authorities"


def _get_or_create_pack(db, state: str, change_summary: str) -> JurisdictionPack:
    pack = (
        db.query(JurisdictionPack)
        .filter(
            JurisdictionPack.pack_type == "tax",
            JurisdictionPack.jurisdiction_country == COUNTRY,
            JurisdictionPack.jurisdiction_state == state,
        )
        .first()
    )
    if pack is None:
        pack = JurisdictionPack(
            pack_id=f"CA-{state}-2026-V1",
            jurisdiction_country=COUNTRY,
            jurisdiction_state=state,
            pack_type="tax",
            version="1.0",
            status="Active",
            tax_year=TAX_YEAR,
            currency=CURRENCY,
            regulatory_authority="ZP-TAX-CA-2026-001",
            change_summary=change_summary,
        )
        db.add(pack)
        db.flush()
    else:
        pack.change_summary = change_summary
        if pack.status != "Active":
            pack.status = "Active"
    return pack


def _get_or_create_h1_h2_pack(db, state: str, half: str, effective_from, effective_to, change_summary: str) -> JurisdictionPack:
    """Same shape as _get_or_create_pack, but keyed by the exact pack_id
    (state can now have TWO packs, H1 and H2) instead of by state alone."""
    pack_id = f"CA-{state}-2026-{half}"
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id).first()
    if pack is None:
        pack = JurisdictionPack(
            pack_id=pack_id, jurisdiction_country=COUNTRY, jurisdiction_state=state,
            pack_type="tax", version="1.0", status="Active", tax_year=TAX_YEAR, currency=CURRENCY,
            regulatory_authority="ZP-TAX-CA-2026-001", change_summary=change_summary,
            effective_from=effective_from, effective_to=effective_to,
        )
        db.add(pack)
        db.flush()
    else:
        pack.change_summary = change_summary
        pack.effective_from = effective_from
        pack.effective_to = effective_to
        if pack.status != "Active":
            pack.status = "Active"
    return pack


def _retire_single_package_pack(db, state: str):
    """BC/NL/PE previously got ONE flat package each (an earlier, since-
    corrected simplification — see _CA_H1_H2_PROVINCES's own comment).
    Retire that pack and remove its rows so it can never win a
    _resolve_pack_scoped_rows candidacy check by accident; the real H1/H2
    packages replace it entirely. No-op if it was never created."""
    old_pack_id = f"CA-{state}-2026-V1"
    old_pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == old_pack_id).first()
    if old_pack is None:
        return
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == old_pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == old_pack.id).delete()
    old_pack.status = "Retired"
    db.commit()


def _get_or_create_source(db) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == SOURCE_AGENCY, SourceArtifact.title == SOURCE_TITLE).first()
    if existing:
        return existing
    artifact = SourceArtifact(agency=SOURCE_AGENCY, title=SOURCE_TITLE)
    db.add(artifact)
    db.flush()
    return artifact


def _upsert_slab(db, state: str, sort_order: int, pack_id: int, min_amount, max_amount, rate_pct: str, rule_type="MARGINAL_RATE", **extra):
    # Matched by (state, sort_order, pack_id) — NOT (state, sort_order)
    # alone. BC/NL/PE's H1 and H2 packs each carry their own bracket rows
    # reusing the SAME sort_order range (that's fine — TaxSlab
    # disambiguation groups by rule_type + pack_id at read time, never by
    # sort_order), so pack_id must be part of the match here too, or the
    # second pack's write silently overwrites the first pack's row
    # in place instead of creating a second one.
    existing = (
        db.query(TaxSlab)
        .filter(
            TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_country == COUNTRY,
            TaxSlab.jurisdiction_state == state, TaxSlab.sort_order == sort_order,
            TaxSlab.jurisdiction_pack_id == pack_id,
        )
        .first()
    )
    fields = dict(
        min_amount=Decimal(str(min_amount)), max_amount=Decimal(str(max_amount)) if max_amount is not None else None,
        rate_pct=Decimal(rate_pct), rate_label=f"{rate_pct}%", tax_formula="Bracket",
        rule_type=rule_type, sort_order=sort_order, jurisdiction_pack_id=pack_id, **extra,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(TaxSlab(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **fields))


def _upsert_rate(db, state: str, component_key: str, pack_id: int, sort_order: int, **fields):
    # Matched by (state, component_key, pack_id) — see _upsert_slab's own
    # comment on why pack_id must be part of the match: BC's H1 and H2
    # packs both carry a "provincial_bpa"/"bc_basic_tax_reduction" row
    # under the SAME component_key (the engine reads that one literal key
    # regardless of which pack wins), so without pack_id in the filter,
    # the H2 write would silently overwrite the H1 row in place.
    existing = (
        db.query(ContributionRate)
        .filter(
            ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_country == COUNTRY,
            ContributionRate.jurisdiction_state == state, ContributionRate.component_key == component_key,
            ContributionRate.filing_status.is_(None), ContributionRate.jurisdiction_pack_id == pack_id,
        )
        .first()
    )
    row_fields = dict(fields, component_key=component_key, sort_order=sort_order, jurisdiction_pack_id=pack_id)
    if existing:
        for k, v in row_fields.items():
            setattr(existing, k, v)
    else:
        db.add(ContributionRate(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **row_fields))


def run():
    db = SessionLocal()
    try:
        source = _get_or_create_source(db)
        db.flush()

        # ── 12 non-Quebec provinces/territories: brackets + BPA ──────────
        for state, brackets in _CA_PROVINCIAL_BRACKETS.items():
            pack = _get_or_create_pack(db, state, change_summary=f"Provincial income tax brackets per {SOURCE_TITLE} §8.")
            pack.source_document_id = source.id
            for i, (lo, hi, rate) in enumerate(brackets, start=1):
                _upsert_slab(db, state, i, pack.id, lo, hi, rate)
            rate_count = 0
            if state == "MB":
                mb = _CA_MB_DYNAMIC_BPA
                _upsert_rate(db, state, "mb_bpa_max", pack.id, 50, label="Manitoba Dynamic BPA — Max", employee_share="—", employer_share="—", total=f"${mb['max']}", flat_amount=Decimal(mb["max"]))
                _upsert_rate(db, state, "mb_bpa_ni_thresh_lo", pack.id, 51, label="Manitoba Dynamic BPA — NI Threshold (Low)", employee_share="—", employer_share="—", total=f"${mb['ni_thresh_lo']}", flat_amount=Decimal(mb["ni_thresh_lo"]))
                _upsert_rate(db, state, "mb_bpa_ni_thresh_hi", pack.id, 52, label="Manitoba Dynamic BPA — NI Threshold (High)", employee_share="—", employer_share="—", total=f"${mb['ni_thresh_hi']}", flat_amount=Decimal(mb["ni_thresh_hi"]))
                rate_count = 3
            elif state in _CA_PROVINCIAL_BPA:
                amount = _CA_PROVINCIAL_BPA[state]
                _upsert_rate(db, state, "provincial_bpa", pack.id, 50, label="Provincial Basic Personal Amount", employee_share="—", employer_share="—", total=f"${amount}", flat_amount=Decimal(amount))
                rate_count = 1
            # YT: no row needed (mirrors federal BPAF via canada.py's own branch).

            if state == "MB":
                lv = _CA_EMPLOYER_LEVIES["mb_he_levy"]
                _upsert_rate(db, state, "mb_he_levy_exemption_threshold", pack.id, 61, label="MB HE Levy Exemption Threshold", employee_share="—", employer_share="—", total=f"${lv['exemption_threshold']}", flat_amount=Decimal(lv["exemption_threshold"]))
                _upsert_rate(db, state, "mb_he_levy_upper_threshold", pack.id, 62, label="MB HE Levy Upper Threshold", employee_share="—", employer_share="—", total=f"${lv['upper_threshold']}", flat_amount=Decimal(lv["upper_threshold"]))
                _upsert_rate(db, state, "mb_he_levy_notch_rate", pack.id, 63, label="MB HE Levy Notch Rate", employee_share="—", employer_share=f"{lv['notch_rate']}%", total=f"{lv['notch_rate']}%", employer_rate_pct=Decimal(lv["notch_rate"]))
                _upsert_rate(db, state, "mb_he_levy_flat_rate", pack.id, 64, label="MB HE Levy Flat Rate", employee_share="—", employer_share=f"{lv['flat_rate']}%", total=f"{lv['flat_rate']}%", employer_rate_pct=Decimal(lv["flat_rate"]))
                rate_count += 4

            if state == "ON":
                _upsert_rate(db, state, "on_eht_exemption", pack.id, 60, label="Ontario EHT Exemption", employee_share="—", employer_share="—", total=f"${_CA_ON_EHT_EXEMPTION}", flat_amount=Decimal(_CA_ON_EHT_EXEMPTION))
                rate_count += 1
                for i, (lo, hi, rate) in enumerate(_CA_ON_EHT_BANDS, start=100):
                    _upsert_slab(db, state, i, pack.id, lo, hi, "0", rule_type="ON_EHT_BAND", employer_rate_pct=Decimal(rate))

            if state in ("NT", "NU"):
                rate = _CA_TERRITORIAL_PAYROLL_TAX[state]
                key = "nwt_payroll_tax" if state == "NT" else "nu_payroll_tax"
                _upsert_rate(db, state, key, pack.id, 60, label=f"{state} Territorial Payroll Tax", employee_share=f"{rate}%", employer_share="—", total=f"{rate}%", employee_rate_pct=Decimal(rate))
                rate_count += 1

            db.commit()
            record_tax_audit(
                db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                jurisdiction_pack_id=pack.id, tax_version=pack.version,
                reason="Canada provincial build-out (ZP-TAX-CA-2026-001): canonical provincial tax data",
                new_value={"taxSlabs": len(brackets), "contributionRates": rate_count},
            )
            print(f"CA-{state}: pack {pack.pack_id} v{pack.version} -> {len(brackets)} tax slab(s), {rate_count} contribution rate row(s).")

        # ── BC / NL / PE: genuine H1 + H2 packages (§9) ──────────────────
        # These 3 are the ONLY jurisdictions the document gives a real
        # mid-year difference for. Retire any old single-package pack from
        # a prior run first, so it can never be picked up as a stray
        # candidate alongside the real H1/H2 pair.
        h1_dates = (date(2026, 1, 1), date(2026, 6, 30))
        h2_dates = (date(2026, 7, 1), date(2026, 12, 31))
        for state, halves in _CA_H1_H2_PROVINCES.items():
            _retire_single_package_pack(db, state)
            for half, (eff_from, eff_to) in (("H1", h1_dates), ("H2", h2_dates)):
                data = halves[half.lower()]
                pack = _get_or_create_h1_h2_pack(
                    db, state, half, eff_from, eff_to,
                    change_summary=f"Provincial income tax brackets ({half}, {eff_from}–{eff_to}) per {SOURCE_TITLE} §8/§9.",
                )
                pack.source_document_id = source.id
                for i, (lo, hi, rate) in enumerate(data["brackets"], start=1):
                    _upsert_slab(db, state, i, pack.id, lo, hi, rate)
                rate_count = 0
                _upsert_rate(db, state, "provincial_bpa", pack.id, 50, label="Provincial Basic Personal Amount", employee_share="—", employer_share="—", total=f"${data['provincial_bpa']}", flat_amount=Decimal(data["provincial_bpa"]))
                rate_count += 1
                if "bc_basic_tax_reduction" in data:
                    _upsert_rate(db, state, "bc_basic_tax_reduction", pack.id, 60, label="BC Basic Tax Reduction", employee_share="—", employer_share="—", total=f"${data['bc_basic_tax_reduction']}", flat_amount=Decimal(data["bc_basic_tax_reduction"]))
                    rate_count += 1
                if state == "BC" and half == "H1":
                    # BC's own employer levies don't vary by half (§15 gives
                    # no H1/H2 split for EHT) — attached to just the H1 pack,
                    # which is fine: _resolve_pack_scoped_rows only narrows
                    # a component_key's rows when 2+ DISTINCT pack_ids exist
                    # for that key, and these only ever have one.
                    for prefix in ("bc_eht", "bc_eht_charity"):
                        lv = _CA_EMPLOYER_LEVIES[prefix]
                        _upsert_rate(db, state, f"{prefix}_exemption_threshold", pack.id, 61, label=f"{prefix} Exemption Threshold", employee_share="—", employer_share="—", total=f"${lv['exemption_threshold']}", flat_amount=Decimal(lv["exemption_threshold"]))
                        _upsert_rate(db, state, f"{prefix}_upper_threshold", pack.id, 62, label=f"{prefix} Upper Threshold", employee_share="—", employer_share="—", total=f"${lv['upper_threshold']}", flat_amount=Decimal(lv["upper_threshold"]))
                        _upsert_rate(db, state, f"{prefix}_notch_rate", pack.id, 63, label=f"{prefix} Notch Rate", employee_share="—", employer_share=f"{lv['notch_rate']}%", total=f"{lv['notch_rate']}%", employer_rate_pct=Decimal(lv["notch_rate"]))
                        _upsert_rate(db, state, f"{prefix}_flat_rate", pack.id, 64, label=f"{prefix} Flat Rate", employee_share="—", employer_share=f"{lv['flat_rate']}%", total=f"{lv['flat_rate']}%", employer_rate_pct=Decimal(lv["flat_rate"]))
                        rate_count += 4
                if state == "NL" and half == "H1":
                    lv = _CA_EMPLOYER_LEVIES["nl_hapset"]
                    _upsert_rate(db, state, "nl_hapset_exemption_threshold", pack.id, 61, label="NL HAPSET Exemption Threshold", employee_share="—", employer_share="—", total=f"${lv['exemption_threshold']}", flat_amount=Decimal(lv["exemption_threshold"]))
                    _upsert_rate(db, state, "nl_hapset_flat_rate", pack.id, 62, label="NL HAPSET Rate", employee_share="—", employer_share=f"{lv['flat_rate']}%", total=f"{lv['flat_rate']}%", employer_rate_pct=Decimal(lv["flat_rate"]))
                    rate_count += 2
                db.commit()
                record_tax_audit(
                    db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                    jurisdiction_pack_id=pack.id, tax_version=pack.version,
                    reason="Canada provincial build-out (ZP-TAX-CA-2026-001): genuine H1/H2 provincial data",
                    new_value={"taxSlabs": len(data["brackets"]), "contributionRates": rate_count},
                )
                print(f"CA-{state}-{half}: pack {pack.pack_id} v{pack.version} ({eff_from}–{eff_to}) -> {len(data['brackets'])} tax slab(s), {rate_count} contribution rate row(s).")

        # ── Quebec ────────────────────────────────────────────────────────
        qc_pack = _get_or_create_pack(db, "QC", change_summary=f"Quebec independent tax module per {SOURCE_TITLE} §12/§13.")
        qc_pack.source_document_id = source.id
        for i, (lo, hi, rate) in enumerate(_CA_QUEBEC_BRACKETS, start=1):
            _upsert_slab(db, "QC", i, qc_pack.id, lo, hi, rate)
        qc = _CA_QUEBEC_PARAMS
        qc_rate_count = 0
        _upsert_rate(db, "QC", "quebec_bpa", qc_pack.id, 50, label="Quebec Basic Personal Amount", employee_share="—", employer_share="—", total=f"${qc['quebec_bpa']}", flat_amount=Decimal(qc["quebec_bpa"]))
        _upsert_rate(db, "QC", "qc_worker_deduction", qc_pack.id, 51, label="Quebec Deduction for Workers", employee_share="—", employer_share="—", total=f"${qc['qc_worker_deduction']}", flat_amount=Decimal(qc["qc_worker_deduction"]))
        _upsert_rate(db, "QC", "qc_labour_standards_cap", qc_pack.id, 52, label="Quebec Labour Standards — Max Subject Remuneration", employee_share="—", employer_share="—", total=f"${qc['qc_labour_standards_cap']}", flat_amount=Decimal(qc["qc_labour_standards_cap"]))
        _upsert_rate(db, "QC", "qpp", qc_pack.id, 53, label="Quebec Pension Plan (QPP)", employee_share=f"{qc['qpp']['employee']}%", employer_share=f"{qc['qpp']['employer']}%", total=f"{Decimal(qc['qpp']['employee']) + Decimal(qc['qpp']['employer'])}%", employee_rate_pct=Decimal(qc["qpp"]["employee"]), employer_rate_pct=Decimal(qc["qpp"]["employer"]))
        _upsert_rate(db, "QC", "qpip", qc_pack.id, 54, label="Quebec Parental Insurance Plan (QPIP)", employee_share=f"{qc['qpip']['employee']}%", employer_share=f"{qc['qpip']['employer']}%", total=f"{Decimal(qc['qpip']['employee']) + Decimal(qc['qpip']['employer'])}%", employee_rate_pct=Decimal(qc["qpip"]["employee"]), employer_rate_pct=Decimal(qc["qpip"]["employer"]))
        _upsert_rate(db, "QC", "qpip_mie", qc_pack.id, 55, label="QPIP Maximum Insurable Earnings", employee_share="—", employer_share="—", total=f"${qc['qpip_mie']}", flat_amount=Decimal(qc["qpip_mie"]))
        _upsert_rate(db, "QC", "qc_hsf_threshold_low", qc_pack.id, 56, label="Quebec HSF — Threshold Low", employee_share="—", employer_share="—", total=f"${qc['qc_hsf_threshold_low']}", flat_amount=Decimal(qc["qc_hsf_threshold_low"]))
        _upsert_rate(db, "QC", "qc_hsf_threshold_high", qc_pack.id, 57, label="Quebec HSF — Threshold High", employee_share="—", employer_share="—", total=f"${qc['qc_hsf_threshold_high']}", flat_amount=Decimal(qc["qc_hsf_threshold_high"]))
        _upsert_rate(db, "QC", "qc_hsf_general_low_rate", qc_pack.id, 58, label="Quebec HSF — General ≤$1M", employee_share="—", employer_share=f"{qc['qc_hsf_general_low_rate']}%", total=f"{qc['qc_hsf_general_low_rate']}%", employer_rate_pct=Decimal(qc["qc_hsf_general_low_rate"]))
        _upsert_rate(db, "QC", "qc_hsf_general_high_rate", qc_pack.id, 59, label="Quebec HSF — General ≥$7.8M", employee_share="—", employer_share=f"{qc['qc_hsf_general_high_rate']}%", total=f"{qc['qc_hsf_general_high_rate']}%", employer_rate_pct=Decimal(qc["qc_hsf_general_high_rate"]))
        _upsert_rate(db, "QC", "qc_hsf_general_mid_base", qc_pack.id, 60, label="Quebec HSF — General Mid Base", employee_share="—", employer_share=f"{qc['qc_hsf_general_mid_base']}%", total=f"{qc['qc_hsf_general_mid_base']}%", employer_rate_pct=Decimal(qc["qc_hsf_general_mid_base"]))
        _upsert_rate(db, "QC", "qc_hsf_general_mid_slope", qc_pack.id, 61, label="Quebec HSF — General Mid Slope", employee_share="—", employer_share=f"{qc['qc_hsf_general_mid_slope']}%", total=f"{qc['qc_hsf_general_mid_slope']}%", employer_rate_pct=Decimal(qc["qc_hsf_general_mid_slope"]))
        _upsert_rate(db, "QC", "qc_hsf_primary_low_rate", qc_pack.id, 62, label="Quebec HSF — Primary/Mfg ≤$1M", employee_share="—", employer_share=f"{qc['qc_hsf_primary_low_rate']}%", total=f"{qc['qc_hsf_primary_low_rate']}%", employer_rate_pct=Decimal(qc["qc_hsf_primary_low_rate"]))
        _upsert_rate(db, "QC", "qc_hsf_primary_high_rate", qc_pack.id, 63, label="Quebec HSF — Primary/Mfg ≥$7.8M", employee_share="—", employer_share=f"{qc['qc_hsf_primary_high_rate']}%", total=f"{qc['qc_hsf_primary_high_rate']}%", employer_rate_pct=Decimal(qc["qc_hsf_primary_high_rate"]))
        _upsert_rate(db, "QC", "qc_hsf_primary_mid_base", qc_pack.id, 64, label="Quebec HSF — Primary/Mfg Mid Base", employee_share="—", employer_share=f"{qc['qc_hsf_primary_mid_base']}%", total=f"{qc['qc_hsf_primary_mid_base']}%", employer_rate_pct=Decimal(qc["qc_hsf_primary_mid_base"]))
        _upsert_rate(db, "QC", "qc_hsf_primary_mid_slope", qc_pack.id, 65, label="Quebec HSF — Primary/Mfg Mid Slope", employee_share="—", employer_share=f"{qc['qc_hsf_primary_mid_slope']}%", total=f"{qc['qc_hsf_primary_mid_slope']}%", employer_rate_pct=Decimal(qc["qc_hsf_primary_mid_slope"]))
        _upsert_rate(db, "QC", "qc_hsf_public_rate", qc_pack.id, 66, label="Quebec HSF — Public Sector", employee_share="—", employer_share=f"{qc['qc_hsf_public_rate']}%", total=f"{qc['qc_hsf_public_rate']}%", employer_rate_pct=Decimal(qc["qc_hsf_public_rate"]))
        qc_rate_count = 16
        db.commit()
        record_tax_audit(
            db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=qc_pack.id,
            jurisdiction_pack_id=qc_pack.id, tax_version=qc_pack.version,
            reason="Canada provincial build-out (ZP-TAX-CA-2026-001): Quebec independent module data",
            new_value={"taxSlabs": len(_CA_QUEBEC_BRACKETS), "contributionRates": qc_rate_count},
        )
        print(f"CA-QC: pack {qc_pack.pack_id} v{qc_pack.version} -> {len(_CA_QUEBEC_BRACKETS)} tax slab(s), {qc_rate_count} contribution rate row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
