from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.auth import router as auth_router
from routes.mobile_v1 import router as mobile_v1_router
from routes.scan import router as scan_router

app = FastAPI(
    title="ScanAI Backend",
    version="1.0.0",
    docs_url="/api/docs",           
    openapi_url="/api/openapi.json" 
)

# На первом этапе оставим CORS максимально открытым,
# потом можно будет сузить под домен/приложение.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ПОТОМ УЖЕЖЕСТИМ
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"status": "ok", "app": "scanai-backend"}


app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(scan_router, prefix="/api/scan", tags=["scan"])
app.include_router(mobile_v1_router, prefix="/api/v1", tags=["mobile-v1"])
