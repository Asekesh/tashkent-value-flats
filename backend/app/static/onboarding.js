/* First-visit onboarding — welcome screen.

   Shown automatically once per browser: while localStorage has no
   "onboarding_seen" flag. Any close (кнопка «Понятно, начать», клик по
   фону, Esc, ссылка «Больше не показывать») записывает флаг.
   Иконка «?» в шапке повторно открывает окно в любой момент.
   Та же подборка преимуществ рендерится в постоянный блок
   «Как это работает» на Главной. */
(function () {
  "use strict";

  var STORAGE_KEY = "onboarding_seen";
  var keyHandler = null;

  function cardsHtml() {
    var items = window.SERVICE_FEATURES || [];
    return items
      .map(function (f) {
        return (
          '<li><span class="onb-ic">' +
          (f.icon || "✦") +
          "</span><b>" +
          f.title +
          "</b><span>" +
          f.body +
          "</span></li>"
        );
      })
      .join("");
  }

  function buildModal() {
    var overlay = document.createElement("div");
    overlay.id = "onboardingOverlay";
    overlay.className = "reg-overlay";
    overlay.innerHTML =
      '<div class="reg-modal onb-modal" role="dialog" aria-modal="true" aria-labelledby="onbTitle">' +
      '<button class="reg-close" type="button" aria-label="Закрыть">×</button>' +
      '<h2 id="onbTitle">Добро пожаловать</h2>' +
      '<p class="reg-sub">Сервис собирает квартиры Ташкента ниже рыночной цены — вот как это работает:</p>' +
      '<ul class="reg-features onb-grid">' +
      cardsHtml() +
      "</ul>" +
      '<button class="reg-primary" type="button">Понятно, начать</button>' +
      '<button class="reg-later" type="button">Больше не показывать</button>' +
      "</div>";
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) closeModal();
    });
    overlay.querySelector(".reg-close").addEventListener("click", closeModal);
    overlay.querySelector(".reg-primary").addEventListener("click", closeModal);
    overlay.querySelector(".reg-later").addEventListener("click", closeModal);
    return overlay;
  }

  function closeModal() {
    var overlay = document.getElementById("onboardingOverlay");
    if (overlay) overlay.classList.remove("active");
    if (keyHandler) {
      document.removeEventListener("keydown", keyHandler);
      keyHandler = null;
    }
    // Шоу один раз — пишем флаг в localStorage.
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch (e) {
      /* приватный режим и т.п. — окно может показаться ещё раз, не критично */
    }
    // Best-effort серверный флаг для залогиненных (наследие Step 6).
    fetch("/onboarding/seen", {
      method: "POST",
      credentials: "same-origin",
    }).catch(function () {});
  }

  function showModal() {
    var overlay = document.getElementById("onboardingOverlay") || buildModal();
    overlay.classList.add("active");
    if (!keyHandler) {
      keyHandler = function (e) {
        if (e.key === "Escape") closeModal();
      };
      document.addEventListener("keydown", keyHandler);
    }
  }

  // Постоянный блок «Как это работает» на Главной.
  var howGrid = document.getElementById("howItWorksGrid");
  if (howGrid) howGrid.innerHTML = cardsHtml();

  // Иконка «?» в шапке — повторно открывает welcome screen.
  var helpBtn = document.getElementById("onboardingHelp");
  if (helpBtn) helpBtn.addEventListener("click", showModal);

  // Доступ к окну для прочих кнопок при необходимости.
  window.openOnboarding = showModal;

  // Первый визит — показываем автоматически.
  var seen = null;
  try {
    seen = localStorage.getItem(STORAGE_KEY);
  } catch (e) {
    /* localStorage недоступен — покажем окно как при первом визите */
  }
  if (!seen) showModal();
})();
