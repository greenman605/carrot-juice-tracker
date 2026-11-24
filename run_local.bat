@echo off
rem Run one stock check on this PC, push it to GitHub, then open the tracker page.
rem   run_local.bat          check now, then open the page
rem   run_local.bat view     just open the page
cd /d "%~dp0"

if /i "%1"=="view" goto open

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python environment...
  py -m venv .venv || goto fail
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto fail
)
".venv\Scripts\python.exe" -m tracker --publish

:open
start "" "%~dp0docs\index.html"
exit /b 0

:fail
echo Setup failed. Make sure Python is installed (the "py" launcher).
pause
exit /b 1
