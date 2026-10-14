# Sign-off packet 09: Super Admins (upload A, review B)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

Two people with **production** Super Admin accounts:
* **A** uploads.
* **B**, a different person, reviews. The product refuses B = A.

1. **After the deploy** (`../ops/HK_DEPLOY_RUNBOOK.md`), A uploads the 32 draft items in `../UPLOAD_KIT/manifest.csv`, following `../UPLOAD_KIT/UPLOAD_GUIDE.md`. This only makes each gate SUBMITTED.
2. **B accepts an item only when** its signed version exists: the corresponding packet in this folder is signed and that signed file has been uploaded and set to supersede the draft. Otherwise B rejects it with a reason, or leaves it.
3. After the uploads, run the read-only check, `python -m scripts.hk_verify_evidence_upload ../docs/hk-evidence/UPLOAD_KIT/manifest.csv --out hk_upload_check.json`. Upload its output under `HK-PRODUCTION-VERIFICATION`.

## What to check

* Before uploading, each file's SHA-256 matches `manifest.csv`.
* Never click Accept on a draft whose sign-off block is blank.
* The upload kit was rehearsed on a scratch database (32 MISSING → 32 MATCH; a deliberately tampered digest was caught). After that rehearsal, the G5 assessment was updated for F-10 and F-11, so its manifest digest was refreshed. The mechanism is unchanged.

## Time estimate

About 1–2 hours for A (32 uploads), and about 1 hour per review session for B, spread over time as signed versions arrive.

## Evidence

* `../UPLOAD_KIT/UPLOAD_GUIDE.md` — SHA-256 `4612f92fb317b657e980c015283f95bfe565af2058a5b6ccd37aeac03bd75947`
* `../UPLOAD_KIT/manifest.csv` — SHA-256 `97a7be989c3bcb72e716aa2918c647c112eff8170b6c6c1bbfd810c2492c729b`

## Sign-off (uploads done; reviews are recorded in the product)

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
