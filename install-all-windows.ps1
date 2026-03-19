# ============================================================
#  whisper_from_sssDeMoNsss -- MASTER INSTALLER (Windows)
#  Polnaya ustanovka na odin Windows PK:
#    1. whisper-ptt        (PTT-klient, trey, goryachie klavishi)
#    2. whisper-server     (Whisper na GPU, Windows Service)
#    3. whisper-webui      (Veb-panel' upravleniya, Windows Service)
#
#  Avtor: sssDeMoNsss | vk.com/basset2 | @snnike
#
#  ZAPUSK (ot imeni Administratora):
#    powershell -ExecutionPolicy Bypass -File "install-all-windows.ps1"
#
#  FAYLY -- vse v odnoy papke s etim skriptom:
#    install-all-windows.ps1          <- etot fayl
#    install-whisper-ptt.ps1
#    install-whisper-server-windows.ps1
#    whisper-ptt.py
#    whisper-server.py
#    whisper-webui.py
#    config.toml
# ============================================================

$ErrorActionPreference = "Continue"

# -- Helpers -------------------------------------------------------------------
function Write-Banner($text, $color = "Cyan") {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor $color
    Write-Host "  $text" -ForegroundColor $color
    Write-Host "============================================================" -ForegroundColor $color
    Write-Host ""
}
function Write-Step($n, $text) {
    Write-Host ""
    Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "  [$n] $text" -ForegroundColor Yellow
    Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host ""
}
function Write-OK($t)   { Write-Host "  [OK]    $t" -ForegroundColor Green   }
function Write-Warn($t) { Write-Host "  [!]     $t" -ForegroundColor Yellow  }
function Write-Err($t)  { Write-Host "  [ERROR] $t" -ForegroundColor Red     }
function Write-Info($t) { Write-Host "  [INFO]  $t" -ForegroundColor Cyan    }

# -- Banner --------------------------------------------------------------------
Clear-Host
Write-Host ""
Write-Host "  +==========================================================+" -ForegroundColor Cyan
Write-Host "  |   whisper_from_sssDeMoNsss -- MASTER INSTALLER           |" -ForegroundColor Cyan
Write-Host "  |   Govori, ne pechatay. / Speak, don't type.              |" -ForegroundColor White
Write-Host "  |                                                          |" -ForegroundColor Cyan
Write-Host "  |   Skhema: vsyo na odnom Windows PK                        |" -ForegroundColor Gray
Write-Host "  |   PTT-klient + Whisper Server (GPU) + Web UI            |" -ForegroundColor Gray
Write-Host "  |                                                          |" -ForegroundColor Cyan
Write-Host "  |   Avtor: sssDeMoNsss | vk.com/basset2 | @snnike         |" -ForegroundColor Gray
Write-Host "  +==========================================================+" -ForegroundColor Cyan
Write-Host ""

