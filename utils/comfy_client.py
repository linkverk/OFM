"""
HTTP-клиент для ComfyUI API.
Отправляет workflow JSON, опрашивает статус, забирает результат.
"""
import json
import time
import uuid
import shutil
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

import websocket  # pip install websocket-client

from config import (
    COMFYUI_URL,
    COMFYUI_ROOT,
    POLL_INTERVAL_SEC,
    QUEUE_TIMEOUT_SEC,
    OUTPUT_DIR,
)


class ComfyClient:
    """Минималистичный клиент к локальному ComfyUI."""

    def __init__(self, server_url: str = COMFYUI_URL):
        self.server = server_url.rstrip("/")
        self.host = self.server.replace("http://", "").replace("https://", "")
        self.client_id = str(uuid.uuid4())

    # ---------- базовые HTTP ----------

    def _post_json(self, path: str, data: dict) -> dict:
        req = urllib.request.Request(
            f"{self.server}{path}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            # ComfyUI возвращает структурированный JSON при валидационных ошибках.
            # Без чтения body urllib даёт только "HTTP Error 400: Bad Request" — бесполезно.
            body = e.read().decode("utf-8", errors="replace")
            self._print_comfy_error(e.code, body)
            raise

    @staticmethod
    def _print_comfy_error(code: int, body: str) -> None:
        """Красиво печатает ошибку валидации workflow от ComfyUI."""
        try:
            err = json.loads(body)
        except json.JSONDecodeError:
            print(f"\n[comfy] HTTP {code} (non-JSON body):\n{body[:2000]}")
            return

        print(f"\n[comfy] HTTP {code} — workflow отвергнут ComfyUI")

        # Корневая ошибка (например missing_node_type)
        root = err.get("error")
        if isinstance(root, dict):
            msg = root.get("message", "?")
            details = root.get("details", "")
            print(f"  error: {msg}")
            if details:
                print(f"    details: {details}")

        # Ошибки конкретных нод
        node_errors = err.get("node_errors") or {}
        for node_id, info in node_errors.items():
            cls = info.get("class_type", "?")
            print(f"  нода #{node_id} ({cls}):")
            for e in info.get("errors", []):
                etype = e.get("type", "?")
                emsg = e.get("message", "")
                edet = e.get("details", "")
                print(f"    - [{etype}] {emsg}")
                if edet:
                    print(f"      details: {edet}")

        if not node_errors and not isinstance(root, dict):
            # Ничего структурированного не нашли — печатаем сырое тело
            print(body[:2000])

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.server}{path}", timeout=30) as resp:
            return json.loads(resp.read())

    # ---------- проверка и управление ----------

    def is_alive(self) -> bool:
        try:
            urllib.request.urlopen(f"{self.server}/system_stats", timeout=5)
            return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            return False

    def get_system_stats(self) -> dict:
        return self._get_json("/system_stats")

    def free_memory(self, unload_models: bool = True, free_memory: bool = True) -> None:
        """Принудительная очистка VRAM между шагами пайплайна."""
        try:
            self._post_json(
                "/free",
                {"unload_models": unload_models, "free_memory": free_memory},
            )
            time.sleep(1.5)
        except Exception as e:
            print(f"[warn] free_memory: {e}")

    def interrupt(self) -> None:
        try:
            self._post_json("/interrupt", {})
        except Exception:
            pass

    # ---------- загрузка файлов в ComfyUI input ----------

    def upload_image(self, image_path: Path, subfolder: str = "ai_ofm") -> str:
        """
        Копирует изображение в ComfyUI/input/<subfolder>/.
        Возвращает имя, которое LoadImage сможет прочитать: "subfolder/filename".
        Это надёжнее HTTP multipart — работает даже если API изменили.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(image_path)

        dest_dir = COMFYUI_ROOT / "input" / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / image_path.name
        if dest.resolve() != image_path.resolve():
            shutil.copy2(image_path, dest)
        return f"{subfolder}/{image_path.name}"

    # ---------- отправка workflow ----------

    def queue_prompt(self, workflow: dict) -> str:
        """Ставит workflow в очередь, возвращает prompt_id."""
        payload = {"prompt": workflow, "client_id": self.client_id}
        result = self._post_json("/prompt", payload)
        if "prompt_id" not in result:
            raise RuntimeError(f"ComfyUI отказал: {result}")
        return result["prompt_id"]

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: int = QUEUE_TIMEOUT_SEC,
        progress_callback=None,
    ) -> dict:
        """
        Ожидает завершения задачи. Использует websocket если доступен,
        иначе fallback на polling истории.
        """
        start = time.time()

        # Попытка через websocket (быстрее, даёт прогресс)
        try:
            return self._wait_via_websocket(prompt_id, timeout, progress_callback)
        except Exception as e:
            print(f"[warn] websocket не сработал ({e}), переходим на polling")

        # Fallback: polling
        while time.time() - start < timeout:
            history = self._get_json(f"/history/{prompt_id}")
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(POLL_INTERVAL_SEC)
        raise TimeoutError(f"Prompt {prompt_id} не завершился за {timeout} сек")

    def _wait_via_websocket(self, prompt_id: str, timeout: int, cb) -> dict:
        ws_url = f"ws://{self.host}/ws?clientId={self.client_id}"
        ws = websocket.create_connection(ws_url, timeout=30)
        ws.settimeout(timeout)
        try:
            while True:
                msg = ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    mtype = data.get("type")
                    mdata = data.get("data", {})
                    if mtype == "progress" and cb:
                        cb(mdata.get("value", 0), mdata.get("max", 1))
                    elif mtype == "executing":
                        if mdata.get("node") is None and mdata.get("prompt_id") == prompt_id:
                            break
                    elif mtype == "execution_error":
                        raise RuntimeError(f"ComfyUI error: {mdata}")
        finally:
            ws.close()
        return self._get_json(f"/history/{prompt_id}")[prompt_id]

    # ---------- извлечение результатов ----------

    def download_outputs(self, history_entry: dict, target_dir: Path = OUTPUT_DIR) -> list[Path]:
        """Скачивает все файлы (картинки + видео), созданные workflow'ом."""
        target_dir.mkdir(parents=True, exist_ok=True)
        saved = []

        outputs = history_entry.get("outputs", {})
        for node_id, node_out in outputs.items():
            # картинки
            for img in node_out.get("images", []) or []:
                saved.append(self._download_file(img, target_dir, kind="view"))
            # видео (от VideoHelperSuite и др.)
            for vid in node_out.get("gifs", []) or []:
                saved.append(self._download_file(vid, target_dir, kind="view"))
            for vid in node_out.get("videos", []) or []:
                saved.append(self._download_file(vid, target_dir, kind="view"))
        return [p for p in saved if p]

    def _download_file(self, file_info: dict, target_dir: Path, kind: str = "view") -> Path | None:
        filename = file_info.get("filename")
        subfolder = file_info.get("subfolder", "")
        ftype = file_info.get("type", "output")
        if not filename:
            return None
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": ftype,
        })
        url = f"{self.server}/{kind}?{params}"
        dest = target_dir / filename
        with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        return dest

    # ---------- высокоуровневый запуск ----------

    def run_workflow(self, workflow: dict, progress_callback=None) -> list[Path]:
        """Полный цикл: очередь → ожидание → скачивание."""
        prompt_id = self.queue_prompt(workflow)
        print(f"[comfy] prompt_id={prompt_id}")
        history = self.wait_for_completion(prompt_id, progress_callback=progress_callback)
        return self.download_outputs(history)