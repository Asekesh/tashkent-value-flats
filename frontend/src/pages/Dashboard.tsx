import { ArrowRight, Building2, Sparkles, TrendingDown } from "lucide-react";
import type { ReactNode } from "react";
import { ListingCard } from "../components/ListingCard";
import type { DashboardStats, Filters, Listing } from "../types";
import { money, sourceLabel } from "../utils";

export function Dashboard({
  listings,
  total,
  stats,
  selected,
  favorites,
  dashboardSource,
  onSelect,
  onToggleFavorite,
  onViewListings,
  onQuickFilter,
  onSourceChange,
}: {
  listings: Listing[];
  total: number;
  stats: DashboardStats | null;
  selected: Listing | null;
  favorites: number[];
  dashboardSource: string;
  onSelect: (listing: Listing) => void;
  onToggleFavorite: (listing: Listing) => void;
  onViewListings: () => void;
  onQuickFilter: (filters: Partial<Filters>) => void;
  onSourceChange: (source: string) => void;
}) {
  const bestDeals = [...listings]
    .filter((listing) => listing.market?.discount_percent != null)
    .sort((a, b) => (b.market?.discount_percent ?? -999) - (a.market?.discount_percent ?? -999))
    .slice(0, 6);
  const sources = ["olx", "uybor", "realt24"];

  function statClick(kind: "all" | "hot" | "new-today") {
    if (kind === "hot") {
      onQuickFilter({ discount_min: "15", source: dashboardSource, sort: "discount" });
    } else if (kind === "new-today") {
      onQuickFilter({ discount_min: "15", source: dashboardSource, sort: "fresh" });
    } else {
      onQuickFilter({ source: dashboardSource, sort: "discount" });
    }
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>Лучшие по цене за м²</h2>
          <p>Квартиры со скидкой 15–99% от средней цены ЖК · самая низкая цена за м² в каждом ЖК</p>
        </div>
        <button className="ghost-button" onClick={onViewListings} type="button">
          Все объявления
          <ArrowRight size={16} />
        </button>
      </div>

      <section className="stats-grid stats-grid-3">
        <MetricCard label="Всего квартир" value={stats?.total ?? total ?? listings.length} icon={<Building2 size={20} />} tone="blue" onClick={() => statClick("all")} />
        <MetricCard label="Горячих скидок" value={stats?.hot ?? 0} icon={<TrendingDown size={20} />} tone="red" onClick={() => statClick("hot")} />
        <MetricCard label="Новых сегодня" hint="(скидка 15%+)" value={stats?.new_today ?? 0} icon={<Sparkles size={20} />} tone="green" onClick={() => statClick("new-today")} />
      </section>

      <section className="quick-filters">
        <span>Площадка</span>
        <button
          className={dashboardSource === "" ? "source-pill active" : "source-pill"}
          onClick={() => onSourceChange("")}
          type="button"
        >
          Все источники
        </button>
        {sources.map((source) => {
          const entry = stats?.sources.find((item) => item.source === source);
          return (
            <button
              key={source}
              className={dashboardSource === source ? "source-pill active" : "source-pill"}
              onClick={() => onSourceChange(source)}
              type="button"
            >
              {sourceLabel(source)} <small>{money(entry?.total ?? 0)}</small>
            </button>
          );
        })}
      </section>

      <section className="quick-filters">
        <span>Быстрый срез</span>
        {[1, 2, 3, 4].map((rooms) => (
          <button key={rooms} onClick={() => onQuickFilter({ rooms: String(rooms), source: dashboardSource, sort: "discount" })} type="button">
            {rooms}-комн.
          </button>
        ))}
        <button onClick={() => onQuickFilter({ discount_min: "15", source: dashboardSource, sort: "discount" })} type="button">
          скидка 15%+
        </button>
        <button onClick={() => onQuickFilter({ source: dashboardSource, sort: "price_per_m2" })} type="button">
          минимум $/м²
        </button>
      </section>

      <section className="content-grid">
        <div className="deal-list">
          <div className="section-title">
            <Sparkles size={17} />
            <span>Самые интересные варианты</span>
          </div>
          {bestDeals.length ? (
            bestDeals.map((listing, index) => (
              <ListingCard
                key={listing.id}
                listing={listing}
                rank={index + 1}
                selected={selected?.id === listing.id}
                favorite={favorites.includes(listing.id)}
                onSelect={onSelect}
                onToggleFavorite={onToggleFavorite}
              />
            ))
          ) : (
            <EmptyState />
          )}
        </div>

        <aside className="insight-panel">
          <div className="section-title">
            <TrendingDown size={17} />
            <span>Рыночный ориентир</span>
          </div>
          {selected ? (
            <>
              <h3>{selected.title}</h3>
              <div className="large-price">${money(selected.price_usd)}</div>
              <dl>
                <dt>Цена за м²</dt>
                <dd>${money(selected.price_per_m2_usd)}</dd>
                <dt>Рынок за м²</dt>
                <dd>{selected.market?.market_price_per_m2_usd ? `$${money(selected.market.market_price_per_m2_usd)}` : "мало данных"}</dd>
                <dt>Дисконт</dt>
                <dd>{selected.market?.discount_percent != null ? `${selected.market.discount_percent.toFixed(1)}%` : "нет"}</dd>
                <dt>Дубли</dt>
                <dd>{selected.duplicate_count}</dd>
              </dl>
              <a className="primary-link" href={selected.url} target="_blank" rel="noreferrer">
                Открыть источник
              </a>
            </>
          ) : (
            <p className="muted-text">Выберите объявление, чтобы увидеть детали оценки.</p>
          )}
        </aside>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  hint,
  value,
  icon,
  tone,
  onClick,
}: {
  label: string;
  hint?: string;
  value: string | number;
  icon: ReactNode;
  tone: string;
  onClick?: () => void;
}) {
  const display = typeof value === "number" ? money(value) : value;
  return (
    <button className="metric-card metric-card-button" onClick={onClick} type="button">
      <div>
        <span>
          {label}
          {hint ? <small> {hint}</small> : null}
        </span>
        <strong>{display}</strong>
      </div>
      <div className={`metric-icon ${tone}`}>{icon}</div>
    </button>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <Building2 size={34} />
      <h3>Пока нет объявлений</h3>
      <p>Запустите сбор или проверьте доступность API.</p>
    </div>
  );
}
