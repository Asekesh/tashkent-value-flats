# SEO: Хаб v2 + аренда-хабы

**Дата:** 2026-06-30
**Статус:** дизайн утверждён, ждёт план реализации
**Цель:** рост органического трафика за счёт (а) более «толстого» контента на хабах
и (б) удвоения покрытия — отдельные SEO-лендинги для аренды.

## Контекст

В проде SSR-хабы только для **продажи**: `/kvartira`, `/kvartira/{район}`,
`/kvartira/{N-komnatnye}`, `/kvartira/{район}/{N-komnatnye}` + динамический
`/sitemap.xml`. Код в `backend/app/seo/` (`router.py`, `service.py`, `slugs.py`,
`templates/`). Шаблон тонкий: H1 + lead + статы + карточки + перелинковка +
BreadcrumbList JSON-LD. Конфиг уже умеет `Settings.thresholds(deal_type)`
(`min_rent_price_usd=50`, `min_rent_price_per_m2_usd=0.3`). Аренда уже льётся в
`listings` (`deal_type='rent'`, `price_period='month'`).

Дорожная карта SEO (из брейнсторма): **этот спек = п.1+п.2**. ЖК-страницы и
тематические срезы — отдельными спеками позже. Фаза 2 (страницы листингов) —
не делаем (риск duplicate-content, проигрыш первоисточнику).

## Объём (этот спек)

1. Шаблон хаба становится **deal-type-aware** (метрика $/м² ↔ $/мес).
2. **Хаб v2** — авто-абзац, таблица цен по комнатности, FAQ-блок (+`FAQPage`),
   `ItemList` JSON-LD. Прилетает и на продажу, и на аренду.
3. **Аренда-хабы** — `/arenda`, `/arenda/{slug}`, `/arenda/{dslug}/{rslug}`.
4. **Кросс-линк** продажа↔аренда в шапке хаба.
5. **Sitemap** включает аренда-хабы.

## Архитектура

Один общий рендер-путь и один `hub.html`, параметризованные `deal_type`.
Существующий код продажи остаётся работать без изменений (дефолты).

### Данные (`service.py`)

- `base_conditions(settings, deal_type="sale")` — параметр с дефолтом. Внутри
  использует `settings.thresholds(deal_type)` вместо захардкоженных порогов
  продажи и фильтрует `Listing.deal_type == deal_type`. **Обратносовместимо:**
  все текущие вызовы без аргумента ведут себя как сейчас.
- `HubData` — добавить поля `deal_type: str` и `price_period: str | None`.
  Новые поля с дефолтами → старый код не ломается.
- `load_hub(..., deal_type="sale")` — прокидывает `deal_type` в conditions и в
  `HubData`. Headline-метрику кладёт в `headline_value`/`headline_unit`
  (см. «Метрика»): sale → средняя `$/м²`, rent → средняя `$/мес`
  (`avg(price_usd)`).
- **Новый агрегат** `rooms_breakdown(db, settings, deal_type, district)` →
  `list[{rooms, count, avg_price}]` для таблицы по комнатности. Для продажи
  `avg_price` = средняя полная цена; для аренды = средняя $/мес. Запрос:
  `GROUP BY rooms` в рамках текущего среза, только `rooms in 1..5`,
  `count >= 1` (таблица — не отдельные индексируемые страницы, порог не нужен).
- `available_hubs(db, settings, deal_type="sale")` — параметр deal_type.

#### Метрика (решение)

Headline-стат у продажи = средняя `$/м²`; у аренды = средняя `$/мес`.
Чтобы не плодить ветвлений в шаблоне, `HubData` несёт:
- `headline_value: float | None` — число (ppm для sale, $/мес для rent),
- `headline_unit: str` — `"$/м²"` или `"$/мес"`.
Поля `avg_ppm_usd`/`min_price_usd` остаются как есть для продажи; для аренды
`min_price_usd` = «от $X/мес». Шаблон печатает `headline_value + headline_unit`.

### Контент Хаб v2 (`router.py` + `hub.html`)

- **Авто-абзац** (функция `_intro(data)` в router): из агрегатов, без ручного
  текста. Шаблон фразы зависит от вида хаба и deal_type. Пример (аренда,
  район+комнаты): «В {районе} сейчас {N} {N}-комнатных квартир в аренду.
  Аренда от {$A/мес} до {$B/мес}, в среднем {$X/мес}. {K} предложений ниже
  рыночной оценки.» Падежи районов — через `district_locative`.
- **Таблица по комнатности** — `rooms_breakdown`; рендерится только когда
  комнатность НЕ фиксирована, т.е. на хабе **район-only** (`data.rooms is
  None and data.district`). На rooms-only и комбо-хабе разбивка по комнатам
  вырождается в одну строку — таблицу скрываем.
