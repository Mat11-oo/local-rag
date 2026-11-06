"""Desktop integration only: authenticated local preferences, no secret disclosure."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...config import get_settings
from ...security import AuthContext, require_roles

router = APIRouter()


def local_path(context: AuthContext) -> Path:
    path = get_settings().local_config_path
    if path is None or get_settings().env == 'production':
        raise HTTPException(404, '当前环境没有本地集成配置')
    if context.auth_type not in ('session', 'local'):
        raise HTTPException(403, '本地环境设置必须通过管理员账号登录')
    return path


@router.get('')
async def status(context: AuthContext = Depends(require_roles('admin'))) -> dict:
    path = local_path(context)
    report_path = path.parent / 'migration-report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    source = Path(__file__).resolve().parents[4] / 'UPSTREAM.json'
    upstream = json.loads(source.read_text()) if source.exists() else {}
    return {'allow_external_processing': get_settings().allow_external_processing,
            'migration': ({'source_counts': report.get('sourceCounts', {}),
                           'warnings': report.get('warnings', []),
                           'retained_in_legacy': report.get('retainedInLegacy', [])} if report else None),
            'upstream': upstream}


class ProcessingPolicy(BaseModel):
    allow_external_processing: bool


@router.put('/processing')
async def processing(payload: ProcessingPolicy,
                     context: AuthContext = Depends(require_roles('admin'))) -> dict:
    path = local_path(context)
    value = json.loads(path.read_text())
    value['allowExternalProcessing'] = payload.allow_external_processing
    # Atomic replacement retains the old file if a write fails.
    temporary = path.with_suffix('.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    get_settings().allow_external_processing = payload.allow_external_processing
    return {'allow_external_processing': payload.allow_external_processing}
