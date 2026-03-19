@echo off
chcp 65001 >nul 2>&1
title Whisper PTT - Installer

:: Check administrator rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo  [!] Trebuutsya prava Administratora!
    echo      Requires Administrator rights!
    echo.
    echo  Perezapuskaem s pravami Administratora...
    echo  Restarting with Administrator rights...
    echo.
    powershell -Command "Start-Process cmd.exe -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo  ============================================================
echo   whisper_from_sssDeMoNsss -- INSTALLER
echo   Govori, ne pechatat. / Speak, don't type.
echo  ============================================================
echo.
echo  [OK] Prava Administratora podtverzhdeny
echo       (Administrator rights confirmed)
echo.

:: ── Search for installer ───────────────────────────────────────────────────
set "INSTALLER="

if exist "%~dp0install-all-windows.ps1" (
    set "INSTALLER=%~dp0install-all-windows.ps1"
    goto :check_python
)
if exist "C:\whisper-install\install-all-windows.ps1" (
    set "INSTALLER=C:\whisper-install\install-all-windows.ps1"
    goto :check_python
)
if exist "%CD%\install-all-windows.ps1" (
    set "INSTALLER=%CD%\install-all-windows.ps1"
    goto :check_python
)

:: Not found
echo  [ERROR] install-all-windows.ps1 ne nayden! (not found!)
echo.
echo  Ubedites chto INSTALL.bat i install-all-windows.ps1
echo  nakhodatsya v odnoy papke (are in the same folder).
echo.
echo  Primer struktury (Example structure):
echo    C:\whisper-install\
echo      INSTALL.bat
echo      install-all-windows.ps1
echo      install-whisper-ptt.ps1
echo      install-whisper-server-windows.ps1
echo      whisper-ptt.py
echo      whisper-server.py
echo      whisper-webui.py
echo      config.toml
echo.
pause
exit /b 1

:: ── Python check ───────────────────────────────────────────────────────────
:check_python
echo  [OK] Nayden ustanovshik (Installer found):
echo       %INSTALLER%
echo.
echo  [INFO] Proverka Python... (Checking Python...)

:: Python 3.13 already present — ideal
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    echo  [OK] Python 3.13 found -- using it.
    goto :python_ready
)

:: Older Python found — install 3.13 alongside (old version stays)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    echo  [INFO] Python 3.12 found but 3.13 is preferred. Installing 3.13...
    goto :install_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    echo  [INFO] Python 3.11 found but 3.13 is preferred. Installing 3.13...
    goto :install_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    echo  [INFO] Python 3.10 found but 3.13 is preferred. Installing 3.13...
    goto :install_python
)

echo  [!] Python ne nayden. Ustanavlivayem Python 3.13...
echo      (Python not found. Installing Python 3.13...)

:: ── Install Python 3.13 ────────────────────────────────────────────────────
:install_python
echo.
echo  [INFO] Avto-ustanovka Python 3.13... (Auto-installing Python 3.13...)
echo.

winget install Python.Python.3.13 --silent --accept-source-agreements --accept-package-agreements
if %errorLevel% equ 0 (
    echo  [OK] Python 3.13 installed via winget.
    powershell -NoProfile -Command "$p=[System.Environment]::GetEnvironmentVariable('Path','Machine'); if ($p -notlike '*Python313*') { [System.Environment]::SetEnvironmentVariable('Path', $p+';%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts', 'Machine') }"
    echo  [OK] Python 3.13 dobavlen v PATH.
    goto :python_ready
)

:: winget failed — try direct download
echo  [!] winget ne srabotan. Skachivayem installer napryamuyu...
echo      (winget failed. Downloading Python installer directly...)
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe' -OutFile '%TEMP%\python313.exe'"
if not exist "%TEMP%\python313.exe" goto :python_fail
echo  [OK] Installer skachan. Ustanavlivayem...
"%TEMP%\python313.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del /f /q "%TEMP%\python313.exe" 2>nul
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    powershell -NoProfile -Command "$p=[System.Environment]::GetEnvironmentVariable('Path','Machine'); if ($p -notlike '*Python313*') { [System.Environment]::SetEnvironmentVariable('Path', $p+';%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts', 'Machine') }"
    echo  [OK] Python 3.13 installed and added to PATH.
    goto :python_ready
)

:python_fail
echo.
echo  [ERROR] Ne udalos ustanovit Python avtomaticheski.
echo          (Could not install Python automatically.)
echo          Ustanovite vruchnuyu: https://www.python.org/downloads/
echo          (Install manually:    https://www.python.org/downloads/)
echo.
pause
exit /b 1

:: ── Run installer ──────────────────────────────────────────────────────────
:python_ready
echo.
echo  [INFO] Zapuskaem ustanovshik... (Starting installer...)
echo.

powershell -ExecutionPolicy Bypass -File "%INSTALLER%"
set "INST_ERR=%errorLevel%"

echo.
if "%INST_ERR%"=="0" (
    echo  [OK] Ustanovka zavershena uspeshno! (Installation complete!)
) else if "%INST_ERR%"=="1" (
    echo  [!]  Zaversheno s oshibkami. Kod: %INST_ERR%
    echo       (Finished with errors. Code: %INST_ERR%)
) else (
    echo  [OK] Zaversheno. (Finished.)
)
echo.
