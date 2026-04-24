"""
Апскейл видео через SeedVR2 7B FP8 с BlockSwap.
"""
import random
import shutil
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    COMFYUI_ROOT,
    SEEDVR2_MODEL,
    SeedVR2Settings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders


def _copy_video_to_comfy_input(video: Path) -> str:
    """VHS_LoadVideo читает из ComfyUI/input/. Копируем туда."""
    dest_dir = COMFYUI_ROOT / "input" / "ai_ofm"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / video.name
    if dest.resolve() != video.resolve():
        shutil.copy2(video, dest)
    return f"ai_ofm/{video.name}"


def upscale_video(
    video: Path,
    target_resolution: int = 1280,
    seed: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Апскейлит видео до target_resolution по большей стороне.

    Args:
        video: путь к входному MP4
        target_resolution: целевая ширина по большей стороне (720, 1080, 1280, 1440)
        seed: сид
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    video_name = _copy_video_to_comfy_input(video)
    used_seed = seed if seed is not None else random.randint(1, 2**31 - 1)

    wf_template = load_workflow(WORKFLOWS_DIR / "seedvr2_upscale.json")
    values = {
        "SEEDVR2_MODEL": SEEDVR2_MODEL,
        "INPUT_VIDEO": video_name,
        "UPSCALE": target_resolution,
        "BATCH": SeedVR2Settings.batch_size,
        "BLOCKS_SWAP": SeedVR2Settings.blocks_to_swap,
        "SEED": used_seed,
    }
    wf = fill_placeholders(wf_template, values)

    print(f"[upscale] SeedVR2 7B FP8 → {target_resolution}p, blocks_swap={SeedVR2Settings.blocks_to_swap}")
    print(f"[upscale] ожидаемое время на 4070S: 3-5 минут...")

    client.free_memory(unload_models=True, free_memory=True)
    files = client.run_workflow(
        wf,
        progress_callback=lambda v, m: print(f"  кадр {v}/{m}", end="\r"),
    )
    print(f"\n[upscale] готово: {[f.name for f in files]}")
    return files
