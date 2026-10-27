# CSD custody contract (gap C3)

**For:** the security lead deciding where Mexican CSD private keys live, and the engineer who will implement it.
**Status:** undecided. Production has no custody provider (`mexico_csd_custody._PROVIDERS` is empty), and the installed signer `GcpSmSigner` refuses with `MX_CSD_SIGNING_BLOCKED`.
**Sources:** MX-035 (secrets are references only), MX-061 (no identifiers in logs), `MEXICO_PHASE_7_PLAN.md` §5.2, Phase 7 decision D12 (`gcp-sm://` references).

## What exists (final mile X5)

| Piece | Where | State |
|---|---|---|
| `CsdCustodyProvider` interface | `backend/app/modules/payroll/mexico_csd_custody.py` | Built |
| `CustodySigner`: checks custody, then signs through the provider | same file | Built, **not installed** |
| Expiry alerts (Super Admin → Mexico → Employer, all organisations) | `csd_expiry_alerts`, `GET /super-admin/compliance/mexico/csd-expiry` | Built, live in the UI |
| Test provider (throwaway key in memory) | `backend/tests/_mx_fake_csd.py` | Tests only |
| Secret Manager provider | — | **Waits for the security lead** |
| Sealer (cadena original + sello) | — | Engineering, after C3 |

## The contract a provider must meet

A provider is registered for the scheme of the credential's `secret_ref` (for example `gcp-sm`). It implements exactly two calls:

```python
describe(secret_ref) -> CsdFacts(fingerprint_sha256, certificate_serial, valid_from, valid_to, status)
sign(secret_ref, data: bytes) -> CsdSignature(signature, certificate_der, certificate_serial)
```

1. **The private key and its password never leave custody.** No call returns key material, and nothing writes it to the database, a log, a temporary file or an error message. The interface has no method that could. Tests check this.
2. **`describe` returns public facts only:**
   - the SHA-256 fingerprint of the certificate in custody;
   - its serial number;
   - its validity window;
   - a status: ACTIVE, REVOKED or NOT_FOUND.
3. **`sign` signs exactly the bytes it is given** with the CSD's key. It returns the signature and the **public** certificate (for the CFDI's `Certificado` and `NoCertificado`).
4. **Errors** (permission, not found, network) raise. The signer never retries a signature on its own.
5. **Access is least-privilege:** only the signing service account may call `sign`. Each signature is logged by the provider (who, when and which secret), without the data.
6. **Rotation:** a new CSD is a new secret version or reference, recorded through the employer's credential rotation (ACTIVE → ROTATED). An old reference is never edited in place.

## What the signer checks before every signature (`custody_refusal`)

| Check | Refusal |
|---|---|
| The employer has an ACTIVE CSD credential reference (kind CSD) | `MX_CSD_NOT_ACTIVE` |
| The provider is configured for the reference's scheme | `MX_CSD_PROVIDER_NOT_CONFIGURED` |
| The provider reports the key ACTIVE | `MX_CSD_NOT_ACTIVE` |
| The fingerprint in custody equals the one recorded when the public `.cer` was uploaded | `MX_CSD_FINGERPRINT_MISMATCH` |
| The certificate is in force at signing time | `MX_CSD_EXPIRED` |
| A sealer exists | `MX_CSD_SEALER_NOT_BUILT` |

## Decisions for the security lead

1. Which custody? The recommendation of record is GCP Secret Manager (Phase 7 D12); KMS-backed signing or an HSM are alternatives. **Zoiko does not choose.**
2. Project, region, IAM roles, and who may add or rotate an employer's CSD.
3. Whether the employer uploads the `.key` and password into custody through a Zoiko screen (never stored by Zoiko), or puts them there out of band.
4. Audit retention for provider access logs.

## After the decision (Engineering)

1. Implement the provider class for the chosen scheme. It passes `test_mexico_csd_custody.py` with the real provider substituted for the fake, in a non-production project with a **test CSD**.
2. Build the sealer: the cadena original from the pinned SAT XSLT (S30), then the `Sello`, `NoCertificado` and `Certificado` attributes.
3. Install `CustodySigner(sealer=…)` as the active signer, with gates G1 and G7 and the ZP-PRIV review.
