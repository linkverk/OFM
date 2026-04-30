"""
Lip sync через LatentSync 1.6.
Принимает видео + аудио, выдаёт видео с синхронизированными губами под аудио.

Ограничения модели:
- Ровно 25 fps на входе (принудительная конвертация в workflow)
- Фронтальное лицо, 1 человек в кадре
- Не anime
- Максимум качество на 512x512 лице
"""
import random
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    COMFYUI_ROOT,
    LatentSyncSettings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders
from utils.journal import run as journal_run


def _copy_to_comfy_input(file: Path, subfolder: str = "ai_ofm") -> str:
    """Копирует файл в ComfyUI/input/<subfolder>/. Возвращает имя для ноды Load*."""
    dest_dir = COMFYUI_ROOT / "input" / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.name
    if dest.resolve() != file.resolve():
        shutil.copy2(file, dest)
    return f"{subfolder}/{file.name}"


def _ensure_wav(audio: Path) -> Path:
    """
    LatentSync стабильнее с WAV 16kHz mono. Если аудио в другом формате —
    пробуем конвертировать через ffmpeg. Если ffmpeg нет — возвращаем как есть.
    """
    if audio.suffix.lower() == ".wav":
        return audio
    converted = audio.with_suffix(".16k.wav")
    if converted.exists():
        return converted
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(audio),
                "-ac", "1", "-ar", "16000",
                "-loglevel", "error",
                str(converted),
            ],
            check=True,
        )
        print(f"[lipsync] сконвертировал аудио → {converted.name}")
        return converted
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"[lipsync] ffmpeg не сработал ({e}), отдаю аудио как есть")
        return audio


def lip_sync(
    video: Path,
    audio: Path,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    lips_expression: Optional[float] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Накладывает lip sync на видео по аудио.

    Args:
        video: исходный клип (любой fps — будет сконвертирован в 25)
        audio: аудиодорожка (WAV/MP3). Длина аудио должна совпадать с видео или быть короче.
        seed: сид
        steps: inference_steps (20-50, дефолт из config)
        lips_expression: интенсивность движений губ (1.5-2.5)
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    video_name = _copy_to_comfy_input(video)
    audio_fixed = _ensure_wav(audio)
    audio_name = _copy_to_comfy_input(audio_fixed)

    used_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    used_steps = steps or LatentSyncSettings.inference_steps
    used_expr = lips_expression if lips_expression is not None else LatentSyncSettings.lips_expression

    wf_template = load_workflow(WORKFLOWS_DIR / "latentsync.json")
    values = {
        "INPUT_VIDEO": video_name,
        "INPUT_AUDIO": audio_name,
        "SEED": used_seed,
        "STEPS": used_steps,
        "LIPS_EXPRESSION": used_expr,
        "GUIDANCE": LatentSyncSettings.guidance_scale,
    }
    wf = fill_placeholders(wf_template, values)

    print(f"[lipsync] LatentSync 1.6, steps={used_steps}, lips_expr={used_expr}")
    print(f"[lipsync] ожидаемое время на 4070S: ~2-4 мин на 10 сек видео")

    client.free_memory(unload_models=True, free_memory=True)

    journal_params = {
        "input_video": video.name,
        "input_audio": audio.name,
        "seed": used_seed,
        "steps": used_steps,
        "lips_expression": used_expr,
        "guidance": LatentSyncSettings.guidance_scale,
    }
    with journal_run("lipsync", params=journal_params, tags=["latentsync"]) as _je:
        files = client.run_workflow(
            wf,
            progress_callback=lambda v, m: print(f"  {v}/{m}", end="\r"),
        )
        print(f"\n[lipsync] готово: {[f.name for f in files]}")
        _je.add_outputs(files)
        return files
