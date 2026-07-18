@echo off
chcp 65001 > nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py
) else (
    python app.py
)
if errorlevel 1 (
    echo.
    echo 실행에 실패했습니다. Python 3가 설치되어 있는지 확인하세요.
    pause
)
