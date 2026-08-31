import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from database import get_db
from mobile_models import (
    LinkedDeviceSession,
    MobileDevice,
    MobileSession,
    MobileUser,
    QrLoginEvent,
    QrLoginSession,
)
from services.oysyn_core_client import oysyn_core_client

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM") or os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
QR_LOGIN_EXPIRE_SECONDS = int(os.getenv("QR_LOGIN_EXPIRE_SECONDS", "120"))

ALLOWED_REPORT_TYPES = {
    "full_report",
    "short_report",
    "certificate",
    "ai_certificate",
}


class LoginRequest(BaseModel):
    email: str
    password: str
    device_id: Optional[str] = None
    platform: Optional[str] = None
    device_name: Optional[str] = None
    device_model: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    push_token: Optional[str] = None
    push_provider: Optional[str] = None

    @field_validator("email", "password")
    @classmethod
    def validate_credentials(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле обязательно")
        return value


class MobileToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class OrganizationUserPayload(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class OrganizationBillingPayload(BaseModel):
    checks_available: int


class ProfileUpdatePayload(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: Optional[str] = None
    city: Optional[str] = None

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


def create_mobile_access_token(
    user_id: int,
    session_id: Optional[int] = None,
    jti: Optional[str] = None,
) -> str:
    secret_key = _ensure_secret_key()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "scope": "mobile",
        "jti": jti or secrets.token_urlsafe(24),
    }
    if session_id is not None:
        payload["sid"] = session_id
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


def _sync_mobile_user_snapshot(
    mobile_user: MobileUser,
    user: Dict[str, Any],
) -> None:
    mobile_user.email = user.get("email") or mobile_user.email
    mobile_user.full_name = user.get("full_name") or mobile_user.full_name
    organization_id = user.get("organization_id") or user.get("core_organization_id")
    if organization_id is not None:
        mobile_user.core_organization_id = str(organization_id)
    if user.get("role") is not None:
        mobile_user.role_snapshot = {"role": user.get("role")}
    mobile_user.last_synced_at = _now()


def _extract_session_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("items", "results", "data", "sessions", "devices"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return []


def _first_text(item: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _parse_user_agent(user_agent: Optional[str]) -> Dict[str, Optional[str]]:
    if not user_agent:
        return {
            "browser": None,
            "browser_version": None,
            "platform": None,
            "os_version": None,
            "device_type": None,
        }

    browser_patterns = [
        ("Microsoft Edge", r"(?:Edg|Edge)/([\d.]+)"),
        ("Chrome", r"Chrome/([\d.]+)"),
        ("Firefox", r"Firefox/([\d.]+)"),
        ("Safari", r"Version/([\d.]+).*Safari/"),
    ]
    browser = None
    browser_version = None
    for name, pattern in browser_patterns:
        match = re.search(pattern, user_agent)
        if match:
            browser = name
            browser_version = match.group(1)
            break

    platform = None
    os_version = None
    device_type = "desktop"

    if "Android" in user_agent:
        device_type = "mobile"
        platform = "Android"
        match = re.search(r"Android ([\d.]+)", user_agent)
        os_version = match.group(1) if match else None
    elif "iPhone" in user_agent:
        device_type = "mobile"
        platform = "iPhone"
        match = re.search(r"OS ([\d_]+)", user_agent)
        os_version = match.group(1).replace("_", ".") if match else None
    elif "iPad" in user_agent:
        device_type = "tablet"
        platform = "iPad"
        match = re.search(r"OS ([\d_]+)", user_agent)
        os_version = match.group(1).replace("_", ".") if match else None
    elif "Mac OS X" in user_agent:
        platform = "macOS"
        match = re.search(r"Mac OS X ([\d_]+)", user_agent)
        os_version = match.group(1).replace("_", ".") if match else None
    elif "Windows NT" in user_agent:
        platform = "Windows"
        match = re.search(r"Windows NT ([\d.]+)", user_agent)
        os_version = match.group(1) if match else None
    elif "Linux" in user_agent:
        platform = "Linux"

    return {
        "browser": browser,
        "browser_version": browser_version,
        "platform": platform,
        "os_version": os_version,
        "device_type": device_type,
    }


def _normalize_linked_device_session(item: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _first_text(item, "id", "pk", "session_id", "sessionId")
    if not session_id:
        session_id = _hash_token(repr(sorted(item.items())))[:24]

    user_agent = _first_text(item, "user_agent", "userAgent", "ua")
    parsed_agent = _parse_user_agent(user_agent)
    device_name = _first_text(
        item,
        "device_name",
        "device",
        "user_agent_device",
        "browser",
    )
    browser = (
        _first_text(item, "browser", "browser_name", "client")
        or parsed_agent["browser"]
    )
    browser_version = _first_text(item, "browser_version") or parsed_agent[
        "browser_version"
    ]
    platform = _first_text(item, "platform", "os", "os_name") or parsed_agent[
        "platform"
    ]
    os_version = _first_text(item, "os_version") or parsed_agent["os_version"]
    device_type = _first_text(item, "device_type") or parsed_agent["device_type"]
    location = _first_text(item, "location", "city", "country")
    ip_address = _first_text(item, "ip_address", "ip", "last_ip")
    status_value = _first_text(item, "status") or "active"
    revoked_at = _first_text(item, "revoked_at", "ended_at", "logout_at")
    is_active = item.get("is_active")
    status_text = status_value.lower()
    if is_active is False or revoked_at:
        status_text = "revoked"

    first_seen = _first_text(
        item,
        "created_at",
        "login_at",
        "started_at",
        "first_seen_at",
    )
    last_active = _first_text(
        item,
        "last_active_at",
        "last_activity",
        "updated_at",
        "last_seen_at",
    )

    return {
        "id": int(session_id) if str(session_id).isdigit() else session_id,
        "core_session_id": str(session_id),
        "device_name": device_name or browser or "Веб-браузер",
        "browser": browser,
        "browser_version": browser_version,
        "platform": platform,
        "os_version": os_version,
        "device_type": device_type,
        "location": location,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "status": status_text,
        "first_seen_at": first_seen,
        "last_active_at": last_active,
        "revoked_at": revoked_at,
        "raw": item,
    }


def _cache_linked_device_sessions(
    db: Session,
    mobile_user_id: int,
    sessions: List[Dict[str, Any]],
) -> None:
    for item in sessions:
        session = (
            db.query(LinkedDeviceSession)
            .filter(
                LinkedDeviceSession.mobile_user_id == mobile_user_id,
                LinkedDeviceSession.core_session_id == item["core_session_id"],
            )
            .first()
        )
        if not session:
            session = LinkedDeviceSession(
                mobile_user_id=mobile_user_id,
                core_session_id=item["core_session_id"],
            )

        session.device_name = item.get("device_name")
        session.browser = item.get("browser")
        session.browser_version = item.get("browser_version")
        session.platform = item.get("platform")
        session.os_version = item.get("os_version")
        session.device_type = item.get("device_type")
        session.location = item.get("location")
        session.ip_address = item.get("ip_address")
        session.user_agent = item.get("user_agent")
        session.status = item.get("status") or "active"
        session.first_seen_at = _parse_datetime(item.get("first_seen_at"))
        session.last_active_at = _parse_datetime(item.get("last_active_at"))
        session.revoked_at = _parse_datetime(item.get("revoked_at"))
        session.raw_payload = item.get("raw")
        db.add(session)
    db.commit()


def _mobile_session_payload(
    session: MobileSession,
    device: Optional[MobileDevice],
) -> Dict[str, Any]:
    platform = (device.platform if device else None) or "mobile"
    device_type = "tablet" if platform.lower() in {"ipad", "tablet"} else "mobile"
    status_text = session.status
    if status_text == "active" and _as_utc(session.expires_at) <= _now():
        status_text = "expired"

    return {
        "id": -int(session.id),
        "mobile_session_id": int(session.id),
        "device_name": (
            (device.device_name if device else None)
            or (device.device_model if device else None)
            or "Мобильное устройство"
        ),
        "browser": "OySyn",
        "browser_version": device.app_version if device else None,
        "platform": platform,
        "os_version": device.os_version if device else None,
        "device_type": device_type,
        "location": None,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "status": status_text,
        "first_seen_at": session.created_at,
        "last_active_at": session.last_used_at,
        "revoked_at": session.revoked_at,
        "source": "mobile",
    }


def get_mobile_user_id(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> int:
    if not token:
        raise _credentials_exception()

    try:
        payload = jwt.decode(token, _ensure_secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise _credentials_exception()
        session_id = payload.get("sid")
        if session_id is not None:
            mobile_user = (
                db.query(MobileUser)
                .filter(MobileUser.core_user_id == str(user_id))
                .first()
            )
            session = (
                db.query(MobileSession)
                .filter(
                    MobileSession.id == int(session_id),
                    MobileSession.mobile_user_id == mobile_user.id,
                )
                .first()
                if mobile_user
                else None
            )
            if (
                not session
                or session.status != "active"
                or session.revoked_at is not None
                or _as_utc(session.expires_at) <= _now()
            ):
                raise _credentials_exception()
            session.last_used_at = _now()
            db.commit()
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
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileToken:
    core_response = oysyn_core_client.login(data.email, data.password)
    user = core_response.get("user") if isinstance(core_response, dict) else None

    if not user or not user.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Oysyn Core API returned login response without user id",
        )

    refresh_token = secrets.token_urlsafe(48)
    mobile_user = _get_or_create_mobile_user(db, int(user["id"]))
    _sync_mobile_user_snapshot(mobile_user, user)
    device_id = data.device_id or f"mobile:{secrets.token_urlsafe(12)}"
    device = (
        db.query(MobileDevice)
        .filter(
            MobileDevice.mobile_user_id == mobile_user.id,
            MobileDevice.device_id == device_id,
        )
        .first()
    )
    if not device:
        device = MobileDevice(
            mobile_user_id=mobile_user.id,
            device_id=device_id,
            platform=data.platform or "mobile",
        )
    device.platform = data.platform or device.platform or "mobile"
    device.device_name = data.device_name or device.device_name
    device.device_model = data.device_model or device.device_model
    device.os_version = data.os_version or device.os_version
    device.app_version = data.app_version or device.app_version
    device.push_token = data.push_token or device.push_token
    device.push_provider = data.push_provider or device.push_provider
    device.is_active = True
    device.last_seen_at = _now()
    device.revoked_at = None
    db.add(device)

    access_token_jti = secrets.token_urlsafe(24)
    mobile_session = MobileSession(
        mobile_user_id=mobile_user.id,
        device_id=device_id,
        access_token_jti=access_token_jti,
        refresh_token_hash=_hash_token(refresh_token),
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        status="active",
        last_used_at=_now(),
        expires_at=_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(mobile_session)
    db.flush()
    access_token = create_mobile_access_token(
        int(user["id"]),
        session_id=mobile_session.id,
        jti=access_token_jti,
    )
    db.commit()

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


@router.patch("/me")
def update_me(
    payload: ProfileUpdatePayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.update_me(
        user_id,
        payload.model_dump(exclude_none=True),
    )

@router.get("/sessions/devices")
def get_linked_device_sessions(
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    mobile_user = _get_or_create_mobile_user(db, user_id)
    try:
        core_response = oysyn_core_client.get_user_sessions(user_id)
        core_sessions = [
            _normalize_linked_device_session(item)
            for item in _extract_session_items(core_response)
        ]
        _cache_linked_device_sessions(db, mobile_user.id, core_sessions)
    except HTTPException:
        core_sessions = []

    devices = {
        device.device_id: device
        for device in db.query(MobileDevice)
        .filter(MobileDevice.mobile_user_id == mobile_user.id)
        .all()
    }
    mobile_sessions = [
        _mobile_session_payload(session, devices.get(session.device_id))
        for session in db.query(MobileSession)
        .filter(MobileSession.mobile_user_id == mobile_user.id)
        .order_by(MobileSession.created_at.desc())
        .all()
    ]
    return {"items": mobile_sessions + core_sessions}


@router.post("/sessions/devices/{session_id}/revoke")
def revoke_linked_device_session(
    session_id: int,
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    mobile_user = _get_or_create_mobile_user(db, user_id)
    if session_id < 0:
        mobile_session = (
            db.query(MobileSession)
            .filter(
                MobileSession.id == -session_id,
                MobileSession.mobile_user_id == mobile_user.id,
            )
            .first()
        )
        if not mobile_session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        mobile_session.status = "revoked"
        mobile_session.revoked_at = _now()
        mobile_session.revoked_by_user_id = mobile_user.id
        mobile_session.revocation_reason = "Revoked by user"
        device = (
            db.query(MobileDevice)
            .filter(
                MobileDevice.mobile_user_id == mobile_user.id,
                MobileDevice.device_id == mobile_session.device_id,
            )
            .first()
        )
        if device:
            device.is_active = False
            device.revoked_at = _now()
        db.commit()
        return {"status": "revoked", "session_id": session_id, "source": "mobile"}

    core_response = oysyn_core_client.revoke_user_session(user_id, session_id)
    session = (
        db.query(LinkedDeviceSession)
        .filter(
            LinkedDeviceSession.mobile_user_id == mobile_user.id,
            LinkedDeviceSession.core_session_id == str(session_id),
        )
        .first()
    )
    if session:
        session.status = "revoked"
        session.revoked_at = _now()
        db.add(session)
        db.commit()

    return {
        "status": "revoked",
        "session_id": session_id,
        "core": core_response if isinstance(core_response, dict) else None,
    }


@router.get("/organizations/{organization_id}")
def get_organization(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization(user_id, organization_id)


@router.get("/organizations")
def get_organizations(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_organizations(user_id)


@router.get("/organizations/{organization_id}/users")
def get_organization_users(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_users(user_id, organization_id)


@router.post("/organizations/{organization_id}/users", status_code=201)
def create_organization_user(
    organization_id: int,
    payload: OrganizationUserPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.create_organization_user(
        user_id,
        organization_id,
        payload.model_dump(exclude_none=True),
    )


@router.patch("/organizations/{organization_id}/users/{target_user_id}")
def update_organization_user(
    organization_id: int,
    target_user_id: int,
    payload: OrganizationUserPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.update_organization_user(
        user_id,
        organization_id,
        target_user_id,
        payload.model_dump(exclude_none=True),
    )


@router.get("/organizations/{organization_id}/api-settings")
def get_organization_api_settings(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_api_settings(
        user_id, organization_id
    )


@router.get("/organizations/{organization_id}/billing")
def get_organization_billing(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_billing(user_id, organization_id)


@router.patch("/organizations/{organization_id}/billing/{target_user_id}")
def update_organization_billing(
    organization_id: int,
    target_user_id: int,
    payload: OrganizationBillingPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.update_organization_billing(
        user_id,
        organization_id,
        target_user_id,
        payload.model_dump(),
    )


@router.get("/organizations/{organization_id}/billing-journal")
def get_organization_billing_journal(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_billing_journal(
        user_id, organization_id
    )


@router.get("/organizations/{organization_id}/reports")
def get_organization_reports(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_reports(user_id, organization_id)


@router.get("/checks")
def get_checks(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    folder_id: Optional[int] = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_mobile_user_id),
):
    params = {"page": page, "page_size": page_size}
    if status_filter:
        params["status"] = status_filter
    if folder_id is not None:
        params["folder_id"] = folder_id
    return oysyn_core_client.get_checks(user_id, params)


@router.get("/folders")
def get_folders(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_folders(user_id)


@router.get("/checks/modules")
def get_check_modules(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_check_modules(user_id)


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
    modules: Optional[str] = Form(default=None),
    modules_kz: Optional[str] = Form(default=None),
    user_id: int = Depends(get_mobile_user_id),
):
    user = oysyn_core_client.get_me(user_id)
    try:
        checks_available = int(user.get("checks_available", 0))
    except (TypeError, ValueError, AttributeError):
        checks_available = 0
    if checks_available <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Лимит проверок исчерпан. "
                "Обратитесь к администратору организации."
            ),
        )

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
        "modules": modules,
        "modules_kz": modules_kz,
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
