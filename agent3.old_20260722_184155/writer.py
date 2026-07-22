import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    TARGET_WORDS_MIN,
    TARGET_WORDS_MAX,
)

class ScriptResult(BaseModel):
    title: str
    hook: str
    script: str
    disclaimer: str
    word_count: int = Field(ge=500, le=3500)

def write_script(case, sources) -> dict:
    source_blocks = []
    for i, source in enumerate(sources, 1):
        source_blocks.append(
            f"""SOURCE {i}
TITLE: {source['title']}
PUBLISHER: {source['source_name']}
URL: {source['url']}
RELIABILITY: {source['reliability_score']}
TEXT:
{source['extracted_text'][:9000]}
"""
        )

    prompt = f"""
You are an investigative documentary scriptwriter.

Write an original English-language YouTube documentary script
about this unresolved case.

CASE:
Name: {case['case_name'] or case['title']}
Country: {case['country']}
Year: {case['incident_year']}
Verified summary: {case['verified_summary']}
Known conflicts: {case['conflicts']}

VERIFIED SOURCES:
{chr(10).join(source_blocks)}

Strict rules:
- Use only supplied source material.
- Never invent evidence, dialogue, motives, dates, witnesses, or police statements.
- Never imply an uncharged person is guilty.
- Clearly distinguish confirmed facts, reported claims, and theories.
- If sources disagree, state that clearly.
- Avoid graphic descriptions.
- Tone: calm, suspenseful, respectful, factual.
- Audience: United States, United Kingdom, Canada, Australia.
- Target length: {TARGET_WORDS_MIN} to {TARGET_WORDS_MAX} words.
- Structure:
  1. Strong 15-25 second hook.
  2. Background.
  3. Chronological timeline.
  4. Evidence and investigation.
  5. Unanswered questions and sourced theories.
  6. Current status.
  7. Respectful ending.
- Include a short disclaimer.
"""

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": 120000},
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.25,
            response_mime_type="application/json",
            response_schema=ScriptResult,
        ),
    )

    result = json.loads(response.text)
    result["word_count"] = len(result.get("script","").split())
    return result
