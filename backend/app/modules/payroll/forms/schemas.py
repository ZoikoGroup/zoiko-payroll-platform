"""
modules/payroll/forms/schemas.py
---------------------------------
Pydantic schemas for "Send Template" — custom employee fields, saved form
templates, sending them to employees, and reviewing what's submitted.
"""
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CustomFieldCreate(BaseModel):
    label: str
    fieldType: str = "text"          # text | number | date | select
    selectOptions: Optional[List[str]] = None


class CustomFieldResponse(BaseModel):
    id: int
    fieldKey: str = Field(validation_alias="field_key", serialization_alias="fieldKey")
    label: str
    fieldType: str = Field(validation_alias="field_type", serialization_alias="fieldType")
    selectOptions: Optional[List[str]] = Field(None, validation_alias="select_options", serialization_alias="selectOptions")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FormFieldConfig(BaseModel):
    key: str
    label: str
    type: str                          # text | number | date | select
    source: str                        # standard | custom
    required: bool = False
    options: Optional[List[str]] = None


class UpdateFormCreate(BaseModel):
    name: str
    fields: List[FormFieldConfig]


class UpdateFormResponse(BaseModel):
    id: int
    name: str
    fields: List[FormFieldConfig] = Field(validation_alias="fields_config", serialization_alias="fields")
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SendFormRequest(BaseModel):
    employeeIds: List[int]


class PublicFormResponse(BaseModel):
    formName: str
    employeeName: str
    fields: List[FormFieldConfig]
    currentValues: dict
    status: str


class PublicFormSubmitRequest(BaseModel):
    values: dict


class SubmissionResponse(BaseModel):
    id: int
    employeeId: int
    employeeName: str
    formName: str
    fields: List[FormFieldConfig]
    submittedData: dict
    currentValues: dict
    status: str
    createdAt: Optional[datetime] = None


class SubmissionReviewRequest(BaseModel):
    notes: Optional[str] = None
