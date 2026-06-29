@echo off
chcp 65001 > nul
cd /d "%~dp0"

set PYTHONUTF8=1
set LOCAL_LM_STUDIO_MODE=true
set AI_PROVIDER=openai_compatible

set OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:1234/v1
set OPENAI_COMPATIBLE_API_KEY=local
set OPENAI_COMPATIBLE_MODEL=qwen3-8b

set OPENAI_COMPATIBLE_JSON_MODE=false
set SOURCE_CONTEXT_MAX_CHARS=3000
set SOURCE_CONTEXT_FILE_MAX_CHARS=500
set OPENAI_COMPATIBLE_MAX_TOKENS=600
set OPENAI_COMPATIBLE_TIMEOUT=240
set QUALITY_AUTO_REPAIR=false

echo.
echo ========================================
echo  Academy Prequel local backend
echo ========================================
echo.
echo LM Studio must be running on:
echo http://127.0.0.1:1234/v1
echo.
echo Starting backend on:
echo http://127.0.0.1:8000
echo.

py -m uvicorn app.server:app --host 127.0.0.1 --port 8000

echo.
echo Backend stopped.
pause
