"""Mexico Phase 6 browser acceptance (installed Chrome, vite preview of the
current build, scratch SQLite backend from setup_db.py via serve.py).

Usage: python acceptance.py on|off — must match how serve.py was started.
Screenshots + RESULTS-<mode>.md go to docs/mexico/phase6-evidence/.
The only database write outside the UI/API is step on-7 (a synthetic change
to the ACTIVE risk premium of the scratch DB, to show approval invalidation)."""
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

MODE = sys.argv[1]
assert MODE in ("on", "off")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase6-evidence")
DB = Path(r"C:\Users\Nikhi\AppData\Local\Temp\claude\d--zoiko-payroll-platform\4310d3e7-cd06-425b-899e-67cfb66b19b8"
          r"\scratchpad\p6browser\mx_p6d.db")
PASSWORD = "BrowserCheck!2026"
A0, A1, SA, NL = "admin0@mx6.example.com", "admin1@mx6.example.com", "sa-a@mx6.example.com", "admin@nl6.example.com"
results, errors, responses = [], [], []


def token(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PASSWORD}).encode())
    return json.load(urllib.request.urlopen(req))


def api(email, method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token(email)['access_token']}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


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


def shot(page, name, locator=None):
    """Full page, or — inside the run drawer, which scrolls on its own — the
    element itself (Playwright scrolls it into view and captures it whole)."""
    page.wait_for_timeout(500)
    if locator is not None and locator.count():
        locator.first.screenshot(path=str(OUT / f"{MODE}_{name}.png"))
    else:
        page.screenshot(path=str(OUT / f"{MODE}_{name}.png"), full_page=True)


def open_run(page):
    page.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
    settle(page)
    page.get_by_text("Jun 1-15, 2026").first.click()
    settle(page, 2500)


