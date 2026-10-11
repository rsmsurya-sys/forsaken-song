@echo off
echo ========================================================
echo  Starting Forsaken Music Locally via Python / Uvicorn
echo ========================================================

uv run uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

pause
