# CFDI XML storage contract (gap C15)

**For:** the release owner and engineer who will configure durable storage for CFDI XML, and legal for the retention period.
**Status:**
- **Today:** CFDI generation refuses with `MX_CFDI_STORAGE_NOT_DURABLE` unless `app/core/object_storage` is backed by GCS (`mexico_cfdi_service.py`).
- **The new contract:** it has no production store (`mexico_xml_store._STORE` is None).

**Sources:** spec §20 (MX-060 to MX-062), and `MEXICO_PHASE_10C_IMPLEMENTATION_REPORT.md` (the Mexico retention categories, still BLOCKED_UNDECIDED, and legal holds). No retention period is stated here: it is legal's decision, from a source legal names.

## What exists (final mile X5)

| Piece | Where | State |
|---|---|---|
| `StampedXmlStore` interface and shared rules | `backend/app/modules/payroll/mexico_xml_store.py` | Built |
| Local-filesystem store | `backend/tests/_mx_local_xml_store.py` | **Tests only** |
| Contract tests | `backend/tests/test_mexico_xml_store.py` | 10 pass against the local store |
| GCS store | — | **Waits for C15** |
| Retention period | — | **Waits for legal** |

## The contract

```python
put(key, data, retention_until) -> StoredXml(ref, key, sha256, size, retention_until)
get(ref) -> bytes
head(ref) -> StoredXml | None
delete(ref, on) -> None
```

1. **Key:** `org/<organisation id>/run/<run id>/<name>.xml`. No path traversal, and no RFC, CURP or NSS in the key. Otherwise the call is refused with `MX_CFDI_XML_KEY_INVALID`.
2. **Write-once:**
   - the same bytes again under the same key are an idempotent no-op that returns the original record;
   - different bytes are refused with `MX_CFDI_XML_WRITE_ONCE`. A stamped CFDI is never overwritten; a correction is a new document.

   In GCS, enforce this with an `ifGenerationMatch=0` precondition and an object retention lock, not by code alone.
3. **Hash on write and on read:** the SHA-256 and size are recorded at write. `get` returns the bytes only if both still match; otherwise it refuses with `MX_CFDI_XML_INTEGRITY` and raises an incident.
4. **Retention:**
   - `retention_until` is stored with each object;
   - `None` means **undecided**, and `delete` refuses (`MX_CFDI_XML_RETENTION_UNDECIDED`);
   - before the date, `delete` refuses (`MX_CFDI_XML_RETAINED`);
   - a legal hold (Phase 10c) overrides the date.
5. **Privacy:**
   - XML holds RFC and CURP, so it is never logged and never put in an error message;
   - access is limited to the CFDI service account;
   - storage is encrypted at rest, with customer-managed keys if the security lead requires it.
6. **Location:** the region the hosting decision fixes (gap register Q9 or hosting). The same region holds backups.
7. **Every environment** (staging and production) has its own bucket. The `/tmp` fallback is refused in production (D4).

## Decisions needed

| Decision | Owner |
|---|---|
| Bucket per environment, region, encryption keys, IAM | Release owner + Eng (C15) |
| **Retention period** for CFDI XML and its evidence, from which event (the stamp date, the fiscal year end) | Legal |
| Legal-hold process and who may release a hold | Legal + Release owner |

## After the decisions (Engineering)

1. Implement `GcsXmlStore(StampedXmlStore)`, reusing the shared `write_once`, `verified` and `deletable` rules. It must pass `test_mexico_xml_store.py` against a non-production bucket.
2. Move the two CFDI write points to it: generation (`mexico_cfdi_service`, the signed XML) and `_store_stamped_xml` (the stamped XML). Keep the existing `xml_storage_ref` column.
3. Set `retention_until` from the legal decision.
