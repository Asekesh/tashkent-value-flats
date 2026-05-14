const defaultFilters = {
  district: "",
  rooms: "",
  area_min: "",
  area_max: "",
  price_min: "",
  price_max: "",
  ppm_min: "",
  ppm_max: "",
  discount_min: "",
  source: "",
  sort: "discount",
};

const PAGE_SIZE = 50;
const state = {
  view: "dashboard",
  listings: [],
  selectedId: null,
  total: 0,
  page: 0,
  favorites: readFavorites(),
  runs: [],
  sourceStats: [],
  stats: { total: 0, hot: 0, new_today: 0, sources: [] },
  dashboardSource: "",
};

const filterIds = Object.keys(defaultFilters);
const statusEl = document.querySelector("#status");
const dashboardList = document.querySelector("#dashboardList");
const listingsList = document.querySelector("#listingsList");
const insightPanel = document.querySelector("#insightPanel");
const runList = document.querySelector("#runList");
const sourceStatsEl = document.querySelector("#sourceStats");
const progressEl = document.querySelector("#scrapeProgress");
const progressPagesEl = document.querySelector("#scrapeProgressPages");
const progressFoundEl = document.querySelector("#scrapeProgressFound");
const progressNewEl = document.querySelector("#scrapeProgressNew");
const progressTitleEl = document.querySelector("#scrapeProgressTitle");
const progressMetaEl = document.querySelector("#scrapeProgressMeta");
const taskListEl = document.querySelector("#taskList");

let progressPollTimer = null;
let tasksState = [];

document.querySelector("#adminImportButton").addEventListener("click", () => runScrapeMode("quick"));
document.querySelector("#quickScanButton").addEventListener("click", () => runScrapeMode("quick"));
document.querySelector("#fullScanButton").addEventListener("click", () => runScrapeMode("full"));
document.querySelector("#stopScanButton").addEventListener("click", stopScrape);
document.querySelector("#applyButton").addEventListener("click", () => fetchListings(readFilters(), 0));
document.querySelector("#resetButton").addEventListener("click", resetFilters);
document.querySelector("#refreshRunsButton").addEventListener("click", fetchTasks);
document.querySelector("#refreshSourcePagesButton").addEventListener("click", fetchSourceStats);
document.querySelectorAll("[data-open-listings]").forEach((button) => button.addEventListener("click", () => setView("listings")));
document.querySelectorAll("[data-view-button]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.viewButton));
});
document.querySelectorAll("[data-quick-rooms]").forEach((button) => {
  button.addEventListener("click", () => {
    writeFilters({ ...defaultFilters, rooms: button.dataset.quickRooms, sort: "discount" });
    setView("listings");
    fetchListings(readFilters(), 0);
  });
});
document.querySelector("[data-quick-discount]").addEventListener("click", () => {
  writeFilters({ ...defaultFilters, discount_min: "15", sort: "discount" });
  setView("listings");
  fetchListings(readFilters(), 0);
});
document.querySelector("[data-quick-ppm]").addEventListener("click", () => {
  writeFilters({ ...defaultFilters, sort: "price_per_m2" });
  setView("listings");
  fetchListings(readFilters(), 0);
});
document.querySelectorAll("[data-stat-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    const kind = button.dataset.statFilter;
    const base = { ...defaultFilters, source: state.dashboardSource };
    if (kind === "hot") {
      writeFilters({ ...base, discount_min: "15", sort: "discount" });
    } else if (kind === "new-today") {
      writeFilters({ ...base, discount_min: "15", sort: "fresh" });
    } else {
      writeFilters({ ...base, sort: "discount" });
    }
    setView("listings");
    fetchListings(readFilters(), 0);
  });
});
document.querySelectorAll("[data-source-pill]").forEach((button) => {
  button.addEventListener("click", () => {
    state.dashboardSource = button.dataset.sourcePill ?? "";
    document.querySelectorAll("[data-source-pill]").forEach((el) => {
      el.classList.toggle("active", el.dataset.sourcePill === state.dashboardSource);
    });
    fetchListings({ ...defaultFilters, source: state.dashboardSource, sort: "discount" }, 0);
  });
});

