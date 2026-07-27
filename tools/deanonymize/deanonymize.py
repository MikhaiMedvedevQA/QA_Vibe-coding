"""Деанонимизация артефактов анонимизатора (CLI).

Восстанавливает исходные значения в готовых артефактах по mapping.json:
  _anon.md      -> _deanon.md   (текстовая замена псевдонимов)
  _anon.json    -> _deanon.json (структурная замена в JSON, сохраняя схему)
  _review.json  -> _deanon_review.json
  index.json    -> _deanon_index.json (в deanonimized/)

Псевдоним = `TYPE_NNNN` (заглавные буквы + 4 цифры). Неразрешённые
(нет в mapping.json) оставляем как есть.

Запуск:
  python tools/deanonymize/deanonymize.py <файл или папка> [--mapping ...] [--out ...]
  python tools/deanonymize/deanonymize.py anonimized/
  python tools/deanonymize/deanonymize.py anonimized/xxx_anon.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Псевдоним вида PERSON_0001, BANK_0042 и т.п. (см. config.pseudonym_format).
_PSEUDO_RE = re.compile(r"([A-Z]+)_\d{4}")

# Дефолтный путь к маппингу анонимизатора (tools/anonymize/mapping.json).
DEFAULT_MAPPING = Path(__file__).resolve().parent.parent / "anonymize" / "mapping.json"

# Артефакты, которые умеем деанонимизировать (по суффиксу/имени).
_TEXT_TARGETS = {".md"}
_JSON_TARGETS = {".json"}


# --------------------------------------------------------------------------- API


def load_reverse_mapping(mapping_path: Path) -> dict[str, str]:
    """Построить обратный словарь «псевдоним -> оригинал» из mapping.json.

    mapping.json имеет вид {TYPE: {original: pseudonym}}. Разворачиваем в
    плоский {pseudonym: original} — псевдонимы уникальны по префиксу типа,
    коллизий не возникает.
    """
    mapping_path = Path(mapping_path)
    if not mapping_path.exists():
        raise FileNotFoundError(
            f"Файл маппинга не найден: {mapping_path}. "
            f"Деанонимизация невозможна без обратного словаря."
        )
    with mapping_path.open("r", encoding="utf-8") as f:
        mapping = json.load(f)
    reverse: dict[str, str] = {}
    for bucket in mapping.values():
        if isinstance(bucket, dict):
            for original, pseudo in bucket.items():
                # Если вдруг один псевдоним встретится дважды — берём первый.
                reverse.setdefault(pseudo, original)
    return reverse


def replace_text(text: str, reverse: dict[str, str], unknown: set[str]) -> str:
    """Заменить псевдонимы в тексте. Неразрешённые — остаются как есть,
    их псевдонимы собираются в `unknown`."""
    def _sub(m: re.Match) -> str:
        pseudo = m.group(0)
        if pseudo in reverse:
            return reverse[pseudo]
        unknown.add(pseudo)
        return pseudo

    return _PSEUDO_RE.sub(_sub, text)


def replace_json(obj, reverse: dict[str, str], unknown: set[str]):
    """Рекурсивно заменить псевдонимы в строковых значениях JSON.
    Ключи не трогаем (имена полей схемы), значения-строки обрабатываем."""
    if isinstance(obj, dict):
        return {k: replace_json(v, reverse, unknown) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_json(v, reverse, unknown) for v in obj]
    if isinstance(obj, str):
        return replace_text(obj, reverse, unknown)
    return obj


# --------------------------------------------------------------------------- вывод


def _out_path(src: Path, out_dir: Path) -> Path:
    """Имя вывода: _anon -> _deanon, прочие _anon_*.json -> _deanon_*.json.

    Примеры:
      xxx_anon.md       -> xxx_deanon.md
      xxx_anon.json     -> xxx_deanon.json
      xxx_anon_review.json -> xxx_deanon_review.json
      index.json        -> _deanon_index.json
    """
    name = src.name
    if name == "index.json":
        return out_dir / "_deanon_index.json"
    if "_anon" in name:
        name = name.replace("_anon", "_deanon", 1)
    else:
        stem = src.stem
        name = f"{stem}_deanon{src.suffix}"
    return out_dir / name


def _resolve_out_dir(src: Path, out_dir: Path | None) -> Path:
    """Каталог вывода. Если --out не задан — папка `deanonimized/` рядом с
    `anonimized/` (т.е. на уровень выше папки-артефакта)."""
    if out_dir is not None:
        return Path(out_dir)
    # Если файл лежит прямо в anonimized/ — вывод рядом, в ../deanonimized/.
    if src.parent.name.lower() == "anonimized":
        return src.parent.parent / "deanonimized"
    # Иначе — deanonimized/ рядом с файлом.
    return src.parent / "deanonimized"


def process_file(src: Path, reverse: dict[str, str], out_dir: Path) -> tuple[Path, int, set[str]]:
    """Деанонимизировать один файл. Возвращает (путь вывода, кол-во замен, unknown)."""
    unknown: set[str] = set()
    ext = src.suffix.lower()
    if ext in _TEXT_TARGETS:
        text = src.read_text(encoding="utf-8")
        before = len(_PSEUDO_RE.findall(text))
        out_text = replace_text(text, reverse, unknown)
        out_path = _out_path(src, out_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text, encoding="utf-8")
        replaced = before - len(unknown)
        return out_path, replaced, unknown
    if ext in _JSON_TARGETS:
        with src.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Подсчёт до замены: считаем псевдонимы во всех строковых значениях.
        before = _count_pseudonyms_in_json(data)
        out_data = replace_json(data, reverse, unknown)
        out_path = _out_path(src, out_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        replaced = before - len(unknown)
        return out_path, replaced, unknown
    raise ValueError(f"Неподдерживаемый формат: {src}")


def _count_pseudonyms_in_json(obj) -> int:
    if isinstance(obj, dict):
        return sum(_count_pseudonyms_in_json(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_pseudonyms_in_json(v) for v in obj)
    if isinstance(obj, str):
        return len(_PSEUDO_RE.findall(obj))
    return 0


def collect_targets(path: Path) -> list[Path]:
    """Собрать целевые артефакты из файла или папки."""
    if path.is_file():
        return [path]
    if path.is_dir():
        targets: list[Path] = []
        for p in sorted(path.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            # Пропускаем подпапки *_assets/ (бинарные ассеты + их манифесты):
            # деанонимизация там не имеет смысла и плодит мусорные выводы.
            if any(
                part == "assets" or part == "attachments" or part.endswith("_assets")
                for part in p.parts
            ):
                continue
            if ext in _TEXT_TARGETS or ext in _JSON_TARGETS:
                targets.append(p)
        return targets
    raise FileNotFoundError(f"Путь не найден: {path}")


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Деанонимизация артефактов анонимизатора по mapping.json.",
    )
    parser.add_argument(
        "path",
        help="Файл-артефакт или папка (рекурсивно обрабатываются .md/.json).",
    )
    parser.add_argument(
        "--mapping",
        default=str(DEFAULT_MAPPING),
        help=f"Путь к mapping.json (по умолчанию: {DEFAULT_MAPPING}).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Каталог вывода (по умолчанию: deanonimized/ рядом с anonimized/).",
    )
    args = parser.parse_args(argv)

    try:
        reverse = load_reverse_mapping(Path(args.mapping))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    src = Path(args.path)
    targets = collect_targets(src)
    if not targets:
        print(f"Не найдено артефактов для деанонимизации: {src}", file=sys.stderr)
        return 1

    total_replaced = 0
    total_unknown: set[str] = set()
    processed = 0
    for t in targets:
        out_dir = _resolve_out_dir(t, Path(args.out) if args.out else None)
        try:
            out_path, replaced, unknown = process_file(t, reverse, out_dir)
        except ValueError as e:
            print(f"SKIP {t}: {e}", file=sys.stderr)
            continue
        processed += 1
        total_replaced += replaced
        total_unknown |= unknown
        line = f"OK  {t} -> {out_path}  | замен: {replaced}"
        if unknown:
            line += f" | неразрешённых: {len(unknown)}"
        print(line)

    print(f"\nОбработано файлов: {processed}")
    print(f"Всего замен псевдонимов: {total_replaced}")
    if total_unknown:
        print(f"Неразрешённых псевдонимов: {len(total_unknown)} (оставлены как есть):")
        for p in sorted(total_unknown):
            print(f"  {p}  ->  {reverse.get(p, '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())