"""Re-check of the Phase 2 browser finding: the pack-header Approve button on
the empty MX Draft pack must now be REFUSED (Mexico pack_approval_refusal),
and the pack must stay Draft. Same harness as acceptance.py."""
import json
import sqlite3
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP, API = "http://127.0.0.1:4173", "http://127.0.0.1:8000"
OUT = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\docs\mexico\phase2-evidence")
DB = Path(__file__).parent / "mx_browser.db"   # the throwaway database built by setup_db.py
results, failed = [], []


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


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(login("sa-a@mxbrowsercheck.io"))
    page = ctx.new_page()
    page.on("response", lambda r: failed.append((r.request.method, r.url.split("/api/")[-1], r.status)) if r.status >= 400 else None)
    page.goto(APP + "/super-admin/compliance/mexico", wait_until="networkidle")
    page.get_by_text("MX-PAYROLL-2026", exact=True).first.click()
    page.wait_for_timeout(800)
    page.get_by_role("button", name="Approve", exact=True).first.click()     # the pack-header Approve
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    check("pack-header Approve is refused with the Mexico reason", "move it through In Review to QA first" in body,
          body[:300])
    page.screenshot(path=str(OUT / "26_pack_approve_refused.png"), full_page=True)
    browser.close()

status = sqlite3.connect(DB).execute(
    "select status, approved_by_id from payroll_jurisdiction_packs where pack_id='MX-PAYROLL-2026'").fetchone()
check("pack stays Draft with no approver", status == ("Draft", None), str(status))
check("the only failed request is that approval refusal (400)",
      failed == [("PUT", "super-admin/compliance/policies/1/approve", 400)], str(failed))
print(f"{sum(ok for _, ok, _ in results)}/{len(results)} checks passed")
_res = OUT / "RESULTS.md"
_text = _res.read_text(encoding="utf-8").split("\n## Re-check after the Mexico approval gate")[0]
with open(_res, "w", encoding="utf-8") as fh:
    fh.write(_text.rstrip("\n") + "\n" + "\n## Re-check after the Mexico approval gate (2026-10-16)\n\n| Check | Result |\n|---|---|\n"
             + "\n".join(f"| {n} | {'PASS' if ok else 'FAIL — ' + d} |" for n, ok, d in results) + "\n")
