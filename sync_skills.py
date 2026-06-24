#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_DEST_DIR = '.claude/skills'
STATE_FILE = '.sync-state.json'


@dataclass(frozen=True)
class Config:
    manifest_url: str
    api_token: str | None
    destination_dir: str
    timeout_seconds: float
    insecure_tls: bool


def main() -> int:
    try:
        config = get_config()
        manifest = fetch_manifest(config)
        validate_manifest(manifest)

        destination_root = Path.cwd() / config.destination_dir
        destination_root.mkdir(parents=True, exist_ok=True)

        previous_state = load_state(destination_root)
        next_state: dict[str, str] = {}
        written_files: list[str] = []

        for skill in manifest['skills']:
            relative_path = normalize_relative_path(skill['path'])
            target_path = resolve_target_path(destination_root, relative_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            content = fetch_skill_content(skill, config, manifest.get('baseUrl'))
            content_hash = sha256(content)
            next_state[relative_path] = content_hash

            if previous_state.get(relative_path) != content_hash:
                target_path.write_text(content, encoding='utf-8')
                written_files.append(relative_path)

        removed_files = remove_stale_files(destination_root, previous_state, next_state)
        save_state(destination_root, next_state)

        log_summary(
            manifest_version=manifest.get('version', 'unknown'),
            destination_root=destination_root,
            total=len(manifest['skills']),
            written_files=written_files,
            removed_files=removed_files,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f'[skill-sync] {format_error(exc)}', file=sys.stderr)
        return 1


def get_config() -> Config:
    manifest_url = os.environ.get('SKILL_MANIFEST_URL')
    if not manifest_url:
        raise ValueError('SKILL_MANIFEST_URL is required.')

    return Config(
        manifest_url=manifest_url,
        api_token=os.environ.get('SKILL_API_TOKEN'),
        destination_dir=os.environ.get('SKILL_DEST_DIR', DEFAULT_DEST_DIR),
        timeout_seconds=parse_timeout(os.environ.get('SKILL_SYNC_TIMEOUT_MS'), 15.0),
        insecure_tls=os.environ.get('SKILL_SYNC_INSECURE_TLS') == '1',
    )


def fetch_manifest(config: Config) -> dict[str, Any]:
    raw = fetch_text(config.manifest_url, config)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Manifest response is not valid JSON: {exc.msg}.') from exc


def validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ValueError('Manifest must be a JSON object.')

    skills = manifest.get('skills')
    if not isinstance(skills, list):
        raise ValueError('Manifest must contain a skills array.')

    for skill in skills:
        if not isinstance(skill, dict):
            raise ValueError('Each skill entry must be an object.')

        skill_path = skill.get('path')
        if not isinstance(skill_path, str) or not skill_path:
            raise ValueError('Each skill entry must include a non-empty path.')

        has_url = isinstance(skill.get('url'), str)
        has_inline_content = isinstance(skill.get('inlineContent'), str)
        if not has_url and not has_inline_content:
            raise ValueError(f'Skill {skill_path} must include either url or inlineContent.')


def fetch_skill_content(skill: dict[str, Any], config: Config, manifest_base_url: Any) -> str:
    inline_content = skill.get('inlineContent')
    if isinstance(inline_content, str):
        return inline_content

    base_url = manifest_base_url if isinstance(manifest_base_url, str) else config.manifest_url
    resolved_url = parse.urljoin(base_url, skill['url'])
    return fetch_text(resolved_url, config, skill_path=skill['path'])


def fetch_text(url: str, config: Config, skill_path: str | None = None) -> str:
    headers = {
        'Accept': 'application/json, text/plain;q=0.9, */*;q=0.8',
        'User-Agent': 'claude-code-skill-sync/1.0',
    }
    if config.api_token:
        headers['Authorization'] = f'Bearer {config.api_token}'

    req = request.Request(url, headers=headers)
    context = None
    if config.insecure_tls:
        context = ssl._create_unverified_context()

    try:
        with request.urlopen(req, timeout=config.timeout_seconds, context=context) as response:
            charset = response.headers.get_content_charset() or 'utf-8'
            return response.read().decode(charset)
    except error.HTTPError as exc:
        if skill_path:
            raise RuntimeError(
                f'Skill download failed for {skill_path}: {exc.code} {exc.reason}.'
            ) from exc
        raise RuntimeError(f'Manifest request failed with {exc.code} {exc.reason}.') from exc
    except error.URLError as exc:
        reason = getattr(exc, 'reason', exc)
        raise RuntimeError(f'Request failed for {url}: {reason}.') from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f'Request timed out after {int(config.timeout_seconds * 1000)}ms for {url}.'
        ) from exc


