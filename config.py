"""
AI OFM Studio — конфигурация под RTX 4070 Super 12GB / R7 7800X3D / 32GB DDR5
Все пороги, квантизации и лимиты подобраны под эту сборку.
"""
from pathlib import Path

# ============ ПУТИ ============
# ComfyUI должен быть установлен отдельно. Укажи путь:
COMFYUI_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\ComfyUI")          # Windows
# COMFYUI_ROOT = Path.home() / "ComfyUI"    # Linux

COMFYUI_URL = "http://127.0.0.1:8188"       # стандартный порт
COMFYUI_MODELS = COMFYUI_ROOT / "models"

PROJECT_ROOT = Path(__file__).parent
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
OUTPUT_DIR = PROJECT_ROOT / "output"
INPUT_DIR = PROJECT_ROOT / "input"

for d in (OUTPUT_DIR, INPUT_DIR):
    d.mkdir(exist_ok=True)

# ============ МОДЕЛИ (имена файлов, как ComfyUI их видит) ============

# --- Flux линия (персонаж) ---
FLUX_UNET_GGUF = "flux1-dev-Q5_K_S.gguf"            # ~8 GB, оптимум для 12 GB
FLUX_CLIP_L = "clip_l.safetensors"
FLUX_T5 = "t5xxl_fp8_e4m3fn.safetensors"            # FP8 чтобы влезть с PuLID
FLUX_VAE = "ae.safetensors"

# Flux Kontext Dev (edit-based генерация)
FLUX_KONTEXT_GGUF = "flux1-kontext-dev-Q5_K_M.gguf"   # QuantStack/FLUX.1-Kontext-dev-GGUF (Q5_K_M существует, оптимум)

# PuLID-Flux II (face consistency)
PULID_MODEL = "pulid_flux_v0.9.1.safetensors"
EVA_CLIP = "EVA02-CLIP-L-14-336.pt"                 # авто-скачается нодой
INSIGHTFACE_MODEL = "antelopev2"                    # авто-скачается

# Face restoration
CODEFORMER_MODEL = "codeformer-v0.1.0.pth"
FACE_YOLO = "bbox/face_yolov8m.pt"                  # для FaceDetailer

# --- Wan 2.2 (image-to-video) ---
WAN_HIGH_NOISE = "wan2.2_i2v_high_noise_14B_Q4_K_M.gguf"
WAN_LOW_NOISE = "wan2.2_i2v_low_noise_14B_Q4_K_M.gguf"
WAN_VAE = "wan_2.1_vae.safetensors"
WAN_CLIP_VISION = "clip_vision_h.safetensors"
WAN_T5 = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"

# Lightning LoRA — КРИТИЧНО, ускоряет x20
WAN_LIGHTNING_HIGH = "wan2.2_i2v_lightning_4steps_high_noise_v1.1.safetensors"
WAN_LIGHTNING_LOW = "wan2.2_i2v_lightning_4steps_low_noise_v1.1.safetensors"

# --- SeedVR2 (апскейл видео) ---
SEEDVR2_MODEL  = "seedvr2_ema_7b_fp8_e4m3fn.safetensors" 

# ============ ПАРАМЕТРЫ ГЕНЕРАЦИИ под 4070S ============

class FluxSettings:
    """Flux.1-dev Q5_K_S + PuLID на 12 GB VRAM"""
    width = 1024
    height = 1024
    steps = 20
    guidance = 3.5              # FluxGuidance для PuLID 2.5-3.5
    sampler = "euler"
    scheduler = "simple"
    # PuLID
    pulid_weight = 1.0          # референс из отчёта
    pulid_start = 0.0
    pulid_end = 1.0
    # FaceDetailer после
    face_detailer_denoise = 0.4
    codeformer_fidelity = 0.6   # 0.5-0.7 баланс identity/качество

class FluxKontextSettings:
    """Flux Kontext Dev — edit-based вариации персонажа по эталону."""
    # Kontext работает с парой (эталон, промпт-редакт) → новое изображение
    width = 1024                # Kontext чувствителен к разрешению, держим квадрат
    height = 1024
    steps = 20
    guidance = 2.5              # для Kontext обычно 2.0-3.0
    sampler = "euler"
    scheduler = "beta"          # для Kontext рекомендуется beta

class WanSettings:
    """Wan 2.2 I2V Q4_K_M + Lightning — 4-6 мин на 5 сек клип (без TeaCache)"""
    # размер — держим 480p для 12 GB
    width = 832
    height = 480
    # длина клипа
    num_frames = 81             # 5 секунд @ 16 fps (Wan native)
    fps_out = 24                # апскейл fps через RIFE потом
    # Lightning 4+4 шагов
    steps_high = 4
    steps_low = 4
    cfg = 1.0                   # с Lightning CFG всегда 1
    sampler = "lcm"
    scheduler = "simple"
    # Память
    blocks_to_swap = 25         # для Q4_K_M на 12 GB оптимально 20-30
    enable_sage_attention = True
    # TeaCache отключён — нода ComfyUI-TeaCache (welltop-cn) ломается на свежих
    # ComfyUI (precompute_freqs_cis перенесли в ядре). Lightning LoRA даёт основное
    # ускорение (×20), потеря TeaCache ~30% — терпимо.
    enable_teacache = False
    teacache_threshold = 0.25   # неактивно пока enable_teacache=False

class SeedVR2Settings:
    """SeedVR2 7B FP8 — апскейл с temporal consistency"""
    upscale_factor = 2          # 480p → 960p или 720p → 1440p
    batch_size = 5              # временной батч кадров
    blocks_to_swap = 12         # для 7B на 12 GB: 10-15
    cfg_scale = 1.0
    seed_offset = 0

