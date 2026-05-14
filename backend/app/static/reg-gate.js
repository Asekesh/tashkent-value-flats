/* Step 5 — soft registration gate.

   Frontend-only layer over the existing public feed. Anonymous users still
   see search results; a registration modal is triggered on a *meaningful*
   action (applying a filter, changing sort, opening a listing card) — never
   on plain scroll or hover. For authenticated users the gate is disabled. */
(function () {
  "use strict";

  var COOKIE = "reg_prompt_seen";
  var authed = false;
  var promptEvery = 3; // overridden from /auth/config (reg_prompt_every)
  var botUsername = "";
  var actionsSinceClose = 0;
  var modalOpen = false;
  var ready = false;

  function hasCookie(name) {
    return document.cookie.split("; ").some(function (c) {
      return c.indexOf(name + "=") === 0;
    });
  }

  function setCookie(name, days) {
    var expires = new Date(Date.now() + days * 86400000).toUTCString();
    document.cookie = name + "=1; expires=" + expires + "; path=/; samesite=lax";
  }

  function featureListHtml() {
    var items = window.SERVICE_FEATURES || [];
    return items
      .map(function (f) {
        return "<li><b>" + f.title + "</b><span>" + f.body + "</span></li>";
      })
      .join("");
  }

  function injectWidget(box) {
    if (!botUsername) {
      box.innerHTML =
        '<span class="reg-hint">Вход через Telegram временно недоступен.</span>';
      return;
    }
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-auth-url", "/auth/telegram/callback");
    script.setAttribute("data-request-access", "write");
    box.appendChild(script);
  }

  function buildModal() {
    var overlay = document.createElement("div");
    overlay.id = "regOverlay";
    overlay.className = "reg-overlay";
    overlay.innerHTML =
      '<div class="reg-modal" role="dialog" aria-modal="true" aria-labelledby="regTitle">' +
      '<button class="reg-close" type="button" aria-label="Закрыть">×</button>' +
      '<h2 id="regTitle">Зарегистрируйтесь, чтобы пользоваться сервисом</h2>' +
      '<p class="reg-sub">Выдача открыта и без входа. Регистрация добавляет:</p>' +
      '<ul class="reg-features">' +
      featureListHtml() +
      "</ul>" +
      '<div class="reg-auth" id="regAuthBox"></div>' +
      '<button class="reg-later" type="button">Позже</button>' +
      "</div>";
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) closeModal();
    });
    overlay.querySelector(".reg-close").addEventListener("click", closeModal);
    overlay.querySelector(".reg-later").addEventListener("click", closeModal);
    return overlay;
  }

  function showModal() {
    if (modalOpen) return;
    var overlay = document.getElementById("regOverlay") || buildModal();
    var box = overlay.querySelector("#regAuthBox");
    if (box && !box.dataset.loaded) {
      box.dataset.loaded = "1";
      injectWidget(box);
    }
    overlay.classList.add("active");
    modalOpen = true;
  }

  function closeModal() {
    var overlay = document.getElementById("regOverlay");
    if (overlay) overlay.classList.remove("active");
    modalOpen = false;
    actionsSinceClose = 0;
    // Remember the dismissal so we don't prompt on every click afterwards.
    setCookie(COOKIE, 30);
  }

  function onMeaningfulAction() {
    if (!ready || authed || modalOpen) return;
    if (!hasCookie(COOKIE)) {
      // First meaningful action ever — show the dismissible prompt.
      showModal();
      return;
    }
    // Already dismissed once: re-show no more often than every N actions.
    actionsSinceClose += 1;
    if (actionsSinceClose >= promptEvery) {
      actionsSinceClose = 0;
      showModal();
    }
  }

  // Meaningful actions = applying filters / opening a card. Scroll & hover
  // are intentionally NOT listed here.
  var TRIGGER_SELECTOR =
    "#applyButton,[data-quick-rooms],[data-quick-discount],[data-quick-ppm]," +
    "[data-stat-filter],[data-source-pill],[data-cma],.listing-card";

  // Capture phase so we see the click even though app.js handlers run too —
  // the gate is purely additive and never blocks the underlying action.
  document.addEventListener(
    "click",
    function (event) {
      if (event.target.closest && event.target.closest(TRIGGER_SELECTOR)) {
        onMeaningfulAction();
      }
    },
    true
  );
  document.addEventListener(
    "change",
    function (event) {
      if (event.target && event.target.id === "sort") onMeaningfulAction();
    },
    true
  );

  // Pull auth state + config once. Gate stays inert until this resolves.
  Promise.all([
    fetch("/auth/me", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .catch(function () { return null; }),
    fetch("/auth/config")
      .then(function (r) { return r.json(); })
      .catch(function () { return null; }),
  ]).then(function (results) {
    var me = results[0];
    var cfg = results[1];
    authed = !!(me && me.authenticated);
    if (cfg) {
      botUsername = cfg.bot_username || "";
      if (typeof cfg.reg_prompt_every === "number" && cfg.reg_prompt_every > 0) {
        promptEvery = cfg.reg_prompt_every;
      }
    }
    ready = true;
  });
})();
