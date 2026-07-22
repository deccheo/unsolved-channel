import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import GEMINI_API_KEY, GEMINI_MODEL


class Verification(BaseModel):
    real_case: bool
    unresolved: bool
    enough_sources: bool
    source_count_used: int
    verification_score: int = Field(ge=0, le=100)
    verified_summary: str
    confirmed_facts: list[str]
    unsupported_claims: list[str]
    conflicts: list[str]
    legal_risk: str
    recommendation: str


def verify(case, sources) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError('Thiếu GEMINI_API_KEY')

    client = genai.Client(api_key=GEMINI_API_KEY)
    source_text = []
    for i, source in enumerate(sources, 1):
        source_text.append(
            f"SOURCE {i}\nTITLE: {source['title']}\nPUBLISHER: {source['source_name']}\n"
            f"URL: {source['url']}\nRELIABILITY: {source['reliability_score']}\n"
            f"TEXT: {(source['extracted_text'] or '')[:7000]}"
        )

    prompt = f'''You are a strict but practical fact-checking editor for an English documentary channel.

CASE LEAD:
Name: {case['case_name'] or case['title']}
Country: {case['country'] or ''}
Initial summary: {case['ai_summary'] or case['article_summary'] or ''}

SOURCES:
{chr(10).join(source_text)}

Rules:
- Use only supplied sources.
- real_case=true only for a real person or real criminal investigation.
- unresolved=true only if the latest supplied source still shows the core case is open.
- enough_sources=true requires one official + one independent source, or at least two independent reliable news sources.
- Put uncertain details in unsupported_claims instead of inventing facts.
- Never accuse an uncharged person.
- legal_risk must be LOW, MEDIUM, or HIGH.
- recommendation must be VERIFIED, NEEDS_REVIEW, or REJECTED.
'''

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type='application/json',
            response_schema=Verification,
        ),
    )
    result = json.loads(response.text)
    result['recommendation'] = str(result.get('recommendation','NEEDS_REVIEW')).strip().upper()
    result['legal_risk'] = str(result.get('legal_risk','MEDIUM')).strip().upper()
    return result
