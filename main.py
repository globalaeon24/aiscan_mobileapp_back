import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routes.mobile_v1 import router as mobile_v1_router

environment = os.getenv("ENVIRONMENT", "development").strip().lower()
cors_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
cors_allowed_origin_regex = os.getenv("CORS_ALLOWED_ORIGIN_REGEX", "").strip()
if environment == "stage" and not cors_allowed_origin_regex:
    cors_allowed_origin_regex = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app = FastAPI(
    title="Oysyn Mobile Backend",
    version="1.0.0",
    docs_url="/api/docs",           
    openapi_url="/api/openapi.json" 
)

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