# -- Admin check ---------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
           [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err "Nuzhno zapustit' ot imeni Administratora!"
    Write-Err "(Right-click -> Run as administrator)"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-OK "Administrator rights confirmed"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Info "Papka ustanovshchika (Installer folder): $scriptDir"

# -- Check required files ------------------------------------------------------
Write-Host ""
Write-Host "  Checking required files..." -ForegroundColor White
Write-Host ""

$requiredFiles = @(
    "install-whisper-ptt.ps1",
    "install-whisper-server-windows.ps1",
    "whisper-ptt.py",
    "whisper-server.py",
    "whisper-webui.py",
    "config.toml",
    "START-whisper.bat",
    "START-ptt-only.bat",
    "STOP-whisper.bat"
)

$missingFiles = @()
foreach ($f in $requiredFiles) {
    $path = Join-Path $scriptDir $f
    if (Test-Path $path) {
        Write-OK "$f"
    } else {
        Write-Err "$f -- NE NAYDEN (NOT FOUND)"
        $missingFiles += $f
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host ""
    Write-Err "Otsutstvuyut fayly (Missing files): $($missingFiles -join ', ')"
    Write-Err "Pomestite vse fayly v odnu papku s etim ustanovshchikom."
    Write-Err "(Place all files in the same folder as this installer.)"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-OK "All files found!"

# ==============================================================================
# DIAGNOSTIC MENU  — run BEFORE installation to verify system readiness
# ==============================================================================
Write-Host ""
Write-Host "  +============================================================+" -ForegroundColor Cyan
Write-Host "  |   WHAT DO YOU WANT TO DO?  (Chto khotite sdelat?)          |" -ForegroundColor Cyan
Write-Host "  +============================================================+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [D]  DIAGNOSTIKA — proverit sistemu PERED ustanovkoy"          -ForegroundColor Yellow
Write-Host "       (DIAGNOSE — check system BEFORE installation)"             -ForegroundColor DarkGray
Write-Host "       Proverka: mikrofon, GPU, FFmpeg, pakety, server, model,   " -ForegroundColor Gray
Write-Host "       bufer obmena. Otchet [OK]/[FAIL] s rekomendatsiyami.      " -ForegroundColor Gray
Write-Host ""
Write-Host "  [Enter]  Nachat USTANOVKU (Start INSTALLATION)"                -ForegroundColor Green
Write-Host ""

$preChoice = Read-Host "  Vvedite D dlya diagnostiki ili Enter dlya ustanovki [D/Enter]"
$preChoice = $preChoice.Trim().ToUpper()

if ($preChoice -eq "D") {
    # ── Find Python for diagnostics ───────────────────────────────────────────
    $DiagPython = ""
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )) { if (Test-Path $p) { $DiagPython = $p; break } }
    if (-not $DiagPython) {
        $f = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($f) { $DiagPython = $f }
    }

    if (-not $DiagPython) {
        Write-Host ""
        Write-Host "  [!]  Python ne nayden — diagnostika nedostupna." -ForegroundColor Red
        Write-Host "       Ustanovite Python 3.10+ i povtorite."        -ForegroundColor Yellow
        Write-Host "       (Python not found — diagnostics unavailable.)" -ForegroundColor DarkGray
        Write-Host ""
        Read-Host "  Press Enter to continue to installation"
    } else {
        # ── Find whisper-ptt.py ───────────────────────────────────────────────
        $DiagScript = Join-Path $scriptDir "whisper-ptt.py"
        if (-not (Test-Path $DiagScript)) {
            $DiagScript = "C:\whisper-ptt\whisper-ptt.py"
        }

        if (-not (Test-Path $DiagScript)) {
            Write-Host ""
            Write-Host "  [!]  whisper-ptt.py ne nayden — diagnostika nedostupna." -ForegroundColor Red
            Write-Host "       (whisper-ptt.py not found — diagnostics unavailable.)" -ForegroundColor DarkGray
            Write-Host ""
            Read-Host "  Press Enter to continue to installation"
        } else {
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Yellow
            Write-Host "  DIAGNOSTIKA SISTEMY / SYSTEM DIAGNOSTICS"                     -ForegroundColor Yellow
            Write-Host "  Python: $DiagPython"                                           -ForegroundColor Gray
            Write-Host "  Script: $DiagScript"                                           -ForegroundColor Gray
            Write-Host "  ============================================================" -ForegroundColor Yellow
            Write-Host ""

            # Run diagnostics in the same console window so user sees output
            & $DiagPython $DiagScript --diagnose

            $diagExit = $LASTEXITCODE
            Write-Host ""
            if ($diagExit -eq 0) {
                Write-Host "  +============================================================+" -ForegroundColor Green
                Write-Host "  |  Vse proverki proideny! Sistema gotova k rabote.           |" -ForegroundColor Green
                Write-Host "  |  (All checks passed! System is ready.)                     |" -ForegroundColor Green
                Write-Host "  +============================================================+" -ForegroundColor Green
            } else {
                Write-Host "  +============================================================+" -ForegroundColor Red
                Write-Host "  |  Naideny problemy (issues found). Smotrite rekomendatsii.  |" -ForegroundColor Red
                Write-Host "  |  (Issues found. See advice above.)                         |" -ForegroundColor Red
                Write-Host "  +============================================================+" -ForegroundColor Red
            }
            Write-Host ""
            Write-Host "  Otchet sohranyon v: logs\whisper-diagnose.log" -ForegroundColor Gray
            Write-Host "  (Report saved to:   logs\whisper-diagnose.log)" -ForegroundColor DarkGray
            Write-Host ""

            $diagContinue = Read-Host "  Prodolzhit ustanovku? Continue with installation? [Enter = yes / N = exit]"
            $diagContinue = $diagContinue.Trim().ToUpper()
            if ($diagContinue -eq "N") {
                Write-Host ""
                Write-Host "  Ustanovka otmenena. Ispravte problemy i zapustite INSTALL.bat snova." -ForegroundColor Yellow
                Write-Host "  (Installation cancelled. Fix issues and re-run INSTALL.bat.)"          -ForegroundColor DarkGray
                Write-Host ""
                Read-Host "  Press Enter to exit"
                exit 0
            }
        }
    }
    Write-Host ""
    Write-Host "  Prodolzhayem ustanovku... (Continuing with installation...)" -ForegroundColor Cyan
    Write-Host ""
}

# -- User choices --------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor White
Write-Host "  INSTALLATION SETTINGS" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor White
Write-Host ""

# PTT version
# ============================================================
# STEP 0: Choose server mode (CLASSIC or LIVE)
# ============================================================
Write-Host ""
Write-Host "  +============================================================+" -ForegroundColor Cyan
Write-Host "  |  VYBOR REZHIMA SERVERA / Choose server mode               |" -ForegroundColor Cyan
Write-Host "  +============================================================+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [1]  whisper_from_sssDeMoNsss  (KLASSICHESKIY / CLASSIC)" -ForegroundColor Green
Write-Host "       RU: Klassicheskiy PTT-rezhim. Nazhali klavishu ->" -ForegroundColor Gray
Write-Host "           skazali frazu - otpustili - tekst vstavlen." -ForegroundColor Gray
Write-Host "       RU: Maksimalnaya tochnost (large-v2), luchshaya punktuatsiya." -ForegroundColor Gray
Write-Host "       RU: Zaderzhka: 0.5-1 sek na GPU, 3-8 sek na CPU." -ForegroundColor Gray
Write-Host "       EN: Classic PTT mode. Hold key, speak, release - text pasted." -ForegroundColor DarkGray
Write-Host "       EN: Best accuracy, best punctuation, best Russian support." -ForegroundColor DarkGray
Write-Host "       EN: Delay: 0.5-1s GPU / 3-8s CPU. HTTP server port 9200." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  [2]  whisper_from_sssDeMoNsss-live  (LIVE / POTOKOVY)" -ForegroundColor Cyan
Write-Host "       RU: Potokovy rezhim - tekst poyavlyaetsya v REALNOM VREMENI" -ForegroundColor Gray
Write-Host "           poka vy govorite (kak diktovka na iPhone)." -ForegroundColor Gray
Write-Host "       RU: Nizhe tochnost chem klassika (Whisper ne optimizirovan" -ForegroundColor Gray
Write-Host "           dlya korotkih fragmentov). Tochka / zapyatye khuzhe." -ForegroundColor Gray
Write-Host "       RU: Pervye slova poyavlyayutsya za ~0.8 sek. WebSocket port 9201." -ForegroundColor Gray
Write-Host "       EN: Streaming mode - text appears in REAL-TIME while speaking." -ForegroundColor DarkGray
Write-Host "       EN: Like iPhone dictation. Lower accuracy on short phrases." -ForegroundColor DarkGray
Write-Host "       EN: WebSocket server port 9201. First words appear in ~0.8s." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  SRAVNENIE / COMPARISON:" -ForegroundColor White
Write-Host "    Tochnost     : Classic >> Live  (Classic is more accurate)" -ForegroundColor Gray
Write-Host "    Pervye slova : Live ~0.8s / Classic ~1-2s after release" -ForegroundColor Gray
Write-Host "    Punktuatsiya : Classic >> Live" -ForegroundColor Gray
Write-Host "    Perevod RU-EN: oba rezhima / both modes support it" -ForegroundColor Gray
Write-Host "    Rekomendatsiya: Nachni s Classic. Pereidi na Live esli nuzhen" -ForegroundColor Green
Write-Host "                   real-time prosmotr teksta v konsoli." -ForegroundColor Green
Write-Host ""
$serverModeInput = Read-Host "  Enter 1 or 2 [Enter = 1 (Classic)]"
$serverModeInput = $serverModeInput.Trim()
if ($serverModeInput -eq "2") {
    $serverMode = "live"
    Write-Host "  [OK] Mode selected: whisper_from_sssDeMoNsss-live (LIVE streaming)" -ForegroundColor Cyan
} else {
    $serverMode = "classic"
    Write-Host "  [OK] Mode selected: whisper_from_sssDeMoNsss (Classic PTT)" -ForegroundColor Green
}
Write-Host ""

# ============================================================
Write-Host "  ============================================================" -ForegroundColor White
Write-Host "  INSTALLATION SETTINGS" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor White
Write-Host ""

Write-Host "  Vyberite versiyu PTT (Choose PTT version):" -ForegroundColor White
Write-Host ""
Write-Host "  [1]  RU-ENG  -- speakte po-RUSSKI  (speak RUSSIAN)"  -ForegroundColor Green
Write-Host "       Pravyy Ctrl = russkiy tekst | Pravyy Alt = angliyskiy perevod" -ForegroundColor Gray
Write-Host ""
Write-Host "  [2]  ENG-RU  -- speakte po-ANGLIYSKI  (speak ENGLISH)" -ForegroundColor Cyan
Write-Host "       Pravyy Ctrl = angliyskiy tekst | Pravyy Alt = russkiy perevod" -ForegroundColor Gray
Write-Host ""
Write-Host "  [3]  Both versions" -ForegroundColor Magenta
Write-Host ""
$pttChoice = Read-Host "  Enter 1, 2 or 3 [Enter = 1]"
$pttChoice = $pttChoice.Trim()
if ($pttChoice -eq "") { $pttChoice = "1" }

switch ($pttChoice) {
    "1" { $pttVersions = @("1");      $pttLabel = "RU-ENG" }
    "2" { $pttVersions = @("2");      $pttLabel = "ENG-RU" }
    "3" { $pttVersions = @("1", "2"); $pttLabel = "RU-ENG + ENG-RU" }
    default {
        Write-Warn "Nevernyy vybor, ispol'zuem RU-ENG po umolchaniyu."
        $pttVersions = @("1"); $pttLabel = "RU-ENG"
    }
}
Write-OK "PTT versiya: $pttLabel"

# GPU choice
Write-Host ""
Write-Host "  Vyberite GPU dlya Whisper Server (Choose GPU for Whisper Server):" -ForegroundColor White
Write-Host ""

# Auto-detect GPUs
$PYTHON_EXE = ""
foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)) { if (Test-Path $p) { $PYTHON_EXE = $p; break } }
if (-not $PYTHON_EXE) {
    $found = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($found) { $PYTHON_EXE = $found }
}

