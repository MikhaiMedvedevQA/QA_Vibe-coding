---
name: python-create-test-template
description: Создаёт каркас проекта автотестов на Python: папки, Page Object, conftest, pytest.ini/pyproject.toml, README и минимальный пример теста.
---

# Скилл: создание стартового шаблона автотестов

## Назначение

Создать каркас проекта автотестов на Python.

## Когда использовать

Пользователь хочет начать новый учебный или рабочий проект автотестов.

## Шаги

1. Уточнить инструмент: Selenium или Playwright.
2. Создать структуру папок:
   - `tests/`
   - `pages/` (Page Object)
   - `conftest.py`
   - `pytest.ini` или `pyproject.toml`
   - `README.md`
3. Написать минимальный пример теста.
4. Написать базовый Page Object для одной страницы.
5. Проверить, что `pytest --collect-only` не падает.

## Формат файлов

Следовать правилам нейминга из `CLAUDE.md`. Шаблоны проектов хранить в `templates/`.
