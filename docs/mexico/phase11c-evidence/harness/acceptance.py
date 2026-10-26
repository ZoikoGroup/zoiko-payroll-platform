"""Mexico Phase 11c (validate-only CFDI preview) browser acceptance — installed
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
A0, A1, NL = "admin0@mx11c.example.com", "admin1@mx11c.example.com", "admin@nl11c.example.com"
L0, L1 = "admin0@live11c.example.com", "admin1@live11c.example.com"
SA_A, SA_B = "sa-a@mx11c.example.com", "sa-b@mx11c.example.com"
NEWCOMER = "admin@new11c.example.com"
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


def open_sa_lifecycle(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name=re.compile("CFDI lifecycle")).first.click()
    settle(page, 2500)
    return tid(page, "mx-cfdi-validations")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    run_id, label = db_one("SELECT id, period_label FROM payroll_runs WHERE status = 'Approved' "
                           "AND organization_id = (SELECT organization_id FROM payroll_mx_employer_profiles LIMIT 1) "
                           "ORDER BY id LIMIT 1")
    before = db_one("SELECT count(*) FROM payroll_mx_cfdi_documents")[0]
    a = new_page(browser, A0)
    validate_responses = []
    a.on("response", lambda r: validate_responses.append(r) if r.url.endswith("/cfdi/validate") else None)
    open_run(a, label)
    stage = tid(a, "mx-cfdi-stage")
    stage.scroll_into_view_if_needed()
    tid(a, "mx-cfdi-validate").click()
    settle(a, 4000)
    preview = tid(a, "mx-cfdi-preview")
    text = preview.inner_text()
    check(f"{MODE}-1 Validate CFDI shows the preview with the G1 decision banner first",
          tid(a, "mx-cfdi-preview-awaiting").count() == 1 and "Waiting for a G1 decision" in text
          and "SalarioDiarioIntegrado" in text, text[:400])
    row = tid(a, "mx-cfdi-preview-row").first.inner_text()
    check(f"{MODE}-2 the payslip is REFUSED with MX_CFDI_INPUT_MISSING and no payload hash",
          "REFUSED" in row and "MX_CFDI_INPUT_MISSING" in row and "—" in row, row[:300])
    shot(a, "01_preview_awaiting_g1", preview)
    body = validate_responses[-1].text() if validate_responses else ""
    check(f"{MODE}-3 the preview response carries no XML and no identifier",
          body and "<cfdi" not in body and "Comprobante" not in body and "LOAV890607" not in body, body[:200])
    after = db_one("SELECT count(*) FROM payroll_mx_cfdi_documents")[0]
    outbox = db_one("SELECT count(*) FROM payroll_mx_cfdi_outbox_items")[0]
    check(f"{MODE}-4 nothing was signed, stored or queued", after == before and outbox == 0, f"{before}->{after}, {outbox}")
    b = new_page(browser, SA_A)
    panel = open_sa_lifecycle(b)
    srow = tid(b, "mx-cfdi-validation-row").first.inner_text() if tid(b, "mx-cfdi-validation-row").count() else ""
    check(f"{MODE}-5 the Super Admin sees the audited summary: counts and codes, awaiting a G1 decision",
          f"#{run_id}" in srow and "MX_CFDI_INPUT_MISSING" in srow and "awaiting a G1 decision" in srow
          and "Persona" not in panel.inner_text(), srow[:300])
    shot(b, "02_sa_validation_summary", panel)
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 11c -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
