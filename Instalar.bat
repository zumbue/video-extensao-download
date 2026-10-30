@echo off
cd /d "%~dp0"
title Video Extensao Download

where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
  mshta "javascript:alert('Instale Python, FFmpeg e Node. Depois abra Instalar de novo.');close()"
  exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  mshta "javascript:alert('Instale o FFmpeg e abra Instalar de novo.');close()"
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 (
    mshta "javascript:alert('Nao consegui criar o ambiente Python.');close()"
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -r host\requirements.txt
if errorlevel 1 (
  ".venv\Scripts\python.exe" -c "import yt_dlp" >nul 2>&1
  if errorlevel 1 (
    mshta "javascript:alert('Nao consegui instalar o yt-dlp. Confira a internet e abra Instalar de novo.');close()"
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-windows.ps1" -Root "%~dp0"
if errorlevel 1 (
  mshta "javascript:alert('O servico nao respondeu. Abra Instalar de novo.');close()"
  exit /b 1
)

start "" "http://127.0.0.1:8734/"
mshta "javascript:alert('A pagina abriu. Cole o link e clique em Baixar. Os arquivos vao para Downloads, na pasta Video Extensao Download.');close()"
exit /b 0
