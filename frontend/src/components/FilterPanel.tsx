import { Search, SlidersHorizontal, X } from "lucide-react";
import { defaultFilters } from "../api";
import type { Filters } from "../types";

export function FilterPanel({
  filters,
  districts,
  onChange,
  onApply,
  onReset,
}: {
  filters: Filters;
  districts: string[];
  onChange: (filters: Filters) => void;
  onApply: () => void;
  onReset: () => void;
}) {
  function update(key: keyof Filters, value: string) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <section className="filter-panel">
      <div className="section-title">
        <SlidersHorizontal size={17} />
        <span>Фильтры и сортировка</span>
      </div>
      <div className="filter-grid">
        <label>
          Район
          <select value={filters.district} onChange={(event) => update("district", event.target.value)}>
            <option value="">Все районы</option>
            {districts.map((district) => (
              <option value={district} key={district}>
                {district}
              </option>
            ))}
          </select>
        </label>
        <label>
          Комнаты
          <select value={filters.rooms} onChange={(event) => update("rooms", event.target.value)}>
            <option value="">Любая</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
            <option value="4">4</option>
            <option value="5">5+</option>
          </select>
        </label>
        <label>
          Источник
          <select value={filters.source} onChange={(event) => update("source", event.target.value)}>
            <option value="">Все</option>
            <option value="olx">OLX</option>
            <option value="uybor">Uybor</option>
            <option value="realt24">Realt24</option>
          </select>
        </label>
        <label>
          Сортировка
          <select value={filters.sort} onChange={(event) => update("sort", event.target.value)}>
            <option value="discount">По скидке</option>
            <option value="price_per_m2">По цене за м²</option>
            <option value="fresh">По дате</option>
            <option value="price">По цене</option>
          </select>
        </label>
        <Range label="Цена, $" minKey="price_min" maxKey="price_max" filters={filters} update={update} />
        <Range label="Площадь, м²" minKey="area_min" maxKey="area_max" filters={filters} update={update} />
        <Range label="$/м²" minKey="ppm_min" maxKey="ppm_max" filters={filters} update={update} />
        <label>
          Скидка от, %
          <input value={filters.discount_min} onChange={(event) => update("discount_min", event.target.value)} placeholder="15" />
        </label>
      </div>
      <div className="filter-actions">
        <button className="primary-button" onClick={onApply} type="button">
          <Search size={16} />
          Применить
        </button>
        <button
          className="ghost-button"
          onClick={() => {
            onChange(defaultFilters);
            onReset();
          }}
          type="button"
        >
          <X size={16} />
          Сбросить
        </button>
      </div>
    </section>
  );
}

function Range({
  label,
  minKey,
  maxKey,
  filters,
  update,
}: {
  label: string;
  minKey: keyof Filters;
  maxKey: keyof Filters;
  filters: Filters;
  update: (key: keyof Filters, value: string) => void;
}) {
  return (
    <div className="range-field">
      <span>{label}</span>
      <div>
        <input value={filters[minKey]} onChange={(event) => update(minKey, event.target.value)} placeholder="от" />
        <input value={filters[maxKey]} onChange={(event) => update(maxKey, event.target.value)} placeholder="до" />
      </div>
    </div>
  );
}
