# whisper_from_sssDeMoNsss -- whisper-server Windows Service Installer
# (Ustanovshchik Windows Sluzhby dlya whisper-server)
#
# Installs whisper-server.py as a Windows Service that:
#   - Starts automatically on Windows boot (avtozapusk pri zagruzke Windows)
#   - Runs in background with no console window (rabotayet v fone bez okna)
#   - Restarts automatically on crash (avtomaticheski pereznpuskayetsya pri sboe)
#   - Logs to C:\whisper-ptt\logs\ (logi v C:\whisper-ptt\logs\)
#
# USAGE (ispolzovaniye):
#   Win+X -> PowerShell (Administrator) -> Run as Administrator
#   powershell -ExecutionPolicy Bypass -File "C:\whisper-server\install-whisper-server-windows.ps1"
#
#   Optional: specify custom port (default 9000):
#   powershell -ExecutionPolicy Bypass -File "...\install-whisper-server-windows.ps1" -Port 9001
#
# After install (posle ustanovki):
#   - Service name: WhisperServer
#   - URL: http://localhost:<Port>
#   - Health: http://localhost:<Port>/health
#   - Logs: C:\whisper-ptt\logs\whisper-server.log
#   - Stop:  Stop-Service WhisperServer
#   - Start: Start-Service WhisperServer

# -- Port parameter (allows custom port to avoid conflicts) --------------------
param(
    [int]$Port        = 9200,
    [int]$GpuIndex    = -99,   # -99 = не передан из мастера → спрашиваем интерактивно
    [string]$GpuDevice  = "",  # "cuda" или "cpu"
    [string]$GpuModel   = "",  # "medium", "large-v2" и т.д.
    [string]$GpuCompute = ""   # "float16" или "int8"
)

$ErrorActionPreference = "Continue"

$SERVICE_NAME    = "WhisperServer"
$SERVICE_DISPLAY = "Whisper Server (whisper_from_sssDeMoNsss)"
$INSTALL_DIR     = "C:\whisper-server"
$LOG_DIR         = "C:\whisper-ptt\logs"   # vse logi tol'ko zdes'

# Use port passed from master installer (or default for standalone)
$SERVER_PORT = $Port
$SERVICE_DESC = "Remote Whisper HTTP transcription server. Listens on port $SERVER_PORT. Part of whisper_from_sssDeMoNsss."

# If running standalone (not called from install-all-windows.ps1) -- ask port interactively.
# Standalone is detected by GpuIndex = -99 (the sentinel the master always overwrites).
if ($GpuIndex -eq -99) {
    Write-Host ""
    Write-Host "  Vyberite port dlya WhisperServer (Choose port for WhisperServer):" -ForegroundColor White
    Write-Host "  Po umolchaniyu: 9200. Izmenite esli port zanyat drugim prilozheniem." -ForegroundColor Gray
    Write-Host "  (Default: 9200. Change if port is occupied by another application.)" -ForegroundColor Gray
    # Check if 9000 is busy
    $portBusy = $false
    try {
        if (Get-NetTCPConnection -LocalPort 9200 -ErrorAction SilentlyContinue) { $portBusy = $true }
    } catch {}
    if ($portBusy) {
        Write-Host "  [!]  Port 9200 ZANYaT! Rekomenduem: 9100, 9201, 9300" -ForegroundColor Red
    }
    $portInput = Read-Host "  Vvedite port [Enter = 9200]"
    $portInput = $portInput.Trim()
    if ($portInput -ne "" -and $portInput -match '^\d+$' -and [int]$portInput -ge 1024 -and [int]$portInput -le 65535) {
        $SERVER_PORT = [int]$portInput
    } else {
        $SERVER_PORT = 9200
    }
    Write-OK "Selected port: $SERVER_PORT"
}
$HAOS_IP         = ""   # Leave empty for local-only install; set to IP if HAOS server exists

# -- Helpers -------------------------------------------------------------------
function Write-Step($n, $text) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  STEP ${n}: $text" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}
function Write-OK($t)   { Write-Host "[OK]    $t" -ForegroundColor Green   }
function Write-Warn($t) { Write-Host "[!]     $t" -ForegroundColor Yellow  }
function Write-Err($t)  { Write-Host "[ERROR] $t" -ForegroundColor Red     }
function Write-Fix($t)  { Write-Host "[FIX]   $t" -ForegroundColor Magenta }

# -- Banner --------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "                                                            " -ForegroundColor Cyan
Write-Host "   whisper-server -- Windows Service Installer              " -ForegroundColor White
Write-Host "   whisper_from_sssDeMoNsss | sssDeMoNsss                  " -ForegroundColor Gray
Write-Host "                                                            " -ForegroundColor Cyan
Write-Host "   Service  : $SERVICE_NAME                                " -ForegroundColor White
Write-Host "   Port     : $SERVER_PORT                                  " -ForegroundColor White
Write-Host "   Dir      : $INSTALL_DIR                                  " -ForegroundColor White
if ($HAOS_IP) { Write-Host "   HAOS IP  : $HAOS_IP                                      " -ForegroundColor Cyan }
else           { Write-Host "   Mode     : LOCAL only (localhost:$SERVER_PORT)              " -ForegroundColor Green }
Write-Host "                                                            " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# -- Admin check ---------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
           [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err "Run as Administrator! Right-click -> Run as administrator"
    Write-Err "(Zapustite ot imeni Administratora! Pravaya knopka -> Zapusk ot imeni administratora)"
    Read-Host "Press Enter to exit (Nazhmite Enter dlya vyhoda)"; exit 1
}
Write-OK "Administrator rights confirmed (Prava administratora podtverzhdeny)"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$errCount  = 0

# =============================================================================
Write-Step 1 "Find Python (Shag 1: Naiti Python)"
# =============================================================================

$PYTHON_EXE = ""
$pyPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)
foreach ($p in $pyPaths) {
    if (Test-Path $p) { $PYTHON_EXE = $p; break }
}
if ([string]::IsNullOrEmpty($PYTHON_EXE)) {
    $found = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($found) { $PYTHON_EXE = $found }
}
if ([string]::IsNullOrEmpty($PYTHON_EXE)) {
    $localBase = "$env:LOCALAPPDATA\Programs\Python"
    if (Test-Path $localBase) {
        $pyDirs = Get-ChildItem $localBase -Directory -Filter "Python31*" -ErrorAction SilentlyContinue
        foreach ($d in ($pyDirs | Sort-Object Name -Descending)) {
            $candidate = "$($d.FullName)\python.exe"
            if (Test-Path $candidate) { $PYTHON_EXE = $candidate; break }
        }
    }
}
if ([string]::IsNullOrEmpty($PYTHON_EXE)) {
    Write-Err "Python not found! (Python ne nayden!)"
    Write-Host "  Install Python 3.12: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"; exit 1
}

$pyver = (& $PYTHON_EXE --version 2>&1).ToString().Trim()
Write-Fix "Using Python: $PYTHON_EXE"
Write-OK  "$pyver"

# =============================================================================
Write-Step 2 "Create directories (Shag 2: Sozdaniye papok)"
# =============================================================================

foreach ($dir in @($INSTALL_DIR, "C:\whisper-ptt\logs")) {
    if (-not (Test-Path $dir)) {
        New-Item $dir -ItemType Directory -Force | Out-Null
        Write-OK "Created (sozdana): $dir"
    } else {
        Write-OK "Exists (uzhe est): $dir"
    }
}

# Copy whisper-server.py
$srcServer = Join-Path $scriptDir "whisper-server.py"
if (-not (Test-Path $srcServer)) {
    $srcServer = "C:\whisper-ptt\whisper-server.py"
}
if (-not (Test-Path $srcServer)) {
    $srcServer = "C:\whisper-ptt-haos\whisper-server.py"
}

