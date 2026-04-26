"""
Генерация консистентного персонажа: Flux.1-dev Q5 GGUF + PuLID-Flux II + FaceDetailer.
"""
import random
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    FLUX_UNET_GGUF,
    FLUX_CLIP_L,
    FLUX_T5,
    FLUX_VAE,
    PULID_MODEL,
    CODEFORMER_MODEL,
    FluxSettings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders


DEFAULT_NEGATIVE = (
    "cartoon, anime, illustration, painting, drawing, 3d render, cgi, "
    "deformed, distorted, disfigured, bad anatomy, extra limbs, extra fingers, "
    "blurry, low quality, jpeg artifacts, watermark, signature, text"
)

PROMPT_QUALITY_PREFIX = (
    "a photorealistic portrait photograph, professional photography, "
    "natural skin texture, detailed eyes, sharp focus, high detail, "
)


def generate_character(
    face_ref: Path,
    prompt: str,
    negative: Optional[str] = None,
    count: int = 1,
    seed: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Генерирует count вариаций персонажа с лицом из face_ref.

    Args:
        face_ref: путь к референсному фото лица (чёткое, фронтальное)
        prompt: описание сцены/одежды/действия
        negative: негативный промпт (по умолчанию — антикартунный)
        count: сколько вариантов сгенерировать (разные сиды)
        seed: фиксированный сид или None
    Returns:
        список путей к сохранённым изображениям
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError(
            "ComfyUI не запущен. Старт: cd ComfyUI && python main.py --use-sage-attention --fast"
        )

    # Копируем референс в ComfyUI/input/ai_ofm/
    face_name = client.upload_image(face_ref)

    full_prompt = PROMPT_QUALITY_PREFIX + prompt
    neg = negative or DEFAULT_NEGATIVE
    base_seed = seed if seed is not None else random.randint(1, 2**31 - 1)

    wf_template = load_workflow(WORKFLOWS_DIR / "flux_pulid.json")
    results: list[Path] = []

    for i in range(count):
        values = {
            "FLUX_UNET": FLUX_UNET_GGUF,
            "CLIP_L": FLUX_CLIP_L,
            "T5": FLUX_T5,
            "VAE": FLUX_VAE,
            "PULID": PULID_MODEL,
            "CODEFORMER": CODEFORMER_MODEL,
            "CODEFORMER_FIDELITY": FluxSettings.codeformer_fidelity,
            "FACE_IMAGE": face_name,
            "POSITIVE": full_prompt,
            "NEGATIVE": neg,
            "WIDTH": FluxSettings.width,
            "HEIGHT": FluxSettings.height,
            "STEPS": FluxSettings.steps,
            "GUIDANCE": FluxSettings.guidance,
            "PULID_WEIGHT": FluxSettings.pulid_weight,
            "SEED": base_seed + i * 7919,  # разные сиды → разные ракурсы
        }
        wf = fill_placeholders(wf_template, values)

        print(f"[character] вариант {i+1}/{count} (seed={values['SEED']})...")
        files = client.run_workflow(
            wf,
            progress_callback=lambda v, m: print(f"  {v}/{m}", end="\r"),
        )
        results.extend(files)
        print(f"  готово: {[f.name for f in files]}")

        # между генерациями чистим VRAM — PuLID склонен копить
        if i < count - 1:
            client.free_memory(unload_models=False, free_memory=True)

    return results
