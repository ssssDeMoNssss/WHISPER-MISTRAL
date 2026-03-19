# whisper_from_sssDeMoNsss — GPU Switcher for WhisperServer Service
# (Pereklyuchatel GPU dlya servisa WhisperServer)
#
# Run any time you want to change which GPU whisper uses.
# (Zapuskayte kogda khotite pomenyat kakuyu videokartu ispolzuyet whisper.)
#
# Does NOT require Administrator rights.
# (Ne trebuyet prav Administratora.)

$ErrorActionPreference = "Continue"
$SERVICE_NAME = "WhisperServer"
$CONFIG_FILE  = "C:\whisper-server\gpu-config.json"

function Write-OK($t)   { Write-Host "[OK]  $t" -ForegroundColor Green  }
function Write-Warn($t) { Write-Host "[!]   $t" -ForegroundColor Yellow }
function Write-Err($t)  { Write-Host "[ERR] $t" -ForegroundColor Red    }

# ── Detect available GPUs ─────────────────────────────────────────────────────
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
if (-not $PYTHON_EXE) {
    Write-Err "Python not found (Python ne nayden)"
    Read-Host "Press Enter"; exit 1
}

# Read current config
$currentGpuIdx = 0
$currentModel  = "large-v2"
$currentPort   = 9200   # default — overwritten below if gpu-config.json exists
if (Test-Path $CONFIG_FILE) {
    try {
        $cfg = Get-Content $CONFIG_FILE -Raw | ConvertFrom-Json
        $currentGpuIdx = $cfg.gpu_index
        $currentModel  = $cfg.model
        if ($cfg.port) { $currentPort = [int]$cfg.port }
    } catch {}
}

# Detect GPUs
$gpuCount = 0
try {
    $gpuCount = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.device_count())" 2>&1).Trim()
} catch {}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  whisper-server — GPU Switcher (Pereklyuchatel GPU)       " -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($gpuCount -eq 0) {
    Write-Warn "No CUDA GPUs found (CUDA GPU ne naydeny)"
    Write-Warn "whisper-server will use CPU mode (rezhim CPU)"
    Read-Host "Press Enter to exit"; exit 0
}

# Build GPU list
$gpuList = @()
for ($i = 0; $i -lt $gpuCount; $i++) {
    $name   = (& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_name($i))"  2>&1).Trim()
    $vramMB = [int](& $PYTHON_EXE -c "import torch; print(torch.cuda.get_device_properties($i).total_memory // 1024 // 1024)" 2>&1).Trim()
    $vramGB = [math]::Round($vramMB / 1024, 1)

    if     ($vramMB -ge 9000) { $optModel = "large-v3"; $tag = "MAXIMUM+" }
    elseif ($vramMB -ge 6000) { $optModel = "large-v2"; $tag = "MAXIMUM"  }
    elseif ($vramMB -ge 3000) { $optModel = "medium";   $tag = "HIGH"     }
    else                      { $optModel = "small";    $tag = "GREAT"    }

    $gpuList += [PSCustomObject]@{
        Index    = $i
        Name     = $name
        VramGB   = $vramGB
        VramMB   = $vramMB
        OptModel = $optModel
        Tag      = $tag
    }
}

# Show current status
$svcStatus = (Get-Service $SERVICE_NAME -ErrorAction SilentlyContinue).Status
Write-Host "  Current service status (tekushchiy status servisa): $svcStatus" -ForegroundColor White
Write-Host "  Current GPU index (tekushchaya videokarta)         : $currentGpuIdx" -ForegroundColor Cyan
Write-Host "  Current model     (tekushchaya model)              : $currentModel" -ForegroundColor Cyan
Write-Host ""

# Show GPU menu
Write-Host "  Available GPUs (dostupnyye videokarty):" -ForegroundColor White
Write-Host ""
foreach ($g in $gpuList) {
    $isCurrent = if ($g.Index -eq $currentGpuIdx) { "  <-- CURRENT (tekushchaya)" } else { "" }
    Write-Host "  [$($g.Index)]  $($g.Name)" -ForegroundColor Cyan
    Write-Host "       VRAM: $($g.VramGB) GB  |  Optimal model: $($g.OptModel) ($($g.Tag))$isCurrent" -ForegroundColor Gray
    Write-Host ""
}
Write-Host "  [C]  Cancel — do nothing (otmena)" -ForegroundColor Gray
Write-Host ""

$gpuChoice = Read-Host "  Select GPU (vyberte videokartu) [0-$($gpuCount-1)]"
$gpuChoice = $gpuChoice.Trim().ToUpper()

