import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config import BASE_DIR, GEMINI_MODEL


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_api_key() -> str:
    candidates = [
        BASE_DIR / ".env",
        BASE_DIR / "agent1" / ".env",
        BASE_DIR / "agent8" / ".env",
        Path("/root/.env"),
    ]
    for path in candidates:
        _load_env_file(path)

    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(
        "Không tìm thấy GEMINI_API_KEY. Hãy thêm GEMINI_API_KEY=... "
        "vào /opt/unsolved-channel/.env"
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if match:
        return json.loads(match.group(1))

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("Gemini không trả về JSON hợp lệ.")


def generate_metadata(prompt: str) -> dict[str, Any]:
    api_key = load_api_key()
    model = os.getenv("GEMINI_MODEL", GEMINI_MODEL)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.75,
            "responseMimeType": "application/json",
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Không kết nối được Gemini: {exc}") from exc

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Phản hồi Gemini không hợp lệ: {body}") from exc

    return _extract_json(text)
