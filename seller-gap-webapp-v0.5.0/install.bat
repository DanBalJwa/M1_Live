@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m pip install --upgrade pip
    py -3 -m pip install -r requirements.txt
    goto :done
)

where python >nul 2>&1
if not errorlevel 1 (
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    goto :done
)

echo Python 3 was not found.
echo Install Python 3 and enable Add python.exe to PATH.
pause
exit /b 1

:done
if errorlevel 1 (
    echo Installation failed.
) else (
    echo Installation completed.
)
pause
endlocal
