import { useEffect, useState } from "react";
import { ExternalLink, FileText, Loader2, X } from "lucide-react";
import { fetchCma } from "../api";
import type { CmaResult, Listing } from "../types";
import { money, sourceLabel } from "../utils";

export function CmaModal({ listing, onClose }: { listing: Listing; onClose: () => void }) {
  const [result, setResult] = useState<CmaResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCma(listing.id)
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch(() => {
        if (!cancelled) setError("Не удалось загрузить аналоги");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listing.id]);

  function handlePrint() {
    window.print();
  }

  return (
    <div className="cma-overlay" onClick={onClose}>
      <div className="cma-modal" onClick={(event) => event.stopPropagation()}>
        <header className="cma-header">
          <div>
            <h2>Сравнительный анализ</h2>
            <p>{listing.title}</p>
          </div>
          <div className="cma-header-actions">
            <button className="ghost-button" onClick={handlePrint} type="button" disabled={!result}>
              <FileText size={14} />
              PDF / Печать
            </button>
            <button className="icon-button" onClick={onClose} type="button" aria-label="Закрыть">
              <X size={16} />
            </button>
          </div>
        </header>

        {loading && (
          <div className="cma-loading">
            <Loader2 size={20} className="spin" />
            Подбираем аналоги...
          </div>
        )}

        {error && <div className="cma-error">{error}</div>}

        {result && <CmaBody result={result} />}
      </div>
    </div>
  );
}

function CmaBody({ result }: { result: CmaResult }) {
  const { subject, stats, analogs, basis_label, subject_vs_market_percent } = result;
  const verdict = makeVerdict(subject_vs_market_percent);

  return (
    <div className="cma-body">
      <section className="cma-summary">
        <div className="cma-summary-row">
          <span>База сравнения</span>
          <strong>{basis_label}</strong>
        </div>
        <div className="cma-summary-row">
          <span>Найдено аналогов</span>
          <strong>{stats.count}</strong>
        </div>
        <div className="cma-summary-row">
          <span>Этот объект</span>
          <strong>
            ${money(subject.price_usd)} · ${money(subject.price_per_m2_usd)}/м² · {subject.area_m2} м²
          </strong>
        </div>
        {stats.median_price_per_m2_usd && (
          <div className="cma-summary-row">
            <span>Медиана по рынку</span>
            <strong>${money(stats.median_price_per_m2_usd)}/м²</strong>
          </div>
        )}
        {stats.avg_price_per_m2_usd && (
          <div className="cma-summary-row">
            <span>Среднее по рынку</span>
            <strong>${money(stats.avg_price_per_m2_usd)}/м²</strong>
          </div>
        )}
        {stats.min_price_per_m2_usd && stats.max_price_per_m2_usd && (
          <div className="cma-summary-row">
            <span>Диапазон $/м²</span>
            <strong>
              ${money(stats.min_price_per_m2_usd)} – ${money(stats.max_price_per_m2_usd)}
            </strong>
          </div>
        )}
        {verdict && (
          <div className={`cma-verdict ${verdict.kind}`}>
            <strong>{verdict.title}</strong>
            <span>{verdict.body}</span>
          </div>
        )}
      </section>

      {analogs.length > 0 && (
        <>
          <PriceChart subject={subject} analogs={analogs} median={stats.median_price_per_m2_usd} />
          <AnalogTable subject={subject} analogs={analogs} />
        </>
      )}

      {analogs.length === 0 && (
        <div className="cma-empty">
          В базе нет похожих объявлений по этим параметрам. Расширьте сбор данных или попробуйте позже.
        </div>
      )}
    </div>
  );
}

