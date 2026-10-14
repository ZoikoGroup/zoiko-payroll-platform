# NL Wage Tax Table Fixtures

**BLOCKED ON G1**: These fixtures require the official 2026 Belastingdienst table files.
G1 cannot be signed off without them.

## Required Files (to be supplied by compliance/legal)

| File | Description | Table Kind | Period | Colour | Residence |
|------|-------------|------------|--------|--------|-----------|
| `loonheffing_2026_white_period_day.csv` | White table, daily periods | PERIOD | DAY | WHITE | NL |
| `loonheffing_2026_white_period_week.csv` | White table, weekly periods | PERIOD | WEEK | WHITE | NL |
| `loonheffing_2026_white_period_4week.csv` | White table, 4-weekly periods | PERIOD | FOUR_WEEK | WHITE | NL |
| `loonheffing_2026_white_period_month.csv` | White table, monthly periods | PERIOD | MONTH | WHITE | NL |
| `loonheffing_2026_white_period_quarter.csv` | White table, quarterly periods | PERIOD | QUARTER | WHITE | NL |
| `loonheffing_2026_white_period_year.csv` | White table, annual periods | PERIOD | YEAR | WHITE | NL |
| `loonheffing_2026_green_period_day.csv` | Green table, daily periods | PERIOD | DAY | GREEN | NL |
| `loonheffing_2026_green_period_week.csv` | Green table, weekly periods | PERIOD | WEEK | GREEN | NL |
| `loonheffing_2026_green_period_4week.csv` | Green table, 4-weekly periods | PERIOD | FOUR_WEEK | GREEN | NL |
| `loonheffing_2026_green_period_month.csv` | Green table, monthly periods | PERIOD | MONTH | GREEN | NL |
| `loonheffing_2026_green_period_quarter.csv` | Green table, quarterly periods | PERIOD | QUARTER | GREEN | NL |
| `loonheffing_2026_green_period_year.csv` | Green table, annual periods | PERIOD | YEAR | GREEN | NL |
| `loonheffing_2026_white_special.csv` | White special remuneration | SPECIAL_REMUNERATION | (none) | WHITE | NL |
| `loonheffing_2026_green_special.csv` | Green special remuneration | SPECIAL_REMUNERATION | (none) | GREEN | NL |
| `loonheffing_2026_derivation_*.csv` | Derivation tables (non-resident) | PERIOD / SPECIAL_REMUNERATION | various | WHITE/GREEN | DERIVATION_CODE |

## CSV Format

### PERIOD tables
```csv
wage_from,wage_to,aow_cohort,with_tax_credit,withholding_amount
0.00,100.00,BELOW_AOW,true,0.00
100.00,200.00,BELOW_AOW,true,5.00
...
```

### SPECIAL_REMUNERATION tables
```csv
wage_from,wage_to,aow_cohort,with_tax_credit,percentage
0.00,100000.00,BELOW_AOW,true,52.0000
...
```

## Expected Test Values (from spec)

Once official tables are loaded, the reproduction harness in `test_netherlands_wage_tax.py`
will verify:

- **F1**: €5,000/month with tax credit → €1,325.08 withholding
- Each AOW cohort (BELOW_AOW, AOW_AGE) and pay period (DAY, WEEK, FOUR_WEEK, MONTH, QUARTER, YEAR)
- With and without tax credit
- Anonymous rate (52% flat)
- Special remuneration percentage
- Replay protection: later table never replaces original when period replayed (NL-004)

## Gate G1 Requirements

Before G1 sign-off:
1. All 14+ official CSV files placed in this directory
2. `scripts/seed_netherlands_canonical_packs.py` run against local DB
3. `netherlands_tables_service.import_table_file()` used to import each CSV
4. Each file validated → approved → activated with four-eyes
4. `test_netherlands_wage_tax.py` all tests pass
5. Golden-run certification for NL passes