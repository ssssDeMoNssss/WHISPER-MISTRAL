@echo off
chcp 65001 >nul
title Whisper PTT — Service Manager

:MENU
cls
:: Read actual server port from gpu-config.json
set "SRV_PORT=9200"
for /f "usebackq tokens=2 delims=:, " %%p in (`powershell -NoProfile -Command "if (Test-Path 'C:\whisper-server\gpu-config.json') { (Get-Content 'C:\whisper-server\gpu-config.json' | ConvertFrom-Json).port }" 2^>nul`) do set "SRV_PORT=%%p"
echo.
echo  ============================================================
echo   whisper_from_sssDeMoNsss — Service Manager
echo   (Menejer servisa whisper_from_sssDeMoNsss)
echo  ============================================================
echo.

REM Get current service status
for /f "tokens=3" %%s in ('sc query WhisperServer ^| findstr "STATE"') do set SVC_STATE=%%s
if "%SVC_STATE%"=="RUNNING" (
    echo   Status ^(status^): [RUNNING - ZAPUSHCHEN]  ^<-- ACTIVE
) else if "%SVC_STATE%"=="STOPPED" (
    echo   Status ^(status^): [STOPPED - OSTANOVLEN]
) else if "%SVC_STATE%"=="START_PENDING" (
    echo   Status ^(status^): [STARTING... - ZAPUSKAYETSYA...]
) else if "%SVC_STATE%"=="STOP_PENDING" (
    echo   Status ^(status^): [STOPPING... - OSTANVLIVAYETSYA...]
) else (
    echo   Status ^(status^): [NOT INSTALLED - NE USTANOVLEN]
)

REM Try to get health info
echo.
curl -s --max-time 3 http://localhost:%SRV_PORT%/health > %TEMP%\whisper_health.tmp 2>nul
if %ERRORLEVEL%==0 (
    for /f "tokens=*" %%l in (%TEMP%\whisper_health.tmp) do (
        echo   Health ^(proverka^): OK - server responding
    )
) else (
    echo   Health ^(proverka^): Server not responding on :%SRV_PORT%
)
del %TEMP%\whisper_health.tmp 2>nul

echo.
echo  ------------------------------------------------------------
echo   [1]  Start service          ^(Zapustit servis^)
echo   [2]  Stop service           ^(Ostanovit servis^)
echo   [3]  Restart service        ^(Perezapustit servis^)
echo   [4]  Health check           ^(Proverka zdorovya :%SRV_PORT%^)
echo   [5]  View log ^(last 50 lines^)  ^(Prosmotr loga^)
echo   [6]  Switch GPU / Model     ^(Smenit GPU / Model^)
echo   [7]  Open Web UI            ^(Otkryt veb-interfeys :8765^)
echo   [8]  Enable autostart       ^(Vklyuchit avtozapusk^)
echo   [9]  Disable autostart      ^(Vyklyuchit avtozapusk^)
echo   [0]  Exit                   ^(Vyhod^)
echo  ------------------------------------------------------------
echo.
set /p CHOICE="  Choose (vyberte) [0-9]: "

if "%CHOICE%"=="1" goto START_SVC
if "%CHOICE%"=="2" goto STOP_SVC
if "%CHOICE%"=="3" goto RESTART_SVC
if "%CHOICE%"=="4" goto HEALTH
if "%CHOICE%"=="5" goto VIEW_LOG
if "%CHOICE%"=="6" goto SWITCH_GPU
if "%CHOICE%"=="7" goto OPEN_WEBUI
if "%CHOICE%"=="8" goto ENABLE_AUTO
if "%CHOICE%"=="9" goto DISABLE_AUTO
if "%CHOICE%"=="0" goto EXIT
goto MENU

:START_SVC
echo.
echo  Starting WhisperServer (zapuskaem WhisperServer)...
net start WhisperServer
echo.
echo  Press any key to return to menu (lyubuyu klavishu dlya vozvrata)...
pause >nul
goto MENU

:STOP_SVC
echo.
echo  Stopping WhisperServer (ostanvlivayem WhisperServer)...
net stop WhisperServer
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:RESTART_SVC
echo.
echo  Restarting WhisperServer (perezapuskaem WhisperServer)...
net stop WhisperServer
timeout /t 3 /nobreak >nul
net start WhisperServer
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:HEALTH
echo.
echo  Health check: http://localhost:%SRV_PORT%/health
echo  --------------------------------------------
curl -s --max-time 10 http://localhost:%SRV_PORT%/health
echo.
echo.
echo  Models: http://localhost:%SRV_PORT%/models
echo  --------------------------------------------
curl -s --max-time 5 http://localhost:%SRV_PORT%/models
echo.
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:VIEW_LOG
echo.
echo  Last 50 lines of log (posledniye 50 strok loga):
echo  C:\whisper-server\logs\whisper-server.log
echo  --------------------------------------------
if exist "C:\whisper-ptt\logs\whisper-server.log" (
    powershell -Command "Get-Content 'C:\whisper-ptt\logs\whisper-server.log' -Tail 50"
) else (
    echo  Log file not found (fayl loga ne nayden)
)
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:SWITCH_GPU
echo.
echo  Launching GPU switcher (zapuskaem pereklyuchatel GPU)...
if exist "C:\whisper-server\switch-whisper-gpu.ps1" (
    powershell -ExecutionPolicy Bypass -File "C:\whisper-server\switch-whisper-gpu.ps1"
) else if exist "%~dp0switch-whisper-gpu.ps1" (
    powershell -ExecutionPolicy Bypass -File "%~dp0switch-whisper-gpu.ps1"
) else (
    echo  switch-whisper-gpu.ps1 not found!
    echo  Place it in C:\whisper-server\
)
goto MENU

:OPEN_WEBUI
echo.
echo  Opening Web UI in browser (otkryvayem veb-interfeys v brauzere)...
start http://localhost:8765
echo  If browser did not open, go to: http://localhost:8765
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:ENABLE_AUTO
echo.
echo  Enabling autostart (vklyuchayem avtozapusk)...
powershell -Command "Set-Service WhisperServer -StartupType Automatic; Write-Host 'Done (gotovo).'"
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:DISABLE_AUTO
echo.
echo  Disabling autostart (vyklyuchayem avtozapusk)...
powershell -Command "Set-Service WhisperServer -StartupType Disabled; Write-Host 'Done (gotovo).'"
echo.
echo  Press any key to return to menu...
pause >nul
goto MENU

:EXIT
echo.
echo  Goodbye! (Poka!)
echo.
exit /b 0