const scrollTopButton = document.querySelector("#scrollTopButton");
if (scrollTopButton) {
  scrollTopButton.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  const onScroll = () => {
    scrollTopButton.hidden = window.scrollY <= 400;
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

async function runScrapeMode(mode = "quick") {
  const sources = selectedSources();
  const modeLabel = mode === "full" ? "полное сканирование" : "быстрый сбор";
  statusEl.textContent = `Запускаем ${modeLabel}: ${sources.map(sourceLabel).join(", ")}...`;
  showProgress({ pages_scanned: 0, found_total: 0, new_total: 0, current_source: null, is_running: true });
  try {
    const response = await fetch("/api/admin/scrape/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: sources.join(","), mode }),
    });
    if (!response.ok) {
      throw new Error("scrape_failed");
    }
    startProgressPolling();
  } catch {
    hideProgress();
    statusEl.textContent = "Сбор не запустился";
  }
}

async function stopScrape() {
  const button = document.querySelector("#stopScanButton");
  if (button) {
    button.disabled = true;
    button.textContent = "■ Останавливаем...";
  }
  statusEl.textContent = "Останавливаем парсинг...";
  try {
    await fetch("/api/admin/scrape/stop", { method: "POST" });
  } catch {
    // безмолвно: следующий polling всё равно подтянет состояние
  }
}

function startProgressPolling() {
  stopProgressPolling();
  pollProgressOnce();
  progressPollTimer = setInterval(pollProgressOnce, 1500);
}

function stopProgressPolling() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer);
    progressPollTimer = null;
  }
}

async function pollProgressOnce() {
  try {
    const response = await fetch("/api/admin/scrape/progress");
    if (!response.ok) return;
    const state = await response.json();
    if (state.is_running) {
      showProgress(state);
      await fetchTasks();
    } else {
      hideProgress();
      stopProgressPolling();
      if (state.started_at) {
        const total = state.new_total ?? 0;
        statusEl.textContent = state.last_error
          ? `Ошибка сбора: ${state.last_error}`
          : `Готово: добавлено ${total}, страниц ${state.pages_scanned}`;
        await fetchListings(readFilters(), 0);
        await fetchTasks();
        await fetchDashboardStats();
      }
    }
  } catch {
    // не прерываем опрос: пробуем дальше
  }
}

function showProgress(state) {
  progressEl.hidden = false;
  progressPagesEl.textContent = formatNumber(state.pages_scanned ?? 0);
  progressFoundEl.textContent = formatNumber(state.found_total ?? 0);
  progressNewEl.textContent = formatNumber(state.new_total ?? 0);
  const id = state.task_id ? `Задача #${state.task_id}` : "Парсинг";
  const src = state.current_source ? ` · ${sourceLabel(state.current_source)}` : "";
  progressTitleEl.textContent = `${id}${src}`;
  progressMetaEl.textContent = state.started_at ? `Начало: ${formatDateTime(state.started_at)}` : "Начало: —";
  const stopButton = document.querySelector("#stopScanButton");
  if (stopButton) {
    if (state.stop_requested) {
      stopButton.disabled = true;
      stopButton.textContent = "■ Останавливаем...";
    } else {
      stopButton.disabled = false;
      stopButton.textContent = "■ Остановить";
    }
  }
}

function hideProgress() {
  progressEl.hidden = true;
  const stopButton = document.querySelector("#stopScanButton");
  if (stopButton) {
    stopButton.disabled = false;
    stopButton.textContent = "■ Остановить";
  }
}

function renderTaskList() {
  if (!taskListEl) return;
  if (!tasksState.length) {
    taskListEl.innerHTML = `<p class="task-empty">Задач пока нет. Запустите парсинг, чтобы увидеть историю.</p>`;
    return;
  }
  taskListEl.innerHTML = tasksState.map(taskCard).join("");
}

