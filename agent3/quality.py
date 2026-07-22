from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .config import TARGET_WORDS_MIN, TARGET_WORDS_MAX

TRANSITION_WORDS = {
    "however", "meanwhile", "later", "then", "although", "because",
    "investigators", "according", "reported", "confirmed", "today"
}

def normalize_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())

def local_quality_check(result: dict[str, Any], source_urls: set[str]) -> dict[str, Any]:
    script = str(result.get("script", "")).strip()
    hook = str(result.get("hook", "")).strip()
    disclaimer = str(result.get("disclaimer", "")).strip()
    claims = result.get("claims") or []
    words = normalize_words(script)
    word_count = len(words)

    issues: list[str] = []
    score = 100

    if not script:
        return {"score": 0, "passed": False, "issues": ["Kịch bản trống"]}

    if word_count < TARGET_WORDS_MIN:
        score -= min(30, 10 + (TARGET_WORDS_MIN - word_count) // 50)
        issues.append(f"Quá ngắn: {word_count}/{TARGET_WORDS_MIN}")
    elif word_count > TARGET_WORDS_MAX:
        score -= min(20, 5 + (word_count - TARGET_WORDS_MAX) // 100)
        issues.append(f"Quá dài: {word_count}/{TARGET_WORDS_MAX}")

    hook_words = normalize_words(hook)
    if not 35 <= len(hook_words) <= 95:
        score -= 8
        issues.append("Hook nên khoảng 35–95 từ")

    if len(disclaimer) < 30:
        score -= 5
        issues.append("Disclaimer quá ngắn")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
    if len(paragraphs) < 8:
        score -= 7
        issues.append("Kịch bản có quá ít đoạn")

    starts = []
    for p in paragraphs:
        first = " ".join(normalize_words(p)[:5])
        if first:
            starts.append(first)
    repeated_starts = sum(v - 1 for v in Counter(starts).values() if v > 1)
    if repeated_starts:
        score -= min(12, repeated_starts * 3)
        issues.append("Có đoạn mở đầu lặp lại")

    sentence_list = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if len(s.strip()) > 25]
    normalized_sentences = [" ".join(normalize_words(s)) for s in sentence_list]
    duplicate_sentences = len(normalized_sentences) - len(set(normalized_sentences))
    if duplicate_sentences:
        score -= min(15, duplicate_sentences * 5)
        issues.append("Có câu bị lặp")

    transition_hits = sum(1 for w in TRANSITION_WORDS if w in set(words))
    if transition_hits < 4:
        score -= 5
        issues.append("Mạch kể thiếu từ chuyển tiếp")

    bad_claims = 0
    for claim in claims:
        urls = set(claim.get("source_urls") or [])
        if not urls or not urls.issubset(source_urls):
            bad_claims += 1
    if bad_claims:
        score -= min(25, bad_claims * 5)
        issues.append(f"{bad_claims} claim không liên kết đúng nguồn")

    if not claims:
        score -= 15
        issues.append("Không có danh sách claim")

    score = max(0, min(100, score))
    return {
        "score": score,
        "passed": score >= 95,
        "issues": issues,
        "word_count": word_count,
        "paragraph_count": len(paragraphs),
        "claim_count": len(claims),
    }
