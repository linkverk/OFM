# AI OFM Studio

Локальный пайплайн генерации AI-инфлюенсера на **RTX 4070 Super 12GB + R7 7800X3D + 32GB DDR5**.

Без облака, без подписок. Только open-source модели.

## Что делает

1. **Консистентный персонаж** — Flux.1-dev Q5 GGUF + PuLID-Flux II + FaceDetailer + CodeFormer
2. **Character edit** — Flux Kontext Dev, вариации эталонного кадра без тренировки LoRA
3. **Image → Video** — Wan 2.2 I2V 14B Q4_K_M + Lightning 4+4 LoRA (ускорение ×20)
4. **Русский TTS** — F5-TTS с файнтюном `Misha24-10/F5-TTS_RUSSIAN` + RUAccent + опциональный RVC
5. **Lip sync** — LatentSync 1.6, синхронизация губ под аудио
6. **Интерполяция fps** — RIFE v4.x, 24 → 48/72 fps
7. **Апскейл видео** — SeedVR2 7B FP8 с BlockSwap
8. **LoRA dataset prep** — сборка датасета из 30 вариаций для последующей тренировки в FluxGym
9. **Batch** — массовая генерация по CSV

**От одного фото и одной фразы — до говорящего клипа 1280p @ 48 fps одной командой:**
```powershell
python main.py full --face me.jpg `
  --prompt "woman in cafe, soft window light, cinematic" `
  --motion "smiling softly, slowly turning head toward camera" `
  --text "Привет! Сегодня расскажу как прошёл мой день." `
  --ref-audio my_voice_ref.wav `
  --ref-text "Это референсная запись моего голоса для клонирования." `
  --rvc --upscale --smooth
```

**Тайминги на 4070S (5-секундный клип):**

| Этап | Время |
|---|---|
| Персонаж (Flux + PuLID + FaceDetailer), 1024×1024 | 30–40 сек |
| TTS (F5-TTS рус) + опц. RVC | 20–40 сек |
| I2V (Wan 2.2 + Lightning), 832×480, 81 кадр | 3–5 мин |
| Lip sync (LatentSync 1.6) | 2–4 мин |
| Апскейл (SeedVR2 7B) → 1280p | 3–5 мин |
| RIFE fps ×2 | 10–30 сек |
| **Итого** | **~10–15 мин** |

## Установка

### Быстрый путь — `install.ps1`

Всё автоматически в одной корневой папке (дефолт: `D:\GitHub\OFM\ai-ofm`):

```powershell
# Из папки с проектом
.\install.ps1
```

Что делает:
- создаёт venv для нашей программы и ставит `requirements.txt`
- клонирует и настраивает **ComfyUI** + все нужные custom_nodes
- ставит **SageAttention 2.2** под твою версию Python
- клонирует **F5-TTS**, **RVC (Mangio fork)**, **FluxGym** в отдельные venv'ы

Флаги для пропуска частей: `-SkipComfyUI`, `-SkipF5TTS`, `-SkipRVC`, `-SkipFluxGym`, `-SkipSageAttention`.
Другой путь установки: `.\install.ps1 -BasePath D:\AI`.

Скрипт **не качает ML-модели** (~60 GB) — для этого отдельный шаг ниже.

### Скачивание моделей

```powershell
venv\Scripts\activate
pip install huggingface_hub
python download_models.py --comfyui D:\GitHub\OFM\ai-ofm\ComfyUI --f5tts D:\GitHub\OFM\ai-ofm\F5-TTS
```

Скрипт устойчив к сбоям — если какая-то модель не скачалась, в конце выведется сводка, остальные продолжат качаться. Флаги пропуска категорий:
`--skip-flux`, `--skip-kontext`, `--skip-wan`, `--skip-seedvr2`, `--skip-f5tts`, `--skip-face-restore`.

Полный список моделей с объёмами и ссылками — в `MODELS_CHECKLIST.md`.