function taskCard(task) {
  const isRunning = task.status === "running";
  const statusClass = isRunning ? "running" : task.status === "success" ? "success" : "failed";
  const statusLabel = isRunning ? "Выполняется" : task.status === "success" ? "Готово" : task.status === "stopped" ? "Остановлено" : "Ошибка";
  const spinner = isRunning ? `<span class="task-spinner"></span>` : "";
  const meta = task.finished_at && !isRunning
    ? `Готово: ${formatDateTime(task.finished_at)}`
    : `Начало: ${formatDateTime(task.started_at)}`;
  const trigger = task.trigger === "auto" ? "auto" : "manual";
  const triggerLabel = trigger === "auto" ? "АВТО" : "Вручную";
  return `
    <div class="task-card${isRunning ? " task-card-active" : ""}">
      <div class="task-card-main">
        <div class="task-card-title">
          <strong>Задача #${task.id}</strong>
          <span class="task-trigger ${trigger}">${triggerLabel}</span>
          <span class="task-status ${statusClass}">${spinner}${escapeHtml(statusLabel)}</span>
        </div>
        <div class="task-card-meta"><span>◷</span><span>${escapeHtml(meta)}</span></div>
      </div>
      <div class="task-card-stats">
        <div><b>${formatNumber(task.pages_scanned)}</b><span>страниц</span></div>
        <div><b>${formatNumber(task.found_count)}</b><span>найдено</span></div>
        <div><b class="accent">${formatNumber(task.new_count)}</b><span>новых</span></div>
      </div>
    </div>
  `;
}

function formatNumber(value) {
  return new Intl.NumberFormat("ru-RU").format(Number(value ?? 0));
}

