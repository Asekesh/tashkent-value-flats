import { useEffect, useState, type ReactNode } from "react";
import { Calendar, Loader2, RotateCcw, TrendingDown, TrendingUp, X, XCircle } from "lucide-react";
import { fetchListingHistory } from "../api";
import type { Listing, ListingEvent, ListingHistory } from "../types";
import { formatDate, money } from "../utils";

export function HistoryModal({ listing, onClose }: { listing: Listing; onClose: () => void }) {
  const [data, setData] = useState<ListingHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchListingHistory(listing.id)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setError("Не удалось загрузить историю");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listing.id]);

  return (
    <div className="cma-overlay" onClick={onClose}>
      <div className="cma-modal" onClick={(event) => event.stopPropagation()}>
        <header className="cma-header">
          <div>
            <h2>История объявления</h2>
            <p>{listing.title}</p>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label="Закрыть">
            <X size={16} />
          </button>
        </header>

        {loading && (
          <div className="cma-loading">
            <Loader2 size={20} className="spin" />
            Загружаем историю...
          </div>
        )}

        {error && <div className="cma-error">{error}</div>}

        {data && <HistoryBody data={data} />}
      </div>
    </div>
  );
}

function HistoryBody({ data }: { data: ListingHistory }) {
  const { summary, events } = data;
  const change = summary.total_price_change_percent;
  const verdict = makeVerdict(summary);

  return (
    <div className="cma-body">
      <section className="cma-summary">
        {summary.first_seen_at && (
          <div className="cma-summary-row">
            <span>Впервые увидели</span>
            <strong>{new Date(summary.first_seen_at).toLocaleDateString("ru-RU")}</strong>
          </div>
        )}
        {summary.first_price_usd !== null && (
          <div className="cma-summary-row">
            <span>Стартовая цена</span>
            <strong>${money(summary.first_price_usd)}</strong>
          </div>
        )}
        {summary.current_price_usd !== null && (
          <div className="cma-summary-row">
            <span>Текущая цена</span>
            <strong>${money(summary.current_price_usd)}</strong>
          </div>
        )}
        {change !== null && (
          <div className="cma-summary-row">
            <span>Изменение цены</span>
            <strong className={change < 0 ? "diff-neg" : change > 0 ? "diff-pos" : ""}>
              {change > 0 ? "+" : ""}
              {change.toFixed(1)}%
            </strong>
          </div>
        )}
        <div className="cma-summary-row">
          <span>Изменений цены</span>
          <strong>{summary.price_change_count}</strong>
        </div>
        <div className="cma-summary-row">
          <span>Перевыставлений</span>
          <strong>{summary.relisted_count}</strong>
        </div>
        {verdict && (
          <div className={`cma-verdict ${verdict.kind}`}>
            <strong>{verdict.title}</strong>
            <span>{verdict.body}</span>
          </div>
        )}
      </section>

      {events.length === 0 ? (
        <div className="cma-empty">Событий по объявлению ещё нет.</div>
      ) : (
        <section className="history-timeline">
          {events.map((event) => (
            <TimelineRow key={event.id} event={event} />
          ))}
        </section>
      )}
    </div>
  );
}

function TimelineRow({ event }: { event: ListingEvent }) {
  const meta = describeEvent(event);
  return (
    <div className={`history-row ${meta.kind}`}>
      <div className="history-icon">{meta.icon}</div>
      <div className="history-content">
        <div className="history-title">{meta.title}</div>
        {meta.detail && <div className="history-detail">{meta.detail}</div>}
        {event.note && <div className="history-note">{event.note}</div>}
        <div className="history-date">{formatDate(event.at)}</div>
      </div>
    </div>
  );
}

function describeEvent(event: ListingEvent): { title: string; detail?: string; kind: string; icon: ReactNode } {
  switch (event.event_type) {
    case "first_seen":
      return {
        title: "Впервые появилось",
        detail: event.new_price_usd ? `Стартовая цена: $${money(event.new_price_usd)}` : undefined,
        kind: "neutral",
        icon: <Calendar size={14} />,
      };
    case "price_changed": {
      const drop = (event.old_price_usd ?? 0) > (event.new_price_usd ?? 0);
      const diff = event.old_price_usd && event.old_price_usd > 0 && event.new_price_usd !== null
        ? ((event.new_price_usd - event.old_price_usd) / event.old_price_usd) * 100
        : null;
      return {
        title: drop ? "Цена снижена" : "Цена повышена",
        detail: `$${money(event.old_price_usd)} → $${money(event.new_price_usd)}${diff !== null ? ` (${diff > 0 ? "+" : ""}${diff.toFixed(1)}%)` : ""}`,
        kind: drop ? "good" : "bad",
        icon: drop ? <TrendingDown size={14} /> : <TrendingUp size={14} />,
      };
    }
    case "relisted":
      return {
        title: "Перевыставлено",
        kind: "warn",
        icon: <RotateCcw size={14} />,
      };
    case "delisted":
      return {
        title: "Снято с продажи",
        kind: "muted",
        icon: <XCircle size={14} />,
      };
    default:
      return { title: event.event_type, kind: "neutral", icon: <Calendar size={14} /> };
  }
}

function makeVerdict(summary: ListingHistory["summary"]) {
  if (summary.relisted_count > 0 && summary.total_price_change_percent !== null && summary.total_price_change_percent <= -5) {
    return {
      kind: "good",
      title: "Продавец «прогрет»",
      body: `Объявление перевыставлялось ${summary.relisted_count} раз и подешевело на ${Math.abs(summary.total_price_change_percent).toFixed(1)}% — можно торговаться смелее.`,
    };
  }
  if (summary.relisted_count > 0) {
    return {
      kind: "warn",
      title: "Объявление перевыставлялось",
      body: "Продавец уже снимал и заново выставлял — это сигнал, что покупатели не идут по текущей цене.",
    };
  }
  if (summary.total_price_change_percent !== null && summary.total_price_change_percent <= -5) {
    return {
      kind: "good",
      title: "Цена идёт вниз",
      body: `За время наблюдения цена снизилась на ${Math.abs(summary.total_price_change_percent).toFixed(1)}% — продавец готов уступать.`,
    };
  }
  return null;
}
