# SEO Хаб v2 + аренда-хабы — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать SEO-хабы deal-type-aware, обогатить их уникальным контентом (авто-абзац, таблица цен по комнатности, FAQ + JSON-LD) и добавить зеркальные лендинги аренды `/arenda/*` с кросс-линком и в sitemap.

**Architecture:** Один общий рендер-путь и один `hub.html`, параметризованные `deal_type`. Слой данных (`service.py`) и хелперы роутера (`router.py`) получают параметр `deal_type` с дефолтом `"sale"` → весь существующий код продажи работает без изменений. Аренда — чистое дополнение поверх той же инфраструктуры.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, pytest + TestClient (SQLite). Файлы в `backend/app/seo/`. Тесты в `backend/tests/test_seo_hubs.py`. Запуск: `cd backend && pytest tests/test_seo_hubs.py -v`.

---

## Шаг 0 (пред-флайт, не код): проверка данных аренды

Перед реализацией убедиться на проде/staging, что у `deal_type='rent'` заполнены поля, от которых зависят блоки. Выполнить (Railway):

```sql
SELECT count(*) AS total,
       count(district) AS with_district,
       count(rooms) AS with_rooms,
       count(*) FILTER (WHERE is_below_market) AS below_mkt,
       count(price_period) AS with_period
FROM listings WHERE deal_type='rent' AND status='active';
```

Ожидание: `with_district`/`with_rooms` — заметная доля (иначе таблица по комнатности и district-хабы аренды будут бедные, но city-level всё равно работает; код от этого не падает). Записать факт в спек/память. Это проверка данных, не блокер для кода.

---

## File Structure

- Modify: `backend/app/seo/service.py` — `deal_type` в `base_conditions`/`load_hub`/`available_hubs`/`build_sitemap_xml`; новые поля `HubData`; новый `rooms_breakdown`.
- Modify: `backend/app/seo/router.py` — `deal_type`-aware хелперы (`_meta`, `_breadcrumbs`, `_related`, `_stats`, `_intro`, `_faq`, JSON-LD), `/arenda/*` роуты, кросс-линк.
- Modify: `backend/app/seo/templates/hub.html` — статы из `_stats`, intro-абзац, таблица по комнатности, FAQ-секция, кросс-линк, второй/третий JSON-LD.
- Modify: `backend/app/seo/templates/hub_base.html` — рендер списка доп. JSON-LD (`jsonld_extra`).
- Modify: `backend/tests/test_seo_hubs.py` — rent-фикстуры и тесты, проверки новых блоков.

---

## Task 1: `deal_type`-aware слой данных (`service.py`)

**Files:**
- Modify: `backend/app/seo/service.py`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающие тесты слоя данных**

Добавить в `tests/test_seo_hubs.py` rent-хелпер и тесты:

```python
def _mk_rent(db, i, district, rooms, *, price_usd, status="active"):
    db.add(
        Listing(
            source="uybor", source_id=f"r{i}", url=f"https://uybor.uz/{i}",
            title=f"Аренда {i}", price=price_usd, currency="USD",
            price_usd=price_usd, area_m2=50.0, price_per_m2_usd=price_usd / 50.0,
            rooms=rooms, district=district, address_raw="ул. Тестовая 2",
            duplicate_group_key=f"rg{i}", status=status,
            deal_type="rent", price_period="month",
            is_below_market=True, discount_percent=15.0,
        )
    )


def _seed_rent(db):
    # Чиланзар аренда: 3 активных (2,2,3) по $300/$400/$600 в мес.
    for i, (rooms, price) in enumerate([(2, 300.0), (2, 400.0), (3, 600.0)]):
        _mk_rent(db, i, CHILANZAR, rooms, price_usd=price)
    db.commit()


def test_load_hub_sale_unchanged(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)
    data = service.load_hub(db_session, get_settings(), district=CHILANZAR)
    assert data.deal_type == "sale"
    assert data.total == 4
    assert data.avg_ppm_usd is not None


def test_load_hub_rent_uses_monthly_avg(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed_rent(db_session)
    data = service.load_hub(db_session, get_settings(), district=CHILANZAR, deal_type="rent")
    assert data.deal_type == "rent"
    assert data.price_period == "month"
    assert data.total == 3
    # средняя $/мес = (300+400+600)/3 = 433.3
    assert 430 <= data.avg_price_usd <= 437


def test_available_hubs_separates_deal_types(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)
    _seed_rent(db_session)
    sale_d, _, _ = service.available_hubs(db_session, get_settings(), deal_type="sale")
    rent_d, _, _ = service.available_hubs(db_session, get_settings(), deal_type="rent")
    assert sale_d.get(CHILANZAR) == 4
    assert rent_d.get(CHILANZAR) == 3  # аренда считается отдельно
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && pytest tests/test_seo_hubs.py::test_load_hub_rent_uses_monthly_avg tests/test_seo_hubs.py::test_available_hubs_separates_deal_types -v`
Expected: FAIL — `load_hub()`/`available_hubs()` не принимают `deal_type`; нет `avg_price_usd`.

- [ ] **Step 3: Обновить `base_conditions` и `HubData`**

В `service.py` заменить `base_conditions`:

