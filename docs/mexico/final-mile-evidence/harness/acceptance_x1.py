"""Mexico final mile X1 — the decision register, every state transition through
the real UI (installed Chrome, headless; vite preview of the current build;
scratch SQLite from setup_db.py, server from serve.py). Screenshots and
RESULTS-X1.md are written next to this folder."""
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


def open_decisions(page):
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(page)
    page.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(page)
    page.get_by_role("button", name=re.compile("^Decisions")).first.click()
    settle(page, 1800)


def decision(page, code, version=1):
    return tid(page, f"mx-decision-{code}-v{version}")


def expand(page, code, version=1):
    decision(page, code, version).locator("button").first.click()
    page.wait_for_timeout(400)


def status(page, code, version=1):
    return decision(page, code, version).locator('[data-testid="mx-decision-status"]').inner_text().strip()


def confirm(page, label):
    page.get_by_role("button", name=label, exact=True).last.click()
    settle(page, 1200)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    open_decisions(a)
    codes = {re.sub(r"^mx-decision-(.+)-v\d+$", r"\1", t) for t in
             a.locator('[data-testid^="mx-decision-"][data-testid*="-v"]').evaluate_all(
                 "els => els.map(e => e.dataset.testid)")}
    check("x1-1 the register lists the seeded decisions, all OPEN",
          {"D-01", "D-07b", "D-21", "D-22", "D-23", "C4", "C5", "C12"} <= codes and status(a, "D-01") == "OPEN",
          str(sorted(codes))[:300])
    a.get_by_label("Filter by gate").select_option("G1")
    settle(a, 1000)
    g1 = {re.sub(r"^mx-decision-(.+)-v\d+$", r"\1", t) for t in
          a.locator('[data-testid^="mx-decision-"][data-testid*="-v"]').evaluate_all("els => els.map(e => e.dataset.testid)")}
    check("x1-2 filtering by gate keeps only that gate's decisions", "D-01" in g1 and "D-13" not in g1, str(sorted(g1)))
    a.get_by_label("Filter by gate").select_option("")
    settle(a, 1000)
    expand(a, "D-01")
    body = decision(a, "D-01").inner_text()
    check("x1-3 D-01 shows its question, both options with sources, the block code and the content key",
          "MX_ROUNDING_RULE_MISSING" in body and "mx_rounding_rule" in body and "S35" in body and "Options" in body,
          body[:400])
    shot(a, "x1_01_d01_open", decision(a, "D-01"))

    form = a.get_by_role("form", name="Propose D-01")
    form.get_by_label("Chosen option").fill("ROUND:1")
    form.get_by_label("Cited sources").fill("S35")
    form.get_by_label("Rationale").fill("SYNTHETIC browser-check rationale")
    form.get_by_role("button", name="Propose").click()
    settle(a)
    check("x1-4 an answer outside the rounding grammar is refused", "MODE:QUANTUM" in a.locator("main").inner_text()
          and status(a, "D-01") == "OPEN", "")
    form.get_by_label("Chosen option").fill("HALF_UP:0.01")
    form.get_by_role("button", name="Propose").click()
    settle(a)
    check("x1-5 propose: D-01 becomes PROPOSED with its answer", status(a, "D-01") == "PROPOSED", status(a, "D-01"))

    expand(a, "D-01") if not decision(a, "D-01").get_by_role("button", name=re.compile("Approve")).count() else None
    decision(a, "D-01").get_by_role("button", name=re.compile("Approve")).click()
    confirm(a, "Approve")
    check("x1-6 the proposer cannot approve (four-eyes), refused on screen",
          "four-eyes" in a.locator("main").inner_text() and status(a, "D-01") == "PROPOSED", "")
    shot(a, "x1_02_self_approval_refused")

    b = new_page(browser, SA_B)
    open_decisions(b)
    expand(b, "D-01")
    decision(b, "D-01").get_by_role("button", name=re.compile("Approve")).click()
    confirm(b, "Approve")
    expand(b, "D-01") if not tid(b, "mx-decision-ticket").count() else None
    ticket = decision(b, "D-01").inner_text()
    check("x1-7 approve by a second Super Admin: APPROVED with a transcription ticket (Draft pack only)",
          status(b, "D-01") == "APPROVED" and "DECISION/D-01#" in ticket and "never an Active pack" in ticket, ticket[-400:])
    shot(b, "x1_03_d01_approved_ticket", decision(b, "D-01"))

    decision(b, "D-01").get_by_role("button", name="Mark transcribed").click()
    decision(b, "D-01").get_by_label("Transcription reference").fill("SYNTHETIC commit 0000000")
    confirm(b, "Mark transcribed")
    check("x1-8 mark transcribed with its reference", status(b, "D-01") == "TRANSCRIBED", status(b, "D-01"))
    expand(b, "D-01") if not decision(b, "D-01").get_by_role("button", name=re.compile("Revise")).count() else None
    decision(b, "D-01").get_by_role("button", name=re.compile("Revise")).click()
    confirm(b, "Revise")
    check("x1-9 revise: a new OPEN version 2 appears; version 1 stays in force",
          decision(b, "D-01", 2).count() == 1 and status(b, "D-01", 2) == "OPEN" and status(b, "D-01") == "TRANSCRIBED", "")

    expand(b, "D-17")
    f17 = b.get_by_role("form", name="Propose D-17")
    f17.get_by_label("Chosen option").fill("DAILY_SALARY_OVER_JORNADA_HOURS")
    f17.get_by_label("Cited sources").fill("S26")
    f17.get_by_label("Rationale").fill("SYNTHETIC")
    f17.get_by_role("button", name="Propose").click()
    settle(b)
    expand(b, "D-17") if not decision(b, "D-17").get_by_role("button", name="Withdraw proposal").count() else None
    decision(b, "D-17").get_by_role("button", name="Withdraw proposal").click()
    decision(b, "D-17").get_by_label("Withdrawal reason").fill("SYNTHETIC: wrong source")
    confirm(b, "Withdraw")
    check("x1-10 withdrawing a proposal returns the decision to OPEN", status(b, "D-17") == "OPEN", status(b, "D-17"))
    expand(b, "D-17") if not decision(b, "D-17").get_by_role("button", name="Withdraw decision").count() else None
    decision(b, "D-17").get_by_role("button", name="Withdraw decision").click()
    decision(b, "D-17").get_by_label("Withdrawal reason").fill("SYNTHETIC: no longer needed")
    confirm(b, "Withdraw")
    check("x1-11 withdrawing an OPEN decision closes it (WITHDRAWN)", status(b, "D-17") == "WITHDRAWN", status(b, "D-17"))
    shot(b, "x1_04_register_after_transitions")

    b.get_by_role("button", name=re.compile("Readiness G1")).first.click()
    settle(b, 1500)
    g1_line = tid(b, "mx-gate-checklist-G1").inner_text()
    check("x1-12 readiness counts the open decisions per gate", "open decisions" in g1_line, g1_line[:200])
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico final mile X1 -- decision register browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + d[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen (expected: the refused proposal and the refused self-approval): "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / "RESULTS-X1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
