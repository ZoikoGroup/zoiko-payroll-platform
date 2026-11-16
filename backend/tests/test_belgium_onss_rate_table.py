"""Belgium (ZP-BE-ENG-001) Block M-ECWC: the ONSS rate table.

SYNTHETIC data only: rates are made-up numbers (never the archived ONSS figures); the code SHAPES are the real ones
confirmed by the importer fix (employer category "000", worker codes "015" / "495", closure fund "809" with types
0 / 2 / 4 / 5). Covers: a signed (attested) file with an unsigned row blocks; a missing employer fact or evidence
blocks; ContributionType resolution for 809 across closure-fund sector x workforce x wage moderation; the service
lifecycle with four-eyes at every step; codes stay text; REFERENCE rows never reach the engine."""
import hashlib
import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException

PAY_DAY = date(2026, 8, 31)
REGISTRAR, ATTESTER, MARKER, SIGNER = 801, 802, 803, 804
RND = lambda v: Decimal(v).quantize(Decimal("0.01"))                                # noqa: E731

# 809 rules shaped like DmfA glossary annex 3 (synthetic content for the test, signed by a second person)
RULES_809 = [
    {"code": "809", "closureFundSector": "COMMERCIAL", "wageModeration": "APPLIES",
     "workforceClass": "UNDER_10,FROM_10_TO_19", "outcome": "0"},
    {"code": "809", "closureFundSector": "COMMERCIAL", "wageModeration": "APPLIES", "workforceClass": "FROM_20",
     "outcome": "5"},
    {"code": "809", "closureFundSector": "COMMERCIAL", "wageModeration": "NOT_APPLICABLE",
     "workforceClass": "UNDER_10,FROM_10_TO_19", "outcome": "2"},
    {"code": "809", "closureFundSector": "COMMERCIAL", "wageModeration": "NOT_APPLICABLE", "workforceClass": "FROM_20",
     "outcome": "4"},
    {"code": "809", "closureFundSector": "NON_COMMERCIAL,NOT_SUBJECT", "outcome": "NOT_DUE"},
]
RULES_WORKER = [{"code": "015", "payBasis": "PAY_108", "outcome": "1"},
                {"code": "495", "payBasis": "PAY_100", "outcome": "0"}]
# synthetic rates (personal, employer, moderation) per (code, type)
SYNTH = {("015", "1"): ("1.11", "2.22", "0.33"), ("495", "0"): ("1.11", "3.33", "0.44"),
         ("809", "0"): ("0.00", "0.10", "0.01"), ("809", "2"): ("0.00", "0.20", "0.00"),
         ("809", "4"): ("0.00", "0.40", "0.00"), ("809", "5"): ("0.00", "0.50", "0.02")}


# ── pure engine ───────────────────────────────────────────────────────────────
def _pack():
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    return BePack({}, [], 1, PAY_DAY)


def _rule(r, status="SIGNED"):
    return {"id": None, "payBasis": "ANY", "closureFundSector": "ANY", "workforceClass": "ANY",
            "wageModeration": "ANY", "effectiveFrom": "2026-01-01", "effectiveTo": None, "status": status, **r}


def _table(rate_status="SIGNED", attested=True, comb_status="SIGNED", rules=None):
    rates = [{"id": i, "employerClass": "000", "codeKind": "CONTRIBUTION", "code": code, "contributionType": t,
              "personalRate": p, "employerRate": e, "moderationRate": m, "totalRate": None, "isFlat": False,
              "minimumFlat": None, "status": rate_status}
             for i, ((code, t), (p, e, m)) in enumerate(SYNTH.items(), start=1)]
    combs = [{"id": i, "employerClass": "000", "workerCode": wc, "contributionCode": "809", "status": comb_status}
             for i, wc in enumerate(("015", "495"), start=1)]
    return {"quarter": "20263", "effectiveFrom": "2026-07-01", "effectiveTo": "2026-09-30", "fileId": 1,
            "fileAttested": attested, "rates": rates, "combinations": combs,
            "typeRules": [_rule(r) for r in (rules if rules is not None else RULES_809 + RULES_WORKER)]}


def _decision(manual=False, sector="COMMERCIAL", workforce="UNDER_10", moderation="APPLIES", evidence=True):
    return {"worker": {"onssManualBase": manual, "workerCode": "015" if manual else "495"},
            "employer": {"employerCategory": "000", "closureFundSector": sector, "workforceClass": workforce,
                         "wageModerationStatus": moderation, "closureFundSectorEvidence": evidence,
                         "workforceClassEvidence": evidence, "wageModerationEvidence": evidence}}


