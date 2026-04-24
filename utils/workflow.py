"""
Общие функции для работы с workflow JSON:
- загрузка из файла с очисткой _comment-ключей
- подстановка {{PLACEHOLDER}} в inputs
"""
import copy
import json
from pathlib import Path


def load_workflow(workflow_path: Path) -> dict:
    """Читает JSON и выкидывает служебные _comment ключи."""
    with open(workflow_path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    return {k: v for k, v in wf.items() if not k.startswith("_")}


def fill_placeholders(wf: dict, values: dict) -> dict:
    """
    Рекурсивно заменяет строки вида "{{KEY}}" в inputs нод на values[KEY].
    Не трогает ноды без inputs и нелитеральные поля.
    """
    wf = copy.deepcopy(wf)
    for node in wf.values():
        if not isinstance(node, dict) or "inputs" not in node:
            continue
        for key, val in list(node["inputs"].items()):
            if isinstance(val, str) and val.startswith("{{") and val.endswith("}}"):
                placeholder = val[2:-2]
                if placeholder in values:
                    node["inputs"][key] = values[placeholder]
    return wf
