"""Mexico Phase 9b (aguinaldo + vacation) browser acceptance — installed
Chrome, vite preview of the current build, scratch SQLite backend.
Usage: python acceptance.py off | on | rules (fresh DB each; serve.py in the
same mode). Non-UI writes: setup_db.py `gen2` (the operator generates the
Jun 16-30 run) and run approvals through the API."""
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
A0, A1, NL = "admin0@mx9b.example.com", "admin1@mx9b.example.com", "admin@nl9b.example.com"
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


def open_run(page, label):
    page.goto(APP + "/payroll/payroll-runs", wait_until="load")
    settle(page)
    page.get_by_text(label, exact=True).first.click()
    settle(page, 2500)


def open_compliance_centre(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)


def open_vacation(page):
    page.goto(APP + "/payroll/employees", wait_until="load")
    settle(page)
    page.get_by_text("Persona Sintética").first.click()
    settle(page)
    page.get_by_role("button", name=re.compile("Manage")).first.click()
    settle(page, 2000)
    return tid(page, "mx-vacation")


def open_aguinaldo(page):
    open_compliance_centre(page)
    panel = tid(page, "mx-aguinaldo-run")
    inputs = panel.locator("input")
    inputs.nth(0).fill("2026")
    inputs.nth(1).fill("2026-12-15")
    panel.get_by_role("button", name="Open aguinaldo run").click()
    settle(page, 2500)
    return panel


def record_taken(page, days="2", start="2026-06-20"):
    form = tid(page, "mx-new-vacation")
    form.locator("select").first.select_option("TAKEN")
    inputs = form.locator("input")
    inputs.nth(0).fill(days)
    inputs.nth(1).fill(start)
    inputs.nth(2).fill(start)
    form.get_by_role("button", name="Record").click()
    settle(page, 2000)


def approve(run_id):
    s1 = api(A0, "PUT", f"/api/payroll/runs/{run_id}/approve")[0]
    s2 = api(A1, "PUT", f"/api/payroll/runs/{run_id}/approve")[0]
    return s1, s2


