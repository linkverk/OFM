"""
Batch-режим: массовая генерация клипов по CSV-файлу.

Формат CSV (обязательные колонки):
    name, face, prompt, motion
Опциональные:
    text, ref_audio, ref_text, audio, upscale, res, smooth, rvc, pitch, seed

Пример CSV:
    name,face,prompt,motion,text,ref_audio,ref_text,upscale,smooth
    monday_cafe,ref.jpg,"woman in cafe","smiling softly","Всем привет!",v.wav,"Это тест",true,true
    monday_beach,ref.jpg,"woman at beach","hair in wind","Какая погода!",v.wav,"Это тест",true,true

Каждая строка = один полный прогон full-пайплайна.
Падение одной строки не останавливает батч — пишется error-лог.
"""
import csv
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR
from utils.comfy_client import ComfyClient
from pipeline.character_gen import generate_character
from pipeline.image_to_video import image_to_video
from pipeline.lip_sync import lip_sync
from pipeline.fps_interpolate import interpolate_fps
from pipeline.video_upscale import upscale_video
from pipeline.tts_voice import synthesize as tts_synthesize
from pipeline.voice_convert import convert as rvc_convert


REQUIRED_COLUMNS = {"name", "face", "prompt", "motion"}


def _bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "y", "+")


def _maybe_path(val: Optional[str]) -> Optional[Path]:
    if not val or not str(val).strip():
        return None
    return Path(str(val)).expanduser().resolve()


def _run_one(row: dict, client: ComfyClient, batch_dir: Path) -> dict:
    """
    Запускает full-пайплайн для одной строки CSV.
    Возвращает словарь с результатом/ошибкой.
    """
    name = row["name"].strip()
    t_start = time.time()
    log = {
        "name": name,
        "started_at": datetime.now().isoformat(),
        "status": "running",
    }

    try:
        face = _maybe_path(row["face"])
        if not face or not face.exists():
            raise FileNotFoundError(f"face not found: {face}")

        prompt = row["prompt"].strip()
        motion = row["motion"].strip()
        seed = int(row["seed"]) if row.get("seed") and str(row["seed"]).strip() else None

        # --- TTS если есть текст ---
        audio_path = _maybe_path(row.get("audio"))
        text = row.get("text", "").strip() if row.get("text") else ""

        if not audio_path and text:
            ref_audio = _maybe_path(row.get("ref_audio"))
            ref_text = row.get("ref_text", "").strip()
            if not ref_audio or not ref_text:
                raise ValueError("При наличии text нужны ref_audio и ref_text")
            print(f"  [tts] синтез '{text[:40]}...'")
            audio_path = tts_synthesize(
                text=text,
                reference_audio=ref_audio,
                reference_text=ref_text,
            )
            if _bool(row.get("rvc")):
                print(f"  [rvc] конверсия")
                pitch = int(row.get("pitch", 0) or 0)
                audio_path = rvc_convert(input_wav=audio_path, pitch=pitch)

        client.free_memory(unload_models=True, free_memory=True)

        # --- 1. Персонаж ---
        print(f"  [1/n] персонаж")
        chars = generate_character(
            face_ref=face, prompt=prompt, count=1, seed=seed, client=client,
        )
        current = chars[0]

        # --- 2. i2v ---
        print(f"  [2/n] i2v")
        client.free_memory(unload_models=True, free_memory=True)
        clips = image_to_video(
            image=current, motion_prompt=motion, seed=seed, client=client,
        )
        current = clips[0]

        # --- 3. lip sync если есть аудио ---
        if audio_path:
            print(f"  [3/n] lip sync")
            client.free_memory(unload_models=True, free_memory=True)
            lipped = lip_sync(video=current, audio=audio_path, seed=seed, client=client)
            if lipped:
                current = lipped[0]

        # --- 4. upscale ---
        if _bool(row.get("upscale")):
            res = int(row.get("res", 1280) or 1280)
            print(f"  [4/n] upscale → {res}p")
            client.free_memory(unload_models=True, free_memory=True)
            up = upscale_video(video=current, target_resolution=res, client=client)
            if up:
                current = up[0]

        # --- 5. smooth ---
        if _bool(row.get("smooth")):
            print(f"  [5/n] rife fps")
            client.free_memory(unload_models=True, free_memory=True)
            sm = interpolate_fps(video=current, multiplier=2, client=client)
            if sm:
                current = sm[0]

        # Копируем финальный клип в batch_dir с читаемым именем
        final = batch_dir / f"{name}.mp4"
        final.write_bytes(current.read_bytes())

        log["status"] = "success"
        log["output"] = str(final)
        log["elapsed_sec"] = round(time.time() - t_start, 1)
        print(f"  ✅ {name}: {log['elapsed_sec']}s → {final.name}")

    except Exception as e:
        log["status"] = "error"
        log["error"] = str(e)
        log["traceback"] = traceback.format_exc()
        log["elapsed_sec"] = round(time.time() - t_start, 1)
        print(f"  ❌ {name}: {e}")

    return log


