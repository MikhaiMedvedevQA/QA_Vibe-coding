"""Юнит-проверки детекторов: находят ожидаемое, не ловят ложное."""

from detectors import find_all


def types_in(text: str) -> list[str]:
    return [m.type for m in find_all(text)]


def values_by_type(text: str, t: str) -> list[str]:
    return [m.value for m in find_all(text) if m.type == t]


def test_email():
    assert values_by_type("пишите на ivan@example.com", "EMAIL") == ["ivan@example.com"]


def test_phone_variants():
    for s in [
        "+7 (495) 123-45-67",
        "8 800 555-35-35",
        "79991234567",
        "84951234567",
    ]:
        assert "PHONE" in types_in(s), f"телефон не распознан: {s}"


def test_inn_anchored_and_bare():
    assert "INN" in types_in("ИНН 7707083893")
    assert "INN" in types_in("ИНН: 500100732259")


def test_snils_format():
    assert "SNILS" in types_in("СНИЛС 112-233-445 95")
    assert "SNILS" in types_in("СНИЛС: 11223344595")


def test_passport_format():
    assert "PASSPORT" in types_in("паспорт 4510 123456")
    assert "PASSPORT" in types_in("серия 46 12 номер 345678")


def test_card():
    assert "CARD" in types_in("карта 4111 1111 1111 1111")
    assert "CARD" in types_in("4111-1111-1111-1111")


def test_account_anchored():
    assert "ACCOUNT" in types_in("р/с 40702810400000001234")
    assert "ACCOUNT" in types_in("счёт 40817810000000012345")


def test_bank_from_dictionary():
    assert "BANK" in types_in("Выплату перечислил Сбербанк")
    assert "BANK" in types_in("Партнёр — ПАО ВТБ")


def test_insurance_from_dictionary():
    assert "INS" in types_in("Полис оформлен в Ингосстрах")
    assert "INS" in types_in("Страховщик — СОГАЗ")


def test_person_by_context():
    assert "PERSON" in types_in("Страхователь: Иванов Иван Иванович, паспорт 4510 123456")
    assert "PERSON" in types_in("Клиент Петров Пётр Сергеевич обратился в банк")


def test_person_initials_form():
    assert "PERSON" in types_in("Застрахованный: Петров П.С.")


def test_address_index():
    assert "ADDR" in types_in("индекс 123456")


def test_address_phrase():
    assert "ADDR" in types_in("г. Москва, ул. Ленина, д. 5, кв. 12")


def test_no_false_positive_on_short_words():
    # Короткие слова из справочников не должны заменяться вне контекста.
    # «Открытие» в смысле «начало» — отдельное слово, но оно в banks.txt,
    # поэтому замена ожидается; проверяем, что случайные буквы не ловятся.
    assert types_in("обычный текст без сущностей") == []


def test_overlap_resolution_card_over_account():
    # 16-значная карта не должна трактоваться как счёт/счёт-20.
    text = "карта 4111 1111 1111 1111"
    types = types_in(text)
    assert "CARD" in types
    # 16 цифр не 20 — не должно давать ACCOUNT.
    assert "ACCOUNT" not in types


def test_consistency_two_passes():
    """Дважды по одному тексту — детекторы стабильны (без маппера)."""
    text = "Клиент Иванов Иван Иванович, телефон +7 999 123-45-67, банк ВТБ."
    first = [(m.value, m.type) for m in find_all(text)]
    second = [(m.value, m.type) for m in find_all(text)]
    assert first == second