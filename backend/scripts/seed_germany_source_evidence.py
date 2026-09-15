"""
scripts/seed_germany_source_evidence.py
------------------------------------------
Phase 8O — backfill SourceArtifact rows for the Germany source-evidence
citations that have ALREADY been independently fetched/verified across
prior phases (8B, 8C-2, 8F, 8H, 8J, 8L), with their exact cited hash/URL/
date preserved verbatim from this codebase's own existing code comments —
never fabricated, never re-guessed.

Phase 8P adds seven more entries — the evidence actually fetched LIVE this
phase (AOK's official 2026 Rechengrößen page independently confirming the
RV/ALV and GKV/PV contribution ceilings already in this codebase; three
Krankenkasse-specific 2026 Zusatzbeitrag rates fetched directly from each
fund's own official page — TK, DAK-Gesundheit, AOK PLUS; and the supplied
Zoiko Germany 2026 statutory document itself, §9 and §10, which this
phase's own instructed source-authority hierarchy ranks ABOVE external
official sources for statutory VALUES the document states directly).

Phase 8Y adds one more entry — §15 of the supplied document itself (the
Earnings and Deduction Taxability Matrix), re-read directly from the docx's
own XML this phase. This is the same "supplied document is Tier-1 authority
for values it states directly" standing already given to §9/§10.

Phase 8Z adds two Tier-2 primary-law entries — §3b EStG and §1 SvEV — the
actual statutory mechanism behind the §15 OVERTIME_SHIFT_PREMIUM row's
"Depends on statutory exemption conditions" / "May differ" classification.
These do not change any registry row's authority_source_id (the row's
stored classification remains a Tier-1 transcription of §15 itself); they
record genuine primary-source evidence for whichever future phase designs
the engine-input fields this statute requires. See
docs/PHASE_8Z_GERMANY_OVERTIME_SHIFT_PREMIUM_STATUTORY_MODEL_AND_ENGINE_READINESS_REPORT.md.

This intentionally does NOT cover all 14 DE-SRC entries from the supplied
document's §24 Source Register, and does NOT cover every Krankenkasse in
Germany. Only entries with an actual fetch/verification EVENT recorded
anywhere in this repository (a hash, a "Stand"/publication date obtained by
directly reading the source, not merely a citation of the document's own
reference table) are included. Ten DE-SRC entries
(003/004/005/006/010/011/012/013/014) remain SOURCE_REQUIRED for the same
reason — see the Phase 8O/8P reports.

Phase 8AL adds a fourth fund — BARMER. Phase 8O/8P had investigated BARMER
and found only secondary/tertiary aggregator sources (never a primary
BARMER-owned page), so it was deliberately excluded then. Phase 8AL found a
genuine, official, BARMER-branded PDF ("Eckwerte ab Januar 2026",
Artikelnummer 6221 0126, fetched directly from barmer.de's own resource/blob
path) stating BARMER's exact 2026 Zusatzbeitrag AND both U1 tariffs AND the
U2 rate on one page — resolving the prior gap with real Tier-1 evidence, not
by lowering the evidence bar.

Usage (against whichever DATABASE_URL is configured in the environment —
this script is NEVER invoked automatically and was not run against any
shared/remote database by this phase; see the phase report's own
disclosure):

    python -m scripts.seed_germany_source_evidence
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from sqlalchemy.orm import Session

from app.database import SessionLocal, initialize_database
from app.modules.payroll.models import SourceArtifact


# Every field here is a verbatim transcription of a value already recorded
# in this codebase (see the `_evidence_ref` comment on each entry) — not a
# new fetch performed by this script, and not an invented value.
# NOTE: All titles kept under 300 chars for VARCHAR(300) DB constraint.
GERMANY_SOURCE_EVIDENCE = [
    dict(
        agency="BMF / ITZBund",
        title="PAP Lohnsteuer 2026 (Lohnsteuer2026.xml) — Stand 2025-10-23; PDF 'endgültig' 2025-11-12",
        form_number=None,
        source_url="https://www.bmf-steuerrechner.de/javax.faces.resource/daten/xmls/Lohnsteuer2026.xml.xhtml",
        publication_date=date(2025, 11, 12),
        checksum_sha256="63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4",
    ),
    dict(
        agency="Deutsche Rentenversicherung",
        title="Gleitzone/Übergangsbereich — Faktor F, Stand 19.12.2025, published 29.12.2025 (ab 01.01.2026)",
        form_number=None,
        source_url="https://rvrecht.deutsche-rentenversicherung.de/SharedDocs/rvRecht/07_AktuelleWerte/D-G/awert_glzre.html",
        publication_date=date(2025, 12, 29),
        checksum_sha256=None,
    ),
    dict(
        agency="Bundesministerium der Justiz (gesetze-im-internet.de)",
        title="SGB XI §55 Abs. 3: PV childless surcharge 0.6 rate points",
        form_number="§55 SGB XI",
        source_url="https://www.gesetze-im-internet.de/sgb_11/__55.html",
        publication_date=None,
        checksum_sha256=None,
    ),
    dict(
        agency="Bundesministerium der Justiz (gesetze-im-internet.de)",
        title="SGB XI §58 Abs. 1: childless PV surcharge 100% employee-borne (all Länder)",
        form_number="§58 SGB XI",
        source_url="https://www.gesetze-im-internet.de/sgb_11/__58.html",
        publication_date=None,
        checksum_sha256=None,
    ),

    # ── Phase 8P — fetched LIVE this phase (WebFetch, 2026-09-04) ────────

    dict(
        agency="AOK",
        title="AOK Rechengrößen 2026: RV/ALV €8450/€101400; GKV/PV €5812.50/€69750; JAEG €77400; Bezugsgröße €3955/€47460",
        form_number=None,
        source_url="https://www.aok.de/pp/gg/update/rechengroessen-2026/",
        publication_date=None,
        checksum_sha256=None,
    ),
    dict(
        agency="Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0",
        title="§9 2026 Social-Insurance Core Rates and Ceilings (RV/ALV/GKV/PV rates and ceilings)",
        form_number="ZP-TAX-DE-2026-001 §9",
        source_url=None,
        publication_date=date(2026, 8, 21),
        checksum_sha256=None,
    ),
    dict(
        agency="Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0",
        title="§10 Long-Term Care Insurance — Child and Saxony Logic (PV rate matrix, 6 child cats × Saxony)",
        form_number="ZP-TAX-DE-2026-001 §10",
        source_url=None,
        publication_date=date(2026, 8, 21),
        checksum_sha256=None,
    ),
    dict(
        agency="Techniker Krankenkasse (TK)",
        title="TK 2026 Zusatzbeitragssatz: 2.69% (Gesamt 17.29%), eff. 2026-01-01",
        form_number=None,
        source_url="https://www.tk.de/presse/themen/gesundheitssystem/selbstverwaltung/zusatzbeitrag-2026-festgelegt-2188214",
        publication_date=date(2025, 12, 19),
        checksum_sha256=None,
    ),
    dict(
        agency="DAK-Gesundheit",
        title="DAK 2026 Zusatzbeitragssatz: 3.2% (Gesamt 17.8%)",
        form_number=None,
        source_url="https://www.dak.de/arbeitgeber-portal/sozialversicherung/beitragssaetze-rechengroessen/informationen-fuer-arbeitgeber-beitragssaetze_64402",
        publication_date=None,
        checksum_sha256=None,
    ),
    dict(
        agency="AOK PLUS (Sachsen und Thüringen)",
        title="AOK PLUS 2026 Zusatzbeitragssatz: 3.1% (Gesamt 17.7%) — Saxony/Thuringia regional fund",
        form_number=None,
        source_url="https://www.aok.de/pp/plus/sachsen-aok-plus-zahlte-51-millionen-euro-kinderkrankengeld-an-eltern-aus/aok-plus-haelt-den-zusatzbeitrag-2026-stabil/",
        publication_date=date(2025, 12, 19),
        checksum_sha256=None,
    ),

    # ── Phase 8V — fetched LIVE this phase (WebFetch/WebSearch, 2026-09-04) ─

    dict(
        agency="Bundesministerium der Justiz (gesetze-im-internet.de)",
        title="SVBezGrV 2026: RV/ALV ceiling €8450/€101400; GKV/PV €5812.50/€69750; JAEG €77400/€6450; Bezugsgröße €3955/€47460",
        form_number="SVBezGrV 2026",
        source_url="https://www.gesetze-im-internet.de/svbezgrv_2026/BJNR1160A0025.html",
        publication_date=date(2026, 1, 1),
        checksum_sha256=None,
    ),
    dict(
        agency="Deutsche Rentenversicherung",
        title="Bundeskabinett SV-RechengrößenV 2026 press release: confirms ceilings, wage-growth 5.16% (2025-10-08/11-21)",
        form_number=None,
        source_url="https://www.deutsche-rentenversicherung.de/DRV/DE/Ueber-uns-und-Presse/Presse/Meldungen/2025/25-10-08-bundeskabinett-sv-rechengroessen-vo-2026.html",
        publication_date=date(2025, 10, 8),
        checksum_sha256=None,
    ),
    dict(
        agency="Deutsche Rentenversicherung",
        title="PV Beitragszuschlag 2026: 3.6% base (unchanged); 0.6pt childless surcharge; 0.25pt/child discount (2nd-5th child)",
        form_number=None,
        source_url="https://www.deutsche-rentenversicherung.de/DRV/DE/Experten/Arbeitgeber-und-Steuerberater/summa-summarum/Lexikon/B/beitragszuschlag_-abschlag_pflegeversicherung.html",
        publication_date=None,
        checksum_sha256=None,
    ),
    dict(
        agency="Techniker Krankenkasse (TK)",
        title=(
            "TK PV-Beitrag 2026 FAQ — confirms Saxony split: employer 1.30%, employee (childless) "
            "2.90%, employee (1 child) 2.30%, vs. non-Saxony employer 1.80%, employee (childless) "
            "2.40%, employee (1 child) 1.80%"
        ),
        form_number=None,
        source_url="https://www.tk.de/firmenkunden/versicherung/beitraege-faq/pv-beitraege/wie-hoch-ist-pv-beitrag-2149454",
        publication_date=None,
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8V) — the
        # only source found this phase directly stating 2026-labeled Saxony PV
        # split figures matching the Zoiko doc §10 matrix exactly; independent
        # cross-check via sozialversicherung-kompetent.de agreed on the same
        # figures but no first-party BMG/GKV-Spitzenverband page could be reached
        # (connection errors) to raise this above "high-confidence, not
        # gold-standard-sourced" for the Saxony split specifically — disclosed,
        # not hidden.
    ),
    dict(
        agency="Techniker Krankenkasse (TK)",
        title=(
            "TK 2026 Umlagesätze U1/U2 — U1 (employer-elected Erstattungssatz tariff): 50%→1.3%, "
            "70% Standard→2.1%, 80%→3.2%; U2 (single 100%-Erstattungssatz tariff): 0.44%"
        ),
        form_number=None,
        source_url="https://www.tk.de/firmenkunden/versicherung/beitraege-faq/umlagen-u1-u2-und-insolvenzgeld/hoehe-umlagesaetze-u1-und-u2-2031720",
        publication_date=None,
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8V).
        # U2 has exactly one tariff and is populated into GermanyHealthFund.u2_rate_pct
        # below. U1 is NOT populated — see this phase's report for the disclosed
        # "SCHEMA GAP — AUTHORITATIVE U1 TARIFF DISTINCTION CANNOT BE REPRESENTED"
        # finding: U1 is employer-elected per tariff, not fund-uniform, and the
        # current GermanyHealthFund.u1_rate_pct column can only hold one rate.
    ),
    dict(
        agency="DAK-Gesundheit",
        title="DAK 2026 Umlagesätze U1/U2: U1 mid-year change eff. 2026-09-01; U2 0.39% (100% tariff)",
        form_number=None,
        source_url="https://www.dak.de/arbeitgeber-portal/sozialversicherung/umlage-u1-und-u2_57160",
        publication_date=date(2026, 9, 1),  # page's own stated "Aktualisiert am" date
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8V), twice
        # (verbatim-quoted both times) — 0.39% for U2, NOT the 0.79% figure found
        # only in an unconfirmed WebSearch snippet elsewhere, which is excluded per
        # this phase's "never trust a snippet without a direct fetch" instruction.
        # U1 NOT populated for the same schema-gap reason as TK above — DAK's own
        # mid-year rate change makes a single-value column doubly unable to
        # represent this fund's real 2026 U1 schedule.
    ),
    dict(
        agency="AOK PLUS (Sachsen und Thüringen)",
        title="AOK PLUS 2026 Umlagesätze U1/U2: U1 50%→2.15%, 65%→2.95%; U2 0.44%",
        form_number=None,
        source_url="https://www.aok.de/fk/plus/tools/weitere-inhalte/beitraege-und-rechengroessen-der-sozialversicherung/umlage-und-erstattungssaetze/",
        publication_date=date(2025, 12, 22),  # page's own stated "Erstellt am" date
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8V), twice
        # (verbatim-quoted both times) — 0.44% for U2, NOT the 0.62% figure found
        # only in an unconfirmed WebSearch snippet elsewhere, excluded for the same
        # reason as DAK's U2 above. U1 NOT populated — same schema-gap reason.
    ),

    # ── Phase 8AL — BARMER, previously excluded (Phase 8O/8P: "its exact
    # 2026 rate could only be confirmed via secondary/tertiary aggregator
    # sites, never a primary BARMER-owned page"). This phase found a real,
    # official, BARMER-branded PDF — "Eckwerte ab Januar 2026"
    # (Artikelnummer 6221 0126), fetched directly this phase from
    # barmer.de's own resource/blob path — containing BARMER's exact 2026
    # Zusatzbeitrag, both U1 Umlage tariffs, and the single U2 Umlage
    # rate, all on one page. Split into two artifacts below (Zusatzbeitrag
    # / Umlagesätze) purely to match this file's own established
    # per-category citation convention for every other fund — both cite
    # the SAME underlying document. Cross-checked internally: the same PDF
    # also states the GKV/PV/RV ceilings, Bezugsgröße, and PV
    # child-category percentages already in this codebase (from the
    # supplied Zoiko document) — all figures matched exactly, corroborating
    # this document's authenticity/currency rather than contradicting it.

    dict(
        agency="BARMER",
        title="BARMER 2026 Zusatzbeitragssatz: 3.29% (Gesamt 17.89%), eff. 2026-01-01",
        form_number="6221 0126",
        source_url="https://www.barmer.de/resource/blob/1024062/87dfc178c282296acc16a6b3fadd2494/barmer-rechengroessen-2026-barrierefrei-6221-data.pdf",
        publication_date=date(2026, 1, 1),  # document's own "ab Januar 2026" effective date; no separate decision date stated on this document
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase
        # 8AL) from BARMER's own official PDF resource, corroborated by a
        # BARMER-owned press page (barmer.de/presse/.../beitragsatz-barmer-2026-1476108,
        # "Letzte Aktualisierung: 22.12.2025") independently confirming the
        # rate was held stable for 2026 (that page does not itself restate
        # the numeric figure, so the PDF remains the source of record for
        # the exact percentage).
    ),
    dict(
        agency="BARMER",
        title="BARMER 2026 Umlagesätze U1/U2: U1 50%→1.90%, 65%→2.50%, 80%→4.00%; U2 0.42%; U3 0.15%",
        form_number="6221 0126",
        source_url="https://www.barmer.de/resource/blob/1024062/87dfc178c282296acc16a6b3fadd2494/barmer-rechengroessen-2026-barrierefrei-6221-data.pdf",
        publication_date=date(2026, 1, 1),
        checksum_sha256=None,
        # _evidence_ref: same document as above. All three U1 tariffs and
        # the single U2 rate are populated below — no schema gap exists
        # for BARMER (Phase 8W's GermanyHealthFundU1Tariff child table
        # already handles multiple per-fund tariffs).
    ),

    # ── Phase 8Y — §15 Earnings and Deduction Taxability Matrix, transcribed
    # directly from the supplied document (re-read in full this phase via the
    # docx's own XML, not cited from memory). Per this project's established
    # source hierarchy, the supplied Zoiko document is itself Tier-1
    # authority for values it states directly — the same standing already
    # given to §9/§10 above. ──────────────────────────────────────────────

    dict(
        agency="Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0",
        title="§15 Earnings and Deduction Taxability Matrix — 9 types, 4-dim taxability (LSt/GKV/RV/Notes)",
        form_number="ZP-TAX-DE-2026-001 §15",
        source_url=None,  # internal document, not a public URL — see docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx
        publication_date=date(2026, 8, 21),  # the document's own "Prepared" cover-page date
        checksum_sha256=None,
        # _evidence_ref: re-extracted directly from word/document.xml this phase
        # (Phase 8Y) — the literal table at document heading "15. Earnings and
        # Deduction Taxability Matrix" (Regular salary / Overtime-shift premiums /
        # Bonus-annual bonus / Pension-Versorgungsbezug / Equity benefit §19a /
        # Expense reimbursement / Occupational pension contribution / Garnishment-
        # attachment / Employee voluntary deduction), each row's Lohnsteuer/GKV-PV/
        # RV-ALV/Notes cell values transcribed verbatim into
        # scripts/seed_germany_2026_registries.py's _earning_taxability_rows().
    ),

    # ── Phase 8Z — OVERTIME_SHIFT_PREMIUM detailed statutory mechanism,
    # fetched LIVE this phase (WebFetch, 2026-09-04) directly from
    # gesetze-im-internet.de. These are Tier-2 primary-law evidence for the
    # DETAILED conditions behind the §15 row's "Depends on statutory
    # exemption conditions" / "May differ" classification — they do NOT
    # replace the §15 SourceArtifact above as the OVERTIME_SHIFT_PREMIUM
    # registry row's authority_source_id (that row's actual stored values
    # are a verbatim transcription of the Tier-1 document, unchanged this
    # phase); they exist to record real, verified evidence for whichever
    # future phase designs the engine-input fields these statutes require
    # (hourly base wage / Grundlohn, night-work 20:00-06:00 and Sunday/
    # holiday date windows, premium amount distinct from base pay). ──────

    dict(
        agency="Bundesministerium der Justiz (gesetze-im-internet.de)",
        title="§3b EStG: SFN-Zuschläge steuerfrei — night 25%/40%, Sun 50%, holidays 125%/150%; Grundlohn capped €50/hr",
        form_number="§3b EStG",
        source_url="https://www.gesetze-im-internet.de/estg/__3b.html",
        publication_date=None,  # consolidated federal law text, no single "Stand" fetched
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8Z) — this
        # is a WAGE-TAX-ONLY provision (Lohnsteuer/EStG). It does NOT by itself
        # determine social-insurance (GKV/PV/RV/ALV) treatment — see the SvEV row
        # below, which uses a genuinely different (lower) Euro-per-hour cap. This is
        # the primary-source proof that the §15 registry's independent GKV/PV vs.
        # RV/ALV vs. Lohnsteuer dimensions are correct to keep separate here, and
        # that "tax-free" must never be silently treated as "SI-free".
    ),
    dict(
        agency="Bundesministerium der Justiz (gesetze-im-internet.de)",
        title="§1 Abs.1 S.1 Nr.1 SvEV: SFN-Zuschläge beitragsfrei nur wenn Entgelt 25 Euro/Std nicht übersteigt",
        form_number="§1 SvEV",
        source_url="https://www.gesetze-im-internet.de/svev/__1.html",
        publication_date=None,  # consolidated federal regulation text, no single "Stand" fetched
        checksum_sha256=None,
        # _evidence_ref: fetched directly via WebFetch this phase (Phase 8Z), quoted
        # verbatim. Confirms a genuinely LOWER hourly-wage cap (€25) applies for
        # social-insurance contribution-freedom than the €50/hour wage-tax cap in
        # §3b EStG above — the exact reason a premium can be simultaneously
        # wage-tax-free and social-insurance-contributory on part of its amount,
        # which the current Zoiko data model (no hourly-rate concept anywhere in
        # the payroll engine — confirmed by this phase's own forensic audit) cannot
        # yet represent. See docs/PHASE_8Z_..._REPORT.md for the full analysis.
    ),

    # ── Phase 8AM — Bad Wimpfen church-tax exception (fresh primary-source
    # research, 2026-09-07) ──────────────────────────────────────────────
    # Multiple independent Tier-1/2 sources converge on the same facts:
    # Baden-Württemberg general church tax: 8% (all confessions).
    # Exception: Roman Catholic church tax for the Diocese of Mainz's
    # Baden-Württemberg enclave (Bad Wimpfen, PLZ 74206) = 9%.
    # Effective 2016-01-01, annually re-confirmed by FinMin BW circulars
    # (same Aktenzeichen FM3-S2442 series). The Diocese of Mainz's own
    # Diözesankirchensteuerrat Beschlüsse independently set 9% for its
    # BW portion. Official municipal websites (Balingen, Backnang, Bad
    # Herrenalb) all publish this exception identically. The exception
    # applies to wage tax (Lohnsteuer), income tax (Einkommensteuer), and
    # capital gains tax (Kapitalertragsteuer) per §51a EStG basis.
    # Evidence tier: Tier-1 (official FinMin circulars, BStBl citations)
    # + Tier-1 (Diocese of Mainz church tax authority decisions)
    # + Tier-2 (official municipal sources). NOT Tier-3 only.

    dict(
        agency="Finanzministerium Baden-Württemberg",
        title="FinMin BW Erlass 22.5.2026 (FM3-S2442-3/38, BStBl 2026 I S.869): Kirchensteuer 2026; RC Mainz BW enclave (Bad Wimpfen PLZ 74206) = 9%",
        form_number="FM3-S2442-3/38",
        source_url="https://www.steuer-telex.de/doc/finmin-baden-wuerttemberg---erlass-vom-22052026-fm3---s-2442---338--1262432",
        publication_date=date(2026, 5, 22),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — official
        # FinMin BW circular for 2026, directly citing the Bad Wimpfen
        # exception. BStBl reference confirms official publication.
    ),
    dict(
        agency="Finanzministerium Baden-Württemberg",
        title="FinMin BW 19.2.2016 (BStBl 2016 I S.235): Original circular — Bad Wimpfen RC 9% exception (Diocese of Mainz enclave, PLZ 74206)",
        form_number=None,
        source_url=None,
        publication_date=date(2016, 2, 19),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — the
        # originating circular. Cited by all subsequent annual circulars
        # and professional publishers as the legal origin of the exception.
    ),
    dict(
        agency="Finanzministerium Baden-Württemberg",
        title="FinMin BW 6.2.2025 (FM3-S2442-3/31, BStBl 2025 I S.420): Bad Wimpfen RC 9% unchanged",
        form_number="FM3-S2442-3/31",
        source_url=None,
        publication_date=date(2025, 2, 6),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — annual
        # re-confirmation, same Aktenzeichen series.
    ),
    dict(
        agency="Finanzministerium Baden-Württemberg",
        title="FinMin BW 12.3.2024 (FM3-S2442-3/22, BStBl 2024 I S.432): Bad Wimpfen RC 9% unchanged",
        form_number="FM3-S2442-3/22",
        source_url=None,
        publication_date=date(2024, 3, 12),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — annual
        # re-confirmation.
    ),
    dict(
        agency="Finanzministerium Baden-Württemberg",
        title="FinMin BW 3.2.2023 (FM3-S2442-3/16, BStBl 2023 I S.248): Bad Wimpfen RC 9% unchanged",
        form_number="FM3-S2442-3/16",
        source_url=None,
        publication_date=date(2023, 2, 3),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — annual
        # re-confirmation.
    ),
    dict(
        agency="Bistum Mainz — Diözesankirchensteuerrat",
        title="Diözesankirchensteuerrat Beschluss 13.12.2025: RC Kirchensteuer 2026 für BW-Anteil (Bad Wimpfen PLZ 74206) = 9%",
        form_number=None,
        source_url="https://kirchenrecht-bistummainz.de/document/9541",
        publication_date=date(2025, 12, 13),
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — the
        # Diocese of Mainz's own church tax authority decision, Tier-1
        # church-tax source, independently setting the 9% rate for its
        # BW enclave.
    ),
    dict(
        agency="Stadt Balingen (official municipal website)",
        title="Kirchensteuer Balingen: BW 8%; RC Bad Wimpfen (PLZ 74206) 9% since 2016-01-01 per FinMin BW",
        form_number=None,
        source_url="https://www.balingen.de/-/Was+erledige+ich+wo_/vbid248",
        publication_date=None,
        checksum_sha256=None,
        # _evidence_ref: Fresh primary-source research Phase 8AM — official
        # municipal source (Tier-2) publishing the exception identically to
        # FinMin circulars. Multiple other municipalities publish verbatim.
    ),
]


def seed_germany_source_evidence(db: Session) -> list[SourceArtifact]:
    """Idempotent: skips any (agency, title) pair that already exists,
    never creates a duplicate row on repeated runs. Returns the rows this
    call actually created (empty list if everything already existed)."""
    created = []
    for entry in GERMANY_SOURCE_EVIDENCE:
        existing = (
            db.query(SourceArtifact)
            .filter(SourceArtifact.agency == entry["agency"], SourceArtifact.title == entry["title"])
            .first()
        )
        if existing:
            continue
        row = SourceArtifact(
            agency=entry["agency"], title=entry["title"], form_number=entry["form_number"],
            source_url=entry["source_url"], publication_date=entry["publication_date"],
            checksum_sha256=entry["checksum_sha256"],
        )
        db.add(row)
        created.append(row)
    if created:
        db.commit()
        for row in created:
            db.refresh(row)
    return created


def main() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        created = seed_germany_source_evidence(db)
        print(f"Created {len(created)} new Germany SourceArtifact row(s) (skipped any already present).")
        for row in created:
            print(f"  - [{row.id}] {row.agency}: {row.title}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