- **FAQ-блок** (`_faq(data)` → list[{q, a}]): 4-5 авто-вопросов из агрегатов,
  например «Сколько стоит {снять/купить} {N}-комн в {районе}?»,
  «Сколько объявлений?», «Где дешевле — по районам?» (если city-level).
  Рендерится как видимый `<section>` **и** дублируется в `FAQPage` JSON-LD.
- **`ItemList` JSON-LD** по `data.cards`: `position`, `name` (title),
  `RealEstateListing` с `url` (внешний) и минимальным `offers.price`. В
  дополнение к существующему BreadcrumbList (две `<script type=ld+json>`).

### Аренда-роуты (`router.py`)

Зеркало текущих, отдельный `APIRouter` или общий с обоими префиксами:
- `/arenda` — каталог (аналог `catalog`), `deal_type="rent"`.
- `/arenda/{slug}` — район ИЛИ `N-komnatnye`.
- `/arenda/{dslug}/{rslug}` — район+комнаты.
Переиспользуют `DISTRICT_SLUGS`/`rooms_slug` (slug-карты общие). Свои meta:
`_meta(data)` ветвится по `data.deal_type` («Аренда {N}-комн квартир в
{районе} — от $X/мес | uyradar.uz»). Хлебные крошки: корень «Аренда» →
`/arenda`. `_canonical` — по `request.url.path` (уже корректно).

### Кросс-линк продажа↔аренда

В `hub.html` шапка: если `deal_type=="sale"` и для того же среза есть
аренда-аналог (проверка через `available_hubs('rent')`) → ссылка
«Снять в {районе}» на зеркальный `/arenda/...`; и наоборот. Если аналога нет —
ссылку не рисуем (без битых ссылок). Решение по «есть аналог» считаем в
router и кладём в контекст как `cross_link: {label, url} | None`.

### Sitemap (`service.py`)

`build_sitemap_xml` после блока продажи добавляет обход
`available_hubs(db, settings, deal_type="rent")` → entries для
`/arenda/...`. `lastmod` — `max(updated_at)` по rent-conditions. Та же защита
`MIN_HUB_LISTINGS`. `/arenda` (каталог) добавить в `_STATIC_URLS`-эквивалент
или отдельной строкой priority 0.8.

## Не входит (явно)

- $/м² для аренды (нишево).
- Ручные тексты-описания районов (отдельный «тяжёлый» уровень — не сейчас).
- Страницы отдельных листингов `/kvartira/{район}/{id}` (Фаза 2).
- Изменения публичного `/api/listings`, фронта `index.html`, бота, парсеров,
  CMA, модели `Listing`.

## Обработка ошибок / edge cases

- Срез с `total==0` → `HTTPException 404` (как сейчас), не в sitemap.
- Срез `< MIN_HUB_LISTINGS` → не в каталоге/sitemap (anti-thin), но прямой
  заход рендерится, если `total>0` (поведение продажи сохраняем).
- Аренда без `district`/`is_below_market` в данных → таблица/бейджи пустые,
  но страница валидна. См. шаг 0 «проверка данных».
- `FAQPage`/`ItemList` с пустыми данными не эмитим (валидный JSON-LD).

## Тестирование

- Юнит: `base_conditions`/`load_hub`/`available_hubs` с `deal_type` обоих
  значений — корректные SQL-условия и пороги.
- `rooms_breakdown` — агрегаты по фикстуре.
- Роуты: `/arenda/{район}/{N-komnatnye}` отдаёт 200 + содержит H1, $/мес,
  FAQ, оба JSON-LD; несуществующий slug → 404.
- Регресс: снапшот/глаз-проверка одной продажа-страницы — рендер не изменился
  по сути (добавились блоки, метрика та же).
- `sitemap.xml` содержит и `/kvartira/...`, и `/arenda/...`, валидный XML.

## Шаги реализации (предварительно, детализирует план)

0. **Проверка данных аренды** (в проде/staging): у `deal_type='rent'`
   заполнены `district`, `rooms`, `price_usd`, `price_period`, есть ли
   `is_below_market`/`discount_percent`. Если district почти пуст — таблица по
   комнатности для аренды деградирует (city-level всё равно работает).
1. `deal_type`-aware data-слой (`service.py`).
2. Хаб v2 контент (intro/FAQ/таблица/ItemList) на продаже.
3. Аренда-роуты + meta + каталог.
4. Кросс-линк.
5. Sitemap rent.
6. Деплой (см. `reference_railway_deploy`), подать обновлённый sitemap не
   нужно — Google перечитает; проверить выдачу `/arenda/...` и rich-results
   тестом (FAQ/ItemList).
