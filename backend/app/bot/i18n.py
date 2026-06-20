from __future__ import annotations

"""Двуязычие бота (ru/uz). Все пользовательские строки бота живут здесь.

Язык выбирается по Telegram language_code при первом /start (uz* → узбекский,
иначе русский) и хранится в users.lang; пользователь может сменить его кнопкой
«🌐 Til / Язык» в меню. Объявления (тексты с источников) НЕ переводим —
переводится только интерфейс-обёртка.

UZ-перевод — рабочий черновик на латинице; стоит вычитать носителем.
"""

SUPPORTED_LANGS = ("ru", "uz")
DEFAULT_LANG = "ru"


def normalize_lang(lang: str | None) -> str:
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def pick_lang(language_code: str | None) -> str:
    """Telegram language_code → наш код. 'uz'/'uz-UZ' → узбекский, иначе русский."""
    if language_code and language_code.lower().startswith("uz"):
        return "uz"
    return DEFAULT_LANG


def t(key: str, lang: str | None = DEFAULT_LANG, **kwargs: object) -> str:
    """Строка по ключу на нужном языке. Нет перевода → fallback на русский → ключ."""
    lang = normalize_lang(lang)
    table = TEXTS.get(key, {})
    text = table.get(lang) or table.get(DEFAULT_LANG) or key
    return text.format(**kwargs) if kwargs else text


# Единицы измерения для кнопок/сводки фильтра.
def rooms_label(n: int, lang: str | None = DEFAULT_LANG) -> str:
    return f"{n}к" if normalize_lang(lang) == "ru" else f"{n} xona"


def area_label(v: int, lang: str | None = DEFAULT_LANG) -> str:
    return f"{v} м²" if normalize_lang(lang) == "ru" else f"{v} m²"


def floor_label(v: int, lang: str | None = DEFAULT_LANG) -> str:
    return f"{v} эт." if normalize_lang(lang) == "ru" else f"{v}-qavat"


