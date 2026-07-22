import json
import re
import time
from typing import Any

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL
from utils import clamp


API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

SYSTEM_TEXT = """
You are a careful research editor for an English-language documentary
channel about unresolved cases.

Your task is to classify and score proposed topics.

You must not invent facts.
You must not accuse any person.
You must not state that a case is unresolved unless the supplied
material supports that conclusion.

Treat the supplied text only as a discovery lead, not as verified evidence.
Return valid JSON only. Do not include Markdown.
""".strip()


def build_prompt(article: dict) -> str:
    return f"""
Evaluate this discovery lead for a factual English-language YouTube
documentary channel about unresolved cases.

ARTICLE TITLE:
{article.get("title", "")}

SOURCE:
{article.get("source_name", "")}

PUBLISHED:
{article.get("published_at", "")}

ARTICLE SUMMARY:
{article.get("summary", "")}

SEARCH QUERY:
{article.get("search_query", article.get("query", ""))}

Determine whether it appears to concern a real unresolved case.

Return exactly this JSON structure:

{{
  "is_real_case": true,
  "is_unresolved": true,
  "is_suitable": true,
  "requires_review": true,
  "case_name": "",
  "country": "",
  "case_type": "missing_person|unsolved_homicide|unidentified_person|other",
  "case_status": "unresolved|possibly_unresolved|solved|unknown",
  "incident_year": null,
  "mystery_score": 0,
  "source_score": 0,
  "storytelling_score": 0,
  "audience_score": 0,
  "safety_score": 0,
  "overall_score": 0,
  "short_summary": "",
  "reason": ""
}}

Scoring guidance:
- mystery_score: strength of the unresolved mystery.
- source_score: reliability suggested by the supplied source.
- storytelling_score: ability to support an 8–15 minute documentary.
- audience_score: likely interest for US, UK, Canada, Australia.
- safety_score: suitability for respectful, non-graphic treatment.
- overall_score: production potential.

Reject entertainment stories, fictional works, movie reviews, podcasts,
and cases that appear solved.
""".strip()


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise ValueError("Gemini không trả về JSON hợp lệ")
        return json.loads(match.group(0))


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    score_fields = (
        "mystery_score",
        "source_score",
        "storytelling_score",
        "audience_score",
        "safety_score",
        "overall_score",
    )

    for field in score_fields:
        result[field] = clamp(result.get(field))

    for field in (
        "is_real_case",
        "is_unresolved",
        "is_suitable",
        "requires_review",
    ):
        result[field] = bool(result.get(field, False))

    try:
        year = int(result.get("incident_year"))
        result["incident_year"] = year if 1800 <= year <= 2100 else None
    except (TypeError, ValueError):
        result["incident_year"] = None

    return result


def score_article(article: dict) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_TEXT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": build_prompt(article)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    last_error = None

    for attempt in range(1, 4):
        try:
            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=(10, 45),
            )
            response.raise_for_status()

            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            return normalize_result(extract_json(text))

        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 3)

    raise RuntimeError(f"Gemini lỗi sau 3 lần thử: {last_error}")

# Tương thích với main.py hiện tại
def score(article):
    return score_article(article)
