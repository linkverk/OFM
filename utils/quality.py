"""
Скоринг качества сгенерированных изображений и видео для Best-of-N выбора.

Использует CLIP-based directional similarity:
    score = sim(image, positive_text) - sim(image, negative_text)

где positive_text = промпт + «high quality, sharp, detailed», а negative_text —
типичные дефекты (blurry, deformed, low quality). Это эмпирически близко к
человеческой оценке для портретов и не требует отдельного aesthetic-предиктора.

Дизайн:
- ленивая загрузка модели (первый score → загрузка ~400 MB CLIP base)
- по умолчанию CPU, чтобы не отжирать VRAM у активного ComfyUI
- если transformers недоступен — fail soft: все скоры = 0 (best-of-N
  деградирует до случайного выбора, но пайплайн не падает)
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional


_POSITIVE_SUFFIX = ", high quality, photorealistic, sharp focus, detailed"
_NEGATIVE_TEXT = (
    "blurry, distorted, deformed, low quality, ugly, bad anatomy, "
    "extra fingers, jpeg artifacts, watermark, text"
)


class CLIPScorer:
    """Скорер на CLIP ViT-B/32 (transformers). Singleton-паттерн через get_scorer()."""

    def __init__(self, device: str = "cpu", model_name: str = "openai/clip-vit-base-patch32"):
        self.device = device
        self.model_name = model_name
        self._model = None
        self._processor = None
        self._available: Optional[bool] = None

    def _lazy_load(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from transformers import CLIPModel, CLIPProcessor
            import torch
            self._torch = torch
            self._model = CLIPModel.from_pretrained(self.model_name).to(self.device).eval()
            self._processor = CLIPProcessor.from_pretrained(self.model_name)
            self._available = True
            print(f"[quality] CLIP scorer загружен ({self.model_name} на {self.device})")
        except Exception as e:
            warnings.warn(f"[quality] CLIP недоступен ({e}); скоринг отключён")
            self._available = False
        return self._available

    def _score_pil(self, pil_image, prompt: str) -> float:
        if not self._lazy_load():
            return 0.0
        torch = self._torch
        pos = (prompt or "").strip() + _POSITIVE_SUFFIX
        neg = _NEGATIVE_TEXT
        with torch.no_grad():
            inputs = self._processor(
                text=[pos, neg], images=pil_image,
                return_tensors="pt", padding=True, truncation=True,
            ).to(self.device)
            out = self._model(**inputs)
            # logits_per_image: shape (1, 2)
            logits = out.logits_per_image[0]
            # нормированная разница: больше — лучше
            diff = (logits[0] - logits[1]).item()
        return diff

    def score_image(self, image_path: Path, prompt: str) -> float:
        try:
            from PIL import Image
            with Image.open(image_path) as im:
                im = im.convert("RGB")
                return self._score_pil(im, prompt)
        except Exception as e:
            warnings.warn(f"[quality] не смог оценить {image_path}: {e}")
            return 0.0

    def score_video(self, video_path: Path, prompt: str) -> float:
        """Оцениваем средний кадр клипа — для I2V этого достаточно
        чтобы поймать развалы лица и сильную деформацию."""
        try:
            import imageio.v3 as iio
            meta = iio.immeta(video_path, plugin="pyav")
            n_frames = meta.get("nframes") or meta.get("duration", 0) * meta.get("fps", 0)
            mid = int(n_frames // 2) if n_frames and n_frames > 0 else 0
            frame = iio.imread(video_path, index=mid, plugin="pyav")
            from PIL import Image
            return self._score_pil(Image.fromarray(frame), prompt)
        except Exception as e:
            warnings.warn(f"[quality] не смог извлечь кадр из {video_path}: {e}")
            return 0.0


_SCORER: Optional[CLIPScorer] = None


def get_scorer() -> CLIPScorer:
    """Глобальный singleton, чтобы CLIP не грузился по 400 MB на каждый вызов."""
    global _SCORER
    if _SCORER is None:
        from config import QualitySettings
        _SCORER = CLIPScorer(device=QualitySettings.scorer_device,
                             model_name=QualitySettings.scorer_model)
    return _SCORER


def pick_best(items: list, prompt: str, kind: str = "image") -> tuple[int, float, list[float]]:
    """
    Из списка путей возвращает (индекс лучшего, его score, все scores).
    kind: "image" или "video".
    Если всё в нулях — вернёт первый элемент.
    """
    scorer = get_scorer()
    fn = scorer.score_image if kind == "image" else scorer.score_video
    scores = [fn(Path(p), prompt) for p in items]
    if not scores:
        return -1, 0.0, []
    best_i = max(range(len(scores)), key=lambda i: scores[i])
    return best_i, scores[best_i], scores
