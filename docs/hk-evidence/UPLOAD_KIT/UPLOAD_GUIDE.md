# Hong Kong evidence: production upload guide (for a Super Admin)

**Who:** two people with Super Admin accounts in **production**. **A** uploads and **B** reviews; the product refuses B = A. **What:** the 32 draft documents in `manifest.csv`. **Claude did not upload anything to production.**

Uploading makes each gate **SUBMITTED**, not PASS. A draft is only *accepted* after it has been completed and signed by the named people, and B has read it. Do not click **Accept** on a draft whose sign-off block is still blank.

## Before you start

1. Check out the commit that contains this kit, and confirm every file's SHA-256 against `manifest.csv`:
   * PowerShell: `Get-FileHash -Algorithm SHA256 <file>`
   * bash: `sha256sum <file>`

   If any digest differs, stop: the file is not the one in the manifest.
2. The production deploy that carries `HKEvidencePanel` must be live. Super Admin → Jurisdictions → Hong Kong → **Statutory Summary & Gates** shows an **Evidence (n)** link on each gate row.

## Upload each item (A)

For each manifest row, in order:

1. Open the place for its **tag**:
   * `HK-GATE-G1` … `G7`: **Statutory Summary & Gates**, then the gate row's **Evidence** link.
   * `HK-DECISION-D-n`: **Activation & Governance** → Owner decisions, then the decision row's **Evidence** link.
2. In the panel:
   * **Document title:** the manifest `title`, exactly. The verification script matches on it.
   * **Issued / signed by:** the manifest `issuer` (`Zoiko internal – draft`).
   * **File:** the manifest `file`.

   Then click **Submit evidence (tag)**.
3. The row shows **Awaiting independent review** with `SHA-256 xxxxxxxxxxxx…`. Its first 12 characters must equal the manifest `sha256`.

When a signed version replaces a draft later:
* Submit the signed file the same way, with a title that says "SIGNED".
* On the draft, choose **Supersede with…** → the signed item → **Supersede**.

The draft stays on record; only the signed item is current.

## Review (B, a different Super Admin)

* **Accept** only when the document is complete and signed by the people its sign-off block names, and you have read it.
* Otherwise **Reject**, with notes saying what is missing. The rejection is kept. The correction is a new upload and then a supersede.

## Verify (read-only, any operator with production DB access)

```bash
cd backend
python -m scripts.hk_verify_evidence_upload ../docs/hk-evidence/UPLOAD_KIT/manifest.csv --out hk_upload_check.json
```

* The script uses SELECT statements only, in a read-only session.
* It prints counts of MATCH / DIGEST_MISMATCH / NOT_UPLOADED / MISSING and lists every row that is not a MATCH. It exits 0 only when all 32 match.
* Its `reviewed` / `independentReview` fields show which items have been accepted.
* Keep `hk_upload_check.json`, and upload it under `HK-PRODUCTION-VERIFICATION`.

## Related production actions (not uploads)

| Action | Who | Instruction |
|---|---|---|
| Re-run the canonical HK seed on the **Draft** packs so the new governed row `mpf_contribution_day_deferral` exists in production (the seed refuses non-Draft packs) | Ops, after the deploy that carries migration `8b14824fb575` | `python -m scripts.seed_hong_kong_canonical_pack` per the existing seed procedure |
| Provision `HK_IDENTITY_TOKEN_KEY` | Ops / Security | `../ops/HK_IDENTITY_TOKEN_KEY_provisioning.md` |
| Read-only production verification | Ops | `../ops/HK_production_readonly_verification_instructions.md` |
| Grant `HK_MPF_ACCOUNT_REVEAL` to the eMPF filer(s) of each HK tenant | That tenant's org admin | Compliance → Hong Kong → Privacy & Legal Holds → MPF account access |

## Rehearsal (scratch environment, 2026-10-13, repeated after the third pass)

The kit was rehearsed on a local scratch database seeded with the canonical HK data, never production:

* Before upload, the verification script reported **32 MISSING** (exit 1).
* All 32 items were registered through the same API the panel uses (`rehearsal_scratch_receipt.json`; every server SHA-256 equals the manifest).
* After upload it reported **32 MATCH, 0 reviewed** (exit 0) (`rehearsal_scratch_verify_report.json`).
* With one manifest digest deliberately altered, it reported **1 DIGEST_MISMATCH** (exit 1).

**Since the rehearsal (2026-10-14).** The G5 assessment gained findings F-10 and F-11, so its digest and the manifest changed. The manifest SHA-256 was `72b68649…` at rehearsal time and is now `5ad4685a1c7c5dd797ce539b7b21b23d57c5314285098c8a04a4e54086d21208`. The rehearsal receipts above record the earlier run and are kept unchanged. Repeat the rehearsal on a scratch database before the production upload (`../ops/HK_DEPLOY_RUNBOOK.md` §7).
