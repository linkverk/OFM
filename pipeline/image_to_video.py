"""
Image-to-Video через Wan 2.2 I2V 14B Q4_K_M + Lightning 4+4.

Поддерживает Best-of-N + bandit (см. character_gen для объяснения).
По умолчанию n_variants_video=1 — один прогон занимает 4-6 минут на 4070S,
делать N=3 имеет смысл только когда время не критично.
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
    QualitySettings,
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
    quality_mode: Optional[bool] = None,
    n_variants: Optional[int] = None,
) -> list[Path]:
    """
    Превращает статичное изображение в видеоклип.

    Args:
        image: стартовый кадр (путь). Лучше после character_gen.
        motion_prompt: описание движения — "slowly smiling and turning head"
        negative: негативный промпт
        seed: сид или None
        frames: число кадров (по умолчанию 81 = 5 сек @ 16fps native Wan)
        quality_mode: Best-of-N (по умолчанию из QualitySettings.enabled).
        n_variants: сколько клипов проскорить (по умолчанию 1 — дорого).
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен.")

    use_quality = QualitySettings.enabled if quality_mode is None else quality_mode
    n_per_final = n_variants or QualitySettings.n_variants_video

    image_name = client.upload_image(image)
    neg = negative or DEFAULT_MOTION_NEGATIVE
    base_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
    num_frames = frames or WanSettings.num_frames

    wf_template = load_workflow(WORKFLOWS_DIR / "wan22_i2v.json")

    bandit = None
    scorer = None
    if use_quality and n_per_final > 1:
        try:
            from utils.bandit import get_bandit
            from utils.quality import get_scorer
            bandit = get_bandit()
            scorer = get_scorer()
        except Exception as e:
            print(f"[i2v] Best-of-N отключён ({e})")
            use_quality = False
            n_per_final = 1

    # Перед тяжёлой задачей — принудительная выгрузка
    client.free_memory(unload_models=True, free_memory=True)

    # Если N=1 и bandit включён, всё равно сэмплируем arm для тренировки бандита
    if use_quality and bandit is not None and n_per_final == 1:
        rng = random.Random(base_seed)
        arm_idx, arm_params = bandit.suggest("i2v", rng=rng)
        steps_high = arm_params.get("steps_high", WanSettings.steps_high)
        steps_low = arm_params.get("steps_low", WanSettings.steps_low)
        files = _run_one(
            client, wf_template, image_name, motion_prompt, neg,
            num_frames, base_seed, steps_high, steps_low,
            label=f"arm#{arm_idx}",
        )
        if files and scorer is not None:
            score = scorer.score_video(files[0], motion_prompt)
            if QualitySettings.log_scores:
                print(f"[i2v] {files[0].name} arm#{arm_idx} score={score:+.3f}")
            bandit.record("i2v", arm_idx, score, extra={"prompt": motion_prompt[:80]})
        return files

    if not (use_quality and n_per_final > 1):
        # Старое поведение
        return _run_one(
            client, wf_template, image_name, motion_prompt, neg,
            num_frames, base_seed,
            WanSettings.steps_high, WanSettings.steps_low,
        )

    # ---- Best-of-N путь (n_per_final > 1) ----
    rng = random.Random(base_seed)
    candidates: list[tuple[Path, int]] = []  # (path, arm_idx)
    print(f"[i2v] Best-of-{n_per_final} режим — это займёт ~{4*n_per_final}-{6*n_per_final} минут")

    for v in range(n_per_final):
        arm_idx, arm_params = bandit.suggest("i2v", rng=rng)
        steps_high = arm_params.get("steps_high", WanSettings.steps_high)
        steps_low = arm_params.get("steps_low", WanSettings.steps_low)
        seed_v = base_seed + v * 7919
        print(f"[i2v] кандидат {v+1}/{n_per_final}: arm#{arm_idx} steps={steps_high}+{steps_low} seed={seed_v}")
        files = _run_one(
            client, wf_template, image_name, motion_prompt, neg,
            num_frames, seed_v, steps_high, steps_low,
            label=f"arm#{arm_idx}",
        )
        for f in files:
            candidates.append((f, arm_idx))
        if v < n_per_final - 1:
            client.free_memory(unload_models=True, free_memory=True)

    if not candidates:
        return []

    scores = [scorer.score_video(p, motion_prompt) for p, _ in candidates]
    if QualitySettings.log_scores:
        for (path, arm), s in zip(candidates, scores):
            tag = "★" if s == max(scores) else " "
            print(f"  {tag} {path.name} arm#{arm} score={s:+.3f}")

    for (_, arm_idx), s in zip(candidates, scores):
        bandit.record("i2v", arm_idx, s, extra={"prompt": motion_prompt[:80]})

    best_i = max(range(len(scores)), key=lambda i: scores[i])
    return [candidates[best_i][0]]


def _run_one(
    client, wf_template, image_name, motion_prompt, neg,
    num_frames, seed, steps_high, steps_low, label: str = "",
) -> list[Path]:
    total_steps = steps_high + steps_low
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
        "SEED": seed,
        "BLOCKS_SWAP": WanSettings.blocks_to_swap,
        "STEPS_HIGH": steps_high,
        "STEPS_LOW": steps_low,
        "STEPS_TOTAL": total_steps,
    }
    wf = fill_placeholders(wf_template, values)
    suffix = f" [{label}]" if label else ""
    print(f"[i2v]{suffix} Wan 2.2 + Lightning {steps_high}+{steps_low}, "
          f"{WanSettings.width}x{WanSettings.height}, {num_frames} кадров, seed={seed}")
    files = client.run_workflow(
        wf, progress_callback=lambda v, m: print(f"  шаг {v}/{m}", end="\r"),
    )
    print(f"\n[i2v] готово: {[f.name for f in files]}")
    return files
