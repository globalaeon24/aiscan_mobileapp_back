from datetime import datetime, timedelta, timezone
from typing import Optional
import os
import hashlib

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database import get_db
from models import User, Organization
from hashing import verify_password, get_password_hash
from schemas import TokenData, UserCreate

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY is not set or too short (min 32 chars)")

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# auto_error=False — чтобы мы сами возвращали корректный 401 и логировали причину
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # Быстрые диагностические логи
    auth_header = request.headers.get("authorization")
    print("AUTH HEADER:", auth_header)
    print("TOKEN PRESENT:", bool(token))
    print("TOKEN LEN:", len(token) if token else 0)
    print("SECRET_KEY SHA256:", hashlib.sha256(SECRET_KEY.encode()).hexdigest()[:12])
    print("ALGORITHM:", ALGORITHM)
    print("TOKEN EXPIRE (MIN):", ACCESS_TOKEN_EXPIRE_MINUTES)

    if not token:
        print("AUTH FAIL: no token extracted by OAuth2PasswordBearer")
        raise _credentials_exception()

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if not user_id:
            print("AUTH FAIL: token has no 'sub'")
            raise _credentials_exception()

        try:
            user_id_int = int(user_id)
        except ValueError:
            print("AUTH FAIL: sub is not int:", user_id)
            raise _credentials_exception()

        token_data = TokenData(user_id=user_id_int)

    except JWTError as e:
        # Тут будет "Signature verification failed" или "Signature has expired"
        print("JWT ERROR:", str(e))
        raise _credentials_exception()

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        print("AUTH FAIL: USER NOT FOUND:", token_data.user_id)
        raise _credentials_exception()

    return user


def register_user(user_data: UserCreate, db: Session) -> User:
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует",
        )

    if not user_data.agree_privacy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо согласие с политикой конфиденциальности",
        )

    org = None
    if user_data.organization_name:
        org = (
            db.query(Organization)
            .filter(Organization.name == user_data.organization_name)
            .first()
        )
        if not org:
            org = Organization(name=user_data.organization_name)
            db.add(org)
            db.flush()

    user = User(
        email=user_data.email,
        name=user_data.name,
        hashed_password=get_password_hash(user_data.password),
        organization_id=org.id if org else None,
        agreed_privacy=True,
        agreed_at=datetime.now(timezone.utc),
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(email: str, password: str, db: Session) -> Optional[User]:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user