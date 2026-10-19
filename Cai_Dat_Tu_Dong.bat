@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo =================================================================
echo        TỰ ĐỘNG THIẾT LẬP VIDEODUB STUDIO (DÀNH CHO THÀNH VIÊN)
echo =================================================================
echo.

REM 1. Kiểm tra Python
set PY_CMD=python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    REM Thu tim trong LocalAppData neu da cai nhung chua vao PATH
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else (
        echo [1/3] May tinh chua co Python. Dang tu dong cai dat Python 3.11...
        echo (Qua trinh nay hoan toan tu dong, vui long doi 1-2 phut...)
        
        REM Thu cai qua winget
        winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
        
        if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
            set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        ) else (
            echo Dang tai goi cai dat Python chinh thuc tu python.org...
            curl -L -o "%TEMP%\python_setup.exe" https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
            echo Dang cai dat Python...
            "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
            del "%TEMP%\python_setup.exe" >nul 2>&1
            if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
                set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
            )
        )
    )
)

echo [1/3] Da san sang Python!
echo.
echo [2/3] Dang khoi tao moi truong va cai dat thu vien AI...
if not exist ".venv" (
    "%PY_CMD%" -m venv .venv
)

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=%PY_CMD%

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt

REM 3. Kiem tra FFmpeg
if not exist "bin\ffmpeg.exe" (
    echo.
    echo [3/4] Dang tai FFmpeg (cong cu xu ly video)...
    if not exist "bin" mkdir bin
    winget install Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    where ffmpeg >nul 2>&1
    if %errorlevel% neq 0 (
        curl -L -o "%TEMP%\ffmpeg.zip" "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        powershell -Command "Expand-Archive -Path '%TEMP%\ffmpeg.zip' -DestinationPath '%TEMP%\ffmpeg_ext' -Force"
        copy /y "%TEMP%\ffmpeg_ext\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" "bin\" >nul 2>&1
        copy /y "%TEMP%\ffmpeg_ext\ffmpeg-master-latest-win64-gpl\bin\ffprobe.exe" "bin\" >nul 2>&1
        del "%TEMP%\ffmpeg.zip" >nul 2>&1
        rmdir /s /q "%TEMP%\ffmpeg_ext" >nul 2>&1
    )
)

echo.
echo =================================================================
echo   [3/3] THIET LAP HOAN TAT THANH CONG!
echo   Tu bay gio, ban chi can bam dup vao:
echo      - File "run_web.bat"  (hoac "Chay_VideoDub.vbs")
echo   de mo phan mem va su dung tren trinh duyet!
echo =================================================================
echo.
pause
