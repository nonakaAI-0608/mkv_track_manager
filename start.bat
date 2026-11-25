@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; assert sys.version_info >= (3,10), 'Python 3.10 or newer is required'"
    if errorlevel 1 goto missing
    start "" pyw -3 launcher.py
    goto finished
)
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys, tkinter; assert sys.version_info >= (3,10), 'Python 3.10 or newer is required'"
if errorlevel 1 goto missing
start "" pythonw launcher.py
goto finished
:missing
echo.
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and the Python launcher during installation.
echo Then run start.bat again.
pause
exit /b 1
:finished
exit /b 0
