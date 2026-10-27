"""Mexico final mile X4 — parallel payroll in the real UI (Mexico Compliance
Centre): a legacy CSV imported against a committed run and mapped column by
column, the differences listed with the D-25 verdict, an identifier file
refused, explain then accept by a second admin, and nothing Mexican for an NL
admin. Usage: python acceptance_x4.py on|off (the server's onboarding flag)."""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
SCRATCH = Path(r"C:\Users\Nikhi\AppData\Local\Temp\claude\d--zoiko-payroll-platform"
               r"\98808133-a255-40fa-94ee-54c6330641ec\scratchpad")
APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
BASE = "/api/payroll/mexico"
PASSWORD = "BrowserCheck!2026"
A0, A1, NL = "admin0@mxfm4.example.com", "admin1@mxfm4.example.com", "admin@nlfm4.example.com"
MODE = sys.argv[1] if len(sys.argv) > 1 else "on"
IDS = json.loads((SCRATCH / "x4_ids.json").read_text(encoding="utf-8"))
results, errors, responses, _tokens = [], [], [], {}


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


def open_parallel(page):
    page.goto(APP + "/payroll/compliances", wait_until="load")
    settle(page)
    page.get_by_role("button", name="Mexico Compliance Centre").first.click()
    settle(page, 2000)
    panel = tid(page, "mx-parallel")
    panel.scroll_into_view_if_needed()
    return panel


def upload(page, panel, csv_path, mapping):
    panel.get_by_label("Committed run id").fill(str(IDS["run"]))
    panel.get_by_label("Legacy system").fill("SYNTHETIC legacy payroll")
    panel.get_by_label("Legacy results CSV").set_input_files(str(csv_path))
    page.wait_for_timeout(500)
    for key, column in mapping.items():
        panel.get_by_label(f"Column for {key}", exact=True).select_option(column)
    panel.get_by_role("button", name="Import and compare").click()
    settle(page)


def no_identifier(text):
    return not any(i in text for i in IDS["identifiers"])


MAPPING = {"employee_code": "Code", "net": "Net", "isr_withheld": "ISR", "imss_employee": "IMSS EE"}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    if MODE == "off":
        for method, path in (("GET", "/parallel/imports"), ("POST", "/parallel/imports"),
                             ("GET", "/parallel/imports/1"), ("POST", "/parallel/imports/1/withdraw"),
                             ("POST", "/parallel/differences/1/explain"), ("POST", "/parallel/differences/1/accept")):
            st, txt = api(A0, method, BASE + path, {} if method == "POST" else None)
            check(f"off-1 {method} {path} refused while Mexico is dormant", st in (403, 404), f"{st} {txt[:150]}")
        a = new_page(browser, A0)
        panel = open_parallel(a)
        check("off-2 the parallel panel shows the dormancy refusal", "not open for onboarding" in panel.inner_text(),
              panel.inner_text()[:300])
        shot(a, "x4_01_parallel_dormant", panel)
    else:
        a = new_page(browser, A0)
        panel = open_parallel(a)
        check("x4-1 the parallel panel is in the Mexico Compliance Centre", panel.count() == 1
              and "No parallel cycle yet." in panel.inner_text(), panel.inner_text()[:300])
        bad = SCRATCH / "x4_identifier.csv"
        bad.write_text(f"Code,Net,Note\n{IDS['employee_code']},1.00,{IDS['identifiers'][0]}\n", encoding="utf-8")
        upload(a, panel, bad, {"employee_code": "Code", "net": "Net"})
        text = panel.inner_text()
        check("x4-2 a file carrying an identifier value is refused, the value never echoed",
              "shaped like an RFC" in text and no_identifier(text), text[:300])
        shot(a, "x4_02_identifier_refused", panel)
        upload(a, panel, HERE / "x4_legacy.csv", MAPPING)
        detail = tid(a, "mx-parallel-detail")
        text = detail.inner_text()
        check("x4-3 import compares by employee code: 2 match, 1 unexplained (net 12.50), unmatched listed",
              "match 2" in text and "unexplained 1" in text and "12.50" in text and "LEGACY-ONLY-1" in text, text[:500])
        check("x4-4 with D-25 unset the cycle is never declared clean",
              "NOT DECIDABLE" in text and "D-25" in tid(a, "mx-parallel-note").inner_text(), text[:300])
        shot(a, "x4_03_parallel_differences", panel)
        reason = detail.locator('input[aria-label^="Reason "]').first
        reason.fill("SYNTHETIC: the legacy system rounds each line")
        detail.get_by_role("button", name="Explain").click()
        settle(a)
        detail.get_by_role("button", name="Accept (another person)").click()
        settle(a)
        text = panel.inner_text()
        check("x4-5 the explainer cannot accept their own explanation (four-eyes)",
              "four-eyes" in text and "explained 1" in tid(a, "mx-parallel-detail").inner_text(), text[:400])
        shot(a, "x4_04_four_eyes_refused", panel)
        b = new_page(browser, A1)
        panel_b = open_parallel(b)
        panel_b.get_by_role("button", name="Open").first.click()
        settle(b)
        tid(b, "mx-parallel-detail").get_by_role("button", name="Accept (another person)").click()
        settle(b)
        text = tid(b, "mx-parallel-detail").inner_text()
        check("x4-6 a second admin accepts; the verdict stays undecidable without D-25",
              "accepted 1" in text and "unexplained 0" in text and "NOT DECIDABLE" in text, text[:400])
        shot(b, "x4_05_accepted_by_second_admin", panel_b)
        st, body = api(A0, "GET", f"{BASE}/parallel/imports?run_id={IDS['run']}")
        check("x4-7 no full RFC / CURP / NSS / CLABE in the panel or the API (MX-061)",
              st == 200 and no_identifier(body) and no_identifier(panel_b.inner_text()), f"{st}")
        n = new_page(browser, NL)
        n.goto(APP + "/payroll/compliances", wait_until="load")
        settle(n)
        check("x4-8 NL compliance page has no Mexico panels",
              n.get_by_role("button", name="Mexico Compliance Centre").count() == 0, "")
        st, body = api(NL, "GET", f"{BASE}/parallel/imports")
        check("x4-9 the NL admin is refused the Mexico parallel API", st == 403, f"{st} {body[:150]}")
    browser.close()

unexpected = [r for r in responses if r[3] >= 500]
check("z1 no 5xx responses and no page errors", not unexpected and not [e for e in errors if "pageerror" in e],
      f"{unexpected} {errors[:5]}")
lines = [f"# Mexico final mile X4 -- parallel payroll browser check ({MODE})", "",
         f"{sum(ok for _, ok, _ in results)}/{len(results)} PASS", "", "| Check | Result |", "|---|---|"]
lines += [f"| {nm} | {'PASS' if ok else 'FAIL -- ' + str(d)[:200].replace('|', '/').replace(chr(10), ' ')} |"
          for nm, ok, d in results]
lines += ["", "4xx responses seen in the browser (expected: the refusals checked above): "
          + (", ".join(sorted({f'{m} {u} {c}' for _, m, u, c in responses})) or "none"),
          "Console errors: " + ("; ".join(e.split(": ", 1)[-1][:160] for e in errors) if errors else "none")]
(OUT / f"RESULTS-X4-{MODE}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
