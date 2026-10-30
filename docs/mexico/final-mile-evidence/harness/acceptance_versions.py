"""Mexico configuration versions in the real UI (Super Admin → Mexico → Versions):
the national and CDMX ISN packs with their versions, one version's rows with
sources, "New version" as a Draft copy with a reason, and compare. Harness:
setup_db.py (real Draft packs seeded by the deployment script) + serve.py."""
import json
import re
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
    a.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(a)
    a.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(a, 1500)
    a.get_by_role("button", name="Versions", exact=True).first.click()
    settle(a, 2500)
    national, cdmx = tid(a, "mx-versions-national"), tid(a, "mx-versions-CDMX")
    nt = national.inner_text() if national.count() else ""
    check("v-1 the national pack and the CDMX ISN pack are listed with their versions",
          national.count() == 1 and cdmx.count() == 1 and "v1.0" in nt.replace("V1.0", "v1.0") and "DRAFT" in nt.upper(),
          nt[:300])
    check("v-2 the rule says rows are never edited here", "never edited in the product" in tid(a, "mx-config-versions").inner_text(), "")
    a.screenshot(path=str(OUT / "v_01_versions.jpg"), type="jpeg", quality=60, full_page=False)
    national.get_by_role("button", name="Rows").first.click()
    settle(a)
    rows = tid(a, "mx-config-rows").inner_text()
    check("v-3 one version's rows show values, dates and a source for each row",
          "read-only" in rows and "#" in rows and "…" in rows, rows[:300])
    el = tid(a, "mx-config-rows")                                   # 241 rows: keep the first screenful
    el.evaluate("e => { e.style.maxHeight = '700px'; e.style.overflow = 'hidden'; }")
    el.screenshot(path=str(OUT / "v_02_version_rows.jpg"), type="jpeg", quality=60)
    national.get_by_role("button", name="New version").first.click()
    national.get_by_label("New version number").fill("1.1")
    national.get_by_label("New version reason").fill("SYNTHETIC browser check: rollback copy")
    national.get_by_role("button", name=re.compile(r"^Create Draft copy")).click()
    settle(a, 2000)
    page_text = tid(a, "mx-config-versions").inner_text()
    check("v-4 'New version' creates a Draft copy with every row, and the list shows it",
          "Created" in page_text and "v1.1" in tid(a, "mx-versions-national").inner_text(), page_text[:400])
    shot_target = tid(a, "mx-versions-national")
    shot_target.screenshot(path=str(OUT / "v_03_new_version.jpg"), type="jpeg", quality=60)
    cmp = tid(a, "mx-config-compare")
    opts = cmp.get_by_label("Compare versions from").locator("option").all_inner_texts()
    v10 = next(o for o in opts if re.search(r"MX-PAYROLL-\S+ v1\.0 ", o))
    v11 = next(o for o in opts if re.search(r"MX-PAYROLL-\S+ v1\.1 ", o))
    cmp.get_by_label("Compare versions from").select_option(label=v10)
    cmp.get_by_label("Compare versions to").select_option(label=v11)
    cmp.get_by_role("button", name="Compare").click()
    settle(a)
    diff = tid(a, "mx-config-diff").inner_text()
    check("v-5 compare of v1.0 and its copy v1.1 is identical (values, dates, sources)", diff.startswith("Identical"),
          diff[:200])
    cmp.screenshot(path=str(OUT / "v_04_compare.jpg"), type="jpeg", quality=60)
    browser.close()

req = urllib.request.Request(f"{API}/api/super-admin/compliance/mexico/configuration/versions",
                             headers={"Authorization": f"Bearer {token(NL)['access_token']}"})
try:
    status = urllib.request.urlopen(req).status
except urllib.error.HTTPError as e:
    status = e.code
check("v-6 an organisation admin is refused the versions route", status in (401, 403), str(status))
unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico configuration versions -- browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser: " + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses}))
                                                       or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-VERSIONS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
