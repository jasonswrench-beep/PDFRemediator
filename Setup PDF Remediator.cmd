@echo off
setlocal
cd /d "%~dp0"
echo Preparing the isolated PDF Remediator application environment.
echo This setup may download Python packages. It does not download AI models.
if not exist ".venvs\app\Scripts\python.exe" (
  py -3.11 -m venv ".venvs\app"
  if errorlevel 1 goto setup_failed
)
".venvs\app\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto setup_failed
if exist "%~dp0local-runtime.toml" (
  ".venvs\app\Scripts\python.exe" -m pdf_remediator doctor --config "%~dp0local-runtime.toml"
) else (
  ".venvs\app\Scripts\python.exe" -m pdf_remediator doctor
)
if errorlevel 1 goto setup_failed
echo Setup is ready. Double-click Start PDF Remediator.cmd.
pause
exit /b 0
:setup_failed
echo Setup needs attention. Read START-HERE.md and the tool inventory above.
echo If a native library reports that a filename or path is too long,
echo create a fresh installation in a shorter local folder and run Setup there.
echo Leave your existing installation, original PDFs and saved reviews in place.
pause
exit /b 1
