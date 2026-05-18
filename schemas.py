from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List

# ================= AUTH =================

class UserBase(BaseModel):
    email: EmailStr
    name: str
    organization_name: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(min_length=6)
    agree_privacy: bool


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    organization_name: Optional[str] = None
    agreed_privacy: bool
    agreed_at: Optional[datetime]

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None

# ================= SCAN =================

class ScanCreate(BaseModel):
    scanned_text: str


class AiFragment(BaseModel):
    start: int
    end: int
    text: Optional[str] = None
    confidence: Optional[float] = 1.0


class ScanShort(BaseModel):
    id: int
    ai_percentage: float
    created_at: datetime

    user_scan_index: Optional[int] = None
    file_name: Optional[str] = None

    class Config:
        from_attributes = True


class ScanDetail(BaseModel):
    id: int
    ai_percentage: float
    scanned_text: str
    highlighted_text: Optional[str]
    ai_fragments: Optional[List[AiFragment]]  # 🔥 ВАЖНО
    created_at: datetime

    user_scan_index: Optional[int] = None
    file_name: Optional[str] = None
    author_name: Optional[str] = None

    class Config:
        from_attributes = True


class ScanHistory(BaseModel):
    items: List[ScanShort]