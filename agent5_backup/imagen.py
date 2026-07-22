import base64
import io
from pathlib import Path

from google import genai
from PIL import Image

from config import (
    GEMINI_API_KEY,
    IMAGE_MODEL,
    IMAGE_SIZE,
    ASPECT_RATIO,
)


def build_prompt(scene) -> str:
    data = dict(scene)

    visual_type = data.get("visual_type") or "atmospheric_broll"
    visual_prompt = data.get("visual_prompt") or data.get("narration") or ""
    camera_direction = data.get("camera_direction") or "cinematic wide shot"
    negative_prompt = data.get("negative_prompt") or (
        "gore, blood, corpse, injury, watermark, logo, text artifacts, "
        "distorted anatomy, extra fingers, deformed face, low quality"
    )

    return f"""
Create one original cinematic documentary image in 16:9.

SCENE TYPE:
{visual_type}

VISUAL PROMPT:
{visual_prompt}

CAMERA DIRECTION:
{camera_direction}

NEGATIVE PROMPT:
{negative_prompt}

Strict requirements:
- Realistic, cinematic, restrained true-crime documentary style.
- No text, captions, logos, watermarks, timestamps, or interface elements.
- No blood, gore, corpse, visible injury, weapons being used, or sensational violence.
- Do not portray an uncharged real person as guilty.
- Avoid recognizable real faces; use anonymous silhouettes, hands, locations, objects,
  documents, maps, and atmospheric reconstructions.
- If a person is needed, use a generic non-identifiable figure.
- Preserve visual consistency with a muted, natural color palette.
- High detail, clean composition, suitable for a YouTube documentary.
""".strip()


def generate_image(scene, output_path: Path) -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    client = genai.Client(api_key=GEMINI_API_KEY)

    interaction = client.interactions.create(
        model=IMAGE_MODEL,
        input=build_prompt(scene),
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": ASPECT_RATIO,
            "image_size": IMAGE_SIZE,
        },
    )

    generated = getattr(interaction, "output_image", None)
    if generated is None or not getattr(generated, "data", None):
        raise RuntimeError("Gemini không trả về dữ liệu ảnh")

    raw = base64.b64decode(generated.data)
    image = Image.open(io.BytesIO(raw)).convert("RGB")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=92, optimize=True)
