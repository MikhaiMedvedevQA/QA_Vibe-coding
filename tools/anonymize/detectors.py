"""Распознавание сущностей для анонимизации.

Возвращает список совпадений (значение, тип, start, end) для фрагмента текста.
Подход — regex для структурированных PII + сопоставление со справочниками
для банков/страховых/продуктов/оргов/известных лиц + эвристики для ФИО и адресов.

Перекрытия совпадений разрешаются в пользу более длинного совпадения
(см. resolve_overlaps). Порядок регистрации детекторов влияет только на
приоритет при равной длине.
"""

import re
from dataclasses import dataclass

from config import ENTITY_TYPES, DICT_DIR, IGNORE_PATH


@dataclass(frozen=True)
class Match:
    value: str
    type: str
    start: int
    end: int

    def __len__(self):
        return self.end - self.start


# --------------------------------------------------------------------------
# Омоглифы: латинские буквы, визуально неотличимые от кириллических.
# Нормализуем латиницу -> кириллицу, но ТОЛЬКО в словах, содержащих кириллицу
# (чистую латиницу: Allianz, AIG, MetLife, PRODUCT_0011 — не трогаем). Лечит
# «Cогласие-Вита» (лат. C + кириллица) -> «Согласие-Вита» -> детектор СК срабатывает.
# --------------------------------------------------------------------------

_LAT2CYR = {
    "A": "А", "a": "а", "C": "С", "c": "с", "E": "Е", "e": "е",
    "O": "О", "o": "о", "P": "Р", "p": "р", "H": "Н", "h": "н",
    "K": "К", "k": "к", "M": "М", "m": "м", "T": "Т", "t": "т",
    "X": "Х", "x": "х", "Y": "У", "y": "у", "B": "В", "b": "в",
}
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
# Слово = буквы + внутренние дефисы (чтобы «Cогласие-Вита» было одним токеном).
_HOMO_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*")


def fix_cyr_homoglyphs(text: str) -> str:
    """Заменить латинские омоглифы на кириллицу в словах, содержащих кириллицу."""
    if not text:
        return text

    def repl(m: "re.Match") -> str:
        w = m.group(0)
        if _CYR_RE.search(w):
            return "".join(_LAT2CYR.get(ch, ch) for ch in w)
        return w

    return _HOMO_WORD_RE.sub(repl, text)


# --------------------------------------------------------------------------
# Справочники: грузятся один раз, кешируются.
# --------------------------------------------------------------------------

_dict_cache: dict[str, list[str]] = {}


def load_dictionary(entity_type: str) -> list[str]:
    """Загрузить строки справочника для типа. Пустые строки и комментарии (#) пропускаются."""
    if entity_type in _dict_cache:
        return _dict_cache[entity_type]
    name = ENTITY_TYPES[entity_type][0]
    entries: list[str] = []
    if name:
        path = DICT_DIR / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    entries.append(line)
    # Длинные сначала — чтобы «Сбербанк» не перекрывался более длинным вариантом.
    entries.sort(key=len, reverse=True)
    _dict_cache[entity_type] = entries
    return entries


def _dict_detector(entity_type: str, text: str) -> list[Match]:
    entries = load_dictionary(entity_type)
    if not entries:
        return []
    # Граница слова для кириллицы/латиницы: не должно быть буквы по краям.
    # Каждое entry ищем отдельным проходом, чтобы собрать и перекрывающиеся
    # совпадения (напр. «ИП МАРТЫЩЕНКО» и «МАРТЫЩЕНКО М. В.») — иначе finditer,
    # найдя короткое, продолжит после него и пропустит длинное. Финальный
    # выбор длинного из перекрывающихся делает resolve_overlaps.
    patterns = _compiled_entries(entity_type)
    out = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            out.append(Match(m.group(1), entity_type, m.start(1), m.end(1)))
    return out


_compiled_cache: dict[str, list[re.Pattern]] = {}


