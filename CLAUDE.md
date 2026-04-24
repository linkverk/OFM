# CLAUDE.md

Инструкция для Claude и других AI-ассистентов, работающих с этим репозиторием.

## Что это

**AI OFM Studio** — локальный пайплайн для создания AI-инфлюенсера на одной RTX 4070 Super 12GB. Полностью open-source, без облачных API. Управляет ComfyUI через REST+WebSocket API, запускает F5-TTS и RVC через subprocess.

**Целевая конфигурация** (зашита в `config.py`):
- GPU: NVIDIA RTX 4070 Super **12 GB VRAM** (Ada Lovelace, sm89)
- CPU: AMD Ryzen 7 7800X3D
- RAM: 32 GB DDR5
- OS: Windows 11
- Базовая папка (по умолчанию): `D:\GitHub\ai-ofm\`

Если пользователь работает на другой конфигурации — первым делом проверь `config.py` и предложи скорректировать пути и параметры `blocks_to_swap`/квантизации.

## Архитектура — важно

Программа **не запускает модели сама**. Она — клиент. Тяжёлая работа делегирована:

1. **ComfyUI** (должен быть запущен отдельно на `http://127.0.0.1:8188`) — всё, что касается диффузии: Flux, Flux Kontext, Wan 2.2, SeedVR2, LatentSync, RIFE. Связь через `utils/comfy_client.py` (REST + WebSocket).
2. **F5-TTS** (отдельная установка в `D:\GitHub\ai-ofm\F5-TTS`) — русский TTS. Запуск через `subprocess.run`, не через импорт.
3. **RVC** (отдельная установка в `D:\GitHub\ai-ofm\RVC`) — voice conversion. Тоже subprocess.
4. **FluxGym** (отдельная установка в `D:\GitHub\ai-ofm\fluxgym`) — тренировка LoRA. Мы только готовим датасет, тренировку пользователь запускает сам в Gradio UI FluxGym.

**Почему subprocess, а не импорт для TTS/RVC:** F5-TTS и RVC агрессивно грузят CUDA при импорте, что конфликтует с уже запущенным ComfyUI за VRAM. Subprocess даёт чистое окружение и позволяет ComfyUI выгрузить модели (`client.free_memory`) до запуска TTS.

## Структура проекта

```
ai_ofm_studio/
├── config.py                   # ВСЕ настройки, пути, квантизации
├── main.py                     # CLI (13 команд)
├── webui.py                    # Gradio веб-интерфейс на порту 7861
├── install.ps1                 # Windows установщик (ComfyUI + F5-TTS + RVC + FluxGym + venv)
├── download_models.py          # скачивание ~55 GB моделей с HuggingFace
├── requirements.txt
├── README.md                   # инструкция для пользователя
├── MODELS_CHECKLIST.md         # что скачать и куда положить (справка)
├── CLAUDE.md                   # этот файл
├── pipeline/                   # функциональные модули
│   ├── character_gen.py        # Flux + PuLID (identity injection)
│   ├── character_edit.py       # Flux Kontext (edit-based)
│   ├── image_to_video.py       # Wan 2.2 I2V + Lightning LoRA
│   ├── video_upscale.py        # SeedVR2
│   ├── lip_sync.py             # LatentSync 1.6
│   ├── fps_interpolate.py      # RIFE v4.x
│   ├── tts_voice.py            # F5-TTS русский (subprocess)
│   ├── voice_convert.py        # RVC (subprocess)
│   ├── lora_training.py        # подготовка датасета для FluxGym
│   └── batch_runner.py         # массовая генерация по CSV
├── workflows/                  # JSON-графы ComfyUI API-формата
│   ├── flux_pulid.json
│   ├── flux_kontext.json
│   ├── wan22_i2v.json
│   ├── latentsync.json
│   ├── rife_interpolation.json
│   └── seedvr2_upscale.json
├── utils/
│   ├── comfy_client.py         # HTTP+WS клиент к ComfyUI
│   └── workflow.py             # load_workflow + fill_placeholders
└── output/                     # результаты генерации
```

## Рабочий процесс установки

Когда пользователь ставит проект с нуля, последовательность такая:

1. `install.ps1` — клонирует ComfyUI + custom_nodes, F5-TTS, RVC, FluxGym. Создаёт для каждого отдельный venv и ставит зависимости включая SageAttention 2.2.
2. `download_models.py --comfyui <путь> --f5tts <путь>` — тянет ~55 GB моделей. Устойчив к ошибкам: провал одной модели не останавливает остальные, в конце печатается сводка.
3. Правка `config.py` — проверить пути к `COMFYUI_ROOT`, `F5_TTS_ROOT`, `RVC_ROOT`, `FLUXGYM_ROOT`.
4. Запуск ComfyUI в отдельном окне: `cd <comfyui> && venv\Scripts\activate && python main.py --use-sage-attention --fast --reserve-vram 0.5`
5. `python webui.py` или `python main.py <cmd>`.

