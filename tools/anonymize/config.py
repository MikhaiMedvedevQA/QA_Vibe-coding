"""Конфигурация утилиты анонимизации.

Типы сущностей, форматы псевдонимов, пути к справочникам и файлу маппинга.
Менять здесь только при необходимости добавить новый тип сущности.
"""

from pathlib import Path

# Корень пакета = каталог этого файла.
PKG_DIR = Path(__file__).resolve().parent

# Справочники лежат рядом с пакетом.
DICT_DIR = PKG_DIR / "dictionaries"

# White-list проверенных пропусков ревью: слова/фразы, которые человек разобрал и
# решил НЕ анонимизировать (повторные прогоны не флагают их как кандидатов).
IGNORE_PATH = DICT_DIR / "ignore.txt"

# Глобальный маппинг «оригинал -> псевдоним» по умолчанию.
DEFAULT_MAPPING_PATH = PKG_DIR / "mapping.json"

# Имя подпапки для результатов анонимизации (внутри папки исходника).
# Файлов может быть много — складываем их отдельно для дальнейшего тест-анализа.
ANON_SUBDIR = "anonimized"


def output_dir(src_path: Path) -> Path:
    """Каталог вывода по умолчанию: подпапка ANON_SUBDIR внутри папки исходника."""
    return src_path.parent / ANON_SUBDIR

# Тип сущности -> (имя справочника, формат псевдонима).
# Формат с {n:04d} даёт строго 4-значный номер: PERSON_0001, BANK_0042 и т.п.
ENTITY_TYPES = {
    "PERSON":   ("persons.txt",    "PERSON_{n:04d}"),
    "BANK":     ("banks.txt",      "BANK_{n:04d}"),
    "INS":      ("insurance.txt",  "INS_{n:04d}"),
    "PRODUCT":  ("products.txt",   "PRODUCT_{n:04d}"),
    "ORG":      ("orgs.txt",       "ORG_{n:04d}"),
    "PHONE":    (None,             "PHONE_{n:04d}"),
    "EMAIL":    (None,             "EMAIL_{n:04d}"),
    "INN":      (None,             "INN_{n:04d}"),
    "SNILS":    (None,             "SNILS_{n:04d}"),
    "PASSPORT": (None,             "PASSPORT_{n:04d}"),
    "CARD":     (None,             "CARD_{n:04d}"),
    "ACCOUNT":  (None,             "ACCOUNT_{n:04d}"),
    "ADDR":     (None,             "ADDR_{n:04d}"),
}

# Расширения входных файлов, которые поддерживаются.
SUPPORTED_TEXT_EXTS = {".txt", ".pdf", ".doc", ".docx"}
SUPPORTED_EXCEL_EXTS = {".xlsx"}
SUPPORTED_EXTS = SUPPORTED_TEXT_EXTS | SUPPORTED_EXCEL_EXTS


def dict_path(entity_type: str) -> Path | None:
    """Путь к файлу справочника для типа или None, если справочника нет."""
    name = ENTITY_TYPES[entity_type][0]
    return DICT_DIR / name if name else None


def pseudonym_format(entity_type: str) -> str:
    return ENTITY_TYPES[entity_type][1]