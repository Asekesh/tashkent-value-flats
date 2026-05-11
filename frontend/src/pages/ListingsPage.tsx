import { Building2 } from "lucide-react";
import { FilterPanel } from "../components/FilterPanel";
import { ListingCard } from "../components/ListingCard";
import type { Filters, Listing } from "../types";

export function ListingsPage({
  listings,
  total,
  selected,
  filters,
  districts,
  favorites,
  onFiltersChange,
  onApply,
  onReset,
  onSelect,
  onToggleFavorite,
  onOpenCma,
  onOpenHistory,
}: {
  listings: Listing[];
  total: number;
  selected: Listing | null;
  filters: Filters;
  districts: string[];
  favorites: number[];
  onFiltersChange: (filters: Filters) => void;
  onApply: () => void;
  onReset: () => void;
  onSelect: (listing: Listing) => void;
  onToggleFavorite: (listing: Listing) => void;
  onOpenCma?: (listing: Listing) => void;
  onOpenHistory?: (listing: Listing) => void;
}) {
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>Объявления</h2>
          <p>{total.toLocaleString()} объектов в базе. Фильтры применяются к текущему FastAPI API.</p>
        </div>
      </div>

      <FilterPanel filters={filters} districts={districts} onChange={onFiltersChange} onApply={onApply} onReset={onReset} />

      <section className="deal-list">
        {listings.length ? (
          listings.map((listing, index) => (
            <ListingCard
              key={listing.id}
              listing={listing}
              rank={index + 1}
              selected={selected?.id === listing.id}
              favorite={favorites.includes(listing.id)}
              onSelect={onSelect}
              onToggleFavorite={onToggleFavorite}
              onOpenCma={onOpenCma}
              onOpenHistory={onOpenHistory}
            />
          ))
        ) : (
          <div className="empty-state">
            <Building2 size={34} />
            <h3>Ничего не найдено</h3>
            <p>Попробуйте сбросить фильтры или запустить сбор объявлений.</p>
          </div>
        )}
      </section>
    </div>
  );
}
