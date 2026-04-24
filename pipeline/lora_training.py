"""
Подготовка датасета для тренировки LoRA через FluxGym.

Workflow:
  1. Берём эталонный кадр персонажа (одобренный)
  2. Через Kontext генерируем 30-50 вариаций (разные позы/сцены/одежда/ракурсы)
  3. Пользователь отбирает лучшие ~20-30 вручную (копирует в финальную папку)
  4. Каждое фото прогоняется через FaceDetailer для чистки лица
  5. Запускается FluxGym тренировка

Ограничение: собственно тренировка LoRA идёт через FluxGym WebUI,
эта программа только готовит датасет и печатает команду для запуска FluxGym.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from config import (
    FLUXGYM_ROOT,
    FluxGymSettings,
    OUTPUT_DIR,
)
from utils.comfy_client import ComfyClient
from pipeline.character_edit import edit_character


# Разнообразные edit-промпты для датасета.
# Задача: покрыть разные ракурсы, выражения, сцены, одежду, освещение.
DEFAULT_EDIT_PROMPTS = [
    # Ракурсы лица
    "same person, head turned slightly left, looking at camera",
    "same person, three-quarter profile view, looking away",
    "same person, front view, neutral expression",
    "same person, slight low angle shot",
    "same person, upper body shot, full face visible",
    # Выражения
    "same person, warm genuine smile, showing teeth slightly",
    "same person, soft subtle smile, closed mouth",
    "same person, thoughtful expression, looking down",
    "same person, laughing naturally, eyes crinkled",
    "same person, serious confident expression",
    # Освещение
    "same person, golden hour natural light, warm tones",
    "same person, soft window light, indoor",
    "same person, cinematic moody lighting",
    "same person, bright outdoor daylight",
    "same person, evening soft lamp light",
    # Сцены/одежда (важно для LoRA — должна научиться отделять персонажа от контекста)
    "same person in a cafe, wearing casual sweater",
    "same person at a beach at sunset, wearing summer dress",
    "same person in a luxury hotel room, evening attire",
    "same person in a modern office, business casual",
    "same person in a park, autumn clothes",
    "same person in an art gallery, elegant outfit",
    "same person in a kitchen cooking, apron",
    "same person on a balcony, morning",
    # Крупные планы — критично для LoRA
    "same person, close up portrait, sharp focus on eyes",
    "same person, extreme close up of face, beauty shot",
    # Разнообразные позы
    "same person, arms crossed, confident pose",
    "same person, leaning on a table",
    "same person, walking, motion blur in background",
    "same person, sitting on a chair, relaxed",
    "same person, hands near face, thoughtful",
]


def generate_dataset_variations(
    reference_image: Path,
    output_dir: Path,
    count: int = 30,
    edit_prompts: Optional[list[str]] = None,
    seed: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Генерирует count вариаций персонажа через Kontext в output_dir.

    Args:
        reference_image: эталонный кадр
        output_dir: куда сохранять — будет создана
        count: сколько сгенерировать (округлится до длины edit_prompts)
        edit_prompts: свой список или DEFAULT_EDIT_PROMPTS
        seed: базовый сид
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompts = edit_prompts or DEFAULT_EDIT_PROMPTS
    # обрезаем или повторяем под count
    if len(prompts) >= count:
        prompts = prompts[:count]
    else:
        # повторяем с разными сидами
        reps = (count + len(prompts) - 1) // len(prompts)
        prompts = (prompts * reps)[:count]

    client = client or ComfyClient()
    results: list[Path] = []

    print(f"[dataset] генерирую {len(prompts)} вариаций в {output_dir}")
    print(f"[dataset] ожидаемое время: ~{len(prompts) * 30 // 60}-{len(prompts) * 45 // 60} минут")

    for i, prompt in enumerate(prompts):
        print(f"\n[dataset] {i+1}/{len(prompts)}: {prompt[:70]}")
        files = edit_character(
            reference_image=reference_image,
            edit_prompt=prompt,
            count=1,
            seed=(seed or 0) + i * 1000,
            client=client,
        )
        # Копируем с осмысленным именем
        for src in files:
            dest = output_dir / f"{i:03d}_{src.name}"
            shutil.copy2(src, dest)
            results.append(dest)

        client.free_memory(unload_models=False, free_memory=True)

    print(f"\n[dataset] сгенерировано {len(results)} фото в {output_dir}")
    print(f"[dataset] ⚠️  ОТБЕРИ ВРУЧНУЮ 20-30 ЛУЧШИХ перед тренировкой.")
    print(f"[dataset] плохие фото = плохой LoRA.")
    return results


def write_captions(
    dataset_dir: Path,
    trigger_word: Optional[str] = None,
    base_caption: str = "a photo of {trigger}, a person",
) -> int:
    """
    Пишет .txt файлы с кэпшенами рядом с каждым .png/.jpg в dataset_dir.
    Минимальный кэпшен: 'a photo of ohwx person'.
    FluxGym потом дополнит Florence-2, но базовый триггер нужен.
    """
    trigger = trigger_word or FluxGymSettings.trigger_word
    caption_text = base_caption.format(trigger=trigger)

    count = 0
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for img in dataset_dir.glob(ext):
            txt = img.with_suffix(".txt")
            if not txt.exists():
                txt.write_text(caption_text, encoding="utf-8")
                count += 1
    print(f"[dataset] написал {count} кэпшенов с триггером '{trigger}'")
    return count


def print_fluxgym_instructions(dataset_dir: Path, lora_name: str) -> None:
    """
    Печатает пошаговую инструкцию для запуска FluxGym WebUI.
    Тренировать через subprocess опасно (длинная сессия + GPU — пусть пользователь
    смотрит на Gradio-прогресс сам).
    """
    print("\n" + "═" * 65)
    print("СЛЕДУЮЩИЙ ШАГ — тренировка LoRA во FluxGym")
    print("═" * 65)
    print(f"\n1. Запусти FluxGym:")
    print(f"   cd {FLUXGYM_ROOT}")
    if sys.platform == "win32":
        print(f"   env\\Scripts\\activate")
    else:
        print(f"   source env/bin/activate")
    print(f"   python app.py")
    print(f"\n2. В браузере (http://127.0.0.1:7860):")
    print(f"   • LoRA Name:      {lora_name}")
    print(f"   • Trigger Word:   {FluxGymSettings.trigger_word}")
    print(f"   • Base Model:     {FluxGymSettings.base_model}")
    print(f"   • VRAM:           {FluxGymSettings.vram_preset}")
    print(f"   • Repeat trains:  {FluxGymSettings.repeat}")
    print(f"   • Max epochs:     {FluxGymSettings.max_epochs}")
    print(f"   • Resize:         {FluxGymSettings.resolution}")
    print(f"\n3. Перетяни ВСЕ отобранные фото из:")
    print(f"   {dataset_dir}")
    print(f"   в поле 'Upload images' (FluxGym сам скопирует куда надо)")
    print(f"\n4. Жми 'Start training'. На 4070S это 3-5 часов для 20-25 фото.")
    print(f"\n5. Результат — {lora_name}.safetensors в:")
    print(f"   {FLUXGYM_ROOT / 'outputs' / lora_name}")
    print(f"\n6. Скопируй .safetensors в ComfyUI\\models\\loras\\")
    print(f"   Используй в промпте: '{FluxGymSettings.trigger_word}, ...' и загружай через LoraLoader")
    print("═" * 65)


def prepare_lora_dataset(
    reference_image: Path,
    lora_name: str,
    count: int = 30,
    skip_generation: bool = False,
    seed: Optional[int] = None,
) -> Path:
    """
    Полная подготовка датасета для тренировки LoRA персонажа.

    Args:
        reference_image: эталонный кадр
        lora_name: как называть LoRA (например 'anna_v1')
        count: сколько вариантов сгенерировать
        skip_generation: если True — пропускает генерацию (датасет уже есть)
        seed: базовый сид
    """
    dataset_dir = OUTPUT_DIR / "lora_datasets" / lora_name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    if not skip_generation:
        generate_dataset_variations(
            reference_image=reference_image,
            output_dir=dataset_dir,
            count=count,
            seed=seed,
        )
    else:
        print(f"[dataset] пропускаю генерацию, использую существующий {dataset_dir}")

    # Считаем сколько фото в датасете
    imgs = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        imgs.extend(dataset_dir.glob(ext))

    if len(imgs) < FluxGymSettings.min_dataset:
        print(f"⚠️  Всего {len(imgs)} фото в датасете. FluxGym хочет минимум "
              f"{FluxGymSettings.min_dataset}, оптимум {FluxGymSettings.max_dataset}.")

    # Пишем базовые кэпшены
    write_captions(dataset_dir)

    # Инструкции
    print_fluxgym_instructions(dataset_dir, lora_name)

    return dataset_dir
