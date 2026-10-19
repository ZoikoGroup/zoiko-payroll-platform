"""Mexico Phase 8 browser acceptance (installed Chrome, vite preview of the
current build, scratch SQLite backend from setup_db.py via serve.py).

Usage: python acceptance.py off | on — must match how serve.py was started.
Run each mode on a fresh `setup_db.py` database. Screenshots +
RESULTS-<mode>.md go to docs/mexico/phase8-evidence/. Everything is driven
through the UI except the reset attempt (API) and read-only API checks."""
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
MODE = sys.argv[1]
assert MODE in ("on", "off")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = HERE.parent
PASSWORD = "BrowserCheck!2026"
A0, A1, SA, NL = "admin0@mx8.example.com", "admin1@mx8.example.com", "sa-a@mx8.example.com", "admin@nl8.example.com"
BASE = "/api/payroll/mexico"
NSS = "12345678901"
results, errors, responses, _tokens = [], [], [], {}


def token(email):
    if email not in _tokens:                       # login is rate-limited: one login per user
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
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
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
    except Exception:                       # background polling can keep the network busy; the wait below covers it
        pass
    page.wait_for_timeout(ms)


def shot(page, name, locator=None):
    page.wait_for_timeout(400)
    if locator is not None and locator.count():
        locator.first.screenshot(path=str(OUT / f"{MODE}_{name}.png"))
    else:
        page.screenshot(path=str(OUT / f"{MODE}_{name}.png"), full_page=True)


def body(page):
    return page.inner_text("body")