### Ручная установка

Если хочется контроля — `MODELS_CHECKLIST.md` содержит прямые ссылки, пути и инструкции по шагам. Для custom_nodes, Python-окружений и SageAttention — читать `install.ps1` как документацию.

### Проверь пути в `config.py`

После установки открой `config.py` и убедись, что эти константы указывают на реальные папки:

```python
COMFYUI_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\ComfyUI")
F5_TTS_ROOT  = Path(r"D:\GitHub\OFM\ai-ofm\F5-TTS")
RVC_ROOT     = Path(r"D:\GitHub\OFM\ai-ofm\RVC")
FLUXGYM_ROOT = Path(r"D:\GitHub\OFM\ai-ofm\fluxgym")
```

## Использование

### 1. Запусти ComfyUI (в отдельном окне, оставь работать)

```powershell
cd D:\GitHub\OFM\ai-ofm\ComfyUI
venv\Scripts\activate
python main.py --use-sage-attention --fast --reserve-vram 0.5
```

Дождись строчки `To see the GUI go to: http://127.0.0.1:8188`.

### 2. Проверка связи

```powershell
cd <папка с проектом>
venv\Scripts\activate
python main.py check
```

### 3. Web UI или CLI

**Web UI (Gradio):**
```powershell
python webui.py
```
Откроется на http://127.0.0.1:7861. Там есть вкладки на все команды — удобно для экспериментов.

**CLI — примеры:**

Только персонаж, 5 вариантов:
```powershell
python main.py character --face my_ref.jpg --prompt "woman in red silk dress, Parisian cafe, golden hour" -n 5
```

Kontext edit (вариации на основе эталона):
```powershell
python main.py kontext --ref output/character_00001_.png --prompt "same person, white sundress, beach at sunset" -n 3
```

Только i2v:
```powershell
python main.py i2v --image output/character_00001_.png --motion "smiling softly, slowly turning head toward camera"
```

Lip sync готового клипа под готовое аудио:
```powershell
python main.py lipsync --video clip.mp4 --audio voice.wav
```

Русский TTS:
```powershell
python main.py tts --text "Привет, как дела?" --ref-audio ref.wav --ref-text "Это референс голоса."
```

Апскейл до 1280p:
```powershell
python main.py upscale --video output/i2v_00001.mp4 --res 1280
```

Удвоить fps (24 → 48):
```powershell
python main.py rife --video output/clip.mp4
```

Полный пайплайн одной командой:
```powershell
python main.py full --face my_ref.jpg `
  --prompt "woman in red dress at sunset beach" `
  --motion "gentle breeze moving hair, slight smile" `
  --text "Какой красивый закат!" `
  --ref-audio voice.wav --ref-text "Это референс." `
  --rvc --upscale --smooth
