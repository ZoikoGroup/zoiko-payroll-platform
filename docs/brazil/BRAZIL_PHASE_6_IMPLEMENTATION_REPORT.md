# Brazil (BR) — Phase 6 Implementation Report (ZP-BR-ENG-001 v1.0)

**Status**: Delivered. Phase 6 (payroll run activation) complete. All gates green.

---

## 1. Summary

Phase 6 activates the Brazil CLT payroll engine for real runs. The previously-blocked `calc_inputs` and `before_run_transition` hooks are now fully implemented, enabling:

- **Real calc_inputs**: Resolves active statutory profile, establishment, employer, RAT/FAP, concurrent INSS, alimony, VT election, CPRB, financial sector — read-only, org-scoped, called at all three calculation sites.
- **Run approval with preflight**: Validates CPF/PIS checksums, employer ACTIVE status, FAP year current, minimum-wage floor, concurrent employment declared.
- **Approval fingerprint**: SHA-256 over frozen `br_calculation_snapshot` + engine version + content hash, stored on `PayrollRun.br_approval_fingerprint` at approval.
- **Payslip persistence**: Flat `br_*` columns + `br_calculation_snapshot` (JSON) written on every PayslipItem; `brCalculationSnapshot` included in API response.
- **Frontend workspace**: `BRRunPreflightPanel`, `BRPayslipBreakdown` (via `brPayslipLines.js`), mounted in `RunDetailPanel`.

---

## 2. Backend Changes

### 2.1 Models (`models.py`)
- **PayrollRun**: Added `br_approval_fingerprint = Column(JSON, nullable=True)` — stores `{fingerprint, approvedBy, approvedAt}` at approval.

### 2.2 Brazil Service (`brazil_service.py`)

| Hook | Implementation |
|------|----------------|
| `calc_inputs` | Resolves profile/establishment/employer/RAT-FAP/concurrent/alimony/VT/CPRB/financial-sector. Returns `brazil_inputs` dict for `PayrollContext`. Validates org consistency; raises `BRBlock(key)` on missing facts. Called at preview, `_compute_payslip_values`, `add_payslip_item`. |
| `br_run_preflight` | Returns `[{employeeId, key, reason, severity, source, action}]`. Checks: CPF/PIS validity, employer ACTIVE, FAP year current, wage floor, concurrent INSS declared. |
| `br_approval_fingerprint` | `SHA-256({run, engine, payslips[{id, employeeId, inputHash, totals}]})`. Stored on `run.br_approval_fingerprint` at approval. |
| `_br_before_run_transition` | Runs `br_run_preflight`; blocks APPROVED/AUTHORIZED/PAID if any BLOCK. Stores fingerprint. |
| `payment_treatment` | Returns `{br_payment_hold: false, br_payment_method: "PIX", br_pix_keys: []}` (Phase 11 expands). |
| `payslip_hold_view` | Reads `br_calculation_snapshot.hold` if present. |

### 2.3 Service Integration (`service.py`)

- **preview_payroll_run**: Calls `jurisdiction_hooks.call("BR", "calc_inputs", db, None, emp, None, as_of)` → passes `brazil_inputs` to `build_context_from_employee`.
- **_compute_payslip_values**: Same pattern with `run` parameter; `brazil_inputs` added to context.
- **add_payslip_item**: Same pattern with `run` parameter.
- **_compute_payslip_values return**: Adds flat `br_*` fields (`br_base_inss`, `br_inss_employee`, … `br_third_parties`) + `br_calculation_snapshot = result.br_result`.

### 2.4 Organisation Router (`brazil_org_router.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/brazil/runs/{run_id}/preflight` | GET | Returns `{status: "OK"|"BLOCKED", checks: [...]}`. |
| `/brazil/runs/{run_id}/fingerprint` | GET | Returns `{fingerprint, payslips, stored: run.br_approval_fingerprint}`. |

Both require payroll operator role; org-scoped via `require_brazil_tenant`.

---

## 3. Frontend Changes

### 3.1 Service (`payrollService.js`)
```js
const BR = "/api/payroll/brazil";
export const getBrRunPreflight = (runId) => api.get(`${BR}/runs/${runId}/preflight`);
export const getBrRunFingerprint = (runId) => api.get(`${BR}/runs/${runId}/fingerprint`);
```

### 3.2 Components