$detectedGPUs = @()
if ($PYTHON_EXE) {
    try {
        $gpuCount = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.device_count())" 2>&1).Trim()
        for ($i = 0; $i -lt $gpuCount; $i++) {
            $gpuName   = (& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_name($i))"  2>&1).Trim()
            $gpuVramMB = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_properties($i).total_memory // 1024 // 1024)" 2>&1).Trim()
            $gpuVramGB = [math]::Round($gpuVramMB / 1024, 1)
            if     ($gpuVramMB -ge 9000) { $optModel = "large-v3"; $tag = "MAXIMUM+" }
            elseif ($gpuVramMB -ge 6000) { $optModel = "large-v2"; $tag = "MAXIMUM"  }
            elseif ($gpuVramMB -ge 3000) { $optModel = "medium";   $tag = "HIGH"     }
            elseif ($gpuVramMB -ge 1300) { $optModel = "small";    $tag = "GREAT"    }
            else                         { $optModel = "base";     $tag = "GOOD"     }
            $detectedGPUs += [PSCustomObject]@{
                Index = $i; Name = $gpuName
                VramGB = $gpuVramGB; VramMB = $gpuVramMB
                OptModel = $optModel; Tag = $tag
            }
            Write-Host "  [$i]  $gpuName -- ${gpuVramGB} GB  ->  rekomenduetsya: $optModel ($tag)" -ForegroundColor Cyan
        }
    } catch {}
}

if ($detectedGPUs.Count -eq 0) {
    Write-Host ""
    Write-Warn "GPU (NVIDIA CUDA) ne obnaruzheny -- budet ispol'zovan CPU."
    Write-Warn "(No NVIDIA CUDA GPUs detected -- CPU mode will be used.)"
    Write-Host "  CPU mode: model 'small' rekomenduetsya (small recommended for CPU)." -ForegroundColor Gray
    $selectedGpuIndex = -1
    $selectedGpuName  = "CPU"
    $useCPU = $true
} else {
    # Show CPU option at the bottom of the list
    $cpuIdx = $detectedGPUs.Count
    Write-Host "  [$cpuIdx]  CPU (bez GPU / no GPU) -- dlya noutbukov i slabykh PK" -ForegroundColor Gray
    Write-Host "        (For laptops, low-power PCs or if GPU causes issues)" -ForegroundColor DarkGray
    Write-Host "        Recommended model: small (~1.3 GB RAM, ~3-8 sec per phrase)" -ForegroundColor DarkGray
    Write-Host ""
    $gpuInput = Read-Host "  Enter GPU index or [$cpuIdx] for CPU [Enter = 0]"
    $gpuInput = $gpuInput.Trim()
    if ($gpuInput -eq "" -or -not ($gpuInput -match '^\d+$')) { $gpuInput = "0" }
    $gpuIdx = [int]$gpuInput
    if ($gpuIdx -eq $cpuIdx) {
        # User explicitly chose CPU
        $selectedGpuIndex = -1
        $selectedGpuName  = "CPU"
        $useCPU = $true
        Write-OK "Selected: CPU mode (rezhim CPU)"
        Write-Host "  CPU mode: transcription will take 3-8 sec per phrase." -ForegroundColor Gray
        Write-Host "  For best CPU performance use model 'small'." -ForegroundColor Gray
    } else {
        if ($gpuIdx -ge $detectedGPUs.Count) { $gpuIdx = 0 }
        $selectedGpuIndex = $gpuIdx
        $selectedGpuName  = $detectedGPUs[$gpuIdx].Name
        $useCPU = $false
        Write-OK "Selected GPU: [$selectedGpuIndex] $selectedGpuName"
    }
}

# Web UI always opens after install — it is the main control panel
$openBrowser = $true
Write-Host ""
Write-Host "  [OK] Web UI otkroyetsya v brauzere posle ustanovki (Web UI will open after install)." -ForegroundColor Cyan

# -- Port selection: default 9200, ask only if occupied by ANOTHER process ----
$DEFAULT_PORT = 9200
$serverPort   = $DEFAULT_PORT

# Check if 9200 is free OR occupied by our own WhisperServer service.
# Only ask the user if the port is taken by something else entirely.
$portOccupiedByOther = $false
try {
    $conn = Get-NetTCPConnection -LocalPort $DEFAULT_PORT -ErrorAction SilentlyContinue
    if ($conn) {
        # Port is in use — check if it belongs to WhisperServer service
        $svc = Get-CimInstance Win32_Service -Filter "Name='WhisperServer'" -ErrorAction SilentlyContinue
        $svcPid = if ($svc) { $svc.ProcessId } else { 0 }
        $portPids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
        # If every PID on this port belongs to our service (or NSSM wrapping it) — it's ours
        $foreignPids = $portPids | Where-Object { $_ -ne $svcPid -and $_ -ne 0 }
        if ($foreignPids) {
            # At least one PID on port 9200 is NOT our service
            $portOccupiedByOther = $true
        } else {
            Write-OK "Server port: $DEFAULT_PORT (occupied by WhisperServer — will be reused)"
        }
    }
} catch {}