При проблемах с установкой моделей — первым делом сверять с `download_models.py`, не с `MODELS_CHECKLIST.md` (последний может отставать, первый — живой код с актуальными URL).

## Как работают workflow'ы

Каждый JSON в `workflows/` — это граф нод ComfyUI в API-формате с плейсхолдерами `{{KEY}}` в строковых полях. Модули pipeline/ загружают JSON через `utils.workflow.load_workflow`, подставляют реальные значения через `fill_placeholders`, отправляют через `ComfyClient.run_workflow`.

**Ключи начинающиеся с `_`** (например `_comment`, `_note`, `_uses`) — это служебные комментарии, которые `load_workflow` автоматически удаляет. Ноды ComfyUI имеют числовые строковые ключи (`"1"`, `"2"`, ...).

Пример жизненного цикла:
```
main.py cmd_character → pipeline/character_gen.py generate_character
  → utils/workflow.load_workflow('flux_pulid.json')
  → fill_placeholders(wf, {"FLUX_UNET": "flux1-dev-Q5_K_S.gguf", ...})
  → ComfyClient.run_workflow(wf)
    → POST /prompt → websocket ws://.../ws → GET /history/{id}
    → GET /view?filename=... → сохраняет в output/
```

## Типичные задачи и где искать

| Задача | Файл |
|---|---|
| Поменять разрешение/шаги Flux | `config.py` → `FluxSettings` |
| Поменять разрешение/длину видео Wan | `config.py` → `WanSettings` |
| Добавить новый этап в pipeline | новый файл в `pipeline/`, новый JSON в `workflows/`, импорт в `main.py`, вкладка в `webui.py` |
| Добавить новую модель в авто-скачивание | `download_models.py` — паттерн `_try(failures, "label", download, repo, file, dest)` |
| OOM на Wan 2.2 | `WanSettings.blocks_to_swap` поднять до 30-35 |
| Ошибка «нода не найдена» | имя ноды в JSON workflow не совпадает с установленным custom_node — обновить JSON |
| Flags запуска ComfyUI | `config.py` → `COMFYUI_LAUNCH_FLAGS` (для документации, не используется программой) |

## Правила при изменении проекта

### Когда добавляешь новую модель/этап

1. Сначала **новый JSON workflow** в `workflows/` — полностью с `_comment` в начале, описывающим что это, какие custom_nodes нужны, какие плейсхолдеры
2. **Константы имён моделей** и класс настроек в `config.py`
3. **Модуль** в `pipeline/` по шаблону существующих: implements одну публичную функцию, использует `load_workflow` и `fill_placeholders` из `utils/workflow`, принимает опциональный `ComfyClient`
4. **Команда** в `main.py` — `cmd_xxx` функция + парсер в `build_parser` + регистрация в `handlers`
5. **Вкладка** в `webui.py` — через `_safe` декоратор, возвращает `(результат, статус_текст)`
6. **Скачивание** — добавить в `download_models.py` через `_try(failures, ..., download, ...)` с `fallback_patterns` для устойчивости к переименованиям
7. **Установка** — если нужен новый внешний репо или custom_node, добавить в `install.ps1`

### Когда правишь существующее