function formatDateTime(value) {
  if (!value) return "—";
  const normalized = typeof value === "string" && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "—";
  const d = String(date.getDate()).padStart(2, "0");
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const y = String(date.getFullYear()).slice(2);
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${d}.${m}.${y}, ${h}:${min}`;
}

async function fetchListings(filters = readFilters(), page = 0) {
  setBusy(true, "Загружаем объявления...");
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(page * PAGE_SIZE));
  try {
    const response = await fetch(`/api/listings?${params.toString()}`);
    const payload = await response.json();
    state.listings = payload.items ?? [];
    state.total = payload.total ?? state.listings.length;
    state.page = page;
    state.selectedId = state.listings.find((item) => item.id === state.selectedId)?.id ?? state.listings[0]?.id ?? null;
    renderAll();
    setBusy(false, `Найдено: ${state.total}`);
  } catch {
    setBusy(false, "API недоступен");
  }
}

function goToPage(nextPage) {
  fetchListings(readFilters(), nextPage);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function fetchRuns() {
  try {
    const response = await fetch("/api/admin/scrape/runs");
    state.runs = await response.json();
  } catch {
    state.runs = [];
  }
  renderRuns();
}

async function fetchTasks() {
  try {
    const response = await fetch("/api/admin/scrape/tasks");
    tasksState = await response.json();
  } catch {
    tasksState = [];
  }
  renderTaskList();
}

async function fetchDashboardStats() {
  try {
    const response = await fetch("/api/listings/stats");
    if (!response.ok) return;
    state.stats = await response.json();
    renderStats();
    renderDistrictOptions();
  } catch {
    // оставляем прежние значения
  }
}

async function fetchSourceStats() {
  const sources = selectedSources();
  setBusy(true, `Считаем страницы: ${sources.map(sourceLabel).join(", ")}...`);
  try {
    const params = new URLSearchParams({ source: sources.join(",") });
    const response = await fetch(`/api/admin/scrape/sources?${params.toString()}`);
    state.sourceStats = await response.json();
    renderSourceStats();
    setBusy(false, "Страницы посчитаны");
  } catch {
    state.sourceStats = [];
    renderSourceStats();
    setBusy(false, "Не удалось посчитать страницы");
  }
}

function renderAll() {
  renderDistrictOptions();
  renderStats();
  renderDashboardList();
  renderListingsList();
  renderInsight();
  renderRuns();
  renderListingsTotal();
  renderPagination();
}

function renderListingsTotal() {
  const total = state.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : state.page * PAGE_SIZE + 1;
  const to = Math.min(total, (state.page + 1) * PAGE_SIZE);
  const el = document.querySelector("#listingsTotal");
  if (!el) return;
  el.textContent = `${total.toLocaleString()} объектов · показаны ${from.toLocaleString()}–${to.toLocaleString()} (стр. ${state.page + 1} из ${totalPages})`;
}

function renderPagination() {
  const container = document.querySelector("#listingsPagination");
  if (!container) return;
  const total = state.total ?? 0;
  if (total <= PAGE_SIZE) {
    container.innerHTML = "";
    return;
  }
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const prevDisabled = state.page <= 0 ? "disabled" : "";
  const nextDisabled = state.page >= totalPages - 1 ? "disabled" : "";
  container.innerHTML = `
    <button type="button" class="ghost-button" data-page-prev ${prevDisabled}>← Назад</button>
    <span class="pagination-info">Стр. ${state.page + 1} из ${totalPages}</span>
    <button type="button" class="ghost-button" data-page-next ${nextDisabled}>Вперёд →</button>
  `;
  const prev = container.querySelector("[data-page-prev]");
  const next = container.querySelector("[data-page-next]");
  if (prev) prev.addEventListener("click", () => goToPage(state.page - 1));
  if (next) next.addEventListener("click", () => goToPage(state.page + 1));
}

function renderStats() {
  const stats = state.stats || {};
  document.querySelector("#statTotal").textContent = formatNumber(stats.total ?? state.total ?? state.listings.length);
  document.querySelector("#statHot").textContent = formatNumber(stats.hot ?? state.listings.filter(isHotDeal).length);
  document.querySelector("#statNew").textContent = formatNumber(stats.new_today ?? 0);
  const sources = stats.sources ?? [];
  ["olx", "uybor", "realt24"].forEach((source) => {
    const el = document.querySelector(`[data-source-count="${source}"]`);
    if (!el) return;
    const entry = sources.find((item) => item.source === source);
    el.textContent = formatNumber(entry?.total ?? 0);
  });
}

function renderDashboardList() {
  const bestDeals = [...state.listings]
    .filter((item) => item.market?.discount_percent != null)
    .sort((a, b) => (b.market?.discount_percent ?? -999) - (a.market?.discount_percent ?? -999))
    .slice(0, 6);
  dashboardList.innerHTML = bestDeals.length
    ? bestDeals.map((listing, index) => listingCard(listing, index + 1)).join("")
    : emptyState("Пока нет объявлений", "Запустите сбор или проверьте доступность API.");
  bindCards(dashboardList);
}

function renderListingsList() {
  listingsList.innerHTML = state.listings.length
    ? state.listings.map((listing, index) => listingCard(listing, index + 1)).join("")
    : emptyState("Ничего не найдено", "Попробуйте сбросить фильтры или запустить сбор объявлений.");
  bindCards(listingsList);
}

function renderInsight() {
  const listing = state.listings.find((item) => item.id === state.selectedId);
  if (!listing) {
    insightPanel.innerHTML = `<div class="section-title">↓ <span>Рыночный ориентир</span></div><p class="muted-text">Выберите объявление, чтобы увидеть детали оценки.</p>`;
    return;
  }
  insightPanel.innerHTML = `
    <div class="section-title">↓ <span>Рыночный ориентир</span></div>
    <h3>${escapeHtml(listing.title)}</h3>
    <div class="large-price">$${money(listing.price_usd)}</div>
    <dl>
      <dt>Цена за м²</dt><dd>$${money(listing.price_per_m2_usd)}</dd>
      <dt>Рынок за м²</dt><dd>${listing.market?.market_price_per_m2_usd ? `$${money(listing.market.market_price_per_m2_usd)}` : "мало данных"}</dd>
      <dt>Дисконт</dt><dd>${listing.market?.discount_percent != null ? `${listing.market.discount_percent.toFixed(1)}%` : "нет"}</dd>
      <dt>Дубли</dt><dd>${listing.duplicate_count}</dd>
      <dt>Источник</dt><dd>${escapeHtml(sourceLabel(listing.source))}</dd>
    </dl>
    <a class="primary-link" href="${escapeAttr(listing.url)}" target="_blank" rel="noreferrer">Смотреть оригинал</a>
  `;
}

function renderRuns() {
  if (!runList) return;
  runList.innerHTML = state.runs.length
    ? state.runs.map((run) => `
      <div class="run-row">
        <div><strong>${escapeHtml(run.source.toUpperCase())}</strong><span>${formatDate(run.started_at)}</span></div>
        <div><span class="${run.status === "success" ? "chip success" : "chip"}">${escapeHtml(run.status)}</span><small>+${run.new_count} / обновлено ${run.updated_count}</small></div>
      </div>
    `).join("")
    : `<p class="muted-text">История сборов пока пуста.</p>`;
}

function renderSourceStats() {
  sourceStatsEl.innerHTML = state.sourceStats.length
    ? state.sourceStats.map((item) => {
        const pages = item.total_pages ? `${item.total_pages.toLocaleString()} стр.` : "неизвестно";
        const total = item.total_listings ? `~${item.total_listings.toLocaleString()} объявл.` : item.total_pages && item.page_size ? `~${(item.total_pages * item.page_size).toLocaleString()} объявл.` : "";
        return `
          <div class="source-row">
            <div><strong>${sourceLabel(item.source)}</strong><span>${item.error ? escapeHtml(item.error) : escapeHtml(total || "страницы найдены")}</span></div>
            <b>${item.error ? "ошибка" : pages}</b>
          </div>
        `;
      }).join("")
    : `<p class="muted-text">Нажмите «Посчитать страницы», чтобы получить текущий объём площадок.</p>`;
}

function renderDistrictOptions() {
  const select = document.querySelector("#district");
  const current = select.value;
  const fromStats = state.stats?.districts ?? [];
  const fromListings = state.listings.map((item) => item.district).filter(Boolean);
  const districts = [...new Set([...fromStats, ...fromListings])].sort();
  select.innerHTML = `<option value="">Все районы</option>${districts.map((district) => `<option value="${escapeAttr(district)}">${escapeHtml(district)}</option>`).join("")}`;
  select.value = districts.includes(current) ? current : "";
}

function listingCard(listing, rank) {
  const photo = listing.photos?.[0] ?? "";
  const discount = listing.market?.discount_percent;
  const selected = state.selectedId === listing.id ? " selected" : "";
  const favorite = state.favorites.includes(listing.id) ? " active" : "";
  return `
    <article class="listing-card${selected}" data-id="${listing.id}">
      <div class="listing-media">${photo ? `<img src="${escapeAttr(photo)}" alt="${escapeAttr(listing.title)}" loading="lazy" />` : "▦"}</div>
      <div class="listing-body">
        <div class="chips">
          <span class="rank">${rank}</span>
          ${isHotDeal(listing) ? `<span class="chip danger">-${discount.toFixed(1)}%</span>` : ""}
          <span class="chip">${listing.rooms}-комн.</span>
          <span class="chip muted">Источник: ${escapeHtml(sourceLabel(listing.source))}</span>
          ${listing.seller_type ? `<span class="chip muted">${escapeHtml(sellerLabel(listing.seller_type))}</span>` : ""}
        </div>
        <h3>${escapeHtml(listing.title)}</h3>
        <p class="listing-subtitle">${escapeHtml(listing.address_raw || listing.district)}</p>
        <div class="listing-facts">
          <span>⌖ ${escapeHtml(listing.district)}</span>
          <span>□ ${listing.area_m2} м²</span>
          <span>↓ $${money(listing.price_per_m2_usd)}/м²</span>
          <span>◷ ${formatDate(listing.seen_at)}</span>
        </div>
        <div class="listing-bottom">
          <div><strong>$${money(listing.price_usd)}</strong><span>рынок: ${listing.market?.market_price_per_m2_usd ? `$${money(listing.market.market_price_per_m2_usd)}/м²` : "мало данных"}</span></div>
          <div class="row-actions">
            <button class="icon-button favorite${favorite}" data-favorite="${listing.id}" title="Избранное" type="button">♡</button>
            <button class="outline-link" data-cma="${listing.id}" title="Сравнительный анализ" type="button">▤ Найти аналоги</button>
            <a class="outline-link" href="${escapeAttr(listing.url)}" target="_blank" rel="noreferrer">↗ Смотреть оригинал</a>
          </div>
        </div>
      </div>
    </article>
  `;
}

function bindCards(root) {
  root.querySelectorAll(".listing-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedId = Number(card.dataset.id);
      renderDashboardList();
      renderListingsList();
      renderInsight();
    });
  });
  root.querySelectorAll("[data-favorite]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFavorite(Number(button.dataset.favorite));
    });
  });
  root.querySelectorAll("[data-cma]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openCma(Number(button.dataset.cma));
    });
  });
  // Hotlinked photos from the source platforms can 403/404 (hotlink
  // protection, expired URLs) — degrade gracefully to the ▦ placeholder
  // instead of leaving a blank/broken image.
  root.querySelectorAll(".listing-media img").forEach((img) => {
    const fallback = () => {
      const media = img.closest(".listing-media");
      if (media) media.textContent = "▦";
    };
    if (img.complete && img.naturalWidth === 0) {
      fallback();
    } else {
      img.addEventListener("error", fallback, { once: true });
    }
  });
}

async function openCma(listingId) {
  const listing = state.listings.find((item) => item.id === listingId);
  showCmaModal(listing);
  try {
    const response = await fetch(`/api/cma/${listingId}`);
    if (!response.ok) throw new Error("cma_failed");
    const result = await response.json();
    renderCmaBody(result);
  } catch {
    renderCmaError("Не удалось загрузить аналоги");
  }
}

function showCmaModal(listing) {
  let overlay = document.querySelector("#cmaOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "cmaOverlay";
    overlay.className = "cma-overlay";
    overlay.innerHTML = `
      <div class="cma-modal" id="cmaModal">
        <header class="cma-header">
          <div>
            <h2>Сравнительный анализ</h2>
            <p id="cmaSubjectTitle"></p>
          </div>
          <div class="cma-header-actions">
            <button class="ghost-button" id="cmaPrintButton" type="button" disabled>▤ PDF / Печать</button>
            <button class="icon-button" id="cmaCloseButton" type="button" aria-label="Закрыть">×</button>
          </div>
        </header>
        <div class="cma-body" id="cmaBody"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closeCma();
    });
    overlay.querySelector("#cmaCloseButton").addEventListener("click", closeCma);
    overlay.querySelector("#cmaPrintButton").addEventListener("click", () => window.print());
  }
  overlay.querySelector("#cmaSubjectTitle").textContent = listing?.title ?? "";
  overlay.querySelector("#cmaBody").innerHTML = `<div class="cma-loading">⟳ Подбираем аналоги...</div>`;
  overlay.querySelector("#cmaPrintButton").disabled = true;
  overlay.classList.add("active");
}

