@echo off
chcp 65001 >nul
cd /d "%~dp0"
title VideoDub Web Studio AI
echo ========================================================
echo   VIDEODUB STUDIO AI - WEB INTERFACE
echo   Dang khoi dong may chu web va mo trinh duyet...
echo   Truy cap tai: http://127.0.0.1:7860
echo ========================================================
set PY=python
if exist "python_runtime\python.exe" set PY=python_runtime\python.exe
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
set PYTHONUTF8=1
"%PY%" -m videodub.server
pause
