"""
scripts/generate_evidence_pack.py
---------------------------------
Build the ZP-PRIV evidence pack EP-01..EP-07 under
docs/privacy/evidence_pack/ (idempotent: every run rewrites the generated
files; hand-added files are left alone).

  EP-01 architecture and decision-point inventory (route registry)
  EP-02 effective roles, entitlements, service-account scopes, IAM / IaC pointers
  EP-03 negative-test evidence (tests/privacy/evidence/*.json)
  EP-04 support-access and break-glass records
  EP-05 audit samples, alert rules + drill, immutability configuration
  EP-06 CI gate, QA report template, defect register, build manifest
  EP-07 privacy and legal review pack

Every file is checked before it is written: no JWTs, bearer tokens,
passwords or secrets may appear (the build fails instead).

    python -m scripts.generate_evidence_pack [--build-number N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PACK = REPO / "docs" / "privacy" / "evidence_pack"
NEGATIVE = BACKEND / "tests" / "privacy" / "evidence"

_FORBIDDEN = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\"(password|secret|credential|signingSecret|access_token|refresh_token)\"\s*:\s*\"[^\"*\[]{6,}"),
    re.compile(r"\bzpmc_[A-Za-z0-9]{6,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{16,}|\bsk_live_[A-Za-z0-9]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class EvidenceLeak(RuntimeError):
    pass


def now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=str(REPO))
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def check_clean(text: str, where: str) -> None:
    for pattern in _FORBIDDEN:
        if pattern.search(text):
            raise EvidenceLeak(f"refusing to write evidence: {where} matches {pattern.pattern[:40]}...")


def _write(path: Path, payload) -> Path:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str) + "\n"
    check_clean(text, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _copy(src: Path, dst: Path) -> Path:
    check_clean(src.read_text(encoding="utf-8", errors="ignore"), str(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def _manifest(folder: Path, title: str, notes: list) -> dict:
    files = []
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and p.name not in ("manifest.json", "README.md")):
        files.append({"path": f.relative_to(folder).as_posix(),
                      "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    manifest = {"pack": folder.name, "title": title, "generatedAt": now_z(), "files": files, "notes": notes}
    _write(folder / "manifest.json", manifest)
    lines = [f"# {folder.name} - {title}", "", f"Generated {manifest['generatedAt']}. Status: awaiting independent review.",
             ""] + [f"- {n}" for n in notes] + ["", "Files (sha256 in manifest.json):", ""]
    lines += [f"- `{f['path']}`" for f in files]
    _write(folder / "README.md", "\n".join(lines) + "\n")
    return manifest


def ep01(out: Path) -> dict:
    registry = json.loads((BACKEND / "app" / "core" / "authz" / "route_registry.json").read_text(encoding="utf-8"))
    entries = registry["entries"]
    by_class: dict = {}
    for e in entries:
        by_class[e["data_class"]] = by_class.get(e["data_class"], 0) + 1
    platform = {"super_admin", "support_operator", "platform_security"}
    _write(out / "decision_point_summary.json", {
        "routes": len(entries), "byDataClass": by_class,
        "retired": sum(1 for e in entries if e["retired_reason"]),
        "overridden": sum(1 for e in entries if e["overridden"]),
        "workerRoutesReachableByPlatformRoles": [f"{e['method']} {e['path']}" for e in entries
                                                 if e["data_class"] == "worker" and platform & set(e["principals"])],
        "enforcement": "app/core/authz/policy.py install_route_policies: a policy dependency at index 0 of "
                       "every route; unregistered routes fail closed",
    })
    _copy(REPO / "docs" / "privacy" / "route_policy_inventory.csv", out / "route_policy_inventory.csv")
    return _manifest(out, "Architecture and decision-point inventory",
                     ["Generated from app/core/authz/route_registry.json (python -m app.core.authz.generate).",
                      "workerRoutesReachableByPlatformRoles must be empty."])


def ep02(out: Path) -> dict:
    from app.core.authz import fields, policy
    from app.modules.security import machine_clients

    _write(out / "role_matrix.json", {role: {dc: sorted(acts) for dc, acts in classes.items()}
                                      for role, classes in policy.MATRIX.items()})
    _write(out / "field_classes.json", {"classes": sorted(fields.FIELD_CLASSES),
                                        "defaultSupportFieldClasses": sorted(fields.DEFAULT_SUPPORT_FIELD_CLASSES),
                                        "maskedColumns": sorted(fields.MASKED_COLUMNS),
                                        "operatorRoles": sorted(fields.OPERATOR_ROLES)})
    scopes = getattr(machine_clients, "SCOPES", {})
    _write(out / "machine_client_scopes.json", {
        scope: {"routes": sorted(f"{m} {p}" for m, p in routes), "fieldClasses": sorted(classes)}
        for scope, (routes, classes) in scopes.items()})
    _write(out / "iam_and_iac.json", {
        "iac": ["deploy/security/iam_roles.tf", "deploy/security/backup_iam.tf", "deploy/security/anchor_bucket.tf",
                "deploy/security/pam_runbook.md"],
        "liveExports": "python -m scripts.privileged_inventory --output EP-02/privileged_inventory.json "
                       "(run by the platform security owner on the deployment)",
        "status": "awaiting infra owner (HP-01, HP-02)"})
    return _manifest(out, "Effective roles, entitlements, service accounts and IAM",
                     ["role_matrix.json is the PDP matrix in code.",
                      "privileged_inventory_format_sample.json / jml_reconciliation_sample.json are synthetic samples; "
                      "the live inventory export is a human proof."])


def ep03(out: Path) -> dict:
    target = out / "negative_tests"
    if target.exists():
        shutil.rmtree(target)
    copied = []
    for f in sorted(NEGATIVE.glob("*")) if NEGATIVE.exists() else []:
        if f.is_file():
            _copy(f, target / f.name)
            copied.append(f.name)
    tests = sorted({re.split(r"[_.]", n)[0] for n in copied if re.match(r"T\d\d", n)})
    return _manifest(out, "Negative-test evidence",
                     [f"{len(copied)} evidence files from tests/privacy/evidence (written by the test run).",
                      f"Test ids present: {', '.join(tests) or 'none - run the privacy suite first'}."])


def ep04(out: Path) -> dict:
    from app.config import settings

    target = out / "records"
    if target.exists():
        shutil.rmtree(target)
    for f in sorted(NEGATIVE.glob("*")) if NEGATIVE.exists() else []:
        if f.is_file() and re.match(r"(T0[6-8]|T12|D_break_glass|PG_support)", f.name):
            _copy(f, target / f.name)
    _write(out / "support_access_configuration.json", {
        "maxMinutes": settings.SUPPORT_ACCESS_MAX_MINUTES,
        "breakGlassMinutes": settings.SUPPORT_ACCESS_BREAK_GLASS_MINUTES,
        "allowedMinutes": settings.SUPPORT_ACCESS_ALLOWED_MINUTES,
        "approval": "DEC-6: 30-minute hard maximum approved by venu@zoikogroup.com on 2026-10-15"})
    return _manifest(out, "Support-access and break-glass records",
                     ["Synthetic grant, break-glass and review records from the test run.",
                      "Production support-access records are exported from the tenant Audit tab / security events."])


def ep05(out: Path) -> dict:
    from app.config import settings
    from app.core.audit_immutability import AUDIT_TABLES

    _copy(REPO / "docs" / "privacy" / "alert_rules.json", out / "alert_rules.json")
    for name in ("E02_tamper_detected.json", "PG_security_events_tamper.json", "T12_attribution_and_drill.json"):
        if (NEGATIVE / name).exists():
            _copy(NEGATIVE / name, out / "audit_samples" / name)
    for name in ("D03_log_sample_payroll_run.txt", "D04_sentry_sample.json"):
        if (NEGATIVE / name).exists():
            _copy(NEGATIVE / name, out / "redaction_samples" / name)
    _write(out / "immutability_configuration.json", {
        "appendOnlyTables": list(AUDIT_TABLES),
        "postgresTriggers": ["<table>_append_only (zoiko_reject_audit_mutation)",
                             "security_events_append_only (zoiko_security_event_guard: set-once row_hash, jsonb compare)"],
        "hashChain": "security_events.prev_hash -> row_hash; GET /api/super-admin/security-events/verify",
        "anchoring": "security_event_anchors + GcsRetentionSink (bucket from SECURITY_ANCHOR_BUCKET; HP-04)",
        "auditPurgeOnOrgHardDelete": settings.AUDIT_PURGE_ON_ORG_HARD_DELETE,
        "auditRetentionYears": settings.AUDIT_RETENTION_YEARS})
    return _manifest(out, "Audit samples, alert drill and immutability configuration",
                     ["alert_drill.json comes from python -m scripts.alert_drill (synthetic database).",
                      "A live drill (--live) on the deployment is a human proof."])


def ep06(out: Path, build_number: str) -> dict:
    workflow = (REPO / ".github" / "workflows" / "backend-deploy.yml").read_text(encoding="utf-8")
    m = re.search(r"\n  privacy-isolation:\n(.*?)(?=\n  [a-z][\w-]*:\n)", workflow, re.S)
    _write(out / "ci_privacy_gate.yml", ("  privacy-isolation:\n" + m.group(1) + "\n") if m
           else "# privacy-isolation job not found in backend-deploy.yml\n")
    _copy(REPO / "docs" / "privacy" / "defect_register.csv", out / "defect_register.csv")
    template = REPO / "docs" / "privacy" / "qa_report_template.md"
    if template.exists():
        _copy(template, out / "qa_report_template.md")
    req = (BACKEND / "requirements.txt").read_bytes()
    head = "unknown"
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        head = ",".join(ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads())
    except Exception:  # noqa: BLE001
        pass
    _write(out / "build_manifest.json", {"gitSha": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                                         "dirty": bool(git("status", "--porcelain")), "buildNumber": build_number,
                                         "python": sys.version.split()[0], "alembicHead": head,
                                         "requirementsSha256": hashlib.sha256(req).hexdigest(),
                                         "generatedAt": now_z()})
    return _manifest(out, "CI gate, QA report template, defect register and build manifest",
                     ["ci_privacy_gate.yml is the job that blocks deploys.",
                      "Branch protection making it required is a human proof (HP-10)."])


def ep07(out: Path) -> dict:
    docs = ["control_register.yaml", "indirect_paths_audit.md", "dpa_role_mapping.md", "region_policy.md",
            "incident_playbook.md", "tabletop_script.md", "tabletop_record_template.md", "evidence_index.md",
            "rls_runbook.md", "test_data_lineage.md", "independent_tester_handover.md"]
    present, missing = [], []
    for name in docs:
        src = REPO / "docs" / "privacy" / name
        if src.exists():
            _copy(src, out / name)
            present.append(name)
        else:
            missing.append(name)
    return _manifest(out, "Privacy and legal review pack",
                     [f"Included: {len(present)} documents.", f"Missing: {', '.join(missing) or 'none'}.",
                      "Counsel sign-off (F01) and the tabletop (F04) are human proofs."])


def build(build_number: str = "local", pack: Path = PACK) -> dict:
    builders = (("EP-01", ep01), ("EP-02", ep02), ("EP-03", ep03), ("EP-04", ep04), ("EP-05", ep05),
                ("EP-06", lambda p: ep06(p, build_number)), ("EP-07", ep07))
    out = {}
    for name, fn in builders:
        folder = pack / name
        folder.mkdir(parents=True, exist_ok=True)
        manifest = fn(folder)
        out[name] = {"path": folder.relative_to(REPO).as_posix(), "files": len(manifest["files"])}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the ZP-PRIV evidence pack EP-01..EP-07.")
    parser.add_argument("--build-number", default="local")
    args = parser.parse_args(argv)
    print(json.dumps(build(args.build_number), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
