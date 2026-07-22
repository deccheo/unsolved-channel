import base64
import hashlib
import wave
from pathlib import Path

from google import genai

from config import (
    CACHE_DIR,
    CHANNELS,
    GEMINI_API_KEY,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    TTS_MODEL,
    TTS_VOICE,
)


def normalize_narration(narration: str) -> str:
    return " ".join((narration or "").split())


def narration_hash(narration: str) -> str:
    payload = f"{TTS_MODEL}|{TTS_VOICE}|{normalize_narration(narration)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_path_for(narration: str) -> Path:
    return CACHE_DIR / f"{narration_hash(narration)}.wav"


def wave_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        return frames / rate if rate else 0.0


def write_wave(path: Path, pcm: bytes) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return wave_duration(path)


def build_prompt(narration: str) -> str:
    narration = normalize_narration(narration)
    return f"""Read the transcript exactly in natural American English.
Voice: calm, mature documentary narrator.
Tone: serious, respectful, measured, investigative.
Pace: 135-150 words per minute. Pause naturally after dates, names and key facts.
Do not add commentary or sound theatrical, sensational, excited or accusatory.

TRANSCRIPT:
{narration}""".strip()


def generate_voice(narration: str, output_path: Path) -> float:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    narration = normalize_narration(narration)
    if not narration:
        raise ValueError("Nội dung thuyết minh trống")

    client = genai.Client(api_key=GEMINI_API_KEY)
    interaction = client.interactions.create(
        model=TTS_MODEL,
        input=build_prompt(narration),
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": TTS_VOICE}]},
    )

    output_audio = getattr(interaction, "output_audio", None)
    if output_audio is None or not getattr(output_audio, "data", None):
        raise RuntimeError("Gemini không trả về dữ liệu âm thanh")

    pcm = base64.b64decode(output_audio.data)
    duration = write_wave(output_path, pcm)

    cache_path = cache_path_for(narration)
    if cache_path != output_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if not cache_path.exists():
            cache_path.write_bytes(output_path.read_bytes())

    return duration
