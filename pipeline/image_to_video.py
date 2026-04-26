"""
Image-to-Video через Wan 2.2 I2V 14B Q4_K_M + Lightning 4+4.
"""
import random
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    WAN_HIGH_NOISE,
    WAN_LOW_NOISE,
    WAN_VAE,
    WAN_T5,
    WAN_CLIP_VISION,
    WAN_LIGHTNING_HIGH,
    WAN_LIGHTNING_LOW,
    WanSettings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders


DEFAULT_MOTION_NEGATIVE = (
    "static, frozen, still image, no motion, artifacts, flickering, "
    "morphing face, distorted body, extra limbs, jitter"
)


def image_to_video(
    image: Path,
    motion_prompt: str,
    negative: Optional[str] = None,
    seed: Optional[int] = None,
    frames: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Превращает статичное изображение в видеоклип.

    Args:
        image: стартовый кадр (путь). Лучше после character_gen.
        motion_prompt: описание движения — "slowly smiling and turning head"
        negative: негативный промпт
        seed: сид или None
        frames: число кадров (по умолчанию 81 = 5 сек @ 16fps native Wan)
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    image_name = client.upload_image(image)
    neg = negative or DEFAULT_MOTION_NEGATIVE
    used_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    num_frames = frames or WanSettings.num_frames

    wf_template = load_workflow(WORKFLOWS_DIR / "wan22_i2v.json")
    total_steps = WanSettings.steps_high + WanSettings.steps_low

    values = {
        "WAN_HIGH": WAN_HIGH_NOISE,
        "WAN_LOW": WAN_LOW_NOISE,
        "WAN_VAE": WAN_VAE,
        "WAN_T5": WAN_T5,
        "WAN_CLIP_VISION": WAN_CLIP_VISION,
        "LIGHTNING_HIGH": WAN_LIGHTNING_HIGH,
        "LIGHTNING_LOW": WAN_LIGHTNING_LOW,
        "START_IMAGE": image_name,
        "POSITIVE": motion_prompt,
        "NEGATIVE": neg,
        "WIDTH": WanSettings.width,
        "HEIGHT": WanSettings.height,
        "FRAMES": num_frames,
        "SEED": used_seed,
        "BLOCKS_SWAP": WanSettings.blocks_to_swap,
        "STEPS_HIGH": WanSettings.steps_high,
        "STEPS_LOW": WanSettings.steps_low,
        "STEPS_TOTAL": total_steps,
        # TEACACHE_THRESH удалён — workflow больше не использует TeaCache
    }
    wf = fill_placeholders(wf_template, values)

    print(f"[i2v] Wan 2.2 + Lightning {WanSettings.steps_high}+{WanSettings.steps_low}, "
          f"{WanSettings.width}x{WanSettings.height}, {num_frames} кадров, seed={used_seed}")
    print(f"[i2v] ожидаемое время на 4070S: 4-6 минут (без TeaCache)...")

    # Перед тяжёлой задачей — принудительная выгрузка
    client.free_memory(unload_models=True, free_memory=True)

    files = client.run_workflow(
        wf,
        progress_callback=lambda v, m: print(f"  шаг {v}/{m}", end="\r"),
    )
    print(f"\n[i2v] готово: {[f.name for f in files]}")
    return files