def _compute(table, decision, base="1000"):
    from app.modules.payroll.engine.jurisdictions.belgium.onss_table import be_onss_table_compute

    # the facts reach the rate table separately (never through the applicability decision: replay hashes)
    return be_onss_table_compute(_pack(), table, decision, decision["employer"], Decimal(base), RND)


def test_the_facts_are_read_from_the_registration_and_stay_out_of_the_decision():
    from app.modules.payroll.engine.jurisdictions.belgium.applicability import _employer
    from app.modules.payroll.engine.jurisdictions.belgium.onss_table import be_onss_registration_facts

    registration = {"closure_fund_sector": "commercial", "closure_fund_sector_evidence_ref": "doc",
                    "workforce_class": "FROM_20", "workforce_class_evidence_ref": None,
                    "wage_moderation_status": None, "wage_moderation_evidence_ref": None}
    assert be_onss_registration_facts(registration) == {
        "closureFundSector": "COMMERCIAL", "closureFundSectorEvidence": True, "workforceClass": "FROM_20",
        "workforceClassEvidence": False, "wageModerationStatus": "UNKNOWN", "wageModerationEvidence": False}
    import inspect

    source = inspect.getsource(_employer)                     # the decision (and so every input hash) is unchanged
    assert "closure_fund_sector" not in source and "workforce_class" not in source


def _blocked(table, decision):
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    with pytest.raises(BECalculationBlockedError) as caught:
        _compute(table, decision)
    return caught.value.key


def test_a_signed_file_does_not_sign_its_rows_an_unsigned_row_blocks():
    assert _blocked(_table(rate_status="PENDING", attested=True), _decision()).startswith("BE_ONSS_RATE_UNSIGNED:")


def test_a_signed_row_in_an_unattested_file_blocks():
    assert _blocked(_table(attested=False), _decision()).startswith("BE_ONSS_RATE_FILE_UNATTESTED:")


def test_an_unsigned_combination_in_use_blocks():
    assert _blocked(_table(comb_status="PENDING"), _decision()).startswith("BE_ONSS_RATE_UNSIGNED:combination")


@pytest.mark.parametrize("fact", ["sector", "workforce", "moderation"])
def test_a_missing_employer_fact_blocks(fact):
    assert _blocked(_table(), _decision(**{fact: "UNKNOWN"})).startswith("BE_ONSS_FACT_MISSING:")


def test_a_fact_without_its_evidence_blocks_like_a_missing_value():
    assert _blocked(_table(), _decision(evidence=False)).startswith("BE_ONSS_FACT_MISSING:")


@pytest.mark.parametrize("sector,workforce,moderation,expected", [
    ("COMMERCIAL", "UNDER_10", "APPLIES", "0"), ("COMMERCIAL", "FROM_10_TO_19", "APPLIES", "0"),
    ("COMMERCIAL", "FROM_20", "APPLIES", "5"), ("COMMERCIAL", "UNDER_10", "NOT_APPLICABLE", "2"),
    ("COMMERCIAL", "FROM_20", "NOT_APPLICABLE", "4"), ("NON_COMMERCIAL", "FROM_20", "APPLIES", None),
    ("NOT_SUBJECT", "UNDER_10", "APPLIES", None)])
def test_the_closure_fund_809_type_follows_sector_workforce_and_moderation(sector, workforce, moderation, expected):
    out = _compute(_table(), _decision(sector=sector, workforce=workforce, moderation=moderation))
    assert out["types"]["809"] == expected
    if expected is None:                                              # NOT_DUE: no closure-fund line at all
        assert "CODE_809" not in out["funds"]
    else:
        employer = Decimal(SYNTH[("809", expected)][1])
        assert out["funds"]["CODE_809"] == RND(Decimal("1000") * employer / 100)


def test_the_base_follows_the_worker_pay_basis_and_adds_the_combined_moderation():
    white = _compute(_table(), _decision(manual=False))
    manual = _compute(_table(), _decision(manual=True))
    assert (white["types"]["495"], manual["types"]["015"]) == ("0", "1")
    assert white["lines"]["BASE"] == Decimal("33.30") and manual["lines"]["BASE"] == Decimal("22.20")
    assert white["lines"]["WAGE_MODERATION"] == Decimal("4.40") + Decimal("0.10")   # base 0.44 % + 809 type 0 0.01 %