```python
def base_conditions(settings: Settings, deal_type: str = "sale") -> list:
    min_price, min_ppm = settings.thresholds(deal_type)
    return [
        Listing.status == "active",
        Listing.deal_type == deal_type,
        Listing.price_usd >= min_price,
        Listing.price_per_m2_usd >= min_ppm,
    ]
```

Расширить датакласс:

```python
@dataclass
class HubData:
    district: str | None
    rooms: int | None
    total: int
    min_price_usd: float | None
    avg_ppm_usd: float | None
    cards: list[dict] = field(default_factory=list)
    deal_type: str = "sale"
    price_period: str | None = None
    avg_price_usd: float | None = None  # средняя $/мес для аренды
    rooms_table: list[dict] = field(default_factory=list)  # заполняется в Task 2
```

- [ ] **Step 4: Прокинуть `deal_type` в `load_hub` и `available_hubs`**

`load_hub` — добавить параметр и rent-ветку средней цены:

```python
def load_hub(
    db: Session,
    settings: Settings,
    *,
    district: str | None = None,
    rooms: int | None = None,
    deal_type: str = "sale",
    limit: int = HUB_LIST_LIMIT,
) -> HubData:
    conds = base_conditions(settings, deal_type)
    if district:
        conds.append(Listing.district == district)
    if rooms:
        conds.append(Listing.rooms == rooms)

    total = db.scalar(select(func.count()).select_from(Listing).where(*conds)) or 0
    period = "month" if deal_type == "rent" else None
    if total == 0:
        return HubData(district, rooms, 0, None, None, [], deal_type, period, None)

    min_price = db.scalar(select(func.min(Listing.price_usd)).where(*conds))
    avg_ppm = db.scalar(select(func.avg(Listing.price_per_m2_usd)).where(*conds))
    avg_price = (
        db.scalar(select(func.avg(Listing.price_usd)).where(*conds))
        if deal_type == "rent"
        else None
    )
    rows = db.scalars(
        select(Listing)
        .where(*conds)
        .order_by(
            nulls_last(Listing.discount_percent.desc()),
            Listing.price_per_m2_usd.asc(),
            Listing.id.asc(),
        )
        .limit(limit)
    ).all()
    return HubData(
        district, rooms, int(total), min_price, avg_ppm,
        [listing_card(r) for r in rows], deal_type, period, avg_price,
    )
```

`available_hubs` — добавить параметр и прокинуть в `base_conditions`:

```python
def available_hubs(
    db: Session, settings: Settings, deal_type: str = "sale"
) -> tuple[dict[str, int], dict[int, int], dict[tuple[str, int], int]]:
    conds = base_conditions(settings, deal_type)
    # ... тело без изменений (использует локальный conds) ...
```

- [ ] **Step 5: Запустить — тесты Task 1 проходят, регресс зелёный**

Run: `cd backend && pytest tests/test_seo_hubs.py -v`
Expected: PASS все (новые + старые продажа-тесты).

- [ ] **Step 6: Commit**

```bash
git add backend/app/seo/service.py backend/tests/test_seo_hubs.py
git commit -m "feat(seo): deal_type-aware слой данных хабов (аренда отдельно)"
```

---

## Task 2: Агрегат «цены по комнатности» (`rooms_breakdown`)

**Files:**
- Modify: `backend/app/seo/service.py`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_rooms_breakdown_sale_avg_full_price(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)  # Чиланзар: 3×2-комн ($50k), 1×3-комн ($50k)
    rows = service.rooms_breakdown(db_session, get_settings(), CHILANZAR, deal_type="sale")
    by_rooms = {r["rooms"]: r for r in rows}
    assert by_rooms[2]["count"] == 3
    assert by_rooms[3]["count"] == 1
    assert by_rooms[2]["avg_price"] == 50000.0


