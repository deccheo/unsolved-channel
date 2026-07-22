import base64
import wave
from pathlib import Path

from google import genai

from config import (
    GEMINI_API_KEY,
    TTS_MODEL,
    TTS_VOICE,
    SAMPLE_RATE,
    CHANNELS,
    SAMPLE_WIDTH,
)

def write_wave(path: Path, pcm: bytes) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)

    bytes_per_second = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
    return len(pcm) / bytes_per_second

def build_prompt(narration: str) -> str:
    narration = " ".join((narration or "").split())

    return f"""
# AUDIO PROFILE
A calm, mature documentary narrator.

# DIRECTOR'S NOTES
Read in natural American English.
Tone: serious, respectful, measured, investigative.
Pace: moderately slow, around 135 to 150 words per minute.
Use clear articulation and subtle suspense.
Do not sound theatrical, sensational, excited, or accusatory.
Pause naturally after dates, names, and important facts.
Read the transcript exactly without adding commentary.

# TRANSCRIPT
{narration}
""".strip()

def generate_voice(narration: str, output_path: Path) -> float:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    if not narration or not narration.strip():
        raise ValueError("Nội dung thuyết minh trống")

    client = genai.Client(api_key=GEMINI_API_KEY)

    interaction = client.interactions.create(
        model=TTS_MODEL,
        input=build_prompt(narration),
        response_format={"type": "audio"},
        generation_config={
            "speech_config": [
                {"voice": TTS_VOICE}
            ]
        },
    )

    output_audio = getattr(interaction, "output_audio", None)
    if output_audio is None or not getattr(output_audio, "data", None):
        raise RuntimeError("Gemini không trả về dữ liệu âm thanh")

    pcm = base64.b64decode(output_audio.data)
    return write_wave(output_path, pcm)
