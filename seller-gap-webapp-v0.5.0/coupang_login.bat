@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    py -3 coupang_login.py
    goto :finished
)

where python >nul 2>&1
if not errorlevel 1 (
    python coupang_login.py
    goto :finished
)

echo Python 3 was not found.
pause
exit /b 1

:finished
if errorlevel 1 pause
endlocal
