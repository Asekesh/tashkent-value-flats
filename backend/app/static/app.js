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

const state = {
  view: "dashboard",
  listings: [],
  selectedId: null,
  total: 0,
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
document.querySelector("#applyButton").addEventListener("click", () => fetchListings(readFilters()));
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
    fetchListings(readFilters());
  });
});
document.querySelector("[data-quick-discount]").addEventListener("click", () => {
  writeFilters({ ...defaultFilters, discount_min: "15", sort: "discount" });
  setView("listings");
  fetchListings(readFilters());
});
document.querySelector("[data-quick-ppm]").addEventListener("click", () => {
  writeFilters({ ...defaultFilters, sort: "price_per_m2" });
  setView("listings");
  fetchListings(readFilters());
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
    fetchListings(readFilters());
  });
});
document.querySelectorAll("[data-source-pill]").forEach((button) => {
  button.addEventListener("click", () => {
    state.dashboardSource = button.dataset.sourcePill ?? "";
    document.querySelectorAll("[data-source-pill]").forEach((el) => {
      el.classList.toggle("active", el.dataset.sourcePill === state.dashboardSource);
    });
    fetchListings({ ...defaultFilters, source: state.dashboardSource, sort: "discount" });
  });
});

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
        await fetchListings(readFilters());
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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const d = String(date.getDate()).padStart(2, "0");
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const y = String(date.getFullYear()).slice(2);
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${d}.${m}.${y}, ${h}:${min}`;
}

async function fetchListings(filters = readFilters()) {
  setBusy(true, "Загружаем объявления...");
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set("limit", "100");
  try {
    const response = await fetch(`/api/listings?${params.toString()}`);
    const payload = await response.json();
    state.listings = payload.items ?? [];
    state.total = payload.total ?? state.listings.length;
    state.selectedId = state.listings.find((item) => item.id === state.selectedId)?.id ?? state.listings[0]?.id ?? null;
    renderAll();
    setBusy(false, `Найдено: ${state.total}`);
  } catch {
    setBusy(false, "API недоступен");
  }
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
  document.querySelector("#listingsTotal").textContent = state.total.toLocaleString();
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
    </dl>
    <a class="primary-link" href="${escapeAttr(listing.url)}" target="_blank" rel="noreferrer">Открыть источник</a>
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
  const districts = [...new Set(state.listings.map((item) => item.district).filter(Boolean))].sort();
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
      <div class="listing-media">${photo ? `<img src="${escapeAttr(photo)}" alt="${escapeAttr(listing.title)}" />` : "▦"}</div>
      <div class="listing-body">
        <div class="chips">
          <span class="rank">${rank}</span>
          ${isHotDeal(listing) ? `<span class="chip danger">-${discount.toFixed(1)}%</span>` : ""}
          <span class="chip">${listing.rooms}-комн.</span>
          <span class="chip muted">${escapeHtml(listing.source.toUpperCase())}</span>
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
            <a class="outline-link" href="${escapeAttr(listing.url)}" target="_blank" rel="noreferrer">↗ Источник</a>
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
  fetchListings(defaultFilters);
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
  const date = new Date(value);
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
