@echo off
setlocal
set "REMEDIATOR_ROOT=%~dp0"
if not exist "%REMEDIATOR_ROOT%.venvs\app\Scripts\pythonw.exe" (
  echo The local application environment is missing.
  echo Run Setup PDF Remediator.cmd in this folder first.
  pause
  exit /b 1
)
start "" "%REMEDIATOR_ROOT%.venvs\app\Scripts\pythonw.exe" "%REMEDIATOR_ROOT%launch_review.pyw"
