#!/usr/bin/env python3
"""Start the README-aligned platform; --legacy starts the preserved local RAG."""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from platform_local import ROOT, PLATFORM, PYTHON, environment


def free_port(port):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'端口 {port} 已占用，请检查现有服务；启动器不会停止其他进程。') from None


def ready(url, process):
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError('服务启动失败，请查看上方日志。')
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError('等待服务启动超时。')


def main():
    parser = argparse.ArgumentParser(description='启动 Local RAG 完整功能版')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--backend-only', action='store_true')
    parser.add_argument('--legacy', action='store_true')
    args = parser.parse_args()
    if args.legacy:
        legacy_python = str(ROOT / 'backend/.venv/bin/python')
        rest = [arg for arg in sys.argv[1:] if arg != '--legacy']
        os.execv(legacy_python, [legacy_python, str(ROOT / 'scripts/start-legacy.py'), *rest])
    if not PYTHON.exists() or not (PLATFORM / 'node_modules').exists():
        print('请先运行 python3 scripts/setup-local.py', file=sys.stderr)
        return 1
    children = []
    os.umask(0o077)
    def interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        free_port(8001)
        if not args.backend_only:
            free_port(4173)
        env = environment()
        backend = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'app.main:app',
                                    '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8001'],
                                   cwd=PLATFORM, env=env, start_new_session=True)
        children.append(backend)
        ready('http://127.0.0.1:8001/api/v1/health/ready', backend)
        if not args.backend_only:
            frontend = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--strictPort'],
                                        cwd=PLATFORM, start_new_session=True)
            children.append(frontend)
            ready('http://127.0.0.1:4173/', frontend)
        print('\nLocal RAG 已启动：http://127.0.0.1:4173/\n本地直接进入工作空间，无需登录；左下角可切换操作角色。'
              '\n数据：.data/platform；Ctrl+C 停止。旧版：python3 scripts/start-local.py --legacy', flush=True)
        if args.open:
            subprocess.run(['open', '-a', 'Google Chrome', 'http://127.0.0.1:4173/'], check=True)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError('服务异常退出，请查看日志。')
    except KeyboardInterrupt:
        print('\n正在停止 Local RAG，保留数据。', flush=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for child in reversed(children):
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
