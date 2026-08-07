@echo off
cd /d "%~dp0"
echo Starting database...
docker compose up -d
echo Starting server...
start "" /b cmd /c "timeout /t 14 /nobreak >nul & start http://127.0.0.1:8000"
call .venv\Scripts\activate.bat
uvicorn api:app --port 8000