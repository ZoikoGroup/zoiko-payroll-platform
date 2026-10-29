# Mexico Phase 11a / 11b — SAT code proposals for engine-produced amounts (D4, D6)

**Status: PROPOSALS, nothing approved.** Each line becomes a system-concept row only when one Super Admin proposes it on the CFDI catalogs tab (Super Admin → Mexico → CFDI catalogs → **SAT codes for engine-produced amounts**) and **a different Super Admin approves it**. The approver checks the cited row in the saved source, not this document.

**Sources:**
- **S28:** `docs/mexico/sources/S28_SAT_catNomina.xls`. Row numbers are the spreadsheet's own (1-based).
- **S4:** `docs/mexico/sources/S4_SAT_Guia_llenado_Nomina.pdf`. Page numbers are the PDF's pages.
- The codes are spelled as the pinned set `sat_2026_08` spells them.

## Ready to propose (the source is unambiguous)

| Engine amount (`conceptKey`) | Node | SAT code | S28 description (verbatim) | Cite as `sourceRef` |
|---|---|---|---|---|
| `ISR_WITHHELD` | DEDUCCION | `002` | ISR | S28 c_TipoDeduccion row 7; S4 p. 113 (period ISR is "002") |
| `IMSS_EMPLOYEE` | DEDUCCION | `001` | Seguridad social | S28 c_TipoDeduccion row 6 |
| `AGUINALDO` | PERCEPCION | `002` | Gratificación Anual (Aguinaldo) | S28 c_TipoPercepcion row 7 |
| `VACATION_PREMIUM` | PERCEPCION | `021` | Prima vacacional | S28 c_TipoPercepcion row 21 |
| `PTU` | PERCEPCION | `003` | Participación de los Trabajadores en las Utilidades PTU | S28 c_TipoPercepcion row 8 |
| `ANNUAL_ADJUSTMENT_CHARGE` | DEDUCCION | `101` | ISR Retenido de ejercicio anterior | S28 c_TipoDeduccion row 106; S4 p. 112 (annual-calculation ISR charged is "101") |
| `SEPARATION_SENIORITY_PREMIUM` | PERCEPCION | `022` | Prima por antigüedad | S28 c_TipoPercepcion row 22; S4 p. 44 |
| `SEPARATION_PAYMENT` | PERCEPCION | `023` | Pagos por separación | S28 c_TipoPercepcion row 23; S4 p. 44 |
| `SEPARATION_INDEMNITY` | PERCEPCION | `025` | Indemnizaciones | S28 c_TipoPercepcion row 25; S4 p. 44 |

**Phase 11b:** the engine now emits the three separation kinds (the termination reason's content names each component's kind, and each kind has its own transcribed tax rule; a component without a kind, or a kind without a rule, blocks). The mappings are therefore unambiguous. **The builder still refuses a separation receipt:** it needs TipoRegimen 13 and the `SeparacionIndemnizacion` node (S4 pp. 34–35, 47, 56–59: last ordinary monthly salary, accumulable / non-accumulable income), which the engine does not produce yet. The guide's contract-type rule (p. 34) and separation rule (p. 35) must also be reconciled against the PAC's test environment.

## Not proposed: the G1 owner decides (two or more codes fit, or the engine needs more detail)

| Engine amount | Candidates in S28 | Why not proposed |
|---|---|---|
| `INFONAVIT_CREDIT` | DEDUCCION `010` "Pago por crédito de vivienda" (row 15); `009` "Préstamos provenientes del Fondo Nacional de la Vivienda para los Trabajadores" (row 14) | Both describe housing-credit deductions. S4 names neither phrase, so the guide does not settle it. |
| `SUBSIDY_APPLIED` | OTRO_PAGO `002` "Subsidio para el empleo (efectivamente entregado al trabajador)." (row 7); S4 pp. 24, 67–69, 102–109 | **Stays unmapped (decided 2026-10-23).** The saved S4 guide is the 2023 edition and its legal basis for the subsidy is the 11 December 2013 decree (S4 pp. 25, 68, 70), so it likely predates the 2024 subsidy reform. SAT's current instructions for reporting the subsidy in the nómina CFDI must be **saved as a new source** before this mapping can be proposed or approved (G1 checklist). The code also needs the `SubsidioAlEmpleo` node (S4 p. 67). Until then a receipt with a subsidy is refused (`MX_CFDI_CONCEPT_UNMAPPED`). |
| `VACATION_PAYOUT` (new in 11b) | PERCEPCION `001` "Sueldos, Salarios  Rayas y Jornales" (row 6); `038` "Otros ingresos por salarios" (row 38) | Vacation days paid out at termination. Neither S28 nor S4 names them; `021` is the vacation **premium**, not the days. |
| `ANNUAL_ADJUSTMENT_REFUND` | OTRO_PAGO `004` "Aplicación de saldo a favor por compensación anual." (row 9; S4 p. 67: requires the `CompensacionSaldosAFavor` node); `005` "Reintegro de ISR retenido en exceso de ejercicio anterior (siempre que no haya sido enterado al SAT)." (row 10) | Two codes with different conditions. `004` needs data the engine does not produce yet (the `CompensacionSaldosAFavor` node). |

## Earning classifications (D6)

No canonical earning classification exists in any environment: organisations define their own earning codes, and each classification is created by a Super Admin. So there is no list of earning codes to propose codes for. What 11a changes:
- **Approving a canonical classification now checks its code against the catalog of its own node type** (PERCEPCION and SEPARACION → c_TipoPercepcion, DEDUCCION → c_TipoDeduccion, OTRO_PAGO → c_TipoOtroPago).
  - Before 11a, any code in any catalog passed, so a percepción could carry a deduction-only code.
- With a release loaded from `sat_2026_08`, a Super Admin picks the code from the release's c_TipoPercepcion entries (filterable on the catalogs tab), cites the row, and a second Super Admin approves.
