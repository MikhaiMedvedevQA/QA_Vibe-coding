---
name: qaagent-repo-guide
description: Помогает Claude Code и коллегам работать с репозиторием дипломного проекта QA-Ассистент — ориентироваться в структуре, запускать анонимизатор (CLI/GUI), прогонять тесты и проверять ошибки, вносить изменения, актуализировать README и не нарушать конфиденциальность. Использовать в начале работы с репозиторием, при онбординге нового человека или при любых правках кода/документации/скиллов.
---

# Скилл: гид по репозиторию QA-Ассистент

Внутренний runbook проекта. Цель — чтобы и агент, и новый коллега могли без лишних вопросов развернуть проект, запустить его, внести правку и не сломать README / не слить в репо конфиденциальное.

## Когда использовать

- Первый запуск / онбординг: «как поднять проект?».
- Перед внесением правок в код, скиллы, агентов или README.
- При проверке ошибок (тесты, импорты, прогон).
- Когда коллега спрашивает «с чего начать?».

## Что это за проект

**QA-Ассистент: Анонимизированный генератор чек-листов** — конвейер из двух слоёв:

- **Слой данных (стабильный):** Excel/документ → анонимизатор (`tools/anonymize`) → JSON-датасет полей ЭФ.
- **Слой генерации (меняется часто):** JSON-датасет → скиллы Claude Code → Markdown-чек-листы.

Полное описание — в корневом `README.md` и `reports/Diplom Project/project-card.md`.

## Карта репозитория

```
.
├── tools/
│   ├── anonymize/            # ядро: анонимизатор (Python)
│   │   ├── anonymize.py      # CLI: python tools/anonymize/anonymize.py <файл|папка>
│   │   ├── extractors.py     # извлечение текста/изображений из pdf/docx/xlsx/txt
│   │   ├── spec_extractor.py # извлечение структуры полей ЭФ в JSON-датасет
│   │   ├── detectors.py      # детекторы сущностей, омоглиф-фикс, review-кандидаты
│   │   ├── writers.py        # запись вывода, сборка review-файла
│   │   ├── mapper.py         # устойчивый маппинг «оригинал → псевдоним»
│   │   ├── config.py         # типы сущностей, справочники, форматы псевдонимов
│   │   ├── mapping.example.json  # пустой шаблон маппинга (реальный mapping.json в .gitignore)
│   │   ├── dictionaries/     # словари сущностей: *.example.txt — шаблоны, *.txt — локально
│   │   └── tests/            # pytest-кейсы (detectors, review-candidates)
│   ├── anonymize_gui/        # десктоп-GUI на Tkinter
│   │   └── app.py            # python tools/anonymize_gui/app.py
│   └── deanonymize/          # деанонимайзер артефактов по mapping.json
│       └── deanonymize.py    # python tools/deanonymize/deanonymize.py <файл|папка>
├── .claude/
│   ├── agents/               # router, qa-assistant
│   └── skills/               # скиллы чек-листов + этот qaagent-repo-guide
├── templates/
│   └── test-case/            # образцы стиля чек-листов
├── README.md                 # главная страница репозитория
├── CLAUDE.md                 # инструкции проекту и описание агентов/скиллов
├── .gitignore                # что не попадает в репо
└── reports/Diplom Project/   # документы диплома (project-card.md)
```

## Первая настройка (для нового коллеги)

```bash
# 1. Клонировать
git clone https://github.com/MikhaiMedvedevQA/QA_Vibe-coding.git
cd QA_Vibe-coding

# 2. Виртуальное окружение и зависимости
python -m venv .venv
source .venv/Scripts/activate          # Windows, Git Bash
# source .venv/bin/activate             # Linux/macOS
pip install -r tools/anonymize/requirements.txt

# 3. Подготовить словари и маппинг (один раз) — скопировать шаблоны в реальные имена
cd tools/anonymize
for f in persons banks insurance products orgs ignore; do
  cp "dictionaries/$f.example.txt" "dictionaries/$f.txt"
done
cp mapping.example.json mapping.json
cd ../..
```