def _compiled_entries(entity_type: str) -> list[re.Pattern]:
    if entity_type in _compiled_cache:
        return _compiled_cache[entity_type]
    entries = load_dictionary(entity_type)
    patterns = [
        re.compile(
            r"(?<![А-Яа-яЁёA-Za-z])(" + re.escape(e) + r")(?![А-Яа-яЁёA-Za-z])",
            re.IGNORECASE,
        )
        for e in entries
    ]
    _compiled_cache[entity_type] = patterns
    return patterns


# --------------------------------------------------------------------------
# Regex-детекторы структурированных PII.
# --------------------------------------------------------------------------

# Телефон: +7/8/7 + 10 цифр, с разделителями; либо прямой московский (495) xxx-xx-xx.
_PHONE_RE = re.compile(
    r"""
    (?<!\d)
    (?:\+7|7|8)\s*\(?\d{3}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}
    |
    (?<!\d)\(?\d{3}\)?[\s\-]*\d{2}[\s\-]*\d{2}[\s\-]*\d{2}
    (?!\d)
    """,
    re.VERBOSE,
)

_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])")

# ИНН: 10 (юрлицо) или 12 (физлицо) цифр, опционально с префиксом «ИНН».
_INN_RE_ANCHORED = re.compile(r"(?i)ИНН[\s:№]*?(\d{12}|\d{10})(?!\d)")
_INN_RE_BARE = re.compile(r"(?<!\d)\d{12}(?!\d)")

# СНИЛС: XXX-XXX-XXX YY или 11 цифр, опционально с префиксом «СНИЛС».
_SNILS_RE_FORMAT = re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}\s\d{2}(?!\d)")
_SNILS_RE_ANCHORED = re.compile(r"(?i)СНИЛС[\s:№]*?(\d{11})(?!\d)")

# Паспорт: серия 4 цифры + номер 6 цифр. Серия может быть записана как «4510» или «45 10».
# Формат без ключевого слова — только NNNN NNNNNN (4+6 через пробел), чтобы не ловить случайные 10 цифр.
_PASSPORT_RE_FORMAT = re.compile(r"(?<!\d)\d{4}\s\d{6}(?!\d)")
# С ключевым словом «серия»/«паспорт» — серия допустима в виде NN NN или NNNN.
_PASSPORT_RE_ANCHORED = re.compile(
    r"(?i)(?:серия|паспорт)[\s:№]*(\d{2}\s?\d{2})\s*(?:номер\s*)?(\d{6})(?!\d)"
)

# Номер карты: 16 цифр, обычно группами по 4.
_CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)")

# Номер счёта: 20 цифр (российский банковский счёт), опционально с префиксом «счёт/счет».
_ACCOUNT_RE_ANCHORED = re.compile(r"(?i)(?:сч[её]т|р/с|к/с)[\s:№]*?(\d{20})(?!\d)")
_ACCOUNT_RE_BARE = re.compile(r"(?<!\d)\d{20}(?!\d)")

# --------------------------------------------------------------------------
# Эвристики ФИО и адресов.
# --------------------------------------------------------------------------

