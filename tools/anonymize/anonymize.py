"""CLI утилиты анонимизации.

Использование:
    python tools/anonymize/anonymize.py <входной_файл_или_папка> [--out DIR] [--mapping FILE] [--reset-mapping]

Заменяет личные данные, наименования банков/страховых/продуктов на строго
структурированные псевдонимы (PERSON_0001, BANK_0001 ...). Маппинг сохраняется
между запусками, поэтому одно и то же значение всегда даёт один и тот же
псевдоним. Изображения из PDF/DOCX/XLSX выносятся в папку <имя>_anon_assets/
без анонимизации — с манифестом index.json и привязкой к позиции в тексте.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Гарантируем, что каталог пакета доступен для импорта соседних модулей
# при прямом запуске скрипта.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import SUPPORTED_EXTS, SUPPORTED_EXCEL_EXTS, ANON_SUBDIR, output_dir
from extractors import extract, is_supported
from writers import write_content
from mapper import Mapper


# Вывод всегда в markdown (текстовые и Excel).
def _out_ext(path: Path) -> str:
    return ".md"


_PSEUDO_RE = re.compile(r"([A-Z]+)_\d{4}")


def _doc_entry(path: Path, out_file: Path) -> dict:
    """Сводка по одному документу для сводного индекса папки вывода."""
    text = out_file.read_text(encoding="utf-8", errors="replace")
    entities: dict[str, int] = {}
    seen: set[str] = set()
    for m in _PSEUDO_RE.finditer(text):
        if m.group(0) not in seen:
            seen.add(m.group(0))
            entities[m.group(1)] = entities.get(m.group(1), 0) + 1
    assets_dir = out_file.parent / f"{out_file.stem}_assets"
    assets: dict[str, int] = {}
    idx = assets_dir / "index.json"
    if idx.exists():
        try:
            man = json.loads(idx.read_text(encoding="utf-8"))
            for a in man.get("assets", []):
                k = a.get("kind", "asset")
                assets[k] = assets.get(k, 0) + 1
        except Exception:
            pass
    # JSON-датасет структуры полей ЭФ (появляется только для Excel-спецификаций).
    spec_json_path = out_file.parent / f"{out_file.stem}.json"
    spec_dataset: dict | None = None
    if spec_json_path.exists():
        try:
            data = json.loads(spec_json_path.read_text(encoding="utf-8"))
            spec_dataset = {
                "file": spec_json_path.name,
                "schema_version": data.get("schema_version"),
                "summary": data.get("summary"),
            }
        except Exception:
            spec_dataset = {"file": spec_json_path.name, "error": "unreadable"}
    # Ревью-кандидаты (подозрительные совпадения, не заменённые детектором).
    review_path = out_file.parent / f"{out_file.stem}_review.json"
    review_candidates: int | None = None
    if review_path.exists():
        try:
            rv = json.loads(review_path.read_text(encoding="utf-8"))
            review_candidates = rv.get("summary", {}).get("total")
        except Exception:
            review_candidates = None
    return {
        "source": path.name,
        "source_format": path.suffix.lower().lstrip("."),
        "output": out_file.name,
        "assets_dir": assets_dir.name if assets_dir.exists() else None,
        "entities": entities,
        "assets": assets,
        "spec_dataset": spec_dataset,
        "review_candidates": review_candidates,
    }


def _plan_outputs(inputs: list[Path]) -> list[tuple[Path, str]]:
    """Разрулить коллизии имён вывода. Ключ — stem (т.к. папка ассетов = stem+'_assets'),
    поэтому при совпадении stem-ов добавляем суффикс исходного расширения."""
    reserved: set[str] = set()
    plan: list[tuple[Path, str]] = []
    for path in inputs:
        stem = path.stem
        src_tag = path.suffix.lower().lstrip(".") or "src"
        candidates = [f"{stem}_anon", f"{stem}_{src_tag}_anon"]
        base = next((c for c in candidates if c not in reserved), None)
        if base is None:
            i = 2
            while f"{candidates[-1]}_{i}" in reserved:
                i += 1
            base = f"{candidates[-1]}_{i}"
        reserved.add(base)
        plan.append((path, f"{base}{_out_ext(path)}"))
    return plan


def process_one(path: Path, out_dir: Path, mapper: Mapper, out_name: str) -> Path | None:
    if not is_supported(path):
        return None
    content = extract(path)
    return write_content(content, out_dir, mapper, out_name)


def iter_inputs(target: Path):
    if target.is_dir():
        for p in sorted(target.rglob("*")):
            if not (p.is_file() and p.suffix.lower() in SUPPORTED_EXTS):
                continue
            # Не обрабатываем уже готовые результаты внутри подпапки вывода.
            try:
                rel_parts = p.relative_to(target).parts
            except ValueError:
                rel_parts = ()
            if ANON_SUBDIR in rel_parts:
                continue
            yield p
    elif target.is_file():
        yield target
    else:
        raise FileNotFoundError(f"Целевой путь не найден: {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Анонимизация документов (PII, банки, страховые, продукты).")
    parser.add_argument("input", help="Входной файл или папка.")
    parser.add_argument("--out", help="Каталог для результатов (по умолчанию — рядом с исходником).")
    parser.add_argument("--mapping", help="Путь к файлу маппинга (по умолчанию mapping.json в пакете).")
    parser.add_argument("--reset-mapping", action="store_true", help="Начать с чистого маппинга (ломает консистентность).")
    args = parser.parse_args(argv)

    target = Path(args.input).resolve()
    out_dir = Path(args.out).resolve() if args.out else None

    mapper = Mapper(mapping_path=args.mapping, reset=args.reset_mapping)

    # Заранее резервировать имена выводов, чтобы одноимённые исходники
    # (sample.pdf + sample.txt) не затирали результаты друг друга.
    inputs = list(iter_inputs(target))
    plan = _plan_outputs(inputs)

    processed = 0
    errors: list[str] = []
    entries_by_dir: dict[Path, list[dict]] = {}
    for path, out_name in plan:
        target_out = out_dir if out_dir else output_dir(path)
        try:
            result = process_one(path, target_out, mapper, out_name)
            if result:
                processed += 1
                print(f"OK  {path} -> {result}")
                entries_by_dir.setdefault(target_out, []).append(_doc_entry(path, result))
        except Exception as e:
            errors.append(f"{path}: {e}")
            print(f"ERR {path}: {e}", file=sys.stderr)

    # Сводный индекс по каждой папке вывода (список документов, пути, stats).
    # Накапливаем между прогонами: заменяем записи по совпадению output, новые — добавляем.
    for odir, entries in entries_by_dir.items():
        idx_path = odir / "index.json"
        existing: list[dict] = []
        if idx_path.exists():
            try:
                existing = json.loads(idx_path.read_text(encoding="utf-8")).get("documents", [])
            except Exception:
                existing = []
        new_outputs = {e["output"] for e in entries}
        merged = [e for e in existing if e.get("output") not in new_outputs] + entries
        merged.sort(key=lambda e: e["output"])
        idx_path.write_text(
            json.dumps({"documents": merged}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    mapper.save()
    print(f"\nОбработано файлов: {processed}")
    if errors:
        print(f"Ошибок: {len(errors)}")
    stats = mapper.stats()
    if stats:
        print("Замены по типам:")
        for t, count in sorted(stats.items()):
            print(f"  {t}: {count}")
    review_total = sum(
        e.get("review_candidates") or 0
        for entries in entries_by_dir.values() for e in entries
    )
    if review_total:
        print(f"Ревью-кандидаты: {review_total} (подозрительные совпадения — см. *_review.json)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())