if (-not $portOccupiedByOther) {
    # Port free or owned by our service — use default silently
    if (-not (Get-NetTCPConnection -LocalPort $DEFAULT_PORT -ErrorAction SilentlyContinue)) {
        Write-OK "Server port: $DEFAULT_PORT (default, free)"
    }
} else {
    # Port 9200 is taken by a foreign process — ask for alternative
    Write-Host ""
    Write-Host "  -------------------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "  [!]  Port $DEFAULT_PORT is IN USE by another application!" -ForegroundColor Red
    Write-Host "     Please choose another port (e.g. 9100, 9201, 9300)" -ForegroundColor Yellow
    Write-Host ""
    $portInput = Read-Host "  Enter port number [Enter = 9100]"
    $portInput = $portInput.Trim()
    if ($portInput -eq "" -or -not ($portInput -match '^\d+$')) {
        $serverPort = 9100
    } else {
        $p = [int]$portInput
        $serverPort = if ($p -ge 1024 -and $p -le 65535) { $p } else { 9100 }
    }
    Write-OK "Selected port: $serverPort"
}

# -- Model selection (ONE TIME for the whole installation) --------------------
Write-Host ""
Write-Host "  -------------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host "  Vyberite model' Whisper (Choose Whisper model):" -ForegroundColor White
Write-Host ""
Write-Host "  Model' ispol'zuetsya na WhisperServer (GPU). PTT klient ispol'zuet" -ForegroundColor Gray
Write-Host "  lokal'nuyu model' 'medium' tol'ko esli server vremenno nedostupen." -ForegroundColor Gray
Write-Host "  (Model runs on WhisperServer GPU. PTT falls back to local 'medium' only if server is down.)" -ForegroundColor DarkGray
Write-Host ""

# CPU mode: recommend small (fast enough on CPU, ~3-8 sec/phrase)
# GPU mode: use detected optimal model
$optModelName = if ($useCPU) {
    "small"
} elseif ($detectedGPUs.Count -gt 0 -and $selectedGpuIndex -ge 0) {
    $detectedGPUs[$selectedGpuIndex].OptModel
} else {
    "small"
}
$modelMenu = [ordered]@{
    "1" = "tiny"
    "2" = "base"
    "3" = "small"
    "4" = "medium"
    "5" = "large-v2"
    "6" = "large-v3"
}
$qualityMap = @{
    "tiny"="BASIC -- fastest, lowest accuracy (~0.5 GB VRAM)"
    "base"="GOOD  -- fast, lower accuracy (~0.7 GB VRAM)"
    "small"="GREAT -- fast and accurate (~1.3 GB VRAM)"
    "medium"="HIGH  -- excellent for everyday use (~2.9 GB VRAM)"
    "large-v2"="MAXIMUM -- best for Russian (~5.5 GB VRAM)"
    "large-v3"="MAXIMUM+ -- latest model (~6.0 GB VRAM)"
}
foreach ($k in $modelMenu.Keys) {
    $mName = $modelMenu[$k]
    $qual  = $qualityMap[$mName]
    $rec   = if ($mName -eq $optModelName) { " <- RECOMMENDED (rekomenduetsya)" } else { "" }
    $col   = if ($mName -eq $optModelName) { "Green" } else { "Cyan" }
    Write-Host "  [$k]  $mName  -- $qual$rec" -ForegroundColor $col
}
Write-Host ""
$modelInput = Read-Host "  Vyberite model' (Enter 1-6) [Enter = $optModelName]"
$modelInput = $modelInput.Trim()
$selectedModel = $optModelName
if ($modelMenu.Contains($modelInput)) { $selectedModel = $modelMenu[$modelInput] }
Write-OK "Selected model: $selectedModel"

# -- Autostart preference (ONE TIME) ------------------------------------------
Write-Host ""
Write-Host "  -------------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host "  Avtozapusk Whisper PTT pri vkhode v Windows:" -ForegroundColor White
Write-Host "  (Autostart Whisper PTT on Windows login:)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  [1]  Vklyuchit' avtozapusk (Enable autostart) -- rekomenduetsya" -ForegroundColor Green
Write-Host "  [2]  Ne vklyuchat' -- zapuskat' vruchnuyu yarlykom (Disable -- launch manually)" -ForegroundColor Gray
Write-Host ""
$autostartInput = Read-Host "  Vyberite 1 ili 2 (Enter 1 or 2) [Enter = 1]"
$autostartInput = $autostartInput.Trim()
$enableAutostart = ($autostartInput -ne "2")
if ($enableAutostart) {
    Write-OK "Avtozapusk: VKLYuChYoN (Autostart: ENABLED)"
} else {
    Write-Host "  Avtozapusk: otklyuchyon. Zapusk vruchnuyu yarlykom na rabochem stole." -ForegroundColor Gray
}
$autostartAnswer = if ($enableAutostart) { "1" } else { "5" }

# Win+H conflict -- always disable (no question needed)
$doDisableWinH = $true

# Confirm
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  INSTALLATION SUMMARY:" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  PTT version      : $pttLabel"        -ForegroundColor White
if ($useCPU) {
    Write-Host "  Device        : CPU (no GPU / bez GPU)" -ForegroundColor Yellow
    Write-Host "  Note: CPU mode is slower (~3-8 sec/phrase). Recommended model: small." -ForegroundColor Gray
} else {
    Write-Host "  Server GPU   : $selectedGpuName" -ForegroundColor Cyan
}
Write-Host "  Model' Whisper (Whisper model) : $selectedModel"   -ForegroundColor Green
Write-Host "    +- WhisperServer (GPU)        : $selectedModel"   -ForegroundColor Green
Write-Host "    `- PTT lokal'no (local fallback): medium"         -ForegroundColor Gray
Write-Host "  Avtozapusk PTT (Autostart)     : $(if ($enableAutostart) { 'DA / YES' } else { 'net / no' })" -ForegroundColor White
Write-Host "  Otkryt' brauzer (Open browser) : $openBrowser"    -ForegroundColor White
Write-Host "  Port WhisperServer (Port)       : $serverPort"    -ForegroundColor Yellow
Write-Host ""
Write-Host "  What will be installed:"  -ForegroundColor White
Write-Host "    [OK] whisper-ptt         -> C:\whisper-ptt\ (i/or C:\whisper-ptt-eng\)" -ForegroundColor Gray
Write-Host "    [OK] WhisperServer       -> Windows Service, model' [$selectedModel], port $serverPort" -ForegroundColor Gray
Write-Host "    [OK] WhisperWebUI        -> Windows Service, port 8765" -ForegroundColor Gray
Write-Host "    [OK] config.toml         -> remote mode = localhost:$serverPort" -ForegroundColor Gray
Write-Host "    [OK] Desktop shortcuts" -ForegroundColor Gray
Write-Host ""