def body(page):
    return page.inner_text("body")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "on":
        a = new_page(browser, A0)
        open_run(a)
        pre = a.locator('[data-testid="mx-run-preflight"]')
        check("on-1 run detail shows the Mexico preflight panel with the blocking exception",
              pre.count() == 1 and "MX_SALARY_DAYS_CONVENTION_UNSET" in pre.inner_text(), body(a)[:600])
        badges = a.locator('[data-testid="mx-run-status"]')
        txt = badges.inner_text() if badges.count() else ""
        check("on-2 four separate status badges (payroll / CFDI / authorities / bank)",
              all(k in txt.upper() for k in ("PAYROLL", "CFDI", "AUTHORITIES", "BANK")) and "HELD" in txt, txt)
        shot(a, "01a_status_badges", a.locator('[data-testid="mx-run-status"]'))
        shot(a, "01b_preflight_blocked", a.locator('[data-testid="mx-run-preflight"]'))

        # Fix: a new labour-policy version with the convention, activated (Phase 3 API).
        st, txt = api(A0, "POST", "/api/payroll/mexico/employers/1/labor-policies", {
            "effectiveFrom": "2026-02-01", "ordinaryWeeklyHours": "40", "aguinaldoDays": "15",
            "vacationPolicy": [{"serviceYearFrom": 1, "serviceYearTo": 1, "days": "12"},
                               {"serviceYearFrom": 2, "serviceYearTo": 2, "days": "14"},
                               {"serviceYearFrom": 3, "serviceYearTo": None, "days": "16"}],
            "vacationPremiumPct": "25", "sundayPremiumPct": "25", "salaryDaysConvention": "CALENDAR"})
        policy_id = json.loads(txt).get("id") if st == 200 else None
        st2, txt2 = api(A0, "PUT", f"/api/payroll/mexico/labor-policies/{policy_id}/activate") if policy_id else (0, txt)
        check("on-3 labour policy with a salary-days convention recorded and activated",
              st == 200 and st2 == 200, f"{st} {txt[:200]} / {st2} {txt2[:200]}")

        open_run(a)
        a.locator("tr").filter(has_text="Persona").first.click()
        settle(a)
        a.get_by_role("button", name=re.compile("Recalculate payslip")).first.click()
        settle(a, 3000)
        open_run(a)
        a.locator("tr").filter(has_text="Persona").first.click()
        settle(a)
        trace = a.locator('[data-testid="mx-trace"]')
        ttxt = trace.inner_text() if trace.count() else ""
        check("on-4 recalculation clears the block and the trace shows every section",
              all(s.upper() in ttxt.upper() for s in ("Perceptions", "ISR and employment subsidy", "SBC",
                                                       "IMSS branches", "INFONAVIT", "Content rows read")),
              ttxt[:400] or body(a)[:600])
        pre_txt = a.locator('[data-testid="mx-run-preflight"]').inner_text()
        check("on-5 preflight now has no exceptions", "No preflight exceptions" in pre_txt, pre_txt[:300])
        shot(a, "02_trace_after_fix", a.locator('[data-testid="mx-trace"]'))

        s1, _ = api(A0, "PUT", "/api/payroll/runs/1/approve")
        s2, t2 = api(A1, "PUT", "/api/payroll/runs/1/approve")
        open_run(a)
        btxt = a.locator('[data-testid="mx-run-status"]').inner_text()
        check("on-6 Draft → Review → Approved: payroll badge Approved, CFDI / authorities / bank unchanged",
              s1 == 200 and s2 == 200 and "APPROVED" in btxt.upper() and "NOT STARTED" in btxt.upper()
              and "HELD" in btxt.upper(), f"{s1} {s2} {t2[:200]} | {btxt}")
        shot(a, "03_approved", a.locator('[data-testid="mx-run-status"]'))

        con = sqlite3.connect(str(DB))
        con.execute("UPDATE payroll_mx_risk_premiums SET premium_rate_pct = 0.6 WHERE status = 'ACTIVE'")
        con.commit()
        con.close()
        open_run(a)
        inv = a.locator('[data-testid="mx-approval-invalidated"]')
        check("on-7 a changed risk premium shows 'Approval invalidated' naming the component",
              inv.count() == 1 and "riskPremium" in inv.inner_text(), body(a)[:500])
        shot(a, "04_approval_invalidated", a.locator('[data-testid="mx-run-status"]'))

        s3, t3 = api(A1, "PUT", "/api/payroll/runs/1/approve")
        check("on-8 Authorize refused (CFDI Phase 7 / bank Phase 10)", s3 >= 400 and "MX_RUN_NOT_SUPPORTED" in t3,
              f"{s3} {t3[:300]}")

        a.goto(APP + "/payroll/payslips", wait_until="networkidle")
        settle(a)
        a.get_by_text("Persona").first.click()
        settle(a, 2000)
        sec = a.locator('[data-testid="mx-payslip-section"]')
        check("on-9 payslip view has the Mexico section (employer cost + SBC apart from pay)",
              sec.count() == 1 and "SBC" in sec.inner_text() and "employer cost" in sec.inner_text().lower(),
              body(a)[:600])
        shot(a, "05_payslip_mexico")
        shot(a, "05b_payslip_mexico_section", a.locator('[data-testid="mx-payslip-section"]'))

        rows = api(A0, "GET", "/api/payroll/mexico/runs/1/status")[1]
        check("on-10 committed ledgers exist after approval", json.loads(rows)["ledgers"]["isnLiabilities"] == 1, rows[:300])
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
        settle(n)
        check("on-11 NL org run screen unchanged — no Mexico panels",
              n.locator('[data-testid="mx-run-preflight"]').count() == 0, "")
        shot(n, "06_nl_regression")
        expected = {("/api/payroll/runs/1/approve", 409), ("/api/payroll/runs/1/approve", 400),
                    ("/api/payroll/runs/1/approve", 422)}
    else:
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
        settle(n)
        check("off-1 NL org run screen loads, no Mexico panels",
              "Payroll" in body(n) and n.locator('[data-testid="mx-run-preflight"]').count() == 0, body(n)[:300])
        shot(n, "01_nl_runs")
        a = new_page(browser, A0)
        open_run(a)
        check("off-2 the Mexican run's Mexico panels show only the dormancy refusal (no badges, no trace)",
              "not open for onboarding" in body(a) and a.locator('[data-testid="mx-run-status"]').count() == 0
              and a.locator('[data-testid="mx-trace"]').count() == 0, body(a)[-800:])
        shot(a, "02_mx_run_dormant")
        for path in ("/api/payroll/mexico/runs/1/preflight", "/api/payroll/mexico/runs/1/status",
                     "/api/payroll/mexico/employees/1/hours"):
            st, txt = api(A0, "GET", path)
            check(f"off-3 {path} → 403", st == 403, f"{st} {txt[:150]}")
        st, txt = api(A0, "POST", "/api/payroll/runs/preview",
                      {"employeeIds": [1], "country": "MX", "periodStart": "2026-07-01", "periodEnd": "2026-07-15"})
        check("off-4 a Mexican payroll preview is refused while dormant (MX_DORMANT)",
              st >= 400 and "not open for onboarding" in txt, f"{st} {txt[:200]}")
        s = new_page(browser, SA)
        s.goto(APP + "/super-admin/compliance/mexico", wait_until="networkidle")
        settle(s)
        check("off-5 Super Admin Mexico workspace still loads", "MX-PAYROLL" in body(s), body(s)[:300])
        shot(s, "03_super_admin")
        expected = set()
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 6 — browser check (flag {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL — ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