# Контекстные ключи для ФИО.
_PERSON_KEYS = re.compile(
    r"(?i)(страхователь|застрахованн(?:ый|ая|ое)|собственник|выгодоприобретатель|"
    r"клиент|гражданин|гражданка|ФИО|Ф\.И\.О\.|заявитель|паспортодержатель|"
    r"владелец|пользователь|застрахованное\s+лицо)"
)
# ФИО в виде «Фамилия Имя Отчество» или «Фамилия И.О.».
_FIO_RE = re.compile(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}")
_FIO_INITIALS_RE = re.compile(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.")

# Компоненты адреса. Trailing-lookahead на не-букву обязателен, иначе
# сокращения «г»/«д»/«ул»/«пр» матчатся внутри случайных слов («продукт», «газета»).
_ADDR_KEYWORDS = re.compile(
    r"(?i)(?:^|(?<=[^А-Яа-яЁёA-Za-z]))"
    r"(?:г\.?|город|обл\.?|область|респ\.?|республика|край|ул\.?|улица|"
    r"пр\.?|пр-т\.?|проспект|пер\.?|переулок|ш\.?|шоссе|пл\.?|площадь|"
    r"д\.?|дом|корп\.?|строение|стр\.?|кв\.?|квартира|офис|литера|"
    r"мкр\.?|микрорайон|нп\.?|населённый\s+пункт)"
    r"(?=[^А-Яа-яЁёA-Za-z]|$)"
)
_INDEX_RE = re.compile(r"(?i)(?:индекс|почтовый\s+индекс)\s*[:№]?\s*(\d{6})")


# --------------------------------------------------------------------------
# Функции-детекторы.
# --------------------------------------------------------------------------

def detect_phone(text: str) -> list[Match]:
    return [Match(m.group(0), "PHONE", m.start(), m.end()) for m in _PHONE_RE.finditer(text)]


def detect_email(text: str) -> list[Match]:
    return [Match(m.group(0), "EMAIL", m.start(), m.end()) for m in _EMAIL_RE.finditer(text)]


def detect_inn(text: str) -> list[Match]:
    out = []
    for m in _INN_RE_ANCHORED.finditer(text):
        s, e = m.start(1), m.end(1)
        out.append(Match(text[s:e], "INN", s, e))
    for m in _INN_RE_BARE.finditer(text):
        # Дубли с anchored разрешаются дальше по длине (они одинаковые -> не страшно).
        out.append(Match(m.group(0), "INN", m.start(), m.end()))
    return out


def detect_snils(text: str) -> list[Match]:
    out = []
    for m in _SNILS_RE_FORMAT.finditer(text):
        out.append(Match(m.group(0), "SNILS", m.start(), m.end()))
    for m in _SNILS_RE_ANCHORED.finditer(text):
        s, e = m.start(1), m.end(1)
        out.append(Match(text[s:e], "SNILS", s, e))
    return out


def detect_passport(text: str) -> list[Match]:
    out = []
    for m in _PASSPORT_RE_FORMAT.finditer(text):
        out.append(Match(m.group(0), "PASSPORT", m.start(), m.end()))
    for m in _PASSPORT_RE_ANCHORED.finditer(text):
        # Полное совпадение «серия + номер» заменяем целиком.
        out.append(Match(m.group(0), "PASSPORT", m.start(), m.end()))
    return out


def detect_card(text: str) -> list[Match]:
    return [Match(m.group(0), "CARD", m.start(), m.end()) for m in _CARD_RE.finditer(text)]


def detect_account(text: str) -> list[Match]:
    out = []
    for m in _ACCOUNT_RE_ANCHORED.finditer(text):
        s, e = m.start(1), m.end(1)
        out.append(Match(text[s:e], "ACCOUNT", s, e))
    for m in _ACCOUNT_RE_BARE.finditer(text):
        out.append(Match(m.group(0), "ACCOUNT", m.start(), m.end()))
    return out


def detect_person(text: str) -> list[Match]:
    """ФИО: из справочника известных лиц + эвристика по контекстным ключам."""
    out = _dict_detector("PERSON", text)
    # Эвристика: после ключевого слова («страхователь», «клиент» ...) берём следующие ФИО.
    for kw in _PERSON_KEYS.finditer(text):
        tail = text[kw.end(): kw.end() + 60]
        for m in _FIO_RE.finditer(tail):
            out.append(Match(m.group(0), "PERSON", kw.end() + m.start(), kw.end() + m.end()))
            break  # только первое ФИО после ключа
        for m in _FIO_INITIALS_RE.finditer(tail):
            out.append(Match(m.group(0), "PERSON", kw.end() + m.start(), kw.end() + m.end()))
            break
    return out


def detect_address(text: str) -> list[Match]:
    """Адрес: индекс NNNNNN + фраза, склеенная от адресного ключевого слова
    через запятые/числа/имена (г. Москва, ул. Ленина, д. 5, кв. 12 -> одно совпадение).
    Эвристика; не претендует на идеальное выделение адреса."""
    out = []
    # Индекс.
    for m in _INDEX_RE.finditer(text):
        s, e = m.start(1), m.end(1)
        out.append(Match(text[s:e], "ADDR", s, e))

    for kw in _ADDR_KEYWORDS.finditer(text):
        i = kw.start()
        j = kw.end()
        # Сразу после ключевого слова может идти имя (название города/улицы).
        m2 = re.match(r"[ \t]*[А-ЯЁ][а-яё\-]+", text[j:])
        if m2:
            j += m2.end()
        # Дальше склеиваем компоненты через запятые/пробелы.
        while j < len(text):
            k = j
            while k < len(text) and text[k] in " \t":
                k += 1
            if k < len(text) and text[k] == ",":
                k += 1
                while k < len(text) and text[k] in " \t":
                    k += 1
            km = _ADDR_KEYWORDS.match(text, k)
            if km:
                j = km.end()
                m3 = re.match(r"[ \t]*[А-ЯЁ][а-яё\-]+", text[j:])
                if m3:
                    j += m3.end()
                continue
            num = re.match(r"\d+", text[k:])
            if num:
                j = k + num.end()
                continue
            break
        phrase = text[i:j].strip(" ,.;")
        if phrase and len(phrase) >= 3:
            out.append(Match(phrase, "ADDR", i, j))
    return out


def detect_bank(text: str) -> list[Match]:
    return _dict_detector("BANK", text)


def detect_ins(text: str) -> list[Match]:
    return _dict_detector("INS", text)


def detect_product(text: str) -> list[Match]:
    """Продукты: «+» трактуется как разделитель с любым расположением пробелов
    (НСЖ + ПДС, НСЖ+ПДС, НСЖ +ПДС, НСЖ+ ПДС — одно и то же). Найденное значение
    нормализуется к каноничному «X + Y», чтобы все варианты давали один псевдоним."""
    entries = load_dictionary("PRODUCT")
    if not entries:
        return []
    patterns = _product_compiled()
    out = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            val = _normalize_product(m.group(1))
            out.append(Match(val, "PRODUCT", m.start(1), m.end(1)))
    return out


_PLUS_RE = re.compile(r"\s*\+\s*")


def _normalize_product(s: str) -> str:
    """Привести написание продукта с '+' к каноничному виду: 'X + Y'."""
    return _PLUS_RE.sub(" + ", s).strip()


_product_compiled_cache: list[re.Pattern] | None = None


def _product_compiled() -> list[re.Pattern]:
    global _product_compiled_cache
    if _product_compiled_cache is not None:
        return _product_compiled_cache
    entries = load_dictionary("PRODUCT")
    patterns = []
    for entry in entries:
        # Каждую часть вокруг '+' экранируем отдельно, а сам '+' заменяем на
        # \s*\+\s* — тогда одна запись матчит любое расположение пробелов.
        parts = [re.escape(p.strip()) for p in entry.split("+")]
        body = r"\s*\+\s*".join(parts)
        patterns.append(re.compile(
            r"(?<![А-Яа-яЁёA-Za-z])(" + body + r")(?![А-Яа-яЁёA-Za-z])",
            re.IGNORECASE,
        ))
    _product_compiled_cache = patterns
    return patterns


def detect_org(text: str) -> list[Match]:
    return _dict_detector("ORG", text)


# Порядок детекторов: специфичные/длинные сущности идут раньше,
# чтобы при разрешении перекрытий совпадение более специфичного детектора
# имело приоритет при равной длине.
DETECTORS = [
    detect_email,       # email не пересекается с другими, но пусть идёт первым
    detect_phone,
    detect_card,
    detect_account,
    detect_inn,
    detect_snils,
    detect_passport,
    detect_bank,
    detect_ins,
    detect_product,
    detect_org,
    detect_person,
    detect_address,
]


def resolve_overlaps(matches: list[Match]) -> list[Match]:
    """Оставить непересекающиеся совпадения, выбирая более длинное при перекрытии.

    Совпадения с одинаковым span и типом — дедуплицируются.
    """
    if not matches:
        return []
    # Дедуп.
    seen = set()
    uniq = []
    for m in matches:
        key = (m.value, m.type, m.start, m.end)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(m)
    # При перекрытии предпочитаем более длинное совпадение: сортируем по убыванию
    # длины, затем по началу, и берём непересекающиеся с уже выбранными.
    # Это нужно, чтобы «МАРТЫЩЕНКО М. В.» (16) побеждало «ИП МАРТЫЩЕНКО» (13),
    # а не наоборот — иначе от ФИО остаётся хвост из инициалов.
    uniq.sort(key=lambda m: (-len(m), m.start))
    chosen: list[Match] = []
    occupied: list[tuple[int, int]] = []
    for m in uniq:
        if all(m.end <= s or m.start >= e for s, e in occupied):
            chosen.append(m)
            occupied.append((m.start, m.end))
    # Возвращаем в порядке появления в тексте.
    chosen.sort(key=lambda m: m.start)
    return chosen


def find_all(text: str) -> list[Match]:
    """Запустить все детекторы и разрешить перекрытия."""
    all_matches: list[Match] = []
    for d in DETECTORS:
        try:
            all_matches.extend(d(text))
        except Exception:
            # Детектор не должен валить весь прогон; логируется вызывающим.
            continue
    return resolve_overlaps(all_matches)


# --------------------------------------------------------------------------
# Ревью-кандидаты: похоже на сущность (СК/продукт/банк/ФИО), но детектор НЕ
# заменил. Не игнорируем такие совпадения молча — флагируем для разбора
# человеком (см. dictionaries/ignore.txt — white-list проверенных пропусков).
# --------------------------------------------------------------------------

from extractors import _norm  # noqa: E402  (поздний импорт — extractors не зависит от detectors)

# Псевдоним вида PERSON_0001 — уже заменённое значение, не кандидат.
_PSEUDO_RE = re.compile(r"^[A-Z]+_\d{4}$")

# Стоп-слова: служебные/общие слова, которые не могут быть названием сущности.
_STOPWORDS = {
    "и", "или", "не", "для", "по", "при", "если", "то", "все", "всех", "всем",
    "остальные", "остальных", "иных", "других", "другие", "на", "в", "с", "со",
    "выбора", "значения", "значение", "поле", "наименование", "поля", "нет",
    "да", "только", "кроме", "без", "до", "после", "укажите", "необходимо",
    "выбрать", "должно", "должен", "страхования", "страховки", "новое", "поле",
}
# Префиксы, с которых не может начинаться название сущности (имя поля/блока/формы).
_STOPWORD_PREFIXES = ("блок ", "поле ", "наименование ", "документ ", "форма ",
                      "раздел ", "группа ", "доступные значения ")

# Lookahead-конструкции для контекстных паттернов: значение заканчивается на
# разделитель [;:,\n], конец строки ИЛИ пробел + стоп-слово с границей слова
# (\s+...\b) — иначе «ед|и|ное» резалось бы на «ед».
_LA_ORG = (r"(?=\s+(?:и|или|для|по|не|при|то|если|кроме|без|после|до|только|"
           r"указан|загружен|является)\b|[;:,\n]|$)")
_LA_PROD = (r"(?=\s+(?:на|по|для|при|то|если|кроме|без|после|до|только|не|и|или|"
            r"указан|загружен|определяется|необходимо|должно|поле|значение|"
            r"выводится|отображается)\b|[;:,\n]|$)")
_LA_PERSON = r"(?=\s+(?:не|для|по|при|то|если|и|или)\b|[;,\n]|\(|$)"

# Контекстные паттерны: (метка причины, regex с группами-значениями, type_guess).
# Каждое совпадение может давать список значений (через ','/'(';')') — разбиваем.
_REVIEW_PATTERNS: list[tuple[str, "re.Pattern[str]", str]] = [
    (
        "партнёр",
        re.compile(
            r"партн[её]р\w*\s+(?:«([^»]+)»|\(([^)]+)\)|([^\n;,]{1,40}?))" + _LA_ORG,
            re.IGNORECASE),
        "ORG",
    ),
    (
        "программа",
        re.compile(
            r"программ\w*\s+([^\n:;,]{1,40}?)" + _LA_PROD,
            re.IGNORECASE),
        "PRODUCT",
    ),
    (
        "продукт",
        re.compile(
            r"продукт\w*\s+([^\n:;,]{1,40}?)" + _LA_PROD,
            re.IGNORECASE),
        "PRODUCT",
    ),
    (
        "значения для выбора",
        re.compile(
            r"(?:для\s+выбора|доступные\s+значения[^\n:]*?)[:]\s*([^;\n]{1,120}?)(?=[;\n]|$)",
            re.IGNORECASE),
        "INS",
    ),
    (
        "пользователь",
        re.compile(
            r"пользовател\w*\s+(?:«([^»]+)»|\(([^)]+)\)|([^\n(;,]{1,40}?))" + _LA_PERSON,
            re.IGNORECASE),
        "PERSON",
    ),
]

# Значение-кандидат должно начинаться с заглавной буквы или цифры (имя собственное).
# Отсекает служебные фразы «на ЭФ определяется тем», «в НТ», «не устранит замечания».
_CAPITAL_RE = re.compile(r"^[А-ЯЁA-Z0-9]")


def load_ignore() -> set[str]:
    """White-list проверенных пропусков (lower). Кешируется."""
    if not hasattr(load_ignore, "_cache"):
        s: set[str] = set()
        if IGNORE_PATH.exists():
            for line in IGNORE_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    s.add(line.lower())
        load_ignore._cache = s  # type: ignore[attr-defined]
    return load_ignore._cache  # type: ignore[attr-defined]


def _value_spans(norm: str, val: str, search_from: int) -> list[tuple[int, int]]:
    """Все вхождения val в norm начиная с search_from (для проверки перекрытия с match)."""
    out: list[tuple[int, int]] = []
    i = norm.find(val, search_from)
    while i >= 0:
        out.append((i, i + len(val)))
        i = norm.find(val, i + 1)
    return out


def find_review_candidates(text: str) -> list[dict]:
    """Найти в тексте подозрительные совпадения, не заменённые детектором.

    Возвращает список {value, type_guess, context, reason}. Контекстный детектор:
    флагует значения после ключей «партнёр / программа / продукт / для выбора /
    пользователь», если они не стали псевдонимом и не перекрыты уже найденной
    сущностью. «Согласие на обработку ПД» (имя поля без контекста) — НЕ кандидат.
    """
    if not text:
        return []
    norm = fix_cyr_homoglyphs(_norm(text))
    matches = find_all(norm)
    ignore = load_ignore()

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ctx_label, pattern, type_guess in _REVIEW_PATTERNS:
        for m in pattern.finditer(norm):
            raw = next((g for g in m.groups() if g), None)
            if not raw:
                continue
            # Список значений может быть перечислен через ','/'('.
            for part in re.split(r"[,(\n]", raw):
                val = part.strip().strip("«»\"'").strip(" ;:.")
                if len(val) < 2 or _PSEUDO_RE.match(val):
                    continue
                if not _CAPITAL_RE.match(val):
                    continue  # служебная фраза, не имя собственное
                low = val.lower()
                if low in ignore or low in _STOPWORDS:
                    continue
                if any(low.startswith(p) for p in _STOPWORD_PREFIXES):
                    continue
                # Перекрытие с уже заменённой детектором сущностью -> не кандидат.
                spans = _value_spans(norm, val, max(0, m.start() - 5))
                if not spans:
                    spans = _value_spans(norm, val, 0)
                if spans and any(
                    not (vend <= mm.start or vstart >= mm.end)
                    for vstart, vend in spans for mm in matches
                ):
                    continue
                key = (val.lower(), type_guess)
                if key in seen:
                    continue
                seen.add(key)
                ctx = norm[max(0, m.start() - 25): min(len(norm), m.end() + 25)].strip()
                out.append({
                    "value": val,
                    "type_guess": type_guess,
                    "context": ctx,
                    "reason": ctx_label,
                })
    return out