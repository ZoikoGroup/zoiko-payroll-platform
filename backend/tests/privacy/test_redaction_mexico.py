"""Mexico Phase 10c (MX-061): Mexican identifiers and CFDI documents never
reach a log line or an error report. SYNTHETIC identifiers only (the RFC /
CURP shapes of the SAT / RENAPO examples, not real people).

Imports are lazy (collection-order hazard: this directory sorts before
tests/test_assist.py)."""

import logging

import pytest

RFC_PF = "GODE561231GR8"            # SYNTHETIC persona física shape
RFC_PM = "AAA010101AAA"             # SYNTHETIC persona moral shape
CURP = "GODE561231HDFRRN09"         # SYNTHETIC
NSS = "12345678901"                 # SYNTHETIC, 11 digits
CLABE = "002180700012345678"        # SYNTHETIC, 18 digits
CFDI = ('<?xml version="1.0" encoding="UTF-8"?><cfdi:Comprobante Version="4.0" Total="15419.25">'
        f'<cfdi:Emisor Rfc="{RFC_PM}"/><cfdi:Receptor Rfc="{RFC_PF}" Nombre="PERSONA SINTETICA"/>'
        f'<cfdi:Complemento><nomina12:Nomina><nomina12:Receptor Curp="{CURP}" NumSeguridadSocial="{NSS}"/>'
        '</nomina12:Nomina></cfdi:Complemento></cfdi:Comprobante>')
SECRETS = (RFC_PF, RFC_PM, CURP, NSS, CLABE, "PERSONA SINTETICA", "15419.25")


def _R():
    from app.core import redaction

    return redaction


@pytest.mark.parametrize("text,mask", [
    (f"receptor {RFC_PF} rejected", "[RFC]"), (f"emisor {RFC_PM} ok", "[RFC]"),
    (f"lower case {RFC_PF.lower()}", "[RFC]"), (f"curp {CURP} invalid", "[CURP]"),
    (f"nss {NSS}", "[NUMBER]"), (f"clabe {CLABE}", "[NUMBER]"),
    (f"pac said: {CFDI} -- end", "[CFDI XML]"),
    (f"truncated {CFDI[:120]}", "[CFDI XML]"),
    (f"fragment <nomina12:Nomina><nomina12:Receptor Curp=\"{CURP}\"/></nomina12:Nomina>", "[CFDI XML]"),
])
def test_free_text_masks_every_mexican_identifier_and_cfdi(text, mask):
    out = _R().scrub_text(text)
    assert mask in out and not [s for s in SECRETS if s in out], out


def test_a_cfdi_is_masked_whole_and_the_text_around_it_survives():
    out = _R().scrub_text(f"stamp failed for folio A-17: {CFDI} -- code 301")
    assert out == "stamp failed for folio A-17: [CFDI XML] -- code 301"


@pytest.mark.parametrize("text", [
    # (an IMSS registro patronal such as Y1234567101 is partly masked by the existing HKID shape,
    # which has no closing word boundary - over-masking, harmless; noted for the ZP-PRIV owner)
    "MX_JOURNAL_UNBALANCED on run 12",
    "pay date 2026-06-30 period 2026-06", "uuid 6F9619FF-8B86-D011-B42D-00C04FC964FF",
    "ISR_PAYABLE SYN-105", "batch ZP-12-34", "PAYROLL123 and ABC123",
])
def test_ordinary_text_is_left_alone(text):
    assert _R().scrub_text(text) == text


@pytest.mark.parametrize("key", ["rfc", "employerRfc", "receptor_rfc", "curp", "nss", "employee_nss", "nssNumber",
                                 "clabe", "bank_clabe", "csd_password", "cfdi_xml", "cfdiXml", "xml_body"])
def test_mexican_identifier_keys_are_sensitive(key):
    assert _R().is_sensitive_key(key)
    assert _R().scrub({key: "SYNTHETIC-VALUE"}) == {key: _R().REDACTED}


@pytest.mark.parametrize("key", ["business", "process", "consensus", "folio", "uuid", "status"])
def test_ordinary_keys_are_not(key):
    assert not _R().is_sensitive_key(key)


def test_the_log_filter_scrubs_messages_args_extras_and_tracebacks():
    R = _R()
    records = []

    class _Keep(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    log = logging.getLogger("zp.test.mx061")
    log.propagate = False
    handler = _Keep()
    handler.addFilter(R.RedactingLogFilter())
    log.addHandler(handler)
    try:
        log.error("stamp of %s for %s", CFDI, RFC_PF)
        log.warning(f"profile {CURP} nss {NSS}", extra={"rfc": RFC_PF, "detail": {"clabe": CLABE}})
        try:
            raise ValueError(f"duplicate key (rfc)=({RFC_PF}) curp {CURP}")
        except ValueError:
            log.exception("insert failed")
    finally:
        log.removeHandler(handler)
    joined = "\n".join(records)
    assert len(records) == 3 and "[RFC]" in joined and "[CURP]" in joined and "[CFDI XML]" in joined
    assert not [s for s in SECRETS if s in joined], joined


def test_sentry_events_are_scrubbed():
    R = _R()
    event = {"message": f"PAC timeout {CFDI}",
             "request": {"data": {"rfc": RFC_PF, "curp": CURP, "note": f"see {RFC_PF}"}},
             "exception": {"values": [{"value": f"bad CURP {CURP}"}]},
             "breadcrumbs": {"values": [{"message": f"nss {NSS}", "data": {"clabe": CLABE}}]}}
    out = R.sentry_before_send(event, None)
    text = repr(out)
    assert not [s for s in SECRETS if s in text], text
