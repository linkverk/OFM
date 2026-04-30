"""
F5-TTS для русского голоса.

Использует русский файнтюн Misha24-10/F5-TTS_RUSSIAN с поддержкой ударений через RUAccent.
Запускается subprocess'ом — не импортом, чтобы не конфликтовать с ComfyUI за CUDA.

Требования:
- F5-TTS установлен отдельно: git clone + pip install -e .
- RUAccent установлен: pip install ruaccent
- Скачан русский ckpt от Misha24-10 (см. MODELS_CHECKLIST.md)

Поток данных:
- входной текст (рус, без ударений) → RUAccent расставляет `+` перед ударными гласными
    → F5-TTS синтезирует WAV, клонируя голос из reference_audio
"""
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from config import (
    F5_TTS_ROOT,
    OUTPUT_DIR,
    F5Settings,
)
from utils.journal import run as journal_run


def _ensure_ruaccent():
    """Ленивый импорт RUAccent. Возвращает инициализированный объект или None."""
    try:
        from ruaccent import RUAccent
        accentizer = RUAccent()
        # omographs=True включает разрешение омографов через ML-модель
        accentizer.load(omograph_model_size='turbo', use_dictionary=True)
        return accentizer
    except ImportError:
        print("[tts] RUAccent не установлен. Поставь: pip install ruaccent")
        print("      Синтез пойдёт без ударений — качество будет хуже.")
        return None
    except Exception as e:
        print(f"[tts] RUAccent не инициализировался ({e}). Пропускаю ударения.")
        return None


def _add_stress_marks(text: str) -> str:
    """Расставляет `+` перед ударными гласными через RUAccent."""
    accentizer = _ensure_ruaccent()
    if accentizer is None:
        return text
    try:
        return accentizer.process_all(text)
    except Exception as e:
        print(f"[tts] RUAccent process_all упал ({e}), отдаю текст как есть")
        return text


def _find_f5_tts_cli() -> str:
    """
    Находит способ запустить F5-TTS.
    Предпочитаем `f5-tts_infer-cli` (появляется после pip install),
    fallback — python -m f5_tts.infer.infer_cli из F5_TTS_ROOT.
    """
    # Пробуем глобальную команду
    if shutil.which("f5-tts_infer-cli"):
        return "f5-tts_infer-cli"
    # Пробуем python -m
    return f"{sys.executable} -m f5_tts.infer.infer_cli"


def synthesize(
    text: str,
    reference_audio: Path,
    reference_text: str,
    output_path: Optional[Path] = None,
    nfe_step: Optional[int] = None,
    speed: Optional[float] = None,
    use_ruaccent: Optional[bool] = None,
    ckpt_path: Optional[Path] = None,
) -> Path:
    """
    Генерирует русскую речь голосом референса.

    Args:
        text: что сказать (рус). Ударения расставятся автоматом через RUAccent.
        reference_audio: эталонный WAV голоса (3-10 сек, чистый, 24kHz mono идеал).
        reference_text: ТОЧНАЯ транскрипция reference_audio — буква в букву, с пунктуацией.
        output_path: куда сохранить WAV (по умолчанию — в OUTPUT_DIR со случайным именем).
        nfe_step: шаги NFE (16-32, больше = качественнее).
        speed: скорость речи (0.8-1.2).
        use_ruaccent: форсировать вкл/выкл ударения (None = из config).
        ckpt_path: путь к ckpt-файлу (None = F5Settings.ckpt_path).

    Returns:
        Path к сгенерированному WAV.
    """
    if not reference_audio.exists():
        raise FileNotFoundError(f"Референс не найден: {reference_audio}")

    if not reference_text.strip():
        raise ValueError("reference_text обязателен — F5-TTS нужна транскрипция референса")

    # Ударения
    do_accent = F5Settings.use_ruaccent if use_ruaccent is None else use_ruaccent
    synth_text = _add_stress_marks(text) if do_accent else text
    ref_text_prepared = _add_stress_marks(reference_text) if do_accent else reference_text

    # Куда писать
    if output_path is None:
        output_path = OUTPUT_DIR / f"tts_{uuid.uuid4().hex[:8]}.wav"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Параметры
    nfe = nfe_step or F5Settings.nfe_step
    spd = speed if speed is not None else F5Settings.speed
    ckpt = Path(ckpt_path) if ckpt_path else F5Settings.ckpt_path

    journal_params = {
        "ref_audio": reference_audio.name,
        "nfe_step": nfe,
        "speed": spd,
        "use_ruaccent": do_accent,
        "model": F5Settings.model_name,
        "text_chars": len(text),
    }

    with journal_run("tts", params=journal_params, prompt=text, tags=["f5-tts", "ru"]) as _je:
        # F5-TTS пишет в временную папку `output_dir`, не туда куда нужно —
        # поэтому даём ему temp и потом сами переносим. Имя файла фиксированное.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            output_name = "f5tts_out.wav"

            cli = _find_f5_tts_cli()
            # команда собирается строкой — многословные аргументы (`reference_text`, `synth_text`)
            # безопаснее прокидывать через список
            cmd = cli.split() + [
                "--model", F5Settings.model_name,
                "--ckpt_file", str(ckpt),
                "--vocab_file", str(F5Settings.vocab_path),
                "--ref_audio", str(reference_audio),
                "--ref_text", ref_text_prepared,
                "--gen_text", synth_text,
                "--output_dir", str(tmp_dir),
                "--output_file", output_name,
                "--nfe_step", str(nfe),
                "--cfg_strength", str(F5Settings.cfg_strength),
                "--speed", str(spd),
                "--cross_fade_duration", str(F5Settings.cross_fade_duration),
            ]
            if F5Settings.remove_silence:
                cmd.append("--remove_silence")

            print(f"[tts] F5-TTS синтез ({len(text)} символов)...")
            print(f"[tts] текст с ударениями: {synth_text[:120]}{'...' if len(synth_text) > 120 else ''}")

            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(F5_TTS_ROOT) if F5_TTS_ROOT.exists() else None,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                )
            except FileNotFoundError:
                raise RuntimeError(
                    "F5-TTS не установлен. Ставь: git clone https://github.com/SWivid/F5-TTS "
                    "&& cd F5-TTS && pip install -e ."
                )

            if result.returncode != 0:
                print("[tts] STDERR:\n" + (result.stderr or "")[-2000:])
                raise RuntimeError(f"F5-TTS упал (код {result.returncode})")

            src = tmp_dir / output_name
            if not src.exists():
                # fallback: ищем любой wav в tmp
                wavs = list(tmp_dir.glob("*.wav"))
                if not wavs:
                    raise RuntimeError(f"F5-TTS не создал WAV в {tmp_dir}")
                src = wavs[0]

            shutil.copy2(src, output_path)

        print(f"[tts] готово: {output_path}")
        _je.add_outputs([output_path])
        return output_path
