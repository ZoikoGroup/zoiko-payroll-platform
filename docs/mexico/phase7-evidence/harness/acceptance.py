"""Mexico Phase 7 browser acceptance (installed Chrome, vite preview of the
current build, scratch SQLite backend from setup_db.py via serve.py).

Usage: python acceptance.py off | on — must match how serve.py was started.
Run `off` first (fresh `init` DB). For `on`, the script calls setup_db.py
`release` and `replace` itself (SYNTHETIC rows, scratch DB only) and scripts
the mock PAC through patches.CONTROL. Screenshots + RESULTS-<mode>.md go to
docs/mexico/phase7-evidence/."""
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
sys.path.insert(0, str(HERE))
from patches import CALLS, CONTROL  # noqa: E402

MODE = sys.argv[1]
assert MODE in ("on", "off")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = HERE.parent
PYTHON = r"C:\Users\Nikhi\AppData\Local\Programs\Python\Python311\python.exe"
PASSWORD = "BrowserCheck!2026"
A0, A1, SA, NL = "admin0@mx7.example.com", "admin1@mx7.example.com", "sa-a@mx7.example.com", "admin@nl7.example.com"
BASE = "/api/payroll/mexico"
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


def setup(step):
    out = subprocess.run([PYTHON, str(HERE / "setup_db.py"), step], capture_output=True, text=True, env=os.environ)
    assert out.returncode == 0, out.stderr[-1500:]
    return out.stdout


def pac_script(**script):
    CONTROL.write_text(json.dumps(script))


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
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page, name, locator=None):
    page.wait_for_timeout(500)
    if locator is not None and locator.count():
        locator.first.screenshot(path=str(OUT / f"{MODE}_{name}.png"))
    else:
        page.screenshot(path=str(OUT / f"{MODE}_{name}.png"), full_page=True)


def open_run(page, label):
    page.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
    settle(page)
    page.get_by_text(label).first.click()
    settle(page, 2500)


def body(page):
    return page.inner_text("body")


def stage(page):
    return page.locator('[data-testid="mx-cfdi-stage"]')


def click_stage(page, name):
    stage(page).get_by_role("button", name=name).click()
    settle(page, 2000)


def open_drawer(page, row=0):
    stage(page).locator('[data-testid="mx-cfdi-row"]').nth(row).get_by_role("button", name="Details").click()
    settle(page)
    return page.locator('[data-testid="mx-cfdi-drawer"]')


def close_drawer(page):
    page.locator('[data-testid="mx-cfdi-drawer"]').get_by_role("button", name="Close").first.click()
    settle(page)


def open_cfdi_lifecycle(page):
    page.get_by_text("MX-PAYROLL-TEST").first.click()        # the pack's tabs appear once a pack is selected
    settle(page)
    page.get_by_text("CFDI lifecycle", exact=True).first.click()
    settle(page)


