"""
modules/payroll/forms/router.py
---------------------------------
Endpoints for "Send Template" — custom employee fields, form templates,
sending forms to employees, and reviewing submissions. Mounted under the
same /api/payroll prefix as the existing payroll_router (see bottom of
router.py for how it's included).

Two endpoints (`get_public_form` / `submit_public_form`) are deliberately
registered on a SEPARATE, unauthenticated router — they're reached by an
employee clicking an emailed link, with no login. Every other endpoint
here requires an authenticated org admin, same as the rest of Payroll.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request

from app.database import get_db
from app.core.dependencies import get_current_user, get_current_payroll_operator, require_active_subscription
from app.core.rate_limiter import limiter
from app.modules.payroll.forms import service
from app.modules.payroll.forms.schemas import (
    CustomFieldCreate, CustomFieldResponse, UpdateFormCreate, UpdateFormResponse,
    SendFormRequest, PublicFormResponse, PublicFormSubmitRequest, SubmissionResponse,
    SubmissionReviewRequest,
)

forms_router = APIRouter(
    prefix="/employee-forms",
    tags=["Payroll — Send Template"],
    dependencies=[Depends(require_active_subscription("payroll"))],
)

# Unauthenticated — reached by an employee's emailed link, no login/org context.
public_forms_router = APIRouter(prefix="/public/employee-forms", tags=["Payroll — Send Template (public)"])


# ── Custom field definitions ─────────────────────────────────────────────

@forms_router.get("/custom-fields", response_model=List[CustomFieldResponse])
def list_custom_fields(db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.list_custom_fields(db, current_user.organization_id)


@forms_router.post("/custom-fields", response_model=CustomFieldResponse, dependencies=[Depends(get_current_payroll_operator)])
def create_custom_field(data: CustomFieldCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.create_custom_field(
        db, current_user.organization_id, data.label, data.fieldType,
        select_options=data.selectOptions, actor_id=current_user.id,
    )


@forms_router.delete("/custom-fields/{field_id}", dependencies=[Depends(get_current_payroll_operator)])
def delete_custom_field(field_id: int, db=Depends(get_db), current_user=Depends(get_current_user)):
    service.delete_custom_field(db, current_user.organization_id, field_id)
    return {"message": "Custom field removed."}


# ── Form templates ────────────────────────────────────────────────────────

@forms_router.get("/templates", response_model=List[UpdateFormResponse])
def list_forms(db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.list_forms(db, current_user.organization_id)


@forms_router.post("/templates", response_model=UpdateFormResponse, dependencies=[Depends(get_current_payroll_operator)])
def create_form(data: UpdateFormCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.create_form(db, current_user.organization_id, data.name, data.fields, actor_id=current_user.id)


@forms_router.post("/templates/{form_id}/send", dependencies=[Depends(get_current_payroll_operator)])
def send_form(form_id: int, data: SendFormRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.send_form(db, current_user.organization_id, form_id, data.employeeIds)


# ── Submissions review queue ──────────────────────────────────────────────

@forms_router.get("/submissions", response_model=List[SubmissionResponse], dependencies=[Depends(get_current_payroll_operator)])
def list_submissions(status: Optional[str] = Query(None), db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.list_submissions(db, current_user.organization_id, status=status)


@forms_router.post("/submissions/{submission_id}/approve", dependencies=[Depends(get_current_payroll_operator)])
def approve_submission(submission_id: int, data: SubmissionReviewRequest = SubmissionReviewRequest(),
                        db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.review_submission(db, current_user.organization_id, submission_id, approve=True,
                                       notes=data.notes, actor_id=current_user.id)


@forms_router.post("/submissions/{submission_id}/reject", dependencies=[Depends(get_current_payroll_operator)])
def reject_submission(submission_id: int, data: SubmissionReviewRequest = SubmissionReviewRequest(),
                       db=Depends(get_db), current_user=Depends(get_current_user)):
    return service.review_submission(db, current_user.organization_id, submission_id, approve=False,
                                       notes=data.notes, actor_id=current_user.id)


# ── Public, unauthenticated — reached via the emailed link ───────────────
# Rate-limited per client IP, same slowapi limiter used on /login and other
# no-auth-gate endpoints — tokens are 256-bit and unguessable, but a limiter
# is still standard defense-in-depth against scripted probing here.

@public_forms_router.get("/{token}", response_model=PublicFormResponse)
@limiter.limit("20/minute")
def get_public_form(request: Request, token: str, db=Depends(get_db)):
    return service.get_public_form(db, token)


@public_forms_router.post("/{token}/submit")
@limiter.limit("10/minute")
def submit_public_form(request: Request, token: str, data: PublicFormSubmitRequest, db=Depends(get_db)):
    return service.submit_public_form(db, token, data.values)
