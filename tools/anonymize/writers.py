"""Сборка анонимизированного вывода.

- Текстовые форматы -> `<stem>_anon.md` + папка `<stem>_anon_assets/`
  (изображения в `assets/`, вложения в `attachments/`, манифест `index.json`
  с привязкой к абзацу). Таблицы рендерятся как markdown-таблицы.
- Excel -> `<stem>_anon.md` (секции по листам, markdown-таблицы) +
  папка `<stem>_anon_assets/` если в книге были изображения.
- В начале файла — сводка `<!-- DOC: ... -->` по сущностям и ассетам.
"""

import json
import re
from pathlib import Path

from dataclasses import is_dataclass

from detectors import find_all, fix_cyr_homoglyphs, find_review_candidates
from extractors import (
    DocumentContent, ExcelContent, TextBlock, ImageBlock, EmbeddedBlock,
    TableBlock, _norm,
)
from spec_extractor import write_spec_json


# Псевдоним вида PERSON_0001 — для подсчёта сущностей в документе.
_PSEUDO_RE = re.compile(r"([A-Z]+)_\d{4}")


def _md_cell(s: str) -> str:
    """Экранировать ячейку для markdown-таблицы: '|' -> '\\|', переносы -> пробел."""
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _md_table(rows: list[list[str]]) -> list[str]:
    """Рендерить список строк ячеек как markdown-таблицу (первая строка — заголовок)."""
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    out = ["| " + " | ".join(_md_cell(c) for c in rows[0]) + " |"]
    out.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
    for r in rows[1:]:
        out.append("| " + " | ".join(_md_cell(c) for c in r) + " |")
    return out


def _pseudonym_counts(lines: list[str]) -> dict[str, int]:
    """Уникальные псевдонимы по типу в наборе строк (для сводки по документу)."""
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for ln in lines:
        for m in _PSEUDO_RE.finditer(ln):
            typ = m.group(1)
            if m.group(0) not in seen:
                seen.add(m.group(0))
                counts[typ] = counts.get(typ, 0) + 1
    return counts