if (Test-Path $srcServer) {
    Copy-Item $srcServer "$INSTALL_DIR\whisper-server.py" -Force
    Write-OK "whisper-server.py copied (skopirovan): $INSTALL_DIR\whisper-server.py"
} else {
    Write-Err "whisper-server.py not found! (Ne nayden!)"
    Write-Err "Place whisper-server.py next to this installer or in C:\whisper-ptt\"
    Write-Err "(Polozhite whisper-server.py ryadom s etim ustanovshchikom ili v C:\whisper-ptt\)"
    $errCount++
}

# =============================================================================
Write-Step 3 "Detect GPU and select model (Shag 3: Opredeleniye GPU i vybor modeli)"
# =============================================================================

$deviceArg = "cpu"
$modelArg  = "small"
$computeArg = "int8"
$selectedGpu = $null

# ── Если мастер уже передал данные GPU — пропускаем интерактивный опрос ──────
if ($GpuIndex -ne -99 -and $GpuDevice -ne "" -and $GpuModel -ne "" -and $GpuCompute -ne "") {
    $deviceArg  = $GpuDevice
    $modelArg   = $GpuModel
    $computeArg = $GpuCompute
    $cudaEnvVal = if ($GpuIndex -ge 0) { "$GpuIndex" } else { "" }
    if ($GpuIndex -ge 0) {
        try {
            $gpuName = (& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_name($GpuIndex))" 2>&1).Trim()
            $gpuVram = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_properties($GpuIndex).total_memory // 1024 // 1024)" 2>&1).Trim()
            $gpuVramGB = [math]::Round($gpuVram / 1024, 1)
            $selectedGpu = [PSCustomObject]@{ Index=$GpuIndex; Name=$gpuName; VramMB=$gpuVram; VramGB=$gpuVramGB; Optimal=$modelArg }
            Write-OK "GPU pre-selected by master installer: GPU $GpuIndex — $gpuName ($gpuVramGB GB)"
        } catch {
            Write-Warn "Could not query GPU $GpuIndex info — continuing with passed parameters"
        }
    }
    Write-OK "Model: $modelArg  device: $deviceArg  compute_type: $computeArg  (passed from master installer)"
} else {
# ── Интерактивный опрос GPU (standalone запуск скрипта) ───────────────────────

$gpuCount = 0
try {
    $gpuCount = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.device_count())" 2>&1).Trim()
} catch {}

if ($gpuCount -gt 0) {
    Write-Host ""
    Write-Host "  GPU(s) detected (videokart(y) obnaruzheny):" -ForegroundColor Cyan

    $gpuInfos = @()
    for ($i = 0; $i -lt $gpuCount; $i++) {
        $gpuName = (& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_name($i))" 2>&1).Trim()
        $gpuVram = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_properties($i).total_memory // 1024 // 1024)" 2>&1).Trim()
        $gpuVramGB = [math]::Round($gpuVram / 1024, 1)

        # Optimal model by VRAM
        if     ($gpuVram -ge 9000)  { $optModel = "large-v3"; $optNote = "MAXIMUM+ 11GB" }
        elseif ($gpuVram -ge 6000)  { $optModel = "large-v2"; $optNote = "MAXIMUM"       }
        elseif ($gpuVram -ge 3000)  { $optModel = "medium";   $optNote = "HIGH"           }
        elseif ($gpuVram -ge 1300)  { $optModel = "small";    $optNote = "GREAT"          }
        else                        { $optModel = "base";     $optNote = "GOOD"            }

        Write-Host "  GPU $i : $gpuName -- ${gpuVramGB} GB -- optimal: $optModel ($optNote)" -ForegroundColor Cyan
        $gpuInfos += [PSCustomObject]@{ Index=$i; Name=$gpuName; VramMB=$gpuVram; VramGB=$gpuVramGB; Optimal=$optModel }
    }

    Write-Host ""

    if ($gpuCount -gt 1) {
        Write-Host "  *** MULTI-GPU DETECTED (MULTI-GPU OBNARUZHEN) ***" -ForegroundColor Yellow
        Write-Host "  Whisper uses ONE GPU at a time." -ForegroundColor White
        Write-Host "  RECOMMENDATION: use the GPU NOT used by games/work." -ForegroundColor White
        Write-Host "  (REKOMENDATSIYA: ispolzuyte videkartu kotoruyu ne zanimayt igry/rabota.)" -ForegroundColor Gray
        Write-Host ""
        for ($i = 0; $i -lt $gpuCount; $i++) {
            $g = $gpuInfos[$i]
            Write-Host "  [${i}]  GPU ${i}: $($g.Name) -- $($g.VramGB) GB -- optimal: $($g.Optimal)" -ForegroundColor Cyan
        }
        Write-Host "  [c]  CPU -- no GPU, for laptops / weak PCs (~3-8 sec per phrase)" -ForegroundColor Gray
        Write-Host ""
        $gpuChoice = Read-Host "  Select GPU index or [c] for CPU [0-$($gpuCount-1) or c]"
        $gpuChoice = $gpuChoice.Trim()
        if ($gpuChoice -eq "c" -or $gpuChoice -eq "C" -or $gpuChoice -eq "cpu") {
            # User chose CPU explicitly
            $selectedGpu = $null
            $deviceArg   = "cpu"
            $computeArg  = "int8"
            $cudaEnvVal  = ""
            Write-OK "Selected: CPU mode (rezhim CPU) -- model will be set to 'small'"
        } else {
            $selIdx = 0
            if ($gpuChoice -match '^\d+$' -and [int]$gpuChoice -lt $gpuCount) {
                $selIdx = [int]$gpuChoice
            }
            $selectedGpu = $gpuInfos[$selIdx]
            $deviceArg   = "cuda"   # ← устанавливаем СРАЗУ при выборе GPU
            $computeArg  = "float16"
            $cudaEnvVal  = "$selIdx"
            Write-OK "Selected GPU $selIdx : $($selectedGpu.Name) ($($selectedGpu.VramGB) GB)"
        }
    } else {
        # Single GPU — also offer CPU option
        Write-Host "  [0]  $($gpuInfos[0].Name) -- $($gpuInfos[0].VramGB) GB -- optimal: $($gpuInfos[0].Optimal)" -ForegroundColor Cyan
        Write-Host "  [c]  CPU -- no GPU, for laptops / weak PCs (~3-8 sec per phrase)" -ForegroundColor Gray
        Write-Host ""
        $gpuChoiceSingle = Read-Host "  Use GPU [0] or CPU [c]? [Enter = 0]"
        $gpuChoiceSingle = $gpuChoiceSingle.Trim()
        if ($gpuChoiceSingle -eq "c" -or $gpuChoiceSingle -eq "C" -or $gpuChoiceSingle -eq "cpu") {
            $selectedGpu = $null
            $deviceArg   = "cpu"
            $computeArg  = "int8"
            $cudaEnvVal  = ""
            Write-OK "Selected: CPU mode (rezhim CPU)"
        } else {
            $selectedGpu = $gpuInfos[0]
            $deviceArg   = "cuda"   # ← устанавливаем СРАЗУ при выборе GPU
            $computeArg  = "float16"
            $cudaEnvVal  = "0"
            Write-OK "Using GPU 0: $($selectedGpu.Name) ($($selectedGpu.VramGB) GB)"
        }
    }

    # Model selection menu — different for CPU vs GPU mode
    $models    = @("tiny","base","small","medium","large-v2","large-v3")
    $vramReqs  = @{tiny=500;base=700;small=1300;medium=3000;"large-v2"=5500;"large-v3"=6000}
    $qualities = @{
        tiny       = "BASIC    -- fastest, lowest accuracy  (samyy bystry)"
        base       = "GOOD     -- fast, lower accuracy      (bystro, horoshee)"
        small      = "GREAT    -- fast and accurate         (bystro i tochno)"
        medium     = "HIGH     -- excellent for everyday    (ochen kachestvenno)"
        "large-v2" = "MAXIMUM  -- best for Russian          (luchshee dlya russkogo)"
        "large-v3" = "MAXIMUM+ -- latest model              (poslednyaya versiya)"
    }

    Write-Host ""
    if ($deviceArg -eq "cpu") {
        # CPU mode: show RAM requirements, recommend small
        Write-Host "  Available models for CPU mode (RAM requirements):" -ForegroundColor White
        Write-Host "  Note: large models are very slow on CPU (60-120 sec/phrase)." -ForegroundColor Yellow
        Write-Host ""
        $idx = 1; $modelMenu = @{}
        foreach ($m in $models) {
            $reqGB = [math]::Round($vramReqs[$m] / 1024, 1)
            $rec   = if ($m -eq "small") { "  <-- RECOMMENDED for CPU" } else { "" }
            $color = if ($m -in @("tiny","base","small")) { "Green" } else { "DarkGray" }
            Write-Host "  [$idx] $(($m).PadRight(10)) $($qualities[$m])  (~${reqGB} GB RAM)$rec" -ForegroundColor $color
            $modelMenu["$idx"] = $m; $idx++
        }
        Write-Host "  [$idx] Keep default: small" -ForegroundColor Gray
        $modelMenu["$idx"] = "small"; Write-Host ""
        $modelChoice = (Read-Host "  Select model 1-$idx [Enter = small]").Trim()
        $modelArg    = if ($modelMenu.ContainsKey($modelChoice)) { $modelMenu[$modelChoice] } else { "small" }
        $computeArg  = "int8"   # Always int8 for CPU
    } else {
        # GPU mode: show VRAM requirements
        Write-Host "  Available models for $($selectedGpu.Name) ($($selectedGpu.VramGB) GB):" -ForegroundColor White
        Write-Host ""
        $idx = 1; $modelMenu = @{}
        foreach ($m in $models) {
            $req   = $vramReqs[$m]
            $reqGB = [math]::Round($req / 1024, 1)
            $fits  = $selectedGpu.VramMB -ge $req
            $marker = if ($fits) { "[OK]" } else { "[--]" }
            $color  = if ($fits) { "Green" } else { "DarkGray" }
            $rec    = if ($m -eq $selectedGpu.Optimal) { "  <-- RECOMMENDED" } else { "" }
            Write-Host "  $marker [$idx] $(($m).PadRight(10)) $($qualities[$m])  (~${reqGB} GB)$rec" -ForegroundColor $color
            $modelMenu["$idx"] = $m; $idx++
        }
        Write-Host "  [$idx] Keep default: small" -ForegroundColor Gray
        $modelMenu["$idx"] = "small"; Write-Host ""
        $modelChoice = (Read-Host "  Select model 1-$idx [Enter = $($selectedGpu.Optimal)]").Trim()
        $modelArg    = if ($modelMenu.ContainsKey($modelChoice)) { $modelMenu[$modelChoice] } else { $selectedGpu.Optimal }
        # compute_type
        $computeArg = "float16"
        if ($modelArg -in @("large-v2","large-v3") -and $selectedGpu.VramMB -lt 8000) {
            $computeArg = "int8"
            Write-Warn "Using compute_type=int8 to fit $modelArg in $($selectedGpu.VramGB) GB VRAM"
        }
        $deviceArg = "cuda"
    }
    # Set CUDA_VISIBLE_DEVICES for selected GPU
    $cudaEnvVal = "$($selectedGpu.Index)"

    Write-OK "Model selected (vybrana model): $modelArg  device=cuda  compute_type=$computeArg"

} else {
    Write-Warn "No CUDA GPU found (CUDA GPU ne naydena) -- using CPU mode"
    Write-Warn "(CPU: model=small, ~5-10 sec per phrase -- dlya CPU: model=small, ~5-10 sek)"
    $modelArg   = "small"
    $deviceArg  = "cpu"
    $computeArg = "int8"
    $cudaEnvVal = ""
}
} # конец блока интерактивного опроса (else от GpuIndex -ne -99)

