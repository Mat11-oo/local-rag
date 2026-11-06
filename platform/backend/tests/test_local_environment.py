import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import get_settings
from app.models import ModelConfig
from app.providers import build_gateway
from app.providers.base import ProviderError
from app.security import AuthContext, _enforce_scope


@pytest.mark.asyncio
async def test_local_no_login_opens_workspace_without_credentials(client, tmp_path, monkeypatch):
    monkeypatch.setenv('APP_LOCAL_NO_LOGIN', 'true')
    monkeypatch.setenv('APP_LOCAL_CONFIG_PATH', str(tmp_path / 'local.json'))
    monkeypatch.setenv('APP_ALLOW_DEMO_HEADERS', 'false')
    get_settings.cache_clear()
    mode = await client.get('/api/v1/auth/mode')
    assert mode.json() == {'local_no_login': True}
    me = await client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer expired-legacy-token'})
    assert me.status_code == 200
    assert me.json()['auth_type'] == 'local'
    assert me.json()['role'] == 'admin'
    assert (await client.get('/api/v1/models')).status_code == 200
    user = await client.get('/api/v1/auth/me', headers={'X-Demo-Role': 'user'})
    assert user.json()['role'] == 'user'
    assert (await client.get('/api/v1/models', headers={'X-Demo-Role': 'user'})).status_code == 403


@pytest.mark.asyncio
async def test_production_keeps_login_even_when_local_mode_is_requested(db_session, tmp_path, monkeypatch):
    from app.config import Settings
    from app.security import get_auth_context
    settings = Settings(env='production', local_no_login=True, local_config_path=tmp_path/'local.json')
    monkeypatch.setattr('app.security.get_settings', lambda: settings)
    with pytest.raises(HTTPException) as denied:
        await get_auth_context(Request({'type': 'http', 'path': '/', 'headers': []}),
                               authorization=None, x_demo_role='admin', x_workspace_id=None, session=db_session)
    assert denied.value.status_code == 401


@pytest.mark.asyncio
async def test_local_mode_requires_login_even_with_forged_demo_header(client, monkeypatch):
    monkeypatch.setenv('APP_ALLOW_DEMO_HEADERS', 'false')
    get_settings.cache_clear()
    response = await client.get('/api/v1/models', headers={'X-Demo-Role': 'admin'})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_local_preferences_require_human_session_and_do_not_return_secrets(client, tmp_path, monkeypatch):
    from app.api.routes.local_environment import status, processing, ProcessingPolicy
    path = tmp_path / 'local.json'
    path.write_text(json.dumps({'encryptionKey': 'hidden-key', 'adminPassword': 'hidden-pass', 'allowExternalProcessing': True}))
    monkeypatch.setenv('APP_LOCAL_CONFIG_PATH', str(path))
    get_settings.cache_clear()
    context = AuthContext('admin', 'workspace', 'user', 'session')
    payload = await status(context)
    assert 'hidden' not in json.dumps(payload)
    result = await processing(ProcessingPolicy(allow_external_processing=False), context)
    assert result == {'allow_external_processing': False}
    saved = json.loads(path.read_text())
    assert saved['encryptionKey'] == 'hidden-key'
    assert saved['allowExternalProcessing'] is False
    assert get_settings().allow_external_processing is False
    with pytest.raises(HTTPException) as denied:
        await status(AuthContext('admin', 'workspace', None, 'api_client', frozenset({'*'})))
    assert denied.value.status_code == 403


def test_cloud_processing_disabled_before_credentials_or_network(monkeypatch):
    monkeypatch.setenv('APP_ALLOW_EXTERNAL_PROCESSING', 'false')
    get_settings.cache_clear()
    model = ModelConfig(provider='openrouter', model_type='llm', model_name='real-model',
                        base_url='https://openrouter.ai/api/v1', config={})
    with pytest.raises(ProviderError, match='云端处理尚未授权'):
        build_gateway(model)


@pytest.mark.parametrize('method,path,allowed', [
    ('POST', '/api/v1/evaluation-sets/abc/run', 'apps:evaluate'),
    ('GET', '/api/v1/evaluation-sets/abc', 'apps:read'),
    ('GET', '/api/v1/observability/runs/abc', 'logs:read'),
])
def test_api_scopes_cover_evaluation_and_trace(method, path, allowed):
    request = Request({'type': 'http', 'method': method, 'path': path, 'headers': []})
    with pytest.raises(HTTPException) as denied:
        _enforce_scope(AuthContext('admin', 'workspace', None, 'api_client', frozenset({'apps:run'})), request)
    assert denied.value.status_code == 403
    _enforce_scope(AuthContext('manager', 'workspace', None, 'api_client', frozenset({allowed})), request)


def test_api_token_cannot_mint_broader_tokens_or_manage_members():
    context = AuthContext('admin', 'workspace', None, 'api_client', frozenset({'apps:run'}))
    for path in ['/api/v1/auth/api-clients', '/api/v1/auth/users']:
        request = Request({'type': 'http', 'method': 'POST', 'path': path, 'headers': []})
        with pytest.raises(HTTPException) as denied:
            _enforce_scope(context, request)
        assert denied.value.status_code == 403