class LatentSyncSettings:
    """LatentSync 1.6 — lip sync. 6-8 GB VRAM, 25 fps обязательно."""
    inference_steps = 25        # 20-50; баланс скорости/качества
    lips_expression = 2.0       # 1.5-2.5 речь, 2.0-3.0 эмоции
    guidance_scale = 1.5
    input_fps = 25              # фикс, требование модели

class RifeSettings:
    """RIFE v4.x — интерполяция fps. ~2 GB VRAM, очень быстро."""
    multiplier = 2              # 24→48. Ставь 3 для 24→72 (ультраплавность)
    output_fps = 48             # должно быть = source_fps * multiplier
    model = "rife47.pth"        # у тебя может оказаться rife49.pth или rife_v4.25.pth
    fast_mode = True
    ensemble = True


# ============ TTS (F5-TTS + RVC) ============
# Запускаются отдельно от ComfyUI, но конкурируют за VRAM.
# F5-TTS: ~4-8 GB VRAM inference. RVC: ~4-6 GB.
# Стратегия: перед запуском TTS выгружаем ComfyUI из VRAM (free_memory).

# Пути к установкам (поставь отдельно — см. MODELS_CHECKLIST.md)
F5_TTS_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\F5-TTS")                # git clone SWivid/F5-TTS
RVC_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\RVC")                   # git clone RVC-Project/...

# --- F5-TTS ---
class F5Settings:
    """F5-TTS с русским файнтюном Misha24-10/F5-TTS_RUSSIAN."""
    # Название модели для CLI ключа `--model`
    model_name = "F5TTS_v1_Base"                # либо "F5TTS_v1_Base_v2" / "..._accent_tune"
    # Путь к ckpt от Misha24-10 (скачивается вручную)
    ckpt_path = F5_TTS_ROOT / "ckpts" / "F5TTS_v1_Base_v2.safetensors"
    vocab_path = F5_TTS_ROOT / "ckpts" / "vocab.txt"
    # Автоматическая расстановка ударений через RUAccent
    use_ruaccent = True
    # Путь к референсу голоса (3-10 сек WAV 24kHz mono, чистая речь)
    reference_audio: Path = None                 # задаётся на лету
    reference_text: str = ""                     # точная транскрипция референса
    # Параметры синтеза
    nfe_step = 32                                # шаги (16-32), больше = качественнее
    cfg_strength = 2.0
    speed = 1.0                                  # 0.8 медленнее, 1.2 быстрее
    cross_fade_duration = 0.15                   # стыковка чанков
    remove_silence = True

# --- RVC (опциональный post-процессинг) ---
class RVCSettings:
    """RVC — голос-конверсия для финальной шлифовки тембра."""
    # Путь к ckpt голоса (.pth) и .index файлу (создаются при обучении)
    model_pth: Path = None
    index_file: Path = None
    # Параметры
    f0_method = "rmvpe"                          # лучший из доступных в 2026
    pitch = 0                                    # семитоны; для ж↔м сдвиг ±12
    index_rate = 0.75
    filter_radius = 3
    rms_mix_rate = 0.25
    protect = 0.33                               # защищает согласные от шумов


# ============ FluxGym (тренировка LoRA персонажа) ============
FLUXGYM_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\fluxgym")            # git clone cocktailpeanut/fluxgym

class FluxGymSettings:
    """
    Настройки тренировки LoRA через FluxGym на RTX 4070 Super 12 GB.
    Берём VRAM preset 12G из официальной документации FluxGym.
    """
    vram_preset = "12G"                          # 12G / 16G / 20G
    base_model = "flux-dev"                      # flux-dev или flux-schnell
    # параметры тренировки
    resolution = 512                             # 512 в 3x быстрее 768; 768 для качества
    repeat = 5                                   # повторы каждого фото за эпоху
    max_epochs = 16                              # 8-16 оптимум
    save_every_n_epochs = 4                      # сохранять чекпойнты
    # датасет
    min_dataset = 15                             # меньше 15 фото — плохой LoRA
    max_dataset = 40                             # 20-30 оптимум
    # кэпшенинг
    auto_caption = True                          # Florence-2 автокэпшенинг
    trigger_word = "ohwx person"                 # редкий токен — обязательно

# ============ ГЛОБАЛЬНЫЕ ОПЦИИ COMFYUI ============

# Флаги запуска ComfyUI для 12 GB + 32 GB RAM:
COMFYUI_LAUNCH_FLAGS = [
    "--use-sage-attention",     # быстрее на Ada Lovelace
    "--reserve-vram", "1.0",    # оставить под систему (поднято с 0.5 — больше запаса при тяжёлых workflow)
    "--disable-dynamic-vram",   # отключить comfy-aimdo hooks (CUDA driver detour). Конфликтует с GGUF partial unload — 'CUDA error: invalid argument' при partially_unload Q5_K тензоров.
    # "--fast",                  # ОТКЛЮЧЕНО: fp16 accumulation плохо дружит с GGUF Q5_K (Flux). Включай только если все модели в нативной точности.
    # "--disable-smart-memory",  # включать если ловишь OOM на Wan
]

# Системные пороги
MAX_RAM_USAGE_GB = 28           # из 32 GB, запас под ОС
POLL_INTERVAL_SEC = 2           # как часто спрашивать статус у ComfyUI
QUEUE_TIMEOUT_SEC = 1800        # 30 мин максимум на одну задачу