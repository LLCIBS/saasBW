import logging
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests

import config

try:
    from .utils import make_request_with_retries  # type: ignore
except ImportError:
    from utils import make_request_with_retries


logger = logging.getLogger(__name__)


class TranscriptionService:
    """Обёртка над Speechmatics API.

    Предоставляет методы запуска транскрипции и получения результата.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://asr.api.speechmatics.com/v2"

    def start_transcription(self, file_path: Path, additional_vocab: Optional[List[str]] = None) -> Optional[str]:
        """Отправляет аудиофайл на транскрипцию и возвращает job_id."""
        url = f"{self.base_url}/jobs"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        transcription_config: Dict[str, Any] = {
            "language": getattr(config, "SPEECHMATICS_LANGUAGE", "ru"),
            "diarization": "speaker",
        }
        if additional_vocab:
            transcription_config["additional_vocab"] = [{"content": w} for w in additional_vocab]

        data_json = {"config": json.dumps({
            "type": "transcription",
            "transcription_config": transcription_config
        })}

        def _request():
            with file_path.open("rb") as f:
                files = {"data_file": (file_path.name, f)}
                return requests.post(url, headers=headers, data=data_json, files=files, timeout=60)

        resp = make_request_with_retries(_request, max_retries=3, delay=5)
        if not resp or resp.status_code not in (200, 201):
            logger.error(f"[Speechmatics] Ошибка загрузки {file_path.name}: {resp.status_code if resp else 'NoResp'} {resp.text if resp else ''}")
            return None

        try:
            return resp.json().get("id")
        except Exception:
            return None

    def get_transcription(self, job_id: str, max_retries: int = 30, delay: int = 15) -> Dict[str, Any]:
        """Пуллит расшифровку до готовности и возвращает JSON."""
        url = f"{self.base_url}/jobs/{job_id}/transcript"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(max_retries):
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception as e:
                    logger.error(f"[Speechmatics] Ошибка парсинга транскрипта: {e}")
                    return {}
            if resp.status_code == 404:
                time.sleep(delay)
                continue
            logger.error(f"[Speechmatics] Неожиданный ответ: {resp.status_code} {resp.text}")
            time.sleep(delay)
        return {}


class TheBaiAnalyzer:
    """Обёртка над TheB.ai для анализа транскриптов."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.url = getattr(config, "THEBAI_URL", "https://api.theb.ai/v1/chat/completions")

    def analyze(self, transcript: str, prompt: str) -> str:
        if not transcript or not transcript.strip():
            return "Пустой транскрипт, нет анализа."

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": f"{prompt}\n\nВот диалог:\n{transcript}"}],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        def _request():
            return requests.post(self.url, headers=headers, json=payload, timeout=90)

        resp = make_request_with_retries(_request, max_retries=3, delay=10)
        if not resp or resp.status_code != 200:
            logger.error(f"[TheB.ai] Ошибка анализа: {resp.status_code if resp else 'NoResp'} {resp.text if resp else ''}")
            return "Ошибка анализа"
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"[TheB.ai] Ошибка парсинга ответа: {e}")
            return "Ошибка анализа"



