import os
import json
import requests
from typing import List, Tuple, Any, Dict, Optional

# -----------------------------
#  TEXT SPLITTING
# -----------------------------
def split_into_chunks(input_text: str, chunk_size: int = 8000) -> List[str]:
    """
    Делит текст на чанки.
    ZeroGPT позволяет до ~10k символов, оптимально — 6–8k.
    """
    return [
        input_text[i:i + chunk_size]
        for i in range(0, len(input_text), chunk_size)
    ]


def _find_all_occurrences_sequential(haystack: str, needle: str) -> List[Tuple[int, int]]:
    """
    Ищет все вхождения needle в haystack последовательно слева направо.
    Возвращает список (start, end) в координатах haystack.
    """
    if not needle:
        return []

    res: List[Tuple[int, int]] = []
    start_pos = 0
    while True:
        idx = haystack.find(needle, start_pos)
        if idx == -1:
            break
        res.append((idx, idx + len(needle)))
        start_pos = idx + len(needle)
    return res


def _normalize_spaces(s: str) -> str:
    return " ".join((s or "").split())


def build_ai_fragments_for_chunk(chunk_text: str, chunk_offset: int, ai_sentences: List[str]) -> List[Dict[str, Any]]:
    """
    Превращает список AI-предложений (как вернул ZeroGPT) в позиции (start/end) в полном тексте.
    chunk_offset — смещение чанка относительно исходного полного текста.
    """
    fragments: List[Dict[str, Any]] = []

    if not ai_sentences:
        return fragments

    # 1) Пытаемся найти точные вхождения
    for sent in ai_sentences:
        sent_clean = (sent or "").strip()
        if not sent_clean:
            continue

        occ = _find_all_occurrences_sequential(chunk_text, sent_clean)

        # 2) Если не нашли — пробуем нормализовать пробелы (часто API возвращает с другими пробелами)
        if not occ:
            norm_chunk = _normalize_spaces(chunk_text)
            norm_sent = _normalize_spaces(sent_clean)

            # ВНИМАНИЕ: индексы после нормализации уже не совпадают с оригиналом.
            # Поэтому при фолбэке мы просто НЕ подсвечиваем, чем рисовать неправильные позиции.
            # Это честнее.
            if norm_sent and norm_sent in norm_chunk:
                # логируем в будущем, но здесь тихо пропускаем
                continue

        for start, end in occ:
            fragments.append({
                "start": chunk_offset + start,
                "end": chunk_offset + end,
                "text": sent_clean,
                "confidence": 1.0,  # ZeroGPT уже сказал, что это AI sentence
            })

    # Убираем пересечения/дубликаты по (start,end)
    uniq = {(f["start"], f["end"]): f for f in fragments}
    fragments = list(uniq.values())
    fragments.sort(key=lambda x: x["start"])
    return fragments


# -----------------------------
#  REQUEST TO ZERO GPT
# -----------------------------
def sendGPTCheckRequest(chunk: str) -> Tuple[float, float, List[str], Any]:
    """
    Отправляет один чанк текста в ZeroGPT API.
    Возвращает: (human_written%, gpt_generated%, gpt_generated_sentences, error)
    """

    url = os.getenv("ZEROGPTURL")
    api_key = os.getenv("X_RAPIDAPI_KEY")
    api_host = os.getenv("X_RAPIDAPI_HOST")

    if not url or not api_key or not api_host:
        return 0.0, 0.0, [], ValueError("ZeroGPT ENV variables missing")

    headers = {
        "Content-Type": "application/json",
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
    }

    payload = {"input_text": chunk}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=40)
        res.raise_for_status()
        data = res.json()

        if not data.get("success"):
            return 0.0, 0.0, [], ValueError(data.get("message"))

        d = data.get("data") or {}

        human = float(d.get("is_human_written", 0.0))
        gpt = float(d.get("is_gpt_generated", 0.0))

        ai_sentences = d.get("gpt_generated_sentences") or []
        if not isinstance(ai_sentences, list):
            ai_sentences = []

        # приводим к строкам
        ai_sentences = [str(x) for x in ai_sentences if str(x).strip()]

        return human, gpt, ai_sentences, None

    except Exception as e:
        return 0.0, 0.0, [], e


# -----------------------------
#  HIGH-LEVEL ZERO GPT CHECK
# -----------------------------
def GPTCheck(text: str) -> Tuple[float, float, str, Any]:
    """
    Выполняет полную проверку текста:
    - режет на чанки
    - отправляет каждый чанк
    - агрегирует проценты
    - собирает ai_fragments (позиции) по gpt_generated_sentences

    Возвращает:
      (avg_gpt, avg_human, ai_fragments_json_string, err)
    """

    if not text:
        return 0.0, 0.0, "[]", None

    chunks = split_into_chunks(text, 8000)

    total_human = 0.0
    total_gpt = 0.0

    all_fragments: List[Dict[str, Any]] = []

    for idx, chunk in enumerate(chunks):
        human, gpt, ai_sentences, err = sendGPTCheckRequest(chunk)

        if err:
            if idx < len(chunks) - 1:
                continue
            return 0.0, 0.0, "[]", err

        total_human += human
        total_gpt += gpt

        chunk_offset = idx * 8000
        fragments = build_ai_fragments_for_chunk(chunk, chunk_offset, ai_sentences)
        all_fragments.extend(fragments)

    avg_human = total_human / len(chunks)
    avg_gpt = total_gpt / len(chunks)

    # чистим фрагменты (сортировка, уникальность)
    uniq = {(f["start"], f["end"]): f for f in all_fragments}
    all_fragments = list(uniq.values())
    all_fragments.sort(key=lambda x: x["start"])

    return avg_gpt, avg_human, json.dumps(all_fragments, ensure_ascii=False), None