"""Mexico Phase 4 browser acceptance (installed Chrome, vite preview bundle,
scratch SQLite backend from setup_db.py).

Usage: python acceptance.py off|on   — must match the backend's
MX_TENANT_ONBOARDING_ENABLED. Screenshots and RESULTS-<mode>.md go to
docs/mexico/phase4-evidence/.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

MODE = sys.argv[1]
assert MODE in ("off", "on")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase4-evidence")
PASSWORD = "BrowserCheck!2026"
ADMIN, NEWORG, NLADMIN, SA = ("admin@mxorg.example.com", "admin@neworg.example.com", "admin@nlorg.example.com",
                              "sa-a@mx.example.com")
results, errors, responses = [], [], []


def token(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PASSWORD}).encode())
    return json.load(urllib.request.urlopen(req))


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
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


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


def go(page, path):
    page.goto(APP + path, wait_until="networkidle")
    page.wait_for_timeout(900)


def settle(page, ms=1200):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page, name):
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / f"{MODE}_{name}.png"), full_page=True)


def body(page):
    return page.inner_text("body")


def open_mx_panel(page):
    go(page, "/payroll/employees")
    page.get_by_text("Persona Sintética").first.click()
    settle(page)
    page.locator("text=Mexico statutory profile").first.scroll_into_view_if_needed()
    page.get_by_role("button", name="Manage").last.click()
    settle(page)
    return page.locator('[data-testid="mx-employee-panel"]')


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, ADMIN)

    if MODE == "off":
        go(a, "/payroll/compliances")
        a.get_by_role("button", name="Mexico Compliance Centre", exact=True).first.click()
        settle(a)
        check("off-1 Mexico Compliance Centre shows the dormancy message", "not open for onboarding" in body(a), body(a)[:500])
        shot(a, "01_compliance_centre_dormant")
        status, text = api(NEWORG, "PUT", "/api/payroll/compliance/company-details", {"jurisdictionCountry": "MX"})
        check("off-2 payroll jurisdiction MX refused", status == 400 and "not open for onboarding" in text, f"{status} {text[:200]}")
        status, text = api(NEWORG, "PUT", "/api/organizations/me", {"country": "Mexico"})
        check("off-3 organisation country Mexico refused", status == 400 and "not open for onboarding" in text, f"{status} {text[:200]}")
        panel = open_mx_panel(a)
        check("off-4 Mexico employee panel reports dormancy, no data", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:400])
        shot(a, "02_employee_panel_dormant")
        status, _ = api(ADMIN, "POST", "/api/payroll/employees",
                        {"name": "X", "employeeCode": "MX-9", "countryCode": "MX", "email": "x9@example.com",
                         "complianceFields": {"rfc": "WXYZ010101AB1", "curp": "WXYZ010101HDFXYZ02", "nss": "10987654321"}})
        check("off-5 creating a Mexican employee is refused", status == 400, str(status))
        s = new_page(browser, SA)
        go(s, "/super-admin/compliance/mexico")
        check("off-6 Super Admin Mexico workspace still loads", "MX-PAYROLL-2026" in body(s), body(s)[:300])
        shot(s, "03_super_admin_workspace")
        provoked = {("/api/payroll/compliance/company-details", 400), ("/api/organizations/me", 400),
                    ("/api/payroll/employees", 400)}
    else:
        go(a, "/payroll/employees")
        a.get_by_text("Persona Sintética").first.click()
        settle(a)
        detail = body(a)
        check("on-1 employee detail shows RFC / CURP / NSS masked, never in full",
              "ABCD010101AB1" not in detail and "ABCD010101HDFXYZ01" not in detail and "12345678901" not in detail
              and "mexico statutory profile" in detail.lower() and "1AB1" in detail, detail[:600])
        shot(a, "01_employee_detail_masked")
        a.get_by_role("button", name="Manage").last.click()
        settle(a)
        panel = a.locator('[data-testid="mx-employee-panel"]')
        text = panel.inner_text()
        check("on-2 Mexico panel renders the §12 sections", all(s in text for s in (
            "Identity", "Workplace", "Employment", "IMSS", "Pay", "CFDI receiver", "ISR", "Versions",
            "INFONAVIT credit notices", "Readiness")), text[:600])
        shot(a, "02_mexico_panel")
        form = panel.locator('[data-testid="mx-profile-form"]')
        form.locator('[name="mx_establishment_id"]').select_option(index=1)
        form.locator('[name="mx_work_state"]').select_option("JAL")
        form.locator('[name="effective_from"]').fill("2026-03-01")
        form.get_by_role("button", name="Record new version").click()
        settle(a)
        check("on-3 work state differing from the establishment needs an exception ref",
              "remote / multi-state exception reference" in panel.inner_text(), panel.inner_text()[:400])
        form.locator('[name="mx_remote_state_exception_ref"]').fill("REMOTE-SYN-1")
        form.locator('[name="mx_work_municipality"]').fill("Guadalajara")
        form.locator('[name="mx_daily_salary"]').fill("500")
        form.locator('[name="mx_contract_type_code"]').fill("01")
        form.get_by_role("button", name="Record new version").click()
        settle(a, 1800)
        text = panel.inner_text()
        check("on-4 version saved; identifiers FORMAT_ONLY with 'source pending' findings",
              "New Mexico profile version recorded" in text and "FORMAT_ONLY" in text and "source pending" in text, text[:700])
        shot(a, "03_version_saved_format_only")
        form.locator('[name="mx_professional_min_code"]').fill("P01")
        form.locator('[name="effective_from"]').fill("2026-04-01")
        form.get_by_role("button", name="Record new version").click()
        settle(a)
        check("on-5 professional minimum refused while content is not active",
              "no professional minimum with that code is in Active" in panel.inner_text(), panel.inner_text()[:400])
        notices = panel.locator('[data-testid="mx-infonavit-notices"]')
        notices.locator('[name="creditNumber"]').fill("CR-SYN-1")
        notices.locator('[name="noticeType"]').select_option("RETENCION")
        notices.locator('[name="discountMethod"]').select_option("PERCENTAGE")
        notices.locator('[name="discountValue"]').fill("20")
        notices.locator('[name="effectiveFrom"]').fill("2026-03-01")
        notices.locator('[name="authorityReference"]').fill("AVISO-SYN-1")
        notices.get_by_role("button", name="Record notice").click()
        settle(a)
        check("on-6 INFONAVIT notice refused without its evidence", "attach the INFONAVIT notice itself" in notices.inner_text(),
              notices.inner_text()[:400])
        notices.locator('[name="creditNumber"]').fill("CR-SYN-1")
        notices.locator('[name="noticeType"]').select_option("RETENCION")
        notices.locator('[name="discountMethod"]').select_option("PERCENTAGE")
        notices.locator('[name="discountValue"]').fill("20")
        notices.locator('[name="effectiveFrom"]').fill("2026-03-01")
        notices.locator('[name="authorityReference"]').fill("AVISO-SYN-1")
        notices.locator('[name="evidenceDocumentId"]').fill("1")
        notices.get_by_role("button", name="Record notice").click()
        settle(a, 1800)
        check("on-7 INFONAVIT notice recorded with evidence", "CR-SYN-1" in notices.inner_text()
              and "RECORDED" in notices.inner_text(), notices.inner_text()[:400])
        shot(a, "04_infonavit_notice")
        panel.get_by_label("Readiness on").fill("2026-03-01")
        settle(a, 1800)
        ready = panel.locator('[data-testid="mx-employee-readiness"]').inner_text()
        check("on-8 employee readiness: blocked items with gates, unmapped, sources and phases",
              all(s in ready for s in ("BLOCKED", "G1", "G4", "G5", "unmapped", "S31/S32", "S28", "MX-045")), ready[:900])
        shot(a, "05_employee_readiness")
        go(a, "/payroll/compliances")
        a.get_by_role("button", name="Mexico Compliance Centre", exact=True).first.click()
        settle(a, 1800)
        a.get_by_label("Readiness on").fill("2026-03-01")
        settle(a, 1800)
        check("on-9 employer readiness shows the employees-with-exceptions line",
              "Employees with blocking exceptions" in body(a) and "1 of 1" in body(a), body(a)[-800:])
        shot(a, "06_employer_readiness")
        n = new_page(browser, NLADMIN)
        go(n, "/payroll/compliances")
        names = [t.strip() for t in n.locator("button").all_inner_texts()]
        check("on-10 NL org tabs unchanged, no Mexico tab",
              "Netherlands Compliance Centre" in names and "Mexico Compliance Centre" not in names, str(names[:25]))
        shot(n, "07_regression_nl")
        provoked = set()
        provoked_prefix = ("/api/payroll/employees/1/statutory-profile", "/api/payroll/mexico/employees/1/infonavit-notices")
    browser.close()

if MODE == "off":
    unexpected = [r for r in responses if (r[2].split("?")[0], r[3]) not in provoked
                  and not (r[3] == 403 and "/api/payroll/mexico/" in r[2])]
else:
    unexpected = [r for r in responses if not (r[3] == 400 and r[2].split("?")[0] in provoked_prefix)]
check(f"{MODE}-last no unexpected HTTP errors", not unexpected, str(unexpected[:8]))
noise = [e for e in errors if "Failed to load resource" not in e]
check(f"{MODE}-last no page errors (besides logged provoked responses)", not noise, str(noise[:5]))
passed = sum(ok for _, ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
(OUT / f"RESULTS-{MODE}.md").write_text(
    f"# Mexico Phase 4 browser acceptance — flag {MODE}\n\n**{passed}/{len(results)} checks passed.**\n\n"
    "| Check | Result |\n|---|---|\n"
    + "\n".join(f"| {name} | {'PASS' if ok else 'FAIL — ' + d.replace('|', '/')[:300]} |" for name, ok, d in results) + "\n",
    encoding="utf-8")
