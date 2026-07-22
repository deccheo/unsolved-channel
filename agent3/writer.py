from __future__ import annotations

import json
import time
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from .config import (
    GEMINI_API_KEY, GEMINI_MODEL, TARGET_WORDS_MIN, TARGET_WORDS_MAX,
    MIN_QA_SCORE, MAX_REWRITES
)
from .quality import local_quality_check

class ClaimItem(BaseModel):
    claim: str
    source_urls: list[str]
    confidence: str

class ScriptResult(BaseModel):
    title: str
    hook: str
    script: str
    disclaimer: str
    word_count: int = Field(default=0, ge=0, le=5000)
    claims: list[ClaimItem]

class QAResult(BaseModel):
    score: int = Field(ge=0, le=100)
    factual_grounding: int = Field(ge=0, le=100)
    structure: int = Field(ge=0, le=100)
    retention: int = Field(ge=0, le=100)
    sensitivity: int = Field(ge=0, le=100)
    passed: bool
    issues: list[str]
    rewrite_instructions: list[str]

def _generate_json(prompt: str, schema: type[BaseModel], temperature: float) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            # Client mới cho mỗi request, tránh tái sử dụng client đã đóng.
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

def build_source_context(sources: list[Any]) -> tuple[str, set[str]]:
    blocks: list[str] = []
    urls: set[str] = set()
    for i, source in enumerate(sources, 1):
        url = str(source["url"] or "").strip()
        if url:
            urls.add(url)
        blocks.append(
            f"""SOURCE {i}
TITLE: {source['title'] or ''}
PUBLISHER: {source['source_name'] or ''}
URL: {url}
RELIABILITY: {source['reliability_score']}
RELEVANCE: {source['relevance_score']}
TEXT:
{str(source['extracted_text'] or '')[:12000]}
"""
        )
    return "\n\n".join(blocks), urls

def draft_script(case: Any, sources: list[Any], rewrite_notes: list[str] | None = None) -> dict[str, Any]:
    source_context, _ = build_source_context(sources)
    rewrite = ""
    if rewrite_notes:
        rewrite = "\nMANDATORY REVISION NOTES:\n- " + "\n- ".join(rewrite_notes)

    prompt = f"""
You are a senior investigative-documentary writer for a high-retention YouTube channel.

CASE DATA:
Name: {_case_value(case, 'case_name') or _case_value(case, 'title')}
Country: {_case_value(case, 'country')}
Incident year: {_case_value(case, 'incident_year')}
Verified summary: {_case_value(case, 'verified_summary')}
Known conflicts: {_case_value(case, 'conflicts')}

VERIFIED SOURCE MATERIAL:
{source_context}

Create an original English-language documentary script.

NON-NEGOTIABLE FACTUAL RULES:
- Use only facts present in CASE DATA or VERIFIED SOURCE MATERIAL.
- Never invent dialogue, evidence, dates, motives, suspects, witnesses, police statements, or outcomes.
- Never imply guilt for an uncharged person.
- Label uncertainty using phrases such as "according to", "was reported", or "remains unconfirmed".
- When sources conflict, explain the disagreement.
- Every important factual claim in the claims array must cite one or more exact URLs supplied above.
- Avoid graphic detail and treat victims and families respectfully.

STORY AND RETENTION:
- Target {TARGET_WORDS_MIN}–{TARGET_WORDS_MAX} words.
- Hook: 35–95 words, intriguing but not sensational or misleading.
- Use a clear chronological timeline.
- Create curiosity through unanswered factual questions, not invented cliffhangers.
- Vary sentence and paragraph openings; avoid repetition.
- Structure: hook; person/background; timeline; investigation/evidence; conflicts and open questions; current status; respectful closing.
- Include a concise factual disclaimer.
- Script must be narration-ready and must not include production directions, citations in brackets, or headings like "Scene 1".
{rewrite}
"""
    result = _generate_json(prompt, ScriptResult, 0.25)
    result["script"] = str(result.get("script", "")).strip()
    result["word_count"] = len(result["script"].split())
    return result

def qa_script(case: Any, sources: list[Any], result: dict[str, Any]) -> dict[str, Any]:
    source_context, source_urls = build_source_context(sources)
    local = local_quality_check(result, source_urls)
    prompt = f"""
Act as a strict editorial quality controller. Evaluate this documentary script only against the supplied source material.

SOURCE MATERIAL:
{source_context}

SCRIPT:
TITLE: {result.get('title','')}
HOOK: {result.get('hook','')}
{result.get('script','')}
DISCLAIMER: {result.get('disclaimer','')}
CLAIMS JSON:
{json.dumps(result.get('claims', []), ensure_ascii=False)}

Score factual grounding, structure, audience retention, and sensitivity.
Fail the script if it invents facts, contains unsupported claims, makes defamatory implications, is repetitive, or materially misses the requested length.
The final score must reflect the weakest important dimension, not an average inflated by strong prose.
"""
    model_qa = _generate_json(prompt, QAResult, 0.0)
    combined_score = min(int(model_qa.get("score", 0)), int(local["score"]))
    issues = list(dict.fromkeys((model_qa.get("issues") or []) + local["issues"]))
    instructions = list(dict.fromkeys(model_qa.get("rewrite_instructions") or []))
    if local["issues"]:
        instructions.extend(f"Fix local QA: {x}" for x in local["issues"])
    return {
        **model_qa,
        "score": combined_score,
        "passed": bool(model_qa.get("passed")) and combined_score >= MIN_QA_SCORE,
        "issues": issues,
        "rewrite_instructions": list(dict.fromkeys(instructions)),
        "local_qa": local,
    }

def write_and_validate(case: Any, sources: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = draft_script(case, sources)
    qa = qa_script(case, sources, result)
    for _ in range(MAX_REWRITES):
        if qa["passed"]:
            break
        result = draft_script(case, sources, qa.get("rewrite_instructions") or qa.get("issues"))
        qa = qa_script(case, sources, result)
    return result, qa
