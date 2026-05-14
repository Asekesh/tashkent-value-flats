import { Link, useLocation } from "wouter";
import { Home, Building2, Settings, TrendingDown, LineChart, Heart, TrendingUp } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
} from "@/components/ui/sidebar";
import { useFavorites } from "@/hooks/use-favorites";

const navItems = [
  { title: "Главная", url: "/", icon: Home, description: "Лучшие по цене/м²" },
  { title: "Объявления", url: "/listings", icon: Building2, description: "Все квартиры" },
  { title: "Избранное", url: "/favorites", icon: Heart, description: "Сохранённые" },
  { title: "Тренды", url: "/trends", icon: LineChart, description: "Динамика цен" },
  { title: "Ликвидность ЖК", url: "/liquidity", icon: TrendingUp, description: "Срок продажи и цены" },
  { title: "Управление", url: "/admin", icon: Settings, description: "Настройки фильтров" },
];

export function AppSidebar() {
  const [location] = useLocation();
  const { favoritesList } = useFavorites();
  const favoritesCount = favoritesList.length;

  return (
    <Sidebar>
      <div className="p-4 border-b border-sidebar-border">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-md bg-primary flex items-center justify-center flex-shrink-0">
            <TrendingDown className="w-4 h-4 text-primary-foreground" />
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-sm text-sidebar-foreground leading-tight">Аналитик недвижимости</div>
            <div className="text-xs text-muted-foreground leading-tight">г. Ташкент</div>
          </div>
        </div>
      </div>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Навигация</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const isActive = location === item.url || (item.url !== "/" && location.startsWith(item.url));
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton asChild isActive={isActive}>
                      <Link href={item.url} data-testid={`nav-${item.title.toLowerCase()}`}>
                        <item.icon className="w-4 h-4" />
                        <span>{item.title}</span>
                        {item.url === "/favorites" && favoritesCount > 0 && (
                          <span className="ml-auto inline-flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full bg-destructive text-destructive-foreground text-xs font-medium">
                            {favoritesCount}
                          </span>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="px-3 py-3 text-xs text-muted-foreground">
          <div className="font-medium text-sidebar-foreground mb-0.5">Ташкент, Узбекистан</div>
          <div>Данные с открытых площадок</div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
