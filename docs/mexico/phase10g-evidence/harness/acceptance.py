"""Mexico Phase 10g (no-new-organisations switch) browser acceptance — installed
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
A0, A1, NL = "admin0@mx10g.example.com", "admin1@mx10g.example.com", "admin@nl10g.example.com"
L0, L1 = "admin0@live10g.example.com", "admin1@live10g.example.com"
SA_A, SA_B = "sa-a@mx10g.example.com", "sa-b@mx10g.example.com"
NEWCOMER = "admin@new10g.example.com"
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


def open_readiness(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name="Readiness G1–G8", exact=True).first.click()
    settle(page, 2500)
    return tid(page, "mx-onboarding-pause")


def open_centre(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2500)
    return tid(page, "mx-compliance-centre")


def become_mexican():
    return api(NEWCOMER, "PUT", "/api/organizations/me", {"country": "Mexico"})


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    cand = db_one("SELECT id FROM payroll_mx_pilot_grants WHERE status = 'PROPOSED'")[0]
    a = new_page(browser, SA_A)
    panel = open_readiness(a)
    check(f"{MODE}-1 the switch shows new Mexican organisations OPEN", tid(a, "mx-onboarding-state").inner_text() == "OPEN",
          panel.inner_text()[:300])
    panel.locator('input[aria-label="Pause reason"]').fill("SYNTHETIC: a go-live check failed")
    panel.get_by_role("button", name="Propose pause").click()
    settle(a, 2500)
    panel = open_readiness(a)
    panel.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(a, 2000)
    check(f"{MODE}-2 the proposer cannot approve the pause (four-eyes)", "MX_FOUR_EYES_REQUIRED" in panel.inner_text(),
          panel.inner_text()[-300:])
    b = new_page(browser, SA_B)
    bpanel = open_readiness(b)
    bpanel.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(b, 2500)
    bpanel = open_readiness(b)
    pre = tid(b, "mx-pilot-preconditions").inner_text()
    check(f"{MODE}-3 a second Super Admin approves: PAUSED; the pilot precondition shows it",
          tid(b, "mx-onboarding-state").inner_text() == "PAUSED" and "not paused (runbook §6): paused" in pre,
          f"{tid(b, 'mx-onboarding-state').inner_text()} {pre[-200:]}")
    shot(b, "01_paused", bpanel)
    st, txt = become_mexican()
    check(f"{MODE}-4 while paused, a new organisation cannot become Mexican (the pause message)",
          st == 400 and "paused" in txt, f"{st} {txt[:200]}")
    st, txt = api(SA_B, "POST", f"/api/super-admin/compliance/mexico/pilot-grants/{cand}/approve", {})
    check(f"{MODE}-5 while paused, a pilot grant cannot be approved", st == 400 and "not paused" in txt, f"{st} {txt[:200]}")
    o = new_page(browser, A0)
    centre = open_centre(o)
    check(f"{MODE}-6 an organisation that is already Mexican keeps running", "not open for onboarding" not in centre.inner_text()
          and "paused" not in centre.inner_text().lower(), centre.inner_text()[:300])
    shot(o, "02_existing_org_runs", centre)
    bpanel = open_readiness(b)
    bpanel.locator('input[aria-label="Pause reason"]').fill("SYNTHETIC: fixed and proven")
    bpanel.get_by_role("button", name="Propose resume").click()
    settle(b, 2500)
    panel = open_readiness(a)
    panel.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(a, 2500)
    panel = open_readiness(a)
    check(f"{MODE}-7 resumed by two Super Admins: OPEN, with both changes listed",
          tid(a, "mx-onboarding-state").inner_text() == "OPEN" and panel.inner_text().upper().count("APPROVED") >= 2,
          panel.inner_text()[:400])
    shot(a, "03_resumed", panel)
    st, txt = become_mexican()
    check(f"{MODE}-8 after resume, the new organisation can become Mexican", st == 200, f"{st} {txt[:200]}")
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10g -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