def test_rooms_breakdown_rent_avg_monthly(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed_rent(db_session)  # 2×2-комн ($300,$400), 1×3-комн ($600)
    rows = service.rooms_breakdown(db_session, get_settings(), CHILANZAR, deal_type="rent")
    by_rooms = {r["rooms"]: r for r in rows}
    assert by_rooms[2]["count"] == 2
    assert by_rooms[2]["avg_price"] == 350.0
    assert by_rooms[3]["avg_price"] == 600.0
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && pytest tests/test_seo_hubs.py -k rooms_breakdown -v`
Expected: FAIL — нет `service.rooms_breakdown`.

- [ ] **Step 3: Реализовать `rooms_breakdown`**

Добавить в `service.py`:

```python
def rooms_breakdown(
    db: Session, settings: Settings, district: str, deal_type: str = "sale"
) -> list[dict]:
    """Средняя цена и кол-во по комнатности (1..5) в рамках района.

    Для продажи avg_price — средняя полная цена, для аренды — средняя $/мес.
    Используется на district-only хабе; на rooms-фиксированных не вызывается.
    """
    conds = base_conditions(settings, deal_type) + [Listing.district == district]
    rows = db.execute(
        select(Listing.rooms, func.count(), func.avg(Listing.price_usd))
        .where(*conds)
        .group_by(Listing.rooms)
        .order_by(Listing.rooms.asc())
    ).all()
    return [
        {"rooms": int(rm), "count": int(cnt), "avg_price": float(avg)}
        for rm, cnt, avg in rows
        if rm and 1 <= rm <= 5
    ]
```

- [ ] **Step 4: Запустить — проходит**

Run: `cd backend && pytest tests/test_seo_hubs.py -k rooms_breakdown -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/seo/service.py backend/tests/test_seo_hubs.py
git commit -m "feat(seo): агрегат rooms_breakdown (цены по комнатности)"
```

---

## Task 3: Аренда-роуты `/arenda/*` + deal-type-aware meta/breadcrumbs/related

**Files:**
- Modify: `backend/app/seo/router.py`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающие тесты роутов аренды**

```python
def test_arenda_district_rooms_hub(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar/2-komnatnye")
    assert r.status_code == 200
    assert "Аренда 2-комнатных квартир в Чиланзарском районе" in r.text
    assert "/мес" in r.text
    assert 'rel="canonical" href="https://uyradar.uz/arenda/chilanzar/2-komnatnye"' in r.text


def test_arenda_district_hub(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar")
    assert r.status_code == 200
    assert "Аренда квартир в Чиланзарском районе" in r.text
    assert "/мес" in r.text


def test_arenda_empty_404(client, db_session):
    _seed(db_session)  # только продажа засеяна
    assert client.get("/arenda/chilanzar").status_code == 404
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && pytest tests/test_seo_hubs.py -k arenda -v`
Expected: FAIL — роутов `/arenda` нет (404 на всех, включая ожидающие 200).

- [ ] **Step 3: Ввести константы префиксов и сделать хелперы deal-type-aware**

В начале `router.py` (после импортов) добавить:

```python
PREFIX = {"sale": "/kvartira", "rent": "/arenda"}
ROOT_LABEL = {"sale": "Квартиры", "rent": "Аренда"}
```

Обновить `_breadcrumbs` — использовать префикс и корневую метку по `data.deal_type`:

```python
def _breadcrumbs(data: HubData) -> list[dict]:
    pre = PREFIX[data.deal_type]
    crumbs = [{"name": "Главная", "url": "/"}, {"name": ROOT_LABEL[data.deal_type], "url": pre}]
    if data.district:
        crumbs.append({"name": data.district, "url": f"{pre}/{DISTRICT_SLUGS[data.district]}"})
        if data.rooms:
            crumbs.append({
                "name": rooms_label(data.rooms),
                "url": f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(data.rooms)}",
            })
    elif data.rooms:
        crumbs.append({"name": rooms_label(data.rooms), "url": f"{pre}/{rooms_slug(data.rooms)}"})
    return crumbs
```

Обновить `_related`, `_district_links`, `_room_links` — принимать `deal_type` и строить URL через `PREFIX[deal_type]`. Сигнатуры:

```python
def _related(db: Session, settings, data: HubData) -> list[dict]:
    districts, rooms, combos = service.available_hubs(db, settings, data.deal_type)
    pre = PREFIX[data.deal_type]
    sections: list[dict] = []
    # ... та же логика, но все f"/kvartira/..." → f"{pre}/..." и
    #     _district_links(districts, pre, exclude=...) / _room_links(rooms, pre, exclude=...)
```

```python
def _district_links(districts: dict[str, int], pre: str, exclude: str | None = None) -> list[dict]:
    return [
        {"label": dist, "url": f"{pre}/{DISTRICT_SLUGS[dist]}"}
        for dist in sorted(districts) if dist != exclude
    ]


def _room_links(rooms: dict[int, int], pre: str, exclude: int | None = None) -> list[dict]:
    return [
        {"label": rooms_label(rm), "url": f"{pre}/{rooms_slug(rm)}"}
        for rm in sorted(rooms) if rm != exclude
    ]
```

> Внутри `_related` каждый блок ссылок строить с `pre`. Пример замены первой ветки:
> `f"/kvartira/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"` → `f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"`. Так во всех трёх ветках, и `_district_links(districts, pre, exclude=...)`.

> **ВАЖНО (иначе сломается `test_catalog_lists_districts`):** существующий `catalog` (роут `/kvartira`) вызывает `_district_links(districts)` / `_room_links(rooms)` со старой сигнатурой. Сразу обновить эти два вызова внутри `catalog` на `_district_links(districts, "/kvartira")` и `_room_links(rooms, "/kvartira")`. В Task 6 `catalog` целиком переедет в общий `_catalog`, но до тех пор он должен оставаться рабочим.

- [ ] **Step 4: Сделать `_meta` deal-type-aware**

Заменить `_meta` на ветвление по `data.deal_type`. Полный код:

```python
def _meta(data: HubData) -> tuple[str, str, str]:
    if data.deal_type == "rent":
        return _meta_rent(data)
    return _meta_sale(data)


def _meta_sale(data: HubData) -> tuple[str, str, str]:
    if data.district and data.rooms:
        place = district_locative(data.district)
        h1 = f"{rooms_label(data.rooms)} квартиры в {place}"
        title = f"{h1} — {data.total} объявлений | uyradar.uz"
        desc = (
            f"{data.total} объявлений: {rooms_label(data.rooms).lower()} квартиры в {place} Ташкента. "
            f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м². "
            "OLX, Uybor и Realt24 в одном месте с оценкой ниже рынка."
        )
    elif data.district:
        place = district_locative(data.district)
        h1 = f"Квартиры в {place}"
        title = f"{h1} — {data.total} объявлений от {fmt_usd(data.min_price_usd)} | uyradar.uz"
        desc = (
            f"{data.total} квартир на продажу в {place} Ташкента. Цены от {fmt_usd(data.min_price_usd)}, "
            f"в среднем {fmt_num(data.avg_ppm_usd)} $/м². Объявления с OLX, Uybor и Realt24 с оценкой ниже рынка."
        )
    else:
        h1 = f"{rooms_label(data.rooms)} квартиры в Ташкенте"
        title = f"{h1} — {data.total} объявлений | uyradar.uz"
        desc = (
            f"{data.total} объявлений: {rooms_label(data.rooms).lower()} квартиры в Ташкенте. "
            f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м². "
            "OLX, Uybor и Realt24 с оценкой ниже рынка."
        )
    return h1, title, desc


def _meta_rent(data: HubData) -> tuple[str, str, str]:
    pm = f"{fmt_usd(data.min_price_usd)}/мес"
    if data.district and data.rooms:
        place = district_locative(data.district)
        h1 = f"Аренда {rooms_label(data.rooms).lower()} квартир в {place}"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} объявлений: снять {rooms_label(data.rooms).lower()} квартиру в {place} Ташкента. "
            f"Аренда от {pm}, в среднем {fmt_usd(data.avg_price_usd)}/мес. OLX и Uybor с оценкой ниже рынка."
        )
    elif data.district:
        place = district_locative(data.district)
        h1 = f"Аренда квартир в {place}"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} квартир в аренду в {place} Ташкента. Аренда от {pm}, "
            f"в среднем {fmt_usd(data.avg_price_usd)}/мес. Объявления с OLX и Uybor с оценкой ниже рынка."
        )
    else:
        h1 = f"Аренда {rooms_label(data.rooms).lower()} квартир в Ташкенте"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} объявлений: снять {rooms_label(data.rooms).lower()} квартиру в Ташкенте. "
            f"Аренда от {pm}, в среднем {fmt_usd(data.avg_price_usd)}/мес. OLX и Uybor с оценкой ниже рынка."
        )
    return h1, title, desc
```

- [ ] **Step 5: Добавить аренда-роуты через общий хелпер**

В `router.py` выделить общую логику slug-хаба и зарегистрировать обе пары роутов. Заменить тела `hub_by_slug`/`hub_district_rooms` на тонкие обёртки и добавить аренда-аналоги:

```python
def _slug_hub(slug: str, request: Request, db: Session, deal_type: str) -> HTMLResponse:
    settings = get_settings()
    rooms = rooms_from_slug(slug)
    if rooms is not None:
        data = service.load_hub(db, settings, rooms=rooms, deal_type=deal_type)
    else:
        district = district_from_slug(slug)
        if not district:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        data = service.load_hub(db, settings, district=district, deal_type=deal_type)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


def _district_rooms_hub(dslug: str, rslug: str, request: Request, db: Session, deal_type: str) -> HTMLResponse:
    settings = get_settings()
    district = district_from_slug(dslug)
    rooms = rooms_from_slug(rslug)
    if not district or rooms is None:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    data = service.load_hub(db, settings, district=district, rooms=rooms, deal_type=deal_type)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


@router.get("/kvartira/{slug}", response_class=HTMLResponse, include_in_schema=False)
def hub_by_slug(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _slug_hub(slug, request, db, "sale")


@router.get("/kvartira/{dslug}/{rslug}", response_class=HTMLResponse, include_in_schema=False)
def hub_district_rooms(dslug: str, rslug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _district_rooms_hub(dslug, rslug, request, db, "sale")


@router.get("/arenda/{slug}", response_class=HTMLResponse, include_in_schema=False)
def rent_hub_by_slug(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _slug_hub(slug, request, db, "rent")


@router.get("/arenda/{dslug}/{rslug}", response_class=HTMLResponse, include_in_schema=False)
def rent_hub_district_rooms(dslug: str, rslug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _district_rooms_hub(dslug, rslug, request, db, "rent")
```

> Примечание: `/arenda` (каталог) добавляется в Task 6 вместе с sitemap; этот шаг — только хабы. Тест `test_arenda_district_hub` уже зелёный без каталога.

- [ ] **Step 6: Запустить — аренда-тесты и регресс зелёные**

Run: `cd backend && pytest tests/test_seo_hubs.py -v`
Expected: PASS. (Часть тестов на новые блоки intro/FAQ появится в Task 4 — здесь проверяем роуты/мету.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/seo/router.py backend/tests/test_seo_hubs.py
git commit -m "feat(seo): аренда-хабы /arenda/* + deal-type-aware meta/breadcrumbs"
```

---

## Task 4: Хаб v2 — статы, intro-абзац, таблица по комнатности, FAQ + JSON-LD

**Files:**
- Modify: `backend/app/seo/router.py`
- Modify: `backend/app/seo/templates/hub.html`
- Modify: `backend/app/seo/templates/hub_base.html`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающие тесты контента**

```python
def test_hub_v2_intro_and_faq_sale(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert "Цены по комнатности" in r.text          # таблица на district-only
    assert "FAQPage" in r.text                       # FAQ JSON-LD
    assert "ItemList" in r.text                       # список объявлений JSON-LD
    assert "Сколько стоит" in r.text                 # видимый FAQ-вопрос


def test_hub_v2_rent_stats_and_table(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar")
    assert r.status_code == 200
    assert "Цены по комнатности" in r.text
    assert "/мес" in r.text
    assert "FAQPage" in r.text


def test_hub_v2_combo_hides_rooms_table(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar/2-komnatnye")
    assert r.status_code == 200
    assert "Цены по комнатности" not in r.text       # на комбо таблицы нет
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && pytest tests/test_seo_hubs.py -k "hub_v2" -v`
Expected: FAIL — нет таблицы/FAQ/ItemList в рендере.

- [ ] **Step 3: Хелперы контента в `router.py`**

Добавить функции `_stats`, `_intro`, `_faq`, `_itemlist_jsonld`, `_faq_jsonld`:

```python
def _stats(data: HubData) -> list[dict]:
    items = [{"value": fmt_num(data.total), "label": "объявлений"}]
    if data.deal_type == "rent":
        items.append({"value": f"{fmt_usd(data.min_price_usd)}/мес", "label": "аренда от"})
        items.append({"value": f"{fmt_usd(data.avg_price_usd)}/мес", "label": "в среднем"})
    else:
        items.append({"value": fmt_usd(data.min_price_usd), "label": "цена от"})
        items.append({"value": f"{fmt_num(data.avg_ppm_usd)} $/м²", "label": "в среднем"})
    return items


def _intro(data: HubData) -> str:
    place = f"в {district_locative(data.district)}" if data.district else "в Ташкенте"
    rlabel = f"{rooms_label(data.rooms).lower()} " if data.rooms else ""
    below = sum(1 for c in data.cards if c.get("discount_percent"))
    below_txt = f" {below} предложений ниже рыночной оценки." if below else ""
    if data.deal_type == "rent":
        return (
            f"Сейчас {data.total} {rlabel}квартир в аренду {place}. "
            f"Аренда от {fmt_usd(data.min_price_usd)}/мес, в среднем {fmt_usd(data.avg_price_usd)}/мес."
            f"{below_txt}"
        )
    return (
        f"Сейчас {data.total} {rlabel}квартир в продаже {place}. "
        f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м²."
        f"{below_txt}"
    )


def _faq(data: HubData) -> list[dict]:
    place = district_locative(data.district) if data.district else "Ташкенте"
    rlabel = rooms_label(data.rooms).lower() if data.rooms else "квартиру"
    verb = "снять" if data.deal_type == "rent" else "купить"
    if data.deal_type == "rent":
        price_a = (
            f"Аренда от {fmt_usd(data.min_price_usd)}/мес, "
            f"в среднем {fmt_usd(data.avg_price_usd)}/мес по {data.total} объявлениям."
        )
    else:
        price_a = (
            f"Цены от {fmt_usd(data.min_price_usd)}, "
            f"в среднем {fmt_num(data.avg_ppm_usd)} $/м² по {data.total} объявлениям."
        )
    faq = [
        {"q": f"Сколько стоит {verb} {rlabel} в {place}?", "a": price_a},
        {"q": "Сколько объявлений доступно?",
         "a": f"В подборке {data.total} активных объявлений с OLX, Uybor и Realt24, обновляется ежедневно."},
        {"q": "Как выбрать вариант ниже рынка?",
         "a": "Объявления отсортированы по скидке к нашей оценке: лучшие сделки сверху, бейдж «−X% к рынку»."},
    ]
    return faq


def _itemlist_jsonld(data: HubData) -> str | None:
    if not data.cards:
        return None
    items = []
    for i, c in enumerate(data.cards):
        offer = {"@type": "Offer", "price": int(round(c["price_usd"])), "priceCurrency": "USD"} if c.get("price_usd") else None
        node = {"@type": "RealEstateListing", "name": c["title"], "url": c["url"]}
        if offer:
            node["offers"] = offer
        items.append({"@type": "ListItem", "position": i + 1, "item": node})
    return json.dumps(
        {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items},
        ensure_ascii=False,
    )


def _faq_jsonld(faq: list[dict]) -> str | None:
    if not faq:
        return None
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faq
            ],
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 4: Дополнить `_render_hub` контекстом**

Заменить `_render_hub`:

```python
def _render_hub(request: Request, db: Session, settings, data: HubData) -> HTMLResponse:
    h1, title, desc = _meta(data)
    crumbs = _breadcrumbs(data)
    # Таблица по комнатности — только на district-only хабе.
    if data.district and not data.rooms:
        data.rooms_table = service.rooms_breakdown(db, settings, data.district, data.deal_type)
    faq = _faq(data)
    jsonld_extra = [j for j in (_itemlist_jsonld(data), _faq_jsonld(faq)) if j]
    context = {
        "page_title": title,
        "meta_description": desc,
        "canonical": _canonical(request),
        "h1": h1,
        "data": data,
        "stats": _stats(data),
        "intro": _intro(data),
        "faq": faq,
        "breadcrumbs": crumbs,
        "related": _related(db, settings, data),
        "jsonld": _breadcrumb_jsonld(request, crumbs),
        "jsonld_extra": jsonld_extra,
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "hub.html", context)
```

- [ ] **Step 5: Рендер доп. JSON-LD в `hub_base.html`**

После строки с `{{ jsonld|safe }}` (строка 20) добавить:

```html
    {% for j in jsonld_extra %}<script type="application/ld+json">{{ j|safe }}</script>
    {% endfor %}
```

- [ ] **Step 6: Обновить `hub.html` — статы из `_stats`, intro, таблица, FAQ**

Заменить блок `stats` и добавить новые секции. Полный `{% block content %}`:

```html
{% extends "hub_base.html" %}
{% block content %}
<h1>{{ h1 }}</h1>
<p class="lead">{{ intro }}</p>

<div class="stats">
  {% for s in stats %}<div><b>{{ s.value }}</b><span>{{ s.label }}</span></div>{% endfor %}
</div>

{% if data.rooms_table %}
<section class="rooms-table">
  <h2>Цены по комнатности</h2>
  <table>
    <thead><tr><th>Комнат</th><th>Объявлений</th><th>Средняя цена</th></tr></thead>
    <tbody>
      {% for row in data.rooms_table %}
      <tr>
        <td>{{ row.rooms }}-комн.</td>
        <td>{{ row.count|num }}</td>
        <td>{{ row.avg_price|usd }}{% if data.deal_type == 'rent' %}/мес{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endif %}

<div class="cards">
  {% for c in data.cards %}
  <article class="card">
    {% if c.photo %}<img class="thumb" src="{{ c.photo }}" alt="{{ c.rooms }}-комн. квартира, {{ c.area_m2|num }} м², {{ c.district }}" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()" />{% endif %}
    <div class="card-body">
      <div class="price">{{ c.price_usd|usd }}{% if data.deal_type == 'rent' %}/мес{% endif %}{% if c.discount_percent %}<span class="disc">−{{ c.discount_percent|round|int }}% к рынку</span>{% endif %}</div>
      <div class="facts">{{ c.rooms }}-комн. · {{ c.area_m2|num }} м²{% if c.floor %} · {{ c.floor }}{% if c.total_floors %}/{{ c.total_floors }}{% endif %} эт.{% endif %} · {{ c.price_per_m2_usd|num }} $/м²</div>
      <div class="addr">{{ c.district }}{% if c.address %} · {{ c.address }}{% endif %}</div>
      <a class="src" href="{{ c.url }}" target="_blank" rel="nofollow noopener">Смотреть на {{ c.source_label }} →</a>
    </div>
  </article>
  {% endfor %}
</div>

{% if data.total > data.cards|length %}
<p class="more">Показаны {{ data.cards|length }} лучших предложений из {{ data.total|num }}. <a href="/">Все объявления и фильтры — в поиске →</a></p>
{% endif %}

{% if faq %}
<section class="faq">
  <h2>Частые вопросы</h2>
  {% for f in faq %}
  <details><summary>{{ f.q }}</summary><p>{{ f.a }}</p></details>
  {% endfor %}
</section>
{% endif %}

{% if related %}
<section class="related">
  {% for sec in related %}
  <div class="related-block">
    <h2>{{ sec.title }}</h2>
    <div class="chips">{% for l in sec.links %}<a href="{{ l.url }}">{{ l.label }}</a>{% endfor %}</div>
  </div>
  {% endfor %}
</section>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Добавить стили таблицы и FAQ в `hub_base.html`**

В `<style>` (перед `@media`) добавить:

```css
      .rooms-table { margin: 0 0 28px; }
      .rooms-table h2, .faq h2 { font-size: 18px; margin: 0 0 12px; }
      .rooms-table table { border-collapse: collapse; width: 100%; max-width: 520px;
                           background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }
      .rooms-table th, .rooms-table td { text-align: left; padding: 10px 14px; font-size: 14px;
                                         border-bottom: 1px solid #eef2f7; }
      .rooms-table th { color: #64748b; font-weight: 600; background: #f8fafc; }
      .rooms-table tr:last-child td { border-bottom: 0; }
      .faq { margin: 32px 0 0; max-width: 760px; }
      .faq details { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                     padding: 12px 16px; margin-bottom: 10px; }
      .faq summary { cursor: pointer; font-weight: 600; font-size: 15px; }
      .faq p { margin: 10px 0 0; color: #475569; font-size: 14px; }
```

- [ ] **Step 8: Запустить — контент-тесты и весь файл зелёные**

Run: `cd backend && pytest tests/test_seo_hubs.py -v`
Expected: PASS все.

- [ ] **Step 9: Commit**

```bash
git add backend/app/seo/router.py backend/app/seo/templates/hub.html backend/app/seo/templates/hub_base.html backend/tests/test_seo_hubs.py
git commit -m "feat(seo): Хаб v2 — intro, таблица по комнатности, FAQ + ItemList/FAQPage JSON-LD"
```

---

## Task 5: Кросс-линк продажа↔аренда

**Files:**
- Modify: `backend/app/seo/router.py`
- Modify: `backend/app/seo/templates/hub.html`
- Modify: `backend/app/seo/templates/hub_base.html`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_cross_link_sale_to_rent(client, db_session):
    _seed(db_session)       # продажа Чиланзар
    _seed_rent(db_session)  # аренда Чиланзар
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert 'href="/arenda/chilanzar"' in r.text
    assert "Снять" in r.text


def test_cross_link_absent_when_no_counterpart(client, db_session):
    _seed(db_session)       # только продажа
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert 'href="/arenda/chilanzar"' not in r.text
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && pytest tests/test_seo_hubs.py -k cross_link -v`
Expected: FAIL — кросс-линка нет.

- [ ] **Step 3: Считать кросс-линк в `_cross_link` и положить в контекст**

В `router.py` добавить:

```python
def _cross_link(db: Session, settings, data: HubData) -> dict | None:
    """Ссылка на зеркальный срез в другом deal_type, если он непустой."""
    other = "rent" if data.deal_type == "sale" else "sale"
    other_data = service.load_hub(
        db, settings, district=data.district, rooms=data.rooms, deal_type=other
    )
    if other_data.total == 0:
        return None
    pre = PREFIX[other]
    if data.district and data.rooms:
        url = f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(data.rooms)}"
    elif data.district:
        url = f"{pre}/{DISTRICT_SLUGS[data.district]}"
    elif data.rooms:
        url = f"{pre}/{rooms_slug(data.rooms)}"
    else:
        url = pre
    place = district_locative(data.district) if data.district else "Ташкенте"
    label = f"Снять в {place}" if other == "rent" else f"Купить в {place}"
    return {"url": url, "label": label, "count": other_data.total}
```

В `_render_hub` добавить в `context`:

```python
        "cross_link": _cross_link(db, settings, data),
```

- [ ] **Step 4: Отрисовать кросс-линк в `hub.html`**

Сразу после `<p class="lead">{{ intro }}</p>` добавить:

```html
{% if cross_link %}
<p class="cross"><a href="{{ cross_link.url }}">{{ cross_link.label }} →</a> <span>({{ cross_link.count|num }})</span></p>
{% endif %}
```

И стиль в `hub_base.html` `<style>`:

```css
      .cross { margin: -10px 0 22px; font-size: 14px; }
      .cross span { color: #94a3b8; }
```

- [ ] **Step 5: Запустить — проходит, регресс зелёный**

Run: `cd backend && pytest tests/test_seo_hubs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/seo/router.py backend/app/seo/templates/hub.html backend/app/seo/templates/hub_base.html backend/tests/test_seo_hubs.py
git commit -m "feat(seo): кросс-линк продажа↔аренда на хабах"
```

---

## Task 6: Каталог `/arenda` + аренда в sitemap

**Files:**
- Modify: `backend/app/seo/router.py`
- Modify: `backend/app/seo/service.py`
- Modify: `backend/app/seo/templates/catalog.html`
- Test: `backend/tests/test_seo_hubs.py`

- [ ] **Step 1: Написать падающие тесты**

```python
def test_sitemap_includes_rent(client, db_session):
    _seed(db_session)
    _seed_rent(db_session)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "https://uyradar.uz/kvartira/chilanzar</loc>" in r.text
    assert "https://uyradar.uz/arenda/chilanzar</loc>" in r.text
    assert "https://uyradar.uz/arenda</loc>" in r.text


def test_arenda_catalog(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda")
    assert r.status_code == 200
    assert "/arenda/chilanzar" in r.text
    assert "аренд" in r.text.lower()
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && pytest tests/test_seo_hubs.py -k "sitemap_includes_rent or arenda_catalog" -v`
Expected: FAIL — нет rent в sitemap, нет `/arenda` каталога.

- [ ] **Step 3: Добавить rent-ветку в `build_sitemap_xml`**

В `service.py` в `build_sitemap_xml` после блока продажи (перед `body = ...`) добавить:

```python
    # Аренда: статический каталог + хабы.
    rent_last = db.scalar(select(func.max(Listing.updated_at)).where(*base_conditions(settings, "rent")))
    rent_mod = (rent_last or datetime.utcnow()).strftime("%Y-%m-%d")
    entries.append(_url_entry("/arenda", rent_mod, "daily", "0.8"))
    r_districts, r_rooms, r_combos = available_hubs(db, settings, "rent")
    for dist in r_districts:
        entries.append(_url_entry(f"/arenda/{DISTRICT_SLUGS[dist]}", rent_mod, "daily", "0.7"))
    for room in r_rooms:
        entries.append(_url_entry(f"/arenda/{rooms_slug(room)}", rent_mod, "daily", "0.6"))
    for dist, room in r_combos:
        entries.append(_url_entry(f"/arenda/{DISTRICT_SLUGS[dist]}/{rooms_slug(room)}", rent_mod, "daily", "0.6"))
```

- [ ] **Step 4: Добавить роут каталога `/arenda` и deal-type-aware catalog**

В `router.py` обобщить каталог. Заменить `catalog` на общий хелпер + два роута:

```python
def _catalog(request: Request, db: Session, deal_type: str) -> HTMLResponse:
    settings = get_settings()
    districts, rooms, _ = service.available_hubs(db, settings, deal_type)
    pre = PREFIX[deal_type]
    if deal_type == "rent":
        page_title = "Аренда квартир в Ташкенте по районам — каталог | uyradar.uz"
        meta = ("Каталог аренды квартир в Ташкенте по районам и комнатности: Чиланзар, Юнусабад, "
                "Мирабад и другие. Объявления с OLX и Uybor с оценкой ниже рынка.")
        root_label = "Аренда"
    else:
        page_title = "Квартиры в Ташкенте по районам — каталог | uyradar.uz"
        meta = ("Каталог квартир в Ташкенте по районам и комнатности: Чиланзар, Юнусабад, "
                "Мирабад и другие. Объявления с OLX, Uybor и Realt24 с оценкой ниже рынка.")
        root_label = "Квартиры"
    context = {
        "page_title": page_title,
        "meta_description": meta,
        "canonical": _canonical(request),
        "district_links": _district_links(districts, pre),
        "room_links": _room_links(rooms, pre),
        "jsonld": _breadcrumb_jsonld(
            request, [{"name": "Главная", "url": "/"}, {"name": root_label, "url": pre}]
        ),
        "jsonld_extra": [],
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "catalog.html", context)


@router.get("/kvartira", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _catalog(request, db, "sale")


@router.get("/arenda", response_class=HTMLResponse, include_in_schema=False)
def rent_catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _catalog(request, db, "rent")
```

> Проверить `catalog.html`: если он использует жёстко «Квартиры» в H1/тексте, передать в контекст `root_label`/`h1` и подставить в шаблон. Минимально — заголовок берётся из `page_title`; если в `catalog.html` есть хардкод H1 «Квартиры в Ташкенте», заменить на `{{ h1 }}` и добавить `"h1": ("Аренда квартир в Ташкенте по районам" if deal_type=="rent" else "Квартиры в Ташкенте по районам")` в context.

- [ ] **Step 5: Запустить — проходит, весь файл зелёный**

Run: `cd backend && pytest tests/test_seo_hubs.py -v`
Expected: PASS все.

- [ ] **Step 6: Commit**

```bash
git add backend/app/seo/router.py backend/app/seo/service.py backend/app/seo/templates/catalog.html backend/tests/test_seo_hubs.py
git commit -m "feat(seo): каталог /arenda + аренда в sitemap"
```

---

## Task 7: Финальная проверка и деплой

- [ ] **Step 1: Полный прогон тестов SEO + смежных**

Run: `cd backend && pytest tests/test_seo_hubs.py tests/test_api.py -v`
Expected: PASS. Регресс по продаже отсутствует.

- [ ] **Step 2: Глаз-проверка рендера локально (один sale + один rent)**

Run: `cd backend && uvicorn app.main:app --port 8001` (в фоне), затем `curl -s localhost:8001/kvartira/chilanzar | grep -o "FAQPage\|ItemList\|Цены по комнатности"` и `curl -s localhost:8001/arenda/chilanzar | grep -o "/мес\|FAQPage"`.
Expected: продажа-хаб содержит FAQPage/ItemList/таблицу и рендерится как раньше; аренда-хаб содержит «/мес» и FAQPage. Остановить uvicorn.

- [ ] **Step 3: Деплой**

Закоммичено по задачам. Push в `main` → GitHub Actions `railway up` (см. `reference_railway_deploy`). Миграций нет — изменения только в коде.

```bash
git push origin main
```

- [ ] **Step 4: Пост-деплой smoke на проде**

- `https://uyradar.uz/arenda/chilanzar/2-komnatnye` → 200, «/мес», FAQ.
- `https://uyradar.uz/sitemap.xml` → содержит `/arenda/...`.
- Google Rich Results Test на одном hub-URL → видит FAQPage + ItemList без ошибок.
- Продажа-хаб `https://uyradar.uz/kvartira/yunusabad` → не сломан.

- [ ] **Step 5: Обновить память**

Дописать в `project_seo_search_consoles.md`: Хаб v2 + аренда-хабы в проде (intro/таблица/FAQ/ItemList JSON-LD, `/arenda/*`, кросс-линк, sitemap с арендой). Следующий SEO-шаг — ЖК-страницы.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спека:** deal-type-aware слой (T1) · таблица по комнатности (T2) · аренда-роуты+meta (T3) · Хаб v2 контент+JSON-LD (T4) · кросс-линк (T5) · каталог+sitemap аренды (T6) · edge-cases 404/thin сохранены (логика `total==0`/`available_hubs` не менялась). Шаг 0 покрывает проверку данных.
- **Плейсхолдеров нет:** весь код приведён дословно; FAQ/intro генерятся из данных.
- **Согласованность типов:** `HubData` поля (`deal_type`, `price_period`, `avg_price_usd`, `rooms_table`) объявлены в T1/T2 и используются в T3-T6; `PREFIX`/`ROOT_LABEL` объявлены в T3 и переиспользуются в T5/T6; `_stats`/`_intro`/`_faq`/`_cross_link` объявлены до использования в `_render_hub`. Хелперы ссылок (`_district_links`/`_room_links`) получили параметр `pre` единообразно в T3 и вызываются с ним в T6.