def _asset_counts(manifest_assets: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in manifest_assets:
        k = a.get("kind", "asset")
        counts[k] = counts.get(k, 0) + 1
    return counts


def _fmt_counts(d: dict[str, int]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(d.items())) if d else "0"


def anonymize_text(text: str, mapper) -> str:
    """Заменить все найденные сущности в тексте на псевдонимы через mapper.
    Перед детекцией текст нормализуется (NBSP -> пробел и т.д.), чтобы
    regex/справочники не промахивались на PDF-выжимке."""
    if not text:
        return text
    text = _norm(text)
    text = fix_cyr_homoglyphs(text)  # лат. омоглифы -> кириллица в кириллических словах
    matches = find_all(text)
    if not matches:
        return text
    # Заменяем справа налево, чтобы индексы не сбивались.
    out = text
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        pseudo = mapper.get(m.value, m.type)
        out = out[:m.start] + pseudo + out[m.end:]
    return out


# --------------------------------------------------------------------------
# Текстовые документы
# --------------------------------------------------------------------------

def build_document_text(content: DocumentContent, mapper) -> tuple[list[str], list[dict]]:
    """Построить анонимизированный текст и манифест ассетов БЕЗ записи на диск.
    Нужно для предпросмотра в GUI. Возвращает (lines, manifest_assets)."""
    lines: list[str] = []
    manifest_assets: list[dict] = []
    for block in content.blocks:
        if isinstance(block, TextBlock):
            lines.append(anonymize_text(block.text, mapper))
        elif isinstance(block, ImageBlock):
            rel_file = f"assets/{block.asset_id}.{block.ext}"
            anchor = len(lines)
            comment = (
                f"<!-- ASSET: {block.asset_id} | kind=image | file={rel_file} | "
                f"anchor=para-{anchor} | src_page={block.src_page} | note=\"{block.note}\" -->"
            )
            placeholder = f"[ИЗОБРАЖЕНИЕ {block.asset_id} — см. {rel_file}]"
            lines.append(comment)
            lines.append(placeholder)
            manifest_assets.append({
                "id": block.asset_id, "kind": "image", "file": rel_file,
                "anchor": anchor, "src_page": block.src_page,
                "src_format": content.source_format, "note": block.note,
            })
        elif isinstance(block, EmbeddedBlock):
            disk_name = f"{block.asset_id}__{block.original_filename}"
            rel_file = f"attachments/{disk_name}"
            anchor = len(lines)
            comment = (
                f"<!-- ASSET: {block.asset_id} | kind=attachment | file={rel_file} | "
                f"original={block.original_filename} | prog_id={block.prog_id} | "
                f"anchor=para-{anchor} | note=\"{block.note}\" -->"
            )
            placeholder = f"[ВЛОЖЕНИЕ {block.asset_id} — {block.original_filename} — см. {rel_file}]"
            lines.append(comment)
            lines.append(placeholder)
            manifest_assets.append({
                "id": block.asset_id, "kind": "attachment", "file": rel_file,
                "original_filename": block.original_filename, "prog_id": block.prog_id,
                "anchor": anchor, "src_page": None,
                "src_format": content.source_format, "note": block.note,
            })
        elif isinstance(block, TableBlock):
            rows = [[anonymize_text(c, mapper) for c in row] for row in block.rows]
            lines.extend(_md_table(rows))
    return lines, manifest_assets


def build_original_text(content) -> list[str]:
    """Исходный текст (без анонимизации) для левой панели предпросмотра («до»)."""
    if isinstance(content, ExcelContent):
        lines = []
        for ws in content.workbook.worksheets:
            lines.append(f"=== Лист: {ws.title} ===")
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    lines.append(" | ".join(cells))
        return lines
    lines = []
    for b in content.blocks:
        if isinstance(b, TextBlock):
            lines.append(b.text)
        elif isinstance(b, ImageBlock):
            # Две строки в «до» — чтобы совпадало построчно с «после»,
            # где ImageBlock занимает комментарий-маркер + плейсхолдер.
            lines.append(
                f"<!-- изображение {b.asset_id} | src_page={b.src_page} | "
                f"note=\"{b.note}\" -->"
            )
            lines.append(f"[изображение {b.asset_id}]")
        elif isinstance(b, EmbeddedBlock):
            lines.append(
                f"<!-- вложение {b.asset_id} | original={b.original_filename} | "
                f"prog_id={b.prog_id} | note=\"{b.note}\" -->"
            )
            lines.append(f"[вложение {b.asset_id} — {b.original_filename}]")
        elif isinstance(b, TableBlock):
            lines.extend(_md_table(b.rows))
    return lines


def build_excel_text(content: ExcelContent, mapper) -> list[str]:
    """Анонимизированный текст Excel для правой панели предпросмотра («после»)."""
    lines = []
    for ws in content.workbook.worksheets:
        lines.append(f"=== Лист: {ws.title} ===")
        for row in ws.iter_rows(values_only=True):
            cells = []
            for v in row:
                if v is None:
                    cells.append("")
                elif isinstance(v, str):
                    cells.append(anonymize_text(v, mapper))
                else:
                    cells.append(str(v))
            if any(c.strip() for c in cells):
                lines.append(" | ".join(cells))
    return lines


def write_document(content: DocumentContent, out_dir: Path, mapper, out_name: str | None = None) -> Path:
    stem = content.source.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / (out_name or f"{stem}_anon.md")
    assets_stem = out_file.stem  # для именования папки ассетов
    assets_dir = out_dir / f"{assets_stem}_assets"
    assets_files_dir = assets_dir / "assets"
    attachments_dir = assets_dir / "attachments"

    lines, manifest_assets = build_document_text(content, mapper)

    # Картинки и внедрённые файлы выносятся как есть (БЕЗ анонимизации — см. README/план).
    for block in content.blocks:
        if isinstance(block, ImageBlock):
            assets_files_dir.mkdir(parents=True, exist_ok=True)
            (assets_files_dir / f"{block.asset_id}.{block.ext}").write_bytes(block.data)
        elif isinstance(block, EmbeddedBlock):
            attachments_dir.mkdir(parents=True, exist_ok=True)
            disk_name = f"{block.asset_id}__{block.original_filename}"
            (attachments_dir / disk_name).write_bytes(block.data)

    # Сводка по документу в начало.
    header = (
        f"<!-- DOC: source={content.source.name} | format={content.source_format} | "
        f"entities: {_fmt_counts(_pseudonym_counts(lines))} | "
        f"assets: {_fmt_counts(_asset_counts(manifest_assets))} -->"
    )
    lines.insert(0, header)

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if manifest_assets:
        assets_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source": content.source.name,
            "source_format": content.source_format,
            "assets": manifest_assets,
        }
        (assets_dir / "index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return out_file


# --------------------------------------------------------------------------
# Excel -> markdown (секции по листам + markdown-таблицы)
# --------------------------------------------------------------------------

def write_excel(content: ExcelContent, out_dir: Path, mapper, out_name: str | None = None) -> Path:
    stem = content.source.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / (out_name or f"{stem}_anon.md")
    assets_stem = out_file.stem

    lines: list[str] = []
    for ws in content.workbook.worksheets:
        title = anonymize_text(ws.title, mapper)
        lines.append(f"## Лист: {title}")
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            cells = []
            for v in row:
                if v is None:
                    cells.append("")
                elif isinstance(v, str):
                    cells.append(anonymize_text(v, mapper))
                else:
                    cells.append(str(v))
            if any(c.strip() for c in cells):
                rows.append(cells)
        lines.extend(_md_table(rows))
        lines.append("")

    # Сводка по документу в начало.
    media_counts = {"media": len(content.media)} if content.media else {}
    header = (
        f"<!-- DOC: source={content.source.name} | format=xlsx | "
        f"entities: {_fmt_counts(_pseudonym_counts(lines))} | "
        f"assets: {_fmt_counts(media_counts)} -->"
    )
    lines.insert(0, header)

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Медиа из книги — выносим в assets (БЕЗ анонимизации).
    if content.media:
        assets_dir = out_dir / f"{assets_stem}_assets"
        assets_files_dir = assets_dir / "assets"
        assets_files_dir.mkdir(parents=True, exist_ok=True)
        manifest_assets = []
        for m in content.media:
            file_name = f"{m.asset_id}.{m.ext}"
            (assets_files_dir / file_name).write_bytes(m.data)
            manifest_assets.append({
                "id": m.asset_id,
                "file": f"assets/{file_name}",
                "anchor": "",
                "src_page": None,
                "src_format": "xlsx",
                "note": f"из {m.src_path}",
            })
        manifest = {
            "source": content.source.name,
            "source_format": "xlsx",
            "assets": manifest_assets,
        }
        (assets_dir / "index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # JSON-датасет структуры полей ЭФ (канонический слой данных для скиллов).
    # Рядом с <stem>_anon.md кладём <stem>_anon.json.
    try:
        write_spec_json(content, out_dir, mapper, out_name=assets_stem)
    except Exception as exc:  # не должен валить анонимизацию ради датасета
        out_file.write_text(
            out_file.read_text(encoding="utf-8") + f"\n<!-- SPEC_EXTRACTOR_ERROR: {exc!r} -->",
            encoding="utf-8",
        )
    return out_file


# --------------------------------------------------------------------------
# Диспетчер записи
# --------------------------------------------------------------------------

def _add_review_cand(store: dict, c: dict, loc: dict) -> None:
    """Сгруппировать кандидата по (value, type_guess), собирая locations."""
    key = (c["value"].lower(), c["type_guess"])
    entry = store.get(key)
    if entry is None:
        entry = {
            "value": c["value"],
            "type_guess": c["type_guess"],
            "reason": c["reason"],
            "example_context": c["context"],
            "locations": [],
            "count": 0,
        }
        store[key] = entry
    entry["locations"].append(loc)
    entry["count"] += 1


def collect_review_candidates(content, mapper) -> dict:
    """Собрать ревью-кандидатов по всему контенту с location.

    Возвращает {schema_version, source, summary, candidates}. source.file_name_anon
    и locations[].sheet анонимизированы через mapper (как в spec_extractor) —
    review-файл лежит рядом с обезличенным датасетом и не должен утекать
    названием продукта/СК. Сырые значения пропущенных сущностей в `candidates[]`
    остаются намеренно — ради этого ревью и существует (человек их разбирает).
    """
    store: dict = {}
    if isinstance(content, ExcelContent):
        for ws in content.workbook.worksheets:
            sheet_name_anon = anonymize_text(ws.title, mapper)
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.strip():
                        for c in find_review_candidates(cell.value):
                            _add_review_cand(store, c, {
                                "sheet": sheet_name_anon,
                                "row": cell.row, "cell": cell.coordinate,
                            })
    else:
        for i, block in enumerate(content.blocks):
            if isinstance(block, TextBlock):
                for c in find_review_candidates(block.text):
                    _add_review_cand(store, c, {"block_index": i})
            elif isinstance(block, TableBlock):
                for ridx, r in enumerate(block.rows):
                    for cidx, cell in enumerate(r):
                        for c in find_review_candidates(cell):
                            _add_review_cand(store, c, {
                                "block_index": i, "row": ridx, "col": cidx,
                            })

    candidates = list(store.values())
    by_type: dict[str, int] = {}
    for c in candidates:
        by_type[c["type_guess"]] = by_type.get(c["type_guess"], 0) + 1
    return {
        "schema_version": "1.0",
        "source": {"file_name_anon": anonymize_text(content.source.name, mapper)},
        "summary": {"total": len(candidates), "by_type": by_type},
        "candidates": candidates,
    }


def write_review_file(content, out_dir: Path, stem: str, mapper) -> Path | None:
    """Записать <stem>_review.json рядом с результатом, если есть кандидаты.

    При отсутствии кандидатов устаревший файл удаляется — иначе сводка в CLI
    будет читать прошлый прогон, а рядом с обезличенным датасетом останется
    файл с устаревшими (и, до фикса source-анонимации, сырыми) значениями.
    """
    try:
        review = collect_review_candidates(content, mapper)
    except Exception:
        return None
    path = out_dir / f"{stem}_review.json"
    if not review["summary"]["total"]:
        if path.exists():
            path.unlink()
        return None
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_content(content, out_dir: Path, mapper, out_name: str | None = None) -> Path:
    if isinstance(content, ExcelContent):
        out_file = write_excel(content, out_dir, mapper, out_name)
    else:
        out_file = write_document(content, out_dir, mapper, out_name)
    # Ревью-кандидаты — рядом с результатом (только если есть).
    write_review_file(content, out_dir, out_file.stem, mapper)
    return out_file