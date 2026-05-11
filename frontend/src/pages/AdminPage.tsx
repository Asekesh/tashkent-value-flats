import { Activity, Database, ExternalLink, Play, RefreshCcw } from "lucide-react";
import { useState } from "react";
import type { ScrapeRun, ScrapeSource } from "../types";
import { formatDate } from "../utils";

const ALL_SOURCES = ["olx", "uybor", "realt24"];
const SOURCE_LABELS: Record<string, string> = { olx: "OLX", uybor: "Uybor", realt24: "Realt24" };

export function AdminPage({
  runs,
  sources,
  loading,
  onRun,
  onRefreshRuns,
  onRefreshSources,
}: {
  runs: ScrapeRun[];
  sources: ScrapeSource[];
  loading: boolean;
  onRun: (mode: string, sources: string[]) => void;
  onRefreshRuns: () => void;
  onRefreshSources: (sources: string[]) => void;
}) {
  const [selectedSources, setSelectedSources] = useState(ALL_SOURCES);
  const activeSources = selectedSources.length ? selectedSources : ALL_SOURCES;

  function toggleSource(source: string) {
    setSelectedSources((current) => (current.includes(source) ? current.filter((item) => item !== source) : [...current, source]));
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>Управление сбором</h2>
          <p>Запуск live-сбора и последние состояния парсеров.</p>
        </div>
        <div className="page-actions">
          <button className="ghost-button" onClick={onRefreshRuns} disabled={loading} type="button">
            <RefreshCcw size={16} />
            Обновить
          </button>
          <button className="primary-button" onClick={() => onRun("quick", activeSources)} disabled={loading} type="button">
            <Database size={16} />
            Запустить сейчас
          </button>
        </div>
      </div>

      <section className="admin-grid">
        <article className="admin-card admin-card-wide">
          <div className="section-title">
            <Play size={17} />
            <span>Управление парсингом</span>
          </div>
          <div className="scan-actions">
            <button className="primary-button scan-button" onClick={() => onRun("quick", activeSources)} disabled={loading} type="button">
              <Play size={20} />
              Запустить сейчас
            </button>
            <button className="ghost-button scan-button" onClick={() => onRun("full", activeSources)} disabled={loading} type="button">
              <Play size={20} />
              Полное сканирование
            </button>
          </div>
          <p className="scan-note">
            <strong>Запустить сейчас</strong> — быстрый режим, стоп после 100 известных подряд. <strong>Полное сканирование</strong> — все страницы выбранных площадок.
          </p>
          <div className="source-picker">
            {ALL_SOURCES.map((source) => (
              <label key={source}>
                <input checked={selectedSources.includes(source)} onChange={() => toggleSource(source)} type="checkbox" />
                {SOURCE_LABELS[source]}
              </label>
            ))}
          </div>
          <div className="auto-row">
            <span>Авто-парсинг</span>
            <strong>Включен: каждые 15 минут, быстрый режим</strong>
          </div>
        </article>

        <article className="admin-card">
          <div className="section-title">
            <Database size={17} />
            <span>Страницы площадок</span>
          </div>
          <button className="ghost-button" onClick={() => onRefreshSources(activeSources)} disabled={loading} type="button">
            <RefreshCcw size={16} />
            Посчитать страницы
          </button>
          <div className="source-stats">
            {sources.length ? (
              sources.map((source) => (
                <div className="source-row" key={source.source}>
                  <div>
                    <strong>{SOURCE_LABELS[source.source] ?? source.source.toUpperCase()}</strong>
                    <span>
                      {source.error
                        ? source.error
                        : source.total_listings
                          ? `~${source.total_listings.toLocaleString()} объявл.`
                          : source.total_pages && source.page_size
                            ? `~${(source.total_pages * source.page_size).toLocaleString()} объявл.`
                            : "страницы найдены"}
                    </span>
                  </div>
                  <b>{source.error ? "ошибка" : source.total_pages ? `${source.total_pages.toLocaleString()} стр.` : "неизвестно"}</b>
                </div>
              ))
            ) : (
              <p className="muted-text">Нажмите «Посчитать страницы», чтобы получить текущий объём площадок.</p>
            )}
          </div>
        </article>

        <article className="admin-card">
          <div className="section-title">
            <Activity size={17} />
            <span>Пайплайн</span>
          </div>
          <ol className="pipeline">
            <li>Сбор объявлений из источника</li>
            <li>Нормализация цены, площади и адреса</li>
            <li>Дедупликация по дому и source URLs</li>
            <li>Расчёт цены за м² и дисконта к рынку</li>
          </ol>
        </article>

        <article className="admin-card">
          <div className="section-title">
            <ExternalLink size={17} />
            <span>Последние запуски</span>
          </div>
          <div className="run-list">
            {runs.length ? (
              runs.map((run) => (
                <div className="run-row" key={run.id}>
                  <div>
                    <strong>{run.source.toUpperCase()}</strong>
                    <span>{formatDate(run.started_at)}</span>
                  </div>
                  <div>
                    <span className={run.status === "success" ? "chip success" : "chip"}>{run.status}</span>
                    <small>
                      +{run.new_count} / обновлено {run.updated_count}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="muted-text">История сборов пока пуста.</p>
            )}
          </div>
        </article>
      </section>
    </div>
  );
}
