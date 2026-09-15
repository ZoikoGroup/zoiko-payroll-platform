"""
scripts/populate_in_source_evidence_v1.py
---------------------------------------------
India counterpart to scripts/populate_ca_source_evidence_v1.py /
scripts/populate_us_source_evidence_v1.py (gap-closure Phase F,
2026-09-11) — closes the same kind of gap those two closed: real
evidence tracking (AC-27/§14/§23) at genuine per-source granularity
instead of one shared/generic SourceArtifact.

ZP-TAX-IN-2026-27-001 §23's own Source Evidence Register lists 14
distinct official sources spanning central income tax (CBDT/ITD),
EPF/ESI (EPFO/ESIC), and 7 states' Professional Tax/Labour Welfare Fund
schedules. This script creates one SourceArtifact per §23 entry
(agency/title/source_url, no publication_date since the document
doesn't give one per source, same disclosed omission as the CA/US
scripts), then links each state's own PT/LWF TaxSlab/ContributionRate
rows to its correct authority — mirroring the CA script's "pack default,
row-level override for a different real authority" structure, adapted
to India's PT/LWF rows (which are TaxSlab/ContributionRate rows scoped
by jurisdiction_state/jurisdiction_locality, not JurisdictionPack-level,
since India runs one country-level Tax pack plus state-scoped PT packs
— see fix_ca_federal_h1_h2_packages.py's own docstring on why CA needed
pack-level linking instead).

Gujarat (IN-GJ-PT) is deliberately marked PRESENT-BUT-NOT-YET-INGESTED:
its SourceArtifact row is created (the source is real and known), but
`reviewer_approved_at` is left unset and no row is linked to it — mirrors
StateLocalProgramReadiness's own SOURCE_REQUIRED status concept (models.py:
"even when the applicable status is NOT_APPLICABLE or SOURCE_REQUIRED"),
since Gujarat's PT rate is deliberately unseeded in hardcoded_defaults.py
pending a current artifact (see this file's own IN-GJ-PT docstring note
below). This script does NOT create a StateLocalProgramReadiness row for
Gujarat itself — that registry is populated by a different mechanism
(see india_uk_knowledge_base_audit's own note that a full §16 readiness
seed is separate, disclosed, still-open work); this script only concerns
itself with SourceArtifact rows and the row-level source_document_id
links this session's own PT/LWF data already has.

Idempotent: get-or-creates every SourceArtifact by (agency, title); safe
to re-run.

Usage:
    python -m scripts.populate_in_source_evidence_v1

IMPORTANT (per this project's own established convention): this script
is written and self-reviewed (static-parse-checked) only in this
session. It has NEVER been executed against any database, live or test —
running any script that imports app.database/app.config requires
explicit go-ahead, every time, per this project's standing rule. Do not
run it without asking first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, SourceArtifact

COUNTRY = "IN"

# (agency, title, source_url) — verbatim from §23's own table.
_SOURCES = {
    "ITD_RATES": (
        "Income Tax Department",
        "Rates / rebate / surcharge reference",
        "https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1",
    ),
    "ITD_TDS_TRANSITION": (
        "Income Tax Department",
        "Section 392 transition FAQ",
        "https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance?mobile-app=1",
    ),
    "CBDT_IT_RULES_2026": (
        "CBDT",
        "Income-tax Rules 2026 notified forms",
        "https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/En-Notified-IT-Rules-2026-20-03-2026.pdf?mobile-app=1",
    ),
    "ITD_FORM_138": (
        "Income Tax Department",
        "Form 138 User Manual",
        "https://www.incometax.gov.in/iec/foportal/newformpage/forms/form138-um",
    ),
    "MOLE_LABOUR_CODES": (
        "Ministry of Labour & Employment",
        "Labour Codes FAQ",
        "https://www.labour.gov.in/static/uploads/2026/01/de4758d5bfeffc456d7de97a801891b0.pdf",
    ),
    "MOLE_COMPLIANCE": (
        "Ministry of Labour & Employment",
        "Compliance Handbook",
        "https://www.labour.gov.in/static/uploads/2026/02/83978455025732b99b0165def80ab171.pdf",
    ),
    "EPFO_FAQ": (
        "EPFO",
        "Contribution rules FAQ",
        "https://www.epfindia.gov.in/site_en/FAQ.php",
    ),
    "ESIC_2026": (
        "ESIC",
        "Contribution guidance",
        "https://esic.gov.in/attachments/publicationfile/9ee889f2149a647db20c722e25ed0ce2.pdf",
    ),
    "KA_PT_SCHED": (
        "Karnataka Commercial Taxes",
        "PT rate schedule",
        "https://gst.karnataka.gov.in/Documents/General/ptnotificationact29323.pdf",
    ),
    "KA_PT_2026_ACT": (
        "Government of Karnataka",
        "PT Amendment Act 2026",
        "https://gst.karnataka.gov.in/latestupdates/PTRules01426.pdf",
    ),
    "MH_PT": (
        "Maharashtra GST Department",
        "PT schedule",
        "https://www.mahagst.gov.in/public/uploads/mvatservices/1761635638Schedule%20of%20Rates%20of%20Tax%20on%20Professions%2C%20Trades%2C%20Callings%20and%20Employments.pdf",
    ),
    "TG_PT": (
        "Telangana Commercial Taxes",
        "PT schedule",
        "https://tgct.gov.in/tgportal/AllActs/APPT/APPTSchedule.aspx",
    ),
    "GJ_PT": (
        "Government of Gujarat Commercial Tax",
        "PT schedule portal",
        "https://commercialtax.gujarat.gov.in/vatwebsite/schedules/schedulesMain.jsp?viewPageNo=6",
    ),
    "OD_PT": (
        "Odisha Tax",
        "PT Act/Schedule",
        "https://web.odishatax.gov.in/PT/ptact.pdf",
    ),
    "CHN_PT": (
        "Greater Chennai Corporation",
        "Revenue Dept PT current schedule",
        "https://chennaicorporation.gov.in/gcc/department/revenue/",
    ),
    "KA_LWF": (
        "Karnataka Labour Welfare Board",
        "Brochure",
        "https://klwb.karnataka.gov.in/storage/pdf-files/brouchernew.pdf",
    ),
    "TN_LWF": (
        "Tamil Nadu Labour Department",
        "Policy Note 2025-26",
        "https://labour.tn.gov.in/pdf/policy_note_lwsd_e_pn_2025_26.pdf",
    ),
}

# component_key PREFIX (ContributionRate) -> source key, for India's
# state-scoped LWF rows (see hardcoded_defaults.py's own lwf_employee_amt/
# lwf_employer_amt/lwf_deduct_month rows, jurisdiction_state-scoped).
_ROW_SOURCE_BY_STATE_PREFIX = {
    "Karnataka": "KA_LWF",
    "Tamil Nadu": "TN_LWF",
}

# TaxSlab jurisdiction_state (+ jurisdiction_locality for Chennai's local
# schedule) -> source key, for India's PT_FLAT bracket rows.
_SLAB_SOURCE_BY_STATE = {
    ("Karnataka", None): "KA_PT_SCHED",
    ("Maharashtra", None): "MH_PT",
    ("Telangana", None): "TG_PT",
    ("Odisha", None): "OD_PT",
    ("Tamil Nadu", "Chennai"): "CHN_PT",
}

# Deliberately present-but-not-yet-ingested (Gujarat's PT rate is
# unseeded in hardcoded_defaults.py pending a current artifact) — the
# SourceArtifact row for GJ_PT is still created (the source is real and
# known, per §23), but is never marked reviewed and never linked to any
# TaxSlab row, since none exists to link.
_NOT_YET_INGESTED = {"GJ_PT"}


def _get_or_create_source(db, key: str, agency: str, title: str, url: str) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        existing.source_url = url
        return existing
    artifact = SourceArtifact(agency=agency, title=title, source_url=url)
    db.add(artifact)
    db.flush()
    return artifact


def run():
    db = SessionLocal()
    try:
        sources = {key: _get_or_create_source(db, key, agency, title, url) for key, (agency, title, url) in _SOURCES.items()}
        db.flush()
        print(f"--- {len(sources)} SourceArtifact rows ready ---")
        for key, s in sources.items():
            flag = " (PRESENT — NOT YET INGESTED/CERTIFIED)" if key in _NOT_YET_INGESTED else ""
            print(f"  {key} -> id={s.id} {s.agency} / {s.title}{flag}")

        print()
        print("--- Setting row-level source_document_id for state LWF ContributionRate rows ---")
        overridden = 0
        rows = db.query(ContributionRate).filter(
            ContributionRate.jurisdiction_country == COUNTRY, ContributionRate.organization_id.is_(None),
        ).all()
        for row in rows:
            source_key = _ROW_SOURCE_BY_STATE_PREFIX.get(row.jurisdiction_state)
            if source_key and row.component_key in ("lwf_employee_amt", "lwf_employer_amt", "lwf_deduct_month"):
                row.source_document_id = sources[source_key].id
                overridden += 1
        print(f"  Overrode {overridden} LWF rate rows.")

        print()
        print("--- Setting row-level source_document_id for state PT_FLAT TaxSlab rows ---")
        slab_overridden = 0
        slab_rows = db.query(TaxSlab).filter(
            TaxSlab.jurisdiction_country == COUNTRY, TaxSlab.organization_id.is_(None), TaxSlab.rule_type == "PT_FLAT",
        ).all()
        for row in slab_rows:
            source_key = _SLAB_SOURCE_BY_STATE.get((row.jurisdiction_state, row.jurisdiction_locality))
            if source_key:
                row.source_document_id = sources[source_key].id
                slab_overridden += 1
        print(f"  Overrode {slab_overridden} PT slab rows.")

        db.commit()
        print()
        print("DONE.")
        print(
            f"NOTE: {sorted(_NOT_YET_INGESTED)} created but deliberately left unreviewed/unlinked "
            "(known source, not yet certified — matches Gujarat's own deliberately-unseeded PT rate)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
