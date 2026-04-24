"""
Скачивание всех моделей одним скриптом через huggingface_hub.

Использование:
    pip install huggingface_hub
    python download_models.py --comfyui C:\ai-ofm\ComfyUI --f5tts C:\ai-ofm\F5-TTS

Всего скачивается ~50 GB. На быстром канале — 30-60 минут.

Если HF требует логин (для Flux-dev) — сначала:
    huggingface-cli login

Можно пропускать категории:
    --skip-flux          — не качать Flux.1-dev и PuLID
    --skip-wan           — не качать Wan 2.2
    --skip-seedvr2       — не качать SeedVR2
    --skip-f5tts         — не качать русский голос
"""
import argparse
import sys
from pathlib import Path
from typing import Optional


def _require_hf():
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
        return hf_hub_download, list_repo_files
    except ImportError:
        print("❌ huggingface_hub не установлен. pip install huggingface_hub")
        sys.exit(1)


def download(
    repo_id: str,
    filename: str,
    target_dir: Path,
    subfolder: Optional[str] = None,
    rename_to: Optional[str] = None,
    fallback_patterns: Optional[list[str]] = None,
) -> Path:
    """
    Скачивает один файл с HF и кладёт в target_dir под нужным именем.
    Если точное имя filename не найдено (404) — пробует fallback_patterns
    как подстроки для поиска в list_repo_files.
    """
    hf_hub_download, list_repo_files = _require_hf()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    final_name = rename_to or filename
    final_path = target_dir / final_name
    if final_path.exists():
        print(f"  ✓ {final_name} уже есть")
        return final_path

    # Пробуем точное имя
    attempts = [filename]
    # Добавляем fallback паттерны
    if fallback_patterns:
        try:
            all_files = list_repo_files(repo_id)
            for pattern in fallback_patterns:
                for f in all_files:
                    name = Path(f).name
                    if pattern.lower() in name.lower() and f not in attempts:
                        attempts.append(f)
        except Exception as e:
            print(f"  ⚠️  не удалось получить список файлов {repo_id}: {e}")

    last_err = None
    for attempt_name in attempts:
        try:
            print(f"  ↓ {repo_id}/{attempt_name}")
            path = hf_hub_download(
                repo_id=repo_id,
                filename=attempt_name,
                subfolder=subfolder,
                local_dir=str(target_dir),
            )
            path = Path(path)
            if rename_to and path.name != rename_to:
                new_path = target_dir / rename_to
                if new_path.exists():
                    new_path.unlink()
                path.rename(new_path)
                path = new_path
            return path
        except Exception as e:
            last_err = e
            # 404 — пробуем следующий в attempts
            if "404" in str(e) or "Not Found" in str(e):
                print(f"    [404] {attempt_name}, пробую следующий вариант...")
                continue
            raise  # другие ошибки — не swallowим

    raise RuntimeError(
        f"Не удалось скачать из {repo_id}. Пробовал: {attempts}\n"
        f"Последняя ошибка: {last_err}\n"
        f"Открой https://huggingface.co/{repo_id}/tree/main и найди нужный файл вручную."
    )


