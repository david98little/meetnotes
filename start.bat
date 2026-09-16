@echo off
chcp 65001 >nul
cd /d %~dp0

if not exist .venv (
    echo [MeetNotes] 首次运行，创建虚拟环境并安装依赖...
    python -m venv .venv
    .venv\Scripts\python -m pip install -q -r requirements.txt
)

echo [MeetNotes] 服务启动中: http://localhost:8618
start "" http://localhost:8618
.venv\Scripts\python -m uvicorn server.main:app --host 127.0.0.1 --port 8618
