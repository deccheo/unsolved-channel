import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from config import (
    DEFAULT_CATEGORY_ID,
    DEFAULT_LANGUAGE,
    DEFAULT_PRIVACY,
    DESCRIPTION_DIR,
    MAX_SOURCE_CHARS,
    METADATA_DIR,
    TAG_DIR,
    TITLE_DIR,
)
from gemini_client import generate_metadata


def clean_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def normalize_hashtag(value: Any) -> str:
    tag = re.sub(r'[^A-Za-z0-9_]', '', clean_text(value).lstrip('#'))
    return f'#{tag}' if tag else ''


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _trim_tags(tags: list[str], max_total: int = 430) -> list[str]:
    output: list[str] = []
    total = 0
    for tag in tags:
        cost = len(tag) + (2 if output else 0)
        if total + cost > max_total:
            break
        output.append(tag)
        total += cost
    return output


def _normalize_chapters(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        timecode = clean_text(item.get('time') or item.get('timecode'))
        label = clean_text(item.get('title') or item.get('label'))
        if re.fullmatch(r'(?:\d{1,2}:)?\d{1,2}:\d{2}', timecode) and label:
            output.append({'time': timecode, 'title': label[:80]})
    return output


def normalize(data: dict[str, Any], fallback_title: str) -> dict[str, Any]:
    titles = data.get('title_options') or data.get('titles') or []
    if isinstance(titles, str):
        titles = [titles]
    titles = _unique([clean_text(x)[:100] for x in titles if clean_text(x)])

    selected = clean_text(data.get('title') or (titles[0] if titles else fallback_title))[:100]
    selected = selected or fallback_title[:100] or 'Untold Mystery'
    title_options = _unique([selected, *titles])[:3]

    description = str(data.get('description') or '').strip()[:5000]
    tags = data.get('tags') or []
    hashtags = data.get('hashtags') or []
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(',')]
    if isinstance(hashtags, str):
        hashtags = [x.strip() for x in hashtags.replace(',', ' ').split()]

    normalized_tags = _trim_tags(_unique([clean_text(x)[:60] for x in tags if clean_text(x)]))[:25]
    normalized_hashtags = _unique([normalize_hashtag(x) for x in hashtags if normalize_hashtag(x)])[:8]
    chapters = _normalize_chapters(data.get('chapters'))

    if normalized_hashtags and not any(tag in description for tag in normalized_hashtags):
        suffix = ' '.join(normalized_hashtags)
        description = (description.rstrip() + '\n\n' + suffix).strip()[:5000]

    return {
        'title': selected,
        'title_options': title_options,
        'description': description,
        'tags': normalized_tags,
        'hashtags': normalized_hashtags,
        'chapters': chapters,
        'categoryId': str(data.get('categoryId') or data.get('category') or DEFAULT_CATEGORY_ID),
        'defaultLanguage': clean_text(data.get('defaultLanguage') or DEFAULT_LANGUAGE),
        'privacyStatus': clean_text(data.get('privacyStatus') or DEFAULT_PRIVACY).lower(),
        'madeForKids': bool(data.get('madeForKids', False)),
        'primary_keyword': clean_text(data.get('primary_keyword')),
    }


def _source_summary(source: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ('summary', 'synopsis', 'description', 'story', 'script', 'script_text', 'content'):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    scenes = source.get('scenes')
    if isinstance(scenes, list):
        scene_text = []
        for scene in scenes[:80]:
            if isinstance(scene, dict):
                text = clean_text(scene.get('narration') or scene.get('text') or scene.get('summary'))
                if text:
                    scene_text.append(text)
        if scene_text:
            values.append(' '.join(scene_text))
    result = '\n\n'.join(values)
    return result[:MAX_SOURCE_CHARS]


def build_prompt(source: dict[str, Any], slug: str) -> str:
    title = clean_text(source.get('title') or source.get('story_title') or source.get('name') or slug.replace('-', ' '))
    summary = _source_summary(source)
    source_type = clean_text(source.get('story_type') or source.get('content_type') or 'unknown')

    return f'''You are Agent 9 for an English-language YouTube mystery storytelling channel.

Create high-quality YouTube metadata that is compelling, searchable, truthful, and safe.
Never present fiction, dramatization, reconstruction, or AI-generated material as verified fact.
Do not accuse an uncharged real person, invent evidence, use graphic wording, or make misleading claims.
Use natural American English. Avoid keyword stuffing and repeated phrases.

SEO requirements:
- Final title: 55-85 characters when practical, hard maximum 100.
- Provide exactly 3 distinct title options.
- Description: 900-1800 characters, hook first, concise story overview, responsible disclaimer when needed, and one brief CTA.
- 15-25 focused tags; total tag text must remain below YouTube limits.
- 5-8 relevant hashtags.
- categoryId 24, defaultLanguage en, privacyStatus {DEFAULT_PRIVACY}, madeForKids false.
- Chapters may be returned only when source material contains reliable timing; otherwise return an empty list.
- Return one JSON object only, with no Markdown.

STORY ID: {slug}
SOURCE TYPE: {source_type}
WORKING TITLE: {title}
SOURCE CONTENT:
{summary}

JSON schema:
{{
  "title": "best final title",
  "title_options": ["option 1", "option 2", "option 3"],
  "description": "complete YouTube description",
  "tags": ["15 to 25 relevant tags"],
  "hashtags": ["5 to 8 hashtags"],
  "chapters": [],
  "primary_keyword": "main search phrase",
  "categoryId": "24",
  "defaultLanguage": "en",
  "privacyStatus": "{DEFAULT_PRIVACY}",
  "madeForKids": false
}}'''.strip()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def save_metadata(slug: str, metadata: dict[str, Any]) -> Path:
    metadata_path = METADATA_DIR / f'{slug}.json'
    _atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    _atomic_write(TITLE_DIR / f'{slug}.txt', '\n'.join(metadata['title_options']) + '\n')
    _atomic_write(DESCRIPTION_DIR / f'{slug}.txt', metadata['description'].rstrip() + '\n')
    _atomic_write(TAG_DIR / f'{slug}.txt', ', '.join(metadata['tags']) + '\n' + ' '.join(metadata['hashtags']) + '\n')
    return metadata_path


def metadata_is_valid(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and 1 <= len(clean_text(data.get('title'))) <= 100
        and isinstance(data.get('description'), str)
        and isinstance(data.get('tags'), list)
        and data.get('story_id')
        and data.get('source_fingerprint')
    )


def source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f'sha256:{digest}'


def generate_for_source(source_path: Path, slug: str, fingerprint: str) -> tuple[Path, int, int]:
    source = json.loads(source_path.read_text(encoding='utf-8'))
    fallback_title = clean_text(source.get('title') or source.get('story_title') or slug.replace('-', ' '))
    raw, calls, retries = generate_metadata(build_prompt(source, slug))
    metadata = normalize(raw, fallback_title)
    metadata.update({
        'source_file': str(source_path),
        'source_fingerprint': fingerprint,
        'story_id': slug,
        'generator': 'agent9-turbo',
    })
    return save_metadata(slug, metadata), calls, retries
