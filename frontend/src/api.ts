import type { CmaResult, DashboardStats, Filters, ListingsPage, ScrapeRun, ScrapeSource } from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const defaultFilters: Filters = {
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

export async function fetchListings(filters: Filters, limit = 100): Promise<ListingsPage> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set("limit", String(limit));
  const response = await fetch(`${API_BASE_URL}/api/listings?${params.toString()}`);
  if (!response.ok) throw new Error("Не удалось загрузить объявления");
  return response.json();
}

export async function runScrape(source = "all", mode = "quick") {
  const response = await fetch(`${API_BASE_URL}/api/admin/scrape/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, mode }),
  });
  if (!response.ok) throw new Error("Не удалось запустить сбор");
  return response.json();
}

export async function fetchScrapeRuns(): Promise<ScrapeRun[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/scrape/runs`);
  if (!response.ok) throw new Error("Не удалось загрузить историю сборов");
  return response.json();
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const response = await fetch(`${API_BASE_URL}/api/listings/stats`);
  if (!response.ok) throw new Error("Не удалось загрузить статистику");
  return response.json();
}

export async function fetchCma(listingId: number): Promise<CmaResult> {
  const response = await fetch(`${API_BASE_URL}/api/cma/${listingId}`);
  if (!response.ok) throw new Error("Не удалось загрузить аналоги");
  return response.json();
}

export async function fetchScrapeSources(source = "all"): Promise<ScrapeSource[]> {
  const params = new URLSearchParams({ source });
  const response = await fetch(`${API_BASE_URL}/api/admin/scrape/sources?${params.toString()}`);
  if (!response.ok) throw new Error("Не удалось посчитать страницы");
  return response.json();
}
