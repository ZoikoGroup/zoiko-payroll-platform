"""Harness-only SYNTHETIC patches for the Mexico Phase 7 browser check,
applied in the setup process AND the server process. Never imported by the
application; never production.

flag_on=False: only the onboarding flag (off) — the real seams stay in place
(SatBuilder / GcpSmSigner refuse, no PAC adapter), as in production.
flag_on=True: the Phase 6 synthetic content mappings, plus the test-only
synthetic builder / signer and a mock PAC whose answers are scripted through
a JSON control file (CONTROL) so the acceptance script can force a timeout.
Every PAC call is appended to CALLS (call, key, payload hash) as evidence."""
import json
import os
from pathlib import Path

SCRATCH = Path(r"C:\Users\Nikhi\AppData\Local\Temp\claude\d--zoiko-payroll-platform"
               r"\4310d3e7-cd06-425b-899e-67cfb66b19b8\scratchpad\p7browser")
CONTROL, CALLS = SCRATCH / "pac_control.json", SCRATCH / "pac_calls.jsonl"


def apply(flag_on: bool):
    from app.config import settings

    settings.MX_TENANT_ONBOARDING_ENABLED = flag_on
    if not flag_on:
        return
    from app.modules.payroll.engine.countries import mexico_content as c

    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
    os.environ["UPLOAD_BASE_DIR"] = str(SCRATCH / "uploads")
    os.environ["PAYROLL_STORAGE_BACKEND"] = "local"

    from app.modules.payroll import mexico_cfdi_builder as B
    from app.modules.payroll import mexico_pac as P
    from tests._mx_cfdi_helpers import SyntheticBuilder, SyntheticSigner
    from tests._mx_mock_pac import MockPac

    class FileScriptedPac(MockPac):
        def _next(self, kind, default):
            script = json.loads(CONTROL.read_text()) if CONTROL.is_file() else {}
            seq = script.get(kind) or []
            how = seq.pop(0) if seq else default
            CONTROL.write_text(json.dumps(script))
            return how

        def _logged(self, fn, *a, **k):
            try:
                return fn(*a, **k)
            finally:
                with CALLS.open("a") as f:
                    f.write(json.dumps(self.calls[-1]) + "\n")

        def stamp(self, *a, **k):
            return self._logged(super().stamp, *a, **k)

        def query_status(self, *a, **k):
            return self._logged(super().query_status, *a, **k)

        def cancel(self, *a, **k):
            return self._logged(super().cancel, *a, **k)

    B._BUILDER, B._SIGNER = SyntheticBuilder(), SyntheticSigner()
    pac = FileScriptedPac()
    P._ADAPTERS[("MOCK", "SANDBOX")] = lambda: pac
