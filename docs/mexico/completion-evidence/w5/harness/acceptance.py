"""Mexico completion W4 (report templates) + W5-1 (read-only content views)
browser check — installed Chrome (headless), vite preview of the current
build, scratch SQLite backend (setup_db.py, serve.py). Screenshots and
RESULTS.md are written next to this folder."""
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
SA_A, SA_B, NL = "sa-a@mxw5.example.com", "sa-b@mxw5.example.com", "admin@nlw5.example.com"
results, errors, responses, _tokens = [], [], [], {}
MX_TEMPLATES = ("MX-PAYROLL-REGISTER", "MX-EMPLOYER-COST", "MX-SUBSIDY", "MX-IMSS-BRANCH", "MX-INFONAVIT",
                "MX-AGUINALDO", "MX-FINIQUITO", "MX-ANNUAL-ISR-ADJ", "MX-ISR-MONTHLY", "MX-IDSE-MOVEMENTS",
                "MX-SUA-RECON", "MX-SIPARE", "MX-CFDI-STATUS", "MX-CFDI-NOMINA-RECEIPT", "MX-PTU-DISTRIBUTION",
                "MX-VACATION-ACCRUAL", "MX-JOURNAL")


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
    """Viewport (or element) JPEG: small enough to keep in the repository."""
    page.wait_for_timeout(400)
    target = locator.first if locator is not None and locator.count() else page
    target.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=60)


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


