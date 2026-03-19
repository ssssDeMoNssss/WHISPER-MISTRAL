@echo off
chcp 65001 >nul 2>&1
title Whisper PTT - Stop All

:: Check administrator rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo  [!] Trebuutsya prava Administratora dlya ostanovki servisov.
    echo      Administrator rights required to stop services.
    echo  Perezapuskaem... Restarting with elevation...
    powershell -Command "Start-Process cmd.exe -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo  ============================================================
echo   whisper_from_sssDeMoNsss -- STOP ALL
echo   Ostanovka vsekh komponentov / Stopping all components
echo  ============================================================
echo.
echo  [OK] Prava Administratora podtverzhdeny
echo.

:: ---- 1. Stop whisper-ptt.py process ----------------------------------------
:: BUGFIX: zamenyaem PowerShell s kaналами (|) i wmic (udalyon v Win11)
:: na taskkill — rabotaet na vsekh versiyakh Windows vklyuchaya Win11
echo  [1/3] Ostanovka whisper-ptt.py... (Stopping whisper-ptt.py...)
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq Whisper PTT*" >nul 2>&1
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq whisper-ptt*"  >nul 2>&1
:: Fallback: kill all python windows with whisper in title
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *whisper*"     >nul 2>&1
echo  [OK]  whisper-ptt.py ostanovlen (stopped or was not running)

:: ---- 2. Stop WhisperWebUI service ------------------------------------------
echo.
echo  [2/3] Ostanovka WhisperWebUI... (Stopping WhisperWebUI...)
sc query WhisperWebUI >nul 2>&1
if %errorLevel% neq 0 (
    echo  [--]  WhisperWebUI ne ustanovlen (not installed)
) else (
    sc query WhisperWebUI | findstr "RUNNING" >nul
    if %errorLevel% equ 0 (
        powershell -Command "Stop-Service WhisperWebUI -Force -ErrorAction SilentlyContinue"
        timeout /t 3 /nobreak >nul
        echo  [OK]  WhisperWebUI ostanovlen (stopped)
    ) else (
        echo  [--]  WhisperWebUI ne zapushchen (not running)
    )
)

:: ---- 3. Stop WhisperServer service (via /shutdown for clean GPU VRAM release)
echo.
echo  [3/3] Ostanovka WhisperServer... (Stopping WhisperServer...)
sc query WhisperServer >nul 2>&1
if %errorLevel% neq 0 (
    echo  [--]  WhisperServer ne ustanovlen (not installed)
) else (
    sc query WhisperServer | findstr "RUNNING" >nul
    if %errorLevel% equ 0 (
        :: Read actual port from gpu-config.json
        set "SRV_PORT=9200"
        for /f "tokens=2 delims=:, " %%p in ('powershell -NoProfile -Command "if (Test-Path 'C:\whisper-server\gpu-config.json') { (Get-Content 'C:\whisper-server\gpu-config.json' | ConvertFrom-Json).port }" 2^>nul') do set "SRV_PORT=%%p"

        :: BUGFIX: peredayom %SRV_PORT% cherez -Command s podstanovkoy znacheniya,
        :: a ne cherez $env (CMD-peremennaya ne peredayotsya v $env avtomaticheski)
        powershell -Command "try { Invoke-WebRequest ('http://localhost:%SRV_PORT%/shutdown') -TimeoutSec 3 -ErrorAction Stop } catch {}" >nul 2>&1
        timeout /t 2 /nobreak >nul
        powershell -Command "Stop-Service WhisperServer -Force -ErrorAction SilentlyContinue"
        timeout /t 3 /nobreak >nul
        echo  [OK]  WhisperServer ostanovlen (stopped, GPU VRAM freed)
    ) else (
        echo  [--]  WhisperServer ne zapushchen (not running)
    )
)

echo.
echo  ============================================================
echo.
echo  Vse komponenty Whisper PTT ostanovleny.
echo  (All Whisper PTT components stopped.)
echo.
echo  Dlya zapuska ispolzuyte START-whisper.bat
echo  (To start again use START-whisper.bat)
echo.
pause
