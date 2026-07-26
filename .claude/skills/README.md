# Скилы проекта

Скилы разложены по папкам в зависимости от того, какой агент или область их использует.

## Структура

- `.claude/skills/router/routing-decision/SKILL.md` — скилы роутера (выбор агента, уточнение запроса).
- `.claude/skills/learn/explain-topic/SKILL.md` — скилы агента обучения автоматизации.
- `.claude/skills/python/create-test-template/SKILL.md` — скилы кодингового агента Python.
- `.claude/skills/qa-generate-test-cases/SKILL.md` — генерация тест-кейсов из User Story.
- `.claude/skills/qa-essay-structured/SKILL.md` — эссе для собеседования Manual QA (структурированная форма).
- `.claude/skills/qa-essay-free/SKILL.md` — эссе для собеседования Manual QA (свободная форма).
- `.claude/skills/shared/naming-conventions/SKILL.md` — общие скилы, используемые несколькими агентами.
- `.claude/skills/pd-review/SKILL.md` — анализ высокоуровневого описания проекта.
- `.claude/skills/test-analysis/SKILL.md` — анализ технического задания на тестируемость.

## Когда какой вариант использовать

- **Структурированный** — когда нужна предсказуемая разбивка по блокам и удобная точечная правка.
- **Свободная форма** — когда нужен «живой» монолитный рассказ без видимых швов между разделами.

## Формат файла скилла

Каждый скилл — это файл `SKILL.md` в собственной подпапке с YAML-шапкой:

```yaml
---
name: short-english-name
description: Когда и зачем использовать этот скилл.
---
```

Тело файла — markdown-описание задачи, шагов и ожидаемого результата.

## Связь с агентами

Агенты из `.claude/agents/*.md` ссылаются на скиллы через `file://.claude/skills/.../SKILL.md` в своих инструкциях или вызывают их по имени из YAML-шапки.
