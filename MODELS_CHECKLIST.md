# Чеклист моделей для скачивания

Всё качается с HuggingFace. Общий объём ~50 GB.
Положи в соответствующие подпапки `ComfyUI/models/`.

## 1. Flux.1-dev (персонаж) — ~10 GB

**unet/** (основная модель):
- `flux1-dev-Q5_K_M.gguf` — https://huggingface.co/city96/FLUX.1-dev-gguf
  - альтернатива для запаса: `flux1-dev-Q4_K_S.gguf` если Q5 впритык

**clip/** (текстовые энкодеры):
- `clip_l.safetensors` — https://huggingface.co/comfyanonymous/flux_text_encoders
- `t5xxl_fp8_e4m3fn.safetensors` — там же (FP8 обязательно для PuLID на 12 GB)

**vae/**:
- `ae.safetensors` (Flux VAE) — https://huggingface.co/black-forest-labs/FLUX.1-dev/tree/main

## 2. PuLID-Flux II — ~1.2 GB

**pulid/** (создать если нет):
- `pulid_flux_v0.9.1.safetensors` — https://huggingface.co/guozinan/PuLID/tree/main

EVA CLIP и AntelopeV2 скачаются нодой автоматически при первом запуске.

## 3. Face restoration — ~500 MB

**facerestore_models/**:
- `codeformer-v0.1.0.pth` — https://github.com/sczhou/CodeFormer/releases

**ultralytics/bbox/**:
- `face_yolov8m.pt` — https://huggingface.co/Bingsu/adetailer/tree/main

## 4. Wan 2.2 I2V (image-to-video) — ~20 GB

**unet/** или **diffusion_models/**:
- `wan2.2_i2v_high_noise_14B_Q4_K_M.gguf` — https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF
- `wan2.2_i2v_low_noise_14B_Q4_K_M.gguf` — там же

**vae/**:
- `wan_2.1_vae.safetensors` — https://huggingface.co/Kijai/WanVideo_comfy

**clip_vision/**:
- `clip_vision_h.safetensors` — https://huggingface.co/Kijai/WanVideo_comfy

**text_encoders/** (или **clip/**):
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors` — https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled

## 5. Lightning LoRA (КРИТИЧНО, ×20 ускорение) — ~600 MB

**loras/**:
- `wan2.2_i2v_lightning_4steps_high_noise_v1.1.safetensors` — https://huggingface.co/lightx2v/Wan2.2-Lightning
- `wan2.2_i2v_lightning_4steps_low_noise_v1.1.safetensors` — там же

## 6. SeedVR2 7B (апскейл видео) — ~7 GB

**seedvr2/** (создать) или **diffusion_models/**:
- `seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors` — https://huggingface.co/numz/SeedVR2_comfyUI

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

В workflow стоит имя `rife47.pth`. Если у тебя подтянулась другая версия (rife49, rife_v4.25) — поправь в `config.py` поле `RifeSettings.model`.

## 9. F5-TTS + русский файнтюн (голос) — ~2 GB

**Установка F5-TTS (в отдельную папку, не в ComfyUI):**
```powershell
git clone https://github.com/SWivid/F5-TTS C:\F5-TTS
cd C:\F5-TTS
pip install -e .
pip install ruaccent
```

Путь `C:\F5-TTS` должен совпадать с `F5_TTS_ROOT` в `config.py`.

**Русский файнтюн Misha24-10 (качай через `huggingface-cli`):**
```powershell
huggingface-cli download Misha24-10/F5-TTS_RUSSIAN ^
  F5TTS_v1_Base_v2/model_last.safetensors vocab.txt ^
  --local-dir C:\F5-TTS\ckpts
```

Переименуй `model_last.safetensors` → `F5TTS_v1_Base_v2.safetensors` (или поправь путь в `config.py` → `F5Settings.ckpt_path`).

**Доступные варианты от Misha24-10:**
- `F5TTS_v1_Base` — базовый русский
- `F5TTS_v1_Base_v2` — улучшенный (рекомендуется)
- `F5TTS_v1_Base_accent_tune` — с акцентом на правильные ударения

**Референсный голос** — запиши сам 3-10 секунд чистого голоса (без музыки, без эха) в WAV 24kHz mono. Запиши ТОЧНУЮ транскрипцию того, что там сказано, — F5-TTS без транскрипции не работает.

## 10. RVC (опциональная шлифовка голоса) — ~1 GB

**Установка (форк Mangio рекомендуется):**
```powershell
git clone https://github.com/Mangio621/Mangio-RVC-Fork C:\RVC
cd C:\RVC
pip install -r requirements.txt
```

Путь `C:\RVC` должен совпадать с `RVC_ROOT` в `config.py`.

**Обучение своего голоса:** залей 10-30 минут чистой речи, запусти `go-web.bat` → вкладка Train → дождись 150-300 эпох. На 4070S это 1-3 часа.

После обучения пропиши в `config.py`:
```python
RVCSettings.model_pth = Path(r"C:\RVC\weights\my_voice.pth")
RVCSettings.index_file = Path(r"C:\RVC\logs\my_voice\added_*.index")
```

## 11. Flux Kontext Dev (edit-based персонаж) — ~8 GB

**unet/**:
- `flux1-kontext-dev-Q5_K_M.gguf` — https://huggingface.co/city96/FLUX.1-Kontext-dev-gguf

Использует тот же `clip_l.safetensors`, `t5xxl_fp8_e4m3fn.safetensors` и `ae.safetensors` что и Flux.1-dev — ничего дополнительно качать не нужно.

В ComfyUI нужны ноды `FluxKontextImageScale` и `ReferenceLatent` — они появились в ядре с августа 2025. Если их нет — обнови ComfyUI до последней версии.

## 12. FluxGym (тренировка LoRA своего персонажа)

**Установка (в отдельную папку, не в ComfyUI):**
```powershell
git clone https://github.com/cocktailpeanut/fluxgym C:\fluxgym
cd C:\fluxgym
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
cd sd-scripts
pip install -r requirements.txt
cd ..
```

Путь `C:\fluxgym` должен совпадать с `FLUXGYM_ROOT` в `config.py`.

FluxGym подтянет базовые модели Flux-dev сам при первом запуске тренировки (~24 GB загрузки).

**Workflow:**
1. `python main.py lora-dataset --ref my_char.png --name anna_v1` — сгенерирует 30 вариаций в `output/lora_datasets/anna_v1/`
2. Отсмотри папку — удали все плохие кадры (кривые лица, артефакты)
3. Запусти FluxGym: `cd C:\fluxgym && env\Scripts\activate && python app.py`
4. Загрузи отобранные фото через Gradio UI, настрой параметры по инструкции в консоли
5. 3-5 часов тренировки на 4070S
6. Итог → скопируй `.safetensors` в `ComfyUI\models\loras\`

---

# Custom nodes (ставить через ComfyUI-Manager)

1. **ComfyUI-GGUF** (city96) — загрузка GGUF моделей
2. **ComfyUI-PuLID-Flux-Enhanced** (sipie800) — PuLID-Flux II
3. **ComfyUI-WanVideoWrapper** (kijai) — Wan 2.2 с block_swap
4. **ComfyUI-SeedVR2_VideoUpscaler** (numz) — SeedVR2
5. **ComfyUI-VideoHelperSuite** (Kosinkadink) — загрузка/сохранение видео
6. **ComfyUI-Impact-Pack** (ltdrdata) — FaceDetailer
7. **ComfyUI-TeaCache** (welltop-cn) — ускорение
8. **ComfyUI-KJNodes** (kijai) — утилиты
9. **rgthree-comfy** — улучшения интерфейса
10. **ComfyUI-LatentSyncWrapper** (ShmuelRonen) — lip sync
11. **ComfyUI-Frame-Interpolation** (Fannovel16) — RIFE для fps

# Установка SageAttention 2.2 (Windows + CUDA 12.8)

В папке ComfyUI portable:
```
python_embeded\python.exe -m pip install -U triton-windows
python_embeded\python.exe -m pip install https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/sageattention-2.2.0+cu128torch2.7.1-cp312-cp312-win_amd64.whl
```

Проверь версию cp311/cp312 под свой Python в python_embeded.

Запуск ComfyUI:
```
python main.py --use-sage-attention --fast --reserve-vram 0.5
```