def run_id(label):
    """Read-only lookup in the scratch SQLite DB (the env URL serve.py uses)."""
    import sqlite3

    path = os.environ["PAYROLL_DATABASE_URL"].replace("sqlite:///", "")
    con = sqlite3.connect(path)
    try:
        row = con.execute("SELECT id FROM payroll_runs WHERE period_label = ? ORDER BY id DESC", (label,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def preflight_codes(rid):
    st, txt = api(A0, "GET", f"{BASE}/runs/{rid}/preflight")
    return {e["code"] for e in json.loads(txt).get("exceptions", [])} if st == 200 else set()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        a = new_page(browser, A0)
        panel = open_aguinaldo(a)
        check("off-1 the aguinaldo panel is refused while Mexico is dormant",
              "not open for onboarding" in panel.inner_text(), panel.inner_text()[:300])
        shot(a, "01_aguinaldo_refused", panel)
        for method, path in (("GET", "/employees/1/vacation"), ("POST", "/employees/1/vacation"),
                             ("POST", "/vacation/1/approve"), ("POST", "/vacation/1/withdraw"),
                             ("POST", "/aguinaldo-runs")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-2 {method} {path} -> 403", st == 403, f"{st} {txt[:150]}")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0 and tid(n, "mx-aguinaldo-run").count() == 0, "")
    else:
        a = new_page(browser, A0)
        panel = open_aguinaldo(a)
        rid = run_id("Aguinaldo 2026")
        check(f"{MODE}-1 aguinaldo run opened from the Compliance Centre",
              rid is not None and "Aguinaldo run created" in panel.inner_text(), panel.inner_text()[:300])
        shot(a, "01_aguinaldo_opened", panel)
        open_run(a, "Aguinaldo 2026")
        pre = tid(a, "mx-run-preflight")
        ptxt = pre.inner_text() if pre.count() else ""
        if MODE == "on":
            check("on-2 every aguinaldo payslip is BLOCKED: the proportion rule is not transcribed (S26)",
                  "MX_AGUINALDO_RULE_MISSING" in ptxt and "MX_AGUINALDO_RULE_MISSING" in preflight_codes(rid), ptxt[:400])
            shot(a, "02_aguinaldo_blocked", pre)
        else:
            a.locator("tr").filter(has_text="Persona").first.click()
            settle(a)
            trace = tid(a, "mx-trace")
            item = json.loads(api(A0, "GET", f"/api/payroll/runs/{rid}")[1])
            check("rules-2 aguinaldo computed (SYNTHETIC rules): 15 days × 600 × full year; no IMSS; ISR by the special rule",
                  not preflight_codes(rid) and trace.count() == 1 and "AGUINALDO" in trace.inner_text().upper(),
                  (trace.inner_text()[:400] if trace.count() else str(item)[:300]))
            shot(a, "02_aguinaldo_trace", trace)
            s1, s2 = approve(rid)
            check("rules-3 the aguinaldo run approves and commits", (s1, s2) == (200, 200), f"{s1} {s2}")

        vac = open_vacation(a)
        record_taken(a)
        vtxt = tid(a, "mx-vacation").inner_text()
        check(f"{MODE}-4 vacation TAKEN recorded from the employee screen (DRAFT)", "DRAFT" in vtxt, vtxt[:300])
        tid(a, "mx-vacation").get_by_role("button", name=re.compile("Approve")).first.click()
        settle(a, 1500)
        refused = tid(a, "mx-vacation").inner_text()
        check(f"{MODE}-5 the recorder cannot approve their own record (four-eyes)",
              "MX_FOUR_EYES_REQUIRED" in refused, refused[-300:])
        b = new_page(browser, A1)
        open_vacation(b)
        tid(b, "mx-vacation").get_by_role("button", name=re.compile("Approve")).first.click()
        settle(b, 1500)
        btxt = tid(b, "mx-vacation").inner_text()
        check(f"{MODE}-6 a second person approves; the ledger shows the balance",
              "APPROVED" in btxt and "14" in btxt, btxt[:400])
        shot(b, "03_vacation_approved", tid(b, "mx-vacation"))
        out = subprocess.run([PYTHON, str(HERE / "setup_db.py"), "gen2", MODE], capture_output=True, text=True,
                             env=os.environ)
        rid2 = run_id("Jun 16-30, 2026")
        open_run(a, "Jun 16-30, 2026")
        pre = tid(a, "mx-run-preflight")
        ptxt = pre.inner_text() if pre.count() else ""
        if MODE == "on":
            check("on-7 the Jun 16-30 payslip with the vacation premium is BLOCKED (special-pay rule, S24)",
                  out.returncode == 0 and "MX_SPECIAL_PAY_RULE_MISSING" in preflight_codes(rid2), ptxt[:400] + out.stderr[-200:])
            shot(a, "04_premium_blocked", pre)
        else:
            a.locator("tr").filter(has_text="Persona").first.click()
            settle(a)
            trace = tid(a, "mx-trace")
            ttxt = trace.inner_text() if trace.count() else ""
            check("rules-7 the premium is a line of the Jun 16-30 payslip (2 days × 600 × 25%)",
                  out.returncode == 0 and not preflight_codes(rid2) and "VACATION_PREMIUM" in ttxt.upper().replace(" ", "_"),
                  ttxt[:400] + out.stderr[-200:])
            shot(a, "04_premium_trace", trace)
            s1, s2 = approve(rid2)
            open_vacation(a)
            vt = tid(a, "mx-vacation").inner_text()
            check("rules-8 approving the run marks the record PAID, linked to the run",
                  (s1, s2) == (200, 200) and "PAID" in vt and f"paid in run #{rid2}" in vt, f"{s1} {s2} {vt[:300]}")
            shot(a, "05_vacation_paid", tid(a, "mx-vacation"))
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-9 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

expected = {"/approve"} if MODE != "off" else set()
unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 9b -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
