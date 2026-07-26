"""Проверки ревью-кандидатов: флагуем пропущенные сущности, не флагуем имена полей."""

import detectors
from detectors import find_review_candidates


def review_values(text: str) -> list[str]:
    return [c["value"] for c in find_review_candidates(text)]


def _empty_ignore():
    """Изолировать тесты детектора от реального dictionaries/ignore.txt:
    белый список считается пустым, чтобы проверять именно логику флагования."""
    return set()


def _patch_ignore(monkeypatch):
    monkeypatch.setattr(detectors, "load_ignore", _empty_ignore)


def test_consent_as_npf_value_is_candidate(monkeypatch):
    """«Согласие» как значение НПФ в списке выбора — кандидат (нет в insurance.txt
    без суффикса, а контекст «для выбора» указывает на значение справочника)."""
    _patch_ignore(monkeypatch)
    text = "Доступные значения в поле «Наименование НПФ» для выбора: Согласие; Ингосстрах"
    vals = review_values(text)
    assert "Согласие" in vals
    # Ингосстрах есть в insurance.txt -> детектор заменит -> не кандидат.
    assert "Ингосстрах" not in vals


def test_consent_field_name_not_candidate():
    """«Согласие на обработку ПД» — название поля, без контекста значений ->
    НЕ кандидат (иначе ломает читаемость чек-листов)."""
    assert review_values("Согласие на обработку ПД") == []
    assert review_values("Отметить Согласие на доп.услугу ПДС") == []


def test_program_not_in_dict_is_candidate(monkeypatch):
    """Программа, которой нет в products.txt — кандидат."""
    _patch_ignore(monkeypatch)
    text = "Для партнёра BANK_0005 и программы Вита НоваяПрограмма: Срок = 1 день."
    vals = review_values(text)
    assert "Вита НоваяПрограмма" in vals


def test_pseudonyms_not_candidates():
    """Уже подставленные псевдонимы — не кандидаты."""
    text = "партнёр BANK_0005 и программы PRODUCT_0003: правило едино."
    vals = review_values(text)
    assert "BANK_0005" not in vals
    assert "PRODUCT_0003" not in vals


def test_partner_unknown_org_is_candidate(monkeypatch):
    """Неизвестный партнёр — кандидат (ORG)."""
    _patch_ignore(monkeypatch)
    vals = review_values("Только для партнёра «ИП Ромашка» и только в программе X")
    assert "ИП Ромашка" in vals


def test_homoglyph_consent_vita_not_candidate_after_fix():
    """«Cогласие-Вита» (лат. C) после омоглиф-фикса заменяется детектором ->
    не кандидат (он в insurance.txt кириллическим написанием)."""
    text = "Отображается, если пользователь Cогласие-Вита (для Собственной сети не смотрим)"
    vals = review_values(text)
    # Пользователь-контекст мог бы зацепить, но значение после омоглиф-фикса
    # совпадает со справочником -> перекрыто match -> не кандидат.
    assert "Cогласие-Вита" not in vals
    assert "Согласие-Вита" not in vals


def test_empty_and_plain_text_no_candidates():
    assert review_values("") == []
    assert review_values("обычный текст без сущностей и контекстов") == []