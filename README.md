# Zoiko Payroll Platform

A standalone, self-contained payroll platform with a governed AI assistant
(**Zoiko Payroll Assist**). It owns its own database, its own JWT namespace and
its own CORS config — nothing is shared with (or imported from) the main
ZoikoOne platform at runtime.

```
zoiko-payroll-platform/
├── backend/     # FastAPI + SQLAlchemy + SQLite(dev)/PostgreSQL(prod)
├── frontend/    # React 19 + Vite + Tailwind 4 (SPA)
├── docs/        # Zoiko Payroll Assist specification suite (8 documents)
└── README.md    # this file
```

---

## 1. Stack

| Layer    | Technology |
|----------|------------|
| Backend  | Python 3.12+, FastAPI, SQLAlchemy 2, pydantic-settings |
| Database | PostgreSQL (prod) / SQLite (dev fallback, `app/data/payroll_dev.sqlite3`) |
| Frontend | React 19, Vite 8, Tailwind 4, react-router 7, recharts, pdfmake, xlsx |
| Auth     | JWT (python-jose) — own secret `PAYROLL_SECRET_KEY` |
| Rate limit | slowapi |
| Jobs     | APScheduler |

The backend exposes the following routers under `/api`:

| Prefix              | Area |
|---------------------|------|
| `/api/auth`         | Login/register, user management |
| `/api/organizations`| Organization profile + super-admin org CRUD |
| `/api/payroll/...`  | Payroll runs, employees, payslips, compliance, attendance, policies |
| `/api/employee`     | Employee self-service (ESS) |
| `/api/super-admin`  | Platform admin |
| `/api/assist`       | **Zoiko Payroll Assist** (AI assistant) |

---

## 2. Prerequisites

- **Python 3.12+** (tested with 3.13)
- **Node.js 20+** (Vite 8 requires a recent LTS)
- **PostgreSQL 14+** — only if you are not using the dev SQLite fallback
- *(Optional)* **Tesseract OCR** binary for payslip/compliance OCR via `pytesseract`

---

## 3. Installation

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # bash: source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend

```powershell
cd frontend
npm install
```

---

## 4. Configuration

Copy the environment templates and fill in:

```powershell
cd backend
copy .env.example .env               # bash: cp .env.example .env

cd ..\frontend
copy .env.example .env               # bash: cp .env.example .env
```

Key variables (see `backend/.env.example` for the full list):

| Variable                    | Purpose |
|-----------------------------|---------|
| `PAYROLL_DATABASE_URL`      | Leave **empty** in dev to use SQLite. Set a `postgresql+psycopg://...` URL in prod. |
| `PAYROLL_SECRET_KEY`        | Own JWT secret — never reuse the main platform's. |
| `PAYROLL_CORS_ORIGINS`      | Comma-separated allowed browser origins. |
| `SETUP_KEY`                 | Required to seed the first Super Admin (see §6). |
| `ASSIST_MODEL_PROVIDER`     | `openai-compatible` to enable the LLM gateway, or empty for deterministic-only (see §9). |
| `ASSIST_MODEL_BASE_URL` / `ASSIST_MODEL_API_KEY` / `ASSIST_MODEL_NAME` | OpenAI-compatible provider settings. |

---

## 5. Database bootstrap

The platform has **no alembic**. The schema is created in one shot with
`Base.metadata.create_all` (see `backend/migrations/create_all/README.md`).

The app calls `initialize_database()` automatically on startup, which also
seeds the Assist reference content (governed KB, capabilities, suggestions,
policy notice). For an explicit/repeatable bootstrap:

```powershell
cd backend
python -m migrations.create_all.create_all              # fresh empty DB
python -m migrations.create_all.create_all --drop       # wipe + recreate scratch DB
```

---

## 6. Seeding users

### Super Admin (first, required)

```powershell
cd backend
set SETUP_KEY=your-setup-key
set PAYROLL_SUPER_ADMIN_EMAIL=admin@example.com
set PAYROLL_SUPER_ADMIN_PASSWORD=change-me-1234
python -m scripts.seed_super_admin
```

Super Admin accounts can **never** be created through `/auth/register`.

### Demo organization + users

```powershell
python -m scripts.seed_org `
  --org "Acme Corp" `
  --admin-email admin@acme.test --admin-password "password123" `
  --payroll-email payroll@acme.test --payroll-password "password123" `
  --employee-email emp@acme.test --employee-password "password123"
```

Alternatively, use the in-app registration flow on the landing page
(`/auth/register` creates a new organization + its first org admin).

---

## 7. Execution process (run the app)

### 7.1 Start the backend

```powershell
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Wait for the log line:

```
Database tables initialized successfully.
Zoiko Payroll Platform backend is ready.
```

Backend URLs once running:

| URL                 | Purpose |
|---------------------|---------|
| `http://localhost:8000/`       | Health root (`{name, version, status, docs}`) |
| `http://localhost:8000/health` | DB connectivity check |
| `http://localhost:8000/docs`   | Swagger UI (interactive API docs) |
| `http://localhost:8000/openapi.json` | OpenAPI spec |

