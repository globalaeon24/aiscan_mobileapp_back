import pytesseract
from PIL import Image


def extract_text_from_image(image_path: str) -> str:
    """
    OCR через Tesseract на стороне бекенда.
    Поддержка рус + англ.
    """

    try:
        img = Image.open(image_path)

        text = pytesseract.image_to_string(
            img,
            lang="rus+eng"  # kaz нет в официальной поставке
        )

        return text.strip()
    except Exception as e:
        raise RuntimeError(f"OCR failed: {str(e)}")