"""Mexico final mile X2 — the calculation sandbox through the real UI: the
expected block linked to D-01, the D-01 → D-03 chain, the spec §21 fixtures
F1–F4 under watermarked what-if candidates, a refused candidate, and no row
written to the scratch database. Same harness as X1 (setup_db.py, serve.py)."""
import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
PASSWORD = "BrowserCheck!2026"
SA_A = "sa-a@mxfm.example.com"
DB_FILE = os.environ["PAYROLL_DATABASE_URL"].replace("sqlite:///", "")
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


def counts():
    con = sqlite3.connect(DB_FILE)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


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


def run(page):
    page.get_by_role("button", name="Run sandbox").click()
    settle(page, 1500)
    return tid(page, "mx-sandbox-result").inner_text() if tid(page, "mx-sandbox-result").count() else \
        page.locator("main").inner_text()


def candidate(page, i, decision, value):
    page.get_by_role("button", name="Add candidate").click()
    page.get_by_label(f"Candidate {i} decision").fill(decision)
    page.get_by_label(f"Candidate {i} value").fill(value)


token(SA_A)                       # the sign-in writes its own auth / security rows: take them before the snapshot
before = counts()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    a = new_page(browser, SA_A)
    a.goto(APP + "/super-admin/compliance/mexico", wait_until="load")
    settle(a)
    a.get_by_text(re.compile(r"^MX-PAYROLL-")).first.click()
    settle(a)
    a.get_by_role("button", name=re.compile("^Sandbox")).first.click()
    settle(a, 1500)

    out = run(a)
    check("x2-1 today the run stops at MX_ROUNDING_RULE_MISSING, cleared by D-01, on the Draft pack",
          "MX_ROUNDING_RULE_MISSING" in out and "cleared by D-01" in out and "NOT ACTIVE" in out
          and "SANDBOX — SYNTHETIC INPUTS — NOT A PAYSLIP" in out and "CANDIDATE" not in out, out[:400])
    shot(a, "x2_01_blocked_d01", tid(a, "mx-sandbox-result"))

    candidate(a, 1, "D-01", "HALF_UP:0.01")
    out = run(a)
    check("x2-2 with a D-01 candidate it stops at D-03 (every employee: the X2 finding)",
          "mx_ceav_lowest_band_min_wage_ref" in out and "cleared by D-03" in out
          and "CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR" in out, out[:400])

    candidate(a, 2, "D-03", "GENERAL")
    a.get_by_role("button", name="F2 first-year SBC").click()
    out = run(a)
    check("x2-3 F2: with both candidates the run is CALCULATED, watermarked, SBC factor 1.049315…",
          tid(a, "mx-sandbox-calculated").count() == 1 and "CANDIDATE — NOT APPROVED" in out
          and "1.049315" in out and "service year 1" in out, out[:500])
    shot(a, "x2_02_f2_calculated_candidate", tid(a, "mx-sandbox-result"))
    tid(a, "mx-sandbox-watermarks").scroll_into_view_if_needed()
    a.mouse.wheel(0, -200)
    shot(a, "x2_02b_candidate_watermark")

    a.get_by_role("button", name="F1 Jan (UMA 113.14)").click()
    jan = run(a)
    a.get_by_role("button", name="F1 Feb (UMA 117.31)").click()
    feb = run(a)
    check("x2-4 F1: January uses UMA 113.14, February 117.31 (25-UMA cap moves with it)",
          "113.14" in jan and "2828.5" in jan and "117.31" in feb and "2932.75" in feb, (jan[:200], feb[:200]))

    a.get_by_role("button", name="F3 CEAV high band").click()
    out = run(a)
    check("x2-5 F3: CEAV employer 7.513 % in band 4.01UMA, employee 1.125 %, retiro 2 %",
          "7.5130" in out and "4.01UMA" in out and "1.12500" in out and "2.0000" in out, out[-600:])
    shot(a, "x2_03_f3_ceav_band", tid(a, "mx-sandbox-result"))

    a.get_by_role("button", name="F4 general zone").click()
    gen = run(a)
    a.get_by_role("button", name="F4 ZLFN").click()
    zlfn = run(a)
    check("x2-6 F4: 400 / day is lawful in the general zone (floor 315.04) and below the ZLFN floor",
          "315.04" in gen and "MX_BELOW_MINIMUM_WAGE" in zlfn and "ZLFN" in zlfn, (gen[:200], zlfn[:200]))

    a.get_by_label("Candidate 1 decision").fill("D-07")
    a.get_by_label("Candidate 1 value").fill("UMA")
    out = run(a)
    check("x2-7 a candidate for a module switch (D-07) is refused on screen", "module switch" in out, out[:300])
    browser.close()

after = counts()
check("x2-8 nothing was written: every table's row count unchanged", after == before,
      str({t: (before.get(t), after.get(t)) for t in set(before) | set(after) if before.get(t) != after.get(t)}))
unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = ["# Mexico final mile X2 -- calculation sandbox browser check", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen (expected: the refused D-07 candidate): "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none"),
          "", "Candidate values used (D-01 HALF_UP:0.01, D-03 GENERAL) are SYNTHETIC test inputs, not decisions."]
(OUT / "RESULTS-X2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
