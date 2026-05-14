/* Step 6 — first-login onboarding window.

   Shown exactly once: right after a user's first login, while
   /auth/me reports has_seen_onboarding = false. Closing the window
   calls POST /onboarding/seen, which flips the flag in the database. */
(function () {
  "use strict";

  function featureListHtml() {
    var items = window.SERVICE_FEATURES || [];
    return items
      .map(function (f) {
        return "<li><b>" + f.title + "</b><span>" + f.body + "</span></li>";
      })
      .join("");
  }

  function buildModal() {
    var overlay = document.createElement("div");
    overlay.id = "onboardingOverlay";
    overlay.className = "reg-overlay";
    overlay.innerHTML =
      '<div class="reg-modal" role="dialog" aria-modal="true" aria-labelledby="onbTitle">' +
      '<button class="reg-close" type="button" aria-label="Закрыть">×</button>' +
      '<h2 id="onbTitle">Добро пожаловать!</h2>' +
      '<p class="reg-sub">Коротко о том, что умеет сервис:</p>' +
      '<ul class="reg-features">' +
      featureListHtml() +
      "</ul>" +
      '<button class="reg-primary" type="button">Начать пользоваться</button>' +
      "</div>";
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) closeModal();
    });
    overlay.querySelector(".reg-close").addEventListener("click", closeModal);
    overlay.querySelector(".reg-primary").addEventListener("click", closeModal);
    return overlay;
  }

  function closeModal() {
    var overlay = document.getElementById("onboardingOverlay");
    if (overlay) overlay.classList.remove("active");
    // Persist the flag so the window never shows again for this user.
    fetch("/onboarding/seen", {
      method: "POST",
      credentials: "same-origin",
    }).catch(function () {
      /* best-effort: a failed call just means it may show once more */
    });
  }

  function showModal() {
    var overlay = document.getElementById("onboardingOverlay") || buildModal();
    overlay.classList.add("active");
  }

  fetch("/auth/me", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (me) {
      if (me && me.authenticated && me.has_seen_onboarding === false) {
        showModal();
      }
    })
    .catch(function () {
      /* public site keeps working even if auth endpoints fail */
    });
})();
