"""Mexico final mile X5 — CSD expiry alerts on the Super Admin Mexico Employer
tab (gap C3): the EXPIRING synthetic CSD is listed with its organisation,
masked fingerprint and serial; the PAC reference is not; no secret reference
reaches the page or the API; an org admin is refused the route. Server:
serve_x4.py off (the alerts are platform configuration, not tenant onboarding)."""
import json
from datetime import date
import re
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
SA_PATH = "/api/super-admin/compliance/mexico"
PASSWORD = "BrowserCheck!2026"
SA, A0 = "sa-a@mxfm4.example.com", "admin0@mxfm4.example.com"
results, errors, responses, _tokens = [], [], [], {}


def token(email):
    if email not in _tokens:
        req = urllib.request.Request(f"{API}/api/auth/login", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"email": email, "password": PASSWORD}).encode())
        _tokens[email] = json.load(urllib.request.urlopen(req))
    return _tokens[email]


def api(email, method, path):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 headers={"Authorization": f"Bearer {token(email)['access_token']}"})
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


def settle(page, ms=1200):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA)
    a.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(a)
    a.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(a, 1500)
    a.get_by_role("button", name="Employer", exact=True).first.click()
    settle(a, 2500)
    card = a.locator('[data-testid="mx-csd-expiry"]')
    text = card.inner_text() if card.count() else ""
    check("x5-1 the Employer tab shows CSD expiry alerts for every organisation",
          "CSD expiry alerts" in text and "EXPIRING" in text and "SYN00000000000000001" in text, text[:400])
    check("x5-2 the PAC reference is not a CSD alert, and the fingerprint is masked",
          "SYN-PAC-REF" not in text and "abababababab…" in text and ("ab" * 32) not in text, text[:400])
    check("x5-3 no secret reference reaches the page", "gcp-sm" not in a.content(), "")
    card.first.screenshot(path=str(OUT / "x5_01_csd_expiry_alerts.jpg"), type="jpeg", quality=60)
    browser.close()

st, body = api(SA, "GET", f"{SA_PATH}/csd-expiry?on={date.today().isoformat()}")
check("x5-4 the API returns public metadata only", st == 200 and "EXPIRING" in body and "gcp-sm" not in body and "secret" not in body.lower(),
      f"{st} {body[:200]}")
st, body = api(A0, "GET", f"{SA_PATH}/csd-expiry?on={date.today().isoformat()}")
check("x5-5 an org admin is refused the Super Admin route", st in (401, 403), f"{st} {body[:150]}")
unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico final mile X5 -- CSD expiry alerts browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses}))
                                                       or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-X5.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