| Component | File | Purpose |
|-----------|------|---------|
| `BRRunPreflightPanel` | `BRRunPreflightPanel.jsx` | Lists BLOCK/WARN checks; shows fingerprint bound status. |
| `BRPayslipBreakdown` | `BRPayslipBreakdown.jsx` | Tabular earnings/deductions/employer/bases; trace drawer. |
| `brPayslipLines.js` | `brPayslipLines.js` | Label maps, formatters, extractors for earnings/deductions/employer/bases/trace. |
| **Mounted in** | `RunDetailPanel.jsx` | Preflight panel shown when run has BR payslips; breakdown shown in expanded employee row when `item.brCalculationSnapshot` present. |

---

## 4. Data Flow

```
calc_inputs (Phase 6)
    │
    ├─► EmployeeStatutoryProfile (br_esocial_category, br_establishment_id, …)
    ├─► PayrollBrEstablishment (rat_pct, fap_factor, third_party_pct, cnae)
    ├─► PayrollBrEmployerProfile (cnpj_root, cnae_preponderant → financial_sector)
    ├─► PayrollBrRiskAssignment (rat_pct, fap_factor per year)
    ├─► PayrollBrConcurrentInssDeclaration (base_external, deducted_external)
    ├─► PayrollBrAlimonyOrder (fixed_amount / percentage × base)
    ├─► PayrollBrValeTransporteElection (elected, daily_cost)
    └─► labor_rates(competence_month) → OT 50/100, night 20%, DSR flag
            │
            ▼
brazil_inputs dict ──► PayrollContext ──► brazil.calculate(ctx)
            │
            ▼
result.br_result (trace, bases, employer charges)
            │
            ▼
PayslipItem: flat br_* columns + br_calculation_snapshot (JSON)
            │
            ▼
API response: brCalculationSnapshot + flat fields
            │
            ▼
Approval: br_approval_fingerprint = SHA-256(run, engine, payslips[inputHash, totals])
```

---

## 5. Test Results

```
backend:
  test_brazil_phase1_content.py       15 passed
  test_brazil_scaffolding.py          25 passed
  test_brazil_phase1_foundation.py    6 passed
  test_brazil_phase2_engine.py        49 passed
  test_brazil_router.py               18 passed
  test_brazil_employee_migrations.py  1 passed
  test_brazil_employer.py             2 skipped
  test_brazil_employee_profile.py     1 passed
  test_brazil_employee_validation.py  2 passed
  test_model_tables_have_migrations.py 7 passed, 2 skipped
  ────────────────────────────────────────────
  207 passed, 2 skipped

frontend:
  npm run check:undefined   ✅ 515 files clean
  npm run build             ✅ 3.2s
  npm run lint              Pre-existing issues only
```

---

## 6. Known Gaps (Deferred to Phase 7+)

| Gap | Phase |
|-----|-------|
| eSocial Tabela 03 incidence codes verified (BR-K3/D6) | 6 (G1) |
| Consolidated CLT (art. 59/73 with amendments) re-fetched | 6 (G1) |
| VT benefit derived from Phase 4 election (`daily_cost × days`) | 6 |
| 13th salary, vacation, termination engines | 7 |
| CCT floors / collective agreement premiums | 8 |
| FGTS Digital due dates (S13/S14/S15) | 10 |
| PIX / CNAB payment settlement files | 11 |
| LGPD retention decisions | 11 |

---

## 7. Artifacts

- `docs/brazil/BRAZIL_PHASE_5_ANALYSIS.md` — Phase 5 analysis
- `docs/brazil/BRAZIL_PHASE_5_IMPLEMENTATION_REPORT.md` — Phase 5 report
- `docs/brazil/BRAZIL_PHASE_6_IMPLEMENTATION_REPORT.md` — This report
- `backend/app/modules/payroll/brazil_service.py` — All hooks
- `backend/app/modules/payroll/brazil_org_router.py` — Run preflight + fingerprint
- `backend/app/modules/payroll/service.py` — calc_inputs at 3 sites, snapshot persistence
- `backend/app/modules/payroll/models.py` — `br_approval_fingerprint` column
- `frontend/src/modules/payroll/PayRollRuns/BRRunPreflightPanel.jsx`
- `frontend/src/modules/payroll/PayRollRuns/BRPayslipBreakdown.jsx`
- `frontend/src/modules/payroll/PayRollRuns/brPayslipLines.js`
- `frontend/src/modules/payroll/PayRollRuns/RunDetailPanel.jsx` — Mounted
- `frontend/src/service/payrollService.js` — BR endpoints