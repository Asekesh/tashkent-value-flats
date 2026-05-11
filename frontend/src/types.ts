export type MarketEstimate = {
  market_price_per_m2_usd: number | null;
  sample_size: number;
  basis: string;
  confidence: string;
  discount_percent: number | null;
  is_below_market: boolean;
};

export type Listing = {
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
  photos: string[];
  seller_type: string | null;
  published_at: string | null;
  seen_at: string;
  status: string;
  duplicate_count: number;
  source_urls: Array<{ source: string; url: string }>;
  market: MarketEstimate | null;
};

export type Filters = {
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

export type ListingsPage = {
  items: Listing[];
  total: number;
};

export type ScrapeRun = {
  id: number;
  source: string;
  status: string;
  trigger: string;
  new_count: number;
  updated_count: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ScrapeSource = {
  source: string;
  supports_live: boolean;
  total_pages: number | null;
  page_size: number | null;
  total_listings: number | null;
  error: string | null;
};

export type View = "dashboard" | "listings" | "admin";

export type SourceStat = {
  source: string;
  total: number;
  hot: number;
};

export type DashboardStats = {
  total: number;
  hot: number;
  new_today: number;
  new_yesterday: number;
  sources: SourceStat[];
  hot_threshold_percent: number;
};

export type CmaAnalog = {
  id: number;
  source: string;
  url: string;
  title: string;
  price_usd: number;
  area_m2: number;
  price_per_m2_usd: number;
  rooms: number;
  floor: number | null;
  district: string;
  address_raw: string;
  seen_at: string;
};

export type CmaStats = {
  count: number;
  avg_price_per_m2_usd: number | null;
  median_price_per_m2_usd: number | null;
  min_price_per_m2_usd: number | null;
  max_price_per_m2_usd: number | null;
  avg_price_usd: number | null;
};

export type ListingEvent = {
  id: number;
  event_type: "first_seen" | "price_changed" | "relisted" | "delisted" | "status_changed";
  old_price_usd: number | null;
  new_price_usd: number | null;
  old_status: string | null;
  new_status: string | null;
  source: string | null;
  source_id: string | null;
  note: string | null;
  at: string;
};

export type ListingHistorySummary = {
  first_seen_at: string | null;
  first_price_usd: number | null;
  current_price_usd: number | null;
  total_price_change_percent: number | null;
  price_change_count: number;
  relisted_count: number;
  last_relisted_at: string | null;
  last_delisted_at: string | null;
};

export type ListingHistory = {
  listing_id: number;
  summary: ListingHistorySummary;
  events: ListingEvent[];
};

export type CmaResult = {
  subject: CmaAnalog;
  basis: "building" | "district";
  basis_label: string;
  area_tolerance_percent: number;
  stats: CmaStats;
  subject_vs_market_percent: number | null;
  analogs: CmaAnalog[];
};
