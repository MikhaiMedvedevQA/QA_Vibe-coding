"""Персистентный маппинг «оригинал -> псевдоним».

Одно и то же исходное значение всегда отображается в один и тот же псевдоним
между всеми запусками и документами. Состояние хранится в JSON-файле:
{
  "PERSON": {"Иванов Иван Иванович": "PERSON_0001", ...},
  "BANK": {"Сбербанк": "BANK_0001", ...},
  ...
}
"""

import json
from pathlib import Path

from config import ENTITY_TYPES, DEFAULT_MAPPING_PATH, pseudonym_format


class Mapper:
    def __init__(self, mapping_path: Path | None = None, reset: bool = False):
        self.path = Path(mapping_path) if mapping_path else DEFAULT_MAPPING_PATH
        # type -> {original: pseudonym}
        self.mapping: dict[str, dict[str, str]] = {}
        # type -> next sequence number (max существующего + 1)
        self._counters: dict[str, int] = {}
        if reset:
            self.mapping = {}
            self._rebuild_counters()
        else:
            self.load()

    # ---------- загрузка / сохранение ----------

    def load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                self.mapping = json.load(f)
        # Гарантируем наличие ключей для всех известных типов.
        for t in ENTITY_TYPES:
            self.mapping.setdefault(t, {})
        self._rebuild_counters()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Не пишем пустые бакеты — маппинг хранит только реально встреченные сущности.
        clean = {t: bucket for t, bucket in self.mapping.items() if bucket}
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2, sort_keys=True)

    def _rebuild_counters(self) -> None:
        """Следующий номер = max текущих + 1 (или 1, если пусто)."""
        for t in ENTITY_TYPES:
            nums = []
            for pseudo in self.mapping.get(t, {}).values():
                try:
                    nums.append(int(pseudo.rsplit("_", 1)[1]))
                except (ValueError, IndexError):
                    continue
            self._counters[t] = max(nums) + 1 if nums else 1

    # ---------- основное API ----------

    def get(self, original: str, entity_type: str) -> str:
        """Вернуть псевдоним для значения. Если новое — выдать следующий по счёту."""
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Неизвестный тип сущности: {entity_type}")
        original = original.strip()
        bucket = self.mapping.setdefault(entity_type, {})
        if original in bucket:
            return bucket[original]
        n = self._counters.get(entity_type, 1)
        pseudo = pseudonym_format(entity_type).format(n=n)
        bucket[original] = pseudo
        self._counters[entity_type] = n + 1
        return pseudo

    def reverse(self, pseudonym: str) -> str | None:
        """Обратный поиск: псевдоним -> оригинал (для верификации)."""
        for bucket in self.mapping.values():
            for orig, pseudo in bucket.items():
                if pseudo == pseudonym:
                    return orig
        return None

    def stats(self) -> dict[str, int]:
        return {t: len(bucket) for t, bucket in self.mapping.items() if bucket}