def test_no_rule_an_ambiguous_rule_or_a_pending_rule_blocks():
    no_rule = [r for r in RULES_809 + RULES_WORKER if r["code"] != "809"]
    assert _blocked(_table(rules=no_rule), _decision()).startswith("BE_ONSS_TYPE_UNRESOLVED:809")
    clash = RULES_809 + RULES_WORKER + [{"code": "809", "closureFundSector": "COMMERCIAL", "outcome": "4"}]
    assert _blocked(_table(rules=clash), _decision()).startswith("BE_ONSS_TYPE_AMBIGUOUS:809")
    table = _table()
    table["typeRules"] = [dict(r, status="PENDING") if r["code"] == "809" else r for r in table["typeRules"]]
    assert _blocked(table, _decision()).startswith("BE_ONSS_RATE_UNSIGNED:type_rule:809")


def test_flat_rates_and_quarterly_minimums_block():
    table = _table()
    next(r for r in table["rates"] if r["code"] == "495")["minimumFlat"] = "1.00"
    assert _blocked(table, _decision()).startswith("BE_ONSS_RATE_FLAT_UNSUPPORTED:")


def test_no_table_or_a_table_of_another_quarter_blocks():
    assert _blocked(None, _decision()).startswith("BE_ONSS_RATE_TABLE_MISSING:")
    table = _table()
    table["effectiveFrom"], table["effectiveTo"] = "2026-10-01", "2026-12-31"
    assert _blocked(table, _decision()).startswith("BE_ONSS_RATE_TABLE_MISSING:")


# ── service lifecycle (database) ──────────────────────────────────────────────
def _xml_rates(quarter="20263"):
    body = "".join(
        f"<ContributionRate><EmployerClass>000</EmployerClass><ContributionWorkerCode>{code}</ContributionWorkerCode>"
        f"<ContributionType>{t}</ContributionType><PersonalRate>{p}</PersonalRate><EmployerRate>{e}</EmployerRate>"
        f"<SalaryModerationRate>{m}</SalaryModerationRate><TotalRate>0</TotalRate><IsFlatRate>false</IsFlatRate>"
        f"</ContributionRate>" for (code, t), (p, e, m) in SYNTH.items())
    body += ("<ContributionRate><EmployerClass>001</EmployerClass><ContributionWorkerCode>027</ContributionWorkerCode>"
             "<ContributionType>1</ContributionType><PersonalRate>9.99</PersonalRate><EmployerRate>9.99</EmployerRate>"
             "<SalaryModerationRate>0</SalaryModerationRate><TotalRate>0</TotalRate><IsFlatRate>false</IsFlatRate>"
             "</ContributionRate>")                                     # a reference-only record
    return (f'<?xml version="1.0" encoding="UTF-8"?><ContributionRateFile><Header><FileType>NOSSContributionRate'
            f"</FileType><Quarter>{quarter}</Quarter><FormCreationDate>2026-09-15</FormCreationDate>"
            f"<FormCreationHour>11:11:31.198</FormCreationHour></Header>{body}</ContributionRateFile>").encode()


def _xml_comb(quarter="20263"):
    body = "".join(f"<WorkerAndContributionComb><EmployerClass>000</EmployerClass><WorkerCode>{wc}</WorkerCode>"
                   f"<ContributionWorkerCode>{cc}</ContributionWorkerCode><OwednessCode>0</OwednessCode>"
                   f"</WorkerAndContributionComb>" for wc in ("015", "495") for cc in ("809", "863"))
    return (f'<?xml version="1.0" encoding="UTF-8"?><WorKerAndContributionCombFile><Header><FileType>'
            f"NOSSWorkerAndContributionComb</FileType><Quarter>{quarter}</Quarter><FormCreationDate>2026-09-15"
            f"</FormCreationDate><FormCreationHour>11:16:50.024</FormCreationHour></Header>{body}"
            f"</WorKerAndContributionCombFile>").encode()


def _zip(quarter="20263") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(f"NOSSContributionRate_TEST_{quarter}.xml", _xml_rates(quarter))
        z.writestr(f"NOSSWorkerAndContributionComb_TEST_{quarter}.xml", _xml_comb(quarter))
    return out.getvalue()


@pytest.fixture
def seeded_be(db):
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_belgium_canonical_packs import seed_belgium

    pack = seed_belgium(db)["pack"]
    rows = {r.component_key: r for r in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id)}
    rows["be_onss_supported_employer_categories"].text_value = "000"                 # the code lists (text)
    rows["be_onss_supported_worker_codes"].text_value = "015,495"
    db.commit()
    return pack


