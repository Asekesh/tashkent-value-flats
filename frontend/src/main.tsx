import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowDownUp, Database, ExternalLink, RefreshCcw, Search, SlidersHorizontal } from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type MarketEstimate = {
  market_price_per_m2_usd: number | null;
  sample_size: number;
  basis: string;
  confidence: string;
  discount_percent: number | null;
  is_below_market: boolean;
};

type Listing = {
  id: number;
  source: string;
  source_id: string;
  url: string;
  title: string;
  price: number;
  currency: string;
  price_usd: number;
  area_m2: number;
  price_per_m2_usd: number;
  rooms: number;
  floor: number | null;
  total_floors: number | null;
  district: string;
  address_raw: string;
  building_key: string | null;
  description: string | null;
  seller_type: string | null;
  duplicate_count: number;
  source_urls: Array<{ source: string; url: string }>;
  market: MarketEstimate | null;
};

type Filters = {
  district: string;
  rooms: string;
  area_min: string;
  area_max: string;
  price_min: string;
  price_max: string;
  ppm_min: string;
  ppm_max: string;
  discount_min: string;
  source: string;
  sort: string;
};

const defaultFilters: Filters = {
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
  sort: "fresh",
};

function App() {
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [listings, setListings] = useState<Listing[]>([]);
  const [selected, setSelected] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("Готово");

  const districts = useMemo(() => Array.from(new Set(listings.map((item) => item.district))).sort(), [listings]);

  async function fetchListings(nextFilters = filters) {
    setLoading(true);
    const params = new URLSearchParams();
    Object.entries(nextFilters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const response = await fetch(`${API_BASE_URL}/api/listings?${params.toString()}`);
    const payload = await response.json();
    setListings(payload.items);
    setSelected((current) => current ?? payload.items[0] ?? null);
    setStatus(`Найдено: ${payload.total}`);
    setLoading(false);
  }

  async function importFixtures() {
    setLoading(true);
    setStatus("Импортируем объявления...");
    await fetch(`${API_BASE_URL}/api/admin/scrape/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "all" }),
    });
    await fetchListings();
  }

  useEffect(() => {
    fetchListings().catch(() => {
      setStatus("API недоступен");
      setLoading(false);
    });
  }, []);

  function updateFilter(key: keyof Filters, value: string) {
    const next = { ...filters, [key]: value };
    setFilters(next);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Tashkent Value Flats</h1>
          <p>Квартиры в Ташкенте с расчётом цены за м² и отклонения от рынка</p>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" onClick={() => fetchListings()} disabled={loading} title="Обновить список">
            <RefreshCcw size={18} />
          </button>
          <button className="primary-button" onClick={importFixtures} disabled={loading}>
            <Database size={18} />
            Импорт fixtures
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="filters">
          <div className="panel-heading">
            <SlidersHorizontal size={18} />
            <span>Фильтры</span>
          </div>
          <label>
            Район
            <select value={filters.district} onChange={(event) => updateFilter("district", event.target.value)}>
              <option value="">Все районы</option>
              {districts.map((district) => (
                <option key={district}>{district}</option>
              ))}
            </select>
          </label>
          <label>
            Комнаты
            <select value={filters.rooms} onChange={(event) => updateFilter("rooms", event.target.value)}>
              <option value="">Любая</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5+</option>
            </select>
          </label>
          <RangeInputs label="Площадь, м²" minKey="area_min" maxKey="area_max" filters={filters} updateFilter={updateFilter} />
          <RangeInputs label="Цена, $" minKey="price_min" maxKey="price_max" filters={filters} updateFilter={updateFilter} />
          <RangeInputs label="$/м²" minKey="ppm_min" maxKey="ppm_max" filters={filters} updateFilter={updateFilter} />
          <label>
            Ниже рынка, %
            <input value={filters.discount_min} onChange={(event) => updateFilter("discount_min", event.target.value)} />
          </label>
          <label>
            Источник
            <select value={filters.source} onChange={(event) => updateFilter("source", event.target.value)}>
              <option value="">Все</option>
              <option value="olx">OLX</option>
              <option value="uybor">Uybor</option>
              <option value="realt24">Realt24</option>
            </select>
          </label>
          <label>
            Сортировка
            <select value={filters.sort} onChange={(event) => updateFilter("sort", event.target.value)}>
              <option value="discount">Ниже рынка</option>
              <option value="price_per_m2">Цена за м²</option>
              <option value="fresh">Свежие</option>
              <option value="price">Цена</option>
            </select>
          </label>
          <button className="primary-button full" onClick={() => fetchListings()} disabled={loading}>
            <Search size={18} />
            Применить
          </button>
        </aside>

        <section className="results">
          <div className="result-toolbar">
            <div>{status}</div>
            <div className="sort-label">
              <ArrowDownUp size={16} />
              {filters.sort}
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Объявление</th>
                  <th>Район</th>
                  <th>Комн.</th>
                  <th>м²</th>
                  <th>Цена</th>
                  <th>$/м²</th>
                  <th>Рынок</th>
                  <th>Дисконт</th>
                </tr>
              </thead>
              <tbody>
                {listings.map((listing) => (
                  <tr key={listing.id} className={selected?.id === listing.id ? "selected" : ""} onClick={() => setSelected(listing)}>
                    <td>
                      <strong>{listing.title}</strong>
                      <span>{listing.source.toUpperCase()} · дублей {listing.duplicate_count}</span>
                    </td>
                    <td>{listing.district}</td>
                    <td>{listing.rooms}</td>
                    <td>{listing.area_m2}</td>
                    <td>${money(listing.price_usd)}</td>
                    <td>${money(listing.price_per_m2_usd)}</td>
                    <td>{listing.market?.market_price_per_m2_usd ? `$${money(listing.market.market_price_per_m2_usd)}` : "мало данных"}</td>
                    <td>
                      <Badge estimate={listing.market} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <DetailPanel listing={selected} />
      </section>
    </main>
  );
}

function RangeInputs({
  label,
  minKey,
  maxKey,
  filters,
  updateFilter,
}: {
  label: string;
  minKey: keyof Filters;
  maxKey: keyof Filters;
  filters: Filters;
  updateFilter: (key: keyof Filters, value: string) => void;
}) {
  return (
    <div className="range-group">
      <span>{label}</span>
      <div>
        <input placeholder="от" value={filters[minKey]} onChange={(event) => updateFilter(minKey, event.target.value)} />
        <input placeholder="до" value={filters[maxKey]} onChange={(event) => updateFilter(maxKey, event.target.value)} />
      </div>
    </div>
  );
}

function Badge({ estimate }: { estimate: MarketEstimate | null }) {
  if (!estimate || estimate.discount_percent === null) return <span className="badge muted">нет</span>;
  const className = estimate.is_below_market ? "badge good" : "badge";
  return <span className={className}>{estimate.discount_percent.toFixed(1)}%</span>;
}

function DetailPanel({ listing }: { listing: Listing | null }) {
  if (!listing) {
    return <aside className="detail empty">Нет выбранного объявления</aside>;
  }
  const market = listing.market;
  return (
    <aside className="detail">
      <h2>{listing.title}</h2>
      <div className="metric-grid">
        <Metric label="Цена" value={`$${money(listing.price_usd)}`} />
        <Metric label="Цена за м²" value={`$${money(listing.price_per_m2_usd)}`} />
        <Metric label="Рынок за м²" value={market?.market_price_per_m2_usd ? `$${money(market.market_price_per_m2_usd)}` : "мало данных"} />
        <Metric label="Ниже рынка" value={market && market.discount_percent !== null ? `${market.discount_percent.toFixed(1)}%` : "нет"} />
      </div>
      <dl>
        <dt>Адрес</dt>
        <dd>{listing.address_raw}</dd>
        <dt>Район</dt>
        <dd>{listing.district}</dd>
        <dt>Этаж</dt>
        <dd>{listing.floor && listing.total_floors ? `${listing.floor}/${listing.total_floors}` : "не указан"}</dd>
        <dt>Основа оценки</dt>
        <dd>{market ? `${basisLabel(market.basis)} · ${confidenceLabel(market.confidence)} · ${market.sample_size} объектов` : "нет оценки"}</dd>
      </dl>
      <p className="description">{listing.description}</p>
      <div className="source-list">
        {listing.source_urls.map((item) => (
          <a key={`${item.source}-${item.url}`} href={item.url} target="_blank" rel="noreferrer">
            {item.source.toUpperCase()}
            <ExternalLink size={14} />
          </a>
        ))}
      </div>
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function money(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function basisLabel(value: string) {
  return {
    building: "тот же дом",
    district_rooms_area: "район, комнаты, площадь",
    district_rooms: "район и комнаты",
    insufficient_data: "недостаточно данных",
  }[value] ?? value;
}

function confidenceLabel(value: string) {
  return {
    high: "высокая уверенность",
    medium: "средняя уверенность",
    low: "низкая уверенность",
  }[value] ?? value;
}

createRoot(document.getElementById("root")!).render(<App />);
