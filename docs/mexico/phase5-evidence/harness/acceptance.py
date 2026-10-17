"""Mexico Phase 5 browser check (plan §9): with the flag OFF (production
setting) the Super Admin Mexico workspace and its Readiness G1–G8 tab still
load, show the Phase 5 engine version / note, and the MX-PAYROLL-2026
activation readiness still lists the pack-bound golden gate as unmet.

Backend: uvicorn on the scratch SQLite DB built by
../../phase4-evidence/harness/setup_db.py, MX_TENANT_ONBOARDING_ENABLED=false.
Frontend: vite preview of the current build. Installed Chrome via Playwright.
"""
import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase5-evidence")
PASSWORD = "BrowserCheck!2026"
SA, ADMIN = "sa-a@mx.example.com", "admin@mxorg.example.com"
results, errors, responses = [], [], []


def token(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PASSWORD}).encode())
    return json.load(urllib.request.urlopen(req))


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def new_page(browser, who):
    tok = token(who)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(
        f"localStorage.setItem('zoiko_payroll_access', {json.dumps(tok['access_token'])});"
        f"localStorage.setItem('zoiko_payroll_refresh', {json.dumps(tok['refresh_token'])});"
        f"localStorage.setItem('zoiko_payroll_user', {json.dumps(json.dumps(tok['user']))});")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{who} pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"{who} console: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: responses.append((who, r.request.method, re.sub(r"^.*?/api/", "/api/", r.url),
                                                    r.status)) if r.status >= 400 else None)
    return page


def settle(page, ms=1500):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page, name):
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    s = new_page(browser, SA)
    s.goto(APP + "/super-admin/compliance/mexico", wait_until="networkidle")
    settle(s)
    text = s.inner_text("body")
    check("p5-1 Super Admin Mexico workspace loads", "MX-PAYROLL-2026" in text, text[:300])
    shot(s, "01_super_admin_workspace")

    s.get_by_text("MX-PAYROLL-2026").first.click()
    settle(s)
    s.get_by_text(re.compile("Readiness G1")).first.click()
    settle(s, 2500)
    text = s.inner_text("body")
    check("p5-2 Readiness G1–G8 tab loads with every gate", all(g in text for g in ("G1", "G4", "G8")), text[:400])
    check("p5-3 engine version is MX-ENGINE-2026.1, not available", "MX-ENGINE-2026.1" in text and
          re.search(r"Available:\s*No", text) is not None, text[:600])
    check("p5-4 note says the engine is not wired to runs and every calculation is BLOCKED",
          "not wired to payroll runs" in text and "BLOCKED" in text, text[:800])
    low = text.lower()
    check("p5-5 activation readiness lists pack-bound golden as unmet (no Mexico golden vector)",
          "pack-bound golden pass" in low and "no mexico golden vector" in low, text[:1500])
    shot(s, "02_readiness_gates")

    a = new_page(browser, ADMIN)
    a.goto(APP + "/payroll/compliances", wait_until="networkidle")
    settle(a)
    a.get_by_role("button", name="Mexico Compliance Centre", exact=True).first.click()
    settle(a)
    check("p5-6 org Mexico Compliance Centre still shows the dormancy message",
          "not open for onboarding" in a.inner_text("body"), a.inner_text("body")[:400])
    shot(a, "03_org_compliance_centre_dormant")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("p5-7 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico Phase 5 — browser check (flag OFF)", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {n} | {'PASS' if ok else 'FAIL — ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for n, ok, d in results]
lines += ["", "4xx/5xx responses seen: " + (", ".join(f"{m} {u} {c}" for _, m, u, c in responses) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