def _archived_source(db, tmp_path, data: bytes):
    from app.modules.payroll.models import SourceArtifact

    path = tmp_path / "dmfa_rate_TEST.zip"
    path.write_bytes(data)
    src = SourceArtifact(agency="Synthetic", title="SYNTHETIC TEST ONLY rate file", form_number="SYN-RATE-1",
                         checksum_sha256=hashlib.sha256(data).hexdigest(), file_path=str(path))
    db.add(src)
    db.commit()
    return src


def _register(db, pack, src):
    from app.modules.payroll import belgium_onss_rates as r

    return r.be_onss_register_rate_file(db, pack.id, {"sourceDocumentId": src.id, "effectiveFrom": "2026-07-01",
                                                      "effectiveTo": "2026-09-30", "reason": "TEST ONLY"}, REGISTRAR)


def test_register_loads_everything_as_reference_and_codes_stay_text(db, seeded_be, tmp_path):
    from app.modules.payroll import belgium_onss_rates as r
    from app.modules.payroll.models import PayrollBeOnssCodeCombination, PayrollBeOnssRate

    f = _register(db, seeded_be, _archived_source(db, tmp_path, _zip()))
    db.commit()
    rows = db.query(PayrollBeOnssRate).filter_by(rate_file_id=f.id).all()
    assert f.quarter == "20263" and f.reference_rows == len(rows) == len(SYNTH) + 1
    assert {row.status for row in rows} == {"REFERENCE"}
    assert {row.employer_class for row in rows} == {"000", "001"}                     # leading zeros kept
    assert {row.code for row in rows} >= {"015", "495", "809", "027"}
    assert {c.worker_code for c in db.query(PayrollBeOnssCodeCombination).filter_by(rate_file_id=f.id)} == {"015",
                                                                                                           "495"}
    table = r.be_onss_rate_table_input(db, seeded_be.id, PAY_DAY)
    assert table["rates"] == [] and table["combinations"] == [] and table["fileAttested"] is False   # nothing live


def test_the_full_lifecycle_with_four_eyes_feeds_the_engine(db, seeded_be, tmp_path):
    from app.modules.payroll import belgium_onss_rates as r
    from app.modules.payroll.models import PayrollBeOnssCodeCombination, PayrollBeOnssRate

    f = _register(db, seeded_be, _archived_source(db, tmp_path, _zip()))
    with pytest.raises(BadRequestException):
        r.be_onss_attest_rate_file(db, f.id, "TEST ONLY", REGISTRAR)                # the registrar cannot attest
    r.be_onss_attest_rate_file(db, f.id, "TEST ONLY: genuine ONSS publication", ATTESTER)
    with pytest.raises(BadRequestException):                                         # 027 is not a supported code
        r.be_onss_mark_live(db, f.id, {"employerClasses": ["000"], "workerCodes": ["027"], "reason": "x"}, MARKER)
    with pytest.raises(BadRequestException):                                         # 863 not in this test's use
        r.be_onss_mark_live(db, f.id, {"employerClasses": ["000"], "workerCodes": ["015", "495"],
                                       "contributionCodes": ["999"], "reason": "x"}, MARKER)
    out = r.be_onss_mark_live(db, f.id, {"employerClasses": ["000"], "workerCodes": ["015", "495"],
                                         "contributionCodes": ["809"], "reason": "TEST ONLY"}, MARKER)
    assert out == {"rates": len(SYNTH), "combinations": 2}                           # 863 / 001 stay REFERENCE
    live = db.query(PayrollBeOnssRate).filter(PayrollBeOnssRate.rate_file_id == f.id,
                                              PayrollBeOnssRate.status == "PENDING").all()
    for actor in (MARKER, REGISTRAR):                                                # neither may sign
        with pytest.raises(BadRequestException):
            r.be_onss_sign_rate(db, live[0].id, "TEST ONLY", actor)
    for row in live:
        r.be_onss_sign_rate(db, row.id, "TEST ONLY", SIGNER)
    for comb in db.query(PayrollBeOnssCodeCombination).filter_by(rate_file_id=f.id, status="PENDING"):
        r.be_onss_sign_combination(db, comb.id, "TEST ONLY", SIGNER)
    for rule in RULES_809 + RULES_WORKER:
        added = r.be_onss_add_type_rule(db, seeded_be.id, {**rule, "effectiveFrom": "2026-01-01",
                                                          "reason": "TEST ONLY"}, MARKER)
        with pytest.raises(BadRequestException):
            r.be_onss_sign_type_rule(db, added.id, "TEST ONLY", MARKER)              # the author cannot sign
        r.be_onss_sign_type_rule(db, added.id, "TEST ONLY", SIGNER)
    db.commit()
    table = r.be_onss_rate_table_input(db, seeded_be.id, PAY_DAY)
    assert table["fileAttested"] is True and {x["status"] for x in table["rates"]} == {"SIGNED"}
    assert all(x["code"] != "027" for x in table["rates"])                           # REFERENCE never included
    result = _compute(table, _decision(sector="COMMERCIAL", workforce="FROM_20", moderation="NOT_APPLICABLE"))
    assert result["types"] == {"495": "0", "809": "4"}
    assert result["funds"] == {"CODE_809": Decimal("4.00")}


