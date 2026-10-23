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
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from mobile_models import (
    LinkedDeviceSession,
    MobileCheckRequest,
    MobileSession,
    MobileUser,
    Notification,
    PushToken,
    QrLoginEvent,
    QrLoginSession,
    RegistrationConsent,
)
from services.oysyn_core_client import oysyn_core_client
from services.push_service import deliver_notification

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


@router.get("/app/version")
def get_app_version(
    platform: str = Query(pattern="^(android|ios)$"),
):
    prefix = "ANDROID" if platform == "android" else "IOS"
    default_store_url = (
        "https://play.google.com/store/apps/details?id=asia.oysyn.mobile"
        if platform == "android"
        else "https://apps.apple.com/kz/app/oysyn/id6810601982"
    )
    latest_version = os.getenv(f"APP_UPDATE_{prefix}_LATEST_VERSION", "1.0.8")
    latest_build = int(os.getenv(f"APP_UPDATE_{prefix}_LATEST_BUILD", "14"))
    minimum_supported_build = int(
        os.getenv(f"APP_UPDATE_{prefix}_MINIMUM_SUPPORTED_BUILD", "0")
    )
    update_required = os.getenv(
        f"APP_UPDATE_{prefix}_REQUIRED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    remind_after_hours = max(
        1,
        int(os.getenv("APP_UPDATE_REMIND_AFTER_HOURS", "24")),
    )
    store_url = os.getenv(f"APP_UPDATE_{prefix}_STORE_URL", default_store_url)
    return {
        "enabled": bool(store_url),
        "latest_version": latest_version,
        "latest_build": latest_build,
        "minimum_supported_build": minimum_supported_build,
        "update_required": update_required,
        "remind_after_hours": remind_after_hours,
        "title": os.getenv("APP_UPDATE_TITLE", "Доступна новая версия OySyn"),
        "message": os.getenv(
            "APP_UPDATE_MESSAGE",
            "Мы улучшили стабильность приложения и работу с документами.",
        ),
        "store_url": store_url,
    }


def _truncate_optional(value: Optional[str], max_length: int) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:max_length] or None


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

    @field_validator("device_id", "device_name", "device_model")
    @classmethod
    def normalize_device_text(cls, value: Optional[str]) -> Optional[str]:
        return _truncate_optional(value, 255)

    @field_validator("platform", "push_provider")
    @classmethod
    def normalize_platform_text(cls, value: Optional[str]) -> Optional[str]:
        return _truncate_optional(value, 32)

    @field_validator("os_version", "app_version")
    @classmethod
    def normalize_version_text(cls, value: Optional[str]) -> Optional[str]:
        return _truncate_optional(value, 64)


