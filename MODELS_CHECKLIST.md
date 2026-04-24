# Чеклист моделей для скачивания

Всё качается с HuggingFace (кроме CodeFormer — с github releases). Общий объём ~55 GB.
Положи в соответствующие подпапки `ComfyUI/models/`.

> **Быстрый путь** — `download_models.py` скачает всё автоматически:
> ```powershell
> pip install huggingface_hub
> python download_models.py --comfyui D:\GitHub\ai-ofm\ComfyUI --f5tts D:\GitHub\ai-ofm\F5-TTS
> ```
> Дальше в этом файле — справка на случай, если хочется скачать руками или разобраться откуда что.

---

## 1. Flux.1-dev (персонаж) — ~10 GB

**unet/** (основная модель):
- `flux1-dev-Q5_K_S.gguf` — https://huggingface.co/city96/FLUX.1-dev-gguf
  - ⚠️ у city96 для **dev** есть Q5_K_S / Q5_0 / Q5_1, но **нет Q5_K_M** (есть только для schnell). Используем Q5_K_S — это оптимум для 12 GB.
  - альтернатива с запасом: `flux1-dev-Q4_K_S.gguf`

**clip/** (текстовые энкодеры):
- `clip_l.safetensors` — https://huggingface.co/comfyanonymous/flux_text_encoders
- `t5xxl_fp8_e4m3fn.safetensors` — там же (FP8 обязательно для PuLID на 12 GB)

**vae/**:
- `ae.safetensors` — https://huggingface.co/ffxvs/vae-flux (non-gated зеркало, SHA256 идентичен BFL)
  - оригинал: https://huggingface.co/black-forest-labs/FLUX.1-dev — **gated**, нужен логин и принятие лицензии

## 2. PuLID-Flux II — ~1.2 GB

**pulid/** (создать если нет):
- `pulid_flux_v0.9.1.safetensors` — https://huggingface.co/guozinan/PuLID/tree/main

EVA CLIP и AntelopeV2 скачаются нодой автоматически при первом запуске.

## 3. Face restoration — ~500 MB

**facerestore_models/**:
- `codeformer-v0.1.0.pth` — https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth
  - SHA256: `1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7`
  - HF-зеркала для CodeFormer нестабильны (файлы теряются из main ветки), качаем с github напрямую.

**ultralytics/bbox/**:
- `face_yolov8m.pt` — https://huggingface.co/Bingsu/adetailer/tree/main

## 4. Wan 2.2 I2V (image-to-video) — ~22 GB

**unet/** (GGUF-кванты с QuantStack, в подпапках `HighNoise/` и `LowNoise/`):
- `Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf` — https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/tree/main/HighNoise
  - в нашем проекте лежит под именем `wan2.2_i2v_high_noise_14B_Q4_K_M.gguf`
- `Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf` — https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/tree/main/LowNoise
  - в нашем проекте: `wan2.2_i2v_low_noise_14B_Q4_K_M.gguf`

**vae/** — `wan_2.1_vae.safetensors`
**clip_vision/** — `clip_vision_h.safetensors`
**clip/** (или text_encoders/) — `umt5_xxl_fp8_e4m3fn_scaled.safetensors`

Все три из одного репо: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/tree/main/split_files — это официальный repackaged комплект для ComfyUI.

## 5. Lightning LoRA (КРИТИЧНО, ×20 ускорение) — ~600 MB

**loras/** — из подпапки `Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1/`:
- `high_noise_model.safetensors` → переименовать в `wan2.2_i2v_lightning_4steps_high_noise_v1.1.safetensors`
- `low_noise_model.safetensors` → переименовать в `wan2.2_i2v_lightning_4steps_low_noise_v1.1.safetensors`

Источник: https://huggingface.co/lightx2v/Wan2.2-Lightning/tree/main

## 6. SeedVR2 7B (апскейл видео) — ~8 GB

**seedvr2/** (создать) или **diffusion_models/**:
- `seedvr2_ema_7b_fp8_e4m3fn.safetensors` — https://huggingface.co/numz/SeedVR2_comfyUI

> ⚠️ **Баг текущего проекта:** в `config.py` указано имя `seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors`, но `download_models.py` качает `seedvr2_ema_7b_fp8_e4m3fn.safetensors` — реальный файл на HF. Поправь одно из двух:
> - либо переименуй скачанный файл в то что ждёт `config.py`
> - либо поправь в `config.py` → `SEEDVR2_MODEL = "seedvr2_ema_7b_fp8_e4m3fn.safetensors"`

## 7. LatentSync 1.6 (lip sync) — ~2 GB

Модели подтянутся автоматически через `ShmuelRonen/ComfyUI-LatentSyncWrapper` при первом запуске:
- ByteDance LatentSync 1.6 checkpoint
- Whisper для аудио-эмбеддингов

Если хочешь вручную — https://huggingface.co/ByteDance/LatentSync-1.6

**Требования к входу:**
- Видео ровно 25 fps (workflow принудительно конвертирует)
- Фронтальное лицо, 1 человек, не anime
- Аудио WAV 16kHz mono предпочтительно (ffmpeg конвертирует автоматом)

## 8. RIFE v4.x (интерполяция fps) — ~70 MB

Автоматически скачивается `ComfyUI-Frame-Interpolation` при первом запуске.
Вручную: https://github.com/Fannovel16/ComfyUI-Frame-Interpolation → папка `models/` внутри custom_node.

В workflow стоит имя `rife47.pth`. Если подтянулась другая версия (`rife49`, `rife_v4.25`) — поправь `RifeSettings.model` в `config.py`.

## 9. F5-TTS + русский файнтюн (голос) — ~1.5 GB

**Установка F5-TTS (в отдельную папку, не в ComfyUI):**
```powershell
git clone https://github.com/SWivid/F5-TTS D:\GitHub\ai-ofm\F5-TTS
cd D:\GitHub\ai-ofm\F5-TTS
python -m venv venv
venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -e .
pip install ruaccent
```

Путь `D:\GitHub\ai-ofm\F5-TTS` должен совпадать с `F5_TTS_ROOT` в `config.py`.

**Русский файнтюн Misha24-10:**

```powershell
huggingface-cli download Misha24-10/F5-TTS_RUSSIAN `
  F5TTS_v1_Base_v2/model_last_inference.safetensors `
  --local-dir D:\GitHub\ai-ofm\F5-TTS\ckpts
```

Переименуй `F5TTS_v1_Base_v2/model_last_inference.safetensors` → `F5TTS_v1_Base_v2.safetensors` (или поправь `F5Settings.ckpt_path`).

> ⚠️ У Misha24-10 **нет** `model_last.safetensors` — только:
> - `model_last_inference.safetensors` (1.35 GB, только веса для инференса) — это то что нужно
> - `model_last.pt` (5.39 GB, тренировочный — оптимизатор и всё остальное)

**vocab.txt** — Misha24-10 свой не выкладывает, используем базовый от SWivid. Русская модель использует тот же char-tokenizer, символ `+` для ударения:

```powershell
huggingface-cli download SWivid/F5-TTS F5TTS_v1_Base/vocab.txt `
  --local-dir D:\GitHub\ai-ofm\F5-TTS\ckpts
```

**Доступные варианты ckpt от Misha24-10:**
- `F5TTS_v1_Base` — базовый русский
- `F5TTS_v1_Base_v2` — улучшенный (рекомендуется, скачивается по умолчанию)
- `F5TTS_v1_Base_accent_tune` — с акцентом на правильные ударения

**Референсный голос** — запиши сам 3-10 секунд чистого голоса (без музыки, без эха) в WAV 24kHz mono. Запиши ТОЧНУЮ транскрипцию того, что там сказано, — F5-TTS без транскрипции не работает.

## 10. RVC (опциональная шлифовка голоса) — ~1 GB

**Установка (форк Mangio рекомендуется):**
```powershell
git clone https://github.com/Mangio621/Mangio-RVC-Fork D:\GitHub\ai-ofm\RVC
cd D:\GitHub\ai-ofm\RVC
python -m venv venv
venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

Путь `D:\GitHub\ai-ofm\RVC` должен совпадать с `RVC_ROOT` в `config.py`.

**Обучение своего голоса:** залей 10-30 минут чистой речи, запусти `go-web.bat` → вкладка Train → дождись 150-300 эпох. На 4070S это 1-3 часа.

После обучения пропиши в `config.py`:
```python
RVCSettings.model_pth = Path(r"D:\GitHub\ai-ofm\RVC\weights\my_voice.pth")
RVCSettings.index_file = Path(r"D:\GitHub\ai-ofm\RVC\logs\my_voice\added_*.index")
```

## 11. Flux Kontext Dev (edit-based персонаж) — ~8 GB

**unet/**:
- `flux1-kontext-dev-Q5_K_M.gguf` — https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF
  - (city96 выкладывает Kontext позже QuantStack'а — берём актуальный)

Использует тот же `clip_l.safetensors`, `t5xxl_fp8_e4m3fn.safetensors` и `ae.safetensors` что и Flux.1-dev — ничего дополнительно качать не нужно.

В ComfyUI нужны ноды `FluxKontextImageScale` и `ReferenceLatent` — они появились в ядре с августа 2025. Если их нет — обнови ComfyUI до последней версии.

## 12. FluxGym (тренировка LoRA своего персонажа)

**Установка (в отдельную папку, не в ComfyUI):**
```powershell
git clone https://github.com/cocktailpeanut/fluxgym D:\GitHub\ai-ofm\fluxgym
cd D:\GitHub\ai-ofm\fluxgym
python -m venv env
env\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
cd sd-scripts
pip install -r requirements.txt
cd ..
```

Путь `D:\GitHub\ai-ofm\fluxgym` должен совпадать с `FLUXGYM_ROOT` в `config.py`.

FluxGym подтянет базовые модели Flux-dev сам при первом запуске тренировки (~24 GB загрузки).

**Workflow:**
1. `python main.py lora-dataset --ref my_char.png --name anna_v1` — сгенерирует 30 вариаций в `output/lora_datasets/anna_v1/`
2. Отсмотри папку — удали все плохие кадры (кривые лица, артефакты)
3. Запусти FluxGym: `cd D:\GitHub\ai-ofm\fluxgym && env\Scripts\activate && python app.py`
4. Загрузи отобранные фото через Gradio UI, настрой параметры по инструкции в консоли
5. 3-5 часов тренировки на 4070S
6. Итог → скопируй `.safetensors` в `ComfyUI\models\loras\`

---

# Custom nodes (ставит `install.ps1` или ComfyUI-Manager)

1. **ComfyUI-Manager** (ltdrdata) — менеджер для остальных нод
2. **ComfyUI-GGUF** (city96) — загрузка GGUF моделей
3. **ComfyUI-PuLID-Flux-Enhanced** (sipie800) — PuLID-Flux II
4. **ComfyUI-WanVideoWrapper** (kijai) — Wan 2.2 с block_swap
5. **ComfyUI-HunyuanVideoWrapper** (kijai) — на будущее
6. **ComfyUI-KJNodes** (kijai) — утилиты
7. **ComfyUI-SeedVR2_VideoUpscaler** (numz) — SeedVR2
8. **ComfyUI-VideoHelperSuite** (Kosinkadink) — загрузка/сохранение видео
9. **ComfyUI-Impact-Pack** (ltdrdata) — FaceDetailer
10. **ComfyUI-TeaCache** (welltop-cn) — ускорение
11. **rgthree-comfy** — улучшения интерфейса
12. **ComfyUI-LatentSyncWrapper** (ShmuelRonen) — lip sync
13. **ComfyUI-Frame-Interpolation** (Fannovel16) — RIFE для fps

# SageAttention 2.2 (Windows + CUDA 12.1, для Ada Lovelace)

`install.ps1` ставит автоматически. Ручная установка в venv ComfyUI:

```powershell
cd D:\GitHub\ai-ofm\ComfyUI
venv\Scripts\activate
pip install -U triton-windows
# замени cp312 на свою версию Python (cp310/cp311/cp312)
pip install https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/sageattention-2.2.0+cu121torch2.5.1-cp312-cp312-win_amd64.whl
```

Проверить версию Python:
```powershell
python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"
```

Запуск ComfyUI с SageAttention:
```powershell
python main.py --use-sage-attention --fast --reserve-vram 0.5
```