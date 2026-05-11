import { useEffect, useMemo, useState } from "react";
import { defaultFilters, fetchDashboardStats, fetchListings, fetchScrapeRuns, fetchScrapeSources, runScrape } from "./api";
import { CmaModal } from "./components/CmaModal";
import { Sidebar, TopBar } from "./components/Shell";
import { AdminPage } from "./pages/AdminPage";
import { Dashboard } from "./pages/Dashboard";
import { ListingsPage } from "./pages/ListingsPage";
import type { DashboardStats, Filters, Listing, ScrapeRun, ScrapeSource, View } from "./types";

const FAVORITES_KEY = "tashkent-value-flats:favorites";

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [listings, setListings] = useState<Listing[]>([]);
  const [selected, setSelected] = useState<Listing | null>(null);
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [sourceStats, setSourceStats] = useState<ScrapeSource[]>([]);
  const [favorites, setFavorites] = useState<number[]>(() => readFavorites());
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("Готово");
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [dashboardSource, setDashboardSource] = useState<string>("");
  const [cmaListing, setCmaListing] = useState<Listing | null>(null);

  const districts = useMemo(() => Array.from(new Set(listings.map((item) => item.district).filter(Boolean))).sort(), [listings]);

  async function loadListings(nextFilters = filters) {
    setLoading(true);
    setStatus("Загружаем объявления...");
    try {
      const payload = await fetchListings(nextFilters);
      setListings(payload.items);
      setTotal(payload.total);
      setSelected((current) => payload.items.find((item) => item.id === current?.id) ?? payload.items[0] ?? null);
      setStatus(`Найдено: ${payload.total}`);
    } catch {
      setStatus("API недоступен");
    } finally {
      setLoading(false);
    }
  }

  async function loadRuns() {
    try {
      setRuns(await fetchScrapeRuns());
    } catch {
      setRuns([]);
    }
  }

  async function loadStats() {
    try {
      setStats(await fetchDashboardStats());
    } catch {
      // оставляем прежние значения
    }
  }

  async function importListings(mode = "quick", sources: string[] = ["olx", "uybor", "realt24"]) {
    setLoading(true);
    setStatus(mode === "full" ? "Запускаем полное сканирование..." : "Запускаем быстрый сбор...");
    try {
      await runScrape(sources.join(","), mode);
      await loadListings();
      await loadRuns();
      await loadStats();
    } catch {
      setStatus("Сбор не запустился");
      setLoading(false);
    }
  }

  async function loadSourceStats(sources: string[] = ["olx", "uybor", "realt24"]) {
    setLoading(true);
    setStatus("Считаем страницы площадок...");
    try {
      setSourceStats(await fetchScrapeSources(sources.join(",")));
      setStatus("Страницы посчитаны");
    } catch {
      setSourceStats([]);
      setStatus("Не удалось посчитать страницы");
    } finally {
      setLoading(false);
    }
  }

  function toggleFavorite(listing: Listing) {
    setFavorites((current) => {
      const next = current.includes(listing.id) ? current.filter((id) => id !== listing.id) : [...current, listing.id];
      window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
      return next;
    });
  }

  function applyQuickFilter(partial: Partial<Filters>) {
    const next = { ...defaultFilters, ...partial };
    setFilters(next);
    setView("listings");
    void loadListings(next);
  }

  function changeDashboardSource(source: string) {
    setDashboardSource(source);
    const next = { ...defaultFilters, source, sort: "discount" };
    setFilters(next);
    void loadListings(next);
  }

  useEffect(() => {
    void loadListings(defaultFilters);
    void loadRuns();
    void loadStats();
  }, []);

  return (
    <div className="app-shell">
      <Sidebar activeView={view} onViewChange={setView} />
      <div className="main-shell">
        <TopBar loading={loading} status={status} onRefresh={() => loadListings()} onImport={importListings} />
        {view === "dashboard" && (
          <Dashboard
            listings={listings}
            total={total}
            stats={stats}
            selected={selected}
            favorites={favorites}
            dashboardSource={dashboardSource}
            onSelect={setSelected}
            onToggleFavorite={toggleFavorite}
            onViewListings={() => setView("listings")}
            onQuickFilter={applyQuickFilter}
            onSourceChange={changeDashboardSource}
            onOpenCma={setCmaListing}
          />
        )}
        {view === "listings" && (
          <ListingsPage
            listings={listings}
            total={total}
            selected={selected}
            filters={filters}
            districts={districts}
            favorites={favorites}
            onFiltersChange={setFilters}
            onApply={() => loadListings(filters)}
            onReset={() => loadListings(defaultFilters)}
            onSelect={setSelected}
            onToggleFavorite={toggleFavorite}
            onOpenCma={setCmaListing}
          />
        )}
        {view === "admin" && (
          <AdminPage
            runs={runs}
            sources={sourceStats}
            loading={loading}
            onRun={importListings}
            onRefreshRuns={loadRuns}
            onRefreshSources={loadSourceStats}
          />
        )}
      </div>
      {cmaListing && <CmaModal listing={cmaListing} onClose={() => setCmaListing(null)} />}
    </div>
  );
}

function readFavorites() {
  try {
    const value = window.localStorage.getItem(FAVORITES_KEY);
    return value ? (JSON.parse(value) as number[]) : [];
  } catch {
    return [];
  }
}
