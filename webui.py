"""
Gradio веб-интерфейс для AI OFM Studio.

Запуск:
    python webui.py

Откроется на http://127.0.0.1:7861 (отличается от ComfyUI:8188 и FluxGym:7860).

Что есть:
- вкладка Character: Flux + PuLID
- вкладка Kontext: редактирование существующего кадра
- вкладка I2V: image → video
- вкладка Lip Sync
- вкладка TTS: русский голос
- вкладка Upscale
- вкладка Full Pipeline: всё одной кнопкой
- вкладка LoRA Dataset: сборка датасета
- вкладка Batch: прогон CSV
"""
import sys
from pathlib import Path

try:
    import gradio as gr
except ImportError:
    print("Gradio не установлен. pip install gradio")
    sys.exit(1)

from config import OUTPUT_DIR
from utils.comfy_client import ComfyClient
from pipeline.character_gen import generate_character
from pipeline.character_edit import edit_character
from pipeline.image_to_video import image_to_video
from pipeline.lip_sync import lip_sync
from pipeline.fps_interpolate import interpolate_fps
from pipeline.video_upscale import upscale_video
from pipeline.tts_voice import synthesize as tts_synthesize
from pipeline.voice_convert import convert as rvc_convert
from pipeline.lora_training import prepare_lora_dataset
from pipeline.batch_runner import run_batch


# ---- Обёртки для Gradio (каждая возвращает файл(ы) и текстовый статус) ----

