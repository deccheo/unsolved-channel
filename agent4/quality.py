from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .config import (
    MIN_SCENE_WORDS, MAX_SCENE_WORDS, MIN_SCENES, MAX_SCENES,
    MIN_QA_SCORE
)

def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(text).lower())

def _normalize(text: str) -> str:
    return " ".join(_words(text))

def local_quality_check(
    script_text: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[str] = []
    score = 100

    if not scenes:
        return {"score": 0, "passed": False, "issues": ["Không có cảnh"]}

    if len(scenes) < MIN_SCENES:
        score -= 20
        issues.append(f"Quá ít cảnh: {len(scenes)}/{MIN_SCENES}")
    if len(scenes) > MAX_SCENES:
        score -= 20
        issues.append(f"Quá nhiều cảnh: {len(scenes)}/{MAX_SCENES}")

    expected = list(range(1, len(scenes) + 1))
    actual = [int(s.get("scene_no", 0)) for s in scenes]
    if actual != expected:
        score -= 30
        issues.append("scene_no không liên tục từ 1")

    short_count = 0
    long_count = 0
    empty_prompt = 0
    short_prompt = 0
    bad_duration = 0

    narrations: list[str] = []
    prompts: list[str] = []

    for scene in scenes:
        narration = str(scene.get("narration", "")).strip()
        prompt = str(scene.get("visual_prompt", "")).strip()
        wc = len(_words(narration))
        if wc < MIN_SCENE_WORDS:
            short_count += 1
        if wc > MAX_SCENE_WORDS:
            long_count += 1
        if not prompt:
            empty_prompt += 1
        elif len(prompt) < 120:
            short_prompt += 1

        duration = float(scene.get("duration_seconds", 0) or 0)
        expected_duration = max(3.0, wc / 2.45)
        if duration < 2.5 or duration > 35 or abs(duration - expected_duration) > 8:
            bad_duration += 1

        narrations.append(_normalize(narration))
        prompts.append(_normalize(prompt))

    if short_count:
        score -= min(15, short_count * 2)
        issues.append(f"{short_count} cảnh quá ngắn")
    if long_count:
        score -= min(20, long_count * 3)
        issues.append(f"{long_count} cảnh quá dài")
    if empty_prompt:
        score -= min(30, empty_prompt * 10)
        issues.append(f"{empty_prompt} cảnh thiếu visual_prompt")
    if short_prompt:
        score -= min(12, short_prompt * 2)
        issues.append(f"{short_prompt} prompt quá ngắn")
    if bad_duration:
        score -= min(10, bad_duration)
        issues.append(f"{bad_duration} duration không hợp lý")

    narration_duplicates = len(narrations) - len(set(narrations))
    if narration_duplicates:
        score -= min(20, narration_duplicates * 5)
        issues.append("Có narration trùng")

    prompt_duplicates = len(prompts) - len(set(prompts))
    if prompt_duplicates:
        score -= min(20, prompt_duplicates * 4)
        issues.append("Có visual_prompt trùng")

    script_words = _words(script_text)
    combined_words = _words(" ".join(str(s.get("narration", "")) for s in scenes))
    if script_words:
        coverage = min(len(combined_words), len(script_words)) / len(script_words)
    else:
        coverage = 0.0

    # Scene narration may remove headings/formatting, but must retain almost all story text.
    if coverage < 0.92:
        score -= min(35, int((0.92 - coverage) * 100))
        issues.append(f"Độ bao phủ narration thấp: {coverage:.1%}")
    elif coverage > 1.15:
        score -= 15
        issues.append(f"Narration dài bất thường so với script: {coverage:.1%}")

    # Check sequence overlap to detect a rewrite rather than a split.
    script_vocab = set(script_words)
    combined_vocab = set(combined_words)
    overlap = len(script_vocab & combined_vocab) / max(1, len(script_vocab))
    if overlap < 0.80:
        score -= 25
        issues.append(f"Từ vựng narration lệch script: overlap={overlap:.1%}")

    continuity_keys = [
        str(s.get("continuity_key", "")).strip()
        for s in scenes
        if str(s.get("continuity_key", "")).strip()
    ]
    if len(continuity_keys) < max(1, len(scenes) // 3):
        score -= 5
        issues.append("Thiếu continuity_key cho nhân vật/bối cảnh lặp lại")

    score = max(0, min(100, score))
    return {
        "score": score,
        "passed": score >= MIN_QA_SCORE,
        "issues": issues,
        "scene_count": len(scenes),
        "script_word_count": len(script_words),
        "narration_word_count": len(combined_words),
        "coverage": round(coverage, 4),
        "vocabulary_overlap": round(overlap, 4),
    }
