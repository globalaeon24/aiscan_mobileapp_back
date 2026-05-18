import os
import subprocess
import tempfile
from typing import Optional

from pdfminer.high_level import extract_text as pdfminer_extract
import docx2txt
from fastapi import UploadFile, HTTPException

from PIL import Image
import pytesseract


# ================================================================
#                    PDF → TEXT  (pdfminer → OCR fallback)
# ================================================================
def parse_pdf(temp_path: str) -> str:
    """
    Основной парсер PDF. Если pdfminer не дал текст — OCR fallback.
    """

    # --- 1) pdfminer ---
    try:
        text = pdfminer_extract(temp_path)
        if text.strip():
            return text
    except Exception:
        pass

    # --- 2) OCR fallback ---
    jpg_prefix = temp_path + "_ocr"
    jpg_file = jpg_prefix + "-1.jpg"

    try:
        subprocess.run(
            ["pdftoppm", temp_path, jpg_prefix, "-jpeg"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        if os.path.exists(jpg_file):
            img = Image.open(jpg_file)
            text = pytesseract.image_to_string(img, lang="rus+eng")
            if text.strip():
                return text

    except Exception:
        pass

    raise HTTPException(status_code=400, detail="Не удалось извлечь текст из PDF")


# ================================================================
#                    DOCX → TEXT
# ================================================================
def parse_docx(temp_path: str) -> str:
    try:
        text = docx2txt.process(temp_path)
        if text.strip():
            return text
        raise Exception("DOCX пустой")
    except Exception:
        raise HTTPException(status_code=400, detail="Не удалось прочитать DOCX")


# ================================================================
#                    DOC → TEXT (antiword → fallback)
# ================================================================
def parse_doc(temp_path: str) -> str:
    txt_path = temp_path + ".txt"

    # --- antiword ---
    try:
        subprocess.run(
            ["antiword", temp_path],
            stdout=open(txt_path, "w"),
            stderr=subprocess.PIPE,
            check=False
        )

        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            if text.strip():
                return text

    except Exception:
        pass

    # --- fallback: LibreOffice → PDF → parse ---
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", temp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        pdf_ver = temp_path.replace(".doc", ".pdf")
        if os.path.exists(pdf_ver):
            return parse_pdf(pdf_ver)

    except Exception:
        pass

    raise HTTPException(status_code=400, detail="Не удалось извлечь текст из DOC")


# ================================================================
#                    IMAGE → TEXT (OCR)
# ================================================================
def parse_image(temp_path: str) -> str:
    try:
        img = Image.open(temp_path)
        text = pytesseract.image_to_string(img, lang="rus+eng+kaz")
        if text.strip():
            return text
        raise Exception("OCR пуст")
    except Exception:
        raise HTTPException(status_code=400, detail="Не удалось распознать текст")


# ================================================================
#                    UNIVERSAL PARSER
# ================================================================
async def extract_text(file: UploadFile) -> str:
    """
    Универсальный метод: PDF, DOCX, DOC, JPG, PNG, TIFF.
    """

    content_type = file.content_type.lower()

    # --- сохраняем временный файл ---
    suffix = ""

    # PDF
    if content_type == "application/pdf":
        suffix = ".pdf"

    # DOCX — поддерживаем два MIME-типа (правильный + кривой от Flutter)
    elif content_type in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.wordprocessinggml.document",
    ]:
        suffix = ".docx"

    # DOC (MS Word 97-2003)
    elif content_type in [
        "application/msword",
        "application/doc",
        "application/octet-stream",   # Android даёт это для старых DOC
    ]:
        suffix = ".doc"

    # Images
    elif "png" in content_type:
        suffix = ".png"
    elif "jpeg" in content_type or "jpg" in content_type:
        suffix = ".jpg"
    elif "tiff" in content_type:
        suffix = ".tiff"

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый тип файла: {content_type}"
        )

    # --- сохраняем файл ---
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = tmp.name

    contents = await file.read()
    with open(temp_path, "wb") as f:
        f.write(contents)

    # --- Обрабатываем ---
    try:
        if suffix == ".pdf":
            return parse_pdf(temp_path)
        elif suffix == ".docx":
            return parse_docx(temp_path)
        elif suffix == ".doc":
            return parse_doc(temp_path)
        else:
            return parse_image(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass