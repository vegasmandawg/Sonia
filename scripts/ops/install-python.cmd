@echo off
REM Install Miniconda3 Python 3.11 to S:\tools\python

setlocal

set "INSTALLER=C:\Users\iamth\Downloads\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"
set "INSTALL_PATH=S:\tools\python"

if not exist "%INSTALLER%" (
  echo [FATAL] Installer not found: %INSTALLER%
  exit /b 1
)

echo Installing Miniconda3 to %INSTALL_PATH%...
echo This will take 2-5 minutes.

"%INSTALLER%" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%INSTALL_PATH%

if errorlevel 1 (
  echo [FATAL] Installation failed
  exit /b 2
)

echo [OK] Installation complete
"%INSTALL_PATH%\python.exe" --version

if errorlevel 1 (
  echo [FATAL] Python verification failed
  exit /b 3
)

echo [SUCCESS] Python 3.11 installed to %INSTALL_PATH%
exit /b 0
