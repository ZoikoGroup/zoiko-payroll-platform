"""
modules/assist/public_router.py
---------------------------------
Unauthenticated Assist endpoints for the public marketing website.

No get_current_user, no get_organization_id, no organization_id accepted
from the caller anywhere — this router is mounted with a completely
different trust boundary than assist_router (router.py). Rate-limited per
client IP with the same slowapi limiter used on /login and the public
forms endpoints (see payroll/forms/router.py for the identical pattern).
"""

from fastapi import APIRouter, Depends, Request

from app.core.rate_limiter import limiter
from app.database import get_db
from app.modules.assist import public_service as service
from app.modules.assist.public_schemas import (
    PublicMessageResponse,
    PublicMessageSubmitRequest,
    PublicMessageSubmitResponse,
    PublicSessionCreate,
    PublicSessionResponse,
)

assist_public_router = APIRouter(prefix="/assist/public", tags=["Assist (Public)"])


@assist_public_router.post("/sessions", response_model=PublicSessionResponse)
@limiter.limit("20/minute")
def create_public_session(request: Request, payload: PublicSessionCreate, db=Depends(get_db)):
    return service.create_public_session(db, request.client.host if request.client else None, payload.locale)


@assist_public_router.post("/sessions/{session_id}/messages", response_model=PublicMessageSubmitResponse)
@limiter.limit("10/minute")
def submit_public_message(request: Request, session_id: int, payload: PublicMessageSubmitRequest, db=Depends(get_db)):
    return service.submit_public_message(db, session_id, payload.text)


@assist_public_router.get("/sessions/{session_id}/messages", response_model=list[PublicMessageResponse])
@limiter.limit("30/minute")
def list_public_messages(request: Request, session_id: int, db=Depends(get_db)):
    return service.list_public_messages(db, session_id)
