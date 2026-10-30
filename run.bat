@echo off
cd /d "%~dp0"
title Video Extensao Download
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  .venv\Scripts\python -m pip install -r host\requirements.txt
)
.venv\Scripts\python -m host