# =============================================================================
Write-Step 4 "Install faster-whisper if needed (Shag 4: Ustanovka faster-whisper)"
# =============================================================================

# -- Ensure correct PyTorch CUDA build is installed ---------------------------
# faster-whisper needs cublas64_12.dll (CUDA 12.x) — cu121, cu124, cu126 all provide it.
# cu121 index has NO wheels for Python 3.13+ (torchaudio missing).
# Python 3.13+: use cu124. Python <=3.12: prefer cu121, fallback to cu124.
$pyMinorStr = (& $PYTHON_EXE -c "import sys; print(sys.version_info.minor)" 2>&1).Trim()
$pyMajorStr = (& $PYTHON_EXE -c "import sys; print(sys.version_info.major)" 2>&1).Trim()
$pyMinor = if ($pyMinorStr -match "^[0-9]+$") { [int]$pyMinorStr } else { 12 }
$pyMajor = if ($pyMajorStr -match "^[0-9]+$") { [int]$pyMajorStr } else { 3 }

if ($pyMajor -gt 3 -or ($pyMajor -eq 3 -and $pyMinor -ge 13)) {
    $TORCH_INDEX     = "https://download.pytorch.org/whl/cu124"
    $TORCH_INDEX_FB  = "https://download.pytorch.org/whl/cu126"
    $CUDA_INDEX_NAME = "cu124"
} else {
    $TORCH_INDEX     = "https://download.pytorch.org/whl/cu121"
    $TORCH_INDEX_FB  = "https://download.pytorch.org/whl/cu124"
    $CUDA_INDEX_NAME = "cu121"
}
Write-Host "  Python $pyMajor.$pyMinor detected -> PyTorch index: $CUDA_INDEX_NAME" -ForegroundColor Cyan

$torchCudaVer = (& $PYTHON_EXE -c "import torch; print(torch.version.cuda or '')" 2>&1).Trim()
$torchAvail   = (& $PYTHON_EXE -c "import torch; print(torch.cuda.is_available())" 2>&1).Trim()
Write-Host "  PyTorch CUDA version: $torchCudaVer  |  GPU available: $torchAvail" -ForegroundColor Cyan

# Detect cases that require reinstall:
# 1. CUDA 11.x → must upgrade (no cublas64_12.dll)
# 2. No torch at all
# 3. CPU-only build installed from PyPI by mistake
# 4. Python 3.13 + torchaudio missing (cu121 has no py313 wheels)
$needsInstall = $false
$reinstallReason = ""

if ($torchCudaVer -like "11.*") {
    $needsInstall = $true
    $reinstallReason = "cu118/cu11x detected — upgrading to $CUDA_INDEX_NAME (CUDA 12 required)"
} elseif ($torchCudaVer -eq "") {
    $needsInstall = $true
    $reinstallReason = "PyTorch not found — installing $CUDA_INDEX_NAME"
} else {
    # Check for CPU-only build
    $torchTag = (& $PYTHON_EXE -c "import torch; print(torch.__version__)" 2>&1).Trim()
    if ($torchTag -like "*+cpu*") {
        $needsInstall = $true
        $reinstallReason = "CPU-only torch detected ($torchTag) — reinstalling with $CUDA_INDEX_NAME"
    } elseif ($pyMajor -eq 3 -and $pyMinor -ge 13) {
        & $PYTHON_EXE -c "import torchaudio" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $needsInstall = $true
            $reinstallReason = "torchaudio missing on Python 3.13 (cu121 has no py3.13 wheels) — reinstalling with $CUDA_INDEX_NAME"
        }
    }
}

