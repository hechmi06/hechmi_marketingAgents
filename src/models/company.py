from pydantic import BaseModel, Field
from typing import Optional, List


class Company(BaseModel):
    name: str
    website: Optional[str] = None
    country: Optional[str] = None
    tier: Optional[int] = None
    description: Optional[str] = None

    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    linkedin: Optional[str] = None
    contact_name: Optional[str] = None

    services: Optional[List[str]] = None
    certifications: Optional[List[str]] = None

    source: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)