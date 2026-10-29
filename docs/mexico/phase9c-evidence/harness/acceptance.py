"""Mexico Phase 9c (termination + finiquito) browser acceptance — installed
Chrome, vite preview of the current build, scratch SQLite backend.
Usage: python acceptance.py off | on | rules (fresh DB each; serve.py in the
same mode). Non-UI writes: setup_db.py `gen2` (the operator generates the
Jun 16-30 run) and reads through the API."""
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
A0, A1, NL = "admin0@mx9c.example.com", "admin1@mx9c.example.com", "admin@nl9c.example.com"
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


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/termination-reasons"), ("GET", "/employees/1/terminations"),
                             ("POST", "/employees/1/terminations"), ("POST", "/terminations/1/approve"),
                             ("POST", "/terminations/1/cancel"), ("POST", "/terminations/1/finiquito-run")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        open_employee(a)
        body = a.locator("body").inner_text()
        check("off-2 the employee screen renders; no termination panel or form while dormant",
              tid(a, "mx-new-termination").count() == 0 and "Persona" in body, body[:300])
        shot(a, "01_employee_dormant")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    else:
        a = new_page(browser, A0)
        open_employee(a)
        panel = tid(a, "mx-termination")
        check(f"{MODE}-1 the termination panel is on the Mexican employee's screen", panel.count() == 1,
              a.locator("body").inner_text()[:300])
        if MODE == "on":
            ptxt = panel.inner_text() if panel.count() else ""
            check("on-2 the panel states the block and offers no record form (catalog not transcribed, S26)",
                  "MX_TERMINATION_RULE_MISSING" in ptxt and tid(a, "mx-new-termination").count() == 0, ptxt[:400])
            shot(a, "01_termination_blocked", panel)
            st, txt = api(A0, "POST", f"{BASE}/employees/{employee_id()}/terminations",
                          {"terminationDate": "2026-06-20", "reasonCode": "ANY", "evidenceRef": "SYN"})
            check("on-3 recording through the API is refused with the named code",
                  st == 400 and "MX_TERMINATION_RULE_MISSING" in txt, f"{st} {txt[:200]}")
        else:
            form = tid(a, "mx-new-termination")
            options = [o for o in form.locator("select").first.locator("option").all_inner_texts() if o != "—"]
            check("rules-2 the reason is chosen only from the transcribed catalog",
                  options == ["SYN_DISMISSAL", "SYN_RESIGNATION"], str(options))
            inputs = form.locator("input")
            inputs.nth(0).fill("2026-06-20")
            inputs.nth(1).fill("SYN-LETTER-001")
            form.get_by_role("button", name="Record termination").click()
            settle(a, 2000)
            ptxt = panel.inner_text()
            check("rules-3 termination recorded from the employee screen (DRAFT)", "DRAFT" in ptxt, ptxt[:400])
            panel.get_by_role("button", name=re.compile("Approve")).first.click()
            settle(a, 1500)
            ptxt = panel.inner_text()
            check("rules-4 the recorder cannot approve it (four-eyes)", "MX_FOUR_EYES_REQUIRED" in ptxt, ptxt[-300:])
            b = new_page(browser, A1)
            open_employee(b)
            bpanel = tid(b, "mx-termination")
            bpanel.get_by_role("button", name=re.compile("Approve")).first.click()
            settle(b, 2000)
            btxt = bpanel.inner_text()
            leaving = db_one("SELECT date_of_leaving FROM payroll_employees WHERE id = ?", employee_id())[0]
            baja = db_one("SELECT count(*) FROM payroll_mx_imss_movements WHERE movement_type = 'BAJA' "
                          "AND event_date = '2026-06-20' AND source_kind = 'TERMINATION'")[0]
            check("rules-5 a second person approves: date of leaving set, IMSS BAJA generated and shown",
                  "APPROVED" in btxt and "movement #" in btxt and str(leaving).startswith("2026-06-20") and baja == 1,
                  f"{btxt[:300]} leaving={leaving} baja={baja}")
            shot(b, "02_termination_approved", bpanel)
            bpanel.locator('input[type="date"]').first.fill("2026-06-25")
            bpanel.get_by_role("button", name="Open finiquito run").click()
            settle(b, 2500)
            btxt = bpanel.inner_text()
            check("rules-6 the finiquito run opens from the panel; Cancel is no longer offered",
                  re.search(r"#\d+ · Draft|#\d+ · Review", btxt) is not None
                  and bpanel.get_by_role("button", name="Cancel").count() == 0, btxt[:400])
            shot(b, "03_finiquito_opened", bpanel)
            term_id = db_one("SELECT id FROM payroll_mx_terminations ORDER BY id DESC")[0]
            label = f"Finiquito (termination {term_id})"
            rid = db_one("SELECT id FROM payroll_runs WHERE period_label = ?", label)[0]
            open_run(b, label)
            b.locator("tr").filter(has_text="Persona").first.click()
            settle(b)
            trace = tid(b, "mx-trace")
            ttxt = (trace.inner_text() if trace.count() else "").upper().replace(" ", "_")
            check("rules-7 finiquito computed (SYNTHETIC rules): aguinaldo, vacation paid out + premium, separation",
                  not preflight_codes(rid) and all(k in ttxt for k in ("AGUINALDO", "VACATION_PAYOUT", "SEPARATION")),
                  ttxt[:500])
            shot(b, "04_finiquito_trace", trace)
            s1 = api(A0, "PUT", f"/api/payroll/runs/{rid}/approve")[0]
            s2 = api(A1, "PUT", f"/api/payroll/runs/{rid}/approve")[0]
            open_employee(b)
            btxt = tid(b, "mx-termination").inner_text()
            vtxt = tid(b, "mx-vacation").inner_text()
            check("rules-8 committing the finiquito marks the termination COMMITTED and writes PAID_OUT vacation",
                  (s1, s2) == (200, 200) and "COMMITTED" in btxt and "PAID_OUT" in vtxt, f"{s1} {s2} {btxt[:200]} {vtxt[:300]}")
            shot(b, "05_committed", tid(b, "mx-termination"))
            shot(b, "06_vacation_paid_out", tid(b, "mx-vacation"))
            out = subprocess.run([PYTHON, str(HERE / "setup_db.py"), "gen2", MODE], capture_output=True, text=True,
                                 env=os.environ)
            rid2 = db_one("SELECT id FROM payroll_runs WHERE period_label = 'Jun 16-30, 2026'")[0]
            st, txt = api(A0, "GET", f"/api/payroll/runs/{rid2}")
            snap = json.dumps(json.loads(txt)) if st == 200 else txt
            item = db_one("SELECT mx_calculation_snapshot FROM payslip_items WHERE payroll_run_id = ?", rid2)
            days = json.loads(item[0])["result"]["days_paid"] if item and item[0] else None
            check("rules-9 the final ordinary period pays to the termination date (16-20 June = 5 days)",
                  out.returncode == 0 and str(days) in ("5", "5.00", "5.0"), f"days={days} {out.stderr[-300:]}")
            open_run(b, "Jun 16-30, 2026")
            shot(b, "07_final_period_run")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 9c -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
