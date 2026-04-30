"""
Журнал прогонов в markdown для Obsidian.

Пишет одну заметку на каждый прогон в journal/YYYY-MM-DD/HH-MM-SS-<stage>.md.
Frontmatter совместим с конвенциями wiki/CLAUDE.md (type/status/tags/updated),
тело — embed-ссылки `![[output/...]]` и обычные `[[...]]` для не-картинок.

Использование:

    from utils.journal import run as journal_run

    with journal_run("character", params={"steps": 20}, prompt="...") as e:
        ...
        e.add_outputs(files)
        e.add_score(arm_idx, score)        # опционально, для best-of-N

Fail-soft: любые ошибки записи журнала только логируются и не ломают прогон.
Если JournalSettings.enabled=False — context manager работает no-op.
"""
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import PROJECT_ROOT, JournalSettings


JOURNAL_DIR = PROJECT_ROOT / "journal"


class _Entry:
    def __init__(
        self,
        stage: str,
        params: Optional[dict] = None,
        prompt: Optional[str] = None,
        tags: Optional[list[str]] = None,
        notes: str = "",
    ):
        self.stage = stage
        self.params: dict[str, Any] = dict(params or {})
        self.prompt = prompt or ""
        self.tags = list(tags or [])
        self.outputs: list[Path] = []
        self.scores: list[tuple[Optional[int], float]] = []
        self.notes = notes
        self.t0 = time.time()
        self.status = "ok"
        self.error = ""

    def add_outputs(self, paths) -> None:
        for p in paths or []:
            self.outputs.append(Path(p))

    def add_score(self, arm: Optional[int], score: float) -> None:
        self.scores.append((arm, float(score)))

    def set_param(self, key: str, value: Any) -> None:
        self.params[key] = value


def _yaml_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\n", " ").replace('"', "'")
    return f'"{s}"'


def _rel(p: Path) -> str:
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
    except (ValueError, OSError):
        return str(p).replace("\\", "/")
    return str(rel).replace("\\", "/")


_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif"}
_VID_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
_AUD_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}


def _format(entry: _Entry) -> str:
    elapsed = time.time() - entry.t0
    now = datetime.now()
    L: list[str] = ["---"]
    L.append("type: run")
    L.append(f"stage: {entry.stage}")
    L.append(f"status: {entry.status}")
    L.append(f"updated: {now.strftime('%Y-%m-%d')}")
    L.append(f"time: {now.strftime('%H:%M:%S')}")
    L.append(f"duration_sec: {elapsed:.1f}")
    if entry.prompt:
        L.append(f"prompt: {_yaml_scalar(entry.prompt[:240])}")
    if entry.params:
        L.append("params:")
        for k, v in entry.params.items():
            L.append(f"  {k}: {_yaml_scalar(v)}")
    if entry.outputs:
        L.append("outputs:")
        for p in entry.outputs:
            L.append(f"  - {_yaml_scalar(_rel(p))}")
    tags = sorted(set(entry.tags + [entry.stage, "run"]))
    L.append(f"tags: [{', '.join(tags)}]")
    L.append("---")
    L.append("")
    L.append(f"# {entry.stage} — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("")
    if entry.prompt:
        L.append("## Prompt")
        L.append("")
        L.append(entry.prompt.strip())
        L.append("")
    if entry.notes:
        L.append("## Notes")
        L.append("")
        L.append(entry.notes.strip())
        L.append("")
    if entry.outputs:
        L.append("## Outputs")
        L.append("")
        for p in entry.outputs:
            rel = _rel(p)
            ext = p.suffix.lower()
            if ext in _IMG_EXT:
                L.append(f"![[{rel}]]")
            elif ext in _VID_EXT or ext in _AUD_EXT:
                # Obsidian умеет встраивать видео/аудио тем же синтаксисом
                L.append(f"![[{rel}]]")
            else:
                L.append(f"- [[{rel}]]")
        L.append("")
    if entry.scores and JournalSettings.log_candidate_scores:
        L.append("## Scores")
        L.append("")
        L.append("| arm | score |")
        L.append("|-----|-------|")
        best = max(s for _, s in entry.scores)
        for arm, s in entry.scores:
            mark = " ★" if s == best else ""
            arm_s = "—" if arm is None else f"#{arm}"
            L.append(f"| {arm_s} | {s:+.3f}{mark} |")
        L.append("")
    if entry.status == "failed" and entry.error:
        L.append("## Error")
        L.append("")
        L.append("```")
        L.append(entry.error.strip()[-2000:])
        L.append("```")
        L.append("")
    return "\n".join(L)


def _write(entry: _Entry) -> Optional[Path]:
    now = datetime.now()
    day_dir = JOURNAL_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%H-%M-%S')}-{entry.stage}.md"
    path = day_dir / fname
    # На случай коллизии в пределах одной секунды
    i = 1
    while path.exists():
        path = day_dir / f"{now.strftime('%H-%M-%S')}-{entry.stage}-{i}.md"
        i += 1
    path.write_text(_format(entry), encoding="utf-8")
    if JournalSettings.verbose:
        print(f"[journal] записал: {_rel(path)}")
    return path


@contextmanager
def run(
    stage: str,
    params: Optional[dict] = None,
    prompt: Optional[str] = None,
    tags: Optional[list[str]] = None,
):
    """
    Контекстный менеджер прогона. Запись пишется при выходе из блока,
    в т.ч. если внутри было исключение (status=failed, traceback в Error).
    """
    entry = _Entry(stage, params, prompt, tags)
    if not JournalSettings.enabled:
        # No-op путь: всё равно отдаём entry, чтобы вызовы add_outputs не падали.
        yield entry
        return
    try:
        yield entry
    except Exception:
        entry.status = "failed"
        entry.error = traceback.format_exc()
        try:
            _write(entry)
        except Exception as we:
            print(f"[journal] не смог записать журнал: {we}")
        raise
    else:
        try:
            _write(entry)
        except Exception as we:
            print(f"[journal] не смог записать журнал: {we}")
