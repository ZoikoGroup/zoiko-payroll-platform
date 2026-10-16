"""Mexico Phase 2 real-browser acceptance (installed Chrome, vite preview bundle,
throwaway SQLite backend). Every check asserts POSITIVE on-screen content;
any page error or console error fails the run. Full-page screenshots go to
docs/mexico/phase2-evidence/."""
import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase2-evidence")
OUT.mkdir(parents=True, exist_ok=True)
results, errors, failed_responses = [], [], []


def login(email):
    req = urllib.request.Request(f"{API}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": "BrowserCheck!2026"}).encode())
    tok = json.load(urllib.request.urlopen(req))
    return (f"localStorage.setItem('zoiko_payroll_access', {json.dumps(tok['access_token'])});"
            f"localStorage.setItem('zoiko_payroll_refresh', {json.dumps(tok['refresh_token'])});"
            f"localStorage.setItem('zoiko_payroll_user', {json.dumps(json.dumps(tok['user']))});")


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def text(page):
    return page.inner_text("body")


def shot(page, name):
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


def has(page, *needles):
    body = text(page)
    missing = [n for n in needles if n not in body]
    return not missing, f"missing {missing}"


def new_page(browser, who):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(login(who))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{who} pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"{who} console.error: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: failed_responses.append((r.request.method, re.sub(r"^.*?/api/", "/api/", r.url), r.status))
            if r.status >= 400 else None)
    return page


def go(page, path):
    page.goto(APP + path, wait_until="networkidle")
    page.wait_for_timeout(800)


def open_mx_pack(page):
    go(page, "/super-admin/compliance/mexico")
    page.get_by_text("MX-PAYROLL-2026", exact=True).first.click()
    page.wait_for_timeout(800)


