"""Mexico Phase 11a (pinned SAT set, system concepts) browser acceptance — installed
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
A0, A1, NL = "admin0@mx11a.example.com", "admin1@mx11a.example.com", "admin@nl11a.example.com"
L0, L1 = "admin0@live11a.example.com", "admin1@live11a.example.com"
SA_A, SA_B = "sa-a@mx11a.example.com", "sa-b@mx11a.example.com"
NEWCOMER = "admin@new11a.example.com"
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


def open_catalogs(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name="CFDI catalogs", exact=True).first.click()
    settle(page, 2500)
    return tid(page, "mx-pinned-sets")


def release_row(page, rid):
    return page.locator("tr").filter(has=page.get_by_role("cell", name=str(rid), exact=True)).first


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    pinned = open_catalogs(a)
    text = pinned.inner_text()
    check(f"{MODE}-1 the pinned SAT set is listed and verified", "sat_2026_08" in text and "Verified" in text
          and "4.0 / 1.2" in text, text[:300])
    shot(a, "01_pinned_set", pinned)
    a.get_by_label("CFDI version").fill("4.0")
    a.get_by_label("Complement version").fill("1.2")
    a.get_by_role("button", name="Register release").click()
    settle(a, 2000)
    rid = db_one("SELECT max(id) FROM payroll_mx_cfdi_schema_releases")[0]
    open_catalogs(a)
    release_row(a, rid).get_by_role("button", name="Load sat_2026_08").click()
    settle(a, 20000)
    open_catalogs(a)
    loaded = db_one("SELECT count(*) FROM payroll_mx_cfdi_catalog_entries WHERE schema_release_id = ?", rid)[0]
    expected = sum(json.loads((Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend\app\modules\payroll"
                                    r"\mx_cfdi_schemas\sat_2026_08\manifest.json")).read_text(encoding="utf-8"))
                   ["catalogCounts"].values())
    row_text = release_row(a, rid).inner_text()
    check(f"{MODE}-2 loading fills the Draft release from the set (every catalog row, the set recorded)",
          loaded == expected and "sat_2026_08" in row_text and str(expected) in row_text.replace(",", ""),
          f"{loaded} of {expected}; row: {row_text[:200]}")
    release_row(a, rid).get_by_role("button", name="Entries").click()
    settle(a, 2500)
    entries = tid(a, "mx-cfdi-entries")
    entries.get_by_label("Catalog filter").select_option("c_TipoPercepcion")
    settle(a, 2500)
    total = tid(a, "mx-cfdi-entries-total").inner_text()
    entries.get_by_label("Catalog search").fill("Aguinaldo")
    entries.get_by_role("button", name="Search").click()
    settle(a, 2500)
    found = tid(a, "mx-cfdi-entries").inner_text()
    check(f"{MODE}-3 entries are filtered by catalog and searchable (not one 150,000-row list)",
          total.startswith("44 matching") and "Gratificación Anual (Aguinaldo)" in found and "1 matching" in found,
          f"{total} / {found[-300:]}")
    shot(a, "02_entries_filtered", tid(a, "mx-cfdi-entries"))
    open_catalogs(a)
    release_row(a, rid).get_by_role("button", name="submit").click()
    settle(a, 2000)
    release_row(a, rid).get_by_role("button", name="approve").click()
    settle(a, 2000)
    own = a.get_by_text(re.compile("different Super Admin must approve")).count() > 0
    b = new_page(browser, SA_B)
    open_catalogs(b)
    release_row(b, rid).get_by_role("button", name="approve").click()
    settle(b, 2000)
    open_catalogs(b)
    check(f"{MODE}-4 the loaded release is approved four-eyes (the loader cannot approve it)",
          own and "Approved" in release_row(b, rid).inner_text(), release_row(b, rid).inner_text()[:200])
    open_catalogs(a)
    panel = tid(a, "mx-cfdi-system-concepts")
    panel.get_by_label("Concept release").select_option(str(rid))
    settle(a, 1500)
    panel.get_by_label("Concept key").select_option("ISR_WITHHELD")
    panel.get_by_label("Concept node").select_option("OTRO_PAGO")
    panel.get_by_label("Concept SAT code").fill("101")
    panel.get_by_label("Concept source").fill("S28 c_TipoDeduccion row 106 (SYNTHETIC wrong node)")
    panel.get_by_role("button", name="Propose").click()
    settle(a, 2000)
    refused = "not in c_TipoOtroPago" in tid(a, "mx-cfdi-system-concepts").inner_text()
    check(f"{MODE}-5 a code outside the node's own catalog is refused", refused,
          tid(a, "mx-cfdi-system-concepts").inner_text()[-300:])
    panel = tid(a, "mx-cfdi-system-concepts")
    panel.get_by_label("Concept node").select_option("DEDUCCION")
    panel.get_by_label("Concept SAT code").fill("002")
    panel.get_by_label("Concept source").fill("S28 c_TipoDeduccion row 7; S4 p. 113")
    panel.get_by_role("button", name="Propose").click()
    settle(a, 2000)
    panel = tid(a, "mx-cfdi-system-concepts")
    panel.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(a, 2000)
    four_eyes = "different Super Admin" in tid(a, "mx-cfdi-system-concepts").inner_text()
    open_catalogs(b)
    bpanel = tid(b, "mx-cfdi-system-concepts")
    bpanel.get_by_role("button", name=re.compile("^Approve")).first.click()
    settle(b, 2500)
    open_catalogs(b)
    bpanel = tid(b, "mx-cfdi-system-concepts")
    t = bpanel.inner_text()
    check(f"{MODE}-6 ISR_WITHHELD -> DEDUCCION 002 proposed, refused to its proposer, approved by a second Super Admin",
          four_eyes and "ISR_WITHHELD" in t and "APPROVED" in t and "S4 p. 113" in t, t[-400:])
    shot(b, "03_system_concept_approved", bpanel)
    over, _ = api(SA_B, "GET", f"{SA}/cfdi-catalogs/{rid}/entries?catalog=c_CodigoPostal&limit=5000")
    st, txt = api(SA_B, "GET", f"{SA}/cfdi-catalogs/{rid}/entries?catalog=c_CodigoPostal&limit=1000")
    body = json.loads(txt) if st == 200 else {}
    check(f"{MODE}-7 a large catalog is capped per request (c_CodigoPostal: over 1000 refused, 1000 returned)",
          over == 422 and st == 200 and len(body.get("entries", [])) == 1000 and body.get("total", 0) > 90000,
          f"{over} / {st} {txt[:200]}")
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check(f"{MODE}-z1 NL compliance page unchanged", n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z2 no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 11a -- browser check (mode {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