$confirm = Read-Host "  Nachat' ustanovku? (Start installation?) [Enter = da/yes]"
$confirm = $confirm.Trim().ToLower()
if ($confirm -ne "" -and $confirm -ne "y" -and $confirm -ne "yes" -and $confirm -ne "da") {
    Write-Warn "Installation cancelled."
    Read-Host "Press Enter to exit"
    exit 0
}

$totalErrors = 0

# ==============================================================================
Write-Banner "ShAG 1 / STEP 1: Ustanovka PTT-klienta (whisper-ptt)" "Green"
# ==============================================================================
# Strategiya: peredayom vse otvety cherez pipe stdin chtoby install-whisper-ptt.ps1
# ne zadaval voprosy povtorno. Zapuskaem v TEKUShchEM okne (ne v novom) cherez
# cmd /c echo + powershell. Final'nye voprosy ("Launch now?" i "Press Enter")
# podavlyaem tozhe cherez pipe.
# (Strategy: pipe all answers so install-whisper-ptt.ps1 asks nothing interactively.)

# ── Remove ALL existing Whisper PTT autostart tasks before install ────────────
# Ensures no old or conflicting versions run on startup after reinstall.
Write-Info "Clearing old PTT autostart tasks (ochistka starykh zadach avtozapuska)..."
@("Whisper PTT Autostart","Whisper PTT Autostart RU","Whisper PTT Autostart ENG",
  "Whisper PTT Autostart ENG-RU","Whisper PTT") | ForEach-Object {
    if (Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "  [OK] Removed old task: $_" -ForegroundColor Gray
    }
}

$pttInstaller = Join-Path $scriptDir "install-whisper-ptt.ps1"

foreach ($ver in $pttVersions) {
    Write-Info "Installing PTT version $ver (Installing PTT version $ver)..."
    Write-Host ""

    # GPU-данные передаются через параметры командной строки — НЕ через piped stdin.
    # В piped stdin остались только: версия PTT, автозапуск, "Launch now? n", Press Enter.
    $pttGpuIndex   = if ($useCPU) { -1 } elseif ($selectedGpuIndex -ge 0) { $selectedGpuIndex } else { 0 }
    $pttDevice     = if ($useCPU) { "cpu" } else { "cuda" }
    $pttCompute    = if ($useCPU) { "int8" } else { "float16" }
    # PTT клиент использует medium как fallback когда сервер недоступен
    $pttModel      = "medium"

    # Piped answers: 1=version, 2=autostart, 3=launch now (n), 4=Press Enter
    $answers = "$ver`n$autostartAnswer`nn`n`n"

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName               = "powershell.exe"
        $psi.Arguments              = "-ExecutionPolicy Bypass -File `"$pttInstaller`" -ServerPort $serverPort -GpuIndex $pttGpuIndex -GpuDevice `"$pttDevice`" -GpuModel `"$pttModel`" -GpuCompute `"$pttCompute`""
        $psi.WorkingDirectory       = $scriptDir
        $psi.UseShellExecute        = $false
        $psi.RedirectStandardInput  = $true
        $psi.RedirectStandardOutput = $false
        $psi.RedirectStandardError  = $false
        $psi.CreateNoWindow         = $false

        $proc = [System.Diagnostics.Process]::Start($psi)

        $answersArray = $answers -split "`n"
        foreach ($line in $answersArray) {
            Start-Sleep -Milliseconds 300
            $proc.StandardInput.WriteLine($line)
        }
        $proc.StandardInput.Close()
        $proc.WaitForExit()

        if ($proc.ExitCode -eq 0) {
            Write-OK "PTT versiya $ver installed successfully"
        } else {
            Write-Warn "PTT versiya $ver zavershilas' s kodom $($proc.ExitCode)"
        }
    } catch {
        Write-Err "Oshibka ustanovki PTT versii $ver`: $_"
        $totalErrors++
    }

    if ($pttVersions.Count -gt 1 -and $ver -ne $pttVersions[-1]) {
        Write-Host ""
        Write-Info "Pause before next version..."
        Start-Sleep -Seconds 2
    }
}

