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


class PublicHealthResponse(BaseModel):
    status: str  # "available" | "degraded" | "unavailable"


class PublicCountry(BaseModel):
    code: str
    name: str
    launch_status: str  # "live" | "planned" | "unavailable"
    aliases: list[str] = Field(default_factory=list)
    capabilities: dict[str, str] = Field(default_factory=dict)
    verified_at: str | None = None
    source_url: str | None = None


class PublicCountriesResponse(BaseModel):
    countries: list[PublicCountry]
    live_count: int
    updated_at: str
