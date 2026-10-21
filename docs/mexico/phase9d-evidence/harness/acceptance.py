"""Mexico Phase 9d (PTU) browser acceptance — installed
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
A0, A1, NL = "admin0@mx9d.example.com", "admin1@mx9d.example.com", "admin@nl9d.example.com"
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


def open_ptu(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)
    return tid(page, "mx-ptu")


def click_in(panel, page, name):
    panel.get_by_role("button", name=re.compile(name)).first.click()
    settle(page, 2000)


def employee2_id():
    return db_one("SELECT id FROM payroll_employees WHERE employee_code = 'MXB9D-2'")[0]


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/ptu/cycles"), ("POST", "/ptu/cycles"), ("POST", "/ptu/cycles/1/allocate"),
                             ("POST", "/ptu/cycles/1/ptu-run"), ("GET", "/ptu/exclusion-reasons")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        panel = open_ptu(a)
        check("off-2 the PTU panel shows the dormancy refusal", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:300])
        shot(a, "01_ptu_dormant", panel)
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    else:
        a = new_page(browser, A0)
        panel = open_ptu(a)
        form = tid(a, "mx-new-ptu-cycle")
        form.locator("select").first.select_option(index=1)
        inputs = form.locator("input")
        inputs.nth(0).fill("2026")
        inputs.nth(1).fill("10000")
        inputs.nth(2).fill("SYN-DECL-2026")
        form.get_by_role("button", name="Record PTU cycle").click()
        settle(a, 2000)
        ptxt = panel.inner_text()
        check(f"{MODE}-1 a PTU cycle is recorded in the Compliance Centre (DRAFT)", "DRAFT" in ptxt and "10000" in ptxt,
              ptxt[:400])
        click_in(panel, a, "Approve amount")
        ptxt = panel.inner_text()
        check(f"{MODE}-2 the recorder cannot approve the amount (four-eyes)", "MX_FOUR_EYES_REQUIRED" in ptxt, ptxt[-300:])
        b = new_page(browser, A1)
        bpanel = open_ptu(b)
        click_in(bpanel, b, "Approve amount")
        btxt = bpanel.inner_text()
        deadline_ok = ("2027-05-30" in btxt) if MODE == "rules" else ("unsourced" in btxt)
        check(f"{MODE}-3 a second person approves the amount; the pay-by date is "
              + ("from the rule" if MODE == "rules" else "unsourced"), "AMOUNT_APPROVED" in btxt and deadline_ok, btxt[:400])
        click_in(bpanel, b, "^Open$")
        cyc = tid(b, "mx-ptu-cycle")
        if MODE == "on":
            ctxt = cyc.inner_text()
            check("on-4 operator exclusions are blocked: the catalog is not transcribed (S26)",
                  "MX_PTU_EXCLUSION_RULE_MISSING" in ctxt and tid(b, "mx-ptu-exclusion").count() == 0, ctxt[:400])
            click_in(bpanel, b, "^Allocate$")
            btxt = bpanel.inner_text()
            check("on-5 allocation is blocked with the named code (PTU rule not transcribed, S26)",
                  "MX_PTU_RULE_MISSING" in btxt and "ALLOCATED" not in btxt.replace("AMOUNT_APPROVED", ""), btxt[-400:])
            shot(b, "02_allocation_blocked", bpanel)
        else:
            ex = tid(b, "mx-ptu-exclusion")
            ex.locator("input").nth(0).fill(str(employee2_id()))
            ex.locator("select").first.select_option("SYN_DIRECTOR")
            ex.locator("input").nth(1).fill("SYN-BOARD-MINUTES")
            ex.get_by_role("button", name="Record exclusion").click()
            settle(b, 2000)
            panel = open_ptu(a)
            click_in(panel, a, "^Open$")
            click_in(tid(a, "mx-ptu-cycle"), a, "Approve \\(another person\\)")
            ctxt = tid(a, "mx-ptu-cycle").inner_text()
            check("rules-4 an operator exclusion: catalog reason + evidence, approved by the other person",
                  "SYN_DIRECTOR" in ctxt and "yes" in ctxt, ctxt[:400])
            click_in(panel, a, "^Allocate$")
            click_in(panel, a, "^Open$")
            ctxt = tid(a, "mx-ptu-cycle").inner_text()
            check("rules-5 allocated from committed runs: worker 1 paid, worker 2 excluded with the reason and evidence",
                  "ALLOCATED" in panel.inner_text() and "SYN_DIRECTOR (SYN-BOARD-MINUTES)" in ctxt and "residue" in ctxt,
                  ctxt[:500])
            shot(a, "02_allocated", tid(a, "mx-ptu-cycle"))
            click_in(panel, a, "Approve allocation")
            check("rules-6 the allocator cannot approve the allocation (four-eyes)",
                  "MX_FOUR_EYES_REQUIRED" in panel.inner_text(), panel.inner_text()[-300:])
            bpanel = open_ptu(b)
            click_in(bpanel, b, "Approve allocation")
            click_in(bpanel, b, "^Open$")
            cyc = tid(b, "mx-ptu-cycle")
            cyc.locator('input[type="date"]').first.fill("2027-05-15")
            cyc.get_by_role("button", name="Open PTU run").click()
            settle(b, 2500)
            btxt = bpanel.inner_text()
            cycle_id = db_one("SELECT id FROM payroll_mx_ptu_cycles ORDER BY id DESC")[0]
            label = f"PTU 2026 (cycle {cycle_id})"
            rid = db_one("SELECT id FROM payroll_runs WHERE period_label = ?", label)
            check("rules-7 a second person approves the allocation; the PTU run opens",
                  "APPROVED" in btxt and rid is not None, btxt[:400])
            shot(b, "03_ptu_run_opened", bpanel)
            rid = rid[0]
            open_run(b, label)
            b.locator("tr").filter(has_text="Persona").first.click()
            settle(b)
            trace = tid(b, "mx-trace")
            ttxt = trace.inner_text() if trace.count() else ""
            check("rules-8 the PTU payslip: one MX_PTU line, special withholding, no IMSS; the excluded worker has none",
                  not preflight_codes(rid) and "MX_PTU" in ttxt
                  and db_one("SELECT count(*) FROM payslip_items WHERE payroll_run_id = ?", rid)[0] == 1, ttxt[:400])
            shot(b, "04_ptu_trace", trace)
            s1 = api(A0, "PUT", f"/api/payroll/runs/{rid}/approve")[0]
            s2 = api(A1, "PUT", f"/api/payroll/runs/{rid}/approve")[0]
            bpanel = open_ptu(b)
            check("rules-9 committing the run marks the cycle DISTRIBUTED",
                  (s1, s2) == (200, 200) and "DISTRIBUTED" in bpanel.inner_text(), f"{s1} {s2} {bpanel.inner_text()[:300]}")
            shot(b, "05_distributed", bpanel)
            open_employee(b)
            etxt = tid(b, "mx-employee-ptu").inner_text() if tid(b, "mx-employee-ptu").count() else ""
            check("rules-10 the employee screen shows the worker's PTU", "2026" in etxt and "DISTRIBUTED" in etxt, etxt[:300])
            shot(b, "06_employee_ptu", tid(b, "mx-employee-ptu"))
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 9d -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
