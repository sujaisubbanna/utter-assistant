import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "./api";
import type { Palette, ThemeMode } from "./types";

const STORAGE_KEY = "utter.theme";
const PALETTE_KEY = "utter.desktopColours";

/** Tokens a matugen palette is allowed to override. */
const TOKENS = [
  "background",
  "foreground",
  "card",
  "card-foreground",
  "popover",
  "popover-foreground",
  "primary",
  "primary-foreground",
  "secondary",
  "secondary-foreground",
  "muted",
  "muted-foreground",
  "accent",
  "accent-foreground",
  "destructive",
  "destructive-foreground",
  "border",
  "input",
  "ring",
];

export function getStoredMode(): ThemeMode {
  const raw = localStorage.getItem(STORAGE_KEY);
  // Dark is the default look; Light and System are opt-in.
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "dark";
}

export function storeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

/** Desktop (matugen) colours are opt-in; the built-in grey + yellow is the default. */
export function getStoredDesktopColours(): boolean {
  try {
    return localStorage.getItem(PALETTE_KEY) === "on";
  } catch {
    return false;
  }
}

export function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function modeIsDark(mode: ThemeMode): boolean {
  return mode === "dark" || (mode === "system" && systemPrefersDark());
}

/**
 * A matugen palette only drives the semantic tokens when its own lightness
 * matches the chosen mode. Otherwise the built-in palette for that mode wins,
 * so the Light/Dark toggle keeps working on a dark desktop.
 */
export function paletteApplies(mode: ThemeMode, palette: Palette | null, enabled = true): boolean {
  return Boolean(enabled && palette && palette.available && palette.dark === modeIsDark(mode));
}

export function applyTheme(mode: ThemeMode, palette: Palette | null, desktopColours = false): void {
  const root = document.documentElement;
  const dark = modeIsDark(mode);
  root.classList.toggle("dark", dark);
  root.dataset.themeMode = mode;
  root.style.colorScheme = dark ? "dark" : "light";

  if (paletteApplies(mode, palette, desktopColours) && palette) {
    for (const token of TOKENS) {
      const value = palette.tokens[token];
      if (value) root.style.setProperty(`--${token}`, value);
      else root.style.removeProperty(`--${token}`);
    }
    root.dataset.palette = "matugen";
  } else {
    for (const token of TOKENS) root.style.removeProperty(`--${token}`);
    root.dataset.palette = "utter";
  }
}

function flashTransition(): void {
  const root = document.documentElement;
  root.classList.add("palette-transition");
  window.setTimeout(() => root.classList.remove("palette-transition"), 420);
}

interface ThemeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  palette: Palette | null;
  paletteActive: boolean;
  desktopColours: boolean;
  setDesktopColours: (on: boolean) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: "system",
  setMode: () => {},
  palette: null,
  paletteActive: false,
  desktopColours: false,
  setDesktopColours: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => getStoredMode());
  const [palette, setPalette] = useState<Palette | null>(null);
  const [desktopColours, setDesktopColoursState] = useState<boolean>(() => getStoredDesktopColours());

  // Apply on every change (and once the palette arrives).
  useEffect(() => {
    applyTheme(mode, palette, desktopColours);
  }, [mode, palette, desktopColours]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    (async () => {
      try {
        const boot = await api.bootParams();
        if (!cancelled && (boot.theme === "light" || boot.theme === "dark" || boot.theme === "system")) {
          setModeState(boot.theme);
        }
      } catch {
        /* ignore */
      }
      try {
        const loaded = await api.getThemePalette();
        if (!cancelled) setPalette(loaded);
      } catch {
        /* ignore */
      }
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const off = await listen<Palette>("theme-changed", (event) => {
          setPalette(event.payload);
          flashTransition();
        });
        if (cancelled) off();
        else unlisten = off;
      } catch {
        /* events are optional */
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  // Follow the system preference live while in "system" mode.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme(mode, palette, desktopColours);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [mode, palette, desktopColours]);

  const setDesktopColours = useCallback((on: boolean) => {
    setDesktopColoursState(on);
    flashTransition();
    try {
      localStorage.setItem(PALETTE_KEY, on ? "on" : "off");
    } catch {
      /* ignore */
    }
  }, []);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    storeMode(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      mode,
      setMode,
      palette,
      paletteActive: paletteApplies(mode, palette, desktopColours),
      desktopColours,
      setDesktopColours,
    }),
    [mode, setMode, palette, desktopColours, setDesktopColours],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