if ($gpuChoice -eq "C" -or $gpuChoice -eq "") {
    Write-Host "  Cancelled (otmeneno)." -ForegroundColor Gray
    Read-Host "Press Enter to exit (Nazhmite Enter dlya vyhoda)"; exit 0
}

$selIdx = 0
if ($gpuChoice -match '^\d+$' -and [int]$gpuChoice -lt $gpuCount) {
    $selIdx = [int]$gpuChoice
} else {
    Write-Err "Invalid choice (nepravilny vybor): $gpuChoice"
    Read-Host "Press Enter to exit"; exit 1
}

$selGpu = $gpuList[$selIdx]
$cudaEnvVal = ""  # инициализируем заранее — будет заполнена ниже при GPU-режиме

# Model menu for selected GPU
Write-Host ""
Write-Host "  Selected (vybrana): GPU $selIdx — $($selGpu.Name) ($($selGpu.VramGB) GB)" -ForegroundColor Green
Write-Host ""
Write-Host "  Select model (vyberte model):" -ForegroundColor White
Write-Host ""

$models    = @("tiny","base","small","medium","large-v2","large-v3")
$vramReqs  = @{tiny=500;base=700;small=1300;medium=3000;"large-v2"=5500;"large-v3"=6000}
$qualities = @{
    tiny       = "BASIC    — fastest (~0.5 sec)   (samyy bystry)"
    base       = "GOOD     — fast    (~1 sec)      (bystro)"
    small      = "GREAT    — fast+accurate (~1-2 sec)"
    medium     = "HIGH     — excellent    (~2-3 sec)"
    "large-v2" = "MAXIMUM  — best for RU  (~2-4 sec)"
    "large-v3" = "MAXIMUM+ — latest model (~2-4 sec)"
}

$idx = 1; $modelMenu = @{}
foreach ($m in $models) {
    $req   = $vramReqs[$m]
    $reqGB = [math]::Round($req / 1024, 1)
    $fits  = $selGpu.VramMB -ge $req
    $color = if ($fits) { "Green" } else { "DarkGray" }
    $fits_marker = if ($fits) { "[OK]" } else { "[--]" }
    $rec   = if ($m -eq $selGpu.OptModel) { "  <-- RECOMMENDED" } else { "" }
    $cur   = if ($m -eq $currentModel)   { "  <-- CURRENT"     } else { "" }
    Write-Host "  $fits_marker [$idx] $($m.PadRight(10)) $($qualities[$m])  (~${reqGB}GB)$rec$cur" -ForegroundColor $color
    $modelMenu["$idx"] = $m
    $idx++
}
Write-Host "  [$idx] Keep current model: $currentModel (ostavit tekushchuyu)" -ForegroundColor Gray
$modelMenu["$idx"] = $currentModel
Write-Host ""

$modelChoice = Read-Host "  Select model 1-$idx (vyberte model) [Enter = $($selGpu.OptModel)]"
$modelChoice = $modelChoice.Trim()
$chosenModel = if ($modelMenu.ContainsKey($modelChoice)) { $modelMenu[$modelChoice] } else { $selGpu.OptModel }

# compute_type
$computeType = "float16"
if ($chosenModel -in @("large-v2","large-v3") -and $selGpu.VramMB -lt 8000) {
    $computeType = "int8"
    Write-Warn "Using int8 to fit $chosenModel in $($selGpu.VramGB) GB VRAM (ispolzuyem int8)"
}

Write-Host ""
Write-Host "  Applying (primenyayem):" -ForegroundColor Yellow
Write-Host "    GPU   : GPU $selIdx — $($selGpu.Name)" -ForegroundColor Cyan
Write-Host "    Model : $chosenModel" -ForegroundColor Cyan
Write-Host "    Device: cuda (CUDA_VISIBLE_DEVICES=$selIdx)" -ForegroundColor Cyan
Write-Host ""

# Save config
$newCfg = @{
    gpu_index    = $selIdx
    gpu_name     = $selGpu.Name
    model        = $chosenModel
    device       = "cuda"
    compute_type = $computeType
    port         = $currentPort
    language     = "ru"
} | ConvertTo-Json
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($CONFIG_FILE, $newCfg, $utf8NoBom)
Write-OK "Config saved (config sohranyon): $CONFIG_FILE"

# Update NSSM service if available
$nssmExe = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssmExe) {
    $nssmExe = "C:\whisper-server\nssm\nssm.exe"
}

# whisper-server.py reads model/device/language from gpu-config.json; only port is a CLI arg
$newArgs = "whisper-server.py --port $currentPort"

