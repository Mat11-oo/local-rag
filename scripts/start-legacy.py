#!/usr/bin/env python3
"""Start project-local PostgreSQL, FastAPI, worker and optionally Vite."""
import argparse
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / 'backend/.venv/bin/python'
if not PYTHON.exists():
    raise SystemExit('尚未安装后端环境。请先用 Python 3.10 或更新版本运行：python3 scripts/setup-legacy.py')
if Path(sys.prefix) != ROOT / 'backend/.venv':
    os.execv(str(PYTHON), [str(PYTHON), __file__, *sys.argv[1:]])
try:
    import psycopg
except ImportError:
    raise SystemExit('后端依赖不完整。请运行：python3 scripts/setup-legacy.py') from None


def require_free_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', port))
        except OSError:
            detail = '若已在运行Local RAG，请直接打开页面，或先在原启动窗口按 Ctrl+C 停止。'
            if port == 5173:
                detail += ' 需要沿用现有前端时可加 --backend-only。'
            raise RuntimeError(f'本地端口 {port} 已被占用。{detail}') from None


def wait_for_service(url, process, label):
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError(f'{label}启动失败，请查看上方启动日志。')
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f'{label}启动超时，请查看上方启动日志。')


def stop_children(children):
    # Each owned child has its own process group, including npm's Vite child.
    for child in reversed(children):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for child in children:
        try:
            child.wait(15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def main():
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    parser = argparse.ArgumentParser(description='启动Local RAG本地知识库，按 Ctrl+C 停止并保留数据。')
    parser.add_argument('--backend-only', action='store_true', help='仅启动后端和任务进程，沿用已运行的前端')
    parser.add_argument('--open', action='store_true', help='服务启动后在默认浏览器打开页面')
    args = parser.parse_args()
    os.umask(0o077)
    data = ROOT / '.data'
    runtime = ROOT / '.runtime/pgsql/bin'
    started_db = False
    children = []
    try:
        require_free_port(8000)
        if not args.backend_only:
            require_free_port(5173)
            if not shutil.which('node') or not shutil.which('npm'):
                raise RuntimeError('未找到 Node.js / npm。请安装 Node.js 22.12 或更新的受支持版本后重新启动。')
            if not (ROOT / 'frontend/node_modules/vite').is_dir():
                raise RuntimeError('前端依赖未安装。请运行：python3 scripts/setup-legacy.py')
        data.mkdir(exist_ok=True)
        data.chmod(0o700)
        if not os.environ.get('DATABASE_URL'):
            if not runtime.is_dir():
                raise RuntimeError('缺少本地 PostgreSQL。请运行 scripts/setup-legacy.py，或设置 DATABASE_URL。')
            config_file = data / 'database.json'
            if config_file.exists():
                config = json.loads(config_file.read_text())
            else:
                password = secrets.token_urlsafe(32)
                config = {'url': f'postgresql://knowhub:{password}@127.0.0.1:55432/knowhub', 'password': password}
                config_file.write_text(json.dumps(config))
                config_file.chmod(0o600)
            cluster = data / 'postgres'
            if not (cluster / 'PG_VERSION').exists():
                password_file = data / 'init-password'
                password_file.write_text(config['password'])
                try:
                    subprocess.run([str(runtime / 'initdb'), '-D', str(cluster), '-U', 'knowhub', '--encoding=UTF8', '--locale=C', '--auth=scram-sha-256', '--pwfile', str(password_file)], check=True, stdout=subprocess.DEVNULL)
                finally:
                    password_file.unlink(missing_ok=True)
            status = subprocess.run([str(runtime / 'pg_ctl'), '-D', str(cluster), 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if status.returncode:
                require_free_port(55432)
                socket_dir = Path('/tmp') / f'knowhub-pg-{os.getuid()}'
                socket_dir.mkdir(exist_ok=True, mode=0o700)
                options = f'-h 127.0.0.1 -p 55432 -k {shlex.quote(str(socket_dir))}'
                # If pg_ctl times out after starting the server, finally still stops it.
                started_db = True
                subprocess.run([str(runtime / 'pg_ctl'), '-D', str(cluster), '-l', str(data / 'postgres.log'), '-o', options, '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
            try:
                with psycopg.connect(config['url'].rsplit('/', 1)[0] + '/postgres', autocommit=True, connect_timeout=10) as conn:
                    if not conn.execute("SELECT 1 FROM pg_database WHERE datname='knowhub'").fetchone():
                        conn.execute('CREATE DATABASE knowhub')
            except psycopg.Error:
                raise RuntimeError('无法连接本地数据库，请查看 .data/postgres.log；数据库配置保存在 .data/database.json。') from None
        backend = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT / 'backend', start_new_session=True)
        children.append(backend)
        wait_for_service('http://127.0.0.1:8000/api/health', backend, '后端')
        children.append(subprocess.Popen([str(PYTHON), '-m', 'app.worker'], cwd=ROOT / 'backend', start_new_session=True))
        if not args.backend_only:
            frontend = subprocess.Popen(['npm', 'run', 'dev'], cwd=ROOT / 'frontend', start_new_session=True)
            children.append(frontend)
            wait_for_service('http://127.0.0.1:5173/', frontend, '前端')
        print('\nLocal RAG已启动：http://127.0.0.1:5173/\n按 Ctrl+C 停止。资料与密钥保存在项目 .data 目录。', flush=True)
        if args.open:
            webbrowser.open('http://127.0.0.1:5173/')
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError('有服务进程已退出，请查看上方日志。其他本次启动的服务将一并停止，数据会保留。')
    except KeyboardInterrupt:
        print('\n正在停止Local RAG，保留本地数据……', flush=True)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'\n启动未完成：{error}', file=sys.stderr, flush=True)
        return 1
    finally:
        # Avoid a second Ctrl+C interrupting process/database cleanup.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop_children(children)
        if started_db:
            subprocess.run([str(runtime / 'pg_ctl'), '-D', str(data / 'postgres'), '-m', 'fast', '-w', 'stop'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