function closeCma() {
  const overlay = document.querySelector("#cmaOverlay");
  if (overlay) overlay.classList.remove("active");
}

function renderCmaError(message) {
  const body = document.querySelector("#cmaBody");
  if (body) body.innerHTML = `<div class="cma-error">${escapeHtml(message)}</div>`;
}

function renderCmaBody(result) {
  const body = document.querySelector("#cmaBody");
  if (!body) return;
  const printButton = document.querySelector("#cmaPrintButton");
  if (printButton) printButton.disabled = false;

  const { subject, stats, analogs, basis_label, subject_vs_market_percent } = result;
  const verdict = makeCmaVerdict(subject_vs_market_percent);

  const summaryRows = [
    ["База сравнения", escapeHtml(basis_label)],
    ["Найдено аналогов", formatNumber(stats.count)],
    ["Этот объект", `$${money(subject.price_usd)} · $${money(subject.price_per_m2_usd)}/м² · ${subject.area_m2} м²`],
  ];
  if (stats.median_price_per_m2_usd) summaryRows.push(["Медиана по рынку", `$${money(stats.median_price_per_m2_usd)}/м²`]);
  if (stats.avg_price_per_m2_usd) summaryRows.push(["Среднее по рынку", `$${money(stats.avg_price_per_m2_usd)}/м²`]);
  if (stats.min_price_per_m2_usd && stats.max_price_per_m2_usd) {
    summaryRows.push(["Диапазон $/м²", `$${money(stats.min_price_per_m2_usd)} – $${money(stats.max_price_per_m2_usd)}`]);
  }

  const summaryHtml = summaryRows
    .map(([label, value]) => `<div class="cma-summary-row"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");

  const verdictHtml = verdict
    ? `<div class="cma-verdict ${verdict.kind}"><strong>${escapeHtml(verdict.title)}</strong><span>${escapeHtml(verdict.body)}</span></div>`
    : "";

  const chartHtml = analogs.length ? cmaChart(subject, analogs, stats.median_price_per_m2_usd) : "";
  const tableHtml = analogs.length ? cmaTable(subject, analogs) : "";
  const emptyHtml = analogs.length
    ? ""
    : `<div class="cma-empty">В базе нет похожих объявлений по этим параметрам. Расширьте сбор данных или попробуйте позже.</div>`;

  body.innerHTML = `
    <section class="cma-summary">${summaryHtml}${verdictHtml}</section>
    ${chartHtml}
    ${tableHtml}
    ${emptyHtml}
  `;
}

function cmaChart(subject, analogs, median) {
  const points = [
    { id: subject.id, ppm: subject.price_per_m2_usd, isSubject: true },
    ...analogs.map((a) => ({ id: a.id, ppm: a.price_per_m2_usd, isSubject: false })),
  ];
  const max = Math.max(...points.map((p) => p.ppm)) * 1.05;
  const min = Math.min(...points.map((p) => p.ppm)) * 0.95;
  const range = (max - min) || 1;
  const barWidth = 100 / points.length;
  const medianLine = median
    ? `<line x1="0" x2="100" y1="${50 - ((median - min) / range) * 50}" y2="${50 - ((median - min) / range) * 50}" stroke="#2563eb" stroke-dasharray="0.6,0.6" stroke-width="0.3" />`
    : "";
  const bars = points
    .map((p, index) => {
      const height = ((p.ppm - min) / range) * 50;
      const x = index * barWidth + barWidth * 0.15;
      const w = barWidth * 0.7;
      const y = 50 - height;
      const fill = p.isSubject ? "#dc2626" : "#94a3b8";
      return `<rect x="${x}" y="${y}" width="${w}" height="${height}" fill="${fill}" />`;
    })
    .join("");
  const medianLegend = median ? `<span><i style="background:#2563eb"></i> медиана $${money(median)}/м²</span>` : "";
  return `
    <section class="cma-chart">
      <h3>$/м² — этот объект vs аналоги</h3>
      <div class="cma-chart-frame">
        <svg viewBox="0 0 100 50" preserveAspectRatio="none" class="cma-chart-svg">${medianLine}${bars}</svg>
        <div class="cma-chart-legend">
          <span><i style="background:#dc2626"></i> этот объект</span>
          <span><i style="background:#94a3b8"></i> аналоги</span>
          ${medianLegend}
        </div>
      </div>
    </section>
  `;
}

function cmaTable(subject, analogs) {
  const rows = analogs
    .map((a) => {
      const diff = ((subject.price_per_m2_usd / a.price_per_m2_usd - 1) * 100);
      const positive = diff > 0;
      return `
        <tr>
          <td>${escapeHtml(sourceLabel(a.source))}</td>
          <td>${escapeHtml(a.address_raw || "—")}</td>
          <td>${a.area_m2} м²</td>
          <td>${a.floor ?? "—"}</td>
          <td>$${money(a.price_usd)}</td>
          <td>$${money(a.price_per_m2_usd)}</td>
          <td class="${positive ? "diff-pos" : "diff-neg"}">${positive ? "+" : ""}${diff.toFixed(1)}%</td>
          <td><a class="outline-link cma-table-link" href="${escapeAttr(a.url)}" target="_blank" rel="noreferrer">↗</a></td>
        </tr>
      `;
    })
    .join("");
  return `
    <section class="cma-table-wrap">
      <h3>Аналоги (${analogs.length})</h3>
      <table class="cma-table">
        <thead><tr><th>Источник</th><th>Адрес</th><th>Площадь</th><th>Этаж</th><th>Цена</th><th>$/м²</th><th>vs объект</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>
  `;
}

function makeCmaVerdict(diff) {
  if (diff === null || diff === undefined) return null;
  if (diff <= -10) {
    return { kind: "good", title: `Хорошая цена: на ${Math.abs(diff).toFixed(1)}% ниже рынка`, body: "Можно смело предлагать клиенту — объект интересный." };
  }
  if (diff >= 10) {
    return { kind: "bad", title: `Дорого: на ${diff.toFixed(1)}% выше рынка`, body: "Аргумент для торга — покажите медиану по аналогам." };
  }
  return { kind: "neutral", title: `Цена в рынке: отклонение ${diff > 0 ? "+" : ""}${diff.toFixed(1)}%`, body: "Объект продаётся по средней цене для этого сегмента." };
}

function toggleFavorite(id) {
  state.favorites = state.favorites.includes(id) ? state.favorites.filter((item) => item !== id) : [...state.favorites, id];
  window.localStorage.setItem("tashkent-value-flats:favorites", JSON.stringify(state.favorites));
  renderDashboardList();
  renderListingsList();
}

function readFilters() {
  return Object.fromEntries(filterIds.map((id) => [id, document.querySelector(`#${id}`).value]));
}

function writeFilters(filters) {
  filterIds.forEach((id) => {
    document.querySelector(`#${id}`).value = filters[id] ?? "";
  });
}

function resetFilters() {
  writeFilters(defaultFilters);
  fetchListings(defaultFilters, 0);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === `${view}View`));
  document.querySelectorAll("[data-view-button]").forEach((button) => button.classList.toggle("active", button.dataset.viewButton === view));
  if (view === "admin" && !state.sourceStats.length) {
    renderSourceStats();
  }
}

