"""
Интерполяция fps через RIFE v4.x.
Вставляет сгенерированные промежуточные кадры. Очень быстро, ~2 GB VRAM.

Типичные сценарии:
- Wan 2.2 даёт 16-24 fps → нужно 48 fps для современного «живого» вида
- После LatentSync (25 fps) → 50 fps для плавности
"""
import shutil
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    COMFYUI_ROOT,
    RifeSettings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders
from utils.journal import run as journal_run


def _copy_to_comfy_input(file: Path, subfolder: str = "ai_ofm") -> str:
    dest_dir = COMFYUI_ROOT / "input" / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.name
    if dest.resolve() != file.resolve():
        shutil.copy2(file, dest)
    return f"{subfolder}/{file.name}"


def interpolate_fps(
    video: Path,
    multiplier: Optional[int] = None,
    output_fps: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Удваивает (или утраивает) fps видео.

    Args:
        video: вход
        multiplier: x2 = удвоение (24→48), x3 = утроение (24→72)
        output_fps: какой fps писать в итоговый mp4. Если None — multiplier * (предполагаемый 24)
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    video_name = _copy_to_comfy_input(video)
    mult = multiplier or RifeSettings.multiplier
    # если output_fps не задан явно — берём из настроек, но масштабируем под multiplier
    if output_fps is None:
        if mult == RifeSettings.multiplier:
            output_fps = RifeSettings.output_fps
        else:
            # приблизительная оценка: берём дефолтный 24 и умножаем
            output_fps = 24 * mult

    wf_template = load_workflow(WORKFLOWS_DIR / "rife_interpolation.json")
    values = {
        "INPUT_VIDEO": video_name,
        "MULTIPLIER": mult,
        "OUTPUT_FPS": output_fps,
    }
    wf = fill_placeholders(wf_template, values)

    print(f"[rife] интерполяция x{mult}, output fps={output_fps}")
    print(f"[rife] ожидаемое время: 10-30 сек на 5-секундный клип")

    journal_params = {
        "input_video": video.name,
        "multiplier": mult,
        "output_fps": output_fps,
    }
    with journal_run("rife", params=journal_params, tags=["rife", "fps"]) as _je:
        files = client.run_workflow(
            wf,
            progress_callback=lambda v, m: print(f"  {v}/{m}", end="\r"),
        )
        print(f"\n[rife] готово: {[f.name for f in files]}")
        _je.add_outputs(files)
        return files