def _safe(fn):
    """Декоратор: ловим исключения и показываем их в UI, а не рушим сервер."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            import traceback
            return None, f"❌ ОШИБКА: {e}\n\n{traceback.format_exc()}"
    return wrapper


def _path_from_gradio(obj) -> Path:
    """Gradio отдаёт либо str либо {'name': '...'} в зависимости от версии."""
    if obj is None:
        return None
    if isinstance(obj, (str, Path)):
        return Path(obj)
    if isinstance(obj, dict) and "name" in obj:
        return Path(obj["name"])
    return Path(str(obj))


@_safe
def ui_character(face_file, prompt, count, seed):
    face = _path_from_gradio(face_file)
    if not face or not face.exists():
        return None, "Загрузи референс лица"
    results = generate_character(
        face_ref=face, prompt=prompt,
        count=int(count), seed=int(seed) if seed else None,
    )
    if not results:
        return None, "Ничего не сгенерировано"
    return [str(p) for p in results], f"✅ {len(results)} фото в {OUTPUT_DIR}"


@_safe
def ui_kontext(ref_file, edit_prompt, count, seed):
    ref = _path_from_gradio(ref_file)
    if not ref or not ref.exists():
        return None, "Загрузи эталонный кадр"
    results = edit_character(
        reference_image=ref, edit_prompt=edit_prompt,
        count=int(count), seed=int(seed) if seed else None,
    )
    return [str(p) for p in results], f"✅ {len(results)} вариаций"


@_safe
def ui_i2v(image_file, motion, frames, seed):
    img = _path_from_gradio(image_file)
    if not img or not img.exists():
        return None, "Загрузи изображение"
    results = image_to_video(
        image=img, motion_prompt=motion,
        frames=int(frames) if frames else None,
        seed=int(seed) if seed else None,
    )
    return str(results[0]) if results else None, f"✅ {results[0].name if results else ''}"


@_safe
def ui_lipsync(video_file, audio_file, steps, lips_expr, seed):
    vid = _path_from_gradio(video_file)
    aud = _path_from_gradio(audio_file)
    if not vid or not aud:
        return None, "Нужны и видео, и аудио"
    results = lip_sync(
        video=vid, audio=aud,
        steps=int(steps) if steps else None,
        lips_expression=float(lips_expr) if lips_expr else None,
        seed=int(seed) if seed else None,
    )
    return str(results[0]) if results else None, f"✅ {results[0].name if results else ''}"


@_safe
def ui_tts(text, ref_audio_file, ref_text, speed, use_rvc, pitch):
    ref = _path_from_gradio(ref_audio_file)
    if not ref:
        return None, "Загрузи референс голоса"
    out = tts_synthesize(
        text=text, reference_audio=ref, reference_text=ref_text,
        speed=float(speed) if speed else 1.0,
    )
    if use_rvc:
        out = rvc_convert(input_wav=out, pitch=int(pitch))
    return str(out), f"✅ {out.name}"


@_safe
def ui_upscale(video_file, res, seed):
    vid = _path_from_gradio(video_file)
    if not vid:
        return None, "Загрузи видео"
    results = upscale_video(
        video=vid, target_resolution=int(res),
        seed=int(seed) if seed else None,
    )
    return str(results[0]) if results else None, "✅ готово"


@_safe
def ui_rife(video_file, x3):
    vid = _path_from_gradio(video_file)
    if not vid:
        return None, "Загрузи видео"
    results = interpolate_fps(video=vid, multiplier=3 if x3 else 2)
    return str(results[0]) if results else None, "✅ готово"


@_safe
def ui_full(
    face_file, prompt, motion,
    text, ref_audio_file, ref_text, use_rvc, pitch, speed,
    do_upscale, res, do_smooth, seed,
):
    face = _path_from_gradio(face_file)
    if not face or not face.exists():
        return None, "Нужен референс лица"

    client = ComfyClient()
    if not client.is_alive():
        return None, "ComfyUI не запущен"

    # TTS
    audio_path = None
    if text:
        ref = _path_from_gradio(ref_audio_file)
        if not ref or not ref_text:
            return None, "Для синтеза голоса нужны ref_audio и ref_text"
        audio_path = tts_synthesize(
            text=text, reference_audio=ref, reference_text=ref_text,
            speed=float(speed),
        )
        if use_rvc:
            audio_path = rvc_convert(input_wav=audio_path, pitch=int(pitch))

    client.free_memory(unload_models=True, free_memory=True)

    seed_int = int(seed) if seed else None

    # 1. Персонаж
    chars = generate_character(
        face_ref=face, prompt=prompt, count=1, seed=seed_int, client=client,
    )
    current = chars[0]

    # 2. I2V
    client.free_memory(unload_models=True, free_memory=True)
    clips = image_to_video(
        image=current, motion_prompt=motion, seed=seed_int, client=client,
    )
    current = clips[0]

    # 3. Lip sync
    if audio_path:
        client.free_memory(unload_models=True, free_memory=True)
        lipped = lip_sync(video=current, audio=audio_path, seed=seed_int, client=client)
        if lipped:
            current = lipped[0]

    # 4. Upscale
    if do_upscale:
        client.free_memory(unload_models=True, free_memory=True)
        up = upscale_video(video=current, target_resolution=int(res), client=client)
        if up:
            current = up[0]

    # 5. Smooth
    if do_smooth:
        client.free_memory(unload_models=True, free_memory=True)
        sm = interpolate_fps(video=current, multiplier=2, client=client)
        if sm:
            current = sm[0]

    return str(current), f"✅ ФИНАЛ: {current.name}"


@_safe
def ui_lora_dataset(ref_file, lora_name, count, seed):
    ref = _path_from_gradio(ref_file)
    if not ref:
        return "Нужен референс"
    dataset_dir = prepare_lora_dataset(
        reference_image=ref,
        lora_name=lora_name or "unnamed",
        count=int(count),
        seed=int(seed) if seed else None,
    )
    return f"✅ Датасет в: {dataset_dir}\nДальше — FluxGym (инструкции в консоли)"


@_safe
def ui_batch(csv_file):
    path = _path_from_gradio(csv_file)
    if not path or not path.exists():
        return "Загрузи CSV"
    batch_dir = run_batch(csv_file=path)
    return f"✅ Батч в: {batch_dir}"


@_safe
def ui_check():
    client = ComfyClient()
    if not client.is_alive():
        return "❌ ComfyUI не отвечает. Запусти его: python main.py --use-sage-attention --fast"
    stats = client.get_system_stats()
    lines = ["✅ ComfyUI работает"]
    for dev in stats.get("devices", []):
        total = dev.get("vram_total", 0) / (1024**3)
        free = dev.get("vram_free", 0) / (1024**3)
        lines.append(f"  {dev.get('name', '?')}: {free:.1f} / {total:.1f} GB свободно")
    return "\n".join(lines)


# ---- Сборка UI ----

def build_ui():
    with gr.Blocks(title="AI OFM Studio", theme=gr.themes.Soft()) as app:
        gr.Markdown("# AI OFM Studio")
        gr.Markdown("Локальный пайплайн на **RTX 4070 Super 12GB / R7 7800X3D / 32GB RAM**")

        # --- Проверка подключения ---
        with gr.Row():
            check_btn = gr.Button("Проверить ComfyUI")
            check_out = gr.Textbox(label="Статус", lines=3)
        check_btn.click(ui_check, outputs=check_out)

        with gr.Tabs():
            # ====== FULL PIPELINE ======
            with gr.Tab("🎬 Full Pipeline"):
                gr.Markdown("От фото + текста — до говорящего клипа одной кнопкой.")
                with gr.Row():
                    with gr.Column():
                        f_face = gr.File(label="Референс лица", file_types=["image"])
                        f_prompt = gr.Textbox(
                            label="Описание сцены",
                            value="woman in a cozy cafe, soft morning light, cinematic",
                            lines=2,
                        )
                        f_motion = gr.Textbox(
                            label="Движение",
                            value="softly smiling, slowly turning head toward camera",
                            lines=2,
                        )
                        with gr.Accordion("🎙️ Голос (опционально)", open=False):
                            f_text = gr.Textbox(label="Текст для озвучки (рус)", lines=3)
                            f_ref_audio = gr.File(label="Референс голоса WAV", file_types=["audio"])
                            f_ref_text = gr.Textbox(label="Транскрипция референса", lines=2)
                            f_speed = gr.Slider(0.8, 1.2, value=1.0, step=0.05, label="Скорость")
                            f_rvc = gr.Checkbox(label="Прогнать через RVC")
                            f_pitch = gr.Slider(-12, 12, value=0, step=1, label="RVC pitch")
                        with gr.Accordion("📺 Post-обработка", open=True):
                            f_upscale = gr.Checkbox(label="Апскейл SeedVR2", value=True)
                            f_res = gr.Dropdown([720, 1080, 1280, 1440], value=1280, label="Разрешение")
                            f_smooth = gr.Checkbox(label="RIFE 24→48 fps", value=True)
                        f_seed = gr.Number(label="Seed (опц.)", precision=0, value=None)
                        f_btn = gr.Button("🚀 Запустить", variant="primary")
                    with gr.Column():
                        f_video = gr.Video(label="Результат")
                        f_status = gr.Textbox(label="Статус", lines=4)
                f_btn.click(
                    ui_full,
                    inputs=[f_face, f_prompt, f_motion,
                            f_text, f_ref_audio, f_ref_text, f_rvc, f_pitch, f_speed,
                            f_upscale, f_res, f_smooth, f_seed],
                    outputs=[f_video, f_status],
                )

            # ====== CHARACTER ======
            with gr.Tab("👤 Персонаж"):
                with gr.Row():
                    with gr.Column():
                        c_face = gr.File(label="Референс лица", file_types=["image"])
                        c_prompt = gr.Textbox(label="Описание сцены", lines=2)
                        c_count = gr.Slider(1, 10, value=3, step=1, label="Вариантов")
                        c_seed = gr.Number(label="Seed", precision=0, value=None)
                        c_btn = gr.Button("Сгенерировать", variant="primary")
                    with gr.Column():
                        c_gallery = gr.Gallery(label="Результаты", columns=3, height=500)
                        c_status = gr.Textbox(label="Статус")
                c_btn.click(ui_character, inputs=[c_face, c_prompt, c_count, c_seed],
                            outputs=[c_gallery, c_status])

            # ====== KONTEXT ======
            with gr.Tab("✏️ Kontext (edit)"):
                gr.Markdown("Бери эталон и меняй сцену/позу/одежду одним промптом.")
                with gr.Row():
                    with gr.Column():
                        k_ref = gr.File(label="Эталонный кадр", file_types=["image"])
                        k_prompt = gr.Textbox(
                            label="Что поменять",
                            value="same person, wearing a red evening dress, luxury hotel lobby",
                            lines=2,
                        )
                        k_count = gr.Slider(1, 10, value=3, step=1, label="Вариантов")
                        k_seed = gr.Number(label="Seed", precision=0, value=None)
                        k_btn = gr.Button("Редактировать", variant="primary")
                    with gr.Column():
                        k_gallery = gr.Gallery(label="Результаты", columns=3, height=500)
                        k_status = gr.Textbox(label="Статус")
                k_btn.click(ui_kontext, inputs=[k_ref, k_prompt, k_count, k_seed],
                            outputs=[k_gallery, k_status])

            # ====== I2V ======
            with gr.Tab("🎥 I2V"):
                with gr.Row():
                    with gr.Column():
                        i_img = gr.File(label="Стартовый кадр", file_types=["image"])
                        i_motion = gr.Textbox(label="Описание движения", lines=2)
                        i_frames = gr.Slider(33, 121, value=81, step=4,
                                             label="Кадров (81=5сек@16fps)")
                        i_seed = gr.Number(label="Seed", precision=0, value=None)
                        i_btn = gr.Button("Анимировать", variant="primary")
                    with gr.Column():
                        i_video = gr.Video(label="Клип")
                        i_status = gr.Textbox(label="Статус")
                i_btn.click(ui_i2v, inputs=[i_img, i_motion, i_frames, i_seed],
                            outputs=[i_video, i_status])

            # ====== LIP SYNC ======
            with gr.Tab("👄 Lip Sync"):
                with gr.Row():
                    with gr.Column():
                        l_vid = gr.File(label="Видео", file_types=["video"])
                        l_aud = gr.File(label="Аудио", file_types=["audio"])
                        l_steps = gr.Slider(15, 50, value=25, step=1, label="Inference steps")
                        l_expr = gr.Slider(1.0, 3.0, value=2.0, step=0.1, label="Lips expression")
                        l_seed = gr.Number(label="Seed", precision=0, value=None)
                        l_btn = gr.Button("Синхронизировать", variant="primary")
                    with gr.Column():
                        l_video = gr.Video(label="Результат")
                        l_status = gr.Textbox(label="Статус")
                l_btn.click(ui_lipsync,
                            inputs=[l_vid, l_aud, l_steps, l_expr, l_seed],
                            outputs=[l_video, l_status])

            # ====== TTS ======
            with gr.Tab("🎙️ TTS (рус)"):
                with gr.Row():
                    with gr.Column():
                        t_text = gr.Textbox(label="Текст (рус)", lines=4)
                        t_ref = gr.File(label="Референс голоса", file_types=["audio"])
                        t_ref_text = gr.Textbox(label="Транскрипция референса", lines=2)
                        t_speed = gr.Slider(0.8, 1.2, value=1.0, step=0.05, label="Скорость")
                        t_rvc = gr.Checkbox(label="RVC пост-процессинг")
                        t_pitch = gr.Slider(-12, 12, value=0, step=1, label="RVC pitch")
                        t_btn = gr.Button("Синтезировать", variant="primary")
                    with gr.Column():
                        t_audio = gr.Audio(label="Результат")
                        t_status = gr.Textbox(label="Статус")
                t_btn.click(ui_tts,
                            inputs=[t_text, t_ref, t_ref_text, t_speed, t_rvc, t_pitch],
                            outputs=[t_audio, t_status])

            # ====== UPSCALE / RIFE ======
            with gr.Tab("⬆️ Upscale + RIFE"):
                gr.Markdown("### SeedVR2 upscale")
                with gr.Row():
                    with gr.Column():
                        u_vid = gr.File(label="Видео", file_types=["video"])
                        u_res = gr.Dropdown([720, 1080, 1280, 1440], value=1280, label="Разрешение")
                        u_seed = gr.Number(label="Seed", precision=0, value=None)
                        u_btn = gr.Button("Апскейл")
                    with gr.Column():
                        u_video = gr.Video(label="Результат")
                        u_status = gr.Textbox(label="Статус")
                u_btn.click(ui_upscale, inputs=[u_vid, u_res, u_seed],
                            outputs=[u_video, u_status])

                gr.Markdown("### RIFE интерполяция")
                with gr.Row():
                    with gr.Column():
                        r_vid = gr.File(label="Видео", file_types=["video"])
                        r_x3 = gr.Checkbox(label="x3 (24→72) вместо x2 (24→48)")
                        r_btn = gr.Button("Интерполировать")
                    with gr.Column():
                        r_video = gr.Video(label="Результат")
                        r_status = gr.Textbox(label="Статус")
                r_btn.click(ui_rife, inputs=[r_vid, r_x3], outputs=[r_video, r_status])

            # ====== LORA DATASET ======
            with gr.Tab("📚 LoRA Dataset"):
                gr.Markdown(
                    "Собирает датасет для тренировки собственного LoRA. "
                    "Сама тренировка идёт во FluxGym (инструкции напечатаются в консоли)."
                )
                with gr.Row():
                    with gr.Column():
                        ld_ref = gr.File(label="Эталонный кадр персонажа", file_types=["image"])
                        ld_name = gr.Textbox(label="Имя LoRA", value="my_character_v1")
                        ld_count = gr.Slider(15, 50, value=30, step=1, label="Вариаций")
                        ld_seed = gr.Number(label="Seed", precision=0, value=None)
                        ld_btn = gr.Button("Собрать датасет", variant="primary")
                    with gr.Column():
                        ld_status = gr.Textbox(label="Статус", lines=12)
                ld_btn.click(ui_lora_dataset,
                             inputs=[ld_ref, ld_name, ld_count, ld_seed],
                             outputs=[ld_status])

            # ====== BATCH ======
            with gr.Tab("📋 Batch"):
                gr.Markdown(
                    "Загрузи CSV с колонками: name, face, prompt, motion "
                    "(+ опционально text, ref_audio, ref_text, upscale, smooth...)"
                )
                with gr.Row():
                    with gr.Column():
                        b_csv = gr.File(label="CSV", file_types=[".csv"])
                        b_btn = gr.Button("Запустить батч", variant="primary")
                    with gr.Column():
                        b_status = gr.Textbox(label="Статус", lines=12)
                b_btn.click(ui_batch, inputs=[b_csv], outputs=[b_status])

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7861,
        show_error=True,
        inbrowser=True,
    )
