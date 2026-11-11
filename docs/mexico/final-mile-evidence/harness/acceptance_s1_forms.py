"""Mexico sweep S1 — the org-admin inputs some decision options read, through
the real UI (installed Chrome, headless; vite preview of the current build;
scratch SQLite from setup_x4.py, server from `serve_x4.py on`):

  - the employee's Mexico profile: union member (C12) and an operator-entered
    SDI with its evidence (C4 OPERATOR_ENTERED) — an SDI without evidence is
    refused on screen, with evidence it is recorded;
  - the termination form: the indemnity daily salary and its evidence (D-12 c);
  - the labour-policy form: the daily-hours figure (D-17 c) and the employer's
    special-pay withholding method (D-08 PER_EMPLOYER), recorded and read back.

Screenshots and RESULTS-S1-FORMS.md are written next to this folder."""
import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
SCRATCH = Path(r"C:\Users\Nikhi\AppData\Local\Temp\claude\d--zoiko-payroll-platform"
               r"\98808133-a255-40fa-94ee-54c6330641ec\scratchpad")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
PASSWORD = "BrowserCheck!2026"
A0 = "admin0@mxfm4.example.com"
IDS = json.loads((SCRATCH / "x4_ids.json").read_text(encoding="utf-8"))
results, errors, responses, _tokens = [], [], [], {}


def token(email):
    if email not in _tokens:
        req = urllib.request.Request(f"{API}/api/auth/login", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"email": email, "password": PASSWORD}).encode())
        _tokens[email] = json.load(urllib.request.urlopen(req))
    return _tokens[email]


def api(email, path):
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token(email)['access_token']}"})
    return json.load(urllib.request.urlopen(req))


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
    a = new_page(browser, A0)

    # ── the employee's Mexico profile ──
    a.goto(APP + "/payroll/employees", wait_until="load")
    settle(a, 1800)
    a.get_by_text(IDS["employee_code"]).first.click()
    settle(a, 1500)
    a.get_by_role("button", name="Manage").last.click()
    settle(a, 2000)
    form = tid(a, "mx-profile-form")
    has = all(form.locator(f'[name="{k}"]').count() == 1
              for k in ("mx_union_member", "mx_sdi_operator_entered", "mx_sdi_evidence_ref"))
    check("s1f-1 the profile form offers union member (C12) and the operator-entered SDI + evidence (C4)", has, "")
    form.locator('[name="mx_union_member"]').select_option("true")
    form.locator('[name="mx_sdi_operator_entered"]').fill("712.40")
    form.get_by_role("button", name="Record new version").click()
    settle(a, 1500)
    text = a.locator('[role="dialog"]').inner_text()
    check("s1f-2 an SDI without its evidence is refused on screen", "evidence reference" in text, text[-500:])
    form.locator('[name="mx_sdi_evidence_ref"]').fill("SYNTHETIC contract annex 1")
    form.locator('[name="mx_sdi_operator_entered"]').scroll_into_view_if_needed()
    shot(a, "s1f_01_profile_sdi_union", form.locator("fieldset").filter(has_text="CFDI receiver"))
    form.get_by_role("button", name="Record new version").click()
    settle(a, 1800)
    text = a.locator('[role="dialog"]').inner_text()
    check("s1f-3 with its evidence the new profile version is recorded", "New Mexico profile version recorded" in text,
          text[-400:])

    # ── the termination form ──
    term = a.locator('[role="dialog"]').get_by_text(re.compile("Indemnity daily salary"))
    if not term.count():
        opener = a.locator('[role="dialog"]').get_by_role("button", name=re.compile("termination", re.I))
        if opener.count():
            opener.first.click()
            settle(a, 800)
    term = a.locator('[role="dialog"]').get_by_text(re.compile("Indemnity daily salary"))
    check("s1f-4 the termination form offers the indemnity daily salary and its evidence (D-12 c)",
          term.count() >= 1 and a.locator('[role="dialog"]').get_by_text("Evidence for that salary").count() >= 1, "")
    if term.count():
        term.first.scroll_into_view_if_needed()
        shot(a, "s1f_02_termination_indemnity", a.locator('[role="dialog"]'))

    # ── the labour-policy form ──
    a.goto(APP + "/payroll/compliances", wait_until="load")
    settle(a)
    a.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(a, 2500)
    pf = tid(a, "mx-new-policy")
    pf.scroll_into_view_if_needed()
    labels = pf.inner_text()
    check("s1f-5 the labour-policy form offers the daily-hours figure (D-17 c) and the employer's special-pay "
          "method (D-08 per employer)", "Daily hours for the overtime hourly rate" in labels
          and "Special-pay withholding method" in labels, labels[:400])
    for label, value in (("Effective from", "2027-01-01"), ("Ordinary weekly hours", "48"), ("Aguinaldo days", "15"),
                         ("Vacation days, year 1", "12"), ("Vacation days, year 2+", "14"), ("Vacation premium %", "25"),
                         ("Sunday premium %", "25"), ("Daily hours for the overtime hourly rate", "8")):
        box = pf.get_by_label(re.compile("^" + re.escape(label)))
        if box.count():
            box.first.fill(value)
    pf.get_by_label(re.compile("^Special-pay withholding method")).select_option("ART_96_MONTHLY")
    shot(a, "s1f_03_policy_form", pf)
    pf.get_by_role("button", name="Record policy (DRAFT)").click()
    settle(a, 2000)
    employers = api(A0, "/api/payroll/mexico/employers")
    employers = employers if isinstance(employers, list) else employers.get("data") or []
    policies = []
    for e in employers:
        policies += api(A0, f"/api/payroll/mexico/employers/{e['employerId']}").get("laborPolicies") or []
    latest = max(policies, key=lambda r: r["id"]) if policies else {}
    check("s1f-6 the policy is recorded with both figures and reads back",
          latest.get("specialPayWithholdingMethod") == "ART_96_MONTHLY" and latest.get("hourlyRateDailyHours") == "8.00",
          json.dumps(latest)[:300])
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico sweep S1 -- org-admin decision inputs, browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen (expected: the refused SDI without evidence): "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-S1-FORMS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
