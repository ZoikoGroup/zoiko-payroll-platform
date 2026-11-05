# Poland P0 — scaffold, dormancy, identifiers

Read first: `docs/poland/README.md` (decisions D1–D6 and the rules for every
phase). Spec: ZP-PL-ENG-001 §1 (PL-001), §3 (identity fields), §12 (PL-023),
§13 (identifiers masked).

## Goal

The platform recognises Poland as `PL`, resolves every Polish country name to
`PL` (today "Poland" would truncate to `"PO"` in
`payroll/service.py::_normalize_country`), refuses any organisation entering
Poland while `PL_TENANT_ONBOARDING_ENABLED` is off, and can validate Polish
identifiers and IBANs. **No payroll calculation, no content values, no
migration, no frontend pages in this phase.**

## Out of scope for P0 (do NOT do)

- No `poland_content.py`, no pack rows, no seed script (P1).
- No migration, no models, no PESEL storage/vault (P2). P0 only *validates*.
- No engine, service hooks or routes (P3/P4). Do **not** add PL to
  `jurisdiction_hooks._MODULES`, `standard._COUNTRY_CALC`,
  `shared._VALIDATION_ENABLED_COUNTRIES`, or the four-eyes lists in `service.py`.
- Do not add PL to `REGISTRATION_COUNTRIES` (the public registration dropdown).

## Backend changes

### 1. `backend/app/core/jurisdiction.py`