def main():
    parser = argparse.ArgumentParser(description="Скачивание всех моделей для AI OFM Studio")
    parser.add_argument("--comfyui", default=None, help="путь к ComfyUI")
    parser.add_argument("--f5tts", default=None, help="путь к F5-TTS")
    parser.add_argument("--skip-flux", action="store_true")
    parser.add_argument("--skip-wan", action="store_true")
    parser.add_argument("--skip-seedvr2", action="store_true")
    parser.add_argument("--skip-f5tts", action="store_true")
    parser.add_argument("--skip-face-restore", action="store_true")
    parser.add_argument("--skip-kontext", action="store_true")
    parser.add_argument("--list", metavar="REPO",
                        help="вместо скачивания — показать файлы в репо HF (например 'city96/FLUX.1-dev-gguf')")
    args = parser.parse_args()

    # --list = диагностический режим
    if args.list:
        _, list_repo_files = _require_hf()
        print(f"Файлы в {args.list}:")
        for f in sorted(list_repo_files(args.list)):
            print(f"  {f}")
        return

    if not args.comfyui:
        print("❌ --comfyui обязателен (если не используешь --list)")
        sys.exit(1)

    comfy = Path(args.comfyui).expanduser().resolve()
    if not comfy.exists():
        print(f"❌ ComfyUI не найден: {comfy}")
        sys.exit(1)

    models = comfy / "models"
    models.mkdir(exist_ok=True)

    print(f"ComfyUI: {comfy}")
    print(f"Модели будут в: {models}\n")

    # ========== 1. Flux.1-dev + PuLID ==========
    if not args.skip_flux:
        print("━━━ 1/6  Flux.1-dev + PuLID (~12 GB) ━━━")

        # Flux UNet GGUF (имя файла часто меняется city96 — используем fallback)
        download("city96/FLUX.1-dev-gguf", "flux1-dev-Q5_K_M.gguf",
                 models / "unet",
                 fallback_patterns=["Q5_K_M", "Q5_1", "Q5_K_S", "Q5_0"])

        # Text encoders
        download("comfyanonymous/flux_text_encoders", "clip_l.safetensors",
                 models / "clip")
        download("comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors",
                 models / "clip")

        # VAE (требует hf login для Flux-dev)
        try:
            download("black-forest-labs/FLUX.1-dev", "ae.safetensors",
                     models / "vae")
        except Exception as e:
            print(f"  ⚠️  ae.safetensors не скачался ({e})")
            print(f"      Залогинься: huggingface-cli login, затем запусти снова")

        # PuLID
        (models / "pulid").mkdir(exist_ok=True)
        download("guozinan/PuLID", "pulid_flux_v0.9.1.safetensors",
                 models / "pulid")
        print()

    # ========== 2. Flux Kontext Dev ==========
    if not args.skip_kontext:
        print("━━━ 2/6  Flux Kontext Dev (~8 GB) ━━━")
        download("city96/FLUX.1-Kontext-dev-gguf", "flux1-kontext-dev-Q5_K_M.gguf",
                 models / "unet",
                 fallback_patterns=["kontext-dev-Q5_K_M", "kontext-dev-Q5", "kontext-dev-Q4_K_M"])
        print()

    # ========== 3. Wan 2.2 ==========
    if not args.skip_wan:
        print("━━━ 3/6  Wan 2.2 I2V + Lightning (~20 GB) ━━━")

        # Wan 2.2 high/low noise GGUF
        download("QuantStack/Wan2.2-I2V-A14B-GGUF",
                 "wan2.2_i2v_high_noise_14B_Q4_K_M.gguf",
                 models / "unet",
                 fallback_patterns=["high_noise_14B_Q4_K_M", "high_noise_14B_Q4", "HighNoise-Q4_K_M"])
        download("QuantStack/Wan2.2-I2V-A14B-GGUF",
                 "wan2.2_i2v_low_noise_14B_Q4_K_M.gguf",
                 models / "unet",
                 fallback_patterns=["low_noise_14B_Q4_K_M", "low_noise_14B_Q4", "LowNoise-Q4_K_M"])

        # VAE и CLIP vision от Kijai
        download("Kijai/WanVideo_comfy", "wan_2.1_vae.safetensors",
                 models / "vae")
        download("Kijai/WanVideo_comfy", "clip_vision_h.safetensors",
                 models / "clip_vision")

        # T5 encoder (FP8 scaled)
        download("Kijai/WanVideo_comfy_fp8_scaled",
                 "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                 models / "clip")

        # Lightning LoRA
        download("lightx2v/Wan2.2-Lightning",
                 "wan2.2_i2v_lightning_4steps_high_noise_v1.1.safetensors",
                 models / "loras",
                 fallback_patterns=["i2v_lightning_4steps_high", "I2V-Lightning-4steps-High"])
        download("lightx2v/Wan2.2-Lightning",
                 "wan2.2_i2v_lightning_4steps_low_noise_v1.1.safetensors",
                 models / "loras",
                 fallback_patterns=["i2v_lightning_4steps_low", "I2V-Lightning-4steps-Low"])
        print()

    # ========== 4. SeedVR2 ==========
    if not args.skip_seedvr2:
        print("━━━ 4/6  SeedVR2 7B (~7 GB) ━━━")
        (models / "seedvr2").mkdir(exist_ok=True)
        download("numz/SeedVR2_comfyUI",
                 "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
                 models / "seedvr2",
                 fallback_patterns=["seedvr2_ema_7b_fp8", "seedvr2_7b_fp8", "7b_fp8_e4m3fn"])
        print()

    # ========== 5. Face restoration ==========
    if not args.skip_face_restore:
        print("━━━ 5/6  Face restoration (~500 MB) ━━━")
        (models / "facerestore_models").mkdir(exist_ok=True)
        # CodeFormer — иногда на HF, иногда на github releases
        try:
            download("sczhou/CodeFormer", "codeformer-v0.1.0.pth",
                     models / "facerestore_models")
        except Exception:
            print("  ⚠️  CodeFormer не на HF — качай с github:")
            print("      https://github.com/sczhou/CodeFormer/releases")

        # YOLO detector для FaceDetailer
        (models / "ultralytics" / "bbox").mkdir(parents=True, exist_ok=True)
        download("Bingsu/adetailer", "face_yolov8m.pt",
                 models / "ultralytics" / "bbox")
        print()

    # ========== 6. F5-TTS русский ==========
    if not args.skip_f5tts:
        if not args.f5tts:
            print("⚠️  --f5tts не указан, пропускаю русский голос")
        else:
            f5_path = Path(args.f5tts).expanduser().resolve()
            if not f5_path.exists():
                print(f"❌ F5-TTS не найден: {f5_path}, пропускаю")
            else:
                print("━━━ 6/6  F5-TTS русский (~2 GB) ━━━")
                ckpts = f5_path / "ckpts"
                ckpts.mkdir(exist_ok=True)
                try:
                    download("Misha24-10/F5-TTS_RUSSIAN",
                             "model_last.safetensors",
                             ckpts,
                             subfolder="F5TTS_v1_Base_v2",
                             rename_to="F5TTS_v1_Base_v2.safetensors")
                    download("Misha24-10/F5-TTS_RUSSIAN", "vocab.txt",
                             ckpts)
                except Exception as e:
                    print(f"  ⚠️  Русский файнтюн не скачался: {e}")
                    print(f"      Скачай вручную с https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN")
                print()

    print("═" * 60)
    print("✅ Скачивание завершено")
    print("═" * 60)
    print()
    print("Что осталось скачать вручную (если не подтянулось автоматом):")
    print("  • EVA-CLIP и AntelopeV2 для PuLID — подтянутся при первом запуске PuLID node")
    print("  • RIFE checkpoints — подтянутся при первом запуске Frame-Interpolation node")
    print("  • LatentSync 1.6 checkpoint — подтянется при первом запуске LatentSyncWrapper")
    print()
    print("Следующий шаг: проверь config.py — пути должны совпадать с реальным расположением")


if __name__ == "__main__":
    main()