def badges(page):
    b = page.locator('[data-testid="mx-run-status"]')
    return {k: b.locator(f'[data-testid="mx-badge-{k}"]').inner_text().replace("\n", " ")
            for k in ("payroll", "cfdi", "authorities", "bank")} if b.count() else {}


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
        settle(n)
        check("off-1 NL org run screen loads, no Mexico CFDI panel",
              "Payroll" in body(n) and stage(n).count() == 0, body(n)[:300])
        shot(n, "01_nl_runs")
        a = new_page(browser, A0)
        open_run(a, "Jun 1-15, 2026")
        check("off-2 the Mexican run shows only the dormancy refusal (no CFDI stage, no badges)",
              "not open for onboarding" in body(a) and stage(a).count() == 0
              and a.locator('[data-testid="mx-run-status"]').count() == 0, body(a)[-800:])
        a.get_by_text(re.compile("not open for onboarding")).first.scroll_into_view_if_needed()
        a.wait_for_timeout(500)
        a.screenshot(path=str(OUT / "off_02_mx_run_dormant.png"))      # viewport: the drawer scrolls on its own
        for method, path in (("GET", "/runs/1/cfdi"), ("POST", "/runs/1/cfdi/generate"), ("POST", "/cfdi/outbox/process"),
                             ("GET", "/cfdi/documents/1"), ("POST", "/cfdi/documents/1/status-query"),
                             ("GET", "/cfdi/cancellation-reasons"), ("POST", "/cfdi/reconcile")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-3 {method} {path} -> 403", st == 403, f"{st} {txt[:150]}")
        s = new_page(browser, SA)
        s.goto(APP + "/super-admin/compliance/mexico", wait_until="networkidle")
        settle(s)
        open_cfdi_lifecycle(s)
        lc = s.locator('[data-testid="mx-cfdi-lifecycle"]')
        ltxt = lc.inner_text() if lc.count() else ""
        check("off-4 Super Admin 'CFDI lifecycle' tab: zero documents and the three production blocks",
              "0 document(s)" in ltxt and all(c in ltxt for c in ("MX_CFDI_BUILDER_BLOCKED", "MX_CSD_SIGNING_BLOCKED",
                                                                  "MX_PAC_NOT_CONFIGURED")), ltxt[:500] or body(s)[:500])
        shot(s, "03_super_admin_cfdi_lifecycle", lc)
    else:
        for f in (CONTROL, CALLS):
            f.unlink(missing_ok=True)
        a = new_page(browser, A0)
        open_run(a, "Jun 1-15, 2026")
        before = badges(a)
        pre = a.locator('[data-testid="mx-cfdi-preflight"]')
        check("on-1 committed run: CFDI preflight blocks (no Active schema release), Generate disabled",
              pre.count() == 1 and "MX_CFDI_NO_ACTIVE_SCHEMA_RELEASE" in pre.inner_text()
              and stage(a).get_by_role("button", name="Generate CFDI").is_disabled()
              and "NOT STARTED" in before.get("cfdi", "").upper(), f"{before} {body(a)[-600:]}")
        shot(a, "01_cfdi_preflight_blocked", stage(a))

        setup("release")
        open_run(a, "Jun 1-15, 2026")
        check("on-2a with the synthetic release the preflight clears",
              a.locator('[data-testid="mx-cfdi-preflight"]').count() == 0, stage(a).inner_text()[:400])
        click_stage(a, "Generate CFDI")
        gen_txt = stage(a).inner_text()
        click_stage(a, "Process PAC queue")
        row = stage(a).locator('[data-testid="mx-cfdi-row"]').first.inner_text()
        check("on-2b Generate -> SIGNED, Process PAC queue -> STAMPED with a UUID",
              "SIGNED" in gen_txt and "STAMPED" in row and "SYN-" in row, f"{gen_txt[:300]} | {row}")
        open_run(a, "Jun 1-15, 2026")
        after = badges(a)
        check("on-2c badges: CFDI -> STAMPED; Payroll / Authorities / Bank unchanged",
              "STAMPED" in after["cfdi"].upper() and all(after[k] == before[k] for k in ("payroll", "authorities", "bank")),
              f"before={before} after={after}")
        shot(a, "02a_status_badges_stamped", a.locator('[data-testid="mx-run-status"]'))
        shot(a, "02b_cfdi_stamped", stage(a))

        pac_script(stamp=["timeout"])
        open_run(a, "Jun 16-30, 2026")
        click_stage(a, "Generate CFDI")
        click_stage(a, "Process PAC queue")
        banner = a.locator('[data-testid="mx-cfdi-unknown-banner"]')
        retry_buttons = stage(a).get_by_role("button", name=re.compile("retry", re.I)).count()
        check("on-3a forced PAC timeout -> UNKNOWN banner; the stage has no retry button",
              banner.count() == 1 and retry_buttons == 0 and "UNKNOWN" in stage(a).inner_text(),
              stage(a).inner_text()[:500])
        shot(a, "03a_unknown_banner", stage(a))
        d = open_drawer(a)
        confirm = d.get_by_role("button", name=re.compile("Confirm retry"))
        check("on-3b UNKNOWN drawer: 'Query status' offered, confirmed retry disabled before any NOT FOUND",
              d.locator('[data-testid="mx-cfdi-unknown-actions"]').count() == 1 and confirm.is_disabled()
              and "No provider rule" in d.inner_text(), d.inner_text()[:600])
        shot(a, "03b_unknown_drawer", d)
        d.get_by_role("button", name="Query status").click()
        settle(a)
        close_drawer(a)
        click_stage(a, "Process PAC queue")                    # the mock answers NOT_FOUND (nothing stamped)
        d = open_drawer(a)
        dtxt = d.inner_text()
        d.get_by_label("Retry reason").fill("SYNTHETIC: PAC answered NOT FOUND after the timeout")
        check("on-4a after NOT FOUND the operator can confirm a retry (reason required)",
              "NOT FOUND answers so far: 1" in dtxt and not confirm.is_disabled(), dtxt[:600])
        confirm.click()
        settle(a)
        close_drawer(a)
        click_stage(a, "Process PAC queue")
        row = stage(a).locator('[data-testid="mx-cfdi-row"]').first.inner_text()
        d = open_drawer(a)
        dtxt = d.inner_text()
        calls = [json.loads(x) for x in CALLS.read_text().splitlines()] if CALLS.is_file() else []
        stamp_calls = [c for c in calls if c[0] == "stamp"]
        key2 = stamp_calls[-1][1] if stamp_calls else None
        same = [c for c in stamp_calls if c[1] == key2]
        check("on-4b confirmed retry -> STAMPED; same idempotency key and payload hash on both attempts",
              "STAMPED" in row and "OPERATOR_RETRY_CONFIRMED" in dtxt and "operator-confirmed" in dtxt
              and len(same) == 2 and same[0][2] == same[1][2], f"{row} | {same} | {dtxt[:400]}")
        shot(a, "04_retry_confirmed_events", d)
        close_drawer(a)

        print(setup("replace").strip())
        open_run(a, "Jul 1-15, 2026")
        click_stage(a, "Process PAC queue")
        st, txt = api(A0, "GET", f"{BASE}/runs/3/cfdi")
        repl = json.loads(txt)["documents"][0]
        check("on-5a replacement CFDI (synthetic correction run) stamped and names the original",
              st == 200 and repl["status"] == "STAMPED" and repl.get("replacesUuid"), txt[:400])
        open_run(a, "Jun 1-15, 2026")
        d = open_drawer(a)
        d.get_by_text("Cancel / replace").click()
        settle(a)
        dlg = a.locator('[data-testid="mx-cfdi-cancel-dialog"]')
        dlg.get_by_label("Cancellation reason").select_option("SYN1")
        dlg.get_by_label("Replacement UUID").fill(repl["uuid"])
        check("on-5b cancel dialog: catalog reasons only; SYN1 asks for the replacement UUID",
              "SYN1" in dlg.inner_text() and "SYN2" in dlg.inner_text()
              and not dlg.get_by_role("button", name="Request cancellation").is_disabled(), dlg.inner_text()[:400])
        shot(a, "05a_cancel_dialog", dlg)
        dlg.get_by_role("button", name="Request cancellation").click()
        settle(a)
        close_drawer(a)
        click_stage(a, "Process PAC queue")
        d = open_drawer(a)
        dtxt = d.inner_text()
        check("on-6 lineage drawer: original REPLACED, original UUID kept, 'Replaced by' = replacement UUID",
              "REPLACED" in dtxt and repl["uuid"] in dtxt and repl["replacesUuid"] in dtxt
              and "CANCEL_REQUESTED" in dtxt and "CANCELLED" in dtxt, dtxt[:700])
        shot(a, "06_lineage_drawer", d)
        close_drawer(a)

        st, txt = api(A1, "POST", f"{BASE}/runs/1/reset", {"reason": "SYNTHETIC reset attempt"})
        check("on-7 reset refused once CFDI acted (MX_RESET_DOWNSTREAM_ACTED)",
              st == 409 and "MX_RESET_DOWNSTREAM_ACTED" in txt, f"{st} {txt[:300]}")
        open_run(a, "Jun 1-15, 2026")
        final = badges(a)
        check("on-8 badges after cancel/replace: CFDI REPLACED; Payroll / Authorities / Bank unchanged",
              "REPLACED" in final["cfdi"].upper() and all(final[k] == before[k] for k in ("payroll", "authorities", "bank")),
              f"before={before} final={final}")
        shot(a, "07_badges_final", a.locator('[data-testid="mx-run-status"]'))

        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="networkidle")
        settle(n)
        check("on-9 NL org run screen unchanged -- no Mexico CFDI panel", stage(n).count() == 0, "")
        shot(n, "08_nl_regression")
        s = new_page(browser, SA)
        s.goto(APP + "/super-admin/compliance/mexico", wait_until="networkidle")
        settle(s)
        open_cfdi_lifecycle(s)
        lc = s.locator('[data-testid="mx-cfdi-lifecycle"]')
        ltxt = lc.inner_text() if lc.count() else ""
        check("on-10 Super Admin CFDI lifecycle counts the documents (read-only)",
              "3 document(s)" in ltxt and "REPLACED 1" in ltxt and "STAMPED 2" in ltxt
              and "Nothing at platform level" in ltxt, ltxt[:500])
        shot(s, "09_super_admin_cfdi_lifecycle", lc)
    browser.close()

expected_4xx = {("POST", f"{BASE}/runs/1/reset")}
unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 7 -- browser check (flag {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
