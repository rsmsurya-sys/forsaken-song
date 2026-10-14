@echo off
title Forsaken Music - Spotify Studio Server
echo ========================================================
echo  Starting Forsaken Spotify Player Server on Port 8000
echo ========================================================

echo App URLs:
echo   - Spotify Desktop Player : http://localhost:8000/desktop
echo   - Spotify Mobile Player  : http://localhost:8000/mobile
echo   - Admin & Downloader Hub : http://localhost:8000/admin
echo ========================================================
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
    goto done
)

if exist ".venv\Scripts\uvicorn.exe" (
    .venv\Scripts\uvicorn.exe server.main:app --host 0.0.0.0 --port 8000 --reload
    goto done
)

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
    goto done
)

python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

:done
pause
