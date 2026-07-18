@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m py_compile app.py core.py self_test.py
    if errorlevel 1 goto :failed
    py -3 self_test.py
    if errorlevel 1 goto :failed
    goto :passed
)

where python >nul 2>&1
if not errorlevel 1 (
    python -m py_compile app.py core.py self_test.py
    if errorlevel 1 goto :failed
    python self_test.py
    if errorlevel 1 goto :failed
    goto :passed
)

echo Python 3 was not found.
goto :failed

:passed
echo Validation passed.
pause
exit /b 0

:failed
echo Validation failed.
pause
exit /b 1
