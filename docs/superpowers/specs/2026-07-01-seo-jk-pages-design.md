# SEO: ЖК-страницы `/jk`

**Дата:** 2026-07-01
**Статус:** дизайн утверждён
**Цель:** SEO-лендинги по жилым комплексам — высокий интент («ЖК {имя} цены»),
низкая конкуренция. Шаг 2 дорожной карты SEO (после Хаб v2 + аренда).

## Контекст

Данные готовы: `ResidentialComplex` (id/name/district/match_key), сервис
`app/services/complex_stats.py::list_complex_stats` уже отдаёт по каждому ЖК
имя/район/count/медиану цены/медиану $/м²/min, порог `COMPLEX_MIN_LISTINGS=5`.
SSR-инфраструктура из прошлого шага: `app/seo/` + `hub_base.html`.

## Объём

- `/jk` — каталог ЖК (≥5 объявлений): имя · район · от $X · медиана · N.
- `/jk/{id}-{slug}` — страница ЖК: H1 «ЖК {имя}», статы (медиана цены/$м², от $X,
  N), таблица по комнатности, топ-объявления (дешевле медианы сверху), FAQ +
  `FAQPage`/`ItemList` JSON-LD, крошки.
- Sitemap: `/jk` + все `/jk/{id}-{slug}` с ≥5.
- Только продажа (`deal_type='sale'`). Аренда-ЖК — потом.

## Архитектура

- **Слаг:** `/jk/{id}-{translit(name)}` через `unidecode` (есть в окружении).
  Резолв по числовому префиксу (`complex_id_from_slug`). Без slug-колонки/миграции.
  Канонично — полный `id-slug`.
- **slugs.py:** `complex_slug(rc_id, name)`, `complex_id_from_slug(slug)`.
- **seo/service.py:** `ComplexHub` (dataclass с `.cards` — совместим с
  `_itemlist_jsonld`), `load_complex(db, settings, rc_id, deal_type='sale')` —
  медиана по всем листингам ЖК (Python median, как в complex_stats), топ-N карточек,
  таблица по комнатности. `None` если ЖК нет или 0 активных → 404.
- **seo/router.py:** роуты `/jk`, `/jk/{slug}`; хелперы `_complex_stats`,
  `_complex_faq`, `_complex_meta`, `_complex_breadcrumbs`. Каталог берёт
  `list_complex_stats(...,deal_type='sale')`.
- **Шаблоны:** `complex.html`, `complex_catalog.html` (extends `hub_base.html`).
- **sitemap:** ветка ЖК в `build_sitemap_xml` (из `list_complex_stats`).

## Не входит

Аренда-ЖК, ручные описания, slug-колонка/миграция, изменения `/api/complexes`,
фронта, CMA. Продажа-хабы и аренда-хабы не трогаем.

## Edge cases

- ЖК с 0 активных / <нет в справочнике → 404, не в sitemap.
- Каталог/sitemap — только ЖК с ≥`COMPLEX_MIN_LISTINGS`.
- Пустые cards → JSON-LD не эмитим.
- Слаг с «мусорным» хвостом (`/jk/42-что-угодно`) резолвится по id=42;
  если каноничный slug иной — отдаём страницу (мягко, без 301 в этой версии).

## Тесты (`tests/test_seo_jk.py`)

- `complex_slug`/`complex_id_from_slug` roundtrip + парс хвоста.
- `load_complex`: медиана/цены/cards по фикстуре; None на несуществующем.
- Роут `/jk/{id}-slug` 200 + H1/статы/FAQ/JSON-LD; несуществующий id → 404.
- `/jk` каталог перечисляет ЖК с ≥5, скрывает <5.
- sitemap содержит `/jk` и `/jk/{id}-...`.