Для legacy `.doc` нужен внешний [pandoc](https://pandoc.org/installing.html) — для `.xlsx/.docx/.pdf/.txt` не требуется.

Пустые словари допустимы — детекторы работают и по эвристике (контекстным ключам), словари лишь расширяют ловлю известных названий. `mapping.json` заполняется автоматически при первом прогоне и дозаписывается при следующих.

## Запуск

### CLI

```bash
python tools/anonymize/anonymize.py <входной_файл_или_папка> [--out DIR] [--mapping FILE] [--reset-mapping]
```

| Параметр          | Назначение                                                          |
|-------------------|---------------------------------------------------------------------|
| `input`           | Файл или папка (`.xlsx`, `.pdf`, `.docx`, `.doc`, `.txt`).          |
| `--out`           | Каталог вывода (по умолчанию `anonimized/` рядом с исходником).     |
| `--mapping`       | Путь к файлу маппинга (по умолчанию `tools/anonymize/mapping.json`).|
| `--reset-mapping` | Начать с чистого маппинга (нарушает консистентность псевдонимов).   |

Результаты — в папке `anonimized/`:
- `<stem>_anon.md` — обезличенный текст.
- `<stem>_anon.json` — JSON-датасет полей ЭФ (только для `.xlsx`).
- `<stem>_anon_review.json` — кандидаты на ручной разбор.
- `<stem>_anon_assets/` — вынесенные изображения с манифестом `index.json`.
- `index.json` — сводный индекс по всем документам.

### GUI

```bash
python tools/anonymize_gui/app.py
```

Выбор файла → анонимизация с предпросмотром «до/после» → сохранение рядом с исходником. Панель ревью — разбор кандидатов и кнопка «В ignore.txt».

### Деанонимизация артефактов

Чтобы прочитать готовый артефакт в исходном виде (реальные значения вместо псевдонимов) — на той же машине, где есть `mapping.json`:

```bash
python tools/deanonymize/deanonymize.py <файл_или_папка> [--mapping FILE] [--out DIR]
```

| Параметр     | Назначение                                                                                 |
|--------------|--------------------------------------------------------------------------------------------|
| `path`       | Файл-артефакт или папка (рекурсивно `.md`/`.json`; подпапки `*_assets/` пропускаются).      |
| `--mapping`  | Путь к `mapping.json` (по умолчанию `tools/anonymize/mapping.json`).                       |
| `--out`      | Каталог вывода (по умолчанию `deanonimized/` рядом с `anonimized/`).                       |

Вывод: `…_anon.md` → `…_deanon.md`, `…_anon.json` → `…_deanon.json`, `…_anon_review.json` → `…_deanon_review.json`, `index.json` → `_deanon_index.json`. Неразрешённые псевдонимы (нет в `mapping.json`) остаются как есть и печатаются списком. Деанонимизированные файлы содержат **реальные** данные → `deanonimized/` и `*_deanon.*` в `.gitignore`.

## Проверка ошибок (обязательно после правок)

```bash
cd tools/anonymize
python -m pytest               # все тесты
python -m pytest -q            # краткий вывод
python -m pytest tests/test_detectors.py -v        # конкретный файл
python -m pytest -k review     # по ключевому слову
```

Дополнительные проверки при правках ядра:
- Импорты модулей: `python -c "import sys; sys.path.insert(0,'tools/anonymize'); import anonymize, extractors, spec_extractor, detectors, writers, mapper, config"`.
- Прогон на тестовом файле: `python tools/anonymize/anonymize.py <тестовый.xlsx>` — убедиться, что `anonimized/<stem>_anon.json` создался и валиден (`python -c "import json; json.load(open('...'))"`).
- GUI: `python tools/anonymize_gui/app.py` — открыть, прогнать небольшой файл, проверить предпросмотр.

## Рабочий процесс внесения изменений

1. **Понять, что меняется** — код ядра, скилл, агент или документация.
2. **Сначала правка, потом проверка:** внести изменение → `python -m pytest` → при правках ядра — прогон на тестовом файле.
3. **Актуализировать README** (см. ниже), если изменение затрагивает структуру, CLI, список скиллов/агентов или состав репо.
4. **Не коммитить конфиденциальное** (см. ниже).
5. Git-операции (add/commit/push) — только по явной команде человека.

## Когда и как обновлять README

Корневой `README.md` — главная страница репо. Обновлять при:

- **Изменение структуры проекта** — поправить блок «Структура проекта» (дерево).
- **Добавление/удаление/переименование скилла** — обновить таблицу в «Генерация чек-листов» и, если нужно, реестр `.claude/skills/README.md`.
- **Изменение CLI** (новые аргументы, форматы вывода) — обновить таблицу параметров и список результатов в «Запуск анонимизатора».
- **Изменение состава репо / `.gitignore`** — обновить раздел «Конфиденциальность».
- **Новый этап roadmap** — переставить галочки в «Дорожная карта».

Не трогать README ради косметики. Если правка не меняет пользовательский интерфейс/структуру — README можно не трогать.

## Конфиденциальность — критично

В публичный репо **не должны попасть** (см. `.gitignore`):

- `tools/anonymize/dictionaries/*.txt` (кроме `.example`) — реальные сущности (банки, СК, продукты, ФИО, организации).
- `tools/anonymize/mapping.json` — маппинг «оригинал → псевдоним» (по нему восстанавливаются исходные сущности).
- Результаты прогонов: `anonimized/`, `*_anon.md`, `*_anon.json`, `*_anon_review.json`, `*_anon_assets/`.
- Результаты деанонимизации: `deanonimized/`, `*_deanon.md`, `*_deanon.json`, `*_deanon_review.json`, `_deanon_index.json` — восстановленные по `mapping.json` артефакты с реальными значениями.
- `.env`, `.claude/settings.local.json`, `.claude/mcp.json`, `.mcp.json`, `.claude/plans/`.
- Рабочие/личные папки: `work/`, `references/`, `learn/`, `reports/*` (кроме `Diplom Project/`).

Перед коммитом проверять: `git status` не должен содержать словари/`mapping.json`/`*_anon*`/`.env`. Если случайно попали в staging — `git rm --cached <файл>` и убедиться, что путь есть в `.gitignore`.

## Частые проблемы и решения (для коллег)

| Симптом | Причина | Решение |
|---|---|---|
| `ModuleNotFoundError: config` / `detectors` | плоские sibling-импорты пакета | запускать из корня: `python tools/anonymize/anonymize.py …` (в коде уже есть `sys.path.insert`). Не запускать модули из произвольной папки. |
| `mapping.json`/словари пустые → мало замен | не скопированы шаблоны | выполнить шаг 3 «Первой настройки». |
| Ошибка на `.doc` | нет pandoc | установить [pandoc](https://pandoc.org/installing.html) или использовать `.docx`. |
| `git status` показывает `mapping.json`/`*.txt` | файл отслеживается | `git rm --cached <файл>`, проверить `.gitignore`. |
| `LF will be replaced by CRLF` | нормализация переносов на Windows | безобидно, игнорировать. |
| Псевдонимы плодятся / сбивается нумерация | `mapping.json` накопил мусор | `--reset-mapping` (осторожно: нарушает консистентность между документами). |
| Скилл не находится агентом | нет записи в реестре / неверное `name` в YAML | проверить `name:` в `SKILL.md` и строку в `.claude/skills/README.md`. |
| Деанонимизатор: `Файл маппинга не найден` | нет `mapping.json` | сначала прогнать анонимизатор (создаст `mapping.json`), либо указать `--mapping`. |
| Деанонимизатор: много неразрешённых псевдонимов | `mapping.json` не из того прогона / был сброшен | использовать маппинг, актуальный для данных артефактов; нераскрытые псевдонимы остаются как есть. |

## Быстрый онбординг для коллеги (один абзац)

Склонируй репо, создай venv, поставь `tools/anonymize/requirements.txt`, скопируй `*.example.txt` → `*.txt` (persons, banks, insurance, products, orgs, ignore) и `mapping.example.json` → `mapping.json` в `tools/anonymize/`, прогони `python tools/anonymize/anonymize.py <твой_файл.xlsx>` — получишь обезличенный `.md` и JSON-датасет полей. Чек-листы генерируются в Claude Code скиллами из этого датасета (см. таблицу скиллов в корневом README). Чтобы прочитать готовый артефакт в исходном виде — `python tools/deanonymize/deanonymize.py anonimized/` (нужен `mapping.json`). Реальные словари, `mapping.json` и `deanonimized/` в репо не входят — они локальные, не коммить их. GUI: `python tools/anonymize_gui/app.py`.