# -- Disable Win+H inline (no script, no interactive prompts) -----------------
if ($doDisableWinH) {
    Write-Info "Otklyuchaem Win+H konflikt napryamuyu cherez reestr... (Disabling Win+H via registry...)"
    try {
        # 1. Disable voice activation
        $sp = "HKCU:\Software\Microsoft\Speech_OneCore\Settings\VoiceActivation"
        if (-not (Test-Path $sp)) { New-Item -Path $sp -Force | Out-Null }
        Set-ItemProperty -Path $sp -Name "AgentActivationEnabled" -Value 0 -Type DWord -Force

        # 2. Disable online speech privacy acceptance (prevents Win+H prompt)
        $pp = "HKCU:\Software\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy"
        if (-not (Test-Path $pp)) { New-Item -Path $pp -Force | Out-Null }
        Set-ItemProperty -Path $pp -Name "HasAccepted" -Value 0 -Type DWord -Force

        # 3. Disable Win+H hotkey in input settings
        $ip = "HKCU:\Software\Microsoft\input\Settings"
        if (-not (Test-Path $ip)) { New-Item -Path $ip -Force | Out-Null }
        Set-ItemProperty -Path $ip -Name "EnableHwkbTextPrediction" -Value 0 -Type DWord -Force
        Set-ItemProperty -Path $ip -Name "InsightsEnabled"          -Value 0 -Type DWord -Force

        # 4. Disable dictation panel auto-invoke
        $dp = "HKCU:\Software\Microsoft\TabletTip.7"
        if (-not (Test-Path $dp)) { New-Item -Path $dp -Force | Out-Null }
        Set-ItemProperty -Path $dp -Name "EnableDesktopModeAutoInvoke" -Value 0 -Type DWord -Force

        Write-OK "Win+H golosovoy vvod Windows otklyuchyon cherez reestr (Win+H disabled via registry)"
        Write-Host "  Changes take effect after Windows restart." -ForegroundColor Gray
        Write-Host "  (Changes take effect after Windows restart.)" -ForegroundColor DarkGray
    } catch {
        Write-Warn "Win+H: ne udalos' izmenit' reestr: $_"
        Write-Warn "Run manually: powershell -ExecutionPolicy Bypass -File `"C:\whisper-ptt\disable-windows-voice.ps1`""
    }
}

# ==============================================================================
Write-Banner "ShAG 2 / STEP 2: Ustanovka Whisper Server + Web UI" "Cyan"
# ==============================================================================
# Analogichno: peredayom vse otvety cherez stdin chtoby ne bylo povtornykh voprosov.
# install-whisper-server-windows.ps1 ozhidaet:
#   1. "Select GPU index"       -> nomer GPU
#   2. "Select model 1-N"       -> Enter = rekomenduemaya
#   3. "Press Enter to exit"    -> Enter

Write-Info "Installing WhisperServer + WhisperWebUI as Windows Services..."
Write-Info "(Installing WhisperServer + WhisperWebUI as Windows Services.)"
Write-Host ""

$serverInstaller = Join-Path $scriptDir "install-whisper-server-windows.ps1"

if (-not (Test-Path (Join-Path $scriptDir "whisper-webui.py"))) {
    Write-Warn "whisper-webui.py ne nayden ryadom s ustanovshchikom!"
    $totalErrors++
}

# ── If LIVE mode: install additional live server components ───────────────────
if ($serverMode -eq "live") {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "  Installing whisper_from_sssDeMoNsss-live components..." -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan

    # Copy live server files
    $liveServer  = Join-Path $scriptDir "whisper-live-server.py"
    $livePtt     = Join-Path $scriptDir "whisper-live-ptt.py"

    if (Test-Path $liveServer) {
        Copy-Item $liveServer "C:\whisper-server\whisper-live-server.py" -Force
        Write-Host "  [OK] whisper-live-server.py copied to C:\whisper-server" -ForegroundColor Green
    } else {
        Write-Host "  [!]  whisper-live-server.py not found — skipping" -ForegroundColor Yellow
    }

    if (Test-Path $livePtt) {
        Copy-Item $livePtt "C:\whisper-ptt\whisper-live-ptt.py" -Force
        Write-Host "  [OK] whisper-live-ptt.py copied to C:\whisper-ptt" -ForegroundColor Green
    } else {
        Write-Host "  [!]  whisper-live-ptt.py not found — skipping" -ForegroundColor Yellow
    }

    # Install websockets package (required for live mode)
    Write-Host "  Installing websockets library..." -ForegroundColor Cyan
    $pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($pyExe) {
        & $pyExe -m pip install websockets --quiet
        Write-Host "  [OK] websockets installed" -ForegroundColor Green
    }

    # Write gpu-config-live.json
    $liveCfg = @{
        model        = $selectedModel
        device       = if ($useCPU) { "cpu" } else { "cuda" }
        compute_type = if ($useCPU) { "int8" } else { "float16" }
        port         = 9201
        language     = "ru"
    } | ConvertTo-Json
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText("C:\whisper-server\gpu-config-live.json", $liveCfg, $utf8NoBom)
    Write-Host "  [OK] gpu-config-live.json saved (port 9201, model $selectedModel)" -ForegroundColor Green

    # Create live launcher — prefer $PYTHON_EXE (set by master GPU-detect block),
    # fall back to $pyExe (Get-Command lookup done just above), then bare "python".
    # This prevents a broken launcher if Python was not yet installed when the
    # GPU-detect block ran (e.g. freshly installed during install-whisper-ptt.ps1).
    $livePyExe = if ($PYTHON_EXE) { $PYTHON_EXE } elseif ($pyExe) { $pyExe } else { "python" }
    $livelauncherContent = "@echo off`r`ncd /d C:\whisper-ptt`r`n`"$livePyExe`" whisper-live-ptt.py`r`n"
    [System.IO.File]::WriteAllText("C:\whisper-ptt\whisper-live-ptt-launcher.bat", $livelauncherContent, $utf8NoBom)
    Write-Host "  [OK] whisper-live-ptt-launcher.bat created" -ForegroundColor Green

    # Desktop shortcut for live PTT
    try {
        $desktop = [System.Environment]::GetFolderPath("Desktop")
        $shell   = New-Object -ComObject WScript.Shell
        $lnk     = $shell.CreateShortcut("$desktop\Whisper PTT LIVE.lnk")
        $lnk.TargetPath   = "C:\whisper-ptt\whisper-live-ptt-launcher.bat"
        $lnk.WorkingDirectory = "C:\whisper-ptt"
        $lnk.Description  = "Whisper PTT LIVE - Real-time streaming transcription"
        $lnk.Save()
        Write-Host "  [OK] Desktop shortcut created: Whisper PTT LIVE.lnk" -ForegroundColor Green
    } catch {
        Write-Host "  [!]  Could not create desktop shortcut: $_" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  +============================================================+" -ForegroundColor Cyan
    Write-Host "  |  whisper_from_sssDeMoNsss-live installed!                  |" -ForegroundColor Cyan
    Write-Host "  |                                                              |" -ForegroundColor Cyan
    Write-Host "  |  1. Start whisper-live-server.py (as Windows Service or    |" -ForegroundColor Gray
    Write-Host "  |     manually: python whisper-live-server.py --port 9201)   |" -ForegroundColor Gray
    Write-Host "  |  2. Launch 'Whisper PTT LIVE' shortcut on Desktop          |" -ForegroundColor Gray
    Write-Host "  |  3. Right Ctrl = LIVE RU transcription                     |" -ForegroundColor Gray
    Write-Host "  |  4. Right Alt  = LIVE RU -> EN translation                 |" -ForegroundColor Gray
    Write-Host "  |  NOTE: Classic server (whisper-server.py) still works!     |" -ForegroundColor Green
    Write-Host "  +============================================================+" -ForegroundColor Cyan
}

try {
    # Передаём GPU-данные напрямую как параметры — никаких piped-ответов на GPU-вопросы.
    # Сервер-скрипт видит GpuIndex != -99 и пропускает интерактивный опрос.
    $srvGpuIndex   = if ($useCPU) { -1 } elseif ($selectedGpuIndex -ge 0) { $selectedGpuIndex } else { 0 }
    $srvDevice     = if ($useCPU) { "cpu" } else { "cuda" }
    $srvCompute    = if ($useCPU) { "int8" } else { "float16" }
    # Если модель large-v2/v3 и VRAM < 8GB — int8
    if (-not $useCPU -and $selectedModel -in @("large-v2","large-v3") -and $detectedGPUs.Count -gt 0 -and $selectedGpuIndex -ge 0) {
        if ($detectedGPUs[$selectedGpuIndex].VramMB -lt 8000) { $srvCompute = "int8" }
    }

    $psi2 = New-Object System.Diagnostics.ProcessStartInfo
    $psi2.FileName               = "powershell.exe"
    $psi2.Arguments              = "-ExecutionPolicy Bypass -File `"$serverInstaller`" -Port $serverPort -GpuIndex $srvGpuIndex -GpuDevice `"$srvDevice`" -GpuModel `"$selectedModel`" -GpuCompute `"$srvCompute`""
    $psi2.WorkingDirectory       = $scriptDir
    $psi2.UseShellExecute        = $false
    $psi2.RedirectStandardInput  = $true
    $psi2.RedirectStandardOutput = $false
    $psi2.RedirectStandardError  = $false
    $psi2.CreateNoWindow         = $false

    $proc2 = [System.Diagnostics.Process]::Start($psi2)

    # Единственный оставшийся piped-ответ — "Press Enter to exit" в конце
    Start-Sleep -Milliseconds 500
    $proc2.StandardInput.WriteLine("")
    $proc2.StandardInput.Close()
    $proc2.WaitForExit()

    if ($proc2.ExitCode -eq 0) {
        Write-OK "WhisperServer + WhisperWebUI ustanovleny (installed successfully)"
    } else {
        Write-Warn "Ustanovshchik servera zavershilsya s kodom $($proc2.ExitCode)"
    }
} catch {
    Write-Err "Oshibka ustanovki servera: $_"
    $totalErrors++
}

# ==============================================================================
Write-Banner "ShAG 3 / STEP 3: Final'naya proverka (Final verification)" "White"
# ==============================================================================

Start-Sleep -Seconds 2

# Check PTT files
Write-Host "  PTT files:" -ForegroundColor White
$pttPaths = @()
if ($pttVersions -contains "1") { $pttPaths += "C:\whisper-ptt\whisper-ptt.py" }
if ($pttVersions -contains "2") { $pttPaths += "C:\whisper-ptt-eng\whisper-ptt-eng.py" }
foreach ($p in $pttPaths) {
    if (Test-Path $p) { Write-OK $p } else { Write-Warn "Ne nayden (Not found): $p" }
}

# Check services
Write-Host ""
Write-Host "  Windows Services:" -ForegroundColor White
foreach ($svcName in @("WhisperServer", "WhisperWebUI")) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) {
        $color = if ($svc.Status -eq "Running") { "Green" } else { "Yellow" }
        Write-Host "  [OK]  $svcName -- $($svc.Status)" -ForegroundColor $color
    } else {
        Write-Host "  [!]   $svcName -- NE USTANOVLEN (NOT INSTALLED)" -ForegroundColor Red
        $totalErrors++
    }
}

# Check config.toml remote mode
Write-Host ""
Write-Host "  config.toml -- remote mode:" -ForegroundColor White
$cfgPaths = @("C:\whisper-ptt\config.toml", "C:\whisper-ptt-eng\config.toml")
foreach ($cfgPath in $cfgPaths) {
    if (Test-Path $cfgPath) {
        $cfgContent = Get-Content $cfgPath -Raw
        if ($cfgContent -match 'enabled\s*=\s*true') {
            Write-OK "$cfgPath -> remote enabled [OK]"
        } else {
            Write-Warn "$cfgPath -> remote NE vklyuchyon (not enabled)"
        }
    }
}

# Check shortcuts
Write-Host ""
Write-Host "  Desktop shortcuts:" -ForegroundColor White
$desktop = [System.Environment]::GetFolderPath("Desktop")
foreach ($lnk in @("Whisper PTT.lnk", "Whisper PTT ENG-RU.lnk", "Whisper Web UI.lnk")) {
    $lnkPath = Join-Path $desktop $lnk
    if (Test-Path $lnkPath) {
        Write-OK $lnk
    }
}

# Quick health check
Write-Host ""
Write-Host "  API health check..." -ForegroundColor White
Start-Sleep -Seconds 3
try {
    $health = Invoke-RestMethod -Uri "http://localhost:$serverPort/health" -Method GET -TimeoutSec 5 -ErrorAction Stop
    if ($health.status -eq "ok") {
        Write-OK "WhisperServer API -> http://localhost:$serverPort/health [OK]"
        Write-Info "  Model': $($health.model) | Device: $($health.device)"
    }
} catch {
    Write-Warn "WhisperServer API poka ne otvechaet -- model' eshchyo zagruzhaetsya (~30-120 sek)"
    Write-Warn "(WhisperServer API not responding yet -- model still loading)"
}

try {
    $webuiResp = Invoke-WebRequest -Uri "http://localhost:8765" -Method GET -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    if ($webuiResp.StatusCode -eq 200) {
        Write-OK "WhisperWebUI -> http://localhost:8765 [OK]"
    }
} catch {
    Write-Warn "WhisperWebUI poka ne otvechaet (WebUI not responding yet)"
}

# ==============================================================================
# FINAL SUMMARY
# ==============================================================================

Write-Host ""
if ($totalErrors -eq 0) {
    Write-Host "  +==========================================================+" -ForegroundColor Green
    Write-Host "  |   USTANOVKA ZAVERShENA USPEShNO!                          |" -ForegroundColor Green
    Write-Host "  |   INSTALLATION COMPLETE!                                |" -ForegroundColor Green
    Write-Host "  +==========================================================+" -ForegroundColor Green
} else {
    Write-Host "  +==========================================================+" -ForegroundColor Yellow
    Write-Host "  |   Ustanovka zavershena s preduprezhdeniyami ($totalErrors)           |" -ForegroundColor Yellow
    Write-Host "  |   Installation finished with warnings ($totalErrors)              |" -ForegroundColor Yellow
    Write-Host "  +==========================================================+" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  -- Kak pol'zovat'sya (How to use) ---------------------------" -ForegroundColor White
Write-Host ""
Write-Host "  1. Whisper PTT zapuskaetsya avtomaticheski pri vkhode v Windows." -ForegroundColor Gray
Write-Host "     (Whisper PTT starts automatically on Windows login.)" -ForegroundColor DarkGray
Write-Host "     Or manually: shortcutyk 'Whisper PTT' na rabochem stole." -ForegroundColor Gray
Write-Host "     (Or manually: 'Whisper PTT' shortcut on Desktop.)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  2. Hold Right Ctrl -> speak -> otpusti -> text is pasted." -ForegroundColor Cyan
Write-Host "     (Hold Right Ctrl -> speak -> release -> text is pasted.)" -ForegroundColor DarkGray
Write-Host "     Hold Right Alt -> speak -> otpusti -> translation is pasted." -ForegroundColor Cyan
Write-Host "     (Hold Right Alt -> speak -> release -> translation is pasted.)" -ForegroundColor DarkGray
Write-Host ""
  Write-Host "  3. WhisperServer: model' [$selectedModel] na GPU. PTT fallback: 'medium' (esli server upal)." -ForegroundColor Gray
  Write-Host "     (WhisperServer: model [$selectedModel] on GPU. PTT local fallback: 'medium' if server is down.)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  4. Web UI -- panel' upravleniya:" -ForegroundColor Gray
Write-Host "     http://localhost:8765  (yarlyk 'Whisper Web UI' na rabochem stole)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  -- Upravlenie servisami (Service management) ---------------" -ForegroundColor White
Write-Host "     Start-Service WhisperServer   /  Stop-Service WhisperServer" -ForegroundColor DarkGray
Write-Host "     Start-Service WhisperWebUI    /  Stop-Service WhisperWebUI" -ForegroundColor DarkGray
Write-Host "     Win+R -> services.msc  (graficheskoe upravlenie)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  -- Logs ----------------------------------------------" -ForegroundColor White
Write-Host "     C:\whisper-ptt\logs\whisper-server.log" -ForegroundColor DarkGray
Write-Host "     C:\whisper-ptt\logs\whisper-webui.log" -ForegroundColor DarkGray
Write-Host "     C:\whisper-ptt\logs\whisper-ptt.log" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  -- Author -------------------------------------------" -ForegroundColor White
Write-Host "     sssDeMoNsss | vk.com/basset2 | Telegram: @snnike" -ForegroundColor DarkGray
Write-Host ""

# Open browser if requested
if ($openBrowser) {
    Write-Info "Otkryvaem Web UI v brauzere... (Opening Web UI in browser...)"
    Start-Sleep -Seconds 2
    try {
        Start-Process "http://localhost:8765"
        Write-OK "Browser opened: http://localhost:8765"
    } catch {
        Write-Warn "Ne udalos' otkryt' brauzer. Otkroyte vruchnuyu: http://localhost:8765"
    }
}

# ==============================================================================
# Kopirovanie BAT-faylov i sozdanie yarlykov na rabochem stole
# ==============================================================================
Write-Host ""
Write-Host "  -- Kopirovanie faylov zapuska (Copying launcher files) -----" -ForegroundColor Cyan

# Папка назначения — рядом с установленным PTT
$batDestDir = "C:\whisper-install"
if (-not (Test-Path $batDestDir)) {
    New-Item -ItemType Directory -Path $batDestDir -Force | Out-Null
}

# Копируем все три BAT-файла
foreach ($batFile in @("START-whisper.bat", "START-ptt-only.bat", "STOP-whisper.bat")) {
    $src = Join-Path $scriptDir $batFile
    $dst = Join-Path $batDestDir $batFile
    if (Test-Path $src) {
        Copy-Item $src $dst -Force
        Write-OK "Скопирован: $batFile -> $batDestDir\"
    } else {
        Write-Warn "$batFile не найден рядом с установщиком — пропускаем"
    }
}

# Создаём ярлыки на рабочем столе
Write-Host ""
Write-Host "  -- Sozdanie yarlykov na rabochem stole (Creating Desktop shortcuts) -" -ForegroundColor Cyan
$desktop = [System.Environment]::GetFolderPath("Desktop")
$shell   = New-Object -ComObject WScript.Shell

$shortcuts = @(
    @{ Name = "▶ Whisper START";    Target = "$batDestDir\START-whisper.bat";   Desc = "Zapustit vse komponenty Whisper PTT" },
    @{ Name = "⏹ Whisper STOP";     Target = "$batDestDir\STOP-whisper.bat";    Desc = "Ostanovit vse komponenty Whisper PTT" },
    @{ Name = "🎤 Whisper PTT only"; Target = "$batDestDir\START-ptt-only.bat"; Desc = "Zapustit tol'ko whisper-ptt.py" }
)

foreach ($sc in $shortcuts) {
    try {
        $lnk = $shell.CreateShortcut("$desktop\$($sc.Name).lnk")
        $lnk.TargetPath       = $sc.Target
        $lnk.WorkingDirectory = $batDestDir
        $lnk.Description      = $sc.Desc
        $lnk.Save()
        Write-OK "Yarlyk sozdan: $($sc.Name).lnk"
    } catch {
        Write-Warn "Ne udalos' sozdat' yarlyk '$($sc.Name)': $_"
    }
}

# -- Launch whisper-ptt.py in a separate console window ------------------------
Write-Host ""
Write-Host "  -- Launching Whisper PTT -----------------" -ForegroundColor Green

$pttLaunchers = @()
if ($pttVersions -contains "1" -and (Test-Path "C:\whisper-ptt\whisper-ptt-launcher.bat")) {
    $pttLaunchers += "C:\whisper-ptt\whisper-ptt-launcher.bat"
}
if ($pttVersions -contains "2" -and (Test-Path "C:\whisper-ptt-eng\whisper-ptt-launcher.bat")) {
    $pttLaunchers += "C:\whisper-ptt-eng\whisper-ptt-launcher.bat"
}

if ($pttLaunchers.Count -gt 0) {
    foreach ($launcher in $pttLaunchers) {
        try {
            Start-Process cmd.exe -ArgumentList "/c `"$launcher`"" -WorkingDirectory (Split-Path $launcher)
            Write-OK "Zapushchen v otdel'nom okne (Launched in separate window): $launcher"
        } catch {
            Write-Warn "Ne udalos' zapustit' (Could not launch): $launcher"
            Write-Warn "Zapustite vruchnuyu yarlykom na rabochem stole (Launch manually from Desktop shortcut)"
        }
    }
} else {
    Write-Warn "Launcher not found -- zapustite vruchnuyu yarlykom 'Whisper PTT' na rabochem stole"
    Write-Warn "(Launch manually from 'Whisper PTT' Desktop shortcut)"
}