function PriceChart({
  subject,
  analogs,
  median,
}: {
  subject: { id: number; price_per_m2_usd: number };
  analogs: Array<{ id: number; price_per_m2_usd: number }>;
  median: number | null;
}) {
  const points = [
    { id: subject.id, ppm: subject.price_per_m2_usd, isSubject: true },
    ...analogs.map((a) => ({ id: a.id, ppm: a.price_per_m2_usd, isSubject: false })),
  ];
  const max = Math.max(...points.map((p) => p.ppm)) * 1.05;
  const min = Math.min(...points.map((p) => p.ppm)) * 0.95;
  const range = max - min || 1;
  const barWidth = 100 / points.length;

  return (
    <section className="cma-chart">
      <h3>$/м² — этот объект vs аналоги</h3>
      <div className="cma-chart-frame">
        <svg viewBox="0 0 100 50" preserveAspectRatio="none" className="cma-chart-svg">
          {median && (
            <line
              x1={0}
              x2={100}
              y1={50 - ((median - min) / range) * 50}
              y2={50 - ((median - min) / range) * 50}
              stroke="#2563eb"
              strokeDasharray="0.6,0.6"
              strokeWidth={0.3}
            />
          )}
          {points.map((p, index) => {
            const height = ((p.ppm - min) / range) * 50;
            const x = index * barWidth + barWidth * 0.15;
            const w = barWidth * 0.7;
            const y = 50 - height;
            return (
              <rect
                key={`${p.id}-${index}`}
                x={x}
                y={y}
                width={w}
                height={height}
                fill={p.isSubject ? "#dc2626" : "#94a3b8"}
              />
            );
          })}
        </svg>
        <div className="cma-chart-legend">
          <span><i style={{ background: "#dc2626" }} /> этот объект</span>
          <span><i style={{ background: "#94a3b8" }} /> аналоги</span>
          {median && (
            <span>
              <i style={{ background: "#2563eb" }} /> медиана ${money(median)}/м²
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function AnalogTable({
  subject,
  analogs,
}: {
  subject: { price_per_m2_usd: number };
  analogs: Array<{
    id: number;
    source: string;
    url: string;
    title: string;
    price_usd: number;
    area_m2: number;
    price_per_m2_usd: number;
    floor: number | null;
    address_raw: string;
  }>;
}) {
  return (
    <section className="cma-table-wrap">
      <h3>Аналоги ({analogs.length})</h3>
      <table className="cma-table">
        <thead>
          <tr>
            <th>Источник</th>
            <th>Адрес</th>
            <th>Площадь</th>
            <th>Этаж</th>
            <th>Цена</th>
            <th>$/м²</th>
            <th>vs объект</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {analogs.map((a) => {
            const diff = ((subject.price_per_m2_usd / a.price_per_m2_usd - 1) * 100).toFixed(1);
            const positive = parseFloat(diff) > 0;
            return (
              <tr key={a.id}>
                <td>{sourceLabel(a.source)}</td>
                <td>{a.address_raw || "—"}</td>
                <td>{a.area_m2} м²</td>
                <td>{a.floor ?? "—"}</td>
                <td>${money(a.price_usd)}</td>
                <td>${money(a.price_per_m2_usd)}</td>
                <td className={positive ? "diff-pos" : "diff-neg"}>
                  {positive ? "+" : ""}
                  {diff}%
                </td>
                <td>
                  <a href={a.url} target="_blank" rel="noreferrer" className="outline-link cma-table-link">
                    <ExternalLink size={12} />
                  </a>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function makeVerdict(diff: number | null) {
  if (diff === null) return null;
  if (diff <= -10) {
    return {
      kind: "good",
      title: `Хорошая цена: на ${Math.abs(diff).toFixed(1)}% ниже рынка`,
      body: "Можно смело предлагать клиенту — объект интересный.",
    };
  }
  if (diff >= 10) {
    return {
      kind: "bad",
      title: `Дорого: на ${diff.toFixed(1)}% выше рынка`,
      body: "Аргумент для торга — покажите медиану по аналогам.",
    };
  }
  return {
    kind: "neutral",
    title: `Цена в рынке: отклонение ${diff > 0 ? "+" : ""}${diff.toFixed(1)}%`,
    body: "Объект продаётся по средней цене для этого сегмента.",
  };
}
