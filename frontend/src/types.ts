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
