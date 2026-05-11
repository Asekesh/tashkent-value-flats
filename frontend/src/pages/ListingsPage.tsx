import { ArrowUp, Building2, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { FilterPanel } from "../components/FilterPanel";
import { ListingCard } from "../components/ListingCard";
import type { Filters, Listing } from "../types";

export function ListingsPage({
  listings,
  total,
  page,
  pageSize,
  selected,
  filters,
  districts,
  favorites,
  onFiltersChange,
  onApply,
  onReset,
  onPageChange,
  onSelect,
  onToggleFavorite,
  onOpenCma,
  onOpenHistory,
}: {
  listings: Listing[];
  total: number;
  page: number;
  pageSize: number;
  selected: Listing | null;
  filters: Filters;
  districts: string[];
  favorites: number[];
  onFiltersChange: (filters: Filters) => void;
  onApply: () => void;
  onReset: () => void;
  onPageChange: (page: number) => void;
  onSelect: (listing: Listing) => void;
  onToggleFavorite: (listing: Listing) => void;
  onOpenCma?: (listing: Listing) => void;
  onOpenHistory?: (listing: Listing) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = page + 1;
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  const [showScrollTop, setShowScrollTop] = useState(false);

  useEffect(() => {
    function onScroll() {
      setShowScrollTop(window.scrollY > 400);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>Объявления</h2>
          <p>
            {total.toLocaleString()} объектов · показаны {from.toLocaleString()}–{to.toLocaleString()} (стр. {currentPage} из {totalPages})
          </p>
        </div>
      </div>

      <FilterPanel filters={filters} districts={districts} onChange={onFiltersChange} onApply={onApply} onReset={onReset} />

      <section className="deal-list">
        {listings.length ? (
          listings.map((listing, index) => (
            <ListingCard
              key={listing.id}
              listing={listing}
              rank={page * pageSize + index + 1}
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

      {total > pageSize && (
        <div className="pagination">
          <button
            type="button"
            className="ghost-button"
            disabled={page <= 0}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft size={16} />
            Назад
          </button>
          <span className="pagination-info">
            Стр. {currentPage} из {totalPages}
          </span>
          <button
            type="button"
            className="ghost-button"
            disabled={page >= totalPages - 1}
            onClick={() => onPageChange(page + 1)}
          >
            Вперёд
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {showScrollTop && (
        <button
          type="button"
          className="scroll-top"
          aria-label="Наверх"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        >
          <ArrowUp size={20} />
        </button>
      )}
    </div>
  );
}
