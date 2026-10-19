@echo off
cd /d "%~dp0"
REM Install / update libraries (run once, or when Edge-TTS starts failing)
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
"%PY%" -m pip install -U -r requirements.txt
pause