- **Не ломай API модулей pipeline/** — на них завязан `webui.py` и `batch_runner.py`. Если расширяешь — добавляй опциональные kwargs с дефолтами.
- **Не хардкодь пути** — всё через константы в `config.py`
- **Пути плейсхолдеров в JSON — строгий шаблон** `"{{KEY}}"` без пробелов, `load_workflow` их матчит literal'ом
- **Синхронизируй три источника** при переименовании моделей: `config.py` (константа имени), `download_models.py` (rename_to), `MODELS_CHECKLIST.md` (справка для пользователя). Если хоть в одном не поправить — либо не скачается, либо workflow не найдёт файл.

### Память и VRAM

Критично: перед тяжёлой моделью вызывай `client.free_memory(unload_models=True, free_memory=True)`. Это особенно важно между Flux → Wan 2.2 → SeedVR2 в `cmd_full`. Без этого второй этап ловит OOM.

## Известные проблемы в текущем коде

На момент последней ревизии:

- **SeedVR2 — рассинхрон имени файла.** В `config.py` константа `SEEDVR2_MODEL = "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors"`, но на HF в `numz/SeedVR2_comfyUI` реальный файл называется `seedvr2_ema_7b_fp8_e4m3fn.safetensors`, и именно его качает `download_models.py`. Workflow будет падать с «model not found». Фикс: либо поправить константу под реальное имя, либо переименовать файл после скачивания.
- **`config.py` — Flux GGUF.** Константа `FLUX_UNET_GGUF = "flux1-dev-Q5_K_M.gguf"`, но у city96 для **dev** есть только Q5_K_S (Q5_K_M — только для schnell). `download_models.py` качает Q5_K_S. Нужно либо поправить константу на `"flux1-dev-Q5_K_S.gguf"`, либо переименовать скачанный файл.

При работе с проектом — если пользователь жалуется на «model not found» в Flux или SeedVR2 workflow'ах — первым делом проверять синхронизацию этих имён.

## Лицензионные нюансы (важно для пользователя)

В проекте используются модели с разными лицензиями. Non-commercial:
- **Flux.1-dev**, **Flux Kontext Dev** — только research/personal
- **PuLID + InsightFace AntelopeV2** (зависимость)
- **CodeFormer**
- **F5-TTS_RUSSIAN** (Misha24-10 файнтюн)

Остальное (Wan 2.2, SeedVR2, LatentSync, RIFE, RVC, F5-TTS сам код) — Apache/MIT.

Если пользователь спрашивает про коммерческое использование — направляй его к альтернативам:
- Flux-dev → **HiDream-I1** (MIT) / **SDXL** / **Flux-schnell**
- PuLID → **IP-Adapter FaceID Plus V2** + MediaPipe detector
- CodeFormer → **GFPGAN**
- F5-TTS русский → **CosyVoice 3** или **Chatterbox Multilingual**

## Как общаться с пользователем

Пользователь — владелец проекта, работает с RTX 4070 Super / 32 GB DDR5. Русскоговорящий, язык инструкций и комментариев — **русский**, имена переменных и строк логов — **английский**. Смешение такое: docstrings модулей на русском, `print()` — префикс на английском + основное сообщение на русском (например `[tts] готово: ...`).

**Стиль ответов:**
- Прямо и по делу, без воды
- Если пользователь просит фичу — сначала 3-5 строк плана, потом код
- Таблицы с трейдоффами когда есть выбор
- Честно признавай ограничения: «эта модель не влезет в 12 GB», «тренировка требует 24 GB», и т.д.

**Что пользователь уже понял** (из прошлых диалогов — упрощает твою задачу):
- ComfyUI ставится отдельно, это не часть программы
- Разница между CLI, webui.py и batch режимами
- Зачем нужны квантизации и block_swap на 12 GB
- Что Flux non-commercial но для личного контента ок

**Что может спутать:**
- Форматы workflow у Kijai WanVideoWrapper меняются между версиями — имена инпутов нод могут расходиться с моим JSON. При ошибке «unknown input» — предложи открыть актуальный example_workflow из `ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper/example_workflows/` и сравнить.
- Пути в config.py заточены под Windows (`D:\...`) — на Linux/macOS надо менять.

## Что НЕ делать

- **Не пиши workflow'ы с нуля** без необходимости. Если нужен новый — сначала найди свежий пример в репо custom_node (Kijai, city96, numz) и адаптируй его, чтобы не угадывать имена инпутов.
- **Не превращай subprocess вызовы в импорты.** F5-TTS и RVC должны оставаться в отдельных процессах ради чистого CUDA-контекста.
- **Не добавляй зависимость на облачные API** (OpenAI, Anthropic API, ElevenLabs и т.п.). Проект — полностью локальный и это его главная ценность.
- **Не ломай совместимость с 12 GB VRAM.** Любая новая модель должна иметь путь через GGUF/FP8/block_swap/CPU offload, иначе она не подходит.
- **Не пиши тесты с реальной генерацией.** Это часы времени GPU. Юнит-тесты — только на утилитах (`fill_placeholders`, парсинг CSV, и т.п.).

## Полезные команды для разработчика

```powershell
# Проверка синтаксиса всех файлов
python -c "import ast, json; from pathlib import Path; [ast.parse(open(f).read()) for f in Path('.').rglob('*.py')]; [json.load(open(f)) for f in Path('workflows').glob('*.json')]"

# Быстрая проверка что CLI собирается
python main.py --help

# Тест одного этапа без полного прогона
python main.py check
python main.py character --face test.jpg --prompt "test" -n 1

# Диагностика: показать файлы в HF-репо (для download_models.py)
python download_models.py --list city96/FLUX.1-dev-gguf
```

## История версий

- **v1** — базовый пайплайн: Flux+PuLID, Wan 2.2, SeedVR2
- **v2** — добавлены LatentSync (lip sync) и RIFE (fps)
- **v3** — F5-TTS русский + RVC (голос)
- **v4** — Flux Kontext, FluxGym dataset prep, batch runner, Gradio UI
- **v5** — `install.ps1` и `download_models.py` для автоматической установки (текущая)

## Если что-то сломалось

Первые шаги диагностики:
1. `python main.py check` — ComfyUI жив?
2. Открыть http://127.0.0.1:8188 — UI ComfyUI открывается?
3. Посмотреть консоль ComfyUI на предмет OOM или missing node
4. Сравнить имена моделей в `config.py` с реально лежащими в `ComfyUI/models/` (см. «Известные проблемы» выше)
5. Для Wan/SeedVR2: актуальность custom_nodes — возможно Kijai переименовал ноды в новой версии

Типичные ошибки и их фиксы — в `README.md` в разделе «Типичные проблемы».