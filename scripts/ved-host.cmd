@echo off
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" exit /b 1
"%PY%" -u "%~dp0ved_host.py"