```

Собрать датасет для LoRA (30 вариаций через Kontext + инструкции для FluxGym):
```powershell
python main.py lora-dataset --ref my_ref.png --name anna_v1 -n 30
```

Массовая генерация по CSV:
```powershell
python main.py batch-template --out my_batch.csv   # получить шаблон
# отредактировать my_batch.csv
python main.py batch --csv my_batch.csv
```

## Структура проекта

```
ai_ofm_studio/
├── config.py              # все настройки под 4070S
├── main.py                # CLI (13 команд)
├── webui.py               # Gradio веб-интерфейс (порт 7861)
├── install.ps1            # установщик для Windows
├── download_models.py     # скачивание моделей с HF
├── requirements.txt
├── README.md
├── MODELS_CHECKLIST.md
├── CLAUDE.md              # инструкция для AI-ассистентов
├── pipeline/
│   ├── character_gen.py
│   ├── character_edit.py
│   ├── image_to_video.py
│   ├── lip_sync.py
│   ├── fps_interpolate.py
│   ├── video_upscale.py
│   ├── tts_voice.py
│   ├── voice_convert.py
│   ├── lora_training.py
│   └── batch_runner.py
├── workflows/             # JSON для ComfyUI API
│   ├── flux_pulid.json
│   ├── flux_kontext.json
│   ├── wan22_i2v.json
│   ├── latentsync.json
│   ├── rife_interpolation.json
│   └── seedvr2_upscale.json
├── utils/
│   ├── comfy_client.py
│   └── workflow.py
└── output/
```

## Тонкая настройка

Все пороги в `config.py`:

- **FluxSettings** — разрешение, guidance, PuLID weight, CodeFormer fidelity
- **FluxKontextSettings** — для edit-based генерации
- **WanSettings** — разрешение видео, число кадров, blocks_to_swap, TeaCache threshold
- **SeedVR2Settings** — upscale factor, batch, blocks_to_swap
- **LatentSyncSettings** — inference_steps, lips_expression
- **RifeSettings** — multiplier, output_fps
- **F5Settings** — модель, ckpt, скорость, NFE, cross-fade
- **RVCSettings** — модель, pitch, f0_method, index_rate

Если ловишь OOM на Wan — увеличь `blocks_to_swap` до 30-35.
Если слишком медленно — уменьши `num_frames` до 49 (3 секунды) или разрешение до 640×384.

## Типичные проблемы

**"ComfyUI не отвечает"** — он не запущен или порт занят. Проверь http://127.0.0.1:8188 в браузере.

**OOM на этапе I2V** — закрой Chrome/Discord/OBS, увеличь `WanSettings.blocks_to_swap` до 30.

**PuLID не находит лицо** — референс должен быть фронтальный, чёткий, одно лицо, не в маске/очках.

**Медленная первая генерация** — прогрев torch.compile 5-10 минут, следующие быстрее.

**Качество Lightning хуже обычного** — проверь, что `cfg=1` и `sampler=lcm`. На любом другом CFG Lightning ломается.

**"Unknown input" в ноде Wan** — Kijai периодически переименовывает инпуты в WanVideoWrapper. Открой свежий пример из `ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper/example_workflows/` и сравни с `workflows/wan22_i2v.json`.

**RIFE чекпойнт с другим именем** — в workflow прописан `rife47.pth`. Если у тебя подтянулось `rife49.pth` / `rife_v4.25.pth` — поправь `RifeSettings.model` в `config.py`.

**F5-TTS падает на длинном тексте** — режь на предложения вручную или уменьши `nfe_step` до 24.

## Лицензии (важно для коммерции)

| Компонент | Лицензия | Коммерция |
|---|---|---|
| Flux.1-dev | FLUX.1 [dev] Non-Commercial | ❌ (альтернатива: HiDream-I1 MIT, SDXL, Flux-schnell) |
| Flux Kontext Dev | FLUX.1 [dev] Non-Commercial | ❌ |
| Wan 2.2 | Apache 2.0 | ✅ |
| PuLID-Flux | Apache 2.0 | ✅, но ⚠️ InsightFace AntelopeV2 — non-commercial (альтернатива: MediaPipe) |
| SeedVR2 | Apache 2.0 | ✅ |
| LatentSync 1.6 | Apache 2.0 | ✅ |
| RIFE | MIT | ✅ |
| F5-TTS (код) | MIT | ✅ |
| F5-TTS_RUSSIAN (Misha24-10 ckpt) | Non-Commercial | ❌ (альтернатива: CosyVoice 3, Chatterbox Multilingual) |
| RVC | MIT | ✅ |
| CodeFormer | S-Lab 1.0 Non-Commercial | ❌ (альтернатива: GFPGAN Apache) |

Для личного/исследовательского контента — всё в порядке. Для коммерции нужно заменить компоненты помеченные ❌.

## Что дальше

Расширение программы — через новые модули в `pipeline/` и workflow'ы в `workflows/`. Подробно в `CLAUDE.md`.