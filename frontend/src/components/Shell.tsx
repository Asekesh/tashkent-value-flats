import { BarChart3, Building2, Database, Home, RefreshCcw, Settings } from "lucide-react";
import type { View } from "../types";

const navItems: Array<{ view: View; label: string; description: string; icon: typeof Home }> = [
  { view: "dashboard", label: "Главная", description: "лучшие сделки", icon: Home },
  { view: "listings", label: "Объявления", description: "поиск и фильтры", icon: Building2 },
  { view: "admin", label: "Управление", description: "сбор данных", icon: Settings },
];

export function Sidebar({ activeView, onViewChange }: { activeView: View; onViewChange: (view: View) => void }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-logo" src="/favicon.png" alt="Логотип" />
        <div>
          <strong>Ташкент Недвижимость</strong>
          <span>Квартиры и дома в столице</span>
        </div>
      </div>

      <nav className="nav-list" aria-label="Основная навигация">
        <p>Навигация</p>
        {navItems.map((item) => (
          <button
            key={item.view}
            className={activeView === item.view ? "nav-item active" : "nav-item"}
            onClick={() => onViewChange(item.view)}
            type="button"
          >
            <item.icon size={17} />
            <span>
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </span>
          </button>
        ))}
      </nav>

      <div className="sidebar-foot">
        <BarChart3 size={16} />
        <span>Открытые площадки, рыночная оценка и поиск дисконта.</span>
      </div>
    </aside>
  );
}

export function TopBar({
  loading,
  status,
  onRefresh,
  onImport,
}: {
  loading: boolean;
  status: string;
  onRefresh: () => void;
  onImport: () => void;
}) {
  return (
    <header className="topbar">
      <div>
        <h1>Квартиры в Ташкенте ниже рынка</h1>
        <p className="topbar-sub">Обновляется каждые 15 минут · только проверенные дисконты</p>
      </div>
      <div className="topbar-actions">
        <span className={loading ? "status loading" : "status"}>{status}</span>
        <button className="icon-button" onClick={onRefresh} disabled={loading} title="Обновить список" type="button">
          <RefreshCcw size={17} />
        </button>
        <button className="primary-button" onClick={onImport} disabled={loading} type="button">
          <Database size={17} />
          Быстрый сбор
        </button>
      </div>
    </header>
  );
}
