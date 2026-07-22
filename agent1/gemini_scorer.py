import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import GEMINI_API_KEY, GEMINI_MODEL
from utils import clamp

class CaseScore(BaseModel):
    is_real_case: bool
    is_unresolved: bool
    is_suitable: bool
    case_name: str = ""
    country: str = ""
    case_type: str = "other"
    case_status: str = "unknown"
    incident_year: int | None = None
    mystery_score: int = Field(ge=0, le=100)
    source_score: int = Field(ge=0, le=100)
    storytelling_score: int = Field(ge=0, le=100)
    audience_score: int = Field(ge=0, le=100)
    safety_score: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    short_summary: str = ""
    reason: str = ""

def score(item: dict) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
You are a careful research editor for an English-language documentary channel about unresolved cases.

Evaluate this discovery lead using only the supplied text. Do not invent facts or accuse anyone.

TITLE: {item.get('title','')}
SOURCE: {item.get('source_name','')}
PUBLISHED: {item.get('published_at','')}
SUMMARY: {item.get('summary','')}

Reject entertainment, fictional stories, solved cases, graphic exploitation, and legally risky speculation.
Score documentary potential for audiences in the US, UK, Canada, and Australia.
"""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=CaseScore,
        ),
    )
    parsed = json.loads(response.text)
    for k in ("mystery_score","source_score","storytelling_score","audience_score","safety_score","overall_score"):
        parsed[k] = clamp(parsed.get(k))
    return parsed
