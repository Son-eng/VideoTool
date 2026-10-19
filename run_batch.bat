@echo off
cd /d "%~dp0"
REM Put videos into input\ then run this file. Results go to output\
if not exist input mkdir input
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
set PYTHONUTF8=1
"%PY%" -m videodub batch input -o output -c config.yaml
pause
