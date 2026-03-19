@echo off
chcp 65001 >nul 2>&1
title Whisper PTT - Start All

:: Check administrator rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo  [!] Trebuutsya prava Administratora.
    echo      Administrator rights required.
    echo  Perezapuskaem... Restarting with elevation...
    powershell -Command "Start-Process cmd.exe -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo  ============================================================
echo   whisper_from_sssDeMoNsss -- START ALL
echo   Zapusk vsekh komponentov / Starting all components
echo  ============================================================
echo.
echo  [OK] Prava Administratora podtverzhdeny
echo.

:: ---- 1. Start WhisperServer service ----------------------------------------
echo  [1/3] Zapusk WhisperServer... (Starting WhisperServer...)
sc query WhisperServer >nul 2>&1
if %errorLevel% neq 0 (
    echo  [!]   WhisperServer ne ustanovlen kak servis.
    echo        Zapustite ustanovshik INSTALL.bat
    goto :start_webui
)
sc query WhisperServer | findstr "RUNNING" >nul
if %errorLevel% equ 0 (
    echo  [OK]  WhisperServer uzhe zapushchen (already running)
    goto :start_webui
)
powershell -Command "Start-Service WhisperServer -ErrorAction SilentlyContinue"
timeout /t 3 /nobreak >nul
sc query WhisperServer | findstr "RUNNING" >nul
if %errorLevel% equ 0 (
    echo  [OK]  WhisperServer zapushchen (started)
) else (
    echo  [!]   WhisperServer ne udalos zapustit (failed to start)
    echo        Provery log: C:\whisper-ptt\logs\whisper-server.log
)

:: ---- 2. Start WhisperWebUI service ------------------------------------------
:start_webui
echo.
echo  [2/3] Zapusk WhisperWebUI... (Starting WhisperWebUI...)
sc query WhisperWebUI >nul 2>&1
if %errorLevel% neq 0 (
    echo  [!]   WhisperWebUI ne ustanovlen (not installed)
    goto :start_ptt
)
sc query WhisperWebUI | findstr "RUNNING" >nul
if %errorLevel% equ 0 (
    echo  [OK]  WhisperWebUI uzhe zapushchen (already running)
    goto :start_ptt
)
powershell -Command "Start-Service WhisperWebUI -ErrorAction SilentlyContinue"
timeout /t 3 /nobreak >nul
sc query WhisperWebUI | findstr "RUNNING" >nul
if %errorLevel% equ 0 (
    echo  [OK]  WhisperWebUI zapushchen - Web UI: http://localhost:8765
) else (
    echo  [!]   WhisperWebUI ne udalos zapustit (failed to start)
    echo        Provery log: C:\whisper-ptt\logs\whisper-webui.log
)

:: ---- 3. Start whisper-ptt.py (only if NOT already running) ------------------
:start_ptt
echo.
echo  [3/3] Proverka whisper-ptt.py... (Checking whisper-ptt.py...)

:: ===========================================================================
:: BUGFIX: zamenyaem problemnuyu stroku PowerShell s kanalami (|) vnutri kavychek
:: na tasklist — rabotaet na vsekh versiyakh Windows vklyuchaya Win11
:: (wmic udalyon v Windows 11 i privodit k oshibkam)
:: ===========================================================================
tasklist /FI "IMAGENAME eq python.exe" 2>nul | findstr /I "python" >nul 2>&1
if %errorLevel% equ 0 (
    echo  [OK]  whisper-ptt.py uzhe zapushchen (already running) - ne zapuskaem vtorogo okna
    goto :done
)

echo  [3/3] Zapusk whisper-ptt.py... (Starting whisper-ptt.py...)

:: Try launcher bat first
if exist "C:\whisper-ptt\whisper-ptt-launcher.bat" (
    start "Whisper PTT" cmd.exe /c "C:\whisper-ptt\whisper-ptt-launcher.bat"
    echo  [OK]  whisper-ptt.py zapushchen cherez launcher (launched via launcher)
    goto :done
)

:: Find Python - check known paths
set "PYTHON="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :found_python
)
for /f "delims=" %%p in ('where python 2^>nul') do (
    set "PYTHON=%%p"
    goto :found_python
)

echo  [!]   Python ne nayden. Proverite ustanovku Python.
echo        Python not found. Check Python installation.
goto :done

:found_python
if exist "C:\whisper-ptt\whisper-ptt.py" (
    start "Whisper PTT" cmd.exe /k "cd /d C:\whisper-ptt && ""%PYTHON%"" whisper-ptt.py"
    echo  [OK]  whisper-ptt.py zapushchen (launched)
) else (
    echo  [!]   whisper-ptt.py ne nayden v C:\whisper-ptt\
    echo        Zapustite ustanovshik INSTALL.bat
)

:done
echo.
echo  ============================================================
echo.
echo  Status:
:: Read actual server port from gpu-config.json
set "SRV_PORT=9200"
for /f "tokens=2 delims=:, " %%p in ('powershell -NoProfile -Command "if (Test-Path 'C:\\whisper-server\\gpu-config.json') { (Get-Content 'C:\\whisper-server\\gpu-config.json' | ConvertFrom-Json).port }" 2^>nul') do set "SRV_PORT=%%p"
echo    WhisperServer  : http://localhost:%SRV_PORT%/health
echo    WhisperWebUI   : http://localhost:8765
echo    Logs / Logi    : C:\whisper-ptt\logs\
echo.
echo  Goryachie klavishi / Hotkeys:
echo    Pravyy Ctrl  -- russkiy tekst    (Right Ctrl = Russian text)
echo    Pravyy Alt   -- angliyskiy tekst (Right Alt  = English translation)
echo.
pause
