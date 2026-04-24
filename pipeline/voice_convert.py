"""
RVC (Retrieval-based Voice Conversion) — пост-процессинг тембра.

Зачем: F5-TTS хорошо клонирует общий голос, но RVC шлифует тембр под точную копию.
Типичный паттерн: F5-TTS синтезирует русскую речь голосом X → RVC уточняет
тембр до идеального совпадения с тренированной RVC моделью голоса X.

Требования:
- RVC установлен отдельно (например, форк Mangio-RVC или RVC-WebUI).
- Есть тренированная RVC модель (.pth + .index файлы).

Запуск через subprocess — тоже из-за конфликта CUDA с ComfyUI.
"""
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from config import (
    RVC_ROOT,
    OUTPUT_DIR,
    RVCSettings,
)


def _find_rvc_cli() -> list[str]:
    """
    Ищет CLI RVC. В разных форках называется по-разному.
    Возвращает list для subprocess, либо пустой список если не найден.
    """
    # Mangio-RVC-Fork
    mangio = RVC_ROOT / "infer_cli.py"
    if mangio.exists():
        return [sys.executable, str(mangio)]
    # Retrieval-based-Voice-Conversion-WebUI (tools/infer_cli.py)
    stock = RVC_ROOT / "tools" / "infer_cli.py"
    if stock.exists():
        return [sys.executable, str(stock)]
    # RVC как pip-пакет
    if shutil.which("rvc"):
        return ["rvc"]
    return []


def convert(
    input_wav: Path,
    model_pth: Optional[Path] = None,
    index_file: Optional[Path] = None,
    pitch: Optional[int] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Прогоняет входной WAV через RVC модель.

    Args:
        input_wav: вход (обычно результат F5-TTS)
        model_pth: путь к .pth модели RVC (None = из RVCSettings)
        index_file: путь к .index файлу (None = из RVCSettings, может быть None вообще)
        pitch: сдвиг в семитонах (-12..+12). 0 обычно. ±12 для смены пола.
        output_path: куда сохранить

    Returns:
        Path к сконвертированному WAV.
    """
    if not input_wav.exists():
        raise FileNotFoundError(input_wav)

    model = Path(model_pth) if model_pth else RVCSettings.model_pth
    index = Path(index_file) if index_file else RVCSettings.index_file

    if model is None or not Path(model).exists():
        raise FileNotFoundError(
            f"RVC модель не найдена: {model}. "
            "Укажи путь в config.py → RVCSettings.model_pth"
        )

    if output_path is None:
        output_path = OUTPUT_DIR / f"{input_wav.stem}_rvc_{uuid.uuid4().hex[:6]}.wav"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cli = _find_rvc_cli()
    if not cli:
        raise RuntimeError(
            "RVC CLI не найден. Проверь RVC_ROOT в config.py.\n"
            "Поддерживаемые форки: Mangio-RVC-Fork, Retrieval-based-Voice-Conversion-WebUI."
        )

    pitch_val = pitch if pitch is not None else RVCSettings.pitch

    # NB: у разных форков разный CLI. Это вариант под Mangio-форк.
    # Если у тебя другой форк — адаптируй флаги под его infer_cli.py.
    cmd = cli + [
        "--f0up_key", str(pitch_val),
        "--input_path", str(input_wav),
        "--index_path", str(index) if index else "",
        "--f0method", RVCSettings.f0_method,
        "--opt_path", str(output_path),
        "--model_name", str(model.name),
        "--index_rate", str(RVCSettings.index_rate),
        "--filter_radius", str(RVCSettings.filter_radius),
        "--rms_mix_rate", str(RVCSettings.rms_mix_rate),
        "--protect", str(RVCSettings.protect),
    ]

    print(f"[rvc] конверсия {input_wav.name} → {output_path.name}, pitch={pitch_val}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(RVC_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Не удалось запустить RVC: {e}")

    if result.returncode != 0:
        print("[rvc] STDERR:\n" + (result.stderr or "")[-2000:])
        raise RuntimeError(f"RVC упал (код {result.returncode})")

    if not output_path.exists():
        raise RuntimeError(f"RVC не создал файл: {output_path}")

    print(f"[rvc] готово: {output_path}")
    return output_path
