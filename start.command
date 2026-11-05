#!/bin/zsh
set -u

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || exit 1
URL="http://127.0.0.1:8000"

if curl -fsS "$URL/api/health" >/dev/null 2>&1; then
  echo "服务已经在运行，正在打开浏览器……"
  open "$URL"
  exit 0
fi

if ! python3 -c 'import requests, bs4' >/dev/null 2>&1; then
  echo "缺少 Python 依赖，请先运行："
  echo "  python3 -m pip install -r requirements.txt"
  read "?按回车键关闭……"
  exit 1
fi

echo "正在启动 cdf 海南免税商品监测系统……"
python3 app.py &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null' INT TERM EXIT

for attempt in {1..30}; do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then
    echo "启动成功：$URL"
    open "$URL"
    wait "$APP_PID"
    exit $?
  fi
  sleep 0.2
done

echo "启动失败，请查看上方错误信息。"
kill "$APP_PID" 2>/dev/null
read "?按回车键关闭……"
exit 1
