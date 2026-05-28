from app.services.listing_features import (
    MATERIAL_BRICK,
    MATERIAL_MONOLITH,
    MATERIAL_PANEL,
    extract_material,
    extract_micro_location,
    extract_year,
    floors_close,
    years_close,
)


def test_material_panel():
    assert extract_material("2-комн панельная", None) == MATERIAL_PANEL
    assert extract_material(None, "дом панельный") == MATERIAL_PANEL


def test_material_brick():
    assert extract_material("кирпичный дом", None) == MATERIAL_BRICK


def test_material_monolith_wins_over_brick():
    # «монолитно-кирпичный» — это монолит, не кирпич
    assert extract_material("монолитно-кирпичный дом", None) == MATERIAL_MONOLITH


def test_material_none():
    assert extract_material("2-комн квартира", None) is None
    assert extract_material(None, None) is None


def test_micro_location_massiv():
    assert extract_micro_location("массив Феруза 5", None, None) == "феруза"


def test_micro_location_block_id():
    assert extract_micro_location("Ц-1, дом 8", None, None) == "ц-1"
    assert extract_micro_location("ТТЗ-3", None, None) == "ттз-3"
    # без дефиса тоже распознаём
    assert extract_micro_location("Ц1", None, None) == "ц-1"


def test_micro_location_known_zhk():
    assert extract_micro_location(None, "ЖК Boulevard", None) == "boulevard"
    assert extract_micro_location(None, None, "Tashkent City новостройка") == "tashkent-city"


def test_micro_location_none():
    assert extract_micro_location("ул. Чехова 5", "2-комн квартира", None) is None


def test_year_explicit():
    assert extract_year("Квартира", "Год постройки 2020, евроремонт") == 2020


def test_year_built_in():
    assert extract_year("Построен в 1985", None) == 1985


def test_year_none():
    assert extract_year("2-комн квартира", None) is None


def test_years_close_within_band():
    assert years_close(2020, 2025) is True
    assert years_close(2020, 2005) is True  # exactly 15


def test_years_close_outside_band():
    assert years_close(2020, 1980) is False


def test_years_close_unknown_does_not_block():
    assert years_close(None, 2020) is True
    assert years_close(2020, None) is True
    assert years_close(None, None) is True


def test_floors_close_within():
    assert floors_close(5, 7) is True
    assert floors_close(5, 3) is True


def test_floors_close_outside():
    assert floors_close(5, 8) is False


def test_floors_close_unknown_does_not_block():
    assert floors_close(None, 5) is True
    assert floors_close(5, None) is True
