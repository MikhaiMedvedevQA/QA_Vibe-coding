"""Деанонимизация артефактов.

Восстанавливает читаемые значения в _anon.md / _anon.json / _review.json /
index.json по обратному словарю «псевдоним → оригинал», который строится из
mapping.json анонимизатора (tools/anonymize/mapping.json).
"""