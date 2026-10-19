@echo off
cd /d "%~dp0"
REM Khoi chay giao dien Desktop VideoDub Studio
set PY=python
if exist "python_runtime\python.exe" set PY=python_runtime\python.exe
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
set PYTHONUTF8=1
"%PY%" -m videodub.gui
pause