def resolve_target_path(destination_root: Path, relative_path: str) -> Path:
    target_path = (destination_root / relative_path).resolve()

    try:
        target_path.relative_to(destination_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f'Refusing to write outside the destination directory: {relative_path}'
        ) from exc

    return target_path


def normalize_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace('\\', '/').lstrip('/')
    return normalized


def load_state(destination_root: Path) -> dict[str, str]:
    state_path = destination_root / STATE_FILE
    if not state_path.exists():
        return {}

    try:
        parsed = json.loads(state_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'Unable to read state file: {exc.msg}.') from exc

    if not isinstance(parsed, dict):
        return {}

    return {str(key): str(value) for key, value in parsed.items()}


def save_state(destination_root: Path, state: dict[str, str]) -> None:
    state_path = destination_root / STATE_FILE
    state_path.write_text(f'{json.dumps(state, indent=2)}\n', encoding='utf-8')


def remove_stale_files(
    destination_root: Path,
    previous_state: dict[str, str],
    next_state: dict[str, str],
) -> list[str]:
    removed_files: list[str] = []

    candidate_paths = set(previous_state)
    candidate_paths.update(list_existing_skill_files(destination_root))

    for relative_path in sorted(candidate_paths):
        if relative_path in next_state:
            continue

        target_path = resolve_target_path(destination_root, relative_path)
        if target_path.exists():
            target_path.unlink()
        removed_files.append(relative_path)

    remove_empty_skill_directories(destination_root)

    return removed_files


def list_existing_skill_files(destination_root: Path) -> list[str]:
    if not destination_root.exists():
        return []

    existing_files: list[str] = []
    for file_path in destination_root.rglob('*'):
        if not file_path.is_file():
            continue
        if file_path.name == STATE_FILE:
            continue
        existing_files.append(file_path.relative_to(destination_root).as_posix())

    return existing_files


def remove_empty_skill_directories(destination_root: Path) -> None:
    if not destination_root.exists():
        return

    directories = sorted(
        (path for path in destination_root.rglob('*') if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            continue


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def parse_timeout(value: str | None, fallback_seconds: float) -> float:
    if not value:
        return fallback_seconds

    try:
        timeout_ms = int(value)
    except ValueError as exc:
        raise ValueError(f'Invalid integer value: {value}') from exc

    if timeout_ms <= 0:
        raise ValueError(f'Invalid integer value: {value}')

    return timeout_ms / 1000.0


def log_summary(
    manifest_version: str,
    destination_root: Path,
    total: int,
    written_files: list[str],
    removed_files: list[str],
) -> None:
    print(f'[skill-sync] destination: {destination_root.resolve()}')
    print(f'[skill-sync] manifest version: {manifest_version}')
    print(f'[skill-sync] skills declared: {total}')
    print(f'[skill-sync] updated: {len(written_files)}')

    for file_path in written_files:
        print(f'[skill-sync] wrote {file_path}')

    for file_path in removed_files:
        print(f'[skill-sync] removed {file_path}')


def format_error(error_value: Exception) -> str:
    return str(error_value)


if __name__ == '__main__':
    sys.exit(main())