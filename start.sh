#!/usr/bin/env bash
# MeetNotes 启动脚本（macOS / Linux）
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[MeetNotes] 首次运行，创建虚拟环境并安装依赖..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -q -r requirements.txt
fi

echo "[MeetNotes] 服务启动中: http://localhost:8618"
( sleep 2; open http://localhost:8618 2>/dev/null || xdg-open http://localhost:8618 2>/dev/null ) &
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8618
