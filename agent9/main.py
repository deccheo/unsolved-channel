#!/usr/bin/env python3
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, LOG_DIR, MAX_ITEMS_PER_RUN, METADATA_DIR, OUTPUT_DIR, STATE_FILE
from generator import generate_for_source, metadata_is_valid, source_fingerprint

LOG_FILE = LOG_DIR / 'agent9.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()],
)
log = logging.getLogger('agent9')


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return value.strip('-') or 'story'


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {'processed': {}, 'failed': {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'processed': {}, 'failed': {}}
    except Exception:
        corrupt = STATE_FILE.with_suffix('.corrupt.json')
        try:
            os.replace(STATE_FILE, corrupt)
        except OSError:
            pass
        return {'processed': {}, 'failed': {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.state.', dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, STATE_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def discover_sources() -> list[tuple[Path, str]]:
    folders = [OUTPUT_DIR / 'scripts', OUTPUT_DIR / 'stories', BASE_DIR / 'agent2' / 'output']
    candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    for folder in folders:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob('*.json')):
            resolved = path.resolve()
            if resolved in seen or path.parent == METADATA_DIR or path.name == 'state.json':
                continue
            seen.add(resolved)
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            keys = {str(key).lower() for key in data.keys()}
            if not keys.intersection({'title', 'story_title', 'story', 'script', 'script_text', 'summary', 'synopsis', 'scenes'}):
                continue
            raw_id = str(data.get('id') or data.get('story_id') or data.get('slug') or (path.parent.name if path.name == 'metadata.json' else path.stem))
            candidates.append((path, slugify(raw_id)))
    return candidates


def main() -> int:
    started = time.monotonic()
    state = load_state()
    processed = state.setdefault('processed', {})
    failed = state.setdefault('failed', {})
    stats = {'sources': 0, 'created': 0, 'reuse': 0, 'api_calls': 0, 'retry': 0, 'errors': 0}

    sources = discover_sources()
    stats['sources'] = len(sources)
    log.info('Agent 9 TURBO bắt đầu | nguồn=%s | tối đa=%s', len(sources), MAX_ITEMS_PER_RUN)
    if not sources:
        log.warning('Không tìm thấy nguồn truyện JSON phù hợp.')
        return 0

    for source_path, slug in sources:
        if stats['created'] >= MAX_ITEMS_PER_RUN:
            break
        key = str(source_path.resolve())
        metadata_path = METADATA_DIR / f'{slug}.json'
        try:
            fingerprint = source_fingerprint(source_path)
        except OSError as exc:
            stats['errors'] += 1
            log.error('Không đọc được nguồn %s: %s', source_path, exc)
            continue

        if metadata_is_valid(metadata_path) and processed.get(key) == fingerprint:
            stats['reuse'] += 1
            log.info('REUSE | %s | %s', slug, metadata_path)
            continue

        try:
            log.info('Tạo SEO | %s | %s', slug, source_path)
            result, calls, retries = generate_for_source(source_path, slug, fingerprint)
            stats['api_calls'] += calls
            stats['retry'] += retries
            stats['created'] += 1
            processed[key] = fingerprint
            failed.pop(key, None)
            state['last_success'] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            log.info('DONE | %s | API=%s | retry=%s | %s', slug, calls, retries, result)
        except Exception as exc:
            stats['errors'] += 1
            failed[key] = {
                'error': str(exc)[:2000],
                'at': datetime.now(timezone.utc).isoformat(),
            }
            save_state(state)
            log.exception('Lỗi khi xử lý %s', source_path)

    elapsed = time.monotonic() - started
    log.info(
        'THỐNG KÊ AGENT 9 | nguồn=%s | tạo mới=%s | reuse=%s | API calls=%s | retry=%s | lỗi=%s | tổng=%.2fs',
        stats['sources'], stats['created'], stats['reuse'], stats['api_calls'], stats['retry'], stats['errors'], elapsed,
    )
    log.info('Agent 9 TURBO hoàn thành')
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
