import json
import os
import random
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config import (
    BASE_DIR,
    GEMINI_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_DELAY_SECONDS,
    RETRY_LIMIT,
)

TRANSIENT_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_api_key() -> str:
    candidates = [
        BASE_DIR / '.env',
        BASE_DIR / 'agent1' / '.env',
        BASE_DIR / 'agent8' / '.env',
        Path('/root/.env'),
    ]
    for path in candidates:
        _load_env_file(path)
    for name in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_AI_API_KEY'):
        value = os.getenv(name, '').strip()
        if value:
            return value
    raise RuntimeError('Không tìm thấy GEMINI_API_KEY trong file .env.')


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    if match:
        data = json.loads(match.group(1))
        if isinstance(data, dict):
            return data

    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        data = json.loads(text[start:end + 1])
        if isinstance(data, dict):
            return data
    raise ValueError('Gemini không trả về JSON object hợp lệ.')


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in TRANSIENT_HTTP
    return isinstance(exc, (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError))


def generate_metadata(prompt: str) -> tuple[dict[str, Any], int, int]:
    api_key = load_api_key()
    model = os.getenv('AGENT9_GEMINI_MODEL', GEMINI_MODEL)
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.55,
            'topP': 0.9,
            'maxOutputTokens': 4096,
            'responseMimeType': 'application/json',
        },
    }

    calls = retries = 0
    last_exc: Exception | None = None
    for attempt in range(1, RETRY_LIMIT + 1):
        calls += 1
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode('utf-8'))
            text = body['candidates'][0]['content']['parts'][0]['text']
            return _extract_json(text), calls, retries
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            last_exc = RuntimeError(f'Gemini HTTP {exc.code}: {detail[:1200]}')
            retryable = exc.code in TRANSIENT_HTTP
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_exc = RuntimeError(f'Lỗi kết nối Gemini: {exc}')
            retryable = True
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            last_exc = RuntimeError(f'Phản hồi Gemini không hợp lệ: {exc}')
            retryable = False

        if attempt >= RETRY_LIMIT or not retryable:
            break
        retries += 1
        delay = RETRY_DELAY_SECONDS * attempt + random.uniform(0, 1.5)
        time.sleep(delay)

    raise last_exc or RuntimeError('Không tạo được metadata từ Gemini.')