def tab(page, label):
    page.get_by_role("button", name=label, exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(700)


TABS = ["ISR tariffs", "Subsidy & UMA", "Minimum wages", "IMSS & CEAV", "INFONAVIT", "Benefits & workweek",
        "Earning classification", "CFDI catalogs", "State ISN", "Sources", "Tests", "Readiness G1–G8"]

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, "sa-a@mxbrowsercheck.io")

    # 1. Compliance landing lists Mexico
    go(a, "/super-admin/compliance")
    check("landing: Mexico card", *has(a, "Mexico"))
    shot(a, "01_compliance_landing")

    # 2. Mexico workspace and its tab set
    open_mx_pack(a)
    body = text(a)
    check("workspace: every Mexico tab present", all(t in body for t in TABS),
          f"missing {[t for t in TABS if t not in body]}")
    check("workspace: generic Rates/Slabs editors hidden", "Contribution Rates" not in body and "Tax Slabs" not in body)
    check("workspace: no TaxabilityMatrix tab", "Taxability" not in body)
    shot(a, "02_mx_workspace_overview")

    # 3. Read-only content tabs: explicit date bar, never today, awaiting transcription
    for i, (label, what) in enumerate([("ISR tariffs", "Art. 96 ISR tariff"), ("Subsidy & UMA", "UMA or employment-subsidy"),
                                        ("Minimum wages", "minimum-wage content"), ("IMSS & CEAV", "IMSS branch content"),
                                        ("INFONAVIT", "INFONAVIT content"), ("Benefits & workweek", "benefit-floor")], start=3):
        tab(a, label)
        ok, detail = has(a, "Law in force on 2026-01-01", "the pack's effective-from", "Awaiting transcription", what,
                         "The server date is never used")
        check(f"{label}: date bar = pack effective-from, awaiting transcription", ok, detail)
        shot(a, f"{i:02d}_tab_{re.sub('[^a-z]+', '_', label.lower()).strip('_')}")
    tab(a, "ISR tariffs")
    a.get_by_label("In force on").fill("2026-02-01")
    a.wait_for_load_state("networkidle")
    a.wait_for_timeout(800)
    check("ISR tariffs: picker selects 2026-02-01", *has(a, "Law in force on 2026-02-01", "the date you chose"))
    shot(a, "09_isr_date_picker_feb")

    # 4. Earning classification: multi-axis draft; creator cannot approve
    tab(a, "Earning classification")
    check("classification: every axis shown, S28 note", *has(a, "Every axis is independent", "S28"))
    a.get_by_role("button", name="New classification").click()
    form = a.get_by_role("form", name="New classification")
    form.get_by_label("Earning code").fill("SUELDO")
    form.get_by_label("Label").fill("Browser-check salary (synthetic)")
    form.get_by_label("Effective from").fill("2026-01-01")
    def pick(label, value):
        form.locator("label", has_text=re.compile("^" + re.escape(label))).locator("select").first.select_option(value)
    pick("ISR", "TAXABLE")
    pick("SBC (IMSS base)", "FIXED")
    for lbl in ("INFONAVIT base", "State ISN base (default)", "PTU wage base"):
        pick(lbl, "true")
    pick("CFDI node", "PERCEPCION")
    shot(a, "10_classification_form")
    form.get_by_role("button", name="Save draft").click()
    a.wait_for_timeout(1200)
    check("classification: draft recorded", *has(a, "Draft recorded", "SUELDO", "DRAFT"))
    a.locator("tr", has_text="SUELDO").get_by_role("button", name="Approve", exact=True).click()
    a.wait_for_timeout(1200)
    check("classification: creator's approval refused (four-eyes)",
          *has(a, "You created this classification — a different Super Admin must approve it"))
    shot(a, "11_classification_four_eyes")

    # 5. CFDI catalogs: register + submit; creator cannot approve
    tab(a, "CFDI catalogs")
    a.get_by_label("CFDI version").fill("4.0")
    a.get_by_label("Complement version").fill("1.2")
    a.get_by_role("button", name="Register release").click()
    a.wait_for_timeout(1000)
    release_row = a.locator("tr", has_text="1.2")
    release_row.get_by_role("button", name="submit", exact=True).click()
    a.wait_for_timeout(1000)
    release_row.get_by_role("button", name="approve", exact=True).click()
    a.wait_for_timeout(1000)
    check("cfdi: release In Review, creator's approval refused",
          *has(a, "In Review", "You registered this release — a different Super Admin must approve it"))
    shot(a, "12_cfdi_four_eyes")

    # 6. State ISN accordion: 32 entities, CDMX pack, the rest BLOCKED
    tab(a, "State ISN")
    check("isn: 32 entities summary", *has(a, "32 federal entities · 1 with an ISN pack · 31 unsupported (payroll BLOCKED)"))
    a.get_by_test_id("mx-isn-CDMX").get_by_role("button").first.click()
    a.wait_for_timeout(1000)
    check("isn: CDMX pack, awaiting transcription", *has(a, "MX-ISN-CDMX-2026", "Awaiting transcription — no ISN rate"))
    shot(a, "13_isn_cdmx")
    a.get_by_test_id("mx-isn-JAL").get_by_role("button").first.click()
    a.wait_for_timeout(800)
    check("isn: Jalisco unsupported and BLOCKED", *has(a, "Jalisco has no certified ISN content pack", "BLOCKED"))
    shot(a, "14_isn_unsupported_state")

    # 7. Sources / Tests tabs render
    tab(a, "Tests")
    check("tests tab: MX fixtures path", *has(a, "mx_golden"))
    shot(a, "15_tests_tab")

    # 8. Readiness: G1–G8 OPEN + per-pack activation checklist
    tab(a, "Readiness G1–G8")
    ok, detail = has(a, "Release gates", "G1", "G8", "OPEN", "Cannot be activated yet.", "Content present and exact",
                     "awaiting transcription", "Every row linked to a hashed source", "G1 human review by a non-activator",
                     "Pack-bound golden PASS", "MX-ISN-CDMX-2026")
    check("readiness: gates + activation checklist for both packs", ok, detail)
    check("readiness: two packs not activatable", text(a).count("Cannot be activated yet.") == 2)
    shot(a, "16_readiness_activation")

    # 9. Second Super Admin approves the CFDI release; activation refused (Phase 7)
    b = new_page(browser, "sa-b@mxbrowsercheck.io")
    open_mx_pack(b)
    tab(b, "CFDI catalogs")
    b_row = b.locator("tr", has_text="1.2")
    b_row.get_by_role("button", name="approve", exact=True).click()
    b.wait_for_timeout(1000)
    check("cfdi: second Super Admin approves", *has(b, "approve done."))
    b_row.get_by_role("button", name="activate", exact=True).click()
    b.wait_for_timeout(1000)
    check("cfdi: activation refused until Phase 7 PAC validation", *has(b, "Phase 7 PAC validation"))
    shot(b, "17_cfdi_activate_refused")
    tab(b, "Earning classification")
    b.locator("tr", has_text="SUELDO").get_by_role("button", name="Approve", exact=True).click()
    b.wait_for_timeout(1200)
    check("classification: canonical approval refused without S28 catalog code",
          *has(b, "the SAT Nómina 1.2 catalog (S28) is not VERIFIED yet"))
    shot(b, "18_classification_canonical_needs_s28")

    # 10. State route, statutory and report-template pages
    go(a, "/super-admin/compliance/mexico/CDMX")
    check("route /compliance/mexico/CDMX: CDMX pack listed", *has(a, "MX-ISN-CDMX-2026", "CDMX"))
    shot(a, "19_route_compliance_cdmx")
    go(a, "/super-admin/statutory-rates/mexico")
    check("statutory-rates/mexico renders", *has(a, "Mexico"))
    shot(a, "20_statutory_rates_mexico")
    go(a, "/super-admin/report-templates/mexico")
    check("report-templates/mexico lists Draft templates", *has(a, "Mexico payroll register", "Draft"))
    shot(a, "21_report_templates_mexico")
    go(a, "/super-admin/report-templates/mexico/CDMX")
    check("report-templates/mexico/CDMX: ISN return", *has(a, "Impuesto Sobre Nóminas return — CDMX"))
    shot(a, "22_report_templates_cdmx")
    go(a, "/super-admin/compliance/test-certification")
    check("test-certification lists Mexico", *has(a, "Mexico (SAT / IMSS)"))
    go(a, "/super-admin/compliance/engine-defaults")
    check("engine-defaults lists Mexico", *has(a, "Mexico"))
    shot(a, "23_engine_defaults")

    # 11. Regression: other jurisdictions still render
    go(a, "/super-admin/compliance/netherlands")
    a.get_by_text("NL-PAYROLL-2026", exact=True).first.click()
    a.wait_for_timeout(800)
    check("regression: NL workspace + its tabs", *has(a, "Netherlands Compliance", "Wage-tax tables", "Readiness G1–G8"))
    shot(a, "24_regression_nl")
    go(a, "/super-admin/compliance/australia")
    check("regression: AU workspace", *has(a, "Australia Compliance"))
    shot(a, "25_regression_au")
    go(a, "/super-admin/statutory-rates/netherlands")
    check("regression: NL statutory rates", *has(a, "Netherlands"))
    go(a, "/super-admin/report-templates/netherlands")
    check("regression: NL report templates", *has(a, "Netherlands"))
    browser.close()

