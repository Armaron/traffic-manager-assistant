from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import CompanyType


class CompanyCreate(BaseModel):
    name: str
    company_type: CompanyType
    notes: str | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company_type: CompanyType
    notes: str | None
    created_at: datetime
    updated_at: datetime
