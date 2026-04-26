#Requires -Version 5.1
<#
.SYNOPSIS
    AI OFM Studio - unified Windows installer.
.DESCRIPTION
    Installs ComfyUI + custom nodes, F5-TTS, RVC, FluxGym and all Python deps.
    Does NOT download ML models (see download_models.py, ~60 GB).
.PARAMETER BasePath
    Root folder for all installations. Default: D:\GitHub\ai-ofm
.EXAMPLE
    .\install.ps1
    .\install.ps1 -BasePath D:\AI
    .\install.ps1 -SkipF5TTS -SkipRVC
#>

param(
    [string]$BasePath = "D:\GitHub\ai-ofm",
    [switch]$SkipComfyUI,
    [switch]$SkipF5TTS,
    [switch]$SkipRVC,
    [switch]$SkipFluxGym,
    [switch]$SkipSageAttention
)

$ErrorActionPreference = "Stop"

# Try to force UTF-8 output (will not crash on old PowerShell)
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

function Write-Step {
    param([string]$msg)
    Write-Host ""
    Write-Host ("=" * 65) -ForegroundColor Cyan
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 65) -ForegroundColor Cyan
}

function Test-Command {
    param([string]$cmd)
    $null = Get-Command $cmd -ErrorAction SilentlyContinue
    return $?
}

# ============================================================
# 0. Environment check
# ============================================================
Write-Step "ENVIRONMENT CHECK"

