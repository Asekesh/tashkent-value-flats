# Бот учится аренде (Шаг 5 раздела «Аренда»)

Дата: 2026-06-20
Статус: согласован, готов к плану реализации

## Контекст

Раздел «Аренда» доведён до фронта (тумблер Продажа/Аренда, цена «$X/мес»),
парсеры аренды наливают (Uybor + OLX, помесячная, `deal_type='rent'`),
rent-CMA/видимость/классификатор собственников/ЖК — в проде. Не умеет аренду
только **Telegram-бот**: алёрты создаются без выбора типа сделки и матчатся без
оглядки на `deal_type`.

### Латентный баг (чинится этим же изменением)

`alert_matches_listing` (`backend/app/bot/matcher.py`) **не фильтрует по
`deal_type`**. Теперь, когда аренда льётся в ту же таблицу `listings`, rent-листинг
может просочиться в sale-алёрт. Пока спасает только разный масштаб цен (аренда
помесячная), но sale-алёрт без ценового фильтра (только район+комнаты) поймает
rent-листинг. Стенку по `deal_type` надо ставить в matcher в любом случае.

## Решение (выбранный вариант A)

Добавить тип сделки и rent-специфичные поля **колонками в существующую таблицу
`alerts`** — тот же приём, что «стенка» `deal_type` в `listings`. Альтернативы
(отдельная таблица rent-алёртов; JSON-колонка) отвергнуты как оверкилл/разнобой
с принятым в проекте паттерном реальных колонок.

Мебель в скоуп НЕ входит (ни фильтр, ни бейдж) — решение пользователя.

## Изменения по компонентам

### 1. Модель `Alert` + миграция

`backend/app/models/alert.py` — добавить:
- `deal_type: str` — `default="sale"`, `server_default="sale"`, `index=True`.
- `no_commission: bool | None` — `True` = только без комиссии, `None` = неважно.

Миграция `0019_alert_deal_type.py` (id ревизии ≤32 символа — иначе деплой тихо
падает и прод застревает на старом коде):
- `add_column alerts.deal_type` (String(16), server_default 'sale', not null).
- `add_column alerts.no_commission` (Boolean, nullable).
- Существующие строки бэкфилятся в `'sale'` через server_default — отдельный
  UPDATE не нужен.

### 2. FSM (`backend/app/bot/states.py`)

Добавить первый шаг и rent-шаг:
```
class NewAlert(StatesGroup):
    deal_type = State()      # новый первый шаг
    districts = State()
    rooms = State()
    price = State()
    area = State()
    floor = State()
    discount = State()       # только sale-ветка
    commission = State()     # только rent-ветка
    name = State()
```

### 3. Хендлеры (`backend/app/bot/handlers.py`)

- `_begin_new_alert` стартует с `NewAlert.deal_type`, кладёт `deal_type='sale'`
  в state по умолчанию, показывает тумблер `[Продажа ✓] [Аренда]`.
- Хендлер `on_deal_type` (`F.data.startswith("deal:")`): тоггл выбора (правит
  reply_markup на той же клавиатуре, галочка переезжает), кнопка `done` →
  переход к `NewAlert.districts`. Дефолт — `sale`.
- **Ветвление после этажа:**
  - sale → `NewAlert.discount` (как сейчас) → имя.
  - rent → `NewAlert.commission` (новый шаг: `[Без комиссии] [Неважно]`) → имя.
- `set_name` пишет `deal_type` и (для rent) `no_commission` в `fields`. Для sale
  `no_commission=None`, для rent `discount_min=None`.
- **Ценовые пресеты** берутся по `deal_type` из `state` (см. keyboards).
- `/edit`: тип сделки **неизменяем** — при редактировании `deal_type` берётся из
  существующего алёрта, шаг тумблера пропускается, ветка флоу выбирается по нему.
  Сменить тип = удалить и создать заново.

### 4. Клавиатуры (`backend/app/bot/keyboards.py`)

- `deal_type_keyboard(selected, lang)` — две кнопки с галочкой + «Готово».
- `commission_keyboard(lang)` — `[Без комиссии] [Неважно]`.
- Ценовые пресеты: `PRICE_VALUES_RENT = [200, 300, 400, 500, 700, 1000, 1500,
  2000, 3000]` ($/мес). `price_from_keyboard`/`price_to_keyboard` принимают
  `deal_type` и выбирают набор (`PRICE_VALUES` для sale, `PRICE_VALUES_RENT` для
  rent). Callback payload остаётся индексом — хендлер резолвит по тому же набору.

### 5. Matcher (`backend/app/bot/matcher.py`)

`alert_matches_listing` — в начало:
```
if (listing.deal_type or "sale") != (alert.deal_type or "sale"):
    return False
```
Для rent дополнительно: если `alert.no_commission` → требовать
`listing.commission_pct == 0` (NULL=неизвестно — не проходит). Скидка к рынку
(`discount_min`) для rent не проверяется (в rent-алёрте всегда NULL).

### 6. Notifier (`backend/app/bot/notifier.py`)

- Порог `min_listing_price_usd` (десятки тысяч) применять **только к sale** — для
  rent он отсекал бы всё. Для rent порога вменяемости цены нет (фильтрация уже на
  уровне парсера).
- `_send_listing_sync` — формат по `deal_type`:
  - sale — как сейчас.
  - rent — цена как `$X/мес`; строка скидки заменяется бейджем «✅ без комиссии»,
    когда `listing.commission_pct == 0`.

### 7. Отображение (`describe_alert` в `matcher.py`, `/list`)

- Шапка алёрта: префикс «🏷 Аренда» / «🏷 Продажа».
- rent: цена «$X…$Y/мес»; строка «✅ без комиссии», когда `no_commission=True`;
  строки скидки нет.

### 8. i18n (`backend/app/bot/i18n.py`)

Новые ключи (ru/uz): шаг `deal_type` (вопрос + подписи кнопок Продажа/Аренда),
шаг `commission` (вопрос + Без комиссии/Неважно), «/мес», бейдж «без комиссии»,
префиксы типа в `describe_alert`.

## Вне скоупа

- Доходность (rental yield) в пуше.
- ЖК-фильтр в алёрте.
- Смена `deal_type` у существующего алёрта.
- Бейдж/фильтр мебели.

## Критерии готовности

- Можно создать rent-алёрт через бота; sale-алёрты работают по-старому.
- rent-листинг матчится только rent-алёртом и наоборот (стенка `deal_type`).
- Фильтр «без комиссии» отсекает листинги с `commission_pct != 0` / NULL.
- Пуш аренды показывает «$X/мес» и (при наличии) «✅ без комиссии».
- `/list` и подтверждение создания показывают тип сделки.
- Миграция 0019 проходит на проде (id ≤32 симв), старые алёрты = `sale`.
