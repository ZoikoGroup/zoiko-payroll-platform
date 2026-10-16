"""Mexico Phase 3 real-browser acceptance (installed Chrome, vite preview
bundle, throwaway SQLite backend built by setup_db.py). Users are throwaway
@example.com accounts that exist only in that scratch DB. Every check
asserts POSITIVE on-screen content; screenshots go to docs/mexico/phase3-evidence/.

Usage: python acceptance.py <path to synthetic_csd.cer written by setup_db.py>
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase3-evidence")
OUT.mkdir(parents=True, exist_ok=True)
CER = sys.argv[1]
PASSWORD = "BrowserCheck!2026"      # throwaway, scratch DB only
results, errors, responses = [], [], []
GCP_REF = "gcp-sm://projects/zoiko-browser-check/secrets/mx-csd-key/versions/1"
PEM_KEY = "-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgSYNTHETICKEY\n-----END PRIVATE KEY-----"


def token(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PASSWORD}).encode())
    return json.load(urllib.request.urlopen(req))


def login_script(email):
    tok = token(email)
    return (f"localStorage.setItem('zoiko_payroll_access', {json.dumps(tok['access_token'])});"
            f"localStorage.setItem('zoiko_payroll_refresh', {json.dumps(tok['refresh_token'])});"
            f"localStorage.setItem('zoiko_payroll_user', {json.dumps(json.dumps(tok['user']))});")


def api(email, method, path, body=None):
    tok = token(email)["access_token"]
    req = urllib.request.Request(f"{API}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def body(page):
    return page.inner_text("body")


def shot(page, name):
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


def new_page(browser, who):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(login_script(who))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{who} pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"{who} console.error: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: responses.append((who, r.request.method, re.sub(r"^.*?/api/", "/api/", r.url), r.status))
            if r.status >= 400 else None)
    return page


def go(page, path):
    page.goto(APP + path, wait_until="networkidle")
    page.wait_for_timeout(900)


def settle(page, ms=900):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def tab_names(page):
    return [t.strip() for t in page.locator("button").all_inner_texts() if t.strip()]


def open_mx_centre(page):
    go(page, "/payroll/compliances")
    page.get_by_role("button", name="Mexico Compliance Centre", exact=True).first.click()
    settle(page)


def fill(page, scope, values):
    root = page.locator(f'[data-testid="{scope}"]')
    for key, value in values.items():
        el = root.locator(f'[name="{key}"]').first
        tag = el.evaluate("e => e.tagName + ':' + (e.type || '')")
        if tag.startswith("SELECT"):
            el.select_option(str(value))
        elif tag.endswith(":checkbox"):
            el.set_checked(bool(value))
        else:
            el.fill(str(value))
    return root


def submit(page, scope, label):
    page.locator(f'[data-testid="{scope}"]').get_by_role("button", name=label).click()
    settle(page, 1200)


ADMIN, OPERATOR, OTHER = "admin@mxorg.example.com", "operator@mxorg.example.com", "admin@mxother.example.com"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # 1 — mount point and Q6
    a = new_page(browser, ADMIN)
    go(a, "/payroll/compliances")
    names = tab_names(a)
    check("01 MX org sees 'Mexico Compliance Centre' and no 'Tax Configuration' tab",
          "Mexico Compliance Centre" in names and "Tax Configuration" not in names, str(names[:30]))
    open_mx_centre(a)
    check("01 Employer & Registrations section renders", "Employer & Registrations" in body(a)
          and "Record a legal employer (RFC)" in body(a), body(a)[:400])
    shot(a, "01_mx_centre_empty")

    # 2 — employer: bad RFC refused field-level, good RFC accepted, new version
    employer = {"taxpayerType": "MORAL", "legalName": "Empresa Sintética SA de CV", "fiscalRegimeCode": "601",
                "fiscalPostalCode": "06600", "placeOfIssuePostalCode": "06600", "effectiveFrom": "2026-01-01"}
    fill(a, "mx-new-employer", {**employer, "rfc": "ABCD010101AB1"})
    submit(a, "mx-new-employer", "Record employer")
    check("02 a 13-character RFC for a persona moral is refused with the field message",
          "a MORAL RFC is 12 characters" in body(a), body(a)[:600])
    shot(a, "02_rfc_refused")
    fill(a, "mx-new-employer", {**employer, "rfc": "ABC010101AB1"})
    submit(a, "mx-new-employer", "Record employer")
    txt = body(a)
    check("02 a valid RFC is accepted and panels A–H render",
          all(s in txt for s in ("Legal / tax entity", "SAT payroll", "IMSS employer registrations",
                                 "Establishments and state ISN", "Workweek and benefits", "Readiness on")), txt[:600])
    fill(a, "mx-new-version", {"effectiveFrom": "2026-07-01", "legalName": "Empresa Sintética v2 SA de CV"})
    submit(a, "mx-new-version", "Record new version")
    txt = body(a)
    check("02 new version recorded; v1 closed 2026-06-30", "2026-06-30" in txt and "Empresa Sintética v2" in txt, txt[:800])
    shot(a, "02_employer_versions")

    # 3 — two IMSS registrations; premium approval refused (four-eyes, single admin)
    for rp in ("Y1234567101", "Z7654321109"):
        fill(a, "mx-new-registration", {"registroPatronal": rp, "riskClass": "I", "fraction": "811",
                                        "effectiveFrom": "2026-01-01", "infonavitOperatingModel": "SUA"})
        submit(a, "mx-new-registration", "Add registration")
    txt = body(a)
    check("03 two IMSS registrations listed", "Y1234567101" in txt and "Z7654321109" in txt, txt[:800])
    a.get_by_label("Premium for registration").select_option(label="Y1234567101")
    settle(a, 500)
    fill(a, "mx-new-premium", {"determinationYear": "2025", "premiumRatePct": "1.5", "periodFrom": "2026-03-01",
                               "periodTo": "2027-02-28"})
    submit(a, "mx-new-premium", "Record premium (DRAFT)")
    a.locator('[data-testid="mx-panel-c"]').get_by_role("button", name="Approve").first.click()
    settle(a, 1200)
    txt = body(a)
    check("03 premium approval refused: waiting for a second org admin (four-eyes, no exception)",
          "waiting for a second org admin" in txt, txt[:800])
    shot(a, "03_registrations_premium_refused")

    # 4 — ISN: CDMX pending pack; another state refused (MX-045)
    fill(a, "mx-new-establishment", {"name": "Planta Jalisco", "stateCode": "JAL", "municipality": "Guadalajara",
                                     "postalCode": "44100"})
    submit(a, "mx-new-establishment", "Add establishment")
    fill(a, "mx-new-isn", {"stateCode": "CDMX", "localAccountNumber": "ISN-SYN-001", "effectiveFrom": "2026-01-01"})
    submit(a, "mx-new-isn", "Register for ISN")
    check("04 CDMX ISN registration shows PENDING_PACK", "PENDING_PACK" in body(a), body(a)[:800])
    fill(a, "mx-new-isn", {"stateCode": "JAL", "localAccountNumber": "ISN-SYN-002", "effectiveFrom": "2026-01-01"})
    submit(a, "mx-new-isn", "Register for ISN")
    txt = body(a)
    check("04 JAL refused with the MX-045 text", "JAL is not supported for state payroll tax" in txt and "MX-045" in txt,
          txt[:800])
    check("04 establishment minimum-wage zone UNRESOLVED (S9 not transcribed)", "UNRESOLVED" in txt)
    shot(a, "04_isn_and_establishments")

    # 5 — labour policy BLOCKED_CONTENT, activation refused
    fill(a, "mx-new-policy", {"effectiveFrom": "2026-03-01", "ordinaryWeeklyHours": "48", "aguinaldoDays": "15",
                              "vacationDaysYear1": "12", "vacationDaysLater": "14", "vacationPremiumPct": "25",
                              "sundayPremiumPct": "25"})
    submit(a, "mx-new-policy", "Record policy (DRAFT)")
    txt = body(a)
    check("05 labour policy floor check is BLOCKED_CONTENT with its reason",
          "BLOCKED_CONTENT" in txt and "statutory content not active" in txt, txt[:800])
    a.locator('[data-testid="mx-panel-fg"]').get_by_role("button", name="Activate").first.click()
    settle(a, 1200)
    check("05 activation refused", "cannot be activated: floor check BLOCKED_CONTENT" in body(a), body(a)[:800])
    shot(a, "05_labor_policy_blocked")

    # 6 — credentials
    fill(a, "mx-new-credential", {"kind": "CSD", "secretRef": PEM_KEY})
    submit(a, "mx-new-credential", "Save reference")
    txt = body(a)
    check("06 pasted private key refused and not shown back",
          "secretRef refused" in txt and "SYNTHETICKEY" not in txt and "BEGIN PRIVATE KEY" not in txt, txt[:800])
    shot(a, "06a_key_material_refused")
    fill(a, "mx-new-credential", {"kind": "CSD", "secretRef": "vault://secret/mx/csd"})
    submit(a, "mx-new-credential", "Save reference")
    check("06 vault:// scheme refused (only gcp-sm://)", "allowed scheme(s): gcp-sm://" in body(a), body(a)[:800])
    fill(a, "mx-new-credential", {"kind": "CSD", "secretRef": GCP_REF})
    submit(a, "mx-new-credential", "Save reference")
    a.reload(wait_until="networkidle")
    open_mx_centre(a)
    txt = body(a)
    check("06 gcp-sm:// reference accepted and shown masked only",
          "gcp-sm://…" in txt and "zoiko-browser-check" not in txt, txt[:800])
    a.get_by_label("Certificate for credential").select_option(index=1)
    a.get_by_label("Certificate file").set_input_files(CER)
    settle(a, 1500)
    txt = body(a)
    check("06 .cer upload shows serial, fingerprint and expiry", "c0ffee" in txt and "2027-12-0" in txt, txt[:1000])
    shot(a, "06b_credentials")

    # 7 — readiness H: date bar = local date, picker changes `on`, gates and unmapped
    readiness_on = a.locator('[data-testid="mx-readiness-on"]').inner_text()
    check("07 readiness date bar shows a date and the LIVE line is BLOCKED",
          re.search(r"Readiness on 20\d\d-\d\d-\d\d", readiness_on) and "BLOCKED" in a.locator('[data-testid="mx-live-eligibility"]').inner_text(),
          readiness_on)
    a.get_by_label("Readiness on").fill("2026-03-01")
    settle(a, 1500)
    h = a.locator('[data-testid="mx-panel-h"]').inner_text()
    check("07 picking 2026-03-01 re-reads readiness for that date", "Readiness on 2026-03-01" in h, h[:300])
    check("07 items show gates, unmapped items and Phase 7/8/10 blocks",
          all(s in h for s in ("unmapped", "Phase 7", "Phase 8", "Phase 10", "G1", "G4", "G5",
                               "waiting for a second org admin")), h[:1500])
    shot(a, "07_readiness_h")

    # 8 — operator: read-only UI, direct write 403
    o = new_page(browser, OPERATOR)
    open_mx_centre(o)
    txt = body(o)
    check("08 operator sees the employer data", "Empresa Sintética v2" in txt, txt[:600])
    status, _ = api(OPERATOR, "POST", "/api/payroll/mexico/employers",
                    {**employer, "rfc": "XYZ010101AB1", "withholdingObligationActive": True})
    check("08 operator write over the API → 403", status == 403, str(status))
    shot(o, "08_operator_view")

    # 9 — other tenant sees nothing; API 404 on A's employer
    b = new_page(browser, OTHER)
    open_mx_centre(b)
    check("09 another tenant has no legal employer and none of org A's data",
          "No legal employer yet" in body(b) and "Empresa Sintética" not in body(b), body(b)[:600])
    _, emps = api(ADMIN, "GET", "/api/payroll/mexico/employers")
    status, _ = api(OTHER, "GET", f"/api/payroll/mexico/employers/{emps[0]['employerId']}")
    check("09 another tenant → 404 on org A's employer id", status == 404, str(status))
    shot(b, "09_other_tenant")

    # 10 — Super Admin Employer tab: read-only, masked
    s = new_page(browser, "sa-a@mx.example.com")
    go(s, "/super-admin/compliance/mexico")
    s.get_by_text("MX-PAYROLL-2026", exact=True).first.click()
    settle(s)
    org_select = s.locator("select").first
    org_select.select_option(label="MX Browser Org")
    settle(s)
    s.get_by_role("button", name="Employer", exact=True).first.click()
    settle(s, 1500)
    txt = body(s)
    check("10 Super Admin Employer tab: panels render read-only, RFC masked",
          "Read-only" in txt and "Legal / tax entity" in txt and "ABC010101AB1" not in txt
          and "Record new version" not in txt and "Add registration" not in txt, txt[:1000])
    shot(s, "10_super_admin_employer_tab")
    s.get_by_role("button", name="Readiness G1–G8", exact=True).first.click()
    settle(s, 1500)
    check("10 Super Admin readiness: per-gate employer summary", "employer readiness" in body(s).lower()
          and "all items passing" in body(s).lower(), body(s)[:800])
    shot(s, "11_super_admin_readiness_summary")

    # 11 — regression: NL and HK org tabs
    n = new_page(browser, "admin@nlorg.example.com")
    go(n, "/payroll/compliances")
    nl = tab_names(n)
    check("12 NL org: Netherlands Compliance Centre, no Tax Configuration, no MX tab",
          "Netherlands Compliance Centre" in nl and "Tax Configuration" not in nl and "Mexico Compliance Centre" not in nl, str(nl[:30]))
    shot(n, "12_regression_nl_org")
    k = new_page(browser, "admin@hkorg.example.com")
    go(k, "/payroll/compliances")
    hk = tab_names(k)
    check("13 HK org: Hong Kong Compliance Centre and Tax Configuration kept, no MX tab",
          "Hong Kong Compliance Centre" in hk and "Tax Configuration" in hk and "Mexico Compliance Centre" not in hk, str(hk[:30]))
    shot(k, "13_regression_hk_org")
    go(s, "/super-admin/compliance/netherlands")
    check("14 Super Admin NL workspace still loads", "Netherlands" in body(s), body(s)[:300])
    shot(s, "14_regression_sa_nl")
    browser.close()

# 12 — only the refusals the script provoked failed
expected = [(w, m, path, st) for (w, m, path, st) in responses
            if (st == 400 and m in ("POST", "PUT") and "/api/payroll/mexico/" in path)]
# Pre-existing app-shell probe, not Mexico: a payroll_admin user's sidebar asks
# for the org-admin assisted-access status and gets 403 on every page.
shell = [r for r in responses if r[0] == OPERATOR and r[2] == "/api/organization-admin/assisted-access/status" and r[3] == 403]
unexpected = [r for r in responses if r not in expected and r not in shell]
check("15 no unexpected 4xx/5xx (only the provoked MX refusals)", not unexpected, str(unexpected[:10]))
# The browser logs each provoked 400 as "Failed to load resource"; anything else is an error.
resource_400 = [e for e in errors if "Failed to load resource: the server responded with a status of 400" in e]
shell_403 = [e for e in errors if e.startswith(OPERATOR) and "status of 403" in e]   # the same shell probe
other_errors = [e for e in errors if e not in resource_400 and (e not in shell_403 or len(shell_403) > len(shell))]
check("15 no page or console errors beyond the provoked refusals",
      not other_errors and len(resource_400) <= len(expected), f"{other_errors[:5]} / {len(resource_400)} vs {len(expected)}")
NOTES = (f"Provoked MX refusals (HTTP 400): {len(expected)}. Pre-existing non-Mexico shell probe "
         f"(payroll_admin → /api/organization-admin/assisted-access/status 403): {len(shell)} call(s).")

passed = sum(ok for _, ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
(OUT / "RESULTS.md").write_text(
    "# Mexico Phase 3 — real-browser acceptance\n\nInstalled Chrome (Playwright `channel=\"chrome\"`), `vite build` + "
    "`vite preview`, uvicorn on a throwaway SQLite DB (`harness/setup_db.py`, scratch path asserted). Users are "
    "throwaway `@example.com` accounts that exist only in that DB.\n\n"
    f"**{passed}/{len(results)} checks passed.**\n\n{NOTES}\n\n| Check | Result |\n|---|---|\n"
    + "\n".join(f"| {n} | {'PASS' if ok else 'FAIL — ' + d.replace('|', '/')[:300]} |" for n, ok, d in results) + "\n",
    encoding="utf-8")
