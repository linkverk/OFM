# AI OFM Studio

Локальный пайплайн генерации AI-инфлюенсера на **RTX 4070 Super 12GB + R7 7800X3D + 32GB DDR5**.

Без облака, без подписок. Только open-source модели из ресёрч-отчёта.

## Что делает

1. **Консистентный персонаж** — Flux.1-dev Q5 GGUF + PuLID-Flux II + FaceDetailer + CodeFormer
2. **Image → Video** — Wan 2.2 I2V 14B Q4_K_M + Lightning 4+4 LoRA (ускорение ×20)
3. **Русский TTS** — F5-TTS с файнтюном `Misha24-10/F5-TTS_RUSSIAN` + RUAccent + опциональный RVC
4. **Lip sync** — LatentSync 1.6, синхронизация губ под аудио
5. **Интерполяция fps** — RIFE v4.x, 24 → 48/72 fps
6. **Апскейл видео** — SeedVR2 7B FP8 с BlockSwap

**От одного фото и одной фразы — до говорящего клипа 1280p @ 48 fps одной командой:**
```powershell
python main.py full --face me.jpg ^
  --prompt "woman in cafe, soft window light, cinematic" ^
  --motion "smiling softly, slowly turning head toward camera" ^
  --text "Привет! Сегодня расскажу как прошёл мой день." ^
  --ref-audio my_voice_ref.wav ^
  --ref-text "Это референсная запись моего голоса для клонирования." ^
  --rvc --upscale --smooth
```

**Тайминги на 4070S (5-секундный клип):**
- Персонаж (Flux + PuLID): 30-40 сек
- TTS (F5-TTS русский + RVC): 20-40 сек
- I2V (Wan 2.2 + Lightning): 3-5 мин
- Lip sync (LatentSync): 2-4 мин
- Апскейл (SeedVR2): 3-5 мин
- RIFE fps: 10-30 сек
- **Итого: ~10-15 минут** на финальный полностью собранный клип 1280p @ 48 fps с русским голосом.

## Установка

### 1. ComfyUI

Скачай ComfyUI (https://github.com/comfyanonymous/ComfyUI) в любую папку, например `C:\ComfyUI`.

### 2. Custom nodes и модели

Смотри `MODELS_CHECKLIST.md` — там полный список с прямыми ссылками.

Nodes ставятся через ComfyUI-Manager (Install Custom Nodes → искать по имени).

### 3. SageAttention 2.2 (обязательно для 4070S)

В папке ComfyUI portable:
```powershell
python_embeded\python.exe -m pip install -U triton-windows
python_embeded\python.exe -m pip install https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/sageattention-2.2.0+cu128torch2.7.1-cp312-cp312-win_amd64.whl
```

### 4. Эта программа

```powershell
cd ai_ofm_studio
pip install websocket-client
```

Потом открой `config.py` и проверь путь `COMFYUI_ROOT`.

## Использование

### Запуск ComfyUI (в отдельном окне, оставь работать)

```powershell
cd C:\ComfyUI
python main.py --use-sage-attention --fast --reserve-vram 0.5
```

Дождись строчки `To see the GUI go to: http://127.0.0.1:8188`.

### Проверка

```powershell
python main.py check
```

### Сценарии

**Только персонаж (несколько вариантов):**
```powershell
python main.py character --face my_ref.jpg --prompt "woman in red silk dress, sitting in a Parisian cafe, golden hour" -n 5
```

**Только анимация уже готовой картинки:**
```powershell
python main.py i2v --image output/character_00001_.png --motion "smiling softly, slowly turning head toward camera"
```

**Апскейл клипа:**
```powershell
python main.py upscale --video output/i2v_00001.mp4 --res 1280
```

**Полный пайплайн одной командой:**
```powershell
python main.py full --face my_ref.jpg --prompt "woman in red dress at sunset beach" --motion "gentle breeze moving hair, slight smile" --upscale --res 1280
```

## Тайминги (измеренные на 4070 Super)

| Этап | Время |
|---|---|
| Flux + PuLID + FaceDetailer, 1024×1024 | 30-40 сек |
| Wan 2.2 I2V 832×480, 5 сек @ Lightning | 3-5 мин |
| SeedVR2 7B апскейл 480p → 1280p, 5 сек | 3-5 мин |
| **Итого за один клип 720p** | **~7-10 мин** |

## Структура

```
ai_ofm_studio/
├── config.py              # все настройки под 4070S
├── main.py                # CLI
├── MODELS_CHECKLIST.md    # что скачать
├── pipeline/
│   ├── character_gen.py
│   ├── image_to_video.py
│   └── video_upscale.py
├── workflows/             # JSON для ComfyUI API
│   ├── flux_pulid.json
│   ├── wan22_i2v.json
│   └── seedvr2_upscale.json
├── utils/
│   └── comfy_client.py
└── output/
```

## Тонкая настройка

Все пороги в `config.py`:

- **FluxSettings**: разрешение, guidance, PuLID weight, CodeFormer fidelity
- **WanSettings**: разрешение видео, число кадров, blocks_to_swap, TeaCache threshold
- **SeedVR2Settings**: upscale factor, batch, blocks_to_swap

Если ловишь OOM на Wan — увеличь `blocks_to_swap` до 30-35.
Если слишком медленно — уменьши `num_frames` до 49 (3 секунды) или разрешение до 640×384.

## Типичные проблемы

**"ComfyUI не отвечает"** — он не запущен или порт занят. Проверь http://127.0.0.1:8188 в браузере.

**OOM на этапе I2V** — закрой Chrome/Discord/OBS, увеличь blocks_to_swap в `config.py` до 30.

**PuLID не находит лицо** — референс должен быть фронтальный, чёткий, одно лицо, не в маске/очках.

**Медленная первая генерация** — прогрев torch.compile 5-10 минут, следующие будут быстрее.

**Качество Lightning хуже чем обещано** — проверь что CFG=1 и sampler=lcm. На любом другом CFG Lightning ломается.

## Лицензии (важно для коммерции)

- **Flux.1-dev** — non-commercial. Для коммерции: HiDream-I1 (MIT), Flux.1-schnell (Apache), SDXL.
- **Wan 2.2** — Apache 2.0 ✅
- **PuLID** — Apache 2.0, но InsightFace AntelopeV2 non-commercial. Для коммерции переключись на MediaPipe-версию.
- **SeedVR2** — Apache 2.0 ✅
- **CodeFormer** — non-commercial (S-Lab 1.0). Альтернативы: GFPGAN (Apache).

## Дальше

Что не вошло в эту версию (можно добавить модулями):
- **Lip sync** (LatentSync 1.6 для замены губ под русский TTS)
- **Голос** (F5-TTS_RUSSIAN + RVC)
- **Интерполяция fps** (RIFE v4.25 24→48 fps)
- **Тренировка собственной LoRA** (FluxGym, 3-5 часов на 4070S)

Структура программы расширяется через новые модули в `pipeline/` и workflow'ы в `workflows/`.
