#!/bin/zsh
# Double-click in Finder; keep the terminal open while the local services run.
cd -- "${0:A:h}" || exit 1
if [[ -x "platform/backend/.venv/bin/python" ]]; then
  platform/backend/.venv/bin/python scripts/start-local.py --open
  result=$?
else
  print -u2 '尚未安装完整功能版环境。请先运行：python3 scripts/setup-local.py'
  result=1
fi
if (( result != 0 )); then
  print '\n按回车关闭此窗口。'
  read -r
fi
exit "$result"
