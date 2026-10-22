"""Mexico Phase 10a (salary payments) browser acceptance — installed
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
A0, A1, NL = "admin0@mx10a.example.com", "admin1@mx10a.example.com", "admin@nl10a.example.com"
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


def open_payments(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)
    return tid(page, "mx-payments")


def click_in(panel, page, name):
    panel.get_by_role("button", name=re.compile(name)).first.click()
    settle(page, 2000)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/payments/batches"), ("POST", "/runs/1/payment-batch"),
                             ("POST", "/payments/batches/1/release"), ("POST", "/payments/batches/1/worklist")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        panel = open_payments(a)
        check("off-2 the payments panel shows the dormancy refusal", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:300])
        shot(a, "01_payments_dormant", panel)
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("off-3 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    else:
        run_id = db_one("SELECT id FROM payroll_runs WHERE period_label = 'Jun 16-30, 2026'")[0]
        a = new_page(browser, A0)
        panel = open_payments(a)
        form = tid(a, "mx-new-payment-batch")
        form.locator("input").first.fill(str(run_id))
        form.get_by_role("button", name="Build payment batch").click()
        settle(a, 2500)
        ptxt = panel.inner_text()
        check(f"{MODE}-1 a batch is built from the committed run: 2 payments, CLABE last 4 only",
              tid(a, "mx-payment-batch").count() == 1 and "DRAFT" in ptxt and "•••• 5678" in ptxt
              and "002180700012345678" not in ptxt, ptxt[:500])
        shot(a, "01_batch_built", tid(a, "mx-payment-batch"))
        click_in(panel, a, "^Release")
        check(f"{MODE}-2 the maker cannot release it (four-eyes)", "MX_FOUR_EYES_REQUIRED" in panel.inner_text(),
              panel.inner_text()[-300:])
        b = new_page(browser, A1)
        bpanel = open_payments(b)
        click_in(bpanel, b, "^Release")
        check(f"{MODE}-3 a second person releases it", "RELEASED" in bpanel.inner_text(), bpanel.inner_text()[:400])
        with b.expect_download() as dl:
            bpanel.get_by_role("button", name="Download worklist").click()
        path = dl.value.path()
        content = Path(path).read_text(encoding="utf-8") if path else ""
        check(f"{MODE}-4 the worklist downloads, labelled NOT A BANK FILE, with the full CLABE (never shown on screen)",
              content.startswith("ZOIKO PAYMENT WORKLIST - NOT A BANK FILE") and "002180700012345678" in content,
              content[:200])
        settle(b, 1500)
        items = bpanel.locator('input[placeholder="SPEI reference"]')
        items.nth(0).fill("SYN-SPEI-0001")
        bpanel.locator("tr").nth(1).get_by_role("button", name="settled").click()
        settle(b, 2000)
        bpanel = open_payments(b)
        bpanel.locator('input[placeholder="SPEI reference"]').nth(0).fill("SYN-RET-0002")
        bpanel.locator("tr").filter(has_text="PENDING").first.get_by_role("button", name="returned").click()
        settle(b, 2000)
        bpanel = open_payments(b)
        btxt = bpanel.inner_text()
        check(f"{MODE}-5 outcomes recorded with references; the batch CLOSES when none is pending",
              "SETTLED" in btxt and "RETURNED" in btxt and "CLOSED" in btxt and "SYN-SPEI-0001" in btxt, btxt[:500])
        click_in(bpanel, b, "Re-issue")
        btxt = bpanel.inner_text()
        check(f"{MODE}-6 the returned payment is re-issued in a new DRAFT batch, linked",
              tid(b, "mx-payment-batch").count() == 2 and "re-issue of #" in btxt and "re-issued as #" in btxt, btxt[:600])
        shot(b, "02_settled_returned_reissued", bpanel)
        st, txt = api(A0, "POST", f"{BASE}/runs/{run_id}/reset", {"reason": "SYNTHETIC"})
        check(f"{MODE}-7 a released batch refuses the run's reset (Phase 6 rule)",
              st == 409 and "payment batch" in txt and "CLOSED" in txt, f"{st} {txt[:200]}")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10a -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