def run_batch(csv_file: Path, stop_on_error: bool = False) -> Path:
    """
    Прогоняет все строки CSV через full-пайплайн.

    Args:
        csv_file: путь к .csv
        stop_on_error: True = остановиться на первой ошибке. False = продолжать.

    Returns:
        Path к папке с результатами этого батча.
    """
    csv_file = Path(csv_file)
    if not csv_file.exists():
        raise FileNotFoundError(csv_file)

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("CSV пустой")
        return OUTPUT_DIR

    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(f"В CSV не хватает колонок: {missing}")

    # Папка под батч
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = OUTPUT_DIR / "batches" / f"{csv_file.stem}_{ts}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    client = ComfyClient()
    if not client.is_alive():
        raise RuntimeError("ComfyUI не запущен")

    print(f"━━━ BATCH: {csv_file.name}, {len(rows)} строк ━━━")
    print(f"     Результаты: {batch_dir}\n")

    logs = []
    t_batch_start = time.time()

    for i, row in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] {row['name']}")
        print("─" * 60)
        log = _run_one(row, client, batch_dir)
        logs.append(log)

        # Сохраняем прогресс после каждой строки — если батч упадёт, видно что успели
        (batch_dir / "batch_log.json").write_text(
            json.dumps({
                "csv": str(csv_file),
                "started": ts,
                "total": len(rows),
                "completed": i,
                "runs": logs,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if log["status"] == "error" and stop_on_error:
            print("Stop on error: прерываю батч")
            break

    # Итог
    total_elapsed = round(time.time() - t_batch_start, 1)
    ok = sum(1 for l in logs if l["status"] == "success")
    err = sum(1 for l in logs if l["status"] == "error")

    print(f"\n{'═'*60}")
    print(f"BATCH ГОТОВ за {total_elapsed}s ({total_elapsed/60:.1f} мин)")
    print(f"  ✅ успешно: {ok}")
    print(f"  ❌ ошибок:  {err}")
    print(f"  📁 папка:   {batch_dir}")
    print(f"  📄 лог:     batch_log.json")
    print(f"{'═'*60}")

    return batch_dir


def write_csv_template(path: Path) -> None:
    """Пишет CSV-шаблон с примерами."""
    path = Path(path)
    path.write_text(
        "name,face,prompt,motion,text,ref_audio,ref_text,audio,upscale,res,smooth,rvc,pitch,seed\n"
        "cafe_morning,C:\\refs\\me.jpg,"
        '"woman in a cozy cafe, golden morning light",'
        '"softly smiling, slowly blinking","Доброе утро! Сегодня прекрасный день.",'
        "C:\\refs\\voice.wav,"
        '"Это референсная запись моего голоса для клонирования.",'
        ",true,1280,true,true,0,42\n"
        "beach_sunset,C:\\refs\\me.jpg,"
        '"woman on a tropical beach at sunset",'
        '"hair moving in the breeze, smiling gently","Закат такой красивый.",'
        "C:\\refs\\voice.wav,"
        '"Это референсная запись моего голоса для клонирования.",'
        ",true,1280,true,true,0,43\n",
        encoding="utf-8",
    )
    print(f"✅ Шаблон записан: {path}")
    print("   Открой в Excel или любом редакторе, заполни и прогоняй через:")
    print(f"   python main.py batch --csv {path.name}")
