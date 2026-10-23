# Mexico Phase 11a — SAT code proposals for engine-produced amounts (D4, D6)

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

## Not proposed: the G1 owner decides (two or more codes fit, or the engine needs more detail)

| Engine amount | Candidates in S28 | Why not proposed |
|---|---|---|
| `INFONAVIT_CREDIT` | DEDUCCION `010` "Pago por crédito de vivienda" (row 15); `009` "Préstamos provenientes del Fondo Nacional de la Vivienda para los Trabajadores" (row 14) | Both describe housing-credit deductions. S4 names neither phrase, so the guide does not settle it. |
| `SUBSIDY_APPLIED` | OTRO_PAGO `002` "Subsidio para el empleo (efectivamente entregado al trabajador)." (row 7); S4 pp. 24, 67–69, 102–109 | The code is clear in S4 (2023 edition), but it also requires the `SubsidioAlEmpleo` node (S4 p. 67). The S4 edition saved is dated 2023-03-09: any later SAT instruction on the employment subsidy is **not** in the saved sources. The G1 owner confirms the current rule before this is approved. |
| `SEPARATION` | PERCEPCION `022` "Prima por antigüedad" (row 22), `023` "Pagos por separación" (row 23), `025` "Indemnizaciones" (row 25); S4 pp. 43–47 (`SeparacionIndemnizacion`) | The engine has **one** `SEPARATION` kind but SAT has three codes. **An engine gap, not a mapping choice:** separation lines need sub-kinds before they can be mapped (Phase 11b). |
| `ANNUAL_ADJUSTMENT_REFUND` | OTRO_PAGO `004` "Aplicación de saldo a favor por compensación anual." (row 9; S4 p. 67: requires the `CompensacionSaldosAFavor` node); `005` "Reintegro de ISR retenido en exceso de ejercicio anterior (siempre que no haya sido enterado al SAT)." (row 10) | Two codes with different conditions. `004` needs data the engine does not produce yet (the `CompensacionSaldosAFavor` node). |

## Earning classifications (D6)

No canonical earning classification exists in any environment: organisations define their own earning codes, and each classification is created by a Super Admin. So there is no list of earning codes to propose codes for. What 11a changes:
- **Approving a canonical classification now checks its code against the catalog of its own node type** (PERCEPCION and SEPARACION → c_TipoPercepcion, DEDUCCION → c_TipoDeduccion, OTRO_PAGO → c_TipoOtroPago).
  - Before 11a, any code in any catalog passed, so a percepción could carry a deduction-only code.
- With a release loaded from `sat_2026_08`, a Super Admin picks the code from the release's c_TipoPercepcion entries (filterable on the catalogs tab), cites the row, and a second Super Admin approves.
