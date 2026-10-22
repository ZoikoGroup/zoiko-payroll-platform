"""Mexico Phase 10b (payroll journal) browser acceptance — installed
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
A0, A1, NL = "admin0@mx10b.example.com", "admin1@mx10b.example.com", "admin@nl10b.example.com"
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


LINE_TYPES = ["WAGES_EXPENSE", "IMSS_EMPLOYER_EXPENSE", "INFONAVIT_EMPLOYER_EXPENSE", "ISN_EXPENSE",
              "NET_PAY_PAYABLE", "ISR_PAYABLE", "IMSS_EMPLOYEE_PAYABLE", "IMSS_EMPLOYER_PAYABLE",
              "INFONAVIT_EMPLOYER_PAYABLE", "INFONAVIT_CREDIT_PAYABLE", "ISN_PAYABLE", "OTHER_DEDUCTIONS_PAYABLE"]


def open_journal(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)
    return tid(page, "mx-journal")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/journal/mappings"), ("POST", "/journal/mappings"),
                             ("GET", "/runs/1/journal"), ("POST", "/runs/1/journal/export")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        panel = open_journal(a)
        check("off-2 the journal panel shows the dormancy refusal", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:300])
        shot(a, "01_journal_dormant", panel)
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    else:
        run_id = db_one("SELECT id FROM payroll_runs WHERE period_label = 'Jun 16-30, 2026'")[0]
        a = new_page(browser, A0)
        panel = open_journal(a)
        form = tid(a, "mx-new-journal-mapping")
        for n_, code in enumerate(LINE_TYPES, start=100):
            form.locator(f'input[name="{code}"]').fill(f"SYN-{n_}")
        form.locator('input[name="note"]').fill("SYNTHETIC chart")
        form.get_by_role("button", name="Propose mapping").click()
        settle(a, 2500)
        mtxt = tid(a, "mx-journal-mappings").inner_text().upper()
        check(f"{MODE}-1 a mapping is proposed as DRAFT v1 with every line type", "V1" in mtxt and "DRAFT" in mtxt
              and "12 MAPPED" in mtxt, mtxt[:400])
        panel.get_by_role("button", name=re.compile("^Approve")).first.click()
        settle(a, 2000)
        check(f"{MODE}-2 its maker cannot approve it (four-eyes)", "MX_FOUR_EYES_REQUIRED" in panel.inner_text(),
              panel.inner_text()[:400])
        b = new_page(browser, A1)
        bpanel = open_journal(b)
        bpanel.get_by_role("button", name=re.compile("^Approve")).first.click()
        settle(b, 2000)
        check(f"{MODE}-3 a second person approves it", "APPROVED" in tid(b, "mx-journal-mappings").inner_text().upper(),
              tid(b, "mx-journal-mappings").inner_text()[:300])
        rform = tid(b, "mx-journal-run")
        rform.locator("input").first.fill(str(run_id))
        rform.get_by_role("button", name="Show journal").click()
        settle(b, 2500)
        jtxt = tid(b, "mx-run-journal").inner_text()
        up = jtxt.upper()
        check(f"{MODE}-4 the run's journal balances, each liability on its own line, accounts from v1",
              "BALANCED" in up and "UNBALANCED" not in up and all(t in jtxt for t in (
                  "ISR_PAYABLE", "IMSS_EMPLOYEE_PAYABLE", "IMSS_EMPLOYER_PAYABLE", "ISN_PAYABLE", "NET_PAY_PAYABLE"))
              and "SYN-105" in jtxt and "UNMAPPED" not in up, jtxt[:700])
        check(f"{MODE}-5 no worker is named in the journal", "Sintética" not in jtxt and "Persona" not in jtxt, "")
        shot(b, "01_journal_balanced", tid(b, "mx-run-journal"))
        with b.expect_download() as dl:
            tid(b, "mx-run-journal").get_by_role("button", name="Export journal (CSV)").click()
        path = dl.value.path()
        content = Path(path).read_text(encoding="utf-8") if path else ""
        rows = content.splitlines()
        total = rows[-1].split(",") if rows else []
        check(f"{MODE}-6 the CSV downloads, labelled NOT POSTED, and its debits equal its credits",
              content.startswith("ZOIKO PAYROLL JOURNAL - NOT POSTED TO ANY LEDGER") and total[:1] == ["TOTAL"]
              and total[3] == total[4] and "Sintética" not in content, content[:300])
        settle(b, 1500)
        st, txt = api(A0, "POST", f"{BASE}/runs/{run_id}/reset", {"reason": "SYNTHETIC"})
        check(f"{MODE}-7 a current journal export refuses the run's reset", st == 409 and "journal export" in txt,
              f"{st} {txt[:200]}")
        bpanel = open_journal(b)
        rform = tid(b, "mx-journal-run")
        rform.locator("input").first.fill(str(run_id))
        rform.get_by_role("button", name="Show journal").click()
        settle(b, 2500)
        rj = tid(b, "mx-run-journal")
        rj.locator('input[placeholder="reason (reversed / never posted)"]').first.fill("SYNTHETIC: reversed")
        rj.get_by_role("button", name="Void").first.click()
        settle(b, 2500)
        vtxt = tid(b, "mx-run-journal").inner_text()
        check(f"{MODE}-8 the export is voided with its reason", "VOIDED" in vtxt.upper()
              and "SYNTHETIC: reversed" in vtxt, vtxt[-400:])
        shot(b, "02_export_voided", tid(b, "mx-run-journal"))
        st, txt = api(A0, "POST", f"{BASE}/runs/{run_id}/reset", {"reason": "SYNTHETIC"})
        check(f"{MODE}-9 once voided, the journal no longer blocks the reset", "journal export" not in txt,
              f"{st} {txt[:200]}")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10b -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