Write-Host ""
Write-Host "  +======================================================================+" -ForegroundColor Yellow
Write-Host "  |  [!]  VAZhNO -- PERVYY ZAPUSK  /  IMPORTANT -- FIRST LAUNCH             |" -ForegroundColor Yellow
Write-Host "  +======================================================================+" -ForegroundColor Yellow
Write-Host "  |                                                                      |" -ForegroundColor Yellow
Write-Host "  |  Samyy PERVYY golosovoy vvod posle zapuska programmy               |" -ForegroundColor Cyan
Write-Host "  |  mozhet ne vstavit'sya v nuzhnoe okno -- eto normal'no.               |" -ForegroundColor Cyan
Write-Host "  |                                                                      |" -ForegroundColor Yellow
Write-Host "  |  Prichina: pri pervom zapuske sistema zagruzhaet model' Whisper       |" -ForegroundColor Gray
Write-Host "  |  (~10-30 sek), fokus okna uspevaet pereklyuchit'sya na konsol'.        |" -ForegroundColor Gray
Write-Host "  |  So vtorogo perevoda programma rabotaet ideal'no.                  |" -ForegroundColor Gray
Write-Host "  |                                                                      |" -ForegroundColor Yellow
Write-Host "  |  The FIRST voice input after launch may not paste correctly.        |" -ForegroundColor Cyan
Write-Host "  |  This is expected -- use it as a system warm-up test.               |" -ForegroundColor Cyan
Write-Host "  |  From the 2nd input onwards everything works perfectly.             |" -ForegroundColor Cyan
Write-Host "  |                                                                      |" -ForegroundColor Yellow
Write-Host "  +======================================================================+" -ForegroundColor Yellow
Write-Host ""

Read-Host "  Press Enter to exit"
