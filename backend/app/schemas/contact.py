from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import Platform


class ContactIdentityCreate(BaseModel):
    platform: Platform
    external_user_id: str


class ContactIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int
    platform: Platform
    external_user_id: str
    created_at: datetime


class ContactCreate(BaseModel):
    name: str
    company_id: int | None = None
    role: str | None = None
    notes: str | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company_id: int | None
    role: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