def open_ss(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    tab = page.get_by_role("button", name="Mexico Social Security")
    if tab.count():
        tab.first.click()
        settle(page, 2000)
    return tab.count()


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


def row(panel, text):
    return panel.locator("tr").filter(has_text=text).first


def prompt(scope, button, value=None):
    """Open a PromptButton inside `scope`, type `value`, confirm."""
    scope.get_by_role("button", name=button).first.click()
    if value is not None:
        scope.locator("input").last.fill(value)
    scope.get_by_role("button", name="Confirm").first.click()


def mv_view():
    st, txt = api(A0, "GET", f"{BASE}/authorities/movements")
    return json.loads(txt)[0] if st == 200 and json.loads(txt) else {}


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        n = new_page(browser, NL)
        open_ss(n)
        check("off-1 NL compliance page: no Mexico tabs, no Social Security Center",
              n.get_by_role("button", name="Mexico Social Security").count() == 0 and tid(n, "mx-ss-center").count() == 0,
              body(n)[:300])
        shot(n, "01_nl_compliance")
        a = new_page(browser, A0)
        had_tab = open_ss(a)
        check("off-2 Mexican org: the Social Security tab shows only the dormancy refusal",
              had_tab and tid(a, "mx-ss-refused").count() == 1 and tid(a, "mx-ss-center").count() == 0
              and "not open for onboarding" in tid(a, "mx-ss-refused").inner_text(), body(a)[-600:])
        shot(a, "02_mx_dormant", tid(a, "mx-ss-refused").locator("xpath=.."))
        for method, path in (("GET", "/authorities/summary"), ("POST", "/authorities/accrue"),
                             ("POST", "/authorities/movements/generate"), ("POST", "/authorities/movements/export"),
                             ("GET", "/authorities/liabilities"), ("POST", "/authorities/sua-periods"),
                             ("POST", "/authorities/isn-returns"), ("POST", "/authorities/movements/1/unknown")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-3 {method} {path} -> 403", st == 403, f"{st} {txt[:150]}")
        s = new_page(browser, SA)
        s.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
        settle(s)
        s.get_by_text("MX-PAYROLL-TEST").first.click()
        settle(s)
        s.get_by_text("Authorities", exact=True).first.click()
        settle(s)
        t = tid(s, "mx-authorities")
        ttxt = t.inner_text() if t.count() else ""
        check("off-4 Super Admin 'Authorities' tab: zero counts and the blocks",
              ttxt.count("none") >= 4 and "MX_IDSE_SUA_SIPARE_LAYOUTS" in ttxt and "DUE_DATE_UNSOURCED" in ttxt,
              ttxt[:500] or body(s)[:400])
        shot(s, "03_super_admin_authorities", t)
    else:
        a = new_page(browser, A0)
        open_ss(a)
        c = tid(a, "mx-ss-center")
        ctext = c.inner_text() if c.count() else ""
        check("on-1 Social Security Center: registration card, counts and the blocks",
              c.count() == 1 and "VERIFIED" in tid(a, "mx-ss-cards").inner_text()
              and all(k in tid(a, "mx-ss-blocks").inner_text() for k in ("MX_IDSE_SUA_SIPARE_LAYOUTS", "DUE_DATE_UNSOURCED",
                                                                          "MX_FILING_CALENDAR_EMPTY")),
              ctext[:600] or body(a)[:600])
        shot(a, "01a_cards", tid(a, "mx-ss-cards"))
        shot(a, "01b_blocks", tid(a, "mx-ss-blocks"))

        tid(a, "mx-accrue").click()
        settle(a)
        lp = tid(a, "mx-liabilities")
        ltxt = lp.inner_text()
        check("on-2 accrue: SAT ISR / IMSS / INFONAVIT / ISN from the committed run, every due date unsourced",
              all(k in ltxt for k in ("SAT ISR", "IMSS", "INFONAVIT", "ISN")) and ltxt.count("DUE DATE UNSOURCED") >= 4,
              ltxt[:600])
        shot(a, "02_liabilities_accrued", lp)

        mp = tid(a, "mx-movements")
        mp.get_by_role("button", name="Generate from committed runs").click()
        settle(a)
        mtxt = mp.inner_text()
        check("on-3a ALTA generated from the committed run; NSS masked on screen",
              "ALTA" in mtxt and NSS not in mtxt and "PENDING" in mtxt, mtxt[:500])
        before = mv_view()
        with a.expect_download() as dl:
            tid(a, "mx-export-worklist").click()
        content = Path(dl.value.path()).read_text(encoding="utf-8")
        settle(a)
        check("on-3b worklist download: labelled not-an-IDSE-file, carries the NSS; movement EXPORTED",
              next(csv.reader(io.StringIO(content)))[0].startswith("ZOIKO WORKLIST - NOT AN IMSS / IDSE FILE")
              and NSS in content
              and "EXPORTED" in tid(a, "mx-movements").inner_text(), content[:200])
        shot(a, "03_movement_exported", tid(a, "mx-movements"))

        mrow = row(tid(a, "mx-movements"), "ALTA")
        prompt(mrow, "Outcome unknown…")
        settle(a)
        mrow = row(tid(a, "mx-movements"), "ALTA")
        unk = mrow.locator('[data-testid="mx-authority-unknown"]')
        check("on-4a outcome unknown -> UNKNOWN banner; confirmed retry disabled before any NOT FOUND",
              tid(a, "mx-ss-unknown-banner").count() == 1 and unk.count() == 1
              and unk.get_by_role("button", name=re.compile("Confirm retry")).is_disabled(), body(a)[-800:])
        shot(a, "04a_unknown", tid(a, "mx-movements"))
        unk.get_by_role("button", name="Record NOT FOUND").click()
        settle(a)
        unk = row(tid(a, "mx-movements"), "ALTA").locator('[data-testid="mx-authority-unknown"]')
        prompt(unk, re.compile("Confirm retry"), "SYNTHETIC: IDSE shows nothing for this worker")
        settle(a)
        after = mv_view()
        check("on-4b confirmed retry -> PENDING with the same idempotency key and payload hash",
              after.get("status") == "PENDING" and after.get("idempotencyKey") == before.get("idempotencyKey")
              and after.get("payloadHash") and after.get("payloadHash") == mv_view().get("payloadHash"),
              f"{before.get('idempotencyKey')} / {after}")
        with a.expect_download():
            tid(a, "mx-export-worklist").click()
        settle(a)
        prompt(row(tid(a, "mx-movements"), "ALTA"), "Record FILED…", "SYN-IDSE-ACUSE-1")
        settle(a)
        final_mv = mv_view()
        check("on-4c re-exported (same record) and recorded FILED with the IDSE reference",
              final_mv.get("status") == "FILED" and final_mv.get("authorityReference") == "SYN-IDSE-ACUSE-1"
              and final_mv.get("idempotencyKey") == before.get("idempotencyKey"), str(final_mv)[:300])
        shot(a, "04b_movement_filed", tid(a, "mx-movements"))

        prompt(row(tid(a, "mx-liabilities"), "SAT ISR"), "Record filed…", "SYN-SAT-DECL-1")
        settle(a)
        st, txt = api(A0, "GET", f"{BASE}/runs/1/status")
        lane = json.loads(txt)
        check("on-5 ISR declaration filed; the run's Authorities lane moved, Payroll / CFDI / Bank did not",
              lane["authorities"]["status"] == "IN_PROGRESS" and lane["payroll"]["status"] == "Approved"
              and lane["cfdi"]["status"] == "NOT_STARTED" and lane["bank"]["status"] == "HELD", str(lane)[:400])
        a.goto(APP + "/payroll/payroll-runs", wait_until="load")
        settle(a)
        a.get_by_text("Jun 1-15, 2026").first.click()
        settle(a, 2500)
        shot(a, "05_run_badges", tid(a, "mx-run-status"))

        open_ss(a)
        sp = tid(a, "mx-sua")
        sp.get_by_label("IMSS registration").select_option(index=1)
        sp.get_by_label("Month (YYYY-MM)").fill("2026-06")
        sp.get_by_role("button", name="Open period").click()           # opens the period's detail too
        settle(a)
        st, txt = api(A0, "GET", f"{BASE}/authorities/sua-periods")
        period_id = json.loads(txt)[0]["id"]
        zoiko = json.loads(api(A0, "GET", f"{BASE}/authorities/sua-periods/{period_id}")[1])["zoikoTotals"]
        detail = tid(a, "mx-sua-detail")
        first = sorted(zoiko)[0]
        for key, amount in zoiko.items():
            value = Decimal(amount) + (Decimal("0.01") if key == first else 0)
            detail.get_by_label(f"SUA {key}").fill(str(value))
        detail.get_by_label("SUA version").fill("3.7.1-SYN")
        detail.get_by_role("button", name="Record SUA figures").click()
        settle(a)
        detail = tid(a, "mx-sua-detail")
        dtxt = detail.inner_text()
        check("on-6a a one-cent difference is BLOCKING (zero tolerance)",
              "BLOCKING" in dtxt and "OPEN" in dtxt, dtxt[:500])
        detail.get_by_role("button", name="Reconcile (second person)").click()
        settle(a)
        refused = tid(a, "mx-sua").inner_text()
        detail = tid(a, "mx-sua-detail")
        detail.get_by_label("Explanation code").select_option("SUA_VERSION")
        detail.get_by_label("Explanation", exact=True).fill("SYNTHETIC: SUA rounds per worker")
        detail.get_by_role("button", name="Explain").click()
        settle(a)
        tid(a, "mx-sua-detail").get_by_role("button", name="Approve (second person)").click()
        settle(a)
        self_approve = tid(a, "mx-sua").inner_text()
        check("on-6b reconcile refused while open; the explainer cannot approve their own explanation",
              "MX_SUA_DIFFERENCES_OPEN" in refused and "MX_FOUR_EYES_REQUIRED" in self_approve,
              refused[-300:] + " | " + self_approve[-300:])
        shot(a, "06a_sua_blocking", tid(a, "mx-sua"))
        b = new_page(browser, A1)
        open_ss(b)
        tid(b, "mx-sua").get_by_role("button", name="Open", exact=True).first.click()
        settle(b)
        tid(b, "mx-sua-detail").get_by_role("button", name="Approve (second person)").click()
        settle(b)
        tid(b, "mx-sua-detail").get_by_role("button", name="Reconcile (second person)").click()
        settle(b)
        st, txt = api(A1, "GET", f"{BASE}/authorities/sua-periods/{period_id}")
        sua = json.loads(txt)
        check("on-6c a second person approves and reconciles the SUA period",
              sua["status"] == "RECONCILED" and sua["openDifferences"] == 0, str(sua)[:300])
        shot(b, "06b_sua_reconciled", tid(b, "mx-sua"))

        ip = tid(a, "mx-isn-returns")
        open_ss(a)
        ip = tid(a, "mx-isn-returns")
        ip.get_by_label("ISN month (YYYY-MM)").fill("2026-06")
        ip.get_by_role("button", name="Draft / refresh / amend").click()
        settle(a)
        ip = tid(a, "mx-isn-returns")
        row(ip, "CDMX").get_by_role("button", name="Reconciliation").click()
        settle(a)
        rec = tid(a, "mx-isn-reconciliation")
        rtxt = rec.inner_text() if rec.count() else ""
        prompt(row(tid(a, "mx-isn-returns"), "CDMX"), "Record filed…", "SYN-CDMX-FOLIO-1")
        settle(a)
        open_ss(b)
        row(tid(b, "mx-isn-returns"), "CDMX").get_by_role("button", name="Accepted (second person)").click()
        settle(b)
        st, txt = api(A1, "GET", f"{BASE}/authorities/isn-returns")
        ret = json.loads(txt)[0]
        check("on-7 ISN return = employee detail = ledger; filed, then ACCEPTED by a second person",
              "RECONCILED" in rtxt and ret["status"] == "ACCEPTED" and ret["filingReference"] == "SYN-CDMX-FOLIO-1",
              rtxt + " | " + str(ret)[:300])
        shot(b, "07_isn_accepted", tid(b, "mx-isn-returns"))

        st, txt = api(A1, "POST", f"{BASE}/runs/1/reset", {"reason": "SYNTHETIC reset attempt"})
        check("on-8 reset refused once filings acted (MX_RESET_DOWNSTREAM_ACTED, naming them)",
              st == 409 and "MX_RESET_DOWNSTREAM_ACTED" in txt and "ISN return" in txt and "IMSS movement" in txt,
              f"{st} {txt[:400]}")

        n = new_page(browser, NL)
        open_ss(n)
        check("on-9 NL compliance page unchanged — no Mexico tabs",
              n.get_by_role("button", name="Mexico Social Security").count() == 0, "")
        shot(n, "08_nl_regression")
        s = new_page(browser, SA)
        s.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
        settle(s)
        s.get_by_text("MX-PAYROLL-TEST").first.click()
        settle(s)
        s.get_by_text("Authorities", exact=True).first.click()
        settle(s)
        t = tid(s, "mx-authorities")
        ttxt = t.inner_text() if t.count() else ""
        check("on-10 Super Admin Authorities tab counts the objects (read-only)",
              "FILED 1" in ttxt and "RECONCILED 1" in ttxt and "ACCEPTED 1" in ttxt, ttxt[:500])
        shot(s, "09_super_admin_authorities", t)
    browser.close()

expected = {("POST", f"{BASE}/runs/1/reset")}
unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 8 -- browser check (flag {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
