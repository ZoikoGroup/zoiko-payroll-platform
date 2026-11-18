"""Navigation helpers for Super Admin → Report templates → Mexico.

Since a72d28c1 the Mexico page uses the shared list + detail layout like every
other country: nothing is stacked under the page any more. The Mexico panels
are reached by selecting a template and opening a tab, or the page "Library"
toggle:
  - "Versions & gates" tab: the selected template's versions, "New version",
    Compare (that template's versions only)  [mx-template-versions, mx-template-compare]
  - "Preview" tab: the sandbox preview, pre-selected  [mx-template-preview]
  - Overview: the template status block  [mx-template-status]
  - "Library" toolbar toggle: every template  [mx-template-library]
"""
import re

# Super Admin refresh tokens are bound to the client that logged in (auth
# service: a different user agent on refresh = NEW_DEVICE, sign in again). The
# harness logs in over HTTP and hands the tokens to the browser, so both must
# present the same user agent, or the first activity refresh signs the browser out.
HARNESS_UA = "Mozilla/5.0 (ZoikoMexicoHarness) Chrome"


def tid(page, name):
    return page.locator(f'[data-testid="{name}"]')


def open_template(page, template_key, version=None, settle_ms=1500):
    """Filter the list by template_key and select it. The list shows each
    template's latest version; for another version, open it from the
    "Versions & gates" tab (the built-in "Versions" tab is hidden on Mexico)."""
    page.get_by_label("Filter by name or report type").fill(template_key)
    page.wait_for_timeout(400)
    page.locator("div.lg\\:grid-cols-\\[280px_1fr\\] > div").first.get_by_role("button").first.click()
    page.wait_for_timeout(settle_ms)
    if version and current_version(page) != version:
        open_tab(page, "Versions & gates")
        tid(page, f"mx-template-versions-{template_key}").get_by_role("button", name=f"Open v{version}", exact=True).click()
        page.wait_for_timeout(settle_ms)


def current_version(page):
    """The open template's version, from the detail header ("v1.0 · MX_REGISTER · ...")."""
    header = page.locator("h2").first.locator("xpath=../..").inner_text()
    m = re.search(r"\bv(\S+) · ", header)
    return m.group(1) if m else None


def open_tab(page, label, settle_ms=1200):
    page.get_by_role("button", name=label, exact=True).first.click()
    page.wait_for_timeout(settle_ms)


def open_library(page, settle_ms=1500):
    toggle = tid(page, "page-tool-mx-library")
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    page.wait_for_timeout(settle_ms)
    return tid(page, "mx-template-library")
