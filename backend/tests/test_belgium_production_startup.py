"""Belgium (ZP-BE-ENG-001) Block H2b: the app starts with production-like settings and no Belgian setting.

A fresh interpreter (so nothing from this test session leaks in) boots the real app WITH its lifespan against a
throwaway SQLite file, ENVIRONMENT=production and every BE_* setting unset:

  * startup completes (create_all, startup guards, schedulers);
  * every /api/payroll/belgium route answers 404 (dormant), for a Belgian organisation's own admin;
  * the Super Admin Belgium console's read-only views load without error (no pack, nothing seeded);
  * no Belgian pack, registry row or payroll_be_* row exists after startup (nothing is seeded automatically).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

CHILD = r'''
import json, re, time
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app

out = {"settings": {k: getattr(settings, k) for k in ("BE_TENANT_ONBOARDING_ENABLED", "BE_CANARY_ORG_IDS",
       "BE_DEMO_PACKS_ENABLED", "BE_DEMO_ORG_IDS", "BE_IDENTIFIER_KEYRING", "BE_IDENTIFIER_FINGERPRINT_KEY")}}
with TestClient(app) as client:
    from app.core.security import hash_password
    from app.database import SessionLocal
    from app.modules.auth.models import User, UserRole
    from app.modules.auth.service import issue_access_token
    from app.modules.organizations.models import Organization

    db = SessionLocal()
    org = Organization(organization_name="Startup BE BV", organization_code="BESTART", is_active=True,
                       workspace_type="EVALUATION")
    db.add(org)
    db.flush()
    users = {}
    for key, role, org_id in (("SA", "super_admin", None), ("OA", "org_admin", org.id)):
        users[key] = User(email=f"{key.lower()}@startup.example", hashed_password=hash_password("Startup-Test-1!x"),
                          role=getattr(UserRole, role.upper()), organization_id=org_id, first_name=key,
                          last_name="Synthetic", is_active=True, is_verified=True)
        db.add(users[key])
    db.commit()
    headers = {k: {"Authorization": "Bearer " + issue_access_token(u, mfa_at=int(time.time()))}
               for k, u in users.items()}
    be_routes = sorted({(m, r.path) for r in app.routes if getattr(r, "path", "").startswith("/api/payroll/belgium")
                        for m in (getattr(r, "methods", None) or ()) if m != "HEAD"})
    out["beRoutes"] = len(be_routes)
    out["beStatuses"] = {}
    for method, path in be_routes:
        url = re.sub(r"\{[^}]+\}", "1", path)
        res = client.request(method, url, headers=headers["OA"], json={} if method != "GET" else None)
        out["beStatuses"][f"{method} {path}"] = res.status_code
        if res.status_code != 404:
            out.setdefault("why", {})[f"{method} {path}"] = res.text[:200]
    out["console"] = {}
    for path in ("/api/super-admin/compliance/belgium/packs", "/api/super-admin/compliance/belgium/decisions",
                 "/api/super-admin/compliance/belgium/joint-committees",
                 "/api/super-admin/compliance/belgium/readiness"):
        res = client.get(path, headers=headers["SA"])
        out["console"][path] = [res.status_code, res.text[:300]]
    from app.modules.payroll.models import JurisdictionPack
    from app.database import Base
    from sqlalchemy import inspect, text
    out["bePacks"] = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country.in_(("BE", "Belgium"))).count()
    names = [t for t in inspect(db.get_bind()).get_table_names()]
    out["beRows"] = sum(db.execute(text(f"select count(*) from {t}")).scalar() for t in names
                        if t.startswith("payroll_be_"))
    out["beTables"] = sum(1 for t in names if t.startswith("payroll_be_"))
    reg = [t for t in names if t == "jurisdiction_service_registry"]
    out["beRegistry"] = (db.execute(text("select count(*) from jurisdiction_service_registry where "
                                         "country in ('BE', 'Belgium')")).scalar() if reg else None)
    db.close()
print("STARTUP-RESULT " + json.dumps(out, default=str))
'''


def test_app_starts_with_no_belgian_settings_and_belgium_is_dormant(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BE_") and k not in ("ZP_TEST_POSTGRES_URL", "DATABASE_URL", "APP_ENV")}
    env.update({
        "PAYROLL_DATABASE_URL": f"sqlite:///{(tmp_path / 'startup.db').as_posix()}",   # never backend/.env's DB
        "ENVIRONMENT": "production", "DEBUG": "false",
        "ASSIST_SWEEP_ENABLED": "false", "TRIAL_SWEEP_ENABLED": "false",
        "SMTP_HOST": "", "SMTP_FROM_EMAIL": "", "ASSIST_SUPPORT_EMAIL": "",
        "ASSIST_MODEL_PROVIDER": "", "ASSIST_MODEL_BASE_URL": "", "ASSIST_MODEL_API_KEY": "",
    })
    done = subprocess.run([sys.executable, "-c", CHILD], cwd=BACKEND, env=env, capture_output=True, text=True,
                          timeout=600)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("STARTUP-RESULT ")), None)
    assert done.returncode == 0 and line, (done.stdout[-3000:], done.stderr[-5000:])
    out = json.loads(line[len("STARTUP-RESULT "):])
    assert out["settings"] == {"BE_TENANT_ONBOARDING_ENABLED": False, "BE_CANARY_ORG_IDS": "",
                               "BE_DEMO_PACKS_ENABLED": False, "BE_DEMO_ORG_IDS": "",
                               "BE_IDENTIFIER_KEYRING": "", "BE_IDENTIFIER_FINGERPRINT_KEY": ""}
    assert out["beRoutes"] >= 20
    assert set(out["beStatuses"].values()) == {404}, out.get("why")
    for path, (code, body) in out["console"].items():
        assert code == 200, (path, code, body)
    assert out["bePacks"] == 0 and out["beRows"] == 0 and out["beTables"] == 19
    assert out["beRegistry"] in (0, None)
