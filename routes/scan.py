from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
import subprocess
import tempfile
import os
import json
from datetime import datetime

from database import get_db
from routes.auth import get_current_user
from models import User, ScanResult
from schemas import (
    ScanDetail,
    ScanShort,
    ScanHistory,
    ScanCreate,
)

# ZeroGPT pipeline
from services.gpt_zero_service import GPTCheck
# Универсальный парсер документов
from services.document_parser import extract_text

router = APIRouter()

# =====================================================================
#        ВСПОМОГАТЕЛЬНО: порядковый номер проверки ДЛЯ ПОЛЬЗОВАТЕЛЯ
# =====================================================================
def get_next_user_scan_index(db: Session, user_id: int) -> int:
    last = (
        db.query(ScanResult.user_scan_index)
        .filter(
            ScanResult.user_id == user_id,
            ScanResult.user_scan_index.isnot(None),
        )
        .order_by(ScanResult.user_scan_index.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


# =====================================================================
#                     OCR (IMAGE → TEXT)  /api/scan/ocr
# =====================================================================
@router.post("/ocr")
async def ocr_extract_text(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_types = ["image/jpeg", "image/png", "image/jpg", "image/tiff"]

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Неверный формат файла ({file.content_type}). Используйте JPG/PNG."
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp_path = tmp.name

    contents = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(contents)

    out_txt = tmp_path + "_out"

    try:
        result = subprocess.run(
            ["tesseract", tmp_path, out_txt, "-l", "rus+eng+kaz"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="ignore")
            raise HTTPException(status_code=500, detail=f"Ошибка OCR: {error}")

        txt_file = out_txt + ".txt"
        if not os.path.exists(txt_file):
            raise HTTPException(status_code=500, detail="Выходной файл OCR не найден.")

        with open(txt_file, "r", encoding="utf-8") as f:
            text = f.read()

        if not text.strip():
            raise HTTPException(status_code=400, detail="Текст не распознан.")

        return {"text": text}

    finally:
        for path in [tmp_path, out_txt + ".txt"]:
            if os.path.exists(path):
                os.remove(path)


# =====================================================================
#        ЗАГРУЗКА ФАЙЛА И ПРОВЕРКА  /api/scan/file
# =====================================================================
@router.post("/file", response_model=ScanDetail)
async def upload_and_scan_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    text = (await extract_text(file)).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст пустой после разбора файла")

    gpt_pct, _, ai_fragments_json, err = GPTCheck(text)
    if err:
        raise HTTPException(status_code=500, detail=f"Ошибка AI-проверки: {err}")

    scan = ScanResult(
        user_id=current_user.id,
        user_scan_index=get_next_user_scan_index(db, current_user.id),
        file_name=file.filename,
        author_name=current_user.name,
        scanned_text=text,
        highlighted_text=text,
        ai_percentage=gpt_pct,
        ai_fragments=ai_fragments_json,
        created_at=datetime.utcnow(),
    )

    db.add(scan)
    db.commit()
    db.refresh(scan)

    # --- распарсить ai_fragments для ответа ---
    try:
        ai_fragments_list = json.loads(scan.ai_fragments) if scan.ai_fragments else []
    except Exception:
        ai_fragments_list = []

    return ScanDetail(
        id=scan.id,
        ai_percentage=scan.ai_percentage,
        scanned_text=scan.scanned_text,
        highlighted_text=scan.highlighted_text,
        ai_fragments=ai_fragments_list,
        created_at=scan.created_at,
        user_scan_index=scan.user_scan_index,
        file_name=scan.file_name,
        author_name=scan.author_name,
    )


# =====================================================================
#        СОЗДАНИЕ СКАНА ПО ТЕКСТУ  /api/scan/
# =====================================================================
@router.post("/", response_model=ScanDetail)
def create_scan(
    data: ScanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    text = data.scanned_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст пустой")

    gpt_pct, _, ai_fragments_json, err = GPTCheck(text)
    if err:
        raise HTTPException(status_code=500, detail=f"Ошибка AI-проверки: {err}")

    scan = ScanResult(
        user_id=current_user.id,
        user_scan_index=get_next_user_scan_index(db, current_user.id),
        file_name="manual_text",
        author_name=current_user.name,
        scanned_text=text,
        highlighted_text=text,
        ai_percentage=gpt_pct,
        ai_fragments=ai_fragments_json,
        created_at=datetime.utcnow(),
    )

    db.add(scan)
    db.commit()
    db.refresh(scan)

    try:
        ai_fragments_list = json.loads(scan.ai_fragments) if scan.ai_fragments else []
    except Exception:
        ai_fragments_list = []

    return ScanDetail(
        id=scan.id,
        ai_percentage=scan.ai_percentage,
        scanned_text=scan.scanned_text,
        highlighted_text=scan.highlighted_text,
        ai_fragments=ai_fragments_list,
        created_at=scan.created_at,
        user_scan_index=scan.user_scan_index,
        file_name=scan.file_name,
        author_name=scan.author_name,
    )


# =====================================================================
#                         ИСТОРИЯ СКАНОВ
# =====================================================================
@router.get("/history", response_model=ScanHistory)
def get_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scans = (
        db.query(ScanResult)
        .filter(ScanResult.user_id == current_user.id)
        .order_by(ScanResult.created_at.desc())
        .limit(50)
        .all()
    )

    items = [ScanShort.model_validate(s) for s in scans]
    return ScanHistory(items=items)


# =====================================================================
#                       ДЕТАЛИ ОДНОГО СКАНА
# =====================================================================
@router.get("/{scan_id}", response_model=ScanDetail)
def get_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scan = (
        db.query(ScanResult)
        .filter(
            ScanResult.id == scan_id,
            ScanResult.user_id == current_user.id,
        )
        .first()
    )

    if not scan:
        raise HTTPException(status_code=404, detail="Результат проверки не найден")

    try:
        ai_fragments_list = json.loads(scan.ai_fragments) if scan.ai_fragments else []
    except Exception:
        ai_fragments_list = []

    return ScanDetail(
        id=scan.id,
        ai_percentage=scan.ai_percentage,
        scanned_text=scan.scanned_text,
        highlighted_text=scan.highlighted_text,
        ai_fragments=ai_fragments_list,
        created_at=scan.created_at,
        user_scan_index=scan.user_scan_index,
        file_name=scan.file_name,
        author_name=scan.author_name,
    )