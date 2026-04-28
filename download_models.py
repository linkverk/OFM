"""
Скачивание всех моделей одним скриптом через huggingface_hub.

Использование:
    pip install huggingface_hub
    python download_models.py --comfyui C:\\ai-ofm\\ComfyUI --f5tts C:\\ai-ofm\\F5-TTS

Всего скачивается ~50 GB. На быстром канале — 30-60 минут.

Все модели качаются из non-gated зеркал — hf login не нужен.

Пропускать категории:
    --skip-flux --skip-kontext --skip-wan --skip-seedvr2
    --skip-f5tts --skip-face-restore

Скрипт устойчив к сбоям: провал одной модели не останавливает остальные,
в конце печатается сводка.
"""
import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Optional


def _require_hf():
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
        return hf_hub_download, list_repo_files
    except ImportError:
        print("[err] huggingface_hub not installed. pip install huggingface_hub")
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
    Скачивает один файл с HF и кладёт в target_dir/rename_to (или .../filename).
    Если subfolder задан — hf_hub_download положит файл в target_dir/subfolder/filename,
    мы потом перенесём его в target_dir/rename_to (плоско).

    fallback_patterns — подстроки для поиска альтернативных имён в репо, если точное
    имя вернуло 404.
    """
    hf_hub_download, list_repo_files = _require_hf()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    final_name = rename_to or Path(filename).name
    final_path = target_dir / final_name
    if final_path.exists():
        print(f"  [ok] {final_name} уже есть")
        return final_path

    # Собираем список попыток как (subfolder, filename).
    attempts: list[tuple[Optional[str], str]] = [(subfolder, filename)]
    if fallback_patterns:
        try:
            all_files = list_repo_files(repo_id)
            for pattern in fallback_patterns:
                for f in all_files:
                    if pattern.lower() in f.lower():
                        parts = f.rsplit("/", 1)
                        if len(parts) == 2:
                            sub, name = parts
                        else:
                            sub, name = None, parts[0]
                        if (sub, name) not in attempts:
                            attempts.append((sub, name))
        except Exception as e:
            print(f"  [warn] не удалось получить список файлов {repo_id}: {e}")

    last_err = None
    for attempt_sub, attempt_name in attempts:
        display = f"{attempt_sub}/{attempt_name}" if attempt_sub else attempt_name
        try:
            print(f"  [dl] {repo_id}/{display}")
            path = hf_hub_download(
                repo_id=repo_id,
                filename=attempt_name,
                subfolder=attempt_sub,
                local_dir=str(target_dir),
            )
            path = Path(path)
            # hf_hub_download кладёт файл в target_dir/subfolder/filename.
            # Переносим на target_dir/final_name (плоско).
            if path.resolve() != final_path.resolve():
                if final_path.exists():
                    final_path.unlink()
                path.rename(final_path)
                # Чистим пустые подпапки снизу вверх.
                if attempt_sub:
                    try:
                        cur = target_dir / attempt_sub
                        while cur != target_dir and cur.exists() and not any(cur.iterdir()):
                            cur.rmdir()
                            cur = cur.parent
                    except OSError:
                        pass
                path = final_path
            return path
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "404" in err_str or "Not Found" in err_str:
                print(f"    [404] {display}, пробую следующий вариант...")
                continue
            if "401" in err_str or "gated" in err_str.lower():
                print(f"    [401/gated] {display}, пробую следующий вариант...")
                continue
            raise

    raise RuntimeError(
        f"Не удалось скачать из {repo_id}. Пробовал: {attempts}\n"
        f"Последняя ошибка: {last_err}"
    )


def download_url(
    url: str,
    target_dir: Path,
    filename: str,
    expected_sha256: Optional[str] = None,
) -> Path:
    """
    Прямое скачивание по URL (для github releases и т.п.).
    Опционально проверяет SHA256, чтобы ловить порчу/подмену.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    if dest.exists():
        print(f"  [ok] {filename} уже есть")
        return dest

    print(f"  [dl] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ai-ofm-studio/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            hasher = hashlib.sha256() if expected_sha256 else None
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"  {downloaded/1e6:.1f}/{total/1e6:.1f} MB ({pct}%)",
                              end="\r")
            print()
        if expected_sha256:
            got = hasher.hexdigest()
            if got.lower() != expected_sha256.lower():
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"SHA256 mismatch: expected {expected_sha256}, got {got}")
        tmp.rename(dest)
        return dest
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _try(failures: list, label: str, fn, *args, **kwargs):
    """Вызов загрузочной функции с изоляцией ошибок."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        print(f"  [FAIL] {label}: {str(e).splitlines()[0]}")
        failures.append((label, str(e).splitlines()[0]))


def main():
    # На Windows-консоли (cp1252) print() с кириллицей валится. Принудительно UTF-8.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
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
                        help="показать файлы в репо HF (диагностика)")
    args = parser.parse_args()

    if args.list:
        _, list_repo_files = _require_hf()
        print(f"Файлы в {args.list}:")
        for f in sorted(list_repo_files(args.list)):
            print(f"  {f}")
        return

    if not args.comfyui:
        print("[err] --comfyui обязателен (если не используешь --list)")
        sys.exit(1)

    comfy = Path(args.comfyui).expanduser().resolve()
    if not comfy.exists():
        print(f"[err] ComfyUI не найден: {comfy}")
        sys.exit(1)

    models = comfy / "models"
    models.mkdir(exist_ok=True)

    print(f"ComfyUI: {comfy}")
    print(f"Модели будут в: {models}\n")

    failures: list[tuple[str, str]] = []

    # ========== 1. Flux.1-dev + PuLID ==========
    if not args.skip_flux:
        print("=== 1/6  Flux.1-dev + PuLID (~12 GB) ===")

        # у city96 для dev есть Q5_K_S / Q5_0 / Q5_1 — НЕТ Q5_K_M
        _try(failures, "flux1-dev Q5",
             download, "city96/FLUX.1-dev-gguf", "flux1-dev-Q5_K_S.gguf",
             models / "unet",
             fallback_patterns=["Q5_K_S", "Q5_0", "Q5_1", "Q4_K_M"])

        _try(failures, "clip_l",
             download, "comfyanonymous/flux_text_encoders", "clip_l.safetensors",
             models / "clip")
        _try(failures, "t5xxl_fp8",
             download, "comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors",
             models / "clip")

        # non-gated зеркало, SHA256 идентичен BFL
        _try(failures, "flux ae.safetensors",
             download, "ffxvs/vae-flux", "ae.safetensors",
             models / "vae")

        (models / "pulid").mkdir(exist_ok=True)
        _try(failures, "pulid_flux",
             download, "guozinan/PuLID", "pulid_flux_v0.9.1.safetensors",
             models / "pulid")
        print()

    # ========== 2. Flux Kontext Dev ==========
    if not args.skip_kontext:
        print("=== 2/6  Flux Kontext Dev (~8 GB) ===")
        _try(failures, "flux-kontext-dev Q5",
             download, "QuantStack/FLUX.1-Kontext-dev-GGUF",
             "flux1-kontext-dev-Q5_K_M.gguf",
             models / "unet",
             fallback_patterns=["kontext-dev-Q5_K_M", "kontext-dev-Q5_K_S", "kontext-dev-Q4_K_M"])
        print()

    # ========== 3. Wan 2.2 ==========
    if not args.skip_wan:
        print("=== 3/6  Wan 2.2 I2V + Lightning (~22 GB) ===")

        # QuantStack кладёт high/low в подпапки HighNoise/ и LowNoise/.
        _try(failures, "wan2.2 high-noise Q4_K_M",
             download, "QuantStack/Wan2.2-I2V-A14B-GGUF",
             "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf",
             models / "unet",
             subfolder="HighNoise",
             rename_to="wan2.2_i2v_high_noise_14B_Q4_K_M.gguf",
             fallback_patterns=["HighNoise-Q4_K_M", "high_noise_14B_Q4_K_M"])
        _try(failures, "wan2.2 low-noise Q4_K_M",
             download, "QuantStack/Wan2.2-I2V-A14B-GGUF",
             "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
             models / "unet",
             subfolder="LowNoise",
             rename_to="wan2.2_i2v_low_noise_14B_Q4_K_M.gguf",
             fallback_patterns=["LowNoise-Q4_K_M", "low_noise_14B_Q4_K_M"])

        # VAE / CLIP-vision / umt5 — все в Comfy-Org репакадже под split_files/.
        _try(failures, "wan 2.1 vae",
             download, "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
             "wan_2.1_vae.safetensors",
             models / "vae",
             subfolder="split_files/vae")
        # CLIP vision — свежий LoadWanVideoClipTextEncoder требует XLM-RoBERTa-ViT-H/14, не стандартный clip_vision_h.
        _try(failures, "wan clip_vision xlm-roberta-vit-h",
             download, "Kijai/WanVideo_comfy",
             "open-clip-xlm-roberta-large-vit-huge-14_visual_fp16.safetensors",
             models / "clip_vision")
        # T5 fp16 — свежий Kijai (LoadWanVideoT5TextEncoder) отвергает fp8_e4m3fn_scaled.
        _try(failures, "umt5 fp16",
             download, "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
             "umt5_xxl_fp16.safetensors",
             models / "clip",
             subfolder="split_files/text_encoders")

        # Lightning LoRA — теперь в подпапке Seko-V1/ с именами high_noise_model/low_noise_model.
        # Переименовываем под имена, которые ждёт workflow.
        _try(failures, "wan2.2 lightning high",
             download, "lightx2v/Wan2.2-Lightning",
             "high_noise_model.safetensors",
             models / "loras",
             subfolder="Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1",
             rename_to="wan2.2_i2v_lightning_4steps_high_noise_v1.1.safetensors")
        _try(failures, "wan2.2 lightning low",
             download, "lightx2v/Wan2.2-Lightning",
             "low_noise_model.safetensors",
             models / "loras",
             subfolder="Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1",
             rename_to="wan2.2_i2v_lightning_4steps_low_noise_v1.1.safetensors")
        print()

    # ========== 4. SeedVR2 ==========
    if not args.skip_seedvr2:
        print("=== 4/6  SeedVR2 7B (~8 GB) ===")
        (models / "seedvr2").mkdir(exist_ok=True)
        _try(failures, "seedvr2 7b fp8",
             download, "numz/SeedVR2_comfyUI",
             "seedvr2_ema_7b_fp8_e4m3fn.safetensors",
             models / "seedvr2",
             fallback_patterns=["seedvr2_ema_7b_fp8", "seedvr2_7b_fp8", "7b_fp8_e4m3fn"])
        # VAE — единственный для SeedVR2, иначе custom-node качает на первом запуске
        # и ломается на закрытых сетках/прокси (вне нашего error-aggregation).
        _try(failures, "seedvr2 vae fp16",
             download, "numz/SeedVR2_comfyUI",
             "ema_vae_fp16.safetensors",
             models / "seedvr2",
             fallback_patterns=["ema_vae_fp16", "vae_fp16", "ema_vae"])
        print()

    # ========== 5. Face restoration ==========
    if not args.skip_face_restore:
        print("=== 5/6  Face restoration (~500 MB) ===")
        (models / "facerestore_models").mkdir(exist_ok=True)

        # CodeFormer официально только на github releases. HF-зеркала нестабильны
        # (файлы живут в old revisions, main ветка их теряет). Качаем с github
        # напрямую и проверяем SHA256.
        _try(failures, "codeformer (github)",
             download_url,
             "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth",
             models / "facerestore_models",
             "codeformer-v0.1.0.pth",
             "1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7")

        (models / "ultralytics" / "bbox").mkdir(parents=True, exist_ok=True)
        _try(failures, "face_yolov8m",
             download, "Bingsu/adetailer", "face_yolov8m.pt",
             models / "ultralytics" / "bbox")
        print()

    # ========== 6. F5-TTS русский ==========
    if not args.skip_f5tts:
        if not args.f5tts:
            print("[warn] --f5tts не указан, пропускаю русский голос")
        else:
            f5_path = Path(args.f5tts).expanduser().resolve()
            if not f5_path.exists():
                print(f"[err] F5-TTS не найден: {f5_path}, пропускаю")
                failures.append(("F5-TTS russian", f"path not found: {f5_path}"))
            else:
                print("=== 6/6  F5-TTS русский (~1.4 GB) ===")
                ckpts = f5_path / "ckpts"
                ckpts.mkdir(exist_ok=True)
                # У Misha24-10 нет model_last.safetensors — есть только model_last_inference.safetensors
                # (1.35 GB, только веса для инференса) и model_last.pt (5.39 GB, тренировочный).
                # Инференс-веса — то что нужно.
                _try(failures, "F5-TTS russian ckpt (v2)",
                     download, "Misha24-10/F5-TTS_RUSSIAN",
                     "model_last_inference.safetensors",
                     ckpts,
                     subfolder="F5TTS_v1_Base_v2",
                     rename_to="F5TTS_v1_Base_v2.safetensors")
                # vocab.txt у Misha24-10 отсутствует — используем базовый от SWivid.
                # Русская модель использует тот же char-tokenizer, символ `+` для ударения.
                _try(failures, "F5-TTS vocab (SWivid base)",
                     download, "SWivid/F5-TTS", "vocab.txt",
                     ckpts,
                     subfolder="F5TTS_v1_Base")
                print()

    # ========== Сводка ==========
    print("=" * 60)
    if not failures:
        print("[OK] Все модели скачаны успешно")
    else:
        print(f"[WARN] Провалы ({len(failures)}):")
        for label, err in failures:
            print(f"  - {label}: {err}")
    print("=" * 60)
    print()
    print("Автоматически подтянутся нодами при первом запуске ComfyUI:")
    print("  - EVA-CLIP и AntelopeV2 (PuLID node)")
    print("  - RIFE checkpoints (Frame-Interpolation node)")
    print("  - LatentSync 1.6 (LatentSyncWrapper node)")


if __name__ == "__main__":
    main()