if ($needsInstall) {
    Write-Host ""
    Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkYellow
    Write-Host "  $reinstallReason" -ForegroundColor Yellow
    Write-Host "  faster-whisper requires CUDA 12 (cublas64_12.dll)." -ForegroundColor Yellow
    Write-Host "  (faster-whisper trebuyet CUDA 12 -- obnovlyayem PyTorch)" -ForegroundColor DarkYellow
    Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkYellow
    Write-Host ""
    & $PYTHON_EXE -m pip uninstall torch torchvision torchaudio -y 2>&1 | Out-Null
    Write-Host "  Installing PyTorch $CUDA_INDEX_NAME (~2.5 GB, may take 5-10 min)..." -ForegroundColor Yellow
    & $PYTHON_EXE -m pip install torch torchvision torchaudio --index-url $TORCH_INDEX
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "$CUDA_INDEX_NAME failed -- trying fallback $TORCH_INDEX_FB..."
        & $PYTHON_EXE -m pip install torch torchvision torchaudio --index-url $TORCH_INDEX_FB
    }
    $torchCudaVer = (& $PYTHON_EXE -c "import torch; print(torch.version.cuda or 'n/a')" 2>&1).Trim()
    Write-OK "PyTorch updated. CUDA version now: $torchCudaVer"
} else {
    Write-OK "PyTorch CUDA $torchCudaVer -- OK (compatible with faster-whisper)"
}

$hasFasterWhisper = $false
& $PYTHON_EXE -c "from faster_whisper import WhisperModel" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    $hasFasterWhisper = $true
    Write-OK "faster-whisper already installed (uzhe ustanovlen)"
} else {
    Write-Host "  Installing faster-whisper (ustanavlivayem faster-whisper)..."
    & $PYTHON_EXE -m pip install faster-whisper --quiet
    & $PYTHON_EXE -c "from faster_whisper import WhisperModel" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "faster-whisper installed (ustanovlen)"
        $hasFasterWhisper = $true
    } else {
        Write-Warn "faster-whisper failed -- will use openai-whisper as fallback"
        Write-Warn "(faster-whisper ne udalos -- budem ispolzovat openai-whisper)"
    }
}

# =============================================================================
Write-Step 5 "Install NSSM (Non-Sucking Service Manager) (Shag 5: Ustanovka NSSM)"
# =============================================================================
# NSSM is the most reliable way to run Python scripts as Windows Services.
# It handles stdout/stderr logging, restart on crash, and clean stop/start.
# (NSSM -- samyy nadezhnyy sposob zapuskat Python kak Windows Sluzhbu.)

$nssmExe = ""

# Check if already installed
$nssmInPath = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if ($nssmInPath) {
    $nssmExe = $nssmInPath
    Write-OK "NSSM already in PATH (uzhe est v PATH): $nssmExe"
}

# Try winget
if ([string]::IsNullOrEmpty($nssmExe)) {
    Write-Host "  Installing NSSM via winget (ustanavlivayem NSSM cherez winget)..."
    $wingetResult = winget install nssm --silent --accept-source-agreements --accept-package-agreements 2>&1
    $nssmInPath = (Get-Command nssm -ErrorAction SilentlyContinue).Source
    if ($nssmInPath) {
        $nssmExe = $nssmInPath
        Write-OK "NSSM installed via winget (ustanovlen cherez winget)"
    }
}

# Download NSSM directly if winget failed
if ([string]::IsNullOrEmpty($nssmExe)) {
    Write-Warn "winget failed -- downloading NSSM directly (skachivayem NSSM napryamuyu)..."
    $nssmDir = "$INSTALL_DIR\nssm"
    $nssmZip = "$env:TEMP\nssm.zip"
    $nssmTarget = "$nssmDir\nssm.exe"

    if (-not (Test-Path $nssmDir)) { New-Item $nssmDir -ItemType Directory -Force | Out-Null }

    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" `
            -OutFile $nssmZip -UseBasicParsing -TimeoutSec 30
        Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm-extract" -Force

        # NSSM zip has win64/win32 subfolders
        $nssmSrc = Get-ChildItem "$env:TEMP\nssm-extract" -Recurse -Filter "nssm.exe" |
                   Where-Object { $_.FullName -like "*win64*" } | Select-Object -First 1
        if (-not $nssmSrc) {
            $nssmSrc = Get-ChildItem "$env:TEMP\nssm-extract" -Recurse -Filter "nssm.exe" | Select-Object -First 1
        }
        if ($nssmSrc) {
            Copy-Item $nssmSrc.FullName $nssmTarget -Force
            $nssmExe = $nssmTarget
            Write-OK "NSSM downloaded and extracted (skachan i raspakovan): $nssmExe"
        }
        Remove-Item $nssmZip -Force -ErrorAction SilentlyContinue
        Remove-Item "$env:TEMP\nssm-extract" -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Warn "NSSM download failed: $_ (ne udalos skachat NSSM: $_)"
    }
}

# Fallback: sc.exe based service (no NSSM)
$useNssm = -not [string]::IsNullOrEmpty($nssmExe)
if (-not $useNssm) {
    Write-Warn "NSSM not available -- using sc.exe + wrapper bat (sc.exe + bat obvertka)"
    Write-Warn "Logging will be limited (logirovaniye budet ogranicheno)"
}

# =============================================================================
Write-Step 6 "Create service wrapper and config (Shag 6: Sozdat obvertku i config servisa)"
# =============================================================================

# Write server config file
$serverConfigPath = "$INSTALL_DIR\server-config.json"
$serverConfigHash = @{
    model        = $modelArg
    device       = $deviceArg
    compute_type = $computeArg
    port         = $SERVER_PORT
    language     = "ru"
    python_exe   = $PYTHON_EXE
    install_dir  = $INSTALL_DIR
}
if ($HAOS_IP) { $serverConfigHash["haos_ip"] = $HAOS_IP }
$serverConfig = $serverConfigHash | ConvertTo-Json
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($serverConfigPath, $serverConfig, $utf8NoBom)
Write-OK "Server config saved (config servisa sohranyon): $serverConfigPath"

# -- Write gpu-config.json -- whisper-server.py reads this at every startup ----
# This file is also updated by WebUI Apply & Restart (model switching).
# Writing it here ensures the correct model is used even if an old gpu-config.json
# from a previous install/test exists on disk.
$gpuConfigPath = "C:\whisper-server\gpu-config.json"
$gpuConfigHash = @{
    gpu_index    = if ($selectedGpu) { $selectedGpu.Index } else { -1 }
    model        = $modelArg
    device       = $deviceArg
    compute_type = $computeArg
    port         = $SERVER_PORT
    language     = "ru"
}
$gpuConfig = $gpuConfigHash | ConvertTo-Json
[System.IO.File]::WriteAllText($gpuConfigPath, $gpuConfig, $utf8NoBom)
Write-OK "gpu-config.json saved: model=$modelArg device=$deviceArg compute_type=$computeArg"

# Build launch arguments
# Model, device, language come from gpu-config.json (written by installer and WebUI).
# Only --port is passed as CLI arg -- everything else is in gpu-config.json.
$launchArgs = "whisper-server.py --port $SERVER_PORT"

# Wrapper BAT for sc.exe fallback (also used by NSSM as the executable)
$wrapperBat = "$INSTALL_DIR\whisper-server-service.bat"
$cudaEnvLine = if ($cudaEnvVal -ne "") { "set CUDA_VISIBLE_DEVICES=$cudaEnvVal" } else { "rem No GPU selection" }

$wrapperContent = @"
@echo off
chcp 65001 >nul
set PYTHONUTF8=1
$cudaEnvLine
cd /d "$INSTALL_DIR"
"$PYTHON_EXE" whisper-server.py --port $SERVER_PORT >> "C:\whisper-ptt\logs\whisper-server.log" 2>&1
"@
[System.IO.File]::WriteAllText($wrapperBat, $wrapperContent, [System.Text.Encoding]::ASCII)
Write-OK "Service wrapper created (obvertka servisa sozdana): $wrapperBat"

