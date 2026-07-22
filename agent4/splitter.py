from __future__ import annotations

import json
import time
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from .config import (
    GEMINI_API_KEY, GEMINI_MODEL, TARGET_SCENE_WORDS,
    MIN_SCENE_WORDS, MAX_SCENE_WORDS, MIN_SCENES, MAX_SCENES,
    MAX_REWRITES, PROMPT_VERSION
)
from .quality import local_quality_check

class SceneItem(BaseModel):
    scene_no: int = Field(ge=1, le=200)
    narration: str
    visual_prompt: str
    negative_prompt: str
    duration_seconds: float = Field(ge=2.5, le=35)
    transition: str
    camera_direction: str
    location: str
    time_period: str
    characters: list[str]
    continuity_key: str
    source_claims: list[str]

class ScenePlan(BaseModel):
    scenes: list[SceneItem]

def _generate_json(prompt: str, schema: type[BaseModel], temperature: float) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise RuntimeError("Gemini trả phản hồi trống")
            return json.loads(text)
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Gemini thất bại sau 3 lần: {last_error}")

def _case_value(case: Any, key: str, default: str = "") -> str:
    try:
        value = case[key]
    except Exception:
        value = default
    return "" if value is None else str(value)

def _claim_context(claims: list[dict[str, Any]]) -> str:
    if not claims:
        return "No structured claims were stored; use only the script text."
    return json.dumps(claims, ensure_ascii=False, indent=2)

def _build_prompt(
    case: Any,
    claims: list[dict[str, Any]],
    rewrite_notes: list[str] | None = None,
) -> str:
    script = _case_value(case, "script_text")
    estimated = max(MIN_SCENES, min(MAX_SCENES, round(len(script.split()) / TARGET_SCENE_WORDS)))
    rewrite = ""
    if rewrite_notes:
        rewrite = "\nMANDATORY CORRECTIONS:\n- " + "\n- ".join(rewrite_notes)

    return f"""
You are the scene director and visual continuity editor for a factual YouTube investigative documentary.

CASE TITLE:
{_case_value(case, 'script_title') or _case_value(case, 'case_name') or _case_value(case, 'title')}

APPROVED SCRIPT:
{script}

FACT CLAIM REGISTER:
{_claim_context(claims)}

TASK:
Split the approved script into approximately {estimated} chronological scenes.
The narration fields, read in scene order, must preserve the complete approved script.
Do not summarize, rewrite, add facts, add dialogue, or remove important details.

SCENE RULES:
- scene_no must be continuous starting at 1.
- Each narration should normally contain {MIN_SCENE_WORDS}–{MAX_SCENE_WORDS} words.
- Split at natural sentence or paragraph boundaries.
- Estimate duration_seconds from narration at about 145–155 spoken words per minute.
- Keep the timeline and emotional pacing clear.
- Avoid graphic depictions, victim exploitation, sensationalism, and implied guilt.

VISUAL PROMPT RULES:
- Write each visual_prompt in English for a cinematic 16:9 documentary still.
- It must be specific enough for an image model: subject, environment, era, lighting, composition, lens/camera angle, mood, realistic materials, and documentary authenticity.
- No readable text, logos, watermarks, captions, UI, maps with labels, gore, weapons being used, or identifiable real-person likeness unless the script explicitly and safely requires a generic public setting.
- For uncertain or sensitive events, use respectful symbolic/environmental reconstruction rather than depicting an accusation as fact.
- Maintain visual identity across scenes by repeating stable descriptors in characters and continuity_key.
- Avoid identical prompts and vary establishing shot, medium shot, close-up, detail shot, and atmospheric cutaway.
- negative_prompt must explicitly exclude text, watermark, malformed anatomy, duplicate people, graphic violence, and anachronisms.
- source_claims should list short claim texts from the FACT CLAIM REGISTER that directly support the scene; it may be empty for purely atmospheric transitions.
- prompt_version for every scene will be added by code.
{rewrite}
"""

def create_scene_plan(
    case: Any,
    claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    notes: list[str] | None = None
    best_scenes: list[dict[str, Any]] = []
    best_qa: dict[str, Any] = {"score": 0, "passed": False, "issues": ["Chưa chạy"]}

    for _ in range(MAX_REWRITES + 1):
        raw = _generate_json(_build_prompt(case, claims, notes), ScenePlan, 0.15)
        scenes = raw.get("scenes") or []

        normalized: list[dict[str, Any]] = []
        for index, scene in enumerate(scenes, 1):
            item = dict(scene)
            item["scene_no"] = index
            item["narration"] = str(item.get("narration", "")).strip()
            item["visual_prompt"] = str(item.get("visual_prompt", "")).strip()
            item["negative_prompt"] = str(item.get("negative_prompt", "")).strip()
            item["transition"] = str(item.get("transition", "cut")).strip() or "cut"
            item["camera_direction"] = str(item.get("camera_direction", "")).strip()
            item["location"] = str(item.get("location", "")).strip()
            item["time_period"] = str(item.get("time_period", "")).strip()
            item["characters"] = [
                str(x).strip() for x in (item.get("characters") or []) if str(x).strip()
            ]
            item["continuity_key"] = str(item.get("continuity_key", "")).strip()
            item["source_claims"] = [
                str(x).strip() for x in (item.get("source_claims") or []) if str(x).strip()
            ]
            words = len(item["narration"].split())
            item["duration_seconds"] = round(max(3.0, min(35.0, words / 2.5)), 2)
            item["prompt_version"] = PROMPT_VERSION
            normalized.append(item)

        qa = local_quality_check(_case_value(case, "script_text"), normalized)
        if qa["score"] > best_qa["score"]:
            best_scenes, best_qa = normalized, qa
        if qa["passed"]:
            return normalized, qa
        notes = qa["issues"]

    return best_scenes, best_qa