import sqlite3  # noqa: E402
_db = sqlite3.connect(str(Path(__file__).parent / "mx_browser.db"))
_packs = _db.execute("select pack_id, status from payroll_jurisdiction_packs where jurisdiction_country='MX'").fetchall()
check("final state: every MX pack still Draft", all(s == "Draft" for _, s in _packs), str(_packs))

# The run provokes exactly four refusals on purpose; each is a 400 the browser
# also logs as "Failed to load resource". Anything else is a real error.
EXPECTED_REFUSALS = [
    ("POST", "/earning-classifications/1/approve"),   # SA-A: creator may not approve
    ("PUT", "/cfdi-catalogs/1/approve"),              # SA-A: registrant may not approve
    ("PUT", "/cfdi-catalogs/1/activate"),             # SA-B: refused until Phase 7
    ("POST", "/earning-classifications/1/approve"),   # SA-B: canonical row needs the S28 catalog
]
seen = sorted((m, u.split("/compliance/mexico")[-1], s) for m, u, s in failed_responses)
check("the only failed requests are the four intended refusals (all 400)",
      seen == sorted((m, u, 400) for m, u in EXPECTED_REFUSALS), str(seen))
unexpected = [e for e in errors if "pageerror" in e or "Failed to load resource: the server responded with a status of 400" not in e]
check("no page errors and no console errors other than those refusals", not unexpected and
      len(errors) == len(EXPECTED_REFUSALS), "; ".join(unexpected[:5]) or f"{len(errors)} console errors")
passed = sum(ok for _, ok, _ in results)
print(f"\n{passed}/{len(results)} checks passed")
(OUT / "RESULTS.md").write_text(
    "# Mexico Phase 2 — browser acceptance results\n\n"
    "Real Chrome (Playwright, headless) against the `vite build` bundle served by `vite preview`, backed by a\n"
    "throwaway SQLite database seeded with the REAL (empty) Mexico Draft packs and templates.\n\n"
    f"**{passed}/{len(results)} checks passed.**\n\n| # | Check | Result |\n|---|---|---|\n"
    + "\n".join(f"| {i} | {n} | {'PASS' if ok else 'FAIL — ' + d} |" for i, (n, ok, d) in enumerate(results, 1))
    + ("\n\nBrowser console errors — all four are the intended refusals (checks 36–37 prove each one maps to an expected 400):\n" + "\n".join(f"- {e}" for e in errors) if errors else "\n"),
    encoding="utf-8")
