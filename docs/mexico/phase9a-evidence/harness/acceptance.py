"""Mexico Phase 9a (correction runs) browser acceptance — installed Chrome,
vite preview of the current build, scratch SQLite backend from setup_db.py
via serve.py. Usage: python acceptance.py off | on (fresh DB each).
The only non-UI writes: setup_db.py `fix` (the operator corrects the daily
salary, SYNTHETIC) and the run approvals / reset attempt through the API."""
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
assert MODE in ("on", "off")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = HERE.parent
PYTHON = r"C:\Users\Nikhi\AppData\Local\Programs\Python\Python311\python.exe"
PASSWORD = "BrowserCheck!2026"
A0, A1, NL = "admin0@mx9.example.com", "admin1@mx9.example.com", "admin@nl9.example.com"
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


def open_run(page, label):
    page.goto(APP + "/payroll/payroll-runs", wait_until="load")
    settle(page)
    page.get_by_text(label, exact=True).first.click()
    settle(page, 2500)


def panel(page):
    return page.locator('[data-testid="mx-corrections"]')


def approve(run_id):
    s1, t1 = api(A0, "PUT", f"/api/payroll/runs/{run_id}/approve")
    s2, t2 = api(A1, "PUT", f"/api/payroll/runs/{run_id}/approve")
    return s1, s2, t1[:200] + t2[:200]


def corrections(run_id):
    return json.loads(api(A0, "GET", f"{BASE}/runs/{run_id}/corrections")[1])


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        a = new_page(browser, A0)
        open_run(a, "Jun 1-15, 2026")
        check("off-1 the Mexican run shows no corrections panel (dormant)", panel(a).count() == 0, "")
        a.get_by_text(re.compile("not open for onboarding")).first.scroll_into_view_if_needed()
        a.screenshot(path=str(OUT / "off_01_mx_run_dormant.png"))
        for method, path in (("GET", "/runs/1/corrections"), ("POST", "/runs/1/corrections"),
                             ("POST", "/corrections/1/void")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-2 {method} {path} -> 403", st == 403, f"{st} {txt[:150]}")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="load")
        settle(n)
        check("off-3 NL run screen loads", "Payroll" in n.inner_text("body"), "")
    else:
        a = new_page(browser, A0)
        open_run(a, "Jun 1-15, 2026")
        pn = panel(a)
        check("on-1 committed run: corrections panel offers its payslips and a reason",
              pn.count() == 1 and pn.get_by_role("checkbox").count() == 1
              and pn.get_by_role("button", name="Open correction run").is_disabled(), pn.inner_text()[:300] if pn.count() else "")
        shot(a, "01_panel_on_committed_run", pn)
        out = subprocess.run([PYTHON, str(HERE / "setup_db.py"), "fix"], capture_output=True, text=True, env=os.environ)
        check("on-2 the operator corrects the daily salary from 1 June (SYNTHETIC input fix)", out.returncode == 0,
              out.stderr[-300:])
        before = json.loads(api(A0, "GET", f"{BASE}/runs/1/status")[1])
        open_run(a, "Jun 1-15, 2026")
        pn = panel(a)
        pn.get_by_role("checkbox").first.check()
        pn.get_by_label("Correction reason").fill("SYNTHETIC: daily salary was 700 from 1 June")
        pn.get_by_role("button", name="Open correction run").click()
        settle(a, 2500)
        view = corrections(1)
        corr_id = view["corrections"][0]["correctionRunId"] if view["corrections"] else None
        check("on-3 correction run opened from the UI; the original shows a DRAFT correction",
              corr_id and view["corrections"][0]["status"] == "DRAFT" and "Correction run created" in panel(a).inner_text(),
              str(view)[:300])
        shot(a, "02_correction_opened", panel(a))
        open_run(a, "Correction — Jun 1-15, 2026")
        cp = panel(a)
        ctext = cp.inner_text() if cp.count() else ""
        check("on-4 the correction run explains itself and offers Void while uncommitted",
              "never edited" in ctext and "DRAFT" in ctext and cp.get_by_role("button", name="Void correction").count() == 1,
              ctext[:300])
        shot(a, "03_correction_run_draft", cp)
        s1, s2, txt = approve(corr_id)
        open_run(a, "Correction — Jun 1-15, 2026")
        cp = panel(a)
        ctext = cp.inner_text()
        row = corrections(corr_id)["corrects"][0]
        check("on-5 approved: the correction is COMMITTED with its posted differences shown",
              s1 == 200 and s2 == 200 and "COMMITTED" in ctext and row["deltas"] and float(row["deltas"]["gross"]) > 0,
              f"{s1} {s2} {txt} | {ctext[:300]}")
        shot(a, "04_correction_committed", cp)
        shot(a, "05_correction_badges", a.locator('[data-testid="mx-run-status"]'))
        open_run(a, "Jun 1-15, 2026")
        otext = panel(a).inner_text()
        after = json.loads(api(A0, "GET", f"{BASE}/runs/1/status")[1])
        check("on-6 the original shows the COMMITTED correction; its payroll lane is untouched",
              "COMMITTED" in otext and after["payroll"]["status"] == before["payroll"]["status"] == "Approved",
              otext[:300])
        shot(a, "06_original_with_correction", panel(a))
        st, txt = api(A1, "POST", f"{BASE}/runs/1/reset", {"reason": "SYNTHETIC reset attempt"})
        check("on-7 the original cannot be reset while a correction stands on it",
              st == 409 and "correction" in txt, f"{st} {txt[:300]}")
        # A second correction, voided before approval: its run disappears, the record stays.
        st, txt = api(A0, "POST", f"{BASE}/runs/{corr_id}/corrections",
                      {"itemIds": [corrections(corr_id)["corrects"][0]["correctedItemId"]], "reason": "SYNTHETIC: second look"})
        second = json.loads(txt)["corrects"][0]["correctionRunId"] if st == 200 else None
        open_run(a, "Correction — Correction — Jun 1-15, 2026")
        cp = panel(a)
        cp.get_by_label("Void reason").fill("SYNTHETIC: opened by mistake")
        cp.get_by_role("button", name="Void correction").click()
        settle(a, 2000)
        removed_msg = panel(a).inner_text()
        gone = api(A0, "GET", f"/api/payroll/runs/{second}")[0]
        voided = [c for c in corrections(corr_id)["corrections"] if c["status"] == "VOIDED"]
        check("on-8 void from the UI: the uncommitted correction run is removed, the VOIDED record kept",
              st == 200 and gone == 404 and len(voided) == 1 and voided[0]["voidReason"]
              and "Correction voided" in removed_msg, f"{st} {gone} {voided} {removed_msg[:200]}")
        shot(a, "07a_void_message", panel(a))
        open_run(a, "Correction — Jun 1-15, 2026")
        chain = panel(a).inner_text()
        check("on-8b the committed correction run lists the VOIDED correction of itself and can be corrected again",
              "CORRECTIONS OF THIS CORRECTION" in chain.upper() and "VOIDED" in chain
              and panel(a).get_by_role("button", name="Open correction run").count() == 1, chain[:400])
        shot(a, "07b_chain_on_correction_run", panel(a))
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/payroll-runs", wait_until="load")
        settle(n)
        check("on-9 NL run screen unchanged", panel(n).count() == 0 and "Payroll" in n.inner_text("body"), "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check(f"{MODE}-z no 5xx responses and no page errors",
      not unexpected and not [e for e in errors if "pageerror" in e], f"{unexpected} {errors[:5]}")
lines = [f"# Mexico Phase 9a -- browser check (flag {MODE.upper()})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / f"RESULTS-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