TEXTS: dict[str, dict[str, str]] = {
    # ---------- /start, /help ----------
    "help": {
        "ru": (
            "🤖 Бот следит за новыми объявлениями по Ташкенту и шлёт вам уведомления, "
            "как только появится подходящая квартира.\n\n"
            "<b>Как пользоваться:</b>\n"
            "1️⃣ Нажмите <b>«➕ Новое уведомление»</b> и за пару шагов задайте фильтр "
            "(район, комнаты, цена…).\n"
            "2️⃣ Бот сам пришлёт сообщение, когда найдётся квартира под ваш фильтр.\n"
            "3️⃣ В <b>«📋 Мои уведомления»</b> можно поставить на паузу или удалить.\n\n"
            "<b>Команды:</b>\n"
            "/new — настроить уведомления о новых квартирах\n"
            "/list — мои уведомления\n"
            "/help — помощь"
        ),
        "uz": (
            "🤖 Bot Toshkent bo'yicha yangi e'lonlarni kuzatadi va mos kvartira "
            "paydo bo'lishi bilanoq sizga xabar yuboradi.\n\n"
            "<b>Qanday foydalaniladi:</b>\n"
            "1️⃣ <b>«➕ Yangi bildirishnoma»</b> tugmasini bosing va bir necha qadamda "
            "filtr belgilang (tuman, xonalar, narx…).\n"
            "2️⃣ Filtringizga mos kvartira topilsa, bot o'zi xabar yuboradi.\n"
            "3️⃣ <b>«📋 Mening bildirishnomalarim»</b> bo'limida pauza qilish yoki "
            "o'chirish mumkin.\n\n"
            "<b>Buyruqlar:</b>\n"
            "/new — yangi kvartiralar bo'yicha bildirishnoma sozlash\n"
            "/list — mening bildirishnomalarim\n"
            "/help — yordam"
        ),
    },
    "welcome": {
        "ru": (
            "Привет! 👋\n\n"
            "Я собираю объявления о квартирах в Ташкенте сразу с трёх площадок — "
            "<b>OLX, Uybor и Realt24</b> — и присылаю уведомление, как только появится "
            "вариант под ваш фильтр.\n\n"
            "Просто нажмите кнопку ниже — настроим за минуту 👇"
        ),
        "uz": (
            "Salom! 👋\n\n"
            "Men Toshkentdagi kvartira e'lonlarini bir vaqtda uch saytdan to'playman — "
            "<b>OLX, Uybor va Realt24</b> — va filtringizga mos variant chiqishi bilanoq "
            "xabar yuboraman.\n\n"
            "Quyidagi tugmani bosing — bir daqiqada sozlaymiz 👇"
        ),
    },
    "choose_action": {
        "ru": "Что хотите сделать?",
        "uz": "Nima qilmoqchisiz?",
    },
    # ---------- Обратная связь ----------
    "feedback_intro": {
        "ru": "Спасибо, что помогаете нам стать лучше! Что хотите сообщить?",
        "uz": "Bizni yaxshilashga yordam berganingiz uchun rahmat! Nima haqida xabar bermoqchisiz?",
    },
    "feedback_bug": {
        "ru": "Опишите ошибку — что произошло и что ожидали 👇",
        "uz": "Xatoni tasvirlang — nima yuz berdi va nimani kutgandingiz 👇",
    },
    "feedback_feature": {
        "ru": "Напишите ваше пожелание или идею 👇",
        "uz": "Istagingiz yoki g'oyangizni yozing 👇",
    },
    "feedback_empty": {
        "ru": "Напишите, пожалуйста, текст сообщения.",
        "uz": "Iltimos, xabar matnini yozing.",
    },
    "feedback_thanks": {
        "ru": "✅ Спасибо! Сообщение отправлено — мы обязательно его прочитаем.",
        "uz": "✅ Rahmat! Xabar yuborildi — biz uni albatta o'qiymiz.",
    },
    # ---------- /new flow ----------
    "step_districts": {
        "ru": "Шаг 1/6. Выберите районы (можно несколько):",
        "uz": "1/6-qadam. Tumanlarni tanlang (bir nechtasini mumkin):",
    },
    "step_districts_edit": {
        "ru": "✏️ Меняем фильтр. Шаг 1/6. Выберите районы (можно несколько):",
        "uz": "✏️ Filtrni o'zgartiramiz. 1/6-qadam. Tumanlarni tanlang (bir nechtasini mumkin):",
    },
    "step_rooms": {
        "ru": "Шаг 2/6. Сколько комнат?",
        "uz": "2/6-qadam. Nechta xona?",
    },
    "step_price_min": {
        "ru": "Шаг 3/7. Цена (USD). Сначала выберите минимум (<b>от</b>):",
        "uz": "3/7-qadam. Narx (USD). Avval minimumni tanlang (<b>dan</b>):",
    },
    "step_price_max": {
        "ru": "Шаг 3/7. Теперь максимум цены (<b>до</b>):",
        "uz": "3/7-qadam. Endi maksimal narx (<b>gacha</b>):",
    },
    "step_area_min": {
        "ru": "Шаг 4/7. Площадь, м². Сначала минимум (<b>от</b>):",
        "uz": "4/7-qadam. Maydon, m². Avval minimum (<b>dan</b>):",
    },
    "step_area_max": {
        "ru": "Шаг 4/7. Теперь максимум площади (<b>до</b>):",
        "uz": "4/7-qadam. Endi maksimal maydon (<b>gacha</b>):",
    },
    "step_floor_min": {
        "ru": "Шаг 5/7. Этаж. Сначала минимум (<b>от</b>):",
        "uz": "5/7-qadam. Qavat. Avval minimum (<b>dan</b>):",
    },
    "step_floor_max": {
        "ru": "Шаг 5/7. Теперь максимум этажа (<b>до</b>):",
        "uz": "5/7-qadam. Endi maksimal qavat (<b>gacha</b>):",
    },
    "step_discount": {
        "ru": "Шаг 6/7. Насколько ниже рынка должна быть цена?",
        "uz": "6/7-qadam. Narx bozordan qancha past bo'lishi kerak?",
    },
    "step_name": {
        "ru": (
            "Шаг 7/7. Как назвать этот фильтр? Напишите любое короткое имя "
            "(например «3-комн. Юнусабад»)."
        ),
        "uz": (
            "7/7-qadam. Bu filtrni qanday nomlaymiz? Istalgan qisqa nom yozing "
            "(masalan «3 xonali Yunusobod»)."
        ),
    },
    "noname": {
        "ru": "Без имени",
        "uz": "Nomsiz",
    },
    "reset_district": {
        "ru": "Сброшено — любой район",
        "uz": "Tozalandi — istalgan tuman",
    },
    "reset_any": {
        "ru": "Сброшено — любое",
        "uz": "Tozalandi — istalgan",
    },
    "not_found": {
        "ru": "Не нашёл уведомление.",
        "uz": "Bildirishnoma topilmadi.",
    },
    "not_found_edit": {
        "ru": "Не нашёл уведомление для изменения.",
        "uz": "O'zgartirish uchun bildirishnoma topilmadi.",
    },
    "saved": {
        "ru": (
            "✅ Уведомление <b>«{name}»</b> {verb}.\n\n{summary}\n\n"
            "Теперь я пришлю сообщение, как только появится подходящая квартира."
        ),
        "uz": (
            "✅ <b>«{name}»</b> bildirishnomasi {verb}.\n\n{summary}\n\n"
            "Endi mos kvartira chiqishi bilanoq xabar yuboraman."
        ),
    },
    "verb_updated": {"ru": "обновлено", "uz": "yangilandi"},
    "verb_created": {"ru": "создано", "uz": "yaratildi"},
    "no_alerts": {
        "ru": "Уведомлений пока нет. Нажмите «➕ Новое уведомление», чтобы создать первое.",
        "uz": "Hozircha bildirishnoma yo'q. Birinchisini yaratish uchun «➕ Yangi bildirishnoma» tugmasini bosing.",
    },
    "status_active": {"ru": "🟢 активно", "uz": "🟢 faol"},
    "status_paused": {"ru": "⏸ на паузе", "uz": "⏸ pauzada"},
    "done": {"ru": "Готово", "uz": "Tayyor"},
    "deleted": {
        "ru": "🗑 Уведомление удалено.",
        "uz": "🗑 Bildirishnoma o'chirildi.",
    },
    # ---------- Смена языка ----------
    "lang_choose": {
        "ru": "Выберите язык:",
        "uz": "Tilni tanlang:",
    },
    "lang_done": {
        "ru": "Готово — продолжаем на русском. 🇷🇺",
        "uz": "Tayyor — oʻzbekchada davom etamiz. 🇺🇿",
    },
    # ---------- Кнопки меню ----------
    "b_new": {"ru": "➕ Новое уведомление", "uz": "➕ Yangi bildirishnoma"},
    "b_list": {"ru": "📋 Мои уведомления", "uz": "📋 Mening bildirishnomalarim"},
    "b_feedback": {"ru": "✍️ Обратная связь", "uz": "✍️ Fikr-mulohaza"},
    "b_help": {"ru": "ℹ️ Помощь", "uz": "ℹ️ Yordam"},
    "placeholder": {"ru": "Нажмите кнопку ниже 👇", "uz": "Quyidagi tugmani bosing 👇"},
    "b_start_new": {
        "ru": "➕ Создать уведомление о новых квартирах",
        "uz": "➕ Yangi kvartiralar haqida bildirishnoma yaratish",
    },
    "b_how": {"ru": "ℹ️ Как это работает", "uz": "ℹ️ Bu qanday ishlaydi"},
    "b_bug": {"ru": "🐞 Ошибка", "uz": "🐞 Xato"},
    "b_feature": {"ru": "💡 Пожелание", "uz": "💡 Taklif"},
    "b_any_district": {"ru": "🌐 Любой", "uz": "🌐 Istalgan"},
    "b_any_rooms": {"ru": "🌐 Любое", "uz": "🌐 Istalgan"},
    "b_done": {"ru": "✔️ Готово", "uz": "✔️ Tayyor"},
    "b_unimportant": {"ru": "🌐 Неважно", "uz": "🌐 Farqi yo'q"},
    "b_no_upper": {"ru": "🌐 Без верхней границы", "uz": "🌐 Yuqori chegarasiz"},
    "b_any_discount": {"ru": "🌐 Любая (не важно)", "uz": "🌐 Istalgan (farqi yo'q)"},
    "b_pause": {"ru": "⏸ Пауза", "uz": "⏸ Pauza"},
    "b_enable": {"ru": "▶️ Включить", "uz": "▶️ Yoqish"},
    "b_delete": {"ru": "🗑 Удалить", "uz": "🗑 O'chirish"},
    "b_edit": {"ru": "✏️ Изменить фильтр", "uz": "✏️ Filtrni o'zgartirish"},
    # Кнопка-переключатель и выбор языка — двуязычные (одинаковы в обоих языках).
    "b_lang": {"ru": "🌐 Til / Язык", "uz": "🌐 Til / Язык"},
    "b_lang_ru": {"ru": "🇷🇺 Русский", "uz": "🇷🇺 Русский"},
    "b_lang_uz": {"ru": "🇺🇿 Oʻzbekcha", "uz": "🇺🇿 Oʻzbekcha"},
    # ---------- Сводка фильтра (describe_alert) ----------
    "da_any_district": {"ru": "любой район", "uz": "istalgan tuman"},
    "da_floor": {"ru": "этаж", "uz": "qavat"},
    "da_discount": {"ru": "скидка ≥ {pct}%", "uz": "chegirma ≥ {pct}%"},
    # ---------- Уведомление о квартире (notifier) ----------
    "n_below_market": {
        "ru": "🎯 <b>{pct}% ниже рынка</b>",
        "uz": "🎯 <b>bozordan {pct}% past</b>",
    },
    "n_view": {
        "ru": "🔎 Смотреть объявление →",
        "uz": "🔎 E'lonni ko'rish →",
    },
    # ---------- Шаг deal_type / комиссия (rent flow) ----------
    "step_deal_type": {
        "ru": "Что ищем — купить или снять?",
        "uz": "Nima qidiramiz — sotib olishmi yoki ijaraga olishmi?",
    },
    "b_deal_sale": {"ru": "🏠 Купить", "uz": "🏠 Sotib olish"},
    "b_deal_rent": {"ru": "🔑 Снять", "uz": "🔑 Ijara"},
    "step_commission": {
        "ru": "Комиссия риелтора?",
        "uz": "Rieltor komissiyasi?",
    },
    "b_no_commission": {"ru": "Без комиссии", "uz": "Komissiyasiz"},
    "da_deal_sale": {"ru": "🏷 Продажа", "uz": "🏷 Sotuv"},
    "da_deal_rent": {"ru": "🏷 Аренда", "uz": "🏷 Ijara"},
    "da_no_commission": {"ru": "✅ без комиссии", "uz": "✅ komissiyasiz"},
    "n_per_month": {"ru": "/мес", "uz": "/oy"},
    "n_no_commission": {"ru": "✅ без комиссии", "uz": "✅ komissiyasiz"},
}
