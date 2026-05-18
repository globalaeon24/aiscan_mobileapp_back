import os
import requests
from typing import Tuple, Optional, Any

ZEROGPT_URL = os.getenv("ZEROGPT_URL")
ZEROGPT_API_KEY = os.getenv("ZEROGPT_API_KEY")
ZEROGPT_API_HOST = os.getenv("ZEROGPT_API_HOST")


def zerogpt_request(chunk: str) -> Tuple[float, float, Optional[Any]]:
    """
    Отправляет чанк текста в ZeroGPT.
    Возвращает: (gpt%, human%, error)
    """

    if not ZEROGPT_URL or not ZEROGPT_API_KEY or not ZEROGPT_API_HOST:
        return 0, 0, "ZeroGPT env variables missing"

    headers = {
        "Content-Type": "application/json",
        "X-RapidAPI-Key": ZEROGPT_API_KEY,
        "X-RapidAPI-Host": ZEROGPT_API_HOST,
    }

    body = {"input_text": chunk}

    try:
        r = requests.post(ZEROGPT_URL, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            return 0, 0, data.get("message")

        human = float(data["data"].get("is_human_written", 0))
        gpt = float(data["data"].get("is_gpt_generated", 0))

        return gpt, human, None

    except Exception as e:
        return 0, 0, e


def split_into_chunks(text: str, size: int = 10000):
    return [text[i:i+size] for i in range(0, len(text), size)]


def run_zerogpt(text: str) -> float:
    """
    Режет текст на чанки, вызывает ZeroGPT, усредняет результат.
    Возвращает процент ИИ.
    """

    if not text.strip():
        return 0.0

    chunks = split_into_chunks(text)
    total_gpt = 0.0

    for chunk in chunks:
        gpt, human, err = zerogpt_request(chunk)
        if err:
            print("ZeroGPT ERROR:", err)
            continue

        total_gpt += gpt

    return total_gpt / len(chunks)