# Log rotation script
$logRotateScript = "$INSTALL_DIR\rotate-logs.ps1"
$logRotateContent = @"
# Auto-rotate whisper-server.log when > 50 MB
`$logFile = "$LOG_DIR\whisper-server.log"
`$maxSize = 50MB
if ((Test-Path `$logFile) -and (Get-Item `$logFile).Length -gt `$maxSize) {
    `$archive = "$LOG_DIR\whisper-server-`$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    Move-Item `$logFile `$archive
    Write-Host "Log rotated to `$archive"
    # Keep last 5 log files
    Get-ChildItem "$LOG_DIR" -Filter "whisper-server-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | Remove-Item -Force
}
"@
[System.IO.File]::WriteAllText($logRotateScript, $logRotateContent, $utf8NoBom)

# =============================================================================
Write-Step 7 "Remove existing service if present (Shag 7: Udaleniye sushchestvuyushchego servisa)"
# =============================================================================

$existingService = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Warn "Service already exists -- removing (servis uzhe sushchestvuyet -- udalyayem)..."
    Write-Host "  Current state: $($existingService.Status)" -ForegroundColor Gray

    # -- Step A: Force-kill the service process tree (NSSM + child python) ------
    # This handles ALL states: Running, StopPending, StartPending
    if ($existingService.Status -ne "Stopped") {
        Write-Host "  Killing service process tree (ubivayem derevo processov)..." -ForegroundColor Yellow

        # Get the NSSM/service PID and kill its entire process tree
        $svcWmi = Get-CimInstance Win32_Service -Filter "Name='$SERVICE_NAME'" -ErrorAction SilentlyContinue
        if ($svcWmi -and $svcWmi.ProcessId -gt 0) {
            $svcPid = $svcWmi.ProcessId
            Write-Host "  Service PID: $svcPid -- killing process tree with taskkill /T /F..." -ForegroundColor Yellow
            taskkill /PID $svcPid /T /F 2>&1 | Out-Null
            Start-Sleep -Seconds 2
        }

        # Also kill any remaining whisper-server python processes
        Get-Process python*, nssm* -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.ProcessName -eq "nssm" -and $_.Id -ne $PID) -or
                ($_.CommandLine -and $_.CommandLine -like "*whisper-server*")
            } |
            ForEach-Object {
                Write-Host "  Killing remaining process: $($_.ProcessName) PID $($_.Id)" -ForegroundColor Yellow
                taskkill /PID $($_.Id) /T /F 2>&1 | Out-Null
            }
        Start-Sleep -Seconds 3

        Write-OK "Processes terminated (processy zaversheny)"
    }

    # -- Step B: Delete the service registration --------------------------------
    if ($useNssm) {
        & $nssmExe remove $SERVICE_NAME confirm 2>&1 | Out-Null
    }
    # Always also try sc.exe delete as backup
    sc.exe delete $SERVICE_NAME 2>&1 | Out-Null

    # -- Step C: Wait for Windows to fully purge the service --------------------
    Write-Host "  Waiting for Windows to fully remove old service..." -ForegroundColor Gray
    $purged = $false
    for ($pw = 1; $pw -le 30; $pw++) {
        Start-Sleep -Seconds 1
        $still = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
        if (-not $still) { $purged = $true; break }
        if ($pw % 5 -eq 0) {
            Write-Host "  Still waiting... ($pw/30 sec) [Status: $($still.Status)]" -ForegroundColor Gray
        }
    }
    if ($purged) {
        Write-OK "Old service fully removed (stary servis polnostyu udalen)"
    } else {
        Write-Warn "Service still visible after 30 sec -- forcing final cleanup..."
        # Last resort: kill everything and delete again
        Get-Process python*, nssm* -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -like "*whisper-server*" } |
            ForEach-Object { taskkill /PID $($_.Id) /T /F 2>&1 | Out-Null }
        sc.exe delete $SERVICE_NAME 2>&1 | Out-Null
        Start-Sleep -Seconds 5
        $stillAfter = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
        if (-not $stillAfter) {
            Write-OK "Old service removed after forced cleanup"
        } else {
            Write-Err "Could not fully remove old service -- a reboot may be required"
            Write-Err "(Ne udalos polnostyu udalit stary servis -- mozhet potrebovatsya perezagruzka)"
        }
    }
}

# =============================================================================
Write-Step 8 "Install Windows Service (Shag 8: Ustanovka Windows Sluzhby)"
# =============================================================================

if ($useNssm) {
    # -- NSSM installation -----------------------------------------------------
    Write-Host "  Installing service via NSSM (ustanavlivayem cherez NSSM)..." -ForegroundColor Cyan

    # Try install -- retry up to 3 times if service is still "marked for deletion"
    $nssmInstalled = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $installOut = & $nssmExe install $SERVICE_NAME "$PYTHON_EXE" 2>&1 | Out-String
        if ($installOut -match "Error creating service|otmechena dlya udaleniya|marked for deletion") {
            Write-Warn "NSSM install attempt $attempt/3 failed -- service still marked for deletion"
            Write-Host "  Waiting 10 sec for Windows to release service handle..." -ForegroundColor Gray
            # Kill any lingering processes holding the service handle
            Get-Process python*, nssm* -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -and $_.CommandLine -like "*whisper-server*" } |
                ForEach-Object { taskkill /PID $($_.Id) /T /F 2>&1 | Out-Null }
            sc.exe delete $SERVICE_NAME 2>&1 | Out-Null
            Start-Sleep -Seconds 10
        } else {
            $nssmInstalled = $true
            break
        }
    }

    if (-not $nssmInstalled) {
        Write-Err "NSSM install failed after 3 attempts -- trying sc.exe fallback..."
        Write-Err "(NSSM ne smog sozdat servis posle 3 popytok -- probuyem sc.exe)"
        # Fall through to sc.exe path
        $useNssm = $false
    }

    if ($useNssm) {
        & $nssmExe set $SERVICE_NAME AppDirectory  "$INSTALL_DIR"          | Out-Null
        & $nssmExe set $SERVICE_NAME AppParameters $launchArgs             | Out-Null
        & $nssmExe set $SERVICE_NAME DisplayName   "$SERVICE_DISPLAY"      | Out-Null
        & $nssmExe set $SERVICE_NAME Description   "$SERVICE_DESC"         | Out-Null
        & $nssmExe set $SERVICE_NAME Start         SERVICE_AUTO_START      | Out-Null

        # Stdout/stderr to log file
        & $nssmExe set $SERVICE_NAME AppStdout "$LOG_DIR\whisper-server.log"  | Out-Null
        & $nssmExe set $SERVICE_NAME AppStderr "$LOG_DIR\whisper-server.log"  | Out-Null
        & $nssmExe set $SERVICE_NAME AppRotateFiles        1                  | Out-Null
        & $nssmExe set $SERVICE_NAME AppRotateBytes        52428800           | Out-Null
        & $nssmExe set $SERVICE_NAME AppRotateOnline       1                  | Out-Null

        # Restart on exit (including clean exit from /shutdown endpoint)
        # AppExit Default covers all exit codes, AppExit 0 explicitly covers os._exit(0)
        & $nssmExe set $SERVICE_NAME AppExit Default Restart   | Out-Null
        & $nssmExe set $SERVICE_NAME AppExit 0       Restart   | Out-Null
        & $nssmExe set $SERVICE_NAME AppRestartDelay 3000      | Out-Null
        & $nssmExe set $SERVICE_NAME AppThrottle       0       | Out-Null

        # Environment variables
        & $nssmExe set $SERVICE_NAME AppEnvironmentExtra "PYTHONUTF8=1" | Out-Null
        if ($cudaEnvVal -ne "") {
            & $nssmExe set $SERVICE_NAME AppEnvironmentExtra "PYTHONUTF8=1" "CUDA_VISIBLE_DEVICES=$cudaEnvVal" | Out-Null
        }

        Write-OK "Service installed via NSSM (ustanovlen cherez NSSM)"
    }
}

