import asyncio
import os
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from routes.mobile_v1 import (
    reconcile_pending_check_notifications,
    router as mobile_v1_router,
)

environment = os.getenv("ENVIRONMENT", "development").strip().lower()
cors_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
cors_allowed_origin_regex = os.getenv("CORS_ALLOWED_ORIGIN_REGEX", "").strip()
if environment == "stage" and not cors_allowed_origin_regex:
    cors_allowed_origin_regex = (
        r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|"
        r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])"
        r"(?:\.\d{1,3}){2})(:\d+)?$"
    )

app = FastAPI(
    title="Oysyn Mobile Backend",
    version="1.0.0",
    docs_url=None if environment == "production" else "/api/docs",
    openapi_url=None if environment == "production" else "/api/openapi.json",
)

notification_poll_task = None
max_request_bytes = int(os.getenv("MAX_REQUEST_BYTES", str(55 * 1024 * 1024)))
max_json_body_bytes = int(os.getenv("MAX_JSON_BODY_BYTES", str(1024 * 1024)))


async def _notification_poll_loop() -> None:
    interval = max(15, int(os.getenv("NOTIFICATION_POLL_SECONDS", "30")))
    while True:
        try:
            await asyncio.to_thread(reconcile_pending_check_notifications)
        except Exception:
            # A temporary Core outage must not stop the next polling cycle.
            pass
        await asyncio.sleep(interval)


@app.on_event("startup")
async def start_notification_polling() -> None:
    global notification_poll_task
    notification_poll_task = asyncio.create_task(_notification_poll_loop())


@app.on_event("shutdown")
async def stop_notification_polling() -> None:
    if notification_poll_task is None:
        return
    notification_poll_task.cancel()
    with suppress(asyncio.CancelledError):
        await notification_poll_task

if cors_allowed_origins or cors_allowed_origin_regex:
    allow_credentials = "*" not in cors_allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_origin_regex=cors_allowed_origin_regex or None,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "app": "oysyn-mobile-backend",
        "environment": environment,
    }


@app.get("/health")
def health():
    return {"status": "ok", "environment": environment}


app.include_router(mobile_v1_router, prefix="/api/v1", tags=["mobile-v1"])


@app.middleware("http")
async def enforce_request_size(request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Content-Length"},
            )
        content_type = request.headers.get("content-type", "").lower()
        limit = (
            max_request_bytes
            if "multipart/form-data" in content_type
            else max_json_body_bytes
        )
        if size > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request is too large"},
            )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    return response
