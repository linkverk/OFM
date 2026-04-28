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
    Обходит вложенные dict'ы (например block_swap_args.blocks_to_swap у Kijai-нод).
    Подставляет значение как есть — если values[KEY] это int, в JSON попадёт int (важно
    для downstream-нод, которые делают арифметику над таким полем).
    """
    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                    placeholder = v[2:-2]
                    if placeholder in values:
                        obj[k] = values[placeholder]
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str) and item.startswith("{{") and item.endswith("}}"):
                    placeholder = item[2:-2]
                    if placeholder in values:
                        obj[i] = values[placeholder]
                else:
                    _walk(item)

    wf = copy.deepcopy(wf)
    for node in wf.values():
        if not isinstance(node, dict) or "inputs" not in node:
            continue
        _walk(node["inputs"])
    return wf