class RegistrationRequest(BaseModel):
    email: str
    password: str
    password_confirmation: str
    agreement_accepted: bool
    agreement_version: str
    agreement_url: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("Введите корректный email")
        return normalized

    @field_validator("password", "password_confirmation")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Пароль должен содержать не менее 8 символов")
        return value

    @field_validator("agreement_version")
    @classmethod
    def validate_agreement_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("Некорректная версия соглашения")
        return normalized

    @field_validator("agreement_url")
    @classmethod
    def validate_agreement_url(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != "https://oysyn.asia/ru/policy/":
            raise ValueError("Некорректная ссылка на соглашение")
        return normalized


class MobileToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def validate_refresh_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле обязательно")
        return value


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


class OrganizationUpdatePayload(BaseModel):
    title: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    @field_validator("title", "city", "address", "description")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class OrganizationApiTokenPayload(BaseModel):
    name: str
    user_id: int
    use_organization_balance: bool = False
    api_checks_available: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Наименование обязательно")
        return value


class FolderPayload(BaseModel):
    name: str
    parent_folder: Optional[int] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите название папки")
        if len(value) > 512:
            raise ValueError("Название папки не должно превышать 512 символов")
        return value


class CheckFolderPayload(BaseModel):
    folder_id: Optional[int] = None


class ProfileUpdatePayload(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    phone_number: Optional[str] = None
    city: Optional[str] = None
    notification: Optional[bool] = None


class PushTokenPayload(BaseModel):
    device_id: str
    token: str
    platform: str
    provider: str = "fcm"

    @field_validator("device_id", "token", "platform", "provider")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Поле обязательно")
        return normalized


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


def create_mobile_access_token(user_id: int, jti: Optional[str] = None) -> str:
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
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _notification_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _check_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "data"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _sync_check_notifications(
    db: Session,
    mobile_user: MobileUser,
    core_user_id: int,
) -> None:
    checks = _check_items(
        oysyn_core_client.get_checks(
            core_user_id,
            {"page": 1, "page_size": 50},
        )
    )
    recent_notifications = (
        db.query(Notification)
        .filter(
            Notification.mobile_user_id == mobile_user.id,
            Notification.notification_type.in_((
                "check_completed",
                "check_failed",
            )),
        )
        .order_by(Notification.created_at.desc())
        .limit(200)
        .all()
    )
    existing_check_ids = {
        str((item.payload or {}).get("check_id"))
        for item in recent_notifications
        if (item.payload or {}).get("check_id") is not None
    }
    changed = False
    for check in checks:
        check_id = check.get("id")
        check_status = str(check.get("status") or "").upper()
        if check_id is None or check_status not in {"CH", "FA"}:
            continue
        if str(check_id) in existing_check_ids:
            continue
        _create_check_notification(db, mobile_user.id, check)
        existing_check_ids.add(str(check_id))
        changed = True
    if changed:
        db.commit()


def _serialize_notification(item: Notification) -> Dict[str, Any]:
    return {
        "id": int(item.id),
        "type": item.notification_type,
        "title": item.title,
        "body": item.body,
        "payload": item.payload or {},
        "status": item.status,
        "priority": item.priority,
        "created_at": item.created_at,
        "read_at": item.read_at,
        "is_read": item.read_at is not None,
    }


def _create_check_notification(
    db: Session,
    mobile_user_id: int,
    check: Dict[str, Any],
) -> Notification:
    check_id = int(check["id"])
    check_status = str(check.get("status") or "").upper()
    title = str(
        check.get("title") or check.get("file_name") or "Документ"
    ).strip()
    failed = check_status == "FA"
    notification = Notification(
        mobile_user_id=mobile_user_id,
        notification_type="check_failed" if failed else "check_completed",
        title=(
            "Проверка завершилась с ошибкой"
            if failed
            else "Проверка завершена"
        ),
        body=title,
        payload={
            "check_id": check_id,
            "check_status": check_status,
            "check": check,
            "route": f"/checks/{check_id}",
        },
        status="created",
        priority="normal",
    )
    created_at = _notification_datetime(check.get("created_at"))
    if created_at is not None:
        notification.created_at = created_at
    db.add(notification)
    db.flush()
    deliver_notification(db, notification)
    return notification


def reconcile_pending_check_notifications() -> int:
    """Poll Core for checks submitted through this gateway."""
    db = SessionLocal()
    completed = 0
    try:
        pending = (
            db.query(MobileCheckRequest)
            .filter(
                MobileCheckRequest.status.in_((
                    "submitted",
                    "processing",
                )),
                MobileCheckRequest.core_check_id.isnot(None),
            )
            .order_by(MobileCheckRequest.created_at.asc())
            .limit(100)
            .all()
        )
        for request_item in pending:
            try:
                core_user_id = int(request_item.core_user_id)
                check_id = int(request_item.core_check_id)
                check = oysyn_core_client.get_check(core_user_id, check_id)
            except Exception:
                continue
            if not isinstance(check, dict):
                continue
            check_status = str(check.get("status") or "").upper()
            if check_status not in {"CH", "FA"}:
                request_item.status = "processing"
                continue
            existing = (
                db.query(Notification)
                .filter(
                    Notification.mobile_user_id == request_item.mobile_user_id,
                    Notification.payload["check_id"].astext == str(check_id),
                )
                .first()
            )
            if existing is None:
                _create_check_notification(
                    db,
                    request_item.mobile_user_id,
                    check,
                )
            request_item.status = "failed" if check_status == "FA" else "completed"
            if check_status == "FA":
                request_item.failed_at = _now()
                request_item.error_message = str(
                    check.get("status_display") or "Проверка завершилась с ошибкой"
                )
            else:
                request_item.completed_at = _now()
            completed += 1
        db.commit()
        return completed
    finally:
        db.close()


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


def get_mobile_user_id(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> int:
    if not token:
        raise _credentials_exception()

    try:
        payload = jwt.decode(token, _ensure_secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id:
            raise _credentials_exception()
        core_user_id = int(user_id)
        mobile_user = (
            db.query(MobileUser)
            .filter(MobileUser.core_user_id == str(core_user_id))
            .first()
        )
        if mobile_user and jti:
            jti_sessions = (
                db.query(MobileSession)
                .filter(
                    MobileSession.mobile_user_id == mobile_user.id,
                    MobileSession.access_token_jti.isnot(None),
                )
                .all()
            )
            if jti_sessions:
                session = next(
                    (item for item in jti_sessions if item.access_token_jti == jti),
                    None,
                )
                if (
                    session is None
                    or session.status != "active"
                    or session.revoked_at is not None
                    or _as_utc(session.expires_at) <= _now()
                ):
                    raise _credentials_exception()
        return core_user_id
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

    access_token_jti = secrets.token_urlsafe(24)
    access_token = create_mobile_access_token(
        int(user["id"]),
        jti=access_token_jti,
    )
    refresh_token = secrets.token_urlsafe(48)
    mobile_user = _get_or_create_mobile_user(db, int(user["id"]))
    _sync_mobile_user_snapshot(mobile_user, user)

    mobile_session = MobileSession(
        mobile_user_id=mobile_user.id,
        device_id=data.device_id or f"mobile:{secrets.token_urlsafe(12)}",
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
    platform = (data.platform or "").lower()
    device_type = (
        "tablet" if platform in {"ipad", "tablet"}
        else "mobile" if platform in {"android", "ios"}
        else "desktop"
    )
    db.add(
        LinkedDeviceSession(
            mobile_user_id=mobile_user.id,
            core_session_id=f"mobile:{mobile_session.id}",
            device_name=data.device_name or "Мобильное приложение OySyn",
            platform=data.platform,
            os_version=data.os_version,
            device_type=device_type,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            status="active",
            first_seen_at=_now(),
            last_active_at=_now(),
            raw_payload={
                "device_model": data.device_model,
                "app_version": data.app_version,
                "source": "mobile",
            },
        )
    )
    db.commit()

    return MobileToken(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user,
    )


@router.post("/auth/register")
def register(
    data: RegistrationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if data.password != data.password_confirmation:
        raise HTTPException(status_code=422, detail="Пароли не совпадают")
    if not data.agreement_accepted:
        raise HTTPException(
            status_code=422,
            detail="Необходимо принять Пользовательское соглашение",
        )

    core_status, core_payload = oysyn_core_client.register(
        data.email,
        data.password,
    )
    if not isinstance(core_payload, dict):
        core_payload = {
            "code": "registration_unavailable",
            "message": "Сервис регистрации временно недоступен.",
        }

    code = str(core_payload.get("code") or "")
    if code == "registration_created":
        db.add(
            RegistrationConsent(
                email=data.email,
                agreement_version=data.agreement_version,
                agreement_url=data.agreement_url,
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
                core_response_code=code,
            )
        )
        db.commit()

    return JSONResponse(status_code=core_status, content=core_payload)


@router.post("/auth/refresh", response_model=MobileToken)
def refresh_access_token(
    data: RefreshTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileToken:
    session = (
        db.query(MobileSession)
        .filter(MobileSession.refresh_token_hash == _hash_token(data.refresh_token))
        .first()
    )
    if (
        not session
        or session.status != "active"
        or session.revoked_at is not None
        or _as_utc(session.expires_at) <= _now()
    ):
        raise _credentials_exception()

    mobile_user = session.mobile_user
    if not mobile_user or not mobile_user.core_user_id:
        raise _credentials_exception()

    try:
        core_user_id = int(mobile_user.core_user_id)
    except (TypeError, ValueError):
        raise _credentials_exception()

    user = oysyn_core_client.get_me(core_user_id)
    if not isinstance(user, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Oysyn Core API returned invalid user data",
        )

    refresh_token = secrets.token_urlsafe(48)
    access_token_jti = secrets.token_urlsafe(24)
    session.refresh_token_hash = _hash_token(refresh_token)
    session.access_token_jti = access_token_jti
    session.last_used_at = _now()
    session.ip_address = _client_ip(request)
    session.user_agent = _user_agent(request)
    _sync_mobile_user_snapshot(mobile_user, user)
    linked_session = (
        db.query(LinkedDeviceSession)
        .filter(
            LinkedDeviceSession.mobile_user_id == mobile_user.id,
            LinkedDeviceSession.core_session_id == f"mobile:{session.id}",
        )
        .first()
    )
    if linked_session:
        linked_session.last_active_at = _now()
        linked_session.ip_address = _client_ip(request)
        linked_session.user_agent = _user_agent(request)
        linked_session.status = "active"
    db.commit()

    return MobileToken(
        access_token=create_mobile_access_token(
            core_user_id,
            jti=access_token_jti,
        ),
        refresh_token=refresh_token,
        user=user,
    )


@router.get("/auth/verify")
def verify(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.verify(user_id)


@router.get("/me")
def get_me(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_me(user_id)


@router.get("/me/statistics")
def get_me_statistics(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_me_statistics(user_id)


@router.patch("/me")
def update_me(
    payload: ProfileUpdatePayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.update_me(
        user_id,
        payload.model_dump(exclude_none=True),
    )


@router.get("/notifications")
def get_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    mobile_user = _get_or_create_mobile_user(db, user_id)
    _sync_check_notifications(db, mobile_user, user_id)
    items = (
        db.query(Notification)
        .filter(
            Notification.mobile_user_id == mobile_user.id,
            Notification.archived_at.is_(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [_serialize_notification(item) for item in items],
        "unread_count": sum(item.read_at is None for item in items),
    }


@router.post("/notifications/read")
def mark_notifications_read(
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    mobile_user = _get_or_create_mobile_user(db, user_id)
    read_at = _now()
    updated = (
        db.query(Notification)
        .filter(
            Notification.mobile_user_id == mobile_user.id,
            Notification.read_at.is_(None),
            Notification.archived_at.is_(None),
        )
        .update(
            {
                Notification.read_at: read_at,
                Notification.status: "read",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return {"status": "ok", "updated": updated, "read_at": read_at}


@router.post("/devices/push-token")
def register_push_token(
    payload: PushTokenPayload,
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    mobile_user = _get_or_create_mobile_user(db, user_id)
    token = (
        db.query(PushToken)
        .filter(
            PushToken.mobile_user_id == mobile_user.id,
            PushToken.device_id == payload.device_id,
        )
        .first()
    )
    if token is None:
        token = PushToken(
            mobile_user_id=mobile_user.id,
            device_id=payload.device_id,
            provider=payload.provider,
            token=payload.token,
            platform=payload.platform,
        )
    else:
        token.provider = payload.provider
        token.token = payload.token
        token.platform = payload.platform
        token.is_active = True
        token.revoked_at = None
    token.last_used_at = _now()
    db.add(token)
    db.commit()
    return {"status": "ok"}


@router.get("/sessions/devices")
def get_linked_device_sessions(
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    core_response = oysyn_core_client.get_user_sessions(user_id)
    sessions = [
        _normalize_linked_device_session(item)
        for item in _extract_session_items(core_response)
    ]
    mobile_user = _get_or_create_mobile_user(db, user_id)
    _cache_linked_device_sessions(db, mobile_user.id, sessions)
    mobile_sessions = (
        db.query(MobileSession)
        .filter(
            MobileSession.mobile_user_id == mobile_user.id,
            MobileSession.status == "active",
            MobileSession.revoked_at.is_(None),
            MobileSession.expires_at > _now(),
        )
        .order_by(MobileSession.last_used_at.desc())
        .all()
    )
    for mobile_session in mobile_sessions:
        linked = (
            db.query(LinkedDeviceSession)
            .filter(
                LinkedDeviceSession.mobile_user_id == mobile_user.id,
                LinkedDeviceSession.core_session_id
                == f"mobile:{mobile_session.id}",
            )
            .first()
        )
        parsed_agent = _parse_user_agent(mobile_session.user_agent)
        sessions.append({
            "id": -int(mobile_session.id),
            "mobile_session_id": int(mobile_session.id),
            "source": "mobile",
            "device_name": (
                linked.device_name if linked and linked.device_name
                else "Мобильное приложение OySyn"
            ),
            "browser": parsed_agent["browser"],
            "browser_version": parsed_agent["browser_version"],
            "platform": (
                linked.platform if linked and linked.platform
                else parsed_agent["platform"]
            ),
            "os_version": (
                linked.os_version if linked and linked.os_version
                else parsed_agent["os_version"]
            ),
            "device_type": (
                linked.device_type if linked and linked.device_type
                else parsed_agent["device_type"]
            ),
            "ip_address": mobile_session.ip_address,
            "user_agent": mobile_session.user_agent,
            "status": "active",
            "first_seen_at": mobile_session.created_at,
            "last_active_at": mobile_session.last_used_at,
            "revoked_at": None,
        })
    sessions.sort(
        key=lambda item: _parse_datetime(item.get("last_active_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {"items": sessions}


@router.post("/sessions/devices/{session_id}/revoke")
def revoke_linked_device_session(
    session_id: int,
    user_id: int = Depends(get_mobile_user_id),
    db: Session = Depends(get_db),
):
    if session_id < 0:
        mobile_user = _get_or_create_mobile_user(db, user_id)
        mobile_session_id = -session_id
        session = (
            db.query(MobileSession)
            .filter(
                MobileSession.id == mobile_session_id,
                MobileSession.mobile_user_id == mobile_user.id,
            )
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        session.status = "revoked"
        session.revoked_at = _now()
        session.revoked_by_user_id = mobile_user.id
        session.revocation_reason = "revoked_by_user"
        linked = (
            db.query(LinkedDeviceSession)
            .filter(
                LinkedDeviceSession.mobile_user_id == mobile_user.id,
                LinkedDeviceSession.core_session_id
                == f"mobile:{mobile_session_id}",
            )
            .first()
        )
        if linked:
            linked.status = "revoked"
            linked.revoked_at = _now()
        db.commit()
        return {"status": "ok"}

    core_response = oysyn_core_client.revoke_user_session(user_id, session_id)
    mobile_user = _get_or_create_mobile_user(db, user_id)
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


@router.patch("/organizations/{organization_id}")
def update_organization(
    organization_id: int,
    payload: OrganizationUpdatePayload,
    user_id: int = Depends(get_mobile_user_id),
):
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы данные для обновления организации",
        )
    return oysyn_core_client.update_organization(
        user_id,
        organization_id,
        values,
    )


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


@router.post("/organizations/{organization_id}/api-settings", status_code=201)
def create_organization_api_setting(
    organization_id: int,
    payload: OrganizationApiTokenPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.create_organization_api_setting(
        user_id,
        organization_id,
        payload.model_dump(),
    )


@router.get("/organizations/{organization_id}/thresholds")
def get_organization_thresholds(
    organization_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_thresholds(user_id, organization_id)


@router.patch("/organizations/{organization_id}/thresholds")
def update_organization_thresholds(
    organization_id: int,
    payload: Dict[str, float],
    user_id: int = Depends(get_mobile_user_id),
):
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы пороговые значения",
        )
    return oysyn_core_client.update_organization_thresholds(
        user_id,
        organization_id,
        payload,
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


@router.get("/organizations/{organization_id}/checks/deleted")
def get_organization_deleted_checks(
    organization_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_organization_deleted_checks(
        user_id,
        organization_id,
        {"page": page, "page_size": page_size},
    )


@router.post("/organizations/{organization_id}/checks/{check_id}/restore")
def restore_organization_check(
    organization_id: int,
    check_id: int,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.restore_organization_check(
        user_id,
        organization_id,
        check_id,
    )


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


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def create_folder(
    payload: FolderPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.create_folder(
        user_id,
        payload.model_dump(exclude_none=True),
    )


@router.patch("/folders/{folder_id}")
def rename_folder(
    folder_id: int,
    payload: FolderPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.rename_folder(
        user_id,
        folder_id,
        {"name": payload.name},
    )


@router.get("/checks/modules")
def get_check_modules(user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_check_modules(user_id)


@router.get("/checks/pair-checks")
def get_pair_checks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.get_pair_checks(
        user_id,
        {"page": page, "page_size": page_size},
    )


@router.post("/checks/pair-checks", status_code=status.HTTP_201_CREATED)
async def create_pair_check(
    a_title: str = Form(...),
    b_title: str = Form(...),
    a_author: str = Form(...),
    b_author: str = Form(...),
    a_document: UploadFile = File(...),
    b_document: UploadFile = File(...),
    user_id: int = Depends(get_mobile_user_id),
):
    return await oysyn_core_client.create_pair_check(
        user_id,
        first_document=a_document,
        second_document=b_document,
        form={
            "a_title": a_title,
            "b_title": b_title,
            "a_author": a_author,
            "b_author": b_author,
        },
    )


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
    db: Session = Depends(get_db),
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

    mobile_user = _get_or_create_mobile_user(db, user_id)
    request_item = MobileCheckRequest(
        mobile_user_id=mobile_user.id,
        core_user_id=str(user_id),
        core_organization_id=(
            str(user.get("organization_id"))
            if user.get("organization_id") is not None
            else None
        ),
        source="mobile",
        status="submitting",
        title=title,
        document_name=document.filename,
        document_type=document_type,
    )
    db.add(request_item)
    db.commit()
    db.refresh(request_item)
    try:
        result = await oysyn_core_client.create_check(
            user_id,
            document=document,
            form=form,
        )
    except Exception as exc:
        request_item.status = "failed"
        request_item.failed_at = _now()
        request_item.error_message = str(exc)[:1000]
        db.commit()
        raise

    if isinstance(result, dict):
        check_id = result.get("id") or result.get("core_check_id")
        request_item.core_check_id = str(check_id) if check_id is not None else None
        request_item.status = "submitted"
        request_item.submitted_at = _now()
        check_status = str(result.get("status") or "").upper()
        if check_status in {"CH", "FA"} and check_id is not None:
            _create_check_notification(db, mobile_user.id, result)
            request_item.status = "failed" if check_status == "FA" else "completed"
            if check_status == "FA":
                request_item.failed_at = _now()
            else:
                request_item.completed_at = _now()
    db.commit()
    return result


@router.get("/checks/{check_id}")
def get_check(check_id: int, user_id: int = Depends(get_mobile_user_id)):
    return oysyn_core_client.get_check(user_id, check_id)


@router.patch("/checks/{check_id}")
def update_check_folder(
    check_id: int,
    payload: CheckFolderPayload,
    user_id: int = Depends(get_mobile_user_id),
):
    return oysyn_core_client.update_check_folder(
        user_id,
        check_id,
        payload.folder_id,
    )


@router.delete("/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_check(check_id: int, user_id: int = Depends(get_mobile_user_id)):
    try:
        oysyn_core_client.delete_check(user_id, check_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Удаление документов пока не поддерживается Oysyn Core API",
            ) from exc
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
