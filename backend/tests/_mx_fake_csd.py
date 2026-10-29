"""TEST-ONLY CSD custody provider (Mexico final mile X5, C3). Never imported by
app/ and never registered in mexico_csd_custody._PROVIDERS outside a test's
monkeypatch. It holds a throwaway key generated in memory (SYNTHETIC) and,
like any real provider, exposes public facts and signatures only."""

from datetime import timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.modules.payroll import mexico_csd_custody as C
from tests._mx_employer_helpers import self_signed_cert


class FakeCustody(C.CsdCustodyProvider):
    scheme = "fake-sm"

    def __init__(self, days=365, not_before=None, status=C.ACTIVE):
        der, cert, key = self_signed_cert(days=days, not_before=not_before)
        self.__key = key                                    # name-mangled: never part of the interface
        self.der, self.cert, self.status = der, cert, status
        self.signed = []

    def fingerprint(self):
        return self.cert.fingerprint(hashes.SHA256()).hex()

    def public_key(self):
        return self.cert.public_key()

    def describe(self, secret_ref):
        return C.CsdFacts(fingerprint_sha256=self.fingerprint(), certificate_serial=format(self.cert.serial_number, "X"),
                          valid_from=self.cert.not_valid_before_utc.astimezone(timezone.utc),
                          valid_to=self.cert.not_valid_after_utc.astimezone(timezone.utc), status=self.status)

    def sign(self, secret_ref, data):
        self.signed.append(data)
        return C.CsdSignature(signature=self.__key.sign(data, ec.ECDSA(hashes.SHA256())),
                              certificate_der=self.cert.public_bytes(serialization.Encoding.DER),
                              certificate_serial=format(self.cert.serial_number, "X"))


def synthetic_sealer(payload, sign):
    """SYNTHETIC sealer: signs the payload bytes and appends the signature as a
    labelled comment — NOT the SAT cadena original / sello."""
    import base64

    sig = sign(payload)
    return payload + b"<!-- SYNTHETIC-SELLO " + base64.b64encode(sig.signature) + b" -->"