if (-not $useNssm) {
    # -- sc.exe fallback -------------------------------------------------------
    Write-Host "  Installing service via sc.exe (ustanavlivayem cherez sc.exe)..." -ForegroundColor Cyan

    $binPath = "`"$wrapperBat`""
    sc.exe create $SERVICE_NAME binPath= $binPath DisplayName= "$SERVICE_DISPLAY" start= auto | Out-Null
    sc.exe description $SERVICE_NAME "$SERVICE_DESC" | Out-Null

    # Configure restart on failure AND on clean exit (exit code 0).
    # whisper-server.py calls os._exit(0) on /shutdown — that's a clean exit.
    # Without failureflag, sc.exe would NOT restart on exit code 0.
    # failureflag= 1 means: restart on ANY exit, including code 0.
    sc.exe failure $SERVICE_NAME reset= 60 actions= restart/3000/restart/3000/restart/3000 | Out-Null
    sc.exe failureflag $SERVICE_NAME 1 | Out-Null

    Write-OK "Service installed via sc.exe"
}

# Verify service was created
$newService = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($newService) {
    Write-OK "Service registered (servis zaregistrirovan): $SERVICE_NAME"
    Write-OK "Startup type (tip zapuska): Automatic (Avtomaticheskiy)"
} else {
    Write-Err "Service registration failed! (Registratsiya servisa ne udalas!)"
    $errCount++
}

# =============================================================================
Write-Step 9 "Open firewall port $SERVER_PORT (Shag 9: Otkrytiye porta $SERVER_PORT)"
# =============================================================================

# Remove old rule if exists
Remove-NetFirewallRule -DisplayName "WhisperServer Port $SERVER_PORT" -ErrorAction SilentlyContinue | Out-Null

# Add new rule -- allow inbound on selected port from local network only
New-NetFirewallRule -DisplayName "WhisperServer Port $SERVER_PORT" `
    -Direction Inbound -Protocol TCP -LocalPort $SERVER_PORT `
    -Action Allow -Profile Any `
    -Description "whisper_from_sssDeMoNsss whisper-server HTTP API" `
    -ErrorAction SilentlyContinue | Out-Null

$fwRule = Get-NetFirewallRule -DisplayName "WhisperServer Port $SERVER_PORT" -ErrorAction SilentlyContinue
if ($fwRule) {
    Write-OK "Firewall rule added (pravilo braumauera dobavleno): TCP inbound :$SERVER_PORT"
} else {
    Write-Warn "Could not add firewall rule -- add manually if needed"
    Write-Warn "(Ne udalos dobavit pravilo -- dobavte vruchnuyu esli nuzhno)"
}

# =============================================================================
Write-Step 10 "Update whisper-ptt config.toml to use localhost:$SERVER_PORT (Shag 10: Obnovleniye config.toml)"
# =============================================================================

# Update all known config.toml locations to point to localhost:$SERVER_PORT
$configPaths = @(
    "C:\whisper-ptt\config.toml",
    "C:\whisper-ptt-haos\config.toml",
    "C:\whisper-ptt-eng\config.toml"
)

foreach ($cfgPath in $configPaths) {
    if (Test-Path $cfgPath) {
        $cfg = Get-Content $cfgPath -Raw

        # Check if [remote] section exists
        if ($cfg -match '\[remote\]') {
            # Update existing remote section
            $cfg = $cfg -replace 'enabled\s*=\s*(true|false)', 'enabled = true'
            $cfg = $cfg -replace 'url\s*=\s*"[^"]*"', "url = `"http://localhost:$SERVER_PORT`""
        } else {
            # Prepend [remote] section
            $remoteSection = @"
# Remote whisper-server running locally (lokalny whisper-server)
[remote]
enabled = true
url = "http://localhost:$SERVER_PORT"
timeout = 30

"@
            $cfg = $remoteSection + $cfg
        }

        [System.IO.File]::WriteAllText($cfgPath, $cfg, $utf8NoBom)
        Write-OK "Updated config: $cfgPath -> remote.url = http://localhost:$SERVER_PORT"
    }
}

# =============================================================================
Write-Step 11 "Start service and verify (Shag 11: Zapusk servisa i proverka)"
# =============================================================================

Write-Host "  Starting service (zapuskaem servis)..." -ForegroundColor Cyan
Start-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

$svc = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "Service is RUNNING (servis ZAPUSHCHEN)"
} else {
    Write-Warn "Service not running yet -- model may still be loading (mozhet zagruzhatsya model)"
    Write-Warn "Check log: $LOG_DIR\whisper-server.log"
}

# Wait for model to load and test health endpoint
Write-Host ""
Write-Host "  Waiting for model to load (zhdem zagruzki modeli)..." -ForegroundColor Yellow
Write-Host "  First-time launch downloads the model (~1-3 GB) -- may take 5-15 minutes!" -ForegroundColor Yellow
Write-Host "  (Perviy zapusk skachivayut model ~1-3 GB -- mozhet zanyat 5-15 minut!)" -ForegroundColor Yellow
Write-Host "  Subsequent starts: 30-120 seconds. (Posle -- 30-120 sekund.)" -ForegroundColor Gray
Write-Host ""

$healthOk = $false
# 24 attempts x 5 sec = 120 sec -- enough to detect if the service is running
# We don't wait the full model download time -- instead we check service status
for ($attempt = 1; $attempt -le 24; $attempt++) {
    Start-Sleep -Seconds 5

    # First check if service is still alive (not crashed / StopPending)
    $svcLoop = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
    if ($svcLoop -and $svcLoop.Status -notin @("Running", "StartPending")) {
        Write-Host ""
        Write-Err "Service is in state '$($svcLoop.Status)' -- not healthy!"
        Write-Err "(Servis v sostoyanii '$($svcLoop.Status)' -- ne zdorov!)"
        break
    }

    Write-Host "  Checking http://localhost:$SERVER_PORT/health ($attempt/24)..." -NoNewline
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:$SERVER_PORT/health" -Method GET -TimeoutSec 5 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            Write-Host " OK" -ForegroundColor Green
            $healthOk = $true

            Write-OK "Server is ready (server gotov)!"
            Write-Host ""
            Write-Host "  Server info (informatsiya o servere):" -ForegroundColor White
            Write-Host "    Model loaded  : $($resp.model)"                  -ForegroundColor Cyan
            Write-Host "    Device        : $($resp.device)"                  -ForegroundColor Cyan
            Write-Host "    Backend       : $($resp.backend)"                 -ForegroundColor Cyan
            Write-Host "    Model ready   : $($resp.model_loaded)"           -ForegroundColor Cyan
            if ($resp.gpu.available) {
                Write-Host "    GPU           : $($resp.gpu.name) ($($resp.gpu.vram_gb) GB)" -ForegroundColor Green
                Write-Host "    CUDA          : $($resp.gpu.cuda_version)"   -ForegroundColor Green
            } else {
                Write-Host "    GPU           : CPU mode (rezhim CPU)"        -ForegroundColor Yellow
            }
            break
        }
    } catch {
        Write-Host " Not ready yet..." -ForegroundColor Gray
    }
}

