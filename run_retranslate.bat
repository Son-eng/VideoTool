@echo off
cd /d "%~dp0"
REM Keep OCR results, translate again (e.g. after switching to Gemini or editing glossary), then dub + export
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
set PYTHONUTF8=1
"%PY%" -m videodub batch input -o output -c config.yaml --retranslate
pause
