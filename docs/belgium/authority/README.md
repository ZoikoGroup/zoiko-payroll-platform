# Belgium authority onboarding — request drafts (Block E5)

Ready-to-send DRAFTS. Nothing here has been sent. Every value the company must supply is marked **[TO FILL]**;
every address not verified in this session is marked **[TO CONFIRM]**. Context: `../BELGIUM_AUTHORITY_ONBOARDING.md`.

| File | To | Unblocks |
|------|----|----------|
| `01_DIMONA_DMFA_CHANNEL_REQUEST.md` | ONSS / RSZ (socialsecurity.be) | G3 (Dimona / DmfA channel + test environment) |
| `02_FINPROF_BELCOTAX_CREDENTIALS_REQUEST.md` | FPS Finance / SPF Finances | G3 (FinProf + Belcotax-on-web) |
| `03_XSD_TECHNICAL_DOCUMENTATION_REQUEST.md` | ONSS / RSZ and FPS Finance | G-31 (schemas + payload mapping), G-33 (codes) |
| `04_MANDATE_TEMPLATE.md` | each launch employer | G3 / G5 (declaring on the employer's behalf) |

Owner: Integration lead (requests 1-3), Payroll operations with each launch employer (mandates). Credentials
received go only into the managed secret store (spec §15) — never into email, tickets, configuration or the repo.
