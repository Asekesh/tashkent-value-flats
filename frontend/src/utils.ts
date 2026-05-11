import type { Listing, MarketEstimate } from "./types";

export function money(value: number | null | undefined) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value ?? 0);
}

export function formatDate(value: string | null | undefined) {
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

export function basisLabel(value: string | undefined) {
  return {
    building: "тот же дом",
    district_rooms_area: "район, комнаты, площадь",
    district_rooms: "район и комнаты",
    insufficient_data: "недостаточно данных",
  }[value ?? ""] ?? value ?? "нет оценки";
}

export function confidenceLabel(value: string | undefined) {
  return {
    high: "высокая",
    medium: "средняя",
    low: "низкая",
  }[value ?? ""] ?? value ?? "нет";
}

export function getDiscount(estimate: MarketEstimate | null | undefined) {
  return estimate?.discount_percent ?? null;
}

export function isHotDeal(listing: Listing, threshold = 15) {
  const discount = getDiscount(listing.market);
  return discount !== null && discount >= threshold;
}

export function bestPhoto(listing: Listing) {
  return listing.photos?.[0] ?? "";
}

export function sourceLabel(source: string) {
  const map: Record<string, string> = { olx: "OLX", uybor: "Uybor", realt24: "Realt24" };
  return map[source.toLowerCase()] ?? source.toUpperCase();
}

export function sellerLabel(value: string | null | undefined) {
  if (!value) return "";
  const key = value.trim().toLowerCase();
  const map: Record<string, string> = {
    owner: "Хозяин",
    private: "Хозяин",
    agency: "Агентство",
    agent: "Агентство",
  };
  return map[key] ?? value;
}
