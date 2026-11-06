#!/usr/bin/env python3
"""Install isolated dependencies without changing the legacy environment."""
import os
import shutil
import subprocess
import sys
from platform_local import ROOT, PLATFORM, PYTHON, configuration


def main():
    if '--legacy' in sys.argv:
        os.execv(sys.executable, [sys.executable, str(ROOT / 'scripts/setup-legacy.py')])
    if not shutil.which('node') or not shutil.which('pnpm'):
        raise SystemExit('需要 Node.js 22.12+ 和 pnpm；安装后重新运行。')
    if not PYTHON.exists():
        interpreter = ROOT / 'backend/.venv/bin/python'
        if not interpreter.exists():
            interpreter = shutil.which('python3.12') or shutil.which('python3.11') or sys.executable
        subprocess.run([str(interpreter), '-c', 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "需要 Python 3.11–3.13"'], check=True)
        subprocess.run([str(interpreter), '-m', 'venv', str(PYTHON.parent.parent)], check=True)
    uv = PYTHON.parent / 'uv'
    if not uv.exists():
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', 'uv'], check=True)
    subprocess.run([str(uv), 'sync', '--frozen', '--inexact'], cwd=PLATFORM / 'backend', check=True)
    subprocess.run(['pnpm', 'install', '--frozen-lockfile'], cwd=PLATFORM, check=True)
    configuration()
    print('依赖已准备。运行 python3 scripts/migrate-local.py 迁移旧资料，再运行 python3 scripts/start-local.py。')


if __name__ == '__main__':
    main()
