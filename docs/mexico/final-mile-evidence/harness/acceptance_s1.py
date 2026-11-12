"""Mexico sweep S1 — decisions as configuration, through the real UI (installed
Chrome, headless; vite preview of the current build; scratch SQLite from
setup_db.py, server from serve.py):

  - unanswered, the sandbox still blocks at D-01;
  - a multi-part answer (D-28) is chosen part by part, its configuration panel
    says what answering changes and what is not built;
  - the proposer cannot approve; a second Super Admin does — the answer is
    "In force" at once;
  - with D-01 and D-03 APPROVED (no candidates), the sandbox CALCULATES and
    names the approved answers and the pack rows they filled.

Screenshots and RESULTS-S1.md are written next to this folder."""
import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
PASSWORD = "BrowserCheck!2026"
SA_A, SA_B = "sa-a@mxfm.example.com", "sa-b@mxfm.example.com"
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


def shot(page, name, locator=None):
    page.wait_for_timeout(300)
    target = locator.first if locator is not None and locator.count() else page
    target.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=60)


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


def open_tab(page, tab):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page)
    page.get_by_role("button", name=re.compile(f"^{tab}")).first.click()
    settle(page, 1800)


def decision(page, code, version=1):
    return tid(page, f"mx-decision-{code}-v{version}")


def expand(page, code):
    decision(page, code).locator("button").first.click()
    page.wait_for_timeout(400)


def status(page, code):
    return decision(page, code).locator('[data-testid="mx-decision-status"]').inner_text().strip()


def confirm(page, label):
    page.get_by_role("button", name=label, exact=True).last.click()
    settle(page, 1200)


def propose(page, code, value, sources):
    expand(page, code)
    form = page.get_by_role("form", name=f"Propose {code}")
    box = form.get_by_label("Chosen option")
    if box.evaluate("e => e.tagName") == "SELECT":
        box.select_option(value)
    else:
        box.fill(value)
    form.get_by_label("Cited sources").fill(sources)
    form.get_by_label("Rationale").fill("SYNTHETIC browser-check rationale")
    form.get_by_role("button", name="Propose").click()
    settle(page)


def approve(page, code):
    if not decision(page, code).get_by_role("button", name=re.compile("Approve")).count():
        expand(page, code)
    decision(page, code).get_by_role("button", name=re.compile("Approve")).click()
    confirm(page, "Approve")


def run_sandbox(page):
    page.get_by_role("button", name="Run sandbox").click()
    settle(page, 1500)
    return tid(page, "mx-sandbox-result").inner_text() if tid(page, "mx-sandbox-result").count() else \
        page.locator("main").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    open_tab(a, "Sandbox")
    out = run_sandbox(a)
    check("s1-1 unanswered, the sandbox still stops at D-01's block code; no approved decisions in force",
          "MX_ROUNDING_RULE_MISSING" in out and "cleared by D-01" in out
          and "Approved decisions in force: none" in out, out[:400])

    open_tab(a, "Decisions")
    expand(a, "D-28")
    body = decision(a, "D-28").inner_text()
    parts = decision(a, "D-28").locator('[data-testid="mx-decision-parts"] select')
    check("s1-2 D-28 offers one choice per part (6) and its configuration panel: what answering changes, "
          "what is not built", parts.count() == 6 and "Answering changes:" in body
          and "second org admin" in body and "Still needs:" in body, f"{parts.count()} {body[:300]}")
    form = a.get_by_role("form", name="Propose D-28")
    for i, part in enumerate(("EMPLOYER_VERSION", "ESTABLISHMENT", "IMSS_REGISTRATION", "INFONAVIT_MODEL",
                              "LABOR_POLICY_ACTIVATION", "CREDENTIAL")):
        form.get_by_label(f"Part {part}").select_option("FOUR_EYES" if i % 2 == 0 else "SINGLE")
    form.get_by_label("Cited sources").fill("GAP-REGISTER")
    form.get_by_label("Rationale").fill("SYNTHETIC browser-check rationale")
    shot(a, "s1_01_d28_parts_configuration", decision(a, "D-28"))
    form.get_by_role("button", name="Propose").click()
    settle(a)
    body = decision(a, "D-28").inner_text()
    check("s1-3 the per-part choices are proposed as one PARTS answer", status(a, "D-28") == "PROPOSED"
          and "EMPLOYER_VERSION=FOUR_EYES" in body and "CREDENTIAL=SINGLE" in body, body[:400])
    approve(a, "D-28")
    check("s1-4 the proposer cannot approve (four-eyes)", "four-eyes" in a.locator("main").inner_text()
          and status(a, "D-28") == "PROPOSED", "")

    propose(a, "D-01", "HALF_UP:0.01", "S35")
    propose(a, "D-03", "GENERAL", "S10")
    check("s1-5 D-01 and D-03 proposed", status(a, "D-01") == "PROPOSED" and status(a, "D-03") == "PROPOSED",
          f"{status(a, 'D-01')} {status(a, 'D-03')}")

    b = new_page(browser, SA_B)
    open_tab(b, "Decisions")
    for code in ("D-28", "D-01", "D-03"):
        expand(b, code)
        approve(b, code)
    if not tid(b, "mx-decision-ticket").count():
        expand(b, "D-28")
    ticket = decision(b, "D-28").inner_text()
    check("s1-6 a second Super Admin approves: each is APPROVED and 'In force' at once (no transcription needed)",
          [status(b, c) for c in ("D-28", "D-01", "D-03")] == ["APPROVED"] * 3 and "In force" in ticket
          and "second org admin" in ticket, ticket[-400:])
    shot(b, "s1_02_d28_in_force", decision(b, "D-28"))

    open_tab(b, "Sandbox")
    out = run_sandbox(b)
    check("s1-7 with D-01 and D-03 APPROVED (no candidates) the sandbox CALCULATES, not watermarked CANDIDATE, "
          "and names the answers and the pack rows they filled",
          tid(b, "mx-sandbox-calculated").count() == 1 and "CANDIDATE" not in out
          and "D-01 v1 = HALF_UP:0.01" in out and "D-03 v1 = GENERAL" in out
          and "Pack rows filled from them: D-01, D-03" in out, out[:600])
    shot(b, "s1_03_sandbox_with_approved_decisions", tid(b, "mx-sandbox-result"))
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico sweep S1 -- decisions as configuration, browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen (expected: the refused self-approval): "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-S1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
