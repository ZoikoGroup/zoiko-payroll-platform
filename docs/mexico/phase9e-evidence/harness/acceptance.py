"""Mexico Phase 9e (annual ISR adjustment) browser acceptance — installed
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
A0, A1, NL = "admin0@mx9e.example.com", "admin1@mx9e.example.com", "admin@nl9e.example.com"
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


def open_annual(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)
    return tid(page, "mx-annual")


def click_in(panel, page, name):
    panel.get_by_role("button", name=re.compile(name)).first.click()
    settle(page, 2000)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/annual-adjustments"), ("POST", "/annual-adjustments/compute"),
                             ("POST", "/annual-adjustments/apply"), ("GET", "/annual-adjustments/exclusion-reasons")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        panel = open_annual(a)
        check("off-2 the annual-adjustment panel shows the dormancy refusal", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:300])
        shot(a, "01_annual_dormant", panel)
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    else:
        a = new_page(browser, A0)
        panel = open_annual(a)
        form = tid(a, "mx-new-annual")
        form.locator("select").first.select_option(index=1)
        form.locator("input").first.fill("2026")
        form.get_by_role("button", name="Compute").click()
        settle(a, 2500)
        ptxt = panel.inner_text()
        if MODE == "on":
            check("on-1 computing is blocked with the named code (rule not transcribed, S24); nothing written",
                  "MX_ANNUAL_ADJUSTMENT_RULE_MISSING" in ptxt and tid(a, "mx-annual-year").count() == 0, ptxt[-400:])
            shot(a, "01_compute_blocked", panel)
        else:
            check("rules-1 the 2026 adjustment is computed from committed runs (2 workers, COMPUTED)",
                  tid(a, "mx-annual-year").count() == 1 and ptxt.count("COMPUTED") >= 2, ptxt[:500])
            shot(a, "01_computed", tid(a, "mx-annual-year"))
            click_in(panel, a, "^Approve \\(another person\\)$")
            check("rules-2 the person who computed cannot approve (four-eyes)", "MX_FOUR_EYES_REQUIRED" in panel.inner_text(),
                  panel.inner_text()[-300:])
            b = new_page(browser, A1)
            bpanel = open_annual(b)
            click_in(bpanel, b, "^Approve \\(another person\\)$")
            btxt = bpanel.inner_text()
            check("rules-3 a second person approves", "APPROVED" in btxt, btxt[:400])
            jan_id = db_one("SELECT id FROM payroll_runs WHERE period_label = 'Jan 1-15, 2027'")[0]
            bpanel.get_by_label("Run id").fill(str(jan_id))
            click_in(bpanel, b, "^Apply in run$")
            check("rules-4 assigned to the open January 2027 run", "Assigned" in bpanel.inner_text(), bpanel.inner_text()[-300:])
            st, txt = api(A0, "POST", f"/api/payroll/runs/{jan_id}/generate-payslips", {})
            if st == 405:
                st, txt = api(A0, "PUT", f"/api/payroll/runs/{jan_id}/generate-payslips", {})
            open_run(b, "Jan 1-15, 2027")
            b.locator("tr").filter(has_text="Persona").first.click()
            settle(b)
            trace = tid(b, "mx-trace")
            ttxt = trace.inner_text() if trace.count() else ""
            check("rules-5 the January payslip shows the 2026 adjustment as its own section",
                  st in (200, 201) and "ANNUAL ISR ADJUSTMENT 2026" in ttxt.upper() and not preflight_codes(jan_id),
                  f"{st} {txt[:200]} {ttxt[:300]}")
            shot(b, "02_january_trace", trace)
            s1 = api(A0, "PUT", f"/api/payroll/runs/{jan_id}/approve")[0]
            s2 = api(A1, "PUT", f"/api/payroll/runs/{jan_id}/approve")[0]
            bpanel = open_annual(b)
            btxt = bpanel.inner_text()
            check("rules-6 committing the run marks the adjustments APPLIED, linked to their payslips",
                  (s1, s2) == (200, 200) and "APPLIED" in btxt and "payslip #" in btxt, f"{s1} {s2} {btxt[:400]}")
            shot(b, "03_applied", bpanel)
            open_employee(b)
            view = tid(b, "mx-employee-annual")
            vtxt = view.inner_text() if view.count() else ""
            check("rules-7 the employee screen shows the worker's adjustment", "2026" in vtxt and "APPLIED" in vtxt, vtxt[:300])
            shot(b, "04_employee_annual", view)
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 9e -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
