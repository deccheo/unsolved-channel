import json
import logging
import time
from typing import Callable

from pydantic import BaseModel, Field

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MAX_ATTEMPTS, GEMINI_RETRY_SECONDS


class Verification(BaseModel):
    real_case: bool
    unresolved: bool
    enough_sources: bool
    source_count_used: int = Field(ge=0)
    verification_score: int = Field(ge=0, le=100)
    verified_summary: str
    confirmed_facts: list[str]
    unsupported_claims: list[str]
    conflicts: list[str]
    legal_risk: str
    recommendation: str


def _new_client():
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)


def _is_closed_client_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "client has been closed" in text or "cannot send a request" in text


def _generate_with_fresh_client(prompt: str, client_factory: Callable = _new_client):
    from google.genai import types

    last_error: Exception | None = None
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        try:
            # Mỗi lần thử dùng một client mới và giữ client sống đến khi request hoàn tất.
            # Context manager đóng tài nguyên đúng lúc sau khi nhận response.
            with client_factory() as client:
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=Verification,
                    ),
                )
        except Exception as exc:
            last_error = exc
            retryable = _is_closed_client_error(exc) or attempt < GEMINI_MAX_ATTEMPTS
            logging.warning(
                "Gemini lỗi lần %s/%s: %s",
                attempt,
                GEMINI_MAX_ATTEMPTS,
                exc,
            )
            if not retryable or attempt >= GEMINI_MAX_ATTEMPTS:
                break
            time.sleep(GEMINI_RETRY_SECONDS * attempt)

    assert last_error is not None
    raise RuntimeError(
        f"Gemini thất bại sau {GEMINI_MAX_ATTEMPTS} lần thử: {last_error}"
    ) from last_error


def verify(case, sources, client_factory: Callable = _new_client) -> dict:
    if not sources:
        raise ValueError("Không có nguồn để kiểm chứng")

    source_text = []
    for i, source in enumerate(sources, 1):
        source_text.append(
            f"SOURCE {i}\n"
            f"TITLE: {source['title']}\n"
            f"PUBLISHER: {source['source_name']}\n"
            f"URL: {source['url']}\n"
            f"RELIABILITY: {source['reliability_score']}\n"
            f"RELEVANCE: {source['relevance_score']}\n"
            f"TEXT: {(source['extracted_text'] or '')[:7000]}"
        )

    prompt = f"""You are a strict fact-checking editor for an English documentary channel. Use only supplied sources.
CASE: {case['case_name'] or case['title']} | COUNTRY: {case['country'] or ''}
INITIAL SUMMARY: {case['ai_summary'] or case['article_summary'] or ''}
SOURCES:
{chr(10).join(source_text)}
Rules:
- real_case=true only for a real person or criminal investigation.
- unresolved=true only when the latest evidence says the core case remains open.
- enough_sources=true for one official source, one reputable detailed news source, or two independent secondary sources.
- Never accuse an uncharged person. Put uncertainty in unsupported_claims.
- recommendation: VERIFIED, NEEDS_REVIEW, or REJECTED. legal_risk: LOW, MEDIUM, or HIGH.
"""

    response = _generate_with_fresh_client(prompt, client_factory=client_factory)
    if not getattr(response, "text", None):
        raise RuntimeError("Gemini trả về nội dung rỗng")

    result = Verification.model_validate(json.loads(response.text)).model_dump()
    result["recommendation"] = result["recommendation"].strip().upper()
    result["legal_risk"] = result["legal_risk"].strip().upper()
    if result["recommendation"] not in {"VERIFIED", "NEEDS_REVIEW", "REJECTED"}:
        result["recommendation"] = "NEEDS_REVIEW"
    if result["legal_risk"] not in {"LOW", "MEDIUM", "HIGH"}:
        result["legal_risk"] = "MEDIUM"
    result["source_count_used"] = min(result["source_count_used"], len(sources))
    return result
