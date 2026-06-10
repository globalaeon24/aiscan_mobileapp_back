import hashlib
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
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from mobile_models import MobileUser, QrLoginEvent, QrLoginSession
from services.oysyn_core_client import oysyn_core_client

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM") or os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
QR_LOGIN_EXPIRE_SECONDS = int(os.getenv("QR_LOGIN_EXPIRE_SECONDS", "120"))

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


class QrLoginCreateRequest(BaseModel):
    web_session_id: Optional[str] = None


class QrLoginCreateResponse(BaseModel):
    qr_token: str
    status: str
    expires_at: datetime


class QrLoginStatusResponse(BaseModel):
    status: str
    expires_at: datetime
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None


class QrLoginActionRequest(BaseModel):
    device_id: Optional[str] = None


class QrLoginActionResponse(BaseModel):
    status: str


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


def _mark_expired_if_needed(
    db: Session,
    session: QrLoginSession,
    request: Request,
) -> bool:
    if session.status != "pending" or _as_utc(session.expires_at) > _now():
        return False

    session.status = "expired"
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="expired",
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.commit()
    db.refresh(session)
    return True


def _get_qr_session_or_404(db: Session, qr_token: str) -> QrLoginSession:
    session = _find_qr_session(db, qr_token)
    if not session:
        raise HTTPException(status_code=404, detail="QR session not found")
    return session


def _find_qr_session(db: Session, qr_token: str) -> Optional[QrLoginSession]:
    qr_token_hash = _hash_token(qr_token)
    return (
        db.query(QrLoginSession)
        .filter(QrLoginSession.qr_token_hash == qr_token_hash)
        .first()
    )


def _get_or_create_mobile_user(db: Session, core_user_id: int) -> MobileUser:
    core_user_id_value = str(core_user_id)
    mobile_user = (
        db.query(MobileUser)
        .filter(MobileUser.core_user_id == core_user_id_value)
        .first()
    )
    if mobile_user:
        return mobile_user

    mobile_user = MobileUser(
        core_user_id=core_user_id_value,
        status="active",
        last_synced_at=_now(),
    )
    db.add(mobile_user)
    db.flush()
    return mobile_user


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


@router.post("/qr-login/sessions", response_model=QrLoginCreateResponse)
def create_qr_login_session(
    request: Request,
    data: Optional[QrLoginCreateRequest] = None,
    db: Session = Depends(get_db),
) -> QrLoginCreateResponse:
    data = data or QrLoginCreateRequest()
    qr_token = secrets.token_urlsafe(48)
    expires_at = _now() + timedelta(seconds=QR_LOGIN_EXPIRE_SECONDS)
    session = QrLoginSession(
        qr_token_hash=_hash_token(qr_token),
        status="pending",
        web_session_id=data.web_session_id,
        requested_ip=_client_ip(request),
        requested_user_agent=_user_agent(request),
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="created",
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            metadata_json={"web_session_id": data.web_session_id},
        )
    )
    db.commit()
    db.refresh(session)
    return QrLoginCreateResponse(
        qr_token=qr_token,
        status=session.status,
        expires_at=session.expires_at,
    )


@router.get("/qr-login/sessions/{qr_token}/status", response_model=QrLoginStatusResponse)
def get_qr_login_status(
    qr_token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> QrLoginStatusResponse:
    session = _get_qr_session_or_404(db, qr_token)
    _mark_expired_if_needed(db, session, request)
    return QrLoginStatusResponse(
        status=session.status,
        expires_at=session.expires_at,
        approved_at=session.approved_at,
        rejected_at=session.rejected_at,
        consumed_at=session.consumed_at,
    )


@router.post(
    "/qr-login/sessions/{qr_token}/approve",
    response_model=QrLoginActionResponse,
)
def approve_qr_login_session(
    qr_token: str,
    request: Request,
    data: Optional[QrLoginActionRequest] = None,
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
) -> QrLoginActionResponse:
    data = data or QrLoginActionRequest()
    session = _find_qr_session(db, qr_token)
    if not session:
        core_response = oysyn_core_client.confirm_qr(user_id, qr_token)
        if isinstance(core_response, dict):
            return QrLoginActionResponse(
                status=core_response.get("status", "confirmed")
            )
        return QrLoginActionResponse(status="confirmed")

    if _mark_expired_if_needed(db, session, request):
        raise HTTPException(status_code=410, detail="QR session expired")
    if session.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"QR session is already {session.status}",
        )

    mobile_user = _get_or_create_mobile_user(db, user_id)
    session.status = "approved"
    session.approved_by_mobile_user_id = mobile_user.id
    session.approved_device_id = data.device_id
    session.approved_at = _now()
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="scanned",
            mobile_user_id=mobile_user.id,
            device_id=data.device_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="approved",
            mobile_user_id=mobile_user.id,
            device_id=data.device_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.commit()
    db.refresh(session)
    return QrLoginActionResponse(status=session.status)


@router.post(
    "/qr-login/sessions/{qr_token}/reject",
    response_model=QrLoginActionResponse,
)
def reject_qr_login_session(
    qr_token: str,
    request: Request,
    data: Optional[QrLoginActionRequest] = None,
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
) -> QrLoginActionResponse:
    data = data or QrLoginActionRequest()
    session = _find_qr_session(db, qr_token)
    if not session:
        return QrLoginActionResponse(status="rejected")

    if _mark_expired_if_needed(db, session, request):
        raise HTTPException(status_code=410, detail="QR session expired")
    if session.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"QR session is already {session.status}",
        )

    mobile_user = _get_or_create_mobile_user(db, user_id)
    session.status = "rejected"
    session.rejected_at = _now()
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="scanned",
            mobile_user_id=mobile_user.id,
            device_id=data.device_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="rejected",
            mobile_user_id=mobile_user.id,
            device_id=data.device_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.commit()
    db.refresh(session)
    return QrLoginActionResponse(status=session.status)


@router.post(
    "/qr-login/sessions/{qr_token}/consume",
    response_model=QrLoginStatusResponse,
)
def consume_qr_login_session(
    qr_token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> QrLoginStatusResponse:
    session = _get_qr_session_or_404(db, qr_token)
    if _mark_expired_if_needed(db, session, request):
        raise HTTPException(status_code=410, detail="QR session expired")
    if session.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"QR session is {session.status}",
        )

    session.status = "consumed"
    session.consumed_at = _now()
    db.add(
        QrLoginEvent(
            qr_login_session_id=session.id,
            event_type="consumed",
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    )
    db.commit()
    db.refresh(session)
    return QrLoginStatusResponse(
        status=session.status,
        expires_at=session.expires_at,
        approved_at=session.approved_at,
        rejected_at=session.rejected_at,
        consumed_at=session.consumed_at,
    )


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