if (-not (Test-Command "git")) {
    Write-Host "[ERR] Git not installed. Get it: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

if (-not (Test-Command "python")) {
    Write-Host "[ERR] Python not in PATH. Get 3.11 or 3.12: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

$pyVersion = (python --version 2>&1 | Out-String).Trim()
Write-Host "[OK] $pyVersion"

$isSupportedPython = $pyVersion -match 'Python 3\.(1[0-2])'
if (-not $isSupportedPython) {
    Write-Host "[WARN] Recommended Python 3.10-3.12. You have: $pyVersion" -ForegroundColor Yellow
}

# CUDA check is non-blocking
try {
    $nvidia = (nvidia-smi 2>&1 | Out-String)
    if ($nvidia -match 'CUDA Version:\s*(\d+\.\d+)') {
        Write-Host "[OK] CUDA $($matches[1]) detected"
    }
} catch {
    Write-Host "[WARN] nvidia-smi not found. Install NVIDIA drivers." -ForegroundColor Yellow
}

if (-not (Test-Path $BasePath)) {
    New-Item -ItemType Directory -Path $BasePath -Force | Out-Null
}
Write-Host "[OK] Base path: $BasePath"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$comfyPath = Join-Path $BasePath "ComfyUI"
$f5Path    = Join-Path $BasePath "F5-TTS"
$rvcPath   = Join-Path $BasePath "RVC"
$gymPath   = Join-Path $BasePath "fluxgym"

# ============================================================
# 1. Our program: venv + requirements.txt
# ============================================================
Write-Step "1/6  AI OFM Studio (this program)"

Set-Location $scriptDir
if (-not (Test-Path "venv")) {
    python -m venv venv
}
& "$scriptDir\venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "[OK] Our deps installed in venv/"
deactivate

# ============================================================
# 2. ComfyUI + custom nodes
# ============================================================
if (-not $SkipComfyUI) {
    Write-Step "2/6  ComfyUI + custom nodes"

    if (-not (Test-Path $comfyPath)) {
        git clone https://github.com/comfyanonymous/ComfyUI.git $comfyPath
    } else {
        Write-Host "[INFO] ComfyUI exists, pulling latest..." -ForegroundColor Yellow
        Set-Location $comfyPath
        git pull
    }

    Set-Location $comfyPath
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "$comfyPath\venv\Scripts\Activate.ps1"
    python -m pip install --upgrade pip

    # PyTorch with CUDA 12.1 (works for Ada Lovelace / 4070S)
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt

    # ----- Pin NumPy 1.x BEFORE installing custom_nodes -----
    # insightface 0.7.3 (используется PuLID) собран под NumPy 1.x ABI.
    # NumPy 2 ломает его cython-extension mesh_core_cython:
    #   ValueError: numpy.dtype size changed, may indicate binary incompatibility.
    # Закрепляем до клонирования нод, чтобы их requirements.txt не подтянули NumPy 2.
    Write-Host "[INFO] Pinning numpy<2 (insightface ABI compat)" -ForegroundColor Cyan
    pip install "numpy<2" --force-reinstall

    # ----- Prebuilt insightface wheel for Windows -----
    # На Windows + Python 3.12 PyPI insightface не собирается без MSVC build tools.
    # Берём prebuilt wheel из Gourieff/Assets, fallback на PyPI если ABI не подошёл.
    $pyAbi = (python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')" | Out-String).Trim()
    $insightUrl = "https://github.com/Gourieff/Assets/raw/main/Insightface/insightface-0.7.3-$pyAbi-$pyAbi-win_amd64.whl"
    Write-Host "[INFO] Installing insightface (prebuilt $pyAbi wheel)" -ForegroundColor Cyan
    try {
        $savedPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        pip install $insightUrl 2>&1 | Out-String | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARN] Prebuilt insightface wheel failed, trying PyPI" -ForegroundColor Yellow
            pip install insightface
        }
    } catch {
        Write-Host "[WARN] insightface install error: $_" -ForegroundColor Yellow
    } finally {
        $ErrorActionPreference = $savedPref
    }
    # PuLID dependencies that are commonly missing
    pip install onnxruntime-gpu facexlib timm

    $nodesDir = Join-Path $comfyPath "custom_nodes"
    if (-not (Test-Path $nodesDir)) {
        New-Item -ItemType Directory -Path $nodesDir | Out-Null
    }
    Set-Location $nodesDir

    # ComfyUI-TeaCache (welltop-cn) удалён из списка — нода ломается на свежих
    # ComfyUI: "cannot import name 'precompute_freqs_cis' from 'comfy.ldm.lightricks.model'".
    # Lightning LoRA даёт основное ускорение (×20), TeaCache добавлял лишь ~30%.
    $customNodes = @(
        "https://github.com/ltdrdata/ComfyUI-Manager.git",
        "https://github.com/city96/ComfyUI-GGUF.git",
        "https://github.com/sipie800/ComfyUI-PuLID-Flux-Enhanced.git",
        "https://github.com/kijai/ComfyUI-WanVideoWrapper.git",
        "https://github.com/kijai/ComfyUI-HunyuanVideoWrapper.git",
        "https://github.com/kijai/ComfyUI-KJNodes.git",
        "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git",
        "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git",
        "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git",
        "https://github.com/rgthree/rgthree-comfy.git",
        "https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper.git",
        "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git"
    )

    foreach ($repo in $customNodes) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($repo)
        if (-not (Test-Path $name)) {
            Write-Host "  cloning $name" -ForegroundColor Gray
            git clone $repo
        } else {
            Write-Host "  $name already present, skip" -ForegroundColor DarkGray
        }
        $reqFile = Join-Path $name "requirements.txt"
        if (Test-Path $reqFile) {
            Write-Host "    installing deps for $name" -ForegroundColor DarkGray
            try {
                $savedPref = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                pip install -r $reqFile 2>&1 | Out-String | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "    [WARN] $name deps failed, continuing" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "    [WARN] ${name}: $_" -ForegroundColor Yellow
            } finally {
                $ErrorActionPreference = $savedPref
            }
        }
    }

    # ----- Re-pin NumPy<2 AFTER nodes -----
    # Какая-нибудь нода в своих requirements могла подтянуть NumPy 2 через
    # transitive deps (например, через свежий scipy/scikit-image без верхней границы).
    # Прогоняем pin ещё раз, чтобы гарантировать совместимость с insightface.
    Write-Host "[INFO] Re-pinning numpy<2 after custom_nodes install" -ForegroundColor Cyan
    pip install "numpy<2" --force-reinstall

    # ----- Sanity check: insightface действительно импортируется -----
    Write-Host "[INFO] Verifying insightface imports cleanly..." -ForegroundColor Cyan
    $checkResult = (python -c "import insightface; print('OK', insightface.__version__)" 2>&1 | Out-String).Trim()
    if ($checkResult -match '^OK') {
        Write-Host "[OK] $checkResult"
    } else {
        Write-Host "[ERR] insightface import broken:" -ForegroundColor Red
        Write-Host $checkResult -ForegroundColor Red
        Write-Host "      PuLID node will fail to load. Fix manually before launching ComfyUI." -ForegroundColor Yellow
    }

    deactivate
    Write-Host "[OK] ComfyUI + 12 custom nodes installed at $comfyPath"
} else {
    Write-Host "[SKIP] ComfyUI skipped" -ForegroundColor Yellow
}

# ============================================================
# 3. SageAttention 2.2 (for Ada Lovelace / 4070S)
# ============================================================
if ((-not $SkipSageAttention) -and (-not $SkipComfyUI)) {
    Write-Step "3/6  SageAttention 2.2"

    Set-Location $comfyPath
    & "$comfyPath\venv\Scripts\Activate.ps1"

    $pyAbi = (python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')" | Out-String).Trim()
    Write-Host "  Python ABI: $pyAbi"

    pip install -U triton-windows

    $sageUrl = "https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/sageattention-2.2.0+cu121torch2.5.1-$pyAbi-$pyAbi-win_amd64.whl"
    $installed = $false
    try {
        pip install $sageUrl
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] SageAttention 2.2 installed"
            $installed = $true
        }
    } catch {
        # fallthrough to warning below
    }

    if (-not $installed) {
        Write-Host "[WARN] SageAttention auto-install failed." -ForegroundColor Yellow
        Write-Host "       Install manually from https://github.com/woct0rdho/SageAttention/releases" -ForegroundColor Yellow
        Write-Host "       Pick a wheel for your Python ($pyAbi) and PyTorch version." -ForegroundColor Yellow
    }

    deactivate
} else {
    Write-Host "[SKIP] SageAttention skipped" -ForegroundColor Yellow
}

