# Optional decision — G1 accepts internal review in lieu of an external Hong Kong specialist (DRAFT)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **Not recommended by engineering, and not decided.** This is not a code-registered decision (it is not in `hong_kong_service.DECISIONS`) and has no evidence tag of its own. If taken, it would be attached to the G1 evidence (`HK-GATE-G1`).

## Question

Should G1 ("Hong Kong specialist signs effective-dated wage, MPF, Employment Ordinance and IRD mappings") be accepted on the strength of a Zoiko internal review, without an external Hong Kong payroll or statutory specialist?

## What the internal review would cover

The 152 values in the 2026/27 pack. 123 of them have an archived official source with a recorded SHA-256 and pass the golden vectors. The decision really concerns the **29 flagged values**:
* 24 earning classifications (whether each pay element counts as EO wages, MPF relevant income, SMW wages and IRD income);
* the MPF partial-month basis;
* the average-wage day divisor;
* the overtime inclusion test;
* the Employment Ordinance week start (which has no hashed source);
* the MPF contribution-day deferral rule.

These are interpretations, not published numbers.

## Options

1. **External specialist (the wireframe's requirement).** Commission a Hong Kong payroll / statutory specialist to certify the worksheet.
2. **Internal review in lieu.** A named Zoiko reviewer certifies, and the owner accepts the risk below.
3. **Narrowed launch.** Launch only for pay elements whose classification is unambiguous (for example basic salary only). Other elements are refused fail-closed until certified. This needs owner decision D-7 and engineering work to restrict the elements.

## Risks of option 2, stated plainly

* **Wrong MPF contributions.** A misclassified allowance changes MPF relevant income for every affected employee, every month. Late or under-paid mandatory contributions attract MPFA surcharges, and the employer is liable. Correction means supplementary eMPF batches for every affected period.
* **Wrong statutory entitlements.** The EO-wage classification and the average-wage method drive holiday pay, annual leave pay, sickness allowance and SP/LSP. Errors underpay employees and expose the customer to Labour Department claims.
* **Wrong IRD reporting.** IR56B/E/F/G income classification errors mean amended returns and possible penalties for the employer.
* **The 468 / continuous-contract week start** affects who qualifies for statutory benefits at all.
* **Liability and contracts.** Zoiko's customer contracts and insurance may assume external certification. An internal sign-off may not be defensible if challenged.
* **The gate text is not met.** The wireframe says "specialist signs". Accepting internal review means G1 is passed by owner exception, and launch documents must say so.

## If option 2 is chosen, minimum conditions (proposed)

* The reviewer is named, with HK payroll experience stated, and is not the engineer who seeded the values.
* The exception is time-limited: external certification by a date, otherwise the pack is suspended.
* Customers are told in writing which classifications are internally certified.

## Decision (leave blank until decided)

Selected option: ________
Reason: ________
Expiry / review date: ________

Decision owner — Name / Role / Date / Signature: ________
Risk accepted by — Name / Role / Date / Signature: ________
