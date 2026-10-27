import asyncio
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import routes.mobile_v1 as mobile_routes
from services.oysyn_core_client import OysynCoreClient


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class _Database:
    def __init__(self, *results):
        self.results = iter(results)

    def query(self, model):
        return _Query(next(self.results))


def test_access_token_requires_matching_active_session(monkeypatch):
    monkeypatch.setattr(mobile_routes, "SECRET_KEY", "s" * 64)
    token = mobile_routes.create_mobile_access_token(42, jti="known-jti")
    user = SimpleNamespace(id=7, status="active")

    with pytest.raises(HTTPException) as error:
        mobile_routes.get_mobile_user_id(token=token, db=_Database(user, None))

    assert error.value.status_code == 401


def test_access_token_accepts_matching_active_session(monkeypatch):
    monkeypatch.setattr(mobile_routes, "SECRET_KEY", "s" * 64)
    token = mobile_routes.create_mobile_access_token(42, jti="known-jti")
    user = SimpleNamespace(id=7, status="active")
    session = SimpleNamespace(
        status="active",
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert mobile_routes.get_mobile_user_id(
        token=token,
        db=_Database(user, session),
    ) == 42


def test_upload_rejects_extension_content_mismatch(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    upload = UploadFile(filename="report.pdf", file=BytesIO(b"not-a-pdf"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(OysynCoreClient._read_upload(upload))

    assert error.value.status_code == 415


def test_upload_rejects_oversized_document(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "8")
    upload = UploadFile(filename="report.pdf", file=BytesIO(b"%PDF-123456"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(OysynCoreClient._read_upload(upload))

    assert error.value.status_code == 413


def test_rate_limit_returns_retry_after():
    mobile_routes._rate_limit_events.clear()
    mobile_routes._enforce_rate_limit(
        "test",
        "identity",
        limit=1,
        window_seconds=60,
    )

    with pytest.raises(HTTPException) as error:
        mobile_routes._enforce_rate_limit(
            "test",
            "identity",
            limit=1,
            window_seconds=60,
        )

    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0
