import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import (
    GEMINI_API_KEY, GEMINI_MODEL, TARGET_SCENE_SECONDS,
    MIN_SCENES, MAX_SCENES
)

class SceneItem(BaseModel):
    scene_no: int
    narration: str
    duration_seconds: float = Field(ge=3, le=20)
    visual_type: str
    visual_prompt: str
    on_screen_text: str = ""
    source_note: str = ""
    disclaimer_label: str = ""

class ScenePlan(BaseModel):
    scenes: list[SceneItem]

def plan(case) -> list[dict]:
    prompt = f"""
You are a documentary scene planner.

Create a complete scene-by-scene plan for this English-language unresolved-case documentary.

TITLE:
{case['script_title']}

HOOK:
{case['script_hook']}

SCRIPT:
{case['script_text']}

Rules:
- Produce between {MIN_SCENES} and {MAX_SCENES} scenes.
- Average scene length around {TARGET_SCENE_SECONDS} seconds.
- Keep narration in exact chronological order.
- Split narration naturally; do not omit major facts.
- visual_type must be one of:
  map, timeline, document, evidence_object, location_reconstruction,
  atmospheric_broll, portrait_placeholder, text_card.
- visual_prompt must describe an original cinematic 16:9 image.
- Never request graphic injury, corpses, blood, gore, or sensational violence.
- Never visually identify an uncharged suspect as guilty.
- For real people, prefer portrait_placeholder unless an authorized photo is available.
- For reconstructed imagery, use disclaimer_label:
  "Dramatized illustration" or "AI-generated reconstruction".
- For maps, timelines, documents, and text cards, disclaimer_label can be empty.
- on_screen_text should be short and factual.
- source_note should identify which part of the script supports the scene.
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=ScenePlan,
        ),
    )

    result = json.loads(response.text)
    scenes = result.get("scenes", [])

    for index, scene in enumerate(scenes, start=1):
        scene["scene_no"] = index

    return scenes