if ($nssmExe -and (Test-Path $nssmExe)) {
    # Check if admin rights available for NSSM
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
               [Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        & $nssmExe set WhisperServer AppParameters $newArgs 2>&1 | Out-Null
    & $nssmExe set WhisperServer AppEnvironmentExtra "PYTHONUTF8=1" | Out-Null
        if ($selIdx -ge 0) {
            $cudaEnvVal = "$selIdx"
            & $nssmExe set WhisperServer AppEnvironmentExtra "PYTHONUTF8=1" "CUDA_VISIBLE_DEVICES=$cudaEnvVal" | Out-Null
        }
        Write-OK "NSSM service updated (servis obnovlyony)"
    } else {
        Write-Warn "Need Administrator rights to update NSSM service (nuzhny prava Administratora)"
        Write-Warn "Re-run this script as Administrator to apply GPU change to service"
        Write-Warn "(Perezapustite ot imeni Administratora chtoby primenit smenu GPU k servisu)"
    }
}

# Restart service
$svc = Get-Service $SERVICE_NAME -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host ""
    $restartChoice = Read-Host "  Restart service now to apply changes? (y/n) (Perezapustit servis seychas? y/n)"
    if ($restartChoice.Trim() -eq "y" -or $restartChoice.Trim() -eq "Y") {
        # Check admin for service control
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
                   [Security.Principal.WindowsBuiltInRole]::Administrator)
        if ($isAdmin) {
            Write-Host "  Stopping service (ostanovka servisa)..." -ForegroundColor Yellow

            # Kill service process tree (handles Running, StopPending, StartPending)
            $svcWmi = Get-CimInstance Win32_Service -Filter "Name='$SERVICE_NAME'" -ErrorAction SilentlyContinue
            if ($svcWmi -and $svcWmi.ProcessId -gt 0) {
                taskkill /PID $svcWmi.ProcessId /T /F 2>&1 | Out-Null
            }
            # Also kill any orphan whisper-server python processes
            Get-Process python* -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -and $_.CommandLine -like "*whisper-server*" } |
                ForEach-Object { taskkill /PID $($_.Id) /T /F 2>&1 | Out-Null }
            Start-Sleep -Seconds 3

            # Wait for service to reach Stopped state
            for ($w = 1; $w -le 10; $w++) {
                $svcNow = Get-Service $SERVICE_NAME -ErrorAction SilentlyContinue
                if (-not $svcNow -or $svcNow.Status -eq "Stopped") { break }
                Start-Sleep -Seconds 1
            }

            Write-Host "  Starting service with GPU $selIdx — $($selGpu.Name)..." -ForegroundColor Yellow
            Start-Service $SERVICE_NAME -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            $newStatus = (Get-Service $SERVICE_NAME -ErrorAction SilentlyContinue).Status
            Write-OK "Service restarted (servis perezapushchen). Status: $newStatus"
            Write-Host ""
            Write-Host "  Model is loading (model zagruzhaetsya)..." -ForegroundColor Yellow
            Write-Host "  Check health in ~30 sec (proverite cherez ~30 sek):" -ForegroundColor Gray
            Write-Host "    http://localhost:$currentPort/health" -ForegroundColor Cyan
        } else {
            Write-Warn "Need Administrator to restart service."
            Write-Warn "Run: Restart-Service WhisperServer  (as Administrator)"
            Write-Warn "(Zapustite ot Administratora: Restart-Service WhisperServer)"
        }
    } else {
        Write-Host "  Changes will apply on next service restart." -ForegroundColor Gray
        Write-Host "  (Izmeneniya primenyatsya pri sleduyushchem zapuske servisa.)" -ForegroundColor Gray
        Write-Host "  Run: Restart-Service WhisperServer" -ForegroundColor Cyan
    }
} else {
    Write-Warn "Service '$SERVICE_NAME' not found — start it with: Start-Service WhisperServer"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  GPU switch complete! (Pereklyucheniye GPU zaversheno!)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick reference (shpargalka):" -ForegroundColor White
Write-Host "    Switch GPU  : Run this script again (zapustite etot skript opyat)" -ForegroundColor Gray
Write-Host "    Stop service: Stop-Service WhisperServer" -ForegroundColor Gray
Write-Host "    Start service: Start-Service WhisperServer" -ForegroundColor Gray
Write-Host "    View log    : Get-Content C:\whisper-ptt\logs\whisper-server.log -Tail 50" -ForegroundColor Gray
Write-Host "    Health check: Invoke-RestMethod http://localhost:$currentPort/health" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to exit (Nazhmite Enter dlya vyhoda)"
