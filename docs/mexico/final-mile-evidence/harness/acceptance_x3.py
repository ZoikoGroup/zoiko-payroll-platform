"""Mexico final mile X3 — the report-template catalog and library tools in the
real UI: the eight new templates listed as Draft, the coverage table, a
version diff, a watermarked sandbox preview, and the organisation report route
refused while Mexico is dormant. Same harness as X1 / X2."""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
PASSWORD = "BrowserCheck!2026"
SA_A, NL = "sa-a@mxfm.example.com", "admin@nlfm.example.com"
NEW = ("MX-RUN-VARIANCE", "MX-PREFLIGHT-EXCEPTIONS", "MX-SBC-MOVEMENTS", "MX-WORK-RISK-ANNUAL", "MX-INFONAVIT-NOTICES",
       "MX-LABOR-COMPLIANCE", "MX-PAYMENT-WORKLIST", "MX-IDENTIFIER-ACCESS-AUDIT")
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


def settle(page, ms=1200):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def shot(page, name, locator=None):
    page.wait_for_timeout(300)
    target = locator.first if locator is not None and locator.count() else page
    target.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=60)


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    a.goto(APP + "/super-admin/report-templates/mexico", wait_until="load")
    settle(a, 2500)
    library = tid(a, "mx-template-library")
    text = library.inner_text()
    check("x3-1 the library lists every new X3 template, Draft, built by its dedicated generator",
          all(k in text for k in NEW) and "Dedicated generator" in text and "Draft" in text, text[:300])
    check("x3-2 snapshot-field templates show their catalogue check",
          "catalogued; proven on a committed payslip at activation" in text, "")
    shot(a, "x3_01_library_coverage", library)

    cmp = tid(a, "mx-template-compare")
    opts = cmp.get_by_label("Compare from").locator("option").all_inner_texts()
    reg = next(o for o in opts if o.startswith("MX-PAYROLL-REGISTER"))
    cost = next(o for o in opts if o.startswith("MX-EMPLOYER-COST"))
    cmp.get_by_label("Compare from").select_option(label=reg)
    cmp.get_by_label("Compare to").select_option(label=cost)
    cmp.get_by_role("button", name="Compare").click()
    settle(a)
    diff = tid(a, "mx-template-diff").inner_text()
    check("x3-3 version diff between two templates shows added / removed / metadata and the hashes",
          "Added" in diff and "template_key" in diff and "Content hashes" in diff, diff[:300])
    shot(a, "x3_02_template_diff", cmp)

    pv = tid(a, "mx-template-preview")
    pv_opts = pv.get_by_label("Template to preview").locator("option").all_inner_texts()
    pv.get_by_label("Template to preview").select_option(label=next(o for o in pv_opts if o.startswith("MX-PAYROLL-REGISTER")))
    pv.get_by_role("button", name="Preview").click()
    settle(a)
    blocked = tid(a, "mx-template-preview-result").inner_text()
    check("x3-4 preview without candidates is blocked at the rounding rule", "MX_ROUNDING_RULE_MISSING" in blocked,
          blocked[:200])
    pv.get_by_label("Preview candidates").fill("D-01=HALF_UP:0.01; D-03=GENERAL")
    pv.get_by_role("button", name="Preview").click()
    settle(a)
    res = tid(a, "mx-template-preview-result").inner_text()
    check("x3-5 preview with what-if candidates resolves the template's fields, watermarked",
          "SANDBOX PREVIEW — SYNTHETIC — NOT A REPORT" in res and "CANDIDATE — NOT APPROVED" in res
          and "9000.0000" in res, res[:400])
    shot(a, "x3_03_template_sandbox_preview", pv)
    browser.close()

templates = json.loads(api(SA_A, "GET", "/api/super-admin/compliance/mexico/report-templates/coverage")[1])
variance = next(t for t in templates if t["templateKey"] == "MX-RUN-VARIANCE")
status, body = api(NL, "POST", f"/api/payroll/mexico/reports/{variance['id']}/generate", {"run_id": 1})
check("x3-6 the organisation report route refuses while Mexico is dormant", status in (400, 403) and
      ("dormant" in body.lower() or "MX_DORMANT" in body or "not open" in body.lower()), f"{status} {body[:200]}")
unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico final mile X3 -- report-template catalog and library browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses}))
                                                       or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-X3.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
