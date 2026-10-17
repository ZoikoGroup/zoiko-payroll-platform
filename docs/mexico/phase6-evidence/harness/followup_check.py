"""Phase 6 follow-up browser check (flag ON, scratch DB from setup_db.py,
serve.py on): the employer total is "—" for a Mexican payslip in the run
breakdown and on the Super Admin finance page; a Mexican preview without the
run's pay date is refused, with it the trace is returned (API)."""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase6-evidence")
PASSWORD = "BrowserCheck!2026"
A0, SA = "admin0@mx6.example.com", "sa-a@mx6.example.com"
results, errors = [], []


_TOKENS = {}


def token(email):          # one login per user (the login route is rate-limited)
    if email in _TOKENS:
        return _TOKENS[email]
    _TOKENS[email] = _login(email)
    return _TOKENS[email]


def _login(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PASSWORD}).encode())
    return json.load(urllib.request.urlopen(req))


def api(email, method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
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


def page_for(browser, who):
    tok = token(who)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(
        f"localStorage.setItem('zoiko_payroll_access', {json.dumps(tok['access_token'])});"
        f"localStorage.setItem('zoiko_payroll_refresh', {json.dumps(tok['refresh_token'])});"
        f"localStorage.setItem('zoiko_payroll_user', {json.dumps(json.dumps(tok['user']))});")
    p = ctx.new_page()
    p.on("pageerror", lambda e: errors.append(str(e)))
    return p


# Make the payslip calculable (labour-policy v2 with the convention), recalculate.
api(A0, "POST", "/api/payroll/mexico/employers/1/labor-policies", {
    "effectiveFrom": "2026-02-01", "ordinaryWeeklyHours": "40", "aguinaldoDays": "15",
    "vacationPolicy": [{"serviceYearFrom": 1, "serviceYearTo": 1, "days": "12"},
                       {"serviceYearFrom": 2, "serviceYearTo": 2, "days": "14"},
                       {"serviceYearFrom": 3, "serviceYearTo": None, "days": "16"}],
    "vacationPremiumPct": "25", "sundayPremiumPct": "25", "salaryDaysConvention": "CALENDAR"})
api(A0, "PUT", "/api/payroll/mexico/labor-policies/2/activate")
api(A0, "PUT", "/api/payroll/runs/1/employees/1/recalculate")

body = {"employeeIds": [1], "country": "MX", "periodStart": "2026-06-01", "periodEnd": "2026-06-15"}
st1, t1 = api(A0, "POST", "/api/payroll/runs/preview", body)
st2, t2 = api(A0, "POST", "/api/payroll/runs/preview", {**body, "payDate": "2026-06-15"})
check("fu-1 preview without the run's pay date is refused (MX_PAY_DATE_MISSING)",
      400 <= st1 < 500 and "MX_PAY_DATE_MISSING" in t1, f"{st1} {t1[:200]}")
check("fu-2 preview with the pay date returns the Mexican trace",
      st2 == 200 and json.loads(t2)["employees"][0].get("mxPreview", {}).get("pay_date") == "2026-06-15", f"{st2} {t2[:200]}")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = page_for(browser, A0)
    a.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
    a.wait_for_timeout(1500)
    a.get_by_text("Jun 1-15, 2026").first.click()
    a.wait_for_timeout(2500)
    a.locator("tr").filter(has_text="Persona").first.click()
    a.wait_for_timeout(1500)
    dash = a.locator('[data-testid="mx-employer-dash"]')
    check("fu-3 run breakdown: Mexican employer contributions / total cost shown as '—' with a pointer to the trace",
          dash.count() == 1 and "Mexico trace" in dash.inner_text(), a.inner_text("body")[-600:])
    if dash.count():
        dash.first.locator("xpath=..").screenshot(path=str(OUT / "fu_01_employer_dash.png"))
    # The finance page's default filter is "This Month" (by period start): for
    # this display-only check the scratch run's period is moved into the
    # current month so the Mexican org has a real row (the June figures stay).
    import sqlite3
    from datetime import date
    db_path = (r"C:\Users\Nikhi\AppData\Local\Temp\claude\d--zoiko-payroll-platform"
               r"\4310d3e7-cd06-425b-899e-67cfb66b19b8\scratchpad\p6browser\mx_fu1.db")
    con = sqlite3.connect(db_path)
    first = date.today().replace(day=1)
    con.execute("UPDATE payroll_runs SET period_start = ?, period_end = ?",
                (first.isoformat(), first.replace(day=15).isoformat()))
    con.commit()
    con.close()
    s = page_for(browser, SA)
    s.goto(APP + "/super-admin/finance", wait_until="networkidle")
    s.wait_for_timeout(2500)
    s.screenshot(path=str(OUT / "fu_02_finance_page.png"), full_page=True)
    row = s.locator("tr").filter(has_text="MXB6 Org")
    txt = row.first.inner_text() if row.count() else ""
    cells = [c.strip() for c in txt.split("\t")] if txt else []
    check("fu-4 Super Admin finance page: the Mexican org HAS a run, gross shown, employer cost '—'",
          len(cells) >= 6 and cells[1] == "MX" and cells[2] not in ("0", "") and "9" in cells[3]
          and cells[5] == "—", " | ".join(cells) or s.inner_text("body")[:800])
    browser.close()
check("fu-z no page errors", not errors, str(errors[:3]))
lines = ["# Mexico Phase 6 follow-up — browser check (flag ON)", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {n} | {'PASS' if ok else 'FAIL — ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |" for n, ok, d in results]
(OUT / "RESULTS-followup.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