### 7.2 Start the frontend

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`.

### 7.3 Login and use

1. Log in with a seeded user (`admin@acme.test` for a demo org admin, or the
   Super Admin).
2. **Payroll**: create/set up a payroll run and employees from the payroll
   module.
3. **Assist**: the assistant launcher is available in the payroll shell (bottom
   right). Ask run-readiness, exception or knowledge questions; A3 actions
   render as preview cards you confirm before execution.
4. **Assist Admin**: open `/payroll/assist-admin` (org admin / payroll admin /
   super admin) for audit events, session governance, retention, model
   executions and knowledge-base management.

### 7.4 Production build

```powershell
cd frontend
npm run build        # outputs to frontend/dist
npm run preview      # serve the production build locally
```

---

## 8. Testing & quality

```powershell
cd backend

python -m pytest tests/ -q           # full backend test suite (17 tests)
python scripts/eval_assist.py        # Assist intent + safety evaluation harness (17 cases)
python scripts/eval_assist.py --llm  # also exercise the LLM gateway (requires config)
python -m ruff check app/ tests/     # lint
```

Frontend build verification:

```powershell
cd frontend
npm run build
```

---

## 9. Zoiko Payroll Assist

### Architecture (backend module `backend/app/modules/assist/`)

```
message ──► intent classifier ──► policy decision ──► evidence gathering
   ──► grounded answer (deterministic OR OpenAI-compatible LLM gateway)
   ──► guardrails validation ──► response + blocks ──► SSE events ──► audit
```

| Component   | Role |
|-------------|------|
| `intents.py`     | Intent classification (run readiness, exceptions, variance, KB, prohibited acts) |
| `service.py` / `guardrails.py` | Policy decisions, risk tiers (A1/A3), prohibited-action refusal, grounded-response validation |
| `gateway.py`     | Deterministic engine (always available) + optional OpenAI-compatible provider with safe fallback |
| `prompts.py`     | System prompt, evidence envelope and task prompt builders |
| `tools.py`       | Read tools (run summary, readiness, exceptions, variance) and A3 actions (assign exception, add note, handoff) |
| `knowledge.py`   | Governed knowledge base (seeded on startup, admin CRUD) |
| `models.py`      | Sessions, messages, responses, evidence, drafts, handoffs, action previews/receipts, audit, model executions |
| `router.py`      | REST + SSE endpoints under `/api/assist` |

### Capabilities

- **Governed by policy** — the notice gate blocks messaging until the policy
  notice is acknowledged; prohibited acts (approve payroll, release payments,
  submit filings, change protected data) are always refused.
- **Evidence-grounded answers** — every response is built from visible payroll
  records + governed knowledge and validated by guardrails before rendering.
- **Controlled actions (A3)** — preview → confirm → receipt lifecycle with an
  auto action-block in the chat; nothing executes without explicit confirmation.
- **Streaming** — SSE event stream per response (`/responses/{id}/events/stream`).
- **Admin** — audit events, session governance, retention cleanup
  (`POST /admin/retention/run`), model-execution records
  (`GET /admin/model-executions`), and knowledge-base management
  (create/edit drafts, publish APPROVED items, list sources).

### Enabling the LLM gateway (optional)

By default Assist runs fully deterministically — no external credentials
needed. To use an OpenAI-compatible model for answer generation:

```powershell
# backend/.env
ASSIST_MODEL_PROVIDER=openai-compatible
ASSIST_MODEL_BASE_URL=https://api.openai.com/v1
ASSIST_MODEL_API_KEY=sk-...
ASSIST_MODEL_NAME=gpt-4o-mini
ASSIST_MODEL_TIMEOUT_SECONDS=30
```

If the provider call fails, the engine automatically falls back to the
deterministic engine with a safe, governed answer. Every generation is logged
to the `assist_model_executions` table.

### Key API groups

```
POST /api/assist/sessions                          create session
POST /api/assist/sessions/{id}/messages            submit message (Idempotency-Key)
GET  /api/assist/responses/{id}                    response + blocks + sources
GET  /api/assist/responses/{id}/events/stream      SSE event stream
POST /api/assist/action-previews                   A3 preview → confirm → receipt
POST /api/assist/handoff-previews                  handoff preview → confirm
GET  /api/assist/admin/audit-events                audit events
GET  /api/assist/admin/retention                   retention summary
POST /api/assist/admin/retention/run               archive expired sessions
GET  /api/assist/admin/model-executions            model execution records
GET  /api/assist/knowledge/items                   list governed knowledge
POST /api/assist/knowledge/items                   create knowledge draft
POST /api/assist/knowledge/items/{id}/publish      publish approved knowledge
```

Full endpoint catalogue: `docs/Zoiko_Payroll_Assist_API_Documentation_Detailed_Wireframe_v1.0.docx`.

---

## 10. Documentation suite

The `docs/` folder holds the 8-document specification suite for Assist:

- PRD & FRS detailed wireframes (`v1.0`)
- API documentation
- Chatbot detailed engineering wireframe
- Database schema / ER diagram
- Knowledge base governance & content specification
- Prompt engineering / AI guardrail specification
- Technical architecture documentation
- UI/UX Figma design specification
