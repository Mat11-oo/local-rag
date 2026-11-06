#!/usr/bin/env python3
"""Install dependencies and official vendor PostgreSQL binaries on Apple Silicon."""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def install_postgres():
    target = RUNTIME / 'pgsql'
    if (target / 'bin/postgres').exists():
        return
    if os.environ.get('DATABASE_URL'):
        return
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('此便携安装脚本面向当前 Apple Silicon Mac；其他系统请准备 PostgreSQL＋pgvector 并设置 DATABASE_URL。')
    downloads = RUNTIME / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    dmg = downloads / 'Postgres-17.dmg'
    if not dmg.exists():
        partial = downloads / 'Postgres-17.dmg.part'
        try:
            subprocess.run(['curl', '-fL', '--retry', '2', 'https://github.com/PostgresApp/PostgresApp/releases/download/v2.9.6/Postgres-2.9.6-17.dmg', '-o', str(partial)], check=True)
            partial.replace(dmg)
        finally:
            partial.unlink(missing_ok=True)
    mount = RUNTIME / 'pg-mount'
    staging = RUNTIME / 'pgsql-installing'
    if staging.exists():
        shutil.rmtree(staging)
    mounted = False
    try:
        subprocess.run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount), str(dmg)], check=True)
        mounted = True
        shutil.copytree(mount / 'Postgres.app/Contents/Versions/17', staging)
        if not (staging / 'bin/postgres').is_file() or not (staging / 'share/postgresql/extension/vector.control').is_file():
            raise RuntimeError('下载的 PostgreSQL 运行环境不完整，未替换现有安装。')
        if target.exists():
            # Only discard an incomplete runtime; persistent data is in .data.
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if mounted:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True)


def main():
    if not shutil.which('node') or not shutil.which('npm'):
        raise SystemExit('未找到 Node.js / npm。请安装 Node.js 22.12 或更新的受支持版本后重新运行。')
    python = ROOT / 'backend/.venv/bin/python'
    if not python.exists():
        if sys.version_info < (3, 10):
            raise SystemExit('需要 Python 3.10 或更新版本；请用可用的 Python 3.12 运行本脚本。')
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / 'backend/.venv')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'backend/requirements.lock.txt')], check=True)
    subprocess.run(['npm', 'ci'], cwd=ROOT / 'frontend', check=True)
    install_postgres()
    print('安装完成。运行：python3 scripts/start-legacy.py --open，或双击「启动知序.command」。')


if __name__ == '__main__':
    main()
