"""
scripts/run_privacy_attestation.py
----------------------------------
ZP-PRIV Part 12 attestation run.

1. Runs the privacy suite (tests/privacy: T01-T12 and the control tests)
   unless --skip-tests.
2. Stamps the git SHA and build number.
3. Regenerates the evidence pack EP-01..EP-07.
4. Counts P0 (41) and P1 (5) controls by status from
   docs/privacy/control_register.yaml plus recorded reviews.
5. Writes an immutable attestation record (a new file per run; existing
   records are never overwritten) and prints the verdict.

The verdict is BLOCKED or NOT VERIFIED. It can never be VERIFIED unless
every control carries an accepted review by a NAMED human reviewer and the
register names the independent reviewer - and even then this script
re-checks that condition itself before printing it.

    python -m scripts.run_privacy_attestation [--skip-tests] [--build-number N]

Exit code: 1 when BLOCKED, otherwise 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
ATTESTATIONS = REPO / "docs" / "privacy" / "evidence_pack" / "attestations"


def run_privacy_tests(junit: Path) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/privacy", f"--junitxml={junit}"]
    proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "exitCode": proc.returncode}
    if junit.exists():
        root = ET.parse(junit).getroot()
        suites = [root] if root.tag == "testsuite" else list(root)
        for s in suites:
            for k in ("tests", "failures", "errors", "skipped"):
                totals[k] += int(s.get(k, 0))
    elif proc.returncode != 0:
        totals["errors"] = 1
    return totals


def attest(*, skip_tests: bool, build_number: str, db_reviews: bool = False) -> dict:
    from app.modules.security import assurance
    from scripts.generate_evidence_pack import build as build_pack
    from scripts.generate_evidence_pack import check_clean, git, now_z

    tests = {"skipped": "not run (--skip-tests)"} if skip_tests else run_privacy_tests(
        BACKEND / ".privacy_attestation_junit.xml")
    failures = 0 if skip_tests else int(tests["failures"]) + int(tests["errors"])
    register = assurance.load_register()
    reviews = assurance._register_reviews(register)
    if db_reviews:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            reviews += assurance.db_reviews(db)
        finally:
            db.close()
    result = assurance.compute_verdict(register, reviews, assurance.open_blocking_defects(), test_failures=failures)
    if skip_tests:
        result["reasons"].append("privacy tests were not run in this attestation (--skip-tests)")
        if result["verdict"] == assurance.VERDICT_VERIFIED:
            result["verdict"] = assurance.VERDICT_NOT_VERIFIED
    # F07: a change to any privacy path since the reviewed commit invalidates
    # the prior attestation.
    reviewed_sha = (register.get("attestation") or {}).get("reviewed_git_sha")
    if reviewed_sha:
        changed = assurance.changed_privacy_paths(reviewed_sha)
        if changed is None or changed:
            result["reasons"].append(
                f"prior attestation invalidated: {'cannot diff against ' + reviewed_sha if changed is None else str(len(changed)) + ' privacy-path file(s) changed since ' + reviewed_sha[:12]}")
            if result["verdict"] == assurance.VERDICT_VERIFIED:
                result["verdict"] = assurance.VERDICT_NOT_VERIFIED
    elif result["verdict"] == assurance.VERDICT_VERIFIED:
        result["reasons"].append("no reviewed_git_sha recorded with the independent review")
        result["verdict"] = assurance.VERDICT_NOT_VERIFIED
    # Belt and braces: VERIFIED needs a named reviewer on every control and
    # on the register; anything less is NOT VERIFIED.
    reviewer = (register.get("attestation") or {}).get("independent_reviewer")
    named = all(r.get("reviewer") and r.get("decision") == "accepted" for r in result["latestReviews"].values())
    if result["verdict"] == assurance.VERDICT_VERIFIED and not (
            reviewer and named and len(result["latestReviews"]) == result["total"]):
        result["verdict"] = assurance.VERDICT_NOT_VERIFIED
    pack = build_pack(build_number)
    record = {
        "checklist": "ZP-PRIV-VERIFY-001", "verdict": result["verdict"], "reasons": result["reasons"],
        "gitSha": git("rev-parse", "HEAD"), "workingTreeDirty": bool(git("status", "--porcelain")),
        "buildNumber": build_number, "ranAt": now_z(), "tests": tests,
        "controls": {"total": result["total"], "P0": result["p0"], "P1": result["p1"], "reviewed": result["reviewed"]},
        "independentReviewer": reviewer, "evidencePack": pack,
    }
    text = json.dumps(record, indent=2) + "\n"
    check_clean(text, "attestation record")
    record_sha = hashlib.sha256(text.encode()).hexdigest()
    ATTESTATIONS.mkdir(parents=True, exist_ok=True)
    name = f"attestation-{record['ranAt'].replace(':', '')}-{record['gitSha'][:12]}.json"
    path = ATTESTATIONS / name
    with open(path, "x", encoding="utf-8") as fh:  # never overwrite a past record
        fh.write(text)
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass
    record["recordPath"] = path.relative_to(REPO).as_posix()
    record["recordSha256"] = record_sha
    return record


def _print(record: dict) -> None:
    c = record["controls"]

    def fmt(group):
        return (f"ENGINEERING_COMPLETE_AWAITING_REVIEW={group['ENGINEERING_COMPLETE_AWAITING_REVIEW']} "
                f"NT={group['NT']} FAIL={group['FAIL']} REVIEWED_ACCEPTED={group['REVIEWED_ACCEPTED']}")

    print("=" * 78)
    print(f"ZP-PRIV-VERIFY-001 attestation    verdict: {record['verdict']}")
    print(f"build {record['buildNumber']}  git {record['gitSha']}{' (dirty tree)' if record['workingTreeDirty'] else ''}")
    t = record["tests"]
    if "tests" in t:
        print(f"privacy tests: {t['tests']} run, {t['failures']} failed, {t['errors']} errors, {t['skipped']} skipped")
    else:
        print(f"privacy tests: {t['skipped']}")
    print(f"P0 ({sum(c['P0'].values())}): {fmt(c['P0'])}")
    print(f"P1 ({sum(c['P1'].values())}): {fmt(c['P1'])}")
    print(f"independent reviewer: {record['independentReviewer'] or 'none recorded'}")
    for reason in record["reasons"]:
        print(f"  - {reason}")
    print("evidence pack:")
    for name, info in record["evidencePack"].items():
        print(f"  {name}: {info['path']} ({info['files']} files)")
    print(f"record: {record['recordPath']} sha256={record['recordSha256'][:16]}...")
    print("=" * 78)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the ZP-PRIV attestation.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--build-number", default=os.environ.get("GITHUB_RUN_NUMBER", "local"))
    parser.add_argument("--with-db-reviews", action="store_true",
                        help="also read reviews recorded on the Privacy Assurance page (configured database)")
    args = parser.parse_args(argv)
    record = attest(skip_tests=args.skip_tests, build_number=args.build_number, db_reviews=args.with_db_reviews)
    _print(record)
    return 1 if record["verdict"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
