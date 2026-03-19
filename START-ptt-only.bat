@echo off
chcp 65001 >nul 2>&1
title Whisper PTT - Launch PTT Only

echo.
echo  ============================================================
echo   whisper_from_sssDeMoNsss -- START PTT ONLY
echo   Zapusk tolko whisper-ptt.py / Launch whisper-ptt.py only
echo  ============================================================
echo.

:: ============================================================================
:: Shag 1: Naydti whisper-ptt.py
:: Prioritety: 1) C:\whisper-ptt\  2) Papka etogo .bat fayla
:: ============================================================================
set "PTT_DIR="
set "PTT_FILE="

if exist "C:\whisper-ptt\whisper-ptt.py" (
    set "PTT_DIR=C:\whisper-ptt"
    set "PTT_FILE=C:\whisper-ptt\whisper-ptt.py"
    echo  [OK] Naydeno v: C:\whisper-ptt\whisper-ptt.py
    goto :check_running
)
if exist "%~dp0whisper-ptt.py" (
    set "PTT_DIR=%~dp0"
    set "PTT_FILE=%~dp0whisper-ptt.py"
    echo  [OK] Naydeno v: %~dp0whisper-ptt.py
    goto :check_running
)

echo  [!!] OSHIBKA: whisper-ptt.py ne naydeno!
echo.
echo       Provereno:
echo         1) C:\whisper-ptt\whisper-ptt.py
echo         2) %~dp0whisper-ptt.py
echo.
echo       Reshenie: zapustite INSTALL.bat ili polozhite etot .bat
echo       v odnu papku s whisper-ptt.py
echo.
pause
exit /b 1

:: ============================================================================
:: Shag 2: Proverka -- uzhe zapushchen?
:: Ispolzuem tasklist (rabotaet na vsekh versiyakh Windows vklyuchaya Win11)
:: ============================================================================
:check_running
echo  [..] Proverka: zapushchen li uzhe whisper-ptt.py?

tasklist /FI "IMAGENAME eq python.exe" 2>nul | findstr /I "python" >nul
if %errorLevel% equ 0 (
    echo  [!]  VNIMANIE: protsess python.exe uzhe zapushchen.
    echo       Vozmozhno whisper-ptt.py uzhe rabotaet.
    echo.
    echo       [Enter]  -- vse ravno zapustit novoe okno
    echo       [Ctrl+C] -- otmena
    echo.
    set /p "CHOICE=  Vash vybor: "
    echo.
) else (
    echo  [OK] Python ne zapushchen. Prodolzhaem...
    echo.
)

:: ============================================================================
:: Shag 3: Naydti Python
:: ============================================================================
set "PYTHON="

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :launch
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :launch
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :launch
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :launch
)
if exist "C:\whisper-ptt\venv\Scripts\python.exe" (
    set "PYTHON=C:\whisper-ptt\venv\Scripts\python.exe"
    goto :launch
)
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON=%~dp0venv\Scripts\python.exe"
    goto :launch
)
for /f "delims=" %%p in ('where python 2^>nul') do (
    set "PYTHON=%%p"
    goto :launch
)

echo  [!!] OSHIBKA: Python ne naydyon!
echo.
echo       Provereno:
echo         - %%LOCALAPPDATA%%\Programs\Python\Python313\
echo         - %%LOCALAPPDATA%%\Programs\Python\Python312\
echo         - %%LOCALAPPDATA%%\Programs\Python\Python311\
echo         - %%LOCALAPPDATA%%\Programs\Python\Python310\
echo         - C:\whisper-ptt\venv\Scripts\
echo         - %~dp0venv\Scripts\
echo         - PATH (where python)
echo.
echo       Reshenie: ustanovite Python 3.10+ ili zapustite INSTALL.bat
echo.
pause
exit /b 1

:: ============================================================================
:: Shag 4: Zapishem zapusk v vremennyj .bat i otkroem ego cherez start
:: Eto izbekaet problemy s vlozhennymi kavychkami v komande start
:: ============================================================================
:launch
echo  [OK] Python: %PYTHON%
echo  [OK] Skript: %PTT_FILE%
echo  [OK] Papka : %PTT_DIR%
echo.

:: Sozdaem vremennyj launcher chtoby ne bylo problem s kavychkami
set "LAUNCHER=%TEMP%\whisper-ptt-run.bat"
(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title Whisper PTT [Running]
    echo cd /d "%PTT_DIR%"
    echo echo.
    echo echo  [Whisper PTT ZAPUSHCHEN / RUNNING]
    echo echo  [Ctrl+C = ostanovit / stop]
    echo echo.
    echo "%PYTHON%" "%PTT_FILE%"
    echo echo.
    echo echo  [Protsess zavershyon / Process exited]
    echo pause
) > "%LAUNCHER%"

echo  [>>] Otkryvayu novoe okno...
start "Whisper PTT [Running]" cmd.exe /k "%LAUNCHER%"

echo  [OK] Okno zapushcheno uspeshno!
echo.
echo  ============================================================
echo   Goryachie klavishi / Hotkeys:
echo     Pravyy Ctrl  --  russkiy tekst    (Right Ctrl = Russian)
echo     Pravyy Alt   --  angliyskiy tekst (Right Alt  = English)
echo  ============================================================
echo.
echo  Eto okno mozhno zakryt. / You may close this window.
echo.
pause
