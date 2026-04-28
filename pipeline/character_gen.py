"""
Генерация консистентного персонажа: Flux.1-dev Q5 GGUF + PuLID-Flux II + FaceDetailer.

Поддерживает Best-of-N + Thompson-bandit (см. utils/quality, utils/bandit):
если QualitySettings.enabled, генерим N вариантов с параметрами, подобранными
бандитом, скорим CLIP'ом, возвращаем top-K. Bandit получает обратную связь от
score лучшего варианта в прогоне (это смещает выбор к выигрышным аркам).
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
    QualitySettings,
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
    quality_mode: Optional[bool] = None,
    n_variants: Optional[int] = None,
) -> list[Path]:
    """
    Генерирует count вариаций персонажа с лицом из face_ref.

    Args:
        face_ref: путь к референсному фото лица (чёткое, фронтальное)
        prompt: описание сцены/одежды/действия
        negative: негативный промпт (по умолчанию — антикартунный)
        count: сколько финальных вариантов хочется (после отбора)
        seed: фиксированный сид или None
        quality_mode: включить Best-of-N (по умолчанию — из QualitySettings.enabled).
            Если True — генерим n_variants > count и оставляем count лучших.
        n_variants: сколько вариантов проскорить за один финальный (по умолчанию
            QualitySettings.n_variants_image).
    Returns:
        список путей к count лучшим изображениям.
    """
    client = client or ComfyClient()
    if not client.is_alive():
        raise RuntimeError(
            "ComfyUI не запущен. Старт: cd ComfyUI && python main.py --use-sage-attention --fast"
        )

    use_quality = QualitySettings.enabled if quality_mode is None else quality_mode
    n_per_final = n_variants or QualitySettings.n_variants_image

    # Копируем референс в ComfyUI/input/ai_ofm/
    face_name = client.upload_image(face_ref)

    full_prompt = PROMPT_QUALITY_PREFIX + prompt
    neg = negative or DEFAULT_NEGATIVE
    base_seed = seed if seed is not None else random.randint(1, 2**31 - 1)

    wf_template = load_workflow(WORKFLOWS_DIR / "flux_pulid.json")

    # Bandit / scorer — ленивые импорты, чтобы пайплайн работал даже если
    # transformers/CLIP недоступны (см. utils/quality fail-soft).
    bandit = None
    scorer = None
    if use_quality:
        try:
            from utils.bandit import get_bandit
            from utils.quality import get_scorer
            bandit = get_bandit()
            scorer = get_scorer()
        except Exception as e:
            print(f"[character] Best-of-N отключён ({e}); работаем как обычно")
            use_quality = False

    final_results: list[Path] = []
    rng = random.Random(base_seed)

    # Если Best-of-N выключен — старое поведение: count прогонов с фикс. параметрами.
    if not use_quality:
        for i in range(count):
            values = _build_values(
                face_name, full_prompt, neg,
                steps=FluxSettings.steps, guidance=FluxSettings.guidance,
                seed=base_seed + i * 7919,
            )
            wf = fill_placeholders(wf_template, values)
            print(f"[character] вариант {i+1}/{count} (seed={values['SEED']})")
            files = client.run_workflow(
                wf, progress_callback=lambda v, m: print(f"  {v}/{m}", end="\r"),
            )
            final_results.extend(files)
            print(f"  готово: {[f.name for f in files]}")
            if i < count - 1:
                client.free_memory(unload_models=False, free_memory=True)
        return final_results

    # ---- Best-of-N путь ----
    for slot in range(count):
        candidates: list[tuple[Path, int, dict]] = []  # (path, arm_idx, params)
        print(f"[character] слот {slot+1}/{count} — генерирую {n_per_final} кандидатов")

        for v in range(n_per_final):
            arm_idx, arm_params = bandit.suggest("character", rng=rng)
            steps = arm_params.get("steps", FluxSettings.steps)
            guidance = arm_params.get("guidance", FluxSettings.guidance)
            values = _build_values(
                face_name, full_prompt, neg,
                steps=steps, guidance=guidance,
                seed=base_seed + (slot * 1000 + v) * 7919,
            )
            wf = fill_placeholders(wf_template, values)
            print(f"  кандидат {v+1}/{n_per_final}: arm#{arm_idx} steps={steps} g={guidance} seed={values['SEED']}")
            files = client.run_workflow(
                wf, progress_callback=lambda val, m: print(f"    {val}/{m}", end="\r"),
            )
            for f in files:
                candidates.append((f, arm_idx, arm_params))
            if v < n_per_final - 1:
                client.free_memory(unload_models=False, free_memory=True)

        if not candidates:
            continue

        # Скорим всех кандидатов и обновляем bandit
        scores = []
        for path, _, _ in candidates:
            s = scorer.score_image(path, prompt)
            scores.append(s)

        if QualitySettings.log_scores:
            for (path, arm, _), s in zip(candidates, scores):
                tag = "★" if s == max(scores) else " "
                print(f"  {tag} {path.name} arm#{arm} score={s:+.3f}")

        # Записываем результаты в bandit (каждый arm получает свой score)
        for (_, arm_idx, _), s in zip(candidates, scores):
            bandit.record("character", arm_idx, s, extra={"prompt": prompt[:80]})

        best_i = max(range(len(scores)), key=lambda i: scores[i])
        final_results.append(candidates[best_i][0])

        if slot < count - 1:
            client.free_memory(unload_models=False, free_memory=True)

    return final_results


def _build_values(
    face_name: str, full_prompt: str, neg: str,
    steps: int, guidance: float, seed: int,
) -> dict:
    return {
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
        "STEPS": steps,
        "GUIDANCE": guidance,
        "PULID_WEIGHT": FluxSettings.pulid_weight,
        "SEED": seed,
    }