function setBusy(isBusy, message) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.id === "stopScanButton") return;
    button.disabled = isBusy;
  });
  statusEl.classList.toggle("loading", isBusy);
  if (message) statusEl.textContent = message;
}

function isHotDeal(listing) {
  return listing.market?.discount_percent != null && listing.market.discount_percent >= 15;
}

function emptyState(title, body) {
  return `<div class="empty-state"><div>▦</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p></div>`;
}

function money(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value ?? 0);
}

function formatDate(value) {
  if (!value) return "нет даты";
  const normalized = typeof value === "string" && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "нет даты";
  const diffHours = (Date.now() - date.getTime()) / 3_600_000;
  if (diffHours < 1) return "только что";
  if (diffHours < 24) return `${Math.floor(diffHours)} ч. назад`;
  if (diffHours < 48) return "вчера";
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays} дн. назад`;
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function readFavorites() {
  try {
    return JSON.parse(window.localStorage.getItem("tashkent-value-flats:favorites") ?? "[]");
  } catch {
    return [];
  }
}

function selectedSources() {
  const sources = [...document.querySelectorAll("#sourcePicker input[type='checkbox']:checked")].map((input) => input.value);
  return sources.length ? sources : ["olx", "uybor", "realt24"];
}

function sourceLabel(source) {
  return { olx: "OLX", uybor: "Uybor", realt24: "Realt24" }[source] ?? source.toUpperCase();
}

function sellerLabel(value) {
  const key = String(value ?? "").trim().toLowerCase();
  return { owner: "Хозяин", private: "Хозяин", agency: "Агентство", agent: "Агентство" }[key] ?? value;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

writeFilters(defaultFilters);
fetchListings(defaultFilters);
fetchDashboardStats();
fetchRuns();
fetchTasks();
renderSourceStats();
resumeProgressIfRunning();

async function resumeProgressIfRunning() {
  try {
    const response = await fetch("/api/admin/scrape/progress");
    if (!response.ok) return;
    const state = await response.json();
    if (state.is_running) {
      showProgress(state);
      startProgressPolling();
    }
  } catch {
    // ничего
  }
}
