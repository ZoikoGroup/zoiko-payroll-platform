"""Mexico final mile X8 — the screens the configuration re-audit touched: the run's
CFDI stage gains "Reconcile after restore" (the UNKNOWN-state runbook's restore
step, behind a confirmation), and the Super Admin Readiness tab states that a
reviewed evidence file is never replaced. Server: serve_x4.py on, on the X4
scratch DB (setup_x4.py)."""
import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
PASSWORD = "BrowserCheck!2026"
A0, SA = "admin0@mxfm4.example.com", "sa-a@mxfm4.example.com"
results, errors, responses, requests, _tokens = [], [], [], [], {}


def token(email):
    if email not in _tokens:
        req = urllib.request.Request(f"{API}/api/auth/login", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"email": email, "password": PASSWORD}).encode())
        _tokens[email] = json.load(urllib.request.urlopen(req))
    return _tokens[email]


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
    page.on("request", lambda r: requests.append((r.method, r.url)) if "/cfdi/reconcile" in r.url else None)
    page.on("response", lambda r: responses.append((who, r.request.method, re.sub(r"^.*?/api/", "/api/", r.url),
                                                    r.status)) if r.status >= 400 else None)
    return page


def settle(page, ms=1200):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, A0)
    a.goto(APP + "/payroll/payroll-runs", wait_until="load")
    settle(a)
    a.get_by_text("Jun 1-15, 2026", exact=True).first.click()
    settle(a, 2500)
    stage = a.locator('[data-testid="mx-cfdi-stage"]')
    button = a.locator('[data-testid="mx-cfdi-reconcile"]')
    check("x8-1 the run's CFDI stage offers 'Reconcile after restore'", stage.count() == 1 and button.count() == 1
          and "Reconcile after restore" in button.inner_text(), stage.inner_text()[:300] if stage.count() else "no stage")
    a.once("dialog", lambda d: d.dismiss())
    button.click()
    settle(a, 800)
    check("x8-2 cancelling the confirmation sends nothing", not requests, str(requests))
    a.once("dialog", lambda d: d.accept())
    button.click()
    settle(a)
    check("x8-3 confirming calls the reconcile route once", len(requests) == 1 and requests[0][0] == "POST",
          str(requests))
    stage.first.screenshot(path=str(OUT / "x8_01_cfdi_reconcile_button.jpg"), type="jpeg", quality=60)

    s = new_page(browser, SA)
    s.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(s)
    s.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(s, 1500)
    s.get_by_role("button", name="Readiness G1–G8", exact=True).first.click()
    settle(s, 2500)
    text = s.content()
    check("x8-4 the Readiness tab says a reviewed evidence file is never replaced",
          "A reviewed file is never replaced" in text, "")
    gates = s.get_by_text("Release gates", exact=True).first.locator("xpath=..")
    gates.screenshot(path=str(OUT / "x8_02_readiness_evidence_rule.jpg"), type="jpeg", quality=60)
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico final mile X8 -- configuration re-audit browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses}))
                                                       or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-X8.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
