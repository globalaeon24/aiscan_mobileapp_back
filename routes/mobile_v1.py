import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from services.oysyn_core_client import oysyn_core_client

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM") or os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

ALLOWED_REPORT_TYPES = {
    "full_report",
    "short_report",
    "certificate",
    "ai_certificate",
}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_id: Optional[str] = None
    platform: Optional[str] = None
    device_name: Optional[str] = None
    device_model: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    push_token: Optional[str] = None
    push_provider: Optional[str] = None


class MobileToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _ensure_secret_key() -> str:
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SECRET_KEY is not set or too short",
        )
    return SECRET_KEY


def create_mobile_access_token(user_id: int) -> str:
    secret_key = _ensure_secret_key()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "scope": "mobile",
        "jti": secrets.token_urlsafe(24),
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def get_mobile_user_id(token: Optional[str] = Depends(oauth2_scheme)) -> int:
    if not token:
        raise _credentials_exception()

    try:
        payload = jwt.decode(token, _ensure_secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise _credentials_exception()
        return int(user_id)
    except (JWTError, ValueError):
        raise _credentials_exception()


@router.post("/auth/login", response_model=MobileToken)
def login(data: LoginRequest) -> MobileToken:
    core_response = oysyn_core_client.login(data.email, data.password)
    user = core_response.get("user") if isinstance(core_response, dict) else None

    if not user or not user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Oysyn Core API returned login response without user id",
        )

    access_token = create_mobile_access_token(int(user["id"]))
    refresh_token = secrets.token_urlsafe(48)

    return MobileToken(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user,
    )


@router.get("/auth/verify")
def verify(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.verify(user_id)


@router.get("/me")
def get_me(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_me(user_id)


@router.get("/organizations/{organization_id}")
def get_organization(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization(user_id, organization_id)


@router.get("/checks")
def get_checks(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_mobile_user_id),
):
    params = {"page": page, "page_size": page_size}
    if status_filter:
        params["status"] = status_filter
    return oysyn_core_client.get_checks(user_id, params)


@router.post("/checks", status_code=status.HTTP_201_CREATED)
async def create_check(
    title: str = Form(...),
    document: UploadFile = File(...),
    author: Optional[str] = Form(default=None),
    department: Optional[str] = Form(default=None),
    document_type: Optional[str] = Form(default=None),
    include_ocr: bool = Form(default=False),
    ocr_languages: str = Form(default="rus"),
    ai_check: bool = Form(default=True),
    user_id: int = Depends(get_mobile_user_id),
):
    form = {
        "title": title,
        "include_ocr": str(include_ocr).lower(),
        "ocr_languages": ocr_languages,
        "ai_check": str(ai_check).lower(),
    }
    optional_values = {
        "author": author,
        "department": department,
        "document_type": document_type,
    }
    form.update({key: value for key, value in optional_values.items() if value})

    return await oysyn_core_client.create_check(
        user_id,
        document=document,
        form=form,
    )


@router.get("/checks/{check_id}")
def get_check(check_id: int, user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_check(user_id, check_id)


@router.get("/checks/{check_id}/report")
def get_report(check_id: int, user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_report(user_id, check_id)


@router.get("/checks/{check_id}/report/pdf/{report_type}")
def get_report_pdf(
    check_id: int,
    report_type: str,
    lang: str = Query(default="ru", pattern="^(kk|ru|en)$"),
    download: Optional[int] = Query(default=None),
    user_id: int = Depends(get_mobile_user_id),
):
    if report_type not in ALLOWED_REPORT_TYPES:
        raise HTTPException(status_code=404, detail="Тип отчета не найден")

    params = {"lang": lang}
    if download is not None:
        params["download"] = download

    upstream_response = oysyn_core_client.get_report_pdf(
        user_id,
        check_id,
        report_type,
        params,
    )

    headers = {}
    content_disposition = upstream_response.headers.get("content-disposition")
    if content_disposition:
        headers["Content-Disposition"] = content_disposition

    return Response(
        content=upstream_response.content,
        media_type=upstream_response.headers.get(
            "content-type",
            "application/pdf",
        ),
        headers=headers,
    )
