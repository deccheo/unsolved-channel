import base64
import io
import textwrap
from pathlib import Path

from google import genai
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from config import GEMINI_API_KEY, IMAGE_MODEL, WIDTH, HEIGHT, JPEG_QUALITY, MAX_FILE_BYTES


FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]

FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


def load_font(paths: list[str], size: int):
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)

    return ImageFont.load_default()


def title_from_case(case) -> str:
    keys = set(case.keys())

    for field in ("script_title", "case_name", "title"):
        if field in keys and case[field]:
            return str(case[field])

    return f"Unsolved Case {case['id']}"


def short_title(title: str) -> str:
    cleaned = " ".join(title.replace(":", " ").split())

    prefixes = [
        "The Disappearance of ",
        "The Unsolved Murder of ",
        "The Unresolved Murder of ",
        "The Search for ",
    ]

    for prefix in prefixes:
        cleaned = cleaned.replace(prefix, "")

    words = cleaned.split()

    if len(words) > 8:
        words = words[:8]

    return " ".join(words).upper()


def build_prompt(case, scene) -> str:
    title = title_from_case(case)
    visual = ""

    if scene is not None:
        visual = (
            scene["visual_prompt"]
            or scene["narration"]
            or ""
        )

    return f"""
Create a clean cinematic 16:9 YouTube documentary thumbnail background.

SUBJECT:
{title}

SCENE INSPIRATION:
{visual}

Composition requirements:
- Serious unresolved mystery documentary tone.
- One strong focal subject on the RIGHT half.
- Leave the LEFT 45 percent darker and visually simple for title text.
- High contrast, dramatic but respectful lighting.
- Realistic location, evidence object, anonymous silhouette, or atmospheric reconstruction.
- No recognizable real-person face.
- No text, letters, numbers, logos, watermarks, borders, police badges, or UI elements.
- No blood, gore, corpse, visible injury, or sensational violence.
- Do not imply that an uncharged person is guilty.
- Cinematic, sharp, premium YouTube documentary look.
""".strip()


def generate_background(case, scene) -> Image.Image:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    client = genai.Client(api_key=GEMINI_API_KEY)

    interaction = client.interactions.create(
        model=IMAGE_MODEL,
        input=build_prompt(case, scene),
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "16:9",
            "image_size": "1K",
        },
    )

    output_image = getattr(interaction, "output_image", None)

    if output_image is None or not getattr(output_image, "data", None):
        raise RuntimeError("Gemini không trả về ảnh thumbnail")

    raw = base64.b64decode(output_image.data)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def fallback_background(scene) -> Image.Image:
    if scene is None or not scene["image_path"]:
        raise RuntimeError("Không có ảnh cảnh để dùng làm dự phòng")

    path = Path(scene["image_path"])

    if not path.is_file():
        raise FileNotFoundError(f"Không thấy ảnh dự phòng: {path}")

    return Image.open(path).convert("RGB")


def fit_background(image: Image.Image) -> Image.Image:
    image = ImageOps.fit(
        image,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    image = ImageEnhance.Contrast(image).enhance(1.08)
    image = ImageEnhance.Color(image).enhance(0.90)
    image = ImageEnhance.Sharpness(image).enhance(1.10)

    return image


def add_overlay(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for x in range(int(WIDTH * 0.62)):
        ratio = x / max(1, int(WIDTH * 0.62))
        alpha = int(205 * (1.0 - ratio))
        draw.line([(x, 0), (x, HEIGHT)], fill=(0, 0, 0, alpha))

    draw.rectangle(
        [0, HEIGHT - 115, WIDTH, HEIGHT],
        fill=(0, 0, 0, 80),
    )

    return Image.alpha_composite(
        image.convert("RGBA"),
        overlay,
    )


def wrap_title(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font, stroke_width=2)

        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines[:4]


def compose_thumbnail(
    background: Image.Image,
    case,
    output_path: Path,
) -> None:
    canvas = add_overlay(fit_background(background))
    draw = ImageDraw.Draw(canvas)

    title = short_title(title_from_case(case))
    title_font = load_font(FONT_BOLD_CANDIDATES, 82)
    label_font = load_font(FONT_BOLD_CANDIDATES, 34)
    small_font = load_font(FONT_REGULAR_CANDIDATES, 25)

    lines = wrap_title(draw, title, title_font, 570)

    line_height = 91
    total_height = len(lines) * line_height
    y = max(105, (HEIGHT - total_height) // 2 - 25)

    draw.rounded_rectangle(
        [62, 48, 388, 102],
        radius=10,
        fill=(176, 22, 28, 235),
    )

    draw.text(
        (82, 56),
        "UNSOLVED CASE",
        font=label_font,
        fill=(255, 255, 255, 255),
    )

    for line in lines:
        draw.text(
            (65, y),
            line,
            font=title_font,
            fill=(255, 255, 255, 255),
            stroke_width=5,
            stroke_fill=(0, 0, 0, 240),
        )
        y += line_height

    draw.rectangle(
        [65, y + 16, 405, y + 24],
        fill=(211, 30, 38, 255),
    )

    draw.text(
        (65, HEIGHT - 78),
        "DOCUMENTARY • AI-GENERATED RECONSTRUCTION",
        font=small_font,
        fill=(235, 235, 235, 230),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 180),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(
        output_path,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
    )


def validate_thumbnail(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Thumbnail chưa được tạo: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise RuntimeError(f"Thumbnail vượt quá {MAX_FILE_BYTES} byte")
    with Image.open(path) as image:
        if image.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"Sai kích thước thumbnail: {image.size}")
        if image.mode not in ("RGB", "RGBA"):
            raise RuntimeError(f"Sai chế độ màu thumbnail: {image.mode}")
