from app.services.segmentation import (
    SEGMENT_NEW,
    SEGMENT_SECONDARY,
    classify_segment,
    is_extreme_floor,
)


def test_explicit_newbuild_marker_wins():
    assert classify_segment("2-комн квартира", "ЖК Boulevard", "новостройка, сдан") == SEGMENT_NEW


def test_secondary_marker_classifies_as_secondary():
    assert classify_segment("2-комн", "Чиланзар, 12 массив", None) == SEGMENT_SECONDARY


def test_brand_name_in_title():
    assert classify_segment("Tashkent City Boulevard", "Юнусабад", None) == SEGMENT_NEW


def test_year_2020_marks_newbuild():
    assert classify_segment("Квартира", "Мирабадский р-н", "Год постройки 2020, евроремонт") == SEGMENT_NEW


def test_year_1985_does_not_mark_newbuild():
    assert classify_segment("Квартира", "Мирабадский р-н", "Год постройки 1985, требует ремонта") == SEGMENT_SECONDARY


def test_default_is_secondary():
    # Пустой шумный текст без сигналов — вторичка (это статистически чаще
    # в Ташкенте, и для дешёвого старого фонда корректнее ловить как secondary).
    assert classify_segment("Квартира", "ул. Чехова 5", None) == SEGMENT_SECONDARY


def test_extreme_floor_first():
    assert is_extreme_floor(1, 9) is True


def test_extreme_floor_last():
    assert is_extreme_floor(9, 9) is True


def test_extreme_floor_middle():
    assert is_extreme_floor(5, 9) is False


def test_extreme_floor_unknown_total():
    # Этаж 1 — крайний даже без знания общего числа этажей.
    assert is_extreme_floor(1, None) is True
    # Этаж 5 без known total — не крайний.
    assert is_extreme_floor(5, None) is False


def test_extreme_floor_missing():
    assert is_extreme_floor(None, None) is False
