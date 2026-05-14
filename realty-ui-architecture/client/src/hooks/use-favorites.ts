import { useState, useEffect, useCallback } from "react";
import type { Apartment } from "@shared/schema";

const STORAGE_KEY = "realty_favorites";

function loadFavorites(): Record<string, Apartment> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

const FAVORITES_EVENT = "realty_favorites_changed";

function saveFavorites(favs: Record<string, Apartment>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(favs));
  } catch {}
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<Record<string, Apartment>>(loadFavorites);

  useEffect(() => {
    saveFavorites(favorites);
  }, [favorites]);

  // Синхронизация между всеми инстансами хука (сайдбар, списки и т.д.)
  useEffect(() => {
    const sync = () => setFavorites(loadFavorites());
    window.addEventListener(FAVORITES_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(FAVORITES_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const isFavorite = useCallback(
    (id: string | number) => Boolean(favorites[String(id)]),
    [favorites]
  );

  const toggleFavorite = useCallback((apt: Apartment) => {
    setFavorites(prev => {
      const id = String(apt.id);
      let next: Record<string, Apartment>;
      if (prev[id]) {
        next = { ...prev };
        delete next[id];
      } else {
        next = { ...prev, [id]: apt };
      }
      saveFavorites(next);
      window.dispatchEvent(new Event(FAVORITES_EVENT));
      return next;
    });
  }, []);

  const removeFavorite = useCallback((id: string | number) => {
    setFavorites(prev => {
      const next = { ...prev };
      delete next[String(id)];
      saveFavorites(next);
      window.dispatchEvent(new Event(FAVORITES_EVENT));
      return next;
    });
  }, []);

  const favoritesList = Object.values(favorites);

  return { favorites, favoritesList, isFavorite, toggleFavorite, removeFavorite };
}
