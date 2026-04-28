"""
Gaussian Thompson Sampling для подбора параметров генерации.

Идея: для каждой стадии (character / i2v / kontext) задан набор «arm»-ов —
дискретных конфигураций параметров. После каждого прогона мы записываем
score (от utils/quality) → обновляем running mean/variance arm-а через
Welford. Перед следующим прогоном сэмплируем mean каждого arm-а из
Normal(μ, σ²/n) и берём arm с наибольшим сэмплом.

Холодный старт: при n<2 у arm-а используем большую дисперсию (2.0), что
гарантированно гонит исследовать каждый arm в начале.

Хранение: один JSON файл `output/_bandit_history.json`. Список arm-ов
жёстко задан в config.BanditArms — если его поменяли, существующая
статистика по сохранённым arm-ам матчится по сериализованным `params`,
новые arm-ы стартуют с нуля.
"""
from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Optional


class _ArmStats:
    __slots__ = ("params", "n", "mean", "M2")

    def __init__(self, params: dict, n: int = 0, mean: float = 0.0, M2: float = 0.0):
        self.params = params
        self.n = n
        self.mean = mean
        self.M2 = M2

    def update(self, score: float) -> None:
        # Welford
        self.n += 1
        delta = score - self.mean
        self.mean += delta / self.n
        self.M2 += delta * (score - self.mean)

    def variance(self) -> float:
        if self.n < 2:
            return 4.0  # сильное исследование при недостатке данных
        return max(self.M2 / (self.n - 1), 1e-4)

    def sample_mean(self, rng: random.Random) -> float:
        if self.n < 2:
            return rng.gauss(self.mean, 2.0)
        # дисперсия оценки среднего
        se = (self.variance() / self.n + 0.01) ** 0.5
        return rng.gauss(self.mean, se)

    def to_json(self) -> dict:
        return {"params": self.params, "n": self.n, "mean": self.mean, "M2": self.M2}

    @classmethod
    def from_json(cls, d: dict) -> "_ArmStats":
        return cls(d["params"], d.get("n", 0), d.get("mean", 0.0), d.get("M2", 0.0))


class ParamBandit:
    """
    Per-stage Thompson sampling с persistent JSON.
    """

    _LOCK = threading.Lock()

    def __init__(self, history_path: Path, arms_by_stage: dict[str, list[dict]]):
        self.history_path = Path(history_path)
        self.arms_by_stage = arms_by_stage
        self._state: dict[str, list[_ArmStats]] = {}
        self._log: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.history_path.exists():
            try:
                data = json.loads(self.history_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        for stage, arms in self.arms_by_stage.items():
            saved = {self._key(a["params"]): a for a in data.get(stage, {}).get("arms", [])}
            stats: list[_ArmStats] = []
            for a in arms:
                k = self._key(a)
                if k in saved:
                    s = _ArmStats.from_json(saved[k])
                    s.params = a  # на случай если конфиг arm обновили
                    stats.append(s)
                else:
                    stats.append(_ArmStats(a))
            self._state[stage] = stats
        self._log = data.get("_log", [])[-500:]  # храним последние 500 событий

    def _save(self) -> None:
        out = {
            stage: {"arms": [s.to_json() for s in stats]}
            for stage, stats in self._state.items()
        }
        out["_log"] = self._log[-500:]
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.history_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.history_path)

    @staticmethod
    def _key(params: dict) -> str:
        return json.dumps(params, sort_keys=True)

    def suggest(self, stage: str, rng: Optional[random.Random] = None) -> tuple[int, dict]:
        """Возвращает (arm_index, params) для следующего прогона."""
        rng = rng or random.Random()
        stats = self._state.get(stage)
        if not stats:
            return -1, {}
        idx = max(range(len(stats)), key=lambda i: stats[i].sample_mean(rng))
        return idx, dict(stats[idx].params)

    def record(self, stage: str, arm_idx: int, score: float, extra: Optional[dict] = None) -> None:
        with self._LOCK:
            stats = self._state.get(stage)
            if not stats or not (0 <= arm_idx < len(stats)):
                return
            stats[arm_idx].update(score)
            self._log.append({
                "ts": int(time.time()),
                "stage": stage,
                "arm": arm_idx,
                "params": stats[arm_idx].params,
                "score": round(score, 4),
                "extra": extra or {},
            })
            self._save()

    def stats_summary(self, stage: str) -> list[dict]:
        return [
            {"params": s.params, "n": s.n, "mean": round(s.mean, 4),
             "var": round(s.variance(), 4)}
            for s in self._state.get(stage, [])
        ]


_BANDIT: Optional[ParamBandit] = None


def get_bandit() -> ParamBandit:
    global _BANDIT
    if _BANDIT is None:
        from config import OUTPUT_DIR, BanditArms
        _BANDIT = ParamBandit(
            history_path=OUTPUT_DIR / "_bandit_history.json",
            arms_by_stage={
                "character": BanditArms.character,
                "i2v": BanditArms.i2v,
                "kontext": BanditArms.kontext,
            },
        )
    return _BANDIT
