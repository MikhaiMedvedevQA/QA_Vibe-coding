# Скилы проекта

Скилы разложены по папкам в зависимости от того, какой агент или область их использует.

## Структура

- `.claude/skills/router/routing-decision/SKILL.md` — скилы роутера (выбор агента, уточнение запроса).
- `.claude/skills/shared/naming-conventions/SKILL.md` — общие скилы, используемые несколькими агентами.
- `.claude/skills/required-fields/SKILL.md` — обязательность полей ЭФ.
- `.claude/skills/default-values-checklist/SKILL.md` — значения по умолчанию в ЭФ.
- `.claude/skills/field-availability/SKILL.md` — условная доступность/видимость/очистка полей ЭФ.
- `.claude/skills/validation-positive/SKILL.md` — позитивная валидация.
- `.claude/skills/validation-negative/SKILL.md` — негативная валидация.
- `.claude/skills/validation-full/SKILL.md` — полная валидация.
- `.claude/skills/qa-full-coverage/SKILL.md` — полное покрытие (v1).
- `.claude/skills/qa-full-coverage-v2/SKILL.md` — полное покрытие (v2).
- `.claude/skills/test-analysis/SKILL.md` — анализ технического задания на тестируемость.
- `.claude/skills/op-scope/SKILL.md` — разбор ОП в скоуп тестирования.
- `.claude/skills/qaagent-repo-guide/SKILL.md` — гид по репозиторию: структура, запуск, тесты, правки, обновление README, онбординг коллег.

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