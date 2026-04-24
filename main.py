"""
AI OFM Studio — локальный пайплайн для AI-инфлюенсера на RTX 4070 Super 12GB.

Команды:
  check                                               — проверка ComfyUI
  character --face ref.jpg --prompt "..." -n 5        — генерация персонажа
  i2v --image photo.png --motion "..."                — image → video
  lipsync --video clip.mp4 --audio speech.wav         — синхронизация губ
  rife --video clip.mp4                               — удвоение fps
  upscale --video clip.mp4 --res 1280                 — апскейл SeedVR2
  tts --text "..." --ref-audio v.wav --ref-text "..." — F5-TTS русский голос
  rvc --input a.wav --pitch 0                         — RVC voice conversion
  full  --face ref.jpg --prompt "..." --motion "..."
        [--text "..." --ref-audio v.wav --ref-text "..." [--rvc]]
        [--audio готовое.wav]  [--upscale] [--smooth]

Пример «всё за один раз»:
  python main.py full --face me.jpg \\
    --prompt "woman in cafe, golden hour" \\
    --motion "smiling softly, slowly turning head" \\
    --text "Привет! Сегодня расскажу как я провела этот день." \\
    --ref-audio voice_ref.wav \\
    --ref-text "Это референсная запись моего голоса." \\
    --rvc --upscale --smooth
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

from utils.comfy_client import ComfyClient
from pipeline.character_gen import generate_character
from pipeline.character_edit import edit_character
from pipeline.image_to_video import image_to_video
from pipeline.video_upscale import upscale_video
from pipeline.lip_sync import lip_sync
from pipeline.fps_interpolate import interpolate_fps
from pipeline.tts_voice import synthesize as tts_synthesize
from pipeline.voice_convert import convert as rvc_convert
from pipeline.lora_training import prepare_lora_dataset
from pipeline.batch_runner import run_batch, write_csv_template


# ---------- helpers ----------

def _require_file(path_str: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    if not p.exists():
        print(f"❌ Нет файла: {p}")
        sys.exit(1)
    return p


def _require_comfy() -> ComfyClient:
    client = ComfyClient()
    if not client.is_alive():
        print("❌ ComfyUI не отвечает.")
        print("   Запусти в другом окне: cd ComfyUI && python main.py --use-sage-attention --fast")
        sys.exit(1)
    return client


# ---------- команды ----------

def cmd_check(_args):
    client = ComfyClient()
    if not client.is_alive():
        print("❌ ComfyUI не отвечает по", client.server)
        print("\nЗапусти его:")
        print("  cd C:\\ComfyUI")
        print("  python main.py --use-sage-attention --fast")
        return 1
    print("✅ ComfyUI работает")
    stats = client.get_system_stats()
    sys_info = stats.get("system", {})
    print(f"   Python: {sys_info.get('python_version', '?').split()[0]}")
    print(f"   OS: {sys_info.get('os', '?')}")
    for dev in stats.get("devices", []):
        name = dev.get("name", "?")
        vram_total = dev.get("vram_total", 0) / (1024**3)
        vram_free = dev.get("vram_free", 0) / (1024**3)
        print(f"   GPU: {name}")
        print(f"   VRAM: {vram_free:.1f} / {vram_total:.1f} GB свободно")
        if vram_total < 11:
            print(f"   ⚠️  Это меньше 12 GB — настройки из config.py могут быть агрессивны")
    return 0


def cmd_character(args):
    face = _require_file(args.face)
    results = generate_character(
        face_ref=face,
        prompt=args.prompt,
        negative=args.negative,
        count=args.count,
        seed=args.seed,
    )
    print(f"\n✅ Сгенерировано {len(results)}:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_i2v(args):
    img = _require_file(args.image)
    results = image_to_video(
        image=img,
        motion_prompt=args.motion,
        negative=args.negative,
        seed=args.seed,
        frames=args.frames,
    )
    print(f"\n✅ Клипы:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_lipsync(args):
    vid = _require_file(args.video)
    aud = _require_file(args.audio)
    results = lip_sync(
        video=vid,
        audio=aud,
        seed=args.seed,
        steps=args.steps,
        lips_expression=args.lips_expression,
    )
    print(f"\n✅ Lip sync:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_rife(args):
    vid = _require_file(args.video)
    mult = 3 if args.x3 else 2
    results = interpolate_fps(video=vid, multiplier=mult, output_fps=args.fps)
    print(f"\n✅ Интерполированные клипы:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_upscale(args):
    vid = _require_file(args.video)
    results = upscale_video(video=vid, target_resolution=args.res, seed=args.seed)
    print(f"\n✅ Апскейлено:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_tts(args):
    ref = _require_file(args.ref_audio)
    out = tts_synthesize(
        text=args.text,
        reference_audio=ref,
        reference_text=args.ref_text,
        speed=args.speed,
        nfe_step=args.nfe,
    )
    if args.rvc:
        out = rvc_convert(input_wav=out, pitch=args.pitch)
    print(f"\n✅ Аудио: {out}")
    return 0


def cmd_rvc(args):
    inp = _require_file(args.input)
    out = rvc_convert(input_wav=inp, pitch=args.pitch)
    print(f"\n✅ RVC конверсия: {out}")
    return 0


def cmd_kontext(args):
    ref = _require_file(args.ref)
    results = edit_character(
        reference_image=ref,
        edit_prompt=args.prompt,
        count=args.count,
        seed=args.seed,
    )
    print(f"\n✅ {len(results)} вариаций:")
    for p in results:
        print(f"   {p}")
    return 0


def cmd_lora_dataset(args):
    ref = _require_file(args.ref)
    prepare_lora_dataset(
        reference_image=ref,
        lora_name=args.name,
        count=args.count,
        skip_generation=args.skip_generation,
        seed=args.seed,
    )
    return 0


def cmd_batch(args):
    csv = _require_file(args.csv)
    run_batch(csv_file=csv, stop_on_error=args.stop_on_error)
    return 0


def cmd_batch_template(args):
    write_csv_template(Path(args.out))
    return 0


def cmd_full(args):
    """
    Полный пайплайн: фото → персонаж → i2v → [lipsync] → [upscale] → [rife]

    Три режима озвучки:
      1) без голоса  — просто клип
      2) --audio X   — готовый WAV/MP3
      3) --text "..." --ref-audio Y --ref-text "..."
                     — генерация голоса на лету через F5-TTS
    """
    face = _require_file(args.face)

    # Подготавливаем аудио — либо берём готовое, либо синтезируем
    audio: Optional[Path] = None
    if args.audio:
        audio = _require_file(args.audio)
    elif args.text:
        if not args.ref_audio or not args.ref_text:
            print("❌ При --text нужны также --ref-audio и --ref-text")
            return 1
        ref = _require_file(args.ref_audio)
        print(f"\n{'━'*60}\nSTEP 0: синтез русской речи (F5-TTS)\n{'━'*60}")
        audio = tts_synthesize(
            text=args.text,
            reference_audio=ref,
            reference_text=args.ref_text,
            speed=args.speed,
        )
        if args.rvc:
            print(f"\n  + RVC пост-процессинг")
            audio = rvc_convert(input_wav=audio, pitch=args.pitch)

    client = _require_comfy()

    # Важно: TTS мог оставить модели в VRAM, а нас впереди ждёт Flux.
    # Попросим ComfyUI принудительно начать с чистого VRAM.
    client.free_memory(unload_models=True, free_memory=True)

    total_steps = 2 + int(bool(audio)) + int(args.upscale) + int(args.smooth)
    step = [1]

    def banner(title: str):
        print(f"\n{'━'*60}\nSTEP {step[0]}/{total_steps}: {title}\n{'━'*60}")
        step[0] += 1

    # --- STEP 1: персонаж ---
    banner("генерация персонажа (Flux + PuLID)")
    chars = generate_character(
        face_ref=face, prompt=args.prompt, count=1, seed=args.seed, client=client,
    )
    if not chars:
        print("❌ не получилось сгенерировать персонажа")
        return 1
    current_image = chars[0]

    # --- STEP 2: i2v ---
    banner("image → video (Wan 2.2 + Lightning)")
    client.free_memory(unload_models=True, free_memory=True)
    clips = image_to_video(
        image=current_image, motion_prompt=args.motion, seed=args.seed, client=client,
    )
    if not clips:
        print("❌ i2v не удалось")
        return 1
    current_video = clips[0]

    # --- STEP 3 (опц.): lip sync ---
    if audio:
        banner(f"lip sync под {audio.name}")
        client.free_memory(unload_models=True, free_memory=True)
        lipped = lip_sync(video=current_video, audio=audio, seed=args.seed, client=client)
        if lipped:
            current_video = lipped[0]

    # --- STEP 4 (опц.): upscale ---
    if args.upscale:
        banner(f"апскейл SeedVR2 → {args.res}p")
        client.free_memory(unload_models=True, free_memory=True)
        up = upscale_video(video=current_video, target_resolution=args.res, client=client)
        if up:
            current_video = up[0]

    # --- STEP 5 (опц.): rife ---
    if args.smooth:
        banner(f"интерполяция fps x{3 if args.x3 else 2}")
        client.free_memory(unload_models=True, free_memory=True)
        smoothed = interpolate_fps(
            video=current_video,
            multiplier=3 if args.x3 else 2,
            client=client,
        )
        if smoothed:
            current_video = smoothed[0]

    print(f"\n{'═'*60}\n✅ ФИНАЛ: {current_video}\n{'═'*60}")
    return 0


# ---------- CLI ----------

def build_parser():
    p = argparse.ArgumentParser(
        prog="ai_ofm",
        description="AI OFM Studio — RTX 4070 Super 12GB локальный пайплайн",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="проверить соединение с ComfyUI")

    pc = sub.add_parser("character", help="генерация персонажа")
    pc.add_argument("--face", required=True, help="референсное фото лица")
    pc.add_argument("--prompt", required=True, help="описание сцены")
    pc.add_argument("--negative", default=None)
    pc.add_argument("-n", "--count", type=int, default=1)
    pc.add_argument("--seed", type=int, default=None)

    pi = sub.add_parser("i2v", help="image → video")
    pi.add_argument("--image", required=True)
    pi.add_argument("--motion", required=True, help="описание движения")
    pi.add_argument("--negative", default=None)
    pi.add_argument("--frames", type=int, default=None, help="число кадров (81 = 5 сек)")
    pi.add_argument("--seed", type=int, default=None)

    pl = sub.add_parser("lipsync", help="lip sync через LatentSync 1.6")
    pl.add_argument("--video", required=True)
    pl.add_argument("--audio", required=True, help="WAV/MP3 дорожка")
    pl.add_argument("--seed", type=int, default=None)
    pl.add_argument("--steps", type=int, default=None, help="inference_steps 20-50")
    pl.add_argument("--lips-expression", type=float, default=None,
                    dest="lips_expression", help="1.5-2.5 речь, 2.0-3.0 эмоции")

    pr = sub.add_parser("rife", help="интерполяция fps (24→48/72)")
    pr.add_argument("--video", required=True)
    pr.add_argument("--x3", action="store_true", help="утроить fps вместо удвоения")
    pr.add_argument("--fps", type=int, default=None, help="целевой fps в итоговый mp4")

    pu = sub.add_parser("upscale", help="апскейл видео через SeedVR2")
    pu.add_argument("--video", required=True)
    pu.add_argument("--res", type=int, default=1280, help="целевая ширина (720/1080/1280/1440)")
    pu.add_argument("--seed", type=int, default=None)

    pt = sub.add_parser("tts", help="синтез русской речи через F5-TTS")
    pt.add_argument("--text", required=True, help="что сказать (рус)")
    pt.add_argument("--ref-audio", required=True, dest="ref_audio",
                    help="референс голоса (3-10 сек WAV)")
    pt.add_argument("--ref-text", required=True, dest="ref_text",
                    help="точная транскрипция референса")
    pt.add_argument("--speed", type=float, default=1.0, help="скорость 0.8-1.2")
    pt.add_argument("--nfe", type=int, default=None, help="NFE шаги (16-32)")
    pt.add_argument("--rvc", action="store_true", help="пропустить через RVC")
    pt.add_argument("--pitch", type=int, default=0, help="семитоны для RVC")

    prv = sub.add_parser("rvc", help="RVC voice conversion готового аудио")
    prv.add_argument("--input", required=True, help="входной WAV")
    prv.add_argument("--pitch", type=int, default=0)

    pk = sub.add_parser("kontext", help="Flux Kontext — edit-based вариации персонажа")
    pk.add_argument("--ref", required=True, help="эталонный кадр")
    pk.add_argument("--prompt", required=True, help="что поменять (англ)")
    pk.add_argument("-n", "--count", type=int, default=1)
    pk.add_argument("--seed", type=int, default=None)

    pld = sub.add_parser("lora-dataset", help="собрать датасет для FluxGym LoRA")
    pld.add_argument("--ref", required=True, help="эталонный кадр")
    pld.add_argument("--name", required=True, help="имя будущей LoRA")
    pld.add_argument("-n", "--count", type=int, default=30, help="сколько вариаций")
    pld.add_argument("--skip-generation", action="store_true", dest="skip_generation",
                     help="пропустить генерацию (если датасет уже собран)")
    pld.add_argument("--seed", type=int, default=None)

    pb = sub.add_parser("batch", help="массовый прогон по CSV")
    pb.add_argument("--csv", required=True)
    pb.add_argument("--stop-on-error", action="store_true", dest="stop_on_error")

    pbt = sub.add_parser("batch-template", help="создать CSV-шаблон")
    pbt.add_argument("--out", default="batch_template.csv")

    pf = sub.add_parser("full", help="полный пайплайн")
    pf.add_argument("--face", required=True)
    pf.add_argument("--prompt", required=True)
    pf.add_argument("--motion", required=True)
    # вариант А — готовое аудио
    pf.add_argument("--audio", default=None, help="готовый WAV/MP3 для lip sync")
    # вариант Б — синтезировать на лету
    pf.add_argument("--text", default=None, help="синтезировать голос из этого текста")
    pf.add_argument("--ref-audio", dest="ref_audio", default=None,
                    help="референс голоса для TTS (нужен при --text)")
    pf.add_argument("--ref-text", dest="ref_text", default=None,
                    help="транскрипция --ref-audio (нужна при --text)")
    pf.add_argument("--speed", type=float, default=1.0)
    pf.add_argument("--rvc", action="store_true", help="прогнать TTS через RVC")
    pf.add_argument("--pitch", type=int, default=0, help="RVC pitch")
    # post-обработка видео
    pf.add_argument("--upscale", action="store_true", help="SeedVR2 апскейл в конце")
    pf.add_argument("--res", type=int, default=1280)
    pf.add_argument("--smooth", action="store_true", help="RIFE интерполяция в конце")
    pf.add_argument("--x3", action="store_true", help="при --smooth: x3 вместо x2")
    pf.add_argument("--seed", type=int, default=None)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    handlers = {
        "check": cmd_check,
        "character": cmd_character,
        "kontext": cmd_kontext,
        "i2v": cmd_i2v,
        "lipsync": cmd_lipsync,
        "rife": cmd_rife,
        "upscale": cmd_upscale,
        "tts": cmd_tts,
        "rvc": cmd_rvc,
        "full": cmd_full,
        "lora-dataset": cmd_lora_dataset,
        "batch": cmd_batch,
        "batch-template": cmd_batch_template,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
