# PAC selection checklist (gap C1)

**For:** the release owner choosing Zoiko's PAC (Proveedor Autorizado de Certificación) and the engineer who will write its adapter.
**Status:** no PAC is chosen. Production has no adapter (`mexico_pac._ADAPTERS` is empty), so every PAC call is refused with `MX_PAC_NOT_CONFIGURED`.
**Sources:** spec ZP-MX-ENG-001 v1.0 §6 and §20; MX-015 to MX-018, MX-035, MX-043 and MX-062; `MEXICO_PHASE_7_PLAN.md` §4 and §5; `MEXICO_UNKNOWN_STATE_RUNBOOK.md`.

Zoiko does not choose the provider. This page lists what any candidate must meet. Once one is chosen, its adapter is one small class behind the existing `PacAdapter` interface (four calls). It must pass the conformance kit in `backend/tests/_mx_pac_conformance.py` in the provider's sandbox before it is registered.

---

## 1. Requirements a provider must meet

| # | Requirement | Why (source) | How Zoiko checks it |
|---|---|---|---|
| R1 | Is on the SAT list of authorised PACs, with a current authorisation | §6, MX-015 | Release owner: the SAT list, saved as a source |
| R2 | Stamps CFDI 4.0 with the Complemento de Nómina 1.2 | §6, MX-015 | Kit `stamp_accepted` using a real payload from the pinned SAT set |
| R3 | **Idempotent stamping:** the same idempotency key (or the same signed document) never produces a second CFDI. A retry returns the original UUID | MX-062, plan §4.2 | Kit `duplicate_idempotency`, `timeout_unknown_status` |
| R4 | **Status query by our reference:** a call answers FOUND (with the UUID) or NOT_FOUND for a document sent before a timeout | MX-043, MX-062 | Kit `timeout_unknown_status`, `timeout_before_stamp` |
| R5 | Rejections are **definitive and coded**: a schema or business error returns a stable code, never a silent drop | §6, plan §4.1 | Kit `stamp_rejected` |
| R6 | An expired, revoked or wrong CSD is a coded rejection, not a timeout | MX-035, gap C3 | Kit `csd_expired` |
| R7 | **Cancellation** with a reason code, with and without a replacement UUID (the c_MotivoCancelacion catalogue) | MX-018, F6 | Kit `cancel_without_replacement`, `cancel_with_replacement` |
| R8 | **Cancellation status polling** until SAT settles (CANCELLED, still pending, or still active when the receiver refuses) | MX-018 | Kit `cancel_status_polling` |
| R9 | Returns the **stamped XML** with the TimbreFiscalDigital (UUID, FechaTimbrado, SelloSAT, NoCertificadoSAT) | RMF 2.7.1.7 (printed receipt, W4-3b) | Kit `stamp_accepted` |
| R10 | Documented **"definitively not found" timing**: how long after a send, and how many NOT_FOUND answers, before a document is certainly not stamped | Plan §4.2 (no default in Zoiko) | Provider's written answer, entered as `ProviderRetryConfig` (`min_wait_seconds`, `min_not_found_queries` ≥ 2) |
| R11 | **The CSD stays in Zoiko's custody:** Zoiko signs (sello) and the PAC only stamps. A provider that requires the employer's private key or password is unacceptable | MX-035, gap C3 | Contract review |
| R12 | Transport: TLS, documented time-outs and rate limits, and a status endpoint | §20, MX-062 | Engineer, during adapter work |
| R13 | Error messages without the XML or identifiers echoed back (or Zoiko redacts them before storing) | MX-061 | Kit `no_raw_xml_in_messages` |
| R14 | A sandbox environment with the facilities in §3 | Plan §1 X3 | Before any adapter code |
| R15 | Contract: SLA, data location and retention of the XML the PAC keeps, incident notice, price per stamp and per cancellation | §20 | Release owner and legal |

## 2. Questions to send each candidate

1. Are you on the SAT's current list of authorised PACs? Please send the authorisation reference.
2. Which API do you offer for CFDI 4.0 with Nómina 1.2 (REST or SOAP)? Please send the full specification and its version.
3. **Idempotency:** if we send the same signed CFDI twice (for example after a network timeout), do you return the original UUID or stamp again? Do you accept a client reference or idempotency key? For how long do you remember it?
4. **Status by reference:** can we ask "did you stamp the document we sent with reference X?" before we have a UUID? What does the answer look like when you never received it?
5. After a send, how long, and how many "not found" answers, before a document is certainly not stamped? (We need a number, not "usually".)
6. Do you need the employer's CSD private key or password at any point? (Our answer must be no: we sign, you stamp.)
7. Cancellation: which reason codes do you support, how do you take the replacement UUID, and how do we poll a pending cancellation?
8. What codes do you return for an expired, revoked or mismatched CSD, an RFC not in the LCO, a schema error, and a duplicate?
9. Do your error messages ever echo the XML or the RFC / CURP back?
10. How long do you keep the stamped XML, and where (country and provider)? Can we get it again later, and how?
11. Rate limits, time-outs, maintenance windows and the status page?
12. Price per stamp and per cancellation, minimums, and the contract term?
13. Sandbox: see §3. Can you confirm each item?

## 3. What the sandbox must allow (each kit check)

| Kit check | The sandbox must let us |
|---|---|
| `stamp_accepted` | stamp a test CFDI signed with a **test CSD** and receive the stamped XML with a TFD |
| `stamp_rejected` | send a deliberately invalid CFDI and receive a coded rejection |
| `timeout_unknown_status` | lose an answer after the stamp (for example a client time-out shorter than the sandbox's response), then find the document by status query, and get the **same UUID** on resend |
| `timeout_before_stamp` | fail before the send reaches you, then receive NOT_FOUND for that reference |
| `duplicate_idempotency` | send the same document twice and receive one UUID |
| `cancel_without_replacement`, `cancel_with_replacement` | cancel test CFDI with each reason code |
| `cancel_status_polling` | poll a cancellation until it settles, within a stated number of polls |
| `csd_expired` | use a test CSD that is expired (or that the sandbox treats as expired) |
| `no_raw_xml_in_messages` | see the real error texts |

A check the sandbox cannot provoke is reported **NOT_RUN** by the kit, and the adapter is not accepted until it is run.

## 4. After the choice (Engineering)

1. Record the decision: provider, contract reference and sandbox account owner. Credentials go to the security lead (gap C3), never into the repository.
2. Write the adapter: one class implementing `PacAdapter` (`stamp`, `query_status`, `cancel`, `query_cancel_status`) with provider-neutral results. Transport errors are left to the lifecycle, which maps them to UNKNOWN.
3. Write its kit driver: how to provoke each scenario in that sandbox. Run `kit.run(driver)`: **every check PASS, none NOT_RUN**. Keep the report as G1/G6 evidence.
4. Enter the provider's R10 numbers in `_PROVIDER_RETRY_CONFIG` (code review plus the release owner).
5. Register the adapter for the SANDBOX environment only. PRODUCTION needs `stamp_test_status = PASSED` (plan §2) and the gates.
