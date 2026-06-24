from __future__ import annotations

import importlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from dotenv import load_dotenv

load_dotenv()


def load_boto3_module() -> Any:
    try:
        return importlib.import_module('boto3')
    except ModuleNotFoundError:
        return None


def load_s3_connection_errors() -> tuple[type[Exception], ...]:
    try:
        exceptions_module = importlib.import_module('botocore.exceptions')
    except ModuleNotFoundError:
        return (RuntimeError,)

    names = (
        'BotoCoreError',
        'ConnectTimeoutError',
        'ConnectionClosedError',
        'EndpointConnectionError',
        'HTTPClientError',
        'ReadTimeoutError',
    )
    return tuple(getattr(exceptions_module, name) for name in names)


LOGGER = logging.getLogger(__name__)

def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    if not DEFAULT_TOKEN:
        return

    expected_header = f'Bearer {DEFAULT_TOKEN}'
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail='Unauthorized')
    

app = FastAPI(title='Claude Code Skill Server', version='1.0.0')

SERVER_ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = Path(os.environ.get('SKILL_CONTENT_DIR', SERVER_ROOT / 'skills')).resolve()
DEFAULT_TOKEN = os.environ.get('SKILL_SERVER_TOKEN')
S3_BUCKET = os.environ.get('SKILL_S3_BUCKET')
S3_PREFIX = os.environ.get('SKILL_S3_PREFIX', '').strip('/')
S3_REGION = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION')
S3_ENDPOINT_URL = os.environ.get('SKILL_S3_ENDPOINT_URL')

BOTO3_MODULE = load_boto3_module()
S3_CONNECTION_ERRORS = load_s3_connection_errors()

ProviderResult = TypeVar('ProviderResult')


class SkillProvider(Protocol):
    def list_skills(self) -> list[str]: ...

    def read_skill_bytes(self, relative_path: str) -> bytes: ...


class LocalSkillProvider:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_skills(self) -> list[str]:
        if not self.root.exists():
            return []

        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob('*')
            if path.is_file()
        )

    def read_skill_bytes(self, relative_path: str) -> bytes:
        target_path = resolve_local_skill_path(relative_path)
        return target_path.read_bytes()


class S3SkillProvider:
    def __init__(self, bucket: str, prefix: str, region: str | None, endpoint_url: str | None) -> None:
        if BOTO3_MODULE is None:
            raise RuntimeError('boto3 is required for S3-backed skill loading.')

        self.bucket = bucket
        self.prefix = prefix
        session = BOTO3_MODULE.session.Session(region_name=region)
        self.client = session.client('s3', endpoint_url=endpoint_url)

    def list_skills(self) -> list[str]:
        paginator = self.client.get_paginator('list_objects_v2')
        skills: list[str] = []

        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.object_key('')):
            for entry in page.get('Contents', []):
                key = entry['Key']
                relative_path = self.relative_path(key)
                if relative_path:
                    skills.append(relative_path)

        return sorted(skills)

    def read_skill_bytes(self, relative_path: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self.object_key(relative_path))
        return response['Body'].read()

    def object_key(self, relative_path: str) -> str:
        normalized_path = normalize_relative_path(relative_path)
        if not self.prefix:
            return normalized_path
        if not normalized_path:
            return f'{self.prefix}/'
        return f'{self.prefix}/{normalized_path}'

    def relative_path(self, key: str) -> str | None:
        if self.prefix:
            expected_prefix = f'{self.prefix}/'
            if key == self.prefix or key == expected_prefix:
                return None
            if not key.startswith(expected_prefix):
                return None
            key = key[len(expected_prefix):]

        normalized_path = normalize_relative_path(key)
        return normalized_path or None


LOCAL_PROVIDER = LocalSkillProvider(SKILLS_ROOT)


def get_primary_provider() -> SkillProvider:
    if not S3_BUCKET:
        return LOCAL_PROVIDER

    try:
        return S3SkillProvider(
            bucket=S3_BUCKET,
            prefix=S3_PREFIX,
            region=S3_REGION,
            endpoint_url=S3_ENDPOINT_URL,
        )
    except RuntimeError as exc:
        LOGGER.warning('Falling back to local skills: %s', exc)
        return LOCAL_PROVIDER


def with_s3_fallback(
    operation_name: str,
    action: Callable[[SkillProvider], ProviderResult],
) -> tuple[ProviderResult, bool]:
    provider = get_primary_provider()
    try:
        return action(provider), False
    except S3_CONNECTION_ERRORS as exc:
        if provider is LOCAL_PROVIDER:
            raise
        LOGGER.warning('S3 %s failed, falling back to local skills: %s', operation_name, exc)
        return action(LOCAL_PROVIDER), True


@app.get('/healthz')
def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/manifest.json')
def get_manifest(
    request: Request,
    _: None = Depends(require_bearer_token),
) -> JSONResponse:
    result, used_fallback = with_s3_fallback('manifest list', lambda provider: provider.list_skills())
    skills = []

    for relative_path in result:
        skills.append(
            {
                'path': relative_path,
                'url': str(request.url_for('download_skill', skill_path=relative_path)),
            }
        )

    manifest = {
        'version': datetime.now(timezone.utc).isoformat(),
        'baseUrl': str(request.base_url),
        'skills': skills,
    }
    response = JSONResponse(manifest)
    if used_fallback:
        response.headers['X-Skill-Source'] = 'local-fallback'
    elif S3_BUCKET:
        response.headers['X-Skill-Source'] = 's3'
    else:
        response.headers['X-Skill-Source'] = 'local'
    return response


@app.get('/skills/{skill_path:path}', name='download_skill')
def download_skill(
    skill_path: str,
    _: None = Depends(require_bearer_token),
) -> Response:
    normalized_path = normalize_relative_path(skill_path)
    if not normalized_path:
        raise HTTPException(status_code=400, detail='Invalid skill path')

    def read_content(provider: SkillProvider) -> bytes:
        return provider.read_skill_bytes(normalized_path)

    try:
        content, used_fallback = with_s3_fallback('skill download', read_content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Skill file not found') from exc

    response = Response(content=content, media_type='text/markdown; charset=utf-8')
    if used_fallback:
        response.headers['X-Skill-Source'] = 'local-fallback'
    elif S3_BUCKET:
        response.headers['X-Skill-Source'] = 's3'
    else:
        response.headers['X-Skill-Source'] = 'local'
    return response


def resolve_local_skill_path(relative_path: str) -> Path:
    normalized_path = normalize_relative_path(relative_path)
    target_path = (SKILLS_ROOT / normalized_path).resolve()

    try:
        target_path.relative_to(SKILLS_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invalid skill path') from exc

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail='Skill file not found')

    return target_path


def normalize_relative_path(relative_path: str) -> str:
    return relative_path.replace('\\', '/').lstrip('/')