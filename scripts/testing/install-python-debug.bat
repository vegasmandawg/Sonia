@echo off
setlocal enabledelayedexpansion

REM Log all output
set LOGFILE=S:\artifacts\phase3\python-install-debug.log

echo. >> %LOGFILE%
echo ======================================== >> %LOGFILE%
echo Python Installation Debug Log >> %LOGFILE%
echo Timestamp: %date% %time% >> %LOGFILE%
echo ======================================== >> %LOGFILE%
echo. >> %LOGFILE%

echo Checking Miniconda3 installer... >> %LOGFILE%
if exist "S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe" (
    echo Found installer >> %LOGFILE%
) else (
    echo ERROR: Installer not found >> %LOGFILE%
    exit /b 1
)

echo. >> %LOGFILE%
echo Attempting to install to S:\tools\python... >> %LOGFILE%

REM Verify installation directory
if not exist "S:\tools\python" (
    echo Creating S:\tools\python >> %LOGFILE%
    mkdir S:\tools\python >> %LOGFILE% 2>&1
)

REM Run installer with all output captured
echo Running: S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe >> %LOGFILE%
S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=S:\tools\python >> %LOGFILE% 2>&1

set INSTALL_EXIT=%errorlevel%
echo Installer exit code: %INSTALL_EXIT% >> %LOGFILE%

echo. >> %LOGFILE%
echo Waiting 3 seconds... >> %LOGFILE%
timeout /t 3 /nobreak >> %LOGFILE% 2>&1

REM Check if python.exe exists
echo. >> %LOGFILE%
echo Checking for S:\tools\python\python.exe... >> %LOGFILE%
if exist "S:\tools\python\python.exe" (
    echo SUCCESS: python.exe found >> %LOGFILE%
    S:\tools\python\python.exe --version >> %LOGFILE% 2>&1
    exit /b 0
) else (
    echo ERROR: python.exe not found >> %LOGFILE%
    echo. >> %LOGFILE%
    echo Directory contents of S:\tools\python: >> %LOGFILE%
    if exist "S:\tools\python" (
        dir /s "S:\tools\python" >> %LOGFILE% 2>&1
    ) else (
        echo Directory does not exist >> %LOGFILE%
    )
    exit /b 1
)
