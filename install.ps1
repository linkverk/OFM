# ============================================================
# AI OFM Studio — единый установщик для Windows
# ============================================================
#
# Запуск (в PowerShell с правами Administrator):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\install.ps1
#
# Что скрипт делает:
#   1. Проверяет Python 3.10-3.12 и CUDA
#   2. Создаёт venv и ставит наши зависимости
#   3. Клонирует и ставит ComfyUI + все custom_nodes
#   4. Клонирует и ставит F5-TTS + ruaccent
#   5. Клонирует и ставит Mangio-RVC-Fork
#   6. Клонирует и ставит FluxGym
#   7. Ставит SageAttention 2.2 wheel для Ada Lovelace (4070S)
#
# Что скрипт НЕ делает автоматически:
#   - Не качает модели (они многогигабайтные, см. download_models.ps1)
#   - Не настраивает пути в config.py (делается вручную после установки)
#   - Не тренирует ничего
#
# Время выполнения: ~30-60 минут в зависимости от интернета.
# Размер установок: ~40 GB (без моделей).
# ============================================================

param(
    [string]$BasePath = "C:\ai-ofm",          # корневая папка для всех инсталляций
    [switch]$SkipComfyUI,
    [switch]$SkipF5TTS,
    [switch]$SkipRVC,
    [switch]$SkipFluxGym,
    [switch]$SkipSageAttention
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host ("=" * 65) -ForegroundColor Cyan
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 65) -ForegroundColor Cyan
}

function Test-Command($cmd) {
    $null = Get-Command $cmd -ErrorAction SilentlyContinue
    return $?
}

# ------------------------------------------------------------
# 0. Проверки окружения
# ------------------------------------------------------------
Write-Step "ПРОВЕРКА ОКРУЖЕНИЯ"

if (-not (Test-Command "git")) {
    Write-Host "❌ Git не установлен. Скачай: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

if (-not (Test-Command "python")) {
    Write-Host "❌ Python не в PATH. Скачай 3.11 или 3.12: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

$pyVersion = python --version 2>&1
Write-Host "✓ $pyVersion"
if ($pyVersion -notmatch "Python 3\.(10|11|12)") {
    Write-Host "⚠️  Рекомендуется Python 3.10-3.12. У тебя: $pyVersion" -ForegroundColor Yellow
}

# CUDA — только предупреждение, не блокер
try {
    $nvidia = nvidia-smi 2>&1
    if ($nvidia -match "CUDA Version: (\d+\.\d+)") {
        Write-Host "✓ CUDA $($matches[1]) детектирован"
    }
} catch {
    Write-Host "⚠️  nvidia-smi не найден. CUDA драйверы установлены?" -ForegroundColor Yellow
}

# Создаём базовую папку
if (-not (Test-Path $BasePath)) {
    New-Item -ItemType Directory -Path $BasePath | Out-Null
}
Write-Host "✓ Базовая папка: $BasePath"

# ------------------------------------------------------------
# 1. Наша программа — venv + requirements.txt
# ------------------------------------------------------------
Write-Step "1/6: НАША ПРОГРАММА (AI OFM Studio)"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path "venv")) {
    python -m venv venv
}
& "venv\Scripts\activate.ps1"
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "✓ Наши зависимости установлены в venv/"
deactivate

