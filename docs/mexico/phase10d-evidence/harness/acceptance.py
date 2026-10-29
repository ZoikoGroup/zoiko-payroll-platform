"""Mexico Phase 10d (release gates) browser acceptance — installed
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
A0, A1, NL = "admin0@mx10d.example.com", "admin1@mx10d.example.com", "admin@nl10d.example.com"
SA_A, SA_B = "sa-a@mx10d.example.com", "sa-b@mx10d.example.com"
SA = "/api/super-admin/compliance"
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


def upload(email, artifact_id, name, data):
    boundary = "zoikoMX10dBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}{SA}/source-artifacts/{artifact_id}/upload", method="POST", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "Authorization": f"Bearer {token(email)['access_token']}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def open_readiness(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name="Readiness G1–G8", exact=True).first.click()
    settle(page, 2500)
    return tid(page, "mx-release-gates")


def gate_row(page, gate):
    return tid(page, "mx-release-gates").locator("tr").filter(has_text=f"MX-GATE-{gate}")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    gates = open_readiness(a)
    gtxt = gates.inner_text()
    states = [gate_row(a, f"G{i}").inner_text().split("	")[-1].strip().upper() for i in range(1, 9)]
    check(f"{MODE}-1 the readiness view lists G1-G8 with their evidence tags, every gate OPEN",
          all(f"MX-GATE-G{i}" in gtxt for i in range(1, 9)) and states == ["OPEN"] * 8, f"{states} {gtxt[:300]}")
    body = a.locator("main").inner_text() if a.locator("main").count() else a.inner_text("body")
    check(f"{MODE}-2 0/8 signed, onboarding off, not available; 3 legal decisions OPEN; 8 retention categories blocked",
          "Gates signed: 0/8" in body and "Onboarding flag: off" in body and "Available: No" in body
          and tid(a, "mx-owner-decisions").inner_text().upper().count("OPEN") == 3
          and tid(a, "mx-retention").inner_text().upper().count("BLOCKED_UNDECIDED") == 8, body[:600])
    check(f"{MODE}-3 the release documents are named", all(d in tid(a, "mx-release-documents").inner_text() for d in (
        "release-gates/README.md", "MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md", "MEXICO_RELEASE_CHECKLIST.md",
        "MEXICO_UNKNOWN_STATE_RUNBOOK.md")), tid(a, "mx-release-documents").inner_text())
    shot(a, "01_gates_open", tid(a, "mx-release-gates"))
    st, txt = api(SA_A, "POST", f"{SA}/source-artifacts", {"agency": "Zoiko (SYNTHETIC)",
                                                            "title": "G1 evidence pack (SYNTHETIC)",
                                                            "formNumber": "MX-GATE-G1"})
    art = json.loads(txt)["id"] if st == 200 else None
    up = upload(SA_A, art, "g1-evidence-SYNTHETIC.pdf", b"%PDF-1.4 SYNTHETIC G1 evidence pack") if art else (0, "")
    gates = open_readiness(a)
    check(f"{MODE}-4 an uploaded, unreviewed G1 pack shows SUBMITTED",
          st == 200 and up[0] == 200 and "SUBMITTED" in gate_row(a, "G1").inner_text().upper(),
          f"{st} {up[0]} {gate_row(a, 'G1').inner_text() if gate_row(a, 'G1').count() else ''}")
    st2, txt2 = api(SA_A, "PUT", f"{SA}/source-artifacts/{art}/review", {})
    check(f"{MODE}-5 its uploader cannot review it", st2 == 400 and "reviewer different" in txt2, f"{st2} {txt2[:200]}")
    b = new_page(browser, SA_B)
    b.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(b)
    b.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(b, 1500)
    b.get_by_role("button", name="Sources", exact=True).first.click()
    settle(b, 2000)
    b.locator("tr").filter(has_text="MX-GATE-G1").get_by_role("button", name="Mark reviewed").first.click()
    settle(b, 2000)
    open_readiness(b)
    row = gate_row(b, "G1").inner_text()
    check(f"{MODE}-6 a second Super Admin marks it reviewed on the Sources tab: G1 SIGNED, linked to its source",
          "SIGNED" in row.upper() and f"#{art}" in row, row)
    body = b.locator("main").inner_text() if b.locator("main").count() else b.inner_text("body")
    check(f"{MODE}-7 1/8 signed and Mexico still not available", "Gates signed: 1/8" in body and "Available: No" in body,
          body[:400])
    shot(b, "02_g1_signed", tid(b, "mx-release-gates"))
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 10d -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
