import { Building2, Calendar, ExternalLink, Heart, MapPin, Ruler, TrendingDown, User } from "lucide-react";
import type { Listing } from "../types";
import { bestPhoto, formatDate, isHotDeal, money, sellerLabel, sourceLabel } from "../utils";

export function ListingCard({
  listing,
  rank,
  selected,
  favorite,
  onSelect,
  onToggleFavorite,
}: {
  listing: Listing;
  rank?: number;
  selected?: boolean;
  favorite: boolean;
  onSelect: (listing: Listing) => void;
  onToggleFavorite: (listing: Listing) => void;
}) {
  const discount = listing.market?.discount_percent;
  const photo = bestPhoto(listing);

  return (
    <article className={selected ? "listing-card selected" : "listing-card"} onClick={() => onSelect(listing)}>
      <div className="listing-media">
        {photo ? <img src={photo} alt={listing.title} /> : <Building2 size={34} />}
      </div>
      <div className="listing-body">
        <div className="chips">
          {typeof rank === "number" && <span className="rank">{rank}</span>}
          {isHotDeal(listing) && <span className="chip danger">-{discount?.toFixed(1)}%</span>}
          <span className="chip">{listing.rooms}-комн.</span>
          <span className="chip muted">{sourceLabel(listing.source)}</span>
          {listing.seller_type && (
            <span className="chip muted">
              <User size={12} />
              {sellerLabel(listing.seller_type)}
            </span>
          )}
        </div>
        <h3>{listing.title}</h3>
        <p className="listing-subtitle">{listing.address_raw || listing.district}</p>
        <div className="listing-facts">
          <span>
            <MapPin size={13} />
            {listing.district}
          </span>
          <span>
            <Ruler size={13} />
            {listing.area_m2} м²
          </span>
          <span>
            <TrendingDown size={13} />
            ${money(listing.price_per_m2_usd)}/м²
          </span>
          <span>
            <Calendar size={13} />
            {formatDate(listing.seen_at)}
          </span>
        </div>
        <div className="listing-bottom">
          <div>
            <strong>${money(listing.price_usd)}</strong>
            <span>
              рынок:{" "}
              {listing.market?.market_price_per_m2_usd ? `$${money(listing.market.market_price_per_m2_usd)}/м²` : "мало данных"}
            </span>
          </div>
          <div className="row-actions">
            <button
              className={favorite ? "icon-button favorite active" : "icon-button favorite"}
              onClick={(event) => {
                event.stopPropagation();
                onToggleFavorite(listing);
              }}
              title={favorite ? "Убрать из избранного" : "Добавить в избранное"}
              type="button"
            >
              <Heart size={15} />
            </button>
            <a className="outline-link" href={listing.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
              <ExternalLink size={14} />
              Источник
            </a>
          </div>
        </div>
      </div>
    </article>
  );
}
