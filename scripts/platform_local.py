"""Shared local configuration. Never print credentials or alter the legacy database."""
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / 'platform'
DATA = ROOT / '.data' / 'platform'
PYTHON = PLATFORM / 'backend' / '.venv' / 'bin' / 'python'


def configuration():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = DATA / 'local.json'
    if not path.exists():
        value = {'encryptionKey': secrets.token_urlsafe(48),
                 'adminEmail': 'admin@fde.local', 'adminPassword': 'fde-dev-admin',
                 'allowExternalProcessing': False, 'loginRequired': False}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
    return json.loads(path.read_text())


def environment():
    value = configuration()
    env = os.environ.copy()
    env.update(APP_DATABASE_URL='sqlite+aiosqlite:///' + str(DATA / 'knowledge_hub.db'),
               APP_LOCAL_STORAGE_PATH=str(DATA / 'uploads'), APP_STORAGE_BACKEND='local',
               APP_TASK_MODE='inline', APP_ENCRYPTION_KEY=value['encryptionKey'],
               APP_BOOTSTRAP_ADMIN_EMAIL=value['adminEmail'],
               APP_BOOTSTRAP_ADMIN_PASSWORD=value['adminPassword'], APP_ALLOW_DEMO_HEADERS='false',
               APP_LOCAL_CONFIG_PATH=str(DATA / 'local.json'),
               APP_LOCAL_NO_LOGIN=str(not value.get('loginRequired', False)).lower(),
               APP_ALLOW_EXTERNAL_PROCESSING=str(value['allowExternalProcessing']).lower())
    return env
