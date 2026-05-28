/* Shared list of "what the service does" — used in the registration gate
   modal (Step 5), the onboarding welcome window and the permanent
   "Как это работает" block on the dashboard.

   `icon` is a name from the SVG sprite in index.html (#i-<name>). */
window.SERVICE_FEATURES = [
  {
    icon: "grid",
    title: "Всё в одном месте",
    body: "Объявления с OLX, Uybor и Realt24 на одной панели — не нужно мониторить площадки вручную.",
  },
  {
    icon: "trending-down",
    title: "Цены ниже рынка",
    body: "Система находит квартиры со скидкой 15–99% от средней цены в том же ЖК.",
  },
  {
    icon: "tag",
    title: "Честная цена за м²",
    body: "Для каждого объекта считается реальная стоимость метра и дисконт к рынку.",
  },
  {
    icon: "building",
    title: "Сравнение внутри ЖК",
    body: "Цена сравнивается со средней по жилому комплексу, а не по городу в целом.",
  },
  {
    icon: "refresh",
    title: "Обновление каждые 15 минут",
    body: "Авто-сбор с 3 площадок — новые скидки появляются почти в реальном времени.",
  },
  {
    icon: "check-circle",
    title: "Без дублей",
    body: "Объявления дедуплицируются по дому и ссылкам — один объект показывается один раз.",
  },
  {
    icon: "clock",
    title: "История объявления",
    body: "Видно, когда объект выставили, как менялась цена и сколько раз его перевыставляли «как новый» — мощный рычаг для торга.",
  },
  {
    icon: "sliders",
    title: "Мощные фильтры",
    body: "Район, комнаты, источник, цена, площадь, $/м², размер скидки и сортировка по выгоде.",
  },
];
