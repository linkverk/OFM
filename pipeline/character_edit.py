"""
Character editing через Flux Kontext Dev.

Парадигма другая, чем в character_gen.py:
- character_gen = "взять новое лицо по референсу, сгенерировать с нуля" (PuLID)
- character_edit = "взять уже готовый кадр персонажа и поменять сцену/позу/одежду"

Типичный use case для AI-OFM:
1. Сделать один эталонный кадр через character_gen + одобрить
2. Наштамповать вариаций через character_edit без тренировки LoRA
"""
import random
from pathlib import Path
from typing import Optional

from config import (
    WORKFLOWS_DIR,
    FLUX_KONTEXT_GGUF,
    FLUX_CLIP_L,
    FLUX_T5,
    FLUX_VAE,
    FluxKontextSettings,
)
from utils.comfy_client import ComfyClient
from utils.workflow import load_workflow, fill_placeholders
from utils.journal import run as journal_run


# Примеры edit-промптов (подсказка в docstring):
# - "change the outfit to a white sundress, keep face and pose"
# - "place this person on a sunny beach at golden hour"
# - "same person, now smiling, laughing naturally"
# - "change background to a luxury hotel room"


def edit_character(
    reference_image: Path,
    edit_prompt: str,
    count: int = 1,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    client: Optional[ComfyClient] = None,
) -> list[Path]:
    """
    Редактирует эталонный кадр персонажа по edit_prompt.

    Args:
        reference_image: уже готовый кадр персонажа (обычно из character_gen).
        edit_prompt: что поменять. Лучше на английском:
            "change outfit to red dress, same pose, same face".
        count: сколько вариантов (разные сиды).
        seed: фиксированный сид или None.
        width/height: None = из FluxKontextSettings.
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    ref_name = client.upload_image(reference_image)
    base_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    w = width or FluxKontextSettings.width
    h = height or FluxKontextSettings.height

    wf_template = load_workflow(WORKFLOWS_DIR / "flux_kontext.json")
    results: list[Path] = []

    journal_params = {
        "count": count,
        "base_seed": base_seed,
        "width": w,
        "height": h,
        "steps": FluxKontextSettings.steps,
        "guidance": FluxKontextSettings.guidance,
        "ref_image": reference_image.name,
    }

    with journal_run(
        "kontext",
        params=journal_params,
        prompt=edit_prompt,
        tags=["flux", "kontext"],
    ) as _je:
        for i in range(count):
            values = {
                "KONTEXT_UNET": FLUX_KONTEXT_GGUF,
                "CLIP_L": FLUX_CLIP_L,
                "T5": FLUX_T5,
                "VAE": FLUX_VAE,
                "REF_IMAGE": ref_name,
                "EDIT_PROMPT": edit_prompt,
                "WIDTH": w,
                "HEIGHT": h,
                "STEPS": FluxKontextSettings.steps,
                "GUIDANCE": FluxKontextSettings.guidance,
                "SEED": base_seed + i * 7919,
            }
            wf = fill_placeholders(wf_template, values)

            print(f"[kontext] {i+1}/{count} '{edit_prompt[:60]}...' (seed={values['SEED']})")
            files = client.run_workflow(
                wf,
                progress_callback=lambda v, m: print(f"  {v}/{m}", end="\r"),
            )
            results.extend(files)
            print(f"  готово: {[f.name for f in files]}")

            if i < count - 1:
                client.free_memory(unload_models=False, free_memory=True)

        _je.add_outputs(results)
        return results
