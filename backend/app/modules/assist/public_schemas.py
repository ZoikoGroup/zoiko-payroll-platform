"""
modules/assist/public_schemas.py
---------------------------------
Request/response models for the unauthenticated public-website Assist mode.
Deliberately separate from schemas.py — this surface never accepts an
organization_id, user identity, or context binding from the caller.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicSessionCreate(BaseModel):
    locale: str = "en"


class PublicSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    created_at: datetime


class PublicMessageSubmitRequest(BaseModel):
    text: str = Field(..., max_length=2000)


class PublicMessageSubmitResponse(BaseModel):
    session_id: int
    intent_id: str
    answer: str
    sources: list[dict] = Field(default_factory=list)


class PublicMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
