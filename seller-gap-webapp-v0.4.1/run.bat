@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    py -3 app.py
    goto :done
)

where python >nul 2>&1
if not errorlevel 1 (
    python app.py
    goto :done
)

echo Python 3 was not found.
echo Install Python 3 and enable Add python.exe to PATH.
pause
exit /b 1

:done
if errorlevel 1 pause
endlocal