# ============================================================
# 4. F5-TTS
# ============================================================
if (-not $SkipF5TTS) {
    Write-Step "4/6  F5-TTS"

    if (-not (Test-Path $f5Path)) {
        git clone https://github.com/SWivid/F5-TTS.git $f5Path
    }

    Set-Location $f5Path
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "$f5Path\venv\Scripts\Activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -e .
    pip install ruaccent

    # F5-TTS use librosa/torchaudio — they pull NumPy 2 via fresh scipy.
    # Pin to 1.x for consistency with the rest of the stack.
    pip install "numpy<2" --force-reinstall

    deactivate

    Write-Host "[OK] F5-TTS installed at $f5Path"
    Write-Host "[INFO] Russian checkpoints: download manually (see MODELS_CHECKLIST.md step 9)"
} else {
    Write-Host "[SKIP] F5-TTS skipped" -ForegroundColor Yellow
}

# ============================================================
# 5. RVC (Mangio fork)
# ============================================================
if (-not $SkipRVC) {
    Write-Step "5/6  RVC"

    if (-not (Test-Path $rvcPath)) {
        git clone https://github.com/Mangio621/Mangio-RVC-Fork.git $rvcPath
    }

    Set-Location $rvcPath
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "$rvcPath\venv\Scripts\Activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt

    # RVC depends on librosa/numba, which historically don't like NumPy 2.
    # Keep the whole project on NumPy 1.x.
    pip install "numpy<2" --force-reinstall

    deactivate

    Write-Host "[OK] RVC installed at $rvcPath"
} else {
    Write-Host "[SKIP] RVC skipped" -ForegroundColor Yellow
}

# ============================================================
# 6. FluxGym
# ============================================================
if (-not $SkipFluxGym) {
    Write-Step "6/6  FluxGym"

    if (-not (Test-Path $gymPath)) {
        git clone https://github.com/cocktailpeanut/fluxgym.git $gymPath
    }

    Set-Location $gymPath
    if (-not (Test-Path "env")) {
        python -m venv env
    }
    & "$gymPath\env\Scripts\Activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt

    $sdScripts = Join-Path $gymPath "sd-scripts"
    if (Test-Path (Join-Path $sdScripts "requirements.txt")) {
        Set-Location $sdScripts
        pip install -r requirements.txt
        Set-Location $gymPath
    }
    deactivate

    Write-Host "[OK] FluxGym installed at $gymPath"
} else {
    Write-Host "[SKIP] FluxGym skipped" -ForegroundColor Yellow
}

# ============================================================
# Done
# ============================================================
Set-Location $scriptDir

Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host "INSTALLATION COMPLETE" -ForegroundColor Green
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host ""
Write-Host "Installed under ${BasePath}:"
Write-Host "  ComfyUI   : $comfyPath"
Write-Host "  F5-TTS    : $f5Path"
Write-Host "  RVC       : $rvcPath"
Write-Host "  FluxGym   : $gymPath"
Write-Host ""
Write-Host "NEXT STEPS:"
Write-Host ""
Write-Host "1) Open config.py and update paths if they differ:"
Write-Host "     COMFYUI_ROOT = Path(r'$comfyPath')"
Write-Host "     F5_TTS_ROOT  = Path(r'$f5Path')"
Write-Host "     RVC_ROOT     = Path(r'$rvcPath')"
Write-Host "     FLUXGYM_ROOT = Path(r'$gymPath')"
Write-Host ""
Write-Host "2) Download ML models (~60 GB):"
Write-Host "     venv\Scripts\activate"
Write-Host "     pip install huggingface_hub"
Write-Host "     python download_models.py --comfyui $comfyPath --f5tts $f5Path"
Write-Host ""
Write-Host "3) Launch ComfyUI (in a separate window):"
Write-Host "     cd $comfyPath"
Write-Host "     venv\Scripts\activate"
Write-Host "     python main.py --use-sage-attention --fast --reserve-vram 0.5"
Write-Host ""
Write-Host "4) Launch our web UI:"
Write-Host "     cd $scriptDir"
Write-Host "     venv\Scripts\activate"
Write-Host "     python webui.py"
Write-Host ""
Write-Host "5) Open in browser: http://127.0.0.1:7861"
Write-Host ""