Add next to the ZA / JP / NZ entries, with a comment in the same style
("Poland (ZP-PL-ENG-001 Phase 0) - schema only. Deliberately NOT in
REGISTRATION_COUNTRIES ...").

`JURISDICTION_TAX_SCHEMAS["PL"]`:

```python
"PL": {
    "label": "NIP / REGON / KRS",
    "currency": "PLN",
    "fields": [
        {"key": "nip", "label": "NIP (tax identification number, 10 digits)",
         "pattern": r"^\d{10}$", "example": "1234563218", "primary": True},
        {"key": "regon", "label": "REGON (statistical number, 9 or 14 digits)",
         "pattern": r"^(\d{9}|\d{14})$", "example": "123456785", "primary": False},
        {"key": "krs", "label": "KRS (National Court Register number, 10 digits)",
         "pattern": r"^\d{10}$", "example": "0000123456", "primary": False},
    ],
},
```

Examples must pass the checksums in step 5 (`1234563218` is a valid NIP and
`123456785` a valid REGON-9 — both hand-checked).

`COUNTRY_NAME_TO_CODE` additions:
`"poland": "PL"`, `"polska": "PL"`, `"rzeczpospolita polska": "PL"`,
`"republic of poland": "PL"`, `"pol": "PL"`.
**Do not add `"pl"`** (the bare code is already resolved by
`get_jurisdiction_code` through `JURISDICTION_TAX_SCHEMAS`).

`CODE_TO_COUNTRY_NAME["PL"] = "Poland"`.

### 2. `backend/app/config.py`

After `NZ_TENANT_ONBOARDING_ENABLED`, same comment style:

```python
# Poland dormancy switch (ZP-PL-ENG-001 Phase 0, poland_dormancy). False = no
# organisation can become Polish and the Poland APIs refuse. Leave UNSET in
# production until the PL release gates G1-G7 are signed.
PL_TENANT_ONBOARDING_ENABLED: bool = False
```

### 3. NEW `backend/app/modules/payroll/poland_dormancy.py`

A copy of `south_africa_dormancy.py` with PL names:
`PL = "PL"`, `DORMANT_MESSAGE` ("Poland is not open for onboarding on this
platform yet - Polish payroll stays disabled until its release gates are
signed."), `onboarding_enabled()` reading `PL_TENANT_ONBOARDING_ENABLED`,
`is_poland(country)` via `get_jurisdiction_code`, and
`entering_poland_refusal(old_country, new_country) -> Optional[str]`.

### 4. `backend/app/modules/payroll/engine/tax_resolver.py`

- Add `"PL"` to `_REGISTRY_ROW_REQUIRED_COUNTRIES`.
- In `get_jurisdiction_change_block_reason`, add a Poland block after the NZ
  one (same shape as the ZA block): import `entering_poland_refusal`, return
  its message if set.

### 5. `backend/app/modules/payroll/employee_validation.py`

Pure functions (module level, next to `za_national_id_is_valid`):

```python
def pl_pesel_is_valid(value) -> bool:
    # 11 digits; weights 1,3,7,9,1,3,7,9,1,3 ; check = (10 - sum % 10) % 10
    # AND digits 1-6 encode a real date: month offsets 80 (1800s), 0 (1900s),
    # 20 (2000s), 40 (2100s), 60 (2200s).
def pl_nip_is_valid(value) -> bool:
    # 10 digits (strip spaces/dashes); weights 6,5,7,2,3,4,5,6,7 ;
    # sum % 11 == 10 -> invalid ; else must equal the 10th digit.
def pl_regon_is_valid(value) -> bool:
    # 9 digits: weights 8,9,2,3,4,5,6,7 ; check = sum % 11, 10 -> 0
    # 14 digits: first 9 must be a valid REGON-9 AND
    #   weights 2,4,8,5,0,9,7,3,6,1,2,4,8 ; check = sum % 11, 10 -> 0
```

These are published checksum algorithms (identifier format), not statutory
payroll values — code is the right place for them, as with ZA's Luhn check.

`class PLEmployeeValidation(EmployeeValidationStrategy)`, modelled on
`ZAEmployeeValidation`:

- `country_code = "PL"`, `duplicate_field = "national_id"`,
  `SENSITIVE_FIELDS = ("national_id", "passport_number", "tax_number", "iban")`.
- `FIELD_SPECS`: `national_id` (PESEL, `^\d{11}$`, strip spaces/dashes),
  `passport_number` (`^[A-Z0-9]{6,20}$`, upper), `tax_number` (NIP,
  `^\d{10}$`, optional — used when a worker has no PESEL), `iban`
  (`^PL\d{26}$`, upper, strip spaces).
- `_validate_combination`: at least one of `national_id` / `passport_number`
  is required; `national_id` must pass `pl_pesel_is_valid`; `tax_number` if
  present must pass `pl_nip_is_valid`; `iban` if present must pass the
  standard IBAN mod-97 check — reuse `validate_iban` / `normalise_iban` from
  `app/modules/payroll/bank_export/sepa_pain001.py` (do not write a new one).
- Error messages must never echo the identifier value.

Register it in `_DORMANT_STRATEGIES["PL"]` and in `_dormant_strategy` gate it
on `poland_dormancy.onboarding_enabled()` (same as ZA). Do **not** add it to
`_STRATEGIES`.

Note for review: PESEL will be stored in the existing plaintext
`national_id` only once P2 adds the encrypted vault; until then PL is dormant.
Add a `# P2: PESEL moves to the PL identifier vault` comment on the class.

### 6. `backend/app/modules/payroll/bank_routing.py`

Add `"PL"` to `ROUTING_COUNTRIES`; `ROUTING_FIELDS["PL"] = [{"key": "iban",
"label": "IBAN"}]` (Polish domestic transfers use the IBAN/NRB only; add BIC
only if the existing IBAN-country entries require it for the export format —
follow the CH/SA entries); `BTF_ROUTING_LABEL["PL"] = "IBAN"`;
`PAYMENT_MODE_LABEL["PL"] = "Elixir / SEPA"`.

## Frontend changes

| File | Change |
|---|---|
| `frontend/src/utils/currency.js` | `PL: "PLN"` in the country→currency map; a `PLN` entry (`symbol: 'zł'`, `name: 'Polish Złoty'`, `nameNative: 'Polski złoty'`, `locale: 'pl-PL'`, flag 🇵🇱, `decimalDigits: 2`); `{ code: "PL", name: "Poland", currency: "PLN" }` in the country list. |
| `frontend/src/utils/jurisdictionTax.js` | `PL` schema that mirrors the backend **exactly** (labels, patterns, examples); aliases `poland`, `polska`, `rzeczpospolita polska`, `republic of poland`; `PL: "Poland"` in the code→name map. Never alias bare `"pl"`. |
| `frontend/src/modules/payroll/Payroll_Employees/countryFieldSpecs.js` | `{ code: "PL", name: "Poland" }` in the country list; `COUNTRY_FIELD_SPECS.PL` = national_id (PESEL), passport_number, tax_number (NIP), iban — same patterns as the backend; add a JS `plPeselIsValid` that matches the Python algorithm. |
| `frontend/src/modules/payroll/Payroll_Employees/bankFieldsFor.js` | `"PL"` in `BANK_ROUTING_COUNTRIES`; mode label, routing label and fields matching `bank_routing.py`. |

Make sure "zł" and "Złoty" are saved as UTF-8 (PL-023).

## Tests

NEW `backend/tests/test_poland_scaffold.py` (model on `tests/test_nz_scaffold.py`):

1. `get_jurisdiction_code` returns `"PL"` for `Poland`, `poland`, ` POLAND `,
   `Polska`, `Rzeczpospolita Polska`, `Republic of Poland`, `PL`, `pl` (the
   bare code still resolves via the schema), and `payroll.service._normalize_country("Poland") == "PL"` (never `"PO"`).
2. `JURISDICTION_TAX_SCHEMAS["PL"]` examples match their own patterns AND pass
   the checksum functions.
3. PESEL: known-valid numbers across centuries (1900s, 2000s), wrong check
   digit, impossible date (month 13, 31 Feb), wrong length, letters.
4. NIP: valid, wrong check digit, the `sum % 11 == 10` case, dashes/spaces accepted.
5. REGON: valid 9, valid 14, invalid 9, 14 whose first 9 are invalid.
6. Dormancy: with the flag off, `entering_poland_refusal(None, "Poland")`
   returns the message; `("PL", "PL")` returns None; flag on returns None;
   `get_jurisdiction_change_block_reason` refuses moving an org into Poland.
7. `_dormant_strategy("PL")` is None with the flag off and
   `PLEmployeeValidation` with it on; `PL` not in `_STRATEGIES`.
8. Validation errors never contain the submitted identifier.
9. `bank_routing`: PL IBAN fields present; a valid PL IBAN passes, a mutated one fails.
10. `"PL"` is NOT in the registration country list and NOT in
    `jurisdiction_hooks._MODULES` (guards against scope creep).

Frontend: extend the nearest existing country check (or add a small block to
an existing `scripts/*-validation.mjs`) proving `plPeselIsValid` agrees with
the Python vectors.

## Commands to run (all must pass; paste the output summary)

```bash
cd backend
python -c "import app.main"            # import check (must not need a database)
python -m pytest tests/test_poland_scaffold.py -q
python -m pytest tests/test_nz_scaffold.py tests/test_south_africa_validation.py tests/test_mexico_scaffolding.py tests/test_mexico_employee_validation.py tests/test_country_entitlement.py -q
cd ../frontend
npm run build
npm run check:undefined
npm test
```

If any command needs a database or `.env`, stop and report instead of working around it.

## Done when

- All files above changed as described; nothing else touched.
- New tests pass; the listed cross-country tests still pass; frontend builds.
- Changes are **uncommitted**; the agent reports the list of changed files and
  test results, plus anything it could not do.