# ------------------------------------------------------------
# 2. ComfyUI
# ------------------------------------------------------------
if (-not $SkipComfyUI) {
    Write-Step "2/6: COMFYUI + CUSTOM NODES"

    $comfyPath = Join-Path $BasePath "ComfyUI"
    if (-not (Test-Path $comfyPath)) {
        git clone https://github.com/comfyanonymous/ComfyUI.git $comfyPath
    } else {
        Write-Host "ComfyUI уже установлен, обновляю..." -ForegroundColor Yellow
        Set-Location $comfyPath
        git pull
    }

    Set-Location $comfyPath
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "venv\Scripts\activate.ps1"
    python -m pip install --upgrade pip

    # PyTorch с CUDA 12.1 (универсальная версия для Ada Lovelace)
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt

    # Custom nodes
    Set-Location (Join-Path $comfyPath "custom_nodes")

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
        "https://github.com/welltop-cn/ComfyUI-TeaCache.git",
        "https://github.com/rgthree/rgthree-comfy.git",
        "https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper.git",
        "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git"
    )

    foreach ($repo in $customNodes) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($repo)
        if (-not (Test-Path $name)) {
            Write-Host "  Клонирую $name..." -ForegroundColor Gray
            git clone $repo
        } else {
            Write-Host "  $name уже есть, пропускаю" -ForegroundColor DarkGray
        }

        # Ставим зависимости node-а если есть requirements.txt
        $reqFile = Join-Path $name "requirements.txt"
        if (Test-Path $reqFile) {
            Write-Host "    ставлю зависимости $name..." -ForegroundColor DarkGray
            pip install -r $reqFile 2>&1 | Out-Null
        }
    }

    deactivate
    Write-Host "✓ ComfyUI + 13 custom nodes установлены"
    Write-Host "  Расположение: $comfyPath"
} else {
    Write-Host "⊘ ComfyUI пропущен" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 3. SageAttention 2.2 (обязательно для 4070S)
# ------------------------------------------------------------
if (-not $SkipSageAttention -and -not $SkipComfyUI) {
    Write-Step "3/6: SAGEATTENTION 2.2 (для Ada Lovelace)"

    Set-Location $comfyPath
    & "venv\Scripts\activate.ps1"

    # Определяем Python ABI версию для подбора wheel
    $pyAbi = python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"
    Write-Host "  Python ABI: $pyAbi"

    pip install -U triton-windows

    # Пытаемся поставить SageAttention. URL может меняться — пользователь поправит при ошибке
    $sageUrl = "https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/sageattention-2.2.0+cu121torch2.5.1-$pyAbi-$pyAbi-win_amd64.whl"
    try {
        pip install $sageUrl
        Write-Host "✓ SageAttention 2.2 установлен"
    } catch {
        Write-Host "⚠️  SageAttention автоустановка не удалась." -ForegroundColor Yellow
        Write-Host "   Поставь вручную с https://github.com/woct0rdho/SageAttention/releases" -ForegroundColor Yellow
        Write-Host "   под свою версию Python ($pyAbi) и PyTorch." -ForegroundColor Yellow
    }

    deactivate
} else {
    Write-Host "⊘ SageAttention пропущен" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 4. F5-TTS
# ------------------------------------------------------------
if (-not $SkipF5TTS) {
    Write-Step "4/6: F5-TTS (русский голос)"

    $f5Path = Join-Path $BasePath "F5-TTS"
    if (-not (Test-Path $f5Path)) {
        git clone https://github.com/SWivid/F5-TTS.git $f5Path
    }

    Set-Location $f5Path
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "venv\Scripts\activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -e .
    pip install ruaccent
    deactivate

    Write-Host "✓ F5-TTS установлен в $f5Path"
    Write-Host "  ⚠️  Русские ckpt качать вручную — см. MODELS_CHECKLIST.md шаг 9"
} else {
    Write-Host "⊘ F5-TTS пропущен" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 5. RVC (Mangio-RVC-Fork)
# ------------------------------------------------------------
if (-not $SkipRVC) {
    Write-Step "5/6: RVC (Mangio-RVC-Fork)"

    $rvcPath = Join-Path $BasePath "RVC"
    if (-not (Test-Path $rvcPath)) {
        git clone https://github.com/Mangio621/Mangio-RVC-Fork.git $rvcPath
    }

    Set-Location $rvcPath
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "venv\Scripts\activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt
    deactivate

    Write-Host "✓ RVC установлен в $rvcPath"
    Write-Host "  ⚠️  Свой голос обучать через go-web.bat в самом RVC"
} else {
    Write-Host "⊘ RVC пропущен" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 6. FluxGym
# ------------------------------------------------------------
if (-not $SkipFluxGym) {
    Write-Step "6/6: FLUXGYM (тренировка LoRA)"

    $gymPath = Join-Path $BasePath "fluxgym"
    if (-not (Test-Path $gymPath)) {
        git clone https://github.com/cocktailpeanut/fluxgym.git $gymPath
    }

    Set-Location $gymPath
    if (-not (Test-Path "env")) {
        python -m venv env
    }
    & "env\Scripts\activate.ps1"
    python -m pip install --upgrade pip
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements.txt

    if (Test-Path "sd-scripts\requirements.txt") {
        Set-Location "sd-scripts"
        pip install -r requirements.txt
        Set-Location ..
    }
    deactivate

    Write-Host "✓ FluxGym установлен в $gymPath"
} else {
    Write-Host "⊘ FluxGym пропущен" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# Финал
# ------------------------------------------------------------
Set-Location $scriptDir

Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host "УСТАНОВКА ЗАВЕРШЕНА" -ForegroundColor Green
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host ""
Write-Host "Установлено в $BasePath:"
Write-Host "  • ComfyUI      $comfyPath"
Write-Host "  • F5-TTS       $BasePath\F5-TTS"
Write-Host "  • RVC          $BasePath\RVC"
Write-Host "  • FluxGym      $BasePath\fluxgym"
Write-Host ""
Write-Host "СЛЕДУЮЩИЕ ШАГИ:"
Write-Host ""
Write-Host "1. Открой config.py и поправь пути если они отличаются от:"
Write-Host "   COMFYUI_ROOT = Path(r`"$comfyPath`")"
Write-Host "   F5_TTS_ROOT  = Path(r`"$BasePath\F5-TTS`")"
Write-Host "   RVC_ROOT     = Path(r`"$BasePath\RVC`")"
Write-Host "   FLUXGYM_ROOT = Path(r`"$BasePath\fluxgym`")"
Write-Host ""
Write-Host "2. Скачай модели (~50 GB) — см. MODELS_CHECKLIST.md"
Write-Host ""
Write-Host "3. Запусти ComfyUI:"
Write-Host "   cd $comfyPath"
Write-Host "   venv\Scripts\activate"
Write-Host "   python main.py --use-sage-attention --fast --reserve-vram 0.5"
Write-Host ""
Write-Host "4. В другом окне — наш веб-интерфейс:"
Write-Host "   cd $scriptDir"
Write-Host "   venv\Scripts\activate"
Write-Host "   python webui.py"
Write-Host ""
Write-Host "5. Откроется http://127.0.0.1:7861"
Write-Host ""