if (-not $healthOk) {
    $svcCheck = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue

    if ($svcCheck -and $svcCheck.Status -eq "Running") {
        # Service is running -- model is still downloading/loading. This is NORMAL for first install.
        Write-Host ""
        Write-Host "  +===============================================================+" -ForegroundColor Yellow
        Write-Host "  |  Servis zapushchen, model' zagruzhaetsya v fone.                   |" -ForegroundColor Yellow
        Write-Host "  |  Service is running, model is loading in background.           |" -ForegroundColor Yellow
        Write-Host "  |                                                                |" -ForegroundColor Yellow
        Write-Host "  |  Pri pervom zapuske skachivanie modeli large-v2 ~3 GB           |" -ForegroundColor Yellow
        Write-Host "  |  mozhet zanyat' 5-15 minut. Eto normal'no!                       |" -ForegroundColor Yellow
        Write-Host "  |  (First-time model download ~3 GB can take 5-15 min. Normal!) |" -ForegroundColor Yellow
        Write-Host "  |                                                                |" -ForegroundColor Yellow
        Write-Host "  |  Proverit' gotovnost': http://localhost:$SERVER_PORT/health          |" -ForegroundColor Yellow
        Write-Host "  |  Log: C:\whisper-ptt\logs\whisper-server.log                   |" -ForegroundColor Yellow
        Write-Host "  +===============================================================+" -ForegroundColor Yellow
    } else {
        Write-Warn "Server did not respond in time."
        Write-Warn "(Server ne otvetil vovremya.)"
        if ($svcCheck) {
            Write-Err "  Service STATUS: $($svcCheck.Status) -- the server may have crashed!"
            Write-Err "  (Status servisa: $($svcCheck.Status) -- server mog upast!)"
        }
        Write-Warn "Check: http://localhost:$SERVER_PORT/health"
        Write-Warn "Log  : $LOG_DIR\whisper-server.log"
    }

    # Show last 10 lines of the log file for diagnostics
    $logFile = "$LOG_DIR\whisper-server.log"
    if (Test-Path $logFile) {
        Write-Host ""
        Write-Host "  -- Last 10 lines of server log (posledniye 10 strok loga): --" -ForegroundColor Gray
        Get-Content $logFile -Tail 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
}

# =============================================================================
# Final summary
# =============================================================================

Write-Host ""
if ($errCount -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  Installation complete! whisper-server running as Service  " -ForegroundColor Green
    Write-Host "  (Ustanovka zavershena! whisper-server rabotayet kak Sluzhba)" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Service name (imya servisa)  : $SERVICE_NAME"                   -ForegroundColor White
    Write-Host "  Status (status)              : $(( Get-Service $SERVICE_NAME -EA SilentlyContinue).Status)" -ForegroundColor White
    Write-Host "  Startup (avtozapusk)         : Automatic (Avtomaticheskiy)"     -ForegroundColor White
    Write-Host "  Model (model)                : $modelArg"                       -ForegroundColor Cyan
    Write-Host "  Device (ustroystvo)          : $deviceArg"                      -ForegroundColor Cyan
    Write-Host "  URL (adres)                  : http://localhost:$SERVER_PORT"   -ForegroundColor Cyan
    Write-Host "  Health (proverka)            : http://localhost:$SERVER_PORT/health" -ForegroundColor Cyan
    Write-Host "  Log file (fayl loga)         : $LOG_DIR\whisper-server.log"     -ForegroundColor Gray
    Write-Host ""
    if ($HAOS_IP) {
        Write-Host "  HAOS server (server HAOS)    : $HAOS_IP"                    -ForegroundColor Cyan
    }
    Write-Host "  whisper-ptt config.toml updated to use localhost:$SERVER_PORT" -ForegroundColor Green
    Write-Host "  (config.toml obnovlyony -- teper ispolzuyet lokalny server)"    -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Service management (upravleniye servison):"                     -ForegroundColor White
    Write-Host "    Start  : Start-Service $SERVICE_NAME"                         -ForegroundColor Gray
    Write-Host "    Stop   : Stop-Service $SERVICE_NAME"                          -ForegroundColor Gray
    Write-Host "    Restart: Restart-Service $SERVICE_NAME"                       -ForegroundColor Gray
    Write-Host "    Status : Get-Service $SERVICE_NAME"                           -ForegroundColor Gray
    Write-Host "    Log    : Get-Content '$LOG_DIR\whisper-server.log' -Tail 50"  -ForegroundColor Gray
    if ($useNssm) {
        Write-Host "    Edit   : nssm edit $SERVICE_NAME"                         -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  GUI management: Win+R -> services.msc -> WhisperServer"         -ForegroundColor Gray
    Write-Host "  (Graficheskoe upravleniye: Win+R -> services.msc -> WhisperServer)" -ForegroundColor Gray
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  Installation finished with $errCount error(s) (s $errCount oshibkami)" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  Check log: $LOG_DIR\whisper-server.log" -ForegroundColor Yellow
}

# =============================================================================
Write-Step 12 "Install WhisperWebUI service (Shag 12: Ustanovka WhisperWebUI servisa)"
# =============================================================================

$WEBUI_SERVICE   = "WhisperWebUI"
$WEBUI_DISPLAY   = "Whisper Web UI (whisper_from_sssDeMoNsss)"
$WEBUI_DESC      = "Whisper PTT management Web UI on port 8765. Part of whisper_from_sssDeMoNsss."
$WEBUI_PORT      = 8765

# Copy whisper-webui.py to install dir
$srcWebui = Join-Path $scriptDir "whisper-webui.py"
if (-not (Test-Path $srcWebui)) {
    $srcWebui = "C:\whisper-ptt\whisper-webui.py"
}
if (Test-Path $srcWebui) {
    Copy-Item $srcWebui "$INSTALL_DIR\whisper-webui.py" -Force
    Write-OK "whisper-webui.py copied (skopirovan): $INSTALL_DIR\whisper-webui.py"
} else {
    Write-Warn "whisper-webui.py not found -- Web UI will not be available"
    Write-Warn "(whisper-webui.py ne nayden -- veb-interfeys ne budet dostupen)"
}

# Also copy to PTT dirs if they exist
foreach ($pttDir in @("C:\whisper-ptt", "C:\whisper-ptt-eng")) {
    if ((Test-Path $pttDir) -and (Test-Path (Join-Path $scriptDir "whisper-webui.py"))) {
        Copy-Item (Join-Path $scriptDir "whisper-webui.py") "$pttDir\whisper-webui.py" -Force
    }
}

# Remove existing WebUI service
$existingWebUI = Get-Service -Name $WEBUI_SERVICE -ErrorAction SilentlyContinue
if ($existingWebUI) {
    Write-Warn "WebUI service already exists -- removing..."
    Write-Host "  Current state: $($existingWebUI.Status)" -ForegroundColor Gray

    if ($existingWebUI.Status -ne "Stopped") {
        Write-Host "  Killing WebUI process tree..." -ForegroundColor Yellow
        $wuiWmi = Get-CimInstance Win32_Service -Filter "Name='$WEBUI_SERVICE'" -ErrorAction SilentlyContinue
        if ($wuiWmi -and $wuiWmi.ProcessId -gt 0) {
            taskkill /PID $wuiWmi.ProcessId /T /F 2>&1 | Out-Null
            Start-Sleep -Seconds 2
        }
        Write-OK "WebUI processes terminated"
    }

    if ($useNssm) {
        & $nssmExe remove $WEBUI_SERVICE confirm 2>&1 | Out-Null
    }
    sc.exe delete $WEBUI_SERVICE 2>&1 | Out-Null

    # Wait for Windows to fully purge the service
    Write-Host "  Waiting for Windows to fully remove old WebUI service..." -ForegroundColor Gray
    $wuiPurged = $false
    for ($pw = 1; $pw -le 20; $pw++) {
        Start-Sleep -Seconds 1
        $wuiStill = Get-Service -Name $WEBUI_SERVICE -ErrorAction SilentlyContinue
        if (-not $wuiStill) { $wuiPurged = $true; break }
        if ($pw % 5 -eq 0) {
            Write-Host "  Still waiting... ($pw/20 sec) [Status: $($wuiStill.Status)]" -ForegroundColor Gray
        }
    }
    if ($wuiPurged) {
        Write-OK "Old WebUI service fully removed"
    } else {
        Write-Warn "WebUI service still visible -- forcing cleanup..."
        sc.exe delete $WEBUI_SERVICE 2>&1 | Out-Null
        Start-Sleep -Seconds 5
    }
}

# Install WebUI service
if (Test-Path "$INSTALL_DIR\whisper-webui.py") {
    if ($useNssm) {
        & $nssmExe install $WEBUI_SERVICE "$PYTHON_EXE" | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppDirectory  "$INSTALL_DIR"          | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppParameters "whisper-webui.py"      | Out-Null
        & $nssmExe set $WEBUI_SERVICE DisplayName   "$WEBUI_DISPLAY"        | Out-Null
        & $nssmExe set $WEBUI_SERVICE Description   "$WEBUI_DESC"           | Out-Null
        & $nssmExe set $WEBUI_SERVICE Start         SERVICE_AUTO_START      | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppStdout     "$LOG_DIR\whisper-webui.log" | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppStderr     "$LOG_DIR\whisper-webui.log" | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppRotateFiles  1                     | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppRotateBytes  10485760              | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppRotateOnline 1                     | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppExit Default Restart               | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppRestartDelay 5000                  | Out-Null
        & $nssmExe set $WEBUI_SERVICE AppEnvironmentExtra "PYTHONUTF8=1"    | Out-Null
        # Run as LocalSystem so it can call sc.exe to control other services
        & $nssmExe set $WEBUI_SERVICE ObjectName LocalSystem                | Out-Null

        Write-OK "WhisperWebUI service installed via NSSM (ustanovlen cherez NSSM)"

    # -- Grant WhisperWebUI permission to control WhisperServer via SCM --------
    # This allows sc.exe start/stop to work from the WebUI service context.
    # sc.exe sdset sets the Security Descriptor -- we add SERVICE_START+STOP
    # rights for the LOCAL SERVICE and NETWORK SERVICE accounts.
    Write-Host "  Granting service control permissions..." -ForegroundColor Cyan
    try {
        # Get current SDDL for WhisperServer
        $sddlOut = (sc.exe sdshow WhisperServer) -join ""
        if ($sddlOut -and $sddlOut -notmatch "LS.*RP WP") {
            # Add RP (start) + WP (stop) for Local Service (LS) and Network Service (NS)
            $newAce = "(A;;RPWP;;;LS)(A;;RPWP;;;NS)(A;;RPWPDTLOCRRC;;;SY)"
            $sddlNew = $sddlOut -replace "^D:", "D:$newAce"
            sc.exe sdset WhisperServer $sddlNew 2>&1 | Out-Null
        }
        Write-OK "Service permissions granted for WhisperWebUI"
    } catch {
        Write-Warn "Could not set service permissions (not critical -- /shutdown HTTP endpoint used)"
    }
    } else {
        $webuiWrapperBat = "$INSTALL_DIR\whisper-webui-service.bat"
        $webuiWrapperContent = @"
@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "$INSTALL_DIR"
"$PYTHON_EXE" whisper-webui.py >> "C:\whisper-ptt\logs\whisper-webui.log" 2>&1
"@
        [System.IO.File]::WriteAllText($webuiWrapperBat, $webuiWrapperContent, [System.Text.Encoding]::ASCII)
        sc.exe create $WEBUI_SERVICE binPath= "`"$webuiWrapperBat`"" DisplayName= "$WEBUI_DISPLAY" start= auto | Out-Null
        sc.exe description $WEBUI_SERVICE "$WEBUI_DESC" | Out-Null
        Write-OK "WhisperWebUI service installed via sc.exe"
    }

    # Verify service creation
    $webuiSvc = Get-Service -Name $WEBUI_SERVICE -ErrorAction SilentlyContinue
    if ($webuiSvc) {
        Write-OK "Service registered: $WEBUI_SERVICE (Autostart)"
    } else {
        Write-Err "WhisperWebUI service registration failed!"
        $errCount++
    }

    # Start WebUI service
    Write-Host "  Starting WhisperWebUI service..." -ForegroundColor Cyan
    Start-Service -Name $WEBUI_SERVICE -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    $webuiSvc = Get-Service -Name $WEBUI_SERVICE -ErrorAction SilentlyContinue
    if ($webuiSvc -and $webuiSvc.Status -eq "Running") {
        Write-OK "WhisperWebUI is RUNNING on http://localhost:$WEBUI_PORT"
    } else {
        Write-Warn "WhisperWebUI not running -- check log: $LOG_DIR\whisper-webui.log"
    }

    # Desktop shortcut for Web UI
    try {
        $desktop = [System.Environment]::GetFolderPath("Desktop")
        $shell   = New-Object -ComObject WScript.Shell
        $lnk     = $shell.CreateShortcut("$desktop\Whisper Web UI.lnk")
        $lnk.TargetPath      = "http://localhost:$WEBUI_PORT"
        $lnk.IconLocation    = "$env:SystemRoot\System32\shell32.dll,14"
        $lnk.Description     = "Whisper PTT Web UI -- http://localhost:$WEBUI_PORT"
        $lnk.Save()
        Write-OK "Desktop shortcut created: Whisper Web UI.lnk"
    } catch {
        Write-Warn "Could not create Web UI shortcut: $_"
    }

    # -- Task Scheduler: open browser to WebUI on user login ------------------
    # WhisperWebUI Service starts automatically (Session 0) but cannot open a
    # browser. A separate scheduled task runs at user logon to open the browser.
    # Delay 15 sec to let the service fully start first.
    Write-Host "  Creating browser autostart task for WebUI..." -ForegroundColor Cyan
    try {
        $taskName   = "Whisper WebUI Browser"
        $taskAction = New-ScheduledTaskAction `
            -Execute "cmd.exe" `
            -Argument "/c start http://localhost:$WEBUI_PORT"
        $taskTrigger = New-ScheduledTaskTrigger -AtLogon
        $taskTrigger.Delay = "PT15S"   # 15 second delay after login
        $taskSettings = New-ScheduledTaskSettingsSet `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 1) `
            -StartWhenAvailable `
            -DisallowDemandStart:$false
        $taskPrincipal = New-ScheduledTaskPrincipal `
            -UserId $env:USERNAME `
            -LogonType Interactive `
            -RunLevel Limited

        # Remove existing task if present
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

        Register-ScheduledTask `
            -TaskName  $taskName `
            -Action    $taskAction `
            -Trigger   $taskTrigger `
            -Settings  $taskSettings `
            -Principal $taskPrincipal `
            -Description "Opens Whisper PTT WebUI in browser after Windows login" `
            -Force | Out-Null

        Write-OK "Browser autostart task created: '$taskName'"
        Write-Host "  WebUI will open in browser 15 sec after login." -ForegroundColor Gray
        Write-Host "  Manage: Win+R -> taskschd.msc -> '$taskName'" -ForegroundColor DarkGray
    } catch {
        Write-Warn "Could not create browser autostart task: $_"
        Write-Warn "Open manually: http://localhost:$WEBUI_PORT"
    }
} else {
    Write-Warn "Skipping WebUI service -- whisper-webui.py not available"
}

Write-Host ""
Write-Host "  WhisperWebUI: http://localhost:$WEBUI_PORT" -ForegroundColor Cyan
Write-Host "  Management : Start-Service WhisperWebUI / Stop-Service WhisperWebUI" -ForegroundColor Gray
Write-Host "  Log        : $LOG_DIR\whisper-webui.log" -ForegroundColor Gray

Write-Host ""
Read-Host "Press Enter to exit (Nazhmite Enter dlya vyhoda)"
