"""Mexico report-template versions in the real UI (Super Admin → Report templates
→ Mexico): every template's versions with the platform part of the activation
gate, "New version" as a Draft copy of the chosen version, and the compare tool
showing the copy identical. Harness: setup_db.py + serve.py."""
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
results, errors, responses, _tokens = [], [], [], {}


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
    page.on("response", lambda r: responses.append((who, r.request.method, re.sub(r"^.*?/api/", "/api/", r.url),
                                                    r.status)) if r.status >= 400 else None)
    return page


def settle(page, ms=1200):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    a.goto(APP + "/super-admin/report-templates/mexico", wait_until="load")
    settle(a, 2500)
    panel = tid(a, "mx-template-versions")
    reg = tid(a, "mx-template-versions-MX-PAYROLL-REGISTER")
    text = reg.inner_text() if reg.count() else ""
    check("t-1 every Mexico template is listed with its versions and the platform gate answer",
          panel.count() == 1 and "v1.0" in text and "not SIGNED" in text and "payslip field proof" in text, text[:300])
    reg.screenshot(path=str(OUT / "t_01_template_versions.jpg"), type="jpeg", quality=60)
    reg.get_by_role("button", name="New version").first.click()
    reg.get_by_label("Template new version number").fill("1.1")
    reg.get_by_label("Template new version reason").fill("SYNTHETIC browser check: rollback copy")
    reg.get_by_role("button", name=re.compile(r"^Create Draft copy")).click()
    settle(a, 2000)
    text = tid(a, "mx-template-versions-MX-PAYROLL-REGISTER").inner_text()
    check("t-2 'New version' creates a Draft copy with the same fields, listed under the template",
          "v1.1" in text and "Created MX-PAYROLL-REGISTER v1.1" in panel.inner_text(), text[:300])
    tid(a, "mx-template-versions-MX-PAYROLL-REGISTER").screenshot(path=str(OUT / "t_02_template_new_version.jpg"),
                                                                   type="jpeg", quality=60)
    a.reload(wait_until="load")
    settle(a, 2500)
    cmp = tid(a, "mx-template-compare")
    opts = cmp.get_by_label("Compare from").locator("option").all_inner_texts()
    v10 = next(o for o in opts if o.startswith("MX-PAYROLL-REGISTER v1.0"))
    v11 = next(o for o in opts if o.startswith("MX-PAYROLL-REGISTER v1.1"))
    cmp.get_by_label("Compare from").select_option(label=v10)
    cmp.get_by_label("Compare to").select_option(label=v11)
    cmp.get_by_role("button", name="Compare").click()
    settle(a)
    diff = tid(a, "mx-template-diff").inner_text()
    check("t-3 compare shows the copy has the same fields (only its version metadata differs)",
          "Added 0" in diff and "removed 0" in diff and "changed 0" in diff, diff[:300])
    cmp.screenshot(path=str(OUT / "t_03_template_compare.jpg"), type="jpeg", quality=60)
    browser.close()

req = urllib.request.Request(f"{API}/api/super-admin/compliance/mexico/report-templates/versions",
                             headers={"Authorization": f"Bearer {token(NL)['access_token']}"})
try:
    status = urllib.request.urlopen(req).status
except urllib.error.HTTPError as e:
    status = e.code
check("t-4 an organisation admin is refused the template versions route", status in (401, 403), str(status))
unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico report-template versions -- browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses}))
                                                       or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-TEMPLATE-VERSIONS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
