"""Mexico Phase 10e (two-level activation) browser acceptance — installed
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
A0, A1, NL = "admin0@mx10e.example.com", "admin1@mx10e.example.com", "admin@nl10e.example.com"
SA_A, SA_B = "sa-a@mx10e.example.com", "sa-b@mx10e.example.com"
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


import zlib
from datetime import date, timedelta


def open_centre(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2500)
    return tid(page, "mx-compliance-centre")


def open_readiness(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name="Readiness G1–G8", exact=True).first.click()
    settle(page, 2500)
    return tid(page, "mx-pilot-grants")


def pdf_text(raw: bytes) -> str:
    """The PDF's text as a reader sees it (pypdf, system Python): the payslip
    embeds a TrueType font, so its content streams hold glyph codes, not text."""
    tmp = OUT / f"{MODE}_05_pilot_payslip.pdf"
    tmp.write_bytes(raw)
    out = subprocess.run([PYTHON, "-c", "import sys; from pypdf import PdfReader; "
                          "sys.stdout.buffer.write(''.join(p.extract_text() for p in PdfReader(sys.argv[1]).pages)"
                          ".encode('utf-8'))", str(tmp)], capture_output=True, timeout=120)
    return out.stdout.decode("utf-8", "replace")


def download(email, path):
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token(email)['access_token']}"})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    org_id = db_one("SELECT organization_id FROM payroll_runs WHERE period_label = 'Jun 16-30, 2026'")[0]
    run2 = db_one("SELECT id FROM payroll_runs WHERE period_label = 'Jun 16-30, 2026'")[0]
    a = new_page(browser, A0)
    centre = open_centre(a)
    st, txt = api(A0, "GET", BASE + "/payments/batches")
    check(f"{MODE}-1 the kill switch alone opens nothing: flag on, no registry, no grant -> refused",
          st == 403 and "not open for onboarding" in centre.inner_text(), f"{st} {txt[:120]}")
    s = new_page(browser, SA_A)
    pilot = open_readiness(s)
    ptxt = pilot.inner_text()
    pre = tid(s, "mx-pilot-preconditions")
    check(f"{MODE}-2 readiness: level DORMANT; every pilot precondition met (kill switch, G1 G2 G4 G5 G7, Q9, hosting, key)",
          "Level: DORMANT" in ptxt and pre.locator("li").count() == 9 and pre.locator(".text-error").count() == 0,
          ptxt[:600])
    shot(s, "01_pilot_preconditions", pilot)
    form = tid(s, "mx-new-pilot-grant")
    form.locator('input[aria-label="Organisation id"]').fill(str(org_id))
    form.locator('input[aria-label="Reason"]').fill("SYNTHETIC: G8 parallel run")
    form.locator('input[aria-label="Expires on"]').fill((date.today() + timedelta(days=60)).isoformat())
    form.get_by_role("button", name="Propose pilot grant").click()
    settle(s, 2500)
    pilot.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(s, 2000)
    check(f"{MODE}-3 the proposer cannot approve the grant (four-eyes)", "MX_FOUR_EYES_REQUIRED" in pilot.inner_text(),
          pilot.inner_text()[-400:])
    b = new_page(browser, SA_B)
    bpilot = open_readiness(b)
    bpilot.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(b, 2500)
    bpilot = open_readiness(b)
    btxt = bpilot.inner_text()
    check(f"{MODE}-4 a second Super Admin approves: grant ACTIVE, level PILOT (1 organisation)",
          "ACTIVE" in btxt and "PILOT (1 organisation)" in btxt, btxt[:600])
    shot(b, "02_pilot_active", bpilot)
    centre = open_centre(a)
    banner = tid(a, "mx-pilot-banner")
    check(f"{MODE}-5 the pilot organisation opens, with the non-binding banner",
          banner.count() == 1 and "Nothing produced here is binding" in banner.inner_text()
          and "not open for onboarding" not in centre.inner_text(), centre.inner_text()[:400])
    shot(a, "03_pilot_banner", banner)
    pay = tid(a, "mx-payments")
    pay.locator("form").locator("input").first.fill(str(run2))
    pay.get_by_role("button", name="Build payment batch").click()
    settle(a, 2500)
    check(f"{MODE}-6 a salary payment batch is refused on screen (MX_PILOT_NO_PAYMENTS)",
          "MX_PILOT_NO_PAYMENTS" in pay.inner_text(), pay.inner_text()[-300:])
    shot(a, "04_no_payments", pay)
    st, txt = api(A0, "POST", BASE + "/authorities/movements/export", {})
    check(f"{MODE}-7 an IDSE worklist export is refused (MX_PILOT_NO_FILINGS)", st == 400 and "MX_PILOT_NO_FILINGS" in txt,
          f"{st} {txt[:200]}")
    out = subprocess.run([PYTHON, str(HERE / "setup_db.py"), "commit3", MODE], capture_output=True, text=True,
                         env=os.environ.copy(), timeout=600)
    item = db_one("SELECT id FROM payslip_items WHERE payroll_run_id = "
                  "(SELECT id FROM payroll_runs WHERE period_label = 'Jul 1-15, 2026') ORDER BY id")
    pdf_ok, detail = False, out.stdout[-200:] + out.stderr[-300:]
    if item:
        stp, raw = download(A0, f"/api/payroll/payslips/{item[0]}/download")
        text = pdf_text(raw)
        pdf_ok = stp == 200 and raw.startswith(b"%PDF") and "PARALLEL RUN" in text and "NOT A PAYSLIP" in text
        (OUT / f"{MODE}_05_pilot_payslip.pdf").write_bytes(raw)
    check(f"{MODE}-8 a run committed in the pilot is recorded as pilot; its payslip PDF carries the PILOT watermark",
          "committed run" in out.stdout and out.stdout.strip().endswith("True") and pdf_ok, detail)
    pilot = open_readiness(s)
    pilot.locator('input[placeholder="Reason to revoke"]').first.fill("SYNTHETIC: end of browser check")
    pilot.get_by_role("button", name="Revoke").first.click()
    settle(s, 2500)
    pilot = open_readiness(s)
    rtxt = pilot.inner_text()
    centre = open_centre(a)
    check(f"{MODE}-9 revoking closes the organisation at once (and the level returns to DORMANT)",
          "REVOKED" in rtxt and "Level: DORMANT" in rtxt and "not open for onboarding" in centre.inner_text()
          and tid(a, "mx-pilot-banner").count() == 0, rtxt[:400])
    shot(s, "06_revoked", pilot)
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10e -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