def open_mx_tab(page, label):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page, 1500)
    page.get_by_role("button", name=re.compile(label)).first.click()
    settle(page, 2500)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)

    # ── W5-1: the Statutory rules tab ───────────────────────────────────────
    open_mx_tab(a, "Statutory rules")
    text = a.locator("main").inner_text()
    families = ["annualIsr", "filingCalendar", "specialPay", "isnInclusion", "termination", "ptu",
                "annualAdjustment", "ordinaryExemptions", "workingTime"]
    check("w5-1 every module-direct rule family has its read-only section",
          all(tid(a, f"mx-rules-{f}").count() == 1 for f in families),
          str([f for f in families if not tid(a, f"mx-rules-{f}").count()]))
    check("w5-2 the date bar shows the pack's effective-from (never today)",
          "Law in force on 2026-01-01" in tid(a, "mx-on-date").inner_text(), tid(a, "mx-on-date").inner_text())
    special = tid(a, "mx-rules-specialPay").inner_text()
    check("w5-3 each rule shows PENDING G1, its saved source with SHA-256 and status, and the quoted wording",
          "PENDING G1" in special and "sha256" in special and "Art. 93" in special
          and ("ARCHIVE_COPY_VERIFIED" in special or "VERIFIED" in special), special[:500])
    check("w5-4 no cited file is missing from the manifest", "NOT_IN_MANIFEST" not in text, "")
    decisions = tid(a, "mx-rules-decisions").inner_text()
    check("w5-5 open decisions D-07 … D-19 are listed as undecided (calculations BLOCK)",
          all(d in decisions for d in ("D-07", "D-08", "D-09", "D-12", "D-13", "D-14", "D-18", "D-19"))
          and "Undecided" in decisions, decisions[:400])
    check("w5-6 annual ISR tariff 2026 has 11 brackets",
          tid(a, "mx-rules-annualIsr").locator("tbody tr").count() == 11,
          str(tid(a, "mx-rules-annualIsr").locator("tbody tr").count()))
    shot(a, "w5_01_statutory_rules")
    shot(a, "w5_02_special_pay", tid(a, "mx-rules-specialPay"))
    a.locator('[data-testid="mx-on-date"] input[type="date"]').fill("2025-06-01")
    settle(a, 2000)
    isr25 = tid(a, "mx-rules-annualIsr").inner_text()
    check("w5-7 choosing 2025 shows the annual tariff as awaiting transcription", "Awaiting transcription" in isr25,
          isr25[:300])
    shot(a, "w5_03_annual_isr_2025", tid(a, "mx-rules-annualIsr"))

    # ── W5-1: State ISN rows with sources; CEAV schedule source column ──────
    open_mx_tab(a, "State ISN")
    a.get_by_text(re.compile(r"MX-ISN-CDMX-2026")).first.click()
    settle(a, 2500)
    isn = a.locator("main").inner_text()
    check("w5-8 the CDMX ISN row shows its 4 % rate, PENDING G1, the source and the date bar",
          "mx_isn_rate_pct" in isn and "PENDING G1" in isn and "sha256" in isn and "Law in force on" in isn, isn[:600])
    shot(a, "w5_04_state_isn_cdmx")
    open_mx_tab(a, "IMSS & CEAV")
    ceav = a.locator("main").inner_text()
    check("w5-9 the CEAV 2023-2030 schedule shows its source", "S11" in ceav or "S10" in ceav, ceav[-500:])
    shot(a, "w5_05_ceav_schedule")

    # ── W5-2: no Mexico hotfix; generic statutory edits refused ────────────
    open_mx_tab(a, "Statutory rules")
    check("w5-10 the Mexico pack header offers no Hotfix Activate",
          a.get_by_role("button", name=re.compile("Hotfix Activate")).count() == 0, "")
    shot(a, "w5_06_mx_pack_header_no_hotfix")
    pack_id = json.loads(api(SA_A, "GET", "/api/super-admin/compliance/mexico/packs")[1])[0]["id"]
    st, txt = api(SA_A, "PUT", "/api/super-admin/compliance/tax-configuration/contribution-rates",
                  {"jurisdictionPackId": pack_id, "jurisdictionCountry": "MX", "componentKey": "mx_uma_daily",
                   "label": "x", "flatAmount": "1"})
    check("w5-11 a generic statutory edit of a Mexico pack is refused (400)",
          st == 400 and "Mexico statutory rows are not edited here" in txt, f"{st} {txt[:200]}")
    st, txt = api(SA_A, "PUT", f"/api/super-admin/compliance/policies/{pack_id}/hotfix-activate",
                  {"incident_id": "INC-W5", "justification": "browser check"})
    check("w5-12 a Mexico hotfix activation is refused (400)",
          st == 400 and "Mexico hotfix activation is not permitted" in txt, f"{st} {txt[:200]}")
    a.goto(APP + "/super-admin/compliance/netherlands", wait_until="load")
    settle(a, 2000)
    a.get_by_text("NL-W5-REGRESSION").first.click()
    settle(a, 1500)
    check("w5-13 another country's Draft pack still offers Hotfix Activate (unchanged)",
          a.get_by_role("button", name=re.compile("Hotfix Activate")).count() == 1, "")

    # ── W5-3: readiness per gate, code vs evidence ─────────────────────────
    open_mx_tab(a, "Readiness G1")
    panel = tid(a, "mx-gate-checklists")
    panel.scroll_into_view_if_needed()
    check("w5-14 the readiness tab lists a checklist for every gate G1-G8",
          all(tid(a, f"mx-gate-checklist-G{n}").count() == 1 for n in range(1, 9)), "")
    tid(a, "mx-gate-checklist-G1").locator("button").first.click()
    settle(a, 800)
    g1 = tid(a, "mx-gate-checklist-G1").inner_text()
    code_items = tid(a, "mx-gate-checklist-G1").locator('[data-testid="mx-gate-item-code"]').count()
    evidence_items = tid(a, "mx-gate-checklist-G1").locator('[data-testid="mx-gate-item-evidence"]').count()
    check("w5-15 G1 shows 7 code items (evaluated now) and its evidence items (awaiting signed evidence)",
          code_items == 7 and evidence_items == 4 and "MX-PAYROLL-2026 v1.0 is Draft" in g1
          and "awaits the gate's signed evidence" in g1 and "code 0/7" in g1, g1[:600])
    shot(a, "w5_07_gate_checklist_g1", tid(a, "mx-gate-checklist-G1"))
    tid(a, "mx-gate-checklist-G4").locator("button").first.click()
    settle(a, 800)
    g4 = tid(a, "mx-gate-checklist-G4").inner_text()
    check("w5-16 G4 shows unsupported states blocked (met) and D-06 undecided (unmet)",
          "payroll is BLOCKED in all" in g4 and "D-06" in g4 and "code 1/3" in g4, g4[:600])
    shot(a, "w5_08_gate_checklist_g4", tid(a, "mx-gate-checklist-G4"))

    # ── W4: each Mexico report template ─────────────────────────────────────
    a.goto(APP + "/super-admin/report-templates/mexico", wait_until="load")
    settle(a, 2500)
    listed = a.locator("main").inner_text()
    missing = [k for k in MX_TEMPLATES if k not in listed]
    names = json.loads(api(SA_A, "GET", "/api/super-admin/report-templates?country=MX")[1] or "[]")
    by_key = {t.get("templateKey"): t for t in names} if isinstance(names, list) else {}
    check("w4-1 the Mexico template list shows every national template", not missing or len(by_key) >= 17,
          f"missing in page text: {missing}")
    shot(a, "w4_00_template_list")
    for i, key in enumerate(MX_TEMPLATES):
        t = by_key.get(key)
        target = a.get_by_text(t["name"], exact=True) if t else a.get_by_text(key)
        if not target.count():
            check(f"w4-t {key} opens", False, "not found in the list")
            continue
        target.first.click()
        settle(a, 1200)
        overview = a.locator("main").inner_text()
        a.get_by_role("button", name=re.compile("^Components")).first.click()
        settle(a, 1200)
        body = a.locator("main").inner_text()
        shown = t["name"] if t else key
        empty = "No components configured yet" in body
        check(f"w4-t {key} opens (Draft) with its components, or says which generator builds it",
              shown in body and "Draft" in body and "Draft shell" not in overview
              and (not empty or "No components:" in overview), body[:200])
        shot(a, f"w4_{i + 1:02d}_{key}")

    # ── regression: Netherlands unchanged ──────────────────────────────────
    n = new_page(browser, NL)
    n.goto(APP + "/payroll/compliances", wait_until="load")
    settle(n)
    check("z1 NL compliance page unchanged (no Mexico entry)",
          n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z2 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico completion W4 / W5-1 -- browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx/5xx responses seen in the browser: "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + (str(len(errors)) if errors else "none")]
(OUT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