def test_a_file_whose_archive_changed_cannot_be_attested(db, seeded_be, tmp_path):
    from app.modules.payroll import belgium_onss_rates as r

    src = _archived_source(db, tmp_path, _zip())
    f = _register(db, seeded_be, src)
    (tmp_path / "dmfa_rate_TEST.zip").write_bytes(_zip() + b"tampered")
    with pytest.raises(BadRequestException):
        r.be_onss_attest_rate_file(db, f.id, "TEST ONLY", ATTESTER)


def test_an_unarchived_source_or_a_second_file_for_the_quarter_is_refused(db, seeded_be, tmp_path):
    from app.modules.payroll import belgium_onss_rates as r
    from app.modules.payroll.models import SourceArtifact

    loose = SourceArtifact(agency="Synthetic", title="not archived", form_number="SYN-LOOSE")
    db.add(loose)
    db.commit()
    with pytest.raises(BadRequestException):
        r.be_onss_register_rate_file(db, seeded_be.id, {"sourceDocumentId": loose.id, "effectiveFrom": "2026-07-01",
                                                        "effectiveTo": "2026-09-30", "reason": "x"}, REGISTRAR)
    src = _archived_source(db, tmp_path, _zip())
    _register(db, seeded_be, src)
    with pytest.raises(BadRequestException):
        _register(db, seeded_be, src)


def test_type_rule_validation(db, seeded_be):
    from app.modules.payroll import belgium_onss_rates as r

    for bad in ({"code": "80", "outcome": "0"}, {"code": "809", "outcome": "12"},
                {"code": "809", "outcome": "0", "workforceClass": "UNKNOWN"},
                {"code": "809", "outcome": "0", "closureFundSector": "SOMETIMES"}):
        with pytest.raises(BadRequestException):
            r.be_onss_add_type_rule(db, seeded_be.id, {**bad, "effectiveFrom": "2026-01-01", "reason": "x"}, MARKER)


# ── employer facts on the registration ────────────────────────────────────────
def test_an_employer_fact_needs_its_evidence_reference(db):
    from app.modules.payroll import belgium_service as be
    from tests._mx_employer_helpers import make_org

    org = make_org(db, name="Facts BV", code="BEFACT", admins=1, country="BE").org
    base = {"effective_from": "2026-01-01", "legal_name": "Facts BV", "enterprise_number": "0999999999"}
    for fact, evidence, value in (("closure_fund_sector", "closure_fund_sector_evidence_ref", "COMMERCIAL"),
                                  ("workforce_class", "workforce_class_evidence_ref", "FROM_20"),
                                  ("wage_moderation_status", "wage_moderation_evidence_ref", "APPLIES")):
        with pytest.raises(BadRequestException):
            be.record_be_employer_registration(db, org.id, {**base, fact: value}, REGISTRAR, "TEST ONLY")
        row = be.record_be_employer_registration(db, org.id, {**base, fact: value, evidence: "TEST ONLY doc"},
                                                 REGISTRAR, "TEST ONLY")
        assert getattr(row, fact) == value
        db.rollback()
    with pytest.raises(BadRequestException):
        be.record_be_employer_registration(db, org.id, {**base, "workforce_class": "HUGE"}, REGISTRAR, "TEST ONLY")


def test_the_rate_table_is_frozen_with_the_payslip_for_replay():
    from app.modules.payroll import belgium_service as be

    assert "be_onss_rate_table" in be._BE_CTX_PLAIN
