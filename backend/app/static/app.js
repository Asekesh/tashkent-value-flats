const state = {
  listings: [],
  selectedId: null,
};

const filterIds = ["district", "rooms", "area_min", "area_max", "price_min", "price_max", "ppm_min", "ppm_max", "discount_min", "source", "sort"];
const rows = document.querySelector("#rows");
const detail = document.querySelector("#detail");
const statusEl = document.querySelector("#status");
const sortLabel = document.querySelector("#sortLabel");

document.querySelector("#applyButton").addEventListener("click", () => fetchListings());
document.querySelector("#refreshButton").addEventListener("click", () => fetchListings());
document.querySelector("#importButton").addEventListener("click", importFixtures);

async function importFixtures() {
  setBusy(true, "Импортируем объявления...");
  await fetch("/api/admin/scrape/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "all" }),
  });
  await fetchListings();
}

async function fetchListings() {
  setBusy(true, "Загружаем...");
  const params = new URLSearchParams();
  for (const id of filterIds) {
    const value = document.querySelector(`#${id}`).value;
    if (value) params.set(id, value);
  }
  const response = await fetch(`/api/listings?${params.toString()}`);
  const payload = await response.json();
  state.listings = payload.items;
  state.selectedId = state.selectedId ?? payload.items[0]?.id ?? null;
  renderDistrictOptions();
  renderRows();
  renderDetail();
  statusEl.textContent = `Найдено: ${payload.total}`;
  sortLabel.textContent = document.querySelector("#sort").value;
  setBusy(false);
}

function renderDistrictOptions() {
  const select = document.querySelector("#district");
  const current = select.value;
  const districts = [...new Set(state.listings.map((item) => item.district))].sort();
  select.innerHTML = `<option value="">Все районы</option>${districts.map((district) => `<option value="${escapeAttr(district)}">${escapeHtml(district)}</option>`).join("")}`;
  select.value = districts.includes(current) ? current : "";
}

function renderRows() {
  rows.innerHTML = state.listings.map((listing) => {
    const market = listing.market?.market_price_per_m2_usd ? `$${money(listing.market.market_price_per_m2_usd)}` : "мало данных";
    const discount = listing.market?.discount_percent == null
      ? `<span class="badge muted">нет</span>`
      : `<span class="badge ${listing.market.is_below_market ? "good" : ""}">${listing.market.discount_percent.toFixed(1)}%</span>`;
    return `
      <tr data-id="${listing.id}" class="${state.selectedId === listing.id ? "selected" : ""}">
        <td><strong>${escapeHtml(listing.title)}</strong><span>${listing.source.toUpperCase()} · дублей ${listing.duplicate_count}</span></td>
        <td>${escapeHtml(listing.district)}</td>
        <td>${listing.rooms}</td>
        <td>${listing.area_m2}</td>
        <td>$${money(listing.price_usd)}</td>
        <td>$${money(listing.price_per_m2_usd)}</td>
        <td>${market}</td>
        <td>${discount}</td>
      </tr>
    `;
  }).join("");
  rows.querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedId = Number(row.dataset.id);
      renderRows();
      renderDetail();
    });
  });
}

function renderDetail() {
  const listing = state.listings.find((item) => item.id === state.selectedId);
  if (!listing) {
    detail.className = "detail empty";
    detail.textContent = "Выберите объявление";
    return;
  }
  detail.className = "detail";
  const market = listing.market;
  const discount = market?.discount_percent == null ? "нет" : `${market.discount_percent.toFixed(1)}%`;
  detail.innerHTML = `
    <h2>${escapeHtml(listing.title)}</h2>
    <div class="metric-grid">
      ${metric("Цена", `$${money(listing.price_usd)}`)}
      ${metric("Цена за м²", `$${money(listing.price_per_m2_usd)}`)}
      ${metric("Рынок за м²", market?.market_price_per_m2_usd ? `$${money(market.market_price_per_m2_usd)}` : "мало данных")}
      ${metric("Ниже рынка", discount)}
    </div>
    <dl>
      <dt>Адрес</dt><dd>${escapeHtml(listing.address_raw)}</dd>
      <dt>Район</dt><dd>${escapeHtml(listing.district)}</dd>
      <dt>Этаж</dt><dd>${listing.floor && listing.total_floors ? `${listing.floor}/${listing.total_floors}` : "не указан"}</dd>
      <dt>Оценка</dt><dd>${market ? `${basisLabel(market.basis)} · ${confidenceLabel(market.confidence)} · ${market.sample_size} объектов` : "нет оценки"}</dd>
    </dl>
    <p class="description">${escapeHtml(listing.description ?? "")}</p>
    <div class="source-list">
      ${listing.source_urls.map((item) => `<a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">${item.source.toUpperCase()} ↗</a>`).join("")}
    </div>
  `;
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function setBusy(isBusy, message) {
  document.querySelectorAll("button").forEach((button) => { button.disabled = isBusy; });
  if (message) statusEl.textContent = message;
}

function money(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function basisLabel(value) {
  return {
    building: "тот же дом",
    district_rooms_area: "район, комнаты, площадь",
    district_rooms: "район и комнаты",
    insufficient_data: "недостаточно данных",
  }[value] ?? value;
}

function confidenceLabel(value) {
  return {
    high: "высокая уверенность",
    medium: "средняя уверенность",
    low: "низкая уверенность",
  }[value] ?? value;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

fetchListings().catch(() => {
  statusEl.textContent = "API недоступен";
  setBusy(false);
});

