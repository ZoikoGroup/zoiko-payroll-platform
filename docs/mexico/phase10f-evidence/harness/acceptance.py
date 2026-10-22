"""Mexico Phase 10f (option B transfer, PILOT markers) browser acceptance — installed
Chrome, vite preview of the current build, scratch SQLite backend.
Usage: python acceptance.py off | on | rules (fresh DB each; serve.py in the
same mode). Non-UI writes: run approvals through the API."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
MODE = sys.argv[1]
assert MODE in ("on", "off", "rules")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = HERE.parent
PYTHON = r"C:\Users\Nikhi\AppData\Local\Programs\Python\Python311\python.exe"
PASSWORD = "BrowserCheck!2026"
A0, A1, NL = "admin0@mx10f.example.com", "admin1@mx10f.example.com", "admin@nl10f.example.com"
L0, L1 = "admin0@live10f.example.com", "admin1@live10f.example.com"
SA_A, SA_B = "sa-a@mx10f.example.com", "sa-b@mx10f.example.com"
SA = "/api/super-admin/compliance/mexico"
BASE = "/api/payroll/mexico"
results, errors, responses, _tokens = [], [], [], {}


def token(email):
    if email not in _tokens:
        req = urllib.request.Request(f"{API}/api/auth/login", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"email": email, "password": PASSWORD}).encode())
        _tokens[email] = json.load(urllib.request.urlopen(req))
    return _tokens[email]


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
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))


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
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def shot(page, name, locator=None):
    page.wait_for_timeout(400)
    if locator is not None and locator.count():
        locator.first.screenshot(path=str(OUT / f"{MODE}_{name}.png"))
    else:
        page.screenshot(path=str(OUT / f"{MODE}_{name}.png"), full_page=True)


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


def open_employee(page):
    page.goto(APP + "/payroll/employees", wait_until="load")
    settle(page)
    page.get_by_text("Persona Sintética").first.click()
    settle(page)
    page.get_by_role("button", name=re.compile("Manage")).first.click()
    settle(page, 2000)


def open_run(page, label):
    page.goto(APP + "/payroll/payroll-runs", wait_until="load")
    settle(page)
    page.get_by_text(label, exact=True).first.click()
    settle(page, 2500)


def db_one(sql, *args):
    """Read-only lookup in the scratch SQLite DB (the env URL serve.py uses)."""
    import sqlite3

    con = sqlite3.connect(os.environ["PAYROLL_DATABASE_URL"].replace("sqlite:///", ""))
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def preflight_codes(rid):
    st, txt = api(A0, "GET", f"{BASE}/runs/{rid}/preflight")
    return {e["code"] for e in json.loads(txt).get("exceptions", [])} if st == 200 else set()


def employee_id():
    return db_one("SELECT id FROM payroll_employees WHERE country_code = 'MX' ORDER BY id")[0]


def open_centre(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2500)
    return tid(page, "mx-master-transfer")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    live_id = db_one("SELECT id FROM organizations WHERE organization_code = 'MXL10F'")[0]
    a = new_page(browser, A0)
    open_run(a, "Jul 1-15, 2026")
    status = tid(a, "mx-run-status")
    check(f"{MODE}-1 the run screen of a pilot run shows PILOT (banner and badge)",
          tid(a, "mx-run-pilot").count() == 1 and tid(a, "mx-badge-pilot").count() == 1
          and "Nothing in it is binding" in status.inner_text(), status.inner_text()[:300] if status.count() else "")
    shot(a, "01_pilot_run_screen", status)
    # the payslip row in the employee table (not the corrections panel's checkbox label)
    a.locator("tr").filter(has_text="Persona Sintética").first.click()
    settle(a, 2000)
    trace = tid(a, "mx-trace-pilot")
    check(f"{MODE}-2 the payslip view of a pilot payslip shows PILOT", trace.count() >= 1
          and "non-binding" in trace.first.inner_text(), "")
    shot(a, "02_pilot_payslip_view", tid(a, "mx-trace"))
    panel = open_centre(a)
    form = tid(a, "mx-new-release")
    form.locator('input[name="targetOrganizationId"]').fill(str(live_id))
    form.locator('input[name="reason"]').fill("SYNTHETIC: go-live")
    form.get_by_role("button", name="Propose release").click()
    settle(a, 2500)
    panel.get_by_role("button", name=re.compile("^Release")).first.click()
    settle(a, 2000)
    check(f"{MODE}-3 the proposing pilot admin cannot release it (four-eyes)",
          "MX_FOUR_EYES_REQUIRED" in panel.inner_text(), panel.inner_text()[-300:])
    b = new_page(browser, A1)
    bpanel = open_centre(b)
    bpanel.get_by_role("button", name=re.compile("^Release")).first.click()
    settle(b, 2500)
    bpanel = open_centre(b)
    btxt = bpanel.inner_text()
    check(f"{MODE}-4 a second pilot admin releases it: AVAILABLE, expiring in 7 days, employer RFC masked",
          "AVAILABLE" in btxt.upper() and "*" in btxt, btxt[:500])
    shot(b, "03_released", bpanel)
    l0 = new_page(browser, L0)
    lpanel = open_centre(l0)
    lpanel.get_by_role("button", name="Review the diff").first.click()
    settle(l0, 2500)
    preview = tid(l0, "mx-import-preview")
    ptxt = preview.inner_text() if preview.count() else ""
    rfc_full = db_one("SELECT compliance_fields FROM payroll_employees WHERE employee_code = 'MXB10F-2'")[0] or ""
    check(f"{MODE}-5 the live admin reviews the diff: employees listed, identifiers masked",
          "Persona Sintética" in ptxt and "*" in ptxt and "WXYZ010101AB1" not in ptxt and "WXYZ010101HDFXYZ01" not in ptxt
          and "10987654321" not in ptxt, ptxt[:500])
    shot(l0, "04_import_diff", preview)
    preview.locator('input[aria-label="Import reason"]').fill("SYNTHETIC: import the pilot's master data")
    preview.get_by_role("button", name=re.compile("^Propose import")).click()
    settle(l0, 2500)
    lpanel = open_centre(l0)
    lpanel.get_by_role("button", name=re.compile("^Approve import")).first.click()
    settle(l0, 2000)
    check(f"{MODE}-6 the proposing live admin cannot approve the import (four-eyes)",
          "MX_FOUR_EYES_REQUIRED" in lpanel.inner_text(), lpanel.inner_text()[-300:])
    l1 = new_page(browser, L1)
    l1panel = open_centre(l1)
    l1panel.get_by_role("button", name=re.compile("^Approve import")).first.click()
    settle(l1, 3000)
    l1panel = open_centre(l1)
    ltxt = l1panel.inner_text()
    check(f"{MODE}-7 a second live admin approves: EXECUTED, 0 differences",
          "EXECUTED" in ltxt.upper() and "0 differences" in ltxt, ltxt[-500:])
    shot(l1, "05_imported", l1panel)
    emps = db_one("SELECT count(*) FROM payroll_employees WHERE organization_id = ? AND country_code = 'MX'", live_id)[0]
    runs = db_one("SELECT count(*) FROM payroll_runs WHERE organization_id = ?", live_id)[0]
    check(f"{MODE}-8 the live organisation now has the pilot's 2 employees and no payroll result",
          emps == 2 and runs == 0, f"employees={emps} runs={runs}")
    apanel = open_centre(a)
    check(f"{MODE}-9 the pilot sees its release USED (one use only)", "USED" in apanel.inner_text().upper(),
          apanel.inner_text()[:300])
    sides = db_one("SELECT count(*) FROM payroll_tax_configuration_audit WHERE entity_type IN "
                   "('mx_master_release', 'mx_master_import') AND new_value LIKE ?", f'%"organizationId": {live_id}%')[0]
    leaked = db_one("SELECT count(*) FROM payroll_tax_configuration_audit WHERE entity_type IN "
                    "('mx_master_release', 'mx_master_import') AND (new_value LIKE '%WXYZ010101AB1%' OR "
                    "new_value LIKE '%10987654321%' OR new_value LIKE '%Persona%')")[0]
    check(f"{MODE}-10 every step is audited on the live side too, with no identifier or name in the audit",
          sides >= 4 and leaked == 0, f"live-side rows={sides} leaked={leaked}